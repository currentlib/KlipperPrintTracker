"""Per-print calculations, ported from the YAML package."""
import re

_COPY_SUFFIX = re.compile(r"_id_\d+_copy_\d+$", re.IGNORECASE)
_MODEL_EXT = re.compile(r"\.(stl|3mf|obj|step|stp)(_\d+)?$", re.IGNORECASE)


def normalise_name(name: str) -> str:
    """Bracket.stl_id_0_copy_2 -> Bracket, SHOERACK.STL_2_ID_1_COPY_0 -> SHOERACK"""
    return _MODEL_EXT.sub("", _COPY_SUFFIX.sub("", name))


def restore_casing(parts: dict[str, int], originals: list[str]) -> dict[str, int]:
    """Klipper reports object names in upper case, the G-code keeps the slicer's casing."""
    casing = {normalise_name(name).upper(): normalise_name(name) for name in originals}
    restored: dict[str, int] = {}
    for name, count in parts.items():
        key = casing.get(name.upper(), name)
        restored[key] = restored.get(key, 0) + count
    return restored


def job_status(moonraker_status: str) -> str:
    """Moonraker has several failure statuses, the add-on only reports one."""
    if moonraker_status in ("completed", "cancelled"):
        return moonraker_status
    return "error"


def count_parts(objects: list[str], excluded: list[str], status: str):
    """Return (printed, excluded, planned). Parts only count as printed on completed jobs."""
    printed_names: dict[str, int] = {}
    excluded_names: dict[str, int] = {}
    if status == "completed":
        for obj in objects:
            if obj not in excluded:
                name = normalise_name(obj)
                printed_names[name] = printed_names.get(name, 0) + 1
    for obj in excluded:
        name = normalise_name(obj)
        excluded_names[name] = excluded_names.get(name, 0) + 1
    return printed_names, excluded_names, len(objects)


def grams_used(metadata: dict | None, used_mm: float, status: str) -> float:
    """Slicer weight, scaled by the used/total ratio for unfinished prints."""
    metadata = metadata or {}
    weight = float(metadata.get("filament_weight_total") or 0)
    total_mm = float(metadata.get("filament_total") or 0)
    if total_mm > 0:
        return round(weight * float(used_mm or 0) / total_mm, 1)
    return round(weight, 1) if status == "completed" else 0.0


def energy_delta(start: float | None, end: float | None) -> float | None:
    """None when the sensor was missing or the counter was reset during the print."""
    if start is None or end is None or end < start:
        return None
    return round(end - start, 3)


def spool_info(spool: dict | None) -> tuple[str | None, float | None]:
    """Return (display name, price per kg) from a Spoolman spool."""
    if not spool:
        return None, None
    filament = spool.get("filament") or {}
    vendor = (filament.get("vendor") or {}).get("name")
    name = " ".join(x for x in (vendor, filament.get("name")) if x) or None
    price = spool.get("price") or filament.get("price")
    weight = spool.get("initial_weight") or filament.get("weight")
    price_kg = round(price / weight * 1000, 2) if price and weight else None
    return name, price_kg


def costs(kwh: float | None, electricity_price: float, grams: float, price_kg: float,
          parts: int, status: str) -> dict:
    energy = round((kwh or 0) * electricity_price, 2)
    filament = round(grams / 1000 * price_kg, 2)
    total = round(energy + filament, 2)
    return {
        "energy_cost": energy,
        "filament_cost": filament,
        "total_cost": total,
        "per_part": round(total / parts, 2) if parts > 0 else 0,
        "wasted_cost": total if status != "completed" else 0,
    }
