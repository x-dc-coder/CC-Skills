---
name: thesis-writing
description: >
  双模式学术论文写作助手：按用户意图自动选择本科毕设（≥15000 字、六章模板、Web 系统论文）或期刊论文模式，生成带图表/公式占位符的结构化 Markdown 草稿（对接 diagram-* 技能族），并经过 Markdown 规范检查器校验。当用户要求写论文、写毕设、生成论文草稿、整理期刊论文（write a thesis / draft a paper）时使用。
---

# 学术论文正文撰写 Skill (Dual-Mode)

双模式学术稿件生成器。生成结构化 Markdown 初稿，图片使用占位符（对接 `diagram-*` skill 家族），最后用 `check_markdown_spec.py` 校验。

## 适用范围

- **Mode A — undergraduate-thesis**：理工科本科毕业论文（Web 系统类，≥15000 字，固定 6 章模板）
- **Mode B — journal-paper**：CS / 工程类期刊或会议论文（领域无关，由 `paper-analysis/` 语料归纳写作规范）

## Decide the mode first

每次调用本 skill 时，**首先判断模式**：

| 信号 | Mode A（undergraduate） | Mode B（journal） |
|------|------------------------|-------------------|
| 用户关键词 | 毕设、毕业论文、本科、开题报告、任务书 | 期刊、会议、journal、conference paper、写论文、投稿、draft based on references |
| 输入 | 项目源码 + 开题报告/任务书 | `paper-analysis/` 目录（MinerU+Marker Markdown，由 paper-reader 生成）+ 用户的实验代码/结果 |
| 字数约束 | ≥15000 字硬下限 | 6000-15000 词软参考，由目标期刊/会议决定 |
| 章节模板 | 固定 6 章（1绪论→6结论） | 由 profiler 从语料归纳（IMRaD-Method / IMRaD-System / Survey） |
| 引文风格 | GB/T 7714-2015 强制 | profiler 检测（IEEE / ACM / author-year / GB-T 7714） |

不确定时向用户确认。两种模式**共享** Markdown 机械化规范（见 `shared-markdown-norms.md`）、占位符语法、diagram skill 对接、`check_markdown_spec.py` 调用接口（`--mode` 区分）。

## Mode A — Undergraduate Thesis Workflow

### 阶段一：环境检查与项目分析

#### 1.1 环境检查
1. 确认用户是否提供了开题报告、任务书或其他参考文档（Markdown、纯文本等均可）
2. 校验提供的文档文件是否存在且可读

#### 1.2 项目分析
1. 读取用户指定的开题报告、任务书等参考文档
2. 扫描项目代码结构：
   - 前端：路由文件、页面组件、API 接口调用
   - 后端：Controller、Service、Entity/Model、数据库配置
3. 分析数据库表结构（从 Entity 类或 SQL 文件推断）
4. 输出"项目理解摘要"，请用户确认是否准确
   - 若用户指出遗漏或错误，补充分析后重新确认

### 阶段二：大纲生成

1. 读取 `references/undergrad-template.md`，获取标准章节结构和字数分配
2. 根据项目分析结果，将模板中的占位符替换为实际内容：
   - 确定相关技术栈的具体名称
   - 确定需求分析中的角色和功能
   - 确定系统设计中的具体模块划分
   - 确定数据库实体和表结构
   - 确定第4章各功能模块的具体子节
3. 标注每章预估字数（确保总计 >= 15000 字）
4. 标注所有图片位置，引用 `references/undergrad-image-spec.md` 的占位符格式
5. 呈现完整大纲，等待用户确认或修改

### 阶段三：逐章撰写

1. 读取 `references/undergrad-example-output.md` 作为写作风格参考
2. 按大纲顺序逐章生成 Markdown 内容
3. **所有图片均使用占位符**，不直接生成图片。占位符格式见下文"图片占位符规范"
4. 每章完成后写入 `thesis-output/thesis-writing/第X章-章节名.md`
5. 每章完成后询问用户：
   - 确认，继续下一章
   - 需要修改（指出具体修改点后重新生成）
   - 调整大纲（回退到阶段二，修改大纲后从当前章节继续）
6. 全部章节完成后，进入阶段四

### 阶段四：合并与质量检查

1. 将所有章节合并为 `thesis-output/thesis-writing/full-thesis.md`
2. **执行 Markdown 规范检查**（必须）：
   ```bash
   cd ~/.claude/skills && uv run python thesis-writing/scripts/check_markdown_spec.py \
     --md <output_dir>/full-thesis.md --mode undergraduate
   ```
   - 若检查失败，必须修复所有 ERROR 后才能继续
   - 建议修复所有 WARN 以获得最佳质量
3. 执行质量检查（checker 已自动完成大部分检查，以下为补充确认）：
   - 统计正文总字数，检查是否 >= 15000 字
   - 确认 checker 报告的图片编号连续性和章节号一致性
   - 确认 checker 报告的表格编号连续性和章节号一致性
   - 确认 checker 报告的标题编号连续性（一级/二级/三级均无跳号无重复）
   - 确认 checker 报告的标题格式一致性（同级标题无混用格式）
   - 确认 checker 报告的参考文献编号从 [1] 开始且连续无重复
   - 检查参考文献引用标记与参考文献列表是否一一对应
   - 确认无残留的图片占位符（`> [图` 或 `> 描述：`）
   - 确认所有本地图片路径指向存在的文件
4. 输出检查报告，标注发现的问题
5. 若有问题，修复后重新检查；若无问题，完成

## Mode B — Journal Paper Workflow

### 阶段 A：文献摄入与领域建模

**目标**：将 `paper-analysis/` 语料（可能数十篇论文 × 上百 MB）转化为一份机器可读的领域写作规范摘要，**不消耗 LLM token 重读所有文献**。

#### A.1 定位语料
- 确认用户提供 `<user_paper_dir>/paper-analysis/` 目录
- 校验目录结构：每篇论文应有 `mineru/<id>/auto/<id>_content_list.json`（由 paper-reader 生成）
- 若用户尚未转换 PDF，**提示用户先调用 paper-reader skill**；不要自行重跑

#### A.2 运行 profiler
```bash
cd ~/.claude/skills && uv run python thesis-writing/scripts/profile_papers.py \
  --corpus "<user_paper_dir>/paper-analysis/" \
  --out "<output_dir>/"
```
生成：
- `<output_dir>/_domain_profile.json` — 机器可读（供阶段 C 消费）
- `<output_dir>/_domain_profile.md` — 人类可读（供用户审阅）

profiler 是纯 Python 脚本（stdlib 实现），毫秒级处理数十篇论文，零 LLM token 成本。

#### A.3 LLM 辅助精炼（唯一读正文的步骤）
读取 `_domain_profile.md` + 语料中**被引最多的 Top-N 篇论文**的 Abstract + Introduction（marker 路径，cap 在 ~15k tokens 内），补充：
- 贡献声明句式（"Our main contributions are..." vs "In this paper, we..."）
- 该领域的术语规范形式（如 VRP/CVRP/MDVRP/HCVRP 的使用习惯）
- 必详写 vs 必略写的判断

#### A.4 用户确认门
将 `_domain_profile.md` 呈现给用户："这份领域写作规范摘要是否准确？有无遗漏？" **这是关键的人工校验点**——后续整个初稿都依赖它。用户修改后重新生成 profile。

### 阶段 B：实验/项目数据收集

#### B.1 盘点用户实验资产
- 实验代码仓库、结果 CSV/JSON、benchmark 日志、消融表、超参配置
- 输出结构化清单 `<output_dir>/_experimental_inventory.md`

#### B.2 确认贡献点
请用户用 1-3 句话陈述本文贡献。这决定阶段 C 的章节字数分配（benchmarking 论文 Experiments 章节会重；方法类论文 Method 章节会重）。

### 阶段 C：写作规划书生成 ★

**这是 Mode B 的核心交付物**——向用户明确说明：本文应如何组织、哪里放图、哪里放表、哪里放公式、字数分配。

读取 `_domain_profile.json` + `_experimental_inventory.md` + 贡献陈述 → 输出 `<output_dir>/_writing_plan.md`：

| 规划项 | 数据来源 |
|--------|---------|
| 目标章节骨架（如 Abstract→Intro→Related→Preliminaries→Method→Experiments→Conclusion） | `_domain_profile.json` → `section_skeleton`（频次排序） |
| 各章节字数预算 | `_domain_profile.json` → `section_skeleton[].median_word_share` × 目标总字数 |
| 图片清单（哪一节、哪一类型：framework / network / algorithm-flow / result-curve / ablation-heatmap） | `_domain_profile.json` → `figure_placement_patterns` × 用户的实际贡献 |
| 表格清单（benchmark / ablation / hyperparameter / dataset-stats / hardware-spec / notation-table） | `_domain_profile.json` → `table_placement_patterns` |
| 公式清单（objective-function / constraint / loss / attention / state-transition / complexity-bound） | `_domain_profile.json` → `equation_placement_patterns` |
| 引文风格 | `_domain_profile.json` → `citation_style.detected` |
| 参考文献数量目标 | `_domain_profile.json` → `reference_count.median ± 20%` |

#### C.1 用户确认门（必须）
用户可编辑规划书；编辑后回到此处再生成，确认后才进入阶段 D。

### 阶段 D：逐章生成

与 Mode A 阶段三相同的循环，两点差异：
- 读取 `references/journal-example-output.md` 作为 few-shot 参考（而非 Web 系统示例）
- 图片占位符使用**期刊图表词汇**（见 `references/journal-image-spec.md`），按子类型路由到对应 diagram skill：

| 期刊图片类型 | 对接 skill | 备注 |
|-------------|-----------|------|
| 方法/框架总览图 | `diagram-flow` | Mermaid 分层架构图 |
| 神经网络结构图 | `diagram-flow` | Mermaid 分层 subgraph 模型图 |
| 算法流程图 | `diagram-flow` | Mermaid 流程图 |
| 实验结果图（折线/柱状/热力/散点） | 无 diagram skill | 占位符描述 matplotlib/seaborn 调用，用户后续渲染 |
| 消融对比表 / 硬件对比表 | 直接 Markdown 表格 | 不需 diagram skill |

章节写入 `<output_dir>/sec-N-<slug>.md`，每章后用户确认循环同 Mode A。

### 阶段 E：质量校验

#### E.1 合并
合并为 `<output_dir>/full-paper.md`。

#### E.2 运行 checker
```bash
cd ~/.claude/skills && uv run python thesis-writing/scripts/check_markdown_spec.py \
  --md <output_dir>/full-paper.md --mode journal
```
`--mode journal` 相对 `undergraduate` 的差异：
- 启用更多英文特殊标题（Keywords / Introduction / Related Work / Acknowledgments / Data Availability 等，不触发编号错误）
- **新增引用密度检查**：任一超过 500 词的章节若零引用，触发 `CITATION_DENSITY_LOW` WARN（期刊论文应密集引用前人工作）
- 不强制 GB/T 7714 引文风格（由 profiler 决定）
- 不强制 15000 字硬下限

#### E.3 补充确认
- 占位符残留检查（同 Mode A）
- 参考文献编号连续性（共享逻辑，已检查）
- 摘要长度：英文 150-250 词 / 中文 200-400 字
- 参考文献数量 vs profile 目标 ±30%（WARN）

## 图片占位符规范（两模式共享）

论文初稿中**所有图片均使用文字占位符**，实际图片在后续阶段由专门的 diagram skill 生成。

### 占位符格式

```
> [图X-Y 图片标题]
> 描述：详细描述图片应展示的内容
```

- X 为章节号，Y 为章内顺序号
- 编号全章连续，不得跳缺或重复
- 描述需足够详细，以便后续调用 skill 生成图片时明确知道要画什么

### 占位符类型与对应生成 Skill

**Mode A（本科毕设）** — 详见 `references/undergrad-image-spec.md`：

| 占位符中的图片类型 | 后续调用 Skill | 所需输入 |
|-------------------|---------------|---------|
| 用例图 | `diagram-usecase` | JSON 文件（actor + usecases） |
| E-R 图（单表含属性） | `diagram-er` | SQL DDL 文件 |
| E-R 图（多实体关系，不含属性） | `diagram-ers` | JSON 文件（entities + relations） |
| 功能模块图 / 系统功能结构图 | `diagram-module` | JSON 文件（tree 结构） |
| 流程图（业务流程 / 系统流程） | `diagram-flow` | 直接生成 Mermaid 代码 |
| 时序图（模块交互） | `diagram-sequence` | JSON 文件（participants + messages） |
| 界面截图 | 不适用 | 需实际运行系统后手动截图 |

**Mode B（期刊论文）** — 详见 `references/journal-image-spec.md`：

| 占位符中的图片类型 | 后续调用 Skill | 所需输入 |
|-------------------|---------------|---------|
| 方法总览图 / 系统架构图 | `diagram-flow` | 文字描述（层名 + 数据流） |
| 神经网络结构图 | `diagram-flow` | 文字描述（层名 + 维度 + 连接） |
| 算法流程图 / 业务流程 | `diagram-flow` | 直接生成 Mermaid 代码 |
| 概念示意图 / 分类法图 | `diagram-flow`（或手绘） | 文字描述 |
| 实验结果图（折线/柱状/热力/散点） | 不适用（用户后续用 matplotlib 渲染） | 数据文件路径 + 轴/系列说明 |
| 实验对比表 / 消融表 / 超参表 | 不适用（直接写 Markdown 表格） | - |

### 占位符替换规范（关键）

当后续调用 diagram skill 生成图片后，**必须按以下规则替换占位符**，确保不残留任何占位符内容：

1. **整段删除**：删除整个引用块（包括 `> [图X-Y ...]` 和 `> 描述：...` 所有行）
2. **替换为 Markdown 图片语法**：`![图X-Y 标题](thesis-output/thesis-writing/img/图X-Y_标题.png)`
3. **路径规范**：所有图片统一放到 `thesis-output/thesis-writing/img/` 目录下（相对项目根目录，非 cwd 相对）
4. **diagram skill 输出对接**：diagram skill 默认输出到 `thesis-output/<skill-name>/`，引用时需指向实际输出路径，或将图片复制到 `thesis-output/thesis-writing/img/`
5. **替换后检查清单**：
   - [ ] 全文搜索 `> \[图`，确认无残留
   - [ ] 全文搜索 `> 描述：`，确认无残留
   - [ ] 检查图片前后是否有段落文字描述（不能只有图题）
   - [ ] 确认图片下方没有重复的标题文字

**错误示例**（残留描述）：
```markdown
![图3-1 系统功能结构图](thesis-output/thesis-writing/img/图3-1_系统功能结构图.png)
> 描述：树状结构图，顶层为...    <-- 错误！必须整段删除
```

**正确示例**：
```markdown
如图3-1所示，系统采用分层架构设计。

![图3-1 系统功能结构图](thesis-output/thesis-writing/img/图3-1_系统功能结构图.png)

从图3-1可以看出，系统主要包含前台和后台两大子系统...
```

## Markdown 格式规范（两模式共享）

所有生成的 Markdown 文档必须符合 `references/shared-markdown-norms.md` 中的机械化规范（由 `check_markdown_spec.py` 检查）。要点：

- **编码**：UTF-8 无 BOM，LF 行尾
- **标题**：ATX 风格（`#`/`##`/`###`），编号连续不跳级
- **图片**：Markdown 语法，禁止 `<img>`，禁止公式以图片插入，图前后须有段落
- **表格**：表题在表格前，编号连续，表前后须有段落，**各行列数一致**（合并 `<<N`/`^^N` 合法）
- **公式**：行内 `$...$`，独立 `$$...$$`（**必须成对闭合**），编号 `\tag{X-Y}`
- **代码块**：fence（```）**必须成对闭合**
- **段内换行**：禁止（用空行分段），禁止 `<br>`
- **参考文献**：从 [1] 开始连续，条目间空行
- **标记成对**：`**` / `*` / `~~` / `` ` `` / `[]` / `()` / 引号
- **Mermaid**：保留会触发 WARN，应渲染为图片或删除

各模式特有的写作规范：
- Mode A：见 `references/writing-norms.md`（GB/T 7714 强制、≥15000 字、CY/T 35-2001 编号）
- Mode B：见 `references/journal-writing-norms.md`（时态、引用密度、对冲语言、可复现性、引文风格由 profiler 决定）

## 写作规范要求

- Mode A：读取 `references/writing-norms.md` 获取本科毕设特有规范
- Mode B：读取 `references/journal-writing-norms.md` 获取期刊论文特有规范
- 两模式共享：读取 `references/shared-markdown-norms.md` 获取机械化 Markdown 规范
- 章节编号使用阿拉伯数字：1, 1.1, 1.1.1
- 图片使用文字占位符，格式见对应的 image-spec 文件
- 表格使用 Markdown 表格格式
- 参考文献格式：Mode A 用 GB/T 7714-2015；Mode B 用 profiler 检测的风格

## 输出目录约定

遵循 CLAUDE.md 的两级回退规则：
- 用户在工作项目目录下（cwd 不在 `~/.claude/skills`）：输出到 `<cwd>/thesis-output/thesis-writing/`
- 否则：输出到 `~/.claude/skills-output/thesis-writing/`

可用 `--output` 显式覆盖。profiler 的 `_domain_profile.{json,md}` 默认写入同一输出目录。
