---
name: paper-reader
description: >
  学术论文 PDF 双引擎对照阅读器 — 四阶段流水线（预检→转换→合并→总结）。
  Marker + MinerU 双引擎并行转换，自动合并、差异对照、文献总结。
  内置 PDF 预检、异常处理三级响应、断点续跑、流水线状态追踪。
---

# Paper Reader — 四阶段论文分析流水线

## 流水线四阶段

```
源PDF目录                 转换目录                  合并目录                 文献总结
papers/              paper-conversion/         paper-merged/           paper-summaries/
    │                      │                        │                       │
    ▼                      ▼                        ▼                       ▼
┌────────┐   ┌──────────────────────┐   ┌──────────────────┐   ┌──────────────────┐
│ 预检    │──▶│ Marker + MinerU 并行  │──▶│ 合并 + 差异对照    │──▶│ LLM 生成结构化总结 │
│ 秒级    │   │ ~6 分钟/篇            │   │ ~2 秒             │   │                  │
└────────┘   └──────────────────────┘   └──────────────────┘   └──────────────────┘
```

## 何时使用（必须用）

- 用户提到"读论文"、"读 PDF"、"分析文献"、"精读"、"对照阅读"
- 用户给出 PDF 路径，需要分析其中方法、公式、实验、图表
- 批量处理目录中所有 PDF

**不要用此 skill 处理**：纯文本 PDF（小说、合同）、扫描件 OCR 单一诉求（直接用 MinerU 单路）、单页快速摘要（用 `look_at` 即可）。

## 输出目录结构（v2 四层架构）

```
<papers_dir>/                          # 源 PDF 目录
├── _pipeline_state.json               # ⭐ 流水线状态 → git 跟踪
├── _download_manifest.json            # 搜索桥接文件 → git 跟踪
├── paper-conversion/                  # 阶段1: 转换 → gitignore
│   └── <stem>/
│       ├── marker/                    # Marker 原始输出（含图片）
│       │   ├── <stem>.md
│       │   └── *.jpeg
│       └── mineru/                    # MinerU 原始输出（含图片）
│           └── auto/
│               ├── <stem>.md
│               └── images/*.jpg
├── paper-merged/                      # 阶段2: 合并 → gitignore（可从 PDF 重现）
│   └── <stem>/
│       ├── images/                    # 从两引擎复制的 Figure 图片（自包含）
│       ├── _MERGED.md                 # 合并版 Markdown
│       ├── _DIFF.md                   # 差异对照
│       └── _META.json                 # 转换元数据（含 pdf_sha256 + engine_versions 溯源）
└── paper-summaries/                   # 阶段3: 文献总结 → git 跟踪
    └── <stem>.md                      # 结构化总结（含期刊等级）
```

### 各层 git 策略

| 目录 | 内容 | git | 理由 |
|---|---|---|---|
| `papers/` | 源 PDF | ✅ 跟踪 | 源文件，不可重现 |
| `_pipeline_state.json` | 状态 + URL | ✅ 跟踪 | 追踪进度，含分析决策 |
| `_download_manifest.json` | 搜索元数据 | ✅ 跟踪 | 论文来源信息快照 |
| `paper-conversion/` | 引擎原始输出 | ❌ ignore | 可从 PDF 重现 |
| `paper-merged/` | 合并产物 | ❌ ignore | 可从 PDF 重现 |
| `paper-summaries/` | LLM 总结 | ✅ 跟踪 | 含主观分析，每次不同 |

### 图片策略

合并阶段从两引擎复制 **仅 Figure 类型图片** 到 `paper-merged/<stem>/images/`：
- **MinerU**: 解析 `content_list.json`，过滤 `type == "image"` 的真正图片
- **Marker**: 无类型分类信息，全部复制（每篇约 14 张，可接受）

公式/表格图片备份留在 `paper-conversion/` 不复制（LaTeX/HTML 已在 md 中，图片冗余）。

## 快速开始

```bash
# === 初始化流水线状态 ===
# 扫描 papers/ 目录，计算 hash，创建 _pipeline_state.json
paper_reader.py papers/ --init

# 从搜索桥接文件自动填入 URL/元数据
paper_reader.py papers/ --init --from-manifest _download_manifest.json

# === 查看流水线状态 ===
paper_reader.py papers/ --status

# === 处理论文 ===
# 基础用法（默认双引擎 + 断点续跑）
paper_reader.py papers/ --batch --resume

# 强制重做某篇
paper_reader.py papers/2605.05208.pdf --force

# 单引擎（快速摘要）
paper_reader.py papers/ --engines marker --resume

# 指定页范围
paper_reader.py papers/2605.05208.pdf --pages 0-4

# 资源限制
paper_reader.py papers/ --batch --resume --max-workers 1 --gpu-fraction 0.5

# 给"已转换过"的语料回填溯源信息（不重跑任何引擎）
paper_reader.py papers/ --backfill-meta
```

## 流水线状态文件

`_pipeline_state.json` 跟踪每篇论文的处理进度：

```json
{
  "pipeline_version": "2.0",
  "last_updated": "2026-07-18T15:30:00",
  "papers": {
    "2605.05208": {
      "source": {
        "url": "https://arxiv.org/abs/2605.05208",
        "pdf_url": "https://arxiv.org/pdf/2605.05208",
        "doi": "10.1109/xxx",
        "arxiv_id": "2605.05208",
        "source_db": "arxiv",
        "title_from_source": "MDVRP: A Multi-Depot...",
        "venue": "Transportation Science",
        "year": 2026,
        "authors": ["Lei, H.", "Smith, J."]
      },
      "pdf_hash": "sha256:abc123...",
      "precheck": {"status": "passed", "page_count": 40},
      "phase1_converted": {
        "status": "done",
        "marker_ok": true,
        "mineru_ok": true,
        "at": "2026-07-15T10:23:00"
      },
      "phase2_merged": {
        "status": "done",
        "diff_paragraphs": 66,
        "images_copied": 22,
        "at": "2026-07-15T10:23:05"
      },
      "phase3_summarized": {
        "status": "done",
        "summary_path": "paper-summaries/2605.05208.md",
        "at": "2026-07-16T09:00:00"
      }
    }
  }
}
```

### 状态字段说明

| 字段 | 值 | 含义 |
|---|---|---|
| `status` | `pending` | 未处理 |
| | `passed` | 预检通过 |
| | `done` | 阶段成功完成 |
| | `degraded` | 部分成功（如单引擎可用） |
| | `skipped` | 因上游失败而跳过 |
| | `failed` | 本阶段执行失败 |
| | `interrupted` | 被 Ctrl+C 中断 |

## 溯源字段（_META.json）

每篇转换完成时写入 `_META.json`，供上层（如 `thesis-writing` 领域画像器）判断**漂移来自哪一版引擎**——缺这些字段时上层只能报"引擎版本未记录"。

| 字段 | 含义 |
|---|---|
| `pdf_sha256` | 源 PDF 完整 SHA-256；算不出写 `null`（原因见 `pdf_sha256_note`） |
| `engine_versions` | 固定含 `marker` / `mineru` / `torch` / `cuda` / `python` 五个键，取不到写 `null`（**不省略键**） |
| `engine_versions_source` | `conversion_time`（转换时实测）\| `current_env_estimate`（回填估计）\| `unavailable`（探测失败） |
| `engine_versions_note` | 失败原因或回填说明；成功为 `null` |
| `pdf_sha256_note` | 源 PDF 定位/失败说明；正常为 `null` |

约束：

- 版本探测**每批只做一次并缓存**（探测各引擎 venv 的解释器；WSL 下经桥接取 Windows 侧解释器）。
- 单项失败只留 `null` + note，**绝不抛异常、绝不阻塞转换**（探测有超时上限，超时保留已产出的部分结果）。
- `pdf_sha256` 复用预检阶段的读取，不额外全量读盘。

**`pdf_sha256` 的来源等级（可信度分层，issue #7）**——同一个字段可能是三种东西，引用时必须说明是哪一级：

| 等级 | 何时出现 | 能证明什么 | 不能证明什么 |
|---|---|---|---|
| **原始投稿 PDF** | 预检时源 PDF 仍在磁盘、可直接读取 | 投稿时那份字节的身份（可用于跨项目比对同一篇 PDF） | 不能证明转换产物与其一致 |
| **引擎侧副本**（`*_origin.pdf`，同时写 `note`） | 原始 PDF 已不在磁盘，只能对引擎保存的副本取哈希 | 只能证明**当前这份产物**的身份（自洽与幂等） | **不能**回指投稿原件；与原件可能不同字节 |
| **`null`** | 上述两者都取不到 | 无 | 无（原因见 `pdf_sha256_note`，不得当 0 或空串处理） |

`engine_versions_source` 同理分三级：`conversion_time`（转换当时写入，可证明转换环境）> `current_env_estimate`（回填估计，**不得当作转换时实测**）> `unavailable`（探测失败）。`--backfill-meta` **只补写缺失字段，绝不覆盖已有 `conversion_time`**（`test_backfill_never_touches_conversion_time_record` 锁定）。实测分布（运筹与管理语料 66 个 `_META.json`）：`conversion_time` 11 篇、`current_env_estimate` 36 篇。

### 回填既有语料（`--backfill-meta`）

已转换过的语料重新转换代价过高（约 6 分钟/篇）。`--backfill-meta` 只补写缺失的溯源字段，**不重跑引擎**：

```bash
paper_reader.py <papers_dir> --backfill-meta
```

- 扫描 `<papers_dir>/paper-analysis/*/_META.json`（v1 语料）与 `<papers_dir>/paper-merged/*/_META.json`（v2 产物）。
- **幂等**：只补缺失字段；已有 `conversion_time` 实测记录一律不动；内容无变化则不重写文件。
- **诚实标注**：回填的版本写 `engine_versions_source = "current_env_estimate"`，note 明说"该论文转换于回填之前，版本为当前环境估计值，非转换时实测"；算不出源 PDF 时 `pdf_sha256 = null` 并在 note 说明。

## 预检（Phase 0：秒级，不启动 GPU）

在处理前自动验证 PDF 有效性，防止坏文件浪费 GPU 资源：

| 检查项 | 检测方式 | 失败动作 |
|---|---|---|
| 文件存在 | `pdf_path.exists()` | SKIP → 标记 `file_missing` |
| 非空文件 | `size ≥ 1KB` | SKIP → 标记 `empty_file` |
| PDF 格式 | magic bytes `%PDF-` | SKIP → 标记 `not_a_pdf` |
| 密码保护 | `pypdf.PdfReader.is_encrypted` | SKIP → 标记 `encrypted` |
| 结构损坏 | `pypdf` 读取抛异常 | SKIP → 标记 `corrupted` |
| 页数超限 | 默认 200 页上限 | SKIP → 标记 `too_large` |
| 扫描件检测 | 前 10 页 text 层检查 | DEGRADE → 警告，建议 MinerU OCR |

## 文本层探针（阶段 1.5：秒级、无模型、无 GPU）

`scripts/textlayer_probe.py` 独立复算 PDF 自带文本层的字符/数字/标点，与 canonical 文本对比，产出 `_textlayer_probe.json`。

**它存在的唯一理由**：`PDF → content_list.json` 这一跳**没有任何独立校验**，而这里会发生两类**静默损坏**（不报错、不告警，直接污染下游指标）。

### 本机实测（《运筹与管理》10 篇中文核心期刊，2026-09-13）

| 损坏类型 | 实测结果 |
|---|---|
| **数字丢失（CNKI 全角字体）** | **10/11 篇命中，丢失率 73 %–90 %**（此前估计 ~52 %，实测更严重）。CNKI 把数字编码成全角 `１２.７３`，PDF 文本层里有、转换后消失（MinerU issue #5330） |
| **英文段空格丢失** | **8 篇命中**：PDF 文本层 **0** 条 15+ 字母长串，canonical 侧 **58** 条 → **空格是转换过程弄丢的**，不是 PDF 本身的问题 |

### 判定规则（`compare_text_layers`，纯函数、可单测）

| verdict | 条件 | 含义 |
|---|---|---|
| `not_applicable` | 文本层 < 200 字符 | 扫描件，**不是"测到 0"** |
| `pdf_only` | 未提供 canonical 文本 | **没对照过就不算通过**（禁止报 `ok`） |
| `warn` | `digit_loss_rate > 2 %` 或 `unspaced_runs_introduced > 2` | 给出 `DIGIT_LOSS_HIGH` / `UNSPACED_ENGLISH_RUNS` |
| `ok` | 上述都不触发 | — |

关键设计：空格丢失用**两侧之差**判定（`canonical - pdf`），因为"长串数量多"可能只是原文真有长复合词；**差值 > 0 才说明是转换引入的**。

### 红线

- **产物绝不喂给 `canonical_text()`**——旁路证据，`paper-metrics` 的纯 stdlib / 零 LLM / 逐字节契约不受影响（实测：同一英文语料改动前后 `_per_paper_metrics.jsonl` **逐字节相同**）；
- 只用无模型、无 GPU 的宽松许可库（`pdfplumber` MIT）；**不要**在这里引入 PyMuPDF（AGPL）；
- 探针失败**绝不阻塞**转换流水线（异常一律降级为 `not_applicable` + `TEXT_LAYER_UNREADABLE`）；
- 同输入两次运行 JSON **逐字节一致**（键排序、无时间戳、只记文件名不记绝对路径）。

### 用法

```bash
cd ~/.claude/skills && uv run python paper-reader/scripts/textlayer_probe.py \
    --pdf paper.pdf --canonical canonical.txt --out _textlayer_probe.json
```

## 引擎与许可（红线）

| 引擎 | 代码许可 | 权重许可 | 备注 |
|---|---|---|---|
| **MinerU** | Apache-2.0 **+ 附加条款** | **AGPL-3.0**（MinerU2.5-2509-1.2B VLM 权重） | 附加条款：MAU > 1 亿或月营收 > 2000 万美元需商业许可；**提供在线服务须署名 MinerU** |
| **Marker 2.0** | Apache-2.0 | Apache-2.0 | v1.x 曾是 GPL-3.0，2.0 起改为 Apache-2.0 |
| **Surya**（经 Marker 引入） | Apache-2.0 | **modified AI Pubs OpenRAIL-M（非 OSI）** | **免费商用仅在融资/营收低于阈值时成立**；它已随 Marker 2.0（`Requires-Dist: surya-ocr>=0.22.1`）进入流水线，因此**必须**与版本一起记录 |
| **PyMuPDF** | **AGPL-3.0** | — | **本技能不使用**（会污染发布路径）；文本层探针改用 MIT 的 `pdfplumber` |

`_META.json` 里：

- `engine_versions` 含 **`marker / mineru / surya / torch / cuda / python`** 六个键（**取不到写 `null`，不省略键**）；
- `engine_license_ids` 记录上表的许可标识——**版本号本身看不出"Surya 权重是 OpenRAIL-M"**，所以许可与版本同行记录。

### venv 布局

- **在用**：`venvs/marker/`（当前 Marker，surya 0.22.1）、`venvs/mineru/`；
- `venvs/marker-v1.10.2/`：**遗留 pinned venv，仓库代码从未引用**（其中 surya 是 0.17.1）。它与在用 venv 是**两套独立环境**，**不是同一环境里的重复 dist-info**——保留或删除需人工决定，不要当垃圾清理。

## 异常处理（三级响应）

| 级别 | 含义 | 行为 | 示例 |
|---|---|---|---|
| **FATAL** | 环境级，继续无意义 | 终止整个运行 | 磁盘满、输出目录不可写 |
| **SKIP** | 此 PDF 不可处理 | 跳过，标记，继续下一个 | 损坏 PDF、密码保护、两引擎都失败 |
| **DEGRADE** | 部分可用 | 继续下游降级处理 | Marker OK 但 MinerU OOM |

### 各阶段异常表

#### Phase 1: 转换

| 异常 | 级别 | 降级策略 |
|---|---|---|
| Marker 失败（OOM/超时/崩溃） | DEGRADE | 单路 MinerU → merged 直接用 MinerU md |
| MinerU 失败 | DEGRADE | 单路 Marker → merged 直接用 Marker md |
| 两引擎都失败 | SKIP | 标记 failed，跳过此 PDF |
| GPU 预算不足被跳过 | SKIP | 标记 `gpu_budget_unavailable` |

#### Phase 2: 合并

| 异常 | 级别 | 降级策略 |
|---|---|---|
| 仅单引擎可用 | DEGRADE | 直接拷贝该引擎输出作为 merged |
| 归一化崩溃 | SKIP | 保留原始输出，标记 failed |
| 图片复制失败 | DEGRADE | merged md 仍生成，图片回退到相对引用 |
| 写入失败 | FATAL | 磁盘满或其他 I/O 问题 |

## 搜索桥接文件（与 unified-search 联动）

`_download_manifest.json` 存放论文的来源信息，由搜索阶段产生、paper-reader 读取：

```json
{
  "generated_by": "unified-search",
  "query": "MDVRP vehicle routing GPU acceleration",
  "generated_at": "2026-07-18T15:00:00",
  "papers": [
    {
      "filename": "2605.05208.pdf",
      "arxiv_id": "2605.05208",
      "title": "MDVRP: A Multi-Depot Vehicle Routing Problem with...",
      "url": "https://arxiv.org/abs/2605.05208",
      "pdf_url": "https://arxiv.org/pdf/2605.05208",
      "doi": "10.1109/xxx",
      "venue": "Transportation Science",
      "year": 2026,
      "authors": ["Lei, H.", "Smith, J."],
      "source_db": "arxiv"
    }
  ]
}
```

`--init --from-manifest` 按 `filename` 匹配，自动填入 `_pipeline_state.json` 的 `source` 字段。
若论文损坏需要重新下载，`source.url` / `source.pdf_url` 可直接用于定位。

## 文献总结模板

总结 md 包含以下结构（Phase 3 由 LLM 基于 MERGED.md 生成）：

```markdown
# <论文标题>

## 元信息
| 字段 | 值 |
|---|---|
| 作者 | ... |
| 年份 | ... |
| 期刊/会议 | ... |
| **期刊等级** | **CCF-A / CCF-B / CCF-C / SCI一区 / SCI二区 / 顶会 / 预印本** |
| DOI | ... |

## 一句话摘要
...

## 研究问题与动机
...

## 方法论
...

## 核心贡献
...

## 实验与结论
...

## 局限与未来工作
...

## 与我方研究的关联度
- 技术相关性：高/中/低
- 可复用的技术点

## 阅读笔记
- 亮点
- 疑问/待深入
```

期刊等级标注规则：
- CCF 推荐列表 → `CCF-A` / `CCF-B` / `CCF-C`
- 中科院分区 → `SCI一区` / `SCI二区` / `SCI三区`
- 顶会 → 标注会议名 + CCF 等级
- arXiv 预印本 → `预印本（未发表/在审）`

## 双引擎设计原理

| 引擎 | 出品方 | 强项 | 弱项 |
|---|---|---|---|
| **Marker** | Vik Paruchuri | 英文 OCR 准、结构清晰 | 公式 LaTeX 不完整 |
| **MinerU** | OpenDataLab | 公式 LaTeX 准、表格强 | 偶有 OCR 错位 |

## 合并策略（_MERGED.md）

| 内容类型 | 来源 | 原因 |
|---|---|---|
| 正文段落（相似度 ≥ 0.85） | Marker | 英文 OCR 更准 |
| 公式段落（相似度 < 0.85） | MinerU | 公式更准 |
| Marker 独有段落 | Marker | 补充通讯信息 |
| MinerU 独有段落 | MinerU | 保留额外内容 |

### LLM 友好后处理

1. **OCR 错误修复**：ff→f 常见错误自动纠正
2. **LaTeX 间距修复**：`\mathrm{M i n i m i z e}` → `\mathrm{Minimize}`
3. **HTML 表格转 Markdown**：`<table>` → `| ... |`
4. **表格恢复**：从 Marker 恢复被归一化的表格
5. **图片索引**：末尾列出所有图片路径
6. **YAML front matter** + 标题 + 摘要 + 目录

## Diff 算法

7 步归一化后再比较（消除格式噪声）：
1. 统一引号（curly → straight）
2. 统一标题层级
3. `<sup>x</sup>` → `^x^`，行内公式提取纯文本
4. 合并 `$$...$$` 块
5. 合并连续非空行为段落 + 跨段断行合并
6. 图片/HTML 表格归一化为占位符
7. 过滤元信息行

然后用贪心最优配对 + 相似度阈值（0.85）分类：
- ≥ 0.85 → `[SAME]` 仅标注字符差异
- < 0.85 → `[DIFF]` 真实内容差异
- 仅一侧 → `[ONLY-M]` / `[ONLY-U]`

## 性能预期

- 40 页论文，双引擎并行：~6 分钟
- 10 页，Marker 单路：~30 秒
- 预检：< 1 秒

## 故障排查

| 症状 | 原因 | 解决 |
|---|---|---|
| `[SKIP] encrypted` | PDF 密码保护 | 用 `source.url` 重新下载未加密版本 |
| `[SKIP] not_a_pdf` | 文件非 PDF 格式 | 检查下载源 |
| `[SKIP] corrupted` | PDF 结构损坏 | 用 `source.pdf_url` 重新下载 |
| `[DEGRADE] MinerU OOM` | 显存不足 | `--max-workers 1 --gpu-fraction 0.5` |
| `[SKIP] gpu_budget_unavailable` | 其他 GPU 任务占满 | 等待或 `--gpu-cap-fraction 0` |
| 批量中断 | Ctrl+C | 已完成的保留，`--resume` 续跑 |

## 资源限制（防 OOM）

默认四层防护：
- ① 单进程 GPU 显存配额 40%
- ② 单进程 CPU 线程上限 6
- ③ 批量串行（1 PDF）
- ④ 设备级协调器（总显存 ≤ 90%）

详见 `/home/dc/CLAUDE.md` "GPU 多路并发铁律"。

## 文件

```
paper-reader/
├── SKILL.md                    # 本文
├── scripts/
│   ├── paper_reader.py         # 主脚本（流水线编排 + CLI）
│   └── bootstrap.sh            # 重装 venvs
├── venvs/
│   ├── marker/                 # Marker 独立 Python 环境
│   └── mineru/                 # MinerU 独立 Python 环境
└── data/                       # 预留缓存目录
```
