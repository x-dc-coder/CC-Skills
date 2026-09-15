#!/usr/bin/env python3
"""Tests for canonical_import: turning non-PDF sources into canonical blocks.

The properties locked here are the reason the module exists at all:

- prose survives the round trip (an importer that silently drops text would make
  every downstream metric a lie);
- the output layout is the one discover_papers_detailed() walks, so an imported
  corpus is indistinguishable from a converted one as far as the profiler is
  concerned;
- re-importing is byte-identical, because corpus ids (and every pinned expected
  value behind them) are hashes of these files.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import canonical_import as ci
import doc_model
import profile_papers

#: No backticks anywhere in this source file: fences are built from chr(96).
FENCE = chr(96) * 3

_ZH_PROSE = (
    "本研究针对车辆路径问题中的多配送站情形展开分析。"
    "已有文献大多假设单一配送站，而实际物流网络常包含多个配送中心。"
    "本文提出一种基于列生成的求解框架，并通过实验验证其有效性。"
)


def _blocks_of(text: str) -> list[dict]:
    return ci.markdown_to_blocks(text)


def _types(blocks: list[dict]) -> list[str]:
    return [str(b.get("type")) for b in blocks]


# ---------------------------------------------------------------------------
# Markdown structure
# ---------------------------------------------------------------------------

def test_headings_become_levelled_text_blocks() -> None:
    blocks = _blocks_of("# Title\n\n## Method\n\n### Sub\n\ntext")
    assert [(b.get("type"), b.get("text_level")) for b in blocks] == [
        ("text", 1), ("text", 2), ("text", 3), ("text", None)]


def test_paragraphs_become_prose_and_headings_are_separate() -> None:
    blocks = _blocks_of("first paragraph\n\nsecond paragraph")
    assert _types(blocks) == ["text", "text"]
    assert [b.get("text") for b in blocks] == ["first paragraph", "second paragraph"]


def test_soft_wrapped_lines_join_into_one_paragraph() -> None:
    blocks = _blocks_of("line one\nline two\n\nafter blank")
    assert [b.get("text") for b in blocks] == ["line one line two", "after blank"]


def test_code_fence_keeps_language_tag_out_of_prose() -> None:
    blocks = _blocks_of(FENCE + "python\nx = 1\ny = 2\n" + FENCE)
    assert _types(blocks) == ["code"]
    assert blocks[0]["text"] == "x = 1\ny = 2"


def test_display_math_same_line_and_multi_line() -> None:
    blocks = _blocks_of("$$a = b + c$$\n\nintro\n\n$$\nx = y\nz = w\n$$")
    assert _types(blocks) == ["equation", "text", "equation"]
    assert blocks[0]["text"] == "a = b + c"
    assert blocks[2]["text"] == "x = y\nz = w"


def test_list_becomes_list_items_block() -> None:
    blocks = _blocks_of("- one\n- two\n\n1. first\n2. second")
    assert _types(blocks) == ["list", "list"]
    assert blocks[0]["list_items"] == ["one", "two"]
    assert blocks[1]["list_items"] == ["first", "second"]


def test_image_line_becomes_figure_block_with_caption() -> None:
    blocks = _blocks_of("![framework](img/framework.png)")
    assert blocks == [{"type": "image", "img_path": "img/framework.png",
                       "img_caption": ["framework"]}]


def test_table_caption_is_paired_not_dropped() -> None:
    md = "Table 1: results\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
    blocks = _blocks_of(md)
    table = [b for b in blocks if b.get("type") == "table"]
    assert len(table) == 1
    assert table[0]["table_caption"] == ["Table 1: results"]


def test_table_cell_text_round_trips_through_doc_model() -> None:
    blocks = _blocks_of("| alpha | beta |\n|---|---|\n| 1 | 2 |\n")
    table = blocks[0]
    cells = doc_model.html_to_text(str(table["table_body"]))
    assert cells.split() == ["alpha", "beta", "1", "2"]


def test_escaped_pipe_inside_cell_survives() -> None:
    blocks = _blocks_of("| a | b |\n|---|---|\n| x \\| y | z |\n")
    table = blocks[0]
    cells = doc_model.html_to_text(str(table["table_body"])).split()
    assert cells == ["a", "b", "x", "|", "y", "z"]


def test_horizontal_merge_becomes_colspan_without_phantom_cells() -> None:
    blocks = _blocks_of("| a | b | c |\n|---|---|---|\n| merged<<3 | |\n")
    html_text = str(blocks[0]["table_body"])
    assert 'colspan="3"' in html_text
    # header row keeps its 3 cells; the merged row is a single cell, and the
    # padding cells the marker absorbed must not reappear as empty <td>
    assert html_text.count("<td") == 4


def test_vertical_merge_becomes_rowspan() -> None:
    md = (
        "| a | b |\n|---|---|\n"
        "| top | 1 |\n| ^^ | 2 |\n"
    )
    blocks = _blocks_of(md)
    html_text = str(blocks[0]["table_body"])
    assert 'rowspan="2"' in html_text
    # header(2) + top+1 + 2 = 5 cells; the continuation row has one cell, not two
    assert html_text.count("<td") == 5

def test_explicit_rowspan_marker_counts_rows() -> None:
    md = (
        "| a | b |\n|---|---|\n"
        "| head<<2 | 1 |\n"
    )
    blocks = _blocks_of(md)
    html_text = str(blocks[0]["table_body"])
    assert 'colspan="2"' in html_text
    assert html_text.count("<td") == 3

def test_level_one_headings_do_not_start_sections() -> None:
    """A '#' everywhere document has no sections; canonical_text() is empty.

    This is the trap the importer's heading mapping exists to avoid: '#' is the
    paper title, '##' is a section.  Locked here because the failure mode is
    silent - the profiler runs fine and reports all-null metrics.
    """
    blocks = _blocks_of("# Intro\n\n" + _ZH_PROSE)
    assert _blocks_of("## Intro\n\n" + _ZH_PROSE)[0]["text_level"] == 2
    assert blocks[0]["text_level"] == 1


def test_orphan_caption_still_becomes_prose() -> None:
    """A caption that never meets its table must not vanish from the text."""
    blocks = _blocks_of("Table 5: nothing follows\n\nsome prose")
    texts = [b.get("text") for b in blocks]
    assert "Table 5: nothing follows" in texts


def test_yaml_front_matter_is_kept_as_prose() -> None:
    blocks = _blocks_of("---\ntitle: Demo\nauthor: A. Nother\n---\n\n# Intro")
    front_texts = [b.get("text") for b in blocks if b.get("text_level") is None]
    assert "title: Demo" in front_texts
    assert blocks[-1]["text_level"] == 1


def test_slim_drops_image_blocks() -> None:
    full = _blocks_of("prose\n\n![f](a.png)\n\nmore")
    slim = ci.markdown_to_blocks("prose\n\n![f](a.png)\n\nmore", slim=True)
    assert _types(full) == ["text", "image", "text"]
    assert _types(slim) == ["text", "text"]


def test_chinese_prose_is_preserved_verbatim() -> None:
    blocks = _blocks_of("# 引言\n\n" + _ZH_PROSE)
    assert blocks[1]["text"] == _ZH_PROSE


# ---------------------------------------------------------------------------
# docx
# ---------------------------------------------------------------------------

def test_docx_headings_paragraphs_and_table(tmp_path: Path) -> None:
    import docx as python_docx

    source = tmp_path / "paper.docx"
    document = python_docx.Document()
    document.add_heading("Introduction", level=1)
    document.add_paragraph("Some English prose about the method.")
    table = document.add_table(rows=2, cols=2)
    for r, row in enumerate((("a", "b"), ("1", "2"))):
        for c, value in enumerate(row):
            table.rows[r].cells[c].text = value
    document.save(str(source))

    blocks = ci.docx_to_blocks(source)
    assert (blocks[0]["type"], blocks[0]["text_level"]) == ("text", 1)
    assert blocks[1]["text"] == "Some English prose about the method."
    table_html = str(blocks[2]["table_body"])
    assert doc_model.html_to_text(table_html).split() == ["a", "b", "1", "2"]


# ---------------------------------------------------------------------------
# Determinism + layout + provenance
# ---------------------------------------------------------------------------

def test_import_is_byte_identical_on_rerun(tmp_path: Path) -> None:
    source = tmp_path / "s.md"
    source.write_text("# T\n\n" + _ZH_PROSE + "\n", encoding="utf-8")
    first = tmp_path / "first"
    second = tmp_path / "second"
    ci.import_file(source, first)
    ci.import_file(source, second)
    for name in ("s/mineru/s/auto/s_content_list.json", "s/_META.json"):
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_meta_records_import_not_fake_conversion(tmp_path: Path) -> None:
    source = tmp_path / "s.md"
    source.write_text("# T\n\n" + _ZH_PROSE + "\n", encoding="utf-8")
    out = tmp_path / "out"
    ci.import_file(source, out)
    meta = json.loads((out / "s" / "_META.json").read_text(encoding="utf-8"))
    assert meta["engines"] == "import"
    assert meta["marker"]["ok"] is False
    assert meta["mineru"]["ok"] is False
    assert meta["pdf_sha256"] is None
    assert all(v is None for v in meta["engine_versions"].values())
    assert meta["engine_versions_source"] == "not_applicable"
    prov = meta["import_provenance"]
    assert prov["source_format"] == "markdown"
    assert prov["source_sha256"] == ci.sha256_bytes(source.read_bytes())
    assert meta["language"] == "zh"
    assert meta["lang_source"] == "import_source_text"
    assert meta["cjk_ratio"] > 0.10


def test_language_matches_shared_rule_on_english_source(tmp_path: Path) -> None:
    source = tmp_path / "en.md"
    source.write_text("# Intro\n\nThis paper studies routing problems in depth.\n",
                      encoding="utf-8")
    out = tmp_path / "out"
    ci.import_file(source, out)
    meta = json.loads((out / "en" / "_META.json").read_text(encoding="utf-8"))
    assert meta["language"] == "en"


def test_unknown_extension_raises(tmp_path: Path) -> None:
    source = tmp_path / "s.pdf"
    source.write_bytes(b"%PDF- fake")
    with pytest.raises(ci.CanonicalImportError):
        ci.import_file(source, tmp_path / "out")


def test_empty_source_raises(tmp_path: Path) -> None:
    source = tmp_path / "empty.md"
    source.write_text("\n\n\n", encoding="utf-8")
    with pytest.raises(ci.CanonicalImportError):
        ci.import_file(source, tmp_path / "out")


# ---------------------------------------------------------------------------
# The profiler accepts an imported corpus exactly like a converted one
# ---------------------------------------------------------------------------

@pytest.fixture
def imported_corpus(tmp_path: Path) -> Path:
    source = tmp_path / "manuscript.md"
    source.write_text(
        "# Manuscript Title\n\n"
        "## Introduction\n\n" + _ZH_PROSE + "\n\n"
        "## Method\n\n" + _ZH_PROSE + "\n\n"
        "## Experiments\n\n" + _ZH_PROSE + "\n",
        encoding="utf-8")
    corpus = tmp_path / "corpus"
    ci.import_file(source, corpus, paper_id="manuscript")
    return corpus


def test_discovery_finds_imported_paper(imported_corpus: Path) -> None:
    discovery = profile_papers.discover_papers_detailed(imported_corpus)
    assert len(discovery.papers) == 1
    paper = discovery.papers[0]
    assert paper.paper_key == "manuscript"
    assert _ZH_PROSE in paper.canonical_text()
    assert paper.upstream["engines"] == "import"
    assert paper.upstream["versions_recorded"] is False


def test_upstream_language_record_is_carried_through(imported_corpus: Path) -> None:
    paper = profile_papers.discover_papers_detailed(imported_corpus).papers[0]
    assert paper.upstream["language_recorded"] == "zh"
    assert paper.upstream["language_source_recorded"] == "import_source_text"


def test_profile_runs_on_imported_corpus(imported_corpus: Path, tmp_path: Path,
                                    monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "profile-out"
    monkeypatch.setattr(sys, "argv", [
        "profile_papers.py", "--corpus", str(imported_corpus), "--out", str(out)])
    profile_papers.main()
    profile = json.loads((out / "_domain_profile.json").read_text(encoding="utf-8"))
    assert profile["corpus"]["n_papers"] == 1
    assert profile["corpus"]["id"]
    assert (out / "_per_paper_metrics.jsonl").is_file()
    assert (out / "_corpus_summary.json").is_file()
    # the imported paper's upstream record reached the audit trail intact
    per_paper = (out / "_per_paper_metrics.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(per_paper) == 1
    record = json.loads(per_paper[0])
    assert record["upstream"]["engines"] == "import"
