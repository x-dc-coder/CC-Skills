#!/usr/bin/env python3
"""Tests for the stage 1.5 text-layer probe (issue #12).

The comparison core is pure on purpose, so every rule can be pinned without a
real PDF: only `probe_pdf` touches I/O.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import textlayer_probe as tp  # noqa: E402


def test_no_text_layer_is_not_applicable_never_zero():
    """A scanned PDF must be 'not measured', not 'measured as ok/zero'."""
    record = tp.compare_text_layers("", "canonical")
    assert record["verdict"] == "not_applicable"
    assert record["warnings"] == ["NO_TEXT_LAYER"]
    assert record["digit_loss_rate"] is None


def test_missing_canonical_is_pdf_only_not_ok():
    """Without a comparison we have checked nothing; 'ok' would be a false pass."""
    pdf = "A perfectly normal English paragraph with 42 numbers inside. " * 8
    record = tp.compare_text_layers(pdf, None)
    assert record["verdict"] == "pdf_only"
    assert record["canonical_compared"] is False
    assert record["warnings"] == ["CANONICAL_NOT_PROVIDED"]
    assert record["digit_loss_rate"] is None


def test_healthy_pair_is_ok():
    pdf = "We propose a method for vehicle routing. The cost is 12.7 km. " * 10
    record = tp.compare_text_layers(pdf, pdf)
    assert record["verdict"] == "ok"
    assert record["warnings"] == []
    assert record["digit_loss_rate"] == 0.0
    assert record["unspaced_runs_introduced"] == 0
    assert record["canonical_compared"] is True


def test_fullwidth_digit_loss_is_detected():
    """The CNKI failure mode: digits exist in the PDF layer, vanish downstream."""
    pdf = "总里程 １２.７３ 公里，车辆 ５０ 辆。" * 20
    canonical = "总里程  公里，车辆  辆。" * 20
    record = tp.compare_text_layers(pdf, canonical)
    assert record["verdict"] == "warn"
    assert "DIGIT_LOSS_HIGH" in record["warnings"]
    assert record["digit_loss_rate"] == 1.0
    # the full-width digits are what got lost, and they are counted as digits
    assert record["pdf"]["fullwidth_digits"] > 0


def test_unspaced_runs_are_attributed_to_the_conversion():
    """The decisive signal is the *delta* between the two sides, not the count."""
    # PDF side: real words with real spaces (no 15+ letter run).
    clean = "vehicle routing problem " * 30
    # Canonical side: the conversion glued the words together, 8 separate runs.
    collapsed = "本文研究。" + "研究。".join(["vehicleroutingproblem"] * 8)
    record = tp.compare_text_layers(clean, collapsed)
    assert "UNSPACED_ENGLISH_RUNS" in record["warnings"]
    assert record["verdict"] == "warn"
    assert record["unspaced_runs_introduced"] > tp.UNSPACED_RUNS_WARN
    # the PDF side alone stays silent: a clean text layer is not a defect
    assert record["pdf"]["long_unspaced_runs"] == 0


def test_a_single_long_run_is_tolerated():
    """One legitimate long compound is not a broken conversion."""
    pdf = " ".join(["word"] * 100)
    canonical = pdf + " " + "a" * 30  # one 30-letter run
    record = tp.compare_text_layers(pdf, canonical)
    assert "UNSPACED_ENGLISH_RUNS" not in record["warnings"]


def test_negative_loss_is_clamped():
    """A converter may add digits (page numbers); a negative rate would be a bug."""
    pdf = "Short text with 1 digit. " * 20
    canonical = pdf + "1" * 50
    record = tp.compare_text_layers(pdf, canonical)
    assert record["digit_loss_rate"] == 0.0
    assert record["canonical_compared"] is True


def test_render_json_is_deterministic_and_sorted():
    record = {"b": 1, "a": {"d": 2, "c": 3}}
    first = tp.render_json(record)
    second = tp.render_json(record)
    assert first == second
    assert list(json.loads(first).keys()) == ["a", "b"]
    assert first.endswith("\n")


def test_probe_pdf_reports_unreadable_file_without_raising(tmp_path: Path):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf at all")
    record = tp.probe_pdf(broken, "canonical")
    assert record["verdict"] == "not_applicable"
    assert "TEXT_LAYER_UNREADABLE" in record["warnings"]
    assert record["pdf_sha256"] and record["pdf_name"] == "broken.pdf"


@pytest.mark.skipif(tp.pdfplumber_version() is None, reason="pdfplumber not installed")
def test_probe_pdf_on_real_pdf_if_available():
    """Integration check against a real corpus PDF when one is mounted."""
    candidates = sorted(Path("/mnt/e/AllProjects202601/M-PCA/_paper-metrics-run"
                             "/运筹与管理/corpus_ycgl_pdf").glob("*.pdf"))
    if not candidates:
        pytest.skip("no corpus PDF mounted")
    record = tp.probe_pdf(candidates[0])
    assert record["pages"] and record["pages"] > 0
    assert record["pdf"]["chars"] > tp.MIN_TEXT_LAYER_CHARS
    assert record["verdict"] in {"ok", "warn", "pdf_only"}
