$ErrorActionPreference = "Stop"

$infra    = Split-Path -Parent $PSScriptRoot
$backend  = Join-Path $infra "..\backend"
$artifacts = Join-Path $infra "artifacts"
$buildDir = Join-Path $infra "build"

if (Test-Path $buildDir) { Remove-Item -Recurse -Force $buildDir }
if (-not (Test-Path $artifacts)) { New-Item -ItemType Directory -Path $artifacts | Out-Null }
New-Item -ItemType Directory -Path $buildDir | Out-Null

$python = Join-Path $backend ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

& $python -m pip install -r (Join-Path $backend "requirements.txt") `
    --target $buildDir `
    --platform manylinux2014_x86_64 `
    --implementation cp `
    --python-version 311 `
    --only-binary=:all: `
    --upgrade --quiet
if ($LASTEXITCODE -ne 0) { throw "pip install fail" }

foreach ($dir in @("schemas", "core", "common", "workers", "api")) {
    Copy-Item (Join-Path $backend $dir) $buildDir -Recurse -Force
}

Get-ChildItem -Path $buildDir -Recurse -Directory -Filter "__pycache__" |
    Remove-Item -Recurse -Force

$zipPath = Join-Path $artifacts "backend.zip"
if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
Compress-Archive -Path (Join-Path $buildDir "*") -DestinationPath $zipPath -Force

Write-Host "OK: $zipPath"
