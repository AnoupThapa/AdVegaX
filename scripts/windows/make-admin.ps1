# AdVegaX desktop — make a person an administrator (for the Admin portal at /admin).
#   & ".\scripts\windows\make-admin.ps1" demo@advegax.local
param([Parameter(Mandatory = $true)][string]$Email)
. "$PSScriptRoot\common.ps1"
Refresh-Path
Import-DesktopEnv
Push-Location $Backend
uv run python -m app.domains.platform.make_admin $Email
Pop-Location
