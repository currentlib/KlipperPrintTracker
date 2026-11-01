import asyncio
import json
from pathlib import Path

import aiohttp

from app import __main__ as entry
from app import tracker as tracker_module
from fake_moonraker import FakeMoonraker, settle

SAMPLE = (Path(__file__).parent / "fixtures" / "sample_tail.gcode").read_bytes()


async def test_whole_add_on(tmp_path, monkeypatch):
    fake = FakeMoonraker()
    url = await fake.start()
    fake.files["plate.gcode"] = SAMPLE
    (tmp_path / "options.json").write_text(json.dumps({
        "moonraker_url": url, "default_filament_price": 800, "auto_fetch_layouts": False, "log_level": "warning"}))
    monkeypatch.setattr(entry, "DATA_DIR", tmp_path)
    monkeypatch.setattr(entry, "load_options", lambda: entry_options(tmp_path))
    monkeypatch.setattr(tracker_module, "FINISH_DELAY", 0.01)
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    task = asyncio.create_task(entry.main())
    await settle(lambda: fake.connections == 1, timeout=5)
    try:
        async with aiohttp.ClientSession() as session:
            await settle(lambda: fake.clients)
            await asyncio.sleep(0.1)
            job = await fake.add_job("000001", "plate.gcode",
                                     metadata={"filament_weight_total": 100, "filament_total": 1000})
            await fake.emit({"print_stats": {"state": "printing", "filename": "plate.gcode"}})
            await asyncio.sleep(0.05)
            await fake.emit({"exclude_object": {"objects": [{"name": "Cube_id_0_copy_0"}]}})
            await asyncio.sleep(0.05)
            await fake.finish_job(job, "completed", filament_used=1000)
            await fake.emit({"print_stats": {"state": "complete"}})
            for _ in range(200):
                async with session.get("http://127.0.0.1:8100/api/stats") as response:
                    stats = await response.json()
                if stats["total"]:
                    break
                await asyncio.sleep(0.02)
            assert stats["parts"] == 1 and stats["top_parts"] == [{"name": "Cube", "count": 1}]
            async with session.get("http://127.0.0.1:8100/api/job/000001") as response:
                data = await response.json()
            assert data["slicer"] == "OrcaSlicer" and data["commit"]
            assert data["settings"][0]["pages"][0]["title"] == "Якість"
            async with session.get("http://127.0.0.1:8099/api/stats") as response:
                assert response.status == 403
        assert (tmp_path / "tracker.db").exists() and (tmp_path / "git" / "effective.ini").exists()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await fake.stop()


def entry_options(path):
    from app.config import load_options
    return load_options(path / "options.json")
