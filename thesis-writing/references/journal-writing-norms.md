# 期刊 / 会议论文写作规范

本文件覆盖期刊论文模式（Mode B）特有的写作规范。机械化 Markdown 规范（ATX 标题、图表语法、编号连续性、标记成对等）见 `shared-markdown-norms.md`，此处不重复。

## 时态规范

| 章节 | 推荐时态 | 示例 |
|------|---------|------|
| Abstract（背景陈述） | 现在时 | "Local search **is** central to..." |
| Abstract（本文工作） | 过去时 | "We **proposed** a tensor-based framework..." |
| Introduction（领域事实） | 现在时 | "VRP **is** NP-hard." |
| Introduction（前人工作） | 过去时或现在完成时 | "Smith **proposed**..." / "Recent work **has shown**..." |
| Method（定义、定理） | 现在时 | "The objective function **is** defined as..." |
| Method（本文做了什么） | 过去时 | "We **modeled** the solution as a tensor..." |
| Experiments（设置） | 过去时 | "We **trained** for 100 epochs..." |
| Experiments（结果） | 过去时 | "TGA **achieved** 5.3× speedup..." |
| Conclusion | 现在时 / 过去时混用 | "This paper **presents**... We **demonstrated**..." |

## 引文密度

期刊/会议论文**密集引用前人工作**。这是与本科毕设的关键差异——毕设可以在大段叙述后不引用，期刊论文则几乎每段都需要引用。

- **规则**：提及他人方法、模型、数据集、定理、对比基准时，**必须**在首次出现处标注引用
- **检测**：`check_markdown_spec.py --mode journal` 会对超过 500 词无引用的章节触发 `CITATION_DENSITY_LOW` WARN
- **典型密度**：Introduction 每段 3-5 处引用；Related Work 每句可能都有引用；Method 主要引用自己的前作；Experiments 引用数据集与基线

## 引文风格（由 profiler 检测，非硬编码）

`paper-metrics` 技能的 `profile_papers.py` 会检测该领域的主流引文风格。常见四种：

| 风格 | 形式 | 典型领域 |
|------|------|---------|
| IEEE-numeric | `[1]`, `[2,3]`, `[4-6]` | CS 顶会顶刊（NeurIPS / ICML / IEEE Trans） |
| ACM-numeric | `[1]` 同上 | ACM 系列会议 |
| Author-year (APA / Springer) | `(Smith, 2020)`, `Smith et al. (2021)` | 部分 Elsevier / Springer 期刊 |
| GB/T 7714-2015 | `[1]` 上标，参考文献列表按出现顺序 | 中文期刊 |

写作时应**采纳 `_domain_profile.json` → `citation_style.detected`** 推荐的风格，并在全文保持一致。

## 对冲语言（Hedging）

避免过度声称。下表左侧为高风险表达，右侧为推荐替代：

| ❌ 过度声称 | ✓ 推荐 |
|-----------|--------|
| "prove" / "证明" | "demonstrate" / "验证" / "表明" |
| "outperforms all existing methods" | "outperforms the compared baselines" / "achieves state-of-the-art on X" |
| "novel"（无对比） | 明确指出与最近邻工作的差异 |
| "first to"（除非确证） | "to the best of our knowledge, the first to" |

## 可复现性规范

现代 CS 论文普遍要求声明可复现性：

- **代码与数据**：在 Method 或 Experiments 末尾、或 Acknowledgments 中声明代码/数据获取方式（GitHub 链接、Zenodo DOI、或"upon request"）
- **随机种子**：声明是否固定种子、跑了多少次取平均（如 "averaged over 10 random seeds"）
- **硬件环境**：列出 GPU 型号、核心数、显存、CUDA 版本（硬件对比表见 `journal-image-spec.md`）
- **超参数**：完整列出学习率、batch size、训练步数等（超参表见 `journal-image-spec.md`）
- **统计显著性**：建议报告标准差、置信区间，或做显著性检验（如 Wilcoxon signed-rank）

## 常见反模式（务必避免）

| 反模式 | 问题 | 替代 |
|--------|------|------|
| **稻草人基线**（cherry-picked weak baselines） | 让自己的方法显得强 | 引入领域内 SOTA 作为对比 |
| **过度声称新颖性** | "novel" 但未对比最近工作 | 明确"与 [N] 的差异在于..." |
| **挑选有利实例** | 只展示方法表现好的例子 | 报告均值/中位数/失败案例分析 |
| **概念盗用** | 不引用方法的真正提出者 | 追溯到原始论文（哪怕较老） |
| **评估指标单一** | 只报告最好的一次结果 | 多指标 + 多数据集 + 统计显著性 |
| **黑盒方法** | 不解释关键设计选择的理由 | 消融实验佐证每个组件的必要性 |

## 摘要要求

- **字数**：英文 150-250 词；中文 200-400 字
- **结构**：问题陈述 → 现有方法局限 → 本文方法 → 关键结果（最好带具体数字）→ 影响
- **关键词**：4-6 个，用"；"（中文）或 ";"（英文）分隔，按外延从大到小排列
- **禁忌**：空洞口号、引用文献编号、未定义缩写

## 致谢要求

- 对资助方、指导者、协助者实事求是地致谢
- 披露利益冲突（无利益冲突也应声明）
- 现代期刊多要求 Author Contributions（CRediT 分类）、Data Availability Statement

## 字数与篇幅

- 会议论文：正文 6000-9000 词（8-12 页含参考文献）
- 期刊论文：正文 8000-15000 词（12-25 页）
- 综述：正文 15000-30000 词

具体以目标期刊/会议 Call for Papers 为准。`check_markdown_spec.py --mode journal` **不强制**字数下限（与毕设模式的 15000 字硬下限不同），而是对各章节字数比例给出 NOTE。
