"""Web UI and internal API. Works under the ingress prefix through relative URLs only."""
import csv
import io
import logging
from datetime import datetime, timedelta
from pathlib import Path

from aiohttp import web

from . import summary, views
from .settings_git import diff_configs, short_changes

log = logging.getLogger(__name__)

SERVICES = web.AppKey("services", object)
STATIC = Path(__file__).parent / "static"
INGRESS_PROXY = "172.30.32.2"
MAX_PAGE = 500
CSV_COLUMNS = {
    "date": "date", "file": "file", "status": "status", "parts": "parts", "planned": "planned",
    "excluded": "excluded", "minutes": "minutes", "grams": "grams", "kwh": "kwh", "cost": "cost",
    "per_part": "cost_per_part", "spool": "spool", "job_id": "job_id",
}


def peer_filter(allowed: str | None):
    """Ingress only: the Supervisor proxy is the single allowed client."""

    @web.middleware
    async def middleware(request, handler):
        if allowed and request.remote != allowed:
            raise web.HTTPForbidden(text="Only the ingress proxy can connect here")
        return await handler(request)

    return middleware


@web.middleware
async def read_only(request, handler):
    """The direct port has no login, so nothing can be changed through it."""
    if request.method not in ("GET", "HEAD"):
        raise web.HTTPForbidden(text="The direct port is read-only")
    return await handler(request)


def create_app(services, ingress: bool = True, allowed_peer: str | None = INGRESS_PROXY) -> web.Application:
    middlewares = [peer_filter(allowed_peer)] if ingress else [read_only]
    app = web.Application(middlewares=middlewares)
    app[SERVICES] = services
    app.add_routes([
        web.get("/", index),
        web.get("/api/health", health),
        web.get("/api/stats", stats),
        web.get("/api/jobs", jobs),
        web.get("/api/jobs.csv", jobs_csv),
        web.get("/api/job/{job_id}", job),
        web.get("/api/compare/{a}/{b}", compare),
        web.get("/api/part/{name}", part),
        web.get("/api/preset/{kind}/{name}", preset),
        web.post("/api/reconcile", reconcile),
        web.static("/static", STATIC),
        web.get("/thumbs/{name}", thumbnail),
    ])
    return app


def _services(request):
    return request.app[SERVICES]


async def index(request):
    return web.FileResponse(STATIC / "index.html")


async def health(request):
    s = _services(request)
    return web.json_response({"status": "ok", "moonraker": s.moonraker.connected,
                              "mqtt": bool(s.mqtt and s.mqtt.client)})


def _row(record: dict, links) -> dict:
    row = summary.recent_row(record, links)
    return {**row, "job_id": record["job_id"], "file": summary.display_name(record.get("filename")),
            "end_time": record.get("end_time"),
            "thumbnail": record.get("thumbnail") and f"thumbs/{record['thumbnail']}",
            "changed": len(short_changes(record)), "kwh": record.get("kwh"),
            "live_data": bool(record.get("live_data")), "spool": record.get("spool") or "",
            "excluded_names": ", ".join(record.get("excluded") or {})}


async def stats(request):
    s = _services(request)
    recent, _ = s.db.jobs(limit=10)
    return web.json_response({
        **s.db.stats(), "currency": summary.display_currency(s.options.currency),
        "recent": [_row(j, s.links) for j in recent],
        "top_parts": s.db.top_parts(), "top_excluded": s.db.top_excluded()})


def _date(value: str | None, days: int = 0) -> float | None:
    if not value:
        return None
    try:
        return (datetime.strptime(value, "%Y-%m-%d") + timedelta(days=days)).timestamp()
    except ValueError as err:
        raise web.HTTPBadRequest(text=f"Bad date: {value}") from err


def _filters(request) -> dict:
    q = request.query
    return {"file": q.get("file") or None, "status": q.get("status") or None,
            "preset": q.get("preset") or None, "spool": q.get("spool") or None,
            "date_from": _date(q.get("from")), "date_to": _date(q.get("to"), 1)}


def _int(request, name: str, default: int) -> int:
    try:
        return max(0, int(request.query.get(name, default)))
    except ValueError as err:
        raise web.HTTPBadRequest(text=f"Bad {name}") from err


async def jobs(request):
    s = _services(request)
    rows, total = s.db.jobs(**_filters(request), limit=min(_int(request, "limit", 50), MAX_PAGE),
                            offset=_int(request, "offset", 0), sort=request.query.get("sort", "date"),
                            descending=request.query.get("dir", "desc") != "asc")
    return web.json_response({"jobs": [_row(j, s.links) for j in rows], "total": total,
                              "facets": s.db.facets(),
                              "currency": summary.display_currency(s.options.currency)})


def _csv_cell(value):
    """A file name must not run as a formula when the CSV is opened in a spreadsheet."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return "" if value is None else value


async def jobs_csv(request):
    s = _services(request)
    rows, _ = s.db.jobs(**_filters(request), limit=100000)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(CSV_COLUMNS)
    for record in rows:
        job_data = {**summary.job_summary(record, s.links),
                    "date": datetime.fromtimestamp(record["end_time"] or 0).strftime("%Y-%m-%d %H:%M")}
        writer.writerow([_csv_cell(job_data.get(key)) for key in CSV_COLUMNS.values()])
    return web.Response(text=out.getvalue(), content_type="text/csv", headers={
        "Content-Disposition": 'attachment; filename="prints.csv"'})


def _get_job(request, key: str = "job_id") -> dict:
    record = _services(request).db.get_job(request.match_info[key])
    if record is None:
        raise web.HTTPNotFound(text="No such job")
    return record


async def job(request):
    s = _services(request)
    record = _get_job(request)
    config = s.db.get_config(record["config_hash"])
    layout = await s.layouts.get(record["slicer"], record["slicer_version"])
    changes = {}
    for kind, change in (record.get("changes") or {}).items():
        other = s.db.get_job(change["job_id"])
        changes[kind] = {"job_id": change["job_id"], "diff": views.labelled_diff(change["diff"], layout),
                         "file": summary.display_name(other["filename"]) if other else None}
    drift = {name: views.labelled_diff(diff, layout) for name, diff in (record.get("preset_drift") or {}).items()}
    return web.json_response({
        **_row(record, s.links), "currency": summary.display_currency(s.options.currency),
        "filename": record["filename"], "printed": record["printed"], "excluded": record["excluded"],
        "filament_mm": record["filament_mm"], "energy_cost": record["energy_cost"],
        "filament_cost": record["filament_cost"], "total_cost": record["total_cost"],
        "wasted_cost": record["wasted_cost"], "config_missing": bool(record["config_missing"]),
        "slicer": record["slicer"], "slicer_version": record["slicer_version"],
        "presets": record["presets"] or {}, "commit": record["commit_sha"], "drift": drift, "changes": changes,
        "settings": views.settings_tabs(config, layout) if config else []})


async def compare(request):
    s = _services(request)
    a, b = _get_job(request, "a"), _get_job(request, "b")
    config_a, config_b = s.db.get_config(a["config_hash"]), s.db.get_config(b["config_hash"])
    if config_a is None or config_b is None:
        raise web.HTTPNotFound(text="Settings of this job aren't available")
    version = views.newer_version(a["slicer_version"], b["slicer_version"])
    slicer = a["slicer"] if a["slicer_version"] == version else b["slicer"]
    layout = await s.layouts.get(slicer, version)
    return web.json_response({
        "a": _row(a, s.links), "b": _row(b, s.links),
        "tabs": views.compare_tabs(config_a, config_b, layout)})


async def part(request):
    s = _services(request)
    name = request.match_info["name"]
    records = s.db.part_jobs(name)
    if not records:
        raise web.HTTPNotFound(text="No such part")
    rows, previous = [], None
    for record in records:
        config = s.db.get_config(record["config_hash"])
        changed = [d["key"] for d in diff_configs(previous, config)] if config and previous else []
        previous = config or previous
        rows.append({**_row(record, s.links), "part_printed": record["part_printed"],
                     "part_excluded": record["part_excluded"], "changes": changed})
    printed = sum(r["part_printed"] for r in rows)
    excluded = sum(r["part_excluded"] for r in rows)
    attempts = printed + excluded
    return web.json_response({
        "name": name, "printed": printed, "excluded": excluded,
        "currency": summary.display_currency(s.options.currency),
        "success_rate": round(100 * printed / attempts, 1) if attempts else 0, "jobs": rows})


async def preset(request):
    s = _services(request)
    kind, name = request.match_info["kind"], request.match_info["name"]
    if kind not in views.TAB_ORDER:
        raise web.HTTPNotFound(text="No such preset type")
    records = s.db.preset_jobs(kind, name)
    if not records:
        raise web.HTTPNotFound(text="No such preset")
    layout = None
    for record in reversed(records):
        layout = await s.layouts.get(record["slicer"], record["slicer_version"])
        if layout:
            break
    keys = layout["preset_keys"][kind] if layout else []
    timeline, previous = [], None
    for record in records:
        values = views.preset_values(s.db.get_config(record["config_hash"]), kind, name, keys)
        if previous is None or previous != values:
            timeline.append({**_row(record, s.links), "first": previous is None,
                             "diff": views.labelled_diff(diff_configs(previous or values, values), layout)})
        previous = values
    return web.json_response({"kind": kind, "name": name, "prints": len(records),
                              "timeline": timeline[::-1]})


async def reconcile(request):
    added = await _services(request).tracker.reconcile()
    return web.json_response({"added": added})


async def thumbnail(request):
    name = Path(request.match_info["name"]).name
    path = _services(request).thumbs / name
    if not path.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(path)
