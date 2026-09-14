#!/usr/bin/env python3
"""Stage 1.5 text-layer probe: make two silent PDF corruptions visible.

Why this exists
---------------
Two classes of damage happen entirely inside the `PDF -> content_list.json` hop
and are invisible downstream because nothing independently checks that hop:

1. **Spaces lost inside English segments** of Chinese journals. Measured on the
   10-paper 《运筹与管理》 corpus: the PDF text layer contains **0** runs of 15+
   letters, while the canonical text contains **58** such runs — the collapse is
   introduced by the conversion, and every word-level English metric (word
   count, sentence length, passive rate) is wrong on a Chinese corpus, silently.
2. **Digits / punctuation lost from CNKI PDFs.** Measured on the same corpus:
   **9 of 10 converted papers lose 73–90 %** of their digits (the issue that
   prompted this work reported ~52 %; the real figure is worse). CNKI encodes
   digits in a custom full-width font (\uFF10-\uFF19), the PDF text layer keeps
   them, and the conversion drops them (MinerU issue #5330).

This probe re-reads the PDF's own text layer (no layout model, no OCR, no GPU)
and compares it against the canonical text, then writes `_textlayer_probe.json`.

Red lines (do not break these)
------------------------------
* **The output never feeds `canonical_text()`.** It is side-band evidence only,
  so `paper-metrics` keeps its pure-stdlib / zero-LLM / byte-reproducible
  contract. Nothing here may become an input to a metric.
* **A scanned PDF (no text layer) is `not_applicable`, never `ok`, never 0.**
  "Not measured" and "measured as zero" are different states.
* **No canonical text means `pdf_only`, not `ok`**: without a comparison we have
  not checked anything, and reporting `ok` would be a false pass.
* **A probe failure must never block the conversion pipeline**: the caller treats
  every exception as a warning (same rule as the existing
  "single item fails -> null + note" convention).
* Only permissive, model-free libraries: `pdfplumber` (MIT). Do **not** add
  PyMuPDF (AGPL) here.

Determinism: the same PDF + the same canonical text + the same pdfplumber
version produce a byte-identical JSON (keys sorted, no timestamps, no absolute
paths). `pdfplumber_version` is recorded because text-layer extraction is
version-dependent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

PROBE_SPEC = "textlayer-probe/1"
PROBE_VERSION = "1.3"
#: 1.3 records canonical_sha256 — the hash of the comparison text itself.  The
#: source label alone cannot tell whether the *content* changed under the same
#: label (a re-conversion rewrites content_list.json while keeping its name), so
#: a cached result could otherwise be reused for a different comparison.
#: 1.2 records canonical_source — which artifact the comparison used.  The field
#: exists because that choice decides whether the damage is visible at all: on the
#: Chinese corpus the same PDF measures 2.1% digit loss against the merged
#: markdown, but 55.5% against the MinerU content_list.json that the metrics layer
#: actually reads.  A verdict without that label is ambiguous.

#: Below this many characters the PDF has no usable text layer (scan / image
#: only) and every comparison is meaningless -> not_applicable.
MIN_TEXT_LAYER_CHARS = 200
#: Warn when more than this share of the PDF-side digits is missing from the
#: canonical text. Healthy conversions measure ~0.00x; CNKI PDFs measure 0.73+.
DIGIT_LOSS_WARN = 0.02
#: 15 letters is longer than a real English word: such a run is a missing-space
#: artefact. Measured baseline on the Chinese corpus: PDF side 0, canonical
#: side 58 across 10 papers, so the *delta* is the decisive signal.
UNSPACED_RUN_MIN = 15
#: Tolerance before the delta counts as a defect: a single legitimate long
#: compound (e.g. a German term or a chemical name) is not a broken conversion.
UNSPACED_RUNS_WARN = 2

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_DIGIT_RE = re.compile(r"[0-9]")
_FULLWIDTH_DIGIT_RE = re.compile(r"[\uff10-\uff19]")
_PUNCT_RE = re.compile(r"[.,;:!?()\[\]{}<>/\\%$#@&*+=~^|_\-\u2014\u2018\u2019\u201c\u201d]")
_CJK_PUNCT_RE = re.compile(r"[\u3000-\u303f\uff01-\uff5e]")
_LONG_UNSPACED_RE = re.compile(r"[A-Za-z]{%d,}" % UNSPACED_RUN_MIN)
_ALPHA_RE = re.compile(r"[A-Za-z]")


def sha256_file(path: Path) -> str:
    """sha256 of the raw bytes, so a probe result is addressable."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def text_layer_counts(text: str) -> dict[str, int]:
    """Raw counts of every class this probe compares (order-independent).

    Digits are counted in both widths: the CNKI failure mode *is* a full-width
    digit the converter drops, so counting only ASCII digits would hide it.
    """
    return {
        "chars": len(text),
        "cjk": len(_CJK_RE.findall(text)),
        "alpha": len(_ALPHA_RE.findall(text)),
        "spaces": len(re.findall(r"[ \t]", text)),
        "digits": len(_DIGIT_RE.findall(text)),
        "fullwidth_digits": len(_FULLWIDTH_DIGIT_RE.findall(text)),
        "punct": len(_PUNCT_RE.findall(text)) + len(_CJK_PUNCT_RE.findall(text)),
        "long_unspaced_runs": len(_LONG_UNSPACED_RE.findall(text)),
    }


def compare_text_layers(pdf_text: str, canonical_text: str | None) -> dict[str, Any]:
    """Pure comparison of the PDF text layer against the canonical text.

    No I/O, so this is the unit-testable core. `canonical_text=None` means
    "not compared" and is reported as `pdf_only` rather than being silently
    treated as a pass.
    """
    pdf_counts = text_layer_counts(pdf_text)
    if pdf_counts["chars"] < MIN_TEXT_LAYER_CHARS:
        return {
            "pdf": pdf_counts,
            "canonical": None,
            "canonical_compared": False,
            "digit_loss_rate": None,
            "punct_loss_rate": None,
            "unspaced_runs_introduced": None,
            "verdict": "not_applicable",
            "warnings": ["NO_TEXT_LAYER"],
        }
    if canonical_text is None:
        return {
            "pdf": pdf_counts,
            "canonical": None,
            "canonical_compared": False,
            "digit_loss_rate": None,
            "punct_loss_rate": None,
            "unspaced_runs_introduced": None,
            "verdict": "pdf_only",
            "warnings": ["CANONICAL_NOT_PROVIDED"],
        }

    canonical_counts = text_layer_counts(canonical_text)
    digits_pdf = pdf_counts["digits"] + pdf_counts["fullwidth_digits"]
    digits_canonical = canonical_counts["digits"] + canonical_counts["fullwidth_digits"]
    warnings: list[str] = []
    digit_loss_rate: float | None = None
    if digits_pdf:
        # Clamp at 0: a converter may legitimately add digits (page numbers), and
        # a negative "loss" would read as a probe bug.
        loss = max(0.0, (digits_pdf - digits_canonical) / digits_pdf)
        digit_loss_rate = round(loss, 6)
        if loss > DIGIT_LOSS_WARN:
            warnings.append("DIGIT_LOSS_HIGH")
    punct_loss_rate: float | None = None
    if pdf_counts["punct"]:
        punct_loss_rate = round(
            max(0.0, (pdf_counts["punct"] - canonical_counts["punct"]) / pdf_counts["punct"]), 6)

    # The collapse is *introduced* by the conversion: compare the two sides.
    introduced = canonical_counts["long_unspaced_runs"] - pdf_counts["long_unspaced_runs"]
    if introduced > UNSPACED_RUNS_WARN:
        warnings.append("UNSPACED_ENGLISH_RUNS")

    return {
        "pdf": pdf_counts,
        "canonical": canonical_counts,
        "canonical_compared": True,
        "digit_loss_rate": digit_loss_rate,
        "punct_loss_rate": punct_loss_rate,
        "unspaced_runs_introduced": introduced,
        "verdict": "warn" if warnings else "ok",
        "warnings": sorted(set(warnings)),
    }


def read_pdf_text_layer(pdf_path: Path) -> tuple[str, int]:
    """(text, page_count) from the PDF's own text layer.

    Isolated from the comparison so a caller can degrade to `not_applicable`
    when pdfplumber is missing or the file is unreadable, without losing the
    rest of the batch.
    """
    import pdfplumber  # imported lazily: the pure part stays dependency-free

    parts: list[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        pages = len(pdf.pages)
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    return "\n".join(parts), pages


def pdfplumber_version() -> str | None:
    try:
        import importlib.metadata as md

        return md.version("pdfplumber")
    except Exception:  # pragma: no cover - metadata always present in practice
        return None


def probe_pdf(pdf_path: Path, canonical_text: str | None = None,
              canonical_source: str | None = None) -> dict[str, Any]:
    """Full probe of one PDF: text layer -> counts -> comparison -> record.

    canonical_source names the artifact the canonical text came from (for example
    "mineru_content_list" or "merged_markdown"), because the same PDF can measure
    very different loss depending on which side of the hop is used as the
    comparison, and a bare warn/ok would hide that choice.
    """
    canonical_sha256 = (
        hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()
        if isinstance(canonical_text, str) else None
    )
    base: dict[str, Any] = {
        "probe_spec": PROBE_SPEC,
        "probe_version": PROBE_VERSION,
        "pdfplumber_version": pdfplumber_version(),
        # File name only: an absolute path would differ per host and break the
        # byte-stability of a corpus-level record.
        "pdf_name": pdf_path.name,
        "pdf_sha256": sha256_file(pdf_path),
        "canonical_source": canonical_source,
        "canonical_sha256": canonical_sha256,
    }
    try:
        text, pages = read_pdf_text_layer(pdf_path)
    except Exception as exc:  # noqa: BLE001 - a probe must never break the batch
        base.update({
            "pages": None,
            "verdict": "not_applicable",
            "warnings": ["TEXT_LAYER_UNREADABLE"],
            "error": f"{type(exc).__name__}: {exc}",
        })
        return base
    base["pages"] = pages
    base.update(compare_text_layers(text, canonical_text))
    return base


def render_json(record: dict[str, Any]) -> str:
    """Deterministic JSON text (sorted keys, 2-space indent, trailing newline)."""
    return json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Stage 1.5 text-layer probe (side-band; never feeds canonical_text)")
    parser.add_argument("--pdf", required=True, type=Path, help="PDF to probe")
    parser.add_argument("--canonical", type=Path, default=None,
                        help="canonical text file to compare against (optional)")
    parser.add_argument("--canonical-source", default=None, metavar="LABEL",
                        help="name of the artifact given to --canonical "
                             "(e.g. mineru_content_list); recorded in the output")
    parser.add_argument("--out", type=Path, default=None,
                        help="write _textlayer_probe.json here (default: stdout)")
    args = parser.parse_args(argv)

    canonical_text = None
    if args.canonical is not None:
        canonical_text = args.canonical.read_text(encoding="utf-8")
    record = probe_pdf(args.pdf, canonical_text, args.canonical_source)
    payload = render_json(record)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
