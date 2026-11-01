"""Add-on options and paths."""
import json
import os
import re
from dataclasses import dataclass, field, fields
from pathlib import Path

DATA_DIR = Path(os.environ.get("TRACKER_DATA", "/data"))
DEFAULT_PRINTER = "printer1"


@dataclass
class PrinterOptions:
    id: str = DEFAULT_PRINTER
    name: str = "3D Printer"
    moonraker_url: str = ""
    energy_sensor: str | None = None

    def __post_init__(self):
        self.moonraker_url = self.moonraker_url.rstrip("/")
        if not re.fullmatch(r"[a-z0-9]+", self.id):
            raise ValueError(f"Printer id {self.id!r}: use only a-z and 0-9")


@dataclass
class Options:
    printers: list = field(default_factory=list)
    # Pre-0.3 options. They stay in the schema because the Supervisor drops unknown keys.
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
        self.printers = [p if isinstance(p, PrinterOptions) else PrinterOptions(**p) for p in self.printers]
        if not self.printers and self.moonraker_url:
            self.printers = [PrinterOptions(DEFAULT_PRINTER, self.printer_name, self.moonraker_url, self.energy_sensor)]
        ids = [p.id for p in self.printers]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Printer ids must be unique: {ids}")


def load_options(path: Path | None = None) -> Options:
    raw = json.loads((path or DATA_DIR / "options.json").read_text())
    known = {f.name for f in fields(Options)}
    return Options(**{k: v for k, v in raw.items() if k in known})
