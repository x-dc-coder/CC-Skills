#!/usr/bin/env python3
"""Domain profiler for the paper-metrics skill (input to thesis-writing Mode B).

Reads a paper-analysis/ corpus (MinerU content_list.json files, produced by the
paper-reader skill) and emits a machine-readable domain profile that drives
section-skeleton selection, figure/table/equation placement, and citation-style
decisions in the writing-plan phase.

Usage:
    cd ~/.claude/skills && uv run python paper-metrics/scripts/profile_papers.py \
        --corpus /path/to/paper-analysis/ --out /path/to/output/

Outputs:
    <out>/_domain_profile.json      — machine-readable (consumed by the skill)
    <out>/_domain_profile.md        — human-readable, rendered deterministically from the JSON
    <out>/_per_paper_metrics.jsonl  — one line per profiled paper (audit trail)
    <out>/_corpus_summary.json      — corpus aggregation, recomputable from the jsonl
    <out>/_run_meta.json            — volatile run metadata (NOT part of the fingerprint)

Design:
    - Pure stdlib. No LLM calls, no third-party deps (OBSERVED-layer red line).
    - Deterministic: dicts emitted with sort_keys=True, floats rounded to 6
      decimals, every directory walk sorted, no timestamps inside the
      fingerprinted JSON. Two runs over the same corpus + path produce
      byte-identical _domain_profile.json / _per_paper_metrics.jsonl /
      _corpus_summary.json.
    - Reproducibility boundary: the bit-level guarantee covers
      "Canonical Document -> OBSERVED metrics". The PDF -> Canonical step is done
      by paper-reader and its drift is NOT measured here: paper-reader does not
      record engine versions, so this profiler can only raise
      ENGINE_VERSION_NOT_RECORDED and record input hashes. Do not read this
      module as providing an engine-drift report.
    - Verifiability: every metric carries value/n/denominator/unit/evidence, and
      every paper carries sha256 input hashes, so a third party can recompute a
      number from the exact artifact it came from.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import importlib
import json
import math
import platform
import re
import statistics
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# Algorithm version — bump when metric *semantics* change.
PROFILER_VERSION = "2.0"
# Output contract version — bump when the JSON *schema* changes.
SCHEMA_VERSION = "2.0"
# Version of the written metric definitions (references/metric-definitions.md).
METRIC_SPEC_VERSION = "1.0"

class ProfileError(Exception):
    """Raised when the corpus cannot be profiled (empty, malformed, unreadable)."""


# A text block becomes a "paragraph" for M-PCNT-25 only if it has at least this
# many words; shorter blocks are usually captions, fragments or reference lines.
_PARAGRAPH_MIN_WORDS = 15
# Sections that get a stratified (by_section) aggregation in _corpus_summary.json.
# Kept to the three sections the metric contract requires (introduction / method /
# experiments): every extra stratum costs a full metric pass over that section,
# and cross-section pooling is meaningless anyway.
_STRATIFIED_SECTIONS = ("introduction", "method", "experiments")
# ---------------------------------------------------------------------------
# Paper discovery
# ---------------------------------------------------------------------------

# Sections whose text is NOT prose and therefore must stay out of the style
# metrics (a bibliography is not body text; a keyword list is not a sentence).
_NON_PROSE_SECTIONS = frozenset(
    {"references", "appendix", "acknowledgments", "keywords", "front_matter"}
)


def sha256_file(path: Path) -> str:
    """sha256 of the raw bytes of a file (hex). Used for input provenance."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class Paper:
    name: str
    content_list_path: Path
    marker_md_path: Path | None = None
    blocks: list[dict] = field(default_factory=list)
    # Stable identifier used as the JSON key / jsonl ordering key.
    paper_key: str = ""
    # [{"artifact": "mineru_content_list", "sha256": "..."}] — provenance so a
    # third party can prove which exact bytes produced a number.
    inputs: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Derived-text caches. The profiler touches each paper's text several times
    # (metrics, token count, per-section strata); recomputing the join and the
    # section walk every time dominated the runtime for a 34-paper corpus.
    _labelled_cache: list | None = field(default=None, repr=False, compare=False)
    _text_cache: str | None = field(default=None, repr=False, compare=False)
    _sections_cache: dict | None = field(default=None, repr=False, compare=False)
    # Upstream (paper-reader) provenance: which engines produced this canonical
    # document, and whether their versions were recorded at all.
    upstream: dict = field(default_factory=dict)

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

    # -- section attribution -------------------------------------------------

    def labelled_blocks(self) -> list[tuple[str, dict]]:
        """(canonical_section_label, block) for every block, in document order.

        A block's label is the nearest preceding level-2 heading; blocks before
        the first heading get "front_matter".
        """
        if self._labelled_cache is not None:
            return self._labelled_cache
        out: list[tuple[str, dict]] = []
        current = "front_matter"
        for b in self.load_blocks():
            t = _is_title_block(b)
            if t and t[1] == 2:
                current = canonical_section_label(normalize_section_title(t[0]))
            elif b.get("type") == "header":
                # MinerU sometimes emits the section title as a running head
                # (type="header") instead of a heading with text_level. Only the
                # bibliography labels are honoured here, so page headers cannot
                # silently re-label body sections.
                header_label = canonical_section_label(
                    normalize_section_title(str(b.get("text") or "")))
                if header_label in ("references", "bibliography"):
                    current = "references"
            out.append((current, b))
        self._labelled_cache = out
        return out

    def canonical_text(self, include_non_prose: bool = False) -> str:
        """Body text of the canonical document.

        Concatenates non-heading text blocks in document order, dropping
        non-prose sections (references / appendix / keywords / ...) unless asked.
        Deterministic: depends only on the content_list.json bytes.
        """
        if not include_non_prose and self._text_cache is not None:
            return self._text_cache
        parts: list[str] = []
        for section, b in self.labelled_blocks():
            if _is_title_block(b):
                continue
            if b.get("type") != "text":
                continue
            text = (b.get("text") or "").strip()
            if not text:
                continue
            if not include_non_prose and section in _NON_PROSE_SECTIONS:
                continue
            parts.append(text)
        # NFC normalisation happens here, once, at the ingestion point: the same
        # logical text in NFC vs NFD would otherwise tokenise differently and
        # silently shift every length/ratio metric. Spans recorded in evidence
        # slice this normalised string, so they stay consistent.
        joined = unicodedata.normalize("NFC", "\n\n".join(parts))
        if not include_non_prose:
            self._text_cache = joined
        return joined

    def section_texts(self) -> dict[str, str]:
        """canonical_section_label -> concatenated body text of that section."""
        if self._sections_cache is not None:
            return self._sections_cache
        buckets: dict[str, list[str]] = defaultdict(list)
        for section, b in self.labelled_blocks():
            if _is_title_block(b) or b.get("type") != "text":
                continue
            text = (b.get("text") or "").strip()
            if text:
                buckets[section].append(text)
        self._sections_cache = {
            k: unicodedata.normalize("NFC", "\n\n".join(v)) for k, v in buckets.items()
        }
        return self._sections_cache

    def sections_present(self) -> list[str]:
        seen = [s for s, _ in self.labelled_blocks() if s != "front_matter"]
        return sorted(set(seen))


@dataclass
class Discovery:
    """Result of walking a corpus: papers + an explicit skip ledger."""

    papers: list[Paper]
    skipped: list[dict]
    empty_dirs: list[str]


_CONTENT_LIST_GLOB = "**/*_content_list.json"


def _pick_first_sorted(paths: list[Path]) -> Path | None:
    """Deterministically choose one path.

    rglob() order depends on the filesystem, which would make the selected
    content_list.json machine-dependent. Sort by (relative POSIX path) instead.
    """
    if not paths:
        return None
    return sorted(paths, key=lambda p: p.as_posix())[0]


def discover_papers_detailed(corpus_dir: Path) -> Discovery:
    """Walk corpus_dir and return papers plus an explicit skip ledger.

    Unlike v1, the choice of content_list.json / marker markdown is order
    independent (sorted), and every skipped paper is recorded with a reason so
    the omission is visible inside the artifact instead of only on stderr.
    """
    papers: list[Paper] = []
    skipped: list[dict] = []
    empty_dirs: list[str] = []
    if not corpus_dir.is_dir():
        raise ProfileError(f"corpus directory not found: {corpus_dir}")
    for paper_dir in sorted((p for p in corpus_dir.iterdir() if p.is_dir()),
                            key=lambda p: p.name):
        mineru_dir = paper_dir / "mineru"
        if not mineru_dir.is_dir():
            skipped.append({"paper_key": paper_dir.name, "reason": "no_mineru_dir"})
            continue
        v2_files = [f for f in mineru_dir.rglob("*_content_list.json")
                    if "_v2" not in f.name]
        cl_path = _pick_first_sorted(v2_files)
        if cl_path is None:
            empty_dirs.append(paper_dir.name)
            skipped.append({"paper_key": paper_dir.name, "reason": "no_content_list_json"})
            continue
        marker_md = None
        marker_dir = paper_dir / "marker"
        if marker_dir.is_dir():
            marker_md = _pick_first_sorted(list(marker_dir.rglob("*.md")))
        inputs = [{"artifact": "mineru_content_list", "sha256": sha256_file(cl_path)}]
        if marker_md is not None:
            inputs.append({"artifact": "marker_markdown", "sha256": sha256_file(marker_md)})
        upstream: dict = {}
        meta_path = paper_dir / "_META.json"
        if meta_path.is_file():
            inputs.append({"artifact": "paper_reader_meta", "sha256": sha256_file(meta_path)})
            try:
                meta_obj = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                meta_obj = None
            if isinstance(meta_obj, dict):
                raw_versions = meta_obj.get("engine_versions")
                versions: dict = {}
                if isinstance(raw_versions, dict):
                    # Contract (paper-reader): keys marker/mineru/torch/cuda/python;
                    # missing or undetectable engines are null, never omitted.
                    versions = {str(k): (str(v) if v not in (None, "") else None)
                                for k, v in raw_versions.items()}
                upstream = {
                    "engines": meta_obj.get("engines"),
                    "marker_ok": bool((meta_obj.get("marker") or {}).get("ok")),
                    "mineru_ok": bool((meta_obj.get("mineru") or {}).get("ok")),
                    "pdf_sha256_recorded": bool(meta_obj.get("pdf_sha256")),
                    "engine_versions": versions,
                    "engine_versions_source": meta_obj.get("engine_versions_source"),
                    # True only when at least one real version was recorded; a
                    # dict of all-nulls must NOT count as "recorded".
                    "versions_recorded": any(v for v in versions.values()),
                }
        papers.append(Paper(
            name=paper_dir.name,
            content_list_path=cl_path,
            marker_md_path=marker_md,
            paper_key=paper_dir.name,
            inputs=inputs,
            upstream=upstream,
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
    papers.sort(key=lambda p: p.paper_key)
    return Discovery(papers=papers, skipped=skipped, empty_dirs=empty_dirs)


def discover_papers(corpus_dir: Path) -> list[Paper]:
    """Backward-compatible wrapper returning just the paper list."""
    return discover_papers_detailed(corpus_dir).papers


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
    """Word count of a block.

    v2 also counts list / code / table blocks: ignoring them made
    median_word_share systematically low (tables and reference lists carry real
    content). Equation blocks count as 1 word so a formula-heavy section is not
    reported as empty.
    """
    btype = b.get("type")
    if btype == "text":
        return len(b.get("text", "").split())
    if btype == "equation":
        return 1
    if btype == "list":
        items = b.get("list_items") or b.get("items")
        if isinstance(items, list) and items:
            return len(" ".join(str(i) for i in items).split())
        return len(str(b.get("text", "")).split())
    if btype == "code":
        return len(str(b.get("code_body") or b.get("text") or "").split())
    if btype == "table":
        return len(re.sub(r"<[^>]+>", " ", str(b.get("table_body") or "")).split())
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
    # NOTE: the legacy field name "confidence" is kept for backward
    # compatibility but it is NOT a statistical confidence — it is the
    # dominance ratio of the winning style, max(ratio, 1-ratio). The honest
    # name is "separation", emitted alongside by _citation_meta().
    confidence: float
    evidence: dict


def _citation_meta(total: int) -> dict:
    return {
        "separation": None,
        "metric_spec": "M-CITSTYLE-50",
        "method": "rule",
        "unit": "ratio",
        "n": total,
        "state": "OBSERVED",
        "thresholds": {"ieee_numeric_min": 0.85, "author_year_max": 0.15},
        "note": ("legacy 'confidence' is a dominance ratio, not a calibrated "
                 "probability; do not compare it with model confidence scores."),
    }


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
        payload = CitationStyleResult(
            detected="unknown", confidence=0.0,
            evidence={"bracket_numeric_matches": 0, "author_year_matches": 0},
        ).__dict__
        payload.update(_citation_meta(0))
        payload["separation"] = 0.0
        return payload
    ratio = numeric_total / total
    separation = round(max(ratio, 1 - ratio), 3)
    if ratio >= 0.85:
        detected = "ieee-numeric"
    elif ratio <= 0.15:
        detected = "author-year"
    else:
        detected = "mixed"
    payload = CitationStyleResult(
        detected=detected,
        confidence=round(max(ratio, 1 - ratio), 3),
        evidence={"bracket_numeric_matches": numeric_total,
                  "author_year_matches": author_year_total},
    ).__dict__
    payload.update(_citation_meta(total))
    payload["separation"] = separation
    return payload


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


# A reference list entry, as MinerU renders it. v1 only accepted
# type == "text" blocks starting with "[N]" / "N. ", while real MinerU emits
# reference lists as type == "list" -> reference_count was silently 0.
_REF_BRACKET_RE = re.compile(r"^\s*\[\d+\]")
_REF_NUMBERED_RE = re.compile(r"^\s*\d{1,3}[.)]\s")
_REF_AUTHOR_YEAR_RE = re.compile(r"^\s*[A-Z][A-Za-z'\-]+,\s*[A-Z]")
_REF_AUTHOR_YEAR_ALT_RE = re.compile(
    r"^\s*[A-Z][A-Za-z'\-]+(?:\s+(?:et al\.?|and|&)\s+[A-Z][A-Za-z'\-]+)*"
    r",?\s*\(\d{4}[a-z]?\)"
)
_REF_BRACKETED_AUTHOR_YEAR_RE = re.compile(
    r"^\s*\[[A-Z][^\]]{0,80}?(?:19|20)\d{2}[a-z]?\]"
)
_REF_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}[a-z]?\b")


def _looks_like_reference(text: str) -> bool:
    if len(text.split()) < 5:
        return False
    if _REF_BRACKET_RE.match(text) or _REF_NUMBERED_RE.match(text):
        return True
    if _REF_BRACKETED_AUTHOR_YEAR_RE.match(text):
        return True
    if _REF_AUTHOR_YEAR_RE.match(text) or _REF_AUTHOR_YEAR_ALT_RE.match(text):
        return True
    # Fallback heuristic: capitalised entry containing a publication year.
    return text[:1].isupper() and bool(_REF_YEAR_RE.search(text))


def _split_reference_entries(chunks: list[str]) -> list[str]:
    """Split reference-section blocks/lists into individual entries.

    Handles the three shapes seen in the wild: one entry per block, one entry
    per list item, and several "[N] ... [N] ..." entries packed into one block.
    """
    entries: list[str] = []
    for chunk in chunks:
        for part in re.split(r"\n+", chunk):
            part = part.strip()
            if not part:
                continue
            starts = [m.start() for m in re.finditer(r"\[\d+\]", part)]
            if len(starts) > 1 and starts[0] <= 2:
                for i, s in enumerate(starts):
                    end = starts[i + 1] if i + 1 < len(starts) else len(part)
                    seg = part[s:end].strip()
                    if seg:
                        entries.append(seg)
            else:
                entries.append(part)
    return [e for e in entries if _looks_like_reference(e)]


def _reference_chunks(paper: Paper) -> list[str]:
    """Raw reference-section text/list chunks of one paper (headings excluded)."""
    chunks: list[str] = []
    for section, b in paper.labelled_blocks():
        if _is_title_block(b):
            continue
        # Two independent signals, either is sufficient:
        #   (a) the block sits in a bibliography section, or
        #   (b) MinerU itself classified the block as reference text.
        if section != "references" and b.get("sub_type") != "ref_text":
            continue
        btype = b.get("type")
        if btype == "text":
            t = (b.get("text") or "").strip()
            if t:
                chunks.append(t)
        elif btype == "list":
            items = b.get("list_items") or b.get("items")
            if isinstance(items, list) and items:
                chunks.extend(str(i).strip() for i in items if str(i).strip())
            else:
                t = (b.get("text") or "").strip()
                if t:
                    chunks.append(t)
    return chunks


def count_references_for_paper(paper: Paper) -> tuple[int, list[str]]:
    entries = _split_reference_entries(_reference_chunks(paper))
    return len(entries), entries


def _count_references(papers: list[Paper]) -> dict:
    per_paper: dict[str, int] = {}
    sample: list[dict] = []
    for paper in papers:
        n, entries = count_references_for_paper(paper)
        per_paper[paper.paper_key] = n
        for e in entries[:1]:
            if len(sample) < 3:
                sample.append({"paper_key": paper.paper_key, "excerpt": e[:80]})
    counts = sorted(c for c in per_paper.values() if c > 0)
    base = {
        "metric_spec": "M-REFCNT-51",
        "method": "rule",
        "unit": "reference entries",
        "n_papers_with_references": len(counts),
        "per_paper": dict(sorted(per_paper.items())),
        "evidence": {"sample": sample},
    }
    if not counts:
        base.update({"median": 0, "p25": 0, "p75": 0})
        return base
    n = len(counts)

    def _pct(p: float) -> int:
        idx = max(0, min(n - 1, int(round(p * (n - 1)))))
        return counts[idx]

    # Use the SAME nearest-rank convention as the corpus summary (the local
    # _pct() above is already nearest-rank); int(statistics.median(...)) would
    # be a different convention that only coincides on odd/even edge cases.
    base.update({"median": int(_percentile([float(c) for c in counts], 0.5)),
                 "p25": _pct(0.25), "p75": _pct(0.75), "quantile_method":
                 "nearest_rank_no_interpolation"})
    return base


# ---------------------------------------------------------------------------
# Top-level driver
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Deterministic serialisation helpers
# ---------------------------------------------------------------------------

def _round_floats(obj, ndigits: int = 6):
    """Recursively round floats and replace NaN/Inf with None.

    NaN is not valid JSON, and float noise must not leak into the fingerprint.
    """
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return round(obj, ndigits)
    if isinstance(obj, dict):
        return {k: _round_floats(v, ndigits) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_round_floats(v, ndigits) for v in obj]
    return obj


def canonical_json_text(obj) -> str:
    """Byte-stable JSON: sorted keys, fixed indent, rounded floats, LF ending."""
    return json.dumps(_round_floats(obj), ensure_ascii=False, indent=2,
                      sort_keys=True) + "\n"


# ---------------------------------------------------------------------------
# Optional metric-layer imports (lexicon_loader / text_metrics)
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = Path(__file__).resolve().parent


def _import_sibling(module_name: str):
    """Import a sibling module from this directory (uv run / pytest safe)."""
    if str(_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_DIR))
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise ProfileError(
            f"required sibling module '{module_name}' is missing: {exc}. "
            f"Expected at {_SCRIPTS_DIR / (module_name + '.py')}"
        ) from exc


def _load_lexicons():
    loader = _import_sibling("lexicon_loader")
    return loader, loader.load_lexicons()


def _toolchain(bundle) -> dict:
    """Versions that a third party needs in order to reproduce a number."""
    return {
        "python": platform.python_version(),
        "implementation": "stdlib-only",
        "third_party_dependencies": [],
        "profiler_version": PROFILER_VERSION,
        "schema_version": SCHEMA_VERSION,
        "metric_spec_version": METRIC_SPEC_VERSION,
        # Text is normalised to NFC before any counting (see Paper.canonical_text).
        "unicode_norm": "NFC",
        "lexicon_version": bundle.version,
        "lexicon_fingerprint": bundle.fingerprint(),
    }


# ---------------------------------------------------------------------------
# Paragraph metrics (M-PCNT-25) — structure-based, not prose-based
# ---------------------------------------------------------------------------

def _distribution(values: list[int]) -> dict:
    if not values:
        return {"median": 0, "p25": 0, "p75": 0, "std": 0.0}
    s = sorted(values)
    n = len(s)

    def pct(p: float) -> float:
        idx = max(0, min(n - 1, int(round(p * (n - 1)))))
        return float(s[idx])

    return {
        "median": pct(0.5),
        "p25": pct(0.25),
        "p75": pct(0.75),
        "std": statistics.pstdev(s) if n > 1 else 0.0,
    }


def compute_paragraph_metric(paper: Paper) -> dict:
    """M-PCNT-25: paragraph count + word-length distribution.

    Definition: a paragraph is a text block with >= _PARAGRAPH_MIN_WORDS words,
    outside non-prose sections (references/appendix/keywords) and not a heading.
    Denominator: number of such paragraphs.
    """
    rows: list[tuple[int, str, int, str]] = []
    for idx, (section, b) in enumerate(paper.labelled_blocks()):
        if section in _NON_PROSE_SECTIONS or _is_title_block(b):
            continue
        if b.get("type") != "text":
            continue
        text = (b.get("text") or "").strip()
        words = len(text.split())
        if words >= _PARAGRAPH_MIN_WORDS:
            rows.append((idx, section, words, text[:80]))
    words_list = [r[2] for r in rows]
    n = len(rows)
    longest = sorted(rows, key=lambda r: (-r[2], r[0]))[:3]
    return {
        "value": (sum(words_list) / n) if n else None,
        "n": n,
        "denominator": n,
        "unit": "words/paragraph",
        "state": "OBSERVED",
        "method": "rule",
        "metric_spec": "M-PCNT-25",
        "distribution": _distribution(words_list),
        "evidence": {
            "count": n,
            "sample": [{"block_index": r[0], "section": r[1], "words": r[2],
                        "excerpt": r[3]} for r in longest],
        },
        "warnings": [] if n else ["no_paragraphs_above_min_words"],
    }


# ---------------------------------------------------------------------------
# Per-paper metric computation
# ---------------------------------------------------------------------------

def compute_paper_metrics(paper: Paper, bundle, text_metrics_mod) -> dict:
    metrics = dict(text_metrics_mod.compute_text_metrics(paper.canonical_text(), bundle))
    metrics["M-PCNT-25"] = compute_paragraph_metric(paper)
    return metrics


def compute_section_metrics(paper: Paper, bundle, text_metrics_mod,
                            metrics_of_interest: tuple[str, ...]) -> dict:
    """Stratified values for the sections in _STRATIFIED_SECTIONS.

    Cross-section mixing is meaningless (Introduction and Method differ in
    sentence length and passive voice), so the corpus summary keeps them apart.
    """
    out: dict[str, dict] = {}
    for section, text in sorted(paper.section_texts().items()):
        if section not in _STRATIFIED_SECTIONS:
            continue
        computed = text_metrics_mod.compute_text_metrics(text, bundle)
        out[section] = {mid: (computed[mid].get("value") if mid in computed else None)
                        for mid in metrics_of_interest}
    return out


# ---------------------------------------------------------------------------
# Corpus aggregation
# ---------------------------------------------------------------------------

_T_CRITICAL_975 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
    8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145,
    15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060, 26: 2.056,
    27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
}


def _percentile(sorted_vals: list[float], p: float) -> float:
    """Nearest-rank quantile, NO interpolation.

    Defined as sorted_vals[round(p * (n-1))]. Consequence worth knowing: for an
    even-sized sample the value reported as "median" is the LOWER of the two
    middle observations, not their average -- i.e. it deliberately differs from
    statistics.median()/numpy's default linear interpolation. The summary carries
    quantile_method="nearest_rank_no_interpolation" so a consumer never has to
    guess which convention produced the number.
    """
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    idx = max(0, min(n - 1, int(round(p * (n - 1)))))
    return float(sorted_vals[idx])


def _rank(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    return _pearson(_rank(xs), _rank(ys))


def _aggregate_metric(per_paper_values: dict[str, float], unit: str,
                      section_values: dict[str, list[float]]) -> dict:
    """Corpus-level summary of one metric over per-paper values."""
    valid = {k: v for k, v in per_paper_values.items() if v is not None}
    missing = sorted(k for k, v in per_paper_values.items() if v is None)
    n_valid = len(valid)
    warnings: list[str] = []
    if n_valid == 0:
        return {
            "unit": unit, "n_valid": 0, "n_missing": len(missing),
            "missing_papers": missing, "mean": None, "sd": None, "median": None,
            "p25": None, "p75": None, "iqr": None, "min": None, "max": None,
            "ci95_low": None, "ci95_high": None, "by_section": {},
            "warnings": ["NO_VALID_VALUES", "N_LT_5", "N_VALID_LT_3"],
        }
    vals = sorted(float(v) for v in valid.values())
    n = n_valid
    mean = sum(vals) / n
    sd = statistics.stdev(vals) if n > 1 else 0.0
    p25, p75 = _percentile(vals, 0.25), _percentile(vals, 0.75)
    iqr = p75 - p25
    if n < 5:
        warnings.append("N_LT_5")
    if n < 3:
        warnings.append("N_VALID_LT_3")
    if iqr == 0:
        warnings.append("IQR_ZERO")
    if len(missing) / max(1, len(per_paper_values)) > 0.3:
        warnings.append("HIGH_MISSING")
    tcrit = _T_CRITICAL_975.get(n - 1, 1.96)
    half = tcrit * sd / math.sqrt(n) if n > 1 else 0.0
    by_section: dict[str, dict] = {}
    for section, svals in sorted(section_values.items()):
        sv = sorted(float(v) for v in svals if v is not None)
        by_section[section] = {
            "n_valid": len(sv),
            "mean": (sum(sv) / len(sv)) if sv else None,
            "median": _percentile(sv, 0.5) if sv else None,
        }
    return {
        "unit": unit, "n_valid": n, "n_missing": len(missing),
        "missing_papers": missing, "mean": mean, "sd": sd,
        "median": _percentile(vals, 0.5), "p25": p25, "p75": p75, "iqr": iqr,
        "min": vals[0], "max": vals[-1],
        "ci95_low": mean - half, "ci95_high": mean + half,
        "by_section": by_section, "warnings": warnings,
    }


def aggregate_corpus(records: list[dict], corpus_id: str | None = None) -> dict:
    """Aggregate per-paper records into _corpus_summary.json.

    Analysis unit = paper (sentences are observation units, not independent
    samples: pooling sentences across papers is pseudoreplication).
    Weighting = equal_paper. Missing values stay missing (never filled with 0).
    """
    n_papers = len(records)
    metric_ids: set[str] = set()
    for r in records:
        metric_ids.update(r["metrics"].keys())
    metrics: dict[str, dict] = {}
    corpus_warnings: list[dict] = []
    length_by_paper = {r["paper_key"]: r.get("n_tokens", 0) for r in records}
    for mid in sorted(metric_ids):
        per_paper: dict[str, float] = {}
        unit = ""
        section_values: dict[str, list[float]] = defaultdict(list)
        for r in records:
            m = r["metrics"].get(mid)
            if m is None:
                per_paper[r["paper_key"]] = None
                continue
            per_paper[r["paper_key"]] = m.get("value")
            unit = unit or m.get("unit", "")
            for section, smap in (r.get("section_metrics") or {}).items():
                if smap.get(mid) is not None:
                    section_values[section].append(float(smap[mid]))
        summary = _aggregate_metric(per_paper, unit, section_values)
        # Length confound: a metric that tracks paper length is not a style fact.
        pairs = [(length_by_paper[k], v) for k, v in per_paper.items() if v is not None]
        if len(pairs) >= 5:
            rho = _spearman([p[0] for p in pairs], [p[1] for p in pairs])
            if rho is not None and abs(rho) > 0.3:
                summary["spearman_rho_vs_length"] = rho
                summary["warnings"].append("LENGTH_CORR")
        metrics[mid] = summary
        for code in summary["warnings"]:
            if code in {"N_LT_5", "N_VALID_LT_3", "NO_VALID_VALUES"}:
                corpus_warnings.append({"code": code, "metric": mid,
                                        "detail": f"n_valid={summary['n_valid']}"})
    # Upstream provenance: can a reader attribute a PDF -> Canonical drift?
    upstream_known = [r.get("upstream") or {} for r in records]
    upstream_known = [u for u in upstream_known if u]
    version_lists: dict[str, set] = defaultdict(set)
    for u in upstream_known:
        for engine, ver in (u.get("engine_versions") or {}).items():
            if ver:
                version_lists[engine].add(str(ver))
    upstream_summary = {
        "papers_with_paper_reader_meta": len(upstream_known),
        "engines": sorted({str(u.get("engines")) for u in upstream_known if u.get("engines")}),
        "marker_ok": sum(1 for u in upstream_known if u.get("marker_ok")),
        "mineru_ok": sum(1 for u in upstream_known if u.get("mineru_ok")),
        "pdf_sha256_recorded": sum(1 for u in upstream_known if u.get("pdf_sha256_recorded")),
        # Observed engine versions, per engine. Empty => nothing recorded.
        "engine_versions": {k: sorted(v) for k, v in sorted(version_lists.items())},
        "engine_versions_sources": sorted({str(u.get("engine_versions_source"))
                                           for u in upstream_known
                                           if u.get("engine_versions_source")}),
        "engine_versions_recorded": bool(version_lists),
    }
    if upstream_known and not upstream_summary["engine_versions_recorded"]:
        corpus_warnings.append({
            "code": "ENGINE_VERSION_NOT_RECORDED", "metric": "",
            "detail": ("paper-reader's _META.json carries no engine version, so a "
                       "PDF->Canonical drift can be detected but not attributed; "
                       "reproducibility here only covers Canonical Document -> metrics"),
        })

    # Section skew: one section dominating the corpus makes pooled means unsafe.
    section_counts: Counter = Counter()
    for r in records:
        for s in r.get("sections", []):
            section_counts[s] += 1
    for section, cnt in sorted(section_counts.items()):
        if n_papers and cnt / n_papers > 0.7 and section not in {"introduction", "method"}:
            corpus_warnings.append(
                {"code": "SECTION_SKEW", "metric": "",
                 "detail": f"section '{section}' present in {cnt}/{n_papers} papers"})
    out = {
        "schema_version": SCHEMA_VERSION,
        "analysis_unit": "paper",
        "weight_mode": "equal_paper",
        # Median/p25/p75 are nearest-rank (no interpolation). For an even n the
        # reported median is therefore the lower middle observation.
        "quantile_method": "nearest_rank_no_interpolation",
        "n_papers": n_papers,
        "upstream": upstream_summary,
        "metrics": metrics,
        "corpus_warnings": sorted(corpus_warnings, key=lambda w: (w["code"], w["metric"])),
    }
    if corpus_id is not None:
        # Lets a downstream contract document name the exact corpus it was
        # derived from (traceability from clause -> corpus -> input hashes).
        out["corpus_id"] = corpus_id
    return out


def _corpus_fingerprint(records: list[dict]) -> str:
    """Content hash of every input artifact in the corpus (order independent)."""
    payload = sorted(
        (r["paper_key"], a["artifact"], a["sha256"])
        for r in records for a in r.get("inputs", [])
    )
    return hashlib.sha256(json.dumps(payload, sort_keys=True,
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


_LOCAL_CONFOUND_METRICS = tuple(
    m for m in ("M-SLEN-01", "M-PCNT-25", "M-HED-14", "M-BOO-15",
                "M-CONN-30", "M-NOM-10", "M-PAS-09")
)


def run_profile(corpus_dir: Path, out_dir: Path,
                include_section_metrics: bool = True) -> dict:
    """Profile the corpus and write the five artifacts to out_dir."""
    t0 = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)
    discovery = discover_papers_detailed(corpus_dir)
    papers = discovery.papers
    loader, bundle = _load_lexicons()
    text_metrics_mod = _import_sibling("text_metrics")

    skeleton = extract_section_skeleton(papers)
    figures, tables, equations = extract_asset_patterns(papers)
    citation_style = detect_citation_style(papers)
    contribution_phrases = _detect_contribution_phrases(papers)
    reference_count = _count_references(papers)

    records: list[dict] = []
    for paper in papers:
        metrics = compute_paper_metrics(paper, bundle, text_metrics_mod)
        section_metrics = (
            compute_section_metrics(paper, bundle, text_metrics_mod,
                                    _LOCAL_CONFOUND_METRICS)
            if include_section_metrics else {}
        )
        records.append({
            "paper_key": paper.paper_key,
            "inputs": paper.inputs,
            "sections": paper.sections_present(),
            "n_tokens": len(text_metrics_mod.tokenize(paper.canonical_text())),
            "metrics": metrics,
            "section_metrics": section_metrics,
            "upstream": paper.upstream,
            "warnings": list(paper.warnings),
        })

    corpus_id = _corpus_fingerprint(records)
    summary = aggregate_corpus(records, corpus_id)

    profile = {
        "schema_version": SCHEMA_VERSION,
        "metric_spec_version": METRIC_SPEC_VERSION,
        "toolchain": _toolchain(bundle),
        "meta": {
            "profiler_version": PROFILER_VERSION,
            "schema_version": SCHEMA_VERSION,
            "paper_count": len(papers),
            # NOTE: no corpus_path here. A machine-specific absolute path inside
            # a fingerprinted artifact would break cross-path / cross-machine
            # reproducibility. The path lives in _run_meta.json (not part of the
            # fingerprint); the corpus identity is corpus.id (content hash).
        },
        "corpus": {
            "id": corpus_id,
            "n_papers": len(papers),
            "profiled": [{"paper_key": r["paper_key"], "inputs": r["inputs"]}
                         for r in records],
            "skipped": discovery.skipped,
        },
        "lexicons": bundle.to_manifest(),
        "section_skeleton": skeleton,
        "figure_placement_patterns": figures,
        "table_placement_patterns": tables,
        "equation_placement_patterns": equations,
        "citation_style": citation_style,
        "reference_count": reference_count,
        "contribution_phrases": contribution_phrases,
        "corpus_summary": summary,
    }

    # Round once, then derive BOTH views from the same rounded payload.
    # (Rendering the markdown from the un-rounded in-memory dict used to emit
    # 17-digit floats that the JSON did not contain -> human and machine views
    # disagreed, and the markdown escaped the determinism check.)
    rounded = _round_floats(profile)
    (out_dir / "_domain_profile.json").write_text(
        canonical_json_text(rounded), encoding="utf-8")
    (out_dir / "_domain_profile.md").write_text(_render_md(rounded), encoding="utf-8")
    (out_dir / "_corpus_summary.json").write_text(
        canonical_json_text(summary), encoding="utf-8")
    with (out_dir / "_per_paper_metrics.jsonl").open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(_round_floats(r), ensure_ascii=False,
                                sort_keys=True) + "\n")
    (out_dir / "_run_meta.json").write_text(canonical_json_text({
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "corpus_path": str(corpus_dir),
        "out_dir": str(out_dir),
        "elapsed_ms": int((time.time() - t0) * 1000),
        "host": platform.node(),
        "python_version": platform.python_version(),
        "profiler_version": PROFILER_VERSION,
        "schema_version": SCHEMA_VERSION,
        "corpus_id": corpus_id,
    }), encoding="utf-8")
    return rounded


_TICK = chr(96)


def _render_md(profile: dict) -> str:
    """Render the human-readable report deterministically from the JSON.

    Both views come from one source of truth, so the human report and the
    machine profile can never disagree (explainability requirement E6).
    """
    lines: list[str] = []
    meta = profile["meta"]
    lines.append("# 领域写作规范摘要 (Domain Profile)")
    lines.append("")
    lines.append(f"- 论文数量: {meta['paper_count']}")
    lines.append(f"- Profiler 版本: {meta['profiler_version']}")
    lines.append(f"- schema 版本: {meta['schema_version']}")
    lines.append(f"- 指标规范版本: {profile.get('metric_spec_version', '')}")
    lines.append(f"- 语料指纹 corpus id: {_TICK}{profile['corpus']['id']}{_TICK}")
    lines.append(f"- 词表指纹: {_TICK}{profile['toolchain']['lexicon_fingerprint']}{_TICK}")
    lines.append(f"- 依赖: {profile['toolchain']['implementation']}（无第三方依赖，无 LLM 调用）")
    skipped = profile["corpus"].get("skipped") or []
    if skipped:
        lines.append(f"- 跳过论文: {len(skipped)} 篇（原因见 _domain_profile.json 的 corpus.skipped）")
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
            lines.append(f"- {_TICK}{p}{_TICK}")
        lines.append("")
    summary = profile.get("corpus_summary") or {}
    metrics = summary.get("metrics") or {}
    if metrics:
        lines.append("## 写作特征指标 (Style Metrics, OBSERVED)")
        lines.append("")
        lines.append("| 指标 | 单位 | n | 中位数 | IQR | 95% CI | 告警 |")
        lines.append("|------|------|---|--------|-----|--------|------|")
        for mid, m in metrics.items():
            ci = ""
            if m.get("ci95_low") is not None and m.get("ci95_high") is not None:
                ci = f"[{m['ci95_low']}, {m['ci95_high']}]"
            warn = ", ".join(m.get("warnings") or [])
            med = m.get("median")
            iqr = m.get("iqr")
            lines.append(
                f"| {mid} | {m.get('unit') or ''} | {m.get('n_valid')} | "
                f"{'' if med is None else med} | {'' if iqr is None else iqr} | {ci} | {warn} |")
        lines.append("")
        lines.append("注：分析单位为**论文**（n 为有效论文数），不是句子；缺失值保持空缺、从不填 0。"
                     "n_valid < 5 的指标只作参考，不得据此得出期刊级结论。")
        lines.append("")
    warns = summary.get("corpus_warnings") or []
    if warns:
        lines.append("## 语料告警 (Corpus Warnings)")
        lines.append("")
        for w in warns:
            lines.append(f"- {_TICK}{w['code']}{_TICK} {w.get('metric') or ''} — {w.get('detail') or ''}")
        lines.append("")
    lines.append("---")
    lines.append("由 profile_papers.py 确定性生成（同一输入两次运行逐字节相同）。")
    lines.append("指标定义、公式与不可推断边界见 references/metric-definitions.md。")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Determinism self-check
# ---------------------------------------------------------------------------

# Files covered by the bit-level reproducibility guarantee. _run_meta.json is
# deliberately excluded: it carries wall-clock time and host identity.
FINGERPRINTED_FILES = ("_domain_profile.json", "_domain_profile.md",
                       "_per_paper_metrics.jsonl", "_corpus_summary.json")


def verify_determinism(corpus_dir: Path, out_dir: Path,
                       include_section_metrics: bool = True) -> dict:
    """Re-run the profiler into a temp dir and byte-compare the fingerprints."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix="pp_verify_") as tmp:
        tmp_out = Path(tmp)
        run_profile(corpus_dir, tmp_out, include_section_metrics=include_section_metrics)
        result: dict = {"ok": True, "checked": list(FINGERPRINTED_FILES), "diffs": []}
        for name in FINGERPRINTED_FILES:
            a, b = out_dir / name, tmp_out / name
            if not a.exists() or not b.exists():
                result["ok"] = False
                which = "out_dir" if not a.exists() else "temp"
                result["diffs"].append(f"{name}: missing in {which}")
                continue
            if a.read_bytes() != b.read_bytes():
                result["ok"] = False
                result["diffs"].append(f"{name}: bytes differ")
        return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Profile a paper-analysis/ corpus for the paper-metrics journal mode.",
    )
    parser.add_argument("--corpus", required=True, help="paper-analysis/ directory")
    parser.add_argument("--out", "--output", dest="out", required=True,
                        help="output directory for _domain_profile.{json,md} + metric artifacts")
    parser.add_argument("--min-papers", type=int, default=3,
                        help="warn if fewer papers are found (default: 3)")
    parser.add_argument("--no-section-metrics", action="store_true",
                        help="skip stratified per-section metrics (faster)")
    parser.add_argument("--verify", action="store_true",
                        help="re-run into a temp dir and assert fingerprints are byte-identical")
    args = parser.parse_args()

    corpus = Path(args.corpus).resolve()
    if not corpus.is_dir():
        raise SystemExit(f"corpus directory not found: {corpus}")
    out = Path(args.out).resolve()
    section_metrics = not args.no_section_metrics

    profile = run_profile(corpus, out, include_section_metrics=section_metrics)
    if profile["meta"]["paper_count"] < args.min_papers:
        print(f"[profile_papers] WARN: only {profile['meta']['paper_count']} papers found; "
              f"results may not be statistically representative", file=sys.stderr)
    for name in ("_domain_profile.json", "_domain_profile.md", "_corpus_summary.json",
                 "_per_paper_metrics.jsonl", "_run_meta.json"):
        print(f"[profile_papers] wrote {out / name}")
    print(f"[profile_papers] papers profiled: {profile['meta']['paper_count']}")
    skipped = profile["corpus"].get("skipped") or []
    if skipped:
        print(f"[profile_papers] papers skipped: {len(skipped)}")
    print(f"[profile_papers] sections detected: {len(profile['section_skeleton'])}")
    print(f"[profile_papers] citation style: {profile['citation_style']['detected']}")
    rcnt = profile["reference_count"]
    print(f"[profile_papers] reference_count median: {rcnt.get('median')} "
          f"(papers with refs: {rcnt.get('n_papers_with_references')})")
    print(f"[profile_papers] corpus id: {profile['corpus']['id']}")
    warns = (profile.get("corpus_summary") or {}).get("corpus_warnings") or []
    if warns:
        print(f"[profile_papers] corpus warnings: "
              f"{', '.join(sorted({w['code'] for w in warns}))}")

    if args.verify:
        res = verify_determinism(corpus, out, include_section_metrics=section_metrics)
        if res["ok"]:
            print(f"[profile_papers] VERIFY OK: {len(res['checked'])} fingerprinted files "
                  f"byte-identical across runs")
        else:
            for d in res["diffs"]:
                print(f"[profile_papers] VERIFY FAIL: {d}", file=sys.stderr)
            raise SystemExit(1)


if __name__ == "__main__":
    main()
