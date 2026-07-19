---
name: md-to-thesis-latex
description: >
  将用户撰写的 Markdown 格式本科毕业论文转换为符合电子科技大学中山学院（ZSC）
  LaTeX 模板规范的 .tex 文件并编译生成 PDF。当用户提到以下任何场景时触发：
  "把 md 转成 latex"、"markdown 转 tex"、"帮我生成论文 pdf"、"md 转 latex"、
  "论文转 latex"、"把 markdown 编译成 pdf"、"生成毕设 pdf"、"论文排版"、
  "把写好的 md 转成论文"，或者用户给出 md 文件要求生成论文时。
  即使只说了"帮我处理论文"或"转成 pdf"，也应该主动使用此 skill。
---

# Markdown 转 ZSC 毕业论文 LaTeX Skill

## 1. 核心职责

将用户提供的 Markdown 格式论文内容（含图片引用、表格、代码块、公式等），转换为符合电子科技大学中山学院（ZSC）毕业论文 LaTeX 模板（`zsc-cs-latex-thesis`）规范的 `.tex` 文件，并编译生成最终 PDF。

**你必须仅参考 Markdown 中的内容，不要添加或扩展任何内容。** 你的工作是格式转换，不是内容创作。

## 2. 前置检查

开始转换前，按顺序确认：

1. **模板文件是否存在**：按以下优先级发现模板（`zscthesis.cls`）：

   a. **`--template-dir` 参数**：如用户指定 `--template-dir /path/to/template`，直接使用该目录下的 `style/`、`logo/`、`bib/`

   b. **`$PROJECT_ROOT/style/`**：检查项目根目录下的 `style/zscthesis.cls` 是否存在

   c. **Gitee 克隆**：从 `https://gitee.com/yeyunxiaopan/zsc-cs-latex-thesis` 克隆 `style/`、`logo/`、`bib/` 到 `$PROJECT_ROOT/template/`。若 Gitee 不可达（离线/网络超时），给出提示：**"模板仓库不可达，请手动放置 `style/zscthesis.cls` 到项目目录"**，继续转换而非中断流程。
2. **图片文件是否存在**：检查 Markdown 中引用的所有 `img/xxx.png`（或 jpg/pdf）是否真实存在。
   - **缺失的图片不中断转换**，使用占位符代替。
   - 占位符方案：生成一个带文字提示的灰色占位框（如 `\fbox{\parbox{0.7\textwidth}{\centering \vspace{2em} [占位符: xxx.png] \\ 请替换为实际图片 \vspace{2em}}}`），并在日志中列出所有缺失图片清单，方便用户后续统一生成和替换。
3. **编码确认**：确保所有 `.tex` 文件以 **UTF-8 无 BOM** 保存。

## 3. 总体要求（2024 版新增）

转换完成后，论文必须满足以下硬性指标：

| 要求 | 指标 |
|------|------|
| 撰写工具 | **必须使用 LaTeX** |
| 正文篇幅 | **不少于 30 页**，主要篇幅集中在第 3、4、5 章 |
| 查重率 | **不高于 25%** |
| 编译链 | `xelatex → bibtex → xelatex → xelatex` |
| 编码 | UTF-8 无 BOM |

**重要约束**：
- 论文题目确定后**不能再更改**（任务书下达后锁定）。
- 所有图建议**导出**而非截屏；同类型图缩放比例一致，图中文字大小一致。
- **不能随意加回车换行、空行或空格**，否则会导致格式错乱。
- 英文标题及英文关键字**首字母要大写**。
- 论文内容要侧重于阐述**系统特有的核心业务**，尽量不要写所有系统都通用的内容（如用户登录、注册等）。

## 4. 目录结构与文件映射

转换后应生成如下结构：

```
thesis-output/latex/
├── main.tex                    # 主文件，引用各章节
├── tex/
│   ├── frontinfo.tex           # 封面信息（2024年起通常注释掉）
│   ├── declaration.tex         # 独创性声明
│   ├── abstract-ch.tex         # 中文摘要
│   ├── abstract-en.tex         # 英文摘要
│   ├── content.tex             # 目录（自动生成，通常不修改）
│   ├── chap-1.tex ~ chap-N.tex # 各章节
│   ├── reference.tex           # 参考文献
│   ├── acknowledgement.tex     # 致谢
│   └── appendix.tex            # 附录（无内容则注释）
├── img/                        # 图片目录
├── style/                      # 模板样式文件
├── logo/                       # 学校logo
└── bib/
    └── ref.bib                 # BibTeX 参考文献
```

## 5. Markdown → LaTeX 转换规则

### 5.1 标题层级

| Markdown | LaTeX | 格式说明 |
|----------|-------|---------|
| `# 绪论` | `\chapter{绪论}` | 三号黑体，居中，自动编号"第X章" |
| `## 课题背景` | `\section{课题背景}` | 小三黑体，左对齐 |
| `### 子标题` | `\subsection{子标题}` | 四号黑体，左对齐 |
| `#### 小小节` | `\subsubsection{小小节}` | 小四黑体，左对齐 |

**注意**：
- Markdown 中的章节编号（如 `## 1.1 课题背景`）转换为 LaTeX 时**去掉数字编号**，LaTeX 自动处理编号
- 第1章正文前必须包含：
  ```latex
  \clearpage
  \setcounter{page}{1}
  \pagenumbering{arabic}
  ```

### 5.2 图片处理

Markdown 图片：`![系统架构图](img/architecture.png)`

转换为 LaTeX：
```latex
如图\ref{fig:architecture}所示，系统采用分层架构。

\begin{figure}[H]
    \centering
    \includegraphics[width=.7\textwidth]{architecture}
    \caption{系统架构图}
    \label{fig:architecture}
\end{figure}
```

**关键规则**：
- 路径处理：去掉 `img/` 前缀和文件后缀，只保留文件名（模板已设置 `\graphicspath{{img/}}`）
- 宽度默认 `.7\textwidth`，若原文有多个小图并列可调整为 `.45\textwidth`
- 浮动参数默认 `[H]`（强制当前位置），若导致大段空白可改为 `[htbp]`
- `\label` 必须紧接在 `\caption` 之后
- 正文引用必须使用 `\ref{fig:xxx}`，**禁止**写"如下图"、"如下表"
- 图片说明文字提取自 `![说明文字]` 的 alt 文本

### 5.3 表格处理

Markdown 表格转换为 `booktabs` 格式：

```latex
如表\ref{tab:user}所示，用户表结构如下：

\begin{table}[H]
    \centering
    \caption{用户表结构}
    \label{tab:user}
    \begin{tabular}{ccccc}
        \toprule
        字段名 & 类型 & 长度 & 是否为空 & 说明 \\
        \midrule
        id & BIGINT & 20 & 否 & 主键 \\
        username & VARCHAR & 50 & 否 & 用户名 \\
        \bottomrule
    \end{tabular}
\end{table}
```

**关键规则**：
- 使用 `\toprule`、`
\midrule`、`\bottomrule` 代替 `\hline`
- 表格标题（`\caption`）必须在表格上方
- `\label` 紧接 `\caption` 之后
- 正文引用使用 `\ref{tab:xxx}`
- 列对齐默认居中 `c`，根据内容可调整为 `l`（左对齐）或 `r`（右对齐）

### 5.3.1 测试用例表特殊格式（第 5 章）

第 5 章系统测试的测试用例表采用**纵向排列的特殊格式**，用例编号、名称、内容三行横向合并，测试数据横向展开：

```latex
\begin{table}[H]
    \centering
    \caption{用户在线选座测试用例}
    \label{tab:test-seat}
    \begin{tabular}{|c|c|c|c|}
        \hline
        用例编号 \u0026 \multicolumn{3}{c|}{A001} \\
        \hline
        用例名称 \u0026 \multicolumn{3}{c|}{用户在线选座} \\
        \hline
        用例内容 \u0026 \multicolumn{3}{c|}{确认用户在线选座工作正常} \\
        \hline
        测试输入数据 \u0026 选择空座并正确填入号码 \u0026 未选择座位 \u0026 选择空座并未填或者错填号码 \\
        \hline
        预期输出结果 \u0026 选座成功 \u0026 选座失败并提示选座 \u0026 选座失败并提示填入正确号码 \\
        \hline
        实际输出结果 \u0026 选座成功 \u0026 选座失败并提示选座 \u0026 选座失败并提示填入正确号码 \\
        \hline
    \end{tabular}
\end{table}
```

**关键特征**：
- 用例编号、用例名称、用例内容 使用 `\multicolumn{3}{c|}{...}` 合并横向单元格
- 测试输入数据、预期输出结果、实际输出结果 横向分为多列（根据测试场景数量）
- 用例编号格式：`A001`、`A002`、`A003`...（A + 三位数字）
- 每个测试模块与第 5 章系统实现的模块一一对应

### 5.4 代码块处理

根据代码语言选择模板预定义环境：

| 语言 | LaTeX 环境 |
|------|-----------|
| Java | `\begin{java} ... \end{java}` |
| Python | `\begin{python} ... \end{python}` |
| C/C++ | `\begin{clan} / \begin{cpp} ... \end{clan} / \end{cpp}` |
| JavaScript | `\begin{javascript} ... \end{javascript}` |
| SQL | `\begin{sql} ... \end{sql}` |
| HTML | `\begin{html} ... \end{html}` |
| MATLAB | `\begin{matlab} ... \end{matlab}` |
| Go | `\begin{gogo} ... \end{gogo}` |
| PHP | `\begin{php} ... \end{php}` |
| XML | `\begin{xml} ... \end{xml}` |
| TeX | `\begin{tex} ... \end{tex}` |

**关键规则**：
- 代码块**上方**需有中文注释说明功能，格式：`#功能说明`，例如：
  ```latex
  #查询相应的电影排片详情
  \begin{java}
  @GetMapping("/{id}")
  \end{java}
  ```
- 代码长度**不宜超过半页**，超长代码应截断只保留核心逻辑
- 代码中**保留注释**，帮助理解
- 第 5 章（系统实现）的代码说明要从**代码实现的角度**描述，不要从用户操作的角度描述

### 5.5 公式处理

Markdown 行间公式 `$$...$$` 转换为 LaTeX `equation` 环境：

```latex
\begin{equation}\label{eq:newton}
    \vec{F} = m\vec{a}
\end{equation}
```

**关键规则**：
- 每个公式必须添加 `\label{eq:xxx}` 以便引用
- 正文引用使用 `\eqref{eq:xxx}`（带括号）或 `公式\eqref{eq:xxx}`
- 行内公式用 `$...$` 保持原样

### 5.6 列表处理

| Markdown | LaTeX |
|----------|-------|
| 有序列表 `1. 2. 3.` | `\begin{enumerate} \item ... \end{enumerate}` |
| 无序列表 `-` / `*` | `\begin{itemize} \item ... \end{itemize}` |

**关键规则**：
- 列表项之间无多余间距（模板已设置 `\setlist{nosep}`）
- 列表嵌套支持，直接嵌套 `enumerate` / `itemize` 环境即可
- 第 1 章"目的意义"建议分条列点；第 6 章"展望"建议分条列出

### 5.7 文本格式

| Markdown | LaTeX |
|----------|-------|
| `**粗体**` | `\textbf{粗体}` |
| `*斜体*` | `\textit{斜体}` |
| 普通段落 | 直接转换，空行分段 |

### 5.8 参考文献处理

**方式一**：BibTeX 格式（推荐）
- 用户提供 BibTeX 条目，写入 `bib/ref.bib`
- 正文中 `[1]` 或 `[@key]` 转换为 `\cite{key}`
- `main.tex` 中使用 `\bibliography{bib/ref}` 和 `\bibliographystyle{bib/gbt7714-numerical}`

**方式二**：手动列表
- 如果用户未提供 BibTeX，使用 `\begin{thebibliography}{99}` 环境
- 条目格式遵循 GB/T 7714 标准

## 6. 各章节特殊处理

### 6.1 封面（frontinfo.tex）

2024年起封面通常由维普系统生成，论文中可注释掉。如需保留，按模板填写：
```latex
\mytitle{论文中文题目}
\MYTITLE{English Title}
\institute{计算机学院}
\major{计算机科学与技术}
\studentid{学号}
\student{姓名}
\advisor{导师姓名(职称)}
\completedate{完成日期}
```

### 6.2 摘要（abstract-ch.tex / abstract-en.tex）

```latex
\clearpage
\setcounter{page}{1}
\pagenumbering{Roman}
\currentpdfbookmark{\defabstractname}{bm@abstractname}
\chapter*{\defabstractname\markboth{\defabstractname}{}}

\abstract{
% 中文摘要内容，300-500字
}

\keywords{关键词1；关键词2；关键词3}
```

英文摘要同理，使用 `\ABSTRACT{}` 和 `\KEYWORDS{}`。

### 6.3 目录（content.tex）

通常无需修改，直接复用模板：
```latex
\clearpage
\currentpdfbookmark{\contentsname}{bm@contentsname}
\tableofcontents

\clearpage
\currentpdfbookmark{\listfigurename}{bm@listfigurename}
\renewcommand{\numberline}{\figurename~\oldnumberline}
\listoffigures

\clearpage
\currentpdfbookmark{\listtablename}{bm@listtablename}
\renewcommand{\numberline}{\tablename~\oldnumberline}
\listoftables
```

### 6.4 正文章节（chap-1.tex ~ chap-N.tex）

- 第1章需包含 `\clearpage \setcounter{page}{1} \pagenumbering{arabic}`
- 后续章节直接以 `\chapter{标题}` 开头
- 每章文件独立，通过 `main.tex` 中的 `\input{tex/chap-N.tex}` 引入

### 6.5 参考文献（reference.tex）

```latex
\clearpage
\chapter*{参考文献}
\addcontentsline{toc}{chapter}{参考文献}
\bibliography{bib/ref}
\bibliographystyle{bib/gbt7714-numerical}
```

### 6.6 致谢（acknowledgement.tex）

```latex
\clearpage
\chapter*{致谢}
\addcontentsline{toc}{chapter}{致谢}

\acknowledgement{
% 致谢内容
}
```

## 7. 各章节内容撰写规范

以下规范来自 `docs/` 中的最新论文要求，用于指导 Markdown 内容的组织。转换时应提醒用户按此规范检查内容完整性。

### 7.1 摘要（300-500 字）

必须分为 **3 个自然段**：
1. **背景意义**：简述行业现状或社会背景，指出传统模式存在的痛点。
2. **核心任务与技术栈**：明确提出核心任务，列举所使用的核心技术（如 Spring Boot、Vue、MySQL 等），概述主要工作流程。
3. **论文组织结构**：概述本文后续章节安排。

**关键词**：3~5 个，用分号隔开；英文关键词与中文一一对应，首字母大写。

### 7.2 第 1 章 绪论

**书写内容**：
1. **课题背景**：详细阐述项目为什么要做。从宏观环境切入，落脚到微观具体行业的实际需求。
2. **目的意义**：
   - 研究意义（方便用户、提高效率、促进产业发展）
   - 研究目的（解决哪些具体问题）
   - 研究内容/范围（包含哪些核心功能模块）
   - 建议采用项目符号（1、2、3）分条列点
3. **论文组织结构**：简明扼要地介绍后续每一章的具体内容。

**书写形式**：纯文字描述为主，清晰简洁。

### 7.3 第 2 章 相关技术和理论基础

**书写内容**：对项目中实际使用到的编程语言、框架、数据库及架构模式进行学术性介绍：
1. 架构模式（如 B/S 架构）
2. 前端技术（如 Vue、Element UI）
3. 后端技术（如 Java、Spring Boot、MyBatis-Plus）
4. 数据库存储（如 MySQL）

**书写形式**：
- 分小节撰写（如 2.1, 2.2）。
- 篇幅最好控制在 **2-3 页**。
- 每项技术的介绍**不应仅停留在百科全书式的定义**，应适当结合项目，说明**为什么该项目要选择这项技术**。
- 可写深入一些，比如具体使用的框架、第三方库等。

### 7.4 第 3 章 系统分析 / 需求分析

**书写内容**：明确系统"需要做什么"。
1. **功能需求分析**：
   - 整体需求概述：系统用来做什么，有哪几种角色，各种用户大概能做什么。
   - 各角色需求详细说明：每个角色的需求采用 **"用例图 + 用例描述"** 的形式阐述。
2. **非功能需求分析**：性能、安全性、数据访问控制等方面的要求（如：密码加密、缓存机制提升性能、订单超时自动取消等业务规则）。

**书写形式**：
- **图文并茂，这是本章的重点**。
- 提供一张 **"系统功能需求分析图"**（思维导图或树状图），展示各角色的功能分支。
- 为每一个角色绘制标准的 **UML 用例图 (Use Case Diagram)**，并配以文字说明他们的操作权限。
- 用例图需包含 `<<use>>`、`<<extend>>`、`<<include>>` 等标准 UML 关系。

### 7.5 第 4 章 系统设计

**书写内容**：明确系统"如何实现这些需求"，从宏观到微观进行设计。
1. **总体设计**：
   - 技术架构设计：绘制系统总体的架构设计图，并配以文字描述。
   - 前后端分离架构：说明前后端分离的概念及在此系统中的优势。
   - MVC 模式：说明 MVC 各层的职责及数据流转过程。
   - 处理流程：分别用文字描述**用户操作流程**、**工作人员操作流程**、**管理员操作流程**。
   - **注意**：这部分很容易雷同，可按自己的理解绘制架构图，或者尽量缩减这部分的内容。
2. **详细设计**：
   - 选取 **5 个系统核心业务** 功能模块（如用户购票、管理员排片、修改个人信息、电影推荐、用户参加活动）。
   - 每个核心业务功能模块都必须配有**流程图**（带判断菱形框的标准流程图）配以文字说明。
   - 可以从 **用户操作流程** 的角度描述。
3. **数据库设计**：
   - **概念模型设计**：**ER 图**一张即可（图4-9），体现实体之间的 1:1、1:n 或 m:n 的关系。字段太多可以不画属性。
   - **物理模型设计**：数据库表结构说明。
     - 先有一张**总表**（表名 → 表含义），列出所有表。
     - 然后每个核心业务表单独一张表，格式为：列名、数据类型、是否为空、是否为主键、说明。
     - **切忌堆砌过多表格**，只保留核心业务表。

**书写形式**：
- 总体设计必须包含 4 张图：**系统架构图**、**前后端分离架构图**、**MVC 模式图**。
- 详细设计每个核心业务必须配有**标准流程图**（带开始/结束、处理、判断框）。
- E-R 图一张即可。
- 数据库表结构：先总表后分表，纵向排列格式（列名 | 数据类型 | 是否为空 | 是否为主键 | 说明）。

### 7.6 第 5 章 系统实现与测试

**书写内容**：展示系统的最终产出以及质量验证。
1. **系统实现**：
   - 选择 **4-5 个核心业务功能模块**。
   - 从**代码的层面**，说明实现的思路，**切勿从操作的层面阐述**。
   - 详细描述核心模块的前后端交互逻辑和代码实现过程。
2. **系统测试**：
   - 采用黑盒测试等方法，针对核心功能设计测试用例。
   - 验证系统能否正常响应各种正确或错误的输入。
   - 如果有性能需求，最好附上 jmeter 之类的压力测试结果。

**书写形式**：
- **核心代码块**：插入关键的前端交互逻辑和后端业务逻辑（Service）的代码片段。
  - 代码块**上方**必须有中文注释说明功能，格式：`#功能说明`。
  - 每个功能模块的代码**不超过半页**。
  - 代码中要有**详细的注释**。
  - 文字说明要从**代码实现的角度**描述，不要从用户操作的角度描述。
- **UML 时序图 (Sequence Diagram)**：为每一个展示的模块绘制时序图，清晰表现前端、控制层、服务层、数据库之间的方法调用和数据返回过程。代码块后紧跟时序图。
- **界面截图**：展示系统最终运行的 UI 截图，可只截页面中相关的部分内容，但一定要能看清。
- **测试用例表**：采用第 5.3.1 节定义的**纵向特殊格式**。
  - 用例编号格式：`A001`、`A002`...（A + 三位数字）。
  - 测试模块与系统实现模块一一对应（共 5 个）。
  - 每个测试用例表后配**界面截图**。

### 7.7 第 6 章 总结和展望

**书写内容**：
1. **本文总结**：回顾毕业设计的全过程，总结所使用的技术栈、完成的核心功能、测试结果以及系统的最终形态（如：需求调研、技术选型、系统实现的功能、系统测试和部署等）。
2. **未来展望**：客观指出当前系统存在的不足（受限于时间或技术能力），提出后续优化的方向（如：引入更高级的人工智能推荐算法、适配移动端、增加支付沙盒等）。

**书写形式**：
- 分为两小节撰写。
- 展望部分建议使用**项目符号分条列出**，显得思路清晰、有条理。
- **不要写个人感想**。

## 8. main.tex 主文件模板

```latex
\documentclass{style/zscthesis}

\begin{document}
    % \input{tex/frontinfo.tex}       % 封面（2024年起可注释）
    \input{tex/abstract-ch.tex}     % 中文摘要
    \input{tex/abstract-en.tex}     % 英文摘要
    \input{tex/content.tex}         % 目录
    \input{tex/chap-1.tex}          % 第1章
    \input{tex/chap-2.tex}
    \input{tex/chap-3.tex}
    \input{tex/chap-4.tex}
    \input{tex/chap-5.tex}
    \input{tex/chap-6.tex}
    \input{tex/reference.tex}       % 参考文献
    \input{tex/acknowledgement.tex} % 致谢
    % \input{tex/appendix.tex}        % 附录（无内容请注释）
\end{document}
```

## 9. 编译流程

必须执行以下编译链（共 3~4 次 xelatex）：

```bash
xelatex -interaction=nonstopmode main.tex
bibtex main                    # 如果使用 BibTeX
xelatex -interaction=nonstopmode main.tex
xelatex -interaction=nonstopmode main.tex  # 确保交叉引用正确
```

或使用 `latexmk`：
```bash
latexmk -xelatex -interaction=nonstopmode main.tex
```

## 10. 质量检查清单

生成 PDF 后，检查以下项目：

### 10.1 格式检查
- [ ] 页边距：上2.5cm、下2.5cm、左2.5cm、右2cm
- [ ] 字号：章标题三号黑体，节标题小三黑体，正文小四
- [ ] 图编号格式：`图1-1`、`图2-3`（章号-序号）
- [ ] 表编号格式：`表1-1`、`表2-3`
- [ ] 图表标题：宋体小五号，编号与标题间用空格（无冒号）
- [ ] 所有图片在正文中用 `\ref` 引用，无"如下图"字样
- [ ] 所有表格在正文中用 `\ref` 引用
- [ ] 参考文献在正文中用 `\cite` 引用
- [ ] 公式编号格式：`(1-1)`、`(2-3)`，用 `\eqref` 引用
- [ ] 页眉显示"电子科技大学中山学院毕业设计(论文)"和当前章标题
- [ ] 页码：摘要用大写罗马数字，正文用阿拉伯数字
- [ ] 目录、图目录、表目录正确生成
- [ ] 代码高亮环境正确渲染
- [ ] 无编译错误和警告（字体警告除外）

### 10.2 内容完整性检查
- [ ] 正文篇幅 **≥ 30 页**，第 3、4、5 章为主要篇幅
- [ ] 摘要分为 **3 个自然段**（背景、技术、结构），300-500 字
- [ ] 第 1 章"目的意义"分条列点，逻辑清晰
- [ ] 第 2 章篇幅控制在 **2-3 页**，结合项目说明技术选型理由
- [ ] 第 3 章包含：**总体功能需求分析图**（思维导图/树状图）+ 每个角色的 **UML 用例图**
- [ ] 第 3 章用例图包含 `\u003c\u003cuse\u003e\u003e`、`\u003c\u003cextend\u003e\u003e`、`\u003c\u003cinclude\u003e\u003e` 等标准 UML 关系
- [ ] 第 3 章包含非功能需求（性能、安全、业务规则）
- [ ] 第 4 章总体设计包含 4 张图：**系统架构图**、**前后端分离架构图**、**MVC 模式图**
- [ ] 第 4 章详细设计包含 **5 个核心模块**，每个配**标准流程图**（带判断框）
- [ ] 第 4 章处理流程分别描述：用户操作流程、工作人员操作流程、管理员操作流程
- [ ] 第 4 章数据库设计：**一张 ER 图** + **一张总表**（表名→含义）+ **核心业务表分表**
- [ ] 第 5 章选取 **5 个核心模块**，每个配**核心代码（≤半页，上方有 `#功能说明` 注释）** + **时序图** + **界面截图**
- [ ] 第 5 章代码说明从**代码实现角度**写，非用户操作角度
- [ ] 第 5 章测试用例表采用**纵向特殊格式**（用例编号/名称/内容合并，数据横向展开）
- [ ] 第 5 章测试用例编号格式：`A001` ~ `A005`
- [ ] 第 5 章每个测试模块后配**界面截图**
- [ ] 第 6 章分为"总结"和"展望"两小节，展望分条列出，**无个人感想**
- [ ] 论文侧重**系统特有的核心业务**，未大篇幅写通用功能（登录、注册等）

## 11. 常见错误与修复

| 问题 | 原因 | 修复 |
|------|------|------|
| 图片不显示 | 路径错误或未放 `img/` 目录 | 确保图片在 `img/`，引用时不写 `img/` 前缀 |
| 图表标题有冒号 | caption 格式问题 | 模板已设置 `labelsep=space`，无需修改 |
| 大段空白 | `[H]` 浮动参数导致 | 改为 `[htbp]` |
| 参考文献不显示 | 未在正文中 `\cite` 引用 | 确保每条参考文献都被引用 |
| 字体警告 | 系统缺少某些 CJK 字体 | 通常不影响输出，可忽略 |
| 中文显示为方框 | 缺少 ctex 或字体 | 确认安装了 `texlive-lang-chinese` |
| 第 2 章篇幅过长 | 技术介绍过于百科全书式 | 控制 2-3 页，只写项目中用到的技术，结合项目说明选型理由 |
| 第 4 章表格过多 | 数据库设计堆砌所有表 | 只保留核心业务表，用一张 ER 图代替 |
| 第 5 章像操作手册 | 从用户操作角度描述 | 改为从代码实现角度，描述前后端交互逻辑和核心算法 |
| 第 6 章像日记 | 写了个人感想和心路历程 | 删除感想，总结用技术语言，展望分条列点 |
| 摘要缺段 | 未按 3 段式（背景/技术/结构）书写 | 提醒用户补充 |
| 图片引用不规范 | 写了"如下图"、"如下表" | 统一改为"如图/表 `\ref{...}` 所示" |
