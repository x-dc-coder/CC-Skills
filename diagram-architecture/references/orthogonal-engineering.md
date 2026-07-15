# 正交工程图布局模板

## 适用场景
大数据平台、微服务架构、基础设施拓扑、任何需要严谨工程图风格的架构。

## 核心布局技术
- `splines=ortho` 所有连线 90 度正交（无斜线）
- 两层嵌套 `cluster` 做系统边界 + 子系统分区
- `rank=same` 左右两列对齐
- `shape=cylinder` 表示存储组件

## 完整模板

```dot
digraph OrthogonalSystem {
  rankdir=TB
  ranksep=0.7
  nodesep=0.4
  splines=ortho
  bgcolor="#FAFAFA"
  fontname="Noto Sans CJK SC"
  fontcolor="#1F2937"
  node [fontname="Noto Sans CJK SC", shape=box, style="filled", penwidth=1.0, fontsize=10]
  edge [fontname="Noto Sans CJK SC", color="#374151", fontcolor="#6B7280", penwidth=0.8, arrowsize=0.6, fontsize=8]
  labelloc="t"
  fontsize=14
  fontcolor="#1F2937"

  // ====== 外层：系统边界 ======
  subgraph cluster_system {
    label="系统名称"
    style="rounded,filled"
    fillcolor="#F3F4F6"
    color="#374151"
    fontcolor="#1F2937"
    penwidth=1.5
    fontsize=13

    // ====== 左半区 ======
    subgraph cluster_left {
      label="左区（如：离线处理）"
      style="rounded,filled"
      fillcolor="#DBEAFE"
      color="#3B82F6"
      fontcolor="#1E3A8A"
      penwidth=1.0
      fontsize=11

      l_store [label="存储", shape=cylinder, fillcolor="#EFF6FF", color="#3B82F6"]
      l_compute [label="计算", fillcolor="#EFF6FF", color="#3B82F6"]
      l_output [label="输出", shape=cylinder, fillcolor="#EFF6FF", color="#3B82F6"]
      l_sched [label="调度", fillcolor="#EFF6FF", color="#3B82F6"]

      l_store -> l_compute
      l_compute -> l_output
      l_sched -> l_compute [style=dashed, constraint=false]
    }

    // ====== 右半区 ======
    subgraph cluster_right {
      label="右区（如：实时处理）"
      style="rounded,filled"
      fillcolor="#D1FAE5"
      color="#10B981"
      fontcolor="#064E3B"
      penwidth=1.0
      fontsize=11

      r_queue [label="消息队列", fillcolor="#F0FDF4", color="#10B981"]
      r_compute [label="流计算", fillcolor="#F0FDF4", color="#10B981"]
      r_state [label="状态存储", shape=cylinder, fillcolor="#F0FDF4", color="#10B981"]
      r_alert [label="告警", fillcolor="#F0FDF4", color="#10B981"]

      r_queue -> r_compute
      r_compute -> r_state [style=dashed, constraint=false]
      r_compute -> r_alert
    }

    // ====== 底部：服务层 ======
    subgraph cluster_serving {
      label="服务层"
      style="rounded,filled"
      fillcolor="#FEF3C7"
      color="#D97706"
      fontcolor="#78350F"
      penwidth=1.0
      fontsize=11

      api [label="API网关", fillcolor="#FFFBEB", color="#D97706"]
      cache [label="查询缓存", fillcolor="#FFFBEB", color="#D97706"]
      monitor [label="监控面板", fillcolor="#FFFBEB", color="#D97706"]
    }

    // 跨区连接
    l_output -> api [label=" 同步"]
    r_compute -> cache [label=" 更新"]
    r_alert -> monitor [label=" 告警"]

    // 对齐
    { rank=same; l_store; r_queue }
    { rank=same; l_compute; r_compute }
    { rank=same; l_output; r_state }
    { rank=same; l_sched; r_alert }
  }

  // ====== 外部数据源 ======
  subgraph cluster_external {
    label="外部数据源"
    style="rounded,dashed"
    fillcolor=white
    color="#9CA3AF"
    fontcolor="#6B7280"
    penwidth=0.6
    fontsize=10

    ext_db [label="业务DB", shape=cylinder, fillcolor="#F9FAFB", color="#6B7280"]
    ext_log [label="日志流", fillcolor="#F9FAFB", color="#6B7280"]
  }

  ext_db -> l_store [label=" 导入"]
  ext_log -> r_queue [label=" 推送"]
}
```

## 自定义要点

1. **替换分区名**：`cluster_left/right` → 实际子系统名
2. **splines=ortho 限制**：正交模式不支持边标签（label），标签会被忽略。如需标签，改用 `splines=polyline` 或 `splines=true`
3. **存储组件**：用 `shape=cylinder` 表示数据库/存储
4. **嵌套层级**：最多两层 cluster 嵌套，更多层会变复杂
5. **论文尺寸**：正交图通常较宽，建议 `size="7,5!"`（跨双栏）
