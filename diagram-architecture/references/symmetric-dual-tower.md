# 对称双塔布局模板

## 适用场景
双塔推荐模型、Encoder-Decoder、对比学习、任何有两条对称并行处理路径的架构。

## 核心布局技术
- `rank=same` 强制左右塔同层对齐
- `group` 属性保持平行流走直线
- `weight=10` 加大塔内部边权重保持垂直紧凑
- `constraint=false` 让残差/反馈线不干扰主分层

## 完整模板

```dot
digraph DualTower {
  rankdir=TB
  ranksep=0.8
  nodesep=0.4
  bgcolor=white
  fontname="Noto Sans CJK SC"
  fontcolor="#1F2937"
  node [fontname="Noto Sans CJK SC", shape=box, style="rounded", fillcolor=white, color="#374151", fontcolor="#111827", penwidth=0.8, fontsize=10]
  edge [fontname="Noto Sans CJK SC", color="#6B7280", fontcolor="#6B7280", penwidth=0.6, arrowsize=0.7, fontsize=8]
  labelloc="t"
  fontsize=14
  fontcolor="#1F2937"
  newrank=true

  // ====== 共享输入层 ======
  subgraph cluster_input {
    label="输入层"
    style="rounded,dashed"
    color="#9CA3AF"
    fontcolor="#4B5563"
    penwidth=0.6
    fontsize=11
    shared_input [label="多模态输入", fillcolor="#FEF3C7", color="#D97706", fontcolor="#78350F"]
  }

  // ====== 左塔 ======
  subgraph cluster_left {
    label="左塔（如：用户塔）"
    style="rounded,dashed"
    color="#3B82F6"
    fontcolor="#1E3A8A"
    penwidth=0.8
    fontsize=11
    l1 [label="嵌入层", fillcolor="#EFF6FF", color="#3B82F6", fontcolor="#1E3A8A", group=g_left]
    l2 [label="注意力层", fillcolor="#EFF6FF", color="#3B82F6", fontcolor="#1E3A8A", group=g_left]
    l3 [label="池化输出", fillcolor="#EFF6FF", color="#3B82F6", fontcolor="#1E3A8A", group=g_left]
  }

  // ====== 右塔 ======
  subgraph cluster_right {
    label="右塔（如：物品塔）"
    style="rounded,dashed"
    color="#10B981"
    fontcolor="#064E3B"
    penwidth=0.8
    fontsize=11
    r1 [label="嵌入层", fillcolor="#F0FDF4", color="#10B981", fontcolor="#064E3B", group=g_right]
    r2 [label="注意力层", fillcolor="#F0FDF4", color="#10B981", fontcolor="#064E3B", group=g_right]
    r3 [label="池化输出", fillcolor="#F0FDF4", color="#10B981", fontcolor="#064E3B", group=g_right]
  }

  // ====== 交叉/融合层 ======
  subgraph cluster_fusion {
    label="融合层"
    style="rounded,dashed"
    color="#8B5CF6"
    fontcolor="#4C1D95"
    penwidth=0.8
    fontsize=11
    cross [label="交叉注意力", fillcolor="#F5F3FF", color="#8B5CF6", fontcolor="#4C1D95"]
    fusion [label="特征融合", fillcolor="#F5F3FF", color="#8B5CF6", fontcolor="#4C1D95"]
  }

  // ====== 输出层 ======
  output [label="预测输出", fillcolor="#FEE2E2", color="#B91C1C", fontcolor="#991B1B", penwidth=1.0]

  // ====== 对称对齐 ======
  { rank=same; l1; r1 }
  { rank=same; l2; r2 }
  { rank=same; l3; r3 }

  // ====== 连接 ======
  shared_input -> l1 [label=" 左流"]
  shared_input -> r1 [label=" 右流"]
  l1 -> l2 [weight=10]
  l2 -> l3 [weight=10]
  r1 -> r2 [weight=10]
  r2 -> r3 [weight=10]
  l3 -> cross [label=" 左向量"]
  r3 -> cross [label=" 右向量"]
  cross -> fusion
  fusion -> output [penwidth=1.0, color="#B91C1C"]

  // 残差连接（不干扰分层）
  // l2 -> l3 [label=" 残差", style=dashed, constraint=false, color="#9CA3AF"]
  // r2 -> r3 [label=" 残差", style=dashed, constraint=false, color="#9CA3AF"]
}
```

## 自定义要点

1. **替换节点名**：`l1/l2/l3` → 用户实际的模块名（如"用户特征嵌入"/"自注意力"/"池化"）
2. **替换塔标题**：`cluster_left` 的 `label` 改为实际名称（如"编码器"/"解码器"）
3. **增减层数**：如果塔有 4 层，加 `l4` 并对应 `{ rank=same; l4; r4 }`
4. **残差连接**：取消注释残差线，或删除
5. **论文尺寸**：在 `graph []` 中加 `size="3.5,4!"`（单栏）或 `size="7,4!"`（跨栏）
