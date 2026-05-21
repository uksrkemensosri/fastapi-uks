$ErrorActionPreference = "Stop"

$taskName = "EMR-UKS-Sekolah-Rakyat"
$root = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $root "scripts\start_server.ps1"

if (-not (Test-Path $scriptPath)) {
    throw "Script not found: $scriptPath"
}

$action = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""

schtasks /Create /TN $taskName /TR $action /SC ONLOGON /RL LIMITED /F | Out-Null
Write-Output "Task Scheduler created: $taskName"
Write-Output "Server will auto-start on Windows logon."
