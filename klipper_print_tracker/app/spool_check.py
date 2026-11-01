"""Compares the print about to start with the active Spoolman spool."""
import math
import re

from . import gcode

PAUSE_ON = ("not_enough", "material_mismatch")
WORD = re.compile(r"[^\W_]{3,}")


def required_grams(metadata: dict, config: dict | None, filament_index: int = 0) -> float | None:
    """Weight from the slicer, or from length and density when only those are known."""
    weight = float(metadata.get("filament_weight_total") or 0)
    if weight > 0:
        return round(weight, 1)
    length = float(metadata.get("filament_total") or 0)
    densities = gcode.split_values((config or {}).get("filament_density", ""))
    diameters = gcode.split_values((config or {}).get("filament_diameter", ""))
    if length <= 0 or filament_index >= min(len(densities), len(diameters)):
        return None
    area = math.pi * (float(diameters[filament_index]) / 2) ** 2
    return round(length * area * float(densities[filament_index]) / 1000, 1)


def same_material(wanted: str, actual: str) -> bool:
    """PETG matches PETG-CF, a spool that says PLA doesn't satisfy PETG."""
    a, b = wanted.upper(), actual.upper()
    return a == b or a.startswith(f"{b}-") or b.startswith(f"{a}-") or a.startswith(f"{b}+") or b.startswith(f"{a}+")


def preset_looks_like(preset: str, spool: dict) -> bool:
    filament = spool.get("filament") or {}
    names = f"{(filament.get('vendor') or {}).get('name') or ''} {filament.get('name') or ''}"
    return bool({w.lower() for w in WORD.findall(preset)} & {w.lower() for w in WORD.findall(names)})


def check(required: float | None, spool: dict | None, material: str | None, preset: str | None,
          margin_percent: float) -> dict:
    """A spool of None means Moonraker has no active spool."""
    result = {"required_g": required, "material": material, "preset": preset, "warnings": []}
    if spool is None:
        result["warnings"].append({"code": "no_spool"})
        return result
    filament = spool.get("filament") or {}
    remaining = spool.get("remaining_weight")
    spool_material = filament.get("material")
    result.update(spool=" ".join(x for x in ((filament.get("vendor") or {}).get("name"), filament.get("name")) if x),
                  spool_id=spool.get("id"), remaining_g=remaining, spool_material=spool_material)
    if required and remaining is not None and remaining < required * (1 + margin_percent / 100):
        result["warnings"].append({"code": "not_enough", "required_g": required, "remaining_g": remaining})
    if material and spool_material and not same_material(material, spool_material):
        result["warnings"].append({"code": "material_mismatch", "wanted": material, "actual": spool_material})
    if preset and not preset_looks_like(preset, spool):
        result["warnings"].append({"code": "preset_mismatch", "info": True, "preset": preset})
    return result


def should_warn(result: dict) -> bool:
    return any(not w.get("info") for w in result["warnings"])


def should_pause(result: dict) -> bool:
    return any(w["code"] in PAUSE_ON for w in result["warnings"])
