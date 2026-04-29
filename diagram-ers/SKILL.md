---
name: diagram-ers
description: |
  生成数据库实体关系图（ER图），展示多个实体及其关联关系。当用户需要以下功能时触发：
  - 生成 ER 图、实体关系图、E-R 图
  - 绘制多实体关联图（不含属性）
  - 展示数据库表之间的关系（1:1、1:n、m:n）
  - 可视化系统数据模型

  使用本项目的 CLI 工具 `uv run python -m scripts.cli` 生成 ER 图。
---

# ER 图生成 Skill

## 核心目标

根据用户提供的实体和关系数据，生成 **Chen 风格 ER 图**，专用于本科毕业论文数据库设计章节。

## 设计风格

- **实体**：矩形，白色背景 + 黑色边框
- **关系**：菱形，白色背景 + 黑色边框
- **连线**：黑色直线，标注基数（1、n、m）
- **属性**：**不绘制**（符合论文简化要求）
- **背景**：白色

## 工作流程

1. **整理实体与关系**
   - 列出系统中所有实体（对应数据库表）
   - 梳理实体之间的关系及基数

2. **创建 JSON 文件**
   - 路径：`docs/er/json/<name>.json`
   - 使用坐标定位确保连线不重叠

3. **生成 ER 图**
   - 使用 CLI 工具生成 PNG 图片
   - 输出路径：`skills/output/diagram-ers/diagram.png`（默认，可自定义）

## 目录结构

```
docs/er/
├── json/       # JSON 数据文件

skills/output/diagram-ers/    # 生成的 ER 图 PNG（默认输出目录）
```

## JSON 文件规范

### 基本结构

```json
{
  "title": "电影院线上订票系统E-R图",
  "entities": [
    {"name": "用户", "x": 100, "y": 200},
    {"name": "订单", "x": 100, "y": 400},
    {"name": "管理员", "x": 400, "y": 400},
    {"name": "电影", "x": 600, "y": 550},
    {"name": "活动", "x": 400, "y": 200}
  ],
  "relations": [
    {
      "name": "创建",
      "x": 100,
      "y": 300,
      "connects": [
        {"entity": "用户", "cardinality": "1"},
        {"entity": "订单", "cardinality": "n"}
      ]
    },
    {
      "name": "管理",
      "x": 250,
      "y": 400,
      "connects": [
        {"entity": "订单", "cardinality": "n"},
        {"entity": "管理员", "cardinality": "1"}
      ]
    }
  ]
}
```

### 字段说明

- `title`: 图标题（可选）
- `entities`: 实体列表
  - `name`: 实体名称（对应数据库表名或中文名）
  - `x`, `y`: 像素坐标（手动指定，避免连线重叠）
- `relations`: 关系列表
  - `name`: 关系名称
  - `x`, `y`: 像素坐标（通常放在关联实体的中间位置）
  - `connects`: 连接的实体及基数
    - `entity`: 实体名称（必须与 `entities` 中的 `name` 一致）
    - `cardinality`: 基数标注，如 `1`、`n`、`m`

## 坐标设计指南

为避免连线重叠，建议：

1. **先画草图**：在纸上或 draw.io 上大致排布实体位置
2. **使用网格坐标**：
   - 实体之间水平间距建议 **≥ 150**
   - 实体之间垂直间距建议 **≥ 120**
   - 关系菱形放在连线交叉点附近
3. **一对一关系**：关系菱形靠近实体连线的中点
4. **一对多关系**：关系菱形靠近 "1" 的一方
5. **多对多关系**：关系菱形放在两个实体的正中间

### 推荐坐标网格（以论文图4-9为参考）

设计原则：让关联的实体靠近，关系菱形放在两者中间。

```
        [留言]     [影院留言]    [回复]
          |            |           |
          1            n           n
          |            |           |
        [用户]---n[参加]m---[活动]---n[创建]1---[工作人员]
          |                         |
          n                         n
          |                         |
        [订单]---n[管理]1---[管理员]---n[创建]m---[日常工作/任务]
          |                                      |
          n                                      |
          |                                      |
        [关联]1---[排片]---n[新建]1---[电影]
                   |
                   1
                   |
                [影厅]
```

对应坐标示例（水平间距180~240，垂直间距150~200）：

```json
{
  "entities": [
    {"name": "用户", "x": 150, "y": 200},
    {"name": "订单", "x": 150, "y": 450},
    {"name": "管理员", "x": 550, "y": 450},
    {"name": "电影", "x": 800, "y": 650},
    {"name": "排片", "x": 450, "y": 650},
    {"name": "活动", "x": 450, "y": 200},
    {"name": "工作人员", "x": 850, "y": 200}
  ],
  "relations": [
    {"name": "参加", "x": 300, "y": 200, "connects": [
      {"entity": "用户", "cardinality": "n"},
      {"entity": "活动", "cardinality": "m"}
    ]},
    {"name": "创建", "x": 150, "y": 325, "connects": [
      {"entity": "用户", "cardinality": "1"},
      {"entity": "订单", "cardinality": "n"}
    ]},
    {"name": "管理", "x": 350, "y": 450, "connects": [
      {"entity": "订单", "cardinality": "n"},
      {"entity": "管理员", "cardinality": "1"}
    ]},
    {"name": "新建", "x": 625, "y": 650, "connects": [
      {"entity": "排片", "cardinality": "n"},
      {"entity": "电影", "cardinality": "1"}
    ]}
  ]
}
```

**坐标设计技巧**：
1. 水平间距 **≥ 180**（两实体之间），关系菱形放中间
2. 垂直间距 **≥ 150**（上下层实体之间）
3. 关系菱形坐标 = 两个实体坐标的平均值
4. 一对多关系：菱形更靠近 "1" 的一方约 1/3 处
5. 多对多关系：菱形严格放在两个实体正中间

## 样式说明

- **实体矩形**：120 x 60 像素，文字居中
- **关系菱形**：110 x 70 像素（旋转45°），文字居中
- **连线**：1px 黑色实线
- **基数标签**：14px 字体，白色背景覆盖线条，位于连线 30% 处（靠近实体）

## ER 图生成命令

```bash
uv run python -m scripts.cli \
  --json-file docs/er/json/<name>.json
```

当输入文件使用**绝对路径**时，CLI 会自动推断项目目录（向上查找包含 `docs/` 或 `thesis-output/` 的目录），默认输出到 `<项目目录>/thesis-output/img/diagram.png`。如使用相对路径或无法推断，则回退到 `skills/output/diagram-ers/diagram.png`。如需自定义路径：

```bash
uv run python -m scripts.cli \
  --json-file docs/er/json/<name>.json \
  --out <自定义路径>.png
```

## 示例

### 简单 ER 图（用户-订单-管理员）

```json
{
  "title": "订单管理系统E-R图",
  "entities": [
    {"name": "用户", "x": 150, "y": 150},
    {"name": "订单", "x": 150, "y": 350},
    {"name": "管理员", "x": 450, "y": 350}
  ],
  "relations": [
    {
      "name": "创建",
      "x": 150,
      "y": 250,
      "connects": [
        {"entity": "用户", "cardinality": "1"},
        {"entity": "订单", "cardinality": "n"}
      ]
    },
    {
      "name": "管理",
      "x": 300,
      "y": 350,
      "connects": [
        {"entity": "订单", "cardinality": "n"},
        {"entity": "管理员", "cardinality": "1"}
      ]
    }
  ]
}
```

生成命令：

```bash
uv run python -m scripts.cli \
  --json-file docs/er/json/simple.json
```

### 简化格式（直接使用）

```bash
uv run python -m scripts.cli --json-file er.json
```

默认输出路径由 CLI 自动推断（绝对路径输入 → `<项目目录>/thesis-output/img/diagram.png`，否则回退到 `skills/output/diagram-ers/diagram.png`）

## 环境管理（统一规范）

```bash
cd ~/.claude/skills
uv sync
```

- Python 依赖统一在根目录 `pyproject.toml` 管理，不在子目录单独安装
- 各 skill 子目录无需创建 `.venv`，`uv run` 会自动向上查找到根目录的虚拟环境

## 自检清单

输出前检查：
- [ ] 所有实体名称在 `entities` 和 `relations.connects` 中一致
- [ ] 每个关系至少连接 2 个实体
- [ ] 坐标已调整，连线不重叠
- [ ] 基数标注正确（1、n、m）
- [ ] 关系名称简洁（2-4字）
