param([Parameter(Mandatory=$true)][string]$DataRoot)
$ErrorActionPreference = 'Stop'
$project = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
& (Join-Path $project '.venv\Scripts\python.exe') -B -m fittrack --data-root $DataRoot --stop
if ($LASTEXITCODE -ne 0) { throw 'FitTrack could not stop. Check the selected data root.' }
