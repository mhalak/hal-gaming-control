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
# SignPath requires identical first-party ProductName/ProductVersion resource
# metadata across owned executables. Resources do not sign the executables.
$agentVersionInfo = Join-Path $PSScriptRoot 'build\agent-version.txt'
$updaterVersionInfo = Join-Path $PSScriptRoot 'build\updater-version.txt'
& $python .\version_metadata.py --version $identity.version --filename SmartHouseGamingControl.exe --output $agentVersionInfo
if ($LASTEXITCODE) { throw 'Agent version metadata failed' }
& $python .\version_metadata.py --version $identity.version --filename SmartHouseGamingUpdater.exe --output $updaterVersionInfo
if ($LASTEXITCODE) { throw 'Updater version metadata failed' }
& $python -m PyInstaller --noconfirm --clean --onedir --name SmartHouseGamingControl --version-file $agentVersionInfo --hidden-import win32timezone --hidden-import win32ts --hidden-import win32profile --hidden-import tkinter service_entry.py
if ($LASTEXITCODE) { throw 'Build failed' }
& $python -m PyInstaller --noconfirm --clean --onedir --name SmartHouseGamingUpdater --version-file $updaterVersionInfo updater.py
if ($LASTEXITCODE) { throw 'Updater build failed' }
# Ensure the source identity did not change during a successful build.
$finalIdentity = & py -3.12 $identityTool @identityArgs
if ($LASTEXITCODE -or $finalIdentity -cne $identityJson) { throw 'Source identity changed during build' }
$agentDist = Join-Path $PSScriptRoot 'dist\SmartHouseGamingControl'
Set-Content -LiteralPath (Join-Path $agentDist 'version.txt') -Value $identity.version -Encoding ascii
[System.IO.File]::WriteAllText((Join-Path $agentDist 'build-info.json'), $identityJson, [System.Text.UTF8Encoding]::new($false))
Write-Output "Built Windows agent $($identity.version), commit $($identity.commit)"
