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
