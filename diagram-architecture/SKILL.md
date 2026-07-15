---
name: diagram-architecture
description: |
  使用 Graphviz (dot) 生成学术论文级别的系统架构图。内置 4 种结构布局模板（对称双塔、线性流水线、正交工程图、多层嵌套），自动控制图片尺寸适配论文双栏/单栏排版，输出 PDF + PNG。
  当用户需要绘制架构图、系统架构图、技术架构图、模型架构图、流程架构图、论文插图、系统设计图时，必须使用此 skill。即使用户只说"画个架构图"或"帮我画图"或"论文里需要一张系统图"，也应触发。触发关键词包括但不限于：架构图、系统图、流程图、模块图、技术架构、模型架构、论文插图、系统设计、architecture diagram、system diagram。
  此 skill 生成的是 Graphviz DOT 源码并编译为 PDF/PNG，不是 Mermaid 或 D2。
---

# 架构图生成器 (Graphviz)

## 概述

用 Graphviz 的 `dot` 布局引擎生成学术论文级架构图。核心优势：**零排版负担**——你只描述节点和边，位置由算法自动计算，天然避免重叠、交叉、对齐问题。

## 环境依赖

- `dot` (Graphviz) — 布局引擎
- `Noto Sans CJK SC` / `Noto Serif CJK SC` — 中文字体（系统已安装）
- `pdftoppm` — PDF 转 PNG 预览

验证：`dot -V && fc-list :lang=zh | grep "Noto Sans CJK SC"`

## 4 种结构布局选择

根据架构的特征选择最合适的布局：

| 布局 | 适用场景 | 结构特征 | 参考文件 |
|------|---------|---------|---------|
| **对称双塔** | 双塔推荐模型、Encoder-Decoder、对比学习 | 左右两条平行分支，顶部共享输入，底部汇聚 | `references/symmetric-dual-tower.md` |
| **线性流水线** | MLOps 生命周期、ETL 管道、CI/CD 流程 | 从左到右线性流转，上方反馈闭环，下方产物存储 | `references/pipeline-linear.md` |
| **正交工程图** | 大数据平台、微服务架构、基础设施拓扑 | 所有连线 90 度正交，嵌套 cluster 分区 | `references/orthogonal-engineering.md` |
| **多层嵌套** | AI 平台、云原生系统、复杂多子系统 | 三层 cluster 嵌套，横向跨区连接，newrank 全局对齐 | `references/nested-hierarchy.md` |

**选择原则**：如果架构有两条对称的并行处理路径 → 双塔；如果是线性流程 → 流水线；如果需要工程图的严谨正交连线 → 正交工程图；如果子系统多且需要分层嵌套 → 多层嵌套。

## 图片尺寸控制（论文适配）

这是学术论文插图的关键。Graphviz 通过以下属性控制最终图片尺寸：

### 1. 全局尺寸约束

```dot
graph [size="3.5,4!"]  // 宽3.5英寸, 高最多4英寸, ! 表示严格不超
```

**关键**：`size` 的 `!` 后缀表示严格约束——输出图片绝不会超过此尺寸。如果内容超出，Graphviz 会等比缩小。因此设置时要留余量：

| 论文排版 | 推荐尺寸 (英寸) | 实际可用宽度 | 说明 |
|---------|----------------|------------|------|
| **单栏**（IEEE/ACM 双栏论文） | `size="3.3,4.5!"` | ~3.3" | 占一栏，留 0.2" 余量 |
| **跨双栏** | `size="6.8,4.5!"` | ~6.8" | 横跨双栏，留 0.2" 余量 |
| **全页**（学位论文单栏） | `size="5.3,7.5!"` | ~5.3" | A4 可容纳 |
| **PPT 展示** | `size="9.5,5.5!"` | ~9.5" | 16:9 比例 |

**尺寸超标排查**：如果编译后 PDF 宽度仍超标，检查：
1. `size` 是否加了 `!` 后缀（不加则只是建议，不强制）
2. `ranksep` 和 `nodesep` 是否过大（论文用 0.6-0.8 / 0.3-0.4）
3. 节点 `fontsize` 是否过大（论文用 9-10pt）
4. 节点文字是否过长（超过 6 字用 `\n` 换行）

### 2. DPI 控制（PNG 清晰度）

```bash
dot -Tpng -Gdpi=300 architecture.dot -o "$OUT_DIR/architecture.png"  # 300dpi 印刷级
dot -Tpng -Gdpi=200 architecture.dot -o "$OUT_DIR/architecture.png"  # 200dpi 屏幕级
```

### 3. 紧凑度控制

```dot
ranksep=0.8    // 层间距（默认1.0），论文用 0.6-0.8 更紧凑
nodesep=0.4    // 同层节点间距（默认0.25），论文用 0.3-0.5
```

### 4. 字体大小

```dot
node [fontsize=10]   // 论文用 9-10pt（太小看不清，太大占空间）
edge [fontsize=8]    // 边标签比节点小 1-2pt
graph [fontsize=12]  // 图标题
```

## 编译命令

**输出路径约定**：遵循 CLAUDE.md 统一规则——默认输出到 `<项目>/thesis-output/diagram-architecture/architecture.<pdf|png>`，兜底到 `~/.claude/skills-output/diagram-architecture/architecture.<pdf|png>`。先创建目录再编译。

```bash
# 创建输出目录（自动选择项目目录或兜底目录）
OUT_DIR="thesis-output/diagram-architecture"
[ -d "thesis-output" ] || OUT_DIR="$HOME/.claude/skills-output/diagram-architecture"
mkdir -p "$OUT_DIR"

# 生成 PDF（矢量，论文直接 \includegraphics）
dot -Tpdf architecture.dot -o "$OUT_DIR/architecture.pdf"

# 生成 PNG（位图，PPT 用）
dot -Tpng -Gdpi=300 architecture.dot -o "$OUT_DIR/architecture.png"

# 生成 SVG（网页用）
dot -Tsvg architecture.dot -o "$OUT_DIR/architecture.svg"
```

## 工作流程

1. **分析架构特征**：用户描述系统后，判断属于哪种结构（双塔/流水线/正交/嵌套）
2. **读取对应参考文件**：加载模板和样式配置
3. **生成 DOT 源码**：按模板结构填充用户的节点和边
4. **设置尺寸约束**：根据用户论文类型（单栏/双栏/全页）设置 `size` 和 `ranksep`
5. **编译**：生成 PDF + PNG
6. **验证**：检查图片尺寸是否合理、中文是否正常

## 学术配色方案

所有布局统一使用低饱和度配色，保证印刷友好：

| 色系 | 主色 | 背景色 | 用途 |
|------|------|--------|------|
| 蓝 | `#2E5C8A` | `#EFF6FF` | 输入/数据层 |
| 绿 | `#2D6E4E` | `#F0FDF4` | 预处理/特征层 |
| 橙 | `#B85C2A` | `#FDF6F0` | 模型/推理层 |
| 紫 | `#6B4E9E` | `#F5F3FF` | 输出/融合层 |
| 红 | `#B91C1C` | `#FEE2E2` | 强调/关键输出 |
| 灰 | `#6B7280` | `#F9FAFB` | 辅助/存储 |

## 关键原则

- **节点文字简短**：每个节点不超过 6 个字，超过的用 `\n` 换行
- **边标签简洁**：1-3 个字说明数据流类型
- **集群分组**：用 `subgraph cluster_xxx` 做功能分组，标题用 `label`
- **反馈线用虚线**：`style=dashed` + `constraint=false` 避免干扰主布局
- **中文字体**：`fontname="Noto Sans CJK SC"`（无衬线）或 `"Noto Serif CJK SC"`（衬线，学术论文推荐）

## 参考文件

当确定布局类型后，读取对应参考文件获取完整模板：

- `references/symmetric-dual-tower.md` — 对称双塔布局完整模板
- `references/pipeline-linear.md` — 线性流水线布局完整模板
- `references/orthogonal-engineering.md` — 正交工程图布局完整模板
- `references/nested-hierarchy.md` — 多层嵌套布局完整模板
