"""OrcaSlicer layout generator.

Reads PrintConfig.cpp (options), Tab.cpp (pages and groups), Preset.cpp (keys per preset
type) and the Ukrainian .po file. Fails loudly when the source structure changed.
"""
import re
import urllib.error
import urllib.request

from .cpp import LITERALS, method_body, strings, strip_comments
from .po import parse_po
from .store import LayoutError

RAW_URL = "https://raw.githubusercontent.com/SoftFever/OrcaSlicer/{tag}/{path}"
SOURCES = {
    "print_config": "src/libslic3r/PrintConfig.cpp",
    "tab": "src/slic3r/GUI/Tab.cpp",
    "preset": "src/libslic3r/Preset.cpp",
    "po": "localization/i18n/uk/OrcaSlicer_uk.po",
}
# key: (tab, page, group), used to prove that the parsers still understand the sources
WELL_KNOWN = {
    "layer_height": ("process", "Quality", "Layer height"),
    "wall_loops": ("process", "Strength", "Walls"),
    "machine_max_speed_x": ("printer", "Motion ability", "Speed limitation"),
    "machine_max_acceleration_e": ("printer", "Motion ability", "Acceleration limitation"),
    "sparse_infill_density": ("process", "Strength", "Infill"),
    "nozzle_temperature": ("filament", "Filament", "Print temperature"),
    "filament_flow_ratio": ("filament", "Filament", "Flow ratio and Pressure Advance"),
}
MIN_OPTIONS = 400
MIN_TAB_KEYS = {"process": 150, "filament": 40, "printer": 40}
SECRET_KEYS = re.compile(r"^(print_host|print_host_webui|printhost_.*|thumbnails_format)$")

_ADD = re.compile(r'def\s*=\s*this->add(?:_nullable)?\(\s*"(\w+)"(\s*\+\s*axis\.name)?\s*,\s*co(\w+)\s*\)')
_FIELD = re.compile(
    r"def->(label|full_label|tooltip|sidetext|category)\s*=\s*\(?(?:boost::format\()?(?:_?L\()?\s*"
    rf"({LITERALS})")
_ENUM_VALUE = re.compile(rf"def->enum_values\.push_back\(\s*({LITERALS})\)")
_ENUM_LABEL = re.compile(rf"def->enum_labels\.push_back\(\s*(?:_?L\()?\s*({LITERALS})")

_TAB_EVENT = re.compile(
    rf'add_options_page\(\s*(?:_?L\(\s*(?P<page>{LITERALS})\)|(?P<page_var>\w+))'
    rf'|new_optgroup\(\s*_?L\(\s*(?P<group>{LITERALS})\)'
    r'|(?:append_single_option_line|get_option|append_option_line|create_line_with_widget)\('
    r'\s*(?:optgroup(?:\.get\(\))?\s*,\s*)?(?:"(?P<key>\w+)"(?P<axis>\s*\+\s*axis\b)?|(?P<var>\w+)\s*,)'
    r'|for\s*\(\s*(?:const\s+)?std::string\s+\w+\s*:\s*\{(?P<keys>[^}]*)\}')
_VECTOR = re.compile(r'std::vector<std::string>\s+(\w+)\s*\{([^}]*)\}')
_LOOP = re.compile(r'for\s*\(\s*const\s+std::string\s*&\s*(\w+)\s*:\s*(\w+)\s*\)')
TAB_METHODS = {
    "process": ["TabPrint::build"],
    "filament": ["TabFilament::build"],
    "printer": ["TabPrinter::build_fff", "TabPrinter::build_unregular_pages"],
}
PAGE_VARIABLES = {"page_name": "Extruder"}


def fetch_sources(tag: str) -> dict[str, str]:
    sources = {}
    for name, path in SOURCES.items():
        url = RAW_URL.format(tag=tag, path=path)
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                sources[name] = resp.read().decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError) as err:
            raise LayoutError(f"Can't fetch {url}: {err}") from err
    return sources


def parse_options(source: str) -> dict[str, dict]:
    source = strip_comments(source)
    start = source.find("void PrintConfigDef::init_common_params")
    end = source.find("void PrintConfigDef::init_sla_params", start)
    if start < 0 or end < 0:
        raise LayoutError("PrintConfig.cpp: init_common_params / init_sla_params not found")
    source = source[start:end]
    axes = re.search(r"std::vector<AxisDefault>\s+axes\s*\{(.*?)\};", source, re.DOTALL)
    axis_names = re.findall(r'\{\s*"(\w+)"\s*,', axes.group(1)) if axes else []

    matches = list(_ADD.finditer(source))
    options: dict[str, dict] = {}
    for i, match in enumerate(matches):
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(source)
        option = _parse_option(match.group(3), source[match.end():body_end])
        if match.group(2):
            for axis in axis_names:
                options[match.group(1) + axis] = _with_axis(option, axis.upper())
        else:
            options[match.group(1)] = option
    return options


def _parse_option(co_type: str, body: str) -> dict:
    fields: dict[str, str] = {}
    for name, literals in _FIELD.findall(body):
        fields.setdefault(name, strings(literals))
    option = {"type": co_type.lower(), **fields}
    values = [strings(v) for v in _ENUM_VALUE.findall(body)]
    labels = [strings(v) for v in _ENUM_LABEL.findall(body)]
    if values:
        option["enum"] = dict(zip(values, labels if len(labels) == len(values) else values))
    return option


def _with_axis(option: dict, axis: str) -> dict:
    return {k: v.replace("%1%", axis) if isinstance(v, str) else v for k, v in option.items()}


def parse_tabs(source: str) -> dict[str, list[dict]]:
    source = strip_comments(source)
    inlined = {
        "add_filament_overrides_page()": method_body(source, "void TabFilament::add_filament_overrides_page"),
        "build_kinematics_page()": method_body(source, "PageShp TabPrinter::build_kinematics_page"),
    }
    tabs: dict[str, list[dict]] = {}
    for tab, methods in TAB_METHODS.items():
        pages: list[dict] = []
        for method in methods:
            body = method_body(source, f"void {method}")
            if body is None:
                raise LayoutError(f"Tab.cpp: {method} not found")
            for call, code in inlined.items():
                body = body.replace(call, f"{{{code}}}" if code else call)
            _read_tab(body, pages)
        tabs[tab] = [p for p in pages if any(g["keys"] for g in p["groups"])]
        for page in tabs[tab]:
            page["groups"] = [g for g in page["groups"] if g["keys"]]
    return tabs


def _read_tab(body: str, pages: list[dict]):
    page = group = None
    vectors = {name: re.findall(r'"(\w+)"', items) for name, items in _VECTOR.findall(body)}
    loops = dict(_LOOP.findall(body))
    for event in _TAB_EVENT.finditer(body):
        if event["page"] or event["page_var"]:
            variable = event["page_var"]
            if variable and variable not in PAGE_VARIABLES:
                raise LayoutError(f"Tab.cpp: unknown page variable {variable}")
            title = PAGE_VARIABLES.get(variable) or strings(event["page"])
            page = next((p for p in pages if p["page"] == title), None)
            if page is None:
                page = {"page": title, "groups": []}
                pages.append(page)
            group = None
        elif event["group"]:
            if page is None:
                raise LayoutError("Tab.cpp: option group before any page")
            title = strings(event["group"])
            group = next((g for g in page["groups"] if g["title"] == title), None)
            if group is None:
                group = {"title": title, "keys": []}
                page["groups"].append(group)
        elif group is not None:
            if event["var"]:
                keys = vectors.get(loops.get(event["var"]), [])
            elif event["axis"]:
                keys = [event["key"] + axis for axis in vectors.get("axes", [])]
            elif event["key"]:
                keys = [event["key"]]
            else:
                keys = re.findall(r'"(\w+)"', event["keys"])
            group["keys"].extend(k for k in keys if k not in group["keys"])


def parse_preset_keys(preset_source: str, print_config_source: str) -> dict[str, list[str]]:
    preset_source = strip_comments(preset_source)
    extruder = method_body(strip_comments(print_config_source),
                           "void PrintConfigDef::init_extruder_option_keys")
    if extruder is None:
        raise LayoutError("PrintConfig.cpp: init_extruder_option_keys not found")

    def named(name: str) -> list[str]:
        found = re.search(rf"s_Preset_{name}_options\s*\{{(.*?)\}};", preset_source, re.DOTALL)
        if not found:
            raise LayoutError(f"Preset.cpp: s_Preset_{name}_options not found")
        return re.findall(r'"(\w+)"', found.group(1))

    printer = named("printer") + named("machine_limits") + re.findall(r'"(\w+)"', extruder)
    return {
        "process": list(dict.fromkeys(named("print"))),
        "filament": list(dict.fromkeys(named("filament"))),
        "printer": [k for k in dict.fromkeys(printer) if not SECRET_KEYS.match(k)],
    }


def translate_layout(options: dict, tabs: dict, translations: dict[str, str]):
    def uk(text: str | None) -> str | None:
        return translations.get(text) if text else None

    for option in options.values():
        label = option.get("full_label") or option.get("label")
        extras = {"label_uk": uk(option.get("label")), "full_label_uk": uk(label),
                  "tooltip_uk": uk(option.get("tooltip")), "unit_uk": uk(option.get("sidetext"))}
        option.update({k: v for k, v in extras.items() if v})
        if "sidetext" in option:
            option["unit"] = option.pop("sidetext")
        if "enum" in option:
            option["enum_uk"] = {v: translations.get(label, label) for v, label in option["enum"].items()}
    for pages in tabs.values():
        for page in pages:
            page["page_uk"] = translations.get(page["page"], page["page"])
            for group in page["groups"]:
                group["title_uk"] = translations.get(group["title"], group["title"])


def generate(version: str, sources: dict[str, str], well_known: dict | None = None,
             min_options: int = MIN_OPTIONS, min_tab_keys: dict | None = None) -> dict:
    options = parse_options(sources["print_config"])
    tabs = parse_tabs(sources["tab"])
    preset_keys = parse_preset_keys(sources["preset"], sources["print_config"])
    translations = parse_po(sources["po"])
    _validate(options, tabs, preset_keys, translations, WELL_KNOWN if well_known is None else well_known,
              min_options, MIN_TAB_KEYS if min_tab_keys is None else min_tab_keys)
    translate_layout(options, tabs, translations)
    return {"version": version, "options": options, "tabs": tabs, "preset_keys": preset_keys}


def _validate(options, tabs, preset_keys, translations, well_known, min_options, min_tab_keys):
    if len(options) < min_options:
        raise LayoutError(f"Only {len(options)} options parsed from PrintConfig.cpp")
    for tab, minimum in min_tab_keys.items():
        count = sum(len(g["keys"]) for p in tabs[tab] for g in p["groups"])
        if count < minimum:
            raise LayoutError(f"Tab {tab}: only {count} keys parsed from Tab.cpp")
    if not translations:
        raise LayoutError("No translations parsed from the .po file")
    for key, (tab, page, group) in well_known.items():
        titles = [(p["page"], g["title"]) for p in tabs[tab] for g in p["groups"] if key in g["keys"]]
        if (page, group) not in titles:
            raise LayoutError(f"{key}: expected in {tab}/{page}/{group}, found in {titles}")
        if key not in preset_keys[tab]:
            raise LayoutError(f"{key}: not in the {tab} preset keys")
