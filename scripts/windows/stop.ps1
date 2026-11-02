# AdVegaX desktop - stop everything start.ps1 started (Phase 16).
# Stops each started process with everything it started in turn (uv -> python, node -> server),
# then anything still answering on the app's ports, so a new build is really picked up.
. "$PSScriptRoot\common.ps1"

function Stop-Tree([int]$id) {
  Get-CimInstance Win32_Process -Filter "ParentProcessId=$id" -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Tree $_.ProcessId }
  Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
}

$pids = Join-Path $Var "pids.txt"
if (Test-Path $pids) {
  foreach ($id in Get-Content $pids) { if ($id) { Stop-Tree ([int]$id) } }
  Remove-Item $pids
}

# Anything left listening on the web (3000) or API (8000) port is an earlier AdVegaX run.
foreach ($port in 3000, 8000) {
  Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Tree $_.OwningProcess }
}

# Background jobs started from this folder (celery worker and scheduler).
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -match "celery" -and $_.CommandLine -match "app\.workers" } |
  ForEach-Object { Stop-Tree $_.ProcessId }

Write-Host "AdVegaX stopped."
