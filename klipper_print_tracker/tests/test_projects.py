import pytest

from app.db import Database
from app.projects import Projects, matches, progress


def job(status="completed", printed=None, hours=1.0, grams=10.0, kwh=0.1, cost=5.0):
    return {"status": status, "printed": printed or {}, "print_duration": hours * 3600, "grams": grams, "kwh": kwh, "total_cost": cost}


PROJECT = {"targets": [{"part": "ShoeRack", "quantity": 10}, {"part": "Bracket", "quantity": 4}]}


def test_progress_counts_only_successful_parts():
    result = progress(PROJECT, [job(printed={"ShoeRack": 2}), job(printed={"ShoeRack": 4, "Bracket": 1}), job("cancelled")])
    assert result["done"] == 7 and result["target"] == 14 and result["percent"] == 50
    assert result["parts"][0] == {"name": "ShoeRack", "target": 10, "printed": 6}
    assert result["prints"] == 3


def test_failed_attempts_are_shown_apart():
    result = progress(PROJECT, [job(printed={"ShoeRack": 1}), job("error", grams=4.0, cost=2.0, kwh=None)])
    assert result["success"] == {"hours": 1.0, "grams": 10.0, "kwh": 0.1, "cost": 5.0}
    assert result["failed"] == {"hours": 1.0, "grams": 4.0, "kwh": 0, "cost": 2.0}


def test_remaining_estimate():
    result = progress(PROJECT, [job(printed={"ShoeRack": 2}, hours=2.0, grams=20.0)])
    assert result["estimate"] == {"hours": 12.0, "grams": 120.0}


def test_extra_parts_dont_inflate_the_total():
    result = progress({"targets": [{"part": "A", "quantity": 2}]}, [job(printed={"A": 5, "B": 9})])
    assert result["percent"] == 100 and result["done"] == 2 and result["estimate"] is None


def test_empty_project():
    result = progress({"targets": []}, [])
    assert result["percent"] == 0 and result["estimate"] is None


def test_rules():
    record = {"filename": "dir/ShoeRack_PETG.gcode", "printed": {"Bracket": 1}, "excluded": {"Clip": 1}}
    assert matches({"kind": "file", "pattern": "*shoerack*"}, record)
    assert not matches({"kind": "file", "pattern": "Other*"}, record)
    assert matches({"kind": "part", "pattern": "brack*"}, record)
    assert matches({"kind": "part", "pattern": "Clip"}, record)
    assert not matches({"kind": "part", "pattern": "Knob"}, record)


@pytest.fixture
def store(tmp_path):
    db = Database(tmp_path / "t.db")
    yield Projects(db)
    db.close()


def save(store, job_id, **extra):
    record = {"printer_id": "printer1", "job_id": job_id, "filename": "ShoeRack.gcode", "status": "completed",
              "end_time": 1.0, "printed": {"ShoeRack": 3}, **extra}
    store.db.save_job(record)
    return record


async def test_rule_assigns_a_finished_print_and_sets_the_line(store):
    project = store.save({"name": "Полиця", "targets": [{"part": "ShoeRack", "quantity": 10}],
                          "rules": [{"kind": "file", "pattern": "ShoeRack*"}]})
    record = save(store, "1")
    await store.job_finished(record)
    assert record["project_id"] == project and record["project_line"] == "Проєкт Полиця: 3 / 10"
    assert store.get(project)["done"] == 3
    assert store.db.get_job("1")["project_line"] == "Проєкт Полиця: 3 / 10"


async def test_print_goes_to_one_project_and_finished_projects_are_skipped(store):
    first = store.save({"name": "A", "rules": [{"kind": "file", "pattern": "*"}]})
    second = store.save({"name": "B", "rules": [{"kind": "file", "pattern": "*"}]})
    store.save({"status": "done"}, first)
    record = save(store, "1")
    await store.job_finished(record)
    assert record["project_id"] == second


def test_manual_assignment_and_delete(store):
    project = store.save({"name": "A", "targets": [{"part": "ShoeRack", "quantity": 4}]})
    save(store, "1")
    store.assign("1", "printer1", project)
    assert store.get(project)["done"] == 3
    store.assign("1", "printer1", None)
    assert store.get(project)["done"] == 0 and store.db.get_job("1")["project_line"] is None
    store.assign("1", "printer1", project)
    store.delete(project)
    assert store.get(project) is None and store.db.has_job("1")


def test_bad_status(store):
    with pytest.raises(ValueError):
        store.save({"name": "A", "status": "nope"})


class Scope:
    printer = None
    id = None

    def topic(self, name):
        return f"klipper_print_tracker/{name}"


def test_sensor_only_for_active_projects(store):
    active = store.save({"name": "A", "targets": [{"part": "X", "quantity": 2}]})
    done = store.save({"name": "B", "status": "done"})
    assert [e[1] for e in store.entities(Scope())] == [f"project_{active}"]
    state = store.states(Scope())[f"klipper_print_tracker/project/{active}"]
    assert state["percent"] == 0 and state["parts"][0]["name"] == "X"
    assert f"klipper_print_tracker/project/{done}" not in store.states(Scope())
