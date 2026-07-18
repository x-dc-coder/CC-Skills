#!/usr/bin/env python3
"""win-launcher — Windows-side Job Object wrapper for orphan process cleanup.

Design
------
This script runs on Windows (via ``pythonw.exe``) as a standalone launcher.
It wraps a child Python process in a Windows Job Object with
``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` — when the wrapper exits (cleanly or
crashed), the OS **automatically terminates every child process** in the job.
No zombies. No orphan GPU processes.

On non-Windows (Linux / WSL-side tests), the Job Object code path is skipped
and the child is launched without protection — graceful degradation.

Why not in gpu_safe_subprocess.py?
----------------------------------
``gpu_safe_subprocess.py`` runs in WSL-side Linux Python.  Linux Python
cannot call Windows ctypes APIs — ``ctypes.windll`` arrives at the WSL
``wslclient`` proxy layer, not the real Windows kernel32.  The Job Object
must be created in a **native Windows Python process**.  This script is that
process.

Known tradeoffs
---------------
- Race between ``Popen`` and ``AssignProcessToJobObject``: ~microseconds,
  acceptable because GPU scripts don't ``fork()`` immediately.
- ``OpenProcess(PROCESS_SET_QUOTA|PROCESS_TERMINATE, …)`` uses the PID
  (not ``Popen._handle`` which is a pipe handle, not a process handle).

Usage (WSL → Windows)
---------------------
.. code-block:: bash

    pythonw.exe win-launcher.py \\
        --py-exe "E:\\venvs\\marker\\Scripts\\python.exe" \\
        --code "$(echo -n 'import torch; print(torch.cuda.is_available())' | base64 -w0)" \\
        --log-file "E:\\temp\\job.log" \\
        --gpu-fraction 0.4 \\
        --cpu-threads 6

Usage (test on Linux)
---------------------
.. code-block:: bash

    python3 win-launcher.py \\
        --py-exe /usr/bin/python3 \\
        --code "$(echo -n 'import sys; print("hello from wrapper"); sys.exit(42)' | base64 -w0)"
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

def _detect_windows() -> bool:
    """True if ctypes.windll.kernel32 is functional (real Windows)."""
    try:
        import ctypes  # noqa: F401
        ctypes.windll.kernel32  # type: ignore[attr-defined]
        return True
    except (ImportError, AttributeError):
        return False


ON_WINDOWS = _detect_windows()


# ---------------------------------------------------------------------------
# Job Object (Windows only)
# ---------------------------------------------------------------------------

if ON_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

    # Constants
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9

    PROCESS_SET_QUOTA = 0x0100
    PROCESS_TERMINATE = 0x0001

    # Structs
    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    def _create_job_object() -> int | None:
        """Create a Job Object with KILL_ON_JOB_CLOSE.

        Returns the job handle (as int) on success, or None if creation fails.
        """
        handle = _kernel32.CreateJobObjectW(None, None)
        if not handle:
            err = _kernel32.GetLastError()
            print(
                f"WARNING: CreateJobObjectW failed (err={err}). "
                f"Child process will NOT be protected against orphan cleanup.",
                file=sys.stderr,
            )
            return None

        extended = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        extended.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

        if not _kernel32.SetInformationJobObject(
            handle,
            JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
            ctypes.byref(extended),
            ctypes.sizeof(extended),
        ):
            err = _kernel32.GetLastError()
            print(
                f"WARNING: SetInformationJobObject failed (err={err}). "
                f"Child process will NOT be protected against orphan cleanup.",
                file=sys.stderr,
            )
            _kernel32.CloseHandle(handle)
            return None

        return handle

    def _assign_to_job(job_handle: int, pid: int) -> None:
        """Assign a child process to the job object.

        Opens the process via ``OpenProcess`` (NOT ``Popen._handle`` — that is
        a pipe handle, not a process handle).  Warnings are printed on failure
        but never abort.
        """
        hproc = _kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
        if not hproc:
            err = _kernel32.GetLastError()
            print(
                f"WARNING: OpenProcess failed for pid={pid} "
                f"(err={err}). "
                f"Child will NOT be protected against orphan cleanup.",
                file=sys.stderr,
            )
            return

        try:
            if not _kernel32.AssignProcessToJobObject(job_handle, hproc):
                err = _kernel32.GetLastError()
                print(
                    f"WARNING: AssignProcessToJobObject failed for pid={pid} "
                    f"(err={err}). "
                    f"Child will NOT be protected against orphan cleanup.",
                    file=sys.stderr,
                )
        finally:
            _kernel32.CloseHandle(hproc)


# ---------------------------------------------------------------------------
# Environment construction
# ---------------------------------------------------------------------------

def _build_env(
    gpu_fraction: float | None,
    cpu_threads: int | None,
) -> dict[str, str]:
    """Build the Windows-side environment for the child process.

    No WSLENV needed — this script runs natively on Windows so every
    ``os.environ`` key is already a Windows env var.

    Sets UTF-8 triple-guard, streaming/progress-bar compat, GPU memory
    limits, and CPU thread constraints.
    """
    env = os.environ.copy()

    # UTF-8 triple guard
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"

    # Streaming / progress-bar compatibility
    # 不设 TQDM_DISABLE —— tqdm 默认 disable=False（启用）。
    # bool("False")==True 会反而禁用进度条（tqdm envwrap 的 bug）。
    env["TTY_COMPATIBLE"] = "1"
    env["TTY_INTERACTIVE"] = "0"
    env["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"

    # GPU limits
    if gpu_fraction is not None:
        env["PYTORCH_CUDA_ALLOC_CONF"] = (
            f"per_process_memory_fraction:{gpu_fraction},"
            f"garbage_collection_threshold:0.7"
        )

    # CPU thread constraints
    if cpu_threads is not None:
        env["OMP_NUM_THREADS"] = str(cpu_threads)
        env["MKL_NUM_THREADS"] = str(cpu_threads)
        env["TOKENIZERS_PARALLELISM"] = "false"

    return env


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Windows-side Job Object launcher for orphan cleanup",
    )
    parser.add_argument(
        "--py-exe", required=True,
        help="Path to python.exe / pythonw.exe on Windows (or any Python on Linux)",
    )
    parser.add_argument(
        "--code", required=True,
        help="Base64-encoded Python code to execute (-c equivalent)",
    )
    parser.add_argument(
        "--args", default=None,
        help="JSON array of additional CLI arguments for the child script",
    )
    parser.add_argument(
        "--log-file", default=None,
        help="If set, child stdout/stderr go to this file; wrapper just waits",
    )
    parser.add_argument(
        "--gpu-fraction", type=float, default=None,
        help="GPU memory fraction per process (0-1). Sets PYTORCH_CUDA_ALLOC_CONF",
    )
    parser.add_argument(
        "--cpu-threads", type=int, default=None,
        help="CPU thread limit (sets OMP_NUM_THREADS / MKL_NUM_THREADS)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # ── Decode --code from base64 ─────────────────────────────────────────
    try:
        decoded_code = base64.b64decode(args.code).decode("utf-8")
    except Exception as exc:
        print(f"ERROR: Failed to decode --code as base64: {exc}", file=sys.stderr)
        return 1

    # ── Parse --args (JSON array) ────────────────────────────────────────
    extra_args: list[str] = []
    if args.args is not None:
        try:
            parsed = json.loads(args.args)
            if not isinstance(parsed, list):
                print("ERROR: --args must be a JSON array", file=sys.stderr)
                return 1
            extra_args = [str(x) for x in parsed]
        except json.JSONDecodeError as exc:
            print(f"ERROR: --args is not valid JSON: {exc}", file=sys.stderr)
            return 1

    # ── Platform banner ──────────────────────────────────────────────────
    if not ON_WINDOWS:
        print(
            "WARNING: Job Object unavailable on this platform (non-Windows). "
            "Child process will NOT be protected against orphan cleanup.",
            file=sys.stderr,
        )

    # ── Build env ────────────────────────────────────────────────────────
    env = _build_env(
        gpu_fraction=args.gpu_fraction,
        cpu_threads=args.cpu_threads,
    )

    # ── Build command ────────────────────────────────────────────────────
    cmd = [args.py_exe, "-u", "-X", "utf8", "-c", decoded_code] + extra_args

    # ── Launch child ─────────────────────────────────────────────────────
    log_fh = None
    if args.log_file:
        # Write stdout/stderr directly to log file; wrapper just waits.
        log_fh = open(args.log_file, "a", encoding="utf-8")
        proc = subprocess.Popen(
            cmd,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            env=env,
        )
    else:
        # Forward child stdout line-by-line to own stdout.
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )

    # ── Job Object assignment (Windows only) ─────────────────────────────
    if ON_WINDOWS:
        job_handle = _create_job_object()
        if job_handle is not None:
            _assign_to_job(job_handle, proc.pid)

    # ── Forward / collect output ─────────────────────────────────────────
    if args.log_file:
        # log-file mode: child writes directly to file; just wait.
        try:
            returncode = proc.wait()
        except KeyboardInterrupt:
            proc.wait()
            returncode = proc.returncode if proc.returncode is not None else 130
        finally:
            if log_fh is not None:
                log_fh.close()
    else:
        # Streaming mode: forward lines to own stdout.
        assert proc.stdout is not None
        try:
            for line in iter(proc.stdout.readline, ""):
                sys.stdout.write(line)
                sys.stdout.flush()
            proc.wait()
            returncode = proc.returncode
        except KeyboardInterrupt:
            proc.wait()
            returncode = proc.returncode if proc.returncode is not None else 130
        finally:
            # Drain any remaining output before returning
            try:
                for line in iter(proc.stdout.readline, ""):
                    sys.stdout.write(line)
                    sys.stdout.flush()
            except (ValueError, OSError):
                pass

    return returncode if returncode is not None else 1


if __name__ == "__main__":
    sys.exit(main())
