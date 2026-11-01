import os
import subprocess
import time

import pytest

from app.config import Options
from app.db import Database
from app import housekeeping, maintenance as m
from app.maintenance import Maintenance

NOW = 1_800_000_000.0
DAY = 86400
TASK = {"hours": 100, "days": 30, "grams": None, "prints": None, "abrasive_grams": None, "last_done_at": NOW - 10 * DAY,
        "enabled": 1, "snooze_until_hours": None}


def usage(hours=0.0, grams=0.0, prints=0, abrasive=0.0):
    return {"hours": hours, "grams": grams, "prints": prints, "abrasive_grams": abrasive}


def test_nothing_due_yet():
    state = m.state(TASK, usage(hours=20), NOW, 20)
    assert not state["due"] and state["percent_used"] == 33
    assert state["worst"]["kind"] == "days" and state["main"]["kind"] == "hours"
    assert state["main"]["remaining"] == 80


def test_hours_limit_comes_first():
    state = m.state(TASK, usage(hours=101), NOW, 101)
    assert state["due"] and state["worst"]["kind"] == "hours" and state["worst"]["remaining"] == -1


def test_calendar_limit_comes_first():
    task = {**TASK, "last_done_at": NOW - 31 * DAY}
    assert m.state(task, usage(hours=1), NOW, 1)["due"]


def test_mixed_limits_with_prints_and_grams():
    task = {**TASK, "hours": None, "days": None, "grams": 500, "prints": 10}
    assert not m.state(task, usage(grams=100, prints=5), NOW, 0)["due"]
    assert m.state(task, usage(grams=100, prints=10), NOW, 0)["due"]
    assert m.state(task, usage(grams=501, prints=1), NOW, 0)["worst"]["kind"] == "grams"


def test_task_without_limits_is_never_due():
    task = {**TASK, "hours": None, "days": None}
    assert not m.state(task, usage(hours=1000), NOW, 1000)["due"]


def test_disabled_and_snoozed():
    assert not m.state({**TASK, "enabled": 0}, usage(hours=500), NOW, 500)["due"]
    snoozed = {**TASK, "snooze_until_hours": 510}
    assert m.state(snoozed, usage(hours=500), NOW, 505)["snoozed"]
    assert m.state(snoozed, usage(hours=511), NOW, 511)["due"]


JOBS = [
    {"end_time": NOW - 5, "print_duration": 7200, "grams": 100, "material": "PETG-CF", "spool": "Acme"},
    {"end_time": NOW - 4, "print_duration": 3600, "grams": 50, "material": "PLA", "spool": "Glow in the dark"},
    {"end_time": NOW - 3, "print_duration": 3600, "grams": 40, "material": "PLA", "spool": "Plain"},
    {"end_time": NOW - 500, "print_duration": 3600, "grams": 999, "material": "PA-GF", "spool": ""},
]


def test_abrasive_filament_counts_by_material_or_spool_name():
    result = m.usage_since(JOBS, NOW - 100, "CF|GF|glow")
    assert result == {"hours": 4.0, "grams": 190, "prints": 3, "abrasive_grams": 150}


def test_grams_for_certain_materials_only():
    assert m.usage_since(JOBS, NOW - 100, "CF", "PLA")["grams"] == 90


def test_abrasive_patterns_can_be_empty():
    assert m.usage_since(JOBS, NOW - 100, "")["abrasive_grams"] == 0


class Supervisor:
    def __init__(self):
        self.events = []

    async def fire_event(self, event_type, data):
        self.events.append((event_type, data))


@pytest.fixture
def rig(tmp_path):
    db = Database(tmp_path / "t.db")
    service = Maintenance(db, Options(), Supervisor())
    service.ensure_defaults("printer1")
    yield service
    db.close()


def add_print(db, job_id, hours, grams=10.0, material="PLA", when=None):
    db.save_job({"job_id": job_id, "filename": "a", "status": "completed", "end_time": when or time.time() + 1,
                 "print_duration": hours * 3600, "grams": grams, "material": material})


def test_defaults_are_seeded_once_and_not_due(rig):
    tasks = rig.tasks("printer1")
    assert len(tasks) == 12 and not any(t["due"] for t in tasks)
    assert all(t["confirmed"] == 0 for t in tasks)
    rig.ensure_defaults("printer1")
    assert len(rig.tasks("printer1")) == 12
    assert {t["printer_id"] for t in rig.tasks("printer2")} == set()


def test_deleted_defaults_stay_deleted(rig):
    rig.delete(rig.tasks("printer1")[0]["id"])
    rig.ensure_defaults("printer1")
    assert len(rig.tasks("printer1")) == 11


def test_setup_answers_set_the_dates(rig):
    task = next(t for t in rig.tasks("printer1") if t["days"] == 7)
    rig.confirm("printer1", {str(task["id"]): time.time() - 8 * DAY})
    after = {t["id"]: t for t in rig.tasks("printer1")}
    assert after[task["id"]]["due"] and all(t["confirmed"] for t in after.values())


async def test_due_is_announced_once_and_never_mid_print(rig):
    add_print(rig.db, "1", 25)
    rig.busy = lambda printer: True
    assert await rig.check("printer1") == []
    rig.busy = lambda printer: False
    fresh = await rig.check("printer1")
    assert [t["hours"] for t in fresh] == [20]
    event_type, data = rig.supervisor.events[0]
    assert event_type == m.DUE_EVENT and data["printer_id"] == "printer1" and data["task_id"]
    assert await rig.check("printer1") == []


async def test_done_resets_and_logs(rig):
    add_print(rig.db, "1", 25)
    task = next(t for t in rig.tasks("printer1") if t["hours"] == 20)
    await rig.done(task["id"], "мийка", time.time() + 5)
    after = next(t for t in rig.tasks("printer1") if t["id"] == task["id"])
    assert not after["due"]
    entry = rig.log("printer1")[0]
    assert entry["note"] == "мийка" and entry["name"] == task["name"]


async def test_snooze_lasts_ten_print_hours(rig):
    add_print(rig.db, "1", 25)
    task = next(t for t in rig.tasks("printer1") if t["hours"] == 20)
    await rig.snooze(task["id"])
    assert not next(t for t in rig.tasks("printer1") if t["id"] == task["id"])["due"]
    add_print(rig.db, "2", 11)
    assert next(t for t in rig.tasks("printer1") if t["id"] == task["id"])["due"]


async def test_actions(rig):
    add_print(rig.db, "1", 25)
    task = next(t for t in rig.tasks("printer1") if t["hours"] == 20)
    assert await rig.from_action("printer1", f"maint-{task['id']}", "snooze", None) is True
    assert await rig.from_action("printer1", "00004F", "good", None) is False
    assert await rig.from_action("printer1", f"maint-{task['id']}", "done", "ok") is True
    assert rig.log("printer1")[0]["note"] == "ok"
    assert await rig.from_action("printer2", f"maint-{task['id']}", "done", None) is True
    assert len(rig.log("printer1")) == 1


def test_save_and_custom_task(rig):
    task_id = rig.save("printer1", {"name": "Змастити", "prints": 5, "hours": None})
    assert rig.task(task_id)["prints"] == 5
    rig.save("printer1", {"name": "Нове", "enabled": 0}, task_id)
    assert rig.task(task_id)["name"] == "Нове" and rig.task(task_id)["enabled"] == 0


class Scope:
    id = "printer1"
    printer = object()

    def topic(self, name):
        return f"klipper_print_tracker/printer1/{name}"


def test_entities_per_task(rig):
    items = rig.entities(Scope())
    assert len(items) == 36
    assert {i[0] for i in items} == {"sensor", "binary_sensor", "button"}
    sensor = next(i for i in items if i[0] == "sensor")
    assert sensor[2]["unit_of_measurement"] == "год"
    state = next(iter(rig.states(Scope()).values()))
    assert set(state) >= {"remaining", "due", "percent_left"}


async def test_button_command(rig):
    task = rig.tasks("printer1")[0]
    assert await rig.command(f"klipper_print_tracker/printer1/maint/{task['id']}/done", b"PRESS")
    assert len(rig.log("printer1")) == 1
    assert not await rig.command("klipper_print_tracker/rescan", b"PRESS")


def test_data_size_and_retention(tmp_path):
    (tmp_path / "tracker.db").write_bytes(b"x" * 1048576)
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()
    old, new = thumbs / "old.png", thumbs / "new.png"
    old.write_bytes(b"x" * 1048576)
    new.write_bytes(b"y")
    os.utime(old, (NOW - 400 * DAY, NOW - 400 * DAY))
    os.utime(new, (NOW, NOW))
    assert housekeeping.data_size(tmp_path)["database"] == 1.0
    assert housekeeping.prune_thumbnails(thumbs, 0, NOW) == 0
    assert housekeeping.prune_thumbnails(thumbs, 365, NOW) == 1
    assert new.exists() and not old.exists()


def test_git_gc_runs_in_every_repository(tmp_path):
    repo = tmp_path / "printer1"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    housekeeping.git_gc(tmp_path)
