# AdVegaX desktop — stop everything start.ps1 started (Phase 16).
. "$PSScriptRoot\common.ps1"
$pids = Join-Path $Var "pids.txt"
if (Test-Path $pids) {
  foreach ($id in Get-Content $pids) {
    Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$id" -ErrorAction SilentlyContinue |
      ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  }
  Remove-Item $pids
}
Write-Host "AdVegaX stopped."
