param(
    [Parameter(Mandatory=$true)][string]$BuildRoot,
    [Parameter(Mandatory=$true)][string]$BootstrapPython
)
$ErrorActionPreference = 'Stop'
$project = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not [IO.Path]::IsPathRooted($BuildRoot)) { throw 'BuildRoot must be absolute' }
$build = [IO.Path]::GetFullPath($BuildRoot)
$downloads = Join-Path $build 'downloads'
$runtime = Join-Path $build 'cpython'
$scratch = Join-Path $build 'tmp'
New-Item -ItemType Directory -Force -Path $downloads,$runtime,$scratch | Out-Null
$env:TMP = $scratch
$env:TEMP = $scratch
$env:PIP_CACHE_DIR = Join-Path $build 'pip-cache'
$env:PYTHONDONTWRITEBYTECODE = '1'
$archive = Join-Path $downloads 'python-3.13.16-embed-amd64.zip'
if (-not (Test-Path -LiteralPath $archive)) {
    Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.13.16/python-3.13.16-embed-amd64.zip' -OutFile $archive
}
$digest = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($digest -ne '97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297') { throw 'Official runtime archive checksum mismatch' }
Expand-Archive -LiteralPath $archive -DestinationPath $runtime -Force
[IO.File]::WriteAllText((Join-Path $runtime 'python313._pth'), "python313.zip`n.`nLib/site-packages`nimport site`n", [Text.Encoding]::ASCII)
& $BootstrapPython -B -m pip --python (Join-Path $runtime 'python.exe') install --only-binary=:all: --no-compile -r (Join-Path $project 'requirements-runtime.lock') -r (Join-Path $project 'requirements-build.lock')
if ($LASTEXITCODE -ne 0) { throw 'Release dependency installation failed' }
Write-Output ('Build interpreter: ' + (Join-Path $runtime 'python.exe'))
