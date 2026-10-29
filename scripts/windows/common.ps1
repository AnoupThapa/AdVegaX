# Shared helpers for the AdVegaX desktop scripts (Phase 16). Not run on its own.
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Var = Join-Path $Root "var"
$EnvFile = Join-Path $Var "desktop.env"
$PgBin = (Get-ChildItem "C:\Program Files\PostgreSQL" -Directory -ErrorAction SilentlyContinue |
  Sort-Object Name -Descending | Select-Object -First 1 | ForEach-Object { Join-Path $_.FullName "bin" })

function Say($text) { Write-Host "`n== $text" -ForegroundColor Cyan }

function Refresh-Path {
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
    [Environment]::GetEnvironmentVariable("Path", "User")
  if ($PgBin) { $env:Path = "$PgBin;$env:Path" }
}

function Import-DesktopEnv {
  if (-not (Test-Path $EnvFile)) { throw "Run setup.ps1 first (no $EnvFile)." }
  foreach ($line in Get-Content $EnvFile) {
    if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
    $name, $value = $line -split '=', 2
    [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim(), "Process")
  }
}

function Need($command, $what) {
  if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
    throw "$what is not installed or not on PATH. Run install.ps1 (then open a new PowerShell window)."
  }
}

# Redis is Memurai when installed; otherwise fall back to Redis inside WSL (Ubuntu). WSL stops its
# virtual machine when idle, so keep it alive with a hidden process that runs Redis.
function Test-RedisPort {
  try {
    $c = New-Object System.Net.Sockets.TcpClient
    $c.Connect("127.0.0.1", 6379); $c.Close(); return $true
  } catch { return $false }
}

function Ensure-Redis {
  if (Test-RedisPort) { return }
  if (Get-Command wsl -ErrorAction SilentlyContinue) {
    Write-Host "  starting Redis in WSL (Memurai is not running)"
    Start-Process wsl -ArgumentList '-u', 'root', '--', 'bash', '-c', '"service redis-server start; exec sleep infinity"' -WindowStyle Hidden
    for ($i = 0; $i -lt 15; $i++) { if (Test-RedisPort) { return }; Start-Sleep -Seconds 1 }
  }
  throw "Redis is not running on port 6379. Install Memurai, or Redis in WSL (sudo apt install redis-server), then try again."
}
