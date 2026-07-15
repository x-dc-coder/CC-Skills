"""命令行入口：从 JSON 生成时序图 PNG

支持两种模式：
1. --json-file : 从 JSON 生成 Mermaid 代码并渲染
2. --mmd-file  : 直接渲染已有的 .mmd 文件
"""

from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
import tempfile
from pathlib import Path


SKILLS_ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve_output_path(input_file: Path | None, skill_name: str, default_name: str = "sequence-diagram.png") -> Path:
    """推断输出路径：<项目目录>/thesis-output/<skill-name>/ 或 ~/.claude/skills-output/<skill-name>/"""
    if input_file and input_file.is_absolute():
        for parent in input_file.resolve().parents:
            if (parent / "thesis-output").exists() or (parent / "docs").exists():
                output_dir = parent / "thesis-output" / skill_name
                output_dir.mkdir(parents=True, exist_ok=True)
                return output_dir / default_name
    out = Path.home() / ".claude" / "skills-output" / skill_name
    out.mkdir(parents=True, exist_ok=True)
    return out / default_name


def _json_to_mermaid(data: dict) -> str:
    """将 JSON 数据转换为 Mermaid sequenceDiagram 代码"""
    lines = [
        "%%{init: {'themeVariables': { 'fontFamily': 'SimSun, Noto Serif CJK SC, serif', 'fontSize': '12px'}}}%%",
        "sequenceDiagram",
    ]

    # 参与者声明
    # sequenceDiagram 只支持 actor 和 participant 两种显式声明类型
    # database 等类型在 sequenceDiagram 中不支持，降级为 participant
    for p in data.get("participants", []):
        ptype = p.get("type", "participant")
        name = p["name"]
        if ptype == "actor":
            lines.append(f"    actor {name}")
        else:
            # participant / database / 其他都统一为 participant
            lines.append(f"    participant {name}")

    # 消息
    active_stack: dict[str, int] = {}
    for msg in data.get("messages", []):
        src = msg["from"]
        dst = msg["to"]
        text = msg.get("text", "")
        dashed = msg.get("dashed", False)
        activate = msg.get("activate", False)
        deactivate = msg.get("deactivate", False)
        note = msg.get("note", "")

        # 处理自调用
        arrow = "-->>" if dashed else "->>"
        if src == dst:
            # sequenceDiagram 不支持 A->>A 直接自调用，用 activate 模拟
            lines.append(f"    activate {src}")
            lines.append(f"    {src}{arrow}{src}: {text}")
        else:
            lines.append(f"    {src}{arrow}{dst}: {text}")

        # 生命周期
        if activate and not dashed:
            lines.append(f"    activate {dst}")
            active_stack[dst] = active_stack.get(dst, 0) + 1

        if deactivate:
            # 默认去激活发送方（表示发送方完成）
            target = src
            if target in active_stack and active_stack[target] > 0:
                lines.append(f"    deactivate {target}")
                active_stack[target] -= 1

        # 备注
        if note:
            lines.append(f"    Note over {src},{dst}: {note}")

    # 自动关闭未关闭的生命周期
    for name, count in active_stack.items():
        for _ in range(count):
            lines.append(f"    deactivate {name}")

    title = data.get("title", "")
    if title:
        lines.insert(0, f"---\ntitle: {title}\n---")

    return "\n".join(lines) + "\n"


def _render_mmd(mmd_text: str, output_path: str, bg: str = "white", scale: int = 2, fmt: str = "png") -> None:
    """调用 mmdc 渲染 Mermaid 代码为 PNG 或 SVG"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".mmd", delete=False, encoding="utf-8") as f:
        f.write(mmd_text)
        mmd_path = f.name

    try:
        cmd = [
            "mmdc",
            "-i", mmd_path,
            "-o", output_path,
            "-e", fmt,
        ]
        if fmt == "png":
            cmd.extend(["-b", bg, "-s", str(scale)])
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"mmdc error:\n{result.stderr}", file=sys.stderr)
            sys.exit(1)
    finally:
        Path(mmd_path).unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate sequence diagram PNG from JSON or Mermaid file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate from JSON file
  python -m scripts.cli --json-file sequence.json --out diagram.png

  # Render existing Mermaid file
  python -m scripts.cli --mmd-file sequence.mmd --out diagram.png

  # Use default output path
  python -m scripts.cli --json-file sequence.json
        """,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--json-file", help="Path to JSON data file")
    group.add_argument("--mmd-file", help="Path to existing Mermaid file")
    parser.add_argument("--out", default=None, help="Output path (default: auto-detect from input file)")
    parser.add_argument("--bg", default="white", help="Background color for PNG (default: white)")
    parser.add_argument("--scale", type=int, default=2, help="Scale factor for PNG (default: 2)")
    parser.add_argument("--format", default="png", choices=["png", "svg"], help="Output format: png or svg (default: png)")
    args = parser.parse_args()

    # 确定输入文件（用于推断项目目录）
    input_file = None
    if args.json_file:
        input_file = Path(args.json_file)
    elif args.mmd_file:
        input_file = Path(args.mmd_file)

    # 确定输出路径
    output_path = args.out
    if output_path is None:
        output_path = _resolve_output_path(input_file, "diagram-sequence")
    else:
        output_path = Path(output_path)

    # 确保输出目录存在
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 生成 Mermaid 代码
    if args.json_file:
        json_data = json.loads(Path(args.json_file).read_text(encoding="utf-8"))
        mmd_text = _json_to_mermaid(json_data)

        # 同时保存 .mmd 源文件到与输出 PNG 同目录
        mmd_out = output_path.parent / f"{output_path.stem}.mmd"
        mmd_out.write_text(mmd_text, encoding="utf-8")
        print(f"Generated Mermaid: {mmd_out}")
    else:
        mmd_text = Path(args.mmd_file).read_text(encoding="utf-8")

    # 渲染
    _render_mmd(mmd_text, str(output_path), bg=args.bg, scale=args.scale, fmt=args.format)
    print(f"Generated {args.format.upper()}: {output_path}")


if __name__ == "__main__":
    main()
