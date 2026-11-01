"""Minimal gettext .po reader."""
import re

from .cpp import unescape

_LINE = re.compile(r'^(msgctxt|msgid|msgstr)\s+"(.*)"\s*$')
_MORE = re.compile(r'^"(.*)"\s*$')


def parse_po(text: str) -> dict[str, str]:
    """msgid -> msgstr, without empty translations and plural forms."""
    result: dict[str, str] = {}
    entry: dict[str, str] = {}
    field = None

    def flush():
        if entry.get("msgid") and entry.get("msgstr"):
            result.setdefault(unescape(entry["msgid"]), unescape(entry["msgstr"]))
        entry.clear()

    for line in text.splitlines():
        match = _LINE.match(line)
        if match:
            field, value = match.groups()
            if field in entry or field == "msgctxt" or (field == "msgid" and "msgstr" in entry):
                flush()
            entry[field] = value
        elif _MORE.match(line) and field:
            entry[field] = entry.get(field, "") + _MORE.match(line).group(1)
        elif not line.strip() or line.startswith("#"):
            field = None
            if "msgstr" in entry:
                flush()
    flush()
    return result
