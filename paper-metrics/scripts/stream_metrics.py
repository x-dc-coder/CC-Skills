#!/usr/bin/env python3
"""Metrics computed on the non-prose streams (tables / figures).

Scope decision (user, 2026-09-14): tables and figures are analysed SEPARATELY and
are never merged into the prose plain text - a table is not a sentence, so folding
its cells into sentence-length or hedge densities would corrupt those metrics.
These metrics therefore read doc_model streams, never the prose canonical text.

All three are deterministic rules over the parsed base artifact, so they inherit
the paper-metrics contract: Canonical Document -> metrics, byte-reproducible.

Record shape follows the product contract used by text_metrics: value / n /
denominator / unit / state / method / metric_spec / evidence / warnings, plus the
stream scope this module introduces.
"""

from __future__ import annotations

import re
from typing import Final

import doc_model as dm

#: Which streams each metric reads.  Declared per record so a consumer never has to
#: infer whether a number came from the prose or from a table.
_SCOPE_INVENTORY: Final[tuple[str, ...]] = (dm.Stream.FIGURES.value,
                                            dm.Stream.TABLES.value)

_FIGURE_REF_RE: Final = re.compile(r"(?:figure|fig\.?|图)\s*(\d+)", re.IGNORECASE)
_TABLE_REF_RE: Final = re.compile(r"(?:table|表)\s*(\d+)", re.IGNORECASE)

_INVENTORY_STREAMS: Final[tuple[dm.Stream, ...]] = (dm.Stream.FIGURES,
                                                    dm.Stream.TABLES)

#: Evidence samples stay bounded and deterministic (the product contract requires
#: every metric to carry a countable sample, not the whole corpus).
_SAMPLE_LIMIT: Final[int] = 20


def _record(metric_spec: str, *, value: float | None, n: int, denominator: int,
            unit: str, evidence: dict[str, dm.JsonValue], warnings: list[str],
            scope: tuple[str, ...] = _SCOPE_INVENTORY) -> dict[str, dm.JsonValue]:
    """Product-shaped metric record (see the module docstring for the contract)."""
    return {
        "value": None if value is None else round(value, 6),
        "n": int(n),
        "denominator": int(denominator),
        "unit": unit,
        "state": "OBSERVED",
        "method": "rule",
        "metric_spec": metric_spec,
        "scope": list(scope),
        "evidence": evidence,
        "warnings": sorted(set(warnings)),
    }


def _normalise_digits(text: str) -> str:
    """Full-width digits to ASCII: CNKI PDFs encode every digit full-width."""
    return text.translate(str.maketrans("\uFF10\uFF11\uFF12\uFF13\uFF14"
                                       "\uFF15\uFF16\uFF17\uFF18\uFF19",
                                       "0123456789"))


def _numbers(text: str, pattern: re.Pattern[str]) -> list[int]:
    return [int(match) for match in pattern.findall(_normalise_digits(text))]


def _inventory_blocks(model: dm.DocumentModel) -> list[tuple[dm.Stream, int, dm.Block]]:
    """(stream, index-within-stream, block) for every figure and table block."""
    counters: dict[dm.Stream, int] = {}
    out: list[tuple[dm.Stream, int, dm.Block]] = []
    for block in model.blocks:
        if block.kind not in _INVENTORY_STREAMS:
            continue
        index = counters.get(block.kind, 0)
        counters[block.kind] = index + 1
        out.append((block.kind, index, block))
    return out


def caption_coverage(model: dm.DocumentModel) -> dict[str, dm.JsonValue]:
    """S-CAP-01: share of figures/tables that actually carry a caption.

    A figure without a caption cannot be paired with its text reference, so it is
    reported by stream index rather than counted as "present".
    """
    inventory = _inventory_blocks(model)
    uncaptioned = [{"kind": stream.value, "index": index}
                   for stream, index, block in inventory if not block.caption.strip()]
    total = len(inventory)
    # Only captioned items are sampled: a sample must be quotable, and the absence
    # of a caption is already reported, item by item, in "uncaptioned".
    sample = [{"block_index": block.index, "field": block.caption_field,
               "excerpt": block.caption[:80],
               "kind": stream.value, "index": index}
              for stream, index, block in inventory
              if block.caption.strip()][:_SAMPLE_LIMIT]
    if not total:
        return _record("S-CAP-01", value=None, n=0, denominator=0, unit="ratio",
                       evidence={"count": 0, "sample": [], "uncaptioned": []},
                       warnings=["NO_FIGURES_OR_TABLES"])
    return _record("S-CAP-01", value=(total - len(uncaptioned)) / total, n=total,
                   denominator=total, unit="ratio",
                   evidence={"count": total, "sample": sample,
                             "uncaptioned": uncaptioned,
                             "captioned": total - len(uncaptioned)},
                   warnings=["CAPTION_MISSING"] if uncaptioned else [])


def _declared_observations(model: dm.DocumentModel
                             ) -> tuple[dict[str, list[int]], list[dict]]:
    """(numbers per stream, one observation per declared number) in document order."""
    declared: dict[str, list[int]] = {dm.Stream.FIGURES.value: [],
                                     dm.Stream.TABLES.value: []}
    observed: list[dict] = []
    for stream, index, block in _inventory_blocks(model):
        pattern = (_FIGURE_REF_RE if stream is dm.Stream.FIGURES
                   else _TABLE_REF_RE)
        for number in _numbers(block.caption, pattern):
            declared[stream.value].append(number)
            # block_index/field/excerpt are the evidence contract's form B: they must
            # re-open the exact block and field the number came from.
            observed.append({"block_index": block.index,
                             "field": block.caption_field,
                             "excerpt": block.caption[:80],
                             "kind": stream.value, "index": index,
                             "number": number})
    return declared, observed


def _declared_numbers(model: dm.DocumentModel) -> dict[str, list[int]]:
    """Caption numbers per stream, in document order."""
    return _declared_observations(model)[0]


def numbering_consistency(model: dm.DocumentModel) -> dict[str, dm.JsonValue]:
    """S-NUM-02: caption numbers unique; gaps reported.

    value = share of declared numbers that are not extra occurrences of an already
    declared one (1.0 = no duplicates).  Gaps and duplicates are both evidence, so
    a reader can see which number is wrong instead of only that something is.
    """
    declared, observed = _declared_observations(model)
    gaps: dict[str, list[int]] = {}
    duplicates: dict[str, list[int]] = {}
    extra = 0
    for stream_name, numbers in declared.items():
        seen = set(numbers)
        top = max(numbers) if numbers else 0
        gaps[stream_name] = sorted(set(range(1, top + 1)) - seen)
        duplicates[stream_name] = sorted({n for n in numbers if numbers.count(n) > 1})
        extra += len(numbers) - len(seen)
    total = sum(len(numbers) for numbers in declared.values())
    warnings: list[str] = []
    if any(gaps.values()):
        warnings.append("NUMBER_GAPS")
    if any(duplicates.values()):
        warnings.append("DUPLICATE_NUMBERS")
    value = None if not total else (total - extra) / total
    return _record("S-NUM-02", value=value, n=total, denominator=total,
                   unit="ratio",
                   evidence={"count": len(observed),
                             "sample": observed[:_SAMPLE_LIMIT],
                             "declared": declared, "gaps": gaps,
                             "duplicates": duplicates},
                   warnings=warnings)


def _referenced_numbers(model: dm.DocumentModel) -> dict[str, list[int]]:
    """Numbers cited in the PROSE stream only (cell values are not references)."""
    prose = model.text(dm.Stream.PROSE)
    return {dm.Stream.FIGURES.value: sorted(set(_numbers(prose, _FIGURE_REF_RE))),
            dm.Stream.TABLES.value: sorted(set(_numbers(prose, _TABLE_REF_RE)))}


def reference_consistency(model: dm.DocumentModel) -> dict[str, dm.JsonValue]:
    """S-REF-03: do the prose references and the declared captions agree?

    value = shared numbers / (declared + referenced).  Dangling = cited but never
    declared; uncited = declared but never cited.  Both are reported per stream.
    """
    declared_numbers, observed = _declared_observations(model)
    declared = {stream: sorted(set(numbers))
                for stream, numbers in declared_numbers.items()}
    referenced = _referenced_numbers(model)
    dangling: dict[str, list[int]] = {}
    uncited: dict[str, list[int]] = {}
    shared = 0
    for stream_name, numbers in declared.items():
        declared_set = set(numbers)
        referenced_set = set(referenced[stream_name])
        dangling[stream_name] = sorted(referenced_set - declared_set)
        uncited[stream_name] = sorted(declared_set - referenced_set)
        shared += len(declared_set & referenced_set)
    denominator = (sum(len(v) for v in declared.values())
                   + sum(len(v) for v in referenced.values()))
    warnings: list[str] = []
    if any(dangling.values()):
        warnings.append("DANGLING_REFERENCES")
    if any(uncited.values()):
        warnings.append("UNCITED_FIGURES_OR_TABLES")
    return _record("S-REF-03",
                   value=None if not denominator else shared / denominator,
                   n=shared, denominator=denominator, unit="ratio",
                   evidence={"count": len(observed),
                             "sample": observed[:_SAMPLE_LIMIT],
                             "declared": declared, "referenced": referenced,
                             "dangling": dangling, "uncited": uncited},
                   warnings=warnings)


_METRIC_IDS: Final[tuple[str, ...]] = ("S-CAP-01", "S-NUM-02", "S-REF-03")


def unavailable_records(warning: str) -> dict[str, dict[str, dm.JsonValue]]:
    """The three metrics as explicit "not measured" records.

    Used when the base artifact cannot be parsed: absent metrics would let the
    corpus summary report the paper as if it had no figures at all.
    """
    return {
        metric_id: _record(metric_id, value=None, n=0, denominator=0, unit="ratio",
                           evidence={"count": 0, "sample": []},
                           warnings=[warning])
        for metric_id in _METRIC_IDS
    }


def stream_metrics(model: dm.DocumentModel) -> dict[str, dict[str, dm.JsonValue]]:
    """All non-prose stream metrics for one paper, keyed by metric id."""
    out: dict[str, dict[str, dm.JsonValue]] = {}
    for record in (caption_coverage(model), numbering_consistency(model),
                   reference_consistency(model)):
        metric_id = record["metric_spec"]
        if isinstance(metric_id, str):
            out[metric_id] = record
    return out
