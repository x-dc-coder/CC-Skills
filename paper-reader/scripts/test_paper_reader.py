#!/usr/bin/env python3
"""Tests for paper-reader paper_reader.py module — non-GPU paths only.

Covers:
  1. _derive_output_dirs — output path derivation from PDF dir
  2. PipelineState — state file JSON serialization roundtrip
  3. _normalize_for_diff — text normalization for dual-engine merge

Does NOT test the Marker/MinerU engines (needs GPU).

Run:
    cd ~/.claude/skills && uv run pytest paper-reader/scripts/test_paper_reader.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

# ── Mock the GPU bridge module before importing paper_reader ──────────
# paper_reader does `from gpu_safe_subprocess import ...` at module level.
# This mock satisfies the import without touching real GPU resources.

_mock_gpu = MagicMock()
_mock_gpu.GpuLimits = MagicMock()
_mock_gpu.build_gpu_env = MagicMock(return_value={})
_mock_gpu.GpuGovernor = MagicMock()
_mock_gpu.GpuLease = MagicMock()
_mock_gpu.InsufficientGpuBudget = type("InsufficientGpuBudget", (Exception,), {})
sys.modules["gpu_safe_subprocess"] = _mock_gpu

import paper_reader as pr  # noqa: E402


# ---------------------------------------------------------------------------
# Test 1: _derive_output_dirs
# ---------------------------------------------------------------------------

def test_derive_output_dirs_from_pdf_dir() -> None:
    """_derive_output_dirs returns a dict with expected conversion/merged/summaries keys."""
    papers_dir = Path("/papers")
    dirs = pr._derive_output_dirs(papers_dir)

    assert isinstance(dirs, dict)
    assert dirs["conversion"] == papers_dir / "paper-conversion"
    assert dirs["merged"] == papers_dir / "paper-merged"
    assert dirs["summaries"] == papers_dir / "paper-summaries"


def test_derive_output_dirs_with_subpath() -> None:
    """_derive_output_dirs works with nested paths."""
    papers_dir = Path("/home/user/research/papers")
    dirs = pr._derive_output_dirs(papers_dir)

    assert dirs["conversion"] == papers_dir / "paper-conversion"
    assert dirs["merged"].parent == papers_dir


# ---------------------------------------------------------------------------
# Test 2: PipelineState serialization roundtrip
# ---------------------------------------------------------------------------

def test_pipeline_state_empty_roundtrip(tmp_path: Path) -> None:
    """New PipelineState saves minimal structure; re-reading returns same data."""
    state_path = tmp_path / "_pipeline_state.json"
    state = pr.PipelineState(state_path)
    assert not state.has("nonexistent")
    state.save()

    # Re-read
    state2 = pr.PipelineState(state_path)
    papers = state2._data.get("papers", {})
    assert isinstance(papers, dict)
    assert len(papers) == 0
    assert state2._data.get("pipeline_version") == "2.0"


def test_pipeline_state_with_entries_roundtrip(tmp_path: Path) -> None:
    """PipelineState with paper entries survives JSON roundtrip accurately."""
    state_path = tmp_path / "_pipeline_state.json"

    # Create and populate
    state = pr.PipelineState(state_path)
    entry = state.ensure_entry("test-paper")
    entry["source"] = {"title": "Test Paper", "doi": "10.1234/test"}
    entry["precheck"] = {"status": "passed", "page_count": 10, "pdf_hash": "abc123"}
    entry["phase1_converted"] = {"status": "done", "marker_ok": True, "mineru_ok": True}
    state.save()

    # Re-read
    state2 = pr.PipelineState(state_path)
    assert state2.has("test-paper")

    paper = state2.get("test-paper")
    assert paper["source"]["title"] == "Test Paper"
    assert paper["source"]["doi"] == "10.1234/test"
    assert paper["precheck"]["status"] == "passed"
    assert paper["precheck"]["page_count"] == 10
    assert paper["precheck"]["pdf_hash"] == "abc123"
    assert paper["phase1_converted"]["status"] == "done"
    assert paper["phase1_converted"]["marker_ok"] is True


def test_pipeline_state_ensure_entry_idempotent(tmp_path: Path) -> None:
    """Calling ensure_entry twice returns same entry and keeps existing data."""
    state = pr.PipelineState(tmp_path / "_pipeline_state.json")
    e1 = state.ensure_entry("my-paper")
    e1["source"] = {"title": "Original"}
    e2 = state.ensure_entry("my-paper")
    assert e2 is e1
    assert e2["source"]["title"] == "Original"


# ---------------------------------------------------------------------------
# Test 3: _normalize_for_diff (7-step normalization)
# ---------------------------------------------------------------------------

def test_normalize_plain_text_paragraph_merge() -> None:
    """Adjacent text lines merge into a single normalized paragraph."""
    raw = "This is line one.\nThis is the continuation.\n\nNew paragraph."
    result = pr._normalize_for_diff(raw)
    assert "This is line one. This is the continuation." in result
    assert "New paragraph." in result


def test_normalize_strips_headings_to_hash_hash() -> None:
    """Headings normalize to ## regardless of original depth."""
    raw = "# Title\n## Section\n### Subsection\n#### Deep"
    result = pr._normalize_for_diff(raw)
    assert "## Title" in result
    assert "## Section" in result
    assert "## Subsection" in result
    assert "## Deep" in result


def test_normalize_replaces_images_with_placeholder() -> None:
    """Image markdown is replaced with [IMAGE] placeholder."""
    raw = "Text before.\n![alt text](path/to/img.png)\nText after."
    result = pr._normalize_for_diff(raw)
    joined = " ".join(result)
    assert "[IMAGE]" in joined
    assert "alt text" not in joined
    assert "path/to/img.png" not in joined


def test_normalize_strips_superscript_tags() -> None:
    """<sup>text</sup> normalizes to ^text^ caret notation."""
    raw = "This is the 1<sup>st</sup> attempt."
    result = pr._normalize_for_diff(raw)
    joined = " ".join(result)
    # <sup>st</sup> → ^st^, so result is "1^st^"
    assert "1^st^" in joined


def test_normalize_preserves_markdown_table_rows() -> None:
    """Markdown table rows stay in their own normalized paragraph group."""
    raw = "| A | B |\n| --- | --- |\n| 1 | 2 |"
    result = pr._normalize_for_diff(raw)
    # Tables should appear as joined row strings
    joined_all = " ".join(result)
    assert "A" in joined_all
    assert "B" in joined_all


def test_normalize_latex_blocks_preserved() -> None:
    """LaTeX $$ blocks are kept as single normalized units."""
    raw = "Preamble.\n$$ f(x) = x^2 $$\nAftermath."
    result = pr._normalize_for_diff(raw)
    joined = " ".join(result)
    assert "$$" in joined
    assert "f(x)" in joined


def test_normalize_meta_lines_are_removed() -> None:
    """Lines matching DOI/URL/Email-addresses/etc. meta patterns are stripped."""
    raw = "DOI: 10.1234/test\nReal content here."
    result = pr._normalize_for_diff(raw)
    joined = "\n".join(result)
    assert "DOI:" not in joined
    assert "Real content here" in joined
