import time
from pathlib import Path

import aiohttp
import pytest

from app import calibration as cal
from app.calibration import Calibrations
from app.config import Options
from app.db import Database
from app.moonraker import Moonraker
from fake_moonraker import FakeMoonraker

TOWER = (Path(__file__).parent / "fixtures" / "temperature_tower_trimmed.gcode").read_text(encoding="utf-8")
SAMPLE = (Path(__file__).parent / "fixtures" / "sample_tail.gcode").read_text(encoding="utf-8")
DAY = 86400


def scan(text):
    import re
    return "\n".join(line for line in text.splitlines() if re.match(cal.SCAN.decode(), line))


def test_real_temperature_tower_from_orca():
    from app import gcode
    names = gcode.object_names(TOWER)
    assert names == ["temperature_tower.drc_id_0_copy_0"]
    assert cal.worth_scanning(TOWER[:4000], names)
    assert cal.detect(names, scan(TOWER)) == {"type": "temperature", "range": {"start": 230.0, "end": 190.0, "step": -5.0}}


def test_ordinary_print_is_not_a_calibration():
    from app import gcode
    names = gcode.object_names(SAMPLE)
    assert not cal.worth_scanning(SAMPLE, names)
    assert cal.detect(["Cube_id_0_copy_0"], "M104 S230\nM104 S225\n") is None


def lines(prefix, values):
    return "\n".join(f"{prefix}{v}" for v in values)


# The following strings copy the formats in OrcaSlicer's GCode.cpp and calib.cpp, no real files yet.
def test_pa_tower_marks():
    text = lines("SET_PRESSURE_ADVANCE ADVANCE=", [0.0, 0.002, 0.004, 0.006, 0.008]).replace("\n", "; Override\n")
    assert cal.detect(["tower_with_seam.drc_id_0_copy_0"], text) == {
        "type": "pa_tower", "range": {"start": 0.002, "end": 0.008, "step": 0.002}}
    assert cal.detect([], text)["type"] == "pa_tower"


def test_pa_pattern_marks():
    text = "; start pressure advance pattern for layer\n" + lines("SET_PRESSURE_ADVANCE ADVANCE=", [0.01, 0.02, 0.03])
    assert cal.worth_scanning(text, []) and cal.detect([], text)["type"] == "pa_pattern"


def test_retraction_marks():
    text = "\n".join(f"; Calib_Retraction_tower: Z_HEIGHT: {z}, length:{z * 0.1:.1f}" for z in range(1, 6))
    assert cal.detect(["retraction_tower.drc_id_0_copy_0"], text) == {
        "type": "retraction", "range": {"start": 0.1, "end": 0.5, "step": 0.1}}


@pytest.mark.parametrize("name,kind", [
    ("flowrate-test-pass1.drc_id_0_copy_0", "flow_pass1"), ("flowrate-test-pass2_id_0_copy_0", "flow_pass2"),
    ("Orca-LinearFlow.3mf_id_0_copy_0", "flow_yolo"), ("SpeedTestStructure.drc_id_0_copy_0", "max_volumetric_speed"),
    ("vfa.drc_id_0_copy_0", "vfa"), ("VFA.DRC_ID_0_COPY_0", None),
])
def test_tests_known_only_by_name(name, kind):
    found = cal.detect([name], "")
    assert (found or {}).get("type") == kind


@pytest.mark.parametrize("text,value", [("0.036", 0.036), ("PA 0,98", 0.98), ("245", 245.0), ("", None), (None, None), ("нічого", None)])
def test_parse_value(text, value):
    assert cal.parse_value(text) == value


def test_value_range_needs_a_real_change():
    assert cal.value_range([230, 230, 230]) is None
    assert cal.value_range([230, 225, 225, 220]) == {"start": 230, "end": 220, "step": -5}


CONFIG_A = {"filament_settings_id": '"PETG A";"PLA B"', "filament_type": "PETG;PLA", "pressure_advance": "0.04,0.02",
            "filament_flow_ratio": "0.98,1"}


@pytest.fixture
def rig(tmp_path):
    db = Database(tmp_path / "t.db")
    db.store_config("a", CONFIG_A)
    service = Calibrations(db, Options(calibration_stale_days=30), {})
    yield service
    db.close()


def calibration_print(rig, job_id="1", end=None, spool_id=5):
    record = {"printer_id": "printer1", "job_id": job_id, "filename": "tower.gcode", "status": "completed",
              "end_time": end or time.time() - 10 * DAY, "presets": {"filament": ["PETG A"]}, "material": "PETG",
              "spool": "Spool", "spool_id": spool_id, "config_hash": "a"}
    rig.db.save_job(record)
    return record


def ordinary_print(rig, job_id="2", spool_id=5, end=None):
    rig.db.save_job({"printer_id": "printer1", "job_id": job_id, "filename": "a.gcode", "status": "completed",
                     "end_time": end or time.time() - DAY, "presets": {"filament": ["PETG A"]}, "config_hash": "a",
                     "spool_id": spool_id})


async def test_result_from_the_notification(rig):
    record = calibration_print(rig)
    rig.save(record, "pa_tower", {"start": 0, "end": 0.1, "step": 0.002}, True)
    assert rig.db.get_job("1")["calibration"] == "pa_tower"
    assert await rig.from_action("printer1", "1", "result", "0,036") is True
    assert rig.get("printer1", "1")["value"] == 0.036
    assert await rig.from_action("printer1", "1", "good", None) is False


async def test_mismatch_with_recent_prints(rig):
    record = calibration_print(rig)
    rig.save(record, "pa_tower", None, True)
    ordinary_print(rig)
    await rig.set_value("printer1", "1", 0.036)
    hint = rig.overview()[0]["latest"]["pa"]
    assert hint["mismatch"] and hint["used"] == 0.04
    assert rig.mismatches() == [{"preset": "PETG A", "type": "pa", "value": 0.036, "used": 0.04}]


async def test_matching_value_is_fine(rig):
    record = calibration_print(rig)
    rig.save(record, "flow_pass1", None, True)
    ordinary_print(rig)
    await rig.set_value("printer1", "1", 0.98)
    assert not rig.overview()[0]["latest"]["flow"]["mismatch"] and rig.mismatches() == []


async def test_retraction_falls_back_to_the_printer_setting(rig):
    rig.db.store_config("r", {**CONFIG_A, "retraction_length": "0.6"})
    record = calibration_print(rig)
    rig.save(record, "retraction", None, True)
    rig.db.save_job({"printer_id": "printer1", "job_id": "2", "filename": "a", "status": "completed",
                     "end_time": time.time() - DAY, "presets": {"filament": ["PETG A"]}, "config_hash": "r"})
    await rig.set_value("printer1", "1", 0.8)
    assert rig.overview()[0]["latest"]["retraction"]["used"] == 0.6


async def test_stale_by_age(rig):
    record = calibration_print(rig, end=time.time() - 40 * DAY)
    rig.save(record, "temperature", None, True)
    await rig.set_value("printer1", "1", 245)
    hint = rig.overview()[0]["latest"]["temperature"]
    assert hint["stale"] and hint["age_days"] == 40


async def test_stale_after_a_new_spool(rig):
    record = calibration_print(rig)
    rig.save(record, "pa_line", None, True)
    ordinary_print(rig, spool_id=6)
    await rig.set_value("printer1", "1", 0.04)
    hint = rig.overview()[0]["latest"]["pa"]
    assert hint["new_spool"] and hint["stale"]


async def test_latest_value_per_kind_and_history(rig):
    first = calibration_print(rig, "1", time.time() - 9 * DAY)
    second = calibration_print(rig, "2", time.time() - 2 * DAY)
    rig.save(first, "pa_line", None, True)
    rig.save(second, "pa_tower", None, True)
    await rig.set_value("printer1", "1", 0.03)
    await rig.set_value("printer1", "2", 0.04)
    entry = rig.overview()[0]
    assert entry["latest"]["pa"]["value"] == 0.04 and len(entry["history"]) == 2


async def test_detection_scans_the_file_after_a_print(tmp_path):
    fake = FakeMoonraker()
    url = await fake.start()
    body = TOWER.encode()
    fake.files["tower.gcode"] = body
    db = Database(tmp_path / "t.db")
    async with aiohttp.ClientSession() as session:
        moonraker = Moonraker(url, session)
        service = Calibrations(db, Options(), {"printer1": moonraker})
        record = {"printer_id": "printer1", "job_id": "1", "filename": "tower.gcode", "status": "completed",
                  "end_time": 5.0, "gcode_head": TOWER[:3000]}
        db.save_job(record)
        await service.job_finished(record)
    saved = service.get("printer1", "1")
    assert saved["type"] == "temperature" and saved["range_end"] == 190 and saved["detected"] == 1
    assert record["calibration"] == "temperature" and "gcode_head" not in record
    db.close()
    await fake.stop()


async def test_ordinary_print_downloads_nothing(rig):
    class NoScan:
        async def scan_gcode(self, *args):
            raise AssertionError("must not read the file")

    rig.moonrakers["printer1"] = NoScan()
    record = {"printer_id": "printer1", "job_id": "9", "filename": "a", "gcode_head": "G28\n"}
    await rig.job_finished(record)
    assert rig.get("printer1", "9") is None
