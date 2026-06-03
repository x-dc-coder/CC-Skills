"""ER 图渲染模块 — 多实体关系图（不含属性）

绘制 Chen 风格 ER 图：
- 实体（Entity）：矩形
- 关系（Relation）：菱形
- 连线：实体与关系之间的直线，标注基数（1, n, m）
"""

from __future__ import annotations

import math
import os
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# 常量配置
SCALE = 4  # 高分辨率渲染后下采样
ENTITY_W = 100  # 实体矩形宽度（缩小）
ENTITY_H = 50   # 实体矩形高度（缩小）
RELATION_DW = 40  # 菱形半宽（缩小）
RELATION_DH = 28  # 菱形半高（缩小）
PADDING = 80    # 画布边距
FONT_SIZE = 12
LABEL_FONT_SIZE = 10


def render_er_diagram(data: dict, auto_crop: bool = True, safe_margin: int = 24, scale: int = None, downsample_output: bool = True) -> bytes:
    """渲染 ER 图为 PNG

    Args:
        downsample_output: 是否下采样到 1x（默认 True）；设为 False 可输出更高像素。
    """
    entities = data.get("entities", [])
    relations = data.get("relations", [])
    title = data.get("title", "")

    # 计算画布尺寸
    canvas_w, canvas_h = _compute_canvas_size(entities, relations)
    if scale is None:
        scale = SCALE

    image = Image.new("RGB", (canvas_w * scale, canvas_h * scale), "#FFFFFF")
    draw = ImageDraw.Draw(image)

    name_font = _load_font(FONT_SIZE * scale)
    label_font = _load_font(LABEL_FONT_SIZE * scale)

    # 先画连线（在实体和关系下方）
    for rel in relations:
        _draw_relation_lines(draw, rel, entities, label_font, scale)

    # 再画实体（矩形）
    for ent in entities:
        _draw_entity(draw, ent, name_font, scale)

    # 再画关系（菱形）
    for rel in relations:
        _draw_relation(draw, rel, name_font, scale)

    if downsample_output:
        image = _downsample(image, scale)
    final = _finalize_image(image, bg_color=(255, 255, 255), auto_crop=auto_crop, safe_margin=safe_margin)
    return _to_png_bytes(final)


def _compute_canvas_size(entities: list, relations: list) -> tuple[int, int]:
    """根据所有节点坐标计算画布尺寸"""
    all_x, all_y = [], []

    for ent in entities:
        all_x.append(ent.get("x", 0))
        all_y.append(ent.get("y", 0))

    for rel in relations:
        all_x.append(rel.get("x", 0))
        all_y.append(rel.get("y", 0))

    if not all_x:
        return 800, 600

    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)

    # 考虑实体/菱形的半宽半高
    canvas_w = max_x - min_x + ENTITY_W + RELATION_DW * 2 + PADDING * 2
    canvas_h = max_y - min_y + ENTITY_H + RELATION_DH * 2 + PADDING * 2

    # 确保最小尺寸
    canvas_w = max(canvas_w, 600)
    canvas_h = max(canvas_h, 400)

    return canvas_w, canvas_h


def _draw_entity(draw: ImageDraw.ImageDraw, ent: dict, font: ImageFont.ImageFont, scale: int) -> None:
    """绘制实体矩形"""
    x = ent.get("x", 0)
    y = ent.get("y", 0)
    name = str(ent.get("name", "Entity"))

    half_w = ENTITY_W // 2
    half_h = ENTITY_H // 2

    left = (x - half_w) * scale
    top = (y - half_h) * scale
    right = (x + half_w) * scale
    bottom = (y + half_h) * scale

    # 绘制矩形
    draw.rectangle((left, top, right, bottom), fill="#FFFFFF", outline="#111111", width=max(1, 2 * scale))

    # 绘制文字（居中）
    draw.text((x * scale, y * scale), name, fill="#111111", font=font, anchor="mm")


def _draw_relation(draw: ImageDraw.ImageDraw, rel: dict, font: ImageFont.ImageFont, scale: int) -> None:
    """绘制关系菱形"""
    x = rel.get("x", 0)
    y = rel.get("y", 0)
    name = str(rel.get("name", "Relation"))

    dw = RELATION_DW
    dh = RELATION_DH

    # 菱形四个顶点：右、上、左、下
    points = [
        ((x + dw) * scale, (y) * scale),
        ((x) * scale, (y - dh) * scale),
        ((x - dw) * scale, (y) * scale),
        ((x) * scale, (y + dh) * scale),
    ]

    draw.polygon(points, fill="#FFFFFF", outline="#111111")
    draw.line(points + [points[0]], fill="#111111", width=max(1, 2 * scale))

    # 文字居中
    draw.text((x * scale, y * scale), name, fill="#111111", font=font, anchor="mm")


def _draw_relation_lines(
    draw: ImageDraw.ImageDraw,
    rel: dict,
    entities: list,
    label_font: ImageFont.ImageFont,
    scale: int,
) -> None:
    """绘制关系与实体之间的连线，并标注基数"""
    rel_x = rel.get("x", 0)
    rel_y = rel.get("y", 0)
    connects = rel.get("connects", [])

    # 建立实体名到坐标的映射
    entity_map = {e.get("name"): e for e in entities}

    for conn in connects:
        ent_name = conn.get("entity")
        cardinality = conn.get("cardinality", "")
        ent = entity_map.get(ent_name)
        if not ent:
            continue

        ent_x = ent.get("x", 0)
        ent_y = ent.get("y", 0)

        # 计算实体矩形边缘点
        ex, ey = _rect_edge_point(ent_x, ent_y, ENTITY_W, ENTITY_H, rel_x, rel_y)
        # 计算菱形边缘点
        rx, ry = _diamond_edge_point(rel_x, rel_y, RELATION_DW, RELATION_DH, ent_x, ent_y)

        # 绘制连线
        draw.line(
            (int(ex * scale), int(ey * scale), int(rx * scale), int(ry * scale)),
            fill="#111111",
            width=max(1, 1 * scale),
        )

        # 绘制基数标签（放在连线的 30% 处，靠近实体）
        if cardinality:
            label_x = ex + (rx - ex) * 0.3
            label_y = ey + (ry - ey) * 0.3

            # 计算文字背景框大小
            bbox = draw.textbbox((0, 0), cardinality, font=label_font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]

            # 文字背景（白色，覆盖线条）
            margin = 4 * scale
            bg_left = int(label_x * scale - tw / 2 - margin)
            bg_top = int(label_y * scale - th / 2 - margin)
            bg_right = int(label_x * scale + tw / 2 + margin)
            bg_bottom = int(label_y * scale + th / 2 + margin)
            draw.rectangle((bg_left, bg_top, bg_right, bg_bottom), fill="#FFFFFF", outline="#FFFFFF")

            # 绘制文字
            draw.text((int(label_x * scale), int(label_y * scale)), cardinality, fill="#111111", font=label_font, anchor="mm")


def _rect_edge_point(cx: float, cy: float, w: float, h: float, tx: float, ty: float) -> tuple[float, float]:
    """计算矩形边缘点（从中心指向目标方向的交点）"""
    dx = tx - cx
    dy = ty - cy
    if dx == 0 and dy == 0:
        return cx, cy
    half_w = w / 2.0
    half_h = h / 2.0
    ratio = 1.0 / max(abs(dx) / half_w if dx != 0 else 0, abs(dy) / half_h if dy != 0 else 0)
    return cx + dx * ratio, cy + dy * ratio


def _diamond_edge_point(cx: float, cy: float, dw: float, dh: float, tx: float, ty: float) -> tuple[float, float]:
    """计算菱形边缘点（菱形边界方程 |x|/dw + |y|/dh = 1）"""
    dx = tx - cx
    dy = ty - cy
    if dx == 0 and dy == 0:
        return cx, cy
    denom = abs(dx) / dw + abs(dy) / dh
    if denom == 0:
        return cx, cy
    ratio = 1.0 / denom
    return cx + dx * ratio, cy + dy * ratio


def _load_font(size: int) -> ImageFont.ImageFont:
    """加载字体（优先中文字体）"""
    custom_path = os.getenv("DIAGRAM_FONT_PATH")
    if custom_path and Path(custom_path).exists():
        try:
            return ImageFont.truetype(str(custom_path), size=size)
        except OSError:
            pass

    # 从其他 skill 的 fonts 目录加载
    fonts_dirs = [
        Path(__file__).parent / "fonts",
        Path(__file__).parent.parent / "diagram-er" / "scripts" / "fonts",
        Path(__file__).parent.parent / "diagram-usecase" / "scripts" / "fonts",
    ]
    for fonts_dir in fonts_dirs:
        if fonts_dir.exists():
            for pattern in ["*.ttc", "*.ttf", "*.otf"]:
                for font_file in fonts_dir.glob(pattern):
                    try:
                        return ImageFont.truetype(str(font_file), size=size)
                    except OSError:
                        continue

    # 系统字体（宋体优先，统一论文字体规范）
    system_candidates = [
        "/mnt/c/Windows/Fonts/simsun.ttc",  # WSL 宋体（优先）
        "C:/Windows/Fonts/simsun.ttc",   # Windows 宋体
        "C:/Windows/Fonts/simsun.ttf",   # Windows 宋体（备选）
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",  # Linux 思源宋体
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
    ]
    for p in system_candidates:
        if p and Path(p).exists():
            try:
                return ImageFont.truetype(str(p), size=size)
            except OSError:
                continue

    return ImageFont.load_default()


def _downsample(image: Image.Image, scale: int) -> Image.Image:
    if scale <= 1:
        return image
    w, h = image.size
    return image.resize((w // scale, h // scale), Image.Resampling.LANCZOS)


def _finalize_image(image: Image.Image, bg_color: tuple[int, int, int], auto_crop: bool, safe_margin: int) -> Image.Image:
    out = image
    if auto_crop:
        out = _auto_crop(out, bg_color)
    if safe_margin > 0:
        out = _pad(out, safe_margin, bg_color)
    return out


def _auto_crop(image: Image.Image, bg_color: tuple[int, int, int], threshold: int = 8) -> Image.Image:
    rgb = image.convert("RGB")
    w, h = rgb.size
    px = rgb.load()
    min_x, min_y = w, h
    max_x, max_y = -1, -1
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            diff = abs(r - bg_color[0]) + abs(g - bg_color[1]) + abs(b - bg_color[2])
            if diff > threshold:
                if x < min_x: min_x = x
                if y < min_y: min_y = y
                if x > max_x: max_x = x
                if y > max_y: max_y = y
    if max_x < min_x or max_y < min_y:
        return image
    return rgb.crop((min_x, min_y, max_x + 1, max_y + 1))


def _pad(image: Image.Image, margin: int, bg_color: tuple[int, int, int]) -> Image.Image:
    w, h = image.size
    out = Image.new("RGB", (w + margin * 2, h + margin * 2), bg_color)
    out.paste(image, (margin, margin))
    return out


def _to_png_bytes(image: Image.Image) -> bytes:
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()
