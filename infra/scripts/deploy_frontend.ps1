# Deploy frontend lên Amplify Hosting bằng zip thủ công (không nối GitHub).
# Theo nếp build_backend.ps1: dùng .NET ZipFile, xử lý stderr của native command.

$ErrorActionPreference = "Stop"
# CẢ HAI assembly: ZipArchive/ZipArchiveMode nằm ở System.IO.Compression, còn
# ZipFile/ZipFileExtensions ở System.IO.Compression.FileSystem. Thiếu cái đầu là
# lỗi "Unable to find type [System.IO.Compression.ZipArchiveMode]".
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$infra = Split-Path -Parent $PSScriptRoot
$frontend = Resolve-Path (Join-Path $infra "..\frontend")

if (-not (Test-Path (Join-Path $frontend ".env"))) {
    Write-Host "Cảnh báo: chưa có frontend/.env — kiểm tra VITE_COGNITO_* và VITE_API_URL trước khi build" -ForegroundColor Yellow
} else {
    $envContent = Get-Content (Join-Path $frontend ".env") -Raw
    $hasPool = $envContent -match "VITE_COGNITO_USER_POOL_ID\s*=\s*\S+"
    $hasClient = $envContent -match "VITE_COGNITO_CLIENT_ID\s*=\s*\S+"
    $apiMatch = [regex]::Match($envContent, "VITE_API_URL\s*=\s*(\S+)")
    $apiVal = if ($apiMatch.Success) { $apiMatch.Groups[1].Value.Trim('"').Trim("'") } else { "" }
    $isLocal = -not $apiVal -or $apiVal -match "localhost|127\.0\.0\.1"
    if (-not $isLocal -and (-not $hasPool -or -not $hasClient)) {
        Write-Host "Cảnh báo: VITE_API_URL trỏ ra ngoài ($apiVal) mà VITE_COGNITO_* trống — build xong frontend sẽ từ chối khởi động (main.tsx)" -ForegroundColor Yellow
    }
}

Write-Host "== Build frontend ==" -ForegroundColor Cyan
Push-Location $frontend
try {
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
} finally {
    Pop-Location
}

$dist = Join-Path $frontend "dist"
if (-not (Test-Path $dist)) { throw "không tìm thấy $dist — build thất bại?" }

$zip = Join-Path $env:TEMP "frontend-dist.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
Write-Host "== Nén $dist -> $zip ==" -ForegroundColor Cyan

# KHÔNG dùng ZipFile::CreateFromDirectory: trên PS 5.1 (.NET Framework) nó ghi
# đường dẫn bằng '\' (assets\index-abc.js). Amplify giải nén trên Linux nên '\'
# không phải dấu phân cách thư mục -> không có thư mục assets/ -> mọi file JS/CSS
# trả 404 và trang trắng, trong khi deploy vẫn báo thành công. Cùng lỗi đã làm
# chết gói Lambda (§5 CLAUDE.md).
$goc = (Resolve-Path $dist).Path.TrimEnd('\') + '\'
$luong = [System.IO.File]::Open($zip, [System.IO.FileMode]::CreateNew)
$kho = New-Object System.IO.Compression.ZipArchive($luong, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    Get-ChildItem -Path $dist -Recurse -File | ForEach-Object {
        $tenTrongZip = $_.FullName.Substring($goc.Length).Replace('\', '/')
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $kho, $_.FullName, $tenTrongZip, [System.IO.Compression.CompressionLevel]::Optimal) | Out-Null
    }
} finally {
    $kho.Dispose()
    $luong.Dispose()
}

# Kiểm chính file zip, không kiểm thư mục dist.
$doc = [System.IO.Compression.ZipFile]::OpenRead($zip)
try {
    $sai = @($doc.Entries | Where-Object { $_.FullName.Contains('\') }).Count
    $coIndex = @($doc.Entries | Where-Object { $_.FullName -eq 'index.html' }).Count
} finally {
    $doc.Dispose()
}
if ($sai -gt 0) { throw "zip có $sai entry dùng dấu '\' - Amplify (Linux) se tra trang trang" }
if ($coIndex -eq 0) { throw "zip thiếu index.html ở gốc" }
Write-Host ("Đã nén {0:N1} MB, entry dùng '/' hết" -f ((Get-Item $zip).Length / 1MB))

$appId = (& "$infra\bin\terraform.exe" output -raw amplify_app_id 2>$null)
if (-not $appId) { throw "không lấy được amplify_app_id — đã terraform apply chưa?" }

$branch = (& "$infra\bin\terraform.exe" output -raw amplify_branch 2>$null)
if (-not $branch) { $branch = "main" }

Write-Host "== Tạo deployment cho app $appId branch $branch ==" -ForegroundColor Cyan
$prevErr = $ErrorActionPreference
$ErrorActionPreference = "Continue"

$createRaw = aws amplify create-deployment --app-id $appId --branch-name $branch --output json 2>&1 | Out-String
if ($LASTEXITCODE -ne 0) { $ErrorActionPreference = $prevErr; throw "aws amplify create-deployment failed: $createRaw" }
$create = $createRaw | ConvertFrom-Json
$zipUrl = $create.zipUploadUrl
$jobId = $create.jobId
if (-not $zipUrl -or -not $jobId) { $ErrorActionPreference = $prevErr; throw "không lấy được zipUploadUrl/jobId: $createRaw" }

Write-Host "== Upload zip lên presigned URL ==" -ForegroundColor Cyan
$curlArgs = @("--fail", "-X", "PUT", $zipUrl, "--data-binary", "@$zip")
& curl.exe @curlArgs | Out-Null
if ($LASTEXITCODE -ne 0) { $ErrorActionPreference = $prevErr; throw "curl upload failed" }

Write-Host "== Bắt đầu deployment job $jobId ==" -ForegroundColor Cyan
$startRaw = aws amplify start-deployment --app-id $appId --branch-name $branch --job-id $jobId --source-url $zipUrl 2>&1 | Out-String
if ($LASTEXITCODE -ne 0) {
    Write-Host "Thử start-deployment chỉ với --job-id ..." -ForegroundColor Yellow
    $startRaw = aws amplify start-deployment --app-id $appId --branch-name $branch --job-id $jobId 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { $ErrorActionPreference = $prevErr; throw "aws amplify start-deployment failed: $startRaw" }
}
$ErrorActionPreference = $prevErr

Write-Host "Deploy xong. Kiểm tra:" -ForegroundColor Green
aws amplify get-branch --app-id $appId --branch-name $branch --query "branch.displayName" 2>$null
$amplifyUrl = (& "$infra\bin\terraform.exe" output -raw amplify_app_url 2>$null)
Write-Host "Amplify URL: $amplifyUrl" -ForegroundColor Cyan
Write-Host "Xong. Đợi 1-2 phút để Amplify build xong." -ForegroundColor Green
