#!/usr/bin/env python3
"""Metrics computed on the non-prose streams (tables / figures).

Scope decision (user, 2026-09-14): tables and figures are analysed SEPARATELY and
are never merged into the prose plain text - a table is not a sentence, so folding
its cells into sentence-length or hedge densities would corrupt those metrics.
These metrics therefore read doc_model streams, never the prose canonical text.

All five are deterministic rules over the parsed base artifact, so they inherit
the paper-metrics contract: Canonical Document -> metrics, byte-reproducible.

Record shape follows the product contract used by text_metrics: value / n /
denominator / unit / state / method / metric_spec / evidence / warnings, plus the
stream scope this module introduces.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import doc_model as dm
import text_metrics as tm

#: Which streams each metric reads.  Declared per record so a consumer never has to
#: infer whether a number came from the prose or from a table.
_SCOPE_INVENTORY: Final[tuple[str, ...]] = (dm.Stream.FIGURES.value,
                                            dm.Stream.TABLES.value)

_FIGURE_REF_RE: Final = re.compile(r"(?:figure|fig\.?|图)\s*(\d+)", re.IGNORECASE)
_TABLE_REF_RE: Final = re.compile(r"(?:table|表)\s*(\d+)", re.IGNORECASE)

_INVENTORY_STREAMS: Final[tuple[dm.Stream, ...]] = (dm.Stream.FIGURES,
                                                    dm.Stream.TABLES)

_SCOPE_FIGURES: Final[tuple[str, ...]] = (dm.Stream.FIGURES.value,)
_SCOPE_TABLES: Final[tuple[str, ...]] = (dm.Stream.TABLES.value,)
#: Metrics that need the prose side (density, citation depth): the mixed-scope set.
#: They are NOT draft-checkable either - a Markdown draft has tables neither.
_SCOPE_PROSE_TABLES: Final[tuple[str, ...]] = (dm.Stream.PROSE.value,
                                              dm.Stream.TABLES.value)

#: The stream(s) each metric reads, keyed by metric id (not by function) so a "not
#: measured" record carries exactly the same scope as a measured one.
_SCOPE_OF_METRIC: Final[dict[str, tuple[str, ...]]] = {
    "S-CAP-01": _SCOPE_INVENTORY,
    "S-NUM-02": _SCOPE_INVENTORY,
    "S-REF-03": _SCOPE_INVENTORY,
    "S-SIZ-04": _SCOPE_FIGURES,
    "S-CAPL-05": _SCOPE_INVENTORY,
    "S-TBL-06": _SCOPE_TABLES,
    "S-TBL-07": _SCOPE_TABLES,
    "S-TBL-08": _SCOPE_TABLES,
    "S-TBL-09": _SCOPE_PROSE_TABLES,
    "S-TBL-10": _SCOPE_TABLES,
    "S-TBL-11": _SCOPE_TABLES,
    "S-TBL-12": _SCOPE_TABLES,
    "S-TBL-13": _SCOPE_TABLES,
    "S-REF-14": _SCOPE_PROSE_TABLES,
}

#: Journal figures are printed at ~300 dpi; 800 px is roughly a 6.8 cm single-column
#: figure at that density.  Below it a raster is not expected to survive print, which
#: is the fact this threshold makes measurable.
_MIN_IMAGE_WIDTH: Final[int] = 800

_PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"
#: SOF0-SOF3 / SOF5-SOF7 / SOF9-SOF11 / SOF13-SOF15 carry the frame dimensions.
_JPEG_SOF_MARKERS: Final = frozenset(
    list(range(0xC0, 0xC4)) + list(range(0xC5, 0xC8))
    + list(range(0xC9, 0xCC)) + list(range(0xCD, 0xD0)))
_HEADER_BYTES: Final[int] = 1 << 16

#: Evidence samples stay bounded and deterministic (the product contract requires
#: every metric to carry a countable sample, not the whole corpus).
_SAMPLE_LIMIT: Final[int] = 20


def _record(metric_spec: str, *, value: float | None, n: int, denominator: int,
            unit: str, evidence: dict[str, dm.JsonValue], warnings: list[str],
            scope: tuple[str, ...] | None = None) -> dict[str, dm.JsonValue]:
    """Product-shaped metric record (see the module docstring for the contract)."""
    return {
        "value": None if value is None else round(value, 6),
        "n": int(n),
        "denominator": int(denominator),
        "unit": unit,
        "state": "OBSERVED",
        "method": "rule",
        "metric_spec": metric_spec,
        "scope": list(scope if scope is not None
                      else _SCOPE_OF_METRIC.get(metric_spec, _SCOPE_INVENTORY)),
        "evidence": evidence,
        "warnings": sorted(set(warnings)),
    }


def _as_int(value: dm.JsonValue) -> int:
    """Narrow a JSON value to int (0 when it is not one)."""
    return value if isinstance(value, int) else 0


def _caption_chars(entry: dict[str, dm.JsonValue]) -> int:
    """Sort key for caption evidence: the character count, typed for the checker."""
    return _as_int(entry.get("chars"))


def _as_str(value: dm.JsonValue) -> str:
    """Narrow a JSON value to str ("" when it is not one)."""
    return value if isinstance(value, str) else ""


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
    # Both coordinates are reported: "index" is the position inside that stream
    # (which figure is missing a caption), "block_index" re-opens the content_list.
    uncaptioned = [{"kind": stream.value, "index": index, "block_index": block.index}
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
                             ) -> tuple[dict[str, list[int]],
                                        list[dict[str, dm.JsonValue]]]:
    """(numbers per stream, one observation per declared number) in document order."""
    declared: dict[str, list[int]] = {dm.Stream.FIGURES.value: [],
                                     dm.Stream.TABLES.value: []}
    observed: list[dict[str, dm.JsonValue]] = []
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
    if not total:
        # No captions carry a number at all.  Without this code the metric is simply
        # "null" and the reader cannot tell "nothing to number" from "not measured"
        # (cross-review M6); the corpus-level small-n noise is not a reason.
        warnings.append("NO_DECLARED_NUMBERS")
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


def _citation_text(model: dm.DocumentModel, canonical_text: str | None) -> str:
    """The text citations are searched in.

    The canonical BODY when the caller supplies it: model.text(PROSE) is every
    text block, which includes headings, front matter and the bibliography itself -
    a search space ~50% larger on the Chinese corpus (measured), so a reference
    list could in principle vote on its own citations.  Falling back to the prose
    stream keeps the metric unit-testable, and the record says which was used.
    """
    return canonical_text if canonical_text is not None else model.text(dm.Stream.PROSE)


def _referenced_numbers(model: dm.DocumentModel,
                        canonical_text: str | None = None) -> dict[str, list[int]]:
    """Numbers cited in the body only (cell values are not references)."""
    return {stream: sorted(counts)
            for stream, counts in _reference_counts(model, canonical_text).items()}


def reference_consistency(model: dm.DocumentModel,
                          canonical_text: str | None = None
                          ) -> dict[str, dm.JsonValue]:
    """S-REF-03: do the prose references and the declared captions agree?

    value = shared / |declared ∪ referenced| (Jaccard overlap; 1.0 = every declared
    number is also referenced and vice versa).  The earlier denominator
    (declared + referenced) capped the value at 0.5, which made a near-perfect
    corpus read as "half of them do not match" and the docs drew exactly that wrong
    conclusion (2026-09-14 cross-review, blocker B2).  Dangling = cited but never
    declared; uncited = declared but never cited.  Both are reported per stream.
    """
    declared_numbers, observed = _declared_observations(model)
    declared = {stream: sorted(set(numbers))
                for stream, numbers in declared_numbers.items()}
    referenced = _referenced_numbers(model, canonical_text)
    dangling: dict[str, list[int]] = {}
    uncited: dict[str, list[int]] = {}
    shared = 0
    for stream_name, numbers in declared.items():
        declared_set = set(numbers)
        referenced_set = set(referenced[stream_name])
        dangling[stream_name] = sorted(referenced_set - declared_set)
        uncited[stream_name] = sorted(declared_set - referenced_set)
        shared += len(declared_set & referenced_set)
    # Jaccard denominator: |A ∪ B| = |A| + |B| - |A ∩ B|.  n carries the numerator,
    # so value == n / denominator holds (the metric contract, cross-review M2).
    denominator = (sum(len(v) for v in declared.values())
                   + sum(len(v) for v in referenced.values()) - shared)
    warnings: list[str] = []
    if not denominator:
        # Neither a declared number nor a reference was found: say so instead of
        # leaving the metric null with no cause (same contract as NO_DECLARED_NUMBERS).
        warnings.append("NO_DECLARED_NUMBERS")
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


def _png_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) from a PNG IHDR chunk."""
    if not data.startswith(_PNG_SIGNATURE) or data[12:16] != b"IHDR":
        return None
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return (width, height) if width and height else None


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) from the first JPEG frame header (SOFn)."""
    if not data.startswith(b"\xff\xd8"):
        return None
    index = 2
    limit = len(data) - 9
    while index < limit:
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in _JPEG_SOF_MARKERS:
            height = int.from_bytes(data[index + 5:index + 7], "big")
            width = int.from_bytes(data[index + 7:index + 9], "big")
            return (width, height) if width and height else None
        if marker == 0xDA:
            return None            # start of scan: no frame header left to find
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            index += 2             # stand-alone marker, no length field
            continue
        length = int.from_bytes(data[index + 2:index + 4], "big")
        index += 2 + max(length, 2)
    return None


def _gif_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) from a GIF logical screen descriptor."""
    if not data.startswith((b"GIF87a", b"GIF89a")):
        return None
    width = int.from_bytes(data[6:8], "little")
    height = int.from_bytes(data[8:10], "little")
    return (width, height) if width and height else None


def image_size(path: Path) -> tuple[int, int] | None:
    """(width, height) from the file's own header, or None when unreadable/unknown.

    Headers only: no decoder, no third-party dependency, so the metrics layer stays
    pure stdlib.  PNG / JPEG / GIF are recognised; anything else (WebP, a vector
    export) returns None and the caller reports it as unreadable rather than guessing.
    """
    try:
        with path.open("rb") as handle:
            data = handle.read(_HEADER_BYTES)
    except OSError:
        return None
    for reader in (_png_size, _jpeg_size, _gif_size):
        size = reader(data)
        if size is not None:
            return size
    return None


def image_resolution(model: dm.DocumentModel) -> dict[str, dm.JsonValue]:
    """S-SIZ-04: share of figure images whose width reaches the print threshold.

    Images are measured from their own headers.  Unreadable files are listed and kept
    OUT of the denominator: an unreadable raster is "not measured", so counting it as
    adequate - or as inadequate - would be a fabricated value.
    """
    base = model.source.parent
    images: list[dict[str, dm.JsonValue]] = []
    unreadable: list[str] = []
    for block in model.blocks:
        if block.kind is not dm.Stream.FIGURES or not block.image_path:
            continue
        size = image_size(base / block.image_path)
        if size is None:
            unreadable.append(block.image_path)
            continue
        width, height = size
        images.append({"block_index": block.index, "field": "img_path",
                       "excerpt": block.image_path[:80],
                       "img_path": block.image_path, "width": width, "height": height,
                       "aspect_ratio": round(width / height, 4) if height else None})
    warnings: list[str] = ["IMAGE_UNREADABLE"] if unreadable else []
    if not images:
        warnings.append("NO_FIGURES")
        # Same evidence shape as the measured branch: a consumer reading
        # median_width must not have to special-case "no figures".
        return _record("S-SIZ-04", value=None, n=0, denominator=0, unit="ratio",
                       evidence={"count": 0, "sample": [], "images": [],
                                 "unreadable": unreadable, "median_width": None,
                                 "min_width_required": _MIN_IMAGE_WIDTH},
                       warnings=warnings)
    widths = sorted(_as_int(item.get("width")) for item in images)
    adequate = sum(1 for width in widths if width >= _MIN_IMAGE_WIDTH)
    return _record("S-SIZ-04", value=adequate / len(widths), n=len(widths),
                   denominator=len(widths), unit="ratio",
                   evidence={"count": len(images), "sample": images[:_SAMPLE_LIMIT],
                             "images": images, "unreadable": unreadable,
                             "median_width": widths[len(widths) // 2],
                             "min_width_required": _MIN_IMAGE_WIDTH},
                   warnings=warnings)


def caption_length(model: dm.DocumentModel) -> dict[str, dm.JsonValue]:
    """S-CAPL-05: median caption length in characters.

    Characters rather than words, so the number exists for Chinese too - which also
    means it is NOT comparable across languages (N Chinese characters carry more
    content than N Latin ones).
    """
    entries: list[dict[str, dm.JsonValue]] = [
        {"block_index": block.index, "field": block.caption_field,
         "excerpt": block.caption[:80], "chars": len(block.caption),
         "kind": block.kind.value}
        for block in model.blocks
        if block.kind in _INVENTORY_STREAMS and block.caption.strip()]
    if not entries:
        return _record("S-CAPL-05", value=None, n=0, denominator=0, unit="characters",
                       evidence={"count": 0, "sample": [], "lengths": []},
                       warnings=["NO_CAPTIONS"])
    lengths = sorted(_as_int(entry.get("chars")) for entry in entries)
    median = lengths[len(lengths) // 2]
    return _record("S-CAPL-05", value=float(median), n=len(lengths),
                   denominator=len(lengths), unit="characters",
                   evidence={"count": len(entries), "sample": entries[:_SAMPLE_LIMIT],
                             "lengths": sorted(entries, key=_caption_chars),
                             "min": lengths[0], "median": median,
                             "max": lengths[-1]},
                   warnings=[])


# ---------------------------------------------------------------------------
# Table structure (tables only): rows, cells, merges, missing bodies
# ---------------------------------------------------------------------------
# Measured on the real corpus (2026-09-14): every table_body is HTML (no markdown
# pipe tables), colspan/rowspan are pervasive (~19 colspans per table on the English
# corpus), 8 of 273 English tables carry no body at all, and the empty-cell ratio
# reaches 0.70 - so "count the <td> tags" would understate wide tables and hide both
# missing data and sparse tables.

_TABLE_ROW_RE: Final = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_TABLE_CELL_RE: Final = re.compile(r"<t[dh]\b([^>]*)>(.*?)</t[dh]>",
                                   re.IGNORECASE | re.DOTALL)
_TABLE_COLSPAN_RE: Final = re.compile(r"colspan\s*=\s*[\"']?\s*(\d+)", re.IGNORECASE)
_TABLE_ROWSPAN_RE: Final = re.compile(r"rowspan\s*=\s*[\"']?\s*(\d+)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class TableShape:
    """Shape of one HTML table_body, as far as the markup states it."""

    rows: int
    cells: int
    empty_cells: int
    declared_columns: int
    colspan_merges: int
    rowspan_merges: int


def _span_value(attrs: str, pattern: re.Pattern[str]) -> int:
    match = pattern.search(attrs)
    return int(match.group(1)) if match else 1


def table_shape(html: str) -> TableShape:
    """Rows / cells / merges / emptiness of one HTML table_body.

    declared_columns sums each row's own colspan (the real corpus merges heavily, so
    counting cells would understate every wide table).  rowspan is counted but NOT
    carried into following rows: this is the row's declared span, not a reconstructed
    render grid - and it is documented as such rather than silently approximated.
    """
    rows = _TABLE_ROW_RE.findall(html)
    cells = _TABLE_CELL_RE.findall(html)
    empty_cells = 0
    colspan_merges = 0
    rowspan_merges = 0
    for attrs, inner in cells:
        # Reuse doc_model's normaliser instead of a second tag-stripping rule: "is this
        # cell empty" must mean the same thing here as it does in the census.
        if not dm.html_to_text(inner):
            empty_cells += 1
        if _span_value(attrs, _TABLE_COLSPAN_RE) > 1:
            colspan_merges += 1
        if _span_value(attrs, _TABLE_ROWSPAN_RE) > 1:
            rowspan_merges += 1
    declared_columns = 0
    if rows:
        for row in rows:
            declared_columns = max(
                declared_columns,
                sum(_span_value(attrs, _TABLE_COLSPAN_RE)
                    for attrs, _inner in _TABLE_CELL_RE.findall(row)))
    elif cells:
        declared_columns = sum(_span_value(attrs, _TABLE_COLSPAN_RE)
                               for attrs, _inner in cells)
    return TableShape(rows=len(rows) if rows else (1 if cells else 0),
                      cells=len(cells), empty_cells=empty_cells,
                      declared_columns=declared_columns,
                      colspan_merges=colspan_merges, rowspan_merges=rowspan_merges)


def _table_observations(model: dm.DocumentModel) -> tuple[list[dict[str, dm.JsonValue]],
                                                          list[int]]:
    """One observation per table block with a body, plus the indices of empty ones."""
    observations: list[dict[str, dm.JsonValue]] = []
    empty_bodies: list[int] = []
    for _stream, index, block in _inventory_blocks(model):
        if block.kind is not dm.Stream.TABLES:
            continue
        body = block.table_body or ""
        shape = table_shape(body)
        if not shape.cells:
            # block_index (position in the content_list), not the stream-relative
            # index: an anomaly must be re-openable at the coordinate it names.
            empty_bodies.append(block.index)
            continue
        observations.append({
            "block_index": block.index, "field": "table_body",
            "excerpt": body[:80], "index": index, "rows": shape.rows,
            "cells": shape.cells, "empty_cells": shape.empty_cells,
            "declared_columns": shape.declared_columns,
            "colspan_merges": shape.colspan_merges,
            "rowspan_merges": shape.rowspan_merges})
    return observations, empty_bodies


def table_columns(model: dm.DocumentModel) -> dict[str, dm.JsonValue]:
    """S-TBL-06: median DECLARED column count over the paper's tables.

    Nearest-rank median (the repo's quantile convention).  Tables that carry no body
    are excluded from the median and listed separately: an unmeasurable table must not
    drag the column count toward zero.
    """
    observations, empty_bodies = _table_observations(model)
    warnings: list[str] = ["TABLE_BODY_EMPTY"] if empty_bodies else []
    if not observations:
        warnings.append("NO_TABLES")
        return _record("S-TBL-06", value=None, n=0, denominator=0, unit="columns",
                       evidence={"count": 0, "sample": [], "tables": [],
                                 "empty_bodies": empty_bodies}, warnings=warnings)
    columns = sorted(_as_int(item.get("declared_columns")) for item in observations)
    return _record("S-TBL-06", value=float(columns[len(columns) // 2]),
                   n=len(columns), denominator=len(columns), unit="columns",
                   evidence={"count": len(observations),
                             "sample": observations[:_SAMPLE_LIMIT],
                             "tables": observations,
                             "empty_bodies": empty_bodies}, warnings=warnings)


def table_empty_cells(model: dm.DocumentModel) -> dict[str, dm.JsonValue]:
    """S-TBL-07: share of table cells that carry no text (pooled over the paper)."""
    observations, empty_bodies = _table_observations(model)
    warnings: list[str] = ["TABLE_BODY_EMPTY"] if empty_bodies else []
    cells = sum(_as_int(item.get("cells")) for item in observations)
    empty = sum(_as_int(item.get("empty_cells")) for item in observations)
    if not cells:
        warnings.append("NO_TABLES")
        return _record("S-TBL-07", value=None, n=0, denominator=0, unit="ratio",
                       evidence={"count": 0, "sample": [], "tables": [], "cells": 0,
                                 "empty_cells": 0, "empty_bodies": empty_bodies},
                       warnings=warnings)
    return _record("S-TBL-07", value=empty / cells, n=len(observations),
                   denominator=len(observations), unit="ratio",
                   evidence={"count": cells, "sample": observations[:_SAMPLE_LIMIT],
                             "tables": observations, "cells": cells,
                             "empty_cells": empty, "empty_bodies": empty_bodies},
                   warnings=warnings)


def table_missing_body(model: dm.DocumentModel) -> dict[str, dm.JsonValue]:
    """S-TBL-08: share of table blocks whose body carries no measurable cells.

    Missing DATA, not a table with zero cells: the two must not be conflated, and the
    affected blocks are named by index so the gap is auditable.
    """
    observations, empty_bodies = _table_observations(model)
    total = len(observations) + len(empty_bodies)
    warnings: list[str] = ["TABLE_BODY_EMPTY"] if empty_bodies else []
    if not total:
        warnings.append("NO_TABLES")
        return _record("S-TBL-08", value=None, n=0, denominator=0, unit="ratio",
                       evidence={"count": 0, "sample": [], "missing": []},
                       warnings=warnings)
    return _record("S-TBL-08", value=len(empty_bodies) / total, n=total,
                   denominator=total, unit="ratio",
                   evidence={"count": total, "sample": observations[:_SAMPLE_LIMIT],
                             "missing": empty_bodies}, warnings=warnings)


# ---------------------------------------------------------------------------
# Table density (cross-stream) + section placement
# ---------------------------------------------------------------------------
# Density needs the prose side too, so its scope is ["prose", "tables"] - the first
# mixed-scope metric.  That has a consequence the contract layer must know about: a
# mixed-scope metric is still NOT draft-checkable (a Markdown draft has no tables), so
# build_contract only accepts metrics whose scope is exactly prose.

_UNIT_PER_1000_WORDS: Final = "per-1000-words"
_UNIT_PER_1000_CJK_UNITS: Final = "per-1000-cjk-units"

#: Sections a table is *expected* to live in.  The reported share is a documented
#: lower bound: on the real Chinese corpus many tables sit under sub-headings whose
#: label cannot be resolved ("3.1 案例构造"), and those are not counted as results.
_RESULT_SECTIONS: Final[frozenset[str]] = frozenset({"experiments", "results",
                                                     "discussion"})


def _count_of(item: tuple[str, int]) -> int:
    """Sort/max key for a section tally, typed for the checker."""
    return item[1]


def _prose_units(prose: str) -> tuple[int, str, str]:
    """(units, unit label, language) from the FROZEN metric tokenizer.

    Reused rather than re-implemented: a second word-splitting rule would drift from
    the one every other density metric uses, and the density would then depend on
    which rule happened to run first.
    """
    language = tm.detect_language(prose)
    cjk = _as_int(language.get("cjk_chars"))
    alpha = _as_int(language.get("ascii_alpha_tokens"))
    name = str(language.get("language"))
    if name == "zh":
        return cjk + alpha, _UNIT_PER_1000_CJK_UNITS, name
    return alpha, _UNIT_PER_1000_WORDS, name


def table_density(model: dm.DocumentModel,
                  canonical_text: str | None = None
                  ) -> dict[str, dm.JsonValue]:
    """S-TBL-09: table blocks per 1000 prose units (words, or cjk-units in Chinese).

    The denominator is measured on the PROSE stream only: counting the tables' own
    text as prose would let a table-heavy paper inflate its own base and hide the very
    density this metric exists to report.
    """
    tables: list[dict[str, dm.JsonValue]] = [
        {"block_index": block.index, "field": "table_body",
         "excerpt": (block.table_body or "")[:80], "index": index}
        for _stream, index, block in _inventory_blocks(model)
        if block.kind is dm.Stream.TABLES]
    body = _citation_text(model, canonical_text)
    units, unit_label, language = _prose_units(body)
    evidence: dict[str, dm.JsonValue] = {
        "count": len(tables), "sample": tables[:_SAMPLE_LIMIT], "prose_units": units,
        "unit_basis": ("cjk-units" if unit_label == _UNIT_PER_1000_CJK_UNITS
                       else "words"),
        "language": language,
        # Which text carried the denominator.  model.text(PROSE) is every text block
        # (headings, front matter, the bibliography); the canonical body is the same
        # text minus the non-prose sections, and on the Chinese corpus the two differ
        # by ~50% of characters - so the basis is stated instead of implied
        # (cross-review H3).
        "unit_basis_text": ("canonical_body" if canonical_text is not None
                            else "prose_stream_incl_headings_and_references")}
    warnings: list[str] = []
    if canonical_text is None:
        warnings.append("UNIT_BASIS_NOT_CANONICAL")
    if not tables:
        warnings.append("NO_TABLES")
        return _record("S-TBL-09", value=None, n=0, denominator=units,
                       unit=unit_label, evidence=evidence, warnings=warnings)
    if not units:
        # No prose to divide by: report "not measured", never a fabricated 0.
        warnings.append("NO_PROSE_UNITS")
        return _record("S-TBL-09", value=None, n=len(tables), denominator=0,
                       unit=unit_label, evidence=evidence, warnings=warnings)
    return _record("S-TBL-09", value=len(tables) / units * 1000, n=len(tables),
                   denominator=units, unit=unit_label, evidence=evidence,
                   warnings=warnings)


def table_placement(model: dm.DocumentModel,
                    sections: dict[int, str] | None = None) -> dict[str, dm.JsonValue]:
    """S-TBL-10: where a paper's tables sit, summarised as a top-1 section share.

    The value is the MOST-USED section rather than "share in results" on purpose: a
    results-only value would be biased low by an unknown amount wherever the section
    label cannot be resolved.  The results share is still reported, next to the caveat
    that it is a lower bound.  sections maps a content_list block index to its
    canonical section label; without it the metric reports itself as unmeasured.
    """
    if sections is None:
        return _record("S-TBL-10", value=None, n=0, denominator=0, unit="ratio",
                       evidence={"count": 0, "sample": [], "sections": {}},
                       warnings=["SECTIONS_UNAVAILABLE"])
    counts: dict[str, int] = {}
    sample: list[dict[str, dm.JsonValue]] = []
    for _stream, _index, block in _inventory_blocks(model):
        if block.kind is not dm.Stream.TABLES:
            continue
        section = sections.get(block.index)
        if not section:
            continue
        counts[section] = counts.get(section, 0) + 1
        sample.append({"block_index": block.index, "field": "table_body",
                       "excerpt": (block.table_body or "")[:80], "section": section})
    total = sum(counts.values())
    if not total:
        return _record("S-TBL-10", value=None, n=0, denominator=0, unit="ratio",
                       evidence={"count": 0, "sample": [], "sections": {}},
                       warnings=["NO_TABLES"])
    top_section, top_count = max(sorted(counts.items()), key=_count_of)
    results = sum(count for name, count in counts.items() if name in _RESULT_SECTIONS)
    return _record(
        "S-TBL-10", value=top_count / total, n=total, denominator=total, unit="ratio",
        evidence={"count": total, "sample": sample[:_SAMPLE_LIMIT],
                  "sections": counts, "top_section": top_section,
                  "top_share": round(top_count / total, 6),
                  "results_share": round(results / total, 6),
                  "results_sections": sorted(_RESULT_SECTIONS),
                  "results_share_note": ("保守下界：只统计 canonical 标签 "
                                         + ", ".join(sorted(_RESULT_SECTIONS))
                                         + "；落在无法识别的子标题下的表不计入")},
        warnings=[])


# ---------------------------------------------------------------------------
# Table content: numeric density + LaTeX residue (tables only)
# ---------------------------------------------------------------------------
# Measured on the real corpus (2026-09-14): 77.9% of the Chinese corpus's table cells
# are strictly numeric versus 49.7% in the English corpus (whose tables carry instance
# labels like "G13" and compound cells like "522(90.0%)"); 1.5-2.3% of cells still
# contain LaTeX ("$r _ { c e n } = 4 . 5$") in roughly a third of all tables.

#: A cell is numeric when only a number, an optional range and an optional short unit
#: remain (full-width digits normalised, thousands separators removed first).
_NUMERIC_CELL_RE: Final = re.compile(r"^[+-]?\d+(?:\.\d+)?\s*[A-Za-z%]{0,6}$")
_NUMERIC_RANGE_RE: Final = re.compile(
    r"^[+-]?\d+(?:\.\d+)?\s*[-~\u2013\u81f3]\s*[+-]?\d+(?:\.\d+)?$")
_NUMBER_BEARING_RE: Final = re.compile(r"\d")
#: MinerU leaves LaTeX in table cells (e.g. "$r _ { c e n } = 4 . 5$").
_LATEX_CELL_MARKER: Final[str] = "$"


@dataclass(frozen=True, slots=True)
class TableCells:
    """Cell text of one table by row - the single scan the three content metrics share."""

    rows: tuple[tuple[str, ...], ...]
    cells: int
    numeric_cells: int
    numeric_bearing_cells: int
    latex_cells: int
    numeric_rows: int


def _cell_text(inner: str) -> str:
    """Normalised cell text: tags stripped, full-width digits folded, separators gone."""
    text = _normalise_digits(dm.html_to_text(inner))
    return text.replace(",", "").replace(" ", "").strip()


def _is_numeric_cell(text: str) -> bool:
    return bool(_NUMERIC_CELL_RE.match(text) or _NUMERIC_RANGE_RE.match(text))


def table_cells(html: str) -> TableCells:
    """Scan one table_body once: per-row cell text plus every count the metrics need.

    Rows rather than reconstructed columns: colspan/rowspan are pervasive here, so
    column alignment would be guesswork while a row's own cells are known exactly.
    """
    rows: list[tuple[str, ...]] = []
    numeric_cells = numeric_bearing = latex_cells = numeric_rows = 0
    for row_html in _TABLE_ROW_RE.findall(html):
        texts = tuple(_cell_text(inner)
                      for _attrs, inner in _TABLE_CELL_RE.findall(row_html))
        if not texts:
            continue
        rows.append(texts)
        row_numeric = 0
        for text in texts:
            if _is_numeric_cell(text):
                numeric_cells += 1
                row_numeric += 1
            if _NUMBER_BEARING_RE.search(text):
                numeric_bearing += 1
            if _LATEX_CELL_MARKER in text:
                latex_cells += 1
        if row_numeric >= max(1, len(texts) // 2):
            numeric_rows += 1
    return TableCells(rows=tuple(rows), cells=sum(len(row) for row in rows),
                      numeric_cells=numeric_cells,
                      numeric_bearing_cells=numeric_bearing,
                      latex_cells=latex_cells, numeric_rows=numeric_rows)


def _table_cell_scan(model: dm.DocumentModel) -> tuple[list[dict[str, dm.JsonValue]],
                                                       list[int]]:
    """Per-table cell scan for the content metrics, plus the empty-body indices."""
    tables: list[dict[str, dm.JsonValue]] = []
    empty_bodies: list[int] = []
    for _stream, index, block in _inventory_blocks(model):
        if block.kind is not dm.Stream.TABLES:
            continue
        body = block.table_body or ""
        cells = table_cells(body)
        if not cells.cells:
            empty_bodies.append(block.index)
            continue
        tables.append({"block_index": block.index, "field": "table_body",
                       "excerpt": body[:80], "index": index,
                       "rows": len(cells.rows), "cells": cells.cells,
                       "numeric_cells": cells.numeric_cells,
                       "numeric_bearing_cells": cells.numeric_bearing_cells,
                       "numeric_rows": cells.numeric_rows,
                       "latex_cells": cells.latex_cells})
    return tables, empty_bodies


def numeric_cell_share(model: dm.DocumentModel) -> dict[str, dm.JsonValue]:
    """S-TBL-11: share of table cells that are STRICTLY numeric.

    The looser "contains a number" reading is reported alongside, because the gap
    between them is a real property of the corpus (labels like G13 and compound cells
    like 522(90.0%)) and one number alone would mislead whichever reader it did not fit.
    """
    tables, empty_bodies = _table_cell_scan(model)
    cells = sum(_as_int(item.get("cells")) for item in tables)
    numeric = sum(_as_int(item.get("numeric_cells")) for item in tables)
    bearing = sum(_as_int(item.get("numeric_bearing_cells")) for item in tables)
    latex = sum(_as_int(item.get("latex_cells")) for item in tables)
    warnings: list[str] = ["TABLE_BODY_EMPTY"] if empty_bodies else []
    if latex:
        warnings.append("LATEX_IN_CELLS")
    if not cells:
        warnings.append("NO_TABLES")
        return _record("S-TBL-11", value=None, n=0, denominator=0, unit="ratio",
                       evidence={"count": 0, "sample": [], "tables": [],
                                 "numeric_cells": 0, "numeric_bearing_cells": 0,
                                 "numeric_bearing_share": None,
                                 "latex_cells": latex,
                                 "empty_bodies": empty_bodies}, warnings=warnings)
    return _record("S-TBL-11", value=numeric / cells, n=cells, denominator=cells,
                   unit="ratio",
                   evidence={"count": cells, "sample": tables[:_SAMPLE_LIMIT],
                             "tables": tables, "numeric_cells": numeric,
                             "numeric_bearing_cells": bearing,
                             "numeric_bearing_share": round(bearing / cells, 6),
                             "latex_cells": latex,
                             "empty_bodies": empty_bodies}, warnings=warnings)


def numeric_row_share(model: dm.DocumentModel) -> dict[str, dm.JsonValue]:
    """S-TBL-12: share of rows whose cells are at least half numeric (data rows)."""
    tables, empty_bodies = _table_cell_scan(model)
    rows = sum(_as_int(item.get("rows")) for item in tables)
    numeric_rows = sum(_as_int(item.get("numeric_rows")) for item in tables)
    warnings: list[str] = ["TABLE_BODY_EMPTY"] if empty_bodies else []
    if not rows:
        warnings.append("NO_TABLES")
        return _record("S-TBL-12", value=None, n=0, denominator=0, unit="ratio",
                       evidence={"count": 0, "sample": [], "tables": [],
                                 "numeric_rows": 0,
                                 "empty_bodies": empty_bodies}, warnings=warnings)
    return _record("S-TBL-12", value=numeric_rows / rows, n=rows, denominator=rows,
                   unit="ratio",
                   evidence={"count": rows, "sample": tables[:_SAMPLE_LIMIT],
                             "tables": tables, "numeric_rows": numeric_rows,
                             "empty_bodies": empty_bodies}, warnings=warnings)


def table_latex_residue(model: dm.DocumentModel) -> dict[str, dm.JsonValue]:
    """S-TBL-13: share of table cells that still carry LaTeX markup.

    Its own metric because it silently breaks numeric reuse of the table: a cell that
    reads "$r _ { c e n } = 4 . 5$" is not a number to any consumer, and it is an
    extraction artifact rather than an authoring choice.
    """
    tables, empty_bodies = _table_cell_scan(model)
    cells = sum(_as_int(item.get("cells")) for item in tables)
    latex = sum(_as_int(item.get("latex_cells")) for item in tables)
    warnings: list[str] = ["TABLE_BODY_EMPTY"] if empty_bodies else []
    if latex:
        warnings.append("LATEX_IN_CELLS")
    if not cells:
        warnings.append("NO_TABLES")
        return _record("S-TBL-13", value=None, n=0, denominator=0, unit="ratio",
                       evidence={"count": 0, "sample": [], "tables": [],
                                 "latex_cells": latex,
                                 "empty_bodies": empty_bodies}, warnings=warnings)
    return _record("S-TBL-13", value=latex / cells, n=cells, denominator=cells,
                   unit="ratio",
                   evidence={"count": cells, "sample": tables[:_SAMPLE_LIMIT],
                             "tables": tables, "latex_cells": latex,
                             "empty_bodies": empty_bodies}, warnings=warnings)


# ---------------------------------------------------------------------------
# Table citation depth
# ---------------------------------------------------------------------------

#: Mentions per declared table: a table that is merely listed reads low, a table that
#: is argued over reads high.
_UNIT_CITATIONS_PER_TABLE: Final = "citations-per-declared-table"


def _reference_counts(model: dm.DocumentModel,
                      canonical_text: str | None = None) -> dict[str, dict[int, int]]:
    """Mentions of each figure/table number in the body.

    A "表 2" written inside a cell is not a citation - otherwise tables would cite
    themselves - so cell text never contributes, exactly as in _referenced_numbers.
    """
    prose = _citation_text(model, canonical_text)
    return {dm.Stream.FIGURES.value: dict(Counter(_numbers(prose, _FIGURE_REF_RE))),
            dm.Stream.TABLES.value: dict(Counter(_numbers(prose, _TABLE_REF_RE)))}


def reference_depth(model: dm.DocumentModel,
                    canonical_text: str | None = None
                    ) -> dict[str, dm.JsonValue]:
    """S-REF-14: mean prose mentions per declared table.

    The uncited tables are named rather than averaged away, and the citation
    distribution (median / max / single- vs multi-mention shares) ships as evidence:
    "how often is a table discussed" is a different question from "is it cited at all".
    """
    declared_numbers, observed = _declared_observations(model)
    declared = sorted(set(declared_numbers[dm.Stream.TABLES.value]))
    if not declared:
        return _record("S-REF-14", value=None, n=0, denominator=0,
                       unit=_UNIT_CITATIONS_PER_TABLE,
                       evidence={"count": 0, "sample": [], "depths": {},
                                 "uncited": []}, warnings=["NO_TABLES"])
    if not model.text(dm.Stream.PROSE).strip():
        # No prose means the citation search could not run: "not measured", not zero.
        return _record("S-REF-14", value=None, n=len(declared),
                       denominator=len(declared), unit=_UNIT_CITATIONS_PER_TABLE,
                       evidence={"count": len(declared),
                                 "sample": observed[:_SAMPLE_LIMIT], "depths": {},
                                 "uncited": declared}, warnings=["NO_PROSE_TEXT"])
    counts = _reference_counts(model, canonical_text)[dm.Stream.TABLES.value]
    depths = {number: counts.get(number, 0) for number in declared}
    values = sorted(depths.values())
    uncited = sorted(number for number, depth in depths.items() if depth == 0)
    warnings: list[str] = ["UNCITED_TABLES"] if uncited else []
    return _record(
        "S-REF-14", value=float(values[len(values) // 2]), n=len(values),
        denominator=len(values), unit=_UNIT_CITATIONS_PER_TABLE,
        evidence={"count": len(values), "sample": observed[:_SAMPLE_LIMIT],
                  "depths": {str(number): depth for number, depth in depths.items()},
                  "median_depth": values[len(values) // 2],
                  # mean and the shares stay in evidence: citation depth is long-tailed
                  # (one table is often discussed many times), so the headline is the
                  # median and the actionable number is how much is never cited
                  # (cross-review M8).
                  "mean_depth": round(sum(values) / len(values), 6),
                  "uncited_share": round(len(uncited) / len(values), 6),
                  "max_depth": values[-1],
                  "single_mention_share": round(
                      sum(1 for value in values if value == 1) / len(values), 6),
                  "multi_mention_share": round(
                      sum(1 for value in values if value >= 2) / len(values), 6),
                  "uncited": uncited}, warnings=warnings)


_METRIC_IDS: Final[tuple[str, ...]] = ("S-CAP-01", "S-NUM-02", "S-REF-03",
                                         "S-SIZ-04", "S-CAPL-05", "S-TBL-06",
                                         "S-TBL-07", "S-TBL-08", "S-TBL-09",
                                         "S-TBL-10", "S-TBL-11", "S-TBL-12",
                                         "S-TBL-13", "S-REF-14")


def unavailable_records(warning: str) -> dict[str, dict[str, dm.JsonValue]]:
    """Every stream metric as an explicit "not measured" record.

    Used when the base artifact cannot be parsed: absent metrics would let the
    corpus summary report the paper as if it had no figures at all.
    """
    return {
        metric_id: _record(metric_id, value=None, n=0, denominator=0, unit="ratio",
                           evidence={"count": 0, "sample": []},
                           warnings=[warning])
        for metric_id in _METRIC_IDS
    }


def stream_metrics(model: dm.DocumentModel,
                   sections: dict[int, str] | None = None,
                   canonical_text: str | None = None
                   ) -> dict[str, dict[str, dm.JsonValue]]:
    """All stream metrics for one paper, keyed by metric id.

    sections maps a content_list block index to its canonical section label; without
    it the placement metric reports itself as unmeasured instead of guessing.
    """
    out: dict[str, dict[str, dm.JsonValue]] = {}
    for record in (caption_coverage(model), numbering_consistency(model),
                   reference_consistency(model, canonical_text),
                   image_resolution(model), caption_length(model),
                   table_columns(model), table_empty_cells(model),
                   table_missing_body(model), table_density(model, canonical_text),
                   table_placement(model, sections), numeric_cell_share(model),
                   numeric_row_share(model), table_latex_residue(model),
                   reference_depth(model, canonical_text)):
        metric_id = record["metric_spec"]
        if isinstance(metric_id, str):
            out[metric_id] = record
    return out
