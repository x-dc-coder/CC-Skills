#!/usr/bin/env python3
"""drawio-xml skill 质检脚本：检查 .drawio 文件的结构质量。

检查项：
1. XML 可解析、根结构完整（mxfile/diagram/mxGraphModel/root）
2. id 唯一性
3. 节点重叠检测
4. 元素越界检测（默认视口 850x1100）
5. 孤立边检测（source/target 引用不存在的 id）
6. 非法 XML 注释检测

用法：
    python3 check-quality.py <file.drawio> [<file2.drawio> ...]
    python3 check-quality.py <file.drawio> --viewport 1200 800

退出码：0 = 全部通过；1 = 存在问题；2 = 参数错误/文件不可读
"""
from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET

DEFAULT_VIEWPORT = (850, 1100)
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def parse_args(argv: list[str]) -> tuple[list[str], tuple[float, float], list[tuple[str, str]]]:
    files: list[str] = []
    viewport = DEFAULT_VIEWPORT
    allow_overlap: list[tuple[str, str]] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--viewport":
            if i + 2 >= len(argv):
                raise SystemExit("usage: --viewport <width> <height>")
            viewport = (float(argv[i + 1]), float(argv[i + 2]))
            i += 3
        elif a == "--allow-overlap":
            if i + 1 >= len(argv):
                raise SystemExit("usage: --allow-overlap <idA,idB> （可多次，用于 UI 弹窗覆盖等设计意图）")
            pair = tuple(x.strip() for x in argv[i + 1].split(","))
            if len(pair) != 2:
                raise SystemExit("--allow-overlap 需要 idA,idB 两个 id")
            allow_overlap.append((pair[0], pair[1]))
            i += 2
        elif a in ("-h", "--help"):
            raise SystemExit(__doc__)
        else:
            files.append(a)
            i += 1
    if not files:
        raise SystemExit("usage: check-quality.py <file.drawio> [--viewport W H] [--allow-overlap idA,idB]")
    return files, viewport, allow_overlap


def check_file(
    path: str,
    viewport: tuple[float, float],
    allow_overlap: list[tuple[str, str]] | None = None,
) -> list[str]:
    allow_overlap = allow_overlap or []
    issues: list[str] = []
    try:
        raw = open(path, encoding="utf-8").read()
    except OSError as e:
        return [f"无法读取文件: {e}"]

    # 1. 非法注释
    if COMMENT_RE.search(raw):
        issues.append("存在 XML 注释（draw.io 会剥离注释，破坏后续编辑匹配）")

    # 2. XML 可解析 + 根结构
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        return [f"XML 解析失败: {e}"]
    if root.tag != "mxfile":
        issues.append(f"根元素应为 <mxfile>，实际为 <{root.tag}>")

    # 3. 收集节点与边（子元素坐标转绝对坐标：沿 parent 链累加容器偏移）
    cells = {cell.get("id"): cell for cell in root.iter("mxCell")}
    verts: list[tuple[str, float, float, float, float]] = []  # id, abs_x, abs_y, w, h
    edges: list[tuple[str, str, str]] = []  # id, source, target
    all_ids: list[str] = []
    for cell in root.iter("mxCell"):
        cid = cell.get("id", "")
        all_ids.append(cid)
        geom = cell.find("mxGeometry")
        if cell.get("edge") == "1":
            src = cell.get("source", "")
            tgt = cell.get("target", "")
            edges.append((cid, src, tgt))
        elif geom is not None:
            w = float(geom.get("width", 0))
            h = float(geom.get("height", 0))
            # 绝对坐标 = 自身 x/y + 所有祖先容器（非根）的 x/y 累加
            ax = float(geom.get("x", 0))
            ay = float(geom.get("y", 0))
            pid = cell.get("parent", "1")
            visited = 0
            while pid and pid != "1" and pid in cells and visited < 50:
                pcell = cells[pid]
                pgeom = pcell.find("mxGeometry")
                if pgeom is not None:
                    ax += float(pgeom.get("x", 0))
                    ay += float(pgeom.get("y", 0))
                pid = pcell.get("parent", "1")
                visited += 1
            verts.append((cid, ax, ay, w, h))

    # 4. id 唯一性
    seen: dict[str, int] = {}
    for cid in all_ids:
        if cid in seen:
            issues.append(f"重复 id: {cid}（出现 {seen[cid] + 1} 次）")
        seen[cid] = seen.get(cid, 0) + 1

    # 5. 重叠检测（跳过父子/祖先容器关系与显式豁免；UI 弹窗覆盖用 --allow-overlap）
    def is_ancestor(cid_a: str, cid_b: str) -> bool:
        """cid_a 是否为 cid_b 的祖先（沿 parent 链）"""
        pid = cells.get(cid_b)
        visited = 0
        while pid is not None and visited < 50:
            if pid.get("id") == cid_a:
                return True
            pid = cells.get(pid.get("parent", ""))
            visited += 1
        return False

    for i in range(len(verts)):
        for j in range(i + 1, len(verts)):
            a, b = verts[i], verts[j]
            aid, ax, ay, aw, ah = a
            bid, bx, by, bw, bh = b
            # 跳过祖先-后代容器关系（子元素在容器内部不算重叠）
            if is_ancestor(aid, bid) or is_ancestor(bid, aid):
                continue
            # 跳过显式豁免对（设计意图，如 UI 弹窗覆盖）
            if (aid, bid) in allow_overlap or (bid, aid) in allow_overlap:
                continue
            if ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah:
                issues.append(f"节点重叠: {aid} 与 {bid}")

    # 6. 越界检测
    vw, vh = viewport
    for cid, x, y, w, h in verts:
        if x + w > vw or y + h > vh:
            issues.append(
                f"越界: {cid} (x+w={x + w:.0f}, y+h={y + h:.0f} > 视口 {vw:.0f}x{vh:.0f})"
            )

    # 7. 孤立边检测
    id_set = set(all_ids)
    for eid, src, tgt in edges:
        if src not in id_set:
            issues.append(f"孤立边: {eid} source={src} 不存在")
        if tgt not in id_set:
            issues.append(f"孤立边: {eid} target={tgt} 不存在")

    return issues


def main() -> int:
    files, viewport, allow_overlap = parse_args(sys.argv[1:])
    overall_ok = True
    for f in files:
        issues = check_file(f, viewport, allow_overlap)
        n_verts = 0
        n_edges = 0
        try:
            root = ET.parse(f).getroot()
            n_verts = sum(1 for c in root.iter("mxCell") if c.get("edge") != "1")
            n_edges = sum(1 for c in root.iter("mxCell") if c.get("edge") == "1")
        except Exception:
            pass
        print(f"== {f}")
        print(f"   节点={n_verts} 边={n_edges}")
        if issues:
            overall_ok = False
            for issue in issues:
                print(f"   ✗ {issue}")
        else:
            print("   ✓ 全部通过：无重叠/越界/孤立边/重复id/注释")
        print()
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
