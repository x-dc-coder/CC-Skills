#!/bin/bash
# render.sh — 一键将 graph-easy 架构描述渲染为多种格式
# Usage: bash render.sh <input.txt> [output_dir]

set -e

INPUT="$1"
OUTDIR="${2:-./output}"

if [ -z "$INPUT" ] || [ ! -f "$INPUT" ]; then
    echo "Usage: bash render.sh <input.txt> [output_dir]"
    echo ""
    echo "  将 graph-easy 架构描述文件渲染为多种格式："
    echo "    - ascii.txt     纯 ASCII 终端版"
    echo "    - boxart.txt    Unicode boxart 终端版"
    echo "    - diagram.png   PNG 图片（via Graphviz dot）"
    echo "    - diagram.svg   SVG 矢量图"
    echo "    - diagram.html  HTML 浏览器版"
    echo "    - diagram.dot   Graphviz DOT 源码"
    exit 1
fi

BASENAME=$(basename "$INPUT" .txt)
mkdir -p "$OUTDIR"

echo "==> 输入: $INPUT"
echo "==> 输出: $OUTDIR/"
echo ""

# 1. ASCII (纯文本)
echo "[1/6] ASCII 终端版..."
graph-easy "$INPUT" --as=ascii > "$OUTDIR/${BASENAME}-ascii.txt"
echo "      → $OUTDIR/${BASENAME}-ascii.txt"

# 2. Boxart (Unicode)
echo "[2/6] Unicode boxart 终端版..."
graph-easy "$INPUT" --as=boxart > "$OUTDIR/${BASENAME}-boxart.txt"
echo "      → $OUTDIR/${BASENAME}-boxart.txt"

# 3. DOT 源码
echo "[3/6] Graphviz DOT 源码..."
graph-easy "$INPUT" --as=dot > "$OUTDIR/${BASENAME}.dot"
echo "      → $OUTDIR/${BASENAME}.dot"

# 4. PNG (via dot)
echo "[4/6] PNG 图片..."
if command -v dot &>/dev/null; then
    graph-easy "$INPUT" --as=dot | dot -Tpng -o "$OUTDIR/${BASENAME}.png" 2>/dev/null && \
        echo "      → $OUTDIR/${BASENAME}.png" || \
        echo "      ⚠ dot 渲染失败，请检查 graphviz 安装"
else
    echo "      ⚠ 未安装 graphviz，跳过 PNG 渲染"
    echo "      安装: sudo apt install -y graphviz"
fi

# 5. SVG
echo "[5/6] SVG 矢量图..."
if graph-easy "$INPUT" --as=svg -o "$OUTDIR/${BASENAME}.svg" 2>/dev/null; then
    echo "      → $OUTDIR/${BASENAME}.svg"
else
    echo "      ⚠ SVG 渲染失败（可能需要 libgraph-easy-as-svg-perl）"
fi

# 6. HTML
echo "[6/6] HTML 网页版..."
graph-easy "$INPUT" --as=html > "$OUTDIR/${BASENAME}.html"
echo "      → $OUTDIR/${BASENAME}.html"

echo ""
echo "==> 完成！共生成 $(ls "$OUTDIR/${BASENAME}"* 2>/dev/null | wc -l) 个文件"
echo ""
echo "预览方式："
echo "  终端:   cat $OUTDIR/${BASENAME}-boxart.txt"
echo "  图片:   code $OUTDIR/${BASENAME}.png"
echo "  浏览器: xdg-open $OUTDIR/${BASENAME}.html 2>/dev/null || echo '  手动打开: $OUTDIR/${BASENAME}.html'"
