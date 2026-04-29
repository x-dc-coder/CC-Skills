---
name: diagram-module
description: |
  生成功能模块图（树形结构图）。当用户需要以下功能时触发：
  - 生成功能模块图、系统模块结构图
  - 创建树形功能层次图
  - 可视化模块组成关系
  - 展示系统功能架构
  
  使用本项目的 CLI 工具 `uv run python -m scripts.cli` 生成功能模块图。
---

# 功能模块图生成 Skill

## 工作流程

生成功能模块图的标准流程：

1. **获取模块结构**
   - 基于用户提供的系统功能模块信息
   - 整理为树形层次结构

2. **创建 JSON 文件**
   - 路径：`docs/module/json/<module_name>.json`
   - 使用树形结构描述功能模块层次

3. **生成模块图**
   - 使用本项目的 CLI 工具生成 PNG 图片
   - 输出路径：`docs/module/diagram/<module_name>.png`

## 目录结构

```
docs/module/
├── json/       # JSON 数据文件
└── diagram/    # 生成的模块图 PNG
```

## JSON 文件规范

### 基本结构
```json
{
  "tree": {
    "name": "系统名称",
    "children": [
      {
        "name": "模块A",
        "children": [
          {"name": "子模块A1"},
          {"name": "子模块A2"}
        ]
      },
      {"name": "模块B"}
    ]
  }
}
```

### 字段说明
- `name`: 模块名称（简洁明了）
- `children`: 子模块数组（可选）
- 支持多级嵌套，建议不超过 3 层

## 样式说明

- **根节点（第一层）**：水平文字
- **子节点（第二层及以下）**：竖直文字（从上到下排列）
- **学术紧凑风格**：纯黑色边框，白色背景

## 模块图生成命令

```bash
uv run python -m scripts.cli \
  --json-file docs/module/json/<module_name>.json \
  --out docs/module/diagram/<module_name>.png
```

## 示例

### 电商系统功能模块
```json
{
  "tree": {
    "name": "电商系统",
    "children": [
      {
        "name": "用户管理",
        "children": [
          {"name": "用户注册"},
          {"name": "用户登录"},
          {"name": "个人信息"}
        ]
      },
      {
        "name": "商品管理",
        "children": [
          {"name": "商品浏览"},
          {"name": "商品搜索"},
          {"name": "商品详情"}
        ]
      },
      {
        "name": "订单管理",
        "children": [
          {"name": "购物车"},
          {"name": "订单创建"},
          {"name": "订单查询"}
        ]
      }
    ]
  }
}
```

生成命令：
```bash
uv run python -m scripts.cli \
  --json-file docs/module/json/ecommerce.json \
  --out docs/module/diagram/ecommerce.png
```

## 简化格式（直接使用）

也可以直接使用简化格式，省略 `--out` 参数：

```bash
uv run python -m scripts.cli --json-file module.json
```

默认输出到 `docs/module/diagram.png`

## 依赖安装

```bash
cd ~/.claude/skills
uv sync
```
