---
name: paper-reader
description: >
  学术论文 PDF 双引擎对照阅读器。同时调用 Marker + MinerU 两个引擎转换 PDF，
  输出双路 Markdown 用于交叉对照阅读，降低单一引擎的解析错误。
  当用户提到"读论文"、"读 PDF"、"分析文献"、"精读"、"对照阅读"，
  或给出 PDF 路径需要分析其中方法、公式、实验、图表时，必须使用此 skill。
  处理学术论文（含数学公式、表格、流程图）时优先使用。支持单 PDF 或目录批量转换。
  不要用于纯文本 PDF（小说、合同）、扫描件 OCR 单一诉求（直接用 MinerU 单路）、
  单页快速摘要（用 look_at 即可）。
---

# Paper Reader

**学术论文 PDF 双引擎对照阅读器** — 同时调用 Marker + MinerU 两个引擎转换 PDF，输出双路 Markdown
用于交叉对照阅读，降低单一引擎的解析错误。

## 何时使用（必须用）

- 用户提到"读论文"、"读 PDF"、"分析文献"、"精读"、"对照阅读"
- 用户给出 PDF 路径，需要分析其中方法、公式、实验、图表
- 处理学术论文（含数学公式、表格、流程图）时**优先使用此 skill**
- 给定一个目录，批量转换其中所有 PDF（如 VRP-GPU课题分析/papers/）

**不要用此 skill 处理**：纯文本 PDF（如小说、合同）、扫描件 OCR 单一诉求（直接用 MinerU 单路）、
单页快速摘要（用 `look_at` 即可）。

## 双引擎设计原理

| 引擎 | 出品方 | 强项 | 弱项 | 用途 |
|---|---|---|---|---|
| **Marker** | Vik Paruchuri | 速度快、Markdown 编辑性好、`<sup>` 标签整洁 | 公式 LaTeX 化不完整 | 主路：稳定、清晰、可读 |
| **MinerU** | OpenDataLab | 公式 LaTeX 准确（`\mathcal{G}` 等）、表格识别强 | 偶有 OCR 字符错位 | 副路：补公式/表格细节 |

两者并行运行后输出：
- `marker/` 和 `mineru/` 两份原始 Markdown
- `_MERGED.md` **合并版**（以 MinerU 为主版，Marker 补充缺失段落，取各自 OCR 优势）
- `_DIFF.md` 智能对照（归一化 + 模糊匹配，仅显示真实内容差异）
- `_META.json` 含两路耗时、文件大小、图片分类统计、差异段落数

## 合并策略（_MERGED.md）

合并目标：生成单个最适合 LLM 读取的 Markdown 文件。

### 内容来源选择

| 内容类型 | 来源 | 原因 |
|---|---|---|
| **正文段落**（相似度 ≥ 0.85） | Marker | 英文 OCR 更准（`effective` vs `efective`） |
| **公式段落**（相似度 < 0.85） | MinerU | 公式识别更准（`\mathcal{G}` 等） |
| **Marker 独有段落** | Marker | 补充 MinerU 省略的通讯信息 |
| **MinerU 独有段落** | MinerU | 保留 MinerU 识别到的额外内容 |

### 5 步 LLM 友好后处理

1. **OCR 错误修复**：自动纠正 15 个常见 ff→f 错误（`ofspring`→`offspring`、`diferent`→`different`、`efective`→`effective` 等）
2. **LaTeX 间距修复**：`\mathrm{M i n i m i z e}` → `\mathrm{Minimize}`；`\mathcal { G }` → `\mathcal{G}`
3. **HTML 表格转 Markdown**：`<table><tr><td>...</td></tr></table>` → `| ... | ... |`（LLM 更易理解）
4. **表格恢复**：把归一化时被替换的 `[TABLE]` 标记替换回 Marker 原始 Markdown 表格内容
5. **图片索引**：末尾附加 `## Images Index`，列出所有图片路径（Marker 14 张 + MinerU 18 张引用）
6. **LLM 友好元数据头**：YAML front matter + 标题 + 作者 + 摘要 + 目录

### 效果指标（Lei & Hao 2026 MDVRP 论文，40 页）

| 指标 | 改进前 | 改进后 |
|---|---|---|
| OCR 错误（ofspring 等） | 42 处 | **0 处** |
| LaTeX 字母间距问题 | 2 处 | **0 处** |
| HTML 表格 | 12 处 | **0**（全转 Markdown） |
| Markdown 表格行 | 0 | **146 行**（从 Marker 恢复） |
| 图片引用 | 0（被归一化吞掉） | **32 张索引** |
| 结构标签 | 无 | **YAML 头 + 目录 + 25 章节** |
| 文件大小 | 89KB | 121KB |

## 图片提取差异说明

Marker 和 MinerU 提取的图片数量不同，**这是正常现象**：

| 引擎 | 提取内容 | 典型数量 |
|---|---|---|
| **Marker** | 仅提取真正的图片（Figure、Picture） | 14 张 |
| **MinerU** | 提取图片 + 公式图片 + 表格图片 + 图表图片 | 39 张 |

MinerU 的 `content_list.json` 会标注每张图片的类型：
- `image`: 真正的图片（Figure）
- `equation`: 公式片段（MinerU 同时输出 LaTeX 文本和图片备份）
- `table`: 表格片段（MinerU 同时输出 HTML 表格和图片备份）
- `chart`: 图表

`_META.json` 的 `img_breakdown` 字段会分类统计，例如：
```json
"img_breakdown": {"image": 8, "equation": 9, "table": 12, "chart": 10}
```

MinerU md 中只引用 `image` 类型的图片（8 张），其余 31 张是公式/表格的图片备份（LaTeX/HTML 已在 md 中，图片只是冗余存档）。

## Diff 算法（v2：归一化 + 模糊匹配）

直接行级 diff 会因格式差异产生大量噪声（一篇 40 页论文原始 diff 981 行）。
脚本做了 7 步归一化后再比较：

1. 统一引号（curly → straight）
2. 统一标题层级（`####` → `##`）
3. `<sup>x</sup>` → `^x^`，行内 `$x$` → `x`
4. 合并 `$$...$$` 块为单段（MinerU 切成三段）
5. 合并连续非空行为段落 + 跨段断行合并（小写字母结尾+小写字母开头）
6. 图片引用归一化为 `[IMAGE]`，HTML 表格归一化为 `[TABLE]`
7. 过滤元信息行（邮箱、通讯作者、DOI、URL）

然后用贪心最优配对（每个 Marker 段落找 MinerU 中相似度最高的段落）做模糊匹配：
- 相似度 ≥ 0.85 → `[SAME]` 仅标注字符级差异（如 OCR 拼写 `effective` vs `efective`）
- 相似度 < 0.85 → `[DIFF]` 真实内容差异，需人工裁决
- 仅一方有 → `[ONLY-M]` / `[ONLY-U]`

**效果**：981 行 → 166 段真实差异（降 83%），其中需人工看的 `[DIFF]` 仅 66 段。

## 快速开始

```bash
# 转换单个 PDF（双引擎对照）
# 默认输出到 <输入 PDF 所在目录>/paper-analysis/<pdf_stem>/
uv run ~/.claude/skills/paper-reader/scripts/paper_reader.py \
  /path/to/paper.pdf

# 显式指定输出目录
uv run ~/.claude/skills/paper-reader/scripts/paper_reader.py \
  /path/to/paper.pdf --output /tmp/pr_out

# 转换整个目录所有 PDF（默认输出到 <目录>/paper-analysis/）
uv run ~/.claude/skills/paper-reader/scripts/paper_reader.py \
  /path/to/papers_dir/ --batch

# 只用 Marker（快速摘要场景）
uv run ~/.claude/skills/paper-reader/scripts/paper_reader.py \
  paper.pdf --engines marker

# 只用 MinerU（扫描版/中文 PDF 场景）
uv run ~/.claude/skills/paper-reader/scripts/paper_reader.py \
  paper.pdf --engines mineru --mineru-method ocr

# 指定页范围（只转前 5 页快速过摘要）
uv run ~/.claude/skills/paper-reader/scripts/paper_reader.py \
  paper.pdf --pages 0-4

# 资源限制调优（防 OOM 卡死，默认值已合理，无需手动设）
# 最稳：单引擎串行 + 50% 显存
uv run ~/.claude/skills/paper-reader/scripts/paper_reader.py \
  paper.pdf --max-workers 1 --gpu-fraction 0.5
# 激进批量：2 PDF 并发（需 GPU ≥ 16GB）
uv run ~/.claude/skills/paper-reader/scripts/paper_reader.py \
  papers/ --batch --max-concurrent-pdfs 2 --gpu-fraction 0.2

# 用 read 工具读取输出（路径形如 paper-analysis/<stem>/marker/<stem>/<stem>.md）
# read paper-analysis/paper/marker/paper/paper.md
# read paper-analysis/paper/mineru/auto/paper.md
# read paper-analysis/paper/_DIFF.md
```

## 默认输出路径规则

不传 `--output` 时，自动写到**输入 PDF/目录的同级 `paper-analysis/` 目录**：

| 输入 | 默认输出 |
|---|---|
| `/path/to/papers/2605.05208.pdf` | `/path/to/papers/paper-analysis/2605.05208/` |
| `/path/to/papers/` (目录批量) | `/path/to/papers/paper-analysis/` |

## 工作流（推荐）

1. **快速过摘要**：`--pages 0-2 --engines marker` → 5 秒提取标题/摘要/引言
2. **决定要精读后**：`--engines both` 全文双引擎对照 → 5-7 分钟（40 页论文）
3. **读双路 Markdown**：
   - 先读 marker/ 的（结构清晰）
   - 遇公式/表格再切到 mineru/ 的（LaTeX 准）
   - 看 _DIFF.md 中的差异行，人工裁决哪个版本对
4. **图分析**：用 `doubao-vision` skill 分析 `mineru/<stem>/auto/images/` 中的架构图、流程图
5. **批量处理目录**：`--batch` 模式，串行处理所有 PDF，进度可见

## 输出目录结构

```
<output_dir>/
├── <pdf_stem>/
│   ├── marker/                  # Marker 输出
│   │   ├── <stem>.md
│   │   ├── <stem>_meta.json
│   │   └── _page_*_Figure_*.jpeg
│   ├── mineru/                  # MinerU 输出
│   │   └── auto/
│   │       ├── <stem>.md
│   │       ├── <stem>_content_list.json
│   │       ├── <stem>_layout.pdf  # 版面分析可视化
│   │       ├── <stem>_span.pdf
│   │       └── images/            # 图片（哈希命名）
│   ├── _DIFF.md                 # 行级对照差异
│   └── _META.json               # 转换元数据
```

## 引擎调用细节

> **WSL 环境**：`paper_reader.py` 会自动检测 WSL，将 Marker/MinerU 的 GPU 计算通过 `cmd.exe` 桥接到 Windows 原生 Python (`E:\venvs\marker` / `E:\venvs\mineru`) 执行，避免 vmmemWSL 内存膨胀。编排逻辑（diff/merge）仍在 WSL 侧。

### Marker 调用
```
~/.claude/skills/paper-reader/venvs/marker/bin/marker_single <pdf> \
  --output_dir <out>/marker [--page_range 0-4]
```
首次运行会下载 ~2GB 模型到 `~/.cache/datalab/`。

### MinerU 调用
```
~/.claude/skills/paper-reader/venvs/mineru/bin/mineru -p <pdf> \
  -o <out>/mineru -b pipeline -m auto
```
- `-b pipeline`：通用模式（快、稳）
- `-b hybrid-engine --effort high`：高精度模式（含图表分析，慢 3-5 倍）
- `-m ocr`：强制 OCR（适合扫描件）
- `-l ch`：中文 PDF 时加这个
首次运行会下载模型到 `~/.cache/modelscope/`。

## 性能预期

- 40 页学术论文（如 Lei&Hao MDVRP）：
  - Marker: ~6 分钟
  - MinerU (pipeline): ~3 分钟
  - 双引擎并行: ~6 分钟（取 max）
- 10 页摘要精读：Marker 单路 ~30 秒

## 资源限制（防 OOM 卡死）

**背景**：双引擎并行模式下，Marker 和 MinerU 两个 Windows GPU 进程同时吃同一块 16GB 显存。不加限制会吃满显存 → CUDA 驱动 hang → 全系统冻住。规范全文见 `/home/dc/CLAUDE.md` → "GPU 多路并发铁律"。

`paper_reader.py` 默认已开启四层防护，无需额外配置：

| 防护层 | 默认值 | CLI 参数 | 作用 |
|---|---|---|---|
| **① GPU 显存配额（单进程）** | 每进程 40% | `--gpu-fraction 0.4` | OOM 抛异常而非杀驱动（最关键） |
| **② CPU 线程上限（单进程）** | 每进程 6 线程 | `--cpu-threads 6` | 防两进程各起 24 线程抢核 |
| **③ 批量并发上限（进程内）** | 串行（1 PDF） | `--max-concurrent-pdfs 1` | 防进程内多 PDF 同时跑 |
| **④ 设备级协调（跨进程）** | 总显存 ≤ 90% | `--gpu-cap-fraction 0.9` | **paper-reader + CV 训练同时跑时排队等待，不抢占** |

**第④层（GpuGovernor）说明**：当 paper-reader 与其他 GPU 任务（如 CV 训练）同时跑时，通过 fcntl 文件锁 + 预算账本互斥访问 GPU。账本位置 `~/.cache/gpu-governor/ledger.json`。其他任务也用同样的 governor 即可自动协调。

常用调优组合：

```bash
# 最稳（单引擎串行，省显存）
uv run paper_reader.py paper.pdf --max-workers 1 --gpu-fraction 0.5

# 默认（双引擎并行，每进程 40% 显存，设备级 90% 上限）
uv run paper_reader.py paper.pdf   # 无需任何参数

# 激进批量（需 GPU ≥ 16GB：2 PDF × 2 引擎 × 20% = 80% ≤ 100%）
uv run paper_reader.py papers/ --batch --max-concurrent-pdfs 2 --gpu-fraction 0.2

# 纯 CPU 模式（不用 GPU，可关限制）
uv run paper_reader.py paper.pdf --gpu-fraction 0
```

**OOM 早预警**：批量并发时若 `max_concurrent_pdfs × max_workers × gpu_fraction > 100%`，脚本会打印警告但仍执行（用户自负）。

## 故障排查

| 症状 | 原因 | 解决 |
|---|---|---|
| CUDA out of memory | 显存不足 | 加 `--engines marker` 单路，或 `--max-workers 1` 串行，或降 `--gpu-fraction` |
| 系统卡死/CUDA 驱动 hang | 多进程吃满显存 | 默认 0.4 配额应能防住；若仍卡，加 `--max-workers 1` |
| GPU 预算不足被跳过（stderr: `GPU budget unavailable`） | CV 训练等其他任务占满 90% cap | 加大 `--gpu-wait-timeout`，或暂停其他 GPU 任务，或 `--gpu-cap-fraction 0` 关协调器（不推荐） |
| MinerU 模型下载卡住 | 网络问题 | 设 `HF_ENDPOINT=https://hf-mirror.com` |
| Marker 公式识别差 | 已知缺陷 | 切到 mineru/ 的对应段落看 |
| MinerU OCR 把 V 识别成 ν | 字体相似 | 切到 marker/ 看同段 |
| venvs/ 被误删 | — | 重跑 `bash scripts/bootstrap.sh` |

## 文件

```
paper-reader/
├── SKILL.md                    # 本文
├── scripts/
│   ├── paper_reader.py         # 主脚本（双引擎调度 + diff）
│   └── bootstrap.sh            # 重装 venvs（如需）
├── venvs/
│   ├── marker/                 # Marker 独立 Python 环境
│   └── mineru/                 # MinerU 独立 Python 环境
└── data/                       # 预留缓存目录
```
