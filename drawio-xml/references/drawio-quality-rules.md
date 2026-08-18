# draw.io 高质量图表生成规则（完整版）

> 来源：next-ai-draw-io 主应用 `lib/system-prompts.ts`（410 行质量规则）实测提炼。
> 适用：drawio-xml skill 模式 A（直接生成）与模式 B（MCP）的所有 XML 生成。

## 一、XML 结构硬规则

1. 完整包装：`<mxfile host="app.diagrams.net"><diagram id="..." name="..."><mxGraphModel><root>...`
2. 根哨兵单元必须有：`<mxCell id="0"/>` 和 `<mxCell id="1" parent="0"/>`
3. 所有 mxCell **必须平级**（siblings），禁止嵌套 mxCell；容器关系用 parent 属性
4. id 唯一，从 "2" 开始；顶层形状 `parent="1"`，容器内元素 `parent="<容器id>"`
5. **禁止 XML 注释**（`<!-- -->`）——draw.io 剥离注释会破坏后续编辑匹配
6. 特殊字符转义：`&lt;`（<）`&gt;`（>）`&amp;`（&）`&quot;`（"）
7. 边必须有 `source`/`target` 引用已存在的 cell id，不得有孤立边

## 二、布局约束（单页视口）

- 所有元素 x ∈ [0, 800]，y ∈ [0, 600]（推荐紧凑范围 x ∈ [40, 760]，y ∈ [40, 560]）
- 容器最大宽 700px、高 550px
- 起始边距 x=40, y=40；元素间距 150-200px（给连线留通道）
- 大图用垂直堆叠或网格布局，禁止横向无限铺开

## 三、边路由 7 规则（质量核心，防连线交叉）

1. **多边不共路**：同一对节点多条边必须不同 exit/entry 点（如 exitY=0.3 与 exitY=0.7，不得都用 0.5）
2. **双向边对侧进出**：A→B 从右出（exitX=1）左进（entryX=0）；B→A 从左出（exitX=0）右进（entryX=1）
3. **必须显式写 exitX/exitY/entryX/entryY**（4 属性缺一不可）
4. **绕障**：连线路径上有中间形状时，必须用 waypoint 绕行（20-30px 净空），禁止穿过任何形状包围盒；对角线连接沿图外围走
5. **先规划再生成**：按流向往分区（列/行）；逐条边预演"源和目标之间有什么形状"
6. **多 waypoint**：一次绕障不够用 2-3 个，形成 L/U 形正交路径；每个方向变化一个 waypoint
7. **自然连接点**：禁止角落连接（entryX=1,entryY=1 等）；上下流出口底（exitY=1）进口顶（entryY=0）；左右流出右（exitX=1）进左（entryX=0）

生成前自检 4 问：
- 有无边穿过非源/目标形状？→ 加 waypoint
- 有无两条边同路径？→ 调整 exit/entry
- 有无角落连接点？→ 改用边中心
- 能否重排减少交叉？→ 调整布局

## 四、样式规范

- 形状：`rounded=1`（圆角）、`fillColor=#hex`、`strokeColor=#hex`、`whiteSpace=wrap;html=1`
- 边：`edgeStyle=orthogonalEdgeStyle`（正交）、`endArrow=classic/block/open/none`、`curved=1`、`startArrow=none/classic`
- 文字：`fontSize=14`、`fontStyle=1`（粗体）、`align=center/left/right`
- 容器（含子形状）必须 `fillColor=none` 透明，否则盖住子元素
- 学术色板：
  - 实体/主体 `#dae8fc` 填充 / `#6c8ebf` 描边（蓝）
  - 流程/处理 `#d5e8d4` / `#82b366`（绿）
  - 准备/资源 `#ffe6cc` / `#d79b00`（橙）
  - 异常/回退 `#f8cecc` / `#b85450`（红，可加 dashed=1）
  - 外部系统 `#e1d5e7` / `#9673a6`（紫）

## 五、学术图表专项（draw.io 内建样式，无需形状库）

| 图表类型 | 关键样式 | 生成要点 |
|---|---|---|
| **ER 图** | `swimlane`（实体表）+ `text`（字段行）+ `endArrow=ERone/ERmany/ERmandatory` | 实体表 swimlane 表头 startSize=26；字段用 text 子单元 parent=表；关系 1:1 用 ERone-ERone，1:N 用 ERone-ERmany |
| **UML 类图** | `swimlane`（类框）| 类框三段：标题行 + 属性段 + 方法段；属性/方法用 text 子单元 |
| **时序图** | 参与者矩形 + 垂直生命线（细矩形）+ 消息水平边（endArrow=classic） | 生命线从参与者底部下垂；消息自上而下时间序 |
| **用例图** | `ellipse`（用例）+ `shape=umlActor`（参与者）| 参与者 stickman 用 `shape=umlActor`；用例椭圆 `ellipse`；关系线无箭头或 include/extends 标注 |
| **流程图** | `rounded=1`（处理）+ `rhombus`（判断）+ `ellipse`（起止）| 判断菱形输出"是/否"分支标注；起止椭圆区分开始/结束 |
| **泳道图** | `swimlane`（泳道容器）+ 内部节点 | 泳道横向排列（如 Frontend/Backend/DB），节点 parent=泳道，跨泳道边用正交 |

## 六、云架构图（形状库强项，31 个库）

- 云图标**必须查库，禁止猜语法**：
  - AWS：`style="shape=mxgraph.aws4.<name>;"`（1031 个，如 s3, ec2, lambda, rds, dynamodb）
  - Azure：`img/lib/azure2/`（608 个）；GCP：`shape=mxgraph.gcp2.<name>`（297 个）
  - K8s：`mxgraph.kubernetes`（40）；Cisco：`mxgraph.cisco19`（232）；BPMN：`mxgraph.bpmn`（40）
  - 完整列表见仓库 `docs/shape-libraries/*.md`
- 云图标典型尺寸 50x50；AWS 区域容器用透明大矩形 + 区域名
- 已知库名：aws4/azure2/gcp2/alibaba_cloud/openstack/digitalocean/salesforce/cisco19/network/arista/kubernetes/vvd/rack/bpmn/eip/lean_mapping/flowchart/basic/arrows2/infographic/sitemap/android/atlassian/cabinets/citrix/electrical/floorplan/fluidpower/mscae/pid/sap/webicons/material_design

## 七、质量自检清单（生成后必查）

1. XML 可解析、id 唯一、无注释
2. 全部元素在视口内（x+w ≤ 850, y+h ≤ 1100）
3. 无任何两个形状重叠
4. 所有边 source/target 有效、无孤立边
5. 边无穿形状、无共路、无角落连接
6. 文字完整无截断（value 无残缺转义）
