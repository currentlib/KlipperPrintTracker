"""Print ratings and failure reasons, from notification actions and from the UI."""
import asyncio
import json
import logging
import re
import time

import aiohttp

log = logging.getLogger(__name__)

ACTION_PREFIX = "KPT"
EVENT_TYPE = "mobile_app_notification_action"
FAILURE_REASONS = ("adhesion", "spaghetti", "clog", "other")
DEFAULT_TAGS = ("stringing", "warping", "погана адгезія першого шару", "зсув шару", "недоекструзія",
                "переекструзія", "засмічення", "бульбашки / волога", "погані нависання", "слабкі підтримки",
                "артефакти шва", "розшарування")
# Android shows three actions, so one reason has to arrive as typed text.
REASON_WORDS = {"clog": r"засм|екструз|clog|jam", "adhesion": r"відкле|адгез|adhes|warp",
                "spaghetti": r"спагет|зсув|spaghetti|shift"}


def parse_action(action: str) -> tuple[str, str, str] | None:
    """KPT_<printer_id>_<target>_<code> -> (printer_id, target, code)."""
    parts = (action or "").split("_", 3)
    if len(parts) != 4 or parts[0] != ACTION_PREFIX or not all(parts):
        return None
    return parts[1], parts[2], parts[3]


def classify_reason(text: str) -> str:
    lowered = (text or "").lower()
    for reason, pattern in REASON_WORDS.items():
        if re.search(pattern, lowered):
            return reason
    return "other"


class Ratings:
    def __init__(self, db, listeners=()):
        self.db = db
        self.listeners = list(listeners)

    async def update(self, printer_id: str, job_id: str, **fields) -> dict | None:
        """Change rating fields, anything left out stays as it was."""
        if not self.db.has_job(job_id, printer_id):
            log.warning("Rating for an unknown job %s:%s", printer_id, job_id)
            return None
        self.db.update_job(job_id, printer_id, rated_at=time.time(), **fields)
        record = self.db.get_job(job_id, printer_id)
        for listener in self.listeners:
            try:
                await listener.job_rated(record)
            except Exception:
                log.exception("Listener %s failed", type(listener).__name__)
        return record

    async def from_action(self, printer_id: str, job_id: str, code: str, text: str | None) -> bool:
        if code in ("good", "bad"):
            await self.update(printer_id, job_id, rating=code)
        elif code == "note":
            await self.update(printer_id, job_id, note=text or "")
        elif code.startswith("fail-"):
            reason = code.removeprefix("fail-")
            if reason == "other":
                reason = classify_reason(text)
            fields = {"note": text} if text else {}
            await self.update(printer_id, job_id, failure_reason=reason, **fields)
        else:
            return False
        return True


class HomeAssistantEvents:
    """Listens for notification actions on HA's event bus, no automation needed."""

    def __init__(self, session, token, url="ws://supervisor/core/websocket"):
        self.session = session
        self.token = token
        self.url = url
        self.handlers = []
        self.connected = False

    async def run(self):
        if not self.token:
            log.info("No Supervisor token: notification actions are off")
            return
        backoff = 1
        while True:
            try:
                async with self.session.ws_connect(self.url, heartbeat=30) as ws:
                    await self._login(ws)
                    backoff = 1
                    self.connected = True
                    async for message in ws:
                        if message.type == aiohttp.WSMsgType.TEXT:
                            await self._dispatch(message.json())
                        elif message.type == aiohttp.WSMsgType.ERROR:
                            break
            except (aiohttp.ClientError, OSError, TimeoutError, PermissionError) as err:
                log.warning("Home Assistant events connection failed: %s", err)
            self.connected = False
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    async def _login(self, ws):
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": self.token})
        reply = await ws.receive_json()
        if reply.get("type") != "auth_ok":
            raise PermissionError(f"Home Assistant refused the token: {reply.get('type')}")
        await ws.send_json({"id": 1, "type": "subscribe_events", "event_type": EVENT_TYPE})

    async def _dispatch(self, message: dict):
        if message.get("type") != "event":
            return
        data = (message.get("event") or {}).get("data") or {}
        parsed = parse_action(data.get("action"))
        if parsed is None:
            return
        for handler in self.handlers:
            try:
                if await handler(*parsed, data.get("reply_text")):
                    return
            except Exception:
                log.exception("Notification action %s failed", json.dumps(data.get("action")))
