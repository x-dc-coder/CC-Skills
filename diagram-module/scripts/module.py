"""功能模块图渲染模块

绘制树形功能模块结构图：
- 第一层（根节点）：水平文字
- 第二层及以下：竖直文字（从上到下排列）
- 自动计算树形布局
- 支持纯白色背景和边距裁剪
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# 常量配置 - 学术紧凑风格
SCALE = 2  # 适度缩放，平衡清晰度与性能（避免下采样过度模糊）
NODE_W = 72  # 竖排文字的节点宽度（1x 尺寸）
NODE_H = 80  # 竖排文字的最小节点高度（1x 尺寸，紧凑）
ROOT_NODE_W = 280  # 根节点宽度（水平文字，1x 尺寸）
ROOT_NODE_H = 72  # 根节点高度（1x 尺寸）
H_SPACING = 24  # 水平间距（1x 尺寸）
V_SPACING = 32  # 垂直间距（1x 尺寸）
FONT_SIZE = 28  # 字体大小（1x 尺寸）
VERTICAL_TEXT_EDGE_PADDING = 0  # 竖排文本首尾额外安全边距
VERTICAL_TEXT_EDGE_TRIM = 16  # 竖排文本首尾留白裁剪量（像素）


@dataclass
class TreeNode:
    """树节点"""
    name: str
    children: list[TreeNode] = field(default_factory=list)
    depth: int = 0
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0


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

    # 3. 系统字体路径
    system_candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
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


def to_png_bytes(image: Image.Image) -> bytes:
    """将图片转换为PNG字节"""
    from io import BytesIO
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def render_module_diagram(
    model: dict,
    auto_crop: bool = True,
    safe_margin: int = 24,
) -> bytes:
    """渲染功能模块图

    Args:
        model: 模块图模型，包含 tree 字段
        auto_crop: 是否自动裁剪空白边距
        safe_margin: 安全边距（像素）

    Returns:
        PNG图片字节数据
    """
    tree_data = model.get("tree", {})
    if not tree_data:
        return _render_empty(auto_crop, safe_margin)

    # 构建树结构
    root = _build_tree(tree_data)

    # 先加载字体，用于计算文字高度
    font = load_font(FONT_SIZE * SCALE)

    # 计算根节点自适应宽度
    root.width = _calc_root_node_width(root.name, font)

    # 计算每一层的统一高度（自适应高度，同一层高度一致）
    layer_heights = _calc_layer_heights(root, font, SCALE)

    # 计算布局（使用统一高度）
    _calculate_tree_size(root, layer_heights)
    _layout_tree(root, 0, 0, layer_heights)

    # 获取画布尺寸
    canvas_w, canvas_h, offset_x, offset_y = _get_canvas_bounds(root)

    # 调整所有节点位置
    def adjust_position(node: TreeNode):
        node.x += offset_x
        node.y += offset_y
        for child in node.children:
            adjust_position(child)

    adjust_position(root)

    # 创建画布
    image = Image.new("RGB", (canvas_w * SCALE, canvas_h * SCALE), "#FFFFFF")
    draw = ImageDraw.Draw(image)

    # 绘制
    _draw_tree(draw, root, font, SCALE)

    # 后处理
    final = finalize_image(
        downsample(image, SCALE),
        bg_color=(255, 255, 255),
        auto_crop=auto_crop,
        safe_margin=safe_margin,
    )
    return to_png_bytes(final)


def _build_tree(data: dict, depth: int = 0) -> TreeNode:
    """从字典构建树结构"""
    name = data.get("name", "未知")
    node = TreeNode(name=name, depth=depth)

    for child_data in data.get("children", []):
        child = _build_tree(child_data, depth + 1)
        node.children.append(child)

    return node


def _calc_root_node_width(text: str, font: ImageFont.ImageFont) -> int:
    """计算根节点所需的宽度（根据水平文字长度自适应）

    Returns:
        1x 尺寸上的节点宽度
    """
    if not text:
        return ROOT_NODE_W

    # 测量文字宽度（2x 画布上的像素值）
    text_width = int(font.getlength(text))
    # 左右各留一个汉字宽度作为边距
    padding = int(font.getlength("汉"))
    # 转换为 1x 值
    return max(ROOT_NODE_W, (text_width + padding * 2) // SCALE)


def _calc_node_height(node: TreeNode, font: ImageFont.ImageFont, scale: int) -> int:
    """计算节点所需的高度（根据文字长度自适应）

    根节点（depth=0）：水平文字，固定高度
    其他节点：竖直文字，根据字符数计算所需高度
    """
    if node.depth == 0:
        # 根节点：水平文字，使用固定高度
        return ROOT_NODE_H

    text = node.name
    if not text:
        return NODE_H

    total_height, _line_step, _upper, _lower = _measure_vertical_text_block(text, font)
    # total_height 是 2x 画布上的像素值，转换为 1x 值
    return max(NODE_H, total_height // SCALE)


def _calc_layer_heights(root: TreeNode, font: ImageFont.ImageFont, scale: int) -> dict[int, int]:
    """计算每一层所有节点的统一高度（取该层最大高度）

    Returns:
        dict: key为层数depth，value为该层的统一高度
    """
    layer_heights: dict[int, list[int]] = {}

    def collect_heights(node: TreeNode):
        # 计算当前节点所需高度
        required_height = _calc_node_height(node, font, scale)

        # 收集到对应层
        if node.depth not in layer_heights:
            layer_heights[node.depth] = []
        layer_heights[node.depth].append(required_height)

        # 递归收集子节点
        for child in node.children:
            collect_heights(child)

    collect_heights(root)

    # 对每一层取最大高度作为统一高度
    return {depth: max(heights) for depth, heights in layer_heights.items()}


def _calculate_tree_size(node: TreeNode, layer_heights: dict[int, int]) -> int:
    """计算树的大小（后序遍历）

    Args:
        node: 当前节点
        layer_heights: 每层的统一高度

    Returns:
        该子树所需的总宽度
    """
    # 设置节点尺寸（使用层统一高度）
    if node.depth == 0:
        # 根节点宽度已在 render_module_diagram 中自适应计算
        node.height = layer_heights.get(0, ROOT_NODE_H)
    else:
        node.width = NODE_W
        node.height = layer_heights.get(node.depth, NODE_H)

    if not node.children:
        # 叶子节点：宽度就是节点宽度
        return node.width

    # 非叶子节点：宽度是所有子节点宽度之和加上间距
    children_width = 0
    for i, child in enumerate(node.children):
        child_width = _calculate_tree_size(child, layer_heights)
        children_width += child_width
        if i < len(node.children) - 1:
            children_width += H_SPACING

    # 节点宽度至少等于子节点总宽度
    return max(node.width, children_width)


def _layout_tree(node: TreeNode, start_x: int, start_y: int, layer_heights: dict[int, int]) -> None:
    """计算节点位置（前序遍历）

    Args:
        node: 当前节点
        start_x: 该子树起始x坐标（左边界）
        start_y: 该子树的y坐标
        layer_heights: 每层的统一高度
    """
    # 设置节点尺寸（使用层统一高度）
    if node.depth == 0:
        # 根节点宽度已在 render_module_diagram 中自适应计算
        node.height = layer_heights.get(0, ROOT_NODE_H)
    else:
        node.width = NODE_W
        node.height = layer_heights.get(node.depth, NODE_H)

    node.y = start_y

    if not node.children:
        # 叶子节点：在可用空间内居中
        node.x = start_x + node.width // 2
        return

    # 计算子树大小
    children_sizes = [_get_subtree_width(child) for child in node.children]
    total_children_width = sum(children_sizes) + H_SPACING * (len(node.children) - 1)

    # 当前节点在子树范围内居中
    subtree_width = max(node.width, total_children_width)
    node.x = start_x + subtree_width // 2

    # 布局子节点（使用下一层的统一高度）
    child_y = start_y + node.height + V_SPACING
    current_x = start_x + (subtree_width - total_children_width) // 2

    for i, child in enumerate(node.children):
        child_size = children_sizes[i]
        # 子节点在其子树范围内居中
        _layout_tree(child, current_x, child_y, layer_heights)
        current_x += child_size + H_SPACING


def _get_subtree_width(node: TreeNode) -> int:
    """获取子树宽度（已计算好的）"""
    if not node.children:
        return node.width

    children_width = sum(_get_subtree_width(child) for child in node.children)
    children_width += H_SPACING * (len(node.children) - 1)
    return max(node.width, children_width)


def _get_canvas_bounds(root: TreeNode) -> tuple[int, int, int, int]:
    """获取画布边界和偏移量

    Returns:
        (宽度, 高度, x偏移, y偏移)
    """
    min_x, max_x = float('inf'), float('-inf')
    min_y, max_y = float('inf'), float('-inf')

    def traverse(node: TreeNode):
        nonlocal min_x, max_x, min_y, max_y
        left = node.x - node.width // 2
        right = node.x + node.width // 2
        top = node.y
        bottom = node.y + node.height

        min_x = min(min_x, left)
        max_x = max(max_x, right)
        min_y = min(min_y, top)
        max_y = max(max_y, bottom)

        for child in node.children:
            traverse(child)

    traverse(root)

    # 添加边距
    padding = 20  # 画布边距（学术紧凑风格）
    width = max_x - min_x + padding * 2
    height = max_y - min_y + padding * 2
    offset_x = -min_x + padding
    offset_y = -min_y + padding

    return width, height, offset_x, offset_y


def _draw_tree(draw: ImageDraw.ImageDraw, node: TreeNode, font: ImageFont.ImageFont, scale: int) -> None:
    """绘制树（先画线，再画节点）"""
    # 先画到子节点的连接线
    for child in node.children:
        _draw_connection(draw, node, child, scale)
        _draw_tree(draw, child, font, scale)

    # 再画当前节点（覆盖线条）
    _draw_node(draw, node, font, scale)


def _draw_node(draw: ImageDraw.ImageDraw, node: TreeNode, font: ImageFont.ImageFont, scale: int) -> None:
    """绘制节点"""
    left = node.x - node.width // 2
    top = node.y
    right = node.x + node.width // 2
    bottom = node.y + node.height

    # 绘制矩形边框
    draw.rectangle(
        (left * scale, top * scale, right * scale, bottom * scale),
        fill="#FFFFFF",
        outline="#000000",
        width=2 * scale,
    )

    # 绘制文字
    if node.depth == 0:
        # 根节点：水平居中
        draw.text(
            (node.x * scale, (node.y + node.height // 2) * scale),
            node.name,
            fill="#000000",
            font=font,
            anchor="mm",
        )
    else:
        # 非根节点：竖直排列（从上到下）
        _draw_vertical_text(
            draw,
            node.name,
            node.x * scale,
            (node.y + node.height // 2) * scale,
            font,
            scale,
        )


def _draw_vertical_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    cx: int,
    cy: int,
    font: ImageFont.ImageFont,
    scale: int,
) -> None:
    """绘制竖直文字（从上到下）

    第一个字紧贴文本框顶部，最后一个字紧贴底部，消除上下空白
    """
    if not text:
        return

    total_height, line_step, upper_extent, _lower_extent = _measure_vertical_text_block(text, font)

    # 计算文本框的顶部位置
    box_top = cy - total_height // 2

    # 第一个字中心 = 顶部 + 首字符中心到顶部的距离，确保首字顶部正好在 box_top
    current_y = box_top + upper_extent

    # 逐字绘制
    for char in text:
        draw.text((cx, current_y), char, fill="#000000", font=font, anchor="mm")
        current_y += line_step


def _measure_vertical_text_block(text: str, font: ImageFont.ImageFont) -> tuple[int, int, int, int]:
    """测量竖排文本块尺寸（返回 2x 画布上的像素值）。

    Returns:
        (total_height, line_step, upper_extent, lower_extent)
    """
    if not text:
        return NODE_H * SCALE, 0, 0, 0

    boxes = [font.getbbox(char, anchor="mm") for char in text]
    bbox_heights = [box[3] - box[1] for box in boxes]
    avg_bbox_height = int(sum(bbox_heights) / len(bbox_heights)) if bbox_heights else 50
    # 步距：字符实际高度 + 半个汉字高度作为间距
    line_step = avg_bbox_height + avg_bbox_height // 2

    # 首字符中心到顶部的距离、尾字符中心到底部的距离
    # 上下各留一个完整汉字高度作为边距
    first_top = boxes[0][1]
    last_bottom = boxes[-1][3]
    upper_extent = -first_top + avg_bbox_height
    lower_extent = last_bottom + avg_bbox_height

    # 总高度 = 上留白 + 中间字间距 + 下留白
    total_height = (len(text) - 1) * line_step + upper_extent + lower_extent
    return total_height, line_step, upper_extent, lower_extent


def _draw_connection(
    draw: ImageDraw.ImageDraw,
    parent: TreeNode,
    child: TreeNode,
    scale: int,
) -> None:
    """绘制父子节点之间的连接线"""
    # 从父节点底部中心到子节点顶部中心
    parent_x = parent.x
    parent_y = parent.y + parent.height
    child_x = child.x
    child_y = child.y

    if parent_x == child_x:
        # 垂直直连
        draw.line(
            ((parent_x * scale, parent_y * scale), (child_x * scale, child_y * scale)),
            fill="#000000",
            width=1 * scale,
        )
    else:
        # 使用倒T形连接：父节点底部 -> 同一水平线 -> 子节点顶部
        mid_y = (parent_y + child_y) // 2

        # 父节点到底部中间
        draw.line(
            ((parent_x * scale, parent_y * scale), (parent_x * scale, mid_y * scale)),
            fill="#000000",
            width=1 * scale,
        )
        # 水平连接线
        draw.line(
            ((parent_x * scale, mid_y * scale), (child_x * scale, mid_y * scale)),
            fill="#000000",
            width=1 * scale,
        )
        # 子节点顶部到中间
        draw.line(
            ((child_x * scale, mid_y * scale), (child_x * scale, child_y * scale)),
            fill="#000000",
            width=1 * scale,
        )


def _render_empty(auto_crop: bool, safe_margin: int) -> bytes:
    """渲染空状态"""
    image = Image.new("RGB", (800 * SCALE, 600 * SCALE), "#FFFFFF")
    draw = ImageDraw.Draw(image)
    font = load_font(24 * SCALE)
    draw.text(
        (400 * SCALE, 300 * SCALE),
        "No module data found.",
        fill="#000000",
        font=font,
        anchor="mm",
    )
    final = finalize_image(
        downsample(image, SCALE),
        bg_color=(255, 255, 255),
        auto_crop=auto_crop,
        safe_margin=safe_margin,
    )
    return to_png_bytes(final)
