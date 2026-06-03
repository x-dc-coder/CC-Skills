#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

IMG_HTML_RE = re.compile(r"<\s*img\b", re.IGNORECASE)
IMAGE_MD_RE = re.compile(r"!\[(.*?)\]\(([^)]+)\)")
SETEXT_RE = re.compile(r"^\s*(=+|-+)\s*$")
ATX_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*$")
TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
TABLE_CAPTION_RE = re.compile(r"^\s*\*{0,2}\s*(?:表|Table)\s*\d+[-－]\d+\s+.+\*{0,2}\s*$")
FIGURE_TITLE_RE = re.compile(r"^\s*(?:图|Figure|Fig\.)\s*\d+[-－]\d+\s+.+\s*$")
FIGURE_TITLE_RE_LOOSE = re.compile(r"^\s*\*{0,2}\s*(?:图|Figure|Fig\.)\s*\d+[-－]\d+\s+.+\*{0,2}\s*$")
MERMAID_FENCE_RE = re.compile(r"^\s*```\s*mermaid\s*$", re.IGNORECASE)
CITATION_RE = re.compile(r"\[(\d+)\]")
META_FIELD_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{1,30}\s*:\s*\S+")
SPECIAL_HEADINGS = {"摘要", "abstract", "参考文献", "references", "致谢", "acknowledgements", "结论", "结  论", "致  谢", "附录"}
REFERENCE_ITEM_RE = re.compile(r"^\[(\d+)\]")
FORMULA_NUMBER_RE = re.compile(r"\\tag\{\s*(\d+)-(\d+)\s*\}|(?:\\?\()\s*(\d+)-(\d+)\s*(?:\\?\))")
FORMULA_IMG_KEYWORDS_RE = re.compile(r"公式|equation|formula", re.IGNORECASE)
CJK_RE = re.compile(r"[一-鿿㐀-䶿　-〿＀-￯]")
ASCII_ALNUM_RE = re.compile(r"[A-Za-z0-9]")


@dataclass
class Finding:
    level: str
    line: int
    code: str
    message: str


def add_findings(findings: list[Finding], level: str, line: int, code: str, message: str) -> None:
    findings.append(Finding(level=level, line=line, code=code, message=message))


def is_setext_candidate(prev_line: str) -> bool:
    prev = prev_line.strip()
    if not prev:
        return False
    if prev.startswith("#"):
        return False
    if prev.startswith(">"):
        return False
    if TABLE_ROW_RE.match(prev):
        return False
    return True


def _normalize_caption(text: str) -> str:
    """移除表题/图题周围的加粗/斜体标记和首尾空格，用于对比重复标题。"""
    return re.sub(r"^\s*\*+\s*", "", text).replace("*", "").strip()


def _strip_inline_code(text: str) -> str:
    return re.sub(r"`[^`]*`", "", text)


def _validate_paired_double_quotes(findings: list[Finding], line_no: int, text: str) -> None:
    sanitized = _strip_inline_code(text)
    quote_count = sanitized.count('"') + sanitized.count("“") + sanitized.count("”")
    if quote_count % 2 != 0:
        add_findings(
            findings,
            "ERROR",
            line_no,
            "UNPAIRED_DOUBLE_QUOTES",
            "双引号未成对出现，请检查本行的中英文双引号是否完整",
        )


def _validate_markdown_pairs(findings: list[Finding], line_no: int, text: str) -> None:
    """检查 Markdown 行内标记是否成对出现（排除已闭合的行内代码后检查）。"""
    # 去掉已闭合的行内代码，保留不完整/未闭合的部分
    code_free = re.sub(r"`[^`]*`", "", text)

    # 加粗 **
    bold_count = code_free.count("**")
    if bold_count % 2 != 0:
        add_findings(
            findings,
            "ERROR",
            line_no,
            "UNPAIRED_BOLD",
            "加粗标记 ** 未成对，请检查是否缺少闭合标记",
        )

    # 斜体 *（去掉 ** 后统计剩余的单个 *）
    no_bold = code_free.replace("**", "")
    italic_count = no_bold.count("*")
    if italic_count % 2 != 0:
        add_findings(
            findings,
            "ERROR",
            line_no,
            "UNPAIRED_ITALIC",
            "斜体标记 * 未成对，请检查是否缺少闭合标记",
        )

    # 删除线 ~~
    strike_count = code_free.count("~~")
    if strike_count % 2 != 0:
        add_findings(
            findings,
            "ERROR",
            line_no,
            "UNPAIRED_STRIKE",
            "删除线标记 ~~ 未成对，请检查是否缺少闭合标记",
        )

    # 行内代码 `（去掉成对的后，检查剩余反引号）
    leftover_ticks = code_free.count("`")
    if leftover_ticks % 2 != 0:
        add_findings(
            findings,
            "ERROR",
            line_no,
            "UNPAIRED_INLINE_CODE",
            "行内代码标记 ` 未成对，请检查是否缺少闭合标记",
        )

    # 方括号 []
    bracket_open = code_free.count("[")
    bracket_close = code_free.count("]")
    if bracket_open != bracket_close:
        add_findings(
            findings,
            "ERROR",
            line_no,
            "UNPAIRED_BRACKETS",
            f"方括号 [] 不匹配：左 {bracket_open} 个，右 {bracket_close} 个",
        )

    # 圆括号 ()
    paren_open = code_free.count("(")
    paren_close = code_free.count(")")
    if paren_open != paren_close:
        add_findings(
            findings,
            "ERROR",
            line_no,
            "UNPAIRED_PARENTHESES",
            f"圆括号 () 不匹配：左 {paren_open} 个，右 {paren_close} 个",
        )


def _validate_cjk_ascii_spacing(
    findings: list[Finding],
    line_no: int,
    text: str,
) -> None:
    """检查中文字符与英文/数字之间是否存在空格。"""
    stripped = text.strip()
    if not stripped:
        return
    # 跳过标题行
    if ATX_HEADING_RE.match(stripped):
        return
    # 跳过表格行
    if TABLE_ROW_RE.match(stripped) or TABLE_SEP_RE.match(stripped):
        return
    # 跳过引用块中的图片占位符和描述
    if stripped.startswith("> [") or stripped.startswith("> 描述："):
        return
    # 跳过参考文献列表行
    if REFERENCE_ITEM_RE.match(stripped):
        return
    # 跳过表题和图题行（支持加粗格式）
    if stripped.startswith("表") or stripped.startswith("图") or stripped.startswith("**表") or stripped.startswith("**图"):
        return

    # 先保护行内代码、URL、图片语法中的内容
    protected_text = re.sub(r"`[^`]*`", lambda m: "\x00" * len(m.group(0)), text)
    protected_text = re.sub(r"!\[[^\]]*\]\([^)]*\)", lambda m: "\x00" * len(m.group(0)), protected_text)
    protected_text = re.sub(r"\[[^\]]+\]\([^)]+\)", lambda m: "\x00" * len(m.group(0)), protected_text)

    # 检查 中文 + 空格 + ASCII/数字
    for m in re.finditer(r"[一-鿿㐀-䶿　-〿＀-￯]\s+[A-Za-z0-9]", protected_text):
        add_findings(
            findings,
            "ERROR",
            line_no,
            "CJK_ASCII_SPACE",
            "中文字符与英文/数字之间不得有空格，请删除空格",
        )
        break  # 每行只报一次

    # 检查 ASCII/数字 + 空格 + 中文
    for m in re.finditer(r"[A-Za-z0-9]\s+[一-鿿㐀-䶿　-〿＀-￯]", protected_text):
        add_findings(
            findings,
            "ERROR",
            line_no,
            "ASCII_CJK_SPACE",
            "英文/数字与中文字符之间不得有空格，请删除空格",
        )
        break


def _validate_formula_number(
    findings: list[Finding],
    line_no: int,
    text: str,
    current_chapter_no: str | None,
    formula_seq_in_chapter: dict[int, int],
) -> None:
    m = FORMULA_NUMBER_RE.search(text)
    if not m:
        return
    # \tag{X-Y} -> groups 1,2; (X-Y) or \(X-Y\) -> groups 3,4
    if m.group(1) is not None:
        chapter = int(m.group(1))
        seq = int(m.group(2))
    else:
        chapter = int(m.group(3))
        seq = int(m.group(4))
    if current_chapter_no is not None and chapter != int(current_chapter_no):
        add_findings(
            findings,
            "WARN",
            line_no,
            "FORMULA_NUMBER_MISMATCH",
            f"公式编号章节号不一致：当前章节为 {current_chapter_no}，但公式编号为 ({chapter}-{seq})",
        )
    expected = formula_seq_in_chapter.get(chapter, 0) + 1
    if seq != expected:
        add_findings(
            findings,
            "ERROR",
            line_no,
            "FORMULA_NUMBER_DISCONTINUITY",
            f"公式编号不连续：章节 {chapter} 当前期望 ({chapter}-{expected})，实际为 ({chapter}-{seq})",
        )
    formula_seq_in_chapter[chapter] = seq



def _validate_figure_table_sequence(
    findings: list[Finding],
    image_lines: list[tuple[int, str, str | None]],
    table_starts: list[tuple[int, str | None]],
    lines: list[str],
) -> None:
    """检查图片和表格的序号是否连续、章节号是否匹配。"""
    # 图片序号检查
    figure_seq: dict[int, int] = {}
    for img_line, alt, chapter_no in image_lines:
        m = re.search(r"(?:图|Figure|Fi\.)\s*(\d+)\s*[-－]\s*(\d+)", alt)
        if m:
            chapter = int(m.group(1))
            seq = int(m.group(2))
            if chapter_no is not None and chapter != int(chapter_no):
                add_findings(
                    findings,
                    "WARN",
                    img_line,
                    "FIGURE_NUMBER_MISMATCH",
                    f"图片编号章节号不一致：当前章节为 {chapter_no}，但图片编号为 {chapter}-{seq}",
                )
            expected = figure_seq.get(chapter, 0) + 1
            if seq != expected:
                add_findings(
                    findings,
                    "ERROR",
                    img_line,
                    "FIGURE_NUMBER_DISCONTINUITY",
                    f"图片编号不连续：章节 {chapter} 当前期望 {chapter}-{expected}，实际为 {chapter}-{seq}",
                )
            figure_seq[chapter] = seq
        else:
            add_findings(
                findings,
                "WARN",
                img_line,
                "FIGURE_NUMBER_MISSING",
                "图片缺少规范的序号（建议格式：图x-x 标题）",
            )

    # 表格序号检查
    table_seq: dict[int, int] = {}
    for start, chapter_no in table_starts:
        look = start - 1
        while look >= 1 and not lines[look - 1].strip():
            look -= 1
        if look >= 1:
            caption = lines[look - 1].strip()
            m = re.search(r"(?:表|Table)\s*(\d+)\s*[-－]\s*(\d+)", caption)
            if m:
                chapter = int(m.group(1))
                seq = int(m.group(2))
                if chapter_no is not None and chapter != int(chapter_no):
                    add_findings(
                        findings,
                        "WARN",
                        start,
                        "TABLE_NUMBER_MISMATCH",
                        f"表格编号章节号不一致：当前章节为 {chapter_no}，但表格编号为 {chapter}-{seq}",
                    )
                expected = table_seq.get(chapter, 0) + 1
                if seq != expected:
                    add_findings(
                        findings,
                        "ERROR",
                        start,
                        "TABLE_NUMBER_DISCONTINUITY",
                        f"表格编号不连续：章节 {chapter} 当前期望 {chapter}-{expected}，实际为 {chapter}-{seq}",
                    )
                table_seq[chapter] = seq
            else:
                add_findings(
                    findings,
                    "WARN",
                    start,
                    "TABLE_NUMBER_MISSING",
                    "表格缺少规范的序号（建议格式：表x-x 标题）",
                )


def _validate_text_around_blocks(
    findings: list[Finding],
    image_lines: list[tuple[int, str, str | None]],
    table_starts: list[tuple[int, str | None]],
    lines: list[str],
) -> None:
    """检查图片和表格前后是否有段落文字描述（不能只有表题/图题）。"""

    def _is_valid_text(line: str) -> bool:
        s = line.strip()
        if not s:
            return False
        if ATX_HEADING_RE.match(s):
            return False
        if IMAGE_MD_RE.search(s):
            return False
        if TABLE_ROW_RE.match(s) or TABLE_SEP_RE.match(s):
            return False
        if TABLE_CAPTION_RE.match(s):
            return False
        if FIGURE_TITLE_RE_LOOSE.match(s):
            return False
        if s.startswith("```") or s.startswith("$$") or s.startswith(">"):
            return False
        if s == "---":
            return False
        if SETEXT_RE.match(s):
            return False
        if REFERENCE_ITEM_RE.match(s):
            return False
        return True

    # 图片前后文字描述（前后至少有一个即可）
    for img_line, _alt, _chapter in image_lines:
        has_text_before = False
        for i in range(img_line - 2, -1, -1):
            if _is_valid_text(lines[i]):
                has_text_before = True
                break
            if lines[i].strip():
                break

        has_text_after = False
        for i in range(img_line, len(lines)):
            if _is_valid_text(lines[i]):
                has_text_after = True
                break
            if lines[i].strip():
                break

        if not has_text_before and not has_text_after:
            add_findings(
                findings,
                "ERROR",
                img_line,
                "MISSING_TEXT_AROUND_IMAGE",
                "图片前后均缺少段落文字描述，请在图片前或图片后添加对图片的说明或分析文字",
            )

    # 表格前后文字描述（前后至少有一个即可）
    for start, _chapter in table_starts:
        table_end = start
        for j in range(start, len(lines)):
            if not TABLE_ROW_RE.match(lines[j].strip()):
                break
            table_end = j

        has_text_before = False
        look = start - 2
        while look >= 0 and not lines[look].strip():
            look -= 1
        if look >= 0 and TABLE_CAPTION_RE.match(lines[look].strip()):
            look -= 1
        while look >= 0 and not lines[look].strip():
            look -= 1
        if look >= 0 and _is_valid_text(lines[look]):
            has_text_before = True

        has_text_after = False
        look = table_end + 1
        while look < len(lines) and not lines[look].strip():
            look += 1
        if look < len(lines) and _is_valid_text(lines[look]):
            has_text_after = True

        if not has_text_before and not has_text_after:
            add_findings(
                findings,
                "ERROR",
                start,
                "MISSING_TEXT_AROUND_TABLE",
                "表格前后均缺少段落文字描述，请在表格前或表格后添加对表格的说明或分析文字",
            )

def check_markdown(path: Path) -> tuple[list[Finding], list[str]]:
    raw = path.read_bytes()
    findings: list[Finding] = []
    notes: list[str] = []

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        add_findings(findings, "ERROR", exc.start + 1, "ENCODING", "文件不是有效 UTF-8 编码")
        return findings, notes

    if "\r\n" in text:
        notes.append("检测到 CRLF 行尾，建议统一为 LF（非强制）")

    lines = text.splitlines()
    in_fence = False
    table_starts: list[tuple[int, str | None]] = []  # (行号, 章节号)
    h1_count = 0
    first_heading_line = None

    # 标题层级跟踪
    prev_heading_level = 0
    current_chapter_no: str | None = None  # e.g. "1"
    current_section_no: str | None = None  # e.g. "1.1"

    # 记录图片位置，用于后续重复标题检查
    image_lines: list[tuple[int, str, str | None]] = []  # (行号, alt文本, 章节号)

    # 公式检查状态
    in_math_block = False
    pending_formula_line: int | None = None  # 等待下一行检查公式编号的行号
    formula_seq_in_chapter: dict[int, int] = {}  # chapter -> last_seen_seq

    # 禁止 Pandoc/YAML 元信息区块
    if lines:
        first_non_empty_idx = None
        for i, ln in enumerate(lines, start=1):
            if ln.strip():
                first_non_empty_idx = i
                break
        if first_non_empty_idx is not None:
            first_line = lines[first_non_empty_idx - 1].strip()
            if first_line == "---":
                add_findings(findings, "ERROR", first_non_empty_idx, "META_FRONT_MATTER", "禁止 YAML front matter 元信息区块")
            if first_line.startswith("%"):
                add_findings(findings, "ERROR", first_non_empty_idx, "META_PANDOC_BLOCK", "禁止 Pandoc 标题元信息块（% 开头）")

    in_references_section = False
    in_appendix_section = False

    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()

        # 处理待检查的公式编号（上一行数学块结束后第一行非空内容）
        if pending_formula_line is not None and stripped:
            _validate_formula_number(
                findings, idx, stripped, current_chapter_no, formula_seq_in_chapter
            )
            pending_formula_line = None

        # fenced code state toggle
        if stripped.startswith("```"):
            if MERMAID_FENCE_RE.match(stripped):
                add_findings(findings, "WARN", idx, "MERMAID_DISABLED", "检测到 Mermaid 代码块：当前导出流程会移除该代码块")
            in_fence = not in_fence
            continue

        if in_fence:
            continue

        # math block toggle
        if stripped.startswith("$$"):
            if in_math_block:
                # 关闭数学块：当前行检查公式编号
                _validate_formula_number(
                    findings, idx, stripped, current_chapter_no, formula_seq_in_chapter
                )
                # 若当前行没有编号，标记下一行待检查
                if not FORMULA_NUMBER_RE.search(stripped):
                    pending_formula_line = idx
                in_math_block = False
            else:
                # 开启数学块
                if stripped.endswith("$$") and len(stripped) > 4:
                    # 单行块：立即检查公式编号，不进入 math_block 状态
                    _validate_formula_number(
                        findings, idx, stripped, current_chapter_no, formula_seq_in_chapter
                    )
                    if not FORMULA_NUMBER_RE.search(stripped):
                        pending_formula_line = idx
                else:
                    in_math_block = True
            continue

        if in_math_block:
            continue

        # 跳过表格行和表格分隔行的配对检查（单元格内标记不应作为Markdown解析）
        is_table = bool(TABLE_ROW_RE.match(line) or TABLE_SEP_RE.match(line))
        if not is_table:
            _validate_paired_double_quotes(findings, idx, line)
            _validate_markdown_pairs(findings, idx, line)
        _validate_cjk_ascii_spacing(findings, idx, line)

        heading = ATX_HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2).strip().lower()
            raw_title = heading.group(2).strip()
            if first_heading_line is None:
                first_heading_line = idx

            # 附录区域判定
            if level == 1 and title == "附录":
                in_appendix_section = True
            elif level == 1 and in_appendix_section:
                in_appendix_section = False

            # 跳级检查（附录区域跳过）
            if not in_appendix_section and prev_heading_level > 0 and level > prev_heading_level + 1:
                add_findings(
                    findings,
                    "ERROR",
                    idx,
                    "HEADING_SKIP_LEVEL",
                    f"标题层级跳级：从 level {prev_heading_level} 直接到 level {level}，请保持层级连续",
                )

            if level == 1:
                h1_count += 1
                # 提取章节号（支持 "1 引言" 和 "第1章 引言" 两种格式）
                m = re.match(r"^(?:第)?(\d+)\s*章?\s+", raw_title)
                if m:
                    current_chapter_no = m.group(1)
                elif title not in SPECIAL_HEADINGS:
                    add_findings(
                        findings,
                        "ERROR",
                        idx,
                        "THESIS_TITLE_IN_BODY",
                        "请勿在正文中使用一级标题写论文题目（应由封面提供），章节请从 '# 1 引言' 开始",
                    )
                current_section_no = None
            elif level == 2:
                if not in_appendix_section and not re.match(r"^\d+\.\d+\s+", raw_title):
                    add_findings(
                        findings,
                        "ERROR",
                        idx,
                        "HEADING2_FORMAT",
                        "二级标题必须使用 '数字.数字 标题' 格式（如 '## 1.1 研究背景'）",
                    )
                else:
                    m = re.match(r"^(\d+)\.\d+", raw_title)
                    if m:
                        section_chapter = m.group(1)
                        if current_chapter_no is not None and section_chapter != current_chapter_no:
                            add_findings(
                                findings,
                                "ERROR",
                                idx,
                                "HEADING2_CHAPTER_MISMATCH",
                                f"二级标题章节号不一致：当前章节为 {current_chapter_no}，但二级标题以 {section_chapter} 开头",
                            )
                        current_section_no = re.match(r"^(\d+\.\d+)", raw_title).group(1)
            elif level == 3:
                if not in_appendix_section and not re.match(r"^\d+\.\d+\.\d+\s+", raw_title):
                    add_findings(
                        findings,
                        "ERROR",
                        idx,
                        "HEADING3_FORMAT",
                        "三级标题必须使用 '数字.数字.数字 标题' 格式（如 '### 1.1.1 国内外现状'）",
                    )
                else:
                    m = re.match(r"^(\d+\.\d+)\.\d+", raw_title)
                    if m:
                        section_prefix = m.group(1)
                        if current_section_no is not None and section_prefix != current_section_no:
                            add_findings(
                                findings,
                                "ERROR",
                                idx,
                                "HEADING3_SECTION_MISMATCH",
                                f"三级标题编号不一致：当前二级为 {current_section_no}，但三级标题以 {section_prefix} 开头",
                            )

            if title in SPECIAL_HEADINGS and level != 1:
                add_findings(findings, "ERROR", idx, "SPECIAL_HEADING_LEVEL", "摘要/Abstract/参考文献/致谢必须使用一级标题（#）")

            prev_heading_level = level

            # 参考文献区域边界判定
            if level == 1 and title == "参考文献":
                in_references_section = True
            elif level == 1 and in_references_section:
                in_references_section = False

            continue

        # 顶部元信息字段（Key: Value）不允许
        if first_heading_line is None and idx <= 40 and META_FIELD_RE.match(stripped):
            add_findings(findings, "ERROR", idx, "META_FIELD", "检测到顶部元信息字段（Key: Value），请移除")

        # forbid html img
        if IMG_HTML_RE.search(line):
            add_findings(findings, "ERROR", idx, "HTML_IMG", "不建议使用 <img>，请改用 Markdown 图片语法")

        # setext heading warning
        if idx > 1 and SETEXT_RE.match(stripped):
            prev = lines[idx - 2]
            if is_setext_candidate(prev):
                add_findings(findings, "WARN", idx, "SETEXT_HEADING", "检测到 Setext 标题风格，建议改用 #/##/###")

        # image checks
        for m in IMAGE_MD_RE.finditer(line):
            alt = m.group(1).strip()
            rel = m.group(2).strip()
            if not alt:
                add_findings(findings, "WARN", idx, "IMAGE_ALT_EMPTY", "图片 alt 为空，建议填写图题（如 图3-1 xxx）")
            elif not FIGURE_TITLE_RE.match(alt):
                add_findings(findings, "WARN", idx, "IMAGE_TITLE_STYLE", "图片标题建议使用“图x-x 标题”格式")

            if FORMULA_IMG_KEYWORDS_RE.search(alt):
                add_findings(
                    findings,
                    "ERROR",
                    idx,
                    "FORMULA_AS_IMAGE",
                    "禁止将公式以图片形式插入，请使用 LaTeX 数学语法（如 $E=mc^2$ 或 $$...$$）",
                )

            image_lines.append((idx, alt, current_chapter_no))

            # local path existence check (ignore URL)
            if not re.match(r"^(https?://|data:)", rel, re.IGNORECASE):
                local = (path.parent / rel).resolve()
                if not local.exists():
                    add_findings(findings, "WARN", idx, "IMAGE_PATH_MISSING", f"图片路径不存在: {rel}")

        # citation simple check
        if "[" in line and "]" in line:
            for m in CITATION_RE.finditer(line):
                if int(m.group(1)) <= 0:
                    add_findings(findings, "WARN", idx, "CITATION_INVALID", "引用编号应为正整数")

        # markdown table start check
        if TABLE_ROW_RE.match(line) and idx < len(lines):
            next_line = lines[idx].strip()
            if TABLE_SEP_RE.match(next_line):
                table_starts.append((idx, current_chapter_no))

        # 参考文献条目之间必须有空行
        if in_references_section and REFERENCE_ITEM_RE.match(stripped) and idx < len(lines):
            next_line = lines[idx].strip()
            if next_line and next_line.startswith("["):
                add_findings(
                    findings,
                    "ERROR",
                    idx,
                    "REF_MISSING_BLANK_LINE",
                    "参考文献条目之间缺少空行，请在每条文献后添加一个空行",
                )

    # 图片下方重复标题检查
    for img_line, alt, _chapter in image_lines:
        if not alt:
            continue
        normalized_alt = _normalize_caption(alt)
        # 检查图片之后的非空行
        nxt = img_line
        while nxt < len(lines) and not lines[nxt].strip():
            nxt += 1
        if nxt < len(lines):
            nxt_stripped = lines[nxt].strip()
            if FIGURE_TITLE_RE_LOOSE.match(nxt_stripped):
                nxt_norm = _normalize_caption(nxt_stripped)
                if nxt_norm == normalized_alt:
                    add_findings(
                        findings,
                        "ERROR",
                        nxt + 1,
                        "DUPLICATE_FIGURE_CAPTION",
                        f"图片下方重复出现图题“{nxt_norm}”，标题应仅在图片 alt 中体现",
                    )

    # table caption check: line before table start should be caption (allow blank spacer)
    for start, _tbl_chapter in table_starts:
        look = start - 1
        blank_spacer = 0
        while look >= 1 and not lines[look - 1].strip():
            look -= 1
            blank_spacer += 1
        if look < 1:
            add_findings(findings, "WARN", start, "TABLE_CAPTION_MISSING", "表格前缺少表题（建议“表x-x 标题”）")
            continue
        if not TABLE_CAPTION_RE.match(lines[look - 1]):
            add_findings(findings, "WARN", start, "TABLE_CAPTION_STYLE", "表格前一行不是规范表题（建议“表x-x 标题”）")
            continue


    if h1_count == 0:
        add_findings(findings, "ERROR", 1, "NO_H1", "文档必须使用一级标题（#）组织章节")

    _validate_figure_table_sequence(findings, image_lines, table_starts, lines)
    _validate_text_around_blocks(findings, image_lines, table_starts, lines)

    return findings, notes


def main() -> None:
    parser = argparse.ArgumentParser(description="检查 Markdown 是否符合本项目导出规范")
    parser.add_argument("--md", required=True, help="Markdown 文件路径")
    parser.add_argument("--strict", action="store_true", help="将 WARN 也视为失败")
    args = parser.parse_args()

    path = Path(args.md).resolve()
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")

    findings, notes = check_markdown(path)

    print(f"[md-check] file={path}")
    for n in notes:
        print(f"[md-check] NOTE: {n}")

    if not findings:
        print("[md-check] PASS: 未发现规范问题")
        return

    level_rank = {"ERROR": 0, "WARN": 1}
    findings.sort(key=lambda f: (level_rank.get(f.level, 9), f.line, f.code))

    err = 0
    warn = 0
    for f in findings:
        print(f"[md-check] {f.level} L{f.line} {f.code}: {f.message}")
        if f.level == "ERROR":
            err += 1
        elif f.level == "WARN":
            warn += 1

    print(f"[md-check] SUMMARY: ERROR={err}, WARN={warn}")

    if err > 0:
        raise SystemExit(2)
    if args.strict and warn > 0:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
