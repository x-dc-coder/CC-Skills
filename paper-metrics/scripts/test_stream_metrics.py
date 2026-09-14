#!/usr/bin/env python3
"""Tests for stream_metrics — metrics computed on the NON-prose streams.

Written before the implementation (TDD).  These are the metrics the 2026-09-14
scope decision requires: tables and figures are analysed separately and are NEVER
merged into the prose plain text.

Covers:
  1. S-CAP-01 caption coverage (a figure/table without a caption is not paired)
  2. S-NUM-02 caption numbering (gaps and duplicates, per kind)
  3. S-REF-03 in-text reference consistency (dangling references, uncited items)
  4. Every record follows the product contract and declares its stream scope

Run:
    cd ~/.claude/skills && uv run pytest paper-metrics/scripts/test_stream_metrics.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

import doc_model as dm
import stream_metrics as sm


def _block(block_type: str, **fields: object) -> dict:
    return {"type": block_type, **fields}


def _write(tmp_path: Path, name: str, blocks: list[dict]) -> dm.DocumentModel:
    path = tmp_path / "auto" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blocks, ensure_ascii=False), encoding="utf-8")
    return dm.parse_document(path)


@pytest.fixture
def model(tmp_path: Path) -> dm.DocumentModel:
    """Two figures (one uncaptioned), one table, prose with references.

    Deliberately inconsistent: Figure 1 and Table 2 are declared, while the prose
    cites Figure 1 / 图 2 / Figure 9 / Table 1 - so the figure stream is missing 2
    and 9, the table stream is missing 1, and Table 2 is never cited.
    """
    return _write(tmp_path, "p1_content_list.json", [
        _block("text", text="As shown in Figure 1 and 图 2, the method works."),
        _block("text", text="Table 1 lists the results; see Figure 9 for details."),
        _block("image", img_path="images/f1.jpg",
               image_caption=["Figure 1", "Framework overview"]),
        _block("image", img_path="images/f2.jpg"),
        _block("table", table_body="<table><tr><td>1</td></tr></table>",
               table_caption=["Table 2", "Results"]),
    ])


# ---------------------------------------------------------------------------
# 1. Caption coverage
# ---------------------------------------------------------------------------

def test_caption_coverage_counts_uncaptioned_figures(model: dm.DocumentModel) -> None:
    record = sm.caption_coverage(model)
    assert record["metric_spec"] == "S-CAP-01"
    assert record["n"] == 3 and record["denominator"] == 3   # 2 figures + 1 table
    assert record["value"] == pytest.approx(2 / 3, abs=1e-6)
    assert record["unit"] == "ratio"
    assert record["state"] == "OBSERVED" and record["method"] == "rule"
    assert record["scope"] == ["figures", "tables"]
    assert record["evidence"]["uncaptioned"] == [{"kind": "figures", "index": 1}]
    assert "CAPTION_MISSING" in record["warnings"]


def test_caption_coverage_is_null_when_there_is_nothing_to_pair(tmp_path: Path) -> None:
    record = sm.caption_coverage(_write(tmp_path, "p2_content_list.json", [
        _block("text", text="Only prose here.")]))
    assert record["value"] is None and record["n"] == 0
    assert "NO_FIGURES_OR_TABLES" in record["warnings"]


# ---------------------------------------------------------------------------
# 2. Caption numbering
# ---------------------------------------------------------------------------

def test_numbering_consistency_reports_gaps_and_duplicates(model: dm.DocumentModel) -> None:
    record = sm.numbering_consistency(model)
    assert record["metric_spec"] == "S-NUM-02"
    evidence = record["evidence"]
    assert evidence["declared"] == {"figures": [1], "tables": [2]}
    assert evidence["gaps"] == {"figures": [], "tables": [1]}
    assert evidence["duplicates"] == {"figures": [], "tables": []}
    assert record["n"] == 2                       # two declared captions
    assert record["value"] == pytest.approx(1.0)  # none duplicated
    assert "NUMBER_GAPS" in record["warnings"]


def test_numbering_duplicates_lower_the_value(tmp_path: Path) -> None:
    record = sm.numbering_consistency(_write(tmp_path, "p3_content_list.json", [
        _block("image", img_path="a.jpg", image_caption=["Figure 1", "One"]),
        _block("image", img_path="b.jpg", image_caption=["图 1", "重复编号"]),
        _block("table", table_body="<table></table>",
               table_caption=["Table 1", "One"]),
    ]))
    assert record["evidence"]["duplicates"] == {"figures": [1], "tables": []}
    assert record["value"] == pytest.approx(2 / 3, abs=1e-6)
    assert "DUPLICATE_NUMBERS" in record["warnings"]


# ---------------------------------------------------------------------------
# 3. In-text reference consistency
# ---------------------------------------------------------------------------

def test_reference_consistency_finds_dangling_and_uncited(model: dm.DocumentModel) -> None:
    record = sm.reference_consistency(model)
    assert record["metric_spec"] == "S-REF-03"
    evidence = record["evidence"]
    assert evidence["declared"] == {"figures": [1], "tables": [2]}
    assert evidence["referenced"] == {"figures": [1, 2, 9], "tables": [1]}
    assert evidence["dangling"] == {"figures": [2, 9], "tables": [1]}
    assert evidence["uncited"] == {"figures": [], "tables": [2]}
    # (1 shared figure number + 0 shared table numbers) / (2 declared + 4 referenced)
    assert record["value"] == pytest.approx(1 / 6, abs=1e-6)
    assert "DANGLING_REFERENCES" in record["warnings"]
    assert "UNCITED_FIGURES_OR_TABLES" in record["warnings"]


def test_reference_consistency_ignores_numbers_in_tables(tmp_path: Path) -> None:
    """Only the prose stream is searched: a dataset value of 2 inside a table cell
    must never look like a figure reference."""
    record = sm.reference_consistency(_write(tmp_path, "p4_content_list.json", [
        _block("text", text="See Figure 1."),
        _block("image", img_path="a.jpg", image_caption=["Figure 1", "One"]),
        _block("table",
               table_body="<table><tr><td>Figure</td><td>2</td></tr></table>",
               table_caption=["Table 1", "Values"]),
    ]))
    assert record["evidence"]["referenced"]["figures"] == [1]
    # Table 1 is declared but never cited -> uncited, not dangling.
    assert record["evidence"]["dangling"] == {"figures": [], "tables": []}
    assert record["evidence"]["uncited"] == {"figures": [], "tables": [1]}
    assert record["value"] == pytest.approx(1 / 3, abs=1e-6)


# ---------------------------------------------------------------------------
# 4. Product contract
# ---------------------------------------------------------------------------

def test_every_stream_metric_declares_scope_and_contract(model: dm.DocumentModel) -> None:
    metrics = sm.stream_metrics(model)
    assert set(metrics) == {"S-CAP-01", "S-NUM-02", "S-REF-03",
                            "S-SIZ-04", "S-CAPL-05"}
    required = {"value", "n", "denominator", "unit", "state", "method",
                "metric_spec", "evidence", "warnings", "scope"}
    for metric_id, record in metrics.items():
        assert required <= set(record), metric_id
        assert record["metric_spec"] == metric_id
        assert record["scope"], metric_id
        for name in record["scope"]:
            assert name in {s.value for s in dm.Stream}, (metric_id, name)
        assert "prose" not in record["scope"], \
            f"{metric_id}: stream metrics must not claim the prose stream"


def test_stream_metrics_are_deterministic(model: dm.DocumentModel) -> None:
    first = sm.stream_metrics(model)
    second = sm.stream_metrics(model)
    assert json.dumps(first, ensure_ascii=False, sort_keys=True) == \
        json.dumps(second, ensure_ascii=False, sort_keys=True)


def test_unavailable_records_are_explicit_not_silent() -> None:
    """When the base artifact cannot be parsed, every stream metric must still be
    reported - as explicit "not measured" records, never as absent ones."""
    records = sm.unavailable_records("CANONICAL_UNPARSEABLE")
    assert set(records) == {"S-CAP-01", "S-NUM-02", "S-REF-03",
                            "S-SIZ-04", "S-CAPL-05"}
    for metric_id, record in records.items():
        assert record["metric_spec"] == metric_id
        assert record["value"] is None and record["n"] == 0
        assert "CANONICAL_UNPARSEABLE" in record["warnings"]
        assert record["scope"] == list(sm._SCOPE_OF_METRIC[metric_id])
        assert record["state"] == "OBSERVED" and record["method"] == "rule"


# ---------------------------------------------------------------------------
# 5. Inventory structure: image resolution + caption length (D-1)
# ---------------------------------------------------------------------------

def _png_bytes(width: int, height: int) -> bytes:
    import struct
    ihdr = struct.pack(">II", width, height) + bytes([8, 6, 0, 0, 0])
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr
            + b"\x00\x00\x00\x00")


def _jpeg_bytes(width: int, height: int) -> bytes:
    import struct
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
    sof0 = (b"\xff\xc0" + struct.pack(">H", 17) + bytes([8])
            + struct.pack(">HH", height, width) + bytes([3]) + b"\x00" * 6)
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xd9"


def _gif_bytes(width: int, height: int) -> bytes:
    import struct
    return b"GIF89a" + struct.pack("<HH", width, height) + b"\x00" * 4


def test_image_resolution_metric_reads_headers(tmp_path: Path) -> None:
    """S-SIZ-04: figure images must be measured from their own headers, with the
    unreadable ones reported instead of silently dropped."""
    auto = tmp_path / "auto"
    (auto / "images").mkdir(parents=True)
    (auto / "images" / "big.png").write_bytes(_png_bytes(1200, 800))
    (auto / "images" / "small.jpg").write_bytes(_jpeg_bytes(400, 300))
    (auto / "images" / "tiny.gif").write_bytes(_gif_bytes(100, 100))
    model = _write(tmp_path, "p5_content_list.json", [
        _block("image", img_path="images/big.png",
               image_caption=["Figure 1", "Big"]),
        _block("image", img_path="images/small.jpg",
               image_caption=["Figure 2", "Small"]),
        _block("image", img_path="images/tiny.gif",
               image_caption=["Figure 3", "Tiny"]),
        _block("image", img_path="images/missing.png",
               image_caption=["Figure 4", "Gone"]),
    ])
    record = sm.image_resolution(model)
    assert record["metric_spec"] == "S-SIZ-04"
    assert record["scope"] == ["figures"]
    assert record["n"] == 3 and record["denominator"] == 3   # the missing one is not measured
    assert record["value"] == pytest.approx(1 / 3, abs=1e-6)  # only the 1200px one is adequate
    assert record["unit"] == "ratio"
    sizes = {item["img_path"]: (item["width"], item["height"])
             for item in record["evidence"]["images"]}
    assert sizes["images/big.png"] == (1200, 800)
    assert sizes["images/small.jpg"] == (400, 300)
    assert sizes["images/tiny.gif"] == (100, 100)
    assert record["evidence"]["unreadable"] == ["images/missing.png"]
    assert "IMAGE_UNREADABLE" in record["warnings"]
    assert record["evidence"]["median_width"] == 400
    assert record["evidence"]["min_width_required"] == sm._MIN_IMAGE_WIDTH
    for sample in record["evidence"]["sample"]:
        assert sample["block_index"] in {0, 1, 2}
        assert sample["field"] == "img_path"
        assert sample["excerpt"]


def test_image_resolution_is_null_without_figures(tmp_path: Path) -> None:
    record = sm.image_resolution(_write(tmp_path, "p6_content_list.json", [
        _block("text", text="Only prose.")]))
    assert record["value"] is None and record["n"] == 0
    assert "NO_FIGURES" in record["warnings"]
    # the evidence shape must not depend on whether anything was measurable
    assert record["evidence"]["median_width"] is None
    assert record["evidence"]["min_width_required"] == sm._MIN_IMAGE_WIDTH


def test_caption_length_reports_the_median(tmp_path: Path) -> None:
    """S-CAPL-05: caption length is a pure inventory fact (characters, so it is
    language-agnostic - and therefore NOT comparable across languages)."""
    model = _write(tmp_path, "p7_content_list.json", [
        _block("image", img_path="a.png", image_caption=["Figure 1", "x" * 10]),
        _block("image", img_path="b.png", image_caption=["Figure 2", "y" * 50]),
        _block("table", table_body="<table></table>",
               table_caption=["Table 1", "z" * 90]),
        _block("text", text="No caption here."),
    ])
    record = sm.caption_length(model)
    assert record["metric_spec"] == "S-CAPL-05"
    assert record["scope"] == ["figures", "tables"]
    assert record["n"] == 3
    assert record["unit"] == "characters"
    # lengths: 12 ("Figure 1" + 10 x's) is wrong on purpose -> the caption is joined
    lengths = sorted(item["chars"] for item in record["evidence"]["lengths"])
    assert lengths == sorted([len("Figure 1 " + "x" * 10),
                              len("Figure 2 " + "y" * 50),
                              len("Table 1 " + "z" * 90)])
    assert record["value"] == pytest.approx(lengths[1], abs=1e-6)   # median
    assert record["evidence"]["min"] == lengths[0]
    assert record["evidence"]["max"] == lengths[-1]
    for sample in record["evidence"]["sample"]:
        assert sample["field"] in {"image_caption", "table_caption"}
        assert sample["excerpt"]


def test_caption_length_is_null_without_captions(tmp_path: Path) -> None:
    record = sm.caption_length(_write(tmp_path, "p8_content_list.json", [
        _block("image", img_path="a.png")]))
    assert record["value"] is None and record["n"] == 0
    assert "NO_CAPTIONS" in record["warnings"]
