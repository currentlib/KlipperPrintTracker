"""Layout files: bundled ones, a runtime cache and the nearest-version fallback."""
import asyncio
import json
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)
BUNDLED = Path(__file__).parents[1] / "layouts"


class LayoutError(Exception):
    """The slicer sources can't be fetched or don't look as expected."""


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", version)[:3])


def _distance(a: tuple, b: tuple) -> tuple:
    return tuple(abs(x - y) for x, y in zip(a, b))


def generate_for(version: str) -> dict:
    from . import orca
    return orca.generate(version, orca.fetch_sources(f"v{version}"))


class LayoutStore:
    def __init__(self, cache_dir: Path, auto_fetch: bool = True, bundled: Path = BUNDLED,
                 generator=generate_for):
        self.cache_dir = Path(cache_dir)
        self.bundled = bundled
        self.auto_fetch = auto_fetch
        self.generator = generator
        self._loaded: dict[str, dict] = {}
        self._failed: set[str] = set()

    def _file(self, version: str) -> Path | None:
        for folder in (self.bundled, self.cache_dir):
            path = folder / f"orca-{version}.json"
            if path.exists():
                return path
        return None

    def _load(self, version: str) -> dict | None:
        if version not in self._loaded:
            path = self._file(version)
            if path is None:
                return None
            self._loaded[version] = json.loads(path.read_text(encoding="utf-8"))
        return self._loaded[version]

    def _nearest(self, version: str) -> dict | None:
        names = [p.stem.removeprefix("orca-") for p in self.bundled.glob("orca-*.json")]
        if not names:
            return None
        wanted = version_key(version)
        return self._load(min(names, key=lambda n: _distance(version_key(n), wanted)))

    async def get(self, slicer: str | None, version: str | None) -> dict | None:
        """Layout for a slicer version, or None for slicers without metadata."""
        if slicer != "OrcaSlicer" or not version:
            return None
        layout = self._load(version)
        if layout:
            return layout
        if self.auto_fetch and version not in self._failed:
            try:
                layout = await asyncio.to_thread(self.generator, version)
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                (self.cache_dir / f"orca-{version}.json").write_text(
                    json.dumps(layout, ensure_ascii=False), encoding="utf-8")
                self._loaded[version] = layout
                return layout
            except LayoutError as err:
                log.warning("No layout for OrcaSlicer %s: %s", version, err)
                self._failed.add(version)
        return self._nearest(version)
