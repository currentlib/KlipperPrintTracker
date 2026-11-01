"""Failure analysis over finished prints. Pure functions plus the HA sensors."""
import time
from datetime import datetime

DAY = 86400
OFFLINE = "power_or_offline"
LAYER_BUCKETS = ((1, 1, "1"), (2, 5, "2-5"), (6, 20, "6-20"), (21, 50, "21-50"), (51, 100, "51-100"), (101, 10**9, "100+"))
TOP = 10


def failed(job: dict) -> bool:
    return job["status"] != "completed"


def counted(jobs: list[dict], include_power: bool) -> list[dict]:
    """A power cut says nothing about the printer, so it stays out of reliability numbers."""
    return jobs if include_power else [j for j in jobs if j.get("interruption") != OFFLINE]


def weekly(jobs: list[dict]) -> list[dict]:
    weeks: dict[str, dict] = {}
    for job in sorted(jobs, key=lambda j: j["end_time"] or 0):
        year, week, _ = datetime.fromtimestamp(job["end_time"] or 0).isocalendar()
        entry = weeks.setdefault(f"{year}-{week:02}", {"week": f"{year}-{week:02}", "total": 0, "completed": 0})
        entry["total"] += 1
        entry["completed"] += job["status"] == "completed"
    for entry in weeks.values():
        entry["rate"] = round(100 * entry["completed"] / entry["total"], 1)
    return list(weeks.values())


def _names(job: dict, dimension: str) -> list[str]:
    presets = job.get("presets") or {}
    if dimension == "material":
        return [job["material"]] if job.get("material") else []
    if dimension == "filament_preset":
        return (presets.get("filament") or [])[:1]
    if dimension == "process_preset":
        return (presets.get("process") or [])[:1]
    if dimension == "spool":
        return [job["spool"]] if job.get("spool") else []
    return sorted(set(job.get("printed") or {}) | set(job.get("excluded") or {}))


def by_dimension(jobs: list[dict], dimension: str) -> list[dict]:
    """Failure rate and top reasons per value, the worst first."""
    groups: dict[str, dict] = {}
    for job in jobs:
        for name in _names(job, dimension):
            group = groups.setdefault(name, {"name": name, "total": 0, "failed": 0, "reasons": {}})
            group["total"] += 1
            if failed(job):
                group["failed"] += 1
                reason = job.get("failure_reason") or "unknown"
                group["reasons"][reason] = group["reasons"].get(reason, 0) + 1
    for group in groups.values():
        group["rate"] = round(100 * group["failed"] / group["total"], 1)
    return sorted(groups.values(), key=lambda g: (-g["rate"], -g["total"], g["name"]))[:TOP]


def progress_histogram(jobs: list[dict]) -> list[dict]:
    """Failed prints per 10% of progress."""
    buckets = [{"label": f"{i * 10}-{i * 10 + 10}%", "count": 0} for i in range(10)]
    for job in jobs:
        if failed(job) and job.get("progress") is not None:
            buckets[min(int(job["progress"] // 10), 9)]["count"] += 1
    return buckets


def layer_histogram(jobs: list[dict]) -> list[dict]:
    buckets = [{"label": label, "count": 0} for _, _, label in LAYER_BUCKETS]
    for job in jobs:
        layer = job.get("current_layer")
        if failed(job) and layer:
            for bucket, (low, high, _) in zip(buckets, LAYER_BUCKETS):
                if low <= layer <= high:
                    bucket["count"] += 1
    return buckets


def wasted(jobs: list[dict]) -> dict:
    lost = [j for j in jobs if failed(j)]
    return {"hours": round(sum(j.get("print_duration") or 0 for j in lost) / 3600, 1),
            "grams": round(sum(j.get("grams") or 0 for j in lost), 1),
            "cost": round(sum(j.get("wasted_cost") or 0 for j in lost), 2)}


def problem_parts(jobs: list[dict]) -> list[dict]:
    parts: dict[str, dict] = {}
    for job in jobs:
        for name in _names(job, "part"):
            entry = parts.setdefault(name, {"name": name, "printed": 0, "excluded": 0, "failed_prints": 0})
            entry["printed"] += (job.get("printed") or {}).get(name, 0)
            entry["excluded"] += (job.get("excluded") or {}).get(name, 0)
            entry["failed_prints"] += failed(job)
    for entry in parts.values():
        attempts = entry["printed"] + entry["excluded"] + entry["failed_prints"]
        entry["problem_rate"] = round(100 * (entry["excluded"] + entry["failed_prints"]) / attempts, 1) if attempts else 0
    problems = [p for p in parts.values() if p["problem_rate"] > 0]
    return sorted(problems, key=lambda p: (-p["problem_rate"], -p["excluded"], p["name"]))[:TOP]


def tag_frequency(jobs: list[dict], dimension: str) -> list[dict]:
    rows: dict[tuple, int] = {}
    for job in jobs:
        for tag in job.get("issues") or []:
            for name in _names(job, dimension) or ["-"]:
                rows[(name, tag)] = rows.get((name, tag), 0) + 1
    ordered = sorted(rows.items(), key=lambda item: (-item[1], item[0]))[:TOP]
    return [{"name": name, "tag": tag, "count": count} for (name, tag), count in ordered]


def top_reason(jobs: list[dict]) -> str | None:
    reasons: dict[str, int] = {}
    for job in jobs:
        if failed(job) and job.get("failure_reason"):
            reasons[job["failure_reason"]] = reasons.get(job["failure_reason"], 0) + 1
    return max(sorted(reasons), key=reasons.get) if reasons else None


def analyse(jobs: list[dict], include_power: bool = False) -> dict:
    reliable = counted(jobs, include_power)
    done = sum(j["status"] == "completed" for j in reliable)
    return {
        "total": len(reliable), "completed": done, "failed": len(reliable) - done,
        "offline": len(jobs) - len(counted(jobs, False)),
        "success_rate": round(100 * done / len(reliable), 1) if reliable else 0,
        "weekly": weekly(reliable), "wasted": wasted(reliable), "top_reason": top_reason(reliable),
        "progress": progress_histogram(reliable), "layers": layer_histogram(reliable),
        "dimensions": {name: by_dimension(reliable, name)
                       for name in ("material", "filament_preset", "process_preset", "spool", "part")},
        "problem_parts": problem_parts(reliable),
        "tags_by_material": tag_frequency(reliable, "material"),
        "tags_by_preset": tag_frequency(reliable, "process_preset"),
    }


class Analysis:
    """Rolling numbers as HA sensors, on both the shared and the printer devices."""

    def __init__(self, db):
        self.db = db

    def entities(self, scope) -> list[tuple[str, str, dict]]:
        topic = scope.topic("analysis")
        return [
            ("sensor", "success_rate_30d", {
                "name": "Success rate, 30 days", "icon": "mdi:check-decagram", "state_topic": topic,
                "unit_of_measurement": "%", "state_class": "measurement", "value_template": "{{ value_json.success_rate }}"}),
            ("sensor", "failures_30d", {
                "name": "Failures, 30 days", "icon": "mdi:alert-circle-outline", "state_topic": topic,
                "unit_of_measurement": "prints", "value_template": "{{ value_json.failed }}",
                "json_attributes_topic": topic}),
        ]

    def states(self, scope) -> dict[str, dict]:
        jobs, _ = self.db.jobs(printer=scope.id, date_from=time.time() - 30 * DAY, limit=100000)
        reliable = counted(jobs, False)
        done = sum(j["status"] == "completed" for j in reliable)
        return {scope.topic("analysis"): {
            "success_rate": round(100 * done / len(reliable), 1) if reliable else 0,
            "failed": len(reliable) - done, "top_reason": top_reason(reliable)}}

    def subscriptions(self) -> list[str]:
        return []

    async def command(self, topic: str, payload: bytes) -> bool:
        return False
