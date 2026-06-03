"""命令行入口"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

try:
    from scripts.usecase import render_usecase_diagram
except ImportError:
    from usecase import render_usecase_diagram


SKILLS_ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve_output_path(input_file: Path | None, skill_name: str, default_name: str = "diagram.png") -> Path:
    """从输入文件路径推断项目目录，默认输出到 <项目目录>/thesis-output/img/"""
    if input_file and input_file.is_absolute():
        for parent in input_file.resolve().parents:
            if (parent / "thesis-output").exists() or (parent / "docs").exists():
                output_dir = parent / "thesis-output" / "img"
                output_dir.mkdir(parents=True, exist_ok=True)
                return output_dir / default_name
    return SKILLS_ROOT / "output" / skill_name / default_name
    today = date.today().isoformat()
    out = Path("/tmp/skills-output") / today / skill_name
    out.mkdir(parents=True, exist_ok=True)
    return out / default_name


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
    parser.add_argument("--out", default=None, help="Output PNG path (default: auto-detect from input file)")
    parser.add_argument(
        "--safe-margin", type=int, default=24, help="Safe white margin in pixels after auto-crop"
    )
    parser.add_argument("--no-auto-crop", action="store_true", help="Disable automatic content-based crop")
    parser.add_argument("--scale", type=int, default=None, help="Render scale factor (higher = more pixels)")
    parser.add_argument("--downsample", action="store_true", help="Downsample output to 1x (default: output high-res)")
    args = parser.parse_args()

    # 读取 JSON
    json_data = json.loads(Path(args.json_file).read_text(encoding="utf-8"))

    # 渲染
    kwargs = dict(
        auto_crop=not args.no_auto_crop,
        safe_margin=max(0, args.safe_margin),
        downsample_output=args.downsample,
    )
    if args.scale is not None:
        kwargs["scale"] = args.scale

    png = render_usecase_diagram(json_data, **kwargs)

    # 确定输出路径
    output_path = args.out
    if output_path is None:
        output_path = _resolve_output_path(Path(args.json_file), "diagram-usecase")
    else:
        output_path = Path(output_path)

    # 确保输出目录存在
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_path.write_bytes(png)
    print(f"Generated: {output_path}")


if __name__ == "__main__":
    main()
