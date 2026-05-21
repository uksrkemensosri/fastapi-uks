param(
    [string]$DatabasePath = "emr_keperawatan.db",
    [string]$BackupDir = "backups"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $DatabasePath)) {
    throw "Database file not found: $DatabasePath"
}

if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$target = Join-Path $BackupDir ("emr_keperawatan_{0}.db" -f $timestamp)
Copy-Item -LiteralPath $DatabasePath -Destination $target

Write-Output "Backup created: $target"
