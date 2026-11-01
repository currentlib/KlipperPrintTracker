"""SQLite storage: one row per print plus deduplicated slicer configs."""
import json
import sqlite3
import threading
import time
import zlib
from pathlib import Path

JSON_COLUMNS = ("printed", "excluded", "presets", "changes", "preset_drift")
SORT_COLUMNS = {"date": "end_time", "file": "filename", "status": "status", "parts": "parts",
                "minutes": "print_duration", "grams": "grams", "cost": "total_cost",
                "per_part": "per_part", "spool": "spool"}
JOB_COLUMNS = (
    "job_id", "filename", "status", "start_time", "end_time", "print_duration",
    "planned", "parts", "printed", "excluded", "filament_mm", "grams", "kwh",
    "spool_id", "spool", "price_kg", "energy_cost", "filament_cost", "total_cost",
    "per_part", "wasted_cost", "live_data", "config_hash", "config_missing", "slicer",
    "slicer_version", "presets", "thumbnail", "commit_sha", "changes", "preset_drift",
)
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS configs (hash TEXT PRIMARY KEY, content BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY, filename TEXT, status TEXT, start_time REAL, end_time REAL,
    print_duration REAL, planned INTEGER, parts INTEGER, printed TEXT, excluded TEXT,
    filament_mm REAL, grams REAL, kwh REAL, spool_id INTEGER, spool TEXT, price_kg REAL,
    energy_cost REAL, filament_cost REAL, total_cost REAL, per_part REAL, wasted_cost REAL,
    live_data INTEGER, config_hash TEXT, config_missing INTEGER, slicer TEXT,
    slicer_version TEXT, presets TEXT, thumbnail TEXT, commit_sha TEXT, changes TEXT,
    preset_drift TEXT, event_pending INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS jobs_end ON jobs(end_time);
CREATE TABLE IF NOT EXISTS job_parts (
    job_id TEXT, name TEXT, printed INTEGER, excluded INTEGER, PRIMARY KEY (job_id, name)
);
CREATE TABLE IF NOT EXISTS job_presets (
    job_id TEXT, type TEXT, name TEXT, PRIMARY KEY (job_id, type, name)
);
CREATE INDEX IF NOT EXISTS job_presets_name ON job_presets(type, name);
"""


class Database:
    def __init__(self, path: Path | str):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.lock = threading.Lock()

    def _query(self, sql: str, params=()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, params).fetchall()

    def _write(self, sql: str, params=()):
        with self.lock, self.conn:
            self.conn.execute(sql, params)

    @staticmethod
    def _job(row: sqlite3.Row) -> dict:
        job = dict(row)
        for column in JSON_COLUMNS:
            job[column] = json.loads(job[column]) if job[column] else None
        return job

    # --- meta --------------------------------------------------------

    def _get_meta(self, key: str) -> str | None:
        rows = self._query("SELECT value FROM meta WHERE key = ?", (key,))
        return rows[0]["value"] if rows else None

    def _set_meta(self, key: str, value: str):
        self._write("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))

    def first_start(self) -> float:
        """Time of the very first run. Older jobs are never imported."""
        value = self._get_meta("first_start")
        if value is None:
            value = str(time.time())
            self._set_meta("first_start", value)
        return float(value)

    def get_active(self) -> dict | None:
        value = self._get_meta("active")
        return json.loads(value) if value else None

    def set_active(self, active: dict | None):
        self._set_meta("active", json.dumps(active) if active else "")

    # --- jobs --------------------------------------------------------

    def has_job(self, job_id: str) -> bool:
        return bool(self._query("SELECT 1 FROM jobs WHERE job_id = ?", (job_id,)))

    def save_job(self, record: dict):
        values = [json.dumps(record.get(c), ensure_ascii=False) if c in JSON_COLUMNS
                  and record.get(c) is not None else record.get(c) for c in JOB_COLUMNS]
        marks = ", ".join("?" * len(JOB_COLUMNS))
        printed, excluded = record.get("printed") or {}, record.get("excluded") or {}
        with self.lock, self.conn:
            self.conn.execute(f"INSERT OR IGNORE INTO jobs ({', '.join(JOB_COLUMNS)}) VALUES ({marks})", values)
            for name in set(printed) | set(excluded):
                self.conn.execute("INSERT OR IGNORE INTO job_parts VALUES (?, ?, ?, ?)",
                                  (record["job_id"], name, printed.get(name, 0), excluded.get(name, 0)))
            for kind, names in (record.get("presets") or {}).items():
                for name in names:
                    self.conn.execute("INSERT OR IGNORE INTO job_presets VALUES (?, ?, ?)",
                                      (record["job_id"], kind, name))

    def get_job(self, job_id: str) -> dict | None:
        rows = self._query("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        return self._job(rows[0]) if rows else None

    def jobs(self, file=None, status=None, preset=None, spool=None, date_from=None,
             date_to=None, limit=100, offset=0, sort="date", descending=True) -> tuple[list[dict], int]:
        where, params = [], []
        if file:
            where.append("filename LIKE ?")
            params.append(f"%{file}%")
        if status:
            where.append("status = ?")
            params.append(status)
        if preset:
            where.append("job_id IN (SELECT job_id FROM job_presets WHERE name = ?)")
            params.append(preset)
        if spool:
            where.append("spool = ?")
            params.append(spool)
        if date_from is not None:
            where.append("end_time >= ?")
            params.append(date_from)
        if date_to is not None:
            where.append("end_time < ?")
            params.append(date_to)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        total = self._query(f"SELECT COUNT(*) n FROM jobs {clause}", params)[0]["n"]
        order = f"{SORT_COLUMNS.get(sort, 'end_time')} {'DESC' if descending else 'ASC'}"
        rows = self._query(f"SELECT * FROM jobs {clause} ORDER BY {order}, end_time DESC LIMIT ? OFFSET ?",
                           [*params, limit, offset])
        return [self._job(r) for r in rows], total

    def previous_by_file(self, filename: str, before: float) -> dict | None:
        rows = self._query("""SELECT * FROM jobs WHERE filename = ? AND end_time < ?
                              AND config_hash IS NOT NULL ORDER BY end_time DESC LIMIT 1""",
                           (filename, before))
        return self._job(rows[0]) if rows else None

    def previous_by_preset(self, kind: str, name: str, before: float) -> dict | None:
        rows = self._query("""SELECT j.* FROM jobs j JOIN job_presets p USING (job_id)
                              WHERE p.type = ? AND p.name = ? AND j.end_time < ?
                              AND j.config_hash IS NOT NULL
                              ORDER BY j.end_time DESC LIMIT 1""", (kind, name, before))
        return self._job(rows[0]) if rows else None

    def preset_jobs(self, kind: str, name: str) -> list[dict]:
        rows = self._query("""SELECT j.* FROM jobs j JOIN job_presets p USING (job_id)
                              WHERE p.type = ? AND p.name = ? AND j.config_hash IS NOT NULL
                              ORDER BY j.end_time""", (kind, name))
        return [self._job(r) for r in rows]

    def part_jobs(self, name: str) -> list[dict]:
        rows = self._query("""SELECT j.*, p.printed part_printed, p.excluded part_excluded
                              FROM jobs j JOIN job_parts p USING (job_id)
                              WHERE p.name = ? ORDER BY j.end_time""", (name,))
        return [self._job(r) for r in rows]

    def pending_events(self) -> list[dict]:
        rows = self._query("SELECT * FROM jobs WHERE event_pending = 1 ORDER BY end_time")
        return [self._job(r) for r in rows]

    def mark_event_sent(self, job_id: str):
        self._write("UPDATE jobs SET event_pending = 0 WHERE job_id = ?", (job_id,))

    # --- configs -----------------------------------------------------

    def store_config(self, config_hash: str, config: dict):
        blob = zlib.compress(json.dumps(config, ensure_ascii=False).encode())
        self._write("INSERT OR IGNORE INTO configs VALUES (?, ?)", (config_hash, blob))

    def get_config(self, config_hash: str | None) -> dict | None:
        rows = self._query("SELECT content FROM configs WHERE hash = ?", (config_hash,))
        return json.loads(zlib.decompress(rows[0]["content"])) if rows else None

    # --- statistics --------------------------------------------------

    def stats(self) -> dict:
        row = self._query("""SELECT COUNT(*) total,
            COALESCE(SUM(status = 'completed'), 0) completed,
            COALESCE(SUM(status = 'cancelled'), 0) cancelled,
            COALESCE(SUM(status = 'error'), 0) failed,
            COALESCE(SUM(parts), 0) parts, COALESCE(SUM(grams), 0) grams,
            COALESCE(SUM(kwh), 0) kwh, COALESCE(SUM(total_cost), 0) total_cost,
            COALESCE(SUM(wasted_cost), 0) wasted_cost FROM jobs""")[0]
        stats = dict(row)
        stats["success_rate"] = round(100 * stats["completed"] / stats["total"], 1) if stats["total"] else 0
        stats["filament_kg"] = round(stats.pop("grams") / 1000, 3)
        stats["kwh"] = round(stats["kwh"], 3)
        stats["total_cost"] = round(stats["total_cost"], 2)
        stats["wasted_cost"] = round(stats["wasted_cost"], 2)
        return stats

    def top_parts(self, limit: int = 10) -> list[dict]:
        rows = self._query("""SELECT name, SUM(printed) count FROM job_parts GROUP BY name
                              HAVING count > 0 ORDER BY count DESC, name LIMIT ?""", (limit,))
        return [dict(r) for r in rows]

    def top_excluded(self, limit: int = 10) -> list[dict]:
        rows = self._query("""SELECT name, SUM(excluded) count,
                              ROUND(100.0 * SUM(excluded) / SUM(excluded + printed)) rate
                              FROM job_parts GROUP BY name HAVING count > 0
                              ORDER BY count DESC, name LIMIT ?""", (limit,))
        return [dict(r) for r in rows]

    def facets(self) -> dict:
        """Values for the filters of the prints list."""
        presets = self._query("SELECT DISTINCT type, name FROM job_presets ORDER BY type, name")
        spools = self._query("SELECT DISTINCT spool FROM jobs WHERE spool IS NOT NULL ORDER BY spool")
        return {"presets": [dict(p) for p in presets], "spools": [s["spool"] for s in spools]}

    def distinct_parts(self) -> int:
        return self._query("SELECT COUNT(DISTINCT name) n FROM job_parts WHERE printed > 0")[0]["n"]

    def close(self):
        self.conn.close()
