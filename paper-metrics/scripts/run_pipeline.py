#!/usr/bin/env python3
"""One command from PDFs to writing-feature metrics (closes R5).

This is a thin orchestrator that chains two skills without duplicating either:

  1. paper-reader   PDF -> <papers>/paper-analysis/<stem>/{marker,mineru,_META.json}
                    (GPU-bound, minutes per paper, resumable)
  2. this metric layer   paper-analysis -> the five deterministic metric artifacts
                    (pure stdlib, seconds per corpus)

Why it lives next to the metric layer rather than inside paper-reader: the
metric layer's input contract is "a canonical corpus directory", not "a PDF".
Anyone who already has paper-analysis/ (or converted with another tool) can run
profile_papers.py directly and never touch this file.

Usage:
    cd ~/.claude/skills && uv run python paper-metrics/scripts/run_pipeline.py \\
        --papers /path/to/pdfs --out /path/to/metrics-out [--analysis-dir DIR] \\
        [--engines both|marker|mineru] [--no-resume] [--skip-convert] [--verify] [--dry-run]

Exit codes:
    0  success
    1  a downstream stage failed (paper-reader or the profiler)
    2  bad input (no PDFs found, missing dependency script, ...)

Reproducibility note: the bit-level guarantee still belongs to the metric layer
(Canonical Document -> metrics). The PDF -> Canonical stage is paper-reader's and
is attributed, not reproduced: its engine versions and the PDF hash are recorded
in each paper's _META.json when paper-reader supports it.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
PAPER_READER = REPO_ROOT / "paper-reader" / "scripts" / "paper_reader.py"
PROFILER = SCRIPT_DIR / "profile_papers.py"
DEFAULT_ANALYSIS_DIRNAME = "paper-analysis"


# Engine-side copies that paper-reader leaves inside the canonical corpus.
# They are conversion intermediates, not submitted papers.
_INTERMEDIATE_PDF_SUFFIXES = ("_origin.pdf",)
_ANALYSIS_DIRNAME = "paper-analysis"


def find_pdfs(papers_dir: Path, exclude_dir: Path | None = None) -> list[Path]:
    """Source PDFs under papers_dir, in a stable order.

    Two exclusions, both learned the hard way:
      * anything inside the canonical corpus (paper-analysis/...) — those are
        engine outputs/origin copies, and counting them as "papers" inflates the
        corpus and re-converts the same document;
      * engine-intermediate names such as <stem>_origin.pdf.

    Pass exclude_dir to exclude an explicit corpus location (e.g. --analysis-dir
    pointing somewhere else under papers_dir).
    """
    if not papers_dir.is_dir():
        return []
    excluded_root = None
    if exclude_dir is not None:
        try:
            exclude_dir.resolve().relative_to(papers_dir.resolve())
            excluded_root = exclude_dir.resolve()
        except ValueError:
            excluded_root = None
    out: list[Path] = []
    for p in papers_dir.rglob("*"):
        if not p.is_file() or p.suffix.lower() != ".pdf":
            continue
        parts = p.relative_to(papers_dir).parts[:-1]
        if _ANALYSIS_DIRNAME in parts:
            continue
        if excluded_root is not None:
            try:
                p.resolve().relative_to(excluded_root)
                continue
            except ValueError:
                pass
        if p.name.lower().endswith(_INTERMEDIATE_PDF_SUFFIXES):
            continue
        out.append(p)
    return sorted(out, key=lambda p: p.relative_to(papers_dir).as_posix())


def build_commands(papers_dir: Path, analysis_dir: Path, out_dir: Path,
                   engines: str = "both", resume: bool = True,
                   skip_convert: bool = False, verify: bool = False
                   ) -> list[list[str]]:
    """Return the exact command lines to run, in order (pure, testable)."""
    cmds: list[list[str]] = []
    if not skip_convert:
        convert = [sys.executable, str(PAPER_READER), str(papers_dir),
                   "--batch", "--engines", engines]
        if resume:
            convert.append("--resume")
        cmds.append(convert)
    profile = [sys.executable, str(PROFILER), "--corpus", str(analysis_dir),
               "--out", str(out_dir)]
    if verify:
        profile.append("--verify")
    cmds.append(profile)
    return cmds


def _run(cmd: list[str], dry_run: bool) -> int:
    printable = " ".join(cmd)
    print(f"[run_pipeline] $ {printable}", flush=True)
    if dry_run:
        return 0
    return subprocess.run(cmd, cwd=str(REPO_ROOT)).returncode


def main() -> int:
    ap = argparse.ArgumentParser(
        description="PDF directory -> paper-analysis/ -> writing-feature metrics.",
    )
    ap.add_argument("--papers", required=True, type=Path,
                    help="directory containing the source PDFs")
    ap.add_argument("--out", "--output", dest="out", required=True, type=Path,
                    help="output directory for the five metric artifacts")
    ap.add_argument("--analysis-dir", type=Path, default=None,
                    help=f"canonical corpus dir (default: <papers>/{DEFAULT_ANALYSIS_DIRNAME})")
    ap.add_argument("--engines", choices=["both", "marker", "mineru"], default="both",
                    help="paper-reader engines (default: both)")
    ap.add_argument("--no-resume", dest="resume", action="store_false",
                    help="reconvert everything instead of resuming")
    ap.add_argument("--skip-convert", action="store_true",
                    help="skip paper-reader and profile an existing canonical corpus")
    ap.add_argument("--verify", action="store_true",
                    help="after profiling, re-run and assert the fingerprint files are identical")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the commands without executing them")
    args = ap.parse_args()

    papers_dir = args.papers.resolve()
    analysis_dir = (args.analysis_dir.resolve() if args.analysis_dir
                    else papers_dir / DEFAULT_ANALYSIS_DIRNAME)
    out_dir = args.out.resolve()

    if not PROFILER.is_file():
        print(f"[run_pipeline] ERROR: metric layer not found at {PROFILER}", file=sys.stderr)
        return 2
    if not args.skip_convert and not PAPER_READER.is_file():
        print(f"[run_pipeline] ERROR: paper-reader not found at {PAPER_READER}; "
              f"use --skip-convert if the corpus is already converted", file=sys.stderr)
        return 2

    if args.skip_convert:
        # --skip-convert exists precisely for "the corpus is already converted
        # and the submission PDFs are gone". Demanding PDFs here would defeat it.
        if not analysis_dir.is_dir():
            print(f"[run_pipeline] ERROR: --skip-convert needs an existing canonical "
                  f"corpus at {analysis_dir}", file=sys.stderr)
            return 2
        pdfs = []
        excluded_n = 0
        print(f"[run_pipeline] using existing corpus: {analysis_dir}")
    else:
        all_pdfs = [p for p in papers_dir.rglob("*")
                    if p.is_file() and p.suffix.lower() == ".pdf"] if papers_dir.is_dir() else []
        pdfs = find_pdfs(papers_dir, exclude_dir=analysis_dir)
        excluded_n = len(all_pdfs) - len(pdfs)
        if excluded_n:
            print(f"[run_pipeline] excluded {excluded_n} engine/intermediate PDF(s) "
                  f"(inside {DEFAULT_ANALYSIS_DIRNAME}/ or *_origin.pdf)")
        if not pdfs:
            print(f"[run_pipeline] ERROR: no source PDFs under {papers_dir}", file=sys.stderr)
            if excluded_n:
                print(f"[run_pipeline] hint: all {excluded_n} PDF(s) found were engine "
                      f"intermediates inside {DEFAULT_ANALYSIS_DIRNAME}/ or named *_origin.pdf. "
                      f"The submission PDFs are not in this directory — if the corpus is "
                      f"already converted, re-run with --skip-convert.", file=sys.stderr)
            return 2
    if not shutil.which(sys.executable) and not Path(sys.executable).exists():
        print(f"[run_pipeline] ERROR: interpreter not executable: {sys.executable}",
              file=sys.stderr)
        return 2

    if pdfs:
        print(f"[run_pipeline] papers     : {papers_dir} ({len(pdfs)} PDFs)")
    print(f"[run_pipeline] canonical  : {analysis_dir}")
    print(f"[run_pipeline] metrics out: {out_dir}")
    if args.skip_convert:
        print("[run_pipeline] stage 1 skipped (--skip-convert)")

    cmds = build_commands(papers_dir, analysis_dir, out_dir, engines=args.engines,
                          resume=args.resume, skip_convert=args.skip_convert,
                          verify=args.verify)
    for i, cmd in enumerate(cmds, start=1):
        rc = _run(cmd, args.dry_run)
        if rc != 0:
            stage = "paper-reader" if i == 1 and not args.skip_convert else "profiler"
            print(f"[run_pipeline] FAILED: stage {i} ({stage}) exited with {rc}",
                  file=sys.stderr)
            return rc if rc > 0 else 1

    if not args.dry_run:
        print("[run_pipeline] done. Artifacts:")
        for name in ("_domain_profile.json", "_domain_profile.md", "_corpus_summary.json",
                     "_per_paper_metrics.jsonl", "_run_meta.json"):
            path = out_dir / name
            print(f"  {'OK ' if path.exists() else 'MISSING '} {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
