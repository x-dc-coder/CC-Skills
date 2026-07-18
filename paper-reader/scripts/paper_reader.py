#!/usr/bin/env python3
"""paper-reader: Marker + MinerU  PDF   +

v2    -

: paper_reader.py <pdf_path_or_dir> [--output OUT] [--engines both|marker|mineru]
                  [--pages 0-9] [--batch] [--init] [--status] [--resume] [--force]
                  [--from-manifest PATH] [--import-urls PATH] [--max-pages N]
"""

from __future__ import annotations

import argparse
import difflib
import enum
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
MARKER_BIN = SKILL_ROOT / "venvs" / "marker" / "bin" / "marker_single"
MINERU_BIN = SKILL_ROOT / "venvs" / "mineru" / "bin" / "mineru"

# ── WSL → Windows   ────────────────────────────────────────────────
_WSL = "microsoft" in os.uname().release.lower()
_WSL_MARKER_PY = r"E:\venvs\marker\Scripts\python.exe"
_WSL_MINERU_PY = r"E:\venvs\mineru\Scripts\python.exe"

# ── GPU    ⭐  OOM   ───────────────────────────────────
_BRIDGE_SCRIPTS = (Path.home() / ".claude" / "skills" / "wsl-windows-bridge" / "scripts")
if str(_BRIDGE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_BRIDGE_SCRIPTS))
from gpu_safe_subprocess import (  # noqa: E402
    GpuLimits, build_gpu_env, GpuGovernor, GpuLease, InsufficientGpuBudget,
)

_GPU_FRACTION: float = 0.4
_CPU_THREADS: int = 6
_GPU_GOVERNOR: GpuGovernor | None = None
_GPU_WAIT_TIMEOUT: float = 600.0

# ──    ─────────────────────────────────────────────────
_PIPELINE_VERSION = "2.0"
_DEFAULT_MAX_PAGES = 200


# ═══════════════════════════════════════════════════════════════════════════════
#   Enums
# ═══════════════════════════════════════════════════════════════════════════════

class ErrorType(str, enum.Enum):
    """.  enum  JSON ."""
    # 0:
    FILE_MISSING = "file_missing"
    EMPTY_FILE = "empty_file"
    NOT_A_PDF = "not_a_pdf"
    ENCRYPTED = "encrypted"
    CORRUPTED = "corrupted"
    TOO_LARGE = "too_large"
    PRECHECK_CRASHED = "precheck_crashed"
    # 1:
    CUDA_OOM = "cuda_oom"
    TIMEOUT = "timeout"
    ENGINE_CRASH = "engine_crash"
    SILENT_CRASH = "silent_crash"
    NO_OUTPUT = "no_output"
    GPU_BUDGET_UNAVAILABLE = "gpu_budget_unavailable"
    # 2:
    BOTH_ENGINES_FAILED = "both_engines_failed"
    NORMALIZE_CRASH = "normalize_crash"
    IMG_COPY_FAILED = "img_copy_failed"
    WRITE_FAILED = "write_failed"
    DISK_FULL = "disk_full"
    #
    WSL_BRIDGE_FAILED = "wsl_bridge_failed"
    PERMISSION_DENIED = "permission_denied"
    INTERRUPTED = "interrupted"

    def __str__(self) -> str:
        return self.value


# ═══════════════════════════════════════════════════════════════════════════════
#
# ═══════════════════════════════════════════════════════════════════════════════

_SEVERITY_EMOJI = {
    "fatal":    "💥",
    "skip":     "⏭️",
    "degrade":  "⚠️",
    "ok":       "✅",
    "pending":  "⏳",
}

_PHASE_NAMES = {
    "precheck": "PRECHECK",
    "phase1_converted": "CONVERTED",
    "phase2_merged": "MERGED",
    "phase3_summarized": "SUMMARIZED",
}


def _precheck_emoji(status: str) -> str:
    """    emoji ."""
    if status == "passed":
        return _SEVERITY_EMOJI["ok"]
    if status == "pending":
        return _SEVERITY_EMOJI["pending"]
    return _SEVERITY_EMOJI["skip"]


def _engine_pair_emoji(phase: dict) -> str:
    """ marker/mineru   ."""
    status = phase.get("status", "pending")
    if status == "done":
        return f"{_SEVERITY_EMOJI['ok']} {_SEVERITY_EMOJI['ok']}"
    if status == "degraded":
        m = _SEVERITY_EMOJI["ok"] if phase.get("marker_ok") else _SEVERITY_EMOJI["skip"]
        u = _SEVERITY_EMOJI["ok"] if phase.get("mineru_ok") else _SEVERITY_EMOJI["skip"]
        err = ""
        for eng in ("marker", "mineru"):
            if not phase.get(f"{eng}_ok"):
                etype = phase.get(f"{eng}_error_type", "unknown")
                err = f"💥{ErrorType(etype).value[:6]}" if etype != "unknown" else "💥err"
        return f"{m} {u}{err}"
    if status == "failed":
        return "❌ ❌"
    if status == "skipped":
        return "⏭️"
    return _SEVERITY_EMOJI["pending"]


def _phase_emoji(phase: dict, key: str) -> str:
    """    emoji."""
    if not phase:
        return _SEVERITY_EMOJI["pending"]
    status = phase.get("status", "pending")
    if status == "done":
        return _SEVERITY_EMOJI["ok"]
    if status == "degraded":
        return _SEVERITY_EMOJI["degrade"]
    if status in ("failed", "skipped"):
        return _SEVERITY_EMOJI["skip"]
    return _SEVERITY_EMOJI["pending"]


def _severity_emoji(status: str) -> str:
    """    -> emoji."""
    return _SEVERITY_EMOJI.get(status, "  ")


# ═══════════════════════════════════════════════════════════════════════════════
#
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PrecheckResult:
    """PDF   ."""
    ok: bool
    status: str = "pending"          # passed | failed | skipped
    reason: str = ""                 # ErrorType value
    detail: str = ""
    page_count: int = 0
    pdf_hash: str = ""
    scan_warning: bool = False       # True =

    @classmethod
    def failed(cls, reason: ErrorType, detail: str = "") -> "PrecheckResult":
        return cls(ok=False, status="failed", reason=reason.value, detail=detail)

    @classmethod
    def skipped(cls, reason: ErrorType, detail: str = "") -> "PrecheckResult":
        return cls(ok=False, status="skipped", reason=reason.value, detail=detail)

    def to_record(self) -> dict:
        return {
            "status": self.status,
            "reason": self.reason,
            "detail": self.detail,
            "page_count": self.page_count,
            "pdf_hash": self.pdf_hash,
            "scan_warning": self.scan_warning,
        }


# ═══════════════════════════════════════════════════════════════════════════════
#
# ═══════════════════════════════════════════════════════════════════════════════

def run_precheck(pdf: Path, max_pages: int = _DEFAULT_MAX_PAGES) -> PrecheckResult:
    """PDF    ——   GPU ,  CPU   ."""

    if not pdf.exists():
        return PrecheckResult.skipped(ErrorType.FILE_MISSING, str(pdf))

    size = pdf.stat().st_size
    if size < 1024:
        return PrecheckResult.skipped(ErrorType.EMPTY_FILE, f"{size} bytes")

    # Magic bytes
    try:
        with open(pdf, "rb") as f:
            header = f.read(5)
    except (OSError, IOError) as e:
        return PrecheckResult.failed(ErrorType.PERMISSION_DENIED, str(e))

    if not header.startswith(b"%PDF-"):
        return PrecheckResult.skipped(
            ErrorType.NOT_A_PDF,
            detail=f"magic bytes: {header[:10]!r}",
        )

    # pypdf
    try:
        from pypdf import PdfReader
    except ImportError:
        # pypdf   →   +
        pdf_hash = hashlib.sha256(pdf.read_bytes()).hexdigest()[:16]
        return PrecheckResult(
            ok=True, status="passed", page_count=-1, pdf_hash=pdf_hash,
            reason="", detail="pypdf not installed, skipped deep check",
        )

    try:
        reader = PdfReader(str(pdf))
    except Exception as e:
        return PrecheckResult.skipped(ErrorType.CORRUPTED, str(e)[:500])

    if reader.is_encrypted:
        return PrecheckResult.skipped(ErrorType.ENCRYPTED, "PDF is password-protected")

    page_count = len(reader.pages)
    if page_count > max_pages:
        return PrecheckResult.skipped(
            ErrorType.TOO_LARGE,
            detail=f"{page_count} pages > max {max_pages}",
        )

    #   :  10  text
    text_pages = 0
    for page in reader.pages[:10]:
        try:
            text = page.extract_text()
            if text and len(text.strip()) > 50:
                text_pages += 1
        except Exception:
            pass
    scan_warning = text_pages < 2

    pdf_hash = hashlib.sha256(pdf.read_bytes()).hexdigest()[:16]

    return PrecheckResult(
        ok=True, status="passed",
        page_count=page_count, pdf_hash=pdf_hash,
        scan_warning=scan_warning,
        detail="",
    )


# ═══════════════════════════════════════════════════════════════════════════════
#
# ═══════════════════════════════════════════════════════════════════════════════

class PipelineState:
    """_pipeline_state.json  CRUD  ."""

    def __init__(self, state_path: Path):
        self._path = state_path
        self._data: dict = {"pipeline_version": _PIPELINE_VERSION, "last_updated": "", "papers": {}}
        self._dirty = False
        if state_path.exists():
            self._load()
        else:
            self._dirty = True

    def _load(self) -> None:
        try:
            self._data = json.loads(self._path.read_text(encoding="utf-8"))
            #
            if "papers" not in self._data:
                self._data["papers"] = {}
            self._data.setdefault("pipeline_version", _PIPELINE_VERSION)
        except (json.JSONDecodeError, OSError):
            self._data = {"pipeline_version": _PIPELINE_VERSION, "last_updated": "", "papers": {}}
            self._dirty = True

    def save(self) -> None:
        """."""
        import datetime
        self._data["last_updated"] = datetime.datetime.now().isoformat()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._dirty = False

    # ──   ──────────────────────────────────────────────────────────

    def has(self, stem: str) -> bool:
        return stem in self._data.get("papers", {})

    def get(self, stem: str) -> dict:
        return self._data.get("papers", {}).get(stem, {})

    def ensure_entry(self, stem: str) -> dict:
        """   ,  ."""
        papers = self._data.setdefault("papers", {})
        if stem not in papers:
            papers[stem] = {
                "source": {},
                "pdf_hash": None,
                "precheck": {"status": "pending"},
                "phase1_converted": {"status": "pending"},
                "phase2_merged": {"status": "pending"},
                "phase3_summarized": {"status": "pending"},
            }
            self._dirty = True
        return papers[stem]

    def set_precheck(self, stem: str, result: PrecheckResult) -> None:
        entry = self.ensure_entry(stem)
        entry["precheck"] = result.to_record()
        entry["pdf_hash"] = result.pdf_hash
        self._dirty = True

    def set_source(self, stem: str, source_info: dict) -> None:
        entry = self.ensure_entry(stem)
        existing = entry.get("source") or {}
        for k, v in source_info.items():
            if v:  #
                existing[k] = v
        entry["source"] = existing
        self._dirty = True

    def set_phase(self, stem: str, phase: str, record: dict) -> None:
        entry = self.ensure_entry(stem)
        entry[phase] = record
        self._dirty = True

    def set_phase_from_error(self, stem: str, phase: str, etype: ErrorType, msg: str) -> None:
        self.set_phase(stem, phase, {
            "status": "failed",
            "error_type": etype.value,
            "error": msg[:500],
        })

    # ──   ──────────────────────────────────────────────────────────

    def is_fully_done(self, stem: str) -> bool:
        """          done  degraded."""
        entry = self.get(stem)
        if not entry:
            return False
        for phase in ("precheck", "phase1_converted"):
            s = (entry.get(phase) or {}).get("status", "pending")
            if s not in ("done", "degraded", "passed"):
                return False
        return True

    def needs_precheck(self, stem: str) -> bool:
        e = self.get(stem)
        return (e.get("precheck") or {}).get("status") not in ("passed",)

    def needs_phase1(self, stem: str) -> bool:
        e = self.get(stem)
        return (e.get("phase1_converted") or {}).get("status") not in ("done", "degraded")

    def needs_phase2(self, stem: str) -> bool:
        e = self.get(stem)
        return (e.get("phase2_merged") or {}).get("status") not in ("done", "degraded")

    # ──  /  ─────────────────────────────────────────────────────

    def init_from_pdfs(self, pdfs: list[Path], max_pages: int) -> list[str]:
        """ PDF   (   )."""
        new_stems = []
        for pdf in pdfs:
            stem = pdf.stem
            if self.has(stem):
                continue
            precheck = run_precheck(pdf, max_pages)
            self.set_precheck(stem, precheck)
            if not precheck.ok:
                print(f"  [{stem}] {precheck.reason}: {precheck.detail[:80]}", file=sys.stderr)
            else:
                print(f"  [{stem}] ✅ {precheck.page_count} ", file=sys.stderr)
            new_stems.append(stem)
        if new_stems:
            self.save()
        return new_stems

    def import_manifest(self, manifest: dict) -> int:
        """  _download_manifest.json  source  .  filename ."""
        papers_in_manifest = manifest.get("papers", [])
        matched = 0
        for paper in papers_in_manifest:
            filename = paper.get("filename", "")
            stem = Path(filename).stem if filename else ""
            if not stem or not self.has(stem):
                continue
            source_info = {
                k: v for k, v in paper.items()
                if k != "filename" and v
            }
            if source_info:
                self.set_source(stem, source_info)
                matched += 1
        if matched:
            self.save()
            print(f"   {matched}  PDF  source ", file=sys.stderr)
        else:
            print(f"  :    PDF  _pipeline_state.json ", file=sys.stderr)
        return matched

    def papers_summary(self) -> list[dict]:
        """    ."""
        return [
            {"stem": stem, **entry}
            for stem, entry in sorted(self._data.get("papers", {}).items())
        ]


# ═══════════════════════════════════════════════════════════════════════════════
#   GPU
# ═══════════════════════════════════════════════════════════════════════════════

def _build_gpu_env(gpu_fraction: float, cpu_threads: int) -> dict[str, str]:
    limits = GpuLimits(
        gpu_memory_fraction=gpu_fraction if gpu_fraction > 0 else 1.0,
        cpu_threads=cpu_threads,
    )
    env = build_gpu_env(limits)
    if gpu_fraction <= 0:
        env.pop("PYTORCH_CUDA_ALLOC_CONF", None)
        wslenv = env.get("WSLENV", "")
        env["WSLENV"] = ":".join(
            x for x in wslenv.split(":") if not x.startswith("PYTORCH_CUDA_ALLOC_CONF")
        )
    return env


def _wsl_to_win(path: Path) -> str:
    r = subprocess.run(["wslpath", "-w", str(path)],
                       capture_output=True, text=True, check=True)
    return r.stdout.strip()


def _run_ps(py_exe: str, module: str, args: list[str], timeout: int,
            job_name: str = "gpu-task") -> subprocess.CompletedProcess:
    cli_map = {
        "marker.scripts.convert_single": (
            "from marker.scripts.convert_single import convert_single_cli; "
            "import sys; sys.exit(convert_single_cli())"
        ),
        "mineru.cli.client": (
            "from mineru.cli.client import main; "
            "import sys; sys.exit(main())"
        ),
    }
    code = cli_map.get(module, f"import {module}")
    cmd = ["cmd.exe", "/c", py_exe, "-c", code] + args
    env = _build_gpu_env(_GPU_FRACTION, _CPU_THREADS)

    if _GPU_GOVERNOR is not None and _GPU_FRACTION > 0:
        budget_mb = int(_GPU_FRACTION * _GPU_GOVERNOR.total_vram_mb)
        try:
            with _GPU_GOVERNOR.acquire(
                budget_mb=budget_mb, job_name=job_name,
                timeout=_GPU_WAIT_TIMEOUT,
            ):
                return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                                      encoding="utf-8", errors="replace",
                                      cwd="/mnt/e/temp", env=env)
        except InsufficientGpuBudget:
            return subprocess.CompletedProcess(
                args=cmd, returncode=124,
                stdout="", stderr=f"GPU budget unavailable for '{job_name}'; skipped\n",
            )
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace", cwd="/mnt/e/temp", env=env)


# ═══════════════════════════════════════════════════════════════════════════════
#
# ═══════════════════════════════════════════════════════════════════════════════

def _classify_engine_error(result: subprocess.CompletedProcess) -> ErrorType:
    stderr = (result.stderr or "").lower()
    if "cuda" in stderr and ("out of memory" in stderr or "oom" in stderr):
        return ErrorType.CUDA_OOM
    if result.returncode == 124 or "gpu budget unavailable" in stderr:
        return ErrorType.GPU_BUDGET_UNAVAILABLE
    if "no output" in stderr or "produced no output" in stderr:
        return ErrorType.NO_OUTPUT
    if not stderr.strip():
        return ErrorType.SILENT_CRASH
    return ErrorType.ENGINE_CRASH


# ═══════════════════════════════════════════════════════════════════════════════
#   —
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class EngineResult:
    engine: str
    ok: bool
    elapsed_sec: float
    md_path: str | None = None
    img_count: int = 0
    error: str | None = None
    error_type: str | None = None
    img_breakdown: dict = field(default_factory=dict)


@dataclass
class PaperResult:
    pdf_path: str
    stem: str
    marker: EngineResult | None = None
    mineru: EngineResult | None = None
    diff_path: str | None = None
    diff_line_count: int = 0
    merged_path: str | None = None
    merged_supplement_count: int = 0
    precheck: PrecheckResult | None = None
    phases_done: list[str] = field(default_factory=list)


def run_marker(pdf: Path, out_dir: Path, pages: str | None) -> EngineResult:
    """ marker_single  PDF."""
    marker_out = out_dir / "marker"
    marker_out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    try:
        if _WSL:
            win_pdf = _wsl_to_win(pdf)
            win_out = _wsl_to_win(marker_out)
            args = [win_pdf, "--output_dir", win_out]
            if pages:
                args += ["--page_range", pages]
            r = _run_ps(_WSL_MARKER_PY, "marker.scripts.convert_single", args,
                        timeout=1800, job_name=f"marker:{pdf.name}")
        else:
            cmd = [str(MARKER_BIN), str(pdf), "--output_dir", str(marker_out)]
            if pages:
                cmd += ["--page_range", pages]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)

        elapsed = time.time() - t0
        if r.returncode != 0:
            etype = _classify_engine_error(r)
            err = r.stderr[-2000:] if r.stderr else "unknown error"
            return EngineResult("marker", False, elapsed, error=err,
                               error_type=etype.value)
        stem = pdf.stem
        md = marker_out / stem / f"{stem}.md"
        if not md.exists():
            mds = list(marker_out.rglob("*.md"))
            md = mds[0] if mds else None
        if md is None:
            etype = ErrorType.NO_OUTPUT
            err = "no md output; " + (r.stderr.strip()[:500] if r.stderr.strip() else "marker produced no output")
            return EngineResult("marker", False, elapsed, error=err,
                               error_type=etype.value)
        img_dir = md.parent
        img_count = sum(1 for _ in img_dir.glob("*.jpeg"))
        img_count += sum(1 for _ in img_dir.glob("*.png"))
        return EngineResult("marker", True, elapsed, str(md), img_count)
    except subprocess.TimeoutExpired:
        return EngineResult("marker", False, time.time() - t0,
                           error="timeout 30min",
                           error_type=ErrorType.TIMEOUT.value)
    except Exception as e:
        return EngineResult("marker", False, time.time() - t0,
                           error=str(e),
                           error_type=ErrorType.ENGINE_CRASH.value)


def run_mineru(pdf: Path, out_dir: Path, pages: str | None,
               method: str, backend: str, lang: str | None) -> EngineResult:
    """ mineru  PDF."""
    mineru_out = out_dir / "mineru"
    mineru_out.mkdir(parents=True, exist_ok=True)

    if _WSL:
        win_pdf = _wsl_to_win(pdf)
        win_out = _wsl_to_win(mineru_out)
        args = ["-p", win_pdf, "-o", win_out, "-b", backend, "-m", method]
    t0 = time.time()
    try:
        if _WSL:
            if lang:
                args += ["-l", lang]
            if pages:
                try:
                    if "-" in pages:
                        s, e = pages.split("-", 1)
                        args += ["-s", str(int(s)), "-e", str(int(e))]
                    else:
                        args += ["-s", str(int(pages)), "-e", str(int(pages))]
                except ValueError:
                    pass
            if backend == "hybrid-engine":
                args += ["--effort", "high"]
            r = _run_ps(_WSL_MINERU_PY, "mineru.cli.client", args,
                        timeout=1800, job_name=f"mineru:{pdf.name}")
        else:
            cmd = [str(MINERU_BIN), "-p", str(pdf), "-o", str(mineru_out),
                   "-b", backend, "-m", method]
            if lang:
                cmd += ["-l", lang]
            if pages:
                try:
                    if "-" in pages:
                        s, e = pages.split("-", 1)
                        cmd += ["-s", str(int(s)), "-e", str(int(e))]
                    else:
                        cmd += ["-s", str(int(pages)), "-e", str(int(pages))]
                except ValueError:
                    pass
            if backend == "hybrid-engine":
                cmd += ["--effort", "high"]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)

        elapsed = time.time() - t0
        if r.returncode != 0:
            etype = _classify_engine_error(r)
            err = r.stderr[-2000:] if r.stderr else "unknown error"
            return EngineResult("mineru", False, elapsed, error=err,
                               error_type=etype.value)
        stem = pdf.stem
        md = mineru_out / stem / method / f"{stem}.md"
        if not md.exists():
            mds = list(mineru_out.rglob("*.md"))
            md = mds[0] if mds else None
        if md is None:
            return EngineResult("mineru", False, elapsed,
                               error_type=ErrorType.NO_OUTPUT.value,
                               error="no md output")
        img_dir = md.parent / "images"
        img_count = 0
        img_breakdown = {}
        if img_dir.exists():
            img_count = sum(1 for _ in img_dir.glob("*.jpg"))
            img_count += sum(1 for _ in img_dir.glob("*.png"))
            content_list_path = md.parent / f"{stem}_content_list.json"
            if content_list_path.exists():
                try:
                    cl = json.loads(content_list_path.read_text(encoding="utf-8"))
                    from collections import Counter
                    types = Counter()
                    for item in cl:
                        if "img_path" in item:
                            types[item.get("type", "unknown")] += 1
                    img_breakdown = dict(types)
                except Exception:
                    pass
        result = EngineResult("mineru", True, elapsed, str(md), img_count)
        result.img_breakdown = img_breakdown
        return result
    except subprocess.TimeoutExpired:
        return EngineResult("mineru", False, time.time() - t0,
                           error_type=ErrorType.TIMEOUT.value,
                           error="timeout 30min")
    except Exception as e:
        return EngineResult("mineru", False, time.time() - t0,
                           error_type=ErrorType.ENGINE_CRASH.value,
                           error=str(e))


# ═══════════════════════════════════════════════════════════════════════════════
#   Worker  ProcessPoolExecutor
# ═══════════════════════════════════════════════════════════════════════════════

def _marker_worker(pdf_str: str, out_str: str, pages: str | None) -> EngineResult:
    return run_marker(Path(pdf_str), Path(out_str), pages)


def _mineru_worker(pdf_str: str, out_str: str, pages: str | None,
                   method: str, backend: str, lang: str | None) -> EngineResult:
    return run_mineru(Path(pdf_str), Path(out_str), pages, method, backend, lang)


# ═══════════════════════════════════════════════════════════════════════════════
#   Diff + Merge    APIdiff & merge logic (preserved from v1; nearly unchanged)
# ═══════════════════════════════════════════════════════════════════════════════

_HEADING_RE = re.compile(r"^#{1,6}\s")
_LATEX_BLOCK_RE = re.compile(r"^\s*\$\$", re.MULTILINE)
_SUPERSCRIPT_RE = re.compile(r"<sup>([^<]*)</sup>")
_LATEX_INLINE_RE = re.compile(r"\$([^$]+)\$")
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LIST_BULLET_RE = re.compile(r"^[•·\-\*]\s+")
_HTML_TABLE_RE = re.compile(r"<table>.*?</table>", re.DOTALL)
_MD_TABLE_ROW_RE = re.compile(r"^\|.*\|\s*$")
_REF_ITEM_RE = re.compile(r"^\[\d+\]\s")

_META_LINE_RE = re.compile(
    r"^(\^[\*∗]\^\s*)?(Email addresses|Corresponding author|"
    r"https?://|doi:|DOI:|ORCID|Received|Accepted|Published)",
    re.IGNORECASE,
)

_MARKER_ONLY_RE = re.compile(
    r"^(Email addresses|Corresponding author|<sup>|Received|Accepted)",
    re.IGNORECASE,
)

_OCR_FIXES = {
    "ofspring": "offspring", "diferent": "different", "eficiency": "efficiency",
    "efective": "effective", "efectively": "effectively", "efectiveness": "effectiveness",
    "ofers": "offers", "ofered": "offered", "ofset": "offset", "ofen": "often",
    "afect": "affect", "afected": "affected", "aford": "afford",
    "eiciency": "efficiency", "fective": "ffective",
}

_LATEX_SPACED_LETTERS_RE = re.compile(
    r"\\mathrm\s*\{\s*((?:[A-Za-z]\s+){2,}[A-Za-z]?)\s*\}"
)


def _normalize_for_diff(text: str) -> list[str]:
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')

    lines = text.splitlines()
    n = len(lines)
    normalized_paragraphs: list[str] = []
    current_para: list[str] = []
    i = 0

    while i < n:
        stripped = lines[i].strip()

        if not stripped:
            if current_para:
                normalized_paragraphs.append(" ".join(current_para))
                current_para = []
            i += 1
            continue

        if _HEADING_RE.match(stripped):
            if current_para:
                normalized_paragraphs.append(" ".join(current_para))
                current_para = []
            content = re.sub(r"^#{1,6}\s+", "## ", stripped)
            normalized_paragraphs.append(content)
            i += 1
            continue

        if stripped.startswith("$$"):
            if current_para:
                normalized_paragraphs.append(" ".join(current_para))
                current_para = []
            block_lines = [stripped]
            j = i + 1
            if not (stripped.endswith("$$") and len(stripped) > 2):
                while j < n:
                    next_stripped = lines[j].strip()
                    if not next_stripped:
                        break
                    block_lines.append(next_stripped)
                    if next_stripped == "$$" or next_stripped.endswith("$$"):
                        j += 1
                        break
                    j += 1
            normalized_paragraphs.append(" ".join(block_lines))
            i = j + 1 if not (stripped.endswith("$$") and len(stripped) > 2) else i + 1
            continue

        if _IMAGE_RE.match(stripped):
            if current_para:
                normalized_paragraphs.append(" ".join(current_para))
                current_para = []
            normalized_paragraphs.append("[IMAGE]")
            i += 1
            continue

        if _MD_TABLE_ROW_RE.match(stripped):
            if current_para and not _MD_TABLE_ROW_RE.match(current_para[-1] if current_para else ""):
                normalized_paragraphs.append(" ".join(current_para))
                current_para = []
            current_para.append(stripped)
            i += 1
            continue

        line_norm = _SUPERSCRIPT_RE.sub(r"^\1^", stripped)
        line_norm = _LATEX_INLINE_RE.sub(r"\1", line_norm)
        line_norm = _IMAGE_RE.sub("[IMAGE]", line_norm)
        line_norm = _LIST_BULLET_RE.sub("", line_norm)
        line_norm = _HTML_TABLE_RE.sub("[TABLE]", line_norm)
        line_norm = re.sub(r"\s+", " ", line_norm).strip()

        if _META_LINE_RE.match(line_norm):
            if current_para:
                normalized_paragraphs.append(" ".join(current_para))
                current_para = []
            i += 1
            continue

        current_para.append(line_norm)
        i += 1

    if current_para:
        normalized_paragraphs.append(" ".join(current_para))

    merged: list[str] = []
    for p in normalized_paragraphs:
        if not p:
            continue
        if merged:
            prev = merged[-1]
            prev_ends_lower = prev[-1:].islower() or prev.endswith((",", ";", ":", "-"))
            curr_starts_lower = p[:1].islower() or p.startswith(
                ("and ", "the ", "but ", "which ", "where ", "with ", "for ", "in "))
            if (prev_ends_lower and curr_starts_lower
                    and not _HEADING_RE.match(p) and not p.startswith("$$")):
                merged[-1] = prev + " " + p
                continue
        merged.append(p)

    return merged


def make_diff(marker_md: Path | None, mineru_md: Path | None,
              out_path: Path, similarity_threshold: float = 0.85) -> tuple[int, int]:
    if not marker_md or not marker_md.exists():
        out_path.write_text("# Diff Skipped\n\nMarker output missing.\n", encoding="utf-8")
        return 0, 0
    if not mineru_md or not mineru_md.exists():
        out_path.write_text("# Diff Skipped\n\nMinerU output missing.\n", encoding="utf-8")
        return 0, 0

    m_paras = _normalize_for_diff(
        marker_md.read_text(encoding="utf-8", errors="replace"))
    u_paras = _normalize_for_diff(
        mineru_md.read_text(encoding="utf-8", errors="replace"))

    sm = difflib.SequenceMatcher(a=m_paras, b=u_paras, autojunk=False)

    diff_lines: list[str] = [
        "#         +   \n",
        f"- Marker: {len(m_paras)} ",
        f"- MinerU: {len(u_paras)} ",
        f"-   : {similarity_threshold}（        ）",
        f"-  : {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        " ：",
        "  [SAME]          >=   （      ）",
        "  [DIFF]          <   （    ，    ）",
        "  [ONLY-M]   Marker    ",
        "  [ONLY-U]   MinerU    ",
        "",
    ]

    real_diff_count = 0
    char_diff_count = 0

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue

        m_block = m_paras[i1:i2] if i1 < i2 else []
        u_block = u_paras[j1:j2] if j1 < j2 else []

        if not m_block and u_block:
            for para in u_block:
                diff_lines.append(f"## [ONLY-U] {j1}-{j2}")
                preview = para[:500] + ("..." if len(para) > 500 else "")
                diff_lines.append(f"+ {preview}")
                diff_lines.append("")
                real_diff_count += 1
            continue

        if m_block and not u_block:
            for para in m_block:
                diff_lines.append(f"## [ONLY-M] {i1}-{i2}")
                preview = para[:500] + ("..." if len(para) > 500 else "")
                diff_lines.append(f"- {preview}")
                diff_lines.append("")
                real_diff_count += 1
            continue

        used_u: set[int] = set()
        for m_idx, m_p in enumerate(m_block):
            best_u_idx = -1
            best_ratio = 0.0
            for u_idx, u_p in enumerate(u_block):
                if u_idx in used_u:
                    continue
                ratio = difflib.SequenceMatcher(None, m_p, u_p).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_u_idx = u_idx

            if best_u_idx < 0:
                diff_lines.append(f"## [ONLY-M] {i1+m_idx}")
                diff_lines.append(f"- {m_p[:500]}")
                diff_lines.append("")
                real_diff_count += 1
                continue

            used_u.add(best_u_idx)
            u_p = u_block[best_u_idx]

            if best_ratio >= similarity_threshold:
                char_diffs = _extract_char_diffs(m_p, u_p)
                if char_diffs:
                    diff_lines.append(
                        f"## [SAME] {i1+m_idx}/{j1+best_u_idx} (  {best_ratio:.2f})"
                    )
                    for cd in char_diffs[:5]:
                        diff_lines.append(f"  Marker: ...{cd['m']}...")
                        diff_lines.append(f"  MinerU: ...{cd['u']}...")
                    char_diff_count += 1
                    diff_lines.append("")
            else:
                diff_lines.append(
                    f"## [DIFF] {i1+m_idx}/{j1+best_u_idx} (  {best_ratio:.2f})"
                )
                diff_lines.append(f"- {m_p[:500]}")
                diff_lines.append(f"+ {u_p[:500]}")
                diff_lines.append("")
                real_diff_count += 1

        for u_idx, u_p in enumerate(u_block):
            if u_idx not in used_u:
                diff_lines.append(f"## [ONLY-U] {j1+u_idx}")
                diff_lines.append(f"+ {u_p[:500]}")
                diff_lines.append("")
                real_diff_count += 1

    diff_lines.append("---")
    diff_lines.append(f"        [DIFF/ONLY-*]: {real_diff_count}")
    diff_lines.append(f"        [SAME]: {char_diff_count}")
    diff_lines.append(f"  : {max(len(m_paras), len(u_paras))}")

    out_path.write_text("\n".join(diff_lines), encoding="utf-8")
    return real_diff_count, max(len(m_paras), len(u_paras))


def _extract_char_diffs(s1: str, s2: str, context: int = 20) -> list[dict]:
    sm = difflib.SequenceMatcher(None, s1, s2)
    diffs: list[dict] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        m_ctx_start = max(0, i1 - context)
        m_ctx_end = min(len(s1), i2 + context)
        u_ctx_start = max(0, j1 - context)
        u_ctx_end = min(len(s2), j2 + context)
        m_frag = s1[m_ctx_start:m_ctx_end]
        u_frag = s2[u_ctx_start:u_ctx_end]
        if m_frag != u_frag:
            diffs.append({"m": m_frag, "u": u_frag})
    return diffs


def _fix_ocr_errors(text: str) -> str:
    for wrong, right in _OCR_FIXES.items():
        text = re.sub(r"\b" + re.escape(wrong) + r"\b", right, text)
    return text


def _fix_latex_spacing(latex: str) -> str:
    def fix_mathrm(m):
        inner = m.group(1)
        if " " in inner and len(inner.replace(" ", "")) >= 2:
            compact = inner.replace(" ", "")
            if compact.isalpha():
                return f"\\mathrm{{{compact}}}"
        return m.group(0)

    latex = _LATEX_SPACED_LETTERS_RE.sub(fix_mathrm, latex)
    latex = re.sub(r"\\mathcal\s*\{\s*([^}]+?)\s*\}", r"\\mathcal{\1}", latex)
    latex = re.sub(r"\\mathbf\s*\{\s*([^}]+?)\s*\}", r"\\mathbf{\1}", latex)
    latex = re.sub(r"\\operatorname\*?\s*\{\s*([^}]+?)\s*\}", r"\\operatorname{\1}", latex)
    latex = re.sub(r"\s*\\\\\s*", r" \\\\ ", latex)
    return latex


def _fix_html_tables(md: str) -> str:
    def html_to_md_table(match):
        html = match.group(0)
        rows = re.findall(r"<tr>(.*?)</tr>", html, re.DOTALL)
        if not rows:
            return html
        md_rows = []
        for i, row in enumerate(rows):
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL)
            cells = [re.sub(r"\s+", " ", c).strip() for c in cells]
            if not cells:
                continue
            md_rows.append("| " + " | ".join(cells) + " |")
            if i == 0:
                md_rows.append("|" + "---|" * len(cells))
        return "\n".join(md_rows) if md_rows else html

    return re.sub(r"<table>.*?</table>", html_to_md_table, md, flags=re.DOTALL)


def _extract_metadata(md_text: str, stem: str) -> dict:
    lines = md_text.splitlines()
    title = ""
    authors = ""
    abstract = ""
    sections: list[dict] = []
    in_abstract = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("<!--") or stripped == "---":
            continue
        if not title:
            m = re.match(r"^#{1,3}\s+(.+)$", stripped)
            if m and not re.match(r"^(Abstract|Keywords|Introduction)", m.group(1), re.IGNORECASE):
                content = m.group(1)
                if len(content) > 10 and not content.startswith("$"):
                    title = content
                    continue
            elif not title and i < 3 and not stripped.startswith("#") and len(stripped) > 15:
                if not re.match(r"^(Abstract|Keywords|\\\[)", stripped, re.IGNORECASE):
                    title = stripped
                    continue
        if not authors and title and stripped != title and not stripped.startswith("#"):
            if i < 8 and any(c.isalpha() for c in stripped):
                if "@" in stripped or "Universit" in stripped or any(name in stripped for name in [",", " and "]):
                    if not stripped.startswith("Abstract") and not stripped.startswith("Keywords"):
                        authors = stripped
                        continue
        if re.match(r"^#{1,6}\s*Abstract", stripped, re.IGNORECASE) or (
            stripped.lower() == "abstract" and not abstract
        ):
            in_abstract = True
            continue
        if in_abstract:
            if re.match(r"^#{1,6}\s", stripped) or re.match(
                r"^(Keywords|1\s+Introduction)", stripped, re.IGNORECASE
            ):
                in_abstract = False
            elif stripped and not stripped.startswith("<!--") and not stripped.startswith("---"):
                abstract = (abstract + " " + stripped).strip()
        m = re.match(r"^(#{1,6})\s+(\d+(?:\.\d+)*)\s+(.+)$", stripped)
        if m:
            sections.append({
                "level": len(m.group(1)), "num": m.group(2), "title": m.group(3),
            })

    return {
        "title": title[:300],
        "authors": authors[:300],
        "abstract": abstract[:1500],
        "sections": sections[:30],
        "section_count": len(sections),
        "total_lines": len(lines),
    }


def merge_md(marker_md: Path | None, mineru_md: Path | None,
             out_path: Path) -> tuple[int, int]:
    if not mineru_md or not mineru_md.exists():
        if marker_md and marker_md.exists():
            shutil.copy(marker_md, out_path)
            return 0, 0
        out_path.write_text("# Merge Skipped\n\nBoth outputs missing.\n", encoding="utf-8")
        return 0, 0
    if not marker_md or not marker_md.exists():
        shutil.copy(mineru_md, out_path)
        return 0, 0

    m_raw = marker_md.read_text(encoding="utf-8", errors="replace")
    u_raw = mineru_md.read_text(encoding="utf-8", errors="replace")
    m_paras = _normalize_for_diff(m_raw)
    u_paras = _normalize_for_diff(u_raw)
    m_raw_lines = m_raw.splitlines()
    u_raw_lines = u_raw.splitlines()

    sm = difflib.SequenceMatcher(a=m_paras, b=u_paras, autojunk=False)

    merged_paragraphs: list[str] = []
    supplement_count = 0
    used_u: set[int] = set()

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for idx in range(j1, j2):
                if idx not in used_u:
                    merged_paragraphs.append(u_paras[idx])
                    used_u.add(idx)
            continue

        m_block = m_paras[i1:i2] if i1 < i2 else []
        u_block = u_paras[j1:j2] if j1 < j2 else []

        if not m_block and u_block:
            for para in u_block:
                if not _META_LINE_RE.match(para) and para != "[IMAGE]":
                    merged_paragraphs.append(para)
            continue

        if m_block and not u_block:
            for para in m_block:
                if _MARKER_ONLY_RE.match(para) or para == "[IMAGE]" or para.startswith("## "):
                    merged_paragraphs.append(para)
                    supplement_count += 1
            continue

        local_used: set[int] = set()
        for m_p in m_block:
            best_u_idx = -1
            best_ratio = 0.0
            for u_idx, u_p in enumerate(u_block):
                if u_idx in local_used:
                    continue
                ratio = difflib.SequenceMatcher(None, m_p, u_p).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_u_idx = u_idx

            if best_u_idx < 0:
                if _MARKER_ONLY_RE.match(m_p) or m_p.startswith("## "):
                    merged_paragraphs.append(m_p)
                    supplement_count += 1
                continue

            local_used.add(best_u_idx)
            used_u.add(j1 + best_u_idx)
            u_p = u_block[best_u_idx]

            if best_ratio >= 0.85:
                merged_paragraphs.append(m_p)
            elif best_ratio < 0.3:
                if _MARKER_ONLY_RE.match(m_p) or m_p.startswith("## "):
                    merged_paragraphs.append(m_p)
                    supplement_count += 1
                if u_p and not _META_LINE_RE.match(u_p):
                    merged_paragraphs.append(u_p)
            else:
                merged_paragraphs.append(u_p)

        for u_idx, u_p in enumerate(u_block):
            if u_idx not in local_used:
                if not _META_LINE_RE.match(u_p):
                    merged_paragraphs.append(u_p)

    merged_text = "\n\n".join(merged_paragraphs)

    marker_tables = re.findall(r"((?:\|[^\n]+\|\s*\n){2,})", m_raw)
    table_idx = 0

    def replace_table(m):
        nonlocal table_idx
        if table_idx < len(marker_tables):
            t = marker_tables[table_idx].rstrip()
            table_idx += 1
            return t
        return m.group(0)

    merged_text = re.sub(r"\[TABLE\]", replace_table, merged_text)
    merged_text = _fix_ocr_errors(merged_text)
    merged_text = _fix_latex_spacing(merged_text)
    merged_text = _fix_html_tables(merged_text)

    stem = (mineru_md or marker_md).stem
    meta = _extract_metadata(merged_text, stem)

    title = meta["title"] or stem
    authors = meta["authors"] or ""
    abstract = meta["abstract"] or ""

    header_lines = [
        "---",
        f"title: |",
        f"  {title}",
        f"authors: |",
        f"  {authors}",
        f'source_pdf: "{stem}"',
        f'merged_at: {time.strftime("%Y-%m-%d %H:%M:%S")}',
        "engines: MinerU(  ) + Marker(  )",
        f'sections: {meta["section_count"]}',
        f'total_lines: {meta["total_lines"]}',
        "---",
        "",
        f"# {title}",
        "",
    ]
    if authors:
        header_lines.append(f"**Authors:** {authors}")
        header_lines.append("")
    if abstract:
        header_lines.append("## Abstract")
        header_lines.append("")
        header_lines.append(abstract[:800] + ("..." if len(abstract) > 800 else ""))
        header_lines.append("")
    if meta["sections"]:
        header_lines.append("## Table of Contents")
        header_lines.append("")
        for s in meta["sections"][:20]:
            indent = "  " * (s["level"] - 1)
            header_lines.append(f"{indent}- {s['num']} {s['title']}")
        header_lines.append("")
    header_lines.append("---")
    header_lines.append("")

    final_text = "\n".join(header_lines) + "\n" + merged_text

    image_list: list[str] = []
    for img_pattern, source in [(m_raw, "Marker"), (u_raw, "MinerU")]:
        for match in re.finditer(r"!\[([^\]]*)\]\(([^)]+)\)", img_pattern):
            alt, path = match.group(1), match.group(2)
            image_list.append(
                f"- {source}: `{path}`" + (f" (alt: {alt})" if alt else "")
            )

    if image_list:
        seen = set()
        unique_images = []
        for img in image_list:
            path_part = img.split("`")[1] if "`" in img else img
            if path_part not in seen:
                seen.add(path_part)
                unique_images.append(img)
        final_text += "\n\n---\n\n## Images Index\n\n"
        final_text += (
            f"  {len(unique_images)}  "
            f"（Marker {len(m_raw_lines)} , MinerU {len(u_raw_lines)} ）\n\n"
        )
        for img in unique_images:
            final_text += img + "\n"

    out_path.write_text(final_text, encoding="utf-8")
    return len(u_paras), supplement_count


# ═══════════════════════════════════════════════════════════════════════════════
#      Figure
# ═══════════════════════════════════════════════════════════════════════════════

def _get_mineru_content_list(mineru_md_path: Path) -> list[dict]:
    """ MinerU  content_list.json ."""
    cl_path = mineru_md_path.parent / f"{mineru_md_path.stem}_content_list.json"
    if not cl_path.exists():
        return []
    try:
        return json.loads(cl_path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _get_mineru_figure_images(mineru_md_path: Path) -> set[str]:
    """ MinerU  Figure (type='image')  ."""
    content_list = _get_mineru_content_list(mineru_md_path)
    figures = set()
    for item in content_list:
        if item.get("type") == "image" and "img_path" in item:
            img_path = item["img_path"]
            #   images/xxx.jpg
            if not img_path.startswith("images/"):
                figures.add(f"images/{Path(img_path).name}")
            else:
                figures.add(img_path)
    return figures


def _get_marker_images(marker_md_path: Path) -> set[str]:
    """ Marker   ."""
    # Marker        md
    md_dir = marker_md_path.parent
    images = set()
    for ext in ("*.jpeg", "*.jpg", "*.png"):
        for img in md_dir.glob(ext):
            images.add(img.name)
    return images


def copy_figure_images(
    stem: str,
    marker_md: Path | None,
    mineru_md: Path | None,
    merged_dir: Path,
) -> int:
    """     Figure     merged/<stem>/images/.

    MinerU:  content_list.json  type=='image'
    Marker:      ( , ~14 )
    """
    if not marker_md and not mineru_md:
        return 0

    images_dir = merged_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    copied = 0

    # MinerU  Figure
    if mineru_md and mineru_md.exists():
        figure_names = _get_mineru_figure_images(mineru_md)
        mineru_img_dir = mineru_md.parent / "images"
        if mineru_img_dir.exists():
            for fname in figure_names:
                src = mineru_img_dir / Path(fname).name
                if src.exists():
                    dst = images_dir / src.name
                    if not dst.exists():
                        shutil.copy2(src, dst)
                        copied += 1

    # Marker
    if marker_md and marker_md.exists():
        marker_img_dir = marker_md.parent
        marker_names = _get_marker_images(marker_md)
        for fname in marker_names:
            src = marker_img_dir / fname
            if src.exists():
                dst = images_dir / src.name
                if not dst.exists():
                    shutil.copy2(src, dst)
                    copied += 1

    return copied


# ═══════════════════════════════════════════════════════════════════════════════
#      — v2   (  /  /  )
# ═══════════════════════════════════════════════════════════════════════════════

def _derive_output_dirs(papers_dir: Path) -> dict[str, Path]:
    """      ."""
    return {
        "conversion": papers_dir / "paper-conversion",
        "merged": papers_dir / "paper-merged",
        "summaries": papers_dir / "paper-summaries",
    }


def process_one(
    pdf: Path,
    papers_dir: Path,
    engines: str,
    pages: str | None,
    method: str,
    backend: str,
    lang: str | None,
    max_workers: int = 2,
    state: PipelineState | None = None,
    force: bool = False,
) -> PaperResult:
    """   PDF  ."""
    stem = pdf.stem
    dirs = _derive_output_dirs(papers_dir)
    conversion_dir = dirs["conversion"] / stem
    merged_dir = dirs["merged"] / stem
    summaries_dir = dirs["summaries"]

    conversion_dir.mkdir(parents=True, exist_ok=True)
    merged_dir.mkdir(parents=True, exist_ok=True)
    summaries_dir.mkdir(parents=True, exist_ok=True)

    result = PaperResult(pdf_path=str(pdf), stem=stem)

    # ── Phase 0:   ────────────────────────────────────────────────
    skip_precheck = state and not force and state.has(stem) and not state.needs_precheck(stem)
    if not skip_precheck:
        max_pages = _DEFAULT_MAX_PAGES
        if state:
            #  TODO:    _pipeline_state.json
            pass
        precheck = run_precheck(pdf)
        result.precheck = precheck
        if state:
            state.set_precheck(stem, precheck)

        if not precheck.ok:
            error_type = ErrorType(precheck.reason) if precheck.reason else ErrorType.PRECHECK_CRASHED
            if state:
                for phase in ("phase1_converted", "phase2_merged", "phase3_summarized"):
                    state.set_phase(stem, phase, {"status": "skipped"})
                state.save()
            return result
    elif state:
        result.precheck = PrecheckResult(
            ok=True, status="passed",
            pdf_hash=state.get(stem).get("pdf_hash", ""),
        )

    # ── Phase 1:   ────────────────────────────────────────────────
    if engines == "both":
        workers = max(1, min(max_workers, 2))
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {
                "marker": ex.submit(
                    _marker_worker, str(pdf), str(conversion_dir), pages,
                ),
                "mineru": ex.submit(
                    _mineru_worker, str(pdf), str(conversion_dir), pages,
                    method, backend, lang,
                ),
            }
            for key, fut in futs.items():
                try:
                    er = fut.result()
                except Exception as e:
                    er = EngineResult(key, False, 0,
                                     error=str(e),
                                     error_type=ErrorType.ENGINE_CRASH.value)
                setattr(result, key, er)
    elif engines == "marker":
        result.marker = run_marker(pdf, conversion_dir, pages)
    elif engines == "mineru":
        result.mineru = run_mineru(pdf, conversion_dir, pages, method, backend, lang)
    else:
        raise ValueError(f"unknown engines: {engines}")

    #   Phase 1
    marker_ok = result.marker and result.marker.ok
    mineru_ok = result.mineru and result.mineru.ok

    #        : --engines marker  marker  mineru  None
    if engines == "both":
        both_failed = not marker_ok and not mineru_ok
    elif engines == "marker":
        both_failed = not marker_ok
    elif engines == "mineru":
        both_failed = not mineru_ok
    else:
        both_failed = not marker_ok and not mineru_ok

    if both_failed:
        #    → SKIP
        phase1_record = {
            "status": "failed",
            "marker_ok": marker_ok if (engines in ("both", "marker")) else None,
            "mineru_ok": mineru_ok if (engines in ("both", "mineru")) else None,
            "marker_error": (result.marker.error if result.marker and not result.marker.ok else "") if engines in ("both", "marker") else None,
            "mineru_error": (result.mineru.error if result.mineru and not result.mineru.ok else "") if engines in ("both", "mineru") else None,
        }
        phase1_record["error_type"] = (
            ErrorType.BOTH_ENGINES_FAILED.value if engines == "both"
            else (result.marker.error_type if engines == "marker" else result.mineru.error_type)
        )
        if state:
            state.set_phase(stem, "phase1_converted", phase1_record)
            state.set_phase(stem, "phase2_merged", {"status": "skipped"})
            state.set_phase(stem, "phase3_summarized", {"status": "skipped"})
            state.save()
        return result

    phase1_status = "degraded" if not (marker_ok and mineru_ok) else "done"
    phase1_record = {
        "status": phase1_status,
        "marker_ok": marker_ok,
        "mineru_ok": mineru_ok,
        "marker_error": result.marker.error if not marker_ok else None,
        "mineru_error": result.mineru.error if not mineru_ok else None,
        "marker_error_type": result.marker.error_type if not marker_ok else None,
        "mineru_error_type": result.mineru.error_type if not mineru_ok else None,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if state:
        state.set_phase(stem, "phase1_converted", phase1_record)
    result.phases_done.append("phase1")

    # ── Phase 2:   ────────────────────────────────────────────────
    diff_path = merged_dir / "_DIFF.md"
    merged_path = merged_dir / "_MERGED.md"
    meta_path = merged_dir / "_META.json"

    try:
        marker_md_p = (Path(result.marker.md_path)
                       if result.marker and result.marker.md_path else None)
        mineru_md_p = (Path(result.mineru.md_path)
                       if result.mineru and result.mineru.md_path else None)

        #   (diff + merge)
        if marker_md_p and mineru_md_p:
            diff_count, total = make_diff(marker_md_p, mineru_md_p, diff_path)
            result.diff_path = str(diff_path)
            result.diff_line_count = diff_count

            merged_total, merged_supp = merge_md(
                marker_md_p, mineru_md_p, merged_path,
            )
            result.merged_path = str(merged_path)
            result.merged_supplement_count = merged_supp

        elif marker_md_p:
            #   Marker →
            shutil.copy(marker_md_p, merged_path)
            result.merged_path = str(merged_path)
            diff_path.write_text("# Diff Skipped\n\nMinerU output missing.\n", encoding="utf-8")

        elif mineru_md_p:
            #   MinerU
            shutil.copy(mineru_md_p, merged_path)
            result.merged_path = str(merged_path)
            diff_path.write_text("# Diff Skipped\n\nMarker output missing.\n", encoding="utf-8")

        #   Figure
        try:
            images_copied = copy_figure_images(
                stem, marker_md_p, mineru_md_p, merged_dir,
            )
        except Exception as e:
            #   → DEGRADE, merged
            print(f"  [{stem}] ⚠️    : {e}", file=sys.stderr)
            images_copied = -1

        phase2_status = "degraded" if not (marker_ok and mineru_ok) else "done"
        phase2_record = {
            "status": phase2_status,
            "diff_paragraphs": result.diff_line_count,
            "images_copied": images_copied,
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        if images_copied < 0:
            phase2_record["img_copy_error"] = str(e) if 'e' in dir() else "unknown"

        if state:
            state.set_phase(stem, "phase2_merged", phase2_record)

        result.phases_done.append("phase2")

    except Exception as e:
        #   → SKIP
        print(f"  [{stem}] ❌   : {e}", file=sys.stderr)
        if state:
            state.set_phase_from_error(stem, "phase2_merged", ErrorType.NORMALIZE_CRASH, str(e))
        return result

    # ──    _META.json ────────────────────────────────────────────
    meta = {
        "pdf_path": result.pdf_path,
        "stem": result.stem,
        "engines": engines,
        "pages": pages,
        "marker": asdict(result.marker) if result.marker else None,
        "mineru": asdict(result.mineru) if result.mineru else None,
        "diff_path": result.diff_path,
        "diff_line_count": result.diff_line_count,
        "merged_path": result.merged_path,
        "merged_supplement_count": result.merged_supplement_count,
        "images_copied": images_copied if 'images_copied' in dir() else 0,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if precheck := result.precheck:
        meta["precheck"] = precheck.to_record()
    try:
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        #   → FATAL?
        print(f"  [{stem}] 💥    _META.json: {e}", file=sys.stderr)

    #   Phase 3
    if state:
        state.set_phase(stem, "phase3_summarized", {"status": "pending"})

    if state:
        state.save()

    return result


# ═══════════════════════════════════════════════════════════════════════════════
#
# ═══════════════════════════════════════════════════════════════════════════════

def find_pdfs(target: Path) -> list[Path]:
    if target.is_file() and target.suffix.lower() == ".pdf":
        return [target]
    if target.is_dir():
        return sorted(p for p in target.rglob("*.pdf") if not p.name.startswith("."))
    return []


def print_summary(results: list[PaperResult]) -> None:
    print("\n" + "=" * 70)
    print(f"{'stem':<40} {'marker':>8} {'mineru':>8} {'diff':>6}")
    print("-" * 70)
    for r in results:
        m_t = (f"{r.marker.elapsed_sec:.0f}s"
               if r.marker and r.marker.ok else
               ("FAIL" if r.marker else "-"))
        u_t = (f"{r.mineru.elapsed_sec:.0f}s"
               if r.mineru and r.mineru.ok else
               ("FAIL" if r.mineru else "-"))
        d = str(r.diff_line_count) if r.diff_path else "-"
        print(f"{r.stem:<40} {m_t:>8} {u_t:>8} {d:>6}")
    print("=" * 70)


def print_status(state: PipelineState) -> None:
    """   ."""
    papers = state.papers_summary()
    if not papers:
        print("  _pipeline_state.json    .", file=sys.stderr)
        print("  paper_reader.py <papers_dir/> --init ", file=sys.stderr)
        return

    #
    COLUMNS = [
        ("STEM", 28),
        ("SOURCE", 8),
        ("PRECHECK", 10),
        ("CONVERTED", 18),
        ("MERGED", 8),
        ("SUMMARIZED", 10),
        ("TIER", 8),
    ]

    header = "".join(name.ljust(w + 1) for name, w in COLUMNS)
    print(header)
    print("-" * len(header))

    stats = {"total": 0, "ok": 0, "degraded": 0, "skipped": 0, "pending": 0}
    skip_reasons: dict[str, int] = {}

    for p in papers:
        stem = p["stem"]
        stats["total"] += 1

        source_db = (p.get("source") or {}).get("source_db", "-")
        tier = (p.get("source") or {}).get("venue", "") or "-"

        precheck = p.get("precheck", {})
        pc_status = precheck.get("status", "pending")
        pc_emoji = _precheck_emoji(pc_status)
        pc_reason = precheck.get("reason", "")
        if pc_status not in ("passed", "pending"):
            pc_emoji += f"{pc_reason[:8]}" if pc_reason else "❌"
            skip_reasons[pc_reason or "unknown"] = skip_reasons.get(pc_reason or "unknown", 0) + 1

        phase1 = p.get("phase1_converted", {})
        phase2 = p.get("phase2_merged", {})
        phase3 = p.get("phase3_summarized", {})

        p1_emoji = _engine_pair_emoji(phase1)
        p2_emoji = _phase_emoji(phase2, "phase2_merged")
        p3_emoji = _phase_emoji(phase3, "phase3_summarized")

        #    precheck passed + phase1 done  = ok
        if pc_status == "passed" and phase1.get("status") in ("done", "degraded"):
            stats["ok" if phase1.get("status") == "done" else "degraded"] += 1
        elif pc_status != "passed" and pc_status != "pending":
            stats["skipped"] += 1
        elif phase1.get("status") == "failed":
            stats["skipped"] += 1
        elif pc_status == "pending":
            stats["pending"] += 1
        else:
            stats["pending"] += 1

        print(
            f"{stem:<{COLUMNS[0][1]+1}}"
            f"{source_db:<{COLUMNS[1][1]+1}}"
            f"{pc_emoji:<{COLUMNS[2][1]+1}}"
            f"{p1_emoji:<{COLUMNS[3][1]+1}}"
            f"{p2_emoji:<{COLUMNS[4][1]+1}}"
            f"{p3_emoji:<{COLUMNS[5][1]+1}}"
            f"{tier[:8]:<{COLUMNS[6][1]+1}}"
        )

    print("-" * len(header))
    summary_parts = [f"  : {stats['total']}"]
    if stats["ok"]:
        summary_parts.append(f"  : {stats['ok']}")
    if stats["degraded"]:
        summary_parts.append(f"  : {stats['degraded']}")
    if stats["skipped"]:
        summary_parts.append(f"  : {stats['skipped']}")
    if stats["pending"]:
        summary_parts.append(f"  : {stats['pending']}")
    print("  ".join(summary_parts))
    if skip_reasons:
        reason_summary = ", ".join(f"{r}={c}" for r, c in skip_reasons.items())
        print(f"  : {reason_summary}")


# ═══════════════════════════════════════════════════════════════════════════════
#   CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Paper Reader v2 —        +   ",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("pdf", type=Path,
                    help="PDF         （  PDF       ）")
    ap.add_argument("-o", "--output", type=Path, default=None,
                    help="[  ]    （ v2       ）")
    ap.add_argument("-e", "--engines", choices=["both", "marker", "mineru"],
                    default="both", help="    （  both）")
    ap.add_argument("-p", "--pages", help="   '0-9'  '5'（0-based）")
    ap.add_argument("-b", "--batch", action="store_true",
                    help="        PDF    ")

    # v2
    ap.add_argument("--init", action="store_true",
                    help="   _pipeline_state.json（ PDF  ）")
    ap.add_argument("--status", action="store_true",
                    help="     ")
    ap.add_argument("--resume", action="store_true",
                    help="       （  --batch  ）")
    ap.add_argument("--force", action="store_true",
                    help="    ，     ")
    ap.add_argument("--from-manifest", type=Path, default=None, metavar="PATH",
                    help="  _download_manifest.json  source ")
    ap.add_argument("--import-urls", type=Path, default=None, metavar="PATH",
                    help=" --from-manifest  （    URL  ）")
    ap.add_argument("--max-pages", type=int, default=_DEFAULT_MAX_PAGES,
                    help=f"PDF     SKIP（  {_DEFAULT_MAX_PAGES}）")

    # MinerU
    ap.add_argument("--mineru-method", choices=["auto", "ocr", "txt"],
                    default="auto", help="MinerU    ")
    ap.add_argument("--mineru-backend", choices=["pipeline", "hybrid-engine"],
                    default="pipeline", help="MinerU  （hybrid     ）")
    ap.add_argument("-l", "--lang", help="PDF  （mineru pipeline  ）")

    # GPU
    ap.add_argument("--max-workers", type=int, default=2,
                    help="  PDF       （  2 = marker+mineru   ）")
    ap.add_argument("--gpu-fraction", type=float, default=0.4,
                    help="  Windows GPU       （0-1   0.4）")
    ap.add_argument("--cpu-threads", type=int, default=6,
                    help="  GPU       CPU    （  6）")
    ap.add_argument("--max-concurrent-pdfs", type=int, default=1,
                    help="        PDF （  1 =  ）")
    ap.add_argument("--gpu-cap-fraction", type=float, default=0.9,
                    help="   GPU      （0-1   0.9=90%%）")
    ap.add_argument("--gpu-wait-timeout", type=float, default=600.0,
                    help="   GPU         （   600=10 ）")

    args = ap.parse_args()

    # ── GPU    ──────────────────────────────────────────────────────
    global _GPU_FRACTION, _CPU_THREADS, _GPU_GOVERNOR, _GPU_WAIT_TIMEOUT
    _GPU_FRACTION = args.gpu_fraction
    _GPU_THREADS = args.cpu_threads
    _GPU_WAIT_TIMEOUT = args.gpu_wait_timeout

    if 0.0 < args.gpu_fraction <= 1.0:
        print(f"GPU  :   {args.gpu_fraction*100:.0f}%  ，"
              f"{args.cpu_threads} CPU  ", file=sys.stderr)
    elif args.gpu_fraction != 0:
        ap.error(
            f"--gpu-fraction     (0, 1]     0（   ），  "
            f"{args.gpu_fraction}"
        )
    else:
        print("GPU  :    （  CPU    ）", file=sys.stderr)

    if 0.0 < args.gpu_cap_fraction <= 1.0:
        _GPU_GOVERNOR = GpuGovernor(cap_fraction=args.gpu_cap_fraction)
        print(f"GPU   :     {args.gpu_cap_fraction*100:.0f}%，"
              f"    {args.gpu_wait_timeout:.0f}s", file=sys.stderr)
    elif args.gpu_cap_fraction != 0:
        ap.error(
            f"--gpu-cap-fraction     (0, 1]     0（  ），  "
            f"{args.gpu_cap_fraction}"
        )
    else:
        print("GPU   :    （    ，      ）", file=sys.stderr)

    # ──    ──────────────────────────────────────────────────
    #   v2:    papers_dir   PDF  /
    papers_dir = args.pdf.resolve()
    if papers_dir.is_file():
        papers_dir = papers_dir.parent

    state_path = papers_dir / "_pipeline_state.json"

    # ── --status ─────────────────────────────────────────────────────
    if args.status:
        if not state_path.exists():
            print(f"  _pipeline_state.json    : {state_path}", file=sys.stderr)
            print("  paper_reader.py papers/ --init ", file=sys.stderr)
            return 1
        state = PipelineState(state_path)
        print_status(state)
        return 0

    # ── --init ───────────────────────────────────────────────────────
    if args.init:
        state = PipelineState(state_path)
        pdfs = find_pdfs(args.pdf)
        if not pdfs:
            print(f"ERROR:    PDF: {args.pdf}", file=sys.stderr)
            return 1
        print(f"  {len(pdfs)}  PDF,     ...", file=sys.stderr)
        new_stems = state.init_from_pdfs(pdfs, args.max_pages)
        print(f"   : {len(new_stems)}   PDF  _pipeline_state.json", file=sys.stderr)
        state.save()

        #   --from-manifest
        manifest_path = args.from_manifest or args.import_urls
        if manifest_path and manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                state.import_manifest(manifest)
            except (json.JSONDecodeError, OSError) as e:
                print(f"ERROR:    manifest: {e}", file=sys.stderr)

        print_status(state)
        return 0

    # ── --import-urls (no --init) ───────────────────────────────────
    manifest_path = args.from_manifest or args.import_urls
    if manifest_path and not args.init:
        if not state_path.exists():
            print(f"ERROR: _pipeline_state.json    : {state_path}", file=sys.stderr)
            print("  paper_reader.py papers/ --init ", file=sys.stderr)
            return 1
        if not manifest_path.exists():
            print(f"ERROR: manifest    : {manifest_path}", file=sys.stderr)
            return 1
        state = PipelineState(state_path)
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            state.import_manifest(manifest)
            return 0
        except (json.JSONDecodeError, OSError) as e:
            print(f"ERROR:    manifest: {e}", file=sys.stderr)
            return 1

    # ──     ────────────────────────────────────────────────────

    #  v1 --output   (  )
    if args.output is not None:
        print("  : --output   v2    ,   .", file=sys.stderr)
        print(f"     : {papers_dir}/paper-conversion/", file=sys.stderr)
        print(f"     : {papers_dir}/paper-merged/", file=sys.stderr)

    #
    if args.engines in ("both", "marker") and not MARKER_BIN.exists():
        print(f"ERROR: marker venv  : {MARKER_BIN}", file=sys.stderr)
        print("  : bash ~/.claude/skills/paper-reader/scripts/bootstrap.sh",
              file=sys.stderr)
        return 2
    if args.engines in ("both", "mineru") and not MINERU_BIN.exists():
        print(f"ERROR: mineru venv  : {MINERU_BIN}", file=sys.stderr)
        print("  : bash ~/.claude/skills/paper-reader/scripts/bootstrap.sh",
              file=sys.stderr)
        return 2

    #   /  _pipeline_state.json
    state = PipelineState(state_path) if state_path.exists() else None

    pdfs = find_pdfs(args.pdf)
    if not pdfs:
        print(f"ERROR:    PDF: {args.pdf}", file=sys.stderr)
        return 1

    #   PDF   /init
    if state and state.has(pdfs[0].stem):
        pass  #   state     process_one  resume
    elif len(pdfs) > 1 and not state:
        print("  :  _pipeline_state.json    .", file=sys.stderr)
        print("  paper_reader.py papers/ --init ", file=sys.stderr)

    dirs = _derive_output_dirs(papers_dir)
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    print(f"   {len(pdfs)}  PDF", file=sys.stderr)
    print(f"  : {args.engines}     : {args.pages or ' '}", file=sys.stderr)
    print(f"  PDF  : {args.max_workers}   |    : {args.max_concurrent_pdfs} PDF", file=sys.stderr)

    # ──     ──────────────────────────────────────────────
    results: list[PaperResult] = []

    def _should_skip(stem: str) -> bool:
        """ resume   force ."""
        if not args.resume or not state:
            return False
        if args.force:
            return False
        if not state.has(stem):
            return False
        return state.is_fully_done(stem)

    if args.max_concurrent_pdfs <= 1 or len(pdfs) == 1:
        #
        for i, pdf in enumerate(pdfs, 1):
            stem = pdf.stem
            if _should_skip(stem):
                print(f"[{i}/{len(pdfs)}] {pdf.name} ⏭️   ", file=sys.stderr)
                #        state
                entry = state.get(stem) if state else {}
                results.append(PaperResult(pdf_path=str(pdf), stem=stem))
                continue

            print(f"\n[{i}/{len(pdfs)}] {pdf.name}", file=sys.stderr)
            try:
                r = process_one(
                    pdf, papers_dir, args.engines, args.pages,
                    args.mineru_method, args.mineru_backend, args.lang,
                    max_workers=args.max_workers,
                    state=state,
                    force=args.force,
                )
                results.append(r)
            except KeyboardInterrupt:
                print("\n  。", file=sys.stderr)
                if state:
                    state.set_phase(stem, "phase1_converted",
                                    {"status": "interrupted"})
                    state.save()
                break
            except Exception as e:
                print(f"  ERROR: {e}", file=sys.stderr)
                if state:
                    state.set_phase(stem, "phase1_converted",
                                    {"status": "failed", "error": str(e)[:500]})
                    state.save()
                results.append(PaperResult(pdf_path=str(pdf), stem=stem))
    else:
        #
        total_procs = args.max_concurrent_pdfs * args.max_workers
        if 0.0 < args.gpu_fraction and total_procs * args.gpu_fraction > 1.0 + 1e-6:
            print(
                f"⚠  : {total_procs}   × {args.gpu_fraction*100:.0f}%   = "
                f"{total_procs*args.gpu_fraction*100:.0f}% > 100%，   OOM！",
                file=sys.stderr,
            )
            print(f"    ：   --max-concurrent-pdfs   --gpu-fraction",
                  file=sys.stderr)

        with ThreadPoolExecutor(max_workers=args.max_concurrent_pdfs) as tex:
            indexed = list(enumerate(pdfs, 1))

            def _run_one(idx_pdf):
                i, pdf = idx_pdf
                stem = pdf.stem
                if _should_skip(stem):
                    print(f"[{i}/{len(pdfs)}] {pdf.name} ⏭️   ", file=sys.stderr)
                    return PaperResult(pdf_path=str(pdf), stem=stem)
                print(f"\n[{i}/{len(pdfs)}] {pdf.name}", file=sys.stderr)
                try:
                    return process_one(
                        pdf, papers_dir, args.engines, args.pages,
                        args.mineru_method, args.mineru_backend, args.lang,
                        max_workers=args.max_workers,
                        state=state,
                        force=args.force,
                    )
                except Exception as e:
                    print(f"  ERROR: {e}", file=sys.stderr)
                    return PaperResult(pdf_path=str(pdf), stem=stem)

            try:
                for r in tex.map(_run_one, indexed):
                    results.append(r)
            except KeyboardInterrupt:
                print("\n  （   PDF  ）。", file=sys.stderr)

    print_summary(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
