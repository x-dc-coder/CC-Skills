"""命令行入口"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
from common import resolve_output_path

from scripts.renderer import render_er_diagram


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
    parser.add_argument("--out", default=None, help="Output PNG path (default: auto-detect from input file)")
    parser.add_argument(
        "--safe-margin", type=int, default=24, help="Safe white margin in pixels after auto-crop"
    )
    parser.add_argument("--no-auto-crop", action="store_true", help="Disable automatic content-based crop")
    parser.add_argument("--scale", type=int, default=None, help="Render scale factor (higher = more pixels)")
    parser.add_argument("--downsample", action="store_true", help="Downsample output to 1x (default: output high-res)")
    args = parser.parse_args()

    json_data = json.loads(Path(args.json_file).read_text(encoding="utf-8"))

    kwargs = dict(
        auto_crop=not args.no_auto_crop,
        safe_margin=max(0, args.safe_margin),
        downsample_output=args.downsample,
    )
    if args.scale is not None:
        kwargs["scale"] = args.scale

    png = render_er_diagram(json_data, **kwargs)

    output_path = args.out
    if output_path is None:
        output_path = resolve_output_path(Path(args.json_file), "diagram-ers", "ers-diagram.png")
    else:
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(png)
    print(f"Generated: {output_path}")


if __name__ == "__main__":
    main()
