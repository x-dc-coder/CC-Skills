from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ENTITY_W = 100
ENTITY_H = 40
ATTR_W = 90
ATTR_H = 44


def render_diagram_png(model: dict, auto_crop: bool = True, safe_margin: int = 24, scale: int = 4, downsample_output: bool = False) -> bytes:
    """渲染单表 ER 图为 PNG

    Args:
        downsample_output: 是否下采样到 1x（默认 False，输出高分辨率）；设为 True 可输出标准分辨率。
    """
    tables = model.get("tables", [])

    if not tables:
        image = Image.new("RGB", (900 * scale, 560 * scale), "#FFFFFF")
        draw = ImageDraw.Draw(image)
        draw.text((40 * scale, 40 * scale), "No table found in SQL DDL.", fill="#111827", font=_load_font(12 * scale))
        if downsample_output:
            image = _downsample(image, scale)
        final = _finalize_image(image, bg_color=(255, 255, 255), auto_crop=auto_crop, safe_margin=safe_margin)
        return _to_png_bytes(final)

    # 只处理第一个表（单表模式）
    table = tables[0]
    layout = _layout_single_entity(table)
    canvas_w, canvas_h = layout["canvas_size"]

    image = Image.new("RGB", (canvas_w * scale, canvas_h * scale), "#FFFFFF")
    draw = ImageDraw.Draw(image)

    entity_font = _load_font(12 * scale)
    attr_font = _load_font(12 * scale)

    _draw_entity_cluster(draw, table, layout, entity_font, attr_font, scale)

    if downsample_output:
        image = _downsample(image, scale)
    final = _finalize_image(image, bg_color=(255, 255, 255), auto_crop=auto_crop, safe_margin=safe_margin)
    return _to_png_bytes(final)


def _layout_single_entity(table: dict) -> dict:
    """计算单表布局"""
    cols_count = len(table.get("columns", []))

    # 根据属性数量调整画布大小
    orbit_x = min(240, max(160, 120 + cols_count * 12))
    orbit_y = min(180, max(120, 90 + cols_count * 9))

    # 计算画布尺寸，确保所有属性都能显示
    margin = 60
    canvas_w = max(560, orbit_x * 2 + ATTR_W + margin * 2)
    canvas_h = max(460, orbit_y * 2 + ATTR_H + margin * 2)

    # 实体居中
    cx = canvas_w // 2
    cy = canvas_h // 2

    attrs = _attribute_positions(cx, cy, cols_count, orbit_x, orbit_y)

    return {
        "cx": cx,
        "cy": cy,
        "attrs": attrs,
        "rect": (cx - ENTITY_W // 2, cy - ENTITY_H // 2, cx + ENTITY_W // 2, cy + ENTITY_H // 2),
        "canvas_size": (canvas_w, canvas_h),
    }


def _attribute_positions(cx: int, cy: int, count: int, radius_x: int, radius_y: int) -> list[tuple[int, int]]:
    """计算属性椭圆的位置（围绕实体均匀分布）"""
    if count <= 0:
        return []

    import math
    points: list[tuple[int, int]] = []
    for i in range(count):
        # 从顶部开始，顺时针分布
        a = -math.pi / 2 + 2 * math.pi * i / count
        ax = int(cx + radius_x * math.cos(a))
        ay = int(cy + radius_y * math.sin(a))
        points.append((ax, ay))
    return points


def _draw_entity_cluster(
    draw: ImageDraw.ImageDraw,
    table: dict,
    layout: dict,
    entity_font: ImageFont.ImageFont,
    attr_font: ImageFont.ImageFont,
    scale: int,
) -> None:
    """绘制实体和其属性"""
    cx, cy = layout["cx"], layout["cy"]

    # 获取实体名和适合的字体
    entity_name = str(table.get("name") or table.get("id") or "Entity")
    fitted_font, text_width, text_height = _get_fitted_font(draw, entity_name, entity_font, ENTITY_W * scale - 40)

    # 实体宽度、高度均贴合文字 + 紧凑边距
    half_h = max(16, int((text_height / scale) / 2) + 6)
    half_w = max(40, int((text_width / scale) / 2) + 10)

    left = cx - half_w
    top = cy - half_h
    right = cx + half_w
    bottom = cy + half_h

    # 绘制实体矩形（宽高自适应）
    _draw_rect(draw, left, top, right, bottom, scale, fill="#FFFFFF", outline="#111111", width=2)

    # 绘制实体名
    draw.text((cx * scale, cy * scale), entity_name, fill="#111111", font=fitted_font, anchor="mm")

    # 绘制属性 —— 先计算所有属性标签，统一调整椭圆大小
    columns = table.get("columns", [])
    attr_labels = [str(col.get("comment") or col.get("name") or "attr") for col in columns]

    # 计算属性文字所需的最大宽度和高度
    max_attr_text_w = 0
    max_attr_text_h = 0
    for label in attr_labels:
        box = draw.textbbox((0, 0), label, font=attr_font)
        w = box[2] - box[0]
        h = box[3] - box[1]
        if w > max_attr_text_w:
            max_attr_text_w = w
        if h > max_attr_text_h:
            max_attr_text_h = h

    # 根据最长文字统一调整椭圆半宽、半高
    attr_half_w = max(ATTR_W // 2, int((max_attr_text_w / scale) / 2) + 10)
    attr_half_h = max(ATTR_H // 2, int((max_attr_text_h / scale) / 2) + 8)

    for idx, col in enumerate(columns):
        ax, ay = layout["attrs"][idx]
        label = attr_labels[idx]

        # 连接线：实体矩形边界 -> 椭圆边界（使用实际宽高）
        sx, sy = _rect_edge_point(cx, cy, half_w * 2, half_h * 2, ax, ay)
        ex, ey = _ellipse_edge_point(ax, ay, attr_half_w, attr_half_h, cx, cy)
        _draw_line(draw, sx, sy, ex, ey, scale, fill="#111111", width=1)

        # 绘制属性椭圆（统一自适应大小）
        _draw_ellipse(
            draw,
            ax - attr_half_w,
            ay - attr_half_h,
            ax + attr_half_w,
            ay + attr_half_h,
            scale,
            fill="#FFFFFF",
            outline="#111111",
            width=1,
        )

        # 属性标签自动适配椭圆宽度
        fitted_attr_font, _, _ = _get_fitted_font(
            draw, label, attr_font, attr_half_w * 2 * scale - 16
        )
        draw.text((ax * scale, ay * scale), label, fill="#111111", font=fitted_attr_font, anchor="mm")

        # 主键加下划线
        if col.get("isPrimaryKey"):
            box = draw.textbbox((ax * scale, ay * scale), label, font=fitted_attr_font, anchor="mm")
            underline_y = box[3] + 2 * scale
            draw.line((box[0], underline_y, box[2], underline_y), fill="#111111", width=max(1, scale))


def _draw_rect(
    draw: ImageDraw.ImageDraw,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    scale: int,
    fill: str,
    outline: str,
    width: int,
) -> None:
    draw.rectangle((x1 * scale, y1 * scale, x2 * scale, y2 * scale), fill=fill, outline=outline, width=max(1, width * scale))


def _draw_ellipse(
    draw: ImageDraw.ImageDraw,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    scale: int,
    fill: str,
    outline: str,
    width: int,
) -> None:
    draw.ellipse((x1 * scale, y1 * scale, x2 * scale, y2 * scale), fill=fill, outline=outline, width=max(1, width * scale))


def _draw_line(draw: ImageDraw.ImageDraw, x1: float, y1: float, x2: float, y2: float, scale: int, fill: str, width: int) -> None:
    draw.line((int(x1 * scale), int(y1 * scale), int(x2 * scale), int(y2 * scale)), fill=fill, width=max(1, width * scale))


def _load_font(size: int) -> ImageFont.ImageFont:
    # 1. 首先检查环境变量指定的字体
    custom_path = os.getenv("DIAGRAM_FONT_PATH")
    if custom_path and Path(custom_path).exists():
        try:
            return ImageFont.truetype(str(custom_path), size=size)
        except OSError:
            pass

    # 2. 从 scripts/fonts/ 目录加载内置字体（优先）
    fonts_dir = Path(__file__).parent / "fonts"
    if fonts_dir.exists():
        # 优先尝试常见的中文字体文件名
        builtin_fonts = [
            "*.ttc",  # TTC 字体集合（如 NotoSansCJK）
            "*.ttf",  # TrueType 字体
            "*.otf",  # OpenType 字体
        ]
        for pattern in builtin_fonts:
            for font_file in fonts_dir.glob(pattern):
                try:
                    return ImageFont.truetype(str(font_file), size=size)
                except OSError:
                    continue

    # 3. 系统字体路径（宋体优先，统一论文字体规范）
    system_candidates = [
        "/mnt/c/Windows/Fonts/simsun.ttc",  # WSL 宋体（优先）
        "C:/Windows/Fonts/simsun.ttc",   # Windows 宋体
        "C:/Windows/Fonts/simsun.ttf",   # Windows 宋体（备选）
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",  # Linux 思源宋体
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/msyh.ttc",     # 微软雅黑
        "C:/Windows/Fonts/simhei.ttf",   # 黑体
    ]
    for p in system_candidates:
        if not p:
            continue
        path = Path(p)
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue

    # 4. 最后使用默认字体（不支持中文）
    return ImageFont.load_default()


def _rect_edge_point(cx: float, cy: float, w: float, h: float, tx: float, ty: float) -> tuple[float, float]:
    """计算矩形边缘点（从中心指向目标方向的交点）"""
    dx = tx - cx
    dy = ty - cy
    if dx == 0 and dy == 0:
        return cx, cy
    half_w = w / 2.0
    half_h = h / 2.0
    ratio = 1.0 / max(abs(dx) / half_w if half_w else 1.0, abs(dy) / half_h if half_h else 1.0)
    return cx + dx * ratio, cy + dy * ratio


def _ellipse_edge_point(cx: float, cy: float, rx: float, ry: float, tx: float, ty: float) -> tuple[float, float]:
    """计算椭圆边缘点（从中心指向目标方向的交点）"""
    import math
    dx = tx - cx
    dy = ty - cy
    if dx == 0 and dy == 0:
        return cx, cy
    denom = math.sqrt((dx * dx) / (rx * rx) + (dy * dy) / (ry * ry))
    if denom == 0:
        return cx, cy
    return cx + dx / denom, cy + dy / denom


def _to_png_bytes(image: Image.Image) -> bytes:
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _downsample(image: Image.Image, scale: int) -> Image.Image:
    if scale <= 1:
        return image
    w, h = image.size
    return image.resize((w // scale, h // scale), Image.Resampling.LANCZOS)


def _get_fitted_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> tuple[ImageFont.ImageFont, int, int]:
    """获取适合宽度的字体，返回(字体, 宽度, 高度)"""
    # 获取文本边界框
    box = draw.textbbox((0, 0), text, font=font)
    text_width = box[2] - box[0]
    text_height = box[3] - box[1]

    if text_width <= max_width:
        # 文本适合，直接返回
        return font, text_width, text_height

    # 文本太长，需要缩小字体
    original_size = font.size
    min_size = max(12, original_size // 3)  # 最小字号限制

    # 尝试缩小字体直到适合
    for new_size in range(original_size - 2, min_size - 1, -2):
        try:
            new_font = _load_font(new_size)
            box = draw.textbbox((0, 0), text, font=new_font)
            new_width = box[2] - box[0]
            new_height = box[3] - box[1]
            if new_width <= max_width:
                return new_font, new_width, new_height
        except Exception:
            continue

    # 如果还是太长，使用最小字体并截断
    min_font = _load_font(min_size)
    # 尝试添加省略号
    ellipsis = "..."
    for i in range(len(text), 0, -1):
        truncated = text[:i] + ellipsis
        box = draw.textbbox((0, 0), truncated, font=min_font)
        trunc_width = box[2] - box[0]
        trunc_height = box[3] - box[1]
        if trunc_width <= max_width:
            # 返回截断后的文本信息（但用原字体绘制时会显示截断版）
            return min_font, trunc_width, trunc_height

    # 最后的备选
    box = draw.textbbox((0, 0), text[:10] + "...", font=min_font)
    return min_font, box[2] - box[0], box[3] - box[1]


def _finalize_image(
    image: Image.Image,
    bg_color: tuple[int, int, int] = (255, 255, 255),
    auto_crop: bool = True,
    safe_margin: int = 24,
) -> Image.Image:
    """最终图像处理：自动裁剪边距并添加安全边距"""
    out = image
    if auto_crop:
        out = _auto_crop(out, bg_color=bg_color)
    if safe_margin > 0:
        out = _pad(out, safe_margin, bg_color)
    return out


def _auto_crop(image: Image.Image, bg_color: tuple[int, int, int], threshold: int = 8) -> Image.Image:
    """自动裁剪空白边距"""
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
                if x < min_x:
                    min_x = x
                if y < min_y:
                    min_y = y
                if x > max_x:
                    max_x = x
                if y > max_y:
                    max_y = y

    if max_x < min_x or max_y < min_y:
        return image

    return rgb.crop((min_x, min_y, max_x + 1, max_y + 1))


def _pad(image: Image.Image, margin: int, bg_color: tuple[int, int, int]) -> Image.Image:
    """添加边距"""
    w, h = image.size
    out = Image.new("RGB", (w + margin * 2, h + margin * 2), bg_color)
    out.paste(image, (margin, margin))
    return out
