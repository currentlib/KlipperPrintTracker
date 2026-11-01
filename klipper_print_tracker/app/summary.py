"""Compact job data for entities, events and the spreadsheet."""
from datetime import datetime

from .config import DEFAULT_PRINTER
from .settings_git import short_changes

MAX_CHANGED_KEYS = 10
CURRENCY_SYMBOLS = {"UAH": "грн", "USD": "$", "EUR": "€", "GBP": "£", "PLN": "zł"}


def display_currency(code: str) -> str:
    return CURRENCY_SYMBOLS.get(code.upper(), code)


def job_summary(record: dict, links, currency: str = "") -> dict:
    excluded = record.get("excluded") or {}
    printer = record.get("printer_id", DEFAULT_PRINTER)
    summary = {
        "job_id": record["job_id"],
        "printer_id": printer,
        "file": display_name(record.get("filename")),
        "status": record["status"],
        "parts": record.get("parts", 0),
        "planned": record.get("planned", 0),
        "excluded": ", ".join(excluded),
        "minutes": round((record.get("print_duration") or 0) / 60),
        "grams": record.get("grams", 0),
        "kwh": record.get("kwh"),
        "cost": record.get("total_cost", 0),
        "cost_per_part": record.get("per_part", 0),
        "currency": currency,
        "rating": record.get("rating"),
        "failure_reason": record.get("failure_reason"),
        "calibration": record.get("calibration"),
        "spool": record.get("spool"),
        "changed_settings": short_changes(record)[:MAX_CHANGED_KEYS],
        "url": links.job(record["job_id"], printer),
    }
    direct = links.direct_job(record["job_id"], printer)
    if direct:
        summary["direct_url"] = direct
    return summary


def recent_row(record: dict, links) -> dict:
    """One row of the dashboard table, kept small on purpose."""
    return {
        "date": _date(record.get("end_time"), "%d.%m %H:%M"),
        "file": display_name(record.get("filename"))[:40],
        "status": record["status"],
        "parts": record.get("parts", 0),
        "planned": record.get("planned", 0),
        "excluded": bool(record.get("excluded")),
        "minutes": round((record.get("print_duration") or 0) / 60),
        "grams": record.get("grams", 0),
        "cost": record.get("total_cost", 0),
        "per_part": record.get("per_part", 0),
        "spool": (record.get("spool") or "")[:24],
        "url": links.job(record["job_id"], record.get("printer_id", DEFAULT_PRINTER)),
    }


def display_name(filename: str | None) -> str:
    name = (filename or "").rsplit("/", 1)[-1]
    return name[:-6] if name.lower().endswith(".gcode") else name


def _date(timestamp: float | None, pattern: str) -> str:
    return datetime.fromtimestamp(timestamp).strftime(pattern) if timestamp else ""


def sheet_row(record: dict, links) -> dict:
    printed = record.get("printed") or {}
    excluded = record.get("excluded") or {}
    return {
        "Date": _date(record.get("end_time"), "%Y-%m-%d %H:%M"),
        "File": display_name(record.get("filename")),
        "Status": record["status"],
        "Parts": record.get("parts", 0),
        "Planned": record.get("planned", 0),
        "Printed per part": ", ".join(f"{k} x{v}" for k, v in printed.items()),
        "Excluded": ", ".join(excluded),
        "Minutes": round((record.get("print_duration") or 0) / 60),
        "Grams": record.get("grams", 0),
        "Spool": record.get("spool") or "",
        "kWh": record.get("kwh") if record.get("kwh") is not None else "",
        "Energy cost": record.get("energy_cost", 0),
        "Filament cost": record.get("filament_cost", 0),
        "Total": record.get("total_cost", 0),
        "Cost per part": record.get("per_part", 0),
        "Job ID": record["job_id"],
        "Link": links.absolute_job(record["job_id"], record.get("printer_id", DEFAULT_PRINTER)),
        "Changed settings": ", ".join(short_changes(record)),
    }
