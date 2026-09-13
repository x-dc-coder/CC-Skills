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

## 支持的语言（红线：不支持就**显式失败**，绝不给假数字）

- **英文（en）**：14 条指标全部可测，词表用 `data/lexicons/v1/`。
- **中文（zh）是逐指标能力，不是一刀切门禁（2026-09-13，issue #13）**：
  - **已可测 12/14 条**：`M-SLEN-01`、`M-LSF-16`、`M-MTLD-02`、`M-HED-14`、`M-BOO-15`、`M-CONN-30(c/k/r)`、`M-AWR-03`、`M-PAS-09`、`M-PCNT-25`（词表用 `data/lexicons/v2-zh/`）；
  - **尚不可测 2 条**：`M-NOM-10`（中文名词化无法用"后缀+动词基"规则可靠判定，需标注集）、`M-TENSE-28`（**中文没有时态**，给数字就是编造）→ `null` + **`CAPABILITY_NOT_SUPPORTED`**（`LANGUAGE_NOT_SUPPORTED` 的逐指标版本；**仍然不是 0**）；
  - **中文口径（与英文不可混用，跨语言不可比）**：句长单位 **`cjk-units/sentence`**（汉字数 + ASCII 字母 token，混合句不漏计）；长句阈值 **80 单位**（不是英文的 40 词）；密度类分母为 **cjk-units**、连接词单位 **`per-1000-cjk-units`**；段落单位 **`cjk-units/paragraph`**（下限 40 单位）；`M-MTLD-02` 是 **字符级**（`tokenization=cjk-char+ascii-token`，与英文词级值不可比）；
  - 分句支持 `。！？…`；`……` 这类终止符连写只结一次；引号内的句号留在句中；**`；` 不切句**（中文在句内使用）；片段过滤要求"无字母**且**无 CJK"才丢弃；
  - 被动用中文标记规则（`被/受到/得到/加以/予以` + 后接汉字）；连接词三组**联合最长匹配**，保证 `M-CONN-30 = 30c + 30k + 30r` 严格成立；
  - 能力矩阵的唯一事实源是 `text_metrics._METRIC_LANGUAGE_CAPABILITY`；**中文词表是策展词表**（无公开可再分发的对应资源，见 `data/lexicons/v2-zh/*.json` 的 source 字段）。
- **元数据层也已支持中文（issue #10 首步）**：引用样式识别认全角 `［N］`，参考文献计数认无空格的中文条目与 GB/T 7714 文献类型标记。
- 每篇都会算 `cjk_ratio = 汉字数 / (汉字数 + ASCII 字母 token 数)`，**`cjk_ratio > 0.10` 判为中文**（阈值与实现见 `text_metrics.detect_language`）。
- **没有规则的语篇**（既不是 en 也不是 zh）：**每一个指标输出 `null`**（`n = 0`、`warnings = ["LANGUAGE_NOT_SUPPORTED"]`），计入 `n_missing`，并在语料级触发 `CORPUS_LANGUAGE_UNSUPPORTED` 告警；**任何情况下不得用 0 代替"未测量"**。
- 草稿校验：**能力感知**（issue #13）——逐条判定，测不了的指标以 `capability_not_supported` 跳过并说明原因；只有"没有任何规则的语言"才整体拒绝（退出码 2 `language_unsupported`）；中文草稿的有效性门槛用 **cjk-units（≥150）**，不是 ASCII 词数。
- 为什么这条是红线：在真实中文语料上，本层曾**静默**产出 `citation_style=unknown`、`reference_count=0`、hedge/连接词/被动/名词化**全为 0.0**、句数中位 **2 句**，而 `n_missing` 全为 0、无任何语言告警——看起来像"合法结果"，实际是垃圾。证据：`/mnt/e/AllProjects202601/M-PCA/_paper-metrics-run/运筹与管理/报告.md`。
- 中文支持路线见 GitHub issue #10；中文词表/标注集等缺口见 issue #11 的评审意见。

## 指标定义（可解释性的事实源）

- 每条指标的定义、公式、分母、evidence 坐标系，以及**不能推断什么**，见 `references/metric-definitions.md`。
- `n_valid < 5` 时**禁止**断言"该期刊偏好 X"；只能呈现单篇表并说明样本不足。
- 禁止任何"87/100"式百分制综合分：只输出逐指标实际值、目标区间与偏差。

## 环境与依赖

- **A 类（统一共享环境）**：纯 stdlib（Python 3.10.12），共享仓库根 `.venv`（`paper-metrics/.venv -> ../.venv`）。
- **零第三方依赖、零 LLM token、零 GPU**；无外部二进制依赖。
- 词表数据：`data/lexicons/v1/`（英文，8 个 JSON）、`data/lexicons/v2-zh/`（中文，同样 8 个），均含版本、source 与 sha256 自校验；loader 按语言加载（`load_lexicons(language=...)`），产物记录实际用到的 release 指纹（`toolchain.lexicon_releases` / `lexicons_by_language`）。

## 测试

```bash
cd ~/.claude/skills && uv run pytest paper-metrics/scripts -q
```

## 文件

```
paper-metrics/
├── SKILL.md                     # 本文
├── scripts/                     # profile_papers / text_metrics / lexicon_loader / build_contract
│                                # validate_draft / baseline_eval / run_pipeline / pas_spotcheck
├── data/lexicons/v1/            # 8 个冻结词表
├── references/metric-definitions.md
└── .venv -> ../.venv            # A 类共享环境
```
