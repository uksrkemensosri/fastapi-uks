$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$logsDir = Join-Path $root "logs"
$pidFile = Join-Path $logsDir "uvicorn.pid"
$stdoutLog = Join-Path $logsDir "uvicorn.out.log"
$stderrLog = Join-Path $logsDir "uvicorn.err.log"

if (-not (Test-Path $python)) {
    throw "Python venv not found: $python"
}

if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
}

if (Test-Path $pidFile) {
    $existingPid = Get-Content $pidFile -ErrorAction SilentlyContinue
    if ($existingPid -and (Get-Process -Id $existingPid -ErrorAction SilentlyContinue)) {
        Write-Output "Server already running with PID $existingPid"
        exit 0
    }
}

$args = @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000")
$proc = Start-Process -FilePath $python -ArgumentList $args -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -PassThru
$proc.Id | Set-Content $pidFile
Write-Output "Server started with PID $($proc.Id)"
