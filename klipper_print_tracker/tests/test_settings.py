import subprocess
import time
from pathlib import Path

import aiohttp
import pytest

from app import moonraker as moonraker_module
from app.db import Database
from app.moonraker import Moonraker
from app.settings_git import GitHistory, SettingsHistory, diff_configs, sanitise, short_changes
from app.slicer_meta import LayoutStore
from fake_moonraker import FakeMoonraker

SAMPLE = (Path(__file__).parent / "fixtures" / "sample_tail.gcode").read_bytes()


def edited(*replacements) -> bytes:
    text = SAMPLE.decode()
    for old, new in replacements:
        assert old in text
        text = text.replace(old, new)
    return text.encode()


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout


@pytest.fixture
async def rig(tmp_path):
    fake = FakeMoonraker()
    url = await fake.start()
    session = aiohttp.ClientSession()
    db = Database(tmp_path / "t.db")
    moonraker = Moonraker(url, session)
    layouts = LayoutStore(tmp_path / "layouts", auto_fetch=False)
    history = SettingsHistory(db, moonraker, layouts, tmp_path)

    class Rig:
        pass

    rig = Rig()
    rig.fake, rig.db, rig.history, rig.moonraker, rig.repo = fake, db, history, moonraker, tmp_path / "git"
    rig.clock = time.time()

    async def job(job_id, filename="plate.gcode", content=SAMPLE, status="completed"):
        if content is not None:
            fake.files[filename] = content
        rig.clock += 60
        record = {"job_id": job_id, "filename": filename, "status": status, "end_time": rig.clock}
        await history.snapshot(record)
        db.save_job(record)
        return record

    rig.job = job
    yield rig
    await session.close()
    db.close()
    await fake.stop()


async def test_first_job_stores_config_and_commits(rig):
    record = await rig.job("000001")
    assert record["slicer"] == "OrcaSlicer" and record["slicer_version"] == "2.3.2"
    assert record["presets"] == {"process": ["0.24mm Draft @Creality K1C"],
                                 "filament": ["SkyWire PETG Чорний"],
                                 "printer": ["Creality K1C 0.4 nozzle - Timelapse"]}
    assert record["commit_sha"]
    assert rig.db.get_config(record["config_hash"])["layer_height"] == "0.24"
    assert git(rig.repo, "log", "--format=%s").strip() == "job 000001: plate.gcode [completed]"
    tracked = git(rig.repo, "-c", "core.quotepath=off", "ls-files").split("\n")
    assert "effective.ini" in tracked
    assert "presets/process/0.24mm Draft @Creality K1C.ini" in tracked
    assert "presets/filament/SkyWire PETG Чорний.ini" in tracked
    assert "presets/printer/Creality K1C 0.4 nozzle - Timelapse.ini" in tracked
    assert not [t for t in tracked if "Флок" in t]


async def test_preset_files_contain_only_their_keys(rig):
    await rig.job("000001")
    process = (rig.repo / "presets/process/0.24mm Draft @Creality K1C.ini").read_text(encoding="utf-8")
    filament = (rig.repo / "presets/filament/SkyWire PETG Чорний.ini").read_text(encoding="utf-8")
    assert "layer_height = 0.24\n" in process and "nozzle_temperature" not in process
    assert "nozzle_temperature = 240\n" in filament and "layer_height" not in filament
    assert "filament_flow_ratio = 1.067\n" in filament
    effective = (rig.repo / "effective.ini").read_text(encoding="utf-8")
    assert "nozzle_temperature = 240,230\n" in effective
    keys = [line.split(" = ")[0] for line in effective.splitlines()]
    assert keys == sorted(keys)


async def test_same_config_makes_no_commit_and_dedupes(rig):
    first = await rig.job("000001")
    second = await rig.job("000002")
    assert second["commit_sha"] is None and second["preset_drift"] == {}
    assert second["config_hash"] == first["config_hash"]
    assert len(git(rig.repo, "log", "--format=%h").split()) == 1
    assert rig.db._query("SELECT COUNT(*) n FROM configs")[0]["n"] == 1


async def test_change_commits_message_and_summaries(rig):
    await rig.job("000001")
    record = await rig.job("000002", content=edited(("; outer_wall_speed = 200", "; outer_wall_speed = 180"),
                                                    ("; filament_flow_ratio = 1.067,1.05",
                                                     "; filament_flow_ratio = 1.04,1.05")), status="cancelled")
    message = git(rig.repo, "log", "-1", "--format=%B").strip().split("\n")
    assert message[0] == "job 000002: plate.gcode [cancelled]"
    assert "0.24mm Draft @Creality K1C: outer_wall_speed 200 -> 180" in message
    assert "SkyWire PETG Чорний: filament_flow_ratio 1.067,1.05 -> 1.04,1.05" in message
    assert record["changes"]["file"]["job_id"] == "000001"
    assert short_changes(record) == ["filament_flow_ratio", "outer_wall_speed"]
    drift = record["preset_drift"]
    assert drift["process/0.24mm Draft @Creality K1C"] == [
        {"key": "outer_wall_speed", "old": "200", "new": "180"}]
    assert drift["filament/SkyWire PETG Чорний"] == [
        {"key": "filament_flow_ratio", "old": "1.067", "new": "1.04"}]


async def test_summaries_by_preset_for_a_new_file(rig):
    await rig.job("000001", filename="a.gcode")
    record = await rig.job("000002", filename="b.gcode",
                           content=edited(("; layer_height = 0.24", "; layer_height = 0.2")))
    assert "file" not in record["changes"]
    assert record["changes"]["process"]["job_id"] == "000001"
    assert record["changes"]["filament"]["diff"] == [{"key": "layer_height", "old": "0.24", "new": "0.2"}]
    assert short_changes(record) == ["layer_height"]


async def test_message_is_limited(rig):
    await rig.job("000001")
    text = SAMPLE.decode()
    for i in range(40):
        text = text.replace("; CONFIG_BLOCK_END", f"; extra_{i} = {i}\n; CONFIG_BLOCK_END")
    await rig.job("000002", content=text.encode())
    message = git(rig.repo, "log", "-1", "--format=%B").strip().split("\n")
    assert len(message) == 2 + 30 + 1 and message[-1] == "... and 10 more"


async def test_deleted_file(rig):
    rig.fake.files.clear()
    record = await rig.job("000001", content=None)
    assert record["config_missing"] is True and record.get("config_hash") is None
    assert rig.db.get_job("000001")["config_missing"] == 1


async def test_tail_uses_range(rig, monkeypatch):
    big = SAMPLE[:200] + b"; padding\n" * 200_000 + SAMPLE
    record = await rig.job("000001", content=big)
    assert record["config_hash"] and rig.fake.range_requests == 2


async def test_tail_grows_when_config_is_far_from_the_end(rig, monkeypatch):
    monkeypatch.setattr(moonraker_module, "TAIL_BYTES", 1024)
    big = SAMPLE + b"; padding\n" * 1000
    record = await rig.job("000001", content=big)
    assert record["config_hash"] and rig.fake.range_requests >= 3


async def test_no_range_support_streams_the_file(rig):
    rig.fake.range_supported = False
    record = await rig.job("000001")
    assert record["slicer"] == "OrcaSlicer" and record["config_hash"]


async def test_non_orca_gcode_has_config_without_presets_files(rig):
    content = b"; generated by PrusaSlicer 2.8.1 on 2025\nG28\n; CONFIG_BLOCK_START\n; layer_height = 0.2\n; CONFIG_BLOCK_END\n"
    record = await rig.job("000001", content=content)
    assert record["slicer"] == "PrusaSlicer" and record["commit_sha"]
    assert git(rig.repo, "ls-files").split() == ["effective.ini"]


async def test_thumbnail(rig):
    rig.fake.metadata["sub/p.gcode"] = {"thumbnails": [
        {"width": 32, "relative_path": ".thumbs/p-32.png"},
        {"width": 300, "relative_path": ".thumbs/p-300.png"},
        {"width": 900, "relative_path": ".thumbs/p-900.png"}]}
    rig.fake.thumbs["sub/.thumbs/p-300.png"] = b"PNGDATA"
    record = await rig.job("000001", filename="sub/p.gcode")
    assert record["thumbnail"] == "000001.png"
    assert (rig.history.thumbs / "000001.png").read_bytes() == b"PNGDATA"


def test_commit_is_idempotent(tmp_path):
    repo = GitHistory(tmp_path / "g")
    record = {"job_id": "1", "filename": "a", "status": "completed"}
    assert repo.commit(record, {"a": "1"}, {})[0]
    assert repo.commit(record, {"a": "1"}, {})[0] is None


def test_diff_and_sanitise():
    assert diff_configs({"a": "1", "different_settings_to_system": "x"}, {"a": "2", "b": "3"}) == [
        {"key": "a", "old": "1", "new": "2"}, {"key": "b", "old": None, "new": "3"}]
    assert sanitise("../../etc/passwd") == "_.._etc_passwd"
    assert sanitise("0.24mm Draft @Creality K1C") == "0.24mm Draft @Creality K1C"
    assert sanitise("...") == "unnamed"
