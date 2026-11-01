import asyncio

import aiohttp
import pytest

from app import tracker as tracker_module
from app.config import Options
from app.db import Database
from app.moonraker import Moonraker
from app.tracker import Tracker
from fake_moonraker import FakeMoonraker, settle

BRACKETS = [{"name": f"Bracket.stl_id_0_copy_{i}"} for i in range(4)] + [{"name": "Clip.stl_id_1_copy_0"}]
META = {"filament_weight_total": 100, "filament_total": 1000}


class FakeSupervisor:
    def __init__(self, value=10.0):
        self.value = value

    async def energy(self, entity):
        return self.value

    async def fire_event(self, event_type, data):
        return True


class Listener:
    def __init__(self):
        self.finished = []
        self.currents = []

    async def current(self, printer_id, active):
        self.currents.append(active)

    async def job_finished(self, record):
        self.finished.append(record)


class Rig:
    """A tracker wired to a fake Moonraker, restartable like the real add-on."""

    def __init__(self, tmp_path):
        self.fake = FakeMoonraker()
        self.db_path = tmp_path / "t.db"
        self.options = Options(moonraker_url="", energy_sensor="sensor.e", electricity_price=4.32,
                               default_filament_price=800)
        self.supervisor = FakeSupervisor()
        self.listener = Listener()
        self.tasks = []

    async def start(self, url=None):
        self.url = url or await self.fake.start()
        self.session = aiohttp.ClientSession()
        self.db = Database(self.db_path)
        self.moonraker = Moonraker(self.url, self.session)
        self.tracker = Tracker(self.options, self.db, self.moonraker, self.supervisor,
                               listeners=[self.listener])
        self.moonraker.on_status = self.tracker.on_status
        self.moonraker.on_history = self.tracker.on_history
        connections = self.fake.connections
        self.task = asyncio.create_task(self.moonraker.run())
        await settle(lambda: self.moonraker.connected and self.fake.connections > connections)

    async def stop_addon(self):
        self.task.cancel()
        await self.session.close()
        self.db.close()
        await self.fake.drop_clients()

    async def close(self):
        await self.stop_addon()
        await self.fake.stop()

    async def start_print(self, job_id="000001", filename="plate.gcode"):
        job = await self.fake.add_job(job_id, filename, metadata=META)
        await self.fake.emit({"print_stats": {"state": "printing", "filename": filename}})
        await settle(lambda: self.tracker.active is not None)
        await self.fake.emit({"exclude_object": {"objects": BRACKETS}})
        await settle(lambda: len(self.tracker.active["objects"]) == 5)
        return job


@pytest.fixture
async def rig(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker_module, "FINISH_DELAY", 0.01)
    rig = Rig(tmp_path)
    await rig.start()
    yield rig
    await rig.close()


async def test_start_exclude_complete(rig):
    job = await rig.start_print()
    assert rig.tracker.active["job_id"] == "000001"
    assert rig.tracker.active["start_kwh"] == 10.0
    await rig.fake.emit({"exclude_object": {"excluded_objects": ["Bracket.stl_id_0_copy_3"]}})
    await settle(lambda: rig.tracker.active["excluded"])
    rig.supervisor.value = 10.5
    await rig.fake.finish_job(job, "completed", filament_used=1000, print_duration=3600)
    await rig.fake.emit({"print_stats": {"state": "complete"},
                         "exclude_object": {"objects": [], "excluded_objects": []}})
    await settle(lambda: rig.listener.finished)
    rec = rig.db.get_job("000001")
    assert rec["status"] == "completed"
    assert rec["printed"] == {"Bracket": 3, "Clip": 1}
    assert rec["excluded"] == {"Bracket": 1}
    assert rec["parts"] == 4 and rec["planned"] == 5
    assert rec["grams"] == 100 and rec["kwh"] == 0.5
    assert rec["filament_cost"] == 80 and rec["energy_cost"] == 2.16
    assert rec["per_part"] == 20.54 and rec["wasted_cost"] == 0
    assert rec["live_data"] == 1
    assert rig.tracker.active is None and rig.db.get_active() is None
    assert rig.listener.currents[-1] is None
    assert len(rig.listener.finished) == 1


async def test_start_cancel(rig):
    job = await rig.start_print()
    await rig.fake.finish_job(job, "cancelled", filament_used=500)
    await rig.fake.emit({"print_stats": {"state": "cancelled"}})
    await settle(lambda: rig.listener.finished)
    rec = rig.db.get_job("000001")
    assert rec["status"] == "cancelled"
    assert rec["parts"] == 0 and rec["printed"] == {} and rec["planned"] == 5
    assert rec["grams"] == 50
    assert rec["wasted_cost"] == rec["total_cost"] > 0


async def test_state_jumps_to_standby(rig):
    job = await rig.start_print()
    await rig.fake.emit({"print_stats": {"state": "standby"}})
    await rig.fake.finish_job(job, "klippy_shutdown")
    await settle(lambda: rig.listener.finished)
    assert rig.db.get_job("000001")["status"] == "error"


async def test_pause_is_not_a_new_print(rig):
    await rig.start_print()
    first = rig.tracker.active
    await rig.fake.emit({"print_stats": {"state": "paused"}})
    await settle(lambda: rig.tracker.state == "paused")
    await rig.fake.emit({"print_stats": {"state": "printing"}})
    await settle(lambda: rig.tracker.state == "printing")
    assert rig.tracker.active is first


async def test_restart_mid_print_keeps_live_data(rig):
    job = await rig.start_print()
    await rig.fake.emit({"exclude_object": {"excluded_objects": ["Clip.stl_id_1_copy_0"]}})
    await settle(lambda: rig.tracker.active["excluded"])
    await rig.stop_addon()
    await rig.fake.finish_job(job, "completed", filament_used=1000)
    rig.fake.status["print_stats"]["state"] = "complete"
    await rig.start(rig.url)
    await settle(lambda: rig.listener.finished)
    rec = rig.db.get_job("000001")
    assert rec["printed"] == {"Bracket": 4} and rec["excluded"] == {"Clip": 1}
    assert rec["live_data"] == 1


async def test_first_start_mid_print_is_best_effort(rig):
    await rig.stop_addon()
    rig.db_path.unlink()
    await rig.fake.add_job("000002", "late.gcode", metadata=META)
    rig.fake.status["print_stats"].update(state="printing", filename="late.gcode")
    await rig.start(rig.url)
    assert rig.tracker.active["live"] is False and rig.tracker.active["start_kwh"] is None


async def test_reconcile_adds_missing_job_without_live_data(rig):
    job = await rig.fake.add_job("000003", "missed.gcode", metadata=META)
    await rig.fake.finish_job(job, "completed", filament_used=1000)
    assert await rig.tracker.reconcile() == 1
    rec = rig.db.get_job("000003")
    assert rec["live_data"] == 0 and rec["kwh"] is None
    assert await rig.tracker.reconcile() == 0


async def test_no_backfill_of_old_jobs(rig):
    job = await rig.fake.add_job("000000", "old.gcode")
    job.update(status="completed", end_time=rig.tracker.first_start - 100)
    assert await rig.tracker.reconcile() == 0
    assert not rig.db.has_job("000000")


async def test_finished_notification_and_state_finalise_once(rig):
    job = await rig.start_print()
    await rig.fake.finish_job(job, "completed", filament_used=1000)
    await rig.fake.emit({"print_stats": {"state": "complete"}})
    await settle(lambda: rig.listener.finished)
    await rig.tracker.reconcile()
    await asyncio.sleep(0.05)
    assert len(rig.listener.finished) == 1


async def test_spool_price_used_and_fallback(rig):
    rig.fake.spool_id = 7
    rig.fake.spools[7] = {"price": 500, "initial_weight": 1000, "filament": {"name": "PETG"}}
    job = await rig.fake.add_job("000004", "a.gcode", metadata=META)
    await rig.fake.finish_job(job, "completed", filament_used=1000)
    await rig.tracker.reconcile()
    rec = rig.db.get_job("000004")
    assert rec["spool"] == "PETG" and rec["price_kg"] == 500 and rec["filament_cost"] == 50
    rig.fake.spools[7] = {"filament": {"name": "PETG"}}
    job = await rig.fake.add_job("000005", "b.gcode", metadata=META)
    await rig.fake.finish_job(job, "completed", filament_used=1000)
    await rig.tracker.reconcile()
    assert rig.db.get_job("000005")["price_kg"] == 800


async def test_missing_energy_sensor(rig):
    rig.supervisor.value = None
    job = await rig.start_print()
    await rig.fake.finish_job(job, "completed", filament_used=1000)
    await rig.fake.emit({"print_stats": {"state": "complete"}})
    await settle(lambda: rig.listener.finished)
    rec = rig.db.get_job("000001")
    assert rec["kwh"] is None and rec["energy_cost"] == 0 and rec["filament_cost"] == 80


async def test_reconnect_resubscribes(rig):
    await rig.fake.drop_clients()
    await settle(lambda: rig.fake.connections == 2, timeout=5)


def test_existing_part_names_are_fixed_once(tmp_path):
    path = tmp_path / "old.db"
    db = Database(path)
    db.save_job({"job_id": "1", "filename": "a", "status": "completed", "end_time": 1.0, "parts": 2,
                 "printed": {"SHOERACK.STL_2_ID_0_COPY_0": 1, "SHOERACK.STL_2_ID_1_COPY_0": 1},
                 "excluded": {"CLIP.STL_ID_0_COPY_0": 1}})
    db._query("SELECT 1")
    db._write("DELETE FROM meta WHERE key = 'part_names_fixed'")
    db.close()
    db = Database(path)
    assert db.get_job("1")["printed"] == {"SHOERACK": 2}
    assert db.get_job("1")["excluded"] == {"CLIP": 1}
    assert db.top_parts() == [{"name": "SHOERACK", "count": 2}]
    assert db.top_excluded()[0]["name"] == "CLIP"
    db.close()


async def test_stats_and_tops(rig):
    job = await rig.start_print()
    await rig.fake.emit({"exclude_object": {"excluded_objects": ["Bracket.stl_id_0_copy_3"]}})
    await settle(lambda: rig.tracker.active["excluded"])
    await rig.fake.finish_job(job, "completed", filament_used=1000)
    await rig.fake.emit({"print_stats": {"state": "complete"}})
    await settle(lambda: rig.listener.finished)
    stats = rig.db.stats()
    assert stats["total"] == stats["completed"] == 1 and stats["success_rate"] == 100
    assert stats["parts"] == 4 and stats["filament_kg"] == 0.1
    assert rig.db.top_parts()[0] == {"name": "Bracket", "count": 3}
    assert rig.db.top_excluded()[0] == {"name": "Bracket", "count": 1, "rate": 25.0}
    jobs, total = rig.db.jobs(status="completed", file="plate")
    assert total == 1 and jobs[0]["job_id"] == "000001"
    assert rig.db.jobs(status="error")[1] == 0


def test_old_database_is_migrated(tmp_path):
    import sqlite3

    from app.db import SCHEMA
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO jobs (job_id, filename, status, end_time, printed, excluded) "
                 "VALUES ('000001', 'a.gcode', 'completed', 5, '{\"Clip\": 1}', '{}')")
    conn.execute("INSERT INTO job_parts VALUES ('000001', 'Clip', 1, 0)")
    conn.execute("INSERT INTO job_presets VALUES ('000001', 'process', 'Draft')")
    conn.execute("INSERT INTO meta VALUES ('active', '{\"filename\": \"b.gcode\"}')")
    conn.commit()
    conn.close()

    db = Database(path)
    assert db.get_job("000001")["printer_id"] == "printer1"
    assert db.get_active("printer1") == {"filename": "b.gcode"}
    assert db.top_parts(printer="printer1") == [{"name": "Clip", "count": 1}]
    assert db.jobs(preset="Draft")[1] == 1
    assert (tmp_path / "old.db.pre-v2").exists()
    version = db.conn.execute("PRAGMA user_version").fetchone()[0]
    db.close()

    again = Database(path)
    assert again.conn.execute("PRAGMA user_version").fetchone()[0] == version
    assert again.get_job("000001")["filename"] == "a.gcode"
    again.close()


def test_same_job_id_on_two_printers(tmp_path):
    db = Database(tmp_path / "t.db")
    for printer in ("printer1", "printer2"):
        db.save_job({"printer_id": printer, "job_id": "000001", "filename": printer, "status": "completed",
                     "end_time": 1.0, "printed": {"Clip": 1}, "parts": 1})
    assert db.stats()["total"] == 2 and db.stats("printer2")["total"] == 1
    assert db.get_job("000001", "printer2")["filename"] == "printer2"
    assert db.top_parts() == [{"name": "Clip", "count": 2}]
    assert db.top_parts(printer="printer1") == [{"name": "Clip", "count": 1}]
    db.close()


async def test_two_printers_stay_apart(tmp_path, monkeypatch):
    from app.config import PrinterOptions
    monkeypatch.setattr(tracker_module, "FINISH_DELAY", 0.01)
    db = Database(tmp_path / "t.db")
    fakes = [FakeMoonraker(), FakeMoonraker()]
    options = Options(default_filament_price=800)
    async with aiohttp.ClientSession() as session:
        tasks, trackers = [], []
        for index, fake in enumerate(fakes):
            printer = PrinterOptions(f"p{index}", f"P{index}", await fake.start())
            moonraker = Moonraker(printer.moonraker_url, session)
            tracker = Tracker(options, db, moonraker, FakeSupervisor(), printer=printer)
            moonraker.on_status, moonraker.on_history = tracker.on_status, tracker.on_history
            tasks.append(asyncio.create_task(moonraker.run()))
            trackers.append(tracker)
        await settle(lambda: all(t.moonraker.connected for t in trackers))
        job = await fakes[1].add_job("000001", "second.gcode", metadata=META)
        await fakes[1].emit({"print_stats": {"state": "printing", "filename": "second.gcode"}})
        await settle(lambda: trackers[1].active is not None)
        assert trackers[0].active is None
        await fakes[0].drop_clients()
        await fakes[1].finish_job(job, "completed", filament_used=1000)
        await fakes[1].emit({"print_stats": {"state": "complete"}})
        await settle(lambda: db.has_job("000001", "p1"))
        assert not db.has_job("000001", "p0")
        await settle(lambda: fakes[0].connections == 2, timeout=5)
        for task in tasks:
            task.cancel()
    for fake in fakes:
        await fake.stop()
    db.close()
