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

## 指标定义（可解释性的事实源）

- 每条指标的定义、公式、分母、evidence 坐标系，以及**不能推断什么**，见 `references/metric-definitions.md`。
- `n_valid < 5` 时**禁止**断言"该期刊偏好 X"；只能呈现单篇表并说明样本不足。
- 禁止任何"87/100"式百分制综合分：只输出逐指标实际值、目标区间与偏差。

## 环境与依赖

- **A 类（统一共享环境）**：纯 stdlib（Python 3.10.12），共享仓库根 `.venv`（`paper-metrics/.venv -> ../.venv`）。
- **零第三方依赖、零 LLM token、零 GPU**；无外部二进制依赖。
- 词表数据：`data/lexicons/v1/`（8 个 JSON，含版本与 sha256 自校验）。

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
