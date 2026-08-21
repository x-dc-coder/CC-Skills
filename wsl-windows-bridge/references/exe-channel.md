# 参考：直调工具通道（Channel B）— reg/sc/tasklist/netsh/certutil/schtasks/icacls + wslu + wsl.exe

> 本文件是 `SKILL.md` 的按需加载参考。需要快速注册表/服务/进程/防火墙/证书/权限操作、
> 或 wslu / wsl.exe 自管理时读取。

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

