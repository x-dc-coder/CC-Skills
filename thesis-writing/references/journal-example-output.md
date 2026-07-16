# 示例章节输出：期刊论文 Method 章节（基于 TGA: Lei-Hao-Wu 2025 改编）

本文件作为期刊论文模式（Mode B）的 few-shot 参考，展示 Method 章节的标准输出格式。改编自 *Speeding up Local Optimization in Vehicle Routing with Tensor-based GPU Acceleration* (Lei, Hao, Wu 2025)，演示：方法总览图占位符、目标函数公式、硬件对比表、贡献点列表、密集引用。

---

# Abstract

Local search is central to many high-performing metaheuristic algorithms for the vehicle routing problem (VRP) and its variants [1][2]. However, neighborhood exploration is computationally expensive, especially for large or highly constrained instances. This paper addressed this challenge by proposing an original Tensor-based GPU Acceleration (TGA) framework. TGA accelerated move evaluation for common local search operators through an attribute-based solution tensor representation and fully tensorized operator implementations that exploited GPU parallelism. Extensive experiments on three routing problems demonstrated speedups of 5.3× to 47.8× over traditional CPU-based implementations. A detailed analysis further revealed performance characteristics, potential bottlenecks, and directions for future improvement.

Keywords: tensor-based GPU acceleration; local search; vehicle routing; combinatorial optimization.

# 1 Introduction

The Vehicle Routing Problem (VRP) [1,2] is one of the most well-known combinatorial optimization problems and is computationally challenging due to its NP-hard nature [3]. Since its introduction, the VRP and its variants have been extensively studied using exact, approximate, heuristic, and metaheuristic approaches. Heuristics and metaheuristics—including simulated annealing [7,8], tabu search [9,10], genetic algorithms [11,12], and memetic algorithms [13,14]—are widely used for larger instances to obtain good suboptimal solutions efficiently.

With recent advances in computer hardware, GPUs have become promising for accelerating combinatorial optimization. Several studies explored redesigning classical heuristics on GPU: [19] implemented hill climbing and simulated annealing, [20] surveyed GPU-based genetic algorithms, and [26,27] parallelized 2-opt and 3-opt operators for the CVRP. However, most existing methods rely on low-level CUDA implementations, which pose a high barrier to entry for operations researchers without specialized GPU expertise.

To address these gaps, we proposed a fine-grained Tensor-based GPU Acceleration (TGA) framework. The main contributions of this paper are summarized as follows:

- The TGA framework, along with two implementations, was proposed to accelerate move evaluation by tensorizing local search operators based on an attribute-based solution tensor representation, thereby fully leveraging GPU parallelism.
- TGA is highly extensible, supporting a wide range of VRP variants and integration into different local search solvers.
- Unlike CUDA-based approaches, TGA can be implemented using high-level tensor libraries such as PyTorch, substantially lowering the barrier to GPU acceleration.
- In-depth theoretical and experimental analyses provided insights into performance characteristics and potential bottlenecks.

# 2 Problem Definition

All three problems studied in this paper can be defined on a complete graph $G = (V, E)$, where the vertices $V = \{v_0, v_1, \dots, v_{N_C}\}$ represent the depot $v_0$ and the $N_C$ customers. Each customer node $v_i$ is associated with a delivery demand $d_i$ and a pickup demand $p_i$. Each node $v_i$ has a time window $[e_i, l_i]$ and a service time $s_i$. The travel distance and travel time matrices, $C = (c_{ij})$ and $T = (t_{ij})$, store the corresponding values for each edge.

The objective is to minimize the total cost, which is the weighted sum of the number of vehicles and the travel distance, as shown in Equation (2-1).

$$f(S) = \mu_1 \cdot M + \mu_2 \cdot D(S) \tag{2-1}$$

Subject to:

$$D(S) = \sum_{i=1}^{M} \sum_{j=0}^{\mathcal{L}_i} c_{n_{i,j} n_{i,j+1}} \tag{2-2}$$

$$q_{n_{i,j}} \leq Q, \quad \forall n_{i,j} \in R_i \tag{2-3}$$

where $\mu_1$ and $\mu_2$ represent the weights assigned to vehicle dispatching and travel distance, $q_{n_{i,j}}$ is the load of the $i$-th vehicle after visiting node $n_{i,j}$, and $Q$ is the vehicle capacity.

# 3 GPU and Tensor Computation

## 3.1 GPU Architecture

Modern NVIDIA GPUs dedicate most resources to arithmetic units, enabling thousands of lightweight threads to execute concurrently. Table 3-1 summarizes three recent GPU generations relevant to this work's experiments.

**表3-1 NVIDIA GPU specifications**

| GPU | Year | Architecture | SMs | Cores/SM | Total Cores | Memory | Memory Bandwidth | FP32 TFLOPS |
|------|------|-------------|-----|----------|-------------|--------|------------------|-------------|
| V100 | 2017 | Volta | 80 | 64 | 5,120 | 16/32 GB HBM2 | ~900-1,134 GB/s | ~15.7 |
| A100 | 2020 | Ampere | 108 | 64 | 6,912 | 40/80 GB HBM2e | ~1.6-2.0 TB/s | ~19.5 |
| H100 | 2022 | Hopper | 132 | 128 | 16,896 | 80 GB HBM3 | ~3.0-3.2 TB/s | ~67 |

Table 3-1 shows consistent increases in SMs, cores, memory capacity, memory bandwidth, and floating-point throughput across the three generations. These improvements substantially boost modern GPUs' ability to handle large-scale, complex parallel workloads.

## 3.2 Tensor Computation

High-level frameworks such as PyTorch and TensorFlow provide a rich set of tensor operations—including element-wise arithmetic, slicing, reshaping, and reduction—that are automatically translated into highly optimized GPU kernels [22][23]. By abstracting away hardware-specific details, tensor computation enables researchers to concentrate on algorithmic design while still achieving high-performance execution.

# 4 Tensor-based GPU Acceleration Framework

## 4.1 Workflow of the TGA Framework

The TGA framework orchestrates computation between CPU and GPU. The overall workflow is illustrated in Figure 4-1.

> [图4-1 TGA 框架工作流总览图]
> 描述：分层架构图，从左到右展示数据流。
> 左侧（CPU 侧）："VRP 实例"（含客户节点 + 距离矩阵 + 容量约束）→
> "Local Search Controller"（决定接受/拒绝 move，更新当前解）；
> 中间双向大箭头标注 "CPU ↔ GPU 数据传输"（PyTorch tensor）；
> 右侧（GPU 侧，PyTorch 实现）四个子模块从上到下：
> "① Extraction"（解 → 属性张量）、
> "② Concatenation"（路线子序列拼接）、
> "③ Differencing"（Δ 目标值计算）、
> "④ Evaluation"（约束可行性判定）；
> 底部标注 "PyTorch 2.0+ as tensor backend (replaces CUDA)"。

As shown in Figure 4-1, the Local Search Controller on the CPU side maintains the current solution and decides which neighborhoods to explore. For each candidate move, the relevant solution segments are transferred to the GPU as tensors, where the four tensorized operators compute the move's cost delta and feasibility in parallel. The result is transferred back to the CPU, which applies the acceptance criterion.

## 4.2 Attribute-based Solution Tensor Representation

We represent the solution as an attribute tensor $\mathbf{A} \in \mathbb{R}^{M \times L_{\max} \times d}$, where $M$ is the number of routes, $L_{\max}$ is the maximum route length, and $d$ is the number of attributes (travel distance, load, time, etc.). The attribute matrix for a single route is illustrated in Figure 4-2.

> [图4-2 属性矩阵示意图]
> 描述：展示一条长度 |R|=5 的路线及其对应的上三角属性矩阵。
> 上半部分：路线表示 v0 → v3 → v1 → v4 → v2 → v0，每个节点为圆圈；
> 下半部分：5×5 上三角矩阵，单元格 a_{i,j} 记录第 i 个节点到第 j 个节点子序列的累积属性值（如距离、负载）；
> 仅上三角部分含有效值，下三角留空。

The concatenation of two subsequences $[i, j]$ and $[k, l]$ can then be computed in constant time using precomputed attribute values:

$$a_{[i,j] \oplus [k,l]} = a_{i,j} \otimes a_{k,l} \oplus \delta(a_{j,k}) \tag{4-1}$$

where $\otimes$ and $\oplus$ are attribute-specific operators and $\delta(\cdot)$ computes the cross-boundary contribution.

## 4.3 Algorithmic Sketch

Algorithm 1 presents the main loop of TGA-accelerated local search.

```
Algorithm 1: TGA-Accelerated Local Search
─────────────────────────────────────────
Input : Initial solution S, operator set O, max iterations T
Output: Improved solution S*
1  S* ← S
2  A ← ExtractAttributeTensor(S)            // GPU
3  for t = 1 to T do
4      for each operator o ∈ O do
5          Δ, feasible ← EvaluateMoves(o, A) // GPU, batched
6          (o*, m*) ← ArgBest(Δ[feasible])
7          if Δ[m*] improves f(S*) then
8              S* ← ApplyMove(S*, o*, m*)
9              A ← UpdateAttributeTensor(A, o*, m*)  // GPU, incremental
10  return S*
```

The key efficiency gain comes from line 5: rather than evaluating each candidate move sequentially on the CPU, TGA batches all moves for an operator into a single tensor operation, exploiting GPU's massive parallelism. Empirically, this batched evaluation achieves 5.3× to 47.8× speedup over CPU baselines (see Section 5).
