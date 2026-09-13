#!/usr/bin/env python3
"""Tests for text_metrics.py - the rule-based text metrics layer (I4/I5).

Run:
    cd ~/.claude/skills && uv run pytest paper-metrics/scripts/test_text_metrics.py -v

Coverage: rule-based sentence splitting (abbreviations / decimals / numbering /
initials must not mis-split), tokenization, MTLD (parameters, short-text
degeneration, bidirectional symmetry), the 13 metric ids and their contract
fields, the M-CONN-30 == sum(components) identity, longest-match / non-overlap
phrase matching, evidence spans that slice back to the original text, the
nominalization denylist, the passive irregular table, tense rules, empty-input
degeneration (value None, never NaN), determinism, plus two environment-
dependent cases: the real lexicon bundle (skipped when lexicon_loader or the
v1 data files are absent) and a real VRP corpus excerpt (skipped when missing).

This module must keep working without lexicon_loader: the only bundle used by
the unit tests is the local FakeBundle below.
"""
from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import text_metrics as tm  # noqa: E402

VRP_CORPUS = Path("/mnt/e/AllProjects202601/M-PCA/VRP-GPU课题分析/paper-analysis")

REQUIRED_FIELDS = {
    "value", "n", "denominator", "unit", "state", "method", "metric_spec",
    "evidence", "warnings",
}


# ---------------------------------------------------------------------------
# Minimal fake bundle (duck-typed: only .entries tuples are needed)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FakeLexicon:
    entries: tuple


class FakeBundle:
    """Minimal stand-in for lexicon_loader.LexiconBundle."""

    def __init__(self, *, hedge=("may", "might", "could", "possibly", "it is likely that"),
                 booster=("clearly", "obviously", "must", "demonstrate"),
                 contrastive=("however", "in contrast", "whereas"),
                 causal=("because", "due to"),
                 result=("therefore", "as a result", "consequently"),
                 suffixes=("tion", "sion", "ment", "ness", "ity", "ance", "ence"),
                 verb_bases=("create", "measure", "develop", "apply", "decide", "compute",
                             "inform", "specify", "achieve", "perform", "propose",
                             "demonstrate", "collect", "build", "use", "test", "report"),
                 denylist=("section", "station", "mention", "question", "function"),
                 academic=("method", "system", "result", "analysis", "approach"),
                 stopwords=("the", "of", "and", "in", "to")):
        self.hedge = FakeLexicon(tuple(hedge))
        self.booster = FakeLexicon(tuple(booster))
        self.connectors = {
            "contrastive": FakeLexicon(tuple(contrastive)),
            "causal": FakeLexicon(tuple(causal)),
            "result": FakeLexicon(tuple(result)),
        }
        self.nominalization_suffixes = FakeLexicon(tuple(suffixes))
        self.nominalization_verb_bases = FakeLexicon(tuple(verb_bases))
        self.nominalization_denylist = FakeLexicon(tuple(denylist))
        self.academic_words = FakeLexicon(tuple(academic))
        self.stopwords = FakeLexicon(tuple(stopwords))


BUNDLE = FakeBundle()

SAMPLE_TEXT = (
    "We propose a method that may improve the system. "
    "However, the results indicate that the model was built on a limited dataset, "
    "and it is likely that the creation of new features is affected by the computation cost. "
    "Therefore, we must measure the improvement carefully. "
    "The system clearly demonstrates the application of the approach."
)


def _all_spans_slice_back(text, metrics):
    problems = []
    for metric_id, record in metrics.items():
        for item in record["evidence"]["sample"]:
            start, end = item["span"]
            if not (0 <= start < end <= len(text)):
                problems.append((metric_id, "span out of range", item["span"]))
                continue
            if text[start:end][:80] != item["excerpt"]:
                problems.append((metric_id, "excerpt mismatch", item["span"]))
            if len(item["excerpt"]) > 80:
                problems.append((metric_id, "excerpt too long", len(item["excerpt"])))
    return problems


# ---------------------------------------------------------------------------
# tokenize
# ---------------------------------------------------------------------------

def test_tokenize_lowercases_and_keeps_inner_punctuation():
    assert tm.tokenize("State-of-the-art approach's results, 2024.") == [
        "state-of-the-art", "approach's", "results",
    ]
    assert tm.tokenize("") == []
    assert tm.tokenize("1234 --- []") == []


def test_tokenize_matches_frozen_regex():
    # the frozen regex cuts "A1b" into "a" + "b" and "C_d" into "c" + "d"
    assert tm.tokenize("A1b C_d e-f") == ["a", "b", "c", "d", "e-f"]


# ---------------------------------------------------------------------------
# split_sentences
# ---------------------------------------------------------------------------

def test_split_sentences_basic_and_spans_slice_back():
    text = "First one here. Second one! Third one?"
    spans = tm.split_sentences(text)
    assert [s.text for s in spans] == ["First one here.", "Second one!", "Third one?"]
    for span in spans:
        assert text[span.start:span.end] == span.text
        assert span.text == span.text.strip()


def test_split_sentences_does_not_split_abbreviations():
    text = ("See Smith et al. 2020 and Fig. 3 and Eq. 2, i.e. the same idea, "
            "vs. the other one, cf. Sec. 4 and Ref. [12], approx. 20 values, no. 5. Done.")
    spans = tm.split_sentences(text)
    assert len(spans) == 2
    assert spans[-1].text == "Done."


def test_split_sentences_does_not_split_decimals():
    text = "The value is 3.14 and the ratio is 0.5 exactly. Next sentence."
    assert [s.text for s in tm.split_sentences(text)] == [
        "The value is 3.14 and the ratio is 0.5 exactly.", "Next sentence.",
    ]


def test_split_sentences_protects_line_leading_numbering():
    text = "1. Introduction\n2. Method\nWe do this."
    assert len(tm.split_sentences(text)) == 1
    bracketed = "[12]. Related work follows here."
    assert len(tm.split_sentences(bracketed)) == 1


def test_split_sentences_single_letter_initials_chain():
    assert len(tm.split_sentences("J. R. Smith proposed it. We agree.")) == 2
    assert len(tm.split_sentences("A. Method\nWe do this.")) == 1
    # F3 regression: the initial rule keys on the RIGHT side only, so a lowercase
    # introducer ("by", "and") no longer breaks the initial apart.
    assert len(tm.split_sentences(
        "The method was proposed by J. Smith. Later, work by R. Kumar improved it.")) == 2
    assert [s.text for s in tm.split_sentences("A. Smith, B. Jones and C. Lee. Done.")] == [
        "A. Smith, B. Jones and C. Lee.", "Done.",
    ]
    # documented, accepted cost of the frozen right-side rule: a genuine
    # one-letter symbol at a sentence end followed by a capitalised word merges
    assert len(tm.split_sentences("We denote the variable X. We then compute it.")) == 1


def test_split_sentences_single_letter_is_not_over_protected():
    # digits and brackets after a one-letter symbol are real boundaries
    assert len(tm.split_sentences("The variable is X. 25 runs were executed.")) == 2
    assert len(tm.split_sentences("The variable is X. [12] reports it.")) == 2
    # a genuine sentence end after a lowercase word still splits
    assert len(tm.split_sentences("The method works well. The cost is low.")) == 2
    assert len(tm.split_sentences("Results were obtained. they were reproducible.")) == 1  # lowercase follower heuristic
    # the lowercase-follower merge comes from the frozen unknown-abbreviation
    # heuristic, not from the initial rule
    assert len(tm.split_sentences("The limit is Y. however, we proceed.")) == 1


def test_split_sentences_newline_then_digit_or_bracket_still_splits():
    """Regression: the abbreviation probe must not cross a line break.

    Scientific prose frequently starts a sentence with a number, "[12]" or a
    formula; probing past it used to merge two sentences and deflate the
    M-SLEN-01 / M-LSF-16 / M-PAS-09 denominators.
    """
    nl = "\n"
    assert len(tm.split_sentences("Model was trained." + nl + "10 experiments were performed.")) == 2
    assert len(tm.split_sentences("Results follow." + nl + "[12] showed gains.")) == 2
    assert len(tm.split_sentences("We use 3 layers. 4 layers are enough.")) == 2


def test_split_sentences_newline_then_formula_or_lowercase_still_splits():
    nl = "\n"
    # inline/block formula right after the stop
    assert len(tm.split_sentences("The cost is low." + nl + "L = 1/N is the loss.")) == 2
    assert len(tm.split_sentences("The bound holds." + nl + "[a, b] is convex.")) == 2
    # lowercase continuation on the next line is still a new sentence
    assert len(tm.split_sentences("This holds." + nl + "where N is the count.")) == 2


def test_split_sentences_see_fig_three_splits():
    assert [s.text for s in tm.split_sentences("See Fig. 3 for details. The cost is low.")] == [
        "See Fig. 3 for details.", "The cost is low.",
    ]


def test_evidence_rule_is_frozen_on_every_metric():
    metrics = tm.compute_text_metrics(SAMPLE_TEXT, BUNDLE)
    for metric_id, record in metrics.items():
        rule = record["evidence_rule"]
        assert "order=document" in rule and "sample=first_5" in rule, metric_id
        assert "excerpt=text[start:end][:80]" in rule, metric_id
    assert "longest_nonoverlapping" in metrics["M-HED-14"]["evidence_rule"]
    assert "words>=40" in metrics["M-LSF-16"]["evidence_rule"]
    assert "passive_phrase_span" in metrics["M-PAS-09"]["evidence_rule"]


def test_split_sentences_empty_and_letterless_input():
    assert tm.split_sentences("") == []
    assert tm.split_sentences("   ") == []
    assert tm.split_sentences("--- 12. [3] (4)") == []


# --- Chinese (zh) sentence splitting: issue #13 --------------------------------

def test_cjk_sentence_terminators_split():
    text = "本文研究车辆路径问题。第二句在这里。第三句！"
    assert [s.text for s in tm.split_sentences(text)] == [
        "本文研究车辆路径问题。", "第二句在这里。", "第三句！"]


def test_cjk_terminator_run_ends_once():
    """…… and ！！ are one terminator run, not one sentence per character."""
    assert [s.text for s in tm.split_sentences("这是一句……然后继续。")] == [
        "这是一句……", "然后继续。"]
    assert len(tm.split_sentences("等等！！后面还有。")) == 2


def test_cjk_closing_quote_stays_inside_the_sentence():
    assert [s.text for s in tm.split_sentences("他说：「好。」然后离开。")] == [
        "他说：「好。」", "然后离开。"]


def test_cjk_semicolon_is_not_a_boundary():
    """Chinese uses ； inside a sentence; splitting on it would fragment prose."""
    assert len(tm.split_sentences("第一点是这个；第二点是那个。")) == 1


def test_cjk_sentences_are_not_dropped_as_letterless_fragments():
    """Regression: the ASCII-only fragment filter used to drop every CJK sentence."""
    spans = tm.split_sentences("本文提出了一种方法。")
    assert len(spans) == 1 and spans[0].text == "本文提出了一种方法。"


def test_mixed_zh_en_splits_on_both_terminator_sets():
    text = "本文提出了一个方法。We propose a method. 结果如下。"
    assert [s.text for s in tm.split_sentences(text)] == [
        "本文提出了一个方法。", "We propose a method.", "结果如下。"]


def test_zh_unit_count_covers_mixed_sentences():
    """A mixed sentence must not be under-counted by ignoring its ASCII terms."""
    text = "采用 K-means 算法求解"
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    assert cjk == 6
    # one ASCII token (the hyphen keeps "K-means" together), so 6 + 1 = 7
    assert tm._zh_cjk_unit_count(text) == cjk + 1 == 7


def test_chinese_abstract_noun_rule():
    """M-NOM-10 for Chinese counts abstract-noun suffixes, not verb derivations.

    Chinese converts verbs to nouns by zero derivation, so the English
    suffix+verb-base rule cannot apply; the recorded variant makes clear that the
    two numbers are different statistics.
    """
    spans = tm.split_sentences("该方法的稳定性和求解效率都很重要。")
    hits = tm._cjk_abstract_noun_hits(spans)
    excerpts = sorted(spans[0].text[start - spans[0].start:end - spans[0].start]
                      for start, end, _ in hits)
    # the span is a window ending at the suffix, so a reviewer sees the word
    assert any(text.endswith("稳定性") for text in excerpts)
    assert any(text.endswith("效率") for text in excerpts)
    # 化 must never count: 优化 / 转化 / 深化 are verbs, not nominalisations
    assert tm._cjk_abstract_noun_hits(tm.split_sentences("我们优化了模型并转化了目标函数。")) == []
    # a bare suffix with too short a prefix is not an abstract noun
    assert tm._cjk_abstract_noun_hits(tm.split_sentences("性 度 率")) == []
    # each hit carries the preceding window so a reviewer sees a real word
    assert all(end - start >= 2 for start, end, _ in hits)


def test_chinese_metric_weights_are_declared():
    assert tm._LONG_SENTENCE_CJK_UNITS == 80
    assert tm._UNIT_CJK_UNITS_PER_SENTENCE == "cjk-units/sentence"
    assert "zh" in tm.SUPPORTED_LANGUAGES


# --- anchor regressions for the keywords / inline-math defect -----------------
# The three patterns below are the ones the issue reproduces on the real corpus
# (Okulewicz keywords line, Chen inline formula, TRACE-VNS formula span).  A
# keywords line or a bare formula must never enter a sentence denominator.

def test_split_sentences_drops_keywords_line_anchor():
    text = ("This paper studies routing.\n"
            "Keywords: Dynamic Vehicle Routing Problem,Particle Swarm Optimization,Hyperheuristic\n"
            "We propose a method.")
    spans = tm.split_sentences(text)
    assert [s.text for s in spans] == ["This paper studies routing.", "We propose a method."]
    assert not any(s.text.lower().startswith("keyword") for s in spans)
    # a keywords line on its own is metadata, not a one-word "sentence"
    assert tm.split_sentences("Keywords: a, b, c") == []
    assert tm.split_sentences("KEY WORDS: routing, scheduling") == []
    assert tm.split_sentences("关键词：车辆路径；粒子群") == []


def test_split_sentences_inline_math_anchor_does_not_become_a_sentence():
    # a formula fragment on its own carries no prose and must be dropped
    assert tm.split_sentences("$c: E \\to \\mathbb{R}$") == []
    assert tm.split_sentences("$x = 1$.") == []
    # a full stop *inside* math must not end a sentence
    text = "The cost is $c_{1} = 0.5$. The second case follows."
    assert [s.text for s in tm.split_sentences(text)] == [
        "The cost is $c_{1} = 0.5$.", "The second case follows.",
    ]
    # display math keeps its surrounding prose split
    nl = "\n"
    assert [s.text for s in tm.split_sentences("Before." + nl + "$$\\sum_{i} x_{i} = 0.$$" + nl + "After it.")] == [
        "Before.", "After it.",
    ]


def test_split_sentences_sub_sup_markup_is_noise():
    text = "Water is H<sub>2</sub>O and x<sup>2</sup> is small. Next one."
    spans = tm.split_sentences(text)
    assert [s.text for s in spans] == ["Water is H<sub>2</sub>O and x<sup>2</sup> is small.", "Next one."]
    assert tm.split_sentences("<sub>2</sub>") == []


def test_split_sentences_span_contract_holds_after_normalisation():
    text = ("Prose before the keywords line." + "\n"
            "Keywords: a, b" + "\n"
            "Prose with $x$ math. And a second one.")
    spans = tm.split_sentences(text)
    assert len(spans) == 3
    for span in spans:
        assert text[span.start:span.end] == span.text
        assert span.text == span.text.strip()
        assert "$" not in span.text or span.text.endswith(".")


# ---------------------------------------------------------------------------
# MTLD
# ---------------------------------------------------------------------------

def test_mtld_short_text_returns_nan():
    assert math.isnan(tm.mtld(["a"] * (2 * tm._MTLD_MIN_FACTOR - 1)))
    assert not math.isnan(tm.mtld(["a"] * (2 * tm._MTLD_MIN_FACTOR)))
    assert math.isnan(tm.mtld([]))


def test_mtld_is_bidirectional_symmetric():
    tokens = ("the quick brown fox jumps over the lazy dog").split() * 3
    assert tm.mtld(tokens) == tm.mtld(list(reversed(tokens)))
    assert tm.mtld(tokens) > 0


def test_mtld_pinned_parameters_are_frozen():
    assert tm._MTLD_TTR_THRESHOLD == 0.720
    assert tm._MTLD_MIN_FACTOR == 10
    assert tm._LONG_SENTENCE_WORDS == 40
    # 1.1: pre-split non-prose masking changed the sentence denominators
    # (issues #2 / #3) -> the version must move with the numbers.
    assert tm.TEXT_METRICS_VERSION == "1.4"


# ---------------------------------------------------------------------------
# compute_text_metrics: contract shape
# ---------------------------------------------------------------------------

def test_every_metric_id_is_present_with_contract_fields():
    metrics = tm.compute_text_metrics(SAMPLE_TEXT, BUNDLE)
    assert set(metrics) == set(tm.METRIC_IDS)
    assert len(tm.METRIC_IDS) == 13
    for metric_id, record in metrics.items():
        assert REQUIRED_FIELDS <= set(record), metric_id
        assert record["metric_spec"] == metric_id
        assert record["state"] == "OBSERVED"
        assert record["method"] == "rule"
        assert isinstance(record["n"], int) and isinstance(record["denominator"], int)
        assert isinstance(record["unit"], str) and record["unit"]
        assert len(record["evidence"]["sample"]) <= 5
        assert record["evidence"]["count"] >= 0
        assert isinstance(record["warnings"], list)


def test_evidence_spans_slice_back_to_the_original_text():
    metrics = tm.compute_text_metrics(SAMPLE_TEXT, BUNDLE)
    assert _all_spans_slice_back(SAMPLE_TEXT, metrics) == []
    assert any(record["evidence"]["sample"] for record in metrics.values())


def test_evidence_sample_is_capped_at_five():
    text = ("may " * 30).strip() + " and this may happen."
    metrics = tm.compute_text_metrics(text, BUNDLE)
    hedges = metrics["M-HED-14"]
    assert hedges["n"] == 31
    assert len(hedges["evidence"]["sample"]) == 5


def test_json_output_never_contains_nan():
    metrics = tm.compute_text_metrics(SAMPLE_TEXT, BUNDLE)
    blob = json.dumps(metrics, sort_keys=True)
    assert "NaN" not in blob
    short = tm.compute_text_metrics("Too short.", BUNDLE)
    assert short["M-MTLD-02"]["value"] is None
    assert "NaN" not in json.dumps(short, sort_keys=True)


def test_empty_text_degrades_to_none_with_warnings():
    metrics = tm.compute_text_metrics("", BUNDLE)
    assert metrics["M-SLEN-01"]["value"] is None
    assert metrics["M-SLEN-01"]["n"] == 0 and metrics["M-SLEN-01"]["denominator"] == 0
    assert metrics["M-LSF-16"]["value"] is None
    assert metrics["M-MTLD-02"]["value"] is None
    assert metrics["M-HED-14"]["value"] is None
    assert metrics["M-CONN-30"]["value"] is None
    assert metrics["M-PAS-09"]["value"] is None
    assert metrics["M-NOM-10"]["value"] is None
    assert metrics["M-TENSE-28"]["value"] is None
    for metric_id, record in metrics.items():
        assert record["warnings"], metric_id


def test_deterministic_across_two_runs():
    first = json.dumps(tm.compute_text_metrics(SAMPLE_TEXT, BUNDLE), sort_keys=True, ensure_ascii=False)
    second = json.dumps(tm.compute_text_metrics(SAMPLE_TEXT, BUNDLE), sort_keys=True, ensure_ascii=False)
    assert first == second


# ---------------------------------------------------------------------------
# Sentence-level metrics
# ---------------------------------------------------------------------------

def test_slen_mean_denominator_and_distribution():
    record = tm.compute_text_metrics("One two three. Four five.", BUNDLE)["M-SLEN-01"]
    assert record["value"] == pytest.approx(2.5)
    assert record["n"] == 2
    assert record["denominator"] == 5
    assert record["unit"] == "words/sentence"
    assert record["distribution"] == {"median": 2.5, "p25": 2.25, "p75": 2.75, "std": 0.5}


def test_lsf_threshold_is_forty_words():
    long_sentence = ("alpha beta gamma delta " * 10).strip()
    text = long_sentence + ". Short one."
    record = tm.compute_text_metrics(text, BUNDLE)["M-LSF-16"]
    assert record["value"] == pytest.approx(0.5)
    assert record["n"] == 1
    assert record["denominator"] == 2
    assert record["long_sentence_threshold"] == 40


# ---------------------------------------------------------------------------
# Lexicon-driven metrics
# ---------------------------------------------------------------------------

def test_denominator_is_the_alpha_token_count():
    metrics = tm.compute_text_metrics(SAMPLE_TEXT, BUNDLE)
    expected = len(tm.tokenize(SAMPLE_TEXT))
    for metric_id in ("M-HED-14", "M-BOO-15", "M-AWR-03", "M-NOM-10",
                      "M-CONN-30", "M-CONN-30c", "M-CONN-30k", "M-CONN-30r"):
        assert metrics[metric_id]["denominator"] == expected, metric_id


def test_connector_identity_total_equals_component_sum():
    metrics = tm.compute_text_metrics(SAMPLE_TEXT, BUNDLE)
    parts = [metrics["M-CONN-30c"], metrics["M-CONN-30k"], metrics["M-CONN-30r"]]
    total = metrics["M-CONN-30"]
    assert total["value"] == round(sum(part["value"] for part in parts), 6)
    assert abs(total["value"] - sum(part["value"] for part in parts)) < 1e-9
    assert total["n"] == sum(part["n"] for part in parts)
    assert total["unit"] == "per-1000-words"
    assert total["components"]["M-CONN-30c"]["n"] == metrics["M-CONN-30c"]["n"]


def test_connector_density_is_per_thousand_words():
    bundle = FakeBundle(contrastive=("however",), causal=(), result=())
    text = ("word " * 100).strip() + " however"
    record = tm.compute_text_metrics(text, bundle)["M-CONN-30c"]
    assert record["denominator"] == 101
    assert record["value"] == pytest.approx(1 / 101 * 1000)


def test_longest_match_wins_and_hits_do_not_overlap():
    bundle = FakeBundle(hedge=("contrast", "in contrast", "may", "may be"))
    text = "In contrast, results may be biased."
    record = tm.compute_text_metrics(text, bundle)["M-HED-14"]
    assert record["n"] == 2  # "in contrast" + "may be" (never overlapping short forms)
    excerpts = [item["excerpt"] for item in record["evidence"]["sample"]]
    assert excerpts == ["In contrast", "may be"]


def test_phrase_matching_does_not_cross_sentence_boundaries():
    bundle = FakeBundle(hedge=("may be",))
    text = "It may. Be careful."  # "may" + "be" are in different sentences
    assert tm.compute_text_metrics(text, bundle)["M-HED-14"]["n"] == 0
    assert tm.compute_text_metrics("It may be fine.", bundle)["M-HED-14"]["n"] == 1


def test_causal_ambiguous_bare_words_are_not_counted():
    """B3: bare "as"/"since"/"through"/"so"/"still" are not causal connectives."""
    bundle = FakeBundle(causal=("because", "due to", "owing to", "as a result of"),
                        contrastive=("however",), result=("therefore", "so that"))
    text = "We use the GPU as a coprocessor. As shown in Fig. 1, it works."
    assert tm.compute_text_metrics(text, bundle)["M-CONN-30k"]["n"] == 0
    unambiguous = ("The cost is high because of memory limits. "
                   "Due to the batch size, we split the work. "
                   "Owing to the scheduler, runs overlap.")
    record = tm.compute_text_metrics(unambiguous, bundle)["M-CONN-30k"]
    assert record["n"] == 3
    assert record["value"] > 0


def test_academic_word_ratio():
    bundle = FakeBundle(academic=("method", "system"))
    record = tm.compute_text_metrics("The method and the system work.", bundle)["M-AWR-03"]
    assert record["n"] == 2
    assert record["value"] == pytest.approx(2 / 6)


# ---------------------------------------------------------------------------
# Passive
# ---------------------------------------------------------------------------

def test_passive_uses_irregular_participle_table():
    text = ("The model was built by us. The data were collected carefully. "
            "The result was shown in Fig. 1.")
    record = tm.compute_text_metrics(text, BUNDLE)["M-PAS-09"]
    assert record["n"] == 3
    assert record["denominator"] == 3
    assert record["value"] == pytest.approx(1.0)
    assert record["n_unresolved"] == 0
    assert len(tm._IRREGULAR_PARTICIPLE) >= 100


def test_passive_copula_is_unresolved_not_passive():
    text = "The system is important. The result was limited. The model was validated."
    record = tm.compute_text_metrics(text, BUNDLE)["M-PAS-09"]
    assert record["n"] == 1  # "was validated" is the only real passive
    assert record["n_unresolved"] == 2  # "is important", "was limited"
    assert record["warnings"]


def test_passive_regular_ed_participle_and_adverbs():
    text = "The data were carefully collected and the model was finally tested."
    assert tm.compute_text_metrics(text, BUNDLE)["M-PAS-09"]["n"] == 1


def test_pas09_evidence_is_phrase_level_but_value_unchanged():
    text = ("The model was built by us. The data were carefully collected. "
            "The problem is complicated.")
    record = tm.compute_text_metrics(text, BUNDLE)["M-PAS-09"]
    # value / n / denominator keep the frozen sentence-level ratio semantics
    assert record["n"] == 2
    assert record["denominator"] == 3
    assert record["value"] == pytest.approx(2 / 3)
    assert record["evidence_target"] == "passive_phrase_span"
    assert [item["excerpt"] for item in record["evidence"]["sample"]] == [
        "was built", "were carefully collected",
    ]
    for item in record["evidence"]["sample"]:
        start, end = item["span"]
        assert text[start:end] == item["excerpt"]


def test_pas09_phrase_span_includes_perfect_and_modal_lead():
    hits, unresolved = tm.detect_passive_spans("The system has been adopted widely.")
    assert [hit.phrase for hit in hits] == ["has been adopted"]
    assert unresolved == 0
    hits, _ = tm.detect_passive_spans("This can be mapped onto a graph.")
    assert [hit.phrase for hit in hits] == ["can be mapped"]
    hits, _ = tm.detect_passive_spans("The data were carefully collected.")
    assert [hit.phrase for hit in hits] == ["were carefully collected"]
    assert hits[0].participle == "collected"
    assert hits[0].sentence.text == "The data were carefully collected."


def test_passive_copula_adjectives_are_not_passive():
    """B2: "is complicated" / "were tired" are copular (主系表), not passive."""
    text = "The problem is complicated. We were tired after the experiment."
    record = tm.compute_text_metrics(text, BUNDLE)["M-PAS-09"]
    assert record["n"] == 0
    assert record["value"] == 0.0
    assert record["denominator"] == 2
    assert record["n_unresolved"] == 2
    assert tm._PARTICIPIAL_ADJECTIVE_DENYLIST >= {
        "complicated", "tired", "interested", "excited", "involved",
        "related", "concerned", "limited", "based",
    }


def test_passive_real_constructions_survive_the_denylist():
    """The denylist must not erase genuine agentless passives."""
    # NB: avoid one-letter sentence-final symbols here, they are intentionally
    # merged by the frozen F3 right-side initial rule.
    text = ("The method was proposed by Smith. The results were obtained using a script. "
            "The model was trained on a GPU. The bound is known to be tight. "
            "The GPU is used to accelerate the search.")
    record = tm.compute_text_metrics(text, BUNDLE)["M-PAS-09"]
    assert record["n"] == 5
    assert record["denominator"] == 5
    assert record["value"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Tense
# ---------------------------------------------------------------------------

def test_tense_present_past_split_and_unresolved():
    text = "The system achieves good results. It was tested on data. We can improve it."
    record = tm.compute_text_metrics(text, BUNDLE)["M-TENSE-28"]
    assert record["n"] == record["n_present"] >= 1
    assert record["n_past"] >= 1
    assert record["denominator"] == record["n_present"] + record["n_past"]
    assert record["value"] == pytest.approx(record["n_present"] / record["denominator"])
    assert record["n_unresolved"] == 1  # "can"


def test_tense_does_not_count_plural_nouns_as_present():
    # "model"/"result" are verb bases too, but their plural forms are the
    # dominant reading and are excluded by the frozen ambiguity gate.
    bundle = FakeBundle(verb_bases=("model", "result"))
    text = "The models and results matter here."
    record = tm.compute_text_metrics(text, bundle)["M-TENSE-28"]
    assert record["n_present"] == 0
    assert record["n_past"] == 0
    assert {"model", "result"} <= tm._AMBIGUOUS_NOUN_VERBS
    # sanity: without the ambiguity gate the same verb bases would be counted
    assert "models" in tm._build_third_person_index(("model", "result"))


# ---------------------------------------------------------------------------
# Nominalization
# ---------------------------------------------------------------------------

def test_nominalization_denylist_excludes_pseudo_nominalizations():
    bundle = FakeBundle(verb_bases=("create", "measure", "inform"),
                        denylist=("section", "station", "mention", "function"))
    text = "The section and the station and the mention of function follow the creation and information."
    record = tm.compute_text_metrics(text, bundle)["M-NOM-10"]
    hits = [item["excerpt"] for item in record["evidence"]["sample"]]
    assert record["n"] == 2
    assert hits == ["creation", "information"]


def test_nominalization_ation_ition_restoration():
    """-ation / -ition forms must be restored to their verb bases."""
    bundle = FakeBundle(verb_bases=("inform", "describe", "evaluate", "recognize"),
                        suffixes=("tion", "sion"), denylist=())
    text = "The information and the description support the evaluation and the recognition."
    record = tm.compute_text_metrics(text, bundle)["M-NOM-10"]
    assert record["n"] == 4
    assert [item["excerpt"] for item in record["evidence"]["sample"]] == [
        "information", "description", "evaluation", "recognition",
    ]


def test_nominalization_plural_form_is_normalised():
    bundle = FakeBundle(verb_bases=("apply",), suffixes=("tion",))
    assert tm.compute_text_metrics("applications matter.", bundle)["M-NOM-10"]["n"] == 1


def test_nominalization_empty_suffix_lexicon_warns_not_crashes():
    bundle = FakeBundle(suffixes=())
    record = tm.compute_text_metrics("The creation is here.", bundle)["M-NOM-10"]
    assert record["value"] == 0.0
    assert record["warnings"]


# ---------------------------------------------------------------------------
# Language detection and "unsupported means null, never 0" (Round A)
# ---------------------------------------------------------------------------

CHINESE_TEXT = (
    "本文提出了一种基于强化学习的车辆路径问题求解方法。"
    "我们在多个基准算例上验证了该方法的有效性，并与传统启发式算法进行了比较。"
    "实验结果表明，所提方法在求解质量与计算时间上均具有优势。"
)

#: Frozen pre-language-gate values for SAMPLE_TEXT + BUNDLE:
#: metric_id -> [value, n, denominator].  The language gate must not move any
#: English number by even one unit in the last place.
ENGLISH_GOLDEN = {
    "M-AWR-03": [0.074074, 4, 54],
    "M-BOO-15": [0.037037, 2, 54],
    "M-CONN-30": [37.037038, 2, 54],
    "M-CONN-30c": [18.518519, 1, 54],
    "M-CONN-30k": [0.0, 0, 54],
    "M-CONN-30r": [18.518519, 1, 54],
    "M-HED-14": [0.037037, 2, 54],
    "M-LSF-16": [0.0, 0, 4],
    "M-MTLD-02": [54.216, 54, 1],
    "M-NOM-10": [0.055556, 3, 54],
    "M-PAS-09": [0.25, 1, 4],
    "M-SLEN-01": [13.5, 4, 54],
    "M-TENSE-28": [0.428571, 3, 7],
}


def test_language_threshold_constant_is_frozen():
    assert tm.LANGUAGE_SUPPORT_CJK_THRESHOLD == 0.10
    assert tm.LANGUAGE_NOT_SUPPORTED == "LANGUAGE_NOT_SUPPORTED"


def test_detect_language_english():
    info = tm.detect_language(SAMPLE_TEXT)
    assert info["language"] == "en"
    assert info["supported"] is True
    assert info["cjk_chars"] == 0
    assert info["cjk_ratio"] == 0.0
    assert info["ascii_alpha_tokens"] == len(tm.tokenize(SAMPLE_TEXT))
    assert info["reason"] is None


def test_detect_language_chinese_is_unsupported_and_loud():
    info = tm.detect_language(CHINESE_TEXT)
    assert info["language"] == "zh"
    assert info["supported"] is False
    assert info["cjk_ratio"] > tm.LANGUAGE_SUPPORT_CJK_THRESHOLD
    assert info["cjk_chars"] > 0
    assert info["ascii_alpha_tokens"] == 0
    assert info["reason"] and "LANGUAGE_NOT_SUPPORTED" in info["reason"]


def test_detect_language_empty_and_non_string():
    empty = tm.detect_language("")
    assert empty == {
        "language": "unknown", "cjk_ratio": 0.0, "cjk_chars": 0,
        "ascii_alpha_tokens": 0, "supported": True, "reason": None,
    }
    # documented: an empty/letter-less text has ratio 0.0, so it is "supported"
    # (nothing is measured anywhere in it) but its language is "unknown"
    assert tm.detect_language(None)["language"] == "unknown"
    assert tm.detect_language(None)["supported"] is True


def test_chinese_measures_the_supported_subset_and_names_the_rest():
    """Chinese is a per-metric capability, not an all-or-nothing language gate.

    Issue #13: the metrics whose pinned rules need no lexicon (sentence length,
    long-sentence ratio) are measured; every other metric is null with
    CAPABILITY_NOT_SUPPORTED, which stays distinguishable from "measured 0".
    """
    metrics = tm.compute_text_metrics(CHINESE_TEXT, BUNDLE)
    assert set(metrics) == set(tm.METRIC_IDS)
    measured: list[str] = []
    for metric_id, record in metrics.items():
        languages = tm._METRIC_LANGUAGE_CAPABILITY.get(
            metric_id, tm._DEFAULT_METRIC_LANGUAGES)
        assert record["state"] == "OBSERVED" and record["method"] == "rule", metric_id
        assert record["metric_spec"] == metric_id
        assert record["unit"], metric_id
        assert record["evidence_rule"], metric_id
        assert record["language"] == "zh"
        assert record["cjk_ratio"] > tm.LANGUAGE_SUPPORT_CJK_THRESHOLD
        if "zh" in languages:
            measured.append(metric_id)
            assert record["value"] is not None, metric_id
            assert record["warnings"] == [], metric_id
            # measured means a non-empty denominator; the evidence count is the
            # number of *hits*, which is legitimately 0 for a rate metric
            assert record["denominator"] > 0, metric_id
        else:
            assert record["value"] is None, metric_id
            assert record["n"] == 0 and record["denominator"] == 0, metric_id
            assert record["warnings"] == ["CAPABILITY_NOT_SUPPORTED"], metric_id
            assert record["evidence"] == {"count": 0, "sample": []}, metric_id
    # 12 of the 14 metrics are measurable for Chinese; only the two that need an
    # annotation set (M-NOM-10) or do not exist in the language (M-TENSE-28,
    # Chinese has no tense) stay unsupported.
    # 13 of the 14 metrics are measurable for Chinese: only M-TENSE-28 stays
    # unmeasurable, because Chinese has no tense and a number there would be
    # fabricated. M-NOM-10 is measurable as the abstract-noun-suffix variant.
    assert set(measured) == set(tm.METRIC_IDS) - {"M-TENSE-28"}
    assert metrics["M-NOM-10"]["variant"] == "cjk-abstract-noun-suffix"
    assert metrics["M-NOM-10"]["unit"] == tm._UNIT_PER_1000_CJK_UNITS
    assert "化" in metrics["M-NOM-10"]["excluded_suffixes"]
    assert metrics["M-SLEN-01"]["unit"] == tm._UNIT_CJK_UNITS_PER_SENTENCE
    assert metrics["M-LSF-16"]["long_sentence_threshold"] == tm._LONG_SENTENCE_CJK_UNITS
    assert metrics["M-CONN-30"]["unit"] == tm._UNIT_PER_1000_CJK_UNITS
    assert metrics["M-MTLD-02"]["params"]["tokenization"] == "cjk-char+ascii-token"
    assert "NaN" not in json.dumps(metrics, sort_keys=True)


def test_english_values_are_bit_identical_to_pre_language_gate():
    metrics = tm.compute_text_metrics(SAMPLE_TEXT, BUNDLE)
    assert set(ENGLISH_GOLDEN) == set(tm.METRIC_IDS)
    for metric_id, (value, n, denominator) in ENGLISH_GOLDEN.items():
        record = metrics[metric_id]
        assert record["value"] == value, metric_id
        assert record["n"] == n, metric_id
        assert record["denominator"] == denominator, metric_id
        assert record["language"] == "en", metric_id
        assert record["cjk_ratio"] == 0.0, metric_id
        assert "LANGUAGE_NOT_SUPPORTED" not in record["warnings"], metric_id


def test_mixed_language_ratio_boundary():
    # 11 / (11 + 89) = 0.11 -> unsupported
    above = tm.detect_language("车" * 11 + " " + "word " * 89)
    assert (above["cjk_chars"], above["ascii_alpha_tokens"]) == (11, 89)
    assert above["cjk_ratio"] == pytest.approx(0.11)
    assert above["supported"] is False and above["language"] == "zh"
    # zh: the surface metrics are measured; the two unmeasurable ones say why
    mixed_zh = tm.compute_text_metrics("车" * 11 + " " + "word " * 89, BUNDLE)
    assert mixed_zh["M-SLEN-01"]["value"] is not None
    assert mixed_zh["M-HED-14"]["value"] is not None
    assert mixed_zh["M-TENSE-28"]["warnings"] == ["CAPABILITY_NOT_SUPPORTED"]
    # 10 / (10 + 90) = 0.10 exactly -> supported (threshold is inclusive)
    exact = tm.detect_language("车" * 10 + " " + "word " * 90)
    assert exact["cjk_ratio"] == pytest.approx(0.10)
    assert exact["supported"] is True and exact["language"] == "en"
    assert tm.compute_text_metrics("车" * 10 + " " + "word " * 90, BUNDLE)["M-SLEN-01"]["value"] is not None
    # 9 / (9 + 91) = 0.09 -> supported
    below = tm.detect_language("车" * 9 + " " + "word " * 91)
    assert below["cjk_ratio"] == pytest.approx(0.09)
    assert below["supported"] is True and below["language"] == "en"


def test_unsupported_language_never_raises_on_empty_bundle():
    """No lexicon bundle must still not raise, and must not fabricate numbers."""
    metrics = tm.compute_text_metrics(CHINESE_TEXT, None)
    # No bundle at all: the lexicon-driven metrics must degrade to empty
    # lexicons (all-zero densities are legitimate here because the lexicon is
    # empty and the warning says so), and nothing may raise.
    for mid, record in metrics.items():
        if record["value"] is None:
            assert record["warnings"] == ["CAPABILITY_NOT_SUPPORTED"], mid
        elif mid in {"M-HED-14", "M-BOO-15", "M-CONN-30c", "M-CONN-30k",
                     "M-CONN-30r", "M-AWR-03"}:
            assert any("is empty" in w for w in record["warnings"]), mid
    assert metrics["M-SLEN-01"]["value"] is not None


# ---------------------------------------------------------------------------
# Environment-dependent integration cases
# ---------------------------------------------------------------------------

def test_integration_with_real_lexicon_bundle():
    loader = pytest.importorskip("lexicon_loader")
    try:
        bundle = loader.load_lexicons()
    except Exception as exc:  # data/lexicons/v1 may not have landed yet
        pytest.skip(f"real lexicon data unavailable: {type(exc).__name__}: {exc}")
    metrics = tm.compute_text_metrics(SAMPLE_TEXT, bundle)
    assert set(metrics) == set(tm.METRIC_IDS)
    assert _all_spans_slice_back(SAMPLE_TEXT, metrics) == []
    for metric_id in ("M-HED-14", "M-BOO-15"):
        record = metrics[metric_id]
        assert record["n_lexicon_entries"] >= 40, metric_id
    parts = [metrics["M-CONN-30c"], metrics["M-CONN-30k"], metrics["M-CONN-30r"]]
    assert abs(metrics["M-CONN-30"]["value"] - sum(p["value"] for p in parts)) < 1e-9
    assert metrics["M-CONN-30c"]["n_lexicon_entries"] >= 15
    assert metrics["M-AWR-03"]["n_lexicon_entries"] >= 300
    assert metrics["M-NOM-10"]["n_denylist"] >= 60
    assert metrics["M-SLEN-01"]["denominator"] == len(tm.tokenize(SAMPLE_TEXT))


def test_real_connector_lexicon_excludes_ambiguous_bare_words():
    """Integration: the frozen causal lexicon must not keep bare ambiguous words."""
    loader = pytest.importorskip("lexicon_loader")
    try:
        bundle = loader.load_lexicons()
    except Exception as exc:  # data/lexicons/v1 may not have landed yet
        pytest.skip(f"real lexicon data unavailable: {type(exc).__name__}: {exc}")
    causal = set(bundle.connectors["causal"].entries)
    result = set(bundle.connectors["result"].entries)
    contrastive = set(bundle.connectors["contrastive"].entries)
    assert not ({"as", "since", "through"} & causal), sorted({"as", "since", "through"} & causal)
    assert {"because", "because of", "due to", "owing to", "as a result of"} <= causal
    assert "so" not in result and "so that" in result
    assert not ({"still", "while"} & contrastive)
    repro = "We use the GPU as a coprocessor. As shown in Fig. 1, it works."
    assert tm.compute_text_metrics(repro, bundle)["M-CONN-30k"]["n"] == 0


def _first_real_corpus_text(limit: int = 6000):
    if not VRP_CORPUS.is_dir():
        return None
    for path in sorted(VRP_CORPUS.glob("*/mineru/*/auto/*_content_list.json")):
        try:
            blocks = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        chunks = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("text")]
        text = "\n".join(chunks)
        if len(text) > 1200:
            return path, text[:limit]
    return None


def test_real_corpus_excerpt_if_available():
    found = _first_real_corpus_text()
    if found is None:
        pytest.skip("real VRP corpus not available")
    path, text = found
    metrics = tm.compute_text_metrics(text, BUNDLE)
    assert set(metrics) == set(tm.METRIC_IDS)
    assert _all_spans_slice_back(text, metrics) == []
    assert metrics["M-SLEN-01"]["n"] >= 3
    assert metrics["M-SLEN-01"]["denominator"] == len(tm.tokenize(text))
    assert metrics["M-MTLD-02"]["value"] is not None
    assert metrics["M-CONN-30"]["value"] is not None
    assert all(0.0 <= metrics[m]["value"] <= 1.0
               for m in ("M-HED-14", "M-BOO-15", "M-AWR-03", "M-NOM-10", "M-PAS-09", "M-TENSE-28"))
    print(f"corpus excerpt: {path.name} chars={len(text)}")
