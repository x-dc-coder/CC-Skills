#!/usr/bin/env python3
"""Rule-based text metrics layer for the paper-metrics profiler (I4/I5).

Frozen API: INTERFACES.md section 3 (implementation interface spec v1).
Pure stdlib, zero LLM calls (OBSERVED red line), deterministic.

Pinned matching rules (a third party reproduces every number from these):

1. **Token** = the regex [A-Za-z][A-Za-z'-]* (ASCII letter, then letters,
   apostrophes or hyphens) matched on the raw text and lowercased.  Digits,
   punctuation and CJK never form tokens; internal apostrophes and hyphens are
   kept ("state-of-the-art" is one token).
2. **Multi-word lexicon entries**: the entry is tokenized with the very same
   rule, then matched against the token stream of each sentence, greedily and
   longest-first, without overlap; one matched span counts exactly once no
   matter how many tokens it spans.  Matching is case-insensitive and never
   crosses a sentence boundary.  Characters *between* the matched tokens
   (punctuation, extra spaces) are ignored, so "on the other hand" also matches
   "on  the other hand" and the recorded span covers the whole phrase.
3. **Numbers**: every float is round(x, 6); a zero denominator or an undefined
   statistic yields value = None plus a warning, because JSON must never
   contain NaN/Infinity.
4. **Contract fields**: every metric carries
   value / n / denominator / unit / state / method / metric_spec / evidence /
   warnings.  evidence.sample has at most 5 entries and follows the frozen
   evidence convention (INTERFACES.md): each entry is
   {"span": [start, end], "excerpt": ...} where span holds [start, end] char
   offsets into the exact input text and excerpt == text[start:end][:80]
   (characters, not words; no whitespace collapsing), so every sample slices
   back to the original characters without loss.  Evidence builders accept
   both 2-tuples and the 3-tuples emitted by _match_entries and always use the
   first two fields.
5. **Evidence sampling rule (frozen, reproducible)**: every metric emits an
   evidence_rule field that pins exactly which items are sampled:
   - candidates are collected in strict document order (sentence index, then
     token index / span start) and never from set or dict iteration;
   - the first 5 candidates are emitted, in that order, as
     sample = [{"span": [start, end], "excerpt": text[start:end][:80]}, ...];
   - evidence.count is the full number of hits (n of the metric or the number
     of sentences/tokens in scope), independent of the sample cap;
   - phrase hits are the greedy longest-match, non-overlapping spans within a
     sentence; one matched span counts once regardless of its token length;
   - M-LSF-16 samples only sentences with >= 40 words, M-PAS-09 only the
     matched passive verb phrase span (aux + <= 2 adverbs + past participle,
     optionally preceded by one perfect/modal auxiliary; the enclosing sentence
     only defines the denominator), M-TENSE-28 only present-tense tokens,
     M-MTLD-02 the first tokens of the text, M-SLEN-01 the first sentences.
   Re-running the same text with the same lexicon bundle therefore reproduces
   the evidence byte for byte.

6. **Language gate (Round A, honesty rule)**: every metric dict carries
   language + cjk_ratio.  detect_language() computes
   cjk_ratio = cjk_chars / (cjk_chars + ascii_alpha_tokens) over the CJK ranges
   U+3400-U+4DBF, U+4E00-U+9FFF, U+F900-U+FAFF; when
   cjk_ratio > LANGUAGE_SUPPORT_CJK_THRESHOLD (0.10) the text is outside the
   validated language (English), and *every* metric is returned as
   value=None / n=0 / denominator=0 with warnings ["LANGUAGE_NOT_SUPPORTED"]
   and an empty evidence sample.  A language the module cannot measure is never
   reported as 0 (that would be a fabricated number) and never raises.

7. **Pre-split normalisation (2026-09-13)**: before any sentence boundary is
   computed, three classes of non-prose characters are blanked to spaces in a
   same-length copy of the text, so every offset stays valid and every span
   still slices the original characters.  (a) A **journal keywords line** (a
   line whose first non-blank token is `Keywords`/`Key words`/`关键词`/
   `关键字` followed by `:`) is metadata, never prose.  (b) **Inline and
   display math** delimited by `$...$` / `$$...$$` (never crossing a line
   break) can no longer be emitted as a standalone "sentence".  (c) The HTML
   **`<sub>`/`<sup>` wrappers** emitted by MinerU are dropped (the characters
   they wrap are kept).  A candidate span whose blanked content contains no
   alpha token is dropped, which is what removes a bare formula or a keywords
   line.  Rationale: keyword lines and inline formulas used to enter the
   sentence denominator of M-SLEN-01 / M-LSF-16 / M-PAS-09 and deflate them
   (issue: 正文块内的关键词行与行内公式参与分句); the normalisation is part of
   the reproducibility contract, not a heuristic knob.

8. **CJK support (Chinese, 2026-09-13, issue #13)**: Chinese is a *per-metric*
   capability, not an all-or-nothing language gate.  Sentence boundaries include
   the CJK terminators `。！？…` (a run like `……` ends once, at its last
   character; a closing quote stays inside the sentence; `；` is NOT a
   boundary because Chinese uses it within a sentence), and the fragment filter
   keeps a span that has no ASCII letter but does have a CJK character.  The
   metrics whose pinned rules need no lexicon are computed for Chinese with
   documented calibers: sentence length counts **CJK characters + ASCII alpha
   tokens** (unit `cjk-units/sentence`, so a mixed sentence is not
   under-counted) and M-LSF-16 uses a Chinese long-sentence threshold of
   `_LONG_SENTENCE_CJK_UNITS` (80) instead of the English 40 words.  Every
   other metric is reported as `null` with **CAPABILITY_NOT_SUPPORTED** — the
   per-metric sibling of LANGUAGE_NOT_SUPPORTED, and still never 0.
   `_METRIC_LANGUAGE_CAPABILITY` is the single source of truth for the matrix.

Deliberate, documented readings of the contract:

* _MTLD_MIN_FACTOR (10) is used only as the length guard
  (len(tokens) < 2 * 10 -> nan).  Factors themselves close as soon as the
  running TTR drops to <= 0.720 (McCarthy & Jarvis 2010); the trailing partial
  factor is scored (1 - TTR) / (1 - threshold), and the reported MTLD is the
  mean of the forward and the reversed pass (bidirectional).
* M-TENSE-28 accepts third-person -s / -es / -ies forms only when the singular
  base is a known verb base (module-frozen _COMMON_VERB_BASES union the
  bundle's nominalization_verb_bases, minus _AMBIGUOUS_NOUN_VERBS).  Without
  that gate every plural noun ("results", "methods", "models") would be
  counted as a present-tense verb and the ratio would be meaningless.  -ed
  forms count as past unless they appear in the frozen participial-adjective
  denylist.  Everything verb-like but tense-ambiguous (modals, be/been/being)
  is reported as n_unresolved.
* M-PAS-09 counts a sentence as passive when a passive auxiliary
  (be/am/is/are/was/were/been/being/get/gets/got/become/becomes/became) is
  followed, after at most two adverbs, by a past participle (irregular table
  >= 100 entries, or an -ed form of at least 4 chars).  A frozen denylist of
  adjectival participles removes the copular false positives ("the problem is
  complicated", "we were tired"), which are then counted as n_unresolved
  instead.  Auxiliaries that do not resolve are reported as n_unresolved.
* M-NOM-10 applies the contract rule (ends with a frozen suffix AND the base is
  a frozen verb base AND the whole token is not in the denylist) with an
  explicit, frozen candidate set for the stem -> verb restoration:
  stem, stem+e, stem+y, stem+te, stem+ate, stem+de, stem+t; for a stem ending
  in a vowel additionally stem[:-1], stem[:-1]+e, stem[:-1]+y; for a stem
  ending in "ica" additionally stem[:-3]+"y"; for a stem ending in p/b
  additionally stem[:-1]+"be"; for a stem ending in "i" additionally stem+"ze"
  (so creation -> crea -> create, computation -> computa -> compute,
  information -> informa -> inform, description -> descrip -> describe,
  recognition -> recogni -> recognize, application -> applica -> apply,
  specification -> specifica -> specify, decision -> deci -> decide).  Plural
  forms are normalised first
  (-s / -es / -ies -> y).  Candidates are only ever tested against the frozen
  verb-base set, never against a fuzzy match, so the rule stays reproducible.

Bundles are duck-typed: this module never imports lexicon_loader at import
time (it may legitimately not exist yet, and the metrics unit tests use a
minimal fake bundle).  Only the TYPE_CHECKING import below documents the
expected shape.
"""

from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable, Mapping, Sequence

import language_registry

if TYPE_CHECKING:  # pragma: no cover - typing only, never executed
    from lexicon_loader import LexiconBundle

TEXT_METRICS_VERSION = "1.6"  # 1.5: Chinese clause layer (issue #22): M-CLS-31/32 + sentence-length P90/P95

_LONG_SENTENCE_WORDS = 40
_MTLD_TTR_THRESHOLD = 0.720
_MTLD_MIN_FACTOR = 10
_ALPHA_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*")

#: metric_id order as frozen in INTERFACES.md section 3 (12 table rows; the
#: connector row expands into three component ids).
METRIC_IDS = (
    "M-SLEN-01",
    "M-LSF-16",
    "M-MTLD-02",
    "M-HED-14",
    "M-BOO-15",
    "M-CONN-30",
    "M-CONN-30c",
    "M-CONN-30k",
    "M-CONN-30r",
    # PDTB temporal/condition senses (issue #23): Chinese-only; the two
    # groups are loaded but never enter M-CONN-30 (which stays 30c+30k+30r).
    "M-CONN-30t",
    "M-CONN-30q",
    "M-AWR-03",
    "M-PAS-09",
    "M-NOM-10",
    "M-TENSE-28",
    # Clause layer (issue #22): Chinese only, see _METRIC_LANGUAGE_CAPABILITY.
    "M-CLS-31",
    "M-CLS-32",
    "M-SLEN-34",
    "M-SLEN-35",
    # Stance layer (issue #23): INFERRED, gated on a frozen annotation set with
    # kappa >= 0.6.  Until the calibration set lands the records are emitted as
    # null + NOT_IMPLEMENTED (never a fabricated number), mirroring
    # figure_profile's placeholders.
    "M-STNC-41",
    "M-STNC-42",
    "M-STNC-43",
    # Sentence-pattern layer (issue #23): deterministic punctuation/
    # structure statistics over split_clauses_zh output. No annotation
    # needed - the patterns are syntactic counts, not semantic labels.
    "M-SPAT-44",
    "M-SPAT-45",
    "M-SPAT-46",
)

#: A text is treated as Chinese (and therefore outside the validated language of
#: every OBSERVED metric here) when its CJK ratio exceeds this threshold.
#: Round A frozen contract: supported <=> cjk_ratio <= LANGUAGE_SUPPORT_CJK_THRESHOLD.
LANGUAGE_SUPPORT_CJK_THRESHOLD = 0.10

#: Languages this module's OBSERVED metrics are validated for.
SUPPORTED_LANGUAGES = ("en", "zh")

#: Per-metric language capability (issue #13). A metric is only emitted for a
#: language whose pinned rules are validated for it; every other (metric,
#: language) pair becomes a null "not measured" record carrying
#: CAPABILITY_NOT_SUPPORTED. English behaviour is unchanged; Chinese starts with
#: the two metrics that need no lexicon at all.
_METRIC_LANGUAGE_CAPABILITY: dict[str, tuple[str, ...]] = {
    "M-SLEN-01": ("en", "zh"),
    "M-LSF-16": ("en", "zh"),
    "M-MTLD-02": ("en", "zh"),
    "M-HED-14": ("en", "zh"),
    "M-BOO-15": ("en", "zh"),
    "M-CONN-30": ("en", "zh"),
    "M-CONN-30c": ("en", "zh"),
    "M-CONN-30k": ("en", "zh"),
    "M-CONN-30r": ("en", "zh"),
    # PDTB temporal/condition (issue #23): zh-only - the English v1 release
    # has no such groups, so en gets null + CAPABILITY_NOT_SUPPORTED.
    "M-CONN-30t": ("zh",),
    "M-CONN-30q": ("zh",),
    "M-AWR-03": ("en", "zh"),
    "M-PAS-09": ("en", "zh"),
    # M-NOM-10(zh): Chinese derives nouns from verbs by ZERO derivation
    # (优化 / 评估 / 分析 are already both), so the English "suffix + verb base"
    # rule has nothing to bite on. The stable, checkable signal in academic
    # Chinese is the abstract-noun suffix set; the metric records
    # variant="cjk-abstract-noun-suffix" so it can never be compared with the
    # English value by accident.
    "M-NOM-10": ("en", "zh"),
    # M-TENSE-28: Chinese has no tense at all - reporting a number would be a
    # fabricated measurement, so it stays unmeasurable for zh by design.
    # Clause layer (issue #22): the boundary rules are Chinese-specific, so the
    # metrics are validated for zh only.  English gets null +
    # CAPABILITY_NOT_SUPPORTED, never a fabricated value.
    "M-CLS-31": ("zh",),
    "M-CLS-32": ("zh",),
    "M-SLEN-34": ("zh",),
    "M-SLEN-35": ("zh",),
    # Stance (issue #23): INFERRED, validated for zh against the frozen
    # 220-sentence calibration set (kappa 0.7584 >= 0.6). English has no
    # calibrated set, so it keeps null + CAPABILITY_NOT_SUPPORTED.
    "M-STNC-41": ("zh",),
    "M-STNC-42": ("zh",),
    "M-STNC-43": ("zh",),
    # Sentence-pattern layer (issue #23): zh-only, computed from the Chinese
    # clause splitter; the English path has no clause layer to build on.
    "M-SPAT-44": ("zh",),
    "M-SPAT-45": ("zh",),
    "M-SPAT-46": ("zh",),
}
_DEFAULT_METRIC_LANGUAGES: tuple[str, ...] = ("en",)
#: Distinct from LANGUAGE_NOT_SUPPORTED: the language is measurable, this
#: particular metric is not (yet) validated for it. Both are "not measured".
CAPABILITY_NOT_SUPPORTED = "CAPABILITY_NOT_SUPPORTED"
#: Chinese sentence-length unit: CJK characters + ASCII alpha tokens, so a mixed
#: sentence ("采用 K-means 算法") is not under-counted.
_UNIT_CJK_UNITS_PER_SENTENCE = "cjk-units/sentence"
#: Connector density for Chinese: hits per 1000 cjk-units (the Chinese analogue
#: of "per-1000-words"; Chinese has no word boundaries).
_UNIT_PER_1000_CJK_UNITS = "per-1000-cjk-units"
#: Clause layer units (issue #22).  A Chinese clause is the text between two
#: comma/semicolon/colon boundaries inside one sentence.
_UNIT_CLAUSES_PER_SENTENCE = "clauses/sentence"
_UNIT_CJK_UNITS_PER_CLAUSE = "cjk-units/clause"
#: Clause separators for Chinese: ，；： plus their ASCII equivalents for mixed
#: text.  A separator inside brackets or quotes is not a boundary (see
#: _mask_brackets), and neither is one inside math or a keyword line.
_CLAUSE_SEPARATORS = "\uff0c\uff1b\uff1a,;:"
#: Bracket/quote pairs whose interior must not split a clause.
_BRACKET_PAIRS = {
    "\uff08": "\uff09", "(": ")",       # （ ）
    "\u3010": "\u3011",                 # 【 】
    "\u300c": "\u300d",                 # 「 」
    "\u300e": "\u300f",                 # 『 』
    "\u300a": "\u300b",                 # 《 》
    "\u201c": "\u201d",                 # “ ”
    "\u2018": "\u2019",                 # ‘ ’
}
#: Chinese token stream for M-MTLD-02: every CJK character and every ASCII word,
#: in document order. Character-level diversity is NOT comparable with the
#: English word-level value; the record says so via its tokenization field.
_TOKEN_STREAM_RE = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]|[A-Za-z][A-Za-z'\-]*")
#: Chinese passive markers. English marks the passive with aux + past participle;
#: Chinese uses a small closed set of function words. Only 被/受到/得到/加以/予以
#: are used: 由 and bare 为 are far too ambiguous in academic Chinese
#: ("由式(1)可得", "为便于讨论") to count as passive without a parser.
_CJK_PASSIVE_MARKERS: tuple[str, ...] = ("受到", "得到", "加以", "予以", "被")
#: How many characters after the marker are recorded as the passive phrase span.
_CJK_PASSIVE_SPAN_CHARS = 4
#: Abstract-noun suffixes for Chinese M-NOM-10 (variant cjk-abstract-noun-suffix).
#: 化 is deliberately excluded: it is entangled with verb forms that are not
#: nominalizations at all (优化 "optimise", 转化 "convert into", 深化 "deepen"),
#: and a metric that counts those would be measuring something else.
_CJK_ABSTRACT_NOUN_SUFFIXES = ("性", "度", "率")
#: A suffix only counts when at least this many CJK characters precede it inside
#: the same run. One is the right floor: two-character abstract nouns are the
#: norm in Chinese (效率 / 精度 / 温度 / 强度), while a bare suffix or one glued to
#: a Latin symbol ("$x$性") is not an abstract noun at all. The evidence window
#: carries the preceding characters, so a reviewer always sees the whole word.
_CJK_ABSTRACT_NOUN_MIN_PREFIX = 1
#: How many preceding characters are recorded as the evidence span.
_CJK_ABSTRACT_NOUN_WINDOW = 4
#: A Chinese academic sentence longer than this many units counts as "long"; the
#: English threshold (40 words) does not transfer (Chinese has no word spaces).
_LONG_SENTENCE_CJK_UNITS = 80

#: Warning code emitted on every metric when the input language is unsupported.
#: The value is null (never 0) so downstream aggregation counts it as missing.
LANGUAGE_NOT_SUPPORTED = "LANGUAGE_NOT_SUPPORTED"

#: CJK code-point ranges counted by detect_language: CJK Unified Ideographs
#: Extension A + the main block + CJK Compatibility Ideographs.
_CJK_RANGES = ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF))
_CJK_CHAR_RE = re.compile("[" + "".join(chr(lo) + "-" + chr(hi) for lo, hi in _CJK_RANGES) + "]")

_ROUND_DIGITS = 6
_STATE_OBSERVED = "OBSERVED"
_METHOD_RULE = "rule"
_EVIDENCE_SAMPLE_MAX = 5
_EXCERPT_MAX = 80
_UNIT_RATIO = "ratio"
_UNIT_PER_1000 = "per-1000-words"
_UNIT_WORDS_PER_SENTENCE = "words/sentence"
_UNIT_INDEX = "index"

#: unit of every metric id, used when a metric is suppressed (unsupported
#: language) so the contract field keeps its original value.
_METRIC_UNITS = {
    "M-SLEN-01": _UNIT_WORDS_PER_SENTENCE,
    "M-LSF-16": _UNIT_RATIO,
    "M-MTLD-02": _UNIT_INDEX,
    "M-HED-14": _UNIT_RATIO,
    "M-BOO-15": _UNIT_RATIO,
    "M-CONN-30": _UNIT_PER_1000,
    "M-CONN-30c": _UNIT_PER_1000,
    "M-CONN-30k": _UNIT_PER_1000,
    "M-CONN-30r": _UNIT_PER_1000,
    "M-CONN-30t": _UNIT_PER_1000,
    "M-CONN-30q": _UNIT_PER_1000,
    "M-AWR-03": _UNIT_RATIO,
    "M-PAS-09": _UNIT_RATIO,
    "M-NOM-10": _UNIT_RATIO,
    "M-TENSE-28": _UNIT_RATIO,
    # Stance layer (issue #23): INFERRED, sentence-level stance rates.
    "M-STNC-41": _UNIT_RATIO,
    "M-STNC-42": _UNIT_RATIO,
    "M-STNC-43": _UNIT_RATIO,
    # Sentence-pattern layer (issue #23): structural counts, OBSERVED.
    "M-SPAT-44": _UNIT_CLAUSES_PER_SENTENCE,
    "M-SPAT-45": _UNIT_RATIO,
    "M-SPAT-46": _UNIT_RATIO,
}

#: Frozen per-metric evidence sampling rules (see module docstring rule 5).
#: Injected into every metric dict as the top-level "evidence_rule" field.
_EVIDENCE_SUFFIX = "|order=document|sample=first_5|excerpt=text[start:end][:80]"
_EVIDENCE_RULES = {
    "M-SLEN-01": "unit=sentence_span|filter=all_sentences" + _EVIDENCE_SUFFIX,
    "M-LSF-16": "unit=sentence_span|filter=words>=40" + _EVIDENCE_SUFFIX,
    "M-MTLD-02": "unit=token_span|filter=all_alpha_tokens" + _EVIDENCE_SUFFIX,
    "M-HED-14": "unit=phrase_span|match=longest_nonoverlapping" + _EVIDENCE_SUFFIX,
    "M-BOO-15": "unit=phrase_span|match=longest_nonoverlapping" + _EVIDENCE_SUFFIX,
    "M-CONN-30": "unit=phrase_span|match=longest_nonoverlapping|union=all_three_groups" + _EVIDENCE_SUFFIX,
    "M-CONN-30c": "unit=phrase_span|match=longest_nonoverlapping" + _EVIDENCE_SUFFIX,
    "M-CONN-30k": "unit=phrase_span|match=longest_nonoverlapping" + _EVIDENCE_SUFFIX,
    "M-CONN-30r": "unit=phrase_span|match=longest_nonoverlapping" + _EVIDENCE_SUFFIX,
    "M-CONN-30t": "unit=phrase_span|match=longest_nonoverlapping|group=temporal" + _EVIDENCE_SUFFIX,
    "M-CONN-30q": "unit=phrase_span|match=longest_nonoverlapping|group=condition" + _EVIDENCE_SUFFIX,
    "M-AWR-03": "unit=phrase_span|match=longest_nonoverlapping" + _EVIDENCE_SUFFIX,
    "M-PAS-09": "unit=passive_phrase_span|filter=aux(+adverb<=2)+past_participle|lead=perfect_or_modal" + _EVIDENCE_SUFFIX,
    "M-NOM-10": "unit=token_span|filter=suffix_and_verb_base_and_not_denylisted" + _EVIDENCE_SUFFIX,
    "M-TENSE-28": "unit=token_span|filter=present_tense" + _EVIDENCE_SUFFIX,
    # Stance layer (issue #23): one stance per sentence; the evidence spans
    # are the sentences the classifier labelled, not the trigger phrases, so a
    # consumer can trace each labelled sentence back to the text.
    "M-STNC-41": "unit=sentence_span|filter=stance==hedging|rule=booster_minus_hedge_presence" + _EVIDENCE_SUFFIX,
    "M-STNC-42": "unit=sentence_span|filter=stance==boosting|rule=booster_minus_hedge_presence" + _EVIDENCE_SUFFIX,
    "M-STNC-43": "unit=sentence_span|filter=stance==assertive|rule=booster_minus_hedge_presence" + _EVIDENCE_SUFFIX,
    "M-SPAT-44": "unit=sentence_span|filter=all_sentences|count=clauses" + _EVIDENCE_SUFFIX,
    "M-SPAT-45": "unit=sentence_span|filter=multi_clause_sentences" + _EVIDENCE_SUFFIX,
    "M-SPAT-46": "unit=clause_span|filter=clauses_starting_with_a_connector" + _EVIDENCE_SUFFIX,
}
_EVIDENCE_RULE_DEFAULT = "unit=span" + _EVIDENCE_SUFFIX

#: Stance layer (issue #23) - INFERRED, calibrated on the frozen set
#: data/stance-calibration-zh.json. The rules are the *presence* of hedge vs
#: booster lexicon entries inside a sentence (not the count: a sentence has one
#: stance, so repeated triggers must not stack). Ties and no-trigger sentences
#: are assertive, which is the residual class by construction.
_STANCE_LABELS = ("assertive", "hedging", "boosting")
_STANCE_CALIBRATION = "data/stance-calibration-zh.json"
_STANCE_CALIBRATION_FACTS = {
    "annotator_agreement": {"metric": "cohens_kappa", "value": 0.7584,
                            "n_sentences": 220, "threshold": 0.6},
    "holdout_macro_f1": 0.5415,
    "holdout_accuracy": 0.7273,
    "holdout_per_label": {
        "assertive": {"precision": 0.9318, "recall": 0.7593, "f1": 0.8367},
        "hedging": {"precision": 0.2500, "recall": 0.5000, "f1": 0.3333},
        "boosting": {"precision": 0.3571, "recall": 0.6250, "f1": 0.4545},
    },
}

# ---------------------------------------------------------------------------
# Sentence splitting
# ---------------------------------------------------------------------------

_TERMINATORS = ".!?"

#: CJK sentence terminators. Kept separate from _TERMINATORS because their
#: boundary rule differs: Chinese prose puts no space after the terminator, so
#: the ASCII rule ("the stop must be followed by whitespace") would never fire.
#: The half-width stop is included (issue #22 follow-up): some CNKI journals
#: terminate Chinese sentences with "." instead of "。", and omitting it merges
#: every such pair of sentences and inflates sentence-length metrics.  It is
#: guarded below by _is_cjk_half_stop_end (digits and ASCII letters around it
#: keep the decimal / abbreviation reading), so an English paper that reaches
#: this branch is unaffected.
_CJK_TERMINATORS = "\u3002\uff01\uff1f\u2026."  # 。！？….
#: Closing punctuation that belongs to the sentence it terminates ("好。」").
_CJK_TRAILING_CLOSERS = "\u300d\u300f\u3011\u300b\uff09\uff3d\uff1e\u3009"  # 」』】》（）＞〉
#: A run of terminators ("……", "！！") ends one sentence at its last character;
#: stopping at the first would emit one-letter fragments.
_CJK_TERMINATOR_RUN_RE = re.compile("[%s]+" % _CJK_TERMINATORS)

# ---------------------------------------------------------------------------
# Pre-split normalisation (issue: 正文块内的关键词行与行内公式参与分句)
# ---------------------------------------------------------------------------
#: A keywords line is metadata: the marker and the rest of the line are blanked
#: (the newline is kept, so line structure survives for the abbreviation probe).
_KEYWORDS_LINE_RE = re.compile(
    r"^[ \t]*(?:keywords?|key[ \t]+words|关键词|关键字|主題詞|主题词)[ \t]*[:：][^\n]*",
    re.IGNORECASE | re.MULTILINE,
)
#: Display math ($$...$$) must be blanked before inline math ($...$).
_DISPLAY_MATH_RE = re.compile(r"\$\$[^$\n]*\$\$")
_INLINE_MATH_RE = re.compile(r"\$[^$\n]*\$")
#: MinerU sub/superscript wrappers; the characters they wrap are kept.
_SUB_SUP_TAG_RE = re.compile(r"</?(?:sub|sup)\b[^>]*>", re.IGNORECASE)
_MASK_PATTERNS = (
    _KEYWORDS_LINE_RE,
    _DISPLAY_MATH_RE,
    _INLINE_MATH_RE,
    _SUB_SUP_TAG_RE,
)


def _mask_non_prose(text: str) -> str:
    """Blank non-prose characters to spaces, keeping length and line breaks.

    The result locates sentence boundaries only; span text is always sliced back
    out of the original string (module docstring rule 7).
    """
    masked = text
    for pattern in _MASK_PATTERNS:
        masked = pattern.sub(lambda match: " " * (match.end() - match.start()), masked)
    return masked


_TRAILING_CLOSERS = frozenset("\"')]}\u00bb\u201d\u2019")
#: Horizontal whitespace only: a line break is a hard sentence-boundary
#: candidate and is never skipped while probing for an abbreviation continuation.
_HORIZONTAL_WS = " \t\f\v"
_LOCAL_WINDOW = 96

#: Abbreviations whose full stop never ends a sentence.  Compared lower-cased
#: against the token immediately left of the stop ("i.e." -> "i.e").
_ABBREVIATIONS = frozenset(
    """
    al etc fig figs eq eqs vs cf cmp approx no nos sec secs ref refs
    i.e e.g u.s u.k e.u ph.d m.s b.s dr prof mr mrs ms st jr sr
    inc ltd co corp dept univ vol vols pp p ch chap app appendix
    min max avg est resp ibid viz seq alii
    jan feb mar apr jun jul aug sep sept oct nov dec
    mon tue wed thu fri sat sun
    """.split()
)

_WORD_ENDING_RE = re.compile(r"[A-Za-z]+(?:\.[A-Za-z]+)*$")
#: Right-side initial rule: a single capital letter plus full stop is an initial
#: when the next token starts with a capital letter ("J. Smith", "R. Kumar",
#: "A. Smith", a line-leading "A. Method" and the "J. R." chain).  A following
#: digit, bracket or lowercase word does not protect, so "X. 25 runs",
#: "X. [12]" and "X. however" still split.
_INITIAL_FOLLOW_RE = re.compile(r"[ \t]+[A-Z](?:[A-Za-z]|\.)")
_LINE_NUMBER_RE = re.compile(r"\s*(?:\d{1,3}|\[\d{1,3}\]|\(\d{1,3}\))")


@dataclass(frozen=True)
class Span:
    """A character span relative to the text passed in (start, end, slice)."""

    start: int
    end: int
    text: str


@dataclass(frozen=True)
class ClauseSpan:
    """One clause: a comma/semicolon/colon-delimited unit inside a sentence.

    sentence_index ties the clause back to the sentence it came from, so clause
    counts and sentence counts can never disagree about the document's shape.

    function / rhetorical_role / confidence are the INFERRED layer and are null
    placeholders until a frozen annotation set with inter-annotator agreement
    exists (the same admission gate every INFERRED metric must pass, see the
    metric-definitions reference).  They are present in the record so a consumer
    can tell "not implemented yet" from "implemented and empty".
    """

    start: int
    end: int
    text: str
    sentence_index: int
    function: str | None = None
    rhetorical_role: str | None = None
    confidence: float | None = None


def _word_ending_at(text: str, index: int) -> str:
    """Alpha token (dotted words kept, e.g. i.e) ending at text[index]."""
    match = _WORD_ENDING_RE.search(text[max(0, index - _LOCAL_WINDOW):index])
    return match.group(0) if match else ""


def _is_line_start_numbering(text: str, index: int) -> bool:
    """True when the token just left of the stop is a line-leading numbering.

    Covers "1." / "[12]." / "(3)." at the start of a line (list numbering),
    which must not split a sentence.  Numbering appearing mid-line is a normal
    sentence end.
    """
    line_start = text.rfind("\n", max(0, index - _LOCAL_WINDOW), index)
    if line_start < 0:
        line_start = max(0, index - _LOCAL_WINDOW)
    else:
        line_start += 1
    return bool(_LINE_NUMBER_RE.fullmatch(text[line_start:index]))


def _single_letter_protected(text: str, index: int) -> bool:
    """Protect a single capital letter + full stop that starts an initial.

    Frozen right-side rule, independent of the word on the left: the stop is an
    initial when the next token starts with a capital letter, which covers
    "by J. Smith", "and R. Kumar", "A. Smith, B. Jones and C. Lee", a
    line-leading "A. Method" and the "J. R." chain.
    Known, accepted cost: a one-letter symbol that genuinely ends a sentence and
    is followed by a capitalised word ("denoted as X. We then ...") is not
    split.  Followers that are digits, brackets or lowercase words never
    protect, so "X. 25 runs", "X. [12]" and "X. however" still split.
    """
    return bool(_INITIAL_FOLLOW_RE.match(text[index + 1:index + 1 + 24]))


def _is_sentence_end(text: str, index: int) -> bool:
    length = len(text)
    char = text[index]
    cursor = index + 1
    while cursor < length and text[cursor] in _TRAILING_CLOSERS:
        cursor += 1
    if cursor < length and not text[cursor].isspace():
        return False
    if char != ".":
        return True
    # Decimal number "3.14": neither side of the stop splits.
    if index > 0 and text[index - 1].isdigit() and index + 1 < length and text[index + 1].isdigit():
        return False
    if _is_line_start_numbering(text, index):
        return False
    token = _word_ending_at(text, index)
    if token.lower() in _ABBREVIATIONS:
        return False
    if len(token) == 1 and token.isupper() and _single_letter_protected(text, index):
        return False
    # Unknown-abbreviation heuristic ("Smith et al. reported", "Sect. 3").
    # The probe must NOT cross a line break and must stop at the first
    # non-space character (digits, brackets, math symbols): scientific prose
    # frequently starts a sentence with a number, "[12]" or a formula, and
    # probing past it would silently merge two sentences and deflate every
    # sentence-count denominator (M-SLEN-01 / M-LSF-16 / M-PAS-09).
    probe = cursor
    while probe < length and text[probe] in _HORIZONTAL_WS:
        probe += 1
    if probe < length and text[probe].isalpha() and text[probe].islower():
        return False
    return True


def _is_cjk_half_stop_end(text: str, index: int) -> bool:
    """A half-width "." in CJK mode ends a sentence only when it is not part of
    a number, a citation-style run or an ASCII abbreviation.

    Rejected as boundaries: "3.14", "v1.2", "[12].5", "U.S." and the like.  The
    rule is deliberately conservative - a true sentence stop in Chinese prose is
    preceded by a CJK character or a closing bracket and followed by whitespace
    or a CJK character.
    """
    prev = text[index - 1] if index > 0 else ""
    nxt = text[index + 1] if index + 1 < len(text) else ""
    if prev.isdigit() or nxt.isdigit():
        return False
    if prev.isascii() and prev.isalpha():
        return False  # "U.S." / "et al." - ASCII abbreviation
    if nxt.isascii() and nxt.isalpha() and not nxt.isspace():
        return False
    return True


def _is_cjk_sentence_end(text: str, index: int) -> bool:
    """True when a CJK terminator at `index` ends a sentence.

    A terminator inside a run ("……" / "！！") is not a boundary: only the last
    character of the run is, otherwise the run would be split into fragments.
    """
    nxt = text[index + 1] if index + 1 < len(text) else ""
    if nxt in _CJK_TERMINATORS:
        return False
    if text[index] == "." and not _is_cjk_half_stop_end(text, index):
        return False
    return True


def _cjk_trailing_closer_run(text: str, start: int) -> int:
    """Length of the closing-punctuation run at `start` (kept inside the span)."""
    end = start
    while end < len(text) and text[end] in _CJK_TRAILING_CLOSERS:
        end += 1
    return end - start


def split_sentences(text: str) -> list[Span]:
    """Split the text into sentence spans (rule-based, deterministic).

    A sentence ends at . / ! / ? followed by whitespace or the end of the text.
    A line break is a hard boundary candidate: the abbreviation probe never
    crosses it, so a following sentence that starts with a number, "[12]" or a
    formula is still split correctly.  Abbreviations, decimals, line-leading
    numbering and initials chains are protected (see the module docstring).
    Fragments without a single letter are dropped.  Span.text is always
    text[span.start:span.end] and never has leading or trailing whitespace.

    Boundaries are located on a blanked copy of the text (module docstring rule
    7): keywords lines, inline/display math and <sub>/<sup> markup are not prose
    and can neither end a sentence nor become one.  Span text is always sliced
    back out of the *original* string, so evidence still quotes the source.
    """
    if not isinstance(text, str) or not text:
        return []
    masked = _mask_non_prose(text)
    raw: list[tuple[int, int]] = []
    start = 0
    length = len(text)
    for index in range(length):
        char = masked[index]
        if char in _TERMINATORS and _is_sentence_end(masked, index):
            raw.append((start, index + 1))
            start = index + 1
        elif char in _CJK_TERMINATORS and _is_cjk_sentence_end(masked, index):
            # keep a trailing closing quote/bracket inside the sentence
            end = index + 1 + _cjk_trailing_closer_run(masked, index + 1)
            raw.append((start, end))
            start = end
    raw.append((start, length))

    spans: list[Span] = []
    for begin, end in raw:
        chunk = masked[begin:end]
        stripped = chunk.strip()
        if not stripped:
            continue
        lead = len(chunk) - len(chunk.lstrip())
        tail = len(chunk) - len(chunk.rstrip())
        s = begin + lead
        e = end - tail
        piece = text[s:e]
        if (_ALPHA_TOKEN_RE.search(masked[s:e]) is None
                and _CJK_CHAR_RE.search(masked[s:e]) is None):
            # letter-less AND CJK-less fragment ("3.", "---", "[]"), a keywords
            # line, or a bare inline formula: none of them are prose sentences.
            # CJK characters must be accepted, otherwise every Chinese sentence
            # is silently dropped instead of measured.
            continue
        spans.append(Span(s, e, piece))
    return spans


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------

def _mask_brackets(text: str) -> str:
    """Replace the interior of every bracket/quote pair with spaces.

    A clause separator inside a bracket or quote pair must not end a clause:
    Chinese uses bracketed commas for enumeration and inline comment, and
    splitting there would shred every list into pseudo-clauses.  Unclosed openers
    are left alone rather than blanking to end-of-text (a stray opener in a title
    should not nuke the rest of the document).
    """
    if not text:
        return text
    characters = list(text)
    closers = {closer: opener for opener, closer in _BRACKET_PAIRS.items()}
    stack: list[list] = []  # [opener_char, opener_index]
    for index, char in enumerate(characters):
        if char in _BRACKET_PAIRS:
            stack.append([char, index])
            continue
        opener = closers.get(char)
        if opener is None:
            continue
        for position in range(len(stack) - 1, -1, -1):
            if stack[position][0] == opener:
                start = stack[position][1]
                for offset in range(start, index + 1):
                    characters[offset] = " "
                del stack[position:]
                break
    return "".join(characters)


def _has_letter_or_cjk(fragment: str) -> bool:
    """A fragment worth keeping as a clause: it carries letters or CJK characters."""
    return (_ALPHA_TOKEN_RE.search(fragment) is not None
            or _CJK_CHAR_RE.search(fragment) is not None)


def split_sentences_zh(text: str) -> list[Span]:
    """Chinese sentence spans.

    split_sentences already handles CJK terminators (。！？…), trailing closers and
    non-prose masking language-agnostically - the Chinese metric path runs through
    it today.  This name exists so the Chinese adapter and the clause layer say
    what they mean.  If Chinese rules ever need to diverge from English (for
    instance not treating an ASCII full stop inside Chinese prose as a boundary),
    the divergence lives here and the frozen English path is untouched.
    """
    return split_sentences(text)


def split_clauses_zh(text: str) -> list[ClauseSpan]:
    """Split every sentence into clauses at ，；： boundaries.

    Deterministic: the mask is rebuilt from the same text, separators are a
    closed set, and spans slice back out of the original.  Clause evidence can
    therefore be re-opened and re-checked by hand, like every other span here.
    """
    sentences = split_sentences_zh(text)
    if not sentences:
        return []
    masked = _mask_brackets(_mask_non_prose(text))
    clauses: list[ClauseSpan] = []
    for sentence_index, sentence in enumerate(sentences):
        region = masked[sentence.start:sentence.end]
        previous = 0
        for position, char in enumerate(region):
            if char not in _CLAUSE_SEPARATORS:
                continue
            if _has_letter_or_cjk(region[previous:position]):
                start = sentence.start + previous
                end = sentence.start + position + 1  # keep the separator
                clauses.append(ClauseSpan(start, end, text[start:end],
                                          sentence_index))
            previous = position + 1
        if _has_letter_or_cjk(region[previous:]):
            start = sentence.start + previous
            clauses.append(ClauseSpan(start, sentence.end, text[start:sentence.end],
                                      sentence_index))
    return clauses


def tokenize_zh(text: str) -> list[Span]:
    """Chinese word segmentation (jieba, precise mode with HMM).

    jieba's default mode is deterministic: no randomness, no learned state
    between calls, dictionary loaded once per process.  Spans, not bare strings,
    so evidence can point into the source text like every other span in this
    module.  Used only by the clause layer; the 14 frozen OBSERVED metrics stay
    character/unit based and byte-identical.
    """
    import jieba

    if not isinstance(text, str) or not text:
        return []
    return [Span(start, end, word)
            for word, start, end in jieba.tokenize(text) if word.strip()]


def tokenize(text: str) -> list[str]:
    """Lower-cased alpha tokens, keeping internal apostrophes and hyphens."""
    if not isinstance(text, str) or not text:
        return []
    return [match.group(0).lower() for match in _ALPHA_TOKEN_RE.finditer(text)]


def _tokens_with_spans(text: str, start: int = 0, end: int | None = None) -> list[tuple[str, int, int]]:
    segment = text[start:end]
    return [
        (match.group(0).lower(), start + match.start(), start + match.end())
        for match in _ALPHA_TOKEN_RE.finditer(segment)
    ]


# ---------------------------------------------------------------------------
# MTLD (McCarthy & Jarvis 2010)
# ---------------------------------------------------------------------------

def _mtld_direction(tokens: Sequence[str]) -> float:
    factors = 0.0
    seen: set[str] = set()
    count = 0
    threshold = _MTLD_TTR_THRESHOLD
    for token in tokens:
        seen.add(token)
        count += 1
        if len(seen) / count <= threshold:
            factors += 1.0
            seen = set()
            count = 0
    if count:
        ttr = len(seen) / count
        if ttr > threshold:
            factors += (1.0 - ttr) / (1.0 - threshold)
    if factors <= 0.0:
        return float("nan")
    return len(tokens) / factors


def mtld(tokens: Sequence[str]) -> float:
    """Bidirectional MTLD over the token sequence.

    Returns nan when len(tokens) < 2 * _MTLD_MIN_FACTOR (fewer than two stable
    factors, so the index is not defined).  Pinned parameters: ttr_threshold =
    0.720, min_factor = 10, bidirectional = True, trailing partial factor =
    (1 - TTR) / (1 - threshold).
    """
    normalised = [str(token).lower() for token in tokens if str(token).strip()]
    if len(normalised) < 2 * _MTLD_MIN_FACTOR:
        return float("nan")
    forward = _mtld_direction(normalised)
    backward = _mtld_direction(list(reversed(normalised)))
    if math.isnan(forward) or math.isnan(backward):
        return float("nan")
    return (forward + backward) / 2.0

# ---------------------------------------------------------------------------
# Frozen lexical tables (embedded: no import-time dependency on lexicon data)
# ---------------------------------------------------------------------------

#: base -> (simple past, past participle).  137 entries; >= 80 present forms
#: and >= 80 past forms, as required by INTERFACES.md section 3.  The simple
#: past column doubles as the past-tense lookup of M-TENSE-28 and the past
#: participle column as the passive lookup of M-PAS-09.
_IRREGULAR_VERBS: dict[str, tuple[str, str]] = {
    "arise": ("arose", "arisen"),
    "awake": ("awoke", "awoken"),
    "be": ("was", "been"),
    "bear": ("bore", "borne"),
    "beat": ("beat", "beaten"),
    "become": ("became", "become"),
    "begin": ("began", "begun"),
    "bend": ("bent", "bent"),
    "bet": ("bet", "bet"),
    "bind": ("bound", "bound"),
    "bite": ("bit", "bitten"),
    "bleed": ("bled", "bled"),
    "blow": ("blew", "blown"),
    "break": ("broke", "broken"),
    "breed": ("bred", "bred"),
    "bring": ("brought", "brought"),
    "build": ("built", "built"),
    "buy": ("bought", "bought"),
    "cast": ("cast", "cast"),
    "catch": ("caught", "caught"),
    "choose": ("chose", "chosen"),
    "cling": ("clung", "clung"),
    "come": ("came", "come"),
    "cost": ("cost", "cost"),
    "creep": ("crept", "crept"),
    "cut": ("cut", "cut"),
    "deal": ("dealt", "dealt"),
    "dig": ("dug", "dug"),
    "dive": ("dove", "dived"),
    "do": ("did", "done"),
    "draw": ("drew", "drawn"),
    "dream": ("dreamt", "dreamt"),
    "drink": ("drank", "drunk"),
    "drive": ("drove", "driven"),
    "eat": ("ate", "eaten"),
    "fall": ("fell", "fallen"),
    "feed": ("fed", "fed"),
    "feel": ("felt", "felt"),
    "fight": ("fought", "fought"),
    "find": ("found", "found"),
    "fit": ("fit", "fit"),
    "flee": ("fled", "fled"),
    "fling": ("flung", "flung"),
    "fly": ("flew", "flown"),
    "forbid": ("forbade", "forbidden"),
    "forget": ("forgot", "forgotten"),
    "forgive": ("forgave", "forgiven"),
    "freeze": ("froze", "frozen"),
    "get": ("got", "gotten"),
    "give": ("gave", "given"),
    "go": ("went", "gone"),
    "grow": ("grew", "grown"),
    "hang": ("hung", "hung"),
    "have": ("had", "had"),
    "hear": ("heard", "heard"),
    "hide": ("hid", "hidden"),
    "hit": ("hit", "hit"),
    "hold": ("held", "held"),
    "hurt": ("hurt", "hurt"),
    "keep": ("kept", "kept"),
    "know": ("knew", "known"),
    "lay": ("laid", "laid"),
    "lead": ("led", "led"),
    "leave": ("left", "left"),
    "lend": ("lent", "lent"),
    "let": ("let", "let"),
    "lie": ("lay", "lain"),
    "light": ("lit", "lit"),
    "lose": ("lost", "lost"),
    "make": ("made", "made"),
    "mean": ("meant", "meant"),
    "meet": ("met", "met"),
    "mistake": ("mistook", "mistaken"),
    "overcome": ("overcame", "overcome"),
    "pay": ("paid", "paid"),
    "prove": ("proved", "proven"),
    "put": ("put", "put"),
    "quit": ("quit", "quit"),
    "read": ("read", "read"),
    "ride": ("rode", "ridden"),
    "ring": ("rang", "rung"),
    "rise": ("rose", "risen"),
    "run": ("ran", "run"),
    "say": ("said", "said"),
    "see": ("saw", "seen"),
    "seek": ("sought", "sought"),
    "sell": ("sold", "sold"),
    "send": ("sent", "sent"),
    "set": ("set", "set"),
    "shake": ("shook", "shaken"),
    "shed": ("shed", "shed"),
    "shine": ("shone", "shone"),
    "shoot": ("shot", "shot"),
    "show": ("showed", "shown"),
    "shrink": ("shrank", "shrunk"),
    "shut": ("shut", "shut"),
    "sing": ("sang", "sung"),
    "sink": ("sank", "sunk"),
    "sit": ("sat", "sat"),
    "sleep": ("slept", "slept"),
    "slide": ("slid", "slid"),
    "speak": ("spoke", "spoken"),
    "speed": ("sped", "sped"),
    "spend": ("spent", "spent"),
    "spin": ("spun", "spun"),
    "spit": ("spat", "spat"),
    "split": ("split", "split"),
    "spread": ("spread", "spread"),
    "spring": ("sprang", "sprung"),
    "stand": ("stood", "stood"),
    "steal": ("stole", "stolen"),
    "stick": ("stuck", "stuck"),
    "sting": ("stung", "stung"),
    "strike": ("struck", "struck"),
    "strive": ("strove", "striven"),
    "swear": ("swore", "sworn"),
    "sweep": ("swept", "swept"),
    "swim": ("swam", "swum"),
    "swing": ("swung", "swung"),
    "take": ("took", "taken"),
    "teach": ("taught", "taught"),
    "tear": ("tore", "torn"),
    "tell": ("told", "told"),
    "think": ("thought", "thought"),
    "throw": ("threw", "thrown"),
    "tread": ("trod", "trodden"),
    "understand": ("understood", "understood"),
    "undertake": ("undertook", "undertaken"),
    "upset": ("upset", "upset"),
    "wake": ("woke", "woken"),
    "wear": ("wore", "worn"),
    "weep": ("wept", "wept"),
    "win": ("won", "won"),
    "wind": ("wound", "wound"),
    "withdraw": ("withdrew", "withdrawn"),
    "withstand": ("withstood", "withstood"),
    "write": ("wrote", "written"),
}

_IRREGULAR_PAST = frozenset(past for past, _ in _IRREGULAR_VERBS.values()) | {"were"}
_IRREGULAR_PARTICIPLE = frozenset(participle for _, participle in _IRREGULAR_VERBS.values())
_IRREGULAR_PRESENT = frozenset(_IRREGULAR_VERBS)

_PASSIVE_AUXILIARIES = frozenset(
    {"be", "am", "is", "are", "was", "were", "been", "being",
     "get", "gets", "got", "gotten", "become", "becomes", "became"}
)

_PASSIVE_ADVERBS = frozenset(
    """
    not never also often already widely commonly frequently generally usually
    typically currently recently then further finally only still just well
    fully partially directly indirectly explicitly implicitly successfully
    effectively automatically manually carefully quickly gradually subsequently
    previously systematically empirically theoretically statistically
    significantly substantially largely mainly primarily closely highly deeply
    rapidly slowly exactly precisely almost nearly always sometimes rarely
    merely simply thus hence therefore first second now soon later easily
    routinely safely reliably consistently correctly jointly simultaneously
    """.split()
)

#: Tokens that may directly precede the passive auxiliary and belong to the same
#: verb phrase: perfect auxiliaries ("has been adopted") and modals
#: ("can be mapped").  They are included in the M-PAS-09 evidence span only;
#: they never trigger a passive by themselves (detection is unchanged).
_PASSIVE_PHRASE_LEAD = frozenset(
    {"have", "has", "had", "can", "could", "may", "might", "must", "shall",
     "should", "will", "would"}
)

_PRESENT_AUXILIARIES = frozenset({"is", "are", "am", "do", "does", "has", "have"})
_PAST_AUXILIARIES = frozenset({"was", "were", "did", "had"})
_MODALS = frozenset({"can", "could", "may", "might", "must", "shall", "should",
                     "will", "would", "cannot", "ought"})
_TENSELESS_BE = frozenset({"be", "been", "being"})

#: Participial adjectives that look like -ed verbs.  Frozen denylist: they are
#: not counted as past-tense verbs (documented precision/recall trade-off).
_ED_ADJECTIVE_DENYLIST = frozenset(
    """
    related limited based detailed advanced complicated sophisticated dedicated
    biased aforementioned unbiased nested left right oriented sized
    """.split()
)

#: Adjectival past participles for M-PAS-09 (B2 fix): "the problem is
#: complicated" / "we were tired" are copular (主系表), not passive.  Kept
#: deliberately narrow ("宁缺毋滥"): high-frequency dynamic participles that
#: carry genuine agentless passives in this corpus (used 161, defined 89,
#: applied 58, based-like constructions notwithstanding) and irregular past
#: forms with a genuine passive reading (known, left, given, made) are NOT
#: denied.  Measured on the 34-paper VRP corpus: the copula + -ed collocations
#: are dominated by real passives, so denying this adjective set removes false
#: positives without erasing the construction.
_PARTICIPIAL_ADJECTIVE_DENYLIST = frozenset(
    """
    related limited based detailed advanced complicated sophisticated dedicated
    biased unbiased aforementioned nested oriented sized
    tired interested excited involved concerned satisfied surprised pleased
    worried committed equipped skilled crowded damaged unexpected
    """.split()
)

#: Verb bases frozen in this module.  Used to gate third-person -s forms of
#: M-TENSE-28 (the bundle's nominalization verb bases are unioned in at call
#: time).  Alphabetical, no duplicates.
_COMMON_VERB_BASES = tuple(
    """
    accept access accommodate account achieve acquire adapt add address adjust
    administer adopt advance affect afford aim align allow alter analyse analyze
    annotate anticipate appear apply appoint appreciate approach approximate
    argue arise arrange articulate assess assign assist associate assure
    attain attempt attend attract attribute augment automate avoid balance base
    become believe benefit build calculate capture carry categorize cause
    challenge change characterize choose cite clarify classify cluster collect
    combine compare compensate compete compile complement complete compose
    compute conceive concentrate conclude conduct configure confirm conflict
    confuse connect consider consist constitute constrain construct consume
    contain continue contract contrast contribute control convert convey
    convince coordinate correlate correspond cover create critique decide
    decompose decrease define degrade delay deliver demonstrate denote depend
    derive describe design detect determine develop deviate devise differentiate
    discover discuss distinguish distribute diverge divide document dominate
    double draw drive drop ease elaborate eliminate embed emphasize employ
    enable encode encounter encourage enhance ensure entail establish estimate
    evaluate evolve examine exceed exclude execute exemplify exhibit exist
    expand expect experiment explain explore expose express extend extract
    facilitate fail favor feature figure fit focus forecast formulate frame
    fulfill function gain gather generalize generate govern grant group grow
    guarantee guide handle highlight identify illustrate implement imply import
    impose improve include incorporate increase incur indicate induce infer
    influence inform initialize inject innovate insert inspect install
    instantiate integrate interpret introduce investigate involve isolate issue
    iterate justify keep label lack launch learn leave lend leverage limit link
    list locate maintain manage manipulate map mark match maximize measure meet
    merge minimize mirror mitigate model modify monitor motivate move multiply
    narrow neglect normalise normalize note obtain occur offer operate optimize
    order organize outline overcome overlap overlook outweigh parallel
    parameterize participate partition pass perform permit persist place plan
    point populate possess postulate predict prefer prepare present preserve
    prevent prioritize process produce prohibit project promote propose prove
    provide publish quantify query rank reach realize reason recall recognize
    recommend reconstruct record recover reduce refine reflect regard regulate
    reinforce reject relate relax release rely remain remove render repeat
    replace replicate report represent reproduce request require research
    resolve respect respond restrict result retain retrieve reveal reverse
    review revise reward run sample satisfy scale schedule score search secure
    seek select separate sequence serve set settle shape share shift show signal
    simplify simulate solve specify split spread stabilize standardize state
    stimulate store streamline strengthen stress strive structure study submit
    substitute succeed suffer suggest suit summarize supervise supply support
    suppose suppress surpass survey sustain switch symbolize tackle tailor
    target teach terminate test theorize think tolerate trace track trade train
    transfer transform translate treat trigger tune turn underestimate underlie
    understand undertake unify unite update upgrade use utilize validate vary
    verify view violate visualize weight widen yield
    """.split()
)

#: Noun/verb homographs excluded from the third-person -s gate: their plural
#: form dominates in academic prose ("models", "results"), so counting them as
#: present-tense verbs would inflate the metric.
_AMBIGUOUS_NOUN_VERBS = frozenset(
    """
    model result process design project report survey study review test sample
    feature function control measure mean approach method change increase
    decrease use limit target level balance focus score rate scale state
    structure order schedule contrast record request access address account
    support influence impact group form figure map link point mark object
    """.split()
)

_THIRD_PERSON_SPECIAL = {"be": "is", "do": "does", "have": "has", "go": "goes"}


def _third_person(base: str) -> str | None:
    if base in _THIRD_PERSON_SPECIAL:
        return _THIRD_PERSON_SPECIAL[base]
    if not base or not base.isalpha():
        return None
    if base.endswith(("s", "x", "z", "ch", "sh")):
        return base + "es"
    if base.endswith("y") and len(base) > 1 and base[-2] not in "aeiou":
        return base[:-1] + "ies"
    return base + "s"


def _build_third_person_index(extra_bases: Iterable[str]) -> dict[str, str]:
    bases = set(_COMMON_VERB_BASES)
    bases.update(_IRREGULAR_VERBS)
    for base in extra_bases:
        base = str(base).strip().lower()
        if base:
            bases.add(base)
    index: dict[str, str] = {}
    for base in sorted(bases):
        form = _third_person(base)
        if form:
            index[form] = base
    return index


# ---------------------------------------------------------------------------
# Bundle access (duck-typed)
# ---------------------------------------------------------------------------

def _entries(bundle: Any, name: str) -> tuple[str, ...]:
    lexicon = getattr(bundle, name, None)
    if lexicon is None:
        return ()
    raw = getattr(lexicon, "entries", None)
    if raw is None:
        return ()
    return tuple(str(entry) for entry in raw)


def _connector_entries(bundle: Any, group: str) -> tuple[str, ...]:
    connectors = getattr(bundle, "connectors", None)
    if connectors is None:
        return ()
    lexicon: Any = None
    if isinstance(connectors, Mapping):
        lexicon = connectors.get(group)
    if lexicon is None:
        try:
            lexicon = connectors[group]
        except Exception:  # pragma: no cover - exotic mapping
            lexicon = getattr(connectors, group, None)
    if lexicon is None:
        return ()
    raw = getattr(lexicon, "entries", None)
    if raw is None:
        return ()
    return tuple(str(entry) for entry in raw)


# ---------------------------------------------------------------------------
# Contract-carrying records
# ---------------------------------------------------------------------------

def _excerpt(text: str, start: int, end: int) -> str:
    return text[start:end][:_EXCERPT_MAX]


def _evidence(spans: Sequence[Sequence[int]], text: str, count: int,
              limit: int = _EVIDENCE_SAMPLE_MAX) -> dict[str, Any]:
    """Build the evidence block from (start, end[, ...]) records.

    Accepts both 2-tuples (sentence / token spans) and the 3-tuples returned by
    _match_entries ((start, end, sentence_index)); only the first two fields are
    used, the rest is ignored.
    """
    sample = [
        {"span": [int(hit[0]), int(hit[1])], "excerpt": _excerpt(text, int(hit[0]), int(hit[1]))}
        for hit in list(spans)[:limit]
    ]
    return {"count": int(count), "sample": sample}


def _metric(metric_spec: str, *, value: Any, n: int, denominator: int, unit: str,
            evidence: dict[str, Any], warnings: Sequence[str] = (),
            **extra: Any) -> dict[str, Any]:
    note = [str(w) for w in warnings]
    normalised: float | None
    if value is None:
        normalised = None
    else:
        number = float(value)
        if not math.isfinite(number):
            normalised = None
            note.append("value was not finite (NaN/Infinity) and is reported as null")
        else:
            normalised = round(number, _ROUND_DIGITS)
    record: dict[str, Any] = {
        "value": normalised,
        "n": int(n),
        "denominator": int(denominator),
        "unit": unit,
        "state": _STATE_OBSERVED,
        "method": _METHOD_RULE,
        "metric_spec": metric_spec,
        "evidence": evidence,
        "warnings": note,
    }
    record.update(extra)
    record.setdefault("evidence_rule", _EVIDENCE_RULES.get(metric_spec, _EVIDENCE_RULE_DEFAULT))
    return record


def _rate(metric_spec: str, numerator: int, denominator: int, unit: str,
          evidence: dict[str, Any], warnings: Sequence[str] = (),
          scale: float = 1.0, **extra: Any) -> dict[str, Any]:
    note = list(warnings)
    if denominator <= 0:
        note.append(
            f"{metric_spec}: denominator is 0 (no alpha token in the input); value is undefined"
        )
        return _metric(metric_spec, value=None, n=numerator, denominator=denominator,
                       unit=unit, evidence=evidence, warnings=note, **extra)
    return _metric(metric_spec, value=numerator * scale / denominator, n=numerator,
                   denominator=denominator, unit=unit, evidence=evidence,
                   warnings=note, **extra)

# ---------------------------------------------------------------------------
# Phrase matching (longest first, non-overlapping, per sentence)
# ---------------------------------------------------------------------------

def _phrase_index(entries: Iterable[str]) -> dict[int, set[tuple[str, ...]]]:
    index: dict[int, set[tuple[str, ...]]] = {}
    for entry in entries:
        tokens = tuple(tokenize(str(entry)))
        if not tokens:
            continue
        index.setdefault(len(tokens), set()).add(tokens)
    return index


def _match_entries(text: str, sentences: Sequence[Span],
                   entries: Iterable[str]) -> list[tuple[int, int, int]]:
    """Return (start, end, sentence_index) hits, in document order."""
    index = _phrase_index(entries)
    if not index:
        return []
    max_len = max(index)
    hits: list[tuple[int, int, int]] = []
    for sentence_index, span in enumerate(sentences):
        tokens = _tokens_with_spans(text, span.start, span.end)
        words = [token for token, _, _ in tokens]
        position = 0
        total = len(words)
        while position < total:
            matched = 0
            for length in range(min(max_len, total - position), 0, -1):
                group = index.get(length)
                if group is not None and tuple(words[position:position + length]) in group:
                    matched = length
                    hits.append((tokens[position][1], tokens[position + length - 1][2],
                                 sentence_index))
                    break
            position += matched if matched else 1
    return hits


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------

def _percentile(ordered: Sequence[int], quantile: float) -> float:
    """Linear-interpolation percentile (identical to numpy's default)."""
    length = len(ordered)
    if length == 0:
        return float("nan")
    if length == 1:
        return float(ordered[0])
    position = quantile * (length - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return float(ordered[lower])
    fraction = position - lower
    return float(ordered[lower]) * (1.0 - fraction) + float(ordered[upper]) * fraction


# ---------------------------------------------------------------------------
# Individual metrics
# ---------------------------------------------------------------------------

def _metric_slen01(text: str, sentences: Sequence[Span],
                   counts: Sequence[int], *,
                   unit: str = _UNIT_WORDS_PER_SENTENCE) -> dict[str, Any]:
    n_sentences = len(sentences)
    n_words = sum(counts)
    warnings: list[str] = []
    if n_sentences == 0:
        warnings.append("M-SLEN-01: no sentence containing a letter was detected; value is undefined")
        value = None
        distribution = {"median": None, "p25": None, "p75": None, "std": None}
    elif n_words == 0:
        warnings.append("M-SLEN-01: no alpha token was detected; value is undefined")
        value = None
        distribution = {"median": None, "p25": None, "p75": None, "std": None}
    else:
        ordered = sorted(counts)
        value = n_words / n_sentences
        distribution = {
            "median": round(_percentile(ordered, 0.5), _ROUND_DIGITS),
            "p25": round(_percentile(ordered, 0.25), _ROUND_DIGITS),
            "p75": round(_percentile(ordered, 0.75), _ROUND_DIGITS),
            "std": round(statistics.pstdev(ordered), _ROUND_DIGITS),
        }
    evidence = _evidence([(span.start, span.end) for span in sentences], text, n_sentences)
    return _metric("M-SLEN-01", value=value, n=n_sentences, denominator=n_words,
                   unit=unit, evidence=evidence, warnings=warnings,
                   distribution=distribution)


def _metric_lsf16(text: str, sentences: Sequence[Span],
                  counts: Sequence[int], *,
                  threshold: int = _LONG_SENTENCE_WORDS) -> dict[str, Any]:
    n_sentences = len(sentences)
    long_spans = [
        (span.start, span.end)
        for span, count in zip(sentences, counts)
        if count >= threshold
    ]
    warnings: list[str] = []
    if n_sentences == 0:
        warnings.append("M-LSF-16: no sentence containing a letter was detected; value is undefined")
        value = None
    else:
        value = len(long_spans) / n_sentences
    evidence = _evidence(long_spans, text, len(long_spans))
    return _metric("M-LSF-16", value=value, n=len(long_spans), denominator=n_sentences,
                   unit=_UNIT_RATIO, evidence=evidence, warnings=warnings,
                   long_sentence_threshold=threshold)


def _mtld_params(tokenization: str) -> dict[str, Any]:
    """Frozen MTLD parameters, plus the token stream when it is not the default.

    English keeps exactly the historical parameter set (byte-identical products);
    a non-default stream (Chinese counts CJK characters + ASCII words) is
    recorded because the two values are different statistics and must never be
    compared by accident.
    """
    params: dict[str, Any] = {
        "ttr_threshold": _MTLD_TTR_THRESHOLD,
        "min_factor": _MTLD_MIN_FACTOR,
        "bidirectional": True,
        "partial_factor": "(1 - ttr) / (1 - ttr_threshold)",
    }
    if tokenization != "ascii-alpha-token":
        params["tokenization"] = tokenization
    return params


def _metric_mtld02(text: str, tokens: Sequence[str],
                   token_spans: Sequence[tuple[int, int]],
                   *, tokenization: str = "ascii-alpha-token") -> dict[str, Any]:
    value = mtld(tokens)
    warnings: list[str] = []
    if math.isnan(value):
        warnings.append(
            "M-MTLD-02: token count %d < 2 * _MTLD_MIN_FACTOR (%d); MTLD is undefined"
            % (len(tokens), 2 * _MTLD_MIN_FACTOR)
        )
        value = None
    evidence = _evidence(token_spans, text, len(tokens))
    return _metric(
        "M-MTLD-02", value=value, n=len(tokens), denominator=1, unit=_UNIT_INDEX,
        evidence=evidence, warnings=warnings,
        params=_mtld_params(tokenization),
    )


def _is_past_participle(token: str) -> bool:
    """True for a past participle usable in a passive reading.

    Adjectival participles (see _PARTICIPIAL_ADJECTIVE_DENYLIST) are rejected
    first, so "is complicated" / "were tired" stay copular; irregular forms with
    a genuine passive reading ("was built", "is known", "was given") are kept.
    """
    if token in _PARTICIPIAL_ADJECTIVE_DENYLIST:
        return False
    if token in _IRREGULAR_PARTICIPLE:
        return True
    return len(token) >= 4 and token.endswith("ed")


@dataclass(frozen=True)
class PassiveHit:
    """One detected passive verb phrase (the M-PAS-09 evidence unit).

    sentence   -- the enclosing sentence span (denominator scope)
    phrase_*   -- char offsets of the passive verb phrase: optional
                  perfect/modal lead + auxiliary (+ up to two adverbs) +
                  past participle, e.g. "has been adopted", "can be mapped",
                  "were carefully collected"
    participle -- the past participle token that triggered the match
    """

    sentence: Span
    phrase_start: int
    phrase_end: int
    phrase: str
    participle: str


def _detect_passive(text: str, sentences: Sequence[Span]) -> tuple[list[PassiveHit], int]:
    """Return one PassiveHit per passive sentence (first phrase wins) and the
    number of auxiliaries that did not resolve to a past participle."""
    hits: list[PassiveHit] = []
    unresolved = 0
    for span in sentences:
        tokens = _tokens_with_spans(text, span.start, span.end)
        for position in range(len(tokens)):
            token = tokens[position][0]
            if token not in _PASSIVE_AUXILIARIES:
                continue
            cursor = position + 1
            skipped = 0
            while cursor < len(tokens) and skipped < 2 and tokens[cursor][0] in _PASSIVE_ADVERBS:
                cursor += 1
                skipped += 1
            if cursor < len(tokens) and _is_past_participle(tokens[cursor][0]):
                first = position
                if position > 0 and tokens[position - 1][0] in _PASSIVE_PHRASE_LEAD:
                    first = position - 1  # "has been adopted" / "can be mapped"
                phrase_start = tokens[first][1]
                phrase_end = tokens[cursor][2]
                hits.append(PassiveHit(
                    sentence=span,
                    phrase_start=phrase_start,
                    phrase_end=phrase_end,
                    phrase=text[phrase_start:phrase_end],
                    participle=tokens[cursor][0],
                ))
                break
            unresolved += 1
    return hits, unresolved


def detect_passive_spans(text: str) -> tuple[list[PassiveHit], int]:
    """Public helper: passive hits of a whole text plus the unresolved count.

    Kept in sync with the metric by construction - M-PAS-09 calls this very
    function, and pas_spotcheck.py uses it to draw its samples, so the sampled
    universe is exactly what the metric counts.
    """
    return _detect_passive(text, split_sentences(text))


def _metric_pas09(text: str, sentences: Sequence[Span]) -> dict[str, Any]:
    """M-PAS-09: passive SENTENCE ratio, with PHRASE-level evidence.

    value / n / denominator are computed exactly as before (one passive
    sentence per sentence, however many phrases it contains); the evidence
    sample points at the passive verb phrase, not at the whole sentence, so a
    third party can judge whether the match itself is correct.
    """
    hits, unresolved = _detect_passive(text, sentences)
    n_sentences = len(sentences)
    warnings: list[str] = []
    if n_sentences == 0:
        warnings.append("M-PAS-09: no sentence containing a letter was detected; value is undefined")
        value = None
    else:
        value = len(hits) / n_sentences
    if unresolved:
        warnings.append(
            "M-PAS-09: %d auxiliary occurrence(s) were not resolved to a past participle "
            "(copula or adjective reading) and are reported as n_unresolved" % unresolved
        )
    evidence = _evidence([(hit.phrase_start, hit.phrase_end) for hit in hits], text, len(hits))
    return _metric("M-PAS-09", value=value, n=len(hits), denominator=n_sentences,
                   unit=_UNIT_RATIO, evidence=evidence, warnings=warnings,
                   n_unresolved=unresolved, evidence_target="passive_phrase_span",
                   n_phrases=sum(1 for _ in hits))


def _nominalization_bases(token: str) -> list[str]:
    """Candidate base spellings for a token (plural normalisation)."""
    variants: list[str] = [token]
    if token.endswith("ies") and len(token) > 4:
        variants.append(token[:-3] + "y")
    elif token.endswith("es") and len(token) > 3:
        variants.append(token[:-2])
    elif token.endswith("s") and len(token) > 3:
        variants.append(token[:-1])
    return variants


def _stem_to_verb_candidates(stem: str) -> set[str]:
    """Frozen stem -> verb-base restoration candidates (see the module docstring)."""
    candidates = {stem, stem + "e", stem + "y", stem + "te", stem + "ate",
                  stem + "de", stem + "t"}
    if stem and stem[-1] in "aeiou":
        candidates.add(stem[:-1])
        candidates.add(stem[:-1] + "e")
        candidates.add(stem[:-1] + "y")
    if stem.endswith("ica") and len(stem) > 3:
        candidates.add(stem[:-3] + "y")
    if stem.endswith(("p", "b")) and len(stem) > 1:
        candidates.add(stem[:-1] + "be")  # description -> descrip -> describe
    if stem.endswith("i"):
        candidates.add(stem + "ze")  # recognition -> recogni -> recognize
    return candidates


def _nominalization_match(token: str, suffixes: Sequence[str],
                          verb_bases: frozenset[str],
                          denylist: frozenset[str]) -> tuple[bool, str]:
    for variant in _nominalization_bases(token):
        if variant in denylist:
            return False, ""
        for suffix in suffixes:
            if not variant.endswith(suffix) or len(variant) <= len(suffix):
                continue
            stem = variant[: -len(suffix)]
            if _stem_to_verb_candidates(stem) & verb_bases:
                return True, stem
    return False, ""


def _metric_nom10(text: str, sentences: Sequence[Span], suffixes: tuple[str, ...],
                  verb_bases: tuple[str, ...], denylist: tuple[str, ...]) -> dict[str, Any]:
    suffix_set = tuple(sorted({str(entry).strip().lower() for entry in suffixes if str(entry).strip()}))
    base_set = frozenset(
        str(entry).strip().lower() for entry in verb_bases if str(entry).strip()
    )
    deny_set = frozenset(
        str(entry).strip().lower() for entry in denylist if str(entry).strip()
    )
    hits: list[tuple[int, int]] = []
    if suffix_set and base_set:
        for span in sentences:
            for token, start, end in _tokens_with_spans(text, span.start, span.end):
                matched, _ = _nominalization_match(token, suffix_set, base_set, deny_set)
                if matched:
                    hits.append((start, end))
    warnings: list[str] = []
    if not suffix_set:
        warnings.append("M-NOM-10: nominalization_suffixes lexicon is empty; the metric is 0 by construction")
    if not base_set:
        warnings.append("M-NOM-10: nominalization_verb_bases lexicon is empty; the metric is 0 by construction")
    if not deny_set:
        warnings.append("M-NOM-10: nominalization_denylist lexicon is empty; pseudo-nominalizations are not filtered")
    return _rate("M-NOM-10", len(hits), len(tokenize(text)), _UNIT_RATIO,
                 _evidence(hits, text, len(hits)), warnings,
                 suffixes=suffix_set, n_denylist=len(deny_set))


def _tense_counts(text: str, sentences: Sequence[Span],
                  verb_bases: Iterable[str]) -> tuple[list[tuple[int, int]], int, int, int]:
    third_person = _build_third_person_index(verb_bases)
    present_hits: list[tuple[int, int]] = []
    present = 0
    past = 0
    unresolved = 0
    for span in sentences:
        for token, start, end in _tokens_with_spans(text, span.start, span.end):
            if token in _MODALS or token in _TENSELESS_BE:
                unresolved += 1
            elif token in _PRESENT_AUXILIARIES:
                present += 1
                present_hits.append((start, end))
            elif token in _PAST_AUXILIARIES or token in _IRREGULAR_PAST:
                past += 1
            elif len(token) >= 4 and token.endswith("ed") and token not in _ED_ADJECTIVE_DENYLIST:
                past += 1
            elif token in _IRREGULAR_PRESENT:
                present += 1
                present_hits.append((start, end))
            else:
                base = third_person.get(token)
                if base and base not in _AMBIGUOUS_NOUN_VERBS:
                    present += 1
                    present_hits.append((start, end))
    return present_hits, present, past, unresolved


def _metric_tense28(text: str, sentences: Sequence[Span],
                    verb_bases: Iterable[str]) -> dict[str, Any]:
    present_hits, present, past, unresolved = _tense_counts(text, sentences, verb_bases)
    denominator = present + past
    warnings: list[str] = []
    if unresolved:
        warnings.append(
            "M-TENSE-28: %d verb-like token(s) are tense-ambiguous (modal or be/been/being) "
            "and are reported as n_unresolved; they are excluded from the denominator" % unresolved
        )
    return _rate("M-TENSE-28", present, denominator, _UNIT_RATIO,
                 _evidence(present_hits, text, present), warnings,
                 n_unresolved=unresolved, n_present=present, n_past=past)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def detect_language(text: str) -> dict[str, Any]:
    """Detect whether the input language is one this module can measure.

    Frozen Round A contract:
      cjk_ratio  = cjk_chars / (cjk_chars + ascii_alpha_tokens), 0.0 if the
                   denominator is 0;
      supported  = cjk_ratio <= LANGUAGE_SUPPORT_CJK_THRESHOLD (0.10);
      language   = "zh" if cjk_ratio > threshold else ("en" if there is at
                   least one ASCII alpha token else "unknown").

    CJK characters counted: U+3400-U+4DBF, U+4E00-U+9FFF, U+F900-U+FAFF.
    ASCII alpha tokens are the module's own frozen tokenization (tokenize()),
    so the ratio is reproducible with the very same rule as every metric.
    """
    if not isinstance(text, str):
        text = ""
    cjk_chars = len(_CJK_CHAR_RE.findall(text))
    ascii_alpha_tokens = len(tokenize(text))
    denominator = cjk_chars + ascii_alpha_tokens
    cjk_ratio = (cjk_chars / denominator) if denominator else 0.0
    supported = cjk_ratio <= LANGUAGE_SUPPORT_CJK_THRESHOLD
    if cjk_ratio > LANGUAGE_SUPPORT_CJK_THRESHOLD:
        language = "zh"
    elif ascii_alpha_tokens > 0:
        language = "en"
    else:
        language = "unknown"
    reason = None
    if not supported:
        reason = (
            "cjk_ratio=%.6f > LANGUAGE_SUPPORT_CJK_THRESHOLD=%.2f: OBSERVED metrics "
            "are validated for %s only; all metrics are reported as null with "
            "warning %s instead of 0"
            % (cjk_ratio, LANGUAGE_SUPPORT_CJK_THRESHOLD,
               "/".join(SUPPORTED_LANGUAGES), LANGUAGE_NOT_SUPPORTED)
        )
    return {
        "language": language,
        "cjk_ratio": round(cjk_ratio, _ROUND_DIGITS),
        "cjk_chars": cjk_chars,
        "ascii_alpha_tokens": ascii_alpha_tokens,
        "supported": bool(supported),
        "reason": reason,
    }


def _unsupported_metric(metric_spec: str, language: dict[str, Any],
                        warning: str = LANGUAGE_NOT_SUPPORTED) -> dict[str, Any]:
    """Contract-shaped "not measured" record for an unsupported language.

    Never 0 (0 would be a fake measurement); never an exception.  Every field
    keeps its original meaning so a downstream consumer can tell "not measured"
    apart from "measured as zero".
    """
    return {
        "value": None,
        "n": 0,
        "denominator": 0,
        "unit": _METRIC_UNITS.get(metric_spec, _UNIT_RATIO),
        "state": _STATE_OBSERVED,
        "method": _METHOD_RULE,
        "metric_spec": metric_spec,
        "evidence": {"count": 0, "sample": []},
        "evidence_rule": _EVIDENCE_RULES.get(metric_spec, _EVIDENCE_RULE_DEFAULT),
        "warnings": [warning],
        "language": language["language"],
        "cjk_ratio": language["cjk_ratio"],
    }


def _pending_or_unsupported(metric_spec: str,
                              language: dict[str, Any]) -> dict[str, Any]:
    """Fallback for a metric the zh path does not compute.

    Two cases must stay distinguishable to a consumer: the metric is not
    validated for this language at all (CAPABILITY_NOT_SUPPORTED), or it is an
    INFERRED metric whose calibration set is still missing (NOT_IMPLEMENTED).
    """
    if not _METRIC_LANGUAGE_CAPABILITY.get(metric_spec, _DEFAULT_METRIC_LANGUAGES):
        return _not_implemented_metric(metric_spec, language)
    return _unsupported_metric(metric_spec, language,
                               warning=CAPABILITY_NOT_SUPPORTED)


def _not_implemented_metric(metric_spec: str, language: dict[str, Any]):
    """Contract-shaped placeholder for an INFERRED metric whose calibration set
    has not landed yet (issue #23 stance layer).

    Distinct from _unsupported_metric: the language *is* in scope and the metric
    *is* designed for it, but the frozen annotation set with kappa >= 0.6 that
    the INFERRED admission rules require does not exist yet.  A value here would
    be an uncalibrated semantic claim, so it stays null + NOT_IMPLEMENTED -
    exactly the placeholder pattern figure_profile uses.
    """
    record = _unsupported_metric(metric_spec, language,
                                 warning="NOT_IMPLEMENTED")
    record["state"] = "INFERRED"
    record["method"] = "model_pending_calibration"
    record["annotation_set"] = {
        "status": "not_frozen",
        "required_kappa": 0.6,
        "required_sentences": 200,
        "measured_kappa": None,
    }
    return record


def _sentence_pattern_stats(text: str, sentences: Sequence[Span],
                            clauses: Sequence[ClauseSpan],
                            connector_groups: Mapping[str, Sequence[str]]
                            ) -> tuple[list[str], list[bool], list[bool]]:
    """Per-sentence pattern classification (issue #23), deterministic.

    Returns three parallel lists aligned with `sentences`: the pattern name
    of each sentence, whether it is multi-clause, and whether its first
    clause opens with a discourse connector. The patterns are syntactic
    counts - no annotation, no model - so they are OBSERVED, not INFERRED.
    """
    # Clause membership: a clause belongs to the sentence whose span contains
    # it. Both are sorted by start, so a single sweep assigns every clause.
    clauses_per: list[int] = [0] * len(sentences)
    si = 0
    for clause in clauses:
        while si < len(sentences) and sentences[si].end < clause.start:
            si += 1
        if si < len(sentences) and sentences[si].start <= clause.start:
            clauses_per[si] += 1
    # A sentence is multi-clause when it splits into more than one clause.
    multi = [c > 1 for c in clauses_per]
    # A clause opens with a connector when its first characters match one.
    all_connectors: set[str] = set()
    for entries in connector_groups.values():
        all_connectors.update(entries)
    min_len = min((len(w) for w in all_connectors), default=0)
    opens = []
    for sentence, n_clauses in zip(sentences, clauses_per):
        if not n_clauses or not all_connectors:
            opens.append(False)
            continue
        first = text[sentence.start:sentence.end].lstrip()
        opens.append(any(first.startswith(w) for w in all_connectors
                         if len(w) >= min_len))
    # Pattern name: the coarse structural shape of the sentence.
    patterns = []
    for n_clauses, is_multi, opens_conn in zip(clauses_per, multi, opens):
        if n_clauses == 0:
            patterns.append("unsplit")
        elif is_multi and opens_conn:
            patterns.append("multi_clause_connective_open")
        elif is_multi:
            patterns.append("multi_clause_plain")
        elif opens_conn:
            patterns.append("single_clause_connective_open")
        else:
            patterns.append("single_clause_plain")
    return patterns, multi, opens


def _metric_spat44(text: str, sentences: Sequence[Span],
                   clauses: Sequence[ClauseSpan]) -> dict[str, Any]:
    """M-SPAT-44: mean distinct clause-start markers per sentence.

    Complements M-CLS-31 (clauses per sentence) with the writer's habit of
    opening a sentence with a discourse connector - 然而/因此/同时 - which is
    the visible scaffolding of an argument. A high value is heavy explicit
    connective framing; a low value is parataxis.
    """
    marked_sentences = [s for s in sentences
                       if any(ch in text[s.start:s.end]
                              for ch in _CLAUSE_SEPARATORS)]
    n_markers = sum(sum(1 for ch in text[s.start:s.end]
                        if ch in _CLAUSE_SEPARATORS)
                     for s in marked_sentences)
    n_sentences = len(sentences)
    evidence = _evidence([(s.start, s.end) for s in marked_sentences], text,
                         len(marked_sentences))
    if n_sentences == 0:
        return _metric(
            "M-SPAT-44", value=None, n=0, denominator=0,
            unit=_UNIT_CLAUSES_PER_SENTENCE, evidence=evidence,
            warnings=["M-SPAT-44: no sentence detected; value is undefined"])
    # n is the number of clause-bearing sentences (the unit the rule
    # describes), so evidence count and n agree; the rate itself divides the
    # marker total by every sentence.
    return _rate("M-SPAT-44", n_markers, n_sentences,
                 _UNIT_CLAUSES_PER_SENTENCE, evidence,
                 denominator_unit="sentences",
                 separator_chars=list(_CLAUSE_SEPARATORS))


def _metric_spat45(text: str, sentences: Sequence[Span],
                    patterns: list[str]) -> dict[str, Any]:
    """M-SPAT-45: share of multi-clause sentences (，；： inside).

    The writer's preference for complex, comma-chained sentences. It is the
    sentence-level view of M-LSF-16: the same long-sentence phenomenon, seen
    from the structure side rather than the length side.
    """
    n_multi = sum(1 for p in patterns if p.startswith("multi_clause"))
    n_sentences = len(sentences)
    spans = [(s.start, s.end) for s, p in zip(sentences, patterns)
             if p.startswith("multi_clause")]
    evidence = _evidence(spans, text, n_multi)
    if n_sentences == 0:
        return _metric(
            "M-SPAT-45", value=None, n=0, denominator=0,
            unit=_UNIT_RATIO, evidence=evidence,
            warnings=["M-SPAT-45: no sentence detected; value is undefined"])
    return _rate("M-SPAT-45", n_multi, n_sentences, _UNIT_RATIO, evidence,
                 denominator_unit="sentences")


def _metric_spat46(text: str, sentences: Sequence[Span],
                    opens: list[bool],
                    connector_groups: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    """M-SPAT-46: share of sentences opening with a discourse connector.

    A connective-open sentence hands the reader the logical relation first.
    High values read as heavily signposted argument; very low values read as
    unmarked juxtaposition, which is where a reviewer loses the thread.
    """
    n_open = sum(1 for o in opens if o)
    n_sentences = len(sentences)
    spans = [(s.start, s.end) for s, o in zip(sentences, opens) if o]
    evidence = _evidence(spans, text, n_open)
    if n_sentences == 0:
        return _metric(
            "M-SPAT-46", value=None, n=0, denominator=0,
            unit=_UNIT_RATIO, evidence=evidence,
            warnings=["M-SPAT-46: no sentence detected; value is undefined"])
    total_connectors = sum(len(v) for v in connector_groups.values())
    return _rate("M-SPAT-46", n_open, n_sentences, _UNIT_RATIO, evidence,
                 denominator_unit="sentences",
                 n_connector_entries=total_connectors,
                 connector_groups=sorted(connector_groups))


def _classify_sentence_stance(sentence_text: str,
                             hedge_entries: Sequence[str],
                             booster_entries: Sequence[str]) -> str:
    """One of _STANCE_LABELS for a single Chinese sentence (issue #23).

    Presence, not count: a sentence carries one stance, so a repeated trigger
    is the same claim made twice rather than a stronger one. A tie or a
    trigger-free sentence is assertive, the residual class by construction.
    This exact rule was calibrated on the frozen 220-sentence set; changing it
    invalidates the holdout figures in _STANCE_CALIBRATION_FACTS.
    """
    if not sentence_text:
        return "assertive"
    n_boost = sum(1 for w in booster_entries if w and w in sentence_text)
    n_hedge = sum(1 for w in hedge_entries if w and w in sentence_text)
    if n_boost > n_hedge:
        return "boosting"
    if n_hedge > n_boost:
        return "hedging"
    return "assertive"


def _stance_evidence(sentences: Sequence[Span], labels: list[str],
                     wanted: str, text: str) -> dict[str, Any]:
    """Evidence for one stance metric: the labelled sentences themselves.

    INFERRED-layer rule 4 (per-sentence traceable output): the consumer must be
    able to see which sentences were counted, not just how many. The spans
    therefore point at the sentences the classifier labelled as wanted.
    """
    spans = [(span.start, span.end) for span, label in zip(sentences, labels)
             if label == wanted]
    return _evidence(spans, text, len(spans))


def _metric_stnc(metric_spec: str, label: str, sentences: Sequence[Span],
                 labels: list[str], text: str) -> dict[str, Any]:
    """M-STNC-41/42/43: share of sentences carrying one stance (issue #23).

    INFERRED, never OBSERVED: the value is a classifier output, not a rule that
    is true by construction. The record therefore always carries the measured
    holdout quality, so a consumer can discount it appropriately; the hedging
    class is rare in academic Chinese (12/220 sentences) and its precision is
    correspondingly weak, which is exactly the kind of caveat a gate must not
    hide. The metrics never enter a gate (rule 5).
    """
    n_label = labels.count(label)
    n_sentences = len(sentences)
    evidence = _stance_evidence(sentences, labels, label, text)
    cal = {"state": "INFERRED", "method": "model_lexicon_presence",
           "calibration": _STANCE_CALIBRATION_FACTS,
           "annotation_set": {"status": "frozen",
                              "path": _STANCE_CALIBRATION,
                              "n_sentences": 220,
                              "labels": list(_STANCE_LABELS)}}
    if n_sentences == 0:
        return _metric(
            metric_spec, value=None, n=0, denominator=0,
            unit=_UNIT_RATIO, evidence=evidence,
            warnings=["%s: no sentence detected; value is undefined"
                      % metric_spec],
            **cal)
    return _rate(
        metric_spec, n_label, n_sentences, _UNIT_RATIO, evidence,
        [] if n_label or n_sentences else ["%s: no sentence detected"
                                           % metric_spec],
        denominator_unit="sentences",
        **cal)
    return _rate(
        metric_spec, n_label, n_sentences, _UNIT_RATIO, evidence,
        [] if n_label or n_sentences else ["%s: no sentence detected"
                                           % metric_spec],
        denominator_unit="sentences",
        state="INFERRED", method="model_lexicon_presence",
        calibration=_STANCE_CALIBRATION_FACTS,
        annotation_set={"status": "frozen",
                        "path": _STANCE_CALIBRATION,
                        "n_sentences": 220,
                        "labels": list(_STANCE_LABELS)})


def _zh_cjk_unit_count(span_text: str) -> int:
    """Chinese sentence-length unit: CJK characters + ASCII alpha tokens.

    Counting CJK characters only would under-count mixed sentences
    ("采用 K-means 算法求解"), and counting ASCII tokens only would report ~0.
    """
    return len(_CJK_CHAR_RE.findall(span_text)) + len(tokenize(span_text))


def _match_cjk_entries(sentences: Sequence[Span],
                       entries: Sequence[str]) -> list[tuple[int, int, int]]:
    """Literal, longest-first, non-overlapping matches of Chinese entries.

    Chinese is written without spaces, so the English token matcher does not
    apply: entries are matched as literal strings **inside a sentence** (matching
    never crosses a sentence boundary, same as the English rule) and a candidate
    is only accepted when it is the longest entry starting at that position.
    Every shipped Chinese entry is >= 2 characters (release policy), which keeps
    single-character function words from firing everywhere.
    """
    if not entries:
        return []
    by_length: dict[int, set[str]] = {}
    for entry in entries:
        by_length.setdefault(len(entry), set()).add(entry)
    lengths = sorted(by_length, reverse=True)
    hits: list[tuple[int, int, int]] = []
    for index, span in enumerate(sentences):
        piece = span.text
        pos, end = 0, len(piece)
        while pos < end:
            matched = 0
            for length in lengths:
                if pos + length <= end and piece[pos:pos + length] in by_length[length]:
                    matched = length
                    break
            if matched:
                hits.append((span.start + pos, span.start + pos + matched, index))
                pos += matched
            else:
                pos += 1
    return hits


def _match_cjk_groups(sentences: Sequence[Span],
                      groups: Mapping[str, Sequence[str]]
                      ) -> dict[str, list[tuple[int, int, int]]]:
    """Match every connector group at once, so the groups stay exclusive.

    M-CONN-30 must equal 30c + 30k + 30r exactly. Matching each group on its own
    would double count a shorter entry inside a longer one of another group
    ("由此可见" contains "由此"), so all groups share one longest-first pass and a
    matched span belongs to exactly one group.
    """
    table: dict[str, str] = {}
    for group, entries in groups.items():
        for entry in entries:
            table[entry] = group
    per_group: dict[str, list[tuple[int, int, int]]] = {group: [] for group in groups}
    if not table:
        return per_group
    lengths = sorted({len(entry) for entry in table}, reverse=True)
    for index, span in enumerate(sentences):
        piece = span.text
        pos, end = 0, len(piece)
        while pos < end:
            chosen: tuple[int, str] | None = None
            for length in lengths:
                if pos + length <= end:
                    candidate = piece[pos:pos + length]
                    group = table.get(candidate)
                    if group is not None:
                        chosen = (length, group)
                        break
            if chosen is not None:
                length, group = chosen
                per_group[group].append((span.start + pos, span.start + pos + length, index))
                pos += length
            else:
                pos += 1
    return per_group


def _cjk_abstract_noun_hits(sentences: Sequence[Span]) -> list[tuple[int, int, int]]:
    """Abstract-noun suffix hits for Chinese (性 / 度 / 率).

    Counts suffix **occurrences**, not segmented words: Chinese has no spaces and
    segmenting it would need a dictionary that could then drift.  The evidence
    span carries the preceding window, so a reviewer sees "稳定性" rather than a
    bare "性".
    """
    hits: list[tuple[int, int, int]] = []
    for index, span in enumerate(sentences):
        piece = span.text
        for position, char in enumerate(piece):
            if char not in _CJK_ABSTRACT_NOUN_SUFFIXES:
                continue
            prefix = 0
            cursor = position - 1
            while cursor >= 0 and _CJK_CHAR_RE.match(piece[cursor]):
                prefix += 1
                cursor -= 1
            if prefix < _CJK_ABSTRACT_NOUN_MIN_PREFIX:
                continue
            start = max(0, position - _CJK_ABSTRACT_NOUN_WINDOW)
            hits.append((span.start + start, span.start + position + 1, index))
    return hits


def _cjk_passive_hits(sentences: Sequence[Span]) -> list[tuple[int, int, int]]:
    """Passive phrase spans for Chinese (marker + the characters that follow).

    A marker alone is not a passive ("被" in a title, "得到" as a plain verb), so
    a marker only counts when a CJK character follows it inside the same
    sentence. Spans are de-duplicated and sorted, because a sentence can carry
    more than one marker.
    """
    hits: set[tuple[int, int, int]] = set()
    for index, span in enumerate(sentences):
        piece = span.text
        for marker in _CJK_PASSIVE_MARKERS:
            cursor = 0
            while True:
                found = piece.find(marker, cursor)
                if found < 0:
                    break
                after = found + len(marker)
                if after < len(piece) and _CJK_CHAR_RE.match(piece[after]):
                    end = min(len(piece), after + _CJK_PASSIVE_SPAN_CHARS)
                    hits.add((span.start + found, span.start + end, index))
                cursor = after
    return sorted(hits)


def _zh_token_stream(text: str) -> tuple[list[str], list[tuple[int, int]]]:
    """Document-order token stream + spans for Chinese MTLD (CJK chars + ASCII words).

    Character-level diversity is not the same statistic as the English word-level
    MTLD; the metric record carries a `tokenization` field that says which one
    was used, so the two can never be compared by accident.
    """
    tokens: list[str] = []
    spans: list[tuple[int, int]] = []
    for match in _TOKEN_STREAM_RE.finditer(text):
        tokens.append(match.group(0).lower())
        spans.append((match.start(), match.end()))
    return tokens, spans


def text_ctx(sentences: Sequence[Span]) -> str:
    """Concatenated sentence text, for evidence excerpts of sentence-level stats."""
    return "\n".join(span.text for span in sentences)


def _metric_cls31(text: str, sentences: Sequence[Span],
                   clauses: Sequence[ClauseSpan]) -> dict[str, Any]:
    """M-CLS-31: mean clauses per sentence.

    A low value is short, simple sentences; a high value is long multi-clause
    sentences.  The denominator is the sentence count, so the metric is only
    defined when at least one sentence was detected.
    """
    n_clauses = len(clauses)
    n_sentences = len(sentences)
    evidence = _evidence([(c.start, c.end) for c in clauses], text, n_clauses)
    if n_sentences == 0:
        return _metric(
            "M-CLS-31", value=None, n=n_clauses, denominator=0,
            unit=_UNIT_CLAUSES_PER_SENTENCE, evidence=evidence,
            warnings=["M-CLS-31: no sentence detected; value is undefined"])
    return _rate("M-CLS-31", n_clauses, n_sentences,
                 _UNIT_CLAUSES_PER_SENTENCE, evidence,
                 denominator_unit="sentences")


def _metric_cls32(text: str, clauses: Sequence[ClauseSpan]) -> dict[str, Any]:
    """M-CLS-32: mean clause length in cjk-units (CJK chars + ASCII words).

    Complements M-CLS-31: the same clauses-per-sentence with longer clauses is a
    different writing profile than the same count with short ones.  Units are the
    Chinese length unit, so the value is not comparable with any English figure.
    """
    lengths = [_zh_cjk_unit_count(clause.text) for clause in clauses]
    n_clauses = len(clauses)
    evidence = _evidence([(c.start, c.end) for c in clauses], text, n_clauses)
    if n_clauses == 0:
        return _metric(
            "M-CLS-32", value=None, n=0, denominator=0,
            unit=_UNIT_CJK_UNITS_PER_CLAUSE, evidence=evidence,
            warnings=["M-CLS-32: no clause detected; value is undefined"])
    return _rate("M-CLS-32", sum(lengths), n_clauses,
                 _UNIT_CJK_UNITS_PER_CLAUSE, evidence,
                 denominator_unit="clauses")


def _metric_slen_percentile(metric_spec: str, sentences: Sequence[Span],
                            counts: Sequence[int], quantile: float) -> dict[str, Any]:
    """M-SLEN-34/35: sentence-length P90/P95 in cjk-units.

    The tail of the sentence-length distribution is what an editor actually
    feels: a journal can share the mean (M-SLEN-01) and still differ sharply in
    the longest 10% of sentences.  Linear interpolation, matching this module's
    own _percentile; the corpus-level aggregation layer uses its own stated
    convention, as it already does for the median.
    """
    ordered = sorted(counts)
    evidence = _evidence([(s.start, s.end) for s in sentences], text_ctx(sentences),
                         len(sentences))
    if not ordered:
        return _metric(
            metric_spec, value=None, n=0, denominator=0,
            unit=_UNIT_CJK_UNITS_PER_SENTENCE, evidence=evidence,
            warnings=[f"{metric_spec}: no sentence detected; value is undefined"])
    value = _percentile(ordered, quantile)
    return _metric(
        metric_spec, value=value, n=len(ordered), denominator=len(ordered),
        unit=_UNIT_CJK_UNITS_PER_SENTENCE, evidence=evidence,
        quantile=quantile, quantile_method="linear_interpolation")


def _zh_metrics(text: str, sentences: Sequence[Span], language: dict[str, Any],
                bundle: Any) -> dict[str, dict[str, Any]]:
    """Chinese metric set.

    Every metric whose rules are validated for Chinese is computed here from the
    **Chinese lexicon release** (`data/lexicons/v2-zh`); the two that cannot be
    decided without an annotation set (M-NOM-10) or that do not exist in the
    language (M-TENSE-28, Chinese has no tense) stay null with
    CAPABILITY_NOT_SUPPORTED. Nothing is ever reported as a fabricated 0.

    Denomination: Chinese has no word boundaries, so densities use
    **cjk-units** (CJK characters + ASCII alpha tokens) as their denominator and
    say so in the metric's unit field.
    """
    counts = [_zh_cjk_unit_count(span.text) for span in sentences]
    n_units = _zh_cjk_unit_count(text)
    hedge_entries = _entries(bundle, "hedge")
    booster_entries = _entries(bundle, "booster")
    academic_entries = _entries(bundle, "academic_words")

    hedge_hits = _match_cjk_entries(sentences, hedge_entries)
    booster_hits = _match_cjk_entries(sentences, booster_entries)
    academic_hits = _match_cjk_entries(sentences, academic_entries)
    # The three M-CONN-30 groups plus the two PDTB derivatives (issue #23).
    # They are matched together so all five groups stay mutually exclusive,
    # but M-CONN-30 itself is assembled over _CONN30_GROUPS only - the
    # 30c+30k+30r identity must survive the new groups unchanged.
    group_specs = (
        ("M-CONN-30c", "contrastive"),
        ("M-CONN-30k", "causal"),
        ("M-CONN-30r", "result"),
        ("M-CONN-30t", "temporal"),
        ("M-CONN-30q", "condition"),
    )
    _CONN30_GROUPS = {"contrastive", "causal", "result"}
    group_entries = {group: _connector_entries(bundle, group) for _, group in group_specs}
    group_hits = _match_cjk_groups(sentences, group_entries)
    passive_hits = _cjk_passive_hits(sentences)

    computed: dict[str, dict[str, Any]] = {}
    computed["M-SLEN-01"] = _metric_slen01(text, sentences, counts,
                                           unit=_UNIT_CJK_UNITS_PER_SENTENCE)
    computed["M-LSF-16"] = _metric_lsf16(text, sentences, counts,
                                         threshold=_LONG_SENTENCE_CJK_UNITS)
    token_stream, token_spans = _zh_token_stream(text)
    computed["M-MTLD-02"] = _metric_mtld02(text, token_stream, token_spans,
                                           tokenization="cjk-char+ascii-token")

    def _density(spec: str, hits: Sequence[tuple[int, int, int]],
                 entries: Sequence[str]) -> dict[str, Any]:
        warnings = [] if entries else [
            f"{spec}: Chinese lexicon is empty; the metric is 0 by construction"]
        return _rate(spec, len(hits), n_units, _UNIT_RATIO,
                     _evidence(hits, text, len(hits)), warnings,
                     n_lexicon_entries=len(entries), denominator_unit="cjk-units")

    computed["M-HED-14"] = _density("M-HED-14", hedge_hits, hedge_entries)
    computed["M-BOO-15"] = _density("M-BOO-15", booster_hits, booster_entries)

    component_records: dict[str, dict[str, Any]] = {}
    for spec, group in group_specs:
        entries = group_entries[group]
        hits = group_hits[group]
        warnings = [] if entries else [
            f"{spec}: Chinese connector group is empty; the metric is 0 by construction"]
        component_records[spec] = _rate(
            spec, len(hits), n_units, _UNIT_PER_1000_CJK_UNITS,
            _evidence(hits, text, len(hits)), warnings, scale=1000.0,
            n_lexicon_entries=len(entries), denominator_unit="cjk-units")
        computed[spec] = component_records[spec]

    # M-CONN-30 totals only the three frozen groups; 30t/30q are separate
    # metrics and must never feed the union total.
    conn30_specs = [(spec, group) for spec, group in group_specs
                    if group in _CONN30_GROUPS]
    all_connector_hits = sorted(hit for _, group in conn30_specs
                                for hit in group_hits[group])
    component_values = [component_records[spec]["value"] for spec, _ in conn30_specs]
    total_n = sum(len(group_hits[group]) for _, group in conn30_specs)
    total_warnings: list[str] = []
    if n_units <= 0:
        total_warnings.append(
            "M-CONN-30: denominator is 0 (no cjk-unit in the input); value is undefined")
        total_value = None
    else:
        component_defined = all(value is not None for value in component_values)
        total_value = round(sum(component_values), _ROUND_DIGITS) if component_defined else None
        if total_value is None:
            total_warnings.append("M-CONN-30: at least one component is undefined; value is undefined")
    computed["M-CONN-30"] = _metric(
        "M-CONN-30", value=total_value, n=total_n, denominator=n_units,
        unit=_UNIT_PER_1000_CJK_UNITS,
        evidence=_evidence(all_connector_hits, text, total_n),
        warnings=total_warnings, denominator_unit="cjk-units",
        components={spec: {"value": component_records[spec]["value"],
                           "n": component_records[spec]["n"]} for spec, _ in conn30_specs},
    )

    # PDTB derivatives (issue #23): separate per-1000-cjk-unit rates, emitted
    # by the same component loop above (empty-group warning included).
    computed["M-CONN-30t"] = component_records["M-CONN-30t"]
    computed["M-CONN-30q"] = component_records["M-CONN-30q"]

    computed["M-AWR-03"] = _density("M-AWR-03", academic_hits, academic_entries)
    abstract_hits = _cjk_abstract_noun_hits(sentences)
    computed["M-NOM-10"] = _rate(
        "M-NOM-10", len(abstract_hits), n_units, _UNIT_PER_1000_CJK_UNITS,
        _evidence(abstract_hits, text, len(abstract_hits)), [],
        scale=1000.0, denominator_unit="cjk-units",
        # Which operationalization this number is. The English M-NOM-10 counts
        # verb->noun derivations; the Chinese one counts abstract-noun suffixes.
        # Same slot in the contract, different statistic: never compare them.
        variant="cjk-abstract-noun-suffix",
        suffixes=list(_CJK_ABSTRACT_NOUN_SUFFIXES),
        excluded_suffixes={"化": "entangled with non-nominalising verb forms (优化/转化/深化)"})

    computed["M-PAS-09"] = _rate(
        "M-PAS-09", len(passive_hits), len(sentences), _UNIT_RATIO,
        _evidence(passive_hits, text, len(passive_hits)),
        [] if passive_hits or sentences else ["M-PAS-09: no sentence detected"],
        denominator_unit="sentences",
        passive_markers=list(_CJK_PASSIVE_MARKERS))

    # Clause layer (issue #22): boundaries are Chinese-specific, so these stay
    # zh-only in _METRIC_LANGUAGE_CAPABILITY; English records get null +
    # CAPABILITY_NOT_SUPPORTED from the fallback below.
    clauses = split_clauses_zh(text)
    computed["M-CLS-31"] = _metric_cls31(text, sentences, clauses)
    computed["M-CLS-32"] = _metric_cls32(text, clauses)
    computed["M-SLEN-34"] = _metric_slen_percentile(
        "M-SLEN-34", sentences, counts, 0.90)
    computed["M-SLEN-35"] = _metric_slen_percentile(
        "M-SLEN-35", sentences, counts, 0.95)

    # Stance layer (issue #23): INFERRED sentence-level stance rates. The
    # classifier is the frozen lexicon-presence rule calibrated on
    # data/stance-calibration-zh.json (kappa 0.7584 >= 0.6).
    stance_labels = [_classify_sentence_stance(span.text,
                                               hedge_entries, booster_entries)
                     for span in sentences]
    computed["M-STNC-41"] = _metric_stnc(
        "M-STNC-41", "hedging", sentences, stance_labels, text)
    computed["M-STNC-42"] = _metric_stnc(
        "M-STNC-42", "boosting", sentences, stance_labels, text)
    computed["M-STNC-43"] = _metric_stnc(
        "M-STNC-43", "assertive", sentences, stance_labels, text)

    # Sentence-pattern layer (issue #23): deterministic structural counts over
    # the same clause/sentence spans. OBSERVED (syntactic counts, no model).
    all_group_entries = {group: _connector_entries(bundle, group)
                         for group in ("contrastive", "causal", "result",
                                       "temporal", "condition")}
    spat_patterns, spat_multi, spat_open = _sentence_pattern_stats(
        text, sentences, clauses, all_group_entries)
    computed["M-SPAT-44"] = _metric_spat44(text, sentences, clauses)
    computed["M-SPAT-45"] = _metric_spat45(text, sentences, spat_patterns)
    computed["M-SPAT-46"] = _metric_spat46(text, sentences, spat_open,
                                           all_group_entries)

    for metric_id, record in computed.items():
        record["language"] = language["language"]
        record["cjk_ratio"] = language["cjk_ratio"]
    return {
        metric_id: (computed[metric_id] if metric_id in computed
                    else _pending_or_unsupported(metric_id, language))
        for metric_id in METRIC_IDS
    }


def compute_text_metrics(text: str, bundle: Any) -> dict[str, dict[str, Any]]:
    """Compute every frozen metric for one text.

    The bundle is duck-typed: it needs the attributes hedge, booster,
    connectors (mapping with keys contrastive / causal / result),
    nominalization_suffixes, nominalization_verb_bases, nominalization_denylist,
    academic_words and stopwords, each exposing an entries tuple of lower-case
    strings.  No import of lexicon_loader happens here.

    Language dispatch goes through language_registry.adapter_for(): the detected
    language code selects the adapter that owns that language's compute path
    (English or Chinese).  A new language is wired by adding an adapter to the
    registry, never by adding another branch here.
    """
    if not isinstance(text, str):
        text = ""
    language = detect_language(text)
    return language_registry.adapter_for(language["language"]).compute(
        text, language, bundle)


def _english_metrics(text: str, language: dict[str, Any],
                     bundle: Any) -> dict[str, dict[str, Any]]:
    """English compute path (frozen): the code that used to live inline.

    Moved verbatim out of compute_text_metrics so EnglishAdapter can delegate to
    it; the metric algorithms, fields and warnings are unchanged.
    """
    sentences = split_sentences(text)
    sentence_counts = [len(tokenize(span.text)) for span in sentences]
    tokens = tokenize(text)
    token_spans = [(start, end) for _, start, end in _tokens_with_spans(text)]
    n_tokens = len(tokens)

    hedge_entries = _entries(bundle, "hedge")
    booster_entries = _entries(bundle, "booster")
    contrastive_entries = _connector_entries(bundle, "contrastive")
    causal_entries = _connector_entries(bundle, "causal")
    result_entries = _connector_entries(bundle, "result")
    academic_entries = _entries(bundle, "academic_words")
    verb_bases = _entries(bundle, "nominalization_verb_bases")

    metrics: dict[str, dict[str, Any]] = {}
    metrics["M-SLEN-01"] = _metric_slen01(text, sentences, sentence_counts)
    metrics["M-LSF-16"] = _metric_lsf16(text, sentences, sentence_counts)
    metrics["M-MTLD-02"] = _metric_mtld02(text, tokens, token_spans)

    hedge_hits = _match_entries(text, sentences, hedge_entries)
    hedge_warnings = []
    if not hedge_entries:
        hedge_warnings.append("M-HED-14: hedge lexicon is empty; the metric is 0 by construction")
    metrics["M-HED-14"] = _rate("M-HED-14", len(hedge_hits), n_tokens, _UNIT_RATIO,
                                _evidence(hedge_hits, text, len(hedge_hits)),
                                hedge_warnings, n_lexicon_entries=len(hedge_entries))

    booster_hits = _match_entries(text, sentences, booster_entries)
    booster_warnings = []
    if not booster_entries:
        booster_warnings.append("M-BOO-15: booster lexicon is empty; the metric is 0 by construction")
    metrics["M-BOO-15"] = _rate("M-BOO-15", len(booster_hits), n_tokens, _UNIT_RATIO,
                                _evidence(booster_hits, text, len(booster_hits)),
                                booster_warnings, n_lexicon_entries=len(booster_entries))

    components: list[tuple[str, list[tuple[int, int, int]], tuple[str, ...]]] = [
        ("M-CONN-30c", _match_entries(text, sentences, contrastive_entries), contrastive_entries),
        ("M-CONN-30k", _match_entries(text, sentences, causal_entries), causal_entries),
        ("M-CONN-30r", _match_entries(text, sentences, result_entries), result_entries),
    ]
    component_records: dict[str, dict[str, Any]] = {}
    for spec, hits, entries in components:
        warnings: list[str] = []
        if not entries:
            warnings.append(f"{spec}: connector lexicon group is empty; the metric is 0 by construction")
        component_records[spec] = _rate(spec, len(hits), n_tokens, _UNIT_PER_1000,
                                        _evidence(hits, text, len(hits)), warnings,
                                        scale=1000.0, n_lexicon_entries=len(entries))
    for spec, _, _ in components:
        metrics[spec] = component_records[spec]

    all_connector_hits = sorted(hit for _, hits, _ in components for hit in hits)
    component_values = [component_records[spec]["value"] for spec, _, _ in components]
    total_n = sum(len(hits) for _, hits, _ in components)
    total_warnings: list[str] = []
    if n_tokens <= 0:
        total_warnings.append(
            "M-CONN-30: denominator is 0 (no alpha token in the input); value is undefined"
        )
        total_value = None
    else:
        component_defined = all(value is not None for value in component_values)
        total_value = round(sum(component_values), _ROUND_DIGITS) if component_defined else None
        if total_value is None:
            total_warnings.append("M-CONN-30: at least one component is undefined; value is undefined")
    metrics["M-CONN-30"] = _metric(
        "M-CONN-30", value=total_value, n=total_n, denominator=n_tokens, unit=_UNIT_PER_1000,
        evidence=_evidence(all_connector_hits, text, total_n),
        warnings=total_warnings,
        components={
            spec: {"value": component_records[spec]["value"], "n": component_records[spec]["n"]}
            for spec, _, _ in components
        },
    )

    academic_hits = _match_entries(text, sentences, academic_entries)
    academic_warnings = []
    if not academic_entries:
        academic_warnings.append("M-AWR-03: academic_words lexicon is empty; the metric is 0 by construction")
    metrics["M-AWR-03"] = _rate("M-AWR-03", len(academic_hits), n_tokens, _UNIT_RATIO,
                                _evidence(academic_hits, text, len(academic_hits)),
                                academic_warnings, n_lexicon_entries=len(academic_entries))

    metrics["M-PAS-09"] = _metric_pas09(text, sentences)

    metrics["M-NOM-10"] = _metric_nom10(
        text, sentences,
        _entries(bundle, "nominalization_suffixes"),
        verb_bases,
        _entries(bundle, "nominalization_denylist"),
    )

    metrics["M-TENSE-28"] = _metric_tense28(text, sentences, verb_bases)

    # Language facts on EVERY metric dict (supported path), so a consumer can
    # always tell which language and CJK share produced the number.
    for record in metrics.values():
        record["language"] = language["language"]
        record["cjk_ratio"] = language["cjk_ratio"]

    # Metrics not computed on the English path (the zh-only clause layer, issue
    # #22) still appear in the record as null + CAPABILITY_NOT_SUPPORTED, so an
    # English paper and a Chinese paper always carry the same key set and a
    # consumer can tell "not measured for this language" from "missing".
    return {
        metric_id: (metrics[metric_id] if metric_id in metrics
                    else _unsupported_metric(metric_id, language,
                                             warning=CAPABILITY_NOT_SUPPORTED))
        for metric_id in METRIC_IDS
    }


__all__ = [
    "TEXT_METRICS_VERSION",
    "METRIC_IDS",
    "LANGUAGE_SUPPORT_CJK_THRESHOLD",
    "LANGUAGE_NOT_SUPPORTED",
    "SUPPORTED_LANGUAGES",
    "detect_language",
    "Span",
    "ClauseSpan",
    "split_sentences",
    "split_sentences_zh",
    "split_clauses_zh",
    "tokenize",
    "tokenize_zh",
    "mtld",
    "compute_text_metrics",
    "PassiveHit",
    "detect_passive_spans",
]


