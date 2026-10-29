# AdVegaX desktop - step 3: start everything and open the browser (Phase 16).
#   & ".\scripts\windows\start.ps1"        (stop with stop.ps1)
#   -Page admin   opens the Admin portal instead of the app's home page
param([string]$Page = "")
. "$PSScriptRoot\common.ps1"
$url = "http://localhost:3000/$Page"
$openBrowser = $Page -ne "none"
if (-not $openBrowser) { $url = "http://localhost:3000/" }

# Already running (e.g. started by the desktop shortcut or at sign-in): just open the page.
try {
  Invoke-WebRequest "http://localhost:8000/api/v1/health/ready" -UseBasicParsing -TimeoutSec 3 | Out-Null
  if ($openBrowser) { Start-Process $url }
  exit 0
} catch { }

Refresh-Path
Need uv "uv"; Need node "Node.js"
Import-DesktopEnv
Ensure-Redis
$logs = Join-Path $Var "logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null

function Start-Part($name, $dir, $file, $arguments) {
  $p = Start-Process -FilePath $file -ArgumentList $arguments -WorkingDirectory $dir `
    -RedirectStandardOutput (Join-Path $logs "$name.log") -RedirectStandardError (Join-Path $logs "$name.err.log") `
    -WindowStyle Hidden -PassThru
  $p.Id | Out-File -Append (Join-Path $Var "pids.txt")
  Write-Host "  started $name"
}

Remove-Item (Join-Path $Var "pids.txt") -ErrorAction SilentlyContinue
Say "Starting AdVegaX"
Start-Part "api" $Backend "uv" "run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000"
Start-Part "worker" $Backend "uv" "run celery -A app.workers.celery_app:celery_app worker --pool=solo --loglevel=INFO"
Start-Part "scheduler" $Backend "uv" "run celery -A app.workers.celery_app:celery_app beat --loglevel=INFO --schedule $Var\celerybeat-schedule"
$env:PORT = "3000"
Start-Part "web" $Frontend "node" "scripts/start-standalone.mjs"

Say "Waiting for the API"
for ($i = 0; $i -lt 60; $i++) {
  try { Invoke-WebRequest "http://localhost:8000/api/v1/health/ready" -UseBasicParsing | Out-Null; break }
  catch { Start-Sleep -Seconds 2 }
}
Start-Sleep -Seconds 3
if ($openBrowser) { Start-Process $url }
Write-Host @"

AdVegaX is running at http://localhost:3000
  Sign in: demo@advegax.local  or  agency@advegax.local   password: AdVegaX-demo-2026
  Emails (sign-up links, invitations): $Var\mail
  Logs: $logs
Stop it with stop.ps1.
"@
