# Figure Profile JSON Schema（图目录 + 图画像，issue #1 MVP-1 + MVP-6）

> 本文是 figure_profile.py 两份产物的字段事实源：_figure_profile.json（逐图）与
> _figure_summary.json（语料级聚合）。文体与 metric-definitions.md 一致：每个字段
> 讲清**来源（OBSERVED / INFERRED / NOT_IMPLEMENTED）**、**怎么算**、**不能推断什么**。

## 0. 范围与红线（先说清"这不是什么"）

本轮只实现 issue #1 的 **MVP-1（Figure Inventory + 稳定 figure_id）** 与
**MVP-6（Figure Profile JSON 的可测量子集）**，**明确不含视觉层**。

- **只做可测量、可复算的 OBSERVED**：题注文本、图片文件头尺寸、章节位置。
- **只做由章节位置启发的 INFERRED**：section 与 type_guess，带 confidence + basis，
  且逐字段标注 status: "INFERRED"。
- **不做任何视觉/语义识别**：chart type 细分类、panel_count、axis/legend、颜色/字体/线宽、
  caption 语义角色 —— 一律 null + status: "NOT_IMPLEMENTED" 占位。

> **红线（不得把 INFERRED 当事实）**：section 与 type_guess 是"这张图落在哪个标题下面"的
> 位置推断，**不是**"这张图画的是什么"。它们可用来做语料分布的可解释性描述，**绝不能**写成
> "该刊 method 章 34 张图里 34 张是 framework 图"这类事实断言，也**不得**进入任何 gate。
> 任何消费方要引用这两个字段，必须带上 confidence 与 basis，并说明"这是位置启发，非视觉识别"。

## 1. 产物

| 产物 | 内容 | 是否参与确定性 |
|---|---|---|
| _figure_profile.json | 逐图记录（figures[]），每图一个稳定 ID | 是 |
| _figure_summary.json | 语料级分布（尺寸/宽高比/题注长度分位、达标率、章节分布） | 是 |

两条都 json.dumps(..., sort_keys=True, ensure_ascii=False, indent=2) 输出，**无时间戳、
无绝对路径**（图片路径相对语料根，见 image_rel_path）。同语料两次运行**逐字节一致**。

## 2. 稳定 figure_id

形状：fig-&lt;paper_stem&gt;-&lt;page&gt;-&lt;block_index&gt;，例如
fig-2018-gpu-ising-computing-for-co-cook-et-al-1-18。

| 组成 | 来源 | 为何稳定 |
|---|---|---|
| paper_stem | paper_dir.name 的确定性 slug（NFC 归一 + 小写 + 非字母数字→-，**保留 CJK**） | 只依赖目录名，不依赖文件系统顺序 |
| page | MinerU page_idx **原样**（**0-based**，第一页是 0） | 只依赖 content_list 字节 |
| block_index | 块在 content_list 列表中的下标（0-based） | 只依赖 content_list 字节 |

**稳定性证明**：三个分量都是"输入 content_list.json 字节 + 目录名"的纯函数，无时间戳、
无绝对路径、无 os.walk 顺序。同输入必得同 ID；换引擎/重新转换 = 换输入 = ID 可能变（与
引擎口径冻结的红线一致）。

**目录名 slug 冲突**：两篇论文 slug 相同时（罕见），冲突者统一追加 -&lt;sha256(目录名)[:6]&gt;
后缀。这是**内容寻址**的消歧（增删无关论文不影响既有 ID），已在实现中写死。

## 3. 逐图字段字典（figures[]）

### 3.1 OBSERVED（可测量、可复算）

| 字段 | 类型 | 含义 / 算法 |
|---|---|---|
| figure_id | string | 稳定 ID，见 §2 |
| paper | string | 论文目录名（原文） |
| paper_stem | string | 参与 ID 的 slug |
| page | int 或 null | MinerU page_idx 原样（0-based）；缺失时为 null |
| block_index | int | 块在 content_list 中的下标 |
| img_path_occurrence_index | int | 该 img_path 在本文内第几次出现（1-based，文档顺序） |
| img_path_occurrence_total | int | 该 img_path 在本文内共出现几次 |
| image_path | string | MinerU 原文 img_path（相对 auto/ 目录） |
| image_rel_path | string | **语料根相对路径**（POSIX），机器无关、可回开文件 |
| caption | string | 原文题注：拼接所有 *_caption 键（image_caption / chart_caption / …） |
| caption_chars | int | len(caption)（Unicode 码点，中文按字） |
| caption_has_number | bool | 题注是否含图编号声明（Figure N / Fig. N / 图 N，全角数字归一） |
| readable | bool | 图片文件头是否可读（决定 width/height 是否为 null） |
| width / height | int 或 null | 只读 PNG/JPEG/GIF 文件头；读不了 = null |
| aspect_ratio | float 或 null | round(width/height, 4)；height=0 或不可读 = null |
| width_usable_for_print | bool 或 null | width ≥ 800；不可读 = null（**未测量，不是 false**） |

**图片头读取**：纯 stdlib、无解码器、无第三方（PNG IHDR / JPEG SOFn / GIF LSD）。
WebP 等未支持格式返回不可读，不猜。width_usable_for_print 阈值 **800 px 与 S-SIZ-04
同阈值、同口径**（见 §6），阈值与语义已在两处同时冻结。

### 3.2 INFERRED（章节位置启发，非视觉识别）

section 与 type_guess 都是**信封结构**：

    {
      "value": "...",          # 推断值
      "confidence": "...",     # high | medium | low
      "basis": "...",          # 规则说明（含命中的原始标题）
      "status": "INFERRED"     # 永远 INFERRED，消费方必须看见
    }

- section.value：图之前**最近的 level-2 标题**经归一 + canonical 映射得到的章节标签
  （introduction/method/experiments/discussion/…）；图之前没有 level-2 标题 → front_matter。
- type_guess.value：**完全由 section 推导**的位置启发子类型 ——
  chart@experiments→data_plot；image@method→framework_architecture；
  image@experiments→result_figure；image@introduction→concept_diagram；
  其余→chart_other/image_other。
- **两个字段的 confidence 相同**：type_guess 的置信度不高于 section。

### 3.3 NOT_IMPLEMENTED（视觉/语义占位）

以下字段一律 {"value": null, "status": "NOT_IMPLEMENTED"}：

chart_type（细分类）、panel_count（子图数）、has_axis、has_legend、colors（颜色）、
fonts（字体）、line_width（线宽）、caption_semantic_role（题注语义角色）。

> **要填这些字段需要视觉模型/GPU**，属于 issue #1 的 **Phase 1（视觉字段抽取）/ Phase 4
> （chart type 细分类）/ Phase 5（caption 语义角色）**，不在本轮 MVP。占位是为了**schema 稳定**
> —— 将来上线时字段位置已预留，不破坏既有消费者。

## 4. 语料级聚合字段（_figure_summary.json）

| 字段 | 含义 |
|---|---|
| n_papers / n_papers_with_figures | 论文数 / 含图论文数 |
| n_figures | 图块总数（**一个块算一张**，见 §5） |
| n_unique_images | 去重后的图片文件数（按 image_rel_path） |
| n_measured / n_unreadable | 可读 / 不可读（缺文件或文件头读不出）图块数 |
| unreadable[] | 逐条 {image_rel_path, reason}，reason 为 missing_file 或 unreadable_header |
| adequacy | {threshold_width_px: 800, same_as: "S-SIZ-04", adequate, measured, rate}；**分母是可读数，读不了的图不计入分母** |
| width / height / aspect_ratio / caption_chars | 各值分布 {count, min, p25, median, p75, max, mean} |
| caption_has_number | {with_number, without_number, measured} |
| section_distribution / type_guess_distribution | 章节/子类型计数（INFERRED 的聚合，**只作描述，不作事实**） |

**分位口径**：nearest-rank，偶数样本取靠前元素（与 S-CAPL-05 的语料级分位口径同族）。
mean 保留 4 位小数。空列表 → count: 0、其余 null。

## 5. 边界规则（写死 + 测试锁定）

- **去重/计数**：**一个 image/chart 块 = 一张图（一条记录）**。同一 img_path 出现 N 次 →
  N 条记录（它们是文档里 N 个不同的落位，如"同图在正文 + 图注各一块"）。每条 ID 因 block_index
  不同而**唯一**，并带 img_path_occurrence_index / _total 供去重可见性；summary 同时给
  n_figures（块数）与 n_unique_images（去重文件数）。
- **缺图/读不了**：缺文件或文件头读不出 → 该图 readable=false、width/height/aspect/usable
  全 null，计入 n_unreadable 并逐条列出，**不计入 adequacy 分母**（与 S-SIZ-04"读不了不算分母"一致）。
- **无图块**：n_figures=0，分布为 count: 0、null，adequacy.rate=null（不编 0）。
- **无 level-2 标题**：section.value = front_matter、confidence = low（位置信号，不是事实）。

## 6. 与 S-SIZ-04 的一致性（同阈值、同口径）

width_usable_for_print 的阈值与 _figure_summary.json → adequacy 的达标口径，与
stream_metrics 的 S-SIZ-04 **完全同源**：_MIN_IMAGE_WIDTH = 800（≈300 dpi 单栏图 6.8 cm）、
只读文件头、读不了不进分母、WebP 不猜。**实测交叉核验**：英文语料 424 张图，达标率 28.3%
（120/424）；中文语料 15 张图，达标率 6.7%（1/15）——与 metric-definitions.md 中 S-SIZ-04
登记的数值**逐位一致**。实现里该常量独立声明（本模块不 import stream_metrics，以隔离并行改动），
并由测试锁定等于 800。

## 7. 本轮未实现（issue #1 其余验收条款）

| 未实现 | 属于 issue #1 | 依赖 |
|---|---|---|
| chart type 细分类 / panel_count / axis / legend / 颜色 / 字体 / 线宽 | Phase 1、Phase 4 | 视觉模型 / GPU |
| caption 语义角色（描述型 vs 解读型等） | Phase 5 | 视觉模型 / LLM |
| 图表生成（按画像生成新图） | issue #1 生成类条款 | 下游生成层（非本层职责） |
| 图相似度 / 图去重检索 | issue #1 相似度类条款 | 视觉嵌入 / GPU |

本轮**只承诺**：图目录、稳定 figure_id、可测量的图片头画像、可解释的章节位置推断、
确定性输出、以及上述视觉字段的 schema 占位。
