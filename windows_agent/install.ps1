#Requires -RunAsAdministrator
param(
    [string]$Config = (Join-Path $PSScriptRoot 'config.yaml'),
    [switch]$EnableUpdates, [string]$UpdateBaseUrl, [string]$PublicKeyPath,
    [switch]$ReplaceConfig
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'install_helpers.ps1')
$name = 'SmartHouseGamingControl'
$task = 'SmartHouseGamingControlUpdate'
$source = Join-Path $PSScriptRoot "dist\$name"
$updaterSource = Join-Path $PSScriptRoot 'dist\SmartHouseGamingUpdater'
$target = Join-Path $env:ProgramFiles $name
$updater = Join-Path $env:ProgramFiles 'SmartHouseGamingUpdater'
$data = Join-Path $env:ProgramData $name
$existingConfig = Join-Path $data 'config.yaml'
$serviceExists = [bool](Get-Service -Name $name -ErrorAction SilentlyContinue)
Test-InstallPreflight -Source $source -Config $Config -Target $target -Data $data `
    -UpdaterSource $updaterSource -UpdaterTarget $updater -EnableUpdates $EnableUpdates.IsPresent `
    -UpdateBaseUrl $UpdateBaseUrl -PublicKeyPath $PublicKeyPath -ServiceExists $serviceExists `
    -ReplaceConfig $ReplaceConfig.IsPresent

$createdService = $false
$createdTask = $false
try {
    New-Item -ItemType Directory -Force -Path $data, $target | Out-Null
    & icacls.exe $data /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F'
    if ($LASTEXITCODE) { throw 'Failed to protect data directory' }
    Assert-ProtectedAcl -Path $data
    Copy-Item -Path (Join-Path $source '*') -Destination $target -Recurse -Force
    & icacls.exe $target /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-32-545:(OI)(CI)RX'
    if ($LASTEXITCODE) { throw 'Failed to protect application directory' }
    Assert-ProtectedAcl -Path $target
    $configExists = Test-Path $existingConfig
    if (!$configExists -or $ReplaceConfig) { Copy-Item -LiteralPath $Config -Destination (Join-Path $data 'config.yaml') }
    $exe = Join-Path $target "$name.exe"
    New-Service -Name $name -BinaryPathName ('"' + $exe + '"') -DisplayName 'SmartHouse Gaming Control' -StartupType Automatic | Out-Null
    $createdService = $true
    & sc.exe failure $name reset= 86400 actions= restart/5000/restart/5000/restart/30000
    if ($LASTEXITCODE) { throw 'Failed to configure service recovery' }
    if ($EnableUpdates) {
        New-Item -ItemType Directory -Force -Path $updater | Out-Null
        Copy-Item -Path (Join-Path $updaterSource '*') -Destination $updater -Recurse -Force
        & icacls.exe $updater /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-32-545:(OI)(CI)RX'
        if ($LASTEXITCODE) { throw 'Failed to protect updater directory' }
        Assert-ProtectedAcl -Path $updater
        @{base_url=$UpdateBaseUrl; public_key_pem=(Get-Content -LiteralPath $PublicKeyPath -Raw)} | ConvertTo-Json -Compress | Set-Content -LiteralPath (Join-Path $data 'updater.json') -Encoding ascii
        $action = New-ScheduledTaskAction -Execute (Join-Path $updater 'SmartHouseGamingUpdater.exe') -WorkingDirectory $updater
        $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
        $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        Register-ScheduledTask -TaskName $task -TaskPath '\' -Action $action -Principal $principal -Settings $settings -Trigger (New-ScheduledTaskTrigger -AtStartup) | Out-Null
        $createdTask = $true
    }
    Start-Service -Name $name
    Get-Service -Name $name
} catch {
    if ($createdTask) { Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue }
    if ($createdService) { Stop-Service -Name $name -ErrorAction SilentlyContinue; & sc.exe delete $name | Out-Null }
    if (Test-Path -LiteralPath $updater) { Remove-Item -LiteralPath $updater -Recurse -Force }
    if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
    throw
}
