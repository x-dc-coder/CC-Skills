from __future__ import annotations

import argparse
from pathlib import Path

try:
    from scripts.parser import ddl_to_model
    from scripts.renderer import render_diagram_png
except ImportError:
    from parser import ddl_to_model
    from renderer import render_diagram_png


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate ER diagram PNG from SQL DDL")
    parser.add_argument("--sql-file", required=True, help="Path to SQL DDL file")
    parser.add_argument("--out", default=None, help="Output PNG path (default: auto-detect from input file)")
    parser.add_argument("--dialect", default="mysql", help="SQL dialect for sqlglot")
    parser.add_argument("--scale", type=int, default=4, help="Render scale factor (default: 4, higher = more pixels)")
    parser.add_argument("--downsample", action="store_true", help="Downsample output to 1x (default: output high-res)")
    args = parser.parse_args()

    sql_text = Path(args.sql_file).read_text(encoding="utf-8")
    model = ddl_to_model(sql_text, dialect=args.dialect)

    png = render_diagram_png(model, scale=args.scale, downsample_output=args.downsample)

    output_path = args.out
    if output_path is None:
        output_path = _resolve_output_path(Path(args.sql_file), "diagram-er")
    else:
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(png)

    print(f"Generated: {output_path}")


if __name__ == "__main__":
    main()
