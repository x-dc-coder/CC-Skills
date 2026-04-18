"""命令行入口：从 JSON 生成时序图 PNG

支持两种模式：
1. --json-file : 从 JSON 生成 Mermaid 代码并渲染
2. --mmd-file  : 直接渲染已有的 .mmd 文件
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def _json_to_mermaid(data: dict) -> str:
    """将 JSON 数据转换为 Mermaid sequenceDiagram 代码"""
    lines = ["sequenceDiagram"]

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


def _render_mmd(mmd_text: str, output_path: str, bg: str = "white", scale: int = 2) -> None:
    """调用 mmdc 渲染 Mermaid 代码为 PNG"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".mmd", delete=False, encoding="utf-8") as f:
        f.write(mmd_text)
        mmd_path = f.name

    try:
        cmd = [
            "mmdc",
            "-i", mmd_path,
            "-o", output_path,
            "-b", bg,
            "-s", str(scale),
        ]
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
    parser.add_argument("--out", default=None, help="Output PNG path (default: docs/sequence/diagram.png)")
    parser.add_argument("--bg", default="white", help="Background color (default: white)")
    parser.add_argument("--scale", type=int, default=2, help="Scale factor (default: 2)")
    args = parser.parse_args()

    # 确定输出路径
    output_path = args.out
    if output_path is None:
        output_path = "docs/sequence/diagram.png"

    # 确保输出目录存在
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # 生成 Mermaid 代码
    if args.json_file:
        json_data = json.loads(Path(args.json_file).read_text(encoding="utf-8"))
        mmd_text = _json_to_mermaid(json_data)

        # 同时保存 .mmd 源文件
        mmd_out = output_file.with_suffix(".mmd")
        mmd_out.write_text(mmd_text, encoding="utf-8")
        print(f"Generated Mermaid: {mmd_out}")
    else:
        mmd_text = Path(args.mmd_file).read_text(encoding="utf-8")

    # 渲染 PNG
    _render_mmd(mmd_text, str(output_path), bg=args.bg, scale=args.scale)
    print(f"Generated PNG: {output_path}")


if __name__ == "__main__":
    main()
