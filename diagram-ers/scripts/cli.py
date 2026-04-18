"""命令行入口"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scripts.renderer import render_er_diagram
except ImportError:
    from renderer import render_er_diagram


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate ER diagram PNG (multi-entity, no attributes)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m scripts.cli --json-file er.json --out diagram.png
  python -m scripts.cli --json-file er.json
        """,
    )
    parser.add_argument("--json-file", required=True, help="Path to JSON data file")
    parser.add_argument("--out", default=None, help="Output PNG path (default: docs/er/diagram.png)")
    parser.add_argument(
        "--safe-margin", type=int, default=24, help="Safe white margin in pixels after auto-crop"
    )
    parser.add_argument("--no-auto-crop", action="store_true", help="Disable automatic content-based crop")
    args = parser.parse_args()

    json_data = json.loads(Path(args.json_file).read_text(encoding="utf-8"))

    png = render_er_diagram(
        json_data,
        auto_crop=not args.no_auto_crop,
        safe_margin=max(0, args.safe_margin),
    )

    output_path = args.out
    if output_path is None:
        output_path = "docs/er/diagram.png"

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_bytes(png)
    print(f"Generated: {output_path}")


if __name__ == "__main__":
    main()
