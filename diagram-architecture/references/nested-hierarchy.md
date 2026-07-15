# 多层嵌套布局模板

## 适用场景
AI 平台、云原生系统、复杂多子系统架构、需要表达从属关系和跨子系统反馈的场景。

## 核心布局技术
- `newrank=true` 全局分层，忽略 cluster 边界（跨集群节点能对齐到同一 rank）
- 三层嵌套 `cluster`：大平台 → 子系统 → 子模块
- 横向跨集群连接用 `constraint=false` + `minlen=2`
- 差异化虚线区分不同类型跨区路径

## 完整模板

```dot
digraph NestedSystem {
  rankdir=TB
  ranksep=0.8
  nodesep=0.4
  newrank=true
  bgcolor=white
  fontname="Noto Sans CJK SC"
  fontcolor="#1F2937"
  node [fontname="Noto Sans CJK SC", shape=box, style="rounded,filled", penwidth=0.8, fontsize=10]
  edge [fontname="Noto Sans CJK SC", color="#6B7280", fontcolor="#6B7280", penwidth=0.7, arrowsize=0.7, fontsize=8]
  labelloc="t"
  fontsize=14
  fontcolor="#1F2937"

  // ====== 第一层：大平台 ======
  subgraph cluster_platform {
    label="平台名称"
    style="rounded,filled"
    fillcolor="#F0F9FF"
    color="#0EA5E9"
    fontcolor="#0C4A6E"
    penwidth=1.5
    fontsize=13

    // ====== 第二层左：子系统A ======
    subgraph cluster_subsys_a {
      label="子系统A（如：训练集群）"
      style="rounded,filled"
      fillcolor="#DBEAFE"
      color="#3B82F6"
      fontcolor="#1E3A8A"
      penwidth=1.0
      fontsize=11

      // 第三层：子模块
      subgraph cluster_mod_a1 {
        label="模块A1"
        style="rounded,dashed"
        fillcolor="#EFF6FF"
        color="#93C5FD"
        fontcolor="#1E40AF"
        penwidth=0.6
        fontsize=9

        a1_1 [label="组件1", fillcolor=white, color="#3B82F6"]
        a1_2 [label="组件2", fillcolor=white, color="#3B82F6"]
      }

      subgraph cluster_mod_a2 {
        label="模块A2"
        style="rounded,dashed"
        fillcolor="#EFF6FF"
        color="#93C5FD"
        fontcolor="#1E40AF"
        penwidth=0.6
        fontsize=9

        a2_1 [label="组件3", fillcolor=white, color="#3B82F6"]
        a2_2 [label="组件4", fillcolor=white, color="#3B82F6"]
      }

      a1_1 -> a1_2 -> a2_1 [weight=5]
      a2_1 -> a2_2
      a2_2 -> a1_1 [label=" 反馈", style=dashed, constraint=false, color="#EF4444", fontcolor="#EF4444"]
    }

    // ====== 第二层右：子系统B ======
    subgraph cluster_subsys_b {
      label="子系统B（如：推理集群）"
      style="rounded,filled"
      fillcolor="#D1FAE5"
      color="#10B981"
      fontcolor="#064E3B"
      penwidth=1.0
      fontsize=11

      subgraph cluster_mod_b1 {
        label="模块B1"
        style="rounded,dashed"
        fillcolor="#F0FDF4"
        color="#6EE7B7"
        fontcolor="#065F46"
        penwidth=0.6
        fontsize=9

        b1_1 [label="组件5", fillcolor=white, color="#10B981"]
        b1_2 [label="组件6", fillcolor=white, color="#10B981"]
      }

      subgraph cluster_mod_b2 {
        label="模块B2"
        style="rounded,dashed"
        fillcolor="#F0FDF4"
        color="#6EE7B7"
        fontcolor="#065F46"
        penwidth=0.6
        fontsize=9

        b2_1 [label="组件7", fillcolor=white, color="#10B981"]
        b2_2 [label="组件8", fillcolor=white, color="#10B981"]
      }

      b1_1 -> b1_2 -> b2_1 [weight=5]
      b2_1 -> b2_2
    }

    // ====== 跨子系统连接 ======
    a2_2 -> b1_1 [label=" 交付", style=bold, color="#8B5CF6", fontcolor="#4C1D95", constraint=false, minlen=2]

    // ====== 底部：监控层（跨两个子系统）======
    subgraph cluster_monitoring {
      label="监控层"
      style="rounded,filled"
      fillcolor="#FEF3C7"
      color="#F59E0B"
      fontcolor="#78350F"
      penwidth=1.0
      fontsize=11

      metrics [label="指标采集", fillcolor="#FFFBEB", color="#F59E0B"]
      dashboard [label="监控面板", fillcolor="#FFFBEB", color="#F59E0B"]
      metrics -> dashboard
    }

    // 监控连接（汇聚模式：每侧只出1条线到监控层，避免交叉）
    b2_2 -> metrics [style=dashed, constraint=false, color="#D97706", label=" 监控"]
    a2_2 -> metrics [style=dashed, constraint=false, color="#D97706"]
  }

  // ====== 外部入口 ======
  client [label="外部请求", fillcolor="#FEE2E2", color="#EF4444", fontcolor="#991B1B", penwidth=1.0]
  client -> b1_1 [label=" API调用"]

  // ====== 全局反馈 ======
  b2_2 -> a1_1 [label=" 在线学习", style=dashed, color="#9CA3AF", constraint=false, fontcolor="#9CA3AF"]
}
```

## 自定义要点

1. **替换层级名称**：`cluster_platform` → 平台名，`cluster_subsys_a/b` → 子系统名，`cluster_mod_x` → 模块名
2. **嵌套深度**：最多三层（平台→子系统→模块），更多层 Graphviz 性能下降
3. **newrank=true**：必须在顶层设置，否则跨集群的 rank=same 不生效
4. **跨区连接防交叉（重要！）**：跨集群的虚线连接容易交叉混乱。遵循以下规则：
   - **所有跨集群边必须用 `constraint=false`**，否则会拉乱分层
   - **跨集群边数量 ≤ 3 条**，超过的用"汇聚节点"模式：多个源 → 1个中间节点 → 多个目标
   - **跨集群边用不同颜色区分类型**：交付（紫粗线）、监控（黄虚线）、反馈（灰虚线）
   - **`minlen=2`** 让跨集群边有足够空间走线
   - 示例（汇聚模式）：
     ```dot
     // 不好的做法：4条跨集群直连，必然交叉
     a1 -> metrics; a2 -> metrics; b1 -> metrics; b2 -> metrics
     
     // 好的做法：先汇聚再分发
     a1 -> hub_a [style=invis]  // 子系统A内部汇聚
     a2 -> hub_a [style=invis]
     hub_a -> metrics [label=" 监控", style=dashed, constraint=false]
     b1 -> hub_b [style=invis]  // 子系统B内部汇聚
     b2 -> hub_b [style=invis]
     hub_b -> metrics [label=" 监控", style=dashed, constraint=false]
     ```
5. **论文尺寸**：嵌套图较复杂，建议 `size="6.8,5!"`（跨双栏）或拆分为多张子图
6. **如果跨集群连接超过 4 条**：考虑拆分为两张图（训练流程图 + 推理流程图），用文字说明关联
