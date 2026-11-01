"""Periodic jobs that keep the add-on's data small."""
import asyncio
import logging
import subprocess
import time
from pathlib import Path

log = logging.getLogger(__name__)

DAY = 86400
GC_INTERVAL = 7 * DAY


def folder_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def data_size(data_dir: Path) -> dict:
    """Megabytes of what the add-on stores."""
    data_dir = Path(data_dir)
    database = sum(f.stat().st_size for f in data_dir.glob("tracker.db*") if f.is_file())
    sizes = {"database": database, "git": folder_bytes(data_dir / "git"), "thumbnails": folder_bytes(data_dir / "thumbs")}
    result = {name: round(value / 1048576, 2) for name, value in sizes.items()}
    result["total"] = round(sum(sizes.values()) / 1048576, 2)
    return result


def prune_thumbnails(folder: Path, days: int, now: float | None = None) -> int:
    """Records stay, only their pictures go. Zero days keeps everything."""
    if days <= 0 or not folder.exists():
        return 0
    limit = (now or time.time()) - days * DAY
    removed = 0
    for path in folder.iterdir():
        if path.is_file() and path.stat().st_mtime < limit:
            path.unlink()
            removed += 1
    return removed


def git_gc(root: Path):
    for repo in Path(root).glob("*/.git"):
        try:
            subprocess.run(["git", "gc", "--auto", "--quiet"], cwd=repo.parent, check=True,
                           capture_output=True, timeout=300)
        except (subprocess.SubprocessError, OSError) as err:
            log.warning("git gc failed in %s: %s", repo.parent, err)


class Housekeeping:
    def __init__(self, data_dir: Path, options, db, on_tick=()):
        self.data_dir = Path(data_dir)
        self.options = options
        self.db = db
        self.on_tick = list(on_tick)

    async def daily(self):
        removed = await asyncio.to_thread(prune_thumbnails, self.data_dir / "thumbs", self.options.thumbnail_retention_days)
        if removed:
            log.info("Removed %s old thumbnails", removed)
        last = float(self.db._get_meta("git_gc_at") or 0)
        if time.time() - last >= GC_INTERVAL:
            await asyncio.to_thread(git_gc, self.data_dir / "git")
            self.db._set_meta("git_gc_at", str(time.time()))
        for callback in self.on_tick:
            await callback()

    async def run(self):
        while True:
            await self.daily()
            await asyncio.sleep(DAY)

    # MQTT provider

    def entities(self, scope) -> list[tuple[str, str, dict]]:
        if scope.printer:
            return []
        return [("sensor", "data_size", {
            "name": "Data size", "icon": "mdi:database", "state_topic": scope.topic("data_size"),
            "unit_of_measurement": "MB", "device_class": "data_size", "state_class": "measurement",
            "value_template": "{{ value_json.total }}", "json_attributes_topic": scope.topic("data_size")})]

    def states(self, scope) -> dict[str, dict]:
        return {} if scope.printer else {scope.topic("data_size"): data_size(self.data_dir)}

    def subscriptions(self) -> list[str]:
        return []

    async def command(self, topic: str, payload: bytes) -> bool:
        return False
