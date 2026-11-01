import pytest

from app import analysis, calc
from app.analysis import Analysis
from app.config import Options
from app.db import Database

WEEK = 7 * 86400
BASE = 1_800_000_000.0


def job(status="completed", **extra):
    return {"status": status, "end_time": BASE, "print_duration": 3600, "grams": 10.0, "wasted_cost": 0, "material": "PLA",
            "spool": "S", "presets": {"process": ["Draft"], "filament": ["PLA Basic"]}, "printed": {"Clip": 1},
            "excluded": {}, "issues": None, "failure_reason": None, "interruption": None, "progress": None,
            "current_layer": None, **extra}


JOBS = [
    job(),
    job(),
    job("error", failure_reason="adhesion", progress=2.0, current_layer=1, wasted_cost=5.0, printed={}, material="PETG",
        interruption="error", issues=["warping"]),
    job("cancelled", failure_reason="spaghetti", progress=55.0, current_layer=30, wasted_cost=3.0, printed={},
        excluded={"Clip": 2}, material="PETG", interruption="cancelled"),
    job("error", progress=70.0, current_layer=40, wasted_cost=9.0, printed={}, interruption="power_or_offline"),
]


@pytest.mark.parametrize("raw,offline,energy,expected", [
    ("completed", True, 0, None), ("cancelled", True, None, "cancelled"), ("error", False, 5.0, "error"),
    ("klippy_shutdown", False, 5.0, "power_or_offline"), ("klippy_disconnect", False, None, "power_or_offline"),
    ("interrupted", False, None, "power_or_offline"), ("error", True, None, "power_or_offline"),
    ("error", False, 0, "power_or_offline"),
])
def test_interruption_type(raw, offline, energy, expected):
    assert calc.interruption(raw, offline, energy) == expected


def test_progress_falls_back_to_filament():
    assert calc.progress_percent(0.5, 0, 0) == 50
    assert calc.progress_percent(None, 250, 1000) == 25
    assert calc.progress_percent(None, 250, 0) is None


def test_power_cuts_stay_out_of_reliability():
    result = analysis.analyse(JOBS)
    assert result["total"] == 4 and result["failed"] == 2 and result["offline"] == 1
    assert result["success_rate"] == 50
    assert analysis.analyse(JOBS, include_power=True)["failed"] == 3


def test_wasted_counts_only_failures():
    assert analysis.analyse(JOBS)["wasted"] == {"hours": 2.0, "grams": 20.0, "cost": 8.0}


def test_weekly_rate():
    jobs = [job(end_time=BASE), job("error", end_time=BASE), job(end_time=BASE + WEEK)]
    weeks = analysis.weekly(jobs)
    assert [w["rate"] for w in weeks] == [50, 100] and weeks[0]["total"] == 2


def test_failure_rate_by_material():
    rows = analysis.by_dimension(analysis.counted(JOBS, False), "material")
    assert rows[0] == {"name": "PETG", "total": 2, "failed": 2, "rate": 100.0,
                       "reasons": {"adhesion": 1, "spaghetti": 1}}
    assert rows[1]["name"] == "PLA" and rows[1]["rate"] == 0


def test_unknown_reason_is_counted():
    rows = analysis.by_dimension([job("error")], "process_preset")
    assert rows[0]["reasons"] == {"unknown": 1}


def test_histograms_show_first_layer_failures():
    progress = analysis.progress_histogram(JOBS)
    assert progress[0]["count"] == 1 and progress[5]["count"] == 1 and sum(b["count"] for b in progress) == 3
    assert analysis.progress_histogram([job("error", progress=100.0)])[9]["count"] == 1
    layers = analysis.layer_histogram(JOBS)
    assert layers[0] == {"label": "1", "count": 1} and layers[3]["count"] == 2


def test_problem_parts():
    parts = analysis.problem_parts(JOBS)
    assert parts[0]["name"] == "Clip" and parts[0]["excluded"] == 2
    assert analysis.problem_parts([job()]) == []


def test_tags_and_top_reason():
    assert analysis.tag_frequency(JOBS, "material") == [{"name": "PETG", "tag": "warping", "count": 1}]
    assert analysis.top_reason(JOBS) in ("adhesion", "spaghetti")
    assert analysis.top_reason([job()]) is None


def test_no_jobs():
    result = analysis.analyse([])
    assert result["success_rate"] == 0 and result["weekly"] == [] and result["top_reason"] is None


def test_sensors_for_30_days(tmp_path):
    import time

    from app.mqtt import Scope
    db = Database(tmp_path / "t.db")
    now = time.time()
    for i, (status, reason, age) in enumerate([("completed", None, 1), ("error", "clog", 2), ("completed", None, 90)]):
        db.save_job({"job_id": str(i), "filename": "a", "status": status, "failure_reason": reason,
                     "end_time": now - age * 86400})
    scope = Scope(Options(moonraker_url="http://a.example").printers[0])
    state = Analysis(db).states(scope)[scope.topic("analysis")]
    assert state == {"success_rate": 50.0, "failed": 1, "top_reason": "clog"}
    assert {e[1] for e in Analysis(db).entities(scope)} == {"success_rate_30d", "failures_30d"}
    db.close()
