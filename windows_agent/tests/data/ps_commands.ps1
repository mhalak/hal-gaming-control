param([Parameter(Mandatory)][string]$File)
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($File, [ref]$tokens, [ref]$errors)
$commands = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.CommandAst] }, $true) |
    Where-Object {
        $p = $_.Parent; $inside = $false
        while ($p) { if ($p -is [System.Management.Automation.Language.FunctionDefinitionAst]) { $inside = $true; break }; $p = $p.Parent }
        -not $inside
    } | ForEach-Object { $_.GetCommandName() }
@($commands) | ConvertTo-Json -Compress
