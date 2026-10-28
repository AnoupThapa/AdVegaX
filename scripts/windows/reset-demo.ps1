# AdVegaX desktop — start again from fresh demo data (deletes everything in the local database).
. "$PSScriptRoot\common.ps1"
& "$PSScriptRoot\stop.ps1"
& "$PSScriptRoot\setup.ps1" -Reset
