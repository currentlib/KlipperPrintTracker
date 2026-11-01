import asyncio
import json

import amqtt.broker
import pytest
import aiomqtt

from app.config import Options
from app.db import Database
from app.links import Links
from app import mqtt

OPTIONS = Options(printer_name="K1C", currency="UAH", moonraker_url="http://printer.example:7125")
LINKS = Links("abcd1234_klipper_print_tracker", "http://pi.example:8100")


def record(job_id="000001", status="completed", end=1000.0, **extra):
    return {"job_id": job_id, "filename": "dir/plate.gcode", "status": status, "end_time": end,
            "print_duration": 3600, "planned": 5, "parts": 4, "printed": {"Bracket": 4},
            "excluded": {"Clip": 1}, "grams": 25.5, "kwh": 0.5, "total_cost": 40, "per_part": 10,
            "wasted_cost": 0 if status == "completed" else 40, "spool": "PETG",
            "changes": {"file": {"job_id": "0", "diff": [{"key": "flow_ratio", "old": "1", "new": "2"}]}},
            **extra}


def test_discovery_covers_the_entity_table():
    topics = mqtt.scope_discovery(mqtt.Scope(), OPTIONS)
    ids = {t.split("/")[1] + "." + t.split("/")[2].removeprefix("klipper_print_tracker_") for t in topics}
    assert ids >= {f"sensor.{k}" for k in (
        "total_prints", "success_rate", "parts_printed", "filament_used", "energy_used", "total_cost",
        "last_print", "recent_prints", "top_parts", "current_print_parts")} | {
        "event.print_finished", "button.rescan_history"}


def test_discovery_schema():
    for topic, payload in mqtt.discovery(OPTIONS).items():
        if "_printer1_" in topic:
            continue
        component, unique_id = topic.split("/")[1:3]
        assert topic == f"homeassistant/{component}/{unique_id}/config"
        assert payload["unique_id"] == unique_id
        assert payload["device"]["identifiers"] == ["klipper_print_tracker"]
        assert payload["device"]["name"] == "Print Tracker"
        assert payload["default_entity_id"].startswith(f"{component}.print_tracker_")
        assert "availability_topic" in payload or "availability" in payload
        assert not ("availability_topic" in payload and "availability" in payload)
        if component == "button":
            assert payload["command_topic"]
        else:
            assert payload["state_topic"]


def test_event_entity_schema():
    event = mqtt.discovery(OPTIONS)["homeassistant/event/klipper_print_tracker_print_finished/config"]
    assert event["event_types"] == ["completed", "cancelled", "error", "rated"]


def test_cost_units_and_current_availability():
    topics = mqtt.discovery(OPTIONS)
    cost = topics["homeassistant/sensor/klipper_print_tracker_total_cost/config"]
    assert cost["unit_of_measurement"] == "UAH" and cost["device_class"] == "monetary"
    current = topics["homeassistant/sensor/klipper_print_tracker_current_print_parts/config"]
    assert current["availability_mode"] == "all" and len(current["availability"]) == 2


def test_states_are_small(tmp_path):
    db = Database(tmp_path / "t.db")
    for i in range(30):
        db.save_job(record(f"{i:06}", end=1000.0 + i))
    payloads = mqtt.state_payloads(db, LINKS, OPTIONS)
    recent = payloads[mqtt.TOPICS["recent"]]
    assert recent["count"] == 30 and len(recent["jobs"]) == 10
    assert all(len(json.dumps(p)) < 16384 for p in payloads.values())
    last = payloads[mqtt.TOPICS["last_print"]]
    assert last["job_id"] == "000029" and last["file"] == "plate"
    assert last["changed_settings"] == ["flow_ratio"]
    assert last["url"] == "/app/abcd1234_klipper_print_tracker/job/printer1:000029"
    assert last["direct_url"] == "http://pi.example:8100/#/job/printer1:000029"
    db.close()


class Supervisor:
    async def mqtt_service(self):
        return None


@pytest.fixture
async def broker():
    port = 18831
    instance = amqtt.broker.Broker({
        "listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{port}"}},
        "plugins": {"amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True}}})
    await instance.start()
    yield port
    await instance.shutdown()


async def collect(port, topic, until, timeout=4):
    received = {}

    async def run():
        async with aiomqtt.Client("127.0.0.1", port) as client:
            await client.subscribe(topic)
            async for message in client.messages:
                received[str(message.topic)] = message.payload.decode()
                if until(received):
                    return

    await asyncio.wait_for(run(), timeout)
    return received


async def test_full_flow_against_a_broker(tmp_path, broker):
    db = Database(tmp_path / "t.db")
    options = Options(printer_name="K1C", mqtt_host="127.0.0.1", mqtt_port=broker,
                      moonraker_url="http://printer.example:7125")
    rescans = []

    async def rescan():
        rescans.append(1)

    publisher = mqtt.MqttPublisher(options, db, Supervisor(), LINKS, rescan)
    listener = asyncio.create_task(collect(
        broker, "#", lambda r: mqtt.TOPICS["event"] in r and mqtt.TOPICS["current"] in r))
    await asyncio.sleep(0.2)
    task = asyncio.create_task(publisher.run())
    for _ in range(300):
        if publisher.client:
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.1)
    await publisher.current("printer1", {"filename": "a.gcode", "objects": ["A", "B"], "excluded": ["B"]})
    db.save_job(record())
    await publisher.job_finished(db.get_job("000001"))
    received = await listener
    assert received[mqtt.AVAILABILITY] == "online"
    assert json.loads(received[mqtt.TOPICS["current"]]) == {
        "planned": 2, "printed": 1, "excluded": ["B"], "file": "a.gcode"}
    event = json.loads(received[mqtt.TOPICS["event"]])
    assert event["event_type"] == "completed" and event["job_id"] == "000001"
    assert json.loads(received[mqtt.TOPICS["stats"]])["total"] == 1
    assert "homeassistant/event/klipper_print_tracker_print_finished/config" in received
    assert "homeassistant/event/klipper_print_tracker_printer1_print_finished/config" in received
    assert db.pending_events() == []

    async with aiomqtt.Client("127.0.0.1", broker) as client:
        await client.publish(mqtt.TOPICS["rescan"], "PRESS")
    for _ in range(200):
        if rescans:
            break
        await asyncio.sleep(0.01)
    assert rescans
    task.cancel()
    db.close()


async def test_events_wait_for_the_broker(tmp_path, broker):
    db = Database(tmp_path / "t.db")
    options = Options(mqtt_host="127.0.0.1", mqtt_port=broker)
    publisher = mqtt.MqttPublisher(options, db, Supervisor(), LINKS, None)
    db.save_job(record())
    await publisher.job_finished(db.get_job("000001"))
    assert len(db.pending_events()) == 1
    listener = asyncio.create_task(collect(broker, mqtt.TOPICS["event"], lambda r: r))
    await asyncio.sleep(0.2)
    task = asyncio.create_task(publisher.run())
    received = await listener
    assert json.loads(received[mqtt.TOPICS["event"]])["event_type"] == "completed"
    task.cancel()
    db.close()


async def test_broker_that_appears_later(tmp_path, broker, monkeypatch):
    monkeypatch.setattr(mqtt, "BROKER_RETRY", 0.01)

    class LateSupervisor:
        answers = [None, None, {"host": "127.0.0.1", "port": broker}]

        async def mqtt_service(self):
            return self.answers.pop(0)

    db = Database(tmp_path / "t.db")
    publisher = mqtt.MqttPublisher(Options(), db, LateSupervisor(), LINKS, None)
    task = asyncio.create_task(publisher.run())
    for _ in range(300):
        if publisher.client:
            break
        await asyncio.sleep(0.01)
    assert publisher.client
    task.cancel()
    db.close()
