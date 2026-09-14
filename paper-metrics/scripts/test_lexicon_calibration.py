#!/usr/bin/env python3
"""Tests for the Chinese lexicon calibration harness (issue #13 step 1)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import lexicon_calibration as lc  # noqa: E402


def _row(item_id: str, stratum: str, a: str = "", b: str = "") -> dict:
    return {"item_id": item_id, "stratum": stratum, "matched_entries": "可能",
            "sentence": "这是一个句子。", "annotator_a": a, "annotator_b": b}


def test_systematic_sample_is_deterministic_and_spreads():
    items = list(range(100))
    first = lc.systematic_sample(items, 10)
    assert first == lc.systematic_sample(items, 10)
    assert first == [0, 10, 20, 30, 40, 50, 60, 70, 80, 90]
    # fewer items than requested -> take everything, never pad with duplicates
    assert lc.systematic_sample([1, 2, 3], 10) == [1, 2, 3]
    assert lc.systematic_sample([], 10) == []


def test_wilson_interval_matches_known_values():
    low, high = lc.wilson_interval(20, 20)
    assert low == pytest.approx(0.8389, abs=1e-3)      # 95% Wilson lower bound
    assert high == pytest.approx(1.0)
    low, high = lc.wilson_interval(0, 10)
    assert low == 0.0 and high == pytest.approx(0.2775, abs=1e-3)
    assert lc.wilson_interval(0, 0) == (None, None)


def test_cohen_kappa_known_cases():
    assert lc.cohen_kappa([("positive", "positive")] * 10) == 1.0
    # total disagreement between two labels -> negative kappa
    pairs = [("positive", "negative")] * 5 + [("negative", "positive")] * 5
    assert lc.cohen_kappa(pairs) == pytest.approx(-1.0)
    # chance-level agreement -> ~0
    chance = ([("positive", "positive")] * 5 + [("negative", "negative")] * 5
              + [("positive", "negative")] * 5 + [("negative", "positive")] * 5)
    assert abs(lc.cohen_kappa(chance)) < 0.2
    assert lc.cohen_kappa([]) is None


def test_score_computes_precision_and_false_negative_rate():
    rows = ([_row("P%03d" % i, "P", "y") for i in range(1, 4)]
            + [_row("P004", "P", "n")]                       # one bad positive
            + [_row("N001", "N", "n") for _ in range(3)]
            + [_row("N004", "N", "y")])                      # a miss the lexicon made
    report = lc.score(rows, method="human", adjudicator="tester", lexicon="hedge")
    assert report["strata"]["P"]["precision"] == pytest.approx(0.75)
    assert report["strata"]["N"]["false_negative_rate"] == pytest.approx(0.25)
    assert report["strata"]["P"]["precision_ci95"][0] < 0.75 < report["strata"]["P"]["precision_ci95"][1]
    # 8 labelled rows < 200 -> the admission checklist caveat must be raised
    assert any("<200" in caveat or "200" in caveat for caveat in report["caveats"])


def test_a_model_pass_may_not_claim_kappa():
    rows = [_row("P001", "P", "y", "y"), _row("P002", "P", "y", "y")]
    human = lc.score(rows, method="human", adjudicator="human", lexicon="hedge")
    assert human["cohen_kappa"] == 1.0
    model = lc.score(rows, method="model", adjudicator="agent", lexicon="hedge")
    assert model["cohen_kappa"] == 1.0                 # the statistic is still shown
    assert model["acceptance"]["kappa_ok"] is None      # ...but never accepted
    assert any("not a gold standard" in caveat for caveat in model["caveats"])


def test_unusable_labels_are_ignored_not_guessed():
    rows = [_row("P001", "P", "maybe"), _row("P002", "P", "")]
    report = lc.score(rows, method="human", adjudicator="t", lexicon="hedge")
    assert report["strata"]["P"]["marked_positive"] == 0
    assert report["n_double_labelled"] == 0
    assert report["cohen_kappa"] is None


def test_sheet_round_trip(tmp_path: Path):
    items = [lc.Candidate(item_id="P001", stratum="P", paper_key="p1",
                          sentence="可能的方案。", matched=["可能"])]
    path = lc.write_sheets(items, "hedge", tmp_path)
    rows = lc.read_sheets(path)
    assert rows[0]["item_id"] == "P001" and rows[0]["stratum"] == "P"
    assert rows[0]["annotator_a"] == "" and rows[0]["annotator_b"] == ""


def test_entries_for_connectors_returns_the_three_groups():
    class _L:
        def __init__(self, entries):
            self.entries = entries

    class _Bundle:
        def __init__(self):
            self.connectors = {"contrastive": _L(("然而",)), "causal": _L(("因此",)),
                               "result": _L(("结果表明",))}

    table = lc.entries_for(_Bundle(), "connectors")
    assert sorted(table) == ["causal", "contrastive", "result"]
    assert table["result"] == ("结果表明",)


def test_validate_reports_concentration_sensitivity_and_discrimination(tmp_path: Path):
    """Zero-annotation validity evidence must be structured and deterministic."""
    import textwrap
    corpus = tmp_path / "zh"
    d = corpus / "P1" / "mineru" / "p1" / "auto"
    d.mkdir(parents=True)
    import json as _json
    blocks = [
        {"type": "text", "text_level": 2, "text": "1 引言"},
        {"type": "text", "text": "本文的方法可能有效，通常假设成立。" * 3},
        {"type": "text", "text_level": 2, "text": "2 方法"},
        {"type": "text", "text": "本文构建模型并求解优化问题。" * 3},
        {"type": "text", "text_level": 2, "text": "3 实验结果"},
        {"type": "text", "text": "结果表明该方法显著有效。" * 3},
    ]
    (d / "p1_content_list.json").write_text(_json.dumps(blocks, ensure_ascii=False),
                                            encoding="utf-8")

    class _L:
        def __init__(self, entries):
            self.entries = entries

    class _Bundle:
        version = "test-zh"

        def __init__(self):
            self.hedge = _L(("可能", "通常", "一般"))
            self.connectors = {"contrastive": _L(("然而",)), "causal": _L(("因此",)),
                               "result": _L(("结果表明",))}

    report = lc.validate(corpus, {"zh": _Bundle()}, "hedge", leave_out_pct=20, subsets=3)
    assert report["n_papers"] == 1 and report["n_entries"] == 3
    assert 0.0 <= report["concentration"]["top20pct_hit_share"] <= 1.0
    assert report["concentration"]["strongest"]
    assert len(report["sensitivity"]["means"]) == 3
    assert report["sensitivity"]["relative_spread"] is not None
    assert set(report["discrimination"]["section_means"]) <= {
        "introduction", "method", "experiments"}
    # deterministic: same inputs -> same report
    again = lc.validate(corpus, {"zh": _Bundle()}, "hedge", leave_out_pct=20, subsets=3)
    assert again == report


def test_validate_sensitivity_ignores_empty_lexicon(tmp_path: Path):
    corpus = tmp_path / "zh"
    d = corpus / "P1" / "mineru" / "p1" / "auto"
    d.mkdir(parents=True)
    import json as _json
    # a level-2 heading is required: blocks before the first heading are
    # front_matter and are dropped from the canonical text
    (d / "p1_content_list.json").write_text(
        _json.dumps([{"type": "text", "text_level": 2, "text": "1 引言"},
                     {"type": "text", "text": "本文研究问题。" * 20}], ensure_ascii=False),
        encoding="utf-8")

    class _L:
        def __init__(self, entries):
            self.entries = entries

    class _Bundle:
        version = "test-zh"

        def __init__(self):
            self.hedge = _L(())
            self.connectors = {"contrastive": _L(()), "causal": _L(()), "result": _L(())}

    report = lc.validate(corpus, {"zh": _Bundle()}, "hedge", subsets=2)
    assert report["corpus_mean"] == 0.0
    assert report["concentration"]["top20pct_hit_share"] is None   # no hits, not 0/0


def test_lexicon_fingerprint_changes_with_entries():
    class _Bundle:
        hedge = type("L", (), {"entries": ("可能", "或许")})()
    first = lc.lexicon_fingerprint(_Bundle, "hedge")
    _Bundle.hedge = type("L", (), {"entries": ("可能", "或许", "大概")})()
    assert lc.lexicon_fingerprint(_Bundle, "hedge") != first
    assert len(first) == 64
