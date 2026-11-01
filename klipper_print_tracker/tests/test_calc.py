import pytest

from app import calc


@pytest.mark.parametrize("raw,expected", [
    ("Bracket.stl_id_0_copy_2", "Bracket"),
    ("Cube_id_0_copy_0", "Cube"),
    ("Holder v2.STEP_id_12_copy_0", "Holder v2"),
    ("plain_name", "plain_name"),
    ("SHOERACK.STL_2_ID_0_COPY_0", "SHOERACK"),
    ("SHOERACK.STL_2_ID_1_COPY_0", "SHOERACK"),
    ("ShoeRack.stl_2_id_1_copy_3", "ShoeRack"),
    ("PLATE.3MF_12_ID_3_COPY_0", "PLATE"),
    ("Bracket.step", "Bracket"),
    ("V1.5_MOUNT_ID_0_COPY_0", "V1.5_MOUNT"),
])
def test_normalise_name(raw, expected):
    assert calc.normalise_name(raw) == expected


def test_completed_with_one_excluded_part():
    objects = ["Bracket.stl_id_0_copy_0", "Bracket.stl_id_0_copy_1", "Clip.stl_id_1_copy_0"]
    printed, excluded, planned = calc.count_parts(objects, ["Bracket.stl_id_0_copy_1"], "completed")
    assert printed == {"Bracket": 1, "Clip": 1}
    assert excluded == {"Bracket": 1}
    assert planned == 3


def test_upper_case_copies_are_one_part():
    objects = ["SHOERACK.STL_2_ID_0_COPY_0", "SHOERACK.STL_2_ID_1_COPY_0"]
    printed, excluded, planned = calc.count_parts(objects, [], "completed")
    assert printed == {"SHOERACK": 2} and excluded == {} and planned == 2


def test_restore_casing():
    originals = ["ShoeRack.stl_2_id_0_copy_0", "ShoeRack.stl_2_id_1_copy_0", "Clip_id_2_copy_0"]
    assert calc.restore_casing({"SHOERACK": 2, "CLIP": 1}, originals) == {"ShoeRack": 2, "Clip": 1}
    assert calc.restore_casing({"OTHER": 1}, originals) == {"OTHER": 1}
    assert calc.restore_casing({"SHOERACK": 1, "ShoeRack": 2}, originals) == {"ShoeRack": 3}


def test_cancelled_prints_no_parts():
    printed, excluded, planned = calc.count_parts(["A_id_0_copy_0"], [], "cancelled")
    assert printed == {} and excluded == {} and planned == 1


def test_grams_scaled_for_cancelled_print():
    metadata = {"filament_weight_total": 100, "filament_total": 1000}
    assert calc.grams_used(metadata, 250, "cancelled") == 25.0


def test_grams_without_total_length():
    metadata = {"filament_weight_total": 12.34}
    assert calc.grams_used(metadata, 0, "completed") == 12.3
    assert calc.grams_used(metadata, 0, "cancelled") == 0


def test_energy_delta():
    assert calc.energy_delta(10.0, 10.5) == 0.5
    assert calc.energy_delta(None, 10.5) is None
    assert calc.energy_delta(10.0, None) is None
    assert calc.energy_delta(10.0, 0.2) is None


def test_costs_completed():
    result = calc.costs(0.5, 4.32, 100, 800, 4, "completed")
    assert result == {"energy_cost": 2.16, "filament_cost": 80.0, "total_cost": 82.16,
                      "per_part": 20.54, "wasted_cost": 0}


def test_costs_missing_energy_and_no_parts_is_wasted():
    result = calc.costs(None, 4.32, 50, 800, 0, "cancelled")
    assert result["energy_cost"] == 0
    assert result["per_part"] == 0
    assert result["wasted_cost"] == result["total_cost"] == 40.0


def test_spool_prefers_spool_price():
    spool = {"price": 500, "initial_weight": 1000,
             "filament": {"name": "PETG Black", "vendor": {"name": "Acme"}, "price": 900, "weight": 1000}}
    assert calc.spool_info(spool) == ("Acme PETG Black", 500.0)


def test_spool_without_price():
    assert calc.spool_info({"filament": {"name": "PLA"}}) == ("PLA", None)
    assert calc.spool_info(None) == (None, None)


@pytest.mark.parametrize("raw,expected", [
    ("completed", "completed"), ("cancelled", "cancelled"),
    ("klippy_shutdown", "error"), ("error", "error"), ("interrupted", "error"),
])
def test_job_status(raw, expected):
    assert calc.job_status(raw) == expected
