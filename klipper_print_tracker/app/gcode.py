"""Slicer data embedded in G-code files."""
import hashlib
import json
import re

_LINE = re.compile(r"^;\s*([A-Za-z0-9_.\[\]-]+)\s*=\s?(.*)$")
_HEADER = re.compile(r"generated (?:by|with)\s+(\S+?)[ _](?:SteamEngine )?(\d[\w.+-]*)", re.IGNORECASE)
_BAMBU = re.compile(r"^;\s*(BambuStudio)\s+(\d[\w.+-]*)", re.MULTILINE)
_FILAMENT = re.compile(r"^;\s*filament:\s*([\d,\s]+)$", re.MULTILINE)
_VALUES = re.compile(r'"((?:[^"\\]|\\.)*)"|([^;,"]+)')
# Slicers can embed printer host credentials, those never leave the G-code.
_SECRET = re.compile(r"(print_?host|api_?key|password|token|secret)", re.IGNORECASE)


def parse_config(text: str) -> dict[str, str] | None:
    """Keys and raw values of the config block, None when the file has none.

    OrcaSlicer repeats some keys, the last value is the effective one.
    """
    start = text.find("CONFIG_BLOCK_START")
    end = text.find("CONFIG_BLOCK_END", start)
    if start < 0 or end < 0:
        return None
    config = {}
    for line in text[start:end].splitlines()[1:]:
        match = _LINE.match(line)
        if match and not _SECRET.search(match.group(1)):
            config[match.group(1)] = match.group(2).rstrip()
    return config or None


def parse_slicer(head: str) -> tuple[str | None, str | None]:
    match = _HEADER.search(head) or _BAMBU.search(head)
    return (match.group(1), match.group(2)) if match else (None, None)


def used_filaments(head: str) -> list[int] | None:
    """Zero-based indexes from the header, None when the header doesn't say."""
    match = _FILAMENT.search(head)
    if not match:
        return None
    return [int(x) - 1 for x in re.findall(r"\d+", match.group(1))] or None


def split_values(raw: str) -> list[str]:
    """Split `"a";"b"` or `1,2` into values."""
    values = []
    for quoted, plain in _VALUES.findall(raw):
        value = quoted or plain.strip()
        if value:
            values.append(value)
    return values


def filament_value(raw: str, index: int, count: int) -> str:
    """The value of one filament from a per-filament list."""
    values = split_values(raw)
    return values[index] if count > 1 and len(values) == count else raw


def config_hash(config: dict) -> str:
    content = json.dumps(config, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(content.encode()).hexdigest()
