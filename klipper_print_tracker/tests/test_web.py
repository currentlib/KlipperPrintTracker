import re
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urljoin

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app import web as web_module
from app.config import Options
from app.db import Database
from app.links import Links
from app.calibration import Calibrations
from app.maintenance import Maintenance
from app.projects import Projects
from app.ratings import Ratings
from app.settings_git import SettingsHistory
from app.slicer_meta import LayoutStore
from app.web import create_app

SAMPLE = (Path(__file__).parent / "fixtures" / "sample_tail.gcode").read_text(encoding="utf-8")
PREFIX = "/api/hassio_ingress/abc123token/"
STATIC = Path(web_module.__file__).parent / "static"


class Tracker:
    calls = 0

    async def reconcile(self):
        Tracker.calls += 1
        return 2


class NoMoonraker:
    connected = True
    printer = Options(moonraker_url="http://a.example").printers[0]

    def __init__(self, parts):
        self.parts = parts

    async def gcode_parts(self, filename):
        return self.parts

    async def metadata(self, filename):
        return {}


@pytest.fixture
async def services(tmp_path):
    db = Database(tmp_path / "t.db")
    layouts = LayoutStore(tmp_path / "layouts", auto_fetch=False)
    moonraker = NoMoonraker((SAMPLE[:400], SAMPLE))
    history = SettingsHistory(db, moonraker, layouts, tmp_path)
    links = Links("slug_x")

    async def add(job_id, end, text=SAMPLE, filename="plate.gcode", **extra):
        moonraker.parts = (text[:400], text)
        record = {"job_id": job_id, "filename": filename, "status": "completed", "end_time": end,
                  "start_time": end - 60, "print_duration": 3600, "planned": 3, "parts": 2,
                  "printed": {"Bracket": 2}, "excluded": {"Clip": 1}, "grams": 10, "kwh": 0.5,
                  "total_cost": 20, "per_part": 10, "wasted_cost": 0, "energy_cost": 1, "filament_cost": 19,
                  "live_data": True, "filament_mm": 100, "spool": "PETG", **extra}
        await history.snapshot(record)
        db.save_job(record)

    await add("000001", 1000000.0)
    await add("000002", 1000100.0, SAMPLE.replace("; outer_wall_speed = 200", "; outer_wall_speed = 180"),
              status="cancelled", spool="PLA")
    await add("000003", 1000200.0, filename="-danger.gcode",
              printed={"Clip": 1}, excluded={})
    tracker = Tracker()
    tracker.moonraker, tracker.printer = moonraker, NoMoonraker.printer
    yield SimpleNamespace(options=Options(currency="UAH"), db=db, trackers={"printer1": tracker},
                          layouts=layouts, links=links, thumbs=tmp_path / "thumbs", mqtt=None, ratings=Ratings(db),
                          maintenance=Maintenance(db, Options()), calibrations=Calibrations(db, Options(), {}), projects=Projects(db))
    db.close()


@pytest.fixture
async def client(services):
    server = TestServer(create_app(services, allowed_peer="127.0.0.1"))
    async with TestClient(server) as test_client:
        yield test_client


async def test_connections_from_elsewhere_are_refused(services):
    async with TestClient(TestServer(create_app(services))) as test_client:
        response = await test_client.get("/api/health")
        assert response.status == 403


async def test_direct_port_is_read_only(services):
    async with TestClient(TestServer(create_app(services, ingress=False))) as test_client:
        assert (await test_client.get("/api/stats")).status == 200
        assert (await test_client.post("/api/reconcile")).status == 403


async def test_health_and_reconcile(client):
    assert (await (await client.get("/api/health")).json())["status"] == "ok"
    assert await (await client.post("/api/reconcile")).json() == {"added": 2}


async def test_stats(client):
    data = await (await client.get("/api/stats")).json()
    assert data["total"] == 3 and data["currency"] == "грн"
    assert data["recent"][0]["job_id"] == "000003"
    assert data["top_parts"][0] == {"name": "Bracket", "count": 4}


async def test_job_list_filters(client):
    data = await (await client.get("/api/jobs?status=cancelled")).json()
    assert [j["job_id"] for j in data["jobs"]] == ["000002"]
    assert data["jobs"][0]["changed"] == 1
    assert (await (await client.get("/api/jobs?spool=PLA")).json())["total"] == 1
    assert (await (await client.get("/api/jobs?file=plate")).json())["total"] == 2
    data = await (await client.get("/api/jobs?preset=0.24mm Draft @Creality K1C")).json()
    assert data["total"] == 3
    assert {"type": "process", "name": "0.24mm Draft @Creality K1C"} in data["facets"]["presets"]
    assert (await (await client.get("/api/jobs?to=1969-01-01")).json())["total"] == 0
    assert (await client.get("/api/jobs?from=nonsense")).status == 400


async def test_job_list_sort(client):
    data = await (await client.get("/api/jobs?sort=spool&dir=asc")).json()
    assert data["jobs"][0]["spool"] == "PETG" and data["jobs"][-1]["spool"] == "PLA"
    data = await (await client.get("/api/jobs?sort=bobby;drop")).json()
    assert data["jobs"][0]["job_id"] == "000003"


async def test_csv_export_is_safe(client):
    text = await (await client.get("/api/jobs.csv")).text()
    lines = text.strip().splitlines()
    assert lines[0].startswith("date,file,status") and len(lines) == 4
    assert ",'-danger," in lines[1]


async def test_job_page_data(client):
    data = await (await client.get("/api/job/000002")).json()
    assert data["slicer_version"] == "2.3.2"
    assert data["printed"] == {"Bracket": 2} and data["excluded"] == {"Clip": 1}
    assert [t["id"] for t in data["settings"]] == ["process", "filament", "printer", "other"]
    quality = data["settings"][0]["pages"][0]
    assert quality["title"] == "Якість"
    row = quality["groups"][0]["rows"][0]
    assert row["key"] == "layer_height" and row["label"] == "Висота шару"
    assert row["unit"] == "мм" and row["raw"] == "0.24" and row["tooltip"]
    change = data["changes"]["file"]
    assert change["ref"] == "printer1:000001" and change["diff"][0]["key"] == "outer_wall_speed"
    assert change["diff"][0]["old"]["raw"] == "200" and change["diff"][0]["new"]["raw"] == "180"
    assert "process/0.24mm Draft @Creality K1C" in data["drift"]


async def test_enum_and_bool_values_use_labels(client):
    data = await (await client.get("/api/job/000001")).json()
    rows = {r["key"]: r for t in data["settings"] for p in t["pages"] for g in p["groups"] for r in g["rows"]}
    assert rows["seam_position"]["raw"] == "aligned"
    assert rows["seam_position"]["text"] not in ("aligned", "Aligned")
    assert rows["spiral_mode"]["flags"] == [False]
    assert rows["different_settings_to_system"]["label"]


async def test_job_refs(client):
    assert (await (await client.get("/api/job/printer1:000002")).json())["ref"] == "printer1:000002"
    assert (await client.get("/api/job/printer2:000002")).status == 404


async def test_unknown_job(client):
    assert (await client.get("/api/job/nope")).status == 404
    assert (await client.get("/api/compare/000001/nope")).status == 404


async def test_compare_only_differing_keys(client):
    data = await (await client.get("/api/compare/000001/000002")).json()
    rows = [r for t in data["tabs"] for p in t["pages"] for g in p["groups"] for r in g["rows"]]
    assert [r["key"] for r in rows] == ["outer_wall_speed"]
    assert rows[0]["a"]["raw"] == "200" and rows[0]["b"]["raw"] == "180"
    assert data["tabs"][0]["id"] == "process"


async def test_part_page(client):
    data = await (await client.get("/api/part/Clip")).json()
    assert data["printed"] == 1 and data["excluded"] == 2 and data["success_rate"] == 33.3
    assert data["jobs"][1]["changes"] == ["outer_wall_speed"]
    assert (await client.get("/api/part/none")).status == 404


async def test_preset_timeline(client):
    data = await (await client.get("/api/preset/process/0.24mm Draft @Creality K1C")).json()
    assert data["prints"] == 3
    timeline = data["timeline"]
    assert [t["job_id"] for t in timeline] == ["000003", "000002", "000001"]
    assert timeline[-1]["first"] is True
    assert timeline[1]["diff"][0]["key"] == "outer_wall_speed"
    assert (await client.get("/api/preset/nope/x")).status == 404


async def test_thumbnail_cant_leave_the_folder(client, services):
    services.thumbs.mkdir()
    (services.thumbs / "a.png").write_bytes(b"png")
    assert (await client.get("/thumbs/a.png")).status == 200
    assert (await client.get("/thumbs/..%2Ft.db")).status == 404


async def test_everything_resolves_under_the_ingress_prefix(client):
    """Follow what the browser would, with the page served at the ingress prefix."""
    headers = {"X-Ingress-Path": PREFIX.rstrip("/")}
    page = await (await client.get("/", headers=headers)).text()
    assets = re.findall(r'(?:src|href)="([^"]+)"', page)
    assert len(assets) == 6
    for asset in assets:
        url = urljoin(PREFIX, asset)
        assert url.startswith(PREFIX)
        assert (await client.get("/" + url.removeprefix(PREFIX), headers=headers)).status == 200

    script = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "fetch(`api/${path}`)" in script
    calls = re.findall(r'api\((?:scoped\()?`?"?([a-z]+)', script)
    assert set(calls) >= {"stats", "jobs", "job", "compare", "part", "preset"}
    for call in ("stats", "jobs", "job/000001", "compare/000001/000002", "part/Clip"):
        url = urljoin(PREFIX, f"api/{call}")
        assert url.startswith(PREFIX)
        assert (await client.get("/" + url.removeprefix(PREFIX), headers=headers)).status == 200


def test_frontend_has_no_absolute_urls():
    for name in sorted(p.name for p in STATIC.iterdir() if p.suffix in (".html", ".js", ".css")):
        text = (STATIC / name).read_text(encoding="utf-8")
        assert not re.search(r"""(?:src|href|fetch\(|url\()\s*=?\s*["'`(]/""", text), name
        assert "http://" not in text and "https://" not in text


def test_all_strings_are_defined():
    script = (STATIC / "app.js").read_text(encoding="utf-8") + (STATIC / "ui.js").read_text(encoding="utf-8")
    strings = (STATIC / "strings.uk.js").read_text(encoding="utf-8")
    defined = set(re.findall(r"(\w+):", strings))
    used = set(re.findall(r"\bS\.(\w+)", script))
    assert used <= defined, used - defined
    keys = re.findall(r"""icon\(\s*["']([a-z0-9-]+)["']|iconName: ["']([a-z0-9-]+)["']""", script)
    icons = (STATIC / "icons.js").read_text(encoding="utf-8")
    assert keys and all(f'"{a or b}":' in icons for a, b in keys)


def test_deep_link_route_regex_matches_real_paths():
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    pattern = re.search(r"const ROUTE = /(.+)/;", script).group(1).replace(r"\/", "/")
    assert re.search(pattern, "/app/abc_klipper_print_tracker/job/000001").group(0) == "/job/000001"
    assert re.search(pattern, "/abc_klipper_print_tracker/compare/1/2").group(0) == "/compare/1/2"
    assert re.search(pattern, "/app/abc_klipper_print_tracker") is None


async def test_rating_api(client, services):
    response = await client.post("/api/job/printer1:000001/rating", json={"rating": "good", "issues": ["warping"], "note": "ok"})
    data = await response.json()
    assert data["rating"] == "good" and data["issues"] == ["warping"] and data["note"] == "ok"
    assert (await client.post("/api/job/printer1:000001/rating", json={"rating": "meh"})).status == 400
    assert (await client.post("/api/job/printer1:000001/rating", json={"failure_reason": "x"})).status == 400
    assert (await (await client.get("/api/jobs?rating=good")).json())["total"] == 1
    assert (await (await client.get("/api/stats")).json())["unrated"] == 2


async def test_tags_api(client):
    assert "stringing" in (await (await client.get("/api/tags")).json())["tags"]
    data = await (await client.post("/api/tags", json={"tags": [" a ", "", "b"]})).json()
    assert data["tags"] == ["a", "b"]
    assert (await client.post("/api/tags", json={"tags": "a"})).status == 400


async def test_preset_timeline_has_results_per_value(client, services):
    services.db.update_job("000001", "printer1", rating="bad", issues=["stringing"])
    services.db.update_job("000002", "printer1", rating="good")
    services.db.update_job("000003", "printer1", rating="good")
    data = await (await client.get("/api/preset/process/0.24mm Draft @Creality K1C")).json()
    row = data["timeline"][1]["diff"][0]
    assert row["key"] == "outer_wall_speed" and row["new"]["raw"] == "180"
    assert row["results"] == {"good": 1, "bad": 0, "tags": {}}


async def test_maintenance_api(client, services):
    data = await (await client.get("/api/maintenance")).json()
    printer = data["printers"][0]
    assert printer["id"] == "printer1" and len(printer["tasks"]) == 12 and printer["needs_setup"]
    task = printer["tasks"][0]["id"]
    assert (await client.post("/api/maintenance/printer1/confirm", json={"dates": {str(task): "2026-01-01"}})).status == 200
    assert not (await (await client.get("/api/maintenance")).json())["printers"][0]["needs_setup"]
    assert (await client.post(f"/api/maintenance/task/{task}/done", json={"note": "x"})).status == 200
    assert (await client.post(f"/api/maintenance/task/{task}", json={"hours": 5})).status == 200
    assert services.maintenance.task(task)["hours"] == 5
    assert (await client.post("/api/maintenance/task/99999/done", json={})).status == 404
    created = await (await client.post("/api/maintenance/printer1", json={"name": "Нове", "days": 3})).json()
    assert (await client.delete(f"/api/maintenance/task/{created['id']}")).status == 200


async def test_direct_port_cant_delete(services):
    async with TestClient(TestServer(create_app(services, ingress=False))) as test_client:
        assert (await test_client.delete("/api/maintenance/task/1")).status == 403


async def test_calibration_api(client, services):
    job = await (await client.get("/api/job/printer1:000001")).json()
    assert job["calibration"] is None and "pa_tower" in job["calibration_types"]
    assert (await client.post("/api/job/printer1:000001/calibration", json={"type": "nope"})).status == 400
    response = await client.post("/api/job/printer1:000001/calibration", json={"type": "temperature", "start": 230, "end": 190, "step": -5, "value": "245"})
    data = await response.json()
    assert data["value"] == 245 and data["range_start"] == 230 and data["detected"] == 0
    data = await (await client.post("/api/job/printer1:000001/calibration", json={"value": "240"})).json()
    assert data["value"] == 240 and data["range_end"] == 190
    overview = await (await client.get("/api/calibration")).json()
    assert overview["presets"][0]["preset"] == "SkyWire PETG Чорний"


async def test_projects_api(client):
    created = await (await client.post("/api/projects", json={"name": "Полиця"})).json()
    project = created["id"]
    response = await client.post(f"/api/project/{project}", json={"targets": [{"part": "Bracket", "quantity": 4}]})
    assert response.status == 200
    assert (await client.post(f"/api/project/{project}", json={"targets": "x"})).status == 400
    assert (await client.post("/api/job/printer1:000001/project", json={"project_id": project})).status == 200
    data = await (await client.get(f"/api/project/{project}")).json()
    assert data["done"] == 2 and data["jobs"][0]["job_id"] == "000001"
    assert (await client.post("/api/job/printer1:000001/project", json={"project_id": 999})).status == 400
    assert (await (await client.get("/api/projects")).json())["projects"][0]["name"] == "Полиця"
    assert (await client.get("/api/project/abc")).status == 404
    assert (await client.delete(f"/api/project/{project}")).status == 200
