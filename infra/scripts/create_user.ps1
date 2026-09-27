# Tạo user Cognito bằng CLI bọc sẵn — KHÔNG truyền mật khẩu.
# Cognito tự sinh mật khẩu tạm và gửi email mời (EMAIL).
# Username chính là `actor` hiện trong audit (cognito:username).

param(
    [Parameter(Mandatory = $true)][string]$Username,
    [Parameter(Mandatory = $true)][string]$Email
)

$ErrorActionPreference = "Stop"

$infra = Split-Path -Parent $PSScriptRoot
# "-chdir=$infra" PHẢI trong ngoặc kép: để trần thì PowerShell 5.1 không thay
# giá trị biến, terraform nhận đúng chuỗi '$infra' và báo không tìm thấy thư mục.
$pool = & "$infra\bin\terraform.exe" "-chdir=$infra" output -raw cognito_user_pool_id
if ($LASTEXITCODE -ne 0 -or -not $pool) { throw "không lấy được cognito_user_pool_id — đã apply chưa?" }

& aws cognito-idp admin-create-user `
    --user-pool-id $pool `
    --username $Username `
    --user-attributes Name=email,Value=$Email Name=email_verified,Value=true `
    --desired-delivery-mediums EMAIL
if ($LASTEXITCODE -ne 0) { throw "admin-create-user thất bại cho $Username" }

Write-Host "Đã tạo $Username — kiểm tra email $Email để nhận mật khẩu tạm." -ForegroundColor Green
