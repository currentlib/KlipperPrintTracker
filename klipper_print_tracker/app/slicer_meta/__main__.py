"""python -m app.slicer_meta generate --tag v2.3.2 [--out app/layouts]"""
import argparse
import json
import sys
from pathlib import Path

from . import orca
from .store import BUNDLED, LayoutError


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.slicer_meta")
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate", help="generate a layout for an OrcaSlicer tag")
    generate.add_argument("--tag", required=True)
    generate.add_argument("--out", type=Path, default=BUNDLED)
    args = parser.parse_args()

    version = args.tag.removeprefix("v")
    try:
        layout = orca.generate(version, orca.fetch_sources(args.tag))
    except LayoutError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"orca-{version}.json"
    path.write_text(json.dumps(layout, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{path}: {len(layout['options'])} options")
    return 0


if __name__ == "__main__":
    sys.exit(main())
