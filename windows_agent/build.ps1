param([string]$Version)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$identityTool = Join-Path $PSScriptRoot '..\tools\release_identity.py'
$identityArgs = @('identity', '--component', 'windows_agent')
if ($PSBoundParameters.ContainsKey('Version')) {
    if ([string]::IsNullOrWhiteSpace($Version)) { throw 'Empty explicit version' }
    $identityArgs += @('--version', $Version)
}
$identityJson = & py -3.12 $identityTool @identityArgs
if ($LASTEXITCODE) { throw 'Invalid source release identity' }
$identity = $identityJson | ConvertFrom-Json
py -3.12 -m venv .venv
if ($LASTEXITCODE) { throw 'venv failed' }
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $python -m pip install -r requirements-dev.txt 'pyinstaller>=6,<7'
if ($LASTEXITCODE) { throw 'Dependency installation failed' }
& $python -m pytest -q
if ($LASTEXITCODE) { throw 'Tests failed' }
& $python -m PyInstaller --noconfirm --clean --onedir --name SmartHouseGamingControl --hidden-import win32timezone --hidden-import win32ts --hidden-import win32profile service_entry.py
if ($LASTEXITCODE) { throw 'Build failed' }
& $python -m PyInstaller --noconfirm --clean --onedir --name SmartHouseGamingUpdater updater.py
if ($LASTEXITCODE) { throw 'Updater build failed' }
# Ensure the source identity did not change during a successful build.
$finalIdentity = & py -3.12 $identityTool @identityArgs
if ($LASTEXITCODE -or $finalIdentity -cne $identityJson) { throw 'Source identity changed during build' }
$agentDist = Join-Path $PSScriptRoot 'dist\SmartHouseGamingControl'
Set-Content -LiteralPath (Join-Path $agentDist 'version.txt') -Value $identity.version -Encoding ascii
[System.IO.File]::WriteAllText((Join-Path $agentDist 'build-info.json'), $identityJson, [System.Text.UTF8Encoding]::new($false))
Write-Output "Built Windows agent $($identity.version), commit $($identity.commit)"
