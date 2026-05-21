$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root "logs\uvicorn.pid"

if (-not (Test-Path $pidFile)) {
    Write-Output "PID file not found. Server may already be stopped."
    exit 0
}

$pidValue = Get-Content $pidFile -ErrorAction SilentlyContinue
if ($pidValue -and (Get-Process -Id $pidValue -ErrorAction SilentlyContinue)) {
    Stop-Process -Id $pidValue -Force
    Write-Output "Server stopped (PID $pidValue)"
} else {
    Write-Output "No running process found for PID $pidValue"
}

Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
