#!/usr/bin/env python3
"""Tests for the corpus audit tool (data/test-corpora.json + audit_corpus.py)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import audit_corpus as ac  # noqa: E402


def _tiny_corpus(root: Path) -> Path:
    """One Chinese paper with a real prose section (front_matter is dropped)."""
    d = root / "P1" / "mineru" / "p1" / "auto"
    d.mkdir(parents=True)
    blocks = [
        {"type": "text", "text_level": 2, "text": "1 引言"},
        {"type": "text", "text": "本文提出的方法可能有效，因此通常优先考虑。" * 4},
        {"type": "text", "text_level": 2, "text": "2 方法"},
        {"type": "text", "text": "构建模型并求解优化问题，稳定性较好。" * 4},
    ]
    (d / "p1_content_list.json").write_text(json.dumps(blocks, ensure_ascii=False),
                                            encoding="utf-8")
    return root


def _entry_from_inspect(corpus: Path, out: Path) -> dict:
    """Build a registry entry the honest way: inspect first, then record."""
    report = ac.inspect_unregistered(corpus, out)
    return {
        "name": "tiny-zh",
        "path": str(corpus),
        "corpus_id": report["corpus_id"],
        "n_papers": report["n_papers"],
        "skipped": report["skipped"],
        "recorded_with": {
            "profiler_version": report["toolchain"]["profiler_version"],
            "schema_version": report["toolchain"]["schema_version"],
            "metric_spec_version": report["toolchain"]["metric_spec_version"],
            "text_metrics_version": report["toolchain"]["text_metrics_version"],
            "lexicon_version": report["toolchain"]["lexicon_version"],
            "lexicon_language": "zh",
            "lexicon_release_version": (report["lexicon_releases"] or {}).get("zh", {}).get("version"),
            "lexicon_fingerprint": (report["lexicon_releases"] or {}).get("zh", {}).get("fingerprint"),
        },
        "expected_metrics": report["expected_metrics"],
    }


def test_inspect_then_audit_matches(tmp_path: Path):
    corpus = _tiny_corpus(tmp_path / "corpus")
    entry = _entry_from_inspect(corpus, tmp_path / "probe")
    report = ac.audit(entry, tmp_path / "audit")
    assert report["verdict"] == "match", report["findings"]
    assert report["cause"] is None
    assert report["n_drifted"] == 0
    # every recorded metric is compared, not just the first one
    assert len(report["metrics"]) == len(entry["expected_metrics"])


def test_audit_reports_inputs_changed_when_corpus_id_differs(tmp_path: Path):
    corpus = _tiny_corpus(tmp_path / "corpus")
    entry = _entry_from_inspect(corpus, tmp_path / "probe")
    entry["corpus_id"] = "0" * 64
    report = ac.audit(entry, tmp_path / "audit")
    assert report["verdict"] == "drift"
    # the cause must be diagnosable, not just "something changed"
    assert report["cause"] == "inputs_changed"


def test_audit_reports_version_change_as_explained_drift(tmp_path: Path):
    corpus = _tiny_corpus(tmp_path / "corpus")
    entry = _entry_from_inspect(corpus, tmp_path / "probe")
    entry["recorded_with"]["profiler_version"] = "0.0-not-this"
    report = ac.audit(entry, tmp_path / "audit")
    assert report["verdict"] == "drift"
    assert report["cause"] == "code_or_word_list_changed"
    # the metrics themselves still match: only the version moved
    assert all(row["status"] == "match" for row in report["metrics"])


def test_audit_reports_unexplained_drift_for_a_wrong_metric(tmp_path: Path):
    corpus = _tiny_corpus(tmp_path / "corpus")
    entry = _entry_from_inspect(corpus, tmp_path / "probe")
    first = sorted(entry["expected_metrics"])[0]
    entry["expected_metrics"][first] = 999.0
    report = ac.audit(entry, tmp_path / "audit")
    assert report["verdict"] == "drift"
    # corpus id and versions are unchanged -> this is the case worth chasing
    assert report["cause"] == "unexplained_drift"


def test_find_entry_unknown_name_exits():
    registry = {"corpora": [{"name": "a"}, {"name": "b"}]}
    with pytest.raises(SystemExit) as excinfo:
        ac.find_entry(registry, "nope")
    assert "a, b" in str(excinfo.value)


def test_load_registry_reads_the_shipped_file():
    registry = ac.load_registry()
    names = sorted(entry["name"] for entry in registry["corpora"])
    assert names == ["vrp-en", "ycgl-zh"]
    for entry in registry["corpora"]:
        assert entry["corpus_id"] and entry["recorded_with"] and entry["expected_metrics"]
