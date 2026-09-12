#!/usr/bin/env python3
"""Tests for paper-reader paper_reader.py module — non-GPU paths only.

Covers:
  1. _derive_output_dirs — output path derivation from PDF dir
  2. PipelineState — state file JSON serialization roundtrip
  3. _normalize_for_diff — text normalization for dual-engine merge
  4. engine version provenance — frozen _META.json contract, memoized probe,
     failure degrades to null + note (never raises, never blocks)
  5. _META.json provenance payload — pdf_sha256 + engine_versions, JSON parseable
  6. backfill — idempotent, never overwrites a conversion_time record

Does NOT test the Marker/MinerU engines (needs GPU).

Run:
    cd ~/.claude/skills && uv run pytest paper-reader/scripts/test_paper_reader.py -v
"""

from __future__ import annotations

import hashlib
import json
import subprocess
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

# ---------------------------------------------------------------------------
# Test 4: engine version provenance (frozen _META.json contract)
# ---------------------------------------------------------------------------

_FAKE_SNAPSHOT = {
    "engine_versions": {"marker": "9.9.9", "mineru": "8.8.8", "torch": "7.7.7",
                        "cuda": "6.6", "python": "3.10.12"},
    "engine_versions_source": "conversion_time",
    "engine_versions_note": None,
}


def test_engine_version_snapshot_contract() -> None:
    """Snapshot exposes the frozen five version keys plus a source marker."""
    pr._reset_engine_version_cache()
    snap = pr._engine_version_snapshot()
    assert set(snap) == {"engine_versions", "engine_versions_source",
                         "engine_versions_note"}
    assert list(snap["engine_versions"]) == list(pr._ENGINE_CONTRACT_KEYS)
    assert snap["engine_versions_source"] in {"conversion_time", "unavailable"}
    assert snap["engine_versions_note"] is None or isinstance(
        snap["engine_versions_note"], str)


def test_engine_version_probe_runs_once_per_process(monkeypatch) -> None:
    """The probe hits both venvs exactly once, then is memoized for the batch."""
    pr._reset_engine_version_cache()
    calls: list[str] = []

    def _fake(engine: str) -> dict:
        calls.append(engine)
        return {"python": "3.10.12", "marker": "9.9.9", "mineru": None,
                "torch": "7.7.7", "cuda": "6.6"}

    monkeypatch.setattr(pr, "_probe_one_env", _fake)
    first = pr._engine_version_snapshot()
    second = pr._engine_version_snapshot()

    assert calls == ["marker", "mineru"]
    assert first is second
    assert first["engine_versions"]["marker"] == "9.9.9"
    assert first["engine_versions"]["mineru"] is None
    assert first["engine_versions_source"] == "conversion_time"


def test_engine_version_probe_failure_never_raises(monkeypatch) -> None:
    """A probe that raises must not abort the run: nulls + note + unavailable."""
    pr._reset_engine_version_cache()

    def _boom(engine: str) -> dict:
        raise RuntimeError(f"probe exploded: {engine}")

    monkeypatch.setattr(pr, "_probe_one_env", _boom)
    snap = pr._engine_version_snapshot()  # must not raise

    assert snap["engine_versions"] == {k: None for k in pr._ENGINE_CONTRACT_KEYS}
    assert snap["engine_versions_source"] == "unavailable"
    assert snap["engine_versions_note"]
    assert "marker" in snap["engine_versions_note"]


def test_run_probe_command_swallows_missing_binary(monkeypatch) -> None:
    """A missing cmd.exe/python degrades to an error note instead of raising."""
    def _raise(*args, **kwargs):
        raise FileNotFoundError("no such file: cmd.exe")

    monkeypatch.setattr(pr.subprocess, "run", _raise)
    out, err = pr._run_probe_command(["definitely-not-a-binary"], 5.0)
    assert out == ""
    assert err and "FileNotFoundError" in err


def test_run_probe_command_keeps_output_on_timeout(monkeypatch) -> None:
    """On timeout the already-flushed fast line is still used."""
    def _timeout(*args, **kwargs):
        raise pr.subprocess.TimeoutExpired(
            cmd="probe", timeout=1.0,
            output='<<<FAST>>>{"python": "3.10.12"}\n')

    monkeypatch.setattr(pr.subprocess, "run", _timeout)
    out, err = pr._run_probe_command(["probe"], 1.0)
    assert "<<<FAST>>>" in out
    assert err and "timeout" in err


# ---------------------------------------------------------------------------
# Test 5: _META.json provenance payload
# ---------------------------------------------------------------------------

def test_precheck_record_includes_full_sha256() -> None:
    """PrecheckResult carries both the short legacy hash and the full digest."""
    rec = pr.PrecheckResult(ok=True, status="passed", pdf_hash="a" * 16,
                            pdf_sha256="c" * 64).to_record()
    assert rec["pdf_hash"] == "a" * 16
    assert rec["pdf_sha256"] == "c" * 64


def test_sha256_of_file_matches_hashlib_and_never_raises(tmp_path: Path) -> None:
    target = tmp_path / "sample.bin"
    target.write_bytes(b"hello world")
    digest, note = pr._sha256_of_file(target)
    assert digest == hashlib.sha256(b"hello world").hexdigest()
    assert note is None

    missing, err = pr._sha256_of_file(tmp_path / "nope.bin")
    assert missing is None
    assert err and "pdf_sha256 unavailable" in err


def test_build_meta_record_contract_and_json_roundtrip(tmp_path: Path) -> None:
    """_META.json carries pdf_sha256 + the five version keys and stays parseable."""
    result = pr.PaperResult(pdf_path="/p/x.pdf", stem="x")
    result.precheck = pr.PrecheckResult(ok=True, status="passed",
                                        pdf_hash="a" * 16, pdf_sha256="b" * 64)

    meta = pr.build_meta_record(
        result, engines="both", pages=None, images_copied=3,
        pdf_sha256=result.precheck.pdf_sha256, pdf_sha256_note=None,
        engine_provenance=dict(_FAKE_SNAPSHOT),
    )

    assert meta["pdf_sha256"] == "b" * 64
    assert list(meta["engine_versions"]) == list(pr._ENGINE_CONTRACT_KEYS)
    assert meta["engine_versions"]["marker"] == "9.9.9"
    assert meta["engine_versions_source"] == "conversion_time"
    assert meta["engine_versions_note"] is None
    assert meta["precheck"]["pdf_sha256"] == "b" * 64

    meta_path = tmp_path / "_META.json"
    assert pr._write_meta_json(meta_path, meta) is None
    parsed = json.loads(meta_path.read_text(encoding="utf-8"))
    assert parsed["pdf_sha256"] == "b" * 64
    assert parsed["engine_versions"]["mineru"] == "8.8.8"


def test_build_meta_record_always_emits_five_version_keys() -> None:
    """Keys are never omitted — unknown values are null, with a note."""
    result = pr.PaperResult(pdf_path="/p/x.pdf", stem="x")
    meta = pr.build_meta_record(
        result, engines="marker", pages="0-3", images_copied=0,
        pdf_sha256=None, pdf_sha256_note="no source pdf",
        engine_provenance={},
    )
    assert meta["pdf_sha256"] is None
    assert meta["pdf_sha256_note"] == "no source pdf"
    assert meta["engine_versions"] == {k: None for k in pr._ENGINE_CONTRACT_KEYS}


def test_write_meta_json_survives_unwritable_path(tmp_path: Path) -> None:
    target = tmp_path / "missing_dir" / "_META.json"
    err = pr._write_meta_json(target, {"a": 1})
    assert err and not target.exists()


# ---------------------------------------------------------------------------
# Test 6: --backfill-meta (provenance for already-converted corpora)
# ---------------------------------------------------------------------------

def _backfill_corpus(tmp_path: Path) -> tuple[Path, dict]:
    """3-paper v1 corpus: fresh / already-measured / no-source-pdf."""
    papers_dir = tmp_path
    corpus = papers_dir / "paper-analysis"

    paper_a = corpus / "PaperA"
    paper_a.mkdir(parents=True)
    (paper_a / "src.pdf").write_bytes(b"%PDF-1.4\n" + b"A" * 4096)
    (paper_a / "_META.json").write_text(
        json.dumps({"pdf_path": "src.pdf", "stem": "PaperA"}), encoding="utf-8")

    paper_b = corpus / "PaperB"
    paper_b.mkdir()
    (paper_b / "_META.json").write_text(json.dumps({
        "stem": "PaperB", "pdf_sha256": "f" * 64,
        "engine_versions_source": "conversion_time",
        "engine_versions_note": None,
        "engine_versions": dict(_FAKE_SNAPSHOT["engine_versions"]),
    }), encoding="utf-8")

    paper_c = corpus / "PaperC"
    paper_c.mkdir()
    (paper_c / "_META.json").write_text(json.dumps({"stem": "PaperC"}),
                                        encoding="utf-8")

    paths = {
        "a": paper_a / "_META.json",
        "b": paper_b / "_META.json",
        "c": paper_c / "_META.json",
    }
    return papers_dir, paths


def _digests(paths: dict) -> dict:
    return {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in paths.items()}


def test_backfill_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(pr, "_engine_version_snapshot", lambda: dict(_FAKE_SNAPSHOT))
    papers_dir, paths = _backfill_corpus(tmp_path)

    first = pr.backfill_meta(papers_dir)
    after_first = _digests(paths)
    second = pr.backfill_meta(papers_dir)
    after_second = _digests(paths)

    assert first["scanned"] == 3
    assert first["updated"] == 2          # PaperA + PaperC
    assert first["skipped_conversion_time"] == 1
    assert second["updated"] == 0         # nothing left to fill
    assert second["unchanged"] == 2
    assert after_first == after_second    # byte-identical: no rewrite


def test_backfill_never_touches_conversion_time_record(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(pr, "_engine_version_snapshot", lambda: dict(_FAKE_SNAPSHOT))
    papers_dir, paths = _backfill_corpus(tmp_path)
    before = paths["b"].read_bytes()

    pr.backfill_meta(papers_dir)
    pr.backfill_meta(papers_dir)

    assert paths["b"].read_bytes() == before
    record = json.loads(paths["b"].read_text(encoding="utf-8"))
    assert record["engine_versions_source"] == "conversion_time"
    assert record["pdf_sha256"] == "f" * 64


def test_backfill_fills_missing_hash_and_marks_estimate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(pr, "_engine_version_snapshot", lambda: dict(_FAKE_SNAPSHOT))
    papers_dir, paths = _backfill_corpus(tmp_path)

    stats = pr.backfill_meta(papers_dir)
    record = json.loads(paths["a"].read_text(encoding="utf-8"))
    expected = hashlib.sha256((paths["a"].parent / "src.pdf").read_bytes()).hexdigest()

    assert record["pdf_sha256"] == expected
    assert stats["pdf_sha256_filled"] == 1
    assert record["engine_versions"] == _FAKE_SNAPSHOT["engine_versions"]
    # Honesty: never claim conversion-time measurement for a backfilled record.
    assert record["engine_versions_source"] == "current_env_estimate"
    assert "not a conversion-time measurement" in record["engine_versions_note"]


def test_backfill_missing_pdf_writes_null(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(pr, "_engine_version_snapshot", lambda: dict(_FAKE_SNAPSHOT))
    papers_dir, paths = _backfill_corpus(tmp_path)

    stats = pr.backfill_meta(papers_dir)
    record = json.loads(paths["c"].read_text(encoding="utf-8"))

    assert "pdf_sha256" in record and record["pdf_sha256"] is None
    assert record["pdf_sha256_note"]
    assert stats["pdf_sha256_null"] == 1
    assert record["engine_versions_source"] == "current_env_estimate"


def test_backfill_without_meta_files_reports_zero(tmp_path: Path) -> None:
    stats = pr.backfill_meta(tmp_path)
    assert stats["scanned"] == 0
    assert stats["updated"] == 0


def test_pipeline_state_persists_full_sha256(tmp_path: Path) -> None:
    """State carries the full digest so a resumed run can reuse it (no re-read)."""
    state_path = tmp_path / "_pipeline_state.json"
    state = pr.PipelineState(state_path)
    result = pr.PrecheckResult(ok=True, status="passed", pdf_hash="a" * 16,
                               pdf_sha256="d" * 64)
    state.set_precheck("paper-x", result)
    state.save()

    reloaded = pr.PipelineState(state_path)
    assert reloaded.get("paper-x")["pdf_sha256"] == "d" * 64
    assert reloaded.get("paper-x")["precheck"]["pdf_sha256"] == "d" * 64


def test_process_one_writes_provenance_meta(tmp_path: Path, monkeypatch) -> None:
    """End-to-end write path (engines + precheck mocked, no GPU): _META.json is
    produced with a correct pdf_sha256 and the five version keys."""
    body = b"%PDF-1.4\n" + b"P" * 4096
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()

    monkeypatch.setattr(
        pr, "run_precheck",
        lambda p, max_pages=pr._DEFAULT_MAX_PAGES: pr.PrecheckResult(
            ok=True, status="passed", page_count=1, pdf_hash=digest[:16],
            pdf_sha256=digest))
    monkeypatch.setattr(pr, "_engine_version_snapshot", lambda: dict(_FAKE_SNAPSHOT))

    def _fake_marker(pdf_path, out_dir, pages):
        md_dir = Path(out_dir) / "marker" / Path(pdf_path).stem
        md_dir.mkdir(parents=True, exist_ok=True)
        md = md_dir / f"{Path(pdf_path).stem}.md"
        md.write_text("# Title\n\nBody text.\n", encoding="utf-8")
        return pr.EngineResult("marker", True, 0.1, md_path=str(md), img_count=0)

    monkeypatch.setattr(pr, "run_marker", _fake_marker)

    pr.process_one(pdf, tmp_path, "marker", None, "auto", "pipeline", None)

    meta_path = tmp_path / "paper-merged" / "paper" / "_META.json"
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["pdf_sha256"] == digest
    assert list(meta["engine_versions"]) == list(pr._ENGINE_CONTRACT_KEYS)
    assert meta["engine_versions"]["marker"] == "9.9.9"
    assert meta["engine_versions_source"] == "conversion_time"


def test_cli_help_exits_zero_and_documents_backfill() -> None:
    proc = subprocess.run(
        [sys.executable, str(Path(pr.__file__)), "--help"],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0
    assert "--backfill-meta" in proc.stdout

