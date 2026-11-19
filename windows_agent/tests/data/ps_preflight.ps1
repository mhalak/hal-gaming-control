param([Parameter(Mandatory)][string]$JsonPath)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../../install_helpers.ps1')
$a = Get-Content -LiteralPath $JsonPath -Raw | ConvertFrom-Json
try {
    Test-InstallPreflight -Source $a.source -Config $a.config -Target $a.target -Data $a.data `
        -UpdaterSource $a.updater_source -UpdaterTarget $a.updater_target `
        -EnableUpdates ([bool]$a.enable) -UpdateBaseUrl $a.url -PublicKeyPath $a.key `
        -ServiceExists ([bool]$a.service) -ReplaceConfig ([bool]$a.replace)
    'OK'
} catch {
    'ERR: ' + $_.Exception.Message
}
