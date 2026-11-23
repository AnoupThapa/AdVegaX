# AdVegaX desktop - make shortcuts so nothing has to be typed again (Phase 16).
# Run once, after setup.ps1:
#   Set-ExecutionPolicy -Scope Process Bypass; .\scripts\windows\create-shortcuts.ps1
# Optional: add -AutoStart to start AdVegaX by itself each time you sign in to Windows.
param([switch]$AutoStart)
. "$PSScriptRoot\common.ps1"

$shell = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath("Desktop")
$powershell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"

function New-Shortcut($path, $script, $arguments, $description, $hotkey) {
  $link = $shell.CreateShortcut($path)
  $link.TargetPath = $powershell
  $link.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$PSScriptRoot\$script`" $arguments"
  $link.WorkingDirectory = $Root
  $link.Description = $description
  $link.IconLocation = "$env:SystemRoot\System32\shell32.dll,13"
  if ($hotkey) { $link.Hotkey = $hotkey }
  $link.Save()
  Write-Host "  created $path $(if ($hotkey) { "(keys: $hotkey)" })"
}

Say "Creating desktop shortcuts"
New-Shortcut (Join-Path $desktop "AdVegaX.lnk") "start.ps1" "" `
  "Start AdVegaX (if needed) and open the app" "Ctrl+Alt+A"
New-Shortcut (Join-Path $desktop "AdVegaX Admin.lnk") "start.ps1" "-Page admin" `
  "Start AdVegaX (if needed) and open the Admin portal" "Ctrl+Alt+D"
New-Shortcut (Join-Path $desktop "AdVegaX Stop.lnk") "stop.ps1" "" `
  "Stop AdVegaX" "Ctrl+Alt+S"

if ($AutoStart) {
  $startup = [Environment]::GetFolderPath("Startup")
  $link = $shell.CreateShortcut((Join-Path $startup "AdVegaX.lnk"))
  $link.TargetPath = $powershell
  $link.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$PSScriptRoot\start.ps1`" -Page none"
  $link.WorkingDirectory = $Root
  $link.Save()
  Write-Host "  AdVegaX will start by itself when you sign in to Windows."
}

Say "Done. Double-click 'AdVegaX' or 'AdVegaX Admin' on your desktop (or press the keys shown)."
