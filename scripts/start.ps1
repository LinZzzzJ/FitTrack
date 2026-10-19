param([string]$DataRoot, [int]$Port = 8788, [switch]$NoBrowser, [switch]$Foreground)
$ErrorActionPreference = 'Stop'
$project = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonName = if ($Foreground) { 'python.exe' } else { 'pythonw.exe' }
$pythonPath = Join-Path $project ".venv\Scripts\$pythonName"
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run scripts/setup.ps1 first.' }
$fittrackArgs = @('-B', '-m', 'fittrack', '--port', "$Port")
if ($DataRoot) { $fittrackArgs += @('--data-root', $DataRoot) }
if ($NoBrowser) { $fittrackArgs += '--no-browser' }
if ($Foreground) {
    & $pythonPath @fittrackArgs
    if ($LASTEXITCODE -ne 0) { throw 'FitTrack failed. Check the selected data root.' }
} else {
    $fittrackArgs += '--background'
    # Windows Start-Process joins the argument list: quote every argument explicitly.
    $escaped = $fittrackArgs | ForEach-Object {
        $inner = [regex]::Replace($_, '(\\*)"', '$1$1\"')
        '"' + [regex]::Replace($inner, '(\\+)$', '$1$1') + '"'
    }
    Start-Process -FilePath $pythonPath -ArgumentList $escaped -WorkingDirectory $project -WindowStyle Hidden
}
