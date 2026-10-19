$ErrorActionPreference = 'Stop'
$project = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $project
$scratch = Join-Path $project 'artifacts\setup'
New-Item -ItemType Directory -Force -Path (Join-Path $scratch 'tmp') | Out-Null
$env:TMP = Join-Path $scratch 'tmp'
$env:TEMP = $env:TMP
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PIP_CACHE_DIR = Join-Path $scratch 'caches\pip'
$env:npm_config_cache = Join-Path $scratch 'caches\npm'
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) { python -m venv .venv; if ($LASTEXITCODE -ne 0) { throw 'Cannot create Python environment' } }
if (Test-Path -LiteralPath 'requirements.lock') {
    & '.\.venv\Scripts\python.exe' -B -m pip install --no-compile -r requirements.lock
    if ($LASTEXITCODE -ne 0) { throw 'Locked Python installation failed' }
}
& '.\.venv\Scripts\python.exe' -B -m pip install --no-compile -e '.[dev]'
if ($LASTEXITCODE -ne 0) { throw 'Python installation failed' }
if (Test-Path -LiteralPath 'web\package-lock.json') { npm --prefix web ci } else { npm --prefix web install }
if ($LASTEXITCODE -ne 0) { throw 'Frontend installation failed' }
npm --prefix web run build
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
& '.\.venv\Scripts\python.exe' -B -m fittrack.desktop shortcuts
if ($LASTEXITCODE -ne 0) { throw 'Cannot create hidden launch shortcuts' }
Write-Output 'FitTrack ready. Open the first-setup shortcut, then choose a dedicated empty data folder.'
