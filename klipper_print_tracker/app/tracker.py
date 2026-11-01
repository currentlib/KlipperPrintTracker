"""Print lifecycle: follows the printer and finalises one record per Moonraker job."""
import asyncio
import logging
import time

import aiohttp

from . import calc, gcode, spool_check
from .config import PrinterOptions

log = logging.getLogger(__name__)

ACTIVE_STATES = ("printing", "paused")
END_STATES = ("complete", "cancelled", "error", "standby")
FINISH_DELAY = 5
FINISH_RETRIES = 4
REST_ERRORS = (aiohttp.ClientError, OSError, TimeoutError, KeyError, ValueError)


class Tracker:
    def __init__(self, options, db, moonraker, supervisor, settings=None, listeners=(), printer=None):
        self.options = options
        self.printer = printer or PrinterOptions(energy_sensor=options.energy_sensor)
        self.db = db
        self.moonraker = moonraker
        self.supervisor = supervisor
        self.settings = settings
        self.listeners = list(listeners)
        self.state = None
        self.active = db.get_active(self.printer.id)
        self.first_start = db.first_start()
        self._last_added = None
        self._finish_task = None
        self._spool_task = None
        self.live = {}
        self._lock = asyncio.Lock()

    # --- printer events ----------------------------------------------

    async def on_offline(self):
        if self.active and self.state in ACTIVE_STATES:
            self.active["offline"] = True
            self.db.set_active(self.active, self.printer.id)

    def _track_live(self, status: dict):
        """Changes every second, so it stays in memory instead of the database."""
        stats = status.get("print_stats") or {}
        info = stats.get("info") or {}
        progress = (status.get("virtual_sdcard") or {}).get("progress")
        if progress is not None:
            self.live["progress"] = progress
        for key in ("current_layer", "total_layer"):
            if info.get(key) is not None:
                self.live[key] = info[key]
        if stats.get("message"):
            self.live["message"] = stats["message"]
        for name, values in status.items():
            if "chamber" in name and (values or {}).get("temperature") is not None:
                self.live["chamber"] = values["temperature"]

    async def on_status(self, status: dict, initial: bool = False):
        self._track_live(status)
        stats = status.get("print_stats") or {}
        new_state = stats.get("state")
        if new_state and new_state != self.state:
            await self._state_changed(new_state, stats.get("filename"), initial)
        if status.get("exclude_object"):
            await self._objects_changed(status["exclude_object"])

    async def _state_changed(self, new: str, filename: str | None, initial: bool):
        old, self.state = self.state, new
        same_print = self.active and self.active.get("filename") == filename
        if new == "printing" and old != "paused" and not (initial and same_print):
            await self._begin(filename, resumed=initial)
        elif new in END_STATES and self.active and (old in ACTIVE_STATES or initial):
            self._schedule_finish()

    async def _begin(self, filename: str | None, resumed: bool):
        self.live = {}
        if not filename:
            filename = await self._status_filename()
        self.active = {
            "job_id": self._last_added, "filename": filename, "started_at": time.time(),
            # An add-on started mid-print can't know the energy at the print's start.
            "start_kwh": None if resumed else await self.supervisor.energy(self.printer.energy_sensor),
            "objects": [], "excluded": [], "live": not resumed,
        }
        self._last_added = None
        self.db.set_active(self.active, self.printer.id)
        await self._notify("current", self.printer.id, self.active)
        if not resumed:
            self._spool_task = asyncio.create_task(self._check_spool(self.active))

    async def _check_spool(self, active: dict):
        try:
            spool_id = await self.moonraker.spool_id()
            spool = await self.moonraker.spool(spool_id) if spool_id is not None else None
        except REST_ERRORS as err:
            log.debug("Spoolman isn't available, no spool check: %s", err)
            return
        filename = active.get("filename")
        metadata, parts = {}, None
        try:
            metadata = await self.moonraker.metadata(filename)
            parts = await self.moonraker.gcode_parts(filename)
        except REST_ERRORS as err:
            log.debug("No file data for the spool check: %s", err)
        config = gcode.parse_config(parts[1]) if parts else None
        used = gcode.used_filaments(parts[0]) if parts else None
        index = (used or [0])[0]
        presets = gcode.split_values((config or {}).get("filament_settings_id", ""))
        preset = presets[index] if index < len(presets) else None
        material = gcode.material(config, preset) if config else None
        material = material or (gcode.split_values(metadata.get("filament_type") or "") or [None])[0]
        result = spool_check.check(spool_check.required_grams(metadata, config, index), spool, material, preset,
                                   self.options.spool_margin_percent)
        result["paused"] = False
        active["spool_check"] = result
        if self.active is active:
            self.db.set_active(active, self.printer.id)
        warn = spool_check.should_warn(result)
        if warn and self.options.spool_check_auto_pause and spool_check.should_pause(result):
            await self.pause()
            result["paused"] = True
        await self._notify("spool_checked", self.printer.id, result)
        if warn:
            await self.supervisor.fire_event("klipper_print_tracker_spool_warning", {
                "printer_id": self.printer.id, "printer": self.printer.name, "file": filename, **result})

    async def pause(self) -> bool:
        try:
            await self.moonraker.pause()
            return True
        except REST_ERRORS as err:
            log.warning("Can't pause %s: %s", self.printer.id, err)
            return False

    async def on_action(self, printer_id: str, target: str, code: str, text: str | None) -> bool:
        if printer_id != self.printer.id or code not in ("spool-pause", "spool-continue"):
            return False
        if code == "spool-pause":
            await self.pause()
        return True

    async def _status_filename(self) -> str | None:
        try:
            jobs = await self.moonraker.history(1)
            return jobs[0]["filename"] if jobs else None
        except REST_ERRORS:
            return None

    async def _objects_changed(self, delta: dict):
        # Klipper clears the list when the file is reset, keep the last real one.
        if not self.active or delta.get("objects") == []:
            return
        if "objects" in delta:
            self.active["objects"] = [o["name"] for o in delta["objects"]]
        if "excluded_objects" in delta:
            self.active["excluded"] = list(delta["excluded_objects"])
        self.db.set_active(self.active, self.printer.id)
        await self._notify("current", self.printer.id, self.active)

    async def on_history(self, action: str, job: dict):
        if action == "added":
            if self.active and not self.active.get("job_id"):
                self.active["job_id"] = job.get("job_id")
                self.db.set_active(self.active, self.printer.id)
            elif not self.active:
                self._last_added = job.get("job_id")
        elif action == "finished" and self.active and self.active.get("job_id") == job.get("job_id"):
            self._schedule_finish()

    # --- finishing ---------------------------------------------------

    def _schedule_finish(self):
        if not self._finish_task or self._finish_task.done():
            self._finish_task = asyncio.create_task(self._finish(self.active))

    async def _finish(self, active: dict):
        for _ in range(FINISH_RETRIES):
            await asyncio.sleep(FINISH_DELAY)
            job = await self._find_job(active)
            if job and job.get("status") != "in_progress":
                await self.finalise(job, active)
                return
        log.warning("Job for %s isn't finished in Moonraker yet, leaving it to reconcile",
                    active.get("filename"))

    async def _find_job(self, active: dict) -> dict | None:
        try:
            if active.get("job_id"):
                return await self.moonraker.job(active["job_id"])
            jobs = await self.moonraker.history(1)
            return jobs[0] if jobs and jobs[0].get("filename") == active.get("filename") else None
        except REST_ERRORS as err:
            log.warning("Can't read job from Moonraker: %s", err)
            return None

    async def reconcile(self) -> int:
        """Finalise finished jobs the live path missed. Returns how many were added."""
        try:
            jobs = await self.moonraker.history()
        except REST_ERRORS as err:
            log.warning("Reconcile failed: %s", err)
            return 0
        added = 0
        for job in reversed(jobs):
            finished = job.get("status") != "in_progress"
            if finished and (job.get("end_time") or 0) >= self.first_start \
                    and not self.db.has_job(job["job_id"], self.printer.id):
                active = self.active if self._matches(job) else None
                added += await self.finalise(job, active)
        return added

    def _matches(self, job: dict) -> bool:
        if not self.active or self.state in ACTIVE_STATES:
            return False
        if self.active.get("job_id"):
            return self.active["job_id"] == job["job_id"]
        return self.active.get("filename") == job.get("filename")

    async def finalise(self, job: dict, active: dict | None) -> bool:
        async with self._lock:
            if self.db.has_job(job["job_id"], self.printer.id):
                return False
            record = await self._build_record(job, active)
            if self.settings:
                try:
                    await self.settings.snapshot(record)
                except Exception:
                    log.exception("Settings snapshot failed for job %s", job["job_id"])
            self.db.save_job(record)
            if active:
                self.db.set_active(None, self.printer.id)
                if self.active is active:
                    self.active = None
                await self._notify("current", self.printer.id, None)
        await self._notify("job_finished", record)
        return True

    async def _build_record(self, job: dict, active: dict | None) -> dict:
        status = calc.job_status(job.get("status", ""))
        objects = (active or {}).get("objects") or []
        excluded = (active or {}).get("excluded") or []
        if not objects:
            try:
                live = await self.moonraker.objects()
                objects = [o["name"] for o in live.get("objects", [])]
                excluded = list(live.get("excluded_objects", []))
            except REST_ERRORS:
                pass
        printed, excluded_names, planned = calc.count_parts(objects, excluded, status)
        parts = sum(printed.values())
        metadata = job.get("metadata") or {}
        used_mm = job.get("filament_used") or 0
        grams = calc.grams_used(metadata, used_mm, status)
        end_kwh = await self.supervisor.energy(self.printer.energy_sensor)
        kwh = calc.energy_delta((active or {}).get("start_kwh"), end_kwh)
        spool_id, spool_name, price_kg = await self._spool()
        price_kg = price_kg or self.options.default_filament_price
        raw_status = job.get("status", "")
        live = self.live if active else {}
        return {
            "interruption": calc.interruption(raw_status, bool((active or {}).get("offline")), end_kwh),
            "progress": calc.progress_percent(live.get("progress"), used_mm, float(metadata.get("filament_total") or 0)),
            "current_layer": live.get("current_layer"), "total_layer": live.get("total_layer"),
            "chamber_temp": live.get("chamber"),
            "error_message": live.get("message") if status == "error" else None,
            "printer_id": self.printer.id, "job_id": job["job_id"], "filename": job.get("filename"),
            "status": status,
            "start_time": job.get("start_time"), "end_time": job.get("end_time"),
            "print_duration": job.get("print_duration") or 0,
            "planned": planned, "parts": parts, "printed": printed, "excluded": excluded_names,
            "filament_mm": round(used_mm, 1), "grams": grams, "kwh": kwh,
            "spool_id": spool_id, "spool": spool_name, "price_kg": price_kg,
            "live_data": bool(active and active.get("live")),
            "spool_check": (active or {}).get("spool_check"),
            "metadata": metadata,
            **calc.costs(kwh, self.options.electricity_price, grams, price_kg, parts, status),
        }

    async def _spool(self):
        try:
            spool_id = await self.moonraker.spool_id()
            if spool_id is None:
                return None, None, None
            name, price_kg = calc.spool_info(await self.moonraker.spool(spool_id))
            return spool_id, name, price_kg
        except REST_ERRORS as err:
            log.debug("Spoolman isn't available: %s", err)
            return None, None, None

    async def _notify(self, method: str, *payload):
        for listener in self.listeners:
            try:
                await getattr(listener, method)(*payload)
            except Exception:
                log.exception("Listener %s.%s failed", type(listener).__name__, method)

    async def run_reconcile(self, interval: int = 300):
        while True:
            await asyncio.sleep(interval)
            await self.reconcile()
