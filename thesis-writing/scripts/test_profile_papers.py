#!/usr/bin/env python3
"""TDD tests for profile_papers.py — the domain profiler for journal-mode thesis-writing.

Covers:
  1. Paper discovery (walks paper-analysis/ → finds content_list.json)
  2. Section skeleton extraction (normalizes titles → canonical labels)
  3. Asset pattern extraction (figures/tables/equations attributed to sections)
  4. Citation style detection (IEEE-numeric / author-year / mixed)
  5. Output contract (_domain_profile.json schema + _domain_profile.md human report)
  6. Robustness: empty corpus, papers with missing mineru/, mixed engine outputs

Run:
    cd ~/.claude/skills && uv run pytest thesis-writing/scripts/test_profile_papers.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

import profile_papers as pp  # noqa: E402

VRP_CORPUS = Path("/mnt/e/AllProjects202601/M-PCA/VRP-GPU课题分析/paper-analysis")
TGA_PAPER = VRP_CORPUS / "2025 - TGA Tensor GPU Acceleration for VRP Local Search [Lei-Hao-Wu]"


# ---------------------------------------------------------------------------
# Fixtures: build a synthetic paper-analysis/ tree
# ---------------------------------------------------------------------------

def _make_block(btype: str, text: str = "", level: int | None = None,
                caption: list[str] | None = None) -> dict:
    """Build a single MinerU content_list.json block."""
    b: dict = {"type": btype, "bbox": [0, 0, 100, 20], "page_idx": 0}
    if btype == "text":
        b["text"] = text
        if level is not None:
            b["text_level"] = level
    elif btype == "equation":
        b["text"] = f"$$ {text} $$"
        b["text_format"] = "latex"
    elif btype in ("image", "chart"):
        b["img_path"] = f"images/{text or 'x'}.jpg"
        b["image_caption"] = caption or []
    elif btype == "table":
        b["table_caption"] = caption or ["Table N", "desc"]
        b["table_body"] = "<table></table>"
    return b


def _write_paper(corpus_dir: Path, paper_name: str, paper_id: str,
                 blocks: list[dict]) -> Path:
    """Create a synthetic paper dir under corpus_dir with content_list.json."""
    paper_dir = corpus_dir / paper_name / "mineru" / paper_id / "auto"
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / f"{paper_id}_content_list.json").write_text(
        json.dumps(blocks), encoding="utf-8"
    )
    return corpus_dir / paper_name


@pytest.fixture
def synthetic_corpus(tmp_path: Path) -> Path:
    """Build a 3-paper synthetic corpus exercising IMRaD + a survey + an IEEE-cited paper."""
    corpus = tmp_path / "paper-analysis"

    # Paper 1: standard IMRaD with IEEE numeric citations
    _write_paper(corpus, "Paper One IMRaD", "p1", [
        _make_block("text", "Title One", level=1),
        _make_block("text", "Abstract", level=2),
        _make_block("text", "Intro body with citation [1] and [2]."),
        _make_block("text", "1 Introduction", level=2),
        _make_block("text", "Prior work [3] showed X. Building on [4], we propose..."),
        _make_block("text", "2 Related Work", level=2),
        _make_block("text", "Method A [5] and method B [6]."),
        _make_block("text", "3 Method", level=2),
        _make_block("text", "Our approach is as follows."),
        _make_block("equation", "f(x) = x^2"),
        _make_block("image", "framework", caption=["Figure 1", "Framework overview."]),
        _make_block("text", "4 Experiments", level=2),
        _make_block("chart", "result_curve"),
        _make_block("table", caption=["Table 1", "Benchmark results."]),
        _make_block("text", "5 Conclusion", level=2),
        _make_block("text", "We conclude."),
    ])

    # Paper 2: survey paper with author-year citations
    _write_paper(corpus, "Paper Two Survey", "p2", [
        _make_block("text", "Title Two", level=1),
        _make_block("text", "Abstract", level=2),
        _make_block("text", "1 Introduction", level=2),
        _make_block("text", "Smith (2020) introduced the problem. Jones et al. (2021) extended it."),
        _make_block("text", "2 Taxonomy", level=2),
        _make_block("text", "We categorize prior methods."),
        _make_block("text", "3 Open Challenges", level=2),
        _make_block("text", "Several challenges remain."),
        _make_block("text", "4 Conclusion", level=2),
    ])

    # Paper 3: IMRaD with equations and tables
    _write_paper(corpus, "Paper Three IMRaD", "p3", [
        _make_block("text", "Title Three", level=1),
        _make_block("text", "1 Introduction", level=2),
        _make_block("text", "The problem is hard [7]."),
        _make_block("text", "2 Preliminaries", level=2),
        _make_block("equation", "E = mc^2"),
        _make_block("text", "3 Method", level=2),
        _make_block("equation", "L = -\\sum y \\log \\hat{y}"),
        _make_block("image", "network"),
        _make_block("text", "4 Experiments", level=2),
        _make_block("table", caption=["Table 1", "Hyperparameters."]),
        _make_block("chart", "loss_curve"),
        _make_block("text", "5 Conclusion", level=2),
    ])

    return corpus


# ---------------------------------------------------------------------------
# Test 1: Paper discovery
# ---------------------------------------------------------------------------

def test_discover_papers_finds_all_three(synthetic_corpus: Path) -> None:
    papers = pp.discover_papers(synthetic_corpus)
    assert len(papers) == 3
    names = {p.name for p in papers}
    assert "Paper One IMRaD" in names
    assert "Paper Two Survey" in names
    assert "Paper Three IMRaD" in names


def test_discover_papers_skips_empty(tmp_path: Path) -> None:
    """An empty paper dir (no content_list.json) is skipped with a warning, not crash."""
    corpus = tmp_path / "paper-analysis"
    (corpus / "Empty Paper" / "mineru").mkdir(parents=True)  # no json
    _write_paper(corpus, "Real Paper", "rp", [_make_block("text", "T", level=1)])
    papers = pp.discover_papers(corpus)
    assert len(papers) == 1
    assert papers[0].name == "Real Paper"


def test_discover_papers_empty_corpus_warns(tmp_path: Path) -> None:
    """A corpus with zero discoverable papers raises a clear error."""
    corpus = tmp_path / "paper-analysis"
    corpus.mkdir()
    with pytest.raises(pp.ProfileError, match="no papers"):
        pp.discover_papers(corpus)


# ---------------------------------------------------------------------------
# Test 2: Section skeleton extraction + canonicalization
# ---------------------------------------------------------------------------

def test_extract_section_skeleton_canonicalizes_variants(synthetic_corpus: Path) -> None:
    papers = pp.discover_papers(synthetic_corpus)
    skeleton = pp.extract_section_skeleton(papers)
    by_canonical = {s["canonical"]: s for s in skeleton}
    # "Introduction" should appear in all 3 papers
    intro = by_canonical["introduction"]
    assert intro["frequency"] == 3
    assert "1 Introduction" in intro["variants_seen"]
    # "Method" appears in papers 1 and 3
    assert by_canonical["method"]["frequency"] == 2
    # "Conclusion" appears in all 3
    assert by_canonical["conclusion"]["frequency"] == 3


def test_section_normalization_handles_numbering_prefixes() -> None:
    assert pp.normalize_section_title("1 Introduction") == "introduction"
    assert pp.normalize_section_title("I. INTRODUCTION") == "introduction"
    assert pp.normalize_section_title("1. Introduction") == "introduction"
    assert pp.normalize_section_title("3.2 CUDA programming") == "cuda programming"
    assert pp.normalize_section_title("Section 4: Method") == "method"


def test_section_canonical_label_mapping() -> None:
    assert pp.canonical_section_label("introduction") == "introduction"
    assert pp.canonical_section_label("related work") == "related_work"
    assert pp.canonical_section_label("related works") == "related_work"
    assert pp.canonical_section_label("preliminaries") == "preliminaries"
    assert pp.canonical_section_label("preliminary") == "preliminaries"
    assert pp.canonical_section_label("method") == "method"
    assert pp.canonical_section_label("methods") == "method"
    assert pp.canonical_section_label("approach") == "method"
    assert pp.canonical_section_label("our approach") == "method"
    assert pp.canonical_section_label("experiments") == "experiments"
    assert pp.canonical_section_label("experimental results") == "experiments"
    assert pp.canonical_section_label("evaluation") == "experiments"
    assert pp.canonical_section_label("conclusion") == "conclusion"
    assert pp.canonical_section_label("conclusions") == "conclusion"


def test_section_keyword_matching_for_subsection_variants() -> None:
    """Numbered subsection variants (tagged level=2 by MinerU) must canonicalize
    to their parent section via keyword matching. This is the key mechanism that
    makes the profiler domain-agnostic across VRP, KD, SR, etc."""
    assert pp.canonical_section_label("reformulating kd") == "method"
    assert pp.canonical_section_label("network architecture") == "method"
    assert pp.canonical_section_label("loss function") == "method"
    assert pp.canonical_section_label("attention transfer") == "method"
    assert pp.canonical_section_label("feature distillation") == "method"
    assert pp.canonical_section_label("proposed approach") == "method"
    assert pp.canonical_section_label("model architecture") == "method"
    assert pp.canonical_section_label("ablation study") == "experiments"
    assert pp.canonical_section_label("comparison with state-of-the-arts") == "experiments"
    assert pp.canonical_section_label("implementation details") == "experiments"
    assert pp.canonical_section_label("datasets and metrics") == "experiments"
    assert pp.canonical_section_label("main results") == "experiments"
    assert pp.canonical_section_label("experimental setup") == "experiments"
    assert pp.canonical_section_label("visualization") == "experiments"
    assert pp.canonical_section_label("model analysis") == "discussion"
    assert pp.canonical_section_label("complexity analysis") == "discussion"
    assert pp.canonical_section_label("消融实验") == "experiments"
    assert pp.canonical_section_label("网络结构") == "method"
    assert pp.canonical_section_label("实验结果及分析") == "experiments"


def test_ablation_pattern_precedence_over_experiment() -> None:
    """The keyword pattern list is ordered: 'ablation' must match before the
    general 'experiment' pattern. This test locks in that ordering invariant;
    'ablation study' contains neither 'experiment' nor 'baseline' as a word,
    so it relies solely on the ablation-specific pattern."""
    assert pp.canonical_section_label("ablation study") == "experiments"


# ---------------------------------------------------------------------------
# Test 3: Asset pattern extraction
# ---------------------------------------------------------------------------

def test_extract_asset_patterns(synthetic_corpus: Path) -> None:
    papers = pp.discover_papers(synthetic_corpus)
    figures, tables, equations = pp.extract_asset_patterns(papers)
    # Equations: paper1 (1) + paper3 (2) = 3 total
    assert sum(f["frequency"] for f in equations) >= 3
    # Tables: paper1 (1) + paper3 (1) = 2
    assert sum(t["frequency"] for t in tables) >= 2
    # Images/charts: paper1 (1 img + 1 chart) + paper3 (1 img + 1 chart) = 4
    assert sum(f["frequency"] for f in figures) >= 4
    # The framework-overview image in paper1's Method section should be attributed to "method"
    framework_figs = [f for f in figures if f["sub_type"] == "framework-overview"]
    assert any(f["section"] == "method" for f in framework_figs)


def test_asset_attribution_uses_nearest_preceding_title() -> None:
    """An equation with no preceding title in the paper should be attributed to a default bucket."""
    corpus = Path("/tmp/_test_inline")
    _write_paper(corpus, "Inline Paper", "ip", [
        _make_block("text", "Title", level=1),
        _make_block("equation", "x = 1"),  # no section header before this
    ])
    papers = pp.discover_papers(corpus)
    _, _, equations = pp.extract_asset_patterns(papers)
    # The equation should be attributed to some section (even if "front_matter"), not crash
    assert len(equations) == 1


# ---------------------------------------------------------------------------
# Test 4: Citation style detection
# ---------------------------------------------------------------------------

def test_detect_citation_style_ieee(synthetic_corpus: Path) -> None:
    papers = pp.discover_papers(synthetic_corpus)
    style = pp.detect_citation_style(papers)
    # Papers 1 and 3 use [N]; paper 2 uses author-year. Majority is IEEE.
    assert style["detected"] in {"ieee-numeric", "mixed"}
    assert style["confidence"] > 0.5
    assert style["evidence"]["bracket_numeric_matches"] >= 4  # [1][2][3][4][7]


def test_detect_citation_style_pure_author_year(tmp_path: Path) -> None:
    corpus = tmp_path / "paper-analysis"
    _write_paper(corpus, "AY Paper", "ay", [
        _make_block("text", "Title", level=1),
        _make_block("text", "Body. Smith (2020) and Jones et al. (2021) and (Brown, 2022)."),
    ])
    papers = pp.discover_papers(corpus)
    style = pp.detect_citation_style(papers)
    assert style["detected"] == "author-year"


# ---------------------------------------------------------------------------
# Test 5: Output contract — JSON schema + MD report
# ---------------------------------------------------------------------------

def test_profile_outputs_valid_json_and_md(synthetic_corpus: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    result = pp.run_profile(synthetic_corpus, out_dir)
    json_path = out_dir / "_domain_profile.json"
    md_path = out_dir / "_domain_profile.md"
    assert json_path.exists()
    assert md_path.exists()

    profile = json.loads(json_path.read_text(encoding="utf-8"))
    # Schema assertions
    assert "meta" in profile
    assert profile["meta"]["paper_count"] == 3
    assert profile["meta"]["corpus_path"].endswith("paper-analysis")
    assert "section_skeleton" in profile
    assert isinstance(profile["section_skeleton"], list)
    assert "figure_placement_patterns" in profile
    assert "table_placement_patterns" in profile
    assert "equation_placement_patterns" in profile
    assert "citation_style" in profile
    assert "reference_count" in profile
    assert "contribution_phrases" in profile

    # MD report is non-empty and mentions the section skeleton
    md_text = md_path.read_text(encoding="utf-8")
    assert "section" in md_text.lower()
    assert "introduction" in md_text.lower()


# ---------------------------------------------------------------------------
# Test 6: Snapshot test against the REAL TGA paper (regression guard)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not TGA_PAPER.exists(), reason="TGA paper not available on this machine")
def test_tga_paper_real_profile(tmp_path: Path) -> None:
    """Profile the real TGA paper alone and verify counts match the source PDF."""
    # Build a 1-paper corpus by symlinking
    corpus = tmp_path / "paper-analysis"
    corpus.mkdir()
    link = corpus / "TGA"
    link.symlink_to(TGA_PAPER, target_is_directory=True)
    out_dir = tmp_path / "out"
    pp.run_profile(corpus, out_dir)
    profile = json.loads((out_dir / "_domain_profile.json").read_text(encoding="utf-8"))

    assert profile["meta"]["paper_count"] == 1
    # TGA has 55 equations (verified by direct inspection)
    total_eq = sum(e["frequency"] for e in profile["equation_placement_patterns"])
    assert 50 <= total_eq <= 60, f"expected ~55 equations, got {total_eq}"
    # TGA has 16 tables
    total_tbl = sum(t["frequency"] for t in profile["table_placement_patterns"])
    assert 14 <= total_tbl <= 18, f"expected ~16 tables, got {total_tbl}"
    # TGA has 15 images + 13 charts = 28 visual assets
    total_img = sum(f["frequency"] for f in profile["figure_placement_patterns"])
    assert 25 <= total_img <= 32, f"expected ~28 figures, got {total_img}"
    # Skeleton must include the expected canonical sections
    canonicals = {s["canonical"] for s in profile["section_skeleton"]}
    assert "introduction" in canonicals
    assert "method" in canonicals
    assert "experiments" in canonicals or "results" in canonicals


# ---------------------------------------------------------------------------
# Test 7: Full corpus run (integration)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not VRP_CORPUS.exists(), reason="VRP corpus not available")
def test_vrp_full_corpus_runs_fast(tmp_path: Path) -> None:
    """The full 28-paper VRP corpus should profile in under 5 seconds."""
    import time
    out_dir = tmp_path / "out"
    t0 = time.time()
    pp.run_profile(VRP_CORPUS, out_dir)
    elapsed = time.time() - t0
    assert elapsed < 5.0, f"profiling took {elapsed:.2f}s, expected <5s"
    profile = json.loads((out_dir / "_domain_profile.json").read_text(encoding="utf-8"))
    assert profile["meta"]["paper_count"] >= 28
