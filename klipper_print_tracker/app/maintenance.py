"""Maintenance reminders counted by print hours, filament, prints and calendar days."""
import logging
import re
import time

log = logging.getLogger(__name__)

DAY = 86400
DUE_EVENT = "klipper_print_tracker_maintenance_due"
SNOOZE_HOURS = 10
# name, hours, days, abrasive grams, note
DEFAULT_TASKS = (
    ("Очистити стіл (IPA / мийка)", 20, 7, None, "Час від часу мийте PEI милом і водою"),
    ("Огляд сопла, очистити зовні", 50, 30, None, ""),
    ("Очистити шестерні екструдера від стружки", 100, 60, None, "Щіткою, а також після кожного засмічення"),
    ("Протерти вал X (графітові втулки, без мастила)", 150, 60, None,
     "На K1 вал X у графітових втулках: протирати, не змащувати"),
    ("Змастити вали Y і гвинти Z (з комплекту)", 200, 60, None, "Тонкий шар мастила з комплекту"),
    ("Перевірити натяг ременів, огляд шківів", 150, 30, None, "Пил біля шківів означає тертя"),
    ("Почистити кулери (хотенд, обдув, бічний, камера)", 200, 90, None,
     "Тримайте лопаті, коли продуваєте стисненим повітрям"),
    ("Перевірити кріплення хотенда, люфт каретки, гвинти", 300, 90, None, ""),
    ("Перевірити роз'єми (хотенд, стіл, живлення)", 600, 180, None, ""),
    ("Перевірити PTFE трубку", 500, 180, None, "Замінити, якщо зношена або змінила колір"),
    ("Перекалібрувати (bed mesh, input shaper)", 300, 90, None, "Також після обслуговування"),
    ("Огляд / заміна сопла", 1000, None, 1000,
     "Загартоване сопло довго живе на PLA/PETG, CF/GF зношує його набагато швидше"),
)
FIELDS = ("name", "note", "hours", "days", "grams", "prints", "abrasive_grams", "material_pattern", "enabled")
UNITS = {"hours": "год", "days": "дн", "grams": "г", "prints": "друків", "abrasive_grams": "г"}


def limits(task: dict, usage: dict, now: float) -> list[dict]:
    """One entry per configured limit. Task order keeps the main unit stable."""
    used = {"hours": usage["hours"], "days": (now - task["last_done_at"]) / DAY, "grams": usage["grams"],
            "prints": usage["prints"], "abrasive_grams": usage["abrasive_grams"]}
    result = []
    for kind in ("hours", "days", "grams", "prints", "abrasive_grams"):
        limit = task.get(kind)
        if limit:
            result.append({"kind": kind, "limit": limit, "used": round(used[kind], 1),
                           "remaining": round(limit - used[kind], 1), "ratio": used[kind] / limit, "unit": UNITS[kind]})
    return result


def state(task: dict, usage: dict, now: float, total_hours: float) -> dict:
    """Whichever limit comes first decides."""
    items = limits(task, usage, now)
    worst = max(items, key=lambda item: item["ratio"]) if items else None
    ratio = worst["ratio"] if worst else 0
    snoozed = bool(task.get("snooze_until_hours") and total_hours < task["snooze_until_hours"])
    return {**task, "limits": items, "worst": worst, "main": items[0] if items else None,
            "percent_used": round(ratio * 100), "percent_left": max(0, round(100 - ratio * 100)),
            "due": ratio >= 1 and not snoozed and bool(task["enabled"]), "snoozed": snoozed}


def usage_since(jobs: list[dict], since: float, patterns: str, material_pattern: str | None = None) -> dict:
    """Counters over finished prints. Failed prints wear the machine too."""
    usage = {"hours": 0.0, "grams": 0.0, "prints": 0, "abrasive_grams": 0.0}
    abrasive = re.compile(patterns, re.IGNORECASE) if patterns else None
    wanted = re.compile(material_pattern, re.IGNORECASE) if material_pattern else None
    for job in jobs:
        if (job["end_time"] or 0) <= since:
            continue
        label = f"{job['material'] or ''} {job['spool'] or ''}"
        usage["hours"] += (job["print_duration"] or 0) / 3600
        usage["prints"] += 1
        if wanted is None or wanted.search(label):
            usage["grams"] += job["grams"] or 0
        if abrasive and abrasive.search(label):
            usage["abrasive_grams"] += job["grams"] or 0
    return usage


class Maintenance:
    def __init__(self, db, options, supervisor=None):
        self.db = db
        self.options = options
        self.supervisor = supervisor
        self.listeners = []
        self.busy = lambda printer_id: False

    def ensure_defaults(self, printer_id: str):
        """Dates default to now and stay unconfirmed until the UI asks about them."""
        key = f"maintenance_seeded:{printer_id}"
        if self.db._get_meta(key):
            return
        now = time.time()
        for position, (name, hours, days, abrasive, note) in enumerate(DEFAULT_TASKS):
            self.db._write("""INSERT INTO maintenance_tasks (printer_id, position, name, note, hours, days,
                              abrasive_grams, last_done_at, confirmed) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                           (printer_id, position, name, note, hours, days, abrasive, now))
        self.db._set_meta(key, "1")

    def _jobs(self, printer_id: str) -> list[dict]:
        return [dict(row) for row in self.db._query(
            "SELECT end_time, print_duration, grams, material, spool FROM jobs WHERE printer_id = ?", (printer_id,))]

    def task(self, task_id: int) -> dict | None:
        rows = self.db._query("SELECT * FROM maintenance_tasks WHERE id = ?", (task_id,))
        return dict(rows[0]) if rows else None

    def tasks(self, printer_id: str, now: float | None = None) -> list[dict]:
        """Current state of every task, most urgent first."""
        now = now or time.time()
        jobs = self._jobs(printer_id)
        total_hours = sum((j["print_duration"] or 0) for j in jobs) / 3600
        rows = self.db._query("SELECT * FROM maintenance_tasks WHERE printer_id = ? ORDER BY position, id", (printer_id,))
        result = []
        for row in rows:
            task = dict(row)
            usage = usage_since(jobs, task["last_done_at"], self.options.abrasive_patterns, task["material_pattern"])
            result.append(state(task, usage, now, total_hours))
        return sorted(result, key=lambda t: (not t["enabled"], -t["percent_used"]))

    def log(self, printer_id: str, limit: int = 50) -> list[dict]:
        rows = self.db._query("""SELECT l.*, t.name FROM maintenance_log l LEFT JOIN maintenance_tasks t ON t.id = l.task_id
                                 WHERE l.printer_id = ? ORDER BY l.done_at DESC LIMIT ?""", (printer_id, limit))
        return [dict(row) for row in rows]

    async def _changed(self):
        for listener in self.listeners:
            await listener.publish_states()

    async def done(self, task_id: int, note: str = "", when: float | None = None) -> bool:
        task = self.task(task_id)
        if task is None:
            return False
        when = when or time.time()
        self.db._write("""UPDATE maintenance_tasks SET last_done_at = ?, notified_at = NULL,
                          snooze_until_hours = NULL WHERE id = ?""", (when, task_id))
        self.db._write("INSERT INTO maintenance_log (task_id, printer_id, done_at, note, name) VALUES (?, ?, ?, ?, ?)",
                       (task_id, task["printer_id"], when, note, task["name"]))
        await self._changed()
        return True

    async def snooze(self, task_id: int, hours: float = SNOOZE_HOURS) -> bool:
        task = self.task(task_id)
        if task is None:
            return False
        total = sum((j["print_duration"] or 0) for j in self._jobs(task["printer_id"])) / 3600
        self.db._write("UPDATE maintenance_tasks SET snooze_until_hours = ?, notified_at = NULL WHERE id = ?",
                       (total + hours, task_id))
        await self._changed()
        return True

    def save(self, printer_id: str, data: dict, task_id: int | None = None) -> int:
        values = {k: data[k] for k in FIELDS if k in data}
        if task_id is None:
            self.db._write("""INSERT INTO maintenance_tasks (printer_id, position, name, last_done_at, confirmed)
                              VALUES (?, 1000, ?, ?, 1)""", (printer_id, values.get("name") or "?", time.time()))
            task_id = self.db._query("SELECT MAX(id) id FROM maintenance_tasks")[0]["id"]
        if values:
            columns = ", ".join(f"{name} = ?" for name in values)
            self.db._write(f"UPDATE maintenance_tasks SET {columns} WHERE id = ?", (*values.values(), task_id))
        return task_id

    def delete(self, task_id: int):
        self.db._write("DELETE FROM maintenance_tasks WHERE id = ?", (task_id,))

    def confirm(self, printer_id: str, dates: dict[str, float]):
        """Answers to "when was this last done", tasks not listed keep today."""
        for task_id, when in dates.items():
            self.db._write("UPDATE maintenance_tasks SET last_done_at = ? WHERE id = ? AND printer_id = ?",
                           (when, int(task_id), printer_id))
        self.db._write("UPDATE maintenance_tasks SET confirmed = 1 WHERE printer_id = ?", (printer_id,))

    async def check(self, printer_id: str) -> list[dict]:
        """Announce newly due tasks once, and never in the middle of a print."""
        if self.busy(printer_id):
            return []
        fresh = [t for t in self.tasks(printer_id) if t["due"] and not t["notified_at"]]
        for task in fresh:
            self.db._write("UPDATE maintenance_tasks SET notified_at = ? WHERE id = ?", (time.time(), task["id"]))
            if self.supervisor:
                await self.supervisor.fire_event(DUE_EVENT, {
                    "printer_id": printer_id, "task_id": task["id"], "name": task["name"], "note": task["note"]})
        return fresh

    # Tracker listener

    async def current(self, printer_id, active):
        pass

    async def spool_checked(self, printer_id, result):
        pass

    async def job_finished(self, record: dict):
        await self.check(record["printer_id"])

    # Notification actions

    async def from_action(self, printer_id: str, target: str, code: str, text: str | None) -> bool:
        if not target.startswith("maint-"):
            return False
        task_id = int(target.removeprefix("maint-"))
        task = self.task(task_id)
        if task is None or task["printer_id"] != printer_id:
            return True
        if code == "done":
            await self.done(task_id, text or "")
        elif code == "snooze":
            await self.snooze(task_id)
        return True

    # MQTT provider

    def entities(self, scope) -> list[tuple[str, str, dict]]:
        if not scope.printer:
            return []
        items = []
        for task in self.tasks(scope.id):
            key = f"maint_{task['id']}"
            topic = scope.topic(f"maint/{task['id']}")
            main = task["main"] or {"unit": "%"}
            items.append(("sensor", key, {
                "name": task["name"], "icon": "mdi:wrench-clock", "state_topic": topic,
                "unit_of_measurement": main["unit"], "value_template": "{{ value_json.remaining }}",
                "json_attributes_topic": topic}))
            items.append(("binary_sensor", f"{key}_due", {
                "name": f"{task['name']}: due", "device_class": "problem", "state_topic": topic,
                "value_template": "{{ 'ON' if value_json.due else 'OFF' }}"}))
            items.append(("button", f"{key}_done", {
                "name": f"{task['name']}: done", "icon": "mdi:check", "command_topic": f"{topic}/done"}))
        return items

    def states(self, scope) -> dict[str, dict]:
        if not scope.printer:
            return {}
        return {scope.topic(f"maint/{t['id']}"): {
            "remaining": (t["main"] or {}).get("remaining"), "due": t["due"], "percent_left": t["percent_left"],
            "note": t["note"], "last_done": t["last_done_at"]} for t in self.tasks(scope.id)}

    def subscriptions(self) -> list[str]:
        return ["klipper_print_tracker/+/maint/+/done"]

    async def command(self, topic: str, payload: bytes) -> bool:
        match = re.fullmatch(r"klipper_print_tracker/\w+/maint/(\d+)/done", topic)
        if match:
            await self.done(int(match.group(1)))
        return bool(match)


