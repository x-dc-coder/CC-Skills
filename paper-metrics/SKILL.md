---
name: paper-metrics
description: >
  论文写作特征指标层（纯 stdlib、确定性、零 LLM）：把 paper-analysis/ 语料转成可复现、可验证、可解释的
  OBSERVED 层写作指标画像，产出 _domain_profile.json/.md、_per_paper_metrics.jsonl、_corpus_summary.json、
  _run_meta.json，并支持写作契约生成与草稿校验。当用户要求提取论文写作特征指标、生成期刊/会议风格画像或
  语料指标基线、生成写作契约、校验草稿指标、或复核指标可复现性（同输入→同输出、逐字节）时使用。
  **本技能只做测量、不做写作生成**：写作由 thesis-writing（Mode B）消费本技能产物后完成。
version: 1.0.0
---

# paper-metrics — 论文写作特征指标层

**一句话**：把"论文的写作特征"变成**可复现、可验证、可解释**的数字，再把数字变成可执行的写作契约与草稿校验。
**本技能只测量，不生成文本。**

## 何时使用（必须用）

- 用户要求"提取这篇/这批论文的写作特征指标""期刊风格画像""语料指标基线"
- 用户要求"按目标期刊的指标区间写" → 先用本技能生成 `_writing_contract.yaml`
- 用户要求"校验我的草稿是否符合期刊风格/指标区间" → `validate_draft.py`
- 用户或第三方要求"复核这些指标数值能不能复算" → `baseline_eval.py` / `profile_papers.py --verify`
- 需要从 PDF 一路跑到指标 → `run_pipeline.py`（内部调用 paper-reader）

**不要用此 skill**：

- 只想把 PDF 转成 Markdown → 用 `paper-reader`
- 写论文正文/大纲/初稿 → 用 `thesis-writing`
- 只做术语一致性检查 → 用 `thesis-ref-check`

## 上下游衔接（事实源边界）

```
PDF ──paper-reader──▶ paper-analysis/（Canonical Document）
                          │  上游：GPU、分钟级/篇；版本与源哈希记在各篇 _META.json
                          ▼
                    paper-metrics（本技能）
                          │  纯 stdlib、秒级/语料、逐字节可复现
                          ▼
        _domain_profile.json / _corpus_summary.json / _per_paper_metrics.jsonl
                          │  下游：thesis-writing **Mode B**（阶段 A.2 → C）
                          ▼
              _writing_plan.md → 逐章生成 → validate_draft.py 校验
```

- **上游 paper-reader**：本技能**不解析 PDF**。输入必须是已转换的 `paper-analysis/`（每篇含 `mineru/<id>/auto/<id>_content_list.json`）。用户尚未转换时，提示先跑 paper-reader，不要自行重跑。
- **下游 thesis-writing Mode B**：只消费 `_domain_profile.json` 的既有字段（`section_skeleton`、`figure|table|equation_placement_patterns`、`citation_style`、`reference_count`、`corpus`）。**字段与形状由本技能承诺，下游不得改写。**

## 五个产物（跑一次 `profile_papers.py` 全部产出）

| 产物 | 用途 | 参与指纹 |
|---|---|---|
| `_domain_profile.json` | 机器可读领域画像（下游 Mode B 消费） | ✅ |
| `_domain_profile.md` | 人类可读（由 JSON 确定性渲染，两者永不冲突） | ✅ |
| `_per_paper_metrics.jsonl` | 每篇一行的审计轨迹（含输入 sha256 与 evidence span） | ✅ |
| `_corpus_summary.json` | 语料级聚合（可由 jsonl 机械重算） | ✅ |
| `_run_meta.json` | 时间戳/主机/路径/耗时（**不参与指纹**） | ❌ |

## 快速开始

```bash
cd ~/.claude/skills

# 1) 语料 → 指标（主入口）
uv run python paper-metrics/scripts/profile_papers.py \
  --corpus "<user_paper_dir>/paper-analysis/" --out "<output_dir>/" [--verify]

# 2) PDF → paper-analysis/ → 指标（串联 paper-reader 与本层）
uv run python paper-metrics/scripts/run_pipeline.py \
  --papers <papers_dir> --out <output_dir> [--analysis-dir DIR] [--skip-convert] [--dry-run]

# 3) 由语料分位生成写作契约（区间 = p25/p75，而非人工设定）
uv run python paper-metrics/scripts/build_contract.py \
  --summary <out>/_corpus_summary.json --out <out>/_writing_contract.yaml

# 4) 用同一套指标校验草稿（任一 gate 失败 → 退出码 1）
uv run python paper-metrics/scripts/validate_draft.py \
  --contract <out>/_writing_contract.yaml --draft <out>/full-paper.md --json <out>/_draft_validation.json

# 5) 基线自证：连跑 N 次逐字节比对 + 8 项验收
uv run python paper-metrics/scripts/baseline_eval.py --corpus <paper-analysis> --out <out> [--drift-probe 10]

# 6) 被动语态抽检（M-PAS-09 精确率/召回率凭证）
uv run python paper-metrics/scripts/pas_spotcheck.py --corpus <paper-analysis> --out <md> --json <json>
```

## 可复现契约（红线）

- **bit 级复现的范围是 `Canonical Document → 指标`**：同一语料、同一路径、同一版本连跑两次，上表 ✅ 的四个文件**逐字节相同**；`--verify` 自检（重跑到临时目录逐字节比对，失败退出码 1）。
- **PDF → Canonical 不由本技能承诺**：那条链属 paper-reader，其漂移通过各篇 `_META.json` 的 `pdf_sha256` / `engine_versions` 归因（可发现、可追责，不承诺跨引擎逐字节）。
- **第三方复核入口**：`_domain_profile.json → corpus.profiled[].inputs[].sha256` 给出每个输入产物的哈希；`_per_paper_metrics.jsonl` 给出逐篇数值与 evidence span，可直接回指原文坐标。
- **词表冻结**：`data/lexicons/v1/*.json` 随发布冻结，bundle 指纹写入产物；改词表即改数值，**必须 bump 版本并重锁基线**。
- **层红线（只做 OBSERVED）**：本技能只产出确定性规则指标（`state = OBSERVED`、`method = rule`，由 `test_profile_papers.py` / `test_determinism.py` 断言守线）。语步（move）、引用功能、论证图等 INFERRED 语义指标**未实现**，且必须同时满足 5 条准入条件才能引入（标签集冻结 + 人工标注集 κ ≥ 0.6 + 留出集 P/R/F1 + 每句可追溯输出 + 不得进 gate / 不得自报置信度）——完整检查表见 `references/metric-definitions.md`〈INFERRED 层准入检查表〉。
- **分句前的非正文掩码（2026-09-13）**：句界只在**等长掩码副本**上判定，关键词行（`Keywords:`/`关键词：`）、行内/行间数学（`$...$`/`$$...$$`）、MinerU 的 `<sub>`/`<sup>` 标签不参与分句；掩码后不含字母的片段直接丢弃。span 仍切片回原文，语料级 before/after 差值见 `references/metric-definitions.md`〈正文口径与关键词行过滤〉。

## 指标基座：范围与块型普查（2026-09-14 起）

指标不是"从论文"算出来的，而是**从某个基座的某个流**算出来的。这两件事过去是隐式的，导致同一篇论文的"数字丢失"可以是 2.1%、25%、55.5% 或 78.2%——**取决于拿什么跟什么比**。现在它们都是产物里的显式字段：

- **基座**：`_corpus_summary.json → base_artifact` = `{name: "mineru_content_list", scope: ["prose"]}`。指标定义在 **MinerU `content_list.json` 的 prose 流**上。
- **每条指标自带 `scope`**：现在全部是 `["prose"]`；**缺 `scope` 即测试失败**（防"隐式口径"回归）。将来建立在表格/图表流上的新指标会显式写 `["tables"]` / `["captions"]` / `["inventory"]`。
- **块型普查**：`_per_paper_metrics.jsonl → block_census`（逐篇）与 `_corpus_summary.json → block_census`（语料级）给出每个流有多少块/字符/数字，以及**是否被指标读取**（`dropped_by_metrics`）。

**实测（中文语料 10 篇，去标记后的规范化计数）**：prose 只覆盖 **69.6% 字符 / 25.0% 数字**；未被读取的流里，`tables` 30 块 **7668 数字**、`lists` 10 块 **19237 字符 / 2175 数字**、`equations` 314 块（去 LaTeX 后 22073 字符）、`footnotes` 30 块、`running_heads` 155 块、`page_numbers` 64 块，另有 732 字符题注（四个键：`image_/table_/chart_/code_caption`）。

### 口径决定（2026-09-14，用户定）

1. **脚注不算正文** → `footnotes` 独立流，不进 prose，但进普查（将来若需要可作为独立指标）。
2. **表格与图表各自独立分析，绝不并入正文纯文本** → 表格数字、图注/表注都要成为**独立指标**（对应 issue #1 的 D-1/D-2），不得混入句长/密度类指标。
3. 因此**现有 14 条指标继续只读 prose 流** → 数值不变、已登记语料无需重登记（审计 23/23 与 22/22 不变即为证明）。

### 两条规范化红线（否则计数直接错）

- **表格必须先剥离 HTML**：真实语料里 `table_body` 的 **51.8% 是标记**，且属性自带约 2600 个"数字"（`colspan`/样式/宽度）——直接计数会凭空多出数字。实现：`html_to_text()`（去标签/注释、解实体、`</td>`/`<br>` 变分隔符）。
- **公式必须先剥离 LaTeX 命令**：`equation` 块的原始文本里命令占 ~60%（314 块 55835 → 22073 字符）；实现：`latex_to_text()`（去命令与 ``{}` 框架，保留变量与数字）。

> 为什么这些是"普查"而不是"指标"：表格不是句子，把表格塞进句长/hedge/被动会把 style 指标污染掉（这正是 prose-only 的正当理由）。但"看不见"也不对——所以每条流的体量都必须**可见、可复算、可追责**。

## 支持的语言（红线：不支持就**显式失败**，绝不给假数字）

- **英文（en）**：14 条指标全部可测，词表用 `data/lexicons/v1/`。
- **中文（zh）是逐指标能力，不是一刀切门禁（2026-09-13，issue #13）**：
  - **已可测 13/14 条**：`M-SLEN-01`、`M-LSF-16`、`M-MTLD-02`、`M-HED-14`、`M-BOO-15`、`M-CONN-30(c/k/r)`、`M-AWR-03`、`M-PAS-09`、`M-PCNT-25`、`M-NOM-10`（词表用 `data/lexicons/v2-zh/`）；
  - **尚不可测 1 条**：`M-TENSE-28`（**中文没有时态**，给数字就是编造）→ `null` + **`CAPABILITY_NOT_SUPPORTED`**（`LANGUAGE_NOT_SUPPORTED` 的逐指标版本；**仍然不是 0**）；
  - **两个"同槽不同量"的指标要特别小心**：`M-MTLD-02` 中文是**字符级**、`M-NOM-10` 中文是**抽象名词后缀（性/度/率）密度**——与英文同名指标**不是同一个统计量**，记录里带 `tokenization` / `variant` 标记，禁止跨语言比较；
  - **中文口径（与英文不可混用，跨语言不可比）**：句长单位 **`cjk-units/sentence`**（汉字数 + ASCII 字母 token，混合句不漏计）；长句阈值 **80 单位**（不是英文的 40 词）；密度类分母为 **cjk-units**、连接词单位 **`per-1000-cjk-units`**；段落单位 **`cjk-units/paragraph`**（下限 40 单位）；`M-MTLD-02` 是 **字符级**（`tokenization=cjk-char+ascii-token`，与英文词级值不可比）；
  - 分句支持 `。！？…`；`……` 这类终止符连写只结一次；引号内的句号留在句中；**`；` 不切句**（中文在句内使用）；片段过滤要求"无字母**且**无 CJK"才丢弃；
  - 被动用中文标记规则（`被/受到/得到/加以/予以` + 后接汉字）；连接词三组**联合最长匹配**，保证 `M-CONN-30 = 30c + 30k + 30r` 严格成立；
  - 能力矩阵的唯一事实源是 `text_metrics._METRIC_LANGUAGE_CAPABILITY`；**中文词表是策展词表**（无公开可再分发的对应资源，见 `data/lexicons/v2-zh/*.json` 的 source 字段）。
- **元数据层也已支持中文（issue #10 首步）**：引用样式识别认全角 `［N］`，参考文献计数认无空格的中文条目与 GB/T 7714 文献类型标记。
- **上游已落盘同规则的语言记录（issue #10 首步，2026-09-14）**：paper-reader 为每篇写 `_META.json` 的 `language` / `cjk_ratio` / `lang_source`，规则与本层 `detect_language` **逐字符类、逐阈值一致**（`cjk_ratio > 0.10 → zh`）。**冻结用例是共享的**：`paper-reader/scripts/lang_spec_cases.json`，本层测试 `test_detect_language_matches_paper_reader_shared_spec` 断言同一份文件——**漂移的是规则，这一点已被钉死**。
- **但语言结论不保证一致，也不得跨层比较**：本层量的是**过滤后的正文**（丢 references/keywords/front_matter），上游量的是**原始 content_list**。同一篇"英文正文 + 中文参考文献"的论文，两层完全可能落在 0.10 阈值两侧。所以本层会**显式交叉核对**，且把两种情形分开（issue #10 首步，2026-09-14）：
  - 双方都给出确定且**不同**的判断 → 逐篇 `LANGUAGE_METADATA_MISMATCH`（附 `language_mismatch`：双方 `language` / `cjk_ratio` 与 `lang_source`）；
  - 上游**有**明确记录、本层**完全测不出**（canonical 拿不到） → 逐篇 `LANGUAGE_DETECT_MISSING`：**"本次没测出"不等于"两边一致"**，混为一谈就是把未测量洗成通过（本层的 R2 红线）；
  - 只有"某一侧为 `unknown`"（没有主张）才算无可比，静默跳过；比较前对大小写与 `zh-CN` 这类地区子标签做归一，避免把标签差异误报成语言差异。
  语料级同步产出同名 code——**不一致、以及"测不出"，都必须被看见**。
- 每篇都会算 `cjk_ratio = 汉字数 / (汉字数 + ASCII 字母 token 数)`，**`cjk_ratio > 0.10` 判为中文**（阈值与实现见 `text_metrics.detect_language`）。
- **没有规则的语篇**（既不是 en 也不是 zh）：**每一个指标输出 `null`**（`n = 0`、`warnings = ["LANGUAGE_NOT_SUPPORTED"]`），计入 `n_missing`，并在语料级触发 `CORPUS_LANGUAGE_UNSUPPORTED` 告警；**任何情况下不得用 0 代替"未测量"**。
- 草稿校验：**能力感知**（issue #13）——逐条判定，测不了的指标以 `capability_not_supported` 跳过并说明原因；只有"没有任何规则的语言"才整体拒绝（退出码 2 `language_unsupported`）；中文草稿的有效性门槛用 **cjk-units（≥150）**，不是 ASCII 词数。
- 为什么这条是红线：在真实中文语料上，本层曾**静默**产出 `citation_style=unknown`、`reference_count=0`、hedge/连接词/被动/名词化**全为 0.0**、句数中位 **2 句**，而 `n_missing` 全为 0、无任何语言告警——看起来像"合法结果"，实际是垃圾。证据：`/mnt/e/AllProjects202601/M-PCA/_paper-metrics-run/运筹与管理/报告.md`。
- 中文支持路线见 GitHub issue #10；中文词表/标注集等缺口见 issue #11 的评审意见。

## 指标定义（可解释性的事实源）

- 每条指标的定义、公式、分母、evidence 坐标系，以及**不能推断什么**，见 `references/metric-definitions.md`。
- `n_valid < 5` 时**禁止**断言"该期刊偏好 X"；只能呈现单篇表并说明样本不足。
- 禁止任何"87/100"式百分制综合分：只输出逐指标实际值、目标区间与偏差。
- **非正文流指标（2026-09-14，5 条）**：`S-CAP-01` 图表题注覆盖率、`S-NUM-02` 编号一致性、`S-REF-03` 正文引用一致性、`S-SIZ-04` 图像分辨率充裕度（只读 `figures`）、`S-CAPL-05` 题注长度中位。它们只读 `figures`/`tables` 流（产物里 `scope` 写明），**绝不并入 prose**；**不进草稿契约**（Markdown 草稿没有块结构、无法复算），`build_contract` 会以 `NON_PROSE_METRICS_EXCLUDED` 显式说明"留在画像、不进契约"。
  实测（2026-09-14）：中文 10 篇 **0.9667 / 0.98 / 0.4829 / 图 6.7% / 18.0 字符**；英文 34 篇 **图 424 张合并达标率 28.3%**。`S-SIZ-04` 只读文件头（纯 stdlib，已用系统 `file` 命令交叉核验）；读不了的图不计入分母而列入 `unreadable`——"读不了"是未测量，不是不达标。

## 词表校准（中文 release 的质量闭环）

中文词表是**策展词表**（无公开可再分发的 Hyland 对应资源，见 issue #11 B 组结论），所以它必须能被质疑、被度量。`scripts/lexicon_calibration.py` 提供四步：

```bash
cd ~/.claude/skills

# ① 抽标注表（确定性分层抽样：P = 词表命中的句子 / N = 未命中的对照句）
uv run python paper-metrics/scripts/lexicon_calibration.py sample \
    --corpus <paper-analysis> --out <dir> --lexicon hedge --positives 120 --negatives 80

# ② 人工在 TSV 的 annotator_a（第二次独立标注写 annotator_b）填 y/n

# ③ 打分：精确率 + 漏检率 + Wilson 区间；两次标注齐了才给 Cohen κ
uv run python paper-metrics/scripts/lexicon_calibration.py score \
    --sheets <dir>/_calibration_hedge.tsv --out <dir> --lexicon hedge --method human

# ④ 零人工效度证据：集中度 / 敏感性 / 区分度（不需要任何人标注）
uv run python paper-metrics/scripts/lexicon_calibration.py validate \
    --corpus <paper-analysis> --out <dir> --lexicon hedge --leave-out-pct 20 --subsets 5

# ⑤ 逐条目审计：哪些条目在真实语料里从不触发（改进词表的直接证据）
uv run python paper-metrics/scripts/lexicon_calibration.py audit \
    --corpus <paper-analysis> --out <dir> --lexicon booster

# ⑥ 候选挖掘：高频 CJK n-gram 中不在任何词表里的串（机器提议、人确认）
uv run python paper-metrics/scripts/lexicon_calibration.py mine \
    --corpus <paper-analysis> --out <dir> --min-count 15
```

**什么时候真的需要人工标注**：只有"把数字当绝对结论"时才需要——写进论文、对外声称某刊"hedge 密度是 X"，或要开 INFERRED 层（语步/引用功能/论证图，那些没有规则可审）。**自用的闭环（同一词表量语料和草稿）不需要**：偏差两边对称，比较自洽。`validate` 的敏感性数据正是这个设计选择的证据（见下）。

**纪律**：

- 抽样是**确定性**的（stride 抽样，无 RNG），同语料同配额必然得到同一张表；表头记录词表指纹，分数不会被张冠李戴到别的 release；
- `--method model` 的标注是**预标注**，报告会写明"不是金标准"并**拒绝给出 κ 结论**（κ 需要两次独立人工）；
- 打分**不改词表**。改词表 = 改 release（`source` 字段写证据 + `LEXICON_VERSIONS` 同步 bump 八个文件），八个文件版本不一致会被 loader 直接拒绝。

**已做的证据化修订（release 2.0-zh → 2.1-zh）**：审计 10 篇 / 1013 句发现 booster 里 `所有` 是最强命中（54 次）——但它是**量化词**，计的是内容分布而非作者确信度，会让 `M-BOO-15` 失去语义。据此移出 4 个纯量化词（所有/全部/广泛/大量），语料均值 0.0044 → **0.0031**；其余指标不变。未触发的 hedge 条目（也许/似乎/建议…）**一律保留**：它们是通用学术模糊限制语，按单一子领域语料删条目会让词表过拟合。

## 环境与依赖

- **A 类（统一共享环境）**：纯 stdlib（Python 3.10.12），共享仓库根 `.venv`（`paper-metrics/.venv -> ../.venv`）。
- **零第三方依赖、零 LLM token、零 GPU**；无外部二进制依赖。
- 词表数据：`data/lexicons/v1/`（英文，8 个 JSON）、`data/lexicons/v2-zh/`（中文，同样 8 个），均含版本、source 与 sha256 自校验；loader 按语言加载（`load_lexicons(language=...)`），产物记录实际用到的 release 指纹（`toolchain.lexicon_releases` / `lexicons_by_language`）。

## 测试

```bash
cd ~/.claude/skills && uv run pytest paper-metrics/scripts -q
```

## 语料登记与结果审计

指标值只有在能说清"**哪份输入 + 哪版代码**"时才可审计。两个语料已登记，审计随时可跑：

```bash
cd ~/.claude/skills
uv run python paper-metrics/scripts/audit_corpus.py --name vrp-en  --out /tmp/audit-en   # 英文基线
uv run python paper-metrics/scripts/audit_corpus.py --name ycgl-zh --out /tmp/audit-zh   # 中文语料
```

- 登记表：`data/test-corpora.json`（机器可读）+ `references/test-corpora.md`（获取方式与已知缺陷）；
- 审计比对三样：**corpus_id**（输入内容哈希）、**expected_metrics**（语料均值）、**recorded_with**（profiler / schema / 指标层 / 词表 release 版本与指纹）；
- 退出码 0 = 逐项 match，1 = drift，并给出归因：`inputs_changed`（输入变了，旧结论作废）/ `code_or_word_list_changed`（语料没变，版本或词表变了，数值移动可解释）/ **`unexplained_drift`（都没变数值却变了 → 确定性被破坏，必须查）**；
- 当前状态：英文 **22/22 match**、中文 **23/23 match**；
- `toolchain.text_metrics_version` 记录指标层版本（此前缺失，数字无法归属版本）；非英文语料的词表 release 记录在 `toolchain.lexicon_releases[lang]`，注意 `toolchain.lexicon_version` 这个历史字段记的**是英文 release**。

## 文件

```
paper-metrics/
├── SKILL.md                     # 本文
├── scripts/                     # profile_papers / text_metrics / lexicon_loader / build_contract
│                                # validate_draft / baseline_eval / run_pipeline / pas_spotcheck
│                                # lexicon_calibration（词表校准+效度）/ audit_corpus（语料审计）
├── data/
│   ├── lexicons/v1/             # 英文 8 个冻结词表（release 1.1）
│   ├── lexicons/v2-zh/          # 中文 8 个冻结词表（release 2.1-zh，策展）
│   └── test-corpora.json        # 测试语料登记表（审计入口）
├── references/
│   ├── metric-definitions.md    # 指标定义/口径/证据坐标系/不能推断什么
│   └── test-corpora.md          # 语料获取方式、已知缺陷、复现命令
└── .venv -> ../.venv            # A 类共享环境
```
