import re
from pathlib import Path

import yaml

ADDON = Path(__file__).parents[1]
CONFIG = yaml.safe_load((ADDON / "config.yaml").read_text(encoding="utf-8"))
SCHEMA_TYPE = re.compile(r"^(str|password|bool|int|float|email|url|port|match\(.+\)|list\(.+\)|device)(\(.*\))?\??$")


def test_required_fields():
    for key in ("name", "version", "slug", "description", "arch"):
        assert CONFIG[key]
    assert isinstance(CONFIG["version"], str)
    assert re.fullmatch(r"[a-z0-9_]+", CONFIG["slug"])
    assert set(CONFIG["arch"]) == {"aarch64", "amd64"}


def test_ingress_and_services():
    assert CONFIG["ingress"] is True and CONFIG["ingress_port"] == 8099
    assert CONFIG["panel_icon"] == "mdi:printer-3d" and CONFIG["panel_title"] == "Print Tracker"
    assert CONFIG["homeassistant_api"] is True
    assert "mqtt:want" in CONFIG["services"]
    assert CONFIG["init"] is False
    assert CONFIG["ports"] == {"8100/tcp": None}


def test_schema_types_and_defaults():
    schema, options = CONFIG["schema"], CONFIG["options"]
    assert all(SCHEMA_TYPE.match(str(v)) for v in schema.values())
    assert set(options) <= set(schema)
    required = {k for k, v in schema.items() if not str(v).endswith("?")} - set(options)
    assert required == {"moonraker_url"}


def test_translations_cover_every_option():
    translations = yaml.safe_load((ADDON / "translations/en.yaml").read_text(encoding="utf-8"))
    assert set(translations["configuration"]) == set(CONFIG["schema"])
    assert all(v["name"] and v["description"] for v in translations["configuration"].values())


def test_options_match_the_code():
    from dataclasses import fields

    from app.config import Options
    assert set(CONFIG["schema"]) == {f.name for f in fields(Options)}


def test_repository_files():
    root = yaml.safe_load((ADDON.parent / "repository.yaml").read_text(encoding="utf-8"))
    assert root["name"]
    assert not (ADDON / "build.yaml").exists()
    for name in ("Dockerfile", "run.sh", "DOCS.md", "CHANGELOG.md", "icon.png", "logo.png", "requirements.txt"):
        assert (ADDON / name).exists(), name
    assert (ADDON / "Dockerfile").read_text().startswith("FROM ghcr.io/home-assistant/base-python:")
