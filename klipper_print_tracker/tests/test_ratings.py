import asyncio

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from app.db import Database
from app.ratings import DEFAULT_TAGS, HomeAssistantEvents, Ratings, classify_reason, parse_action
from fake_moonraker import settle


class FakeHomeAssistant:
    """The Core websocket: login, subscription and bus events."""

    def __init__(self, accept=True):
        self.accept = accept
        self.socket = None
        self.subscribed = None
        self.server = None

    async def start(self) -> str:
        app = web.Application()
        app.add_routes([web.get("/ws", self.handler)])
        self.server = TestServer(app)
        await self.server.start_server()
        return str(self.server.make_url("/ws")).replace("http", "ws")

    async def handler(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_json({"type": "auth_required"})
        message = await ws.receive_json()
        assert message["type"] == "auth" and message["access_token"] == "token"
        await ws.send_json({"type": "auth_ok" if self.accept else "auth_invalid"})
        if not self.accept:
            await ws.close()
            return ws
        self.subscribed = await ws.receive_json()
        await ws.send_json({"id": self.subscribed["id"], "type": "result", "success": True})
        self.socket = ws
        async for _ in ws:
            pass
        return ws

    async def fire(self, action, reply_text=None):
        data = {"action": action}
        if reply_text:
            data["reply_text"] = reply_text
        await self.socket.send_json({"id": self.subscribed["id"], "type": "event", "event": {
            "event_type": "mobile_app_notification_action", "data": data}})


class Listener:
    def __init__(self):
        self.rated = []

    async def job_rated(self, record):
        self.rated.append(record)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "t.db")
    database.save_job({"printer_id": "printer1", "job_id": "00004F", "filename": "a", "status": "completed",
                       "end_time": 1.0})
    yield database
    database.close()


@pytest.mark.parametrize("action,expected", [
    ("KPT_printer1_00004F_good", ("printer1", "00004F", "good")),
    ("KPT_p2_000001_fail-other", ("p2", "000001", "fail-other")),
    ("KPT_printer1_maint-3_done", ("printer1", "maint-3", "done")),
    ("OTHER_printer1_1_good", None), ("KPT_x", None), ("KPT__1_good", None), (None, None), ("", None),
])
def test_parse_action(action, expected):
    assert parse_action(action) == expected


@pytest.mark.parametrize("text,reason", [
    ("Засмічення сопла", "clog"), ("недоекструзія", "clog"), ("відклеїлось від столу", "adhesion"),
    ("Спагеті", "spaghetti"), ("зсув шару", "spaghetti"), ("закінчився пластик", "other"), (None, "other"),
])
def test_typed_reasons(text, reason):
    assert classify_reason(text) == reason


async def test_good_and_note(db):
    listener = Listener()
    ratings = Ratings(db, [listener])
    await ratings.from_action("printer1", "00004F", "good", None)
    await ratings.from_action("printer1", "00004F", "note", "трохи стрингінгу")
    record = db.get_job("00004F")
    assert record["rating"] == "good" and record["note"] == "трохи стрингінгу" and record["rated_at"]
    assert len(listener.rated) == 2


async def test_failure_reasons(db):
    ratings = Ratings(db)
    await ratings.from_action("printer1", "00004F", "fail-adhesion", None)
    assert db.get_job("00004F")["failure_reason"] == "adhesion"
    await ratings.from_action("printer1", "00004F", "fail-other", "засмічення")
    record = db.get_job("00004F")
    assert record["failure_reason"] == "clog" and record["note"] == "засмічення"


async def test_unknown_things_are_ignored(db):
    ratings = Ratings(db)
    assert await ratings.from_action("printer1", "00004F", "nonsense", None) is False
    await ratings.from_action("printer1", "FFFFFF", "good", None)
    assert db.get_job("00004F")["rating"] is None


def test_unrated_and_filters(db):
    assert db.stats()["unrated"] == 1
    assert db.jobs(rating="none")[1] == 1
    db.update_job("00004F", "printer1", rating="bad", issues=["warping"])
    assert db.stats()["unrated"] == 0 and db.jobs(rating="bad")[1] == 1
    assert db.get_job("00004F")["issues"] == ["warping"]
    with pytest.raises(ValueError):
        db.update_job("00004F", "printer1", filename="x")


def test_tags_are_editable(db):
    assert db.tags() == list(DEFAULT_TAGS)
    db.set_tags(["b", "a"])
    assert db.tags() == ["b", "a"]


async def test_actions_arrive_over_the_ha_websocket(db):
    ha = FakeHomeAssistant()
    url = await ha.start()
    ratings = Ratings(db)
    async with aiohttp.ClientSession() as session:
        events = HomeAssistantEvents(session, "token", url)
        events.handlers.append(ratings.from_action)
        task = asyncio.create_task(events.run())
        await settle(lambda: ha.socket is not None)
        assert ha.subscribed["event_type"] == "mobile_app_notification_action"
        await ha.fire("something_else")
        await ha.fire("KPT_printer1_00004F_note", "дуже добре")
        await settle(lambda: db.get_job("00004F")["note"])
        assert db.get_job("00004F")["note"] == "дуже добре"
        task.cancel()
    await ha.server.close()


async def test_refused_token_retries_quietly(db):
    ha = FakeHomeAssistant(accept=False)
    url = await ha.start()
    async with aiohttp.ClientSession() as session:
        events = HomeAssistantEvents(session, "token", url)
        task = asyncio.create_task(events.run())
        await asyncio.sleep(0.1)
        assert not events.connected and not task.done()
        task.cancel()
    await ha.server.close()


async def test_no_token_means_no_listener():
    await HomeAssistantEvents(None, None).run()
