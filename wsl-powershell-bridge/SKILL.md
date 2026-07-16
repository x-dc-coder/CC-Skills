---
name: wsl-powershell-bridge
description: >
  WSL → Windows 三层桥接方案：cmd.exe (GPU/Python/EXE, ~55ms) 为首选，
  Direct EXE (注册表/服务/进程, ~10ms) 为快速通道，
  PowerShell (COM/WMI/P/Invoke, ~600ms) 为复杂场景保留。
  覆盖 GPU 训练、Windows Python 环境、注册表、WMI、COM 自动化、Event Log 等。
  GPU 规则统一在 /home/dc/CLAUDE.md。
---

# WSL → Windows 桥接 Skill

## Purpose

WSL2 runs a Linux kernel — Windows-only capabilities (COM, Win32 API, Registry, WMI, GPU) are **not directly accessible**. WSL provides `WSLInterop` to launch Windows executables from Linux.

This skill documents **three channels** ranked by speed and simplicity:

| Channel | Launcher | Overhead | When |
|---------|----------|----------|------|
| **C: cmd.exe** | `cmd.exe /c` | ~55ms | **GPU / Python scripts / 任意可执行文件** |
| **B: Direct EXE** | `reg.exe`, `sc.exe`... | ~10ms | 简单系统工具（注册表/服务/进程） |
| **A: PowerShell** | `powershell.exe` | ~600ms | COM / WMI / P/Invoke / Event Log |

**核心原则：能 cmd 不用 ps，能直调不套壳。**

## Channel C: cmd.exe — GPU & Python（⭐ 首选）

### Python 标准调用（`subprocess` 封装）

```python
import subprocess, os

def _run_windows(python_exe, code, args=None, timeout=1800):
    cmd = ["cmd.exe", "/c", python_exe, "-c", code] + (args or [])
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace",
        cwd="/mnt/e/temp",   # 必须：避免 UNC 路径报错
    )
```

**注意事项：**
- `cwd` 必须设为 `/mnt/` 下共享盘路径，否则 `cmd.exe` 报 UNC 不支持
- 中文输出需写文件（pipe 输出走系统 GBK 编码）：
  ```python
  cmd = [py, "-c", code, ">", win_out_file, "2>", win_err_file]
  subprocess.run(["cmd.exe", "/c"] + cmd, cwd="/mnt/e/temp")
  # 然后从 WSL 读取文件
  ```
- 退出码、参数传递、stderr 均正确（已验证）

### 后台长时间任务（会话关闭不中断）

`cmd.exe /c` 启动的 Windows 进程在 WSL 父进程被杀后不受影响（实测 SIGHUP/SIGKILL 存活）。用 `Popen` 非阻塞启动，输出重定向到文件：

```python
import subprocess

# 启动（不等待）
p = subprocess.Popen(
    ["cmd.exe", "/c", py_exe, "-c", code] + args,
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    cwd="/mnt/e/temp",
)
# p.pid 是 WSL bash 进程 — 退出时不影响 Windows 子进程

# 让训练脚本自己写 Windows PID 到文件
# Python 中: open(r"E:\temp\train_pid.txt","w").write(f"{os.getpid()}\n")
```

**监控/终止**：
```bash
nvidia-smi                                        # 查看 GPU
taskkill.exe /F /PID $(cat /mnt/e/temp/pid.txt)  # 终止
tail -f /mnt/e/temp/train.log                     # 日志
```

### GPU 环境检查 & 规则

> **GPU 相关全部统一在 `/home/dc/CLAUDE.md` → "GPU 桥接" 章节**，此处不再重复。
> 特别注意 **"GPU 多路并发铁律"**（≥2 个 GPU 子进程时必读，防 OOM 卡死系统）。

快速验证：
```bash
cmd.exe /c "E:\venvs\marker\Scripts\python.exe -c \"import torch; print('CUDA:', torch.cuda.is_available(), '| GPU:', torch.cuda.get_device_name(0))\""
```

### 资源限制（多路 GPU 子进程必备）

当一次启动 ≥2 个 Windows GPU 子进程时，**必须**给每个子进程注入显存配额 + CPU 线程约束。规则全文在 `/home/dc/CLAUDE.md` → "GPU 多路并发铁律"，此 skill 提供现成封装：

**通用模块**：`~/.claude/skills/wsl-powershell-bridge/scripts/gpu_safe_subprocess.py`

```python
from gpu_safe_subprocess import GpuLimits, run_gpu_windows, acquire_gpu_slot

# 每个 GPU 子进程上限：40% 显存 + 6 CPU 线程
limits = GpuLimits(gpu_memory_fraction=0.4, cpu_threads=6)

# 串行：直接调用
r = run_gpu_windows(
    py_exe=r"E:\venvs\marker\Scripts\python.exe",
    code="from marker.scripts.convert_single import convert_single_cli; import sys; sys.exit(convert_single_cli())",
    args=[win_pdf, "--output_dir", win_out],
    limits=limits,
    timeout=1800,
)

# 并发：用 Semaphore 限流
with acquire_gpu_slot(max_concurrent=2):
    run_gpu_windows(...)
```

模块原理：注入 `PYTORCH_CUDA_ALLOC_CONF=per_process_memory_fraction:0.4,throw_on_cudamalloc_oom:True,...`（PyTorch 官方 OOM 防护机制），让超额进程抛异常而非杀驱动。

### Windows 侧 Python venv 管理

用 `uv` 管理（路径 `C:\Users\32841\.local\bin\uv.exe`）：
```bash
# 创建 venv
powershell.exe -Command "& 'C:\Users\32841\.local\bin\uv.exe' venv E:\venvs\myproj --python 3.11"

# 安装 CUDA 版 PyTorch（cu128 稳定，cu130 有 DLL 问题）
powershell.exe -Command "& 'C:\Users\32841\.local\bin\uv.exe' pip install torch==2.11.0+cu128 --python E:\venvs\myproj\Scripts\python.exe --index-url https://download.pytorch.org/whl/cu128"
```

## Channel Selection Guide

| 场景 | 用哪个通道 | 命令 | 原因 |
|------|-----------|------|------|
| **GPU / Python 脚本** | cmd.exe (C) | `cmd.exe /c "py -c '...'"` | ~55ms, 参数不拆分, stderr 干净 |
| **中文输出** | cmd.exe + 文件 | `cmd.exe /c "py ... > out.txt"` | pipe 编码 GBK→UTF-8 可行 |
| **任意 EXE 调用** | cmd.exe (C) | `cmd.exe /c program.exe args` | 薄转发层, 无额外处理 |
| 简单注册表 | reg.exe (B) | `reg query HKLM\...` | ~10ms, 原生工具 |
| 服务启停 | sc.exe (B) | `sc start MyService` | 原生, 输出简洁 |
| 进程管理(简单) | tasklist/taskkill (B) | `taskkill /F /PID 12345` | 快速, 无需 PS |
| 进程管理(按命令行) | PowerShell (A) | `Get-CimInstance Win32_Process` | 只有 WMI 能按命令行过滤 |
| WMI/CIM 查询 | PowerShell (A) | `Get-CimInstance ...` | PowerShell 独有能力 |
| Event Log | PowerShell (A) | `Get-WinEvent ...` | PowerShell 独有能力 |
| COM 自动化 | PowerShell (A) | `New-Object -ComObject` | COM 必须用 PS |
| Win32 P/Invoke | PowerShell (A) | `Add-Type -TypeDefinition` | 动态编译 C# 必须用 PS |

## Environment Requirements

### 基础要求（所有能力的前置条件）

| 组件 | 最低版本 | 你的环境 | 检查命令 |
|------|---------|---------|---------|
| **Windows** | Windows 10 Build 19041+ | Windows 10/11 | `systeminfo.exe \| grep "OS Name"` |
| **WSL** | 2.0.0+ | 2.6.3 ✅ | `wsl.exe --version` |
| **WSLInterop** | enabled | enabled ✅ | `cat /proc/sys/fs/binfmt_misc/WSLInterop` |
| **Ubuntu** | 20.04 LTS+ | 22.04.5 ✅ | `lsb_release -a` |
| **PowerShell** | 5.1+ (Windows 内置) | 5.1.26100 ✅ | `powershell.exe -Command '$PSVersionTable.PSVersion'` |
| **iconv** | 任意 (GNU coreutils) | 已安装 ✅ | `which iconv` |
| **base64** | 任意 (GNU coreutils) | 已安装 ✅ | `which base64` |

### 可选工具安装

**wslu (WSL Utilities)** — 提供 `wslview`、`wslvar`、`wslsys` 等便捷工具：

```bash
# Ubuntu 22.04+ / Debian（apt 仓库）
sudo apt update && sudo apt install -y wslu

# 验证安装
wslview --version   # 应显示 3.2.3+
wslvar --version
```

> **环境要求**: Ubuntu 20.04 LTS+ 或 Debian 11+。其他发行版请参考 [wslu 官方文档](https://wslutiliti.es/wslu/install.html)。
> wslu 依赖: `desktop-file-utils`, `bc`（apt 会自动安装）。

**jq** — JSON 解析（配合 `pshj()` 使用）：

```bash
sudo apt install -y jq
```

## When to Use This Skill

- 需要在 WSL 中调用 Windows 侧能力（EXE / Python / GPU / 系统工具）
- 关键词: `cmd.exe`、`powershell.exe`、GPU、CUDA、torch、Windows venv、注册表、WMI、COM、Visio、Office
- **GPU 训练/推理**: 见 `/home/dc/CLAUDE.md` → "GPU 桥接" 章节（单一事实来源）

## WSLInterop Quick Check

Before attempting any Windows calls, verify WSLInterop is working:

```bash
# Should print "Hello from Windows" if WSLInterop is enabled
powershell.exe -Command "Write-Host 'Hello from Windows'"
```

If this fails with `Exec format error`, WSLInterop is not registered.
Fix it with:

```bash
# Requires sudo; may need to re-run after WSL restart
echo ':WSLInterop:M::MZ::/init:' | sudo tee /proc/sys/fs/binfmt_misc/register
```

For persistence, add to `/etc/wsl.conf`:

```ini
[interop]
enabled=true
appendWindowsPath=true
```

---

## Encoding Notes

- **Channel C (cmd.exe)**: pipe 输出走系统 GBK 编码 → 非 ASCII 字符乱码。**写文件绕开**。
- **Channel B (Direct EXE)**: 同样 GBK 编码。用 `grep` 提取 ASCII 字段即可。
- **Channel A (PowerShell)**: 通过设置 `[Console]::OutputEncoding = UTF8` 可正确输出中文。

---

## Channel A: PowerShell — COM / WMI / P/Invoke / Event Log

> **仅当 cmd.exe 无法胜任时使用**：COM 对象、WMI 查询、Event Log、P/Invoke 动态编译 C#。

### Calling Patterns

**简单一行**（使用单引号避免 bash 展开）：
```bash
powershell.exe -Command 'Get-Process -Name code | ConvertTo-Json'
```

**复杂脚本**（写 `.ps1` 文件，通过 `-File` 调用）：
```bash
# 从 WSL 写入 PS1 到共享盘
cat > /mnt/e/temp/task.ps1 << 'EOF'
param([string]$Name)
$r = Get-CimInstance Win32_Process | Where-Object CommandLine -like "*$Name*"
$r | Select-Object ProcessId,CommandLine | ConvertTo-Json
EOF

powershell.exe -File "E:\temp\task.ps1" -Name "python"
```

**注意**：
- PowerShell `-Command` 参数传递有 bug：含空格的参数（如 `"hello world"`）会被拆分为两个参数。复杂参数用 `-File`。
- `-EncodedCommand` 的 stdout 在非 TTY 时会包 CLIXML，不推荐用于数据交换。

---

## Channel B: Direct Windows EXE Tools (Zero PowerShell Overhead)

> **核心原则**: PowerShell 不是唯一的桥接通道。WSL 可以**直接调用** Windows 系统工具，
> 每次调用仅 ~10ms 启动开销（vs PowerShell 的 ~300ms）。以下所有工具都是
> **Windows 内置、零安装、开箱即用**。

### B1: `reg.exe` — Registry Access (Fast Path)

**比 PowerShell `Get-ItemProperty` 快 3-5 倍**，适合简单的读写操作。

```bash
# === 读取 ===

# 查询单个值
reg.exe query "HKLM\Software\Microsoft\Windows NT\CurrentVersion" /v ProductName

# 查询子键列表
reg.exe query "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall" /s /f "DisplayName" | grep DisplayName | head -10

# 导出整个注册表分支
reg.exe export "HKCU\Software\MyApp" "E:\backup\myapp.reg"

# === 写入 ===

# 添加/修改一个字符串值
reg.exe add "HKCU\Software\MyBridge" /v LastRun /t REG_SZ /d "2026-06-05" /f

# 添加 DWORD 值
reg.exe add "HKCU\Software\MyBridge" /v Timeout /t REG_DWORD /d 300 /f

# === 删除 ===

# 删除一个值
reg.exe delete "HKCU\Software\MyBridge" /v TempSetting /f

# 删除整个子键（谨慎！）
reg.exe delete "HKCU\Software\MyBridge\OldConfig" /f
```

**`reg.exe` vs PowerShell 对比:**

| 操作 | `reg.exe` (Channel B) | PowerShell (Channel A) |
|------|----------------------|------------------------|
| 简单查询 | `reg query HKLM\... /v Name` | `powershell.exe -Command "(Get-ItemProperty ...).Name"` |
| 启动时间 | ~10ms | ~300ms |
| 输出格式 | 纯文本（需 grep 解析） | JSON（结构化） |
| 数据类型 | 自动处理 REG_SZ/DWORD/... | 需要显式转换 |
| 适用场景 | 运维脚本、快速检查 | 需要 JSON 输出的场景 |

```bash
# 实用示例：列出所有启动了自动更新的软件
reg.exe query "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall" /s /f "DisplayName" | grep -E "DisplayName|ParentKeyName"
```

### B2: `sc.exe` — Windows Service Control

管理 Windows 服务的启动/停止/查询，无需 PowerShell。

```bash
# === 查询 ===

# 查询单个服务状态
sc.exe query Dhcp

# 查询所有服务（仅名称）
sc.exe query state=all | grep SERVICE_NAME | head -20

# 查询服务配置
sc.exe qc Dhcp

# === 控制 ===

# 启动服务
sc.exe start Dhcp

# 停止服务
sc.exe stop Dhcp

# 重启服务
sc.exe stop Dhcp && sleep 2 && sc.exe start Dhcp

# === 配置 ===

# 设置启动类型（auto=自动, demand=手动, disabled=禁用）
sc.exe config MyService start=auto

# 设置服务描述
sc.exe description MyService "My custom service from WSL"

# === 创建/删除 ===

# 创建一个新服务
sc.exe create MyWSLService binPath="D:\Anconda\python.exe E:\scripts\daemon.py" start=auto

# 删除服务
sc.exe delete MyWSLService
```

**注意**: `sc.exe` 的 `=` 后面必须有空格（`start=auto` 而非 `start=auto`）。

### B3: `tasklist.exe` / `taskkill.exe` — Process Management (Fast Path)

```bash
# === tasklist — 列出进程 ===

# 按名称查找
tasklist.exe /FI "IMAGENAME eq code.exe"

# 按 PID 查找
tasklist.exe /FI "PID eq 14392"

# 按内存使用过滤（大于 100MB）
tasklist.exe /FI "MEMUSAGE gt 102400"

# 输出为 CSV 格式（便于解析）
tasklist.exe /FO CSV /FI "IMAGENAME eq explorer.exe"

# === taskkill — 终止进程 ===

# 按名称终止
taskkill.exe /F /IM notepad.exe

# 按 PID 终止（推荐）
taskkill.exe /F /PID 12345

# 终止进程及其子进程树
taskkill.exe /F /T /PID 12345
```

**`tasklist/taskkill` vs PowerShell 对比:**

| 操作 | Direct EXE (B) | PowerShell (A) |
|------|---------------|----------------|
| 按名称列进程 | `tasklist /FI "IMAGENAME eq code.exe"` | `Get-Process -Name code` |
| 按名杀进程 | `taskkill /F /IM code.exe` | `Stop-Process -Name code -Force` |
| 按 PID 杀进程 | `taskkill /F /PID 12345` | `Stop-Process -Id 12345 -Force` |
| 按命令行过滤 | ❌ 不支持 | ✅ `Get-CimInstance Win32_Process \| Where CommandLine -like ...` |

**选择规则**: 简单按名/PID 操作用 `taskkill`（快），需要按命令行匹配用 PowerShell（精确）。

### B4: `whoami.exe` — Windows User Identity

```bash
# 当前 Windows 用户
whoami.exe

# 用户所属的 Windows 安全组
whoami.exe /groups

# 用户的特权列表
whoami.exe /priv

# 检查是否以管理员权限运行
whoami.exe /groups | grep -i "S-1-16-12288" && echo "High integrity (Admin)" || echo "Medium integrity (Standard)"
```

### B5: `netsh.exe` — Network Configuration & Firewall

```bash
# === 网络接口 ===

# 列出所有网络接口
netsh.exe interface show interface

# 查看 IP 配置
netsh.exe interface ip show addresses

# 查看 DNS 配置
netsh.exe interface ip show dnsservers

# === 防火墙规则 ===

# 列出所有入站规则（名称）
netsh.exe advfirewall firewall show rule name=all dir=in | grep "规则名称" | head -20

# 添加入站规则（开放端口给 WSL 服务访问）
netsh.exe advfirewall firewall add rule name="WSL-MyAPI" dir=in action=allow protocol=TCP localport=3000

# 删除防火墙规则
netsh.exe advfirewall firewall delete rule name="WSL-MyAPI"

# === 端口代理（portproxy） ===

# 将 Windows 端口转发到 WSL 端口
netsh.exe interface portproxy add v4tov4 listenport=8080 listenaddress=0.0.0.0 connectport=3000 connectaddress=127.0.0.1

# 查看当前端口转发
netsh.exe interface portproxy show all

# 删除端口转发
netsh.exe interface portproxy delete v4tov4 listenport=8080 listenaddress=0.0.0.0
```

> **⚠️ 注意**: `netsh.exe advfirewall` 操作通常需要**管理员权限**。从 WSL 执行时，WSL 进程本身需要有管理员权限（以管理员身份启动 Windows Terminal）。

### B6: `certutil.exe` — Certificate Store & File Hashing

```bash
# === 文件哈希（替代 Linux sha256sum/md5sum） ===

# 计算 SHA256
certutil.exe -hashfile "E:\file.bin" SHA256

# 计算 MD5
certutil.exe -hashfile "E:\file.bin" MD5

# === Base64 编解码 ===

# 编码
certutil.exe -encode input.bin output.b64

# 解码
certutil.exe -decode input.b64 output.bin

# === 证书管理 ===

# 列出受信任的根证书
certutil.exe -store Root

# 列出个人证书存储
certutil.exe -store My

# 导出证书
certutil.exe -exportPFX -p "password" My "thumbprint_here" "E:\backup\cert.pfx"
```

### B7: `schtasks.exe` — Scheduled Tasks (Fast Path)

```bash
# 列出所有计划任务
schtasks.exe /Query /FO LIST | grep "任务名" | head -20

# 查询特定任务详情
schtasks.exe /Query /TN "MyBackup" /FO LIST /V

# 创建定时任务
schtasks.exe /Create /TN "WSL_DailyBackup" /TR "D:\Anconda\python.exe E:\scripts\backup.py" /SC DAILY /ST 02:00

# 立即运行任务
schtasks.exe /Run /TN "WSL_DailyBackup"

# 删除任务
schtasks.exe /Delete /TN "WSL_DailyBackup" /F
```

### B8: `icacls.exe` / `takeown.exe` — File Permissions

```bash
# 查看文件/目录权限
icacls.exe "E:\AllProjects"

# 授予用户完全控制权限
icacls.exe "E:\AllProjects\share" /grant "Everyone:(F)" /T

# 移除用户权限
icacls.exe "E:\AllProjects\share" /remove "Everyone"

# 获取文件所有权
takeown.exe /F "E:\locked_file.txt"
```

### B9: `systeminfo.exe` / `driverquery.exe` — System Information

```bash
# Windows 系统信息摘要
systeminfo.exe | head -20

# 查找特定信息
systeminfo.exe | grep -E "OS Name|System Boot Time|Total Physical Memory|Hotfix"

# 已安装的驱动程序
driverquery.exe /FO LIST | grep -E "模块名称|显示名称|驱动程序类型" | head -30
```

---

## wslu — WSL Utilities (增强跨环境交互)

[`wslu`](https://wslutiliti.es/wslu/) 是 WSL 官方推荐的便捷工具集，提供跨环境交互能力。

### 安装

| 发行版 | 安装命令 | 最低版本 |
|--------|---------|---------|
| **Ubuntu 22.04+** | `sudo apt install -y wslu` | wslu 3.2.3 |
| **Ubuntu 20.04** | `sudo add-apt-repository ppa:wslutilities/wslu && sudo apt install wslu` | wslu 4.x |
| **Debian 11+** | `sudo apt install -y wslu` | wslu 3.x |
| **Arch** | `yay -S wslu` | wslu 4.x |
| **其他** | 见 [wslu 官方安装指南](https://wslutiliti.es/wslu/install.html) | — |

```bash
# 验证安装
wslview --version
wslvar --version
```

> **依赖**: `desktop-file-utils`, `bc`（通过 apt 自动安装）。不需要 Windows 侧的任何配置。

### `wslview` — 用 Windows 默认程序打开文件/URL

```bash
# 用 Windows 默认浏览器打开 URL
wslview https://github.com

# 用 Windows 默认 PDF 阅读器打开 PDF
wslview /mnt/e/docs/thesis.pdf

# 用 Windows 文件管理器打开目录
wslview /mnt/e/AllProjects

# 用 Windows 默认图片查看器打开图片
wslview /mnt/e/screenshots/diagram.png
```

**适用场景**: WSL 内生成了文件（PDF、图片、报告），想立即用 Windows 应用查看。

### `wslvar` — 读取 Windows 环境变量（无需 PowerShell）

```bash
# 获取 Windows 用户目录
wslvar USERPROFILE
# → C:\Users\32841

# 获取 Windows AppData 路径
wslvar APPDATA

# 将 Windows 路径转为 WSL 路径
cd "$(wslpath -u "$(wslvar USERPROFILE)")/Desktop"

# 获取 Windows PATH
wslvar PATH
```

**`wslvar` vs PowerShell `$env:`:**

| 方式 | 命令 | 开销 |
|------|------|------|
| wslvar (B) | `wslvar USERPROFILE` | ~5ms |
| PowerShell (A) | `powershell.exe -Command '$env:USERPROFILE'` | ~300ms |

### `wslsys` / `wslfetch` — WSL 系统信息

```bash
# WSL 版本和发行版信息
wslsys

# 美化显示（类似 screenfetch/neofetch）
wslfetch
```

### `wslusc` — 为 WSL Linux 程序创建 Windows 快捷方式

```bash
# 在 Windows 桌面创建 WSL 应用的快捷方式
wslusc --name "My Python Tool" --icon /usr/share/icons/hicolor/48x48/apps/python3.png python3 /home/dc/scripts/tool.py
```

---

## `wsl.exe` Self-Management — WSL 自管理

WSL 发行版内部可以直接调用 `wsl.exe` 来管理 WSL 本身。

```bash
# 查看 WSL 版本信息
wsl.exe --version

# 列出所有发行版及状态
wsl.exe --list --verbose

# 列出正在运行的发行版
wsl.exe --list --running

# 在当前 WSL 中，在另一个发行版中执行命令
wsl.exe -d Ubuntu-24.04 --user root -- ls /home

# 终止指定发行版
wsl.exe --terminate Ubuntu-24.04

# 关闭所有 WSL 发行版
wsl.exe --shutdown

# 导出当前发行版为 tar
wsl.exe --export Ubuntu-22.04 E:\backup\ubuntu.tar

# 更新 WSL 内核
wsl.exe --update
```

---

## Channel A: PowerShell Bridge — Core Capabilities

> **以下能力需要 PowerShell 桥接通道**（启动开销 ~300ms，适用于复杂操作、结构化输出、COM/WMI/P/Invoke）。
> 对于简单快速的注册表/服务/进程操作，请先用 [Channel B](#channel-b-direct-windows-exe-tools-zero-powershell-overhead) 的直调工具。

### Capability 1: Registry Access

Read and write the Windows Registry — essential for discovering installed software,
system configuration, file associations, and COM class registration.

```bash
# Read: list installed software
powershell.exe -Command "
    Get-ItemProperty 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*' |
    Where-Object DisplayName -ne \$null |
    Select-Object DisplayName, DisplayVersion, Publisher |
    ConvertTo-Json
"

# Read: Windows version info
powershell.exe -Command "
    Get-ItemProperty 'HKLM:\Software\Microsoft\Windows NT\CurrentVersion' |
    Select-Object ProductName, CurrentBuild, EditionID |
    ConvertTo-Json
"

# Read: find Java home from registry
powershell.exe -Command "
    Get-ItemProperty 'HKLM:\Software\JavaSoft\JDK\*' |
    Select-Object JavaHome |
    ConvertTo-Json
"

# Write: set a user-level registry value
powershell.exe -Command "
    New-Item -Path 'HKCU:\Software\MyBridge' -Force | Out-Null;
    Set-ItemProperty -Path 'HKCU:\Software\MyBridge' -Name 'LastRun' -Value (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
"

# Delete: remove a registry key
powershell.exe -Command "Remove-ItemProperty -Path 'HKCU:\Software\MyBridge' -Name 'TempSetting' -ErrorAction SilentlyContinue"
```

**Registry hive mappings:**
| Abbreviation | Full Path |
|-------------|-----------|
| `HKLM:` | `HKEY_LOCAL_MACHINE` |
| `HKCU:` | `HKEY_CURRENT_USER` |
| `HKCR:` | `HKEY_CLASSES_ROOT` |
| `HKU:` | `HKEY_USERS` |
| `HKCC:` | `HKEY_CURRENT_CONFIG` |

### Capability 2: Clipboard Integration

Exchange data between WSL and the Windows clipboard seamlessly.

```bash
# WSL → Windows clipboard (使用 Set-Clipboard 确保中文不乱码)
echo "Copied from WSL terminal" | powershell.exe -Command "Set-Clipboard -Value (Get-Content -Path '\$(wslpath -w /tmp/clip.txt)' -Raw -Encoding UTF8)"
# Or use the psh helper: echo "hello" | win-clip

# The safer pattern via temp file:
echo "中文内容 from WSL" > /tmp/clip.txt
powershell.exe -Command "${POWERSHELL_UTF8} Set-Clipboard -Value (Get-Content -Path '\\wsl.localhost\Ubuntu\tmp\clip.txt' -Raw -Encoding UTF8)"

# Windows clipboard → WSL
powershell.exe -Command "Get-Clipboard"
powershell.exe -Command "Get-Clipboard" > /tmp/clipboard_content.txt

# WSL → Windows clipboard (simple ASCII only — 中文会乱码!)
echo "ASCII only text" | clip.exe

# Get image from clipboard (saves to Windows path)
powershell.exe -Command "
    Add-Type -AssemblyName System.Windows.Forms;
    \$img = [System.Windows.Forms.Clipboard]::GetImage();
    if (\$img) { \$img.Save('E:\temp\clipboard_image.png') }
"
```

### Capability 3: WMI / CIM Queries

Query system hardware, OS configuration, process details, and network info
via WMI (Windows Management Instrumentation). **Use `Get-CimInstance`** (PowerShell 5+)
— it's the modern, WSMan-based replacement for the deprecated `Get-WmiObject`.

```bash
# System hardware info
powershell.exe -Command "Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model,TotalPhysicalMemory | ConvertTo-Json"

# CPU info
powershell.exe -Command "Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,MaxClockSpeed | ConvertTo-Json"

# Disk info
powershell.exe -Command "Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | Select-Object DeviceID,@{N='SizeGB';E={[math]::Round(\$_.Size/1GB,1)}},@{N='FreeGB';E={[math]::Round(\$_.FreeSpace/1GB,1)}} | ConvertTo-Json"

# Network adapter info
powershell.exe -Command "Get-CimInstance Win32_NetworkAdapter -Filter 'NetEnabled=True' | Select-Object Name,MACAddress,AdapterType | ConvertTo-Json"

# Find process by command line (!! crucial for precise process management)
powershell.exe -Command "Get-CimInstance Win32_Process | Where-Object CommandLine -like '*uvicorn*app:app*' | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json"

# List all services and their states
powershell.exe -Command "Get-CimInstance Win32_Service | Select-Object Name,State,StartMode,DisplayName | ConvertTo-Json"

# Check Windows Update history
powershell.exe -Command "Get-CimInstance Win32_QuickFixEngineering | Select-Object HotFixID,InstalledOn,Description | ConvertTo-Json"
```

**Common WMI classes:**
| Class | Use For |
|-------|---------|
| `Win32_ComputerSystem` | Manufacturer, model, RAM, domain |
| `Win32_Processor` | CPU name, cores, clock speed |
| `Win32_LogicalDisk` | Drive letters, size, free space |
| `Win32_NetworkAdapter` | NIC names, MAC, type |
| `Win32_Process` | Process details **including command line** |
| `Win32_Service` | Windows services and their states |
| `Win32_Product` | MSI-installed products (slow — prefer Registry for listing) |
| `Win32_QuickFixEngineering` | Windows Update / hotfix history |
| `Win32_OperatingSystem` | OS version, install date, last boot |
| `Win32_BIOS` | BIOS version, serial number |

### Capability 4: Win32 API via Add-Type (P/Invoke)

Call **any** Win32 API function by compiling C# on-the-fly inside PowerShell.
This unlocks capabilities that have no PowerShell cmdlet equivalent.

```bash
# Call kernel32!GetTickCount
cmd_b64=$(cat <<'EOF' | iconv -t UTF-16LE | base64 -w0
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class Kernel32 {
    [DllImport("kernel32.dll")]
    public static extern uint GetTickCount();
}
"@
[Kernel32]::GetTickCount()
EOF
)
powershell.exe -EncodedCommand "$cmd_b64"

# Show a Windows MessageBox (GUI — useful for notifications from WSL)
cmd_b64=$(cat <<'EOF' | iconv -t UTF-16LE | base64 -w0
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class User32 {
    [DllImport("user32.dll", CharSet=CharSet.Auto)]
    public static extern int MessageBox(IntPtr hWnd, string text, string caption, uint type);
}
"@
[User32]::MessageBox([IntPtr]::Zero, "Build completed from WSL!", "WSL Notification", 0)
EOF
)
powershell.exe -EncodedCommand "$cmd_b64"

# Get monitor count / screen resolution
cmd_b64=$(cat <<'EOF' | iconv -t UTF-16LE | base64 -w0
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class User32 {
    [DllImport("user32.dll")]
    public static extern int GetSystemMetrics(int nIndex);
}
"@
@{
    ScreenWidth = [User32]::GetSystemMetrics(0)
    ScreenHeight = [User32]::GetSystemMetrics(1)
    MonitorCount = [User32]::GetSystemMetrics(80)
} | ConvertTo-Json
EOF
)
powershell.exe -EncodedCommand "$cmd_b64"

# Check if a DLL is loaded in a process
cmd_b64=$(cat <<'EOF' | iconv -t UTF-16LE | base64 -w0
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public class Psapi {
    [DllImport("psapi.dll")]
    public static extern bool EnumProcessModules(IntPtr hProcess, IntPtr[] lphModule, uint cb, out uint lpcbNeeded);
}
"@
Write-Host "PSAPI loaded — EnumProcessModules available"
EOF
)
powershell.exe -EncodedCommand "$cmd_b64"
```

**Common Win32 DLLs to P/Invoke from:**
| DLL | What It Provides |
|-----|-----------------|
| `kernel32.dll` | Process/thread management, memory, file ops, timing |
| `user32.dll` | Windows, messages, clipboard (advanced), input, display |
| `advapi32.dll` | Registry (low-level), security, services, Event Log |
| `shell32.dll` | Shell execute, file associations, special folders |
| `psapi.dll` | Process enumeration, memory usage |
| `gdi32.dll` | Drawing, fonts, printing |

### Capability 5: Windows Environment Variables

Discover Windows-side paths (VS, Python, Java, Node installations) from WSL.

```bash
# Get all Windows environment variables
powershell.exe -Command 'Get-ChildItem Env: | Select-Object Name,Value | ConvertTo-Json'

# Get a specific variable
powershell.exe -Command '$env:JAVA_HOME'
powershell.exe -Command '$env:USERPROFILE'
powershell.exe -Command '$env:Path -split ";" | ConvertTo-Json'

# Find Visual Studio installation
powershell.exe -Command '
    $vsPath = ${env:ProgramFiles(x86)};
    Get-ChildItem "$vsPath\Microsoft Visual Studio" -ErrorAction SilentlyContinue |
    Select-Object Name
'

# Get Windows user profile path
powershell.exe -Command '[Environment]::GetFolderPath("Desktop")'
powershell.exe -Command '[Environment]::GetFolderPath("MyDocuments")'
```

### Capability 6: COM Object Automation

Automate Windows applications via COM (Component Object Model).

```bash
# Visio
powershell.exe -Command "
    \$visio = New-Object -ComObject Visio.Application;
    Write-Output \$visio.Version;
    \$visio.Quit()
"

# Excel (create a workbook, write data)
powershell.exe -Command "
    \$excel = New-Object -ComObject Excel.Application;
    \$excel.Visible = \$false;
    \$wb = \$excel.Workbooks.Add();
    \$ws = \$wb.Worksheets.Item(1);
    \$ws.Cells.Item(1,1) = 'Hello from WSL';
    \$wb.SaveAs('E:\\temp\\wsl_output.xlsx');
    \$excel.Quit()
"

# Word (open doc, extract text)
powershell.exe -Command "
    \$word = New-Object -ComObject Word.Application;
    \$word.Visible = \$false;
    \$doc = \$word.Documents.Open('E:\\docs\\report.docx');
    \$text = \$doc.Content.Text;
    Write-Output \$text.Substring(0, [Math]::Min(500, \$text.Length));
    \$doc.Close();
    \$word.Quit()
"

# Internet Explorer (navigate, get page content — for legacy systems)
powershell.exe -Command "
    \$ie = New-Object -ComObject InternetExplorer.Application;
    \$ie.Visible = \$false;
    \$ie.Navigate('https://example.com');
    while (\$ie.Busy -or \$ie.ReadyState -ne 4) { Start-Sleep -Milliseconds 100 };
    Write-Output \$ie.Document.body.innerText;
    \$ie.Quit()
"
```

**Critical Note:** COM objects cannot be passed across the WSL-Windows boundary.
They must be created, used, and destroyed entirely within the Windows-side process.

**Common COM ProgIDs:**
| ProgID | Application |
|--------|------------|
| `Visio.Application` | Microsoft Visio |
| `Word.Application` | Microsoft Word |
| `Excel.Application` | Microsoft Excel |
| `PowerPoint.Application` | Microsoft PowerPoint |
| `Outlook.Application` | Microsoft Outlook |
| `InternetExplorer.Application` | Internet Explorer |
| `Shell.Application` | Windows Shell |
| `Scripting.FileSystemObject` | File system operations |
| `WScript.Shell` | Shell execute, shortcuts, env vars |
| `MSXML2.DOMDocument` | XML parsing |

### Capability 7: Process Management (Enhanced)

Start, monitor, and stop Windows processes with precision.

```bash
# === START ===

# Simple: launch a process
powershell.exe -Command "Start-Process notepad.exe"

# Launch with working directory + env vars
powershell.exe -Command '
    cd E:\AllProjects\DrawForge\agent\skills\visioskills\bridge_server;
    $env:VISIO_BRIDGE_TOKEN="drawforge-test-token-2026";
    . .venv\Scripts\Activate.ps1;
    Start-Process -NoNewWindow uvicorn -ArgumentList "app:app","--host","0.0.0.0","--port","18761"
'

# Launch and capture PID for later management
powershell.exe -Command '
    $p = Start-Process -PassThru -FilePath "python.exe" -ArgumentList "-m http.server 8888";
    $p.Id | Out-File -FilePath "E:\temp\wsl_managed_pid.txt";
    Write-Output $p.Id
'

# === MONITOR ===

# Check if a specific PID is running
powershell.exe -Command "Get-Process -Id 12345 -ErrorAction SilentlyContinue | Select-Object Id,ProcessName"

# Find process by command line pattern (PRECISE — won't match unrelated processes)
powershell.exe -Command "
    Get-CimInstance Win32_Process |
    Where-Object CommandLine -like '*uvicorn*app:app*' |
    Select-Object ProcessId,Name,CommandLine |
    ConvertTo-Json
"

# Check process resource usage
powershell.exe -Command "
    Get-Process -Name uvicorn -ErrorAction SilentlyContinue |
    Select-Object Id,ProcessName,@{N='CPU_s';E={[math]::Round(\$_.CPU,1)}},@{N='MemMB';E={[math]::Round(\$_.WorkingSet64/1MB,1)}}
"

# === STOP ===

# Stop by PID (preferred — most precise)
powershell.exe -Command "Stop-Process -Id 12345 -Force"

# Stop by PID file (the safe pattern)
pid=$(powershell.exe -Command 'Get-Content "E:\temp\wsl_managed_pid.txt" -ErrorAction SilentlyContinue')
if [ -n "$pid" ]; then
    powershell.exe -Command "Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue"
    powershell.exe -Command 'Remove-Item "E:\temp\wsl_managed_pid.txt" -ErrorAction SilentlyContinue'
fi

# Stop by name (use cautiously — may affect unrelated processes!)
powershell.exe -Command "Get-Process -Name uvicorn -ErrorAction SilentlyContinue | Stop-Process -Force"

# === BACKGROUND LIFECYCLE ===

# The proper way to manage daemon-like processes from WSL:
# 1. Start → capture PID to file
# 2. Check → verify PID is still running + command line matches
# 3. Stop → kill by PID, clean up PID file
```

### Capability 8: File Operations Between WSL and Windows

```bash
# WSL path → Windows path conversion
wslpath -w /home/user/project/file.txt
# Output: \\wsl.localhost\Ubuntu\home\user\project\file.txt

# Windows path → WSL path
wslpath -u "E:\AllProjects\DrawForge"
# Output: /mnt/e/AllProjects/DrawForge

# Copy from WSL to Windows
powershell.exe -Command "Copy-Item '\\wsl.localhost\Ubuntu\home\dc\file.txt' 'E:\\dest\\'"

# Copy a directory recursively
powershell.exe -Command "Copy-Item '\\wsl.localhost\Ubuntu\home\dc\project' 'E:\\backup\\' -Recurse"

# Create a Windows directory
powershell.exe -Command "New-Item -ItemType Directory -Path 'E:\\temp\\wsl_output' -Force"

# List Windows directory contents from WSL
ls /mnt/e/AllProjects/

# Open a file with its Windows default application
powershell.exe -Command "Start-Process 'E:\\docs\\report.docx'"
cmd.exe /c start "" "E:\\docs\\report.docx"

# Open Explorer at a specific path
powershell.exe -Command "Invoke-Item 'E:\\AllProjects'"
```

### Capability 9: Windows Event Log Access

Query Windows Event Logs for diagnostics, error investigation, and system monitoring.

```bash
# Recent System errors (last 24 hours)
powershell.exe -Command '
    Get-WinEvent -FilterHashtable @{LogName="System"; Level=2; StartTime=(Get-Date).AddHours(-24)} -MaxEvents 10 |
    Select-Object TimeCreated,Id,LevelDisplayName,Message |
    ConvertTo-Json -Depth 2
'

# Recent Application errors
powershell.exe -Command '
    Get-WinEvent -FilterHashtable @{LogName="Application"; Level=2; StartTime=(Get-Date).AddDays(-1)} -MaxEvents 20 |
    Select-Object TimeCreated,Id,ProviderName,Message |
    ConvertTo-Json -Depth 2
'

# Security audit failures
powershell.exe -Command '
    Get-WinEvent -FilterHashtable @{LogName="Security"; StartTime=(Get-Date).AddHours(-1)} -MaxEvents 50 |
    Where-Object {$_.Id -eq 4625} |
    Select-Object TimeCreated,Id,Message |
    ConvertTo-Json -Depth 2
'

# Check if a specific service crashed
powershell.exe -Command '
    Get-WinEvent -FilterHashtable @{LogName="System"; Level=1,2; StartTime=(Get-Date).AddHours(-1)} -MaxEvents 100 |
    Where-Object {$_.Message -match "uvicorn|python"} |
    Select-Object TimeCreated,LevelDisplayName,Message
'

# List available event logs
powershell.exe -Command "Get-WinEvent -ListLog * | Select-Object LogName,RecordCount | Where-Object RecordCount -gt 0"
```

### Capability 10: Windows Task Scheduler

Create, query, and manage scheduled tasks for persistent automation.

```bash
# List all scheduled tasks
powershell.exe -Command "Get-ScheduledTask | Select-Object TaskName,State | ConvertTo-Json"

# Get details of a specific task
powershell.exe -Command "Get-ScheduledTask -TaskName 'MyBackup' | Get-ScheduledTaskInfo"

# Create a simple daily task
powershell.exe -Command '
    $action = New-ScheduledTaskAction -Execute "D:\Anconda\python.exe" -Argument "E:\scripts\daily_backup.py";
    $trigger = New-ScheduledTaskTrigger -Daily -At "02:00AM";
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest;
    Register-ScheduledTask -TaskName "WSL_Backup" -Action $action -Trigger $trigger -Principal $principal -Description "Backup triggered from WSL"
'

# Run a task immediately
powershell.exe -Command "Start-ScheduledTask -TaskName 'WSL_Backup'"

# Disable / Enable a task
powershell.exe -Command "Disable-ScheduledTask -TaskName 'WSL_Backup'"
powershell.exe -Command "Enable-ScheduledTask -TaskName 'WSL_Backup'"

# Delete a task
powershell.exe -Command "Unregister-ScheduledTask -TaskName 'WSL_Backup' -Confirm:`$false"
```

---

## Common Scenarios (Summary)

### Scenario A: Run Windows Python (GPU or otherwise)

```bash
# 一行检查
cmd.exe /c "E:\venvs\marker\Scripts\python.exe -c \"import torch; print(torch.cuda.is_available())\""
```

### Scenario B: Check if a Windows Package is Available

```bash
cmd.exe /c "D:\Anconda\python.exe -c \"import win32com.client; print('pywin32 OK')\""
```

### Scenario C: Cross-Boundary Clipboard Operations

```bash
# WSL → Windows clipboard
dmesg | tail -20 | clip.exe               # ASCII only
echo "中文" > /tmp/clip.txt                # 中文：写文件方式
powershell.exe -Command 'Set-Clipboard -Value (Get-Content -Path "\\wsl.localhost\Ubuntu\tmp\clip.txt" -Raw -Encoding UTF8)'

# Windows clipboard → WSL
powershell.exe -Command "Get-Clipboard"
```

### Scenario D: System Inventory

```bash
powershell.exe -Command "
    Get-ComputerInfo | Select-Object CsName,WindowsVersion,OsArchitecture |
    ConvertTo-Json
"
```

```bash
# One-shot system snapshot
powershell.exe -Command "
    @{
        OS = (Get-ItemProperty 'HKLM:\Software\Microsoft\Windows NT\CurrentVersion').ProductName
        CPU = (Get-CimInstance Win32_Processor).Name.Trim()
        RAM_GB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB, 1)
        Disks = (Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | ForEach-Object { \"\$(\$_.DeviceID) \$([math]::Round(\$_.Size/1GB,1))GB\" }) -join ', '
    } | ConvertTo-Json
"
```

---

## Error Handling and Debugging

### Common Errors

| Error | Meaning | Fix |
|-------|---------|-----|
| `Exec format error` | WSLInterop not registered | Register with `binfmt_misc` |
| `The term 'X' is not recognized` | Windows PATH issue | Use full paths or activate env |
| `Access is denied` | UAC/permission issue | Run as Administrator or adjust ACLs |
| `COM initialization failed` | COM not available in context | Ensure Windows-side process can access COM |
| Command appears to hang | Process waiting for input | Use `-NoNewWindow` and redirect stdin |
| `base64: invalid input` | EncodedCommand requires UTF-16LE | Always pipe through `iconv -t UTF-16LE` first |
| `Cannot convert value to System.String` | PowerShell output type mismatch | Pipe through `Out-String` or `ConvertTo-Json` before capture |

### Debugging Strategy

1. **Test the command directly in Windows PowerShell first**
   If it doesn't work there, it won't work from WSL either.

2. **Capture stderr explicitly**
   ```bash
   powershell.exe -Command "..." 2>&1
   ```

3. **Use transcript logging**
   ```bash
   powershell.exe -Command '
       Start-Transcript -Path "E:\\logs\\debug.log";
       # ... your commands ...
       Stop-Transcript
   '
   ```

4. **Check exit codes**
   ```bash
   powershell.exe -Command "..."
   echo "Exit code: $?"
   ```

5. **For EncodedCommand: verify encoding**
   ```bash
   # Decode to check what was sent
   echo "$cmd_b64" | base64 -d | xxd | head
   # Should show UTF-16LE (alternating null bytes for ASCII)
   ```

6. **Use `$ErrorActionPreference = 'Stop'`** to surface hidden errors
   ```bash
   powershell.exe -Command '$ErrorActionPreference = "Stop"; ...'
   ```

---

## Limitations (Must Know)

1. **No Interactive Input**: Cannot use `Read-Host`, interactive prompts, or GUI dialogs (except via `[User32]::MessageBox` w/ P/Invoke).
2. **No State Persistence**: Each call is a fresh process. Variables don't persist between calls.
3. **Encoding Gap**: cmd.exe (C) 和 Direct EXE (B) 的 pipe 输出走系统 GBK 编码，中文会乱码。**解决：写文件**（`cmd.exe /c "py ... > out.txt"`）。
4. **cmd.exe UNC 路径**: 从 WSL `~/` 目录调用 `cmd.exe` 报 UNC 不支持。**`cwd="/mnt/e/temp"`** 解决。
5. **ps -Command 参数拆分**: `powershell.exe -Command '...' "hello world"` 会把 hello world 拆成两个参数。复杂参数用 `-File`。
6. **ps -EncodedCommand CLIXML**: 非 TTY 输出会包 CLIXML。不推荐用于数据交换。
7. **ps -File 退出码**: 子进程的退出码在 `-File` 模式下会被吞掉。不推荐用于需要检测退出码的场景。
8. **COM Object Boundaries**: COM 对象在 PowerShell 进程内创建和使用，不能传递给 WSL。
9. **Administrator Privileges**: `netsh.exe firewall`、`sc.exe config` 等需要管理员权限。

## Best Practices

- **Channel 优先级**: cmd.exe (C) > Direct EXE (B) > PowerShell (A)。能 cmd 不用 ps。
- **GPU / Python 脚本**: 始终用 `cmd.exe /c`，`cwd="/mnt/e/temp"`。
- **PowerShell 仅用于**: COM / WMI / Event Log / P/Invoke — 这些是 cmd.exe 做不到的。
- **中文输出**: 写文件（`> win_file` 然后从 WSL 读取），不要依赖 pipe 编码。
- **复杂 PS 脚本**: 写入 `/mnt/e/temp/*.ps1`，用 `-File` 调用，参数不会被拆分。
- **安装 `wslu`**: `wslview` (打开文件), `wslvar` (读 Windows 环境变量)。
- **用 `wslpath`** 做路径转换。
- **用 JSON** 输出数据（`ConvertTo-Json`）便于 WSL 侧 `jq` 解析。
- **GPU 规则**: 统一在 `/home/dc/CLAUDE.md` → "GPU 桥接" 章节。

---

## Related Concepts

- **HTTP Bridge Pattern**: For complex automation, consider running a persistent HTTP server on the Windows side (like DrawForge's Visio Bridge) and calling it from WSL via HTTP. This avoids process-per-call overhead and provides session management.
- **SSH to Windows**: If WSLInterop fails, an alternative is running an SSH server on Windows and connecting via `ssh windows-host`.
- **WSLg (WSL GUI)**: Windows 11's WSLg allows Linux GUI apps to run natively on the Windows desktop, but the reverse (WSL controlling Windows GUI) still requires PowerShell bridge.
- **$env:WSLENV**: WSL shares this environment variable with Windows. Use it to pass values between environments: `export WSLENV=MYVAR/w` makes `$env:MYVAR` available in PowerShell.
