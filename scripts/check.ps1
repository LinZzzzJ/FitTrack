$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$checkRoot = Join-Path (Get-Location).Path 'artifacts\checks'
New-Item -ItemType Directory -Force -Path (Join-Path $checkRoot 'tmp') | Out-Null
$env:TMP = Join-Path $checkRoot 'tmp'
$env:TEMP = $env:TMP
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:RUFF_CACHE_DIR = Join-Path $checkRoot 'caches\ruff'
$env:npm_config_cache = Join-Path $checkRoot 'caches\npm'
& '.\.venv\Scripts\python.exe' -B -m pytest --basetemp (Join-Path $checkRoot 'pytest') -o "cache_dir=$checkRoot/caches/pytest"
if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed' }
& '.\.venv\Scripts\python.exe' -B -m ruff check src tests scripts
if ($LASTEXITCODE -ne 0) { throw 'Backend lint failed' }
$env:PYTHON_TEST_EXECUTABLE = (Resolve-Path -LiteralPath '.\.venv\Scripts\python.exe').Path
npm --prefix web test
if ($LASTEXITCODE -ne 0) { throw 'Mobile data compatibility tests failed' }
npm --prefix web run check
if ($LASTEXITCODE -ne 0) { throw 'Frontend check failed' }
npm --prefix web run build
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
