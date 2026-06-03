"""用例图渲染模块

用于绘制UML用例图：
- 参与者（Actor）：火柴人图标
- 用例（Use Case）：水平椭圆
- 系统边界（可选）
- 关联、包含、扩展关系

采用学术论文风格，适用于本科毕业论文。
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# 常量配置 - 学术论文风格（较高清）
SCALE = 8  # 高分辨率渲染，然后下采样以获得更清晰的图像

# Actor 尺寸（适配 12pt 字号）
ACTOR_HEAD_RADIUS = 14  # 头部半径
ACTOR_BODY_HEIGHT = 30  # 身体高度
ACTOR_ARM_WIDTH = 20  # 手臂宽度
ACTOR_LEG_HEIGHT = 24  # 腿部高度
ACTOR_WIDTH = 40  # 整体宽度（用于布局）
ACTOR_HEIGHT = ACTOR_HEAD_RADIUS * 2 + ACTOR_BODY_HEIGHT + ACTOR_LEG_HEIGHT  # 整体高度
ACTOR_LABEL_MARGIN = 10  # 标签与图标的间距

# 用例椭圆尺寸（适配 12pt 字号）
USECASE_MIN_WIDTH = 100  # 最小宽度
USECASE_HEIGHT = 45  # 椭圆高度
USECASE_TEXT_PADDING = 14  # 文字边距（紧凑）

# 布局间距（紧凑，减少留白）
ACTOR_TO_USECASE = 80   # 参与者到用例的水平距离
USECASE_V_SPACING = 12  # 用例之间的垂直间距
CANVAS_PADDING = 20     # 画布边距

# 字体（统一论文标准字号 12pt）
FONT_SIZE = 12
ACTOR_FONT_SIZE = 12


@dataclass
class Actor:
    """参与者"""
    name: str
    x: int = 0
    y: int = 0


@dataclass
class UseCase:
    """用例"""
    name: str
    x: int = 0
    y: int = 0
    width: int = USECASE_MIN_WIDTH
    height: int = USECASE_HEIGHT


@dataclass
class Relation:
    """关系（参与者与用例之间的关联）"""
    from_actor: str
    to_usecase: str


@dataclass
class UseCaseModel:
    """用例图模型"""
    actors: list[Actor] = field(default_factory=list)
    usecases: list[UseCase] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)


def load_font(size: int) -> ImageFont.ImageFont:
    """加载字体，按优先级尝试多个来源"""
    # 1. 环境变量指定的字体
    custom_path = os.getenv("DIAGRAM_FONT_PATH")
    if custom_path and Path(custom_path).exists():
        try:
            return ImageFont.truetype(str(custom_path), size=size)
        except OSError:
            pass

    # 2. 脚本所在目录的 fonts 文件夹
    script_dir = Path(__file__).parent
    fonts_dir = script_dir / "fonts"
    if fonts_dir.exists():
        for pattern in ["*.ttc", "*.ttf", "*.otf"]:
            for font_file in fonts_dir.glob(pattern):
                try:
                    return ImageFont.truetype(str(font_file), size=size)
                except OSError:
                    continue

    # 3. 系统字体路径（宋体优先，统一论文字体规范）
    system_candidates = [
        "/mnt/c/Windows/Fonts/simsun.ttc",  # WSL 宋体（优先）
        "C:/Windows/Fonts/simsun.ttc",   # Windows 宋体
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",  # Linux 思源宋体
        "C:/Windows/Fonts/simsun.ttf",   # Windows 宋体（备选）
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
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

    # 4. 使用默认字体（不支持中文）
    return ImageFont.load_default()


def downsample(image: Image.Image, scale: int) -> Image.Image:
    """下采样图片"""
    if scale <= 1:
        return image
    w, h = image.size
    return image.resize((w // scale, h // scale), Image.Resampling.LANCZOS)


def finalize_image(
    image: Image.Image,
    bg_color: tuple[int, int, int] = (255, 255, 255),
    auto_crop: bool = True,
    safe_margin: int = 24,
) -> Image.Image:
    """图片后处理：添加边距、裁剪等"""
    if not auto_crop:
        return image

    # 转换为 RGBA 以支持透明处理
    if image.mode != "RGBA":
        image = image.convert("RGBA")

    # 获取非空白区域
    bbox = image.getbbox()
    if bbox is None:
        return image.convert("RGB")

    # 添加安全边距
    left = max(0, bbox[0] - safe_margin)
    top = max(0, bbox[1] - safe_margin)
    right = min(image.width, bbox[2] + safe_margin)
    bottom = min(image.height, bbox[3] + safe_margin)

    # 裁剪
    cropped = image.crop((left, top, right, bottom))

    # 转回 RGB
    return cropped.convert("RGB")


def to_png_bytes(image: Image.Image, dpi: tuple[int, int] = (150, 150)) -> bytes:
    """将图片转换为PNG字节

    Args:
        image: PIL Image 对象
        dpi: DPI 元数据，用于控制 Word 等软件中的渲染清晰度
    """
    from io import BytesIO
    out = BytesIO()
    image.save(out, format="PNG", dpi=dpi)
    return out.getvalue()


def ellipse_edge_point(
    cx: float, cy: float, rx: float, ry: float, tx: float, ty: float
) -> tuple[float, float]:
    """计算椭圆边缘点（从中心指向目标方向的交点）"""
    dx = tx - cx
    dy = ty - cy
    if dx == 0 and dy == 0:
        return cx, cy
    denom = math.sqrt((dx * dx) / (rx * rx) + (dy * dy) / (ry * ry))
    if denom == 0:
        return cx, cy
    return cx + dx / denom, cy + dy / denom


def render_usecase_diagram(
    model: dict,
    auto_crop: bool = True,
    safe_margin: int = 24,
    scale: int = None,
    downsample_output: bool = False,
    dpi: tuple[int, int] = (150, 150),
) -> bytes:
    """渲染用例图

    Args:
        model: 用例图模型，推荐使用单参与者简洁格式
        auto_crop: 是否自动裁剪空白边距
        safe_margin: 安全边距（像素）
        scale: 渲染缩放比例（默认使用全局 SCALE）
        downsample_output: 是否下采样到 1x（默认 False，输出高分辨率）
        dpi: PNG DPI 元数据（用于控制 Word 等软件中的渲染清晰度，默认 150）

    Returns:
        PNG图片字节数据

    JSON格式示例（简洁格式，单参与者）：
        {
            "actor": "用户",
            "usecases": ["登录系统", "重置密码", "商品下单", "退出系统"]
        }
    """
    if scale is None:
        scale = SCALE

    # 解析模型
    diagram_model = _parse_model(model)

    if not diagram_model.actors and not diagram_model.usecases:
        return _render_empty(auto_crop, safe_margin, scale, downsample_output, dpi)

    # 计算布局
    _calculate_layout(diagram_model)

    # 获取画布尺寸
    canvas_w, canvas_h = _get_canvas_size(diagram_model)

    # 创建画布
    image = Image.new("RGB", (canvas_w * scale, canvas_h * scale), "#FFFFFF")
    draw = ImageDraw.Draw(image)

    # 绘制
    font = load_font(FONT_SIZE * scale)
    actor_font = load_font(ACTOR_FONT_SIZE * scale)

    # 先绘制关系（在底层）
    for relation in diagram_model.relations:
        _draw_relation(draw, relation, diagram_model, scale)

    # 再绘制参与者和用例
    for actor in diagram_model.actors:
        _draw_actor(draw, actor, actor_font, scale)

    for usecase in diagram_model.usecases:
        _draw_usecase(draw, usecase, font, scale)

    # 后处理
    if downsample_output:
        image = downsample(image, scale)
    final = finalize_image(
        image,
        bg_color=(255, 255, 255),
        auto_crop=auto_crop,
        safe_margin=safe_margin,
    )
    return to_png_bytes(final, dpi=dpi)


def _parse_model(data: dict) -> UseCaseModel:
    """从字典解析用例图模型

    支持两种格式：
    1. 简洁格式（推荐，单参与者）：
       {"actor": "用户", "usecases": ["登录", "注册"]}

    2. 完整格式（多参与者）：
       {"actors": [...], "usecases": [...], "relations": [...]}
    """
    usecase_list = data.get("usecases", [])
    if len(usecase_list) < 3 or len(usecase_list) > 6:
        raise ValueError(
            f"用例数量限制为 3-6 个，当前提供了 {len(usecase_list)} 个。"
            "请调整 usecases 列表，确保数量不低于 3 个且不超过 6 个。"
        )

    model = UseCaseModel()

    # 优先使用简洁格式（单参与者）
    if "actor" in data:
        actor_name = data["actor"] if isinstance(data["actor"], str) else data["actor"].get("name", "用户")
        model.actors.append(Actor(name=actor_name))

        # 解析用例
        for usecase_data in data.get("usecases", []):
            if isinstance(usecase_data, str):
                model.usecases.append(UseCase(name=usecase_data))
            elif isinstance(usecase_data, dict):
                model.usecases.append(UseCase(
                    name=usecase_data.get("name", "未知"),
                    x=usecase_data.get("x", 0),
                    y=usecase_data.get("y", 0),
                    width=usecase_data.get("width", USECASE_MIN_WIDTH),
                    height=usecase_data.get("height", USECASE_HEIGHT),
                ))

        # 自动建立关系（单参与者与所有用例关联）
        for usecase in model.usecases:
            model.relations.append(Relation(from_actor=actor_name, to_usecase=usecase.name))

        return model

    # 完整格式（多参与者，向后兼容）
    for actor_data in data.get("actors", []):
        if isinstance(actor_data, str):
            model.actors.append(Actor(name=actor_data))
        elif isinstance(actor_data, dict):
            model.actors.append(Actor(
                name=actor_data.get("name", "未知"),
                x=actor_data.get("x", 0),
                y=actor_data.get("y", 0),
            ))

    for usecase_data in data.get("usecases", []):
        if isinstance(usecase_data, str):
            model.usecases.append(UseCase(name=usecase_data))
        elif isinstance(usecase_data, dict):
            model.usecases.append(UseCase(
                name=usecase_data.get("name", "未知"),
                x=usecase_data.get("x", 0),
                y=usecase_data.get("y", 0),
                width=usecase_data.get("width", USECASE_MIN_WIDTH),
                height=usecase_data.get("height", USECASE_HEIGHT),
            ))

    for relation_data in data.get("relations", []):
        if isinstance(relation_data, (list, tuple)) and len(relation_data) >= 2:
            model.relations.append(Relation(
                from_actor=relation_data[0],
                to_usecase=relation_data[1],
            ))
        elif isinstance(relation_data, dict):
            model.relations.append(Relation(
                from_actor=relation_data.get("from", relation_data.get("actor", "")),
                to_usecase=relation_data.get("to", relation_data.get("usecase", "")),
            ))

    return model


def _calculate_layout(model: UseCaseModel) -> None:
    """计算自动布局

    布局策略：
    - 参与者在左侧垂直排列
    - 用例在右侧垂直排列
    - 关系线自动连接
    """
    if not model.usecases:
        return

    # 计算用例的实际宽度（基于文字长度）
    # 这里使用简单的估算，实际绘制时会根据字体调整
    for usecase in model.usecases:
        # 中文每个字约14px宽，英文每个字符约7px宽
        text_width = _estimate_text_width(usecase.name)
        usecase.width = max(USECASE_MIN_WIDTH, text_width + USECASE_TEXT_PADDING * 2)

    # 计算用例总高度
    total_usecase_height = len(model.usecases) * USECASE_HEIGHT + (len(model.usecases) - 1) * USECASE_V_SPACING

    # 计算参与者总高度
    actor_total_height = len(model.actors) * ACTOR_HEIGHT + (len(model.actors) - 1) * 40

    # 画布整体高度取较大值
    total_height = max(total_usecase_height, actor_total_height)

    # 布局用例（垂直居中排列）
    start_y = (total_height - total_usecase_height) // 2 + CANVAS_PADDING
    current_y = start_y

    # 用例X位置（右侧）
    usecase_x = CANVAS_PADDING + ACTOR_WIDTH + ACTOR_TO_USECASE

    for usecase in model.usecases:
        usecase.x = usecase_x + usecase.width // 2  # x为中心点
        usecase.y = current_y
        current_y += USECASE_HEIGHT + USECASE_V_SPACING

    # 布局参与者（垂直分布）
    if model.actors:
        actor_start_y = (total_height - actor_total_height) // 2 + CANVAS_PADDING
        actor_x = CANVAS_PADDING + ACTOR_WIDTH // 2

        for i, actor in enumerate(model.actors):
            # 根据参与者名称宽度调整 x，确保文字不超出左边界
            label_width = _estimate_text_width(actor.name)
            min_actor_x = label_width // 2 + CANVAS_PADDING
            actor.x = max(actor_x, min_actor_x)
            actor.y = actor_start_y + i * (ACTOR_HEIGHT + 40)


def _estimate_text_width(text: str) -> int:
    """估算文字宽度（按 12pt 字号）"""
    width = 0
    for char in text:
        if '\u4e00' <= char <= '\u9fff':  # 中文字符
            width += 14
        else:
            width += 7  # 英文字符
    return width


def _get_canvas_size(model: UseCaseModel) -> tuple[int, int]:
    """获取画布尺寸"""
    if not model.usecases:
        return 400, 300

    # 计算边界
    max_x = 0
    max_y = 0

    # 参与者边界
    for actor in model.actors:
        max_x = max(max_x, actor.x + ACTOR_WIDTH)
        max_y = max(max_y, actor.y + ACTOR_HEIGHT + ACTOR_LABEL_MARGIN + 20)

    # 用例边界
    for usecase in model.usecases:
        max_x = max(max_x, usecase.x + usecase.width // 2)
        max_y = max(max_y, usecase.y + usecase.height)

    # 添加边距
    width = max_x + CANVAS_PADDING
    height = max_y + CANVAS_PADDING

    return width, height


def _draw_actor(draw: ImageDraw.ImageDraw, actor: Actor, font: ImageFont.ImageFont, scale: int) -> None:
    """绘制参与者（火柴人）"""
    cx = actor.x
    cy = actor.y + ACTOR_HEAD_RADIUS  # 从头部开始

    # 绘制头部（圆形）
    head_radius = ACTOR_HEAD_RADIUS
    draw.ellipse(
        (
            (cx - head_radius) * scale,
            (cy - head_radius) * scale,
            (cx + head_radius) * scale,
            (cy + head_radius) * scale,
        ),
        fill="#FFFFFF",
        outline="#000000",
        width=2 * scale,
    )

    # 绘制身体（竖线）
    body_top = cy + head_radius
    body_bottom = body_top + ACTOR_BODY_HEIGHT
    draw.line(
        (
            (cx * scale, body_top * scale),
            (cx * scale, body_bottom * scale),
        ),
        fill="#000000",
        width=2 * scale,
    )

    # 绘制手臂（横线）
    arm_y = body_top + ACTOR_BODY_HEIGHT // 3
    draw.line(
        (
            ((cx - ACTOR_ARM_WIDTH // 2) * scale, arm_y * scale),
            ((cx + ACTOR_ARM_WIDTH // 2) * scale, arm_y * scale),
        ),
        fill="#000000",
        width=2 * scale,
    )

    # 垂直线连接到手臂
    draw.line(
        (
            (cx * scale, body_top * scale),
            (cx * scale, arm_y * scale),
        ),
        fill="#000000",
        width=2 * scale,
    )

    # 绘制腿部（分叉线）
    leg_bottom = body_bottom + ACTOR_LEG_HEIGHT
    # 左腿
    draw.line(
        (
            (cx * scale, body_bottom * scale),
            ((cx - ACTOR_ARM_WIDTH // 2) * scale, leg_bottom * scale),
        ),
        fill="#000000",
        width=2 * scale,
    )
    # 右腿
    draw.line(
        (
            (cx * scale, body_bottom * scale),
            ((cx + ACTOR_ARM_WIDTH // 2) * scale, leg_bottom * scale),
        ),
        fill="#000000",
        width=2 * scale,
    )

    # 绘制名称（Actor下方）
    label_y = leg_bottom + ACTOR_LABEL_MARGIN
    draw.text(
        (cx * scale, label_y * scale),
        actor.name,
        fill="#000000",
        font=font,
        anchor="mt",  # middle-top
    )


def _draw_usecase(draw: ImageDraw.ImageDraw, usecase: UseCase, font: ImageFont.ImageFont, scale: int) -> None:
    """绘制用例（椭圆）"""
    # 计算椭圆边界（usecase.x, usecase.y 是中心点）
    rx = usecase.width // 2
    ry = usecase.height // 2
    left = usecase.x - rx
    top = usecase.y
    right = usecase.x + rx
    bottom = usecase.y + usecase.height

    # 绘制椭圆
    draw.ellipse(
        (
            left * scale,
            top * scale,
            right * scale,
            bottom * scale,
        ),
        fill="#FFFFFF",
        outline="#000000",
        width=2 * scale,
    )

    # 绘制文字（居中）
    draw.text(
        (usecase.x * scale, (usecase.y + usecase.height // 2) * scale),
        usecase.name,
        fill="#000000",
        font=font,
        anchor="mm",  # middle-middle
    )


def _draw_relation(
    draw: ImageDraw.ImageDraw,
    relation: Relation,
    model: UseCaseModel,
    scale: int,
) -> None:
    """绘制关系（带箭头的直线）"""
    # 查找参与者
    actor = None
    for a in model.actors:
        if a.name == relation.from_actor:
            actor = a
            break

    if actor is None:
        return

    # 查找用例
    usecase = None
    for u in model.usecases:
        if u.name == relation.to_usecase:
            usecase = u
            break

    if usecase is None:
        return

    # 计算连接点
    # Actor的连接点：右侧手臂或身体
    actor_cx = actor.x
    actor_cy = actor.y + ACTOR_HEIGHT // 2

    # UseCase的连接点：使用椭圆边缘点
    usecase_cx = usecase.x
    usecase_cy = usecase.y + usecase.height // 2

    # 计算从Actor指向UseCase的边缘点
    actor_edge_x, actor_edge_y = _actor_edge_point(actor_cx, actor_cy, usecase_cx, usecase_cy)
    usecase_edge_x, usecase_edge_y = ellipse_edge_point(
        usecase_cx, usecase_cy,
        usecase.width / 2, usecase.height / 2,
        actor_cx, actor_cy
    )

    # 绘制线条
    draw.line(
        (
            (int(actor_edge_x * scale), int(actor_edge_y * scale)),
            (int(usecase_edge_x * scale), int(usecase_edge_y * scale)),
        ),
        fill="#000000",
        width=1 * scale,
    )

    # 绘制箭头（在UseCase端）
    _draw_arrow(draw, actor_edge_x, actor_edge_y, usecase_edge_x, usecase_edge_y, scale)


def _actor_edge_point(cx: float, cy: float, tx: float, ty: float) -> tuple[float, float]:
    """计算Actor的边缘点

    简化为矩形边缘计算，Actor的碰撞盒为：
    - 宽度：ACTOR_WIDTH
    - 高度：ACTOR_HEIGHT
    """
    dx = tx - cx
    dy = ty - cy
    if dx == 0 and dy == 0:
        return cx, cy

    half_w = ACTOR_WIDTH / 2.0
    half_h = ACTOR_HEIGHT / 2.0

    ratio = 1.0 / max(
        abs(dx) / half_w if half_w else 1.0,
        abs(dy) / half_h if half_h else 1.0
    )
    return cx + dx * ratio, cy + dy * ratio


def _draw_arrow(
    draw: ImageDraw.ImageDraw,
    x1: float, y1: float,
    x2: float, y2: float,
    scale: int,
    arrow_size: int = 8,
) -> None:
    """绘制箭头"""
    # 计算角度
    angle = math.atan2(y2 - y1, x2 - x1)

    # 箭头两翼的角度
    left_angle = angle + math.pi * 0.85  # 约150度
    right_angle = angle - math.pi * 0.85

    # 箭头两翼的端点
    ax1 = x2 + arrow_size * math.cos(left_angle)
    ay1 = y2 + arrow_size * math.sin(left_angle)
    ax2 = x2 + arrow_size * math.cos(right_angle)
    ay2 = y2 + arrow_size * math.sin(right_angle)

    # 绘制箭头两翼
    draw.line(
        (
            (int(x2 * scale), int(y2 * scale)),
            (int(ax1 * scale), int(ay1 * scale)),
        ),
        fill="#000000",
        width=1 * scale,
    )
    draw.line(
        (
            (int(x2 * scale), int(y2 * scale)),
            (int(ax2 * scale), int(ay2 * scale)),
        ),
        fill="#000000",
        width=1 * scale,
    )


def _render_empty(auto_crop: bool, safe_margin: int, scale: int = None, downsample_output: bool = False, dpi: tuple[int, int] = (150, 150)) -> bytes:
    """渲染空状态"""
    if scale is None:
        scale = SCALE
    image = Image.new("RGB", (800 * scale, 600 * scale), "#FFFFFF")
    draw = ImageDraw.Draw(image)
    font = load_font(12 * scale)
    draw.text(
        (400 * scale, 300 * scale),
        "No use case data found.",
        fill="#000000",
        font=font,
        anchor="mm",
    )
    if downsample_output:
        image = downsample(image, scale)
    final = finalize_image(
        image,
        bg_color=(255, 255, 255),
        auto_crop=auto_crop,
        safe_margin=safe_margin,
    )
    return to_png_bytes(final, dpi=dpi)
