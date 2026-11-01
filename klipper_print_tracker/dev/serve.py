"""UI dev server with a seeded database, no Moonraker or Home Assistant needed.

python dev/serve.py [--empty] [--port 8099]

Open /harness?theme=dark to run the app in a frame with HA's variables on the parent.
"""
import argparse
import asyncio
import random
import struct
import sys
import tempfile
import time
import zlib
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from aiohttp import web  # noqa: E402

from app.calibration import Calibrations  # noqa: E402
from app.config import Options, PrinterOptions  # noqa: E402
from app.db import Database  # noqa: E402
from app.links import Links  # noqa: E402
from app.maintenance import Maintenance  # noqa: E402
from app.projects import Projects  # noqa: E402
from app.ratings import Ratings  # noqa: E402
from app.settings_git import SettingsHistory  # noqa: E402
from app.slicer_meta import LayoutStore  # noqa: E402
from app.web import create_app  # noqa: E402

SAMPLE = (ROOT / "tests/fixtures/sample_tail.gcode").read_text(encoding="utf-8")
PARTS = ["Bracket", "ShoeRack", "Clip", "Hinge", "CableGuide", "Knob", "Spacer"]
FILES = ["ShoeRack_PETG_1h40m", "Bracket_set_x4_PETG_2h15m", "CableGuide_desk_mount_right_side_v3_final_PLA_55m",
         "Hinge_0.2mm_PETG", "Knob_PLA_25m"]
TAGS = ["stringing", "warping", "погана адгезія першого шару", "зсув шару", "недоекструзія", "артефакти шва"]
REASONS = ["adhesion", "spaghetti", "clog", "other"]
CALIBRATIONS = [("temperature", {"start": 230, "end": 190, "step": -5}, 240.0),
                ("pa_tower", {"start": 0, "end": 0.1, "step": 0.002}, 0.042),
                ("flow_pass2", None, 1.05), ("retraction", {"start": 0, "end": 2, "step": 0.1}, 0.8),
                ("max_volumetric_speed", {"start": 5, "end": 25, "step": 0.5}, 18.0)]
SPOOLS = ["SkyWire Чорний PETG", "LBL Білий Флок", "Polymaker PolyTerra PLA"]
EDITS = [("; outer_wall_speed = 200", "; outer_wall_speed = 180"),
         ("; filament_flow_ratio = 1.067,1.05", "; filament_flow_ratio = 1.04,1.05"),
         ("; sparse_infill_density = 15%", "; sparse_infill_density = 25%"),
         ("; print_settings_id = 0.24mm Draft @Creality K1C", "; print_settings_id = 0.20mm Standard @Creality K1C"),
         ("; layer_height = 0.24", "; layer_height = 0.2")]


def thumbnail(seed: int) -> bytes:
    """A small block on a plate, stands in for the slicer's preview."""
    rng = random.Random(seed)
    size = 96
    inset = rng.randint(14, 30)
    hue = rng.choice([(70, 120, 210), (210, 120, 60), (90, 170, 110), (170, 90, 190)])
    rows = bytearray()
    for y in range(size):
        rows.append(0)
        for x in range(size):
            inside = inset <= x < size - inset and inset <= y < size - inset
            rows += bytes((*hue, 255)) if inside else bytes((0, 0, 0, 0))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(rows))) + chunk(b"IEND", b"")


class Moonraker:
    connected = True
    parts = None

    async def gcode_parts(self, filename):
        return self.parts

    async def metadata(self, filename):
        return {}


class Tracker:
    async def reconcile(self):
        return 0


async def seed(db, histories, calibrations, maintenance, projects, thumbs, count=34):
    rng = random.Random(7)
    text = SAMPLE
    now = time.time()
    thumbs.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        printer = "printer2" if i % 6 == 5 else "printer1"
        history = histories[printer]
        status = rng.choices(["completed", "cancelled", "error"], [8, 2, 2])[0]
        if i % 6 == 3:
            old, new = EDITS[(i // 6) % len(EDITS)]
            text = text.replace(old, new)
        names = rng.sample(PARTS, rng.randint(1, 3))
        planned = {name: rng.randint(1, 4) for name in names}
        excluded = {names[0]: 1} if rng.random() < 0.25 else {}
        printed = {} if status != "completed" else {n: c - excluded.get(n, 0) for n, c in planned.items()}
        printed = {n: c for n, c in printed.items() if c}
        parts = sum(printed.values())
        grams = round(rng.uniform(4, 120) * (1 if status == "completed" else 0.4), 1)
        kwh = None if i % 11 == 5 else round(rng.uniform(0.05, 0.9), 3)
        filament_cost = round(grams / 1000 * 350, 2)
        energy_cost = round((kwh or 0) * 4.32, 2)
        total = round(filament_cost + energy_cost, 2)
        job_id = f"{i + 1:06}"
        material = "PETG" if i % 3 else "PLA"
        interruption = {"completed": None, "cancelled": "cancelled", "error": "error"}[status]
        if status == "error" and i % 4 == 0:
            interruption = "power_or_offline"
        rated = rng.random() < 0.8
        tags = rng.sample(TAGS, rng.randint(0, 2)) if rated and rng.random() < 0.5 else []
        (thumbs / f"{job_id}.png").write_bytes(thumbnail(i % 5))
        record = {
            "job_id": job_id, "filename": f"{FILES[i % len(FILES)]}.gcode", "status": status,
            "end_time": now - (count - i) * 36000, "start_time": now - (count - i) * 36000 - 3600,
            "print_duration": rng.randint(600, 14000), "planned": sum(planned.values()), "parts": parts,
            "printed": printed, "excluded": excluded, "grams": grams, "filament_mm": round(grams * 330),
            "kwh": kwh, "spool": SPOOLS[i % len(SPOOLS)], "price_kg": 350, "energy_cost": energy_cost,
            "filament_cost": filament_cost, "total_cost": total, "per_part": round(total / parts, 2) if parts else 0,
            "wasted_cost": 0 if status == "completed" else total, "live_data": i % 9 != 4, "printer_id": printer,
            "interruption": interruption, "progress": None if status == "completed" else round(rng.uniform(1, 95), 1),
            "current_layer": None if status == "completed" else rng.choice([1, 1, 2, 7, 30, 64, 120]), "total_layer": 150,
            "chamber_temp": None if status == "completed" else 41.0,
            "error_message": "Heater extruder not heating at expected rate" if status == "error" and interruption == "error" else None,
            "rating": ("good" if status == "completed" and rng.random() < 0.85 else "bad") if rated else None, "issues": tags,
            "failure_reason": rng.choice(REASONS) if status != "completed" and rated else None,
            "spool_id": 1 + i % 3,
            "spool_check": {"required_g": grams, "remaining_g": grams * 0.7, "warnings": [
                {"code": "not_enough", "required_g": grams, "remaining_g": round(grams * 0.7, 1)},
                {"code": "preset_mismatch", "info": True, "preset": "SkyWire PETG Чорний"}], "paused": False} if i % 10 == 2 else None,
        }
        history.moonraker.parts = (text[:600], text)
        await history.snapshot(record)
        record["thumbnail"] = f"{job_id}.png"
        record["material"] = material
        record.pop("gcode_head", None)
        db.save_job(record)
        if i % 7 == 1:
            kind, tested, value = CALIBRATIONS[(i // 7) % len(CALIBRATIONS)]
            calibrations.save(record, kind, tested, True, value)
            await calibrations.set_value(printer, job_id, value)
    for printer in histories:
        maintenance.ensure_defaults(printer)
    tasks = maintenance.tasks("printer1")
    maintenance.confirm("printer1", {str(t["id"]): now - (40 + 13 * i) * 86400 for i, t in enumerate(tasks)})
    await maintenance.done(tasks[3]["id"], "Протер, змастив")
    projects.save({"name": "Полиця для взуття", "description": "Для передпокою", "deadline": "2026-12-20", "targets": [
        {"part": "ShoeRack", "quantity": 10}, {"part": "Bracket", "quantity": 4}],
        "rules": [{"kind": "file", "pattern": "ShoeRack*"}, {"kind": "file", "pattern": "Bracket*"}]})
    projects.save({"name": "Органайзер кабелів", "targets": [{"part": "CableGuide", "quantity": 8}, {"part": "Clip", "quantity": 12}],
                   "rules": [{"kind": "file", "pattern": "CableGuide*"}]})
    for job in db.jobs(limit=1000)[0]:
        await projects.job_finished(job)


async def harness(request):
    return web.FileResponse(Path(__file__).parent / "harness.html")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--empty", action="store_true")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--fonts", type=Path, help="folder with Roboto woff2 files for the harness")
    args = parser.parse_args()

    data = Path(tempfile.mkdtemp())
    db = Database(data / "tracker.db")
    moonraker = Moonraker()
    layouts = LayoutStore(data / "layouts", auto_fetch=False)
    printers = [PrinterOptions("printer1", "Creality K1C"), PrinterOptions("printer2", "Voron 0")]
    histories = {p.id: SettingsHistory(db, moonraker, layouts, data, p.id) for p in printers}
    thumbs = histories["printer1"].thumbs
    calibrations = Calibrations(db, Options(), {})
    maintenance = Maintenance(db, Options())
    projects = Projects(db)
    if not args.empty:
        await seed(db, histories, calibrations, maintenance, projects, thumbs)
    trackers = {}
    for printer in printers[:None if not args.empty else 1]:
        trackers[printer.id] = Tracker()
        trackers[printer.id].moonraker, trackers[printer.id].printer = moonraker, printer
    services = SimpleNamespace(options=Options(currency="UAH"), db=db, trackers=trackers,
                               layouts=layouts, links=Links("local_klipper_print_tracker"),
                               thumbs=thumbs, mqtt=None, ratings=Ratings(db), maintenance=maintenance,
                               calibrations=calibrations, projects=projects)
    app = create_app(services, allowed_peer=None)
    app.router.add_get("/harness", harness)
    if args.fonts:
        app.router.add_static("/dev-fonts", args.fonts)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", args.port).start()
    print(f"http://localhost:{args.port}/harness?theme=dark", flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
