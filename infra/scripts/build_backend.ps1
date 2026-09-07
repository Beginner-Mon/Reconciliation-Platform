# Dựng MỘT gói riêng cho MỖI Lambda.
#
# Bảng gói nằm ở backend/packaging.py — một nguồn duy nhất, và
# backend/tests/test_packaging.py khoá nó khớp với local.workers +
# local.api_functions bên main.tf.
#
# Moi goi chi chep module no THAT SU chay (khoa `modules`) va thu vien no that
# su can (khoa `requires`). boto3 khong vao goi nao vi runtime python3.11 cua
# Lambda da cap san.
#
# Dựng xong mỗi gói đều được KIỂM: nạp thử `phai_import_duoc` với sys.path chỉ
# có đúng thư mục vừa dựng. Thiếu thư viện thì hỏng ở đây, không phải lúc chạy
# thật trên Lambda — đặc biệt cần với import lười (Google nằm trong thân hàm ở
# common/ai_clients.py) vì import module handler thôi không phát hiện được.

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.IO.Compression.FileSystem

$infra     = Split-Path -Parent $PSScriptRoot
$backend   = Resolve-Path (Join-Path $infra "..\backend")
$artifacts = Join-Path $infra "artifacts"
$build     = Join-Path $infra "build"

$python = Join-Path $backend ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

if (Test-Path $build) { Remove-Item -Recurse -Force $build }
New-Item -ItemType Directory -Path $build | Out-Null
if (-not (Test-Path $artifacts)) { New-Item -ItemType Directory -Path $artifacts | Out-Null }

# Đọc bảng gói từ Python — KHÔNG chép lại sang PowerShell.
$json = & $python -c @"
import json, sys
sys.path.insert(0, r'$backend')
from packaging import PACKAGES
print(json.dumps({'packages': PACKAGES}))
"@
if ($LASTEXITCODE -ne 0) { throw "khong doc duoc backend/packaging.py" }
$manifest = $json | ConvertFrom-Json

# Nhiều function dùng chung một bộ thư viện (6 cái chỉ cần pydantic). Cài một
# lần cho mỗi BỘ rồi chép lại — nếu không phải chạy pip 10 lần cho 4 bộ khác nhau.
$caches = @{}

function Get-DepsCache([string[]] $requires) {
    $key = ($requires | Sort-Object) -join " "
    if ($caches.ContainsKey($key)) { return $caches[$key] }

    $dir = Join-Path $build ("deps-" + [Math]::Abs($key.GetHashCode()))
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    if ($requires.Count -gt 0) {
        & $python -m pip install @requires `
            --target $dir `
            --platform manylinux2014_x86_64 `
            --implementation cp `
            --python-version 311 `
            --only-binary=:all: `
            --disable-pip-version-check `
            --upgrade --quiet
        if ($LASTEXITCODE -ne 0) { throw "pip install fail: $key" }
    }
    $caches[$key] = $dir
    return $dir
}

$tong = 0
$ketQua = @()

foreach ($ten in ($manifest.packages | Get-Member -MemberType NoteProperty | Select-Object -ExpandProperty Name | Sort-Object)) {
    $spec = $manifest.packages.$ten
    $requires = @($spec.requires)

    $stage = Join-Path $build $ten
    New-Item -ItemType Directory -Path $stage -Force | Out-Null

    $deps = Get-DepsCache $requires
    Get-ChildItem -Path $deps -Force | Copy-Item -Destination $stage -Recurse -Force

    # CHI chep module goi nay that su chay — khong chep het nhu truoc.
    foreach ($mod in $spec.modules) {
        Copy-Item (Join-Path $backend $mod) $stage -Recurse -Force
    }
    Get-ChildItem -Path $stage -Recurse -Directory -Filter "__pycache__" |
        Remove-Item -Recurse -Force

    # KIEM truoc khi dong goi: nhung module da khai co mat chua.
    #
    # Kiem SU HIEN DIEN chu khong nap thu — wheel cai bang --platform
    # manylinux2014 chua phan bien dich cho Linux (pydantic_core._pydantic_core),
    # nap tren Windows la chet du goi hoan toan dung cho Lambda.
    $mods = ($spec.phai_co_module) -join " "
    & $python -c @"
import pathlib, sys
goc = pathlib.Path(r'$stage')
thieu = []
for ten in '$mods'.split():
    duong = goc.joinpath(*ten.split('.'))
    if not (duong.is_dir() or duong.with_suffix('.py').is_file()):
        thieu.append(ten)
if thieu:
    print('THIEU: ' + ', '.join(thieu)); sys.exit(1)
"@
    if ($LASTEXITCODE -ne 0) { throw "goi '$ten' thieu module (khai trong packaging.py)" }

    # Dung .NET chu khong Compress-Archive: cmdlet do cham, va tren PS 5.1 hay
    # dinh loi "file is being used by another process" khi antivirus dang quet
    # dong file vua chep ra.
    $zip = Join-Path $artifacts "$ten.zip"
    if (Test-Path $zip) { Remove-Item -Force $zip }
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $stage, $zip, [System.IO.Compression.CompressionLevel]::Optimal, $false)

    $mb = [Math]::Round((Get-Item $zip).Length / 1MB, 1)
    $tong += $mb
    $ketQua += [PSCustomObject]@{
        Lambda   = $ten
        MB       = $mb
        Modules  = ($spec.modules -join " ")
        Requires = ($requires -join ", ")
    }
}

$ketQua | Format-Table -AutoSize
Write-Host ("TONG {0} goi = {1} MB (truoc khi tach: 10 x 34 MB = 340 MB)" -f $ketQua.Count, [Math]::Round($tong, 1))
