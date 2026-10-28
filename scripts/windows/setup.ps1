# AdVegaX desktop - step 2 of 3: database, settings, packages and demo data (Phase 16).
# Run once (and again any time with -Reset to start from fresh demo data):
#   Set-ExecutionPolicy -Scope Process Bypass; & ".\scripts\windows\setup.ps1"
param([switch]$Reset)
. "$PSScriptRoot\common.ps1"
Refresh-Path
Need uv "uv"; Need npm "Node.js"; Need psql "PostgreSQL"
New-Item -ItemType Directory -Force -Path $Var | Out-Null

if (-not (Test-Path $EnvFile)) {
  Say "Writing this computer's settings ($EnvFile)"
  $rand = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 48 | ForEach-Object { [char]$_ })
  $key = [Convert]::ToBase64String((1..32 | ForEach-Object { [byte](Get-Random -Maximum 256) }))
  $settings = Get-Content (Join-Path $Root ".env.example") | Where-Object { $_ -notmatch '^\s*#' -and $_ -match '=' }
  $settings += @(
    "ENVIRONMENT=local",
    "SECRET_KEY=$rand",
    "ENCRYPTION_KEYS=1:$key",
    "EMAIL_BACKEND=folder",
    "EMAIL_FOLDER=$Var\mail",
    "BILLING_ENABLED=true",
    "BILLING_TRIAL_DAYS=90",
    "AGENCY_ENABLED=true",
    "OPTIMIZATION_ENABLED=true",
    "THROTTLE_LOGIN_PER_ACCOUNT_IP_PER_MINUTE=30",
    "THROTTLE_REGISTER_PER_IP_PER_HOUR=50"
  )
  $settings | Set-Content -Encoding utf8 $EnvFile
  Write-Host "Keep a copy of ENCRYPTION_KEYS in your password manager: keys saved in the Admin portal need it."
}
Import-DesktopEnv

$env:PGPASSWORD = "postgres"
if ($Reset) {
  Say "Removing the old database"
  psql -h localhost -U postgres -d postgres -c "DROP DATABASE IF EXISTS advegax WITH (FORCE)"
  Remove-Item -Recurse -Force (Join-Path $Var "mail") -ErrorAction SilentlyContinue
}
Say "Creating the database roles and database"
psql -h localhost -U postgres -d postgres -v ON_ERROR_STOP=1 -f (Join-Path $Root "infrastructure\docker\postgres\init\001_roles.sql")
$exists = psql -h localhost -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = 'advegax'"
if ($exists -ne "1") {
  psql -h localhost -U postgres -d postgres -c "CREATE DATABASE advegax OWNER advegax_migrator"
  psql -h localhost -U postgres -d advegax -v ON_ERROR_STOP=1 -c @"
REVOKE ALL ON DATABASE advegax FROM PUBLIC;
GRANT CONNECT ON DATABASE advegax TO advegax_migrator, advegax_app, advegax_system;
ALTER SCHEMA public OWNER TO advegax_migrator;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO advegax_app, advegax_system;
"@
}

Say "Installing the backend's packages"
Push-Location $Backend
uv sync --frozen
Say "Updating the database"
uv run alembic upgrade head
Say "Filling it with demo data (simulated platforms; nothing leaves this computer)"
uv run python -m demo.seed
Pop-Location

Say "Installing and building the web app (a few minutes)"
Push-Location $Frontend
npm ci
$env:NEXT_PUBLIC_API_BASE_URL = "http://localhost:8000"
npm run build
Pop-Location

Say "Ready. Run start.ps1 to open AdVegaX."
