#Requires -RunAsAdministrator
param([switch]$Force)
$ErrorActionPreference = 'Stop'
$name = 'SmartHouseGamingControl'
$task = 'SmartHouseGamingControlUpdate'
$data = Join-Path $env:ProgramData $name
$updater = Join-Path $env:ProgramFiles 'SmartHouseGamingUpdater'
$journal = Join-Path $data 'update-journal.json'
if ((Test-Path -LiteralPath $journal) -and !$Force) { throw 'An unfinished update-journal.json transaction exists; recover it or use -Force explicitly.' }
if (Get-Service -Name $name -ErrorAction SilentlyContinue) {
    Stop-Service -Name $name -ErrorAction SilentlyContinue
    & sc.exe delete $name
    if ($LASTEXITCODE) { throw 'Service deletion failed' }
}
Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue
if (Test-Path -LiteralPath $updater) { Remove-Item -LiteralPath $updater -Recurse -Force }
# ProgramData configuration, logs, journal, and recovery evidence are deliberately retained.
