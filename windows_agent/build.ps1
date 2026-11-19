param([string]$Version = '0.2.1')
$ErrorActionPreference = 'Stop'
if ($Version -notmatch '^(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})$') { throw 'Invalid version' }
Set-Location $PSScriptRoot
py -3.12 -m venv .venv
if ($LASTEXITCODE) { throw 'venv failed' }
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $python -m pip install -r requirements-dev.txt 'pyinstaller>=6,<7'
if ($LASTEXITCODE) { throw 'Dependency installation failed' }
& $python -m pytest -q
if ($LASTEXITCODE) { throw 'Tests failed' }
& $python -m PyInstaller --noconfirm --clean --onedir --name SmartHouseGamingControl --hidden-import win32timezone --hidden-import win32ts --hidden-import win32profile service_entry.py
if ($LASTEXITCODE) { throw 'Build failed' }
Set-Content -Path (Join-Path $PSScriptRoot 'dist\SmartHouseGamingControl\version.txt') -Value $Version -Encoding ascii
& $python -m PyInstaller --noconfirm --clean --onedir --name SmartHouseGamingUpdater updater.py
if ($LASTEXITCODE) { throw 'Updater build failed' }
