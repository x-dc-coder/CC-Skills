---
name: d2-paper
description: >
  使用 D2 声明式图表语言 + d2-render 工具包生成高质量学术图表。
  **仅当其他 diagram-* skill 无法满足时使用本 skill（兜底方案）。**

  支持类图、SQL表图、实验对比表(grid)、神经网络结构图、思维架构图/理论框架图、
  数据流图、多层看板(layers/scenarios)、LaTeX公式图、代码块等多种图表类型。

  **高度自定义**：字体(宋体/Times New Roman/任意.ttf)、配色、字号、布局引擎(elk/dagre)、
  边距、连接线样式、填充图案、3D/阴影/圆角/透明度效果、变量复用等全部可调。

  **触发规则** — 以下关键词且其他 diagram-* 无法处理时触发：
  - "论文图" "学术图表" "论文插图" "毕业论文图" "期刊图"
  - "d2 绘图" "用 D2 画" "D2 渲染" "d2-render"
  - "实验对比表" "实验结果表" "消融实验" "基准对比" "性能对比表"
  - "神经网络图" "网络结构图" "模型架构图" "深度学习"
  - "思维架构图" "理论框架图" "概念框架图" "分析框架图"
  - "数据流图" "数据流程图" "知识图谱构建流程" "ETL"
  - "研究方法" "技术路线" "研究步骤" "算法流程"
  - "类图" "SQL表图" "序列图" "看板图" "多场景图" "LaTeX公式图"
  - "数字经济" "数据要素" "产业数字化" "数字治理"

  **优先级规则**：如果用户说"画个流程图"，优先用 diagram-flow；说"画个架构图"，
  优先用 diagram-architecture；说"画时序图"，优先用 diagram-sequence。
  d2-paper 仅在这些专用 skill 无法产出所需图表时兜底（如实验对比表、神经网络图、
  理论框架图等学术专属图表）。
---

# D2 学术论文绘图 Skill

> **优先级规则**：流程图用 diagram-flow，架构图用 diagram-architecture，时序图用 diagram-sequence，ER图用 diagram-er/ers，模块图用 diagram-module。d2-paper 负责这些专用 skill 无法产出的论文专属图表。

## 工具与安装

| 项目 | 路径/命令 |
|------|-----------|
| 工具包 | `/home/dc/projects/D2/d2-paper-toolkit/` |
| 渲染脚本 | `/home/dc/projects/D2/d2-paper-toolkit/d2-render` |
| 全局命令 | `~/.local/bin/d2-render`（已安装到 PATH） |
| 示例文件 | `/home/dc/projects/D2/d2-paper-toolkit/examples/` |
| 工作区 | `/home/dc/projects/D2/d2-paper-toolkit/workspace/` |
| 字体目录 | `/home/dc/projects/D2/d2-paper-toolkit/fonts/` |

### 前置依赖

D2 CLI v0.7.1 已安装在 `~/.local/bin/d2`。使用前确保：

```bash
export PATH="$HOME/.local/bin:$PATH"
```

### 基本调用

```bash
# 默认学术风格渲染（宋体 + 紧凑 ELK 布局）
d2-render <input.d2> [output.svg|output.png|output.pdf]

# 自定义所有参数
D2_LAYOUT=dagre D2_PAD=50 D2_ELK_NODE_GAP=60 d2-render input.d2 output.png
```

## 工作流

1. 询问用户：图表类型、标题、内容、特殊样式要求
2. 在 `workspace/` 下编写 `.d2` 文件
3. 渲染：

```bash
export PATH="$HOME/.local/bin:$PATH"
d2-render workspace/<name>.d2 workspace/<name>.svg
d2-render workspace/<name>.d2 workspace/<name>.png  # 预览用
```

4. 将输出路径告诉用户。SVG 可嵌入 LaTeX/Word，PNG 用于预览。

## 快速开始模板

```d2
vars: {
  d2-config: {
    layout-engine: elk
    theme-id: 0
  }
}
direction: down

my_node: "节点文字" {
  shape: rectangle
  style.fill: "#FFFFFF"
  style.stroke: "#333333"
  style.font-size: 14
  style.font-color: "#000000"
}

a -> b: "标注文字" {
  style.stroke: "#666666"
  style.stroke-dash: 3
  style.font-size: 12
}
```

## ⚠️ 字体限制（重要）

D2 只支持一种字体，无法混搭中文/英文字体。

| 场景 | 推荐字体 | 效果 |
|------|----------|------|
| **中文学术论文** | SimSun-Regular.ttf（宋体） | 中文=宋体，英文=宋体内嵌拉丁字形 |
| **英文学术论文** | Times New Roman 系列 | 英文=TNR，中文=豆腐块(无CJK字形) |
| **中英混合推荐** | SimSun-Regular.ttf | 中文是宋体，英文虽非TNR但字形整洁 |
| 开源替代 | Noto Serif CJK SC (思源宋体) | 中文=宋体风格，英文=衬线体 |

> 如果选 TNR，中文会丢失（显示为方块）；选宋体，英文用宋体内嵌的拉丁字符。

## 字号对照（pt → D2 px）

D2 的 `style.font-size` 单位是 **px**，不是 pt。

| 论文标准 | 中文字号 | pt | D2 px |
|----------|----------|-----|-------|
| 图表主标题 | 小四号 | 12pt | **18px** |
| 容器/节点标签 | 五号 | 10.5pt | **14px** |
| 子节点/嵌套 | 小五号 | 9pt | **13px** |
| 表格内容 | 六号 | 7.5pt | **12px** |
| 连接标注 | 七号 | 5.5pt | **11px** |

## 布局引擎选择

- **严格分层/树形** → ELK（默认）
- **网状/自由连接** → Dagre
- **表格/网格数据** → 不需要布局引擎（grid 自身管理位置）

```bash
D2_LAYOUT=dagre d2-render input.d2
```

## 容器内子节点排列（防图片过宽）

⚠️ ELK/dagre 默认将容器内子节点水平排列。超过 3 个时宽度急剧膨胀。
用 `grid-rows` + `grid-columns` 强制垂直排列：

```d2
# ❌ 错误：4 个子节点挤在一行 → 图片超宽
module: 功能模块 {
  child1: 子功能A
  child2: 子功能B
  child3: 子功能C
  child4: 子功能D
}

# ✅ 正确：grid 强制竖排 → 紧凑纵向
module: 功能模块 {
  grid-rows: 4
  grid-columns: 1
  child1: 子功能A {width: 200}
  child2: 子功能B {width: 200}
  child3: 子功能C {width: 200}
  child4: 子功能D {width: 200}
}
```

`grid-rows` 值必须等于子节点数量，否则会留空行或溢出。

## 节点内边距（文字居中不贴边）

D2 自动尺寸无内边距控制，默认 auto-size 导致文字贴底边。
给节点显式设 `width` 和 `height`：

**height 公式**：`height ≥ font-size × 3.5`

| 字号 | 最小 height | 推荐 height |
|------|------------|------------|
| 13px（子节点） | 44px | 48px |
| 14px（节点） | 48px | 52px |
| 15px（模块） | 52px | 56px |

⚠️ **容器不要设 `height`**：ELK 把容器 `height` 当固定值，导致父容器不扩展、子节点溢出。

```d2
# ❌ 错误：容器设 height → 父容器被「卡死」
module: 模块 {
  height: 48
  grid-rows: 4
  child1: "文字" {width: 200; height: 44}
}

# ✅ 正确：仅叶节点设 height，容器自适应
module: 模块 {
  grid-rows: 4
  child1: "文字" {width: 200; height: 44}
  child2: "文字" {width: 200; height: 44}
}
```

```d2
# ❌ 错误：无 width/height，文字贴边不对称
item: 功能名称 {style.fill: "#FAFAFA"; style.stroke: "#333333"; style.font-size: 13}

# ✅ 正确：显式 width + height
item: 功能名称 {
  style.fill: "#FAFAFA"
  style.stroke: "#333333"
  style.font-size: 13
  width: 200
  height: 40
}
```

容器标题边距：增大 `--elk-padding`（如 `[top=40,...]`）使子节点下移改善视觉效果。

## 配色建议

- **论文黑白版**：`#333333` 描边 + `#FFFFFF`/`#FAFAFA`/`#F5F5F5`/`#EDEDED` 四级灰底
- **彩色版（PPT/答辩）**：`--theme 0-105`
- **色盲友好**：`--theme 8`
- **深色模式**：`--theme 200` 或 `--theme 201`

## 常见错误

- ❌ .ttc 字体文件（D2 只支持 .ttf）
- ❌ `style.font-style: italic` → 正确是 `style.italic: true`
- ❌ `style.font-weight: bold` → 正确是 `style.bold: true`
- ❌ elk-* 配置写在 .d2 的 d2-config 中 → 必须通过 CLI 传递
- ❌ `near: center` → 正确是 `near: center-left` 或 `near: center-right`
- ❌ 4个以上 ELK 容器同时用 `near: center-left`（PNG 渲染可能出错）
- ❌ `left`/`right` 作为节点 ID → 它们是 D2 保留关键字

## 文字重叠修复策略（按优先级）

1. 增大 ELK 层间距：`D2_ELK_NODE_GAP=55`（默认35），严重时用 70+
2. 增大 Dagre 间距：`--dagre-nodesep 80 --dagre-edgesep 30`
3. SQL Table 限宽：加 `width: 200`
4. 缩短字段名：`password_hash` → `pass`
5. 换用 dagre 布局：SQL ERD / 网状图用 `--layout dagre`
6. 增大画布边距：`D2_PAD=50`（默认30）
7. 减少节点数：拆分为多张图
8. 容器内用 grid 垂直排列：`grid-rows: N; grid-columns: 1`

## 7 种内置示例

所有示例源码：`/home/dc/projects/D2/d2-paper-toolkit/examples/`

| # | 文件 | 类型 | 关键特征 |
|---|------|------|---------|
| 1 | `01-research-flow.d2` | 研究方法流程图 | oval起止 + diamond分支 + 虚线反馈 |
| 2 | `02-architecture.d2` | 系统架构图 | direction:right + 四层容器 + cylinder/hexagon |
| 3 | `03-algorithm.d2` | 算法流程图 | parallelogram输入 + 虚线循环容器 + diamond收敛 |
| 4 | `04-comparison-table.d2` | 实验对比表 | grid表格 + 交替行色 + 本文方法高亮 |
| 5 | `05-class-diagram.d2` | UML类图 | shape:class + 可见性前缀 + 关系线基数标注 |
| 6 | `06-digital-economy.d2` | 理论框架图 | hexagon核心 + 四支柱容器 + 双向虚线关联 |
| 7 | `07-data-market.d2` | 数据流图 | direction:right + pipeline + diamond关键节点 |

## d2-render 常用环境变量

```bash
D2_FONT_DIR=/my/fonts d2-render input.d2       # 自定义字体目录
D2_LAYOUT=dagre d2-render input.d2             # 切换布局
D2_PAD=50 d2-render input.d2                   # 画布边距
D2_ELK_NODE_GAP=50 d2-render input.d2          # 节点间距
```

d2-render 已预设：宋体 + ELK 布局 + 30px边距 + 35px节点间距 + 主题0。

## 完整 D2 语法参考

Shape 类型、UML类图、SQL表图、Grid表格、连接线、容器、LaTeX、多层看板、
序列图、变量/classes复用、CLI功能、视觉效果等完整语法 → **[references/d2-language.md](references/d2-language.md)**
