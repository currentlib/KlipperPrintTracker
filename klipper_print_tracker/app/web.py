"""Web UI and internal API. Works under the ingress prefix through relative URLs only."""
import csv
import io
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

from aiohttp import web

from . import analysis, summary, views
from .config import DEFAULT_PRINTER
from .ratings import FAILURE_REASONS
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
        web.get("/api/analysis", analysis_page),
        web.get("/api/maintenance", maintenance),
        web.post("/api/maintenance/{printer}", add_task),
        web.post("/api/maintenance/{printer}/confirm", confirm_tasks),
        web.post("/api/maintenance/task/{task}", edit_task),
        web.post("/api/maintenance/task/{task}/done", task_done),
        web.delete("/api/maintenance/task/{task}", delete_task),
        web.post("/api/job/{job_id}/rating", rate),
        web.get("/api/tags", tags),
        web.post("/api/tags", save_tags),
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
    printers = {t.printer.id: t.moonraker.connected for t in s.trackers.values()}
    return web.json_response({"status": "ok", "printers": printers,
                              "mqtt": bool(s.mqtt and s.mqtt.client)})


def _row(record: dict, links) -> dict:
    row = summary.recent_row(record, links)
    printer = record.get("printer_id", DEFAULT_PRINTER)
    return {**row, "job_id": record["job_id"], "printer_id": printer, "ref": f"{printer}:{record['job_id']}",
            "file": summary.display_name(record.get("filename")),
            "end_time": record.get("end_time"),
            "thumbnail": record.get("thumbnail") and f"thumbs/{record['thumbnail']}",
            "changed": len(short_changes(record)), "kwh": record.get("kwh"),
            "live_data": bool(record.get("live_data")), "spool": record.get("spool") or "",
            "excluded_names": ", ".join(record.get("excluded") or {}), "rating": record.get("rating"),
            "issues": record.get("issues") or [], "failure_reason": record.get("failure_reason"),
            "note": record.get("note") or "", "material": record.get("material")}


async def stats(request):
    s = _services(request)
    printer = request.query.get("printer") or None
    recent, _ = s.db.jobs(printer=printer, limit=10)
    return web.json_response({
        **s.db.stats(printer), "currency": summary.display_currency(s.options.currency),
        "printers": _printers(s), "recent": [_row(j, s.links) for j in recent],
        "top_parts": s.db.top_parts(printer=printer), "top_excluded": s.db.top_excluded(printer=printer)})


def _printers(s) -> list[dict]:
    return [{"id": t.printer.id, "name": t.printer.name} for t in s.trackers.values()]


def _date(value: str | None, days: int = 0) -> float | None:
    if not value:
        return None
    try:
        return (datetime.strptime(value, "%Y-%m-%d") + timedelta(days=days)).timestamp()
    except ValueError as err:
        raise web.HTTPBadRequest(text=f"Bad date: {value}") from err


def _filters(request) -> dict:
    q = request.query
    return {"printer": q.get("printer") or None, "file": q.get("file") or None, "status": q.get("status") or None,
            "rating": q.get("rating") or None,
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
                              "facets": s.db.facets(request.query.get("printer") or None),
                              "printers": _printers(s),
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
    """Takes printer1:000042. A bare job id, from an older link, finds the first match."""
    db = _services(request).db
    printer, _, job_id = request.match_info[key].rpartition(":")
    record = db.get_job(job_id, printer) if printer else db.find_job(job_id)
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
        other = s.db.get_job(change["job_id"], record["printer_id"])
        changes[kind] = {"ref": f"{record['printer_id']}:{change['job_id']}", "diff": views.labelled_diff(change["diff"], layout),
                         "file": summary.display_name(other["filename"]) if other else None}
    drift = {name: views.labelled_diff(diff, layout) for name, diff in (record.get("preset_drift") or {}).items()}
    return web.json_response({
        **_row(record, s.links), "currency": summary.display_currency(s.options.currency),
        "filename": record["filename"], "printed": record["printed"], "excluded": record["excluded"],
        "filament_mm": record["filament_mm"], "energy_cost": record["energy_cost"],
        "filament_cost": record["filament_cost"], "total_cost": record["total_cost"],
        "interruption": record["interruption"], "progress": record["progress"],
        "current_layer": record["current_layer"], "total_layer": record["total_layer"],
        "chamber_temp": record["chamber_temp"], "error_message": record["error_message"],
        "wasted_cost": record["wasted_cost"], "config_missing": bool(record["config_missing"]),
        "slicer": record["slicer"], "slicer_version": record["slicer_version"],
        "spool_check": record["spool_check"], "presets": record["presets"] or {}, "commit": record["commit_sha"], "drift": drift, "changes": changes,
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
    records = s.db.preset_jobs(kind, name, request.query.get("printer") or None)
    if not records:
        raise web.HTTPNotFound(text="No such preset")
    layout = None
    for record in reversed(records):
        layout = await s.layouts.get(record["slicer"], record["slicer_version"])
        if layout:
            break
    keys = layout["preset_keys"][kind] if layout else []
    timeline, previous, all_values = [], None, []
    for record in records:
        values = views.preset_values(s.db.get_config(record["config_hash"]), kind, name, keys)
        all_values.append((record, values))
        if previous is None or previous != values:
            timeline.append({**_row(record, s.links), "first": previous is None,
                             "diff": views.labelled_diff(diff_configs(previous or values, values), layout)})
        previous = values
    changed = {row["key"] for entry in timeline for row in entry["diff"]}
    results = views.results_by_value(all_values, changed)
    for entry in timeline:
        for row in entry["diff"]:
            row["results"] = results[row["key"]].get(row["new"].get("raw"))
    return web.json_response({"kind": kind, "name": name, "prints": len(records),
                              "timeline": timeline[::-1]})


async def _body(request) -> dict:
    try:
        body = await request.json()
    except ValueError as err:
        raise web.HTTPBadRequest(text="Bad JSON") from err
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="Expected an object")
    return body


async def rate(request):
    record = _get_job(request)
    body = await _body(request)
    fields = {k: body[k] for k in ("rating", "issues", "failure_reason", "note") if k in body}
    if fields.get("rating") not in ("good", "bad", None):
        raise web.HTTPBadRequest(text="Bad rating")
    if fields.get("failure_reason") not in (*FAILURE_REASONS, None):
        raise web.HTTPBadRequest(text="Bad failure reason")
    updated = await _services(request).ratings.update(record["printer_id"], record["job_id"], **fields)
    return web.json_response(_row(updated, _services(request).links))


async def analysis_page(request):
    s = _services(request)
    q = request.query
    printer = q.get("printer") or None
    days = _int(request, "days", 0)
    since = time.time() - days * 86400 if days else None
    jobs_list, _ = s.db.jobs(printer=printer, material=q.get("material") or None, date_from=since, limit=100000)
    return web.json_response({**analysis.analyse(jobs_list, q.get("include_power") == "1"),
                              "currency": summary.display_currency(s.options.currency),
                              "facets": s.db.facets(printer)})


async def maintenance(request):
    s = _services(request)
    wanted = request.query.get("printer")
    result = []
    for tracker in s.trackers.values():
        printer = tracker.printer
        if wanted and printer.id != wanted:
            continue
        s.maintenance.ensure_defaults(printer.id)
        tasks = s.maintenance.tasks(printer.id)
        result.append({"id": printer.id, "name": printer.name, "tasks": tasks, "log": s.maintenance.log(printer.id),
                       "needs_setup": any(not t["confirmed"] for t in tasks)})
    return web.json_response({"printers": result})


def _task_id(request) -> int:
    try:
        return int(request.match_info["task"])
    except ValueError as err:
        raise web.HTTPNotFound() from err


async def _after_task_change(s):
    if s.mqtt and s.mqtt.client:
        await s.mqtt.publish_all()


async def add_task(request):
    s = _services(request)
    task_id = s.maintenance.save(request.match_info["printer"], await _body(request))
    await _after_task_change(s)
    return web.json_response({"id": task_id})


async def edit_task(request):
    s = _services(request)
    task = s.maintenance.task(_task_id(request))
    if task is None:
        raise web.HTTPNotFound()
    s.maintenance.save(task["printer_id"], await _body(request), task["id"])
    await _after_task_change(s)
    return web.json_response({"id": task["id"]})


async def task_done(request):
    s = _services(request)
    if not await s.maintenance.done(_task_id(request), (await _body(request)).get("note", "")):
        raise web.HTTPNotFound()
    return web.json_response({"ok": True})


async def delete_task(request):
    s = _services(request)
    s.maintenance.delete(_task_id(request))
    await _after_task_change(s)
    return web.json_response({"ok": True})


async def confirm_tasks(request):
    s = _services(request)
    dates = (await _body(request)).get("dates") or {}
    s.maintenance.confirm(request.match_info["printer"], {k: _date(v) for k, v in dates.items() if v})
    return web.json_response({"ok": True})


async def tags(request):
    return web.json_response({"tags": _services(request).db.tags()})


async def save_tags(request):
    names = (await _body(request)).get("tags")
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise web.HTTPBadRequest(text="Expected a list of tags")
    _services(request).db.set_tags([n.strip() for n in names if n.strip()])
    return web.json_response({"tags": _services(request).db.tags()})


async def reconcile(request):
    trackers = _services(request).trackers.values()
    return web.json_response({"added": sum([await t.reconcile() for t in trackers])})


async def thumbnail(request):
    name = Path(request.match_info["name"]).name
    path = _services(request).thumbs / name
    if not path.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(path)
