"""Add-on options and paths."""
import json
import os
from dataclasses import dataclass, fields
from pathlib import Path

DATA_DIR = Path(os.environ.get("TRACKER_DATA", "/data"))


@dataclass
class Options:
    moonraker_url: str = ""
    printer_name: str = "3D Printer"
    energy_sensor: str | None = None
    electricity_price: float = 0
    default_filament_price: float = 0
    currency: str = "UAH"
    google_sheets_config_entry: str | None = None
    google_sheets_worksheet: str = "Print Tracker"
    mqtt_host: str | None = None
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    direct_url: str | None = None
    auto_fetch_layouts: bool = True
    log_level: str = "info"

    def __post_init__(self):
        self.moonraker_url = self.moonraker_url.rstrip("/")
        if self.direct_url:
            self.direct_url = self.direct_url.rstrip("/")


def load_options(path: Path | None = None) -> Options:
    raw = json.loads((path or DATA_DIR / "options.json").read_text())
    known = {f.name for f in fields(Options)}
    return Options(**{k: v for k, v in raw.items() if k in known})
