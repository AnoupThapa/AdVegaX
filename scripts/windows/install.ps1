# AdVegaX desktop - step 1 of 3: install the tools (Phase 16). Run once, in PowerShell:
#   Right-click the Start button > Terminal (Admin), then:
#   Set-ExecutionPolicy -Scope Process Bypass; & "$HOME\Downloads\Tools\Advegax\scripts\windows\install.ps1"
. "$PSScriptRoot\common.ps1"

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
  throw "winget is missing. Install 'App Installer' from the Microsoft Store, then run this again."
}

$packages = @(
  @{ Id = "Python.Python.3.12"; Name = "Python 3.12" },
  @{ Id = "astral-sh.uv"; Name = "uv (Python package manager)" },
  @{ Id = "OpenJS.NodeJS.LTS"; Name = "Node.js LTS" },
  @{ Id = "Memurai.MemuraiDeveloper"; Name = "Memurai Developer (Redis for Windows)" }
)
foreach ($p in $packages) {
  Say "Installing $($p.Name)"
  winget install --id $p.Id --exact --silent --accept-package-agreements --accept-source-agreements
}

Say "Installing PostgreSQL 16 (database superuser password: postgres - this computer only)"
winget install --id PostgreSQL.PostgreSQL.16 --exact --silent --accept-package-agreements `
  --accept-source-agreements --override "--mode unattended --superpassword postgres --serverport 5432"

Say "Done. Close this window, open a new PowerShell window and run setup.ps1."
