---
name: wsl-powershell-bridge
description: >
  How to invoke Windows special environments (pywin32, COM interfaces, Visio, Office,
  .NET, Win32 API, Windows-specific Python packages) from WSL using PowerShell as a bridge.
  Use this skill whenever the user is in WSL and needs to:
  - interact with Windows COM objects (Visio, Word, Excel, PowerPoint)
  - run Python scripts that require pywin32, pythonnet, or other Windows-only packages
  - call Windows executables or services that have no Linux equivalent
  - automate Windows software from a WSL development environment
  - handle WSLInterop setup, cross-boundary file paths, or process management
  Even if the user does not explicitly mention "PowerShell" or "WSLInterop",
  if they are in WSL and need Windows-specific capabilities, use this skill.
---

# WSL PowerShell Bridge Skill

## Purpose

WSL2 runs a Linux kernel, which means Windows-only capabilities (COM, Win32 API,
Windows-specific Python packages) are **not directly accessible** from WSL.
However, WSL provides `WSLInterop` — a mechanism to launch Windows executables
from Linux. This skill teaches how to use `powershell.exe` as a bridge to
invoke Windows environments from WSL.

## When to Use This Skill

- The user is in a WSL environment (Linux shell, `/mnt/c/` paths, etc.)
- The user needs to interact with Windows-only software or APIs
- Common indicators: mentions of Visio, Office, COM, pywin32, Windows services,
  .NET Framework, or paths like `E:\` or `C:\`

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

## Three Calling Patterns

### Pattern 1: Inline PowerShell Command (Simple, One-off)

Best for: quick checks, single commands, process management

```bash
powershell.exe -Command "Get-Process -Name python | Select-Object Id"
```

**Limitations:**
- Command length limited (~8000 chars)
- Quote escaping is painful (double quotes inside double quotes)
- No state persistence between calls

**Tip:** Use single quotes for the outer shell, double quotes inside:

```bash
powershell.exe -Command 'Write-Host "Hello World"'
```

### Pattern 2: PowerShell Script File (Recommended for Complex Tasks)

Best for: multi-step operations, parameter passing, error handling

```powershell
# Save as E:\scripts\visio_check.ps1
param(
    [string]$Action = "GetVersion"
)

$env:VISIO_BRIDGE_TOKEN = "my-token"
Import-Module -Name SomeWindowsModule

switch ($Action) {
    "GetVersion" {
        $visio = New-Object -ComObject Visio.Application
        Write-Output $visio.Version
        $visio.Quit()
    }
    "Export" {
        # ... complex export logic
    }
}
```

Call from WSL:

```bash
powershell.exe -File "E:\scripts\visio_check.ps1" -Action "GetVersion"
```

**Advantages:**
- Clean separation of Windows logic
- Proper parameter handling
- Full PowerShell error handling (`try/catch`, `$ErrorActionPreference`)

### Pattern 3: Python Script on Windows Side (Best for Data Exchange)

Best for: passing complex data, long-running tasks, structured output

```python
# Save as E:\scripts\visio_automation.py
import json
import sys
import win32com.client

def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "info"
    visio = win32com.client.Dispatch("Visio.Application")
    visio.Visible = False

    if action == "info":
        result = {"version": visio.Version, "name": visio.Name}
        print(json.dumps(result))
    elif action == "export":
        # ... export logic
        print(json.dumps({"status": "ok", "file": "output.png"}))

    visio.Quit()

if __name__ == "__main__":
    main()
```

Call from WSL:

```bash
# Windows Python with pywin32 runs the script
powershell.exe -Command "E:\\Python311\\python.exe E:\\scripts\\visio_automation.py info"
```

**Advantages:**
- JSON output easy to parse from WSL
- Both sides use Python (less context switching)
- Can use all Windows Python packages (pywin32, pythonnet, etc.)

## Common Scenarios

### Scenario A: Check if a Windows Package is Available

```bash
powershell.exe -Command "python -c \"import win32com.client; print('pywin32 OK')\""
```

### Scenario B: Manage a Windows Service (e.g., Bridge Server)

```bash
# Start
powershell.exe -Command '
    cd E:\AllProjects\DrawForge\agent\skills\visioskills\bridge_server;
    $env:VISIO_BRIDGE_TOKEN="drawforge-test-token-2026";
    . .venv\Scripts\Activate.ps1;
    Start-Process -NoNewWindow uvicorn -ArgumentList "app:app","--host","0.0.0.0","--port","18761"
'

# Stop
powershell.exe -Command "Get-Process -Name python* -ErrorAction SilentlyContinue | Stop-Process -Force"

# Check status
powershell.exe -Command "Get-Process -Name uvicorn -ErrorAction SilentlyContinue | Select-Object Id, ProcessName"
```

### Scenario C: File Operations Between WSL and Windows

```bash
# WSL path → Windows path conversion
wslpath -w /home/user/project/file.txt
# Output: \\wsl.localhost\Ubuntu\home\user\project\file.txt

# Windows path → WSL path
wslpath -u "E:\AllProjects\DrawForge"
# Output: /mnt/e/AllProjects/DrawForge

# Copy from WSL to Windows
powershell.exe -Command "Copy-Item '\$(wslpath -w /home/user/file.txt)' 'E:\\dest\\'"
```

### Scenario D: COM Object Automation (Visio, Office)

```bash
# Get Visio version via COM
powershell.exe -Command "
    \$visio = New-Object -ComObject Visio.Application;
    Write-Output \$visio.Version;
    \$visio.Quit()
"
```

**Critical Note:** COM objects cannot be passed across the WSL-Windows boundary.
They must be created, used, and destroyed entirely within the Windows-side process.

## Error Handling and Debugging

### Common Errors

| Error | Meaning | Fix |
|-------|---------|-----|
| `Exec format error` | WSLInterop not registered | Register with `binfmt_misc` |
| `The term 'X' is not recognized` | Windows PATH issue | Use full paths or activate env |
| `Access is denied` | UAC/permission issue | Run as Administrator or adjust ACLs |
| `COM initialization failed` | COM not available in context | Ensure Windows-side process can access COM |
| Command appears to hang | Process waiting for input | Use `-NoNewWindow` and redirect stdin |

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

## Limitations (Must Know)

1. **No Interactive Input**: Cannot use `Read-Host`, interactive prompts, or GUI dialogs.
2. **No State Persistence**: Each `powershell.exe` call is a fresh process. Variables set in one call don't exist in the next.
3. **Process Lifecycle Complexity**: Background processes started with `Start-Process -NoNewWindow` detach from the PowerShell session. Killing them requires filtering by name/command line, which is unreliable.
4. **Quote Escaping Hell**: Complex commands with nested quotes become unreadable quickly. Prefer script files.
5. **Performance Overhead**: Each call spins up a new PowerShell process (~200-500ms). Not suitable for high-frequency operations.
6. **COM Object Boundaries**: COM objects created in Windows cannot be referenced from WSL. They must be fully managed within the Windows-side script.
7. **No TTY/GUI**: Cannot open Windows GUI windows or interact with desktop applications from WSL.

## Best Practices

- **Use Pattern 2 (script files) for anything longer than one line**
- **Use Pattern 3 (Python on Windows) for data-intensive workflows**
- **Always use full paths** — relative paths resolve in unpredictable contexts
- **Set environment variables in the same command** as the execution
- **Log to files** for debugging rather than relying on stdout capture
- **Use `wslpath`** for robust path conversion between Linux and Windows formats
- **Kill processes carefully** — avoid `Stop-Process -Name python*` which may kill unrelated processes

## Related Concepts

- **HTTP Bridge Pattern**: For complex automation, consider running a persistent HTTP server on the Windows side (like DrawForge's Visio Bridge) and calling it from WSL via HTTP. This avoids process-per-call overhead and provides session management.
- **SSH to Windows**: If WSLInterop fails, an alternative is running an SSH server on Windows and connecting via `ssh windows-host`.
