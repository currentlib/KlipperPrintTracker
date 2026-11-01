"""Small Moonraker stand-in: websocket, REST history, metadata, Spoolman and files."""
import asyncio
import time

from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestServer


class FakeMoonraker:
    def __init__(self):
        self.status = {"print_stats": {"state": "standby", "filename": ""},
                       "exclude_object": {"objects": [], "excluded_objects": []},
                       "virtual_sdcard": {}}
        self.jobs: list[dict] = []
        self.files: dict[str, bytes] = {}
        self.spool_id = None
        self.spools: dict[int, dict] = {}
        self.metadata = {}
        self.thumbs: dict[str, bytes] = {}
        self.range_requests = 0
        self.range_supported = True
        self.clients: list[web.WebSocketResponse] = []
        self.server = None
        self.connections = 0

    async def start(self) -> str:
        app = web.Application()
        app.add_routes([
            web.get("/websocket", self.websocket),
            web.get("/server/history/list", self.history_list),
            web.get("/server/history/job", self.history_job),
            web.get("/printer/objects/query", self.objects_query),
            web.get("/server/spoolman/spool_id", self.get_spool_id),
            web.post("/server/spoolman/proxy", self.spool_proxy),
            web.get("/server/files/metadata", self.file_metadata),
            web.get("/server/files/gcodes/{path:.*}", self.file),
        ])
        self.server = TestServer(app)
        await self.server.start_server()
        return str(self.server.make_url("")).rstrip("/")

    async def stop(self):
        for ws in self.clients:
            await ws.close()
        await self.server.close()

    # --- what a test drives ------------------------------------------

    async def emit(self, delta: dict):
        for key, value in delta.items():
            self.status.setdefault(key, {}).update(value)
        await self._broadcast("notify_status_update", [delta, time.time()])

    async def add_job(self, job_id: str, filename: str, **extra) -> dict:
        job = {"job_id": job_id, "filename": filename, "status": "in_progress",
               "start_time": time.time(), "end_time": None, "print_duration": 0,
               "filament_used": 0, "metadata": {}, "exists": True, **extra}
        self.jobs.insert(0, job)
        await self._broadcast("notify_history_changed", [{"action": "added", "job": job}])
        return job

    async def finish_job(self, job: dict, status: str, **extra):
        job.update(status=status, end_time=time.time(), **extra)
        await self._broadcast("notify_history_changed", [{"action": "finished", "job": job}])

    async def _broadcast(self, method: str, params: list):
        for ws in list(self.clients):
            if not ws.closed:
                await ws.send_json({"jsonrpc": "2.0", "method": method, "params": params})

    async def drop_clients(self):
        for ws in list(self.clients):
            await ws.close()
        self.clients.clear()

    # --- handlers ----------------------------------------------------

    async def websocket(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.clients.append(ws)
        self.connections += 1
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            data = msg.json()
            result = {"connection_id": 1}
            if data["method"] == "printer.objects.subscribe":
                result = {"eventtime": 1.0, "status": self.status}
            await ws.send_json({"jsonrpc": "2.0", "id": data["id"], "result": result})
        return ws

    async def history_list(self, request):
        limit = int(request.query.get("limit", 50))
        return web.json_response({"result": {"count": len(self.jobs), "jobs": self.jobs[:limit]}})

    async def history_job(self, request):
        for job in self.jobs:
            if job["job_id"] == request.query["uid"]:
                return web.json_response({"result": {"job": job}})
        raise web.HTTPNotFound()

    async def objects_query(self, request):
        return web.json_response({"result": {"status": {
            "exclude_object": self.status["exclude_object"]}}})

    async def get_spool_id(self, request):
        return web.json_response({"result": {"spool_id": self.spool_id}})

    async def spool_proxy(self, request):
        body = await request.json()
        spool = self.spools.get(int(body["path"].rsplit("/", 1)[1]))
        return web.json_response({"result": {"response": spool, "error": None}})

    async def file_metadata(self, request):
        return web.json_response({"result": self.metadata.get(request.query["filename"], {})})

    async def file(self, request):
        path = request.match_info["path"]
        if path in self.thumbs:
            return web.Response(body=self.thumbs[path], content_type="image/png")
        if path not in self.files:
            raise web.HTTPNotFound()
        content = self.files[path]
        header = request.headers.get("Range")
        if not header or not self.range_supported:
            return web.Response(body=content)
        self.range_requests += 1
        spec = header.removeprefix("bytes=")
        if spec.startswith("-"):
            start, end = max(0, len(content) - int(spec[1:])), len(content) - 1
        else:
            first, last = spec.split("-")
            start, end = int(first), min(int(last), len(content) - 1)
        return web.Response(status=206, body=content[start:end + 1], headers={
            "Content-Range": f"bytes {start}-{end}/{len(content)}"})


async def settle(condition, timeout: float = 3):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise TimeoutError("condition not reached")
        await asyncio.sleep(0.01)
