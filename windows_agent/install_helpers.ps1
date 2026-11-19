Set-StrictMode -Version Latest

function Test-AclRulesSafe {
    param([Parameter(Mandatory)]$Rules)
    $trusted = @('S-1-5-18', 'S-1-5-32-544')
    # Synchronize is included in ordinary read/execute grants and does not permit modification.
    $writeMask = [int64]([System.Security.AccessControl.FileSystemRights]::Write -bor
        [System.Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
        [System.Security.AccessControl.FileSystemRights]::Delete -bor
        [System.Security.AccessControl.FileSystemRights]::ChangePermissions -bor
        [System.Security.AccessControl.FileSystemRights]::TakeOwnership) -bor 0x40000000 -bor 0x10000000
    @($Rules | Where-Object {
        $_.Type -eq 'Allow' -and $_.Sid -notin $trusted -and (([int64]$_.Rights -band $writeMask) -ne 0)
    } | ForEach-Object { $_.Sid })
}

function Assert-ProtectedAcl {
    param([Parameter(Mandatory)][string]$Path)
    $rules = (Get-Acl -LiteralPath $Path).Access | ForEach-Object {
        [pscustomobject]@{ Sid = $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value; Rights = [int64]$_.FileSystemRights; Type = [string]$_.AccessControlType }
    }
    $unsafe = @(Test-AclRulesSafe -Rules $rules)
    if ($unsafe.Count) { throw "Unsafe writable ACL on $Path for $($unsafe -join ', ')" }
}

function Test-InstallPreflight {
    param(
        [Parameter(Mandatory)][string]$Source, [Parameter(Mandatory)][string]$Config,
        [Parameter(Mandatory)][string]$Target, [Parameter(Mandatory)][string]$Data,
        [Parameter(Mandatory)][string]$UpdaterSource, [Parameter(Mandatory)][string]$UpdaterTarget,
        [bool]$EnableUpdates, [string]$UpdateBaseUrl, [string]$PublicKeyPath,
        [bool]$ServiceExists, [bool]$ReplaceConfig
    )
    if ($ServiceExists) { throw 'Existing service must be removed or upgraded explicitly' }
    if (!(Test-Path -LiteralPath (Join-Path $Source 'SmartHouseGamingControl.exe') -PathType Leaf)) { throw 'Run build.ps1 first' }
    if (!(Test-Path -LiteralPath (Join-Path $Source 'version.txt') -PathType Leaf)) { throw 'Build version.txt is missing' }
    if (Test-Path -LiteralPath $Target) { throw 'Program Files target is a leftover' }
    if (Test-Path -LiteralPath $UpdaterTarget) { throw 'Updater target is a leftover' }
    foreach ($p in @("$Target.rollback", "$Target.staging")) { if (Test-Path -LiteralPath $p) { throw 'Unfinished update transaction found' } }
    if (Test-Path -LiteralPath (Join-Path $Data 'update-journal.json')) { throw 'Unfinished update transaction journal found' }
    $existingConfig = Join-Path $Data 'config.yaml'
    $configToCheck = if (Test-Path -LiteralPath $existingConfig -PathType Leaf) { $existingConfig } else { $Config }
    if (!(Test-Path -LiteralPath $configToCheck -PathType Leaf)) { throw 'Configuration file is missing' }
    $configText = Get-Content -LiteralPath $configToCheck -Raw
    if ($configText -match 'REPLACE_WITH_') { throw 'Configuration still contains a placeholder' }
    $configuredEnabled = $configText -match '(?m)^\s*enabled:\s*true\s*$'
    if ($EnableUpdates -ne $configuredEnabled) { throw 'Installer choice must agree with update.enabled' }
    if (!$EnableUpdates -and ($UpdateBaseUrl -or $PublicKeyPath)) { throw 'Update options require EnableUpdates' }
    if ($EnableUpdates) {
        if (!$UpdateBaseUrl -or !$PublicKeyPath) { throw 'EnableUpdates requires URL and public key' }
        try { $uri = [Uri]$UpdateBaseUrl } catch { throw 'Invalid HTTPS update URL' }
        if (!$uri.IsAbsoluteUri -or $uri.Scheme -ne 'https' -or !$uri.Host -or $uri.UserInfo -or $uri.Query -or $uri.Fragment) { throw 'Invalid HTTPS update URL' }
        if (!(Test-Path -LiteralPath $PublicKeyPath -PathType Leaf)) { throw 'Public key file missing' }
        if ((Get-Content -LiteralPath $PublicKeyPath -Raw) -notmatch 'BEGIN PUBLIC KEY') { throw 'Invalid public key' }
        if (!(Test-Path -LiteralPath (Join-Path $UpdaterSource 'SmartHouseGamingUpdater.exe') -PathType Leaf)) { throw 'Updater build required' }
    }
}
