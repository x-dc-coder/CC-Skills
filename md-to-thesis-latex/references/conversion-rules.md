# 参考：Markdown → LaTeX 转换规则（§5 全量）

> 本文件是 `SKILL.md` 的按需加载参考。执行具体要素（标题/图片/表格/代码/公式/列表/参考文献）转换时读取。

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

