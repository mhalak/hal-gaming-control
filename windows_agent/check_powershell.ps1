param([Parameter(Mandatory)][string]$Path)
$files = if (Test-Path -LiteralPath $Path -PathType Leaf) { @(Get-Item -LiteralPath $Path) } else { @(Get-ChildItem -LiteralPath $Path -Filter '*.ps1' -File -Recurse) }
if (!$files.Count) { Write-Output 'No PowerShell files found'; exit 2 }
$failed = $false
foreach ($file in $files) {
    $tokens = $null; $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$errors)
    foreach ($parseError in $errors) { Write-Output "$($file.FullName): $($parseError.Message)"; $failed = $true }
}
if ($failed) { exit 1 }
Write-Output "Parsed $($files.Count) PowerShell files without errors"
