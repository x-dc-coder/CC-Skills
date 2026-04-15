"""命令行入口"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scripts.usecase import render_usecase_diagram
except ImportError:
    from usecase import render_usecase_diagram


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate use case diagram PNG",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate from JSON file (single actor format)
  python -m scripts.cli --json-file usecase.json --out diagram.png

  # Use default output path
  python -m scripts.cli --json-file usecase.json
        """,
    )
    parser.add_argument("--json-file", required=True, help="Path to JSON data file")
    parser.add_argument("--out", default=None, help="Output PNG path (default: docs/usecase/diagram.png)")
    parser.add_argument(
        "--safe-margin", type=int, default=24, help="Safe white margin in pixels after auto-crop"
    )
    parser.add_argument("--no-auto-crop", action="store_true", help="Disable automatic content-based crop")
    args = parser.parse_args()

    # 读取 JSON
    json_data = json.loads(Path(args.json_file).read_text(encoding="utf-8"))

    # 渲染
    png = render_usecase_diagram(
        json_data,
        auto_crop=not args.no_auto_crop,
        safe_margin=max(0, args.safe_margin),
    )

    # 确定输出路径
    output_path = args.out
    if output_path is None:
        output_path = "docs/usecase/diagram.png"

    # 确保输出目录存在
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    output_file.write_bytes(png)
    print(f"Generated: {output_path}")


if __name__ == "__main__":
    main()
