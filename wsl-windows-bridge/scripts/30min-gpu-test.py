#!/usr/bin/env python3
"""30-minute GPU training endurance test with real-time log monitoring.

================================================================
PURPOSE: Verify GPU stability under sustained load (30 min continuous training).
         Exercises: CUDA, VRAM, PyTorch autograd, WSL→Windows bridge, launch_detached.

Phases:
  1. Launch detached PyTorch training on Windows GPU via pythonw.exe
  2. Monitor log every ~2 minutes (13 checkpoints)
  3. Final verification + copy permanent log
  4. Cleanup temp files

Output: ~/test-results/30min-gpu-test/30min-gpu-test_<PID>.log (permanent)
================================================================
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Ensure we can import from skills
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gpu_safe_subprocess import GpuLimits, launch_detached

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────
PYW_EXE = r"E:\venvs\marker\Scripts\pythonw.exe"
# WSL drvfs path (launch_detached needs WSL path, not Windows drive-letter)
PYW_WSL = "/mnt/e/venvs/marker/Scripts/pythonw.exe"
PERMANENT_LOG_DIR = Path.home() / "test-results" / "30min-gpu-test"
JOB_NAME = "30min-gpu-test"

# ─────────────────────────────────────────────────────────────
# Training code (runs on Windows GPU)
# ─────────────────────────────────────────────────────────────
TRAINING_CODE = r"""
import torch, time, sys

device = torch.device('cuda')
print(f'device: {torch.cuda.get_device_name(0)}', flush=True)
print(f'VRAM total: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB', flush=True)
print(f'PyTorch: {torch.__version__} | CUDA: {torch.version.cuda}', flush=True)

# Set per-process memory fraction (Python API, not env var)
torch.cuda.set_per_process_memory_fraction(0.25)
print(f'memory_fraction: 0.25', flush=True)

# 2-layer MLP
model = torch.nn.Sequential(
    torch.nn.Linear(2048, 512),
    torch.nn.ReLU(),
    torch.nn.Linear(512, 128),
    torch.nn.ReLU(),
    torch.nn.Linear(128, 10),
).to(device)
criterion = torch.nn.CrossEntropyLoss()
optimizer = torch.optim.Adam(model.parameters(), lr=0.001)

start_time = time.time()
running_loss = 0.0

for epoch in range(1800):
    x = torch.randn(64, 2048, device=device)
    target = torch.randint(0, 10, (64,), device=device)
    y = model(x)
    loss = criterion(y, target)
    loss.backward()
    optimizer.step()
    optimizer.zero_grad()
    running_loss += loss.item()

    if epoch % 60 == 0:
        elapsed = time.time() - start_time
        avg_loss = running_loss / 60 if epoch > 0 else loss.item()
        running_loss = 0.0
        vram_used = torch.cuda.memory_allocated() / 1024**3
        print(f'epoch {epoch:4d}/1800 | loss={avg_loss:.4f} | VRAM={vram_used:.2f}GB | elapsed={elapsed:.0f}s', flush=True)

    time.sleep(1)  # 1s per epoch = 1800s = 30 min

elapsed = time.time() - start_time
print(f'TRAINING COMPLETE total_time={elapsed:.0f}s ({elapsed/60:.1f}min)', flush=True)
"""


def main() -> None:
    # ── Phase 1: Launch ──────────────────────────────────────
    PERMANENT_LOG_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Phase 1: Launching 30-minute GPU training test")
    print(f"Python: {PYW_EXE}")
    print(f"Log dir: {PERMANENT_LOG_DIR}")
    print("=" * 60)
    sys.stdout.flush()

    handle = launch_detached(
        py_exe=PYW_WSL,
        code=TRAINING_CODE,
        job_name=JOB_NAME,
        limits=GpuLimits(gpu_memory_fraction=0.25, cpu_threads=4),
    )
    monitor_start = time.time()

    print(f"\nLaunch OK @ {time.strftime('%H:%M:%S')}")
    print(f"  Windows PID: {handle.win_pid}")
    print(f"  Live log:    {handle.wsl_log_path}")
    print(f"  PID file:    {handle.wsl_pid_path}")

    # Copy handle files to permanent location
    perm_log = PERMANENT_LOG_DIR / f"30min-gpu-test_{handle.win_pid}.log"
    shutil.copy2(str(handle.wsl_log_path), str(perm_log))
    print(f"  Permanent:   {perm_log}")
    sys.stdout.flush()

    # ── Phase 2: Monitor (sample every ~2 minutes) ───────────
    # Checkpoints in seconds from launch
    checkpoints = [30, 120, 300, 480, 600, 720, 900, 1080, 1200, 1320, 1500, 1680, 1800]

    print("\n" + "=" * 60)
    print("Phase 2: Real-time Log Monitoring (13 checkpoints)")
    print("=" * 60)
    sys.stdout.flush()

    last_size = 0
    alive = True

    for checkpoint in checkpoints:
        # Wait until checkpoint time
        elapsed = time.time() - monitor_start
        remaining = max(0, checkpoint - elapsed)
        while remaining > 0:
            time.sleep(min(remaining, 5))
            elapsed = time.time() - monitor_start
            remaining = max(0, checkpoint - elapsed)

        elapsed = time.time() - monitor_start
        try:
            content = handle.wsl_log_path.read_text(encoding="utf-8")
            size = len(content)
            delta = size - last_size
            last_size = size

            lines = content.strip().split("\n")
            last_lines = lines[-5:] if len(lines) >= 5 else lines

            # Check if process alive
            r = subprocess.run(
                ["tasklist.exe", "/FI", f"PID eq {handle.win_pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
            )
            alive = f'"{handle.win_pid}"' in r.stdout or str(handle.win_pid) in r.stdout

            print(f"\n[{elapsed:.0f}s / {checkpoint}s] size={size}B (+{delta}B) | alive={alive}")
            for line in last_lines:
                print(f"  {line[:140]}")
            sys.stdout.flush()

            if not alive:
                print("  ⚠️  Process not alive — may have completed or crashed")
                break
        except Exception as exc:
            print(f"  ERROR at checkpoint {checkpoint}s: {exc}")
            sys.stdout.flush()

    # Wait for any remaining output
    print("\n--- Waiting for final output (5s) ---")
    sys.stdout.flush()
    time.sleep(5)

    # ── Phase 3: Final verification ──────────────────────────
    print("\n" + "=" * 60)
    print("Phase 3: Final Verification")
    print("=" * 60)
    sys.stdout.flush()

    try:
        content = handle.wsl_log_path.read_text(encoding="utf-8")
        final_size = len(content)
        lines = content.strip().split("\n")
        total_lines = len(lines)

        has_device = "device:" in content
        has_loss = "loss=" in content
        has_complete = "TRAINING COMPLETE" in content
        has_vram = "VRAM=" in content
        has_pytorch = "PyTorch:" in content

        print(f"Log size:    {final_size} bytes")
        print(f"Total lines: {total_lines}")
        print(f"Device info: {'✅' if has_device else '❌'}")
        print(f"PyTorch ver: {'✅' if has_pytorch else '❌'}")
        print(f"Loss output: {'✅' if has_loss else '❌'}")
        print(f"VRAM track:  {'✅' if has_vram else '❌'}")
        print(f"Complete:    {'✅' if has_complete else '⏳ (may still be running or crashed)'}")
        if not has_complete:
            total_elapsed = time.time() - monitor_start
            print(f"             (elapsed since launch: {total_elapsed:.0f}s / {total_elapsed/60:.1f}min)")

        print(f"\n--- Last 10 lines ---")
        for line in lines[-10:]:
            print(f"  {line[:150]}")

        # Copy final log to permanent location
        shutil.copy2(str(handle.wsl_log_path), str(perm_log))
        print(f"\n✅ Permanent log saved to: {perm_log}")
        print(f"   Review: cat {perm_log}")
        sys.stdout.flush()
    except Exception as exc:
        print(f"❌ Final check error: {exc}")
        sys.stdout.flush()

    # ── Phase 4: Cleanup ─────────────────────────────────────
    print("\n" + "=" * 60)
    print("Phase 4: Cleanup")
    print("=" * 60)
    sys.stdout.flush()

    # Kill if still running
    r = subprocess.run(
        ["taskkill.exe", "/F", "/PID", str(handle.win_pid)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
    )
    if r.returncode == 0:
        print(f"Killed PID {handle.win_pid}")
    else:
        print(f"PID {handle.win_pid} not found (already exited) or kill failed: {r.stdout.strip()}")
    print("Cleanup done.")
    print(f"\n📄 Permanent log: {perm_log}")
    print("=" * 60)


if __name__ == "__main__":
    main()
