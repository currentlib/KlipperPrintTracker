"""Supervisor and Home Assistant Core API."""
import logging
import os

import aiohttp

log = logging.getLogger(__name__)
BASE = "http://supervisor"


class Supervisor:
    def __init__(self, session: aiohttp.ClientSession, token: str | None = None, base: str = BASE):
        self.session = session
        self.token = token if token is not None else os.environ.get("SUPERVISOR_TOKEN")
        self.base = base

    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    async def _get(self, path: str):
        if not self.token:
            return None
        try:
            async with self.session.get(self.base + path, headers=self._headers) as resp:
                if resp.status != 200:
                    log.debug("GET %s returned %s", path, resp.status)
                    return None
                return await resp.json()
        except (aiohttp.ClientError, OSError, TimeoutError) as err:
            log.warning("GET %s failed: %s", path, err)
            return None

    async def app_slug(self) -> str:
        info = await self._get("/addons/self/info")
        if info and info.get("data", {}).get("slug"):
            return info["data"]["slug"]
        return os.environ.get("HOSTNAME", "klipper_print_tracker").replace("-", "_")

    async def mqtt_service(self) -> dict | None:
        result = await self._get("/services/mqtt")
        return (result or {}).get("data") or None

    async def external_url(self) -> str | None:
        config = await self._get("/core/api/config")
        return (config or {}).get("external_url") or (config or {}).get("internal_url")

    async def energy(self, entity_id: str | None) -> float | None:
        """Current counter value, None when it can't be read."""
        if not entity_id:
            return None
        state = await self._get(f"/core/api/states/{entity_id}")
        try:
            return float(state["state"])
        except (TypeError, KeyError, ValueError):
            return None

    async def call_service(self, domain: str, service: str, data: dict) -> bool:
        if not self.token:
            return False
        url = f"{self.base}/core/api/services/{domain}/{service}"
        try:
            async with self.session.post(url, headers=self._headers, json=data) as resp:
                if resp.status >= 300:
                    log.warning("%s.%s returned %s: %s", domain, service, resp.status, await resp.text())
                    return False
                return True
        except (aiohttp.ClientError, OSError, TimeoutError) as err:
            log.warning("%s.%s failed: %s", domain, service, err)
            return False
