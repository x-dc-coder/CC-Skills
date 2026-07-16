#!/usr/bin/env python3
"""gpu_safe_subprocess — WSL → Windows GPU 子进程的资源栅栏封装.

为什么需要这个模块
-------------------
WSL 通过 `cmd.exe /c` 启动的 Windows GPU 进程 **不受 `.wslconfig` 限制**。
（`.wslconfig` 只管 WSL VM 自己，不管从 WSL 起的 Windows 进程。）
如果同时启动多个 GPU 进程（例如 paper-reader 的 Marker + MinerU 双引擎），
它们会直接吃 Windows 侧的 RAM + 整块 GPU 显存，没有任何上层约束 →
显存吃满 → CUDA 驱动 hang → 全系统冻住。

本模块用三层防护堵住这个漏洞：

1. **GPU 显存配额**（最关键，PyTorch 官方推荐）
   通过 `PYTORCH_CUDA_ALLOC_CONF=per_process_memory_fraction:X` 限制每个
   子进程最多占用多少 GPU 显存。超额时抛 Python 异常（不杀驱动）。
   官方文档：https://pytorch.org/docs/stable/notes/cuda.html#optimizing-memory-usage

2. **CPU 线程约束**
   通过 `OMP_NUM_THREADS` / `MKL_NUM_THREADS` 防止 N 个 PyTorch 子进程
   各自起满线程池互相抢核（典型：两个进程各 24 线程抢 24 逻辑核）。

3. **进程数硬上限**（multiprocessing.Semaphore）
   由调用方自己 `acquire/release`，避免外部多开 paper-reader 时 N×2 个
   Windows 进程同时冲向同一块 GPU。

为什么不在这里集成 Windows Job Object
-------------------------------------
Job Object 需要 ctypes P/Invoke，在 WSL 侧 Python（Linux）无法直接调用
Windows API。Job Object 的使用必须在 Windows 侧 Python 进程里完成，
而 paper-reader 的 Marker/MinerU 是被 `cmd.exe /c` 拉起的第三方 CLI，
我们没有干净的注入点。改 venv 里的 marker/mineru 入口违反"不污染第三方 venv"原则。

退路：环境变量方案（Layer 1 + 2）已经能覆盖 95% 场景；孤儿进程防护由
`cmd.exe /c` 启动的 Windows 进程在父 WSL 进程死后仍存活——这是已知行为，
用户可通过 `taskkill /F /PID <win_pid>` 清理。如果未来需要真正的 Job Object
孤儿防护，应该写一个 Windows 侧的 launcher.exe，那是另一个工程。

用法
----
```python
from gpu_safe_subprocess import GpuLimits, run_gpu_windows

limits = GpuLimits(gpu_memory_fraction=0.4, cpu_threads=6)
r = run_gpu_windows(
    py_exe=r"E:\\venvs\\marker\\Scripts\\python.exe",
    code="from marker.scripts.convert_single import convert_single_cli; import sys; sys.exit(convert_single_cli())",
    args=[win_pdf, "--output_dir", win_out],
    limits=limits,
    timeout=1800,
)
print(r.returncode, r.stdout[:200])
```

更推荐配合 `acquire_gpu_slot()` 做跨进程并发控制：
```python
with acquire_gpu_slot(max_concurrent=2):
    run_gpu_windows(...)
```
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

__all__ = [
    "GpuLimits", "run_gpu_windows", "acquire_gpu_slot", "build_gpu_env",
    "GpuGovernor", "GpuLease", "InsufficientGpuBudget",
]


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GpuLimits:
    """GPU 子进程资源上限（通过环境变量注入，不修改第三方代码）.

    Attributes
    ----------
    gpu_memory_fraction : float
        每个进程最多可用 GPU 显存的比例（0-1）。
        官方：torch.cuda.set_per_process_memory_fraction 的等价环境变量。
        0.4 = 每个 GPU 进程最多占 40% 显存。16GB GPU 上即 6.4GB。
    cpu_threads : int
        每个进程的 CPU 线程上限（OMP_NUM_THREADS / MKL_NUM_THREADS）。
        建议：物理核数 / 并发进程数。如 16 物理核 + 2 进程 = 6-8。
    garbage_collection_threshold : float
        显存占用达到多少比例时主动 GC（0-1）。PyTorch 官方推荐 0.5-0.8。
    expandable_segments : bool
        减少显存碎片。PyTorch 官方推荐长期推理服务开启。
    """

    gpu_memory_fraction: float = 0.4
    cpu_threads: int = 6
    garbage_collection_threshold: float = 0.7
    expandable_segments: bool = True

    def __post_init__(self) -> None:
        if not 0.0 < self.gpu_memory_fraction <= 1.0:
            raise ValueError(
                f"gpu_memory_fraction must be in (0, 1], got {self.gpu_memory_fraction}"
            )
        if self.cpu_threads < 1:
            raise ValueError(f"cpu_threads must be >= 1, got {self.cpu_threads}")
        if not 0.0 < self.garbage_collection_threshold <= 1.0:
            raise ValueError(
                f"garbage_collection_threshold must be in (0, 1], "
                f"got {self.garbage_collection_threshold}"
            )

    def to_env(self) -> dict[str, str]:
        """生成可传给 subprocess 的环境变量字典（合并 os.environ 基础上覆盖）."""
        return build_gpu_env(self)


# --------------------------------------------------------------------------- #
# 核心函数
# --------------------------------------------------------------------------- #
def build_gpu_env(limits: GpuLimits, base: dict[str, str] | None = None) -> dict[str, str]:
    """构建带 GPU 资源限制的环境变量字典.

    Parameters
    ----------
    limits : GpuLimits
        资源配额
    base : dict, optional
        基础环境（默认 os.environ）

    Returns
    -------
    dict[str, str]
        可直接传给 subprocess.run(env=...) 的字典

    Note
    ----
    **WSL 关键陷阱**：在 WSL Linux Python 里用 `subprocess.run(env=...)` 启动
    Windows 进程时，**Linux 环境变量默认不会转发给 Windows 子进程**。
    WSL interop 只转发 `WSLENV` 中以 `/w` 标志列入白名单的变量。
    官方文档：https://learn.microsoft.com/en-us/windows/wsl/filesystems#share-environment-variables-between-windows-and-wsl-with-wslenv

    本函数自动构造 `WSLENV` 条目，使下方所有 GPU 限制变量都能穿越边界。
    """
    env = dict(base if base is not None else os.environ)

    # ── Layer 1: PyTorch 显存配额（最关键） ────────────────────────────
    # 官方文档：
    # https://pytorch.org/docs/stable/notes/cuda.html#optimizing-memory-usage
    conf_parts = [
        f"per_process_memory_fraction:{limits.gpu_memory_fraction}",
        # "throw_on_cudamalloc_oom:True",  # PyTorch<2.13 不支持此 key
        f"garbage_collection_threshold:{limits.garbage_collection_threshold}",
    ]
    if limits.expandable_segments:
        conf_parts.append("expandable_segments:True")
    env["PYTORCH_CUDA_ALLOC_CONF"] = ",".join(conf_parts)

    # ── Layer 2: CPU 线程约束（防 N 个进程各起满线程池互相抢核） ───────
    env["OMP_NUM_THREADS"] = str(limits.cpu_threads)
    env["MKL_NUM_THREADS"] = str(limits.cpu_threads)
    # HuggingFace tokenizer 多进程死锁防护（官方推荐关闭）
    env["TOKENIZERS_PARALLELISM"] = "false"

    # ── WSL→Windows 环境转发白名单（关键！否则上面所有变量静默失效） ──
    _GPU_ENV_VARS = (
        "PYTORCH_CUDA_ALLOC_CONF",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "TOKENIZERS_PARALLELISM",
    )
    if _is_wsl():
        # 合并已有 WSLENV（保留用户/系统已设的其他条目）+ 用 /w 标志白名单化
        existing = env.get("WSLENV", "")
        suffix = ":".join(f"{name}/w" for name in _GPU_ENV_VARS)
        env["WSLENV"] = f"{existing}:{suffix}".lstrip(":") if existing else suffix

    return env


def _is_wsl() -> bool:
    """运行时检测：当前进程是否在 WSL 内."""
    return "microsoft" in os.uname().release.lower()


def run_gpu_windows(
    py_exe: str,
    code: str,
    args: list[str] | None = None,
    limits: GpuLimits | None = None,
    timeout: int = 1800,
    cwd: str = "/mnt/e/temp",
    capture: bool = True,
) -> subprocess.CompletedProcess:
    """通过 cmd.exe /c 启动 Windows 侧 GPU Python 子进程，带资源配额.

    Parameters
    ----------
    py_exe : str
        Windows 侧 python.exe 绝对路径，例如
        ``r"E:\\venvs\\marker\\Scripts\\python.exe"``
    code : str
        传给 ``python -c`` 的代码字符串
    args : list[str], optional
        额外 CLI 参数
    limits : GpuLimits, optional
        资源配额。None 则用 GpuLimits() 默认值（0.4 / 6 线程）
    timeout : int
        子进程超时（秒）
    cwd : str
        WSL 侧工作目录（必须是 /mnt/ 下，避免 cmd.exe UNC 路径报错）
    capture : bool
        True 则 capture_output=True（拿 stdout/stderr），
        False 则透传到父进程（适合调试）

    Returns
    -------
    subprocess.CompletedProcess
    """
    limits = limits or GpuLimits()
    cmd = ["cmd.exe", "/c", py_exe, "-c", code] + (args or [])
    env = build_gpu_env(limits)
    return subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
        env=env,
    )


# --------------------------------------------------------------------------- #
# 跨进程并发上限（线程内安全；跨进程需用 multiprocessing.Semaphore）
# --------------------------------------------------------------------------- #
_slot_lock = threading.Lock()
_slots: dict[int, threading.BoundedSemaphore] = {}


@contextlib.contextmanager
def acquire_gpu_slot(max_concurrent: int = 2):
    """同进程内限流：限制同时进入 GPU 临界区的线程数.

    跨进程（多个 paper-reader 实例）的并发控制应该用文件锁或
    multiprocessing.Semaphore；本函数只解决单进程内 ThreadPool/asyncio 场景。

    用法::

        with acquire_gpu_slot(max_concurrent=2):
            run_gpu_windows(...)

    Parameters
    ----------
    max_concurrent : int
        同进程内最多同时运行多少个 GPU 子进程
    """
    if max_concurrent < 1:
        raise ValueError(f"max_concurrent must be >= 1, got {max_concurrent}")
    with _slot_lock:
        sem = _slots.get(max_concurrent)
        if sem is None:
            sem = threading.BoundedSemaphore(max_concurrent)
            _slots[max_concurrent] = sem
    sem.acquire()
    try:
        yield
    finally:
        sem.release()


# --------------------------------------------------------------------------- #
# 设备级 GPU 资源协调器（GpuGovernor）
# --------------------------------------------------------------------------- #
# 解决"多任务同时跑时设备过载"问题。
#
# 设计要点（方案 B：fcntl 文件锁 + 预算账本）：
# - 一个 WSL 原生文件系统上的账本文件（~/.cache/gpu-governor/ledger.json）
# - 多个 WSL 协调器进程（paper-reader、CV 训练脚本）通过 fcntl.flock 互斥访问账本
# - 每个任务 declare 一个 budget_mb（预期显存），账本里 sum(budget) ≤ cap * total_vram
# - acquire 时：原子地 {reap 死进程 → 检查预算 → 写入新条目}，避免 TOCTOU 竞态
# - 释放时：原子地从账本里减去这个 lease 的 budget
#
# 为什么不用 nvidia-smi 实时采样？因为采样滞后 1s，且 PyTorch 的 reserved pool
# 会虚高 memory.used。基于 declared budget 的准入更可预测。
#
# 为什么用 WSL fcntl 而非跨边界锁？协调器都是 WSL Python 进程，共享 WSL 原生 FS。
# Windows 子进程不参与锁，由其父进程（协调器）代理。
#
# 官方依据：
# - fcntl.flock：https://docs.python.org/3/library/fcntl.html#fcntl.flock
# - POSIX rename 原子性：https://pubs.opengroup.org/onlinepubs/9699919799/functions/rename.html


class InsufficientGpuBudget(Exception):
    """设备 GPU 预算不足。cap 已被其他活跃 lease 占满。"""


@dataclass
class _LedgerEntry:
    """账本里的一条 lease 记录。"""
    lease_id: str
    pid: int               # WSL 协调器进程 PID（用于 reap 死进程）
    budget_mb: int
    job_name: str
    acquired_at: float     # unix timestamp


@dataclass
class _Ledger:
    """GPU 预算账本（持久化到 ledger.json）。"""
    entries: list[_LedgerEntry] = field(default_factory=list)

    @property
    def committed_mb(self) -> int:
        return sum(e.budget_mb for e in self.entries)

    @classmethod
    def load(cls, path: Path) -> "_Ledger":
        """从 JSON 加载；文件缺失/损坏时返回空账本（容错）。"""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            entries = [_LedgerEntry(**e) for e in data.get("entries", [])]
            return cls(entries=entries)
        except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
            return cls()

    def save(self, path: Path) -> None:
        """原子写入：先写 .tmp 再 rename（POSIX rename 是原子的）。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        payload = {"entries": [asdict(e) for e in self.entries]}
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)  # POSIX rename，原子


def _pid_alive(pid: int) -> bool:
    """检查 WSL 进程是否存活（os.kill 0 信号探测）。"""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _query_nvidia_smi_used_mb() -> int | None:
    """查 nvidia-smi 当前已用显存（MB）。失败返回 None。"""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return int(r.stdout.strip().splitlines()[0])
    except (subprocess.TimeoutExpired, ValueError, OSError):
        pass
    return None


@dataclass(frozen=True)
class GpuGovernor:
    """设备级 GPU 资源协调器：保证多任务总显存不超过设备 cap。

    Parameters
    ----------
    cap_fraction : float
        设备级软上限（0.9 = 90%）。多个 lease 的 budget_mb 之和不超过 cap * total_vram_mb。
    total_vram_mb : int
        GPU 总显存（MB）。0 表示启动时自动从 nvidia-smi 探测。
    ledger_dir : Path
        账本文件目录（必须在 WSL 原生文件系统，不要放 /mnt/）。
    poll_interval_s : float
        blocking acquire 时的轮询间隔（秒）。
    sanity_check_nvidia_smi : bool
        是否额外用 nvidia-smi 做兜底检查（防非 governor 管理的进程偷吃显存）。

    用法::

        gov = GpuGovernor.default()
        with gov.acquire(budget_mb=6144, job_name="marker") as lease:
            run_gpu_windows(..., limits=lease.to_limits(cpu_threads=6))
    """
    cap_fraction: float = 0.9
    total_vram_mb: int = 0
    ledger_dir: Path = field(default_factory=lambda: Path.home() / ".cache" / "gpu-governor")
    poll_interval_s: float = 0.5
    sanity_check_nvidia_smi: bool = False

    def __post_init__(self) -> None:
        if not 0.0 < self.cap_fraction <= 1.0:
            raise ValueError(f"cap_fraction must be in (0, 1], got {self.cap_fraction}")
        if self.total_vram_mb == 0:
            # 启动时自动探测一次（frozen dataclass 用 object.__setattr__ 绕过）
            detected = _detect_total_vram_mb()
            object.__setattr__(self, "total_vram_mb", detected)
        if self.total_vram_mb <= 0:
            raise ValueError(f"total_vram_mb must be > 0 (or 0 for auto-detect), got {self.total_vram_mb}")

    @property
    def cap_mb(self) -> int:
        return int(self.cap_fraction * self.total_vram_mb)

    @classmethod
    def default(cls) -> "GpuGovernor":
        """默认实例：cap 0.9、自动探测 VRAM、账本在 ~/.cache/gpu-governor/。"""
        return cls()

    def acquire(self, *, budget_mb: int, job_name: str,
                timeout: float = 0.0) -> "GpuLease":
        """申请 GPU 预算。

        Parameters
        ----------
        budget_mb : int
            本任务预期使用的显存（MB）。governor 用此值做准入检查；
            同时 lease.to_limits() 会把它转成 per_process_memory_fraction。
        job_name : str
            人类可读的任务名（便于账本调试，如 "marker:paper.pdf"）。
        timeout : float
            0（默认）= 非阻塞，预算不足立即抛 InsufficientGpuBudget；
            >0 = 阻塞最多 timeout 秒，期间反复尝试。

        Returns
        -------
        GpuLease
            上下文管理器；离开 with 块时自动归还 budget。

        Raises
        ------
        InsufficientGpuBudget
            预算不足且 timeout=0，或 blocking 超时。
        ValueError
            budget_mb 非法（≤0 或 >total_vram_mb）。
        """
        if budget_mb <= 0:
            raise ValueError(f"budget_mb must be > 0, got {budget_mb}")
        if budget_mb > self.total_vram_mb:
            raise ValueError(
                f"budget_mb {budget_mb} exceeds total VRAM {self.total_vram_mb}"
            )

        deadline = time.monotonic() + timeout if timeout > 0 else None
        while True:
            lease = self._try_acquire_once(budget_mb, job_name)
            if lease is not None:
                return lease
            if deadline is None or time.monotonic() >= deadline:
                raise InsufficientGpuBudget(
                    f"cannot admit {budget_mb}MB for '{job_name}': "
                    f"committed {_load_ledger(self).committed_mb}MB / cap {self.cap_mb}MB"
                )
            time.sleep(self.poll_interval_s)

    def _try_acquire_once(self, budget_mb: int, job_name: str) -> "GpuLease | None":
        """单次尝试：fcntl 锁 → reap → 检查 → 写账本 → 释放锁。"""
        lock_path = self.ledger_dir / "ledger.lock"
        self.ledger_dir.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "a+") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                ledger = _load_ledger(self)
                # 1. reap 死进程条目
                ledger.entries = [e for e in ledger.entries if _pid_alive(e.pid)]
                # 2. 可选 nvidia-smi sanity gate（防非 governor 进程偷吃）
                if self.sanity_check_nvidia_smi:
                    used = _query_nvidia_smi_used_mb()
                    if used is not None and used > self.cap_mb + int(0.05 * self.total_vram_mb):
                        return None
                # 3. 检查预算
                if ledger.committed_mb + budget_mb > self.cap_mb:
                    return None
                # 4. 写入新条目并持久化
                lease_id = uuid.uuid4().hex[:12]
                entry = _LedgerEntry(
                    lease_id=lease_id, pid=os.getpid(),
                    budget_mb=budget_mb, job_name=job_name,
                    acquired_at=time.time(),
                )
                ledger.entries.append(entry)
                ledger.save(self.ledger_dir / "ledger.json")
                fraction = budget_mb / self.total_vram_mb
                return GpuLease(
                    lease_id=lease_id, budget_mb=budget_mb, fraction=fraction,
                    job_name=job_name, _governor=self,
                )
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


def _load_ledger(gov: GpuGovernor) -> _Ledger:
    return _Ledger.load(gov.ledger_dir / "ledger.json")


def _detect_total_vram_mb() -> int:
    """启动时探测 GPU 总显存（MB）。失败回退到 16384（16GB 默认）。"""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return int(r.stdout.strip().splitlines()[0])
    except (subprocess.TimeoutExpired, ValueError, OSError):
        pass
    return 16384  # 回退默认值；用户可显式传 total_vram_mb 覆盖


@dataclass
class GpuLease:
    """GPU 预算租约。离开 with 块时自动归还 budget。"""
    lease_id: str
    budget_mb: int
    fraction: float        # budget_mb / total_vram_mb
    job_name: str
    _governor: GpuGovernor

    def to_limits(self, cpu_threads: int = 6) -> GpuLimits:
        """把 lease 转成 GpuLimits，让 allocator 在运行时强制执行这个 budget。"""
        return GpuLimits(
            gpu_memory_fraction=self.fraction,
            cpu_threads=cpu_threads,
        )

    def __enter__(self) -> "GpuLease":
        return self

    def __exit__(self, *exc) -> None:
        self.release()

    def release(self) -> None:
        """归还 budget（幂等：重复调用安全）。"""
        lock_path = self._governor.ledger_dir / "ledger.lock"
        try:
            with open(lock_path, "a+") as lf:
                fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
                try:
                    ledger = _load_ledger(self._governor)
                    ledger.entries = [e for e in ledger.entries if e.lease_id != self.lease_id]
                    ledger.save(self._governor.ledger_dir / "ledger.json")
                finally:
                    fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass  # 账本文件已删除等极端情况，幂等忽略
