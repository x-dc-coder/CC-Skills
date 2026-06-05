#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Windows-side JSON command runner for WSL PowerShell Bridge.
    Accepts commands as JSON via file or argument, executes them, returns JSON output.

.DESCRIPTION
    Call from WSL with:
      powershell.exe -File "E:\path\to\win-json-runner.ps1" -CommandFile "E:\temp\cmd.json"

    Input JSON format:
    {
        "action": "registry_read" | "registry_write" | "wmi_query" | "process" | "exec",
        "params": { ... action-specific parameters ... }
    }

    All actions return JSON on stdout. Errors go to stderr.
#>

param(
    [string]$CommandFile,
    [string]$CommandJson
)

$ErrorActionPreference = "Stop"

function Write-JsonOutput($data) {
    $data | ConvertTo-Json -Depth 10 -Compress
}

function Write-JsonError($message, $details) {
    @{ error = $true; message = $message; details = "$details" } | ConvertTo-Json -Compress
}

try {
    # Load command
    if ($CommandFile -and (Test-Path $CommandFile)) {
        $cmd = Get-Content $CommandFile -Raw | ConvertFrom-Json
    } elseif ($CommandJson) {
        $cmd = $CommandJson | ConvertFrom-Json
    } else {
        throw "Either -CommandFile or -CommandJson is required"
    }

    switch ($cmd.action) {
        "registry_read" {
            $path = $cmd.params.path
            $name = $cmd.params.name
            if ($name) {
                $val = (Get-ItemProperty -Path $path -Name $name -ErrorAction Stop).$name
                Write-JsonOutput @{ path = $path; name = $name; value = $val }
            } else {
                $props = Get-ItemProperty -Path $path -ErrorAction Stop
                Write-JsonOutput $props
            }
        }

        "registry_write" {
            $path = $cmd.params.path
            $name = $cmd.params.name
            $value = $cmd.params.value
            $type = if ($cmd.params.type) { $cmd.params.type } else { "String" }
            New-Item -Path $path -Force -ErrorAction SilentlyContinue | Out-Null
            Set-ItemProperty -Path $path -Name $name -Value $value -Type $type -ErrorAction Stop
            Write-JsonOutput @{ status = "ok"; path = $path; name = $name }
        }

        "wmi_query" {
            $class = $cmd.params.class
            $filter = $cmd.params.filter
            $properties = $cmd.params.properties
            if ($filter) {
                $result = Get-CimInstance -ClassName $class -Filter $filter -ErrorAction Stop
            } else {
                $result = Get-CimInstance -ClassName $class -ErrorAction Stop
            }
            if ($properties) {
                $result = $result | Select-Object -Property $properties
            }
            Write-JsonOutput @{ count = ($result | Measure-Object).Count; data = $result }
        }

        "process_list" {
            $pattern = $cmd.params.commandLinePattern
            $name = $cmd.params.processName
            if ($pattern) {
                $procs = Get-CimInstance Win32_Process | Where-Object CommandLine -like "*$pattern*"
            } elseif ($name) {
                $procs = Get-CimInstance Win32_Process | Where-Object Name -like "*$name*"
            } else {
                $procs = Get-CimInstance Win32_Process
            }
            $result = $procs | Select-Object ProcessId, Name, CommandLine,
                @{N='WorkingSetMB';E={[math]::Round($_.WorkingSetSize/1MB,1)}},
                @{N='ThreadCount';E={$_.ThreadCount}}
            Write-JsonOutput @{ count = ($result | Measure-Object).Count; data = $result }
        }

        "process_stop" {
            $pid_val = $cmd.params.pid
            $pattern = $cmd.params.commandLinePattern
            if ($pid_val) {
                Stop-Process -Id $pid_val -Force -ErrorAction Stop
                Write-JsonOutput @{ status = "stopped"; pid = $pid_val }
            } elseif ($pattern) {
                $procs = Get-CimInstance Win32_Process | Where-Object CommandLine -like "*$pattern*"
                $stopped = @()
                foreach ($p in $procs) {
                    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
                    $stopped += $p.ProcessId
                }
                Write-JsonOutput @{ status = "stopped"; pids = $stopped; count = $stopped.Count }
            } else {
                throw "Either pid or commandLinePattern is required for process_stop"
            }
        }

        "process_start" {
            $exe = $cmd.params.executable
            $args_list = $cmd.params.arguments
            $workDir = $cmd.params.workingDirectory
            $envVars = $cmd.params.environment
            $wait = $cmd.params.wait

            $procParams = @{
                FilePath = $exe
                PassThru = $true
            }
            if ($args_list) { $procParams.ArgumentList = $args_list }
            if ($workDir) { $procParams.WorkingDirectory = $workDir }
            if (-not $wait) { $procParams.NoNewWindow = $true }

            # Set env vars for this process
            $oldEnv = @{}
            if ($envVars) {
                foreach ($key in $envVars.PSObject.Properties.Name) {
                    $oldEnv[$key] = [Environment]::GetEnvironmentVariable($key, "Process")
                    [Environment]::SetEnvironmentVariable($key, $envVars.$key, "Process")
                }
            }

            $proc = Start-Process @procParams

            if ($wait) {
                $proc.WaitForExit()
                Write-JsonOutput @{ status = "completed"; pid = $proc.Id; exitCode = $proc.ExitCode }
            } else {
                Write-JsonOutput @{ status = "started"; pid = $proc.Id }
            }
        }

        "clipboard_get" {
            Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
            $text = [System.Windows.Forms.Clipboard]::GetText()
            Write-JsonOutput @{ text = $text }
        }

        "clipboard_set" {
            $text = $cmd.params.text
            Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
            [System.Windows.Forms.Clipboard]::SetText($text)
            Write-JsonOutput @{ status = "ok" }
        }

        "event_log" {
            $logName = if ($cmd.params.logName) { $cmd.params.logName } else { "System" }
            $level = $cmd.params.level
            $hours = if ($cmd.params.hours) { $cmd.params.hours } else { 24 }
            $maxEvents = if ($cmd.params.maxEvents) { $cmd.params.maxEvents } else { 50 }
            $pattern = $cmd.params.messagePattern

            $filter = @{
                LogName = $logName
                StartTime = (Get-Date).AddHours(-$hours)
            }
            if ($level) { $filter.Level = $level }

            $events = Get-WinEvent -FilterHashtable $filter -MaxEvents $maxEvents -ErrorAction SilentlyContinue
            if ($pattern) {
                $events = $events | Where-Object { $_.Message -match $pattern }
            }
            $result = $events | Select-Object TimeCreated, Id, LevelDisplayName,
                @{N='Provider';E={$_.ProviderName}},
                @{N='Message';E={if ($_.Message.Length -gt 500) { $_.Message.Substring(0,500) + "..." } else { $_.Message }}}
            Write-JsonOutput @{ count = ($result | Measure-Object).Count; data = $result }
        }

        "system_info" {
            $os = Get-ItemProperty "HKLM:\Software\Microsoft\Windows NT\CurrentVersion"
            $cs = Get-CimInstance Win32_ComputerSystem
            $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
            $disks = Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3'
            $mem = Get-CimInstance Win32_OperatingSystem

            Write-JsonOutput @{
                os = "$($os.ProductName) Build $($os.CurrentBuild) $($os.EditionID)"
                manufacturer = $cs.Manufacturer
                model = $cs.Model
                cpu = $cpu.Name.Trim()
                cpuCores = $cpu.NumberOfCores
                cpuThreads = $cpu.ThreadCount
                ramTotalGB = [math]::Round($cs.TotalPhysicalMemory/1GB, 1)
                ramFreeGB = [math]::Round($mem.FreePhysicalMemory/1MB, 1)
                disks = ($disks | ForEach-Object {
                    "$($_.DeviceID) $([math]::Round($_.Size/1GB,1))GB ($([math]::Round($_.FreeSpace/1GB,1))GB free)"
                }) -join "; "
                lastBoot = $mem.LastBootUpTime
            }
        }

        "env_get" {
            $varName = $cmd.params.name
            if ($varName) {
                $val = [Environment]::GetEnvironmentVariable($varName, "Machine")
                if (-not $val) { $val = [Environment]::GetEnvironmentVariable($varName, "User") }
                if (-not $val) { $val = $env:$varName }
                Write-JsonOutput @{ name = $varName; value = $val }
            } else {
                $all = @{}
                Get-ChildItem Env: | ForEach-Object { $all[$_.Name] = $_.Value }
                Write-JsonOutput @{ count = $all.Count; variables = $all }
            }
        }

        "scheduled_task_list" {
            $tasks = Get-ScheduledTask | Select-Object TaskName, State, Description
            Write-JsonOutput @{ count = ($tasks | Measure-Object).Count; data = $tasks }
        }

        default {
            throw "Unknown action: $($cmd.action). Available: registry_read, registry_write, wmi_query, process_list, process_stop, process_start, clipboard_get, clipboard_set, event_log, system_info, env_get, scheduled_task_list"
        }
    }
} catch {
    Write-JsonError -message $_.Exception.Message -details $_.ScriptStackTrace
    exit 1
}
