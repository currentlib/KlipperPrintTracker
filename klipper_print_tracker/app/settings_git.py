"""Settings snapshots: config per job, change summaries and a git history."""
import asyncio
import logging
import re
import subprocess
from pathlib import Path
from posixpath import dirname, join

import aiohttp

from . import calc, gcode

log = logging.getLogger(__name__)

MESSAGE_LINES = 30
VALUE_WIDTH = 40
THUMB_WIDTH = 240
PRESET_IDS = {"process": "print_settings_id", "filament": "filament_settings_id",
              "printer": "printer_settings_id"}
# These restate other keys, a diff on them is noise.
NOISE_KEYS = {"different_settings_to_system"}


def diff_configs(old: dict, new: dict) -> list[dict]:
    keys = sorted((set(old) | set(new)) - NOISE_KEYS)
    return [{"key": k, "old": old.get(k), "new": new.get(k)} for k in keys if old.get(k) != new.get(k)]


def sanitise(name: str) -> str:
    """A preset name as a file name."""
    return re.sub(r"[^\w .@()+-]", "_", name).strip(". ")[:120] or "unnamed"


def short_changes(record: dict) -> list[str]:
    """Keys changed since the closest comparable print."""
    changes = record.get("changes") or {}
    for kind in ("file", "process", "filament"):
        if changes.get(kind):
            return [item["key"] for item in changes[kind]["diff"]]
    return []


def _ini(values: dict) -> str:
    return "".join(f"{k} = {values[k]}\n" for k in sorted(values))


def _read_ini(path: Path) -> dict | None:
    if not path.exists():
        return None
    pairs = (line.split(" = ", 1) for line in path.read_text(encoding="utf-8").splitlines())
    return {p[0]: p[1] if len(p) > 1 else "" for p in pairs}


def _clip(value: str | None) -> str:
    text = "-" if value is None else value
    return text if len(text) <= VALUE_WIDTH else text[:VALUE_WIDTH - 3] + "..."


class GitHistory:
    """A normal repository, one commit per job when the effective config changed."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", "-c", "user.name=Print Tracker", "-c", "user.email=tracker@localhost", *args],
            cwd=self.path, capture_output=True, text=True, check=True)
        return result.stdout.strip()

    def init(self):
        self.path.mkdir(parents=True, exist_ok=True)
        if not (self.path / ".git").exists():
            self._git("init", "-q")

    def commit(self, record: dict, config: dict, preset_values: dict) -> tuple[str | None, dict]:
        """Return (commit sha or None, values that differ from the committed presets)."""
        self.init()
        effective = self.path / "effective.ini"
        old = _read_ini(effective)
        drift, labels = {}, {}
        for kind, presets in preset_values.items():
            for name, values in presets.items():
                path = self.path / "presets" / kind / f"{sanitise(name)}.ini"
                previous = _read_ini(path)
                if previous is not None:
                    diff = diff_configs(previous, values)
                    if diff:
                        drift[f"{kind}/{name}"] = diff
                labels.update({key: name for key in values})
                path.parent.mkdir(parents=True, exist_ok=True)
                if config != old:
                    path.write_text(_ini(values), encoding="utf-8")
        if config == old:
            return None, drift
        effective.write_text(_ini(config), encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", self._message(record, old, config, labels))
        return self._git("rev-parse", "HEAD"), drift

    @staticmethod
    def _message(record: dict, old: dict | None, new: dict, labels: dict) -> str:
        title = f"job {record['job_id']}: {record['filename']} [{record['status']}]"
        if old is None:
            return title
        diff = diff_configs(old, new)
        lines = [f"{labels.get(d['key'], 'effective')}: {d['key']} {_clip(d['old'])} -> {_clip(d['new'])}"
                 for d in diff[:MESSAGE_LINES]]
        if len(diff) > MESSAGE_LINES:
            lines.append(f"... and {len(diff) - MESSAGE_LINES} more")
        return "\n".join([title, "", *lines]) if lines else title


class SettingsHistory:
    def __init__(self, db, moonraker, layouts, data_dir: Path):
        self.db = db
        self.moonraker = moonraker
        self.layouts = layouts
        self.thumbs = Path(data_dir) / "thumbs"
        self.git = GitHistory(Path(data_dir) / "git")

    async def snapshot(self, record: dict):
        """Fill the settings fields of a record. Missing data never stops tracking."""
        record["thumbnail"] = await self._thumbnail(record)
        try:
            parts = await self.moonraker.gcode_parts(record["filename"])
        except (aiohttp.ClientError, OSError, TimeoutError) as err:
            log.warning("Can't read G-code of job %s: %s", record["job_id"], err)
            parts = None
        if parts:
            self._restore_part_names(record, parts[0])
        config = gcode.parse_config(parts[1]) if parts else None
        if config is None:
            record["config_missing"] = True
            return
        head = parts[0]
        record["slicer"], record["slicer_version"] = gcode.parse_slicer(head)
        record["config_hash"] = gcode.config_hash(config)
        self.db.store_config(record["config_hash"], config)
        used = gcode.used_filaments(head)
        record["presets"] = self._presets(config, used)
        record["changes"] = self._changes(record, config)
        layout = await self.layouts.get(record["slicer"], record["slicer_version"])
        values = self._preset_values(config, record["presets"], layout, used)
        record["commit_sha"], record["preset_drift"] = await asyncio.to_thread(
            self.git.commit, record, config, values)

    def _restore_part_names(self, record: dict, head: str):
        originals = gcode.object_names(head)
        if not originals:
            return
        for field in ("printed", "excluded"):
            if field in record:
                record[field] = calc.restore_casing(record[field], originals)
        self.db.adopt_part_names(calc.normalise_name(name) for name in originals)

    @staticmethod
    def _presets(config: dict, used: list[int] | None) -> dict:
        presets = {}
        for kind, key in PRESET_IDS.items():
            names = gcode.split_values(config.get(key, ""))
            if kind == "filament" and used:
                names = [names[i] for i in used if i < len(names)]
            if names:
                presets[kind] = list(dict.fromkeys(names))
        return presets

    @staticmethod
    def _preset_values(config: dict, presets: dict, layout: dict | None, used) -> dict:
        if layout is None:
            return {}
        keys = layout["preset_keys"]
        values: dict[str, dict] = {}
        for kind in ("process", "printer"):
            for name in presets.get(kind, []):
                values[kind] = {name: {k: config[k] for k in keys[kind] if k in config}}
        all_filaments = gcode.split_values(config.get(PRESET_IDS["filament"], ""))
        count = len(all_filaments)
        filament_values = {}
        for index, name in enumerate(all_filaments):
            if name in presets.get("filament", []) and (used is None or index in used):
                filament_values[name] = {k: gcode.filament_value(config[k], index, count)
                                         for k in keys["filament"] if k in config}
        if filament_values:
            values["filament"] = filament_values
        return values

    def _changes(self, record: dict, config: dict) -> dict:
        end = record.get("end_time") or 0
        candidates = {"file": self.db.previous_by_file(record["filename"], end)}
        for kind in ("process", "filament"):
            names = record["presets"].get(kind) or []
            candidates[kind] = self.db.previous_by_preset(kind, names[0], end) if names else None
        changes = {}
        for kind, previous in candidates.items():
            if previous:
                old = self.db.get_config(previous["config_hash"])
                changes[kind] = {"job_id": previous["job_id"], "diff": diff_configs(old, config)}
        return changes

    async def _thumbnail(self, record: dict) -> str | None:
        metadata = record.get("metadata") or {}
        try:
            thumbs = metadata.get("thumbnails") or (
                await self.moonraker.metadata(record["filename"])).get("thumbnails") or []
            if not thumbs:
                return None
            # Moonraker keeps several sizes, the smallest big enough one saves resizing.
            thumbs = sorted(thumbs, key=lambda t: t.get("width", 0))
            best = next((t for t in thumbs if t.get("width", 0) >= THUMB_WIDTH), thumbs[-1])
            path = join(dirname(record["filename"]), best["relative_path"])
            content = await self.moonraker.thumbnail(path)
        except (aiohttp.ClientError, OSError, TimeoutError, KeyError) as err:
            log.debug("No thumbnail for job %s: %s", record["job_id"], err)
            return None
        if not content:
            return None
        self.thumbs.mkdir(parents=True, exist_ok=True)
        name = f"{sanitise(str(record['job_id']))}.png"
        (self.thumbs / name).write_bytes(content)
        return name
