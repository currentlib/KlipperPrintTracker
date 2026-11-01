"""Home Assistant device over MQTT discovery."""
import asyncio
import json
import logging

import aiomqtt

from .summary import job_summary, recent_row

log = logging.getLogger(__name__)

PREFIX = "homeassistant"
BASE = "klipper_print_tracker"
AVAILABILITY = f"{BASE}/availability"
ONLINE, OFFLINE = "online", "offline"
EVENT_TYPES = ["completed", "cancelled", "error"]
TOPICS = {name: f"{BASE}/{name}" for name in (
    "stats", "last_print", "recent", "top_parts", "current", "current/availability", "event", "rescan")}
SENSORS = {
    "total_prints": {"name": "Total prints", "icon": "mdi:printer-3d", "state_class": "total_increasing",
                     "unit_of_measurement": "prints", "value_template": "{{ value_json.total }}",
                     "topic": "stats"},
    "success_rate": {"name": "Success rate", "icon": "mdi:check-decagram", "state_class": "measurement",
                     "unit_of_measurement": "%", "value_template": "{{ value_json.success_rate }}",
                     "topic": "stats"},
    "parts_printed": {"name": "Parts printed", "icon": "mdi:shape", "state_class": "total_increasing",
                      "unit_of_measurement": "parts", "value_template": "{{ value_json.parts }}",
                      "topic": "stats"},
    "filament_used": {"name": "Filament used", "device_class": "weight", "state_class": "total_increasing",
                      "unit_of_measurement": "kg", "value_template": "{{ value_json.filament_kg }}",
                      "topic": "stats"},
    "energy_used": {"name": "Energy used", "device_class": "energy", "state_class": "total_increasing",
                    "unit_of_measurement": "kWh", "value_template": "{{ value_json.kwh }}",
                    "topic": "stats"},
    "last_print": {"name": "Last print", "icon": "mdi:history",
                   "value_template": "{{ value_json.status }}", "topic": "last_print", "attributes": True},
    "recent_prints": {"name": "Recent prints", "icon": "mdi:format-list-bulleted",
                      "unit_of_measurement": "prints", "value_template": "{{ value_json.count }}",
                      "topic": "recent", "attributes": True},
    "top_parts": {"name": "Top parts", "icon": "mdi:trophy-outline", "unit_of_measurement": "parts",
                  "value_template": "{{ value_json.count }}", "topic": "top_parts", "attributes": True},
    "current_print_parts": {"name": "Current print parts", "icon": "mdi:shape-outline",
                            "unit_of_measurement": "parts", "value_template": "{{ value_json.planned }}",
                            "topic": "current", "attributes": True},
}


def discovery(options, version: str = "0.1.0") -> dict[str, dict]:
    """Discovery topic -> payload for every entity."""
    device = {"identifiers": [BASE], "name": f"Print Tracker ({options.printer_name})",
              "manufacturer": "KlipperPrintTracker", "model": "Home Assistant add-on",
              "sw_version": version}
    origin = {"name": "KlipperPrintTracker", "sw_version": version,
              "support_url": "https://github.com/currentlib/KlipperPrintTracker"}
    common = {"device": device, "origin": origin, "availability_topic": AVAILABILITY}

    def config(component: str, key: str, payload: dict) -> tuple[str, dict]:
        unique_id = f"{BASE}_{key}"
        body = {"unique_id": unique_id, "default_entity_id": f"{component}.print_tracker_{key}",
                **common, **payload}
        if "availability" in body:
            del body["availability_topic"]
        return f"{PREFIX}/{component}/{unique_id}/config", body

    entities = {}
    for key, sensor in SENSORS.items():
        payload = {k: v for k, v in sensor.items() if k not in ("topic", "attributes")}
        topic = TOPICS[sensor["topic"]]
        payload["state_topic"] = topic
        if sensor.get("attributes"):
            payload["json_attributes_topic"] = topic
        if key == "current_print_parts":
            payload["availability"] = [{"topic": AVAILABILITY}, {"topic": TOPICS["current/availability"]}]
            payload["availability_mode"] = "all"
        topic_name, body = config("sensor", key, payload)
        entities[topic_name] = body
    topic_name, body = config("sensor", "total_cost", {
        "name": "Total cost", "device_class": "monetary", "state_class": "total",
        "unit_of_measurement": options.currency, "state_topic": TOPICS["stats"],
        "value_template": "{{ value_json.total_cost }}", "json_attributes_topic": TOPICS["stats"],
        "json_attributes_template": "{{ {'wasted_cost': value_json.wasted_cost} | tojson }}"})
    entities[topic_name] = body
    topic_name, body = config("event", "print_finished", {
        "name": "Print finished", "event_types": EVENT_TYPES, "state_topic": TOPICS["event"],
        "icon": "mdi:printer-3d-nozzle-alert"})
    entities[topic_name] = body
    topic_name, body = config("button", "rescan_history", {
        "name": "Rescan history", "command_topic": TOPICS["rescan"], "icon": "mdi:database-sync"})
    entities[topic_name] = body
    return entities


def state_payloads(db, links, recent: int = 10) -> dict[str, dict]:
    """Retained state topic -> payload, derived from the database."""
    stats = db.stats()
    jobs, total = db.jobs(limit=recent)
    payloads = {
        TOPICS["stats"]: stats,
        TOPICS["recent"]: {"count": total, "jobs": [recent_row(j, links) for j in jobs]},
        TOPICS["top_parts"]: {"count": db.distinct_parts(), "parts": db.top_parts(), "excluded": db.top_excluded()},
    }
    if jobs:
        payloads[TOPICS["last_print"]] = job_summary(jobs[0], links)
    return payloads


def current_payload(active: dict) -> dict:
    return {"planned": len(active.get("objects") or []),
            "printed": len(set(active.get("objects") or []) - set(active.get("excluded") or [])),
            "excluded": active.get("excluded") or [],
            "file": active.get("filename")}


class MqttPublisher:
    """Keeps the broker connection. State is rebuilt from the database after every connect."""

    def __init__(self, options, db, supervisor, links, on_rescan):
        self.options = options
        self.db = db
        self.supervisor = supervisor
        self.links = links
        self.on_rescan = on_rescan
        self.client = None
        self.active = None

    async def _broker(self) -> dict | None:
        service = await self.supervisor.mqtt_service()
        if self.options.mqtt_host:
            return {"hostname": self.options.mqtt_host, "port": self.options.mqtt_port,
                    "username": self.options.mqtt_username, "password": self.options.mqtt_password}
        if service:
            return {"hostname": service["host"], "port": service["port"],
                    "username": service.get("username"), "password": service.get("password")}
        return None

    async def run(self):
        broker = await self._broker()
        if broker is None:
            log.warning("No MQTT broker: entities are disabled, tracking and the UI keep working")
            return
        backoff = 1
        will = aiomqtt.Will(AVAILABILITY, OFFLINE, retain=True)
        while True:
            try:
                async with aiomqtt.Client(will=will, **broker) as client:
                    self.client = client
                    backoff = 1
                    await client.subscribe(f"{PREFIX}/status")
                    await client.subscribe(TOPICS["rescan"])
                    await self.publish_all()
                    async for message in client.messages:
                        await self._handle(message)
            except aiomqtt.MqttError as err:
                log.warning("MQTT connection lost: %s", err)
            self.client = None
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    async def _handle(self, message):
        if message.topic.matches(f"{PREFIX}/status") and message.payload == b"online":
            await self.publish_all()
        elif message.topic.matches(TOPICS["rescan"]):
            await self.on_rescan()

    async def _publish(self, topic: str, payload, retain: bool = True):
        text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        await self.client.publish(topic, text, retain=retain)

    async def publish_all(self):
        for topic, payload in discovery(self.options).items():
            await self._publish(topic, payload)
        await self._publish(AVAILABILITY, ONLINE)
        await self._publish_states()
        await self._publish_current()
        await self._flush_events()

    async def _publish_states(self):
        for topic, payload in state_payloads(self.db, self.links).items():
            await self._publish(topic, payload)

    async def _publish_current(self):
        if self.active:
            await self._publish(TOPICS["current"], current_payload(self.active))
        await self._publish(TOPICS["current/availability"], ONLINE if self.active else OFFLINE)

    async def _flush_events(self):
        for record in self.db.pending_events():
            payload = {"event_type": record["status"], **job_summary(record, self.links)}
            await self._publish(TOPICS["event"], payload, retain=False)
            self.db.mark_event_sent(record["job_id"])

    # Tracker listener. Without a connection the data waits in the database.

    async def current(self, active: dict | None):
        self.active = active
        if self.client:
            await self._publish_current()

    async def job_finished(self, record: dict):
        if self.client:
            await self._publish_states()
            await self._flush_events()
