from __future__ import annotations

import argparse
from pathlib import Path

try:
    from scripts.parser import ddl_to_model
    from scripts.renderer import render_diagram_png
except ImportError:
    from parser import ddl_to_model
    from renderer import render_diagram_png


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate ER diagram PNG from SQL DDL")
    parser.add_argument("--sql-file", required=True, help="Path to SQL DDL file")
    parser.add_argument("--out", default="er.png", help="Output PNG path")
    parser.add_argument("--dialect", default="mysql", help="SQL dialect for sqlglot")
    args = parser.parse_args()

    sql_text = Path(args.sql_file).read_text(encoding="utf-8")
    model = ddl_to_model(sql_text, dialect=args.dialect)

    png = render_diagram_png(model)
    Path(args.out).write_bytes(png)

    print(f"Generated: {args.out}")
    if model.get("warnings"):
        print("Warnings:")
        for w in model["warnings"]:
            print(f"- {w}")


if __name__ == "__main__":
    main()
