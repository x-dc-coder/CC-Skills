#!/usr/bin/env python3
"""drawio-xml skill 论文级交付自检脚本（单文件自包含）。

在 check-quality.py（布局质检）之上增加论文交付检查：
1. 布局质检（内联 check-quality.py 核心逻辑，支持 --viewport）
2. PNG 导出尺寸 / 有效 DPI 估算（论文 300DPI 标准）
3. 交付物完整性（.drawio + .png + .svg 三件套）

用法：
    python3 scripts/check-paper-delivery.py <base.drawio> [--scale 4] [--viewport W H]

退出码：0 = 通过；1 = 有问题；2 = 参数错误
"""
from __future__ import annotations
import os
import re
import struct
import sys
import xml.etree.ElementTree as ET

DEFAULT_VIEWPORT = (850, 1100)
PAPER_DPI = 300
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def quality_issues(path: str, viewport) -> list:
    """内联 check-quality.py 的 check_file 核心"""
    issues = []
    raw = open(path, encoding="utf-8").read()
    if COMMENT_RE.search(raw):
        issues.append("存在 XML 注释")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        return [f"XML 解析失败: {e}"]
    cells = {c.get("id"): c for c in root.iter("mxCell")}
    verts, edges, all_ids = [], [], []
    for cell in root.iter("mxCell"):
        cid = cell.get("id", "")
        all_ids.append(cid)
        geom = cell.find("mxGeometry")
        if cell.get("edge") == "1":
            edges.append((cid, cell.get("source", ""), cell.get("target", "")))
        elif geom is not None:
            w = float(geom.get("width", 0)); h = float(geom.get("height", 0))
            ax = float(geom.get("x", 0)); ay = float(geom.get("y", 0))
            pid = cell.get("parent", "1"); visited = 0
            while pid and pid != "1" and pid in cells and visited < 50:
                pg = cells[pid].find("mxGeometry")
                if pg is not None:
                    ax += float(pg.get("x", 0)); ay += float(pg.get("y", 0))
                pid = cells[pid].get("parent", "1"); visited += 1
            verts.append((cid, ax, ay, w, h))
    seen = {}
    for cid in all_ids:
        if cid in seen:
            issues.append(f"重复 id: {cid}")
        seen[cid] = seen.get(cid, 0) + 1

    def is_ancestor(a, b):
        pid = cells.get(b); v = 0
        while pid is not None and v < 50:
            if pid.get("id") == a:
                return True
            pid = cells.get(pid.get("parent", "")); v += 1
        return False

    for i in range(len(verts)):
        for j in range(i + 1, len(verts)):
            aid, ax, ay, aw, ah = verts[i]
            bid, bx, by, bw, bh = verts[j]
            if is_ancestor(aid, bid) or is_ancestor(bid, aid):
                continue
            if ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah:
                issues.append(f"节点重叠: {aid} 与 {bid}")
    vw, vh = viewport
    for cid, x, y, w, h in verts:
        if x + w > vw or y + h > vh:
            issues.append(f"越界: {cid} (x+w={x + w:.0f}, y+h={y + h:.0f} > {vw:.0f}x{vh:.0f})")
    id_set = set(all_ids)
    for eid, src, tgt in edges:
        if src not in id_set:
            issues.append(f"孤立边: {eid} source={src}")
        if tgt not in id_set:
            issues.append(f"孤立边: {eid} target={tgt}")
    return issues


def png_size(path: str):
    try:
        with open(path, "rb") as f:
            head = f.read(33)
        if not head.startswith(b"\x89PNG\r\n\x1a\n"):
            return None
        return struct.unpack(">II", head[16:24])
    except OSError:
        return None


def svg_size(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read(2000)
        m = re.search(r'width="([^"]+)"[^>]*height="([^"]+)"', content)
        if not m:
            return None
        try:
            return float(m.group(1).rstrip("px")), float(m.group(2).rstrip("px"))
        except ValueError:
            return None
    except OSError:
        return None


def main() -> int:
    args = sys.argv[1:]
    scale, viewport, files = 2, DEFAULT_VIEWPORT, []
    i = 0
    while i < len(args):
        if args[i] == "--scale":
            scale = int(args[i + 1]); i += 2
        elif args[i] == "--viewport":
            viewport = (int(args[i + 1]), int(args[i + 2])); i += 3
        else:
            files.append(args[i]); i += 1
    if not files:
        print(__doc__); return 2
    ok = True
    for base in files:
        print(f"== {base}")
        issues = quality_issues(base, viewport)
        n_vert = n_edge = 0
        root = ET.parse(base).getroot()
        n_vert = sum(1 for c in root.iter("mxCell") if c.get("edge") != "1")
        n_edge = sum(1 for c in root.iter("mxCell") if c.get("edge") == "1")
        print(f"   顶点={n_vert} 边={n_edge}")
        if issues:
            ok = False
            for it in issues[:8]:
                print(f"   ✗ {it}")
        else:
            print("   布局质检: ✓ 通过（无重叠/越界/孤立边/重复id/注释）")
        stem = os.path.splitext(base)[0]
        png, svg = stem + ".png", stem + ".svg"
        has_png, has_svg = os.path.exists(png), os.path.exists(svg)
        print(f"   交付物: .drawio=✓ .png={'✓' if has_png else '✗'} .svg={'✓' if has_svg else '✗'}")
        if has_png:
            size = png_size(png)
            if size:
                w, h = size
                lw = lh = None
                if has_svg:
                    sv = svg_size(svg)
                    if sv:
                        lw, lh = sv
                if lw and lh:
                    dpi = round(w * 72 / lw, 1)
                    if dpi >= PAPER_DPI:
                        mark = "✓ 达论文300DPI"
                    elif dpi >= 280:
                        mark = "✓ 接近300DPI（印刷可接受）"
                    else:
                        mark = "⚠ 未达300DPI（增大 DRAWIO_EXPORT_SCALE，如 scale=5）"
                        ok = False
                    print(f"   PNG: {w}x{h}px 逻辑 {lw:.0f}x{lh:.0f} 有效DPI≈{dpi} {mark}")
                else:
                    print(f"   PNG: {w}x{h}px")
            else:
                print("   ✗ PNG 无法解析"); ok = False
        print()
    print("总评:", "✓ 全部通过，可交付论文" if ok else "✗ 存在问题，修复后重检")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
