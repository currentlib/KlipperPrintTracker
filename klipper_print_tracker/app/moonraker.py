"""Moonraker client: websocket subscription plus the REST calls the tracker needs."""
import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from urllib.parse import quote

import aiohttp

log = logging.getLogger(__name__)

OBJECTS = {"print_stats": None, "exclude_object": None, "virtual_sdcard": None}
TAIL_BYTES = 512 * 1024
MAX_TAIL_BYTES = 8 * 1024 * 1024
HEAD_BYTES = 4096
MAX_BACKOFF = 60


class Moonraker:
    def __init__(self, url: str, session: aiohttp.ClientSession):
        self.url = url
        self.session = session
        self.on_status: Callable[[dict, bool], Awaitable[None]] | None = None
        self.on_history: Callable[[str, dict], Awaitable[None]] | None = None
        self._ws = None
        self._next_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self.connected = False

    # --- websocket ---------------------------------------------------

    async def run(self):
        backoff = 1
        while True:
            try:
                async with self.session.ws_connect(self.url + "/websocket", heartbeat=30) as ws:
                    self._ws = ws
                    backoff = 1
                    await self._serve(ws)
            except (aiohttp.ClientError, OSError, asyncio.TimeoutError) as err:
                log.warning("Moonraker connection failed: %s", err)
            self._ws = None
            self.connected = False
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)

    async def _serve(self, ws):
        setup = asyncio.create_task(self._on_connect())
        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._dispatch(msg.json())
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    break
        finally:
            setup.cancel()
            for fut in self._pending.values():
                fut.cancel()
            self._pending.clear()

    async def _on_connect(self):
        try:
            await self._call("server.connection.identify", {
                "client_name": "KlipperPrintTracker", "version": "0.1.0",
                "type": "other", "url": "https://github.com/currentlib/KlipperPrintTracker",
            })
        except RuntimeError as err:
            log.debug("identify failed: %s", err)
        await self._subscribe()

    async def _subscribe(self):
        try:
            result = await self._call("printer.objects.subscribe", {"objects": OBJECTS})
        except RuntimeError as err:
            # Klipper isn't ready yet, notify_klippy_ready brings us back here.
            log.info("Subscribe failed, waiting for Klipper: %s", err)
            return
        self.connected = True
        if self.on_status:
            await self.on_status(result.get("status", {}), True)

    async def _call(self, method: str, params: dict | None = None) -> dict:
        self._next_id += 1
        fut = asyncio.get_running_loop().create_future()
        self._pending[self._next_id] = fut
        await self._ws.send_json({"jsonrpc": "2.0", "method": method,
                                  "params": params or {}, "id": self._next_id})
        return await asyncio.wait_for(fut, 15)

    async def _dispatch(self, msg: dict):
        if "id" in msg:
            fut = self._pending.pop(msg["id"], None)
            if fut and not fut.done():
                if "error" in msg:
                    fut.set_exception(RuntimeError(str(msg["error"])))
                else:
                    fut.set_result(msg.get("result") or {})
            return
        method, params = msg.get("method"), msg.get("params") or []
        if method == "notify_status_update" and self.on_status and params:
            await self.on_status(params[0], False)
        elif method == "notify_history_changed" and self.on_history and params:
            await self.on_history(params[0].get("action"), params[0].get("job") or {})
        elif method == "notify_klippy_ready":
            asyncio.create_task(self._subscribe())

    # --- REST --------------------------------------------------------

    async def _get(self, path: str, **params):
        async with self.session.get(self.url + path, params=params) as resp:
            resp.raise_for_status()
            return (await resp.json())["result"]

    async def job(self, uid: str) -> dict:
        return (await self._get("/server/history/job", uid=uid))["job"]

    async def history(self, limit: int = 50) -> list[dict]:
        return (await self._get("/server/history/list", limit=limit, order="desc"))["jobs"]

    async def objects(self) -> dict:
        async with self.session.get(self.url + "/printer/objects/query?exclude_object") as resp:
            resp.raise_for_status()
            return (await resp.json())["result"]["status"]["exclude_object"]

    async def metadata(self, filename: str) -> dict:
        return await self._get("/server/files/metadata", filename=filename)

    async def spool_id(self) -> int | None:
        return (await self._get("/server/spoolman/spool_id")).get("spool_id")

    async def spool(self, spool_id: int) -> dict | None:
        body = {"request_method": "GET", "path": f"/v1/spool/{spool_id}", "use_v2_response": True}
        async with self.session.post(self.url + "/server/spoolman/proxy", json=body) as resp:
            resp.raise_for_status()
            result = (await resp.json())["result"]
        return result.get("response") if "response" in result else result

    def _file_url(self, path: str) -> str:
        return f"{self.url}/server/files/gcodes/{quote(path)}"

    async def thumbnail(self, relative_path: str) -> bytes | None:
        async with self.session.get(self._file_url(relative_path)) as resp:
            return await resp.read() if resp.status == 200 else None

    async def gcode_parts(self, filename: str) -> tuple[str, str] | None:
        """Return (head, tail) of a G-code file, or None when it's gone.

        Files can be large and this runs on a Pi, so only the tail is kept. The
        tail grows when CONFIG_BLOCK_START isn't in it, up to MAX_TAIL_BYTES.
        """
        url = self._file_url(filename)
        size = TAIL_BYTES
        while True:
            async with self.session.get(url, headers={"Range": f"bytes=-{size}"}) as resp:
                if resp.status == 404:
                    return None
                resp.raise_for_status()
                if resp.status != 206:
                    return await self._stream_ends(resp)
                tail = await resp.read()
                match = re.search(r"/(\d+)$", resp.headers.get("Content-Range", ""))
            whole = match and int(match.group(1)) <= size
            if b"CONFIG_BLOCK_START" in tail or whole or size >= MAX_TAIL_BYTES:
                break
            size *= 4
        range_head = {"Range": f"bytes=0-{HEAD_BYTES - 1}"}
        async with self.session.get(url, headers=range_head) as resp:
            head = await resp.content.read(HEAD_BYTES)
        return head.decode("utf-8", "replace"), tail.decode("utf-8", "replace")

    async def _stream_ends(self, resp) -> tuple[str, str]:
        """No Range support: read the stream and keep only both ends."""
        head = bytearray()
        tail = bytearray()
        async for chunk in resp.content.iter_chunked(64 * 1024):
            if len(head) < HEAD_BYTES:
                head += chunk[:HEAD_BYTES - len(head)]
            tail += chunk
            if len(tail) > 2 * MAX_TAIL_BYTES:
                del tail[:-MAX_TAIL_BYTES]
        return head.decode("utf-8", "replace"), bytes(tail[-MAX_TAIL_BYTES:]).decode("utf-8", "replace")
