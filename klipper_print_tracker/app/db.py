"""SQLite storage: one row per print plus deduplicated slicer configs."""
import json
import sqlite3
import threading
import time
import zlib
from collections.abc import Callable, Iterable
from pathlib import Path

from . import gcode
from .calc import normalise_name
from .config import DEFAULT_PRINTER
from .ratings import DEFAULT_TAGS

JSON_COLUMNS = ("printed", "excluded", "presets", "changes", "preset_drift", "issues", "spool_check")
SORT_COLUMNS = {"date": "end_time", "file": "filename", "status": "status", "parts": "parts",
                "minutes": "print_duration", "grams": "grams", "cost": "total_cost",
                "per_part": "per_part", "spool": "spool"}
JOB_COLUMNS = (
    "printer_id", "job_id", "filename", "status", "start_time", "end_time", "print_duration",
    "planned", "parts", "printed", "excluded", "filament_mm", "grams", "kwh",
    "spool_id", "spool", "price_kg", "energy_cost", "filament_cost", "total_cost",
    "per_part", "wasted_cost", "live_data", "config_hash", "config_missing", "slicer",
    "slicer_version", "presets", "thumbnail", "commit_sha", "changes", "preset_drift",
    "material", "rating", "issues", "failure_reason", "note", "rated_at", "spool_check", "progress",
    "current_layer", "total_layer", "chamber_temp", "interruption",
)
EDITABLE_COLUMNS = {"rating", "issues", "failure_reason", "note", "rated_at", "calibration"}
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


def _rebuild(conn, table: str, create: str, columns: str):
    conn.execute(f"ALTER TABLE {table} RENAME TO {table}_old")
    conn.execute(create)
    conn.execute(f"INSERT INTO {table} (printer_id, {columns}) SELECT '{DEFAULT_PRINTER}', {columns} FROM {table}_old")
    conn.execute(f"DROP TABLE {table}_old")


def migrate_v2_printers(conn):
    """Every print belongs to a printer, job ids are only unique per printer."""
    columns = [row[1] for row in conn.execute("PRAGMA table_info(jobs)")]
    conn.execute("DROP INDEX IF EXISTS jobs_end")
    conn.execute("DROP INDEX IF EXISTS job_presets_name")
    _rebuild(conn, "jobs", """CREATE TABLE jobs (
        printer_id TEXT NOT NULL, job_id TEXT NOT NULL, filename TEXT, status TEXT, start_time REAL,
        end_time REAL, print_duration REAL, planned INTEGER, parts INTEGER, printed TEXT, excluded TEXT,
        filament_mm REAL, grams REAL, kwh REAL, spool_id INTEGER, spool TEXT, price_kg REAL,
        energy_cost REAL, filament_cost REAL, total_cost REAL, per_part REAL, wasted_cost REAL,
        live_data INTEGER, config_hash TEXT, config_missing INTEGER, slicer TEXT,
        slicer_version TEXT, presets TEXT, thumbnail TEXT, commit_sha TEXT, changes TEXT,
        preset_drift TEXT, event_pending INTEGER DEFAULT 1, PRIMARY KEY (printer_id, job_id))""",
             ", ".join(columns))
    _rebuild(conn, "job_parts", """CREATE TABLE job_parts (
        printer_id TEXT NOT NULL, job_id TEXT, name TEXT, printed INTEGER, excluded INTEGER,
        PRIMARY KEY (printer_id, job_id, name))""", "job_id, name, printed, excluded")
    _rebuild(conn, "job_presets", """CREATE TABLE job_presets (
        printer_id TEXT NOT NULL, job_id TEXT, type TEXT, name TEXT,
        PRIMARY KEY (printer_id, job_id, type, name))""", "job_id, type, name")
    conn.execute("CREATE INDEX jobs_end ON jobs(end_time)")
    conn.execute("CREATE INDEX job_presets_name ON job_presets(type, name)")
    conn.execute(f"UPDATE meta SET key = 'active:{DEFAULT_PRINTER}' WHERE key = 'active'")


def migrate_v3_results(conn):
    """Rating, failure details and spool check per print, material from the stored configs."""
    for definition in ("material TEXT", "rating TEXT", "issues TEXT", "failure_reason TEXT", "note TEXT",
                       "rated_at REAL", "spool_check TEXT", "progress REAL", "current_layer INTEGER",
                       "total_layer INTEGER", "chamber_temp REAL", "interruption TEXT"):
        conn.execute(f"ALTER TABLE jobs ADD COLUMN {definition}")
    conn.execute("CREATE TABLE tags (name TEXT PRIMARY KEY, position INTEGER)")
    conn.executemany("INSERT INTO tags VALUES (?, ?)", [(tag, i) for i, tag in enumerate(DEFAULT_TAGS)])
    for printer_id, job_id, presets, config_hash in conn.execute(
            "SELECT printer_id, job_id, presets, config_hash FROM jobs WHERE config_hash IS NOT NULL").fetchall():
        row = conn.execute("SELECT content FROM configs WHERE hash = ?", (config_hash,)).fetchone()
        if row:
            names = json.loads(presets or "{}").get("filament") or [None]
            material = gcode.material(json.loads(zlib.decompress(row[0])), names[0])
            conn.execute("UPDATE jobs SET material = ? WHERE printer_id = ? AND job_id = ?",
                         (material, printer_id, job_id))


MIGRATIONS = [migrate_v2_printers, migrate_v3_results]


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self._migrate()
        if not self._get_meta("part_names_fixed"):
            self._rename_parts(normalise_name)
            self._set_meta("part_names_fixed", "1")

    def _migrate(self):
        """Versioned steps in PRAGMA user_version, schema version 1 is SCHEMA itself."""
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        existing = self.conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'jobs'").fetchone()
        pending = MIGRATIONS[max(version - 1, 0):]
        if existing and pending:
            backup = self.path.with_name(f"{self.path.name}.pre-v{max(version, 1) + 1}")
            if not backup.exists():
                target = sqlite3.connect(backup)
                self.conn.backup(target)
                target.close()
        self.conn.executescript(SCHEMA)
        for number, migration in enumerate(pending, start=max(version, 1) + 1):
            with self.conn:
                migration(self.conn)
                self.conn.execute(f"PRAGMA user_version = {number}")

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

    def get_active(self, printer_id: str = DEFAULT_PRINTER) -> dict | None:
        value = self._get_meta(f"active:{printer_id}")
        return json.loads(value) if value else None

    def set_active(self, active: dict | None, printer_id: str = DEFAULT_PRINTER):
        self._set_meta(f"active:{printer_id}", json.dumps(active) if active else "")

    # --- jobs --------------------------------------------------------

    def has_job(self, job_id: str, printer_id: str = DEFAULT_PRINTER) -> bool:
        return bool(self._query("SELECT 1 FROM jobs WHERE printer_id = ? AND job_id = ?", (printer_id, job_id)))

    def save_job(self, record: dict):
        record.setdefault("printer_id", DEFAULT_PRINTER)
        printer = record["printer_id"]
        values = [json.dumps(record.get(c), ensure_ascii=False) if c in JSON_COLUMNS
                  and record.get(c) is not None else record.get(c) for c in JOB_COLUMNS]
        marks = ", ".join("?" * len(JOB_COLUMNS))
        printed, excluded = record.get("printed") or {}, record.get("excluded") or {}
        with self.lock, self.conn:
            self.conn.execute(f"INSERT OR IGNORE INTO jobs ({', '.join(JOB_COLUMNS)}) VALUES ({marks})", values)
            for name in set(printed) | set(excluded):
                self.conn.execute("INSERT OR IGNORE INTO job_parts VALUES (?, ?, ?, ?, ?)",
                                  (printer, record["job_id"], name, printed.get(name, 0), excluded.get(name, 0)))
            for kind, names in (record.get("presets") or {}).items():
                for name in names:
                    self.conn.execute("INSERT OR IGNORE INTO job_presets VALUES (?, ?, ?, ?)",
                                      (printer, record["job_id"], kind, name))

    def get_job(self, job_id: str, printer_id: str = DEFAULT_PRINTER) -> dict | None:
        rows = self._query("SELECT * FROM jobs WHERE printer_id = ? AND job_id = ?", (printer_id, job_id))
        return self._job(rows[0]) if rows else None

    def find_job(self, job_id: str) -> dict | None:
        rows = self._query("SELECT * FROM jobs WHERE job_id = ? ORDER BY printer_id LIMIT 1", (job_id,))
        return self._job(rows[0]) if rows else None

    def update_job(self, job_id: str, printer_id: str = DEFAULT_PRINTER, **fields):
        unknown = set(fields) - EDITABLE_COLUMNS
        if unknown:
            raise ValueError(f"Not editable: {unknown}")
        columns = ", ".join(f"{name} = ?" for name in fields)
        values = [json.dumps(v, ensure_ascii=False) if name in JSON_COLUMNS else v for name, v in fields.items()]
        self._write(f"UPDATE jobs SET {columns} WHERE printer_id = ? AND job_id = ?", (*values, printer_id, job_id))

    def tags(self) -> list[str]:
        return [row["name"] for row in self._query("SELECT name FROM tags ORDER BY position, name")]

    def set_tags(self, names: list[str]):
        with self.lock, self.conn:
            self.conn.execute("DELETE FROM tags")
            self.conn.executemany("INSERT OR IGNORE INTO tags VALUES (?, ?)", [(n, i) for i, n in enumerate(names)])

    def jobs(self, printer=None, file=None, status=None, preset=None, spool=None, date_from=None,
             date_to=None, rating=None, limit=100, offset=0, sort="date", descending=True) -> tuple[list[dict], int]:
        where, params = [], []
        if printer:
            where.append("printer_id = ?")
            params.append(printer)
        if file:
            where.append("filename LIKE ?")
            params.append(f"%{file}%")
        if status:
            where.append("status = ?")
            params.append(status)
        if preset:
            where.append("(printer_id, job_id) IN (SELECT printer_id, job_id FROM job_presets WHERE name = ?)")
            params.append(preset)
        if spool:
            where.append("spool = ?")
            params.append(spool)
        if rating == "none":
            where.append("rating IS NULL")
        elif rating:
            where.append("rating = ?")
            params.append(rating)
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

    def previous_by_file(self, filename: str, before: float, printer: str = DEFAULT_PRINTER) -> dict | None:
        rows = self._query("""SELECT * FROM jobs WHERE printer_id = ? AND filename = ? AND end_time < ?
                              AND config_hash IS NOT NULL ORDER BY end_time DESC LIMIT 1""",
                           (printer, filename, before))
        return self._job(rows[0]) if rows else None

    def previous_by_preset(self, kind: str, name: str, before: float,
                           printer: str = DEFAULT_PRINTER) -> dict | None:
        rows = self._query("""SELECT j.* FROM jobs j JOIN job_presets p USING (printer_id, job_id)
                              WHERE j.printer_id = ? AND p.type = ? AND p.name = ? AND j.end_time < ?
                              AND j.config_hash IS NOT NULL
                              ORDER BY j.end_time DESC LIMIT 1""", (printer, kind, name, before))
        return self._job(rows[0]) if rows else None

    def preset_jobs(self, kind: str, name: str, printer: str | None = None) -> list[dict]:
        rows = self._query("""SELECT j.* FROM jobs j JOIN job_presets p USING (printer_id, job_id)
                              WHERE p.type = ? AND p.name = ? AND j.config_hash IS NOT NULL
                              AND (? IS NULL OR j.printer_id = ?)
                              ORDER BY j.end_time""", (kind, name, printer, printer))
        return [self._job(r) for r in rows]

    def part_jobs(self, name: str) -> list[dict]:
        rows = self._query("""SELECT j.*, p.printed part_printed, p.excluded part_excluded
                              FROM jobs j JOIN job_parts p USING (printer_id, job_id)
                              WHERE p.name = ? ORDER BY j.end_time""", (name,))
        return [self._job(r) for r in rows]

    def _rename_parts(self, rename: Callable[[str], str]):
        """Apply a new name to every stored part, parts that end up the same are merged."""

        def renamed(names: dict) -> dict:
            result: dict[str, int] = {}
            for name, count in names.items():
                result[rename(name)] = result.get(rename(name), 0) + count
            return result

        for row in self._query("SELECT printer_id, job_id, printed, excluded FROM jobs"):
            old_printed = json.loads(row["printed"] or "{}")
            old_excluded = json.loads(row["excluded"] or "{}")
            printed, excluded = renamed(old_printed), renamed(old_excluded)
            if printed == old_printed and excluded == old_excluded:
                continue
            key = (row["printer_id"], row["job_id"])
            with self.lock, self.conn:
                self.conn.execute("UPDATE jobs SET printed = ?, excluded = ? WHERE printer_id = ? AND job_id = ?",
                                  (json.dumps(printed, ensure_ascii=False),
                                   json.dumps(excluded, ensure_ascii=False), *key))
                self.conn.execute("DELETE FROM job_parts WHERE printer_id = ? AND job_id = ?", key)
                for name in set(printed) | set(excluded):
                    self.conn.execute("INSERT INTO job_parts VALUES (?, ?, ?, ?, ?)",
                                      (*key, name, printed.get(name, 0), excluded.get(name, 0)))

    def adopt_part_names(self, names: Iterable[str]):
        """Older records that only know the upper case name get the real one."""
        wanted = {name.upper(): name for name in names}
        stored = {row["name"] for row in self._query("SELECT DISTINCT name FROM job_parts")}
        if any(wanted.get(name.upper(), name) != name for name in stored):
            self._rename_parts(lambda name: wanted.get(name.upper(), name))

    def pending_events(self) -> list[dict]:
        rows = self._query("SELECT * FROM jobs WHERE event_pending = 1 ORDER BY end_time")
        return [self._job(r) for r in rows]

    def mark_event_sent(self, job_id: str, printer_id: str = DEFAULT_PRINTER):
        self._write("UPDATE jobs SET event_pending = 0 WHERE printer_id = ? AND job_id = ?", (printer_id, job_id))

    # --- configs -----------------------------------------------------

    def store_config(self, config_hash: str, config: dict):
        blob = zlib.compress(json.dumps(config, ensure_ascii=False).encode())
        self._write("INSERT OR IGNORE INTO configs VALUES (?, ?)", (config_hash, blob))

    def get_config(self, config_hash: str | None) -> dict | None:
        rows = self._query("SELECT content FROM configs WHERE hash = ?", (config_hash,))
        return json.loads(zlib.decompress(rows[0]["content"])) if rows else None

    # --- statistics --------------------------------------------------

    def stats(self, printer: str | None = None) -> dict:
        row = self._query("""SELECT COUNT(*) total,
            COALESCE(SUM(status = 'completed'), 0) completed,
            COALESCE(SUM(status = 'cancelled'), 0) cancelled,
            COALESCE(SUM(status = 'error'), 0) failed,
            COALESCE(SUM(parts), 0) parts, COALESCE(SUM(grams), 0) grams,
            COALESCE(SUM(kwh), 0) kwh, COALESCE(SUM(total_cost), 0) total_cost,
            COALESCE(SUM(wasted_cost), 0) wasted_cost, COALESCE(SUM(rating IS NULL), 0) unrated FROM jobs
            WHERE ? IS NULL OR printer_id = ?""", (printer, printer))[0]
        stats = dict(row)
        stats["success_rate"] = round(100 * stats["completed"] / stats["total"], 1) if stats["total"] else 0
        stats["filament_kg"] = round(stats.pop("grams") / 1000, 3)
        stats["kwh"] = round(stats["kwh"], 3)
        stats["total_cost"] = round(stats["total_cost"], 2)
        stats["wasted_cost"] = round(stats["wasted_cost"], 2)
        return stats

    def top_parts(self, limit: int = 10, printer: str | None = None) -> list[dict]:
        rows = self._query("""SELECT name, SUM(printed) count FROM job_parts
                              WHERE ? IS NULL OR printer_id = ? GROUP BY name
                              HAVING count > 0 ORDER BY count DESC, name LIMIT ?""", (printer, printer, limit))
        return [dict(r) for r in rows]

    def top_excluded(self, limit: int = 10, printer: str | None = None) -> list[dict]:
        rows = self._query("""SELECT name, SUM(excluded) count,
                              ROUND(100.0 * SUM(excluded) / SUM(excluded + printed)) rate
                              FROM job_parts WHERE ? IS NULL OR printer_id = ? GROUP BY name HAVING count > 0
                              ORDER BY count DESC, name LIMIT ?""", (printer, printer, limit))
        return [dict(r) for r in rows]

    def facets(self, printer: str | None = None) -> dict:
        """Values for the filters of the prints list."""
        presets = self._query("""SELECT DISTINCT type, name FROM job_presets
                                 WHERE ? IS NULL OR printer_id = ? ORDER BY type, name""", (printer, printer))
        spools = self._query("""SELECT DISTINCT spool FROM jobs WHERE spool IS NOT NULL
                                AND (? IS NULL OR printer_id = ?) ORDER BY spool""", (printer, printer))
        return {"presets": [dict(p) for p in presets], "spools": [s["spool"] for s in spools]}

    def distinct_parts(self, printer: str | None = None) -> int:
        return self._query("""SELECT COUNT(DISTINCT name) n FROM job_parts WHERE printed > 0
                              AND (? IS NULL OR printer_id = ?)""", (printer, printer))[0]["n"]

    def close(self):
        self.conn.close()
