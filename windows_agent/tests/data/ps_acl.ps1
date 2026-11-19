param([Parameter(Mandatory)][string]$JsonPath)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../../install_helpers.ps1')
$rules = Get-Content -LiteralPath $JsonPath -Raw | ConvertFrom-Json | ForEach-Object {
    [pscustomobject]@{ Sid = $_.sid; Rights = [int]$_.rights; Type = $_.type }
}
(Test-AclRulesSafe -Rules @($rules)) -join ','
