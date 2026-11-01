"""Home Assistant devices over MQTT discovery: one shared, one per printer."""
import asyncio
import json
import logging

import aiomqtt

from .summary import display_currency, job_summary, recent_row

log = logging.getLogger(__name__)

VERSION = "0.3.0"
PREFIX = "homeassistant"
BASE = "klipper_print_tracker"
AVAILABILITY = f"{BASE}/availability"
ONLINE, OFFLINE = "online", "offline"
EVENT_TYPES = ["completed", "cancelled", "error", "rated"]
BROKER_RETRY = 60
TOPICS = {name: f"{BASE}/{name}" for name in (
    "stats", "last_print", "recent", "top_parts", "current", "current/availability", "event", "rescan")}
SENSORS = {
    "total_prints": {"name": "Total prints", "icon": "mdi:printer-3d", "state_class": "total_increasing",
                     "unit_of_measurement": "prints", "value_template": "{{ value_json.total }}",
                     "topic": "stats", "attributes": True},
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
    "unrated_prints": {"name": "Unrated prints", "icon": "mdi:star-outline", "unit_of_measurement": "prints",
                       "value_template": "{{ value_json.unrated }}", "topic": "stats"},
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
SHARED_EXTRA = {}
PRINTER_EXTRA = {}


class Scope:
    """Topics and identifiers of one device: shared when printer is None."""

    def __init__(self, printer=None):
        self.printer = printer
        self.id = printer.id if printer else None
        self.base = f"{BASE}/{printer.id}" if printer else BASE
        self.identifier = f"{BASE}_{printer.id}" if printer else BASE
        self.entity_prefix = f"print_tracker_{printer.id}" if printer else "print_tracker"

    def topic(self, name: str) -> str:
        return f"{self.base}/{name}"

    def device(self) -> dict:
        name = f"Print Tracker ({self.printer.name})" if self.printer else "Print Tracker"
        return {"identifiers": [self.identifier], "name": name, "manufacturer": "KlipperPrintTracker",
                "model": "Home Assistant add-on", "sw_version": VERSION}


def entity(scope: Scope, component: str, key: str, payload: dict) -> tuple[str, dict]:
    unique_id = f"{scope.identifier}_{key}"
    origin = {"name": "KlipperPrintTracker", "sw_version": VERSION,
              "support_url": "https://github.com/currentlib/KlipperPrintTracker"}
    body = {"unique_id": unique_id, "default_entity_id": f"{component}.{scope.entity_prefix}_{key}",
            "device": scope.device(), "origin": origin, "availability_topic": AVAILABILITY, **payload}
    if "availability" in body:
        del body["availability_topic"]
    return f"{PREFIX}/{component}/{unique_id}/config", body


def scope_discovery(scope: Scope, options) -> dict[str, dict]:
    entities = {}

    def add(component, key, payload):
        topic, body = entity(scope, component, key, payload)
        entities[topic] = body

    for key, sensor in SENSORS.items():
        payload = {k: v for k, v in sensor.items() if k not in ("topic", "attributes")}
        topic = scope.topic(sensor["topic"])
        payload["state_topic"] = topic
        if sensor.get("attributes"):
            payload["json_attributes_topic"] = topic
        if key == "current_print_parts":
            payload["availability"] = [{"topic": AVAILABILITY}, {"topic": scope.topic("current/availability")}]
            payload["availability_mode"] = "all"
        add("sensor", key, payload)
    add("sensor", "total_cost", {
        "name": "Total cost", "device_class": "monetary", "state_class": "total",
        "unit_of_measurement": options.currency, "state_topic": scope.topic("stats"),
        "value_template": "{{ value_json.total_cost }}", "json_attributes_topic": scope.topic("stats"),
        "json_attributes_template": "{{ {'wasted_cost': value_json.wasted_cost} | tojson }}"})
    add("event", "print_finished", {
        "name": "Print finished", "event_types": EVENT_TYPES, "state_topic": scope.topic("event"),
        "icon": "mdi:printer-3d-nozzle-alert"})
    add("button", "rescan_history", {
        "name": "Rescan history", "command_topic": scope.topic("rescan"), "icon": "mdi:database-sync"})
    for key, payload in (PRINTER_EXTRA if scope.printer else SHARED_EXTRA).items():
        body = dict(payload)
        component = body.pop("component", "sensor")
        body["state_topic"] = scope.topic(body.pop("topic", "extra"))
        if body.pop("attributes", False):
            body["json_attributes_topic"] = body["state_topic"]
        add(component, key, body)
    return entities


def discovery(options) -> dict[str, dict]:
    """Discovery topic -> payload for every entity of every device."""
    entities = scope_discovery(Scope(), options)
    for printer in options.printers:
        entities.update(scope_discovery(Scope(printer), options))
    return entities


def state_payloads(db, links, options, scope: Scope | None = None, recent: int = 10) -> dict[str, dict]:
    """Retained state topic -> payload, derived from the database."""
    scope = scope or Scope()
    printer = scope.id
    stats = db.stats(printer)
    currency = display_currency(options.currency)
    jobs, total = db.jobs(printer=printer, limit=recent)
    payloads = {
        scope.topic("stats"): {**stats, "currency": currency, "panel_url": links.panel(),
                               "electricity_price": options.electricity_price},
        scope.topic("recent"): {"count": total, "jobs": [recent_row(j, links) for j in jobs]},
        scope.topic("top_parts"): {"count": db.distinct_parts(printer), "parts": db.top_parts(printer=printer),
                                   "excluded": db.top_excluded(printer=printer)},
    }
    if jobs:
        payloads[scope.topic("last_print")] = job_summary(jobs[0], links, currency)
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
        self.active: dict[str, dict] = {}
        self.scopes = [Scope(), *(Scope(p) for p in options.printers)]

    async def _broker(self) -> dict | None:
        if self.options.mqtt_host:
            return {"hostname": self.options.mqtt_host, "port": self.options.mqtt_port,
                    "username": self.options.mqtt_username, "password": self.options.mqtt_password}
        service = await self.supervisor.mqtt_service()
        if service:
            return {"hostname": service["host"], "port": service["port"],
                    "username": service.get("username"), "password": service.get("password")}
        return None

    async def run(self):
        broker = await self._broker()
        if broker is None:
            log.warning("No MQTT broker yet: entities wait for it, tracking and the UI keep working")
        while broker is None:
            await asyncio.sleep(BROKER_RETRY)
            broker = await self._broker()
        backoff = 1
        will = aiomqtt.Will(AVAILABILITY, OFFLINE, retain=True)
        while True:
            try:
                async with aiomqtt.Client(will=will, **broker) as client:
                    self.client = client
                    backoff = 1
                    await client.subscribe(f"{PREFIX}/status")
                    await client.subscribe(f"{BASE}/#")
                    await self.publish_all()
                    async for message in client.messages:
                        await self._handle(message)
            except aiomqtt.MqttError as err:
                log.warning("MQTT connection lost: %s", err)
            self.client = None
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    async def _handle(self, message):
        topic = str(message.topic)
        if topic == f"{PREFIX}/status":
            if message.payload == b"online":
                await self.publish_all()
        elif any(topic == scope.topic("rescan") for scope in self.scopes):
            await self.on_rescan()

    async def _publish(self, topic: str, payload, retain: bool = True):
        text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        await self.client.publish(topic, text, retain=retain)

    async def publish_all(self):
        for topic, payload in discovery(self.options).items():
            await self._publish(topic, payload)
        await self._publish(AVAILABILITY, ONLINE)
        await self.publish_states()
        await self._publish_current()
        await self._flush_events()

    async def publish_states(self):
        if not self.client:
            return
        for scope in self.scopes:
            for topic, payload in state_payloads(self.db, self.links, self.options, scope).items():
                await self._publish(topic, payload)

    async def _publish_current(self):
        for scope in self.scopes:
            active = self.active.get(scope.id) if scope.printer else next(iter(self.active.values()), None)
            if active:
                await self._publish(scope.topic("current"), current_payload(active))
            await self._publish(scope.topic("current/availability"), ONLINE if active else OFFLINE)

    async def _flush_events(self):
        currency = display_currency(self.options.currency)
        for record in self.db.pending_events():
            payload = {"event_type": record["status"], **job_summary(record, self.links, currency)}
            await self.publish_event(record["printer_id"], payload)
            self.db.mark_event_sent(record["job_id"], record["printer_id"])

    async def publish_event(self, printer_id: str, payload: dict):
        for scope in self.scopes:
            if scope.id in (None, printer_id):
                await self._publish(scope.topic("event"), payload, retain=False)

    async def job_rated(self, record: dict):
        if not self.client:
            return
        await self.publish_states()
        summary = job_summary(record, self.links, display_currency(self.options.currency))
        await self.publish_event(record["printer_id"], {**summary, "event_type": "rated"})

    # Tracker listener. Without a connection the data waits in the database.

    async def current(self, printer_id: str, active: dict | None):
        if active:
            self.active[printer_id] = active
        else:
            self.active.pop(printer_id, None)
        if self.client:
            await self._publish_current()

    async def job_finished(self, record: dict):
        if self.client:
            await self.publish_states()
            await self._flush_events()
