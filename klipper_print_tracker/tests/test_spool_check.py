import asyncio
from pathlib import Path

import aiohttp
import pytest

from app import spool_check, tracker as tracker_module
from app.config import Options
from app.db import Database
from app.moonraker import Moonraker
from app.tracker import Tracker
from fake_moonraker import FakeMoonraker, settle

SAMPLE = (Path(__file__).parent / "fixtures" / "sample_tail.gcode").read_bytes()
PETG = {"id": 7, "remaining_weight": 500,
        "filament": {"name": "Чорний PETG", "material": "PETG", "vendor": {"name": "SkyWire"}}}


def codes(result):
    return [w["code"] for w in result["warnings"]]


def test_enough_filament():
    result = spool_check.check(100, PETG, "PETG", "SkyWire PETG Чорний", 5)
    assert result["warnings"] == [] and not spool_check.should_warn(result)


@pytest.mark.parametrize("remaining,warns", [(106, False), (104, True), (50, True)])
def test_margin(remaining, warns):
    result = spool_check.check(100, {**PETG, "remaining_weight": remaining}, "PETG", None, 5)
    assert ("not_enough" in codes(result)) is warns


def test_no_active_spool():
    result = spool_check.check(100, None, "PETG", None, 5)
    assert codes(result) == ["no_spool"] and spool_check.should_warn(result)
    assert not spool_check.should_pause(result)


def test_material_mismatch():
    pla = {**PETG, "filament": {**PETG["filament"], "material": "PLA"}}
    result = spool_check.check(100, pla, "PETG", None, 5)
    assert codes(result) == ["material_mismatch"] and spool_check.should_pause(result)


@pytest.mark.parametrize("wanted,actual,same", [
    ("PETG", "PETG", True), ("petg", "PETG", True), ("PETG-CF", "PETG", True), ("PLA", "PETG", False), ("PLA+", "PLA", True)])
def test_material_names(wanted, actual, same):
    assert spool_check.same_material(wanted, actual) is same


def test_preset_mismatch_is_only_information():
    result = spool_check.check(100, PETG, "PETG", "Generic ABS", 5)
    assert codes(result) == ["preset_mismatch"] and not spool_check.should_warn(result)
    assert not spool_check.should_pause(result)


def test_unknown_values_dont_warn():
    spool = {"filament": {}}
    assert spool_check.check(None, spool, None, None, 5)["warnings"] == []


def test_required_grams():
    assert spool_check.required_grams({"filament_weight_total": 12.34}, None) == 12.3
    config = {"filament_density": "1.27,1.24", "filament_diameter": "1.75,1.75"}
    assert spool_check.required_grams({"filament_total": 1000}, config) == 3.1
    assert spool_check.required_grams({}, config) is None
    assert spool_check.required_grams({"filament_total": 1000}, None) is None


class FakeSupervisor:
    def __init__(self):
        self.events = []

    async def energy(self, entity):
        return None

    async def fire_event(self, event_type, data):
        self.events.append((event_type, data))
        return True


class Listener:
    def __init__(self):
        self.checks = []

    async def current(self, printer_id, active):
        pass

    async def job_finished(self, record):
        pass

    async def spool_checked(self, printer_id, result):
        self.checks.append(result)


@pytest.fixture
async def rig(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker_module, "FINISH_DELAY", 0.01)
    fake = FakeMoonraker()
    url = await fake.start()
    fake.files["p.gcode"] = SAMPLE
    fake.metadata["p.gcode"] = {"filament_weight_total": 100}
    session = aiohttp.ClientSession()
    db = Database(tmp_path / "t.db")

    class Rig:
        pass

    rig = Rig()
    rig.fake, rig.db, rig.supervisor, rig.listener = fake, db, FakeSupervisor(), Listener()

    async def start(**options):
        moonraker = Moonraker(url, session)
        rig.tracker = Tracker(Options(**options), db, moonraker, rig.supervisor, listeners=[rig.listener])
        moonraker.on_status, moonraker.on_history = rig.tracker.on_status, rig.tracker.on_history
        rig.task = asyncio.create_task(moonraker.run())
        await settle(lambda: moonraker.connected)

    async def print_starts():
        await fake.add_job("000001", "p.gcode")
        await fake.emit({"print_stats": {"state": "printing", "filename": "p.gcode"}})
        await settle(lambda: rig.tracker._spool_task is not None)
        await rig.tracker._spool_task

    rig.start, rig.print_starts = start, print_starts
    yield rig
    rig.task.cancel()
    await session.close()
    db.close()
    await fake.stop()


async def test_warning_fires_an_event_and_stays_with_the_job(rig):
    rig.fake.spool_id = 7
    rig.fake.spools[7] = {**PETG, "remaining_weight": 50}
    await rig.start()
    await rig.print_starts()
    event_type, data = rig.supervisor.events[0]
    assert event_type == "klipper_print_tracker_spool_warning"
    assert data["printer_id"] == "printer1" and data["warnings"][0]["code"] == "not_enough"
    assert data["material"] == "PETG"
    assert rig.fake.pauses == 0
    job = rig.fake.jobs[0]
    await rig.fake.finish_job(job, "completed")
    await rig.fake.emit({"print_stats": {"state": "complete"}})
    await settle(lambda: rig.db.has_job("000001"))
    assert rig.db.get_job("000001")["spool_check"]["warnings"][0]["code"] == "not_enough"


async def test_auto_pause(rig):
    rig.fake.spool_id = 7
    rig.fake.spools[7] = {**PETG, "remaining_weight": 50}
    await rig.start(spool_check_auto_pause=True)
    await rig.print_starts()
    assert rig.fake.pauses == 1 and rig.listener.checks[0]["paused"] is True


async def test_auto_pause_ignores_a_missing_spool(rig):
    await rig.start(spool_check_auto_pause=True)
    await rig.print_starts()
    assert rig.listener.checks[0]["warnings"][0]["code"] == "no_spool"
    assert rig.fake.pauses == 0 and len(rig.supervisor.events) == 1


async def test_good_spool_is_quiet(rig):
    rig.fake.spool_id = 7
    rig.fake.spools[7] = PETG
    await rig.start()
    await rig.print_starts()
    assert rig.supervisor.events == [] and rig.listener.checks[0]["warnings"] == []


async def test_without_spoolman_nothing_is_reported(rig):
    rig.fake.spoolman = False
    await rig.start()
    await rig.print_starts()
    assert rig.supervisor.events == [] and rig.listener.checks == []


async def test_pause_action_from_the_notification(rig):
    await rig.start()
    assert await rig.tracker.on_action("printer1", "current", "spool-pause", None) is True
    assert rig.fake.pauses == 1
    assert await rig.tracker.on_action("printer1", "current", "spool-continue", None) is True
    assert rig.fake.pauses == 1
    assert await rig.tracker.on_action("printer2", "current", "spool-pause", None) is False
    assert await rig.tracker.on_action("printer1", "000001", "good", None) is False
