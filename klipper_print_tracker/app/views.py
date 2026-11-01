"""Settings data shaped for the UI: tabs and groups of the slicer, labels and units."""
import re

from . import gcode
from .settings_git import PRESET_IDS, diff_configs
from .slicer_meta.store import version_key

TAB_ORDER = ("process", "filament", "printer")
BOOLEANS = {"bool", "bools"}


def humanise(key: str) -> str:
    return re.sub(r"[_\s]+", " ", key).strip().capitalize()


def describe(key: str, layout: dict | None) -> dict:
    option = (layout or {}).get("options", {}).get(key)
    if not option:
        return {"key": key, "label": humanise(key)}
    label = option.get("label_uk") or option.get("full_label_uk") or option.get("label") \
        or option.get("full_label") or humanise(key)
    return {"key": key, "label": label,
            "unit": option.get("unit_uk") or option.get("unit"),
            "tooltip": option.get("tooltip_uk") or option.get("tooltip")}


def display(key: str, value: str | None, layout: dict | None) -> dict:
    """A raw value plus what the slicer's UI shows for it."""
    option = (layout or {}).get("options", {}).get(key) or {}
    labels = option.get("enum_uk") or option.get("enum")
    if value is None:
        return {"raw": None}
    if labels:
        return {"raw": value, "text": ", ".join(labels.get(v, v) for v in value.split(","))}
    if option.get("type") in BOOLEANS and set(value.split(",")) <= {"0", "1"}:
        return {"raw": value, "flags": [v == "1" for v in value.split(",")]}
    return {"raw": value}


def grouped(keys, layout: dict | None, make_row) -> list[dict]:
    """Slicer tabs with the given keys, the rest goes to the "other" tab."""
    remaining = dict.fromkeys(keys)
    tabs = []
    for tab in TAB_ORDER if layout else ():
        pages = []
        for page in layout["tabs"].get(tab, []):
            groups = []
            for group in page["groups"]:
                rows = [make_row(k) for k in group["keys"] if k in remaining]
                for key in group["keys"]:
                    remaining.pop(key, None)
                if rows:
                    groups.append({"title": group.get("title_uk") or group["title"], "rows": rows})
            if groups:
                pages.append({"title": page.get("page_uk") or page["page"], "groups": groups})
        if pages:
            tabs.append({"id": tab, "pages": pages})
    if remaining:
        rows = [make_row(k) for k in sorted(remaining)]
        tabs.append({"id": "other", "pages": [{"title": None, "groups": [{"title": None, "rows": rows}]}]})
    return tabs


def settings_tabs(config: dict, layout: dict | None) -> list[dict]:
    return grouped(config, layout, lambda k: {**describe(k, layout), **display(k, config[k], layout)})


def labelled_diff(diff: list[dict], layout: dict | None) -> list[dict]:
    return [{**describe(d["key"], layout), "old": display(d["key"], d["old"], layout),
             "new": display(d["key"], d["new"], layout)} for d in diff]


def compare_tabs(a: dict, b: dict, layout: dict | None) -> list[dict]:
    diff = {d["key"]: d for d in diff_configs(a, b)}
    return grouped(diff, layout, lambda k: {
        **describe(k, layout), "a": display(k, diff[k]["old"], layout), "b": display(k, diff[k]["new"], layout)})


def newer_version(a: str | None, b: str | None) -> str | None:
    if not a or not b:
        return a or b
    return a if version_key(a) >= version_key(b) else b


def preset_values(config: dict, kind: str, name: str, keys: list[str]) -> dict:
    """Values of one preset in a config, per-filament lists reduced to that filament."""
    selected = {k: config[k] for k in keys if k in config} if keys else {}
    if kind != "filament":
        return selected
    names = gcode.split_values(config.get(PRESET_IDS["filament"], ""))
    if name not in names:
        return selected
    index = names.index(name)
    return {k: gcode.filament_value(v, index, len(names)) for k, v in selected.items()}
