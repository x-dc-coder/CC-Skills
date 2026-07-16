#!/usr/bin/env python3
"""paper-reader: Marker + MinerU 双引擎学术论文 PDF 对照阅读器.

用法:
  paper_reader.py <pdf_path_or_dir> [--output OUT] [--engines both|marker|mineru]
                  [--pages 0-9] [--batch] [--mineru-method auto|ocr|txt]
                  [--mineru-backend pipeline|hybrid-engine] [--lang ch]
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
MARKER_BIN = SKILL_ROOT / "venvs" / "marker" / "bin" / "marker_single"
MINERU_BIN = SKILL_ROOT / "venvs" / "mineru" / "bin" / "mineru"

# ── WSL → Windows 桥接配置 ────────────────────────────────────────────────
# 在 WSL 中运行时，将 Marker/MinerU 的 GPU 计算路由到 Windows 原生 Python，
# 避免 vmmemWSL 进程内存膨胀（WSL2 不主动归还内核内存给 Windows）。
_WSL = "microsoft" in os.uname().release.lower()
_WSL_MARKER_PY = r"E:\venvs\marker\Scripts\python.exe"
_WSL_MINERU_PY = r"E:\venvs\mineru\Scripts\python.exe"

# ── GPU 资源栅栏（⭐ 防 OOM 卡死系统） ───────────────────────────────────
# 从 wsl-windows-bridge 共享模块导入 GPU 资源栅栏（含设备级 GpuGovernor）。
# 规范见 /home/dc/CLAUDE.md "GPU 多路并发铁律"。
# 共享模块位置：~/.claude/skills/wsl-windows-bridge/scripts/gpu_safe_subprocess.py
_BRIDGE_SCRIPTS = (Path.home() / ".claude" / "skills" / "wsl-windows-bridge" / "scripts")
if str(_BRIDGE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_BRIDGE_SCRIPTS))
from gpu_safe_subprocess import (  # noqa: E402
    GpuLimits, build_gpu_env, GpuGovernor, GpuLease, InsufficientGpuBudget,
)

# 运行期被 main() 依据 CLI 参数填充；(_gpu_fraction<=0, _cpu_threads) 表示不限制
_GPU_FRACTION: float = 0.4   # 默认每进程 40% 显存（16GB GPU → 6.4GB）
_CPU_THREADS: int = 6         # 默认每进程 6 线程（2 进程 × 6 = 12 ≤ 物理核）
# 设备级协调器：保证多任务总显存 ≤ cap_fraction × total_vram（默认 90%）
# 多个 paper-reader 实例 / CV 训练同时跑时，通过 fcntl 文件锁互斥，避免过载
_GPU_GOVERNOR: GpuGovernor | None = None
_GPU_WAIT_TIMEOUT: float = 600.0   # 设备预算不足时等待秒数（默认 10 分钟）


def _build_gpu_env(gpu_fraction: float, cpu_threads: int) -> dict[str, str]:
    """薄包装：用共享模块构造 GPU 限制环境变量（含 WSLENV 白名单）。"""
    limits = GpuLimits(
        gpu_memory_fraction=gpu_fraction if gpu_fraction > 0 else 1.0,
        cpu_threads=cpu_threads,
    )
    env = build_gpu_env(limits)
    # gpu_fraction<=0 表示用户禁用：删掉 PYTORCH_CUDA_ALLOC_CONF
    if gpu_fraction <= 0:
        env.pop("PYTORCH_CUDA_ALLOC_CONF", None)
        # 同步从 WSLENV 移除（避免 Windows 侧读到空值）
        wslenv = env.get("WSLENV", "")
        env["WSLENV"] = ":".join(
            x for x in wslenv.split(":") if not x.startswith("PYTORCH_CUDA_ALLOC_CONF")
        )
    return env


def _wsl_to_win(path: Path) -> str:
    """WSL 路径 → Windows 路径（通过 wslpath -w）"""
    r = subprocess.run(["wslpath", "-w", str(path)],
                       capture_output=True, text=True, check=True)
    return r.stdout.strip()


def _run_ps(py_exe: str, module: str, args: list[str], timeout: int,
            job_name: str = "gpu-task") -> subprocess.CompletedProcess:
    # marker/mineru 的 Python 模块没有 __main__ 入口，必须通过 -c 显式调用 CLI 函数
    cli_map = {
        "marker.scripts.convert_single": "from marker.scripts.convert_single import convert_single_cli; import sys; sys.exit(convert_single_cli())",
        "mineru.cli.client": "from mineru.cli.client import main; import sys; sys.exit(main())",
    }
    code = cli_map.get(module, f"import {module}")
    cmd = ["cmd.exe", "/c", py_exe, "-c", code] + args
    env = _build_gpu_env(_GPU_FRACTION, _CPU_THREADS)

    # 设备级协调：若 governor 已初始化，先申请预算（阻塞等待其他进程释放）
    # 预算 = gpu_fraction × total_vram_mb（和单进程配额对齐）
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
            # GPU 预算不足且等待超时：返回失败结果，让上层优雅跳过
            return subprocess.CompletedProcess(
                args=cmd, returncode=124,  # 124 = timeout-like
                stdout="", stderr=f"GPU budget unavailable for '{job_name}'; skipped\n",
            )
    # governor 未启用：直接跑（旧行为）
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace", cwd="/mnt/e/temp", env=env)


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #
@dataclass
class EngineResult:
    engine: str
    ok: bool
    elapsed_sec: float
    md_path: str | None = None
    img_count: int = 0
    error: str | None = None
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


# --------------------------------------------------------------------------- #
# 引擎调用
# --------------------------------------------------------------------------- #
def run_marker(pdf: Path, out_dir: Path, pages: str | None) -> EngineResult:
    """调用 marker_single 转换单个 PDF."""
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
            err = r.stderr[-2000:] if r.stderr else "unknown error"
            return EngineResult("marker", False, elapsed, error=err)
        stem = pdf.stem
        md = marker_out / stem / f"{stem}.md"
        if not md.exists():
            mds = list(marker_out.rglob("*.md"))
            md = mds[0] if mds else None
        if md is None:
            err = "no md output; " + (r.stderr.strip()[:500] if r.stderr.strip() else "marker produced no output")
            return EngineResult("marker", False, elapsed, error=err)
        img_dir = md.parent
        img_count = sum(1 for _ in img_dir.glob("*.jpeg"))
        img_count += sum(1 for _ in img_dir.glob("*.png"))
        return EngineResult("marker", True, elapsed, str(md), img_count)
    except subprocess.TimeoutExpired:
        return EngineResult("marker", False, time.time() - t0, error="timeout 30min")
    except Exception as e:
        return EngineResult("marker", False, time.time() - t0, error=str(e))


def run_mineru(pdf: Path, out_dir: Path, pages: str | None,
               method: str, backend: str, lang: str | None) -> EngineResult:
    """调用 mineru 转换单个 PDF."""
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
            return EngineResult("mineru", False, elapsed, error=r.stderr[-2000:])
        stem = pdf.stem
        md = mineru_out / stem / method / f"{stem}.md"
        if not md.exists():
            mds = list(mineru_out.rglob("*.md"))
            md = mds[0] if mds else None
        if md is None:
            return EngineResult("mineru", False, elapsed, error="no md output")
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
        return EngineResult("mineru", False, time.time() - t0, error="timeout 30min")
    except Exception as e:
        return EngineResult("mineru", False, time.time() - t0, error=str(e))


# --------------------------------------------------------------------------- #
# Worker（用于 ProcessPoolExecutor 并行调用两引擎）
# --------------------------------------------------------------------------- #
def _marker_worker(pdf_str: str, out_str: str, pages: str | None) -> EngineResult:
    return run_marker(Path(pdf_str), Path(out_str), pages)


def _mineru_worker(pdf_str: str, out_str: str, pages: str | None,
                   method: str, backend: str, lang: str | None) -> EngineResult:
    return run_mineru(Path(pdf_str), Path(out_str), pages, method, backend, lang)


# --------------------------------------------------------------------------- #
# 差异对照
# --------------------------------------------------------------------------- #
# Markdown 归一化（消除纯格式差异，只保留内容差异）
# --------------------------------------------------------------------------- #
import re as _re
import re

_HEADING_RE = _re.compile(r"^#{1,6}\s")
_LATEX_BLOCK_RE = _re.compile(r"^\s*\$\$", re.MULTILINE)
_SUPERSCRIPT_RE = _re.compile(r"<sup>([^<]*)</sup>")
_LATEX_INLINE_RE = _re.compile(r"\$([^$]+)\$")
_IMAGE_RE = _re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LIST_BULLET_RE = _re.compile(r"^[•·\-\*]\s+")
_HTML_TABLE_RE = _re.compile(r"<table>.*?</table>", _re.DOTALL)
_MD_TABLE_ROW_RE = _re.compile(r"^\|.*\|\s*$")
_REF_ITEM_RE = _re.compile(r"^\[\d+\]\s")


_META_LINE_RE = _re.compile(
    r"^(\^[\*∗]\^\s*)?(Email addresses|Corresponding author|"
    r"https?://|doi:|DOI:|ORCID|Received|Accepted|Published)",
    _re.IGNORECASE,
)


def _normalize_for_diff(text: str) -> list[str]:
    """归一化 Markdown 文本，使 diff 只反映内容差异而非格式差异。

    归一化步骤：
      1. 统一引号（curly → straight）
      2. 统一标题层级（###+ → ##）
      3. 将 <sup>x</sup> 转为 ^x^（与 MinerU 的 LaTeX 行内公式对齐）
      4. 将行内 $x$ LaTeX 公式提取为纯文本（去掉 $ 符号，保留内容）
      5. 合并 $$...$$ 块为单段（MinerU 把 $$ 公式 $$ 切成三段，导致对齐失败）
      6. 合并连续非空行为一个段落（消除段落切分差异）
      7. 过滤元信息行（邮箱、通讯作者、DOI、URL）——两引擎对这类信息取舍不同，会引发连锁偏移
    """
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    
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
            content = _re.sub(r"^#{1,6}\s+", "## ", stripped)
            normalized_paragraphs.append(content)
            i += 1
            continue
        
        if stripped.startswith("$$"):
            if current_para:
                normalized_paragraphs.append(" ".join(current_para))
                current_para = []
            block_lines = [stripped]
            if not (stripped.endswith("$$") and len(stripped) > 2):
                j = i + 1
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
        line_norm = _re.sub(r"\s+", " ", line_norm).strip()
        
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
            curr_starts_lower = p[:1].islower() or p.startswith(("and ", "the ", "but ", "which ", "where ", "with ", "for ", "in "))
            if prev_ends_lower and curr_starts_lower and not _HEADING_RE.match(p) and not p.startswith("$$"):
                merged[-1] = prev + " " + p
                continue
        merged.append(p)
    
    return merged


def _count_real_diffs(diff_blocks: list[tuple]) -> int:
    """统计真实内容差异块数（非格式差异）。"""
    return sum(1 for tag, *_ in diff_blocks if tag != "equal")


# --------------------------------------------------------------------------- #
def make_diff(marker_md: Path | None, mineru_md: Path | None,
              out_path: Path, similarity_threshold: float = 0.85) -> tuple[int, int]:
    """生成模糊匹配 diff。

    先归一化两份 Markdown，然后用相似度阈值做段落对齐：
      - 相似度 >= threshold: 视为相同段落，仅标注微小差异字符
      - 相似度 < threshold: 视为真实差异，输出完整对照

    返回 (真实差异段落数, 总段落数)。
    """
    if not marker_md or not marker_md.exists():
        out_path.write_text("# Diff Skipped\n\nMarker 输出缺失。\n", encoding="utf-8")
        return 0, 0
    if not mineru_md or not mineru_md.exists():
        out_path.write_text("# Diff Skipped\n\nMinerU 输出缺失。\n", encoding="utf-8")
        return 0, 0

    m_paras = _normalize_for_diff(
        marker_md.read_text(encoding="utf-8", errors="replace"))
    u_paras = _normalize_for_diff(
        mineru_md.read_text(encoding="utf-8", errors="replace"))

    sm = difflib.SequenceMatcher(a=m_paras, b=u_paras, autojunk=False)

    diff_lines: list[str] = [
        "# 双引擎差异对照（归一化 + 模糊匹配）\n",
        f"- Marker: {len(m_paras)} 段",
        f"- MinerU: {len(u_paras)} 段",
        f"- 相似度阈值: {similarity_threshold}（高于此值视为相同，仅标注字符级差异）",
        f"- 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "说明：",
        "  [SAME]    两引擎段落相似度 >= 阈值（仅显示字符级差异）",
        "  [DIFF]    两引擎段落相似度 < 阈值（真实内容差异，需人工裁决）",
        "  [ONLY-M]  仅 Marker 有此段落",
        "  [ONLY-U]  仅 MinerU 有此段落",
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
                diff_lines.append(f"## [ONLY-U] 段落 {j1}-{j2}")
                preview = para[:500] + ("..." if len(para) > 500 else "")
                diff_lines.append(f"+ {preview}")
                diff_lines.append("")
                real_diff_count += 1
            continue

        if m_block and not u_block:
            for para in m_block:
                diff_lines.append(f"## [ONLY-M] 段落 {i1}-{i2}")
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
                diff_lines.append(f"## [ONLY-M] 段落 {i1+m_idx}")
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
                        f"## [SAME] 段落 {i1+m_idx}/{j1+best_u_idx} (相似度 {best_ratio:.2f})"
                    )
                    for cd in char_diffs[:5]:
                        diff_lines.append(f"  Marker: ...{cd['m']}...")
                        diff_lines.append(f"  MinerU: ...{cd['u']}...")
                    char_diff_count += 1
                    diff_lines.append("")
            else:
                diff_lines.append(
                    f"## [DIFF] 段落 {i1+m_idx}/{j1+best_u_idx} (相似度 {best_ratio:.2f})"
                )
                diff_lines.append(f"- {m_p[:500]}")
                diff_lines.append(f"+ {u_p[:500]}")
                diff_lines.append("")
                real_diff_count += 1

        for u_idx, u_p in enumerate(u_block):
            if u_idx not in used_u:
                diff_lines.append(f"## [ONLY-U] 段落 {j1+u_idx}")
                diff_lines.append(f"+ {u_p[:500]}")
                diff_lines.append("")
                real_diff_count += 1

    diff_lines.append("---")
    diff_lines.append(f"真实内容差异段落数 [DIFF/ONLY-*]: {real_diff_count}")
    diff_lines.append(f"字符级微差异段落数 [SAME]: {char_diff_count}")
    diff_lines.append(f"总段落数: {max(len(m_paras), len(u_paras))}")

    out_path.write_text("\n".join(diff_lines), encoding="utf-8")
    return real_diff_count, max(len(m_paras), len(u_paras))


def _extract_char_diffs(s1: str, s2: str, context: int = 20) -> list[dict]:
    """提取两个相似字符串的字符级差异片段。

    返回 [{"m": marker 片段, "u": mineru 片段}, ...]，
    每个片段包含差异点前后 context 个字符的上下文。
    """
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


# --------------------------------------------------------------------------- #
# 合并：MinerU 公式 + Marker 文字 + LLM 友好后处理
# --------------------------------------------------------------------------- #
_MARKER_ONLY_RE = _re.compile(r"^(Email addresses|Corresponding author|<sup>|Received|Accepted)", _re.IGNORECASE)

_OCR_FIXES = {
    "ofspring": "offspring", "diferent": "different", "eficiency": "efficiency",
    "efective": "effective", "efectively": "effectively", "efectiveness": "effectiveness",
    "ofers": "offers", "ofered": "offered", "ofset": "offset", "ofen": "often",
    "afect": "affect", "afected": "affected", "aford": "afford",
    "eiciency": "efficiency", "fective": "ffective",
}

_LATEX_SPACED_LETTERS_RE = _re.compile(
    r"\\mathrm\s*\{\s*((?:[A-Za-z]\s+){2,}[A-Za-z]?)\s*\}"
)
_LATEX_SPACED_REGEX = _re.compile(r"\\mathrm\s*\{\s*([^}]+?)\s*\}")


def _fix_ocr_errors(text: str) -> str:
    for wrong, right in _OCR_FIXES.items():
        text = _re.sub(r"\b" + _re.escape(wrong) + r"\b", right, text)
    return text


def _fix_latex_spacing(latex: str) -> str:
    """修复 MinerU LaTeX 中的字母间距问题。

    MinerU 常把 \\mathrm{Minimize} 输出为 \\mathrm{ M i n i m i z e }，
    以及 \\mathcal{G} 输出为 \\mathcal { G }。
    """
    def fix_mathrm(m):
        inner = m.group(1)
        if " " in inner and len(inner.replace(" ", "")) >= 2:
            compact = inner.replace(" ", "")
            if compact.isalpha():
                return f"\\mathrm{{{compact}}}"
        return m.group(0)

    latex = _LATEX_SPACED_LETTERS_RE.sub(fix_mathrm, latex)
    latex = _re.sub(r"\\mathcal\s*\{\s*([^}]+?)\s*\}", r"\\mathcal{\1}", latex)
    latex = _re.sub(r"\\mathbf\s*\{\s*([^}]+?)\s*\}", r"\\mathbf{\1}", latex)
    latex = _re.sub(r"\\operatorname\*?\s*\{\s*([^}]+?)\s*\}", r"\\operatorname{\1}", latex)
    latex = _re.sub(r"\s*\\\\\s*", r" \\\\ ", latex)
    return latex


def _fix_html_tables(md: str) -> str:
    """把 MinerU 的 HTML 表格转成 Markdown 表格（LLM 更易理解）。"""
    def html_to_md_table(match):
        html = match.group(0)
        rows = _re.findall(r"<tr>(.*?)</tr>", html, _re.DOTALL)
        if not rows:
            return html
        md_rows = []
        for i, row in enumerate(rows):
            cells = _re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, _re.DOTALL)
            cells = [_re.sub(r"\s+", " ", c).strip() for c in cells]
            if not cells:
                continue
            md_rows.append("| " + " | ".join(cells) + " |")
            if i == 0:
                md_rows.append("|" + "---|" * len(cells))
        return "\n".join(md_rows) if md_rows else html

    return _re.sub(r"<table>.*?</table>", html_to_md_table, md, flags=_re.DOTALL)


def _extract_metadata(md_text: str, stem: str) -> dict:
    """从 Markdown 提取标题、作者、摘要等元数据，供 LLM 快速定位。"""
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
            m = _re.match(r"^#{1,3}\s+(.+)$", stripped)
            if m and not _re.match(r"^(Abstract|Keywords|Introduction)", m.group(1), _re.IGNORECASE):
                content = m.group(1)
                if len(content) > 10 and not content.startswith("$"):
                    title = content
                    continue
            elif not title and i < 3 and not stripped.startswith("#") and len(stripped) > 15:
                if not _re.match(r"^(Abstract|Keywords|\\\[)", stripped, _re.IGNORECASE):
                    title = stripped
                    continue
        if not authors and title and stripped != title and not stripped.startswith("#"):
            if i < 8 and any(c.isalpha() for c in stripped):
                if "@" in stripped or "Universit" in stripped or any(name in stripped for name in [",", " and "]):
                    if not stripped.startswith("Abstract") and not stripped.startswith("Keywords"):
                        authors = stripped
                        continue
        if _re.match(r"^#{1,6}\s*Abstract", stripped, _re.IGNORECASE) or (stripped.lower() == "abstract" and not abstract):
            in_abstract = True
            continue
        if in_abstract:
            if _re.match(r"^#{1,6}\s", stripped) or _re.match(r"^(Keywords|1\s+Introduction)", stripped, _re.IGNORECASE):
                in_abstract = False
            elif stripped and not stripped.startswith("<!--") and not stripped.startswith("---"):
                abstract = (abstract + " " + stripped).strip()
        m = _re.match(r"^(#{1,6})\s+(\d+(?:\.\d+)*)\s+(.+)$", stripped)
        if m:
            sections.append({"level": len(m.group(1)), "num": m.group(2), "title": m.group(3)})

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
    """合并两份 Markdown 为单个最适合 LLM 读取的版本。

    策略：
      1. 用归一化段落做对齐，但输出原始文本（保留图片引用、公式格式）
      2. 相似度 >= 0.85 的段落取 Marker 原文（英文 OCR 更准）
      3. 相似度 < 0.85 的段落取 MinerU 原文（公式更准）
      4. 后处理：修复 OCR 错误、LaTeX 间距、HTML 表格
      5. 添加 LLM 友好元数据头

    返回 (merged_para_count, supplement_count)。
    """
    if not mineru_md or not mineru_md.exists():
        if marker_md and marker_md.exists():
            shutil.copy(marker_md, out_path)
            return 0, 0
        out_path.write_text("# Merge Skipped\n\n两份输出均缺失。\n", encoding="utf-8")
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

    marker_tables = _re.findall(r"((?:\|[^\n]+\|\s*\n){2,})", m_raw)
    table_idx = 0
    def replace_table(m):
        nonlocal table_idx
        if table_idx < len(marker_tables):
            t = marker_tables[table_idx].rstrip()
            table_idx += 1
            return t
        return m.group(0)
    merged_text = _re.sub(r"\[TABLE\]", replace_table, merged_text)

    merged_text = _fix_ocr_errors(merged_text)
    merged_text = _fix_latex_spacing(merged_text)
    merged_text = _fix_html_tables(merged_text)

    stem = mineru_md.stem
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
        "engines: MinerU(公式主) + Marker(文字主)",
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
        for match in _re.finditer(r"!\[([^\]]*)\]\(([^)]+)\)", img_pattern):
            alt, path = match.group(1), match.group(2)
            image_list.append(f"- {source}: `{path}`" + (f" (alt: {alt})" if alt else ""))

    if image_list:
        seen = set()
        unique_images = []
        for img in image_list:
            path_part = img.split("`")[1] if "`" in img else img
            if path_part not in seen:
                seen.add(path_part)
                unique_images.append(img)
        final_text += "\n\n---\n\n## Images Index\n\n"
        final_text += f"共 {len(unique_images)} 张图片（Marker {len(m_raw_lines)} 行, MinerU {len(u_raw_lines)} 行）。\n\n"
        for img in unique_images:
            final_text += img + "\n"

    out_path.write_text(final_text, encoding="utf-8")
    return len(u_paras), supplement_count


# --------------------------------------------------------------------------- #
# 单篇处理
# --------------------------------------------------------------------------- #
def process_one(pdf: Path, output_root: Path, engines: str, pages: str | None,
                method: str, backend: str, lang: str | None,
                max_workers: int = 2) -> PaperResult:
    stem = pdf.stem
    paper_dir = output_root / stem
    paper_dir.mkdir(parents=True, exist_ok=True)
    result = PaperResult(pdf_path=str(pdf), stem=stem)

    # 双引擎并行（max_workers 由 CLI 参数控制：默认 2，可降到 1 串行省显存）
    if engines == "both":
        workers = max(1, min(max_workers, 2))  # both 模式最多就 2 个引擎
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {}
            futs["marker"] = ex.submit(_marker_worker, str(pdf), str(paper_dir), pages)
            futs["mineru"] = ex.submit(_mineru_worker, str(pdf), str(paper_dir), pages,
                                       method, backend, lang)
            for key, fut in futs.items():
                er = fut.result()
                setattr(result, key, er)
    elif engines == "marker":
        result.marker = run_marker(pdf, paper_dir, pages)
    elif engines == "mineru":
        result.mineru = run_mineru(pdf, paper_dir, pages, method, backend, lang)
    else:
        raise ValueError(f"unknown engines: {engines}")

    # 生成 diff 和 merge（需要两路都成功）
    merged_path = paper_dir / "_MERGED.md"
    if result.marker and result.mineru and result.marker.ok and result.mineru.ok:
        # 守卫已保证 ok=True；ok=True 的语义契约是 md_path 非空（见 run_marker/run_mineru）
        assert result.marker.md_path is not None
        assert result.mineru.md_path is not None
        diff_path = paper_dir / "_DIFF.md"
        diff_count, total = make_diff(
            Path(result.marker.md_path),
            Path(result.mineru.md_path),
            diff_path,
        )
        result.diff_path = str(diff_path)
        result.diff_line_count = diff_count

        merged_total, merged_supp = merge_md(
            Path(result.marker.md_path),
            Path(result.mineru.md_path),
            merged_path,
        )
        result.merged_path = str(merged_path)
        result.merged_supplement_count = merged_supp

    # 写 meta
    meta_path = paper_dir / "_META.json"
    meta = {
        "pdf_path": result.pdf_path,
        "stem": result.stem,
        "engines": engines,
        "pages": pages,
        "marker": asdict(result.marker) if result.marker else None,
        "mineru": asdict(result.mineru) if result.mineru else None,
        "diff_path": result.diff_path,
        "diff_line_count": result.diff_line_count,
        "merged_path": getattr(result, "merged_path", None),
        "merged_supplement_count": getattr(result, "merged_supplement_count", 0),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


# --------------------------------------------------------------------------- #
# 批量处理
# --------------------------------------------------------------------------- #
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
        m_t = f"{r.marker.elapsed_sec:.0f}s" if r.marker and r.marker.ok else \
              ("FAIL" if r.marker else "-")
        u_t = f"{r.mineru.elapsed_sec:.0f}s" if r.mineru and r.mineru.ok else \
              ("FAIL" if r.mineru else "-")
        d = str(r.diff_line_count) if r.diff_path else "-"
        print(f"{r.stem:<40} {m_t:>8} {u_t:>8} {d:>6}")
    print("=" * 70)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(
        description="Paper Reader: Marker + MinerU 双引擎 PDF 对照阅读器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("pdf", type=Path,
                    help="PDF 文件或目录（含 PDF 的目录会批量处理）")
    ap.add_argument("-o", "--output", type=Path, default=None,
                    help="输出根目录（默认: 输入 PDF/目录的同级 paper-analysis 目录）")
    ap.add_argument("-e", "--engines", choices=["both", "marker", "mineru"],
                    default="both", help="使用哪些引擎（默认 both）")
    ap.add_argument("-p", "--pages",
                    help="页范围，如 '0-9' 或 '5'（0-based）")
    ap.add_argument("-b", "--batch", action="store_true",
                    help="批量模式（目录下所有 PDF 串行处理）")
    ap.add_argument("--mineru-method", choices=["auto", "ocr", "txt"],
                    default="auto", help="MinerU 解析方法")
    ap.add_argument("--mineru-backend", choices=["pipeline", "hybrid-engine"],
                    default="pipeline", help="MinerU 后端（hybrid 精度高但慢）")
    ap.add_argument("-l", "--lang",
                    help="PDF 语言（mineru pipeline 模式），如 ch、korean、arabic")
    ap.add_argument("--max-workers", type=int, default=2,
                    help="单 PDF 的引擎并发数（默认 2 = marker+mineru 同时跑）。"
                         "减小到 1 可让两引擎串行，省显存但变慢；增大需确保 GPU 显存够用")
    ap.add_argument("--gpu-fraction", type=float, default=0.4,
                    help="每个 Windows GPU 子进程最多可用显存比例（0-1，默认 0.4）。"
                         "0 表示不限制（仅用于纯 CPU 模式）。16GB GPU × 0.4 = 6.4GB/进程")
    ap.add_argument("--cpu-threads", type=int, default=6,
                    help="每个 GPU 子进程的 CPU 线程上限（默认 6）。"
                         "防两个 PyTorch 进程各起 24 线程互相抢核")
    ap.add_argument("--max-concurrent-pdfs", type=int, default=1,
                    help="批量模式下最多同时处理的 PDF 数（默认 1 = 串行）。"
                         "增大可大幅提速但 N×max_workers 个 GPU 进程会同时跑")
    ap.add_argument("--gpu-cap-fraction", type=float, default=0.9,
                    help="设备级 GPU 总显存上限（0-1，默认 0.9=90 百分比）。"
                         "当本进程 + 其他进程（如 CV 训练）的总显存超过此值时，"
                         "paper-reader 会排队等待（最多 --gpu-wait-timeout 秒）。"
                         "设为 0 禁用协调，回到无序抢占模式（不推荐）")
    ap.add_argument("--gpu-wait-timeout", type=float, default=600.0,
                    help="设备级 GPU 预算不足时，等待其他进程释放的最长时间（秒，默认 600=10分钟）。"
                         "超时则放弃该 PDF 并打印警告。设为 0 表示不等待、立即放弃")
    args = ap.parse_args()

    # 应用 GPU 资源栅栏配置到模块级全局
    global _GPU_FRACTION, _CPU_THREADS, _GPU_GOVERNOR, _GPU_WAIT_TIMEOUT
    _GPU_FRACTION = args.gpu_fraction
    _CPU_THREADS = args.cpu_threads
    _GPU_WAIT_TIMEOUT = args.gpu_wait_timeout
    if 0.0 < args.gpu_fraction <= 1.0:
        print(f"GPU 限制: 每进程 {args.gpu_fraction*100:.0f}% 显存，"
              f"{args.cpu_threads} CPU 线程", file=sys.stderr)
    elif args.gpu_fraction != 0:
        ap.error(f"--gpu-fraction 必须在 (0, 1] 范围内或为 0（不限制），当前 {args.gpu_fraction}")
    else:
        print("GPU 限制: 已禁用（纯 CPU 模式或手动管控）", file=sys.stderr)

    # 初始化设备级 GPU 协调器（防 paper-reader + CV 训练同时跑时过载）
    if 0.0 < args.gpu_cap_fraction <= 1.0:
        _GPU_GOVERNOR = GpuGovernor(cap_fraction=args.gpu_cap_fraction)
        print(f"GPU 协调器: 设备上限 {args.gpu_cap_fraction*100:.0f}%，"
              f"等待超时 {args.gpu_wait_timeout:.0f}s", file=sys.stderr)
    elif args.gpu_cap_fraction != 0:
        ap.error(f"--gpu-cap-fraction 必须在 (0, 1] 范围内或为 0（禁用），当前 {args.gpu_cap_fraction}")
    else:
        print("GPU 协调器: 已禁用（抢占模式，多任务可能过载）", file=sys.stderr)

    # 默认输出目录: 输入 PDF/目录的同级 paper-analysis/
    if args.output is None:
        args.output = args.pdf.resolve().parent / "paper-analysis"

    # 校验 venvs
    if args.engines in ("both", "marker") and not MARKER_BIN.exists():
        print(f"ERROR: marker venv 缺失: {MARKER_BIN}", file=sys.stderr)
        print("请先运行: bash ~/.claude/skills/paper-reader/scripts/bootstrap.sh",
              file=sys.stderr)
        return 2
    if args.engines in ("both", "mineru") and not MINERU_BIN.exists():
        print(f"ERROR: mineru venv 缺失: {MINERU_BIN}", file=sys.stderr)
        print("请先运行: bash ~/.claude/skills/paper-reader/scripts/bootstrap.sh",
              file=sys.stderr)
        return 2

    pdfs = find_pdfs(args.pdf)
    if not pdfs:
        print(f"ERROR: 未找到 PDF: {args.pdf}", file=sys.stderr)
        return 1

    args.output.mkdir(parents=True, exist_ok=True)
    print(f"将处理 {len(pdfs)} 个 PDF，输出到: {args.output}")
    print(f"引擎: {args.engines}  页范围: {args.pages or '全部'}")
    print(f"单 PDF 并发: {args.max_workers} 引擎 | 批量并发: {args.max_concurrent_pdfs} PDF")

    results: list[PaperResult] = []
    if args.max_concurrent_pdfs <= 1 or len(pdfs) == 1:
        # 串行模式（默认）：一次一个 PDF，最稳
        for i, pdf in enumerate(pdfs, 1):
            print(f"\n[{i}/{len(pdfs)}] {pdf.name}")
            try:
                r = process_one(
                    pdf, args.output, args.engines, args.pages,
                    args.mineru_method, args.mineru_backend, args.lang,
                    max_workers=args.max_workers,
                )
                results.append(r)
            except KeyboardInterrupt:
                print("\n中断。", file=sys.stderr)
                break
            except Exception as e:
                print(f"  ERROR: {e}", file=sys.stderr)
                results.append(PaperResult(pdf_path=str(pdf), stem=pdf.stem))
    else:
        # 批量并发模式：N 个 PDF 同时处理。
        # 注意：总 GPU 进程数 = max_concurrent_pdfs × max_workers，
        # 必须确保 GPU 显存够（fraction × 进程数 ≤ 1）。
        from concurrent.futures import ThreadPoolExecutor
        total_procs = args.max_concurrent_pdfs * args.max_workers
        if 0.0 < args.gpu_fraction and total_procs * args.gpu_fraction > 1.0 + 1e-6:
            print(f"⚠ 警告: {total_procs} 进程 × {args.gpu_fraction*100:.0f}% 显存 = "
                  f"{total_procs*args.gpu_fraction*100:.0f}% > 100%，必将 OOM！",
                  file=sys.stderr)
            print(f"  建议：减小 --max-concurrent-pdfs 或 --gpu-fraction",
                  file=sys.stderr)
        with ThreadPoolExecutor(max_workers=args.max_concurrent_pdfs) as tex:
            indexed = list(enumerate(pdfs, 1))
            def _run_one(idx_pdf):
                i, pdf = idx_pdf
                print(f"\n[{i}/{len(pdfs)}] {pdf.name}")
                try:
                    return process_one(
                        pdf, args.output, args.engines, args.pages,
                        args.mineru_method, args.mineru_backend, args.lang,
                        max_workers=args.max_workers,
                    )
                except Exception as e:
                    print(f"  ERROR: {e}", file=sys.stderr)
                    return PaperResult(pdf_path=str(pdf), stem=pdf.stem)
            try:
                for r in tex.map(_run_one, indexed):
                    results.append(r)
            except KeyboardInterrupt:
                print("\n中断（已完成的 PDF 保留）。", file=sys.stderr)

    print_summary(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
