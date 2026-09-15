#!/usr/bin/env python3
"""Language dispatch registry for text_metrics (issue #10, Phase 1).

One data-driven mapping from a detect_language() language code to the adapter
that owns that language's compute path.  The registry is the single place a new
language is wired: add an adapter + one entry here, never another
``if language == ...`` branch inside compute_text_metrics().

The adapters deliberately defer their ``import text_metrics`` into the
compute method: language_registry is imported by text_metrics at module load, so
the metric functions it delegates to only exist after text_metrics is fully
loaded (a top-level import here would be a circular import).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class LanguageAdapter(Protocol):
    """The compute contract every registered language must satisfy.

    ``compute`` returns the full METRIC_IDS-keyed metric dict for ``text``,
    stamped with the language facts carried by ``language``.  ``code`` is
    the canonical language code the adapter is registered under.
    """

    code: str

    def compute(self, text: str, language: dict[str, Any],
                bundle: Any) -> dict[str, dict[str, Any]]:
        ...


@dataclass(frozen=True)
class EnglishAdapter:
    """English compute path: delegates to text_metrics' frozen English metrics."""

    code: str = "en"

    def compute(self, text: str, language: dict[str, Any],
                bundle: Any) -> dict[str, dict[str, Any]]:
        import text_metrics as _tm

        return _tm._english_metrics(text, language, bundle)


@dataclass(frozen=True)
class ChineseAdapter:
    """Chinese compute path: delegates to _zh_metrics + the v2-zh lexicon path."""

    code: str = "zh"

    def compute(self, text: str, language: dict[str, Any],
                bundle: Any) -> dict[str, dict[str, Any]]:
        import text_metrics as _tm

        return _tm._zh_metrics(text, _tm.split_sentences(text), language, bundle)


#: Explicit registry: language code -> adapter.  Tests inject a FakeAdapter here
#: to prove the dispatch reads the registry rather than a chain of if branches.
ADAPTERS: dict[str, LanguageAdapter] = {
    "en": EnglishAdapter(),
    "zh": ChineseAdapter(),
}


def adapter_for(code: str) -> LanguageAdapter:
    """Return the adapter for ``code``.

    Unregistered codes (including detect_language()'s "unknown") fall back to the
    English adapter, which reproduces the pre-registry behaviour of routing every
    non-"zh" input through the English compute path.
    """
    adapter = ADAPTERS.get(code)
    return adapter if adapter is not None else ADAPTERS["en"]
