#!/usr/bin/env python3
"""Regression test: the rejected-manuscript analysis (issue #22 field use).

Two layers, because the fixture decision was 分层:

1. Committed synthetic part (runs everywhere, no external data): the half-width
   stop boundary and the hedge/booster direction are pinned with hand-written
   Chinese snippets, so the rules this analysis depends on cannot silently rot.
2. Opt-in real-corpus part (skipped unless the corpora exist on this machine):
   re-profiles the four manuscript versions and the journal baseline and asserts
   the writing-characteristic gaps are still where they were measured.  Set
   PAPER_METRICS_REAL=1 to run; the M-PCA tree lives on /mnt/e by convention.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import text_metrics as tm  # noqa: E402
from lexicon_loader import load_lexicons  # noqa: E402

_BUNDLE = load_lexicons(language="zh")

# The manuscript versions and their import provenance (source sha256 of v1).
_MPCA_CORPUS = Path("/tmp/mpca-corpus")
_MPCA_PROFILE = Path("/tmp/mpca-v6")
_KZYJC_CORPUS = Path("/mnt/e/AllProjects202601/M-PCA/papers/kzyjc_reading/paper-conversion")
_V1_SHA256 = "55d2bc316b9c273030ff74f8b1cd3ffa0e25b68d7cd0a4bb89d7d33dd5715c11"

_REAL = os.environ.get("PAPER_METRICS_REAL") == "1"


# ---------------------------------------------------------------------------
# Committed: the rules the analysis stands on
# ---------------------------------------------------------------------------

def test_half_stop_ends_a_chinese_sentence() -> None:
    """CNKI journals terminate Chinese sentences with '.', not '。

    Without this the whole journal baseline has its sentence lengths inflated
    by roughly 20% and the 'your sentences are 32% shorter' reading is fiction.
    """
    text = "建立了多车场模型.首先采用混合编码，使问题变得更简洁."
    sentences = tm.split_sentences_zh(text)
    assert [s.text for s in sentences] == [
        "建立了多车场模型.", "首先采用混合编码，使问题变得更简洁."]


@pytest.mark.parametrize("text", [
    "准确率达到 98.73，高于基线方法.",
    "框架从 v1.2 升级到 v2.0，性能提升 12.5%.",
    "采用 U.S. 学者的 et al. 建议，改进算法.",
])
def test_half_stop_guards(text: str) -> None:
    """Decimals, version numbers and abbreviations keep their internal stops."""
    sentences = tm.split_sentences_zh(text)
    assert len(sentences) == 1, [s.text for s in sentences]


def test_hedge_and_booster_are_measured_on_chinese() -> None:
    """The hedge/booster pair is the analysis' headline finding.

    A hedge-light, booster-heavy snippet must measure as exactly that: the pair
    is only useful if each side moves independently of the other.
    """
    hedgy = "结果可能在某种程度上表明，该算法或许具有较好的稳定性，但仍有待进一步验证。"
    bossy = "本文方法显著优于所有基线，性能大幅提升，完全解决了该问题。"
    hed = tm.compute_text_metrics(hedgy, _BUNDLE)["M-HED-14"]
    boo = tm.compute_text_metrics(bossy, _BUNDLE)["M-BOO-15"]
    assert hed["value"] > 0 and boo["value"] > 0
    assert tm.compute_text_metrics(bossy, _BUNDLE)["M-HED-14"]["value"] == 0
    assert tm.compute_text_metrics(hedgy, _BUNDLE)["M-BOO-15"]["value"] == 0


# ---------------------------------------------------------------------------
# Opt-in: real corpora (skip when absent)
# ---------------------------------------------------------------------------

pytestmark_real = pytest.mark.skipif(
    not _REAL or not _MPCA_CORPUS.exists(),
    reason="set PAPER_METRICS_REAL=1 and import the manuscripts first")


@pytestmark_real
def test_v1_import_provenance_is_traceable() -> None:
    meta_path = _MPCA_CORPUS / "mpca-v1-rejected" / "_META.json"
    assert meta_path.exists(), f"import {meta_path} first (see report reproduce)"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["engines"] == "import"
    assert meta["import_provenance"]["source_sha256"] == _V1_SHA256
    assert meta["import_provenance"]["source_format"] == "markdown"


@pytestmark_real
def test_rejected_draft_hedges_less_than_journal() -> None:
    """The finding that matched the rejection review: v1 under-hedges.

    Guarded as a direction, not as exact numbers - editing the manuscript would
    change the values, and the point is that the *relation* to the journal
    baseline is stable and reviewable.
    """
    summary = json.loads((_MPCA_PROFILE / "_corpus_summary.json")
                         .read_text(encoding="utf-8"))
    rows = [json.loads(r) for r in
            (_MPCA_PROFILE / "_per_paper_metrics.jsonl").read_text(
                encoding="utf-8").splitlines() if r.strip()]
    by_key = {r["paper_key"]: r for r in rows}
    v1 = by_key["mpca-v1-rejected"]["metrics"]["M-HED-14"]["value"]
    journal = summary["metrics"]["M-HED-14"]["mean"]
    assert v1 < journal * 0.75, (v1, journal)


@pytestmark_real
def test_journal_baseline_has_no_half_stop_inflation() -> None:
    """After v1.6 the kzyjc corpus must not be silently merged again.

    A half-width-terminated corpus whose sentence count is far below its
    terminator count means the boundary rule regressed.
    """
    import glob
    files = glob.glob(str(_KZYJC_CORPUS / "*" / "mineru" / "*" / "auto"
                          / "*_content_list.json"))
    assert files, f"journal corpus missing at {_KZYJC_CORPUS}"
    checked = 0
    for f in files:
        blocks = json.loads(Path(f).read_text(encoding="utf-8"))
        text = "\n".join(b.get("text", "") for b in blocks
                         if isinstance(b, dict) and b.get("type") == "text")
        n_half = text.count(".")
        if n_half < 20:
            continue  # this paper uses full-width stops; not the regression
        sentences = tm.split_sentences_zh(text)
        # before the fix this ratio was ~0.4 (sentences merged); after it is
        # close to 1 (each stop that can end a sentence does)
        assert len(sentences) >= n_half * 0.6, Path(f).name
        checked += 1
        if checked >= 5:
            break
