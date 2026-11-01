"""Add-on entry point."""
import asyncio
import logging
from dataclasses import dataclass

import aiohttp
from aiohttp import web

from .config import DATA_DIR, load_options
from .db import Database
from .links import Links
from .moonraker import Moonraker
from .mqtt import MqttPublisher
from .settings_git import SettingsHistory
from .sheets import GoogleSheets
from .slicer_meta import LayoutStore
from .supervisor import Supervisor
from .tracker import Tracker
from .web import create_app

log = logging.getLogger("app")
INGRESS_PORT = 8099
DIRECT_PORT = 8100


@dataclass
class Services:
    options: object
    db: Database
    moonraker: Moonraker
    tracker: Tracker
    layouts: LayoutStore
    links: Links
    thumbs: object
    mqtt: MqttPublisher | None = None


async def serve(app: web.Application, port: int) -> web.AppRunner:
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    return runner


async def keep_running(name: str, factory):
    """One failing background job must not take the others down."""
    while True:
        try:
            await factory()
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("%s crashed, restarting", name)
            await asyncio.sleep(10)


async def main():
    options = load_options()
    logging.basicConfig(level=options.log_level.upper(),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    timeout = aiohttp.ClientTimeout(total=300, sock_connect=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        supervisor = Supervisor(session)
        links = Links(await supervisor.app_slug(), options.direct_url, await supervisor.external_url())
        db = Database(DATA_DIR / "tracker.db")
        moonraker = Moonraker(options.moonraker_url, session)
        layouts = LayoutStore(DATA_DIR / "layouts", options.auto_fetch_layouts)
        settings = SettingsHistory(db, moonraker, layouts, DATA_DIR)
        tracker = Tracker(options, db, moonraker, supervisor, settings)
        mqtt = MqttPublisher(options, db, supervisor, links, tracker.reconcile)
        tracker.listeners = [mqtt, GoogleSheets(options, supervisor, links)]
        moonraker.on_status = tracker.on_status
        moonraker.on_history = tracker.on_history
        services = Services(options, db, moonraker, tracker, layouts, links, settings.thumbs, mqtt)

        runners = [await serve(create_app(services), INGRESS_PORT),
                   await serve(create_app(services, ingress=False), DIRECT_PORT)]
        log.info("Print Tracker started, panel at %s", links.panel())
        try:
            await asyncio.gather(
                keep_running("Moonraker", moonraker.run),
                keep_running("MQTT", mqtt.run),
                keep_running("Reconcile", tracker.run_reconcile))
        finally:
            for runner in runners:
                await runner.cleanup()
            db.close()


if __name__ == "__main__":
    asyncio.run(main())
