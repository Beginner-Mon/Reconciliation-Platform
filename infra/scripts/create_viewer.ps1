# Tạo tài khoản AWS CHỈ để xem dashboard CloudWatch (người hướng dẫn, giảng viên).
# Đăng nhập AWS Console bằng mật khẩu; KHÔNG tạo access key, người xem không cần
# `aws configure`. Quyền nằm ở nhóm IAM do Terraform khai (aws_iam_group.dashboard_viewer);
# script chỉ tạo user, cho vào nhóm và đặt mật khẩu tạm, để mật khẩu không vào tfstate.

param(
    [string]$Username = "dashboard-viewer"
)

$ErrorActionPreference = "Stop"

$infra = Split-Path -Parent $PSScriptRoot
# "-chdir=$infra" PHẢI trong ngoặc kép (xem create_user.ps1).
$group = & "$infra\bin\terraform.exe" "-chdir=$infra" output -raw dashboard_viewer_group
if ($LASTEXITCODE -ne 0 -or -not $group) { throw "không lấy được dashboard_viewer_group — đã apply chưa?" }
$dashboard = & "$infra\bin\terraform.exe" "-chdir=$infra" output -raw dashboard_url
if ($LASTEXITCODE -ne 0 -or -not $dashboard) { throw "không lấy được dashboard_url" }
$account = & aws sts get-caller-identity --query Account --output text
if ($LASTEXITCODE -ne 0 -or -not $account) { throw "không lấy được Account ID — AWS CLI đã đăng nhập chưa?" }

# Mật khẩu tạm 20 ký tự, đủ chữ hoa, chữ thường, số và ký hiệu. Bỏ các ký tự dễ nhầm
# (I, l, O, 0, 1) và các ký tự đặc biệt với dòng lệnh (dấu nháy, $, %, ^, !, &, -, khoảng trắng).
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
function KyTu([string]$tap) {
    $b = New-Object byte[] 4
    $rng.GetBytes($b)
    $tap[[int]([BitConverter]::ToUInt32($b, 0) % [uint32]$tap.Length)]
}
$hoa = "ABCDEFGHJKLMNPQRSTUVWXYZ"
$thuong = "abcdefghijkmnopqrstuvwxyz"
$so = "23456789"
$kyHieu = "@#*_+="
$tatCa = $hoa + $thuong + $so + $kyHieu
$chu = @((KyTu $hoa), (KyTu $thuong), (KyTu $so), (KyTu $kyHieu)) + (1..16 | ForEach-Object { KyTu $tatCa })
$matKhau = -join ($chu | Sort-Object { Get-Random })

& aws iam create-user --user-name $Username | Out-Null
if ($LASTEXITCODE -ne 0) { throw "create-user thất bại cho $Username (đã có user tên này?)" }
& aws iam add-user-to-group --user-name $Username --group-name $group
if ($LASTEXITCODE -ne 0) { throw "add-user-to-group thất bại — gỡ user dở dang: aws iam delete-user --user-name $Username" }
& aws iam create-login-profile --user-name $Username "--password=$matKhau" --password-reset-required | Out-Null
if ($LASTEXITCODE -ne 0) { throw "create-login-profile thất bại — gỡ user dở dang theo infra/README.md §10" }

Write-Host "Đã tạo $Username trong nhóm $group. Không có access key." -ForegroundColor Green
Write-Host ""
Write-Host "Gửi cho người xem (mật khẩu chỉ hiện MỘT lần, đừng lưu vào repo):"
Write-Host "  Link dashboard : $dashboard"
Write-Host "  Account ID     : $account"
Write-Host "  Tên đăng nhập  : $Username"
Write-Host "  Mật khẩu tạm   : $matKhau"
Write-Host "Lần đăng nhập đầu, AWS bắt đổi mật khẩu rồi đưa thẳng vào dashboard."
