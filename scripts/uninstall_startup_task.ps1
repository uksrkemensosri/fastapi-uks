$taskName = "EMR-UKS-Sekolah-Rakyat"
schtasks /Delete /TN $taskName /F | Out-Null
Write-Output "Task Scheduler removed: $taskName"
