import json
from pathlib import Path

import pytest

from app.slicer_meta import LayoutError, LayoutStore, orca
from app.slicer_meta.cpp import method_body, strings, strip_comments
from app.slicer_meta.po import parse_po
from app.slicer_meta.store import BUNDLED

FIXTURES = Path(__file__).parent / "fixtures" / "orca"
TAGS = ["v2.3.2", "v2.4.2"]
WELL_KNOWN = {k: v for k, v in orca.WELL_KNOWN.items() if not k.startswith("machine_")}


def sources(tag):
    return {name: (FIXTURES / tag / Path(path).name).read_text(encoding="utf-8")
            for name, path in orca.SOURCES.items()}


def generate(tag):
    return orca.generate(tag.removeprefix("v"), sources(tag), WELL_KNOWN, 5, {})


def find(layout, key):
    return [(tab, p["page"], g["title"]) for tab, pages in layout["tabs"].items()
            for p in pages for g in p["groups"] if key in g["keys"]]


@pytest.mark.parametrize("tag", TAGS)
@pytest.mark.parametrize("key,place", WELL_KNOWN.items())
def test_fixture_keys_land_in_their_group(tag, key, place):
    layout = generate(tag)
    assert place in find(layout, key)
    assert key in layout["preset_keys"][place[0]]


@pytest.mark.parametrize("tag", TAGS)
def test_fixture_translations_and_enum(tag):
    layout = generate(tag)
    option = layout["options"]["layer_height"]
    assert option["label"] == "Layer height" and option["label_uk"] == "Висота шару"
    assert option["unit"] == "mm" and option["unit_uk"] == "мм"
    assert option["type"] == "float"
    seam = layout["options"]["seam_position"]
    assert seam["enum"]["aligned"] == "Aligned" and seam["enum_uk"]["nearest"] == "Найближче"
    quality = layout["tabs"]["process"][0]
    assert quality["page"] == "Quality" and quality["page_uk"] == "Якість"


@pytest.mark.parametrize("version", ["2.3.2", "2.4.2"])
def test_bundled_layouts(version):
    layout = json.loads((BUNDLED / f"orca-{version}.json").read_text(encoding="utf-8"))
    assert layout["version"] == version
    for key, place in orca.WELL_KNOWN.items():
        assert place in find(layout, key)
    speed = layout["options"]["machine_max_speed_x"]
    assert speed["full_label"] == "Maximum speed X" and speed["unit"] == "mm/s"
    assert "nozzle_diameter" in layout["preset_keys"]["printer"]
    assert not {"print_host", "printhost_apikey"} & set(layout["preset_keys"]["printer"])
    labelled = [o for o in layout["options"].values() if o.get("label_uk") or o.get("full_label_uk")]
    assert len(labelled) > 400


def test_changed_structure_fails_loudly():
    broken = sources("v2.3.2")
    broken["tab"] = broken["tab"].replace("new_optgroup", "add_group")
    with pytest.raises(LayoutError, match="expected in"):
        orca.generate("x", broken, WELL_KNOWN, 5, {})
    broken = sources("v2.3.2")
    broken["print_config"] = broken["print_config"].replace("init_common_params", "other")
    with pytest.raises(LayoutError, match="not found"):
        orca.generate("x", broken, WELL_KNOWN, 5, {})
    with pytest.raises(LayoutError, match="options parsed"):
        orca.generate("x", sources("v2.3.2"), WELL_KNOWN, 5000, {})


def test_cpp_helpers():
    assert strip_comments('a // "x"\nb /* c */ "// keep"') == 'a  \nb   "// keep"'
    assert strings('"one " u8"two\\n"') == "one two\n"
    assert method_body('void A::b() { if (x) { "}"; } } tail', "void A::b") == ' if (x) { "}"; } '
    assert method_body("nothing", "void A::b") is None


def test_po_multiline_and_empty():
    text = 'msgid ""\nmsgstr "Header"\n\nmsgid "a"\n"b"\nmsgstr "c"\n"d"\n\nmsgid "e"\nmsgstr ""\n'
    assert parse_po(text) == {"ab": "cd"}


async def test_store_fetches_unknown_version_and_caches(tmp_path):
    calls = []

    def generator(version):
        calls.append(version)
        return {"version": version, "options": {}, "tabs": {}, "preset_keys": {}}

    store = LayoutStore(tmp_path, generator=generator)
    assert (await store.get("OrcaSlicer", "9.9.9"))["version"] == "9.9.9"
    assert (tmp_path / "orca-9.9.9.json").exists()
    fresh = LayoutStore(tmp_path, generator=generator)
    assert (await fresh.get("OrcaSlicer", "9.9.9"))["version"] == "9.9.9"
    assert calls == ["9.9.9"]


async def test_store_falls_back_to_nearest_bundled(tmp_path):
    def generator(version):
        raise LayoutError("no network")

    store = LayoutStore(tmp_path, generator=generator)
    assert (await store.get("OrcaSlicer", "2.3.9"))["version"] == "2.3.2"
    assert (await store.get("OrcaSlicer", "2.4.1"))["version"] == "2.4.2"
    off = LayoutStore(tmp_path, auto_fetch=False, generator=None)
    assert (await off.get("OrcaSlicer", "2.4.0"))["version"] == "2.4.2"


async def test_store_other_slicers_have_no_layout(tmp_path):
    store = LayoutStore(tmp_path)
    assert await store.get("PrusaSlicer", "2.8.1") is None
    assert await store.get("OrcaSlicer", None) is None
