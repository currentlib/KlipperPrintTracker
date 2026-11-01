"""Projects: prints grouped toward target quantities of parts."""
import fnmatch
import logging
import time

log = logging.getLogger(__name__)

STATUSES = ("active", "done", "archived")


def matches(rule: dict, record: dict) -> bool:
    pattern = rule["pattern"].lower()
    if rule["kind"] == "file":
        return fnmatch.fnmatch((record.get("filename") or "").lower(), pattern)
    names = set(record.get("printed") or {}) | set(record.get("excluded") or {})
    return any(fnmatch.fnmatch(name.lower(), pattern) for name in names)


def progress(project: dict, jobs: list[dict]) -> dict:
    """Printed vs target. Failed attempts count toward the costs, never toward the parts."""
    good = [j for j in jobs if j["status"] == "completed"]
    failed = [j for j in jobs if j["status"] != "completed"]
    printed: dict[str, int] = {}
    for job in good:
        for name, count in (job.get("printed") or {}).items():
            printed[name] = printed.get(name, 0) + count
    parts = [{"name": t["part"], "target": t["quantity"], "printed": printed.get(t["part"], 0)}
             for t in project["targets"]]
    target = sum(p["target"] for p in parts)
    done = sum(min(p["printed"], p["target"]) for p in parts)

    def totals(group: list[dict]) -> dict:
        return {"hours": round(sum(j.get("print_duration") or 0 for j in group) / 3600, 1),
                "grams": round(sum(j.get("grams") or 0 for j in group), 1),
                "kwh": round(sum(j.get("kwh") or 0 for j in group), 2),
                "cost": round(sum(j.get("total_cost") or 0 for j in group), 2)}

    made = sum(printed.values())
    left = target - done
    success, wasted = totals(good), totals(failed)
    estimate = None
    if made and left:
        estimate = {"hours": round(success["hours"] / made * left, 1), "grams": round(success["grams"] / made * left, 1)}
    return {"parts": parts, "target": target, "done": done, "percent": round(100 * done / target) if target else 0,
            "prints": len(jobs), "success": success, "failed": wasted, "estimate": estimate}


class Projects:
    def __init__(self, db):
        self.db = db
        self.listeners = []

    def _load(self, row) -> dict:
        project = dict(row)
        project["targets"] = [dict(t) for t in self.db._query(
            "SELECT part, quantity FROM project_targets WHERE project_id = ? ORDER BY part", (project["id"],))]
        project["rules"] = [dict(r) for r in self.db._query(
            "SELECT kind, pattern FROM project_rules WHERE project_id = ?", (project["id"],))]
        return project

    def all(self, status: str | None = None) -> list[dict]:
        rows = self.db._query("""SELECT * FROM projects WHERE ? IS NULL OR status = ?
                                 ORDER BY status, created_at DESC""", (status, status))
        return [self.with_progress(self._load(row)) for row in rows]

    def get(self, project_id: int) -> dict | None:
        rows = self.db._query("SELECT * FROM projects WHERE id = ?", (project_id,))
        return self.with_progress(self._load(rows[0])) if rows else None

    def jobs(self, project_id: int) -> list[dict]:
        return self.db.jobs(project=project_id, limit=100000)[0]

    def with_progress(self, project: dict) -> dict:
        return {**project, **progress(project, self.jobs(project["id"]))}

    def save(self, data: dict, project_id: int | None = None) -> int:
        fields = {k: data[k] for k in ("name", "description", "status", "deadline") if k in data}
        if fields.get("status", "active") not in STATUSES:
            raise ValueError("Bad status")
        # Checked before anything changes, a bad request must not lose the existing lists.
        targets = [(t["part"], int(t["quantity"])) for t in data.get("targets", [])]
        rules = [(r["kind"], r["pattern"]) for r in data.get("rules", [])]
        if project_id is None:
            self.db._write("INSERT INTO projects (name, status, created_at) VALUES (?, 'active', ?)",
                           (fields.get("name") or "?", time.time()))
            project_id = self.db._query("SELECT MAX(id) id FROM projects")[0]["id"]
        if fields:
            columns = ", ".join(f"{name} = ?" for name in fields)
            self.db._write(f"UPDATE projects SET {columns} WHERE id = ?", (*fields.values(), project_id))
        if "targets" in data:
            self.db._write("DELETE FROM project_targets WHERE project_id = ?", (project_id,))
            for part, quantity in targets:
                self.db._write("INSERT OR REPLACE INTO project_targets VALUES (?, ?, ?)", (project_id, part, quantity))
        if "rules" in data:
            self.db._write("DELETE FROM project_rules WHERE project_id = ?", (project_id,))
            for kind, pattern in rules:
                self.db._write("INSERT INTO project_rules VALUES (?, ?, ?)", (project_id, kind, pattern))
        return project_id

    def delete(self, project_id: int):
        """The prints stay, they just leave the project."""
        self.db._write("UPDATE jobs SET project_id = NULL, project_line = NULL WHERE project_id = ?", (project_id,))
        for table in ("project_targets", "project_rules"):
            self.db._write(f"DELETE FROM {table} WHERE project_id = ?", (project_id,))
        self.db._write("DELETE FROM projects WHERE id = ?", (project_id,))

    def assign(self, job_id: str, printer_id: str, project_id: int | None):
        """A print counts toward one project, a manual choice replaces the rules' choice."""
        self.db.update_job(job_id, printer_id, project_id=project_id)
        self._set_line(job_id, printer_id, project_id)

    def _set_line(self, job_id: str, printer_id: str, project_id: int | None) -> str | None:
        line = None
        if project_id is not None:
            project = self.get(project_id)
            line = f"Проєкт {project['name']}: {project['done']} / {project['target']}"
        self.db.update_job(job_id, printer_id, project_line=line)
        return line

    async def job_finished(self, record: dict):
        for project in self.all("active"):
            if any(matches(rule, record) for rule in project["rules"]):
                self.db.update_job(record["job_id"], record["printer_id"], project_id=project["id"])
                record["project_id"] = project["id"]
                record["project_line"] = self._set_line(record["job_id"], record["printer_id"], project["id"])
                return

    # Tracker listener

    async def current(self, printer_id, active):
        pass

    async def spool_checked(self, printer_id, result):
        pass

    # MQTT provider

    def entities(self, scope) -> list[tuple[str, str, dict]]:
        if scope.printer:
            return []
        items = []
        for project in self.all("active"):
            topic = scope.topic(f"project/{project['id']}")
            items.append(("sensor", f"project_{project['id']}", {
                "name": f"Project {project['name']}", "icon": "mdi:folder-multiple-outline", "state_topic": topic,
                "unit_of_measurement": "%", "value_template": "{{ value_json.percent }}", "json_attributes_topic": topic}))
        return items

    def states(self, scope) -> dict[str, dict]:
        if scope.printer:
            return {}
        return {scope.topic(f"project/{p['id']}"): {
            "percent": p["percent"], "done": p["done"], "target": p["target"], "parts": p["parts"], "deadline": p["deadline"]}
            for p in self.all("active")}

    def subscriptions(self) -> list[str]:
        return []

    async def command(self, topic: str, payload: bytes) -> bool:
        return False
