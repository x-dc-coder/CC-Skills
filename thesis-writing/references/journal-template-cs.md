# 期刊/会议论文章节骨架模板（CS / 工程类）

本文件**不是固定模板**，而是骨架选择器。`profile_papers.py` 生成的 `_domain_profile.json` 中的 `section_skeleton` 字段会指出该领域最常用的骨架；写作时应优先采纳频次最高的骨架，再根据本文贡献微调。

## 三种常见 CS 骨架

### 骨架 1：IMRaD-Method（算法/方法类论文，最常见）

适用于：提出新算法、新模型、新框架的论文（如 VRP 求解、网络结构创新、训练方法改进）。

| # | 章节 | 规范标签 | 中位字数占比 | 必备 | 说明 |
|---|------|---------|------------|------|------|
| - | Abstract | `abstract` | 2-4% | ✓ | 150-250 词（英文）/ 200-400 字（中文），含问题、方法、关键结果 |
| - | Keywords | `keywords` | - | ✓ | 4-6 个，按外延从大到小排列 |
| 1 | Introduction | `introduction` | 10-15% | ✓ | 背景、问题、贡献点列表（typically "Our main contributions are: (1)... (2)..."）、论文组织 |
| 2 | Related Work | `related_work` | 8-12% | ✓ | 前人工作分类综述，引出本文差异点；可与 Preliminaries 合并 |
| 3 | Preliminaries | `preliminaries` | 8-15% | ○ | 问题定义（含数学定义 + 目标函数公式）、符号表、背景知识 |
| 4 | Method / Proposed Approach | `method` | 25-35% | ✓ | 核心方法章节。必备：方法总览图 + 公式推导 + 算法伪代码 |
| 5 | Experiments | `experiments` | 25-35% | ✓ | 实验设置（数据集、对比基线、评估指标、硬件环境）+ 主结果 + 消融实验 + 效率分析 |
| 6 | Discussion | `discussion` | 3-8% | ○ | 局限性、可扩展性、与相关工作对比 |
| 7 | Conclusion | `conclusion` | 2-5% | ✓ | 成果总结、未来工作 |
| - | References | `references` | - | ✓ | 引文风格由 `_domain_profile.json` 决定 |

### 骨架 2：IMRaD-System（系统类论文）

适用于：构建完整系统、工具链、基准测试平台的论文。

将骨架 1 的第 4 章拆为：`System Design`（架构图 + 模块设计）+ `Implementation`（实现细节 + 接口）+ `Evaluation`（性能基准 + 可扩展性测试）。

### 骨架 3：Survey / Review（综述类论文）

适用于：系统梳理某一领域现有工作的论文。

| # | 章节 | 说明 |
|---|------|------|
| 1 | Introduction | 问题定义、综述范围、贡献（如新分类法） |
| 2 | Taxonomy / Classification | 提出分类维度（用一张分类图） |
| 3-5 | Method-by-method（按分类逐章） | 每类方法一节，统一比较维度 |
| 6 | Open Challenges | 未来方向 |
| 7 | Conclusion | |

## 摘要与关键词

### 摘要写作要点

- **结构**：问题陈述 → 现有方法局限 → 本文方法 → 关键结果（最好带数字）→ 影响
- **字数**：英文 150-250 词，中文 200-400 字
- **禁忌**：空洞口号（"具有重大意义"）、引用文献编号、未定义的缩写（首次出现需全称）
- **时态**：背景与结论用现在时；具体做法用过去时（"we proposed" / "we evaluated"）

### 贡献声明（Introduction 末尾，几乎必备）

期刊与会议论文普遍在 Introduction 末尾用列表形式声明贡献。常用句式（由 profiler 检测该领域的偏好）：

```
The main contributions of this paper are summarized as follows:
- (Contribution 1) ...
- (Contribution 2) ...
- (Contribution 3) ...
```

或：

```
In this paper, we make the following contributions:
(1) ...  (2) ...  (3) ...
```

## 篇幅参考

- **会议论文**：8-12 页（含参考文献），正文 6000-9000 词
- **期刊论文**：12-25 页，正文 8000-15000 词
- **综述**：20-50 页，正文 15000-30000 词

具体字数应参考目标期刊/会议的 Call for Papers。

## Back-matter（部分现代期刊要求）

| 章节 | 是否常见 | 说明 |
|------|---------|------|
| Acknowledgments | 常见 | 资助、致谢，放在 References 之前 |
| Author Contributions | 部分期刊 | CRediT 分类（Conceptualization / Methodology / Writing 等） |
| Conflict of Interest / Competing Interests | 几乎全部 | 声明无利益冲突或披露 |
| Data Availability Statement | 几乎全部 | 数据/代码获取方式 |
| Funding | 部分 | 资助方与项目编号 |
| Appendix | 可选 | 补充材料、详细推导、扩展实验 |
