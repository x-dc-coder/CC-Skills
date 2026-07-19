#!/usr/bin/env python3
"""Domain profiler for the thesis-writing skill's journal-paper mode.

Reads a paper-analysis/ corpus (MinerU content_list.json files, produced by the
paper-reader skill) and emits a machine-readable domain profile that drives
section-skeleton selection, figure/table/equation placement, and citation-style
decisions in the writing-plan phase.

Usage:
    cd ~/.claude/skills && uv run python thesis-writing/scripts/profile_papers.py \
        --corpus /path/to/paper-analysis/ --out /path/to/output/

Outputs:
    <out>/_domain_profile.json   — machine-readable (consumed by the skill)
    <out>/_domain_profile.md     — human-readable (consumed by the user review step)

Design:
    - Pure stdlib (json, re, pathlib, statistics). No LLM tokens consumed.
    - O(papers × blocks_per_paper) — runs in <1s for a 30-paper corpus.
    - Idempotent: same corpus → same profile (modulo timestamps).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

PROFILER_VERSION = "1.0"


class ProfileError(Exception):
    """Raised when the corpus cannot be profiled (empty, malformed, etc.)."""


# ---------------------------------------------------------------------------
# Paper discovery
# ---------------------------------------------------------------------------

@dataclass
class Paper:
    name: str
    content_list_path: Path
    marker_md_path: Path | None = None
    blocks: list[dict] = field(default_factory=list)

    def load_blocks(self) -> list[dict]:
        if self.blocks:
            return self.blocks
        try:
            data = json.loads(self.content_list_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProfileError(f"failed to read {self.content_list_path}: {exc}") from exc
        if not isinstance(data, list):
            raise ProfileError(f"{self.content_list_path}: expected a JSON list")
        self.blocks = [b for b in data if isinstance(b, dict)]
        return self.blocks


_CONTENT_LIST_GLOB = "**/*_content_list.json"


def discover_papers(corpus_dir: Path) -> list[Paper]:
    """Walk corpus_dir for MinerU content_list.json files.

    Skips papers whose mineru/ directory exists but contains no content_list.json
    (emits a warning on stderr). Raises ProfileError if zero papers are found.
    """
    papers: list[Paper] = []
    empty_dirs: list[str] = []
    for paper_dir in sorted(p for p in corpus_dir.iterdir() if p.is_dir()):
        mineru_dir = paper_dir / "mineru"
        if not mineru_dir.is_dir():
            continue
        v2_files = list(mineru_dir.rglob("*_content_list.json"))
        v2_files = [f for f in v2_files if "_v2" not in f.name]
        if not v2_files:
            empty_dirs.append(paper_dir.name)
            continue
        cl_path = v2_files[0]
        marker_md = None
        marker_dir = paper_dir / "marker"
        if marker_dir.is_dir():
            md_files = list(marker_dir.rglob("*.md"))
            if md_files:
                marker_md = md_files[0]
        papers.append(Paper(
            name=paper_dir.name,
            content_list_path=cl_path,
            marker_md_path=marker_md,
        ))
    if empty_dirs:
        for name in empty_dirs:
            print(f"[profile_papers] WARN: skipping '{name}' (no content_list.json)",
                  file=sys.stderr)
    if not papers:
        raise ProfileError(
            f"corpus '{corpus_dir}' contains no papers with parseable content_list.json; "
            f"run paper-reader on the source PDFs first"
        )
    return papers


# ---------------------------------------------------------------------------
# Section title normalization + canonical mapping
# ---------------------------------------------------------------------------

_NUM_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"(?:section\s+)?\d+(?:\.\d+)*\.?\s*[:：]?\s+"   # 1 / 1. / 1.2 / Section 4:
    r"|[IVXLC]+\.\s+"
    r"|第[一二三四五六七八九十百千\d]+[章节]\s*"
    r"|[（(]\d+[）)]\s*"
    r")",
    re.IGNORECASE,
)
_TRAILING_PUNCT_RE = re.compile(r"[\s.。:：]+$")


def normalize_section_title(raw: str, keep_case: bool = False) -> str:
    """Strip numbering prefix and trailing punctuation.

    By default lowercases (used as a dict key for canonical lookup).
    Pass keep_case=True to preserve the original case (used for human-readable
    variant reporting, e.g. 'Introduction' rather than 'introduction').
    """
    s = raw.strip()
    s = _NUM_PREFIX_RE.sub("", s, count=1)
    s = _TRAILING_PUNCT_RE.sub("", s)
    s = s.strip()
    return s if keep_case else s.lower()


# Canonical labels: variants → single canonical key.
# Keys use snake_case so they can be used as JSON object keys / identifiers.
_CANONICAL_MAP: dict[str, str] = {
    "introduction": "introduction",
    "intro": "introduction",
    "background": "background",
    "motivation": "background",
    "related work": "related_work",
    "related works": "related_work",
    "related research": "related_work",
    "literature review": "related_work",
    "prior work": "related_work",
    "preliminaries": "preliminaries",
    "preliminary": "preliminaries",
    "problem definition": "preliminaries",
    "problem formulation": "preliminaries",
    "problem statement": "preliminaries",
    "definitions": "preliminaries",
    "notations": "preliminaries",
    "notation": "preliminaries",
    "method": "method",
    "methods": "method",
    "methodology": "method",
    "approach": "method",
    "our approach": "method",
    "proposed approach": "method",
    "proposed method": "method",
    "the proposed framework": "method",
    "framework": "method",
    "model": "method",
    "algorithm": "method",
    "algorithm design": "method",
    "solution approach": "method",
    "move evaluation and attribute matrix": "method",
    "tensor-based gpu acceleration framework": "method",
    "tensor-based gpu acceleration for local search operators": "method",
    "the proposed algorithm": "method",
    "our method": "method",
    "the proposed method": "method",
    "design": "method",
    "system design": "method",
    "architecture": "method",
    "system architecture": "method",
    "experiments": "experiments",
    "experiment": "experiments",
    "experimental results": "experiments",
    "results": "experiments",
    "evaluation": "experiments",
    "experiments and results": "experiments",
    "computational results": "experiments",
    "empirical study": "experiments",
    "empirical evaluation": "experiments",
    "case study": "experiments",
    "discussion": "discussion",
    "discussions": "discussion",
    "analysis": "discussion",
    "conclusion": "conclusion",
    "conclusions": "conclusion",
    "concluding remarks": "conclusion",
    "summary": "conclusion",
    "conclusion and future work": "conclusion",
    "future work": "conclusion",
    "abstract": "abstract",
    "keywords": "keywords",
    "acknowledgments": "acknowledgments",
    "acknowledgements": "acknowledgments",
    "references": "references",
    "bibliography": "references",
    "appendix": "appendix",
    "appendices": "appendix",
    "supplementary material": "appendix",
    "taxonomy": "taxonomy",
    "open challenges": "open_challenges",
    "future directions": "open_challenges",
}


def canonical_section_label(normalized_title: str) -> str:
    """Map a normalized section title to its canonical label.

    Three-stage resolution:
      1. Exact match in _CANONICAL_MAP (handles canonical forms + common synonyms).
      2. Keyword-based substring match (handles numbered subsection variants
         like '3.1 reformulating kd', '4.4 comparison with state-of-the-arts'
         that MinerU tags as level-2 headings).
      3. Fall back to the normalized title verbatim (rare/domain-specific
         sections are preserved as-is for the human-readable report).

    The keyword stage is what makes the profiler domain-agnostic: rather than
    enumerating every possible subsection name, we recognize the parent section
    by its characteristic keywords (experiment/ablation/baseline → experiments,
     distillation/architecture/method → method, etc.).
    """
    exact = _CANONICAL_MAP.get(normalized_title)
    if exact:
        return exact
    for pattern, canonical in _SECTION_KEYWORD_PATTERNS:
        if pattern.search(normalized_title):
            return canonical
    return normalized_title


import re as _re_for_patterns

# Keyword patterns applied AFTER exact-match lookup fails. Substring-based
# canonicalization lets us recognize numbered subsection variants like
# '3.1 reformulating kd' or '4.4 comparison with state-of-the-arts' that MinerU
# tags as level-2 headings, without enumerating every possible subsection name.
#
# ORDER MATTERS: more specific patterns must precede broader ones. E.g.
# 'ablation' must come before 'experiment' so 'ablation study' → experiments
# rather than being caught by a later general pattern.
_SECTION_KEYWORD_PATTERNS: list[tuple["re.Pattern[str]", str]] = [
    (_re_for_patterns.compile(r"\b(ablation|ablating)\b"), "experiments"),
    (_re_for_patterns.compile(r"\bcomparison with (the )?state[- ]?of[- ]?the[- ]?art"), "experiments"),
    (_re_for_patterns.compile(r"\b(baseline|benchmark|evaluation results|main results|experimental results)\b"), "experiments"),
    (_re_for_patterns.compile(r"\b(experiment|experiments|experimental setup|implementation details|datasets? and metrics?|training details|results and analysis|qualitative results|quantitative results)\b"), "experiments"),
    (_re_for_patterns.compile(r"(消融|对比实验|实验结果|实验设置|数据集|训练细节|实现细节|可视化|效果)"), "experiments"),
    (_re_for_patterns.compile(r"\b(visualiz|visualization|reconstruction results?|image quality)\b"), "experiments"),
    (_re_for_patterns.compile(r"\b(distillation|distilling|kd|knowledge distillation)\b"), "method"),
    (_re_for_patterns.compile(r"\b(proposed (method|approach|framework)|our (method|approach|framework))\b"), "method"),
    (_re_for_patterns.compile(r"\b(network architecture|model architecture|architecture|backbone|encoder|decoder)\b"), "method"),
    (_re_for_patterns.compile(r"\b(loss function|loss design|objective function|training objective|attention transfer|feature distillation|contrastive)\b"), "method"),
    (_re_for_patterns.compile(r"\b(method|methods|methodology|approach|algorithm design|formulation|pipeline)\b"), "method"),
    (_re_for_patterns.compile(r"(算法|方法|模型|网络结构|损失函数|注意力机制|特征蒸馏)"), "method"),
    (_re_for_patterns.compile(r"\b(related work|related works?|prior work|literature review)\b"), "related_work"),
    (_re_for_patterns.compile(r"\b(preliminaries|preliminary|background|problem (definition|formulation|statement))\b"), "preliminaries"),
    (_re_for_patterns.compile(r"\b(representation analysis|representation learning|notation|notations|definitions?)\b"), "preliminaries"),
    (_re_for_patterns.compile(r"(预备知识|相关工作|问题定义|符号说明|背景)"), "preliminaries"),
    (_re_for_patterns.compile(r"\b(discussion|discussions|analysis|analysis of|discussion and conclusion)\b"), "discussion"),
    (_re_for_patterns.compile(r"\b(model analysis|complexity analysis|theoretical analysis|running time|efficiency analysis)\b"), "discussion"),
    (_re_for_patterns.compile(r"(讨论|分析)"), "discussion"),
    (_re_for_patterns.compile(r"\b(conclusion|conclusions? and future work|concluding remarks|summary|future work|future directions?)\b"), "conclusion"),
    (_re_for_patterns.compile(r"(结论|总结|展望)"), "conclusion"),
    (_re_for_patterns.compile(r"(appendix|appendices|supplementary( material)?|附录|补充材料)"), "appendix"),
    (_re_for_patterns.compile(r"(acknowledg(e)?ments?|致谢|鸣谢)"), "acknowledgments"),
    (_re_for_patterns.compile(r"(references|bibliography|参考文献)"), "references"),
    (_re_for_patterns.compile(r"\b(introduction|motivation|contributions?)\b"), "introduction"),
    (_re_for_patterns.compile(r"(引言|绪论|介绍)"), "introduction"),
]


# ---------------------------------------------------------------------------
# Asset sub-type classification
# ---------------------------------------------------------------------------

# Image/chart sub-types. Heuristic: figures in the Method section are
# framework/architecture overviews; figures in Experiments are data plots.
_METHOD_SECTION_LABELS = {"method", "preliminaries", "background"}
_EXPERIMENT_SECTION_LABELS = {"experiments", "results", "discussion"}


def _classify_figure(section_label: str, block_type: str) -> str:
    """Classify an image/chart block by where it appears."""
    if block_type == "chart":
        if section_label in _EXPERIMENT_SECTION_LABELS:
            return "data-plot"
        return "chart-other"
    # block_type == "image"
    if section_label in _METHOD_SECTION_LABELS:
        return "framework-overview"
    if section_label in _EXPERIMENT_SECTION_LABELS:
        return "result-figure"
    if section_label == "introduction":
        return "concept-diagram"
    return "image-other"


def _classify_table(section_label: str) -> str:
    if section_label in _EXPERIMENT_SECTION_LABELS:
        return "benchmark-comparison"
    if section_label in _METHOD_SECTION_LABELS:
        return "notation-table"
    if section_label == "preliminaries":
        return "notation-table"
    return "table-other"


def _classify_equation(section_label: str) -> str:
    if section_label == "preliminaries":
        return "problem-definition"
    if section_label == "method":
        return "method-formulation"
    if section_label in _EXPERIMENT_SECTION_LABELS:
        return "evaluation-metric"
    return "equation-other"


# ---------------------------------------------------------------------------
# Section skeleton extraction
# ---------------------------------------------------------------------------

@dataclass
class SectionStat:
    canonical: str
    frequency: int = 0
    variants_seen: set[str] = field(default_factory=set)
    positions: list[float] = field(default_factory=list)
    word_shares: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "canonical": self.canonical,
            "frequency": self.frequency,
            "variants_seen": sorted(self.variants_seen),
            "median_position": round(statistics.median(self.positions), 3) if self.positions else 0.0,
            "median_word_share": round(statistics.median(self.word_shares), 3) if self.word_shares else 0.0,
        }


def _is_title_block(b: dict) -> tuple[str, int] | None:
    """Return (title_text, level) if block b is a heading, else None.

    MinerU content_list.json represents headings as type="text" with a
    "text_level" field (1 = paper title, 2 = section, 3 = subsection).
    """
    if b.get("type") != "text":
        return None
    level = b.get("text_level")
    if level is None or not isinstance(level, int) or level < 1:
        return None
    text = b.get("text", "").strip()
    if not text:
        return None
    return text, level


def _block_word_count(b: dict) -> int:
    if b.get("type") == "text":
        return len(b.get("text", "").split())
    if b.get("type") == "equation":
        return 1
    return 0


def extract_section_skeleton(papers: list[Paper]) -> list[dict]:
    """Aggregate section-level headings across all papers into frequency stats.

    variants_seen stores each section's raw heading text verbatim (including
    original numbering like '1 Introduction', 'I. INTRODUCTION') rather than the
    normalized form, so the human-readable report shows what titles actually
    look like in the field. Canonicalization happens separately via
    canonical_section_label() for aggregation keys.
    """
    stats: dict[str, SectionStat] = defaultdict(lambda: SectionStat(canonical=""))
    for paper in papers:
        blocks = paper.load_blocks()
        section_starts: list[tuple[int, str, str]] = []
        total_blocks = len(blocks)
        for idx, b in enumerate(blocks):
            t = _is_title_block(b)
            if t and t[1] == 2:
                raw_title = t[0].strip()
                canonical = canonical_section_label(normalize_section_title(raw_title))
                section_starts.append((idx, raw_title, canonical))
        if not section_starts:
            continue
        total_words = sum(_block_word_count(b) for b in blocks) or 1
        for i, (idx, raw_title, canonical) in enumerate(section_starts):
            end_idx = section_starts[i + 1][0] if i + 1 < len(section_starts) else total_blocks
            section_words = sum(_block_word_count(b) for b in blocks[idx:end_idx])
            stat = stats[canonical]
            stat.canonical = canonical
            stat.frequency += 1
            stat.variants_seen.add(raw_title)
            stat.positions.append(idx / total_blocks if total_blocks else 0.0)
            stat.word_shares.append(section_words / total_words)
    # Sort by frequency desc, then alphabetical
    ordered = sorted(stats.values(), key=lambda s: (-s.frequency, s.canonical))
    return [s.to_dict() for s in ordered]


# ---------------------------------------------------------------------------
# Asset pattern extraction
# ---------------------------------------------------------------------------

@dataclass
class AssetPattern:
    section: str
    sub_type: str
    frequency: int = 0

    def to_dict(self) -> dict:
        return {"section": self.section, "sub_type": self.sub_type, "frequency": self.frequency}


def extract_asset_patterns(papers: list[Paper]) -> tuple[list[dict], list[dict], list[dict]]:
    """Attribute figures/tables/equations to their nearest preceding section."""
    fig_counter: Counter = Counter()
    tbl_counter: Counter = Counter()
    eq_counter: Counter = Counter()

    for paper in papers:
        blocks = paper.load_blocks()
        current_section = "front_matter"
        for b in blocks:
            t = _is_title_block(b)
            if t and t[1] == 2:
                current_section = canonical_section_label(normalize_section_title(t[0]))
                continue
            btype = b.get("type")
            if btype in ("image", "chart"):
                sub = _classify_figure(current_section, btype)
                fig_counter[(current_section, sub)] += 1
            elif btype == "table":
                sub = _classify_table(current_section)
                tbl_counter[(current_section, sub)] += 1
            elif btype == "equation":
                sub = _classify_equation(current_section)
                eq_counter[(current_section, sub)] += 1

    def _to_list(counter: Counter) -> list[dict]:
        items = [AssetPattern(section=s, sub_type=st, frequency=f)
                 for (s, st), f in counter.items()]
        items.sort(key=lambda a: (-a.frequency, a.section, a.sub_type))
        return [a.to_dict() for a in items]

    return _to_list(fig_counter), _to_list(tbl_counter), _to_list(eq_counter)


# ---------------------------------------------------------------------------
# Citation style detection
# ---------------------------------------------------------------------------

_BRACKET_NUMERIC_RE = re.compile(r"\[\d+\]")
_AUTHOR_YEAR_PAREN_RE = re.compile(
    r"\([A-Z][A-Za-z''-]+(?:\s+(?:et al\.?|and|&)\s+[A-Z][A-Za-z''-]+)*,?\s*\d{4}[a-z]?\)"
)
_NARRATIVE_RE = re.compile(
    r"[A-Z][A-Za-z''-]+(?:\s+(?:et al\.?|and|&)\s+[A-Z][A-Za-z''-]+)*\s*\(\d{4}[a-z]?\)"
)


def _paper_citation_text(paper: Paper) -> str:
    if paper.marker_md_path and paper.marker_md_path.exists():
        try:
            return paper.marker_md_path.read_text(encoding="utf-8")
        except OSError:
            pass
    # Fall back to concatenating text blocks
    blocks = paper.load_blocks()
    return "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")


@dataclass
class CitationStyleResult:
    detected: str
    confidence: float
    evidence: dict


def detect_citation_style(papers: list[Paper]) -> dict:
    numeric_total = 0
    author_year_total = 0
    for paper in papers:
        text = _paper_citation_text(paper)
        numeric_total += len(_BRACKET_NUMERIC_RE.findall(text))
        author_year_total += len(_AUTHOR_YEAR_PAREN_RE.findall(text))
        author_year_total += len(_NARRATIVE_RE.findall(text))
    total = numeric_total + author_year_total
    if total == 0:
        return CitationStyleResult(
            detected="unknown", confidence=0.0,
            evidence={"bracket_numeric_matches": 0, "author_year_matches": 0},
        ).__dict__
    ratio = numeric_total / total
    if ratio >= 0.85:
        detected = "ieee-numeric"
    elif ratio <= 0.15:
        detected = "author-year"
    else:
        detected = "mixed"
    return CitationStyleResult(
        detected=detected,
        confidence=round(max(ratio, 1 - ratio), 3),
        evidence={"bracket_numeric_matches": numeric_total,
                  "author_year_matches": author_year_total},
    ).__dict__


# ---------------------------------------------------------------------------
# Contribution phrases + reference count
# ---------------------------------------------------------------------------

_CONTRIBUTION_PHRASES = [
    r"our (?:main |key |primary )?contributions? (?:are|is)",
    r"in this paper,? we (?:propose|present|introduce)",
    r"we (?:propose|present|introduce|develop|design) (?:a |an |the )?",
    r"the (?:main |key )?contributions? of this (?:paper|work|article)",
    r"this paper (?:makes|presents|proposes) (?:the following |several )?(?:main |key )?contributions?",
]
_CONTRIBUTION_RE = re.compile(
    "|".join(f"(?:{p})" for p in _CONTRIBUTION_PHRASES), re.IGNORECASE
)


def _detect_contribution_phrases(papers: list[Paper]) -> list[str]:
    found: set[str] = set()
    for paper in papers:
        text = _paper_citation_text(paper)
        for m in _CONTRIBUTION_RE.finditer(text):
            found.add(m.group(0).strip())
    return sorted(found)


def _count_references(papers: list[Paper]) -> dict:
    counts: list[int] = []
    for paper in papers:
        blocks = paper.load_blocks()
        in_refs = False
        n = 0
        for b in blocks:
            t = _is_title_block(b)
            if t and t[1] == 2:
                title_norm = normalize_section_title(t[0])
                in_refs = title_norm in {"references", "bibliography"}
                continue
            if in_refs and b.get("type") == "text":
                # Each reference typically starts with [N] or a number
                line = b.get("text", "").strip()
                if re.match(r"^\[\d+\]", line) or re.match(r"^\d+\.\s", line):
                    n += 1
        if n > 0:
            counts.append(n)
    if not counts:
        return {"median": 0, "p25": 0, "p75": 0}
    counts.sort()
    n = len(counts)
    def _pct(p: float) -> int:
        idx = max(0, min(n - 1, int(round(p * (n - 1)))))
        return counts[idx]
    return {"median": int(statistics.median(counts)),
            "p25": _pct(0.25), "p75": _pct(0.75)}


# ---------------------------------------------------------------------------
# Top-level driver
# ---------------------------------------------------------------------------

def run_profile(corpus_dir: Path, out_dir: Path) -> dict:
    """Profile the corpus and write _domain_profile.{json,md} to out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    papers = discover_papers(corpus_dir)
    skeleton = extract_section_skeleton(papers)
    figures, tables, equations = extract_asset_patterns(papers)
    citation_style = detect_citation_style(papers)
    contribution_phrases = _detect_contribution_phrases(papers)
    reference_count = _count_references(papers)

    profile = {
        "meta": {
            "corpus_path": str(corpus_dir),
            "paper_count": len(papers),
            "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "profiler_version": PROFILER_VERSION,
        },
        "section_skeleton": skeleton,
        "figure_placement_patterns": figures,
        "table_placement_patterns": tables,
        "equation_placement_patterns": equations,
        "citation_style": citation_style,
        "reference_count": reference_count,
        "contribution_phrases": contribution_phrases,
    }

    json_path = out_dir / "_domain_profile.json"
    md_path = out_dir / "_domain_profile.md"
    json_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_render_md(profile), encoding="utf-8")
    return profile


def _render_md(profile: dict) -> str:
    lines: list[str] = []
    meta = profile["meta"]
    lines.append("# 领域写作规范摘要 (Domain Profile)")
    lines.append("")
    lines.append(f"- 语料目录: `{meta['corpus_path']}`")
    lines.append(f"- 论文数量: {meta['paper_count']}")
    lines.append(f"- 生成时间: {meta['generated_at']}")
    lines.append(f"- Profiler 版本: {meta['profiler_version']}")
    lines.append("")
    lines.append("## 章节骨架 (Section Skeleton)")
    lines.append("")
    lines.append("| 规范标签 | 出现频次 | 变体示例 | 中位位置 | 中位字数占比 |")
    lines.append("|---------|---------|---------|---------|------------|")
    for s in profile["section_skeleton"][:15]:
        variants = ", ".join(s["variants_seen"][:3])
        lines.append(
            f"| {s['canonical']} | {s['frequency']} | {variants} | "
            f"{s['median_position']} | {s['median_word_share']} |"
        )
    lines.append("")
    lines.append("## 图片使用模式 (Figure Placement)")
    lines.append("")
    lines.append("| 章节 | 子类型 | 频次 |")
    lines.append("|------|--------|------|")
    for f in profile["figure_placement_patterns"][:15]:
        lines.append(f"| {f['section']} | {f['sub_type']} | {f['frequency']} |")
    lines.append("")
    lines.append("## 表格使用模式 (Table Placement)")
    lines.append("")
    lines.append("| 章节 | 子类型 | 频次 |")
    lines.append("|------|--------|------|")
    for t in profile["table_placement_patterns"][:15]:
        lines.append(f"| {t['section']} | {t['sub_type']} | {t['frequency']} |")
    lines.append("")
    lines.append("## 公式使用模式 (Equation Placement)")
    lines.append("")
    lines.append("| 章节 | 子类型 | 频次 |")
    lines.append("|------|--------|------|")
    for e in profile["equation_placement_patterns"][:15]:
        lines.append(f"| {e['section']} | {e['sub_type']} | {e['frequency']} |")
    lines.append("")
    cs = profile["citation_style"]
    lines.append("## 引文风格 (Citation Style)")
    lines.append("")
    lines.append(f"- 检测结果: **{cs['detected']}** (置信度 {cs['confidence']})")
    lines.append(f"- 数字方括号引用 [N] 次数: {cs['evidence']['bracket_numeric_matches']}")
    lines.append(f"- 作者-年份引用次数: {cs['evidence']['author_year_matches']}")
    lines.append("")
    rc = profile["reference_count"]
    lines.append("## 参考文献数量分布")
    lines.append("")
    lines.append(f"- 中位数: {rc['median']} 篇")
    lines.append(f"- 25 分位: {rc['p25']} 篇")
    lines.append(f"- 75 分位: {rc['p75']} 篇")
    lines.append("")
    cp = profile["contribution_phrases"]
    if cp:
        lines.append("## 贡献声明句式 (Contribution Phrases)")
        lines.append("")
        for p in cp[:10]:
            lines.append(f"- `{p}`")
        lines.append("")
    lines.append("---")
    lines.append("由 `profile_papers.py` 自动生成。请审阅后确认是否准确反映该领域的写作规范。")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Profile a paper-analysis/ corpus for the thesis-writing journal mode.",
    )
    parser.add_argument("--corpus", required=True, help="paper-analysis/ directory")
    parser.add_argument("--out", "--output", dest="out", required=True, help="output directory for _domain_profile.{json,md}")
    parser.add_argument("--min-papers", type=int, default=3,
                        help="warn if fewer papers are found (default: 3)")
    args = parser.parse_args()

    corpus = Path(args.corpus).resolve()
    if not corpus.is_dir():
        raise SystemExit(f"corpus directory not found: {corpus}")
    out = Path(args.out).resolve()

    profile = run_profile(corpus, out)
    if profile["meta"]["paper_count"] < args.min_papers:
        print(f"[profile_papers] WARN: only {profile['meta']['paper_count']} papers found; "
              f"results may not be statistically representative", file=sys.stderr)
    print(f"[profile_papers] wrote {out / '_domain_profile.json'}")
    print(f"[profile_papers] wrote {out / '_domain_profile.md'}")
    print(f"[profile_papers] papers profiled: {profile['meta']['paper_count']}")
    print(f"[profile_papers] sections detected: {len(profile['section_skeleton'])}")
    print(f"[profile_papers] citation style: {profile['citation_style']['detected']}")


if __name__ == "__main__":
    main()
