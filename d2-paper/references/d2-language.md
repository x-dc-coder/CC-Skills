# D2 语言完整语法参考

> 从 d2-paper SKILL.md 提取，供需要完整 D2 语法时查阅。

## 快速开始模板

```d2
vars: {
  d2-config: {
    layout-engine: elk   # 或 dagre
    theme-id: 0          # 0 = 自定义颜色（论文推荐）
  }
}

direction: down           # down | right

# 任意节点
my_node: "节点文字" {
  shape: rectangle       # 可选，默认 rectangle
  style.fill: "#FFFFFF"
  style.stroke: "#333333"
  style.font-size: 14
  style.font-color: "#000000"
}

# 连接
a -> b: "标注文字" {
  style.stroke: "#666666"
  style.stroke-dash: 3   # 虚线（数字=间隔像素）
  style.font-size: 12
}
```

---

## 一、布局引擎

### ELK（Layered — 适合层次图、流程图）

| CLI 参数 | 默认值 | 含义 |
|----------|--------|------|
| `--elk-padding` | `[top=50,left=50,bottom=50,right=50]` | 容器内边距 |
| `--elk-nodeNodeBetweenLayers` | 70 | 层间节点间距 |
| `--elk-edgeNodeBetweenLayers` | 40 | 边缘与节点间距 |
| `--elk-nodeSelfLoop` | 50 | 自循环间距 |

### Dagre（适合自由拓扑、网状架构）

| CLI 参数 | 默认值 | 含义 |
|----------|--------|------|
| `--dagre-nodesep` | 60 | 节点水平间距 |
| `--dagre-edgesep` | 20 | 边水平间距 |

### 选择指南

- **层次化/树形/流程图** → `elk` 或 `--layout elk`
- **自由拓扑/网状/任意连接** → `dagre` 或 `--layout dagre`

---

## 二、所有 Shape 类型

```d2
# 基础形状
rect: "矩形" {shape: rectangle}        # 默认，可省略
sq: "正方形" {shape: square}           # 1:1 宽高比
oval: "椭圆" {shape: oval}             # 开始/结束
diamond: "菱形" {shape: diamond}       # 条件判断
parallelogram: "平行四边形" {shape: parallelogram}  # 数据/输入输出
hexagon: "六边形" {shape: hexagon}     # 核心模块
circle: "圆形" {shape: circle}         # 神经网络节点
step: "步骤" {shape: step}             # 操作步骤

# 文档/存储类
cylinder: "圆柱" {shape: cylinder}     # 数据库/存储
queue: "队列" {shape: queue}           # 消息队列
page: "页面" {shape: page}             # 文档
document: "文档" {shape: document}     # 文件
package: "包" {shape: package}         # 模块/库
stored_data: "存储" {shape: stored_data}  # 数据存储
callout: "标注" {shape: callout}       # 气泡标注
cloud: "云" {shape: cloud}             # 云服务

# 特殊形状
person: "人" {shape: person}           # 角色/Actor
class: "类" {shape: class}             # UML 类（见下方）
sql_table: "表" {shape: sql_table}     # 数据库表（见下方）
code: "代码" {shape: code}             # 代码块
text: "文本" {shape: text}             # 纯文本/标题（无边框）
image: "图片" {shape: image}           # 图标/图片
```

---

## 三、UML 类图 (shape: class)

```d2
ClassName: 中文标签 {
  shape: class
  style.fill: "#FFFFFF"
  style.stroke: "#333333"
  style.font-size: 13

  # 字段：可见性前缀 (- = private, + = public, # = protected)
  -id: int
  -name: string
  +getName(): string
  +setName(name: string): void

  # 用引号包裹保留关键字
  "type": string
}
```

---

## 四、SQL 表图 (shape: sql_table)

```d2
users: 用户表 {
  shape: sql_table
  style.fill: "#FFFFFF"
  style.stroke: "#333333"

  id: int {constraint: primary_key}
  name: varchar(100) {constraint: unique}
  email: varchar(255)
  department_id: int {constraint: foreign_key}
  created_at: timestamp
}
```

---

## 五、Grid 网格表格

```d2
table: {
  grid-rows: 5          # 行数
  grid-columns: 4       # 列数
  grid-gap: 0           # 0 = 单元格紧密拼接

  # 逐行填充：row1_col1, row1_col2, ..., row2_col1, ...
  h1: "列1" {style.fill: "#D9D9D9"; style.stroke: "#333333"; style.font-size: 12; style.bold: true}
  h2: "列2" {style.fill: "#D9D9D9"; style.stroke: "#333333"; style.font-size: 12; style.bold: true}
  h3: "列3" {style.fill: "#D9D9D9"; style.stroke: "#333333"; style.font-size: 12; style.bold: true}
  h4: "列4" {style.fill: "#D9D9D9"; style.stroke: "#333333"; style.font-size: 12; style.bold: true}

  r1c1: "数据" {style.fill: "#FFFFFF"; style.stroke: "#333333"; style.font-size: 13}
  r1c2: "数据" {style.fill: "#FFFFFF"; style.stroke: "#333333"; style.font-size: 13}
  # ...填满 rows × columns 个格子
}
```

---

## 六、连接线 / 边 (Edges)

### 连接方向

```d2
a -> b: "单向"
a <- b: "反向"
a <-> b: "双向"
a -- b: "无方向连线"
```

### ERD 风格的鱼尾纹连接

```d2
a -> b: "一对一" {
  source-arrowhead: "{shape: cf-one-required}"
  target-arrowhead: "{shape: cf-one-required}"
}
a -> b: "一对多" {
  source-arrowhead: "{shape: cf-one-required}"
  target-arrowhead: "{shape: cf-many-required}"
}
```

### 连接线样式

```d2
a -> b: {
  style.stroke: "#333333"         # 线条颜色
  style.stroke-dash: 4            # 虚线间距
  style.stroke-width: 2           # 线条粗细
  style.animated: true            # 流动动画（SVG）
  style.opacity: 0.5              # 透明度
  style.font-size: 12             # 标注字号
  style.font-color: "#666666"     # 标注颜色
}
```

### 连接串联（Chaining）

```d2
a -> b -> c -> d: 流程             # 链式连接
a -> b <- c: 汇聚                  # 多源汇聚
a -> b -> c -> a: 循环             # 允许循环
```

### 连接引用（多条同向连线分别样式）

```d2
x -> y: "第一条"
x -> y: "第二条"
(x -> y)[0].style.stroke: "#333333"
(x -> y)[1].style.stroke: "#999999"
```

### 自引用连接

```d2
node -> node: 自循环               # 指向自身
```

### 箭头形状

可用值：`triangle`, `arrow`, `diamond`, `circle`, `box`, `cf-one`, `cf-many`, `cross`

```d2
a -> b {
  source-arrowhead: {shape: diamond}
  target-arrowhead: {shape: arrow; style.filled: true}
}
```

### 连接上的图标

```d2
deploy -> backup: { icon: https://...svg }
```

---

## 七、容器与分组

```d2
group: "容器标题" {
  style.fill: "#FAFAFA"
  style.stroke: "#333333"
  style.font-size: 14
  style.stroke-dash: 3            # 虚线容器

  child1: 子节点1
  child2: 子节点2
  child1 -> child2
}

# 容器间的连接
group1.child1 -> group2.child1: 跨容器连接

# 引用父级容器（_ 前缀）
christmas: {
  presents
}
birthdays: {
  presents
  _.christmas.presents -> presents: regift
  _.christmas.style.fill: "#E8F5E9"
}
```

### 导入复用（Spread Import）

```d2
# 引入另一个 .d2 文件的内容
my_node: { ...@shared-styles.d2 }

# 在模板中使用
template: {
  ...@base-template.d2
  custom_field: "自定义内容"
}
```

### 根级样式（整个图的背景/边框）

```d2
style: {
  fill: "#FFFFFF"
  stroke: "#000000"
  stroke-width: 1
}
```

---

## 八、文本与排版

### Markdown 文本块

```d2
desc: |md
  ## 标题
  - 列表项 1
  - 列表项 2
  **粗体** *斜体* `代码`
| {shape: text; style.font-size: 13}
```

### LaTeX 公式

```d2
formula: |latex
  E = mc^2
  \sum_{i=1}^{n} x_i = \frac{n(n+1)}{2}
|
```

### 代码块

```d2
snippet: |go
  func main() {
    fmt.Println("hello")
  }
|

# 或使用 code shape
snippet: |python
  def factorial(n):
    return 1 if n <= 1 else n * factorial(n-1)
| {shape: code}
```

### 字体样式

```d2
node: "文字" {
  style.bold: true                # 粗体
  style.italic: true              # 斜体
  style.underline: true           # 下划线
  style.font: mono                # 等宽字体
  style.text-transform: uppercase # 全大写
}
```

---

## 九、位置控制

### near 定位（将节点吸附到指定位置）

```d2
title: "标题" {near: top-center}
legend: "图例" {near: bottom-left}
note: "注解" {near: bottom-right}
```

有效常量：`top-left`, `top-center`, `top-right`, `center-left`, `center-right`, `bottom-left`, `bottom-center`, `bottom-right`

**near 前缀**：

```d2
label.near: outside-top-center        # 容器标签放在外部上方
label.near: outside-bottom-center     # 容器标签放在外部下方
icon.near: outside-top-right          # 图标放外部右上
tooltip.near: border-top-center       # tooltip 放边框上
```

### 尺寸控制

```d2
node: "文字" {
  width: 300          # 固定宽度（像素）
  height: 200         # 固定高度（像素）
}
```

### 方向

```d2
direction: right      # 水平布局（左→右）
direction: down       # 垂直布局（上→下）
```

### 渐变配色

```d2
gradient: "渐变填充" {
  style.fill: "linear-gradient(#E3F2FD, #1565C0)"
  style.font-color: "linear-gradient(#333333, #999999)"
}
```

---

## 十、视觉效果

```d2
fancy: "效果演示" {
  style.fill: "#E3F2FD"
  style.stroke: "#1565C0"

  style.border-radius: 10        # 圆角（像素）
  style.opacity: 0.7             # 透明度（0-1）
  style.shadow: true             # 阴影
  style.3d: true                 # 3D 效果
  style.double-border: true      # 双线边框
  style.multiple: true           # 堆叠/重复效果
  style.fill-pattern: dots       # 填充图案: dots | lines | grain | paper
  style.stroke-width: 3          # 边框粗细
  style.font-color: "#C62828"    # 字体颜色
}
```

---

## 十一、多层看板 (Layers / Scenarios / Steps)

D2 支持在一个 .d2 文件中定义多张图，渲染为多个 SVG 文件。

```d2
layers: {
  overview: {
    title: "系统概览" {near: top-center}
    api: API网关
    svc: 微服务
    db: 数据库
    api -> svc -> db
  }
  detail: {
    title: "微服务详情" {near: top-center}
    svc: 微服务 {
      auth: 认证服务
      biz: 业务服务
      report: 报表服务
      auth -> biz -> report
    }
  }
}
```

### 看板间导航（SVG 交互）

```d2
box: "点击查看详情" {
  link: layers.detail      # 点击跳转到 detail 层
}
```

### 渲染特定看板

```bash
# 渲染根看板
d2 --target='' input.d2

# 渲染特定看板及其子层
d2 --target='layers.overview.*' input.d2
```

### tooltip（悬停提示）

```d2
node: "悬停查看说明" {
  tooltip: "这里会显示详细的说明文字"
}
```

### Layers vs Scenarios vs Steps 区别

| 关键词 | 继承关系 | 适用场景 |
|--------|----------|---------|
| `layers` | 不继承根层 | 独立看板（概览→详情→更多） |
| `scenarios` | 继承根层样式 | 同一图的多种状态（正常→故障→高负载） |
| `steps` | 继承上一步 | 顺序流程（第1步→第2步→第3步） |

```d2
# Scenarios 示例：同一架构图的不同状态
scenarios: {
  normal: {
    title.label: 正常运行状态
    server.style.fill: "#E8F5E9"
  }
  failure: {
    title.label: 故障降级状态
    server.style.fill: "#FFCDD2"
    (api -> db)[0].style.stroke: red
  }
}
```

---

## 十二、序列图 (Sequence Diagrams)

### 基本用法

```d2
shape: sequence_diagram

# 参与者从左到右排序
alice; bob; carol; dave

alice -> bob: 请求数据
bob -> carol: 查询数据库
carol -> bob: 返回结果
bob -> alice: 响应数据
```

### 自消息

```d2
shape: sequence_diagram
father -> father: 内心思考
```

### 生命线/激活框（Spans）

```d2
shape: sequence_diagram
alice.t1 -> bob
alice.t2 -> bob.a           # .a = 激活框
alice.t2.a -> bob.a
alice.t2.a <- bob.a
alice.t2 <- bob.a
```

### 分组（Fragments）

```d2
shape: sequence_diagram
loop: {
  alice -> bob: 轮询消息
  bob -> alice: 确认收到
}
```

### 注释（Notes）

```d2
shape: sequence_diagram
alice -> bob: 你好
bob."注意到Alice今天很开心"
bob -> alice: 你也好
```

### 添加 Actor Shape

```d2
shape: sequence_diagram
alice: {shape: person}
bob: {shape: person}
alice -> bob: 对话
```

### 样式

```d2
shape: sequence_diagram
# 虚线消息
alice -> bob: 异步消息 {style.stroke-dash: 5}
# Actor 样式
alice.style: {stroke: "#333333"; stroke-width: 2}
```

---

## 十三、变量与复用

### vars 变量

```d2
vars: {
  primary-color: "#1565C0"
  light-bg: "#E3F2FD"
  small-font: 12
}

node: "使用变量" {
  style.fill: ${light-bg}
  style.stroke: ${primary-color}
  style.font-size: ${small-font}
}
```

### classes 样式类（复用一组样式）

```d2
classes: {
  primary: {
    style.fill: "#E3F2FD"
    style.stroke: "#1565C0"
    style.font-size: 14
  }
  highlight: {
    style.fill: "#FFF3E0"
    style.stroke: "#E65100"
    style.bold: true
    style.border-radius: 8
  }
}

a: "普通节点" {class: primary}
b: "高亮节点" {class: highlight}
```

### 通配符样式（批量应用）

```d2
container: {
  # 所有子节点统一样式
  *.style.fill: "#FAFAFA"
  *.style.stroke: "#333333"
  *.style.font-size: 13

  # 按模式匹配
  step*.style.fill: "#E8F5E9"     # step1, step2, step3...
  error*.style.fill: "#FFCDD2"    # error1, error2...
}
```

---

## 十四、CLI 功能

### 格式检查与格式化

```bash
d2 validate input.d2    # 检查语法
d2 fmt input.d2         # 自动格式化代码
```

### 在线预览

```bash
d2 play input.d2        # 在浏览器中打开 D2 Playground
```

### 实时预览（热更新）

```bash
d2 --watch input.d2 output.svg    # 修改 .d2 自动重新渲染
```

### 手绘风格

```bash
d2 --sketch input.d2 output.svg   # 手绘草图效果
```

### SVG 动画

```bash
# 多看板轮播动画（SVG only）
d2 --animate-interval 3000 input.d2 output.svg
```

### 输出格式

| 格式 | 扩展名 | 说明 |
|------|--------|------|
| SVG | `.svg` | 矢量图（推荐，可嵌入 LaTeX） |
| PNG | `.png` | 位图预览 |
| PDF | `.pdf` | 打印/投稿 |
| PPTX | `.pptx` | PowerPoint |
| GIF | `.gif` | 动画 |
| ASCII | `.txt` | 终端预览 |

### 管道模式（stdin/stdout）

```bash
echo 'a -> b' | d2 - output.svg
d2 input.d2 --stdout-format png - > output.png
```

### 其他 CLI 标志

| 标志 | 用途 |
|------|------|
| `--pad N` | 画布外边距（像素） |
| `--center` | 在 viewbox 中居中 |
| `--scale 0.5` | 缩放输出（-1=适配屏幕） |
| `--no-xml-tag` | SVG 去掉 XML 标签（HTML 嵌入用） |
| `--salt "xxx"` | 唯一 ID 后缀（同一页多个 SVG） |
| `--omit-version` | 去掉 D2 版本水印 |
| `--force-appendix` | SVG 也生成 tooltip/link 附录 |
| `--bundle false` | SVG 不内联资源 |
| `--timeout N` | 超时秒数（大图需要调大） |

---

## 十五、d2-render 自定义

### 默认参数（已预设）

```
字体: SimSun-Regular.ttf (宋体)
布局: elk
内边距: 30px
容器内边距: 30px
节点间距: 35px
主题: 0 (手动控制颜色)
```

### 环境变量覆盖

```bash
D2_FONT_DIR=/my/fonts d2-render input.d2       # 自定义字体目录
D2_LAYOUT=dagre d2-render input.d2             # 切换布局
D2_PAD=50 d2-render input.d2                   # 画布边距
D2_ELK_PADDING="[top=40,left=40,bottom=40,right=40]" d2-render input.d2
D2_ELK_NODE_GAP=50 d2-render input.d2          # 节点间距
D2_THEME=1 d2-render input.d2                  # 使用主题（不用手动配色）
```

### 完全自定义渲染（绕过 d2-render）

如需精细控制，直接用 D2 CLI：

```bash
d2 input.d2 output.svg \
  --font-regular /path/to/font.ttf \
  --font-bold /path/to/font-bold.ttf \
  --font-italic /path/to/font-italic.ttf \
  --pad 40 \
  --layout elk \
  --theme 0 \
  --elk-padding "[top=30,left=30,bottom=30,right=30]" \
  --elk-nodeNodeBetweenLayers 40 \
  --sketch \
  --center \
  --scale 1
```

---

## 十六、7 种示例速查

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

---

## 十七、布局选择

- **严格分层/树形** → ELK
- **网状/自由连接** → Dagre
- **表格/网格数据** → 不需要布局引擎（grid 自身管理位置）

## 常见错误

- ❌ .ttc 字体文件（D2 只支持 .ttf）
- ❌ `style.font-style: italic` → 正确是 `style.italic: true`
- ❌ `style.font-weight: bold` → 正确是 `style.bold: true`
- ❌ elk-* 配置写在 .d2 的 d2-config 中 → 必须通过 CLI 传递
- ❌ `near: center` → 正确是 `near: center-left` 或 `near: center-right`
- ❌ 4个以上 ELK 容器同时用 `near: center-left`（PNG 渲染可能出错）
- ❌ `left`/`right` 作为节点 ID → 它们是 D2 保留关键字

## 文字重叠修复策略（按优先级）

1. **增大 ELK 层间距**：`D2_ELK_NODE_GAP=55`（默认35），严重时用 70+
2. **增大 Dagre 间距**：`--dagre-nodesep 80 --dagre-edgesep 30`（默认60/20）
3. **SQL Table 限宽**：加 `width: 200` 防字段名过长溢出
4. **缩短字段名**：`password_hash` → `pass`，`decimal(10,2)` → `decimal`
5. **换用 dagre 布局**：SQL ERD / 网状图用 `--layout dagre`
6. **增大画布边距**：`D2_PAD=50`（默认30）
7. **减少节点数**：拆分为多张图
8. **容器内用 grid 垂直排列**：`grid-rows: N; grid-columns: 1` + `width: N`
