"""Calibration log. Detection follows what OrcaSlicer really writes:

Calibration models keep their file name in EXCLUDE_OBJECT_DEFINE, for example
temperature_tower.drc_id_0_copy_0. PA and retraction tests also leave marks in the G-code, the
other tests change speed or per-object flow only, so their name is all there is.
"""
import logging
import re
import time
from collections import Counter

from . import gcode, views
from .calc import normalise_name

log = logging.getLogger(__name__)

DAY = 86400
MODEL_TYPES = {
    "temperature_tower": "temperature", "pressure_advance_test": "pa_line", "tower_with_seam": "pa_tower",
    "retraction_tower": "retraction", "SpeedTestStructure": "max_volumetric_speed", "vfa": "vfa",
    "flowrate-test-pass1": "flow_pass1", "flowrate-test-pass2": "flow_pass2",
    "Orca-LinearFlow": "flow_yolo", "Orca-LinearFlow_fine": "flow_yolo",
}
TYPES = ("pa_line", "pa_pattern", "pa_tower", "flow_pass1", "flow_pass2", "flow_yolo", "temperature", "retraction",
         "max_volumetric_speed", "vfa")
# Which setting a calibration result ends up in.
RESULT_KEYS = {"pa": "pressure_advance", "flow": "filament_flow_ratio", "temperature": "nozzle_temperature",
               "retraction": "filament_retraction_length", "max_volumetric_speed": "filament_max_volumetric_speed"}
SCAN = rb"^(M104 S[1-9]|SET_PRESSURE_ADVANCE ADVANCE=|; Calib_Retraction_tower:|; start pressure advance pattern)"
_TEMP = re.compile(r"^M104 S(\d+)", re.MULTILINE)
_PA = re.compile(r"^SET_PRESSURE_ADVANCE ADVANCE=([\d.]+)", re.MULTILINE)
_RETRACTION = re.compile(r"^; Calib_Retraction_tower: Z_HEIGHT: [\d.]+, length:([\d.]+)", re.MULTILINE)
PATTERN_MARK = "; start pressure advance pattern"


def group(kind: str) -> str:
    return "pa" if kind.startswith("pa_") else "flow" if kind.startswith("flow_") else kind


def by_model(names: list[str]) -> str | None:
    for name in names:
        kind = MODEL_TYPES.get(normalise_name(name))
        if kind:
            return kind
    return None


def worth_scanning(head: str, names: list[str]) -> bool:
    """Reading a whole file is only justified when the start already looks like a test."""
    return bool(by_model(names) or PATTERN_MARK in head or "Calib_Retraction_tower" in head
                or len(set(_PA.findall(head))) >= 3)


def value_range(values: list[float]) -> dict | None:
    """Start, end and the usual step of a sequence that changes along the print."""
    changes = [b for a, b in zip([None, *values], values) if a != b]
    if len(set(changes)) < 2:
        return None
    steps = Counter(round(b - a, 6) for a, b in zip(changes, changes[1:]))
    return {"start": changes[0], "end": changes[-1], "step": steps.most_common(1)[0][0]}


def detect(names: list[str], lines: str) -> dict | None:
    """Type and tested range, None when nothing clearly says calibration."""
    pa = [float(v) for v in _PA.findall(lines)]
    retraction = [float(v) for v in _RETRACTION.findall(lines)]
    kind = by_model(names)
    if retraction:
        kind = "retraction"
    elif PATTERN_MARK in lines:
        kind = "pa_pattern"
    elif kind is None and len(set(pa)) >= 3:
        kind = "pa_tower"
    if kind is None:
        return None
    if kind == "temperature":
        tested = value_range([float(v) for v in _TEMP.findall(lines)])
    elif kind == "retraction":
        tested = value_range(retraction)
    elif group(kind) == "pa":
        tested = value_range([v for v in pa if v > 0])
    else:
        tested = None
    return {"type": kind, "range": tested}


def parse_value(text: str | None) -> float | None:
    match = re.search(r"-?\d+(?:[.,]\d+)?", text or "")
    return float(match.group(0).replace(",", ".")) if match else None


class Calibrations:
    def __init__(self, db, options, moonrakers: dict):
        self.db = db
        self.options = options
        self.moonrakers = moonrakers
        self.listeners = []

    def get(self, printer_id: str, job_id: str) -> dict | None:
        rows = self.db._query("SELECT * FROM calibrations WHERE printer_id = ? AND job_id = ?", (printer_id, job_id))
        return dict(rows[0]) if rows else None

    def save(self, record: dict, kind: str, tested: dict | None, detected: bool, value: float | None = None):
        presets = record.get("presets") or {}
        tested = tested or {}
        self.db._write("""INSERT OR REPLACE INTO calibrations (printer_id, job_id, type, range_start, range_end,
                          range_step, value, filament_preset, material, spool, spool_id, created_at, detected)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                       (record["printer_id"], record["job_id"], kind, tested.get("start"), tested.get("end"),
                        tested.get("step"), value, (presets.get("filament") or [None])[0], record.get("material"),
                        record.get("spool"), record.get("spool_id"), record.get("end_time") or time.time(), int(detected)))
        self.db.update_job(record["job_id"], record["printer_id"], calibration=kind)
        record["calibration"] = kind

    async def job_finished(self, record: dict):
        head = record.pop("gcode_head", "") or ""
        names = gcode.object_names(head)
        if not head or not worth_scanning(head, names):
            return
        moonraker = self.moonrakers.get(record["printer_id"])
        try:
            lines = await moonraker.scan_gcode(record["filename"], SCAN)
        except Exception as err:
            log.warning("Can't scan %s: %s", record["filename"], err)
            lines = head
        found = detect(names, lines)
        if found:
            self.save(record, found["type"], found["range"], True)

    async def set_value(self, printer_id: str, job_id: str, value: float | None) -> bool:
        if self.get(printer_id, job_id) is None:
            return False
        self.db._write("UPDATE calibrations SET value = ?, value_at = ? WHERE printer_id = ? AND job_id = ?",
                       (value, time.time(), printer_id, job_id))
        for listener in self.listeners:
            await listener.publish_states()
        return True

    async def from_action(self, printer_id: str, target: str, code: str, text: str | None) -> bool:
        if code != "result":
            return False
        await self.set_value(printer_id, target, parse_value(text))
        return True

    def history(self, printer_id: str | None = None) -> list[dict]:
        rows = self.db._query("""SELECT c.*, j.filename FROM calibrations c LEFT JOIN jobs j USING (printer_id, job_id)
                                 WHERE ? IS NULL OR c.printer_id = ? ORDER BY c.created_at DESC""", (printer_id, printer_id))
        return [dict(row) for row in rows]

    def _used_value(self, printer_id: str, preset: str, kind: str, since: float) -> tuple[float | None, dict | None]:
        """What the latest ordinary print with this preset used."""
        key = RESULT_KEYS.get(group(kind))
        if key is None:
            return None, None
        for job in reversed(self.db.preset_jobs("filament", preset, printer_id)):
            if job.get("calibration") or (job["end_time"] or 0) <= since:
                continue
            config = self.db.get_config(job["config_hash"]) or {}
            raw = views.preset_values(config, "filament", preset, [key]).get(key)
            if group(kind) == "retraction" and raw in (None, "nil"):
                raw = config.get("retraction_length")
            try:
                return float(str(raw).rstrip("%")), job
            except ValueError:
                return None, job
        return None, None

    def overview(self, printer_id: str | None = None, now: float | None = None) -> list[dict]:
        """Per filament preset: the latest result of each kind, its history and any hints."""
        now = now or time.time()
        presets: dict[tuple, dict] = {}
        for row in self.history(printer_id):
            preset = row["filament_preset"] or "-"
            entry = presets.setdefault((row["printer_id"], preset), {
                "printer_id": row["printer_id"], "preset": preset, "material": row["material"], "latest": {}, "history": []})
            entry["history"].append(row)
            latest = entry["latest"]
            kind = group(row["type"])
            if row["value"] is not None and kind not in latest:
                latest[kind] = self._hints(row, now)
        return sorted(presets.values(), key=lambda e: e["preset"])

    def _hints(self, row: dict, now: float) -> dict:
        used, job = self._used_value(row["printer_id"], row["filament_preset"], row["type"], row["created_at"])
        age = (now - row["created_at"]) / DAY
        new_spool = bool(job and row["spool_id"] and job.get("spool_id") and job["spool_id"] != row["spool_id"])
        mismatch = used is not None and abs(used - row["value"]) > 1e-6
        return {**row, "used": used, "mismatch": mismatch, "age_days": round(age),
                "stale": age > self.options.calibration_stale_days or new_spool, "new_spool": new_spool}

    def mismatches(self, printer_id: str | None = None) -> list[dict]:
        return [{"preset": e["preset"], "type": kind, "value": hint["value"], "used": hint["used"]}
                for e in self.overview(printer_id) for kind, hint in e["latest"].items() if hint["mismatch"]]

    # Tracker listener

    async def current(self, printer_id, active):
        pass

    async def spool_checked(self, printer_id, result):
        pass

    # MQTT provider

    def entities(self, scope) -> list[tuple[str, str, dict]]:
        if not scope.printer:
            return []
        topic = scope.topic("calibration")
        return [("sensor", "calibration_mismatches", {
            "name": "Calibration mismatches", "icon": "mdi:tune-variant", "state_topic": topic,
            "value_template": "{{ value_json.count }}", "json_attributes_topic": topic})]

    def states(self, scope) -> dict[str, dict]:
        if not scope.printer:
            return {}
        items = self.mismatches(scope.id)
        return {scope.topic("calibration"): {"count": len(items), "mismatches": items[:10]}}

    def subscriptions(self) -> list[str]:
        return []

    async def command(self, topic: str, payload: bytes) -> bool:
        return False
