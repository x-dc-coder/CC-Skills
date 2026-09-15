#!/usr/bin/env python3
"""Tests for the Chinese clause layer (issue #22).

The layer adds three primitives - split_sentences_zh, split_clauses_zh,
tokenize_zh - and four metrics: M-CLS-31 (clauses per sentence), M-CLS-32 (clause
length), M-SLEN-34/35 (sentence-length P90/P95).  Two properties matter more than
any individual number:

- the rules must be right, which is why data/clause_spec_cases.json freezes cases
  that were hand-verified (a bracketed comma not splitting, an ellipsis run not
  fragmenting, an unclosed bracket degrading instead of swallowing the document);
- the spans must be honest - every clause slices back out of the original text, so
  a reviewer can re-open any evidence line and see the same characters.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import text_metrics as tm  # noqa: E402

_HERE = Path(__file__).resolve().parent
_SPEC = json.loads((_HERE.parent / "data" / "clause_spec_cases.json")
                  .read_text(encoding="utf-8"))
_BUNDLE: dict = {}

_TWO_SENTENCE_TEXT = (
    "本文提出一种新方法，并在三个数据集上验证了其有效性。"
    "该方法的准确率达到 95%，显著优于基线方法。"
)


# ---------------------------------------------------------------------------
# Frozen spec
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", _SPEC["cases"], ids=[c["id"] for c in _SPEC["cases"]])
def test_spec_sentences_and_clauses_match(case: dict) -> None:
    sentences = tm.split_sentences_zh(case["text"])
    clauses = tm.split_clauses_zh(case["text"])
    assert len(sentences) == case["expected"]["n_sentences"]
    assert len(clauses) == case["expected"]["n_clauses"]
    assert [c.text for c in clauses] == case["expected"]["clauses"]


@pytest.mark.parametrize("case", _SPEC["cases"], ids=[c["id"] for c in _SPEC["cases"]])
def test_spec_clause_spans_slice_back_to_the_original(case: dict) -> None:
    text = case["text"]
    for clause in tm.split_clauses_zh(text):
        assert text[clause.start:clause.end] == clause.text


@pytest.mark.parametrize("case", _SPEC["cases"], ids=[c["id"] for c in _SPEC["cases"]])
def test_spec_clause_indices_are_within_their_sentence(case: dict) -> None:
    sentences = tm.split_sentences_zh(case["text"])
    for clause in tm.split_clauses_zh(case["text"]):
        sentence = sentences[clause.sentence_index]
        assert sentence.start <= clause.start <= clause.end <= sentence.end


def test_spec_token_counts_are_frozen() -> None:
    """jieba is part of the toolchain: a segmentation change must be visible."""
    with_tokens = [c for c in _SPEC["cases"] if "n_tokens" in c["expected"]]
    assert with_tokens, "the spec must pin at least one token count"
    for case in with_tokens:
        assert len(tm.tokenize_zh(case["text"])) == case["expected"]["n_tokens"]


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_clause_layer_is_deterministic_across_runs() -> None:
    first = [c.text for c in tm.split_clauses_zh(_TWO_SENTENCE_TEXT)]
    second = [c.text for c in tm.split_clauses_zh(_TWO_SENTENCE_TEXT)]
    assert first == second
    first_tokens = [t.text for t in tm.tokenize_zh(_TWO_SENTENCE_TEXT)]
    second_tokens = [t.text for t in tm.tokenize_zh(_TWO_SENTENCE_TEXT)]
    assert first_tokens == second_tokens


def test_clause_spans_never_overlap_within_a_sentence() -> None:
    clauses = tm.split_clauses_zh(_TWO_SENTENCE_TEXT)
    for index in range(len(clauses) - 1):
        if clauses[index].sentence_index == clauses[index + 1].sentence_index:
            assert clauses[index].end <= clauses[index + 1].start


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def test_clause_metrics_are_measured_for_chinese() -> None:
    metrics = tm.compute_text_metrics(_TWO_SENTENCE_TEXT, _BUNDLE)
    clauses = tm.split_clauses_zh(_TWO_SENTENCE_TEXT)
    sentences = tm.split_sentences_zh(_TWO_SENTENCE_TEXT)
    assert len(clauses) == 4 and len(sentences) == 2

    cls31 = metrics["M-CLS-31"]
    assert cls31["value"] == pytest.approx(2.0)  # 4 clauses over 2 sentences
    assert cls31["n"] == 4 and cls31["denominator"] == 2
    assert cls31["unit"] == tm._UNIT_CLAUSES_PER_SENTENCE
    assert cls31["warnings"] == []

    cls32 = metrics["M-CLS-32"]
    # n follows _rate's convention: the numerator (total cjk-units), so the
    # corpus layer can recompute a corpus-wide mean as sum(n)/sum(denominator).
    total_units = sum(tm._zh_cjk_unit_count(c.text) for c in clauses)
    assert cls32["n"] == total_units
    assert cls32["denominator"] == 4
    assert cls32["unit"] == tm._UNIT_CJK_UNITS_PER_CLAUSE
    assert cls32["value"] == pytest.approx(total_units / 4, abs=1e-6)


def test_sentence_length_percentiles_are_measured_for_chinese() -> None:
    metrics = tm.compute_text_metrics(_TWO_SENTENCE_TEXT, _BUNDLE)
    counts = sorted(tm._zh_cjk_unit_count(s.text)
                    for s in tm.split_sentences_zh(_TWO_SENTENCE_TEXT))
    assert metrics["M-SLEN-34"]["value"] == pytest.approx(
        tm._percentile(counts, 0.90))
    assert metrics["M-SLEN-35"]["value"] == pytest.approx(
        tm._percentile(counts, 0.95))
    assert metrics["M-SLEN-34"]["quantile"] == 0.90
    assert metrics["M-SLEN-35"]["quantile"] == 0.95
    assert metrics["M-SLEN-34"]["quantile_method"] == "linear_interpolation"


def test_clause_metrics_are_null_with_reason_for_english() -> None:
    metrics = tm.compute_text_metrics(
        "We propose a method, and validate it on three datasets.", _BUNDLE)
    for metric_id in ("M-CLS-31", "M-CLS-32", "M-SLEN-34", "M-SLEN-35"):
        record = metrics[metric_id]
        assert record["value"] is None, metric_id
        assert record["warnings"] == ["CAPABILITY_NOT_SUPPORTED"], metric_id


def test_clause_metrics_on_empty_text_degrade_to_none() -> None:
    metrics = tm.compute_text_metrics("", _BUNDLE)
    for metric_id in ("M-CLS-31", "M-CLS-32", "M-SLEN-34", "M-SLEN-35"):
        record = metrics[metric_id]
        assert record["value"] is None, metric_id
        assert record["denominator"] == 0, metric_id
        assert record["warnings"], metric_id


def test_clause_metrics_are_registered_in_metric_ids() -> None:
    """The layer must stay wired into the frozen contract, not bolted on."""
    for metric_id in ("M-CLS-31", "M-CLS-32", "M-SLEN-34", "M-SLEN-35"):
        assert metric_id in tm.METRIC_IDS
        assert "zh" in tm._METRIC_LANGUAGE_CAPABILITY[metric_id]
