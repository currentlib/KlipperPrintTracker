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

from app.config import Options, PrinterOptions  # noqa: E402
from app.db import Database  # noqa: E402
from app.links import Links  # noqa: E402
from app.ratings import Ratings  # noqa: E402
from app.settings_git import SettingsHistory  # noqa: E402
from app.slicer_meta import LayoutStore  # noqa: E402
from app.web import create_app  # noqa: E402

SAMPLE = (ROOT / "tests/fixtures/sample_tail.gcode").read_text(encoding="utf-8")
PARTS = ["Bracket", "ShoeRack", "Clip", "Hinge", "CableGuide", "Knob", "Spacer"]
FILES = ["ShoeRack_PETG_1h40m", "Bracket_set_x4_PETG_2h15m", "CableGuide_desk_mount_right_side_v3_final_PLA_55m",
         "Hinge_0.2mm_PETG", "Knob_PLA_25m"]
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


async def seed(db, history, thumbs, count=30):
    rng = random.Random(7)
    text = SAMPLE
    now = time.time()
    thumbs.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        status = rng.choices(["completed", "cancelled", "error"], [8, 2, 1])[0]
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
        (thumbs / f"{job_id}.png").write_bytes(thumbnail(i % 5))
        record = {
            "job_id": job_id, "filename": f"{FILES[i % len(FILES)]}.gcode", "status": status,
            "end_time": now - (count - i) * 36000, "start_time": now - (count - i) * 36000 - 3600,
            "print_duration": rng.randint(600, 14000), "planned": sum(planned.values()), "parts": parts,
            "printed": printed, "excluded": excluded, "grams": grams, "filament_mm": round(grams * 330),
            "kwh": kwh, "spool": SPOOLS[i % len(SPOOLS)], "price_kg": 350, "energy_cost": energy_cost,
            "filament_cost": filament_cost, "total_cost": total, "per_part": round(total / parts, 2) if parts else 0,
            "wasted_cost": 0 if status == "completed" else total, "live_data": i % 9 != 4,
        }
        history.moonraker.parts = (text[:600], text)
        await history.snapshot(record)
        record["thumbnail"] = f"{job_id}.png"
        db.save_job(record)


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
    history = SettingsHistory(db, moonraker, layouts, data)
    if not args.empty:
        await seed(db, history, history.thumbs)
    tracker = Tracker()
    tracker.moonraker, tracker.printer = moonraker, PrinterOptions(name="Creality K1C")
    services = SimpleNamespace(options=Options(currency="UAH"), db=db, trackers={"printer1": tracker},
                               layouts=layouts, links=Links("local_klipper_print_tracker"),
                               thumbs=history.thumbs, mqtt=None, ratings=Ratings(db))
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
