# Hướng dẫn deploy bằng Terraform

## 1. Cài công cụ (một lần)

Terraform **không** cài được vào `.venv` của backend (`.venv` chỉ chứa package
PyPI; terraform là binary Go). Giữ cục bộ trong project bằng cách tải binary vào
`infra/bin/` — không cần quyền admin, không đụng hệ thống, đã gitignore:

```powershell
cd infra
New-Item -ItemType Directory -Force bin | Out-Null
$v = "1.15.8"
Invoke-WebRequest "https://releases.hashicorp.com/terraform/$v/terraform_${v}_windows_amd64.zip" -OutFile bin\tf.zip
# đối chiếu SHA256 với https://releases.hashicorp.com/terraform/$v/terraform_${v}_SHA256SUMS
Expand-Archive bin\tf.zip -DestinationPath bin -Force
Remove-Item bin\tf.zip
.\bin\terraform.exe version
```

Muốn cài toàn máy thì `choco install terraform -y` hoặc
`winget install HashiCorp.Terraform`. AWS CLI và gcloud SDK vẫn cài toàn máy.

Từ đây trở xuống, thay `terraform` bằng `.\bin\terraform.exe` nếu dùng cách cục bộ.

## 2. Dán credential

### AWS (dùng CLI, không dán vào file)
```powershell
aws configure
# AWS Access Key ID: <dán key tạo ở IAM>
# AWS Secret Access Key: <dán secret>
# region: us-east-1   (khớp aws_region trong tfvars và stack bootstrap)
```

### Google Cloud (chọn 1 trong 2 cách)
Cách A — đăng nhập bằng CLI:
```powershell
gcloud auth application-default login
```

Cách B — dùng file service account key JSON:
tạo ở GCP Console → IAM & Admin → Service Accounts → Keys → Add Key → JSON,
rồi điền đường dẫn file vào `dev.tfvars`:
```hcl
gcp_credentials_file = "C:/path/to/key.json"
```

### Gemini API key (bắt buộc, miễn phí)
Vào https://aistudio.google.com/apikey → Create API key → dán vào `dev.tfvars`:
```hcl
gemini_api_key = "AIza..."
```

## 3. Việc thủ công bên Google (một lần)

Terraform **cố ý không** bật API và **không** gán quyền trên GCP: hai việc đó đòi
`Service Usage Admin` và `Project IAM Admin`, mà ai có `Project IAM Admin` thì tự
gán được Owner cho chính mình. Đổi lại vài cú bấm dưới đây, tài khoản chạy
Terraform chỉ cần **Service Account Admin + Service Account Key Admin**.

**3.1 Tạo Document AI processor**
1. Vào https://console.cloud.google.com/ai/document-ai/processor-library
2. Chọn **Document OCR** → Create → copy processor ID → `gcp_docai_ocr_processor_id`
   (thêm **Form Parser** nếu cần đo bằng `evaluation/` → `gcp_docai_processor_id`)

**3.2 Bật API cho project** (Console → APIs & Services → Library → Enable)
`documentai.googleapis.com` · `iam.googleapis.com` ·
`cloudresourcemanager.googleapis.com` · `serviceusage.googleapis.com`

**3.3 Cấp quyền cho tài khoản chạy Terraform** (Console → IAM & Admin → IAM):
`Service Account Admin` + `Service Account Key Admin`. **Không** cấp
`Project IAM Admin`.

**3.4 SAU khi `apply` xong**: gán `roles/documentai.apiUser` cho service account
mà Terraform vừa tạo (`recon-lambda-<env>@<project>.iam.gserviceaccount.com`).
Thiếu bước này thì engine `dococr` trả 403 lúc gọi Document AI.
**Không** cần `roles/aiplatform.user` — Gemini dùng API key, không dùng service
account này.

## 4. Điền giá trị vào dev.tfvars

```powershell
Copy-Item dev.tfvars.example dev.tfvars
```

Mở `dev.tfvars`, dán vào các chỗ đánh dấu:
- `gcp_project_id` = project ID Google Cloud
- `gcp_docai_ocr_processor_id` = ID của processor **Document OCR** tạo ở bước 3.1
- `gemini_api_key` = key lấy ở bước 2

## 5. Build code backend thành zip

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_backend.ps1
```

Tạo ra 11 file `artifacts/<tên function>.zip` — mỗi Lambda một gói riêng, chỉ
chứa thư viện nó cần. `boto3` không nằm trong gói nào vì runtime Lambda đã có.

## 5b. State remote (bắt buộc trước deploy prod)

State chứa private key Google và Gemini key nên **không để local**:

```powershell
cd infra\bootstrap
..\bin\terraform.exe init
..\bin\terraform.exe apply              # copy output backend_hcl thành infra\backend.hcl
cd ..
.\bin\terraform.exe init -reconfigure "-backend-config=backend.hcl"
```

Tham số có dấu chấm **phải bọc nháy** như trên. PowerShell 5.1 cắt
`-var-file=prod.tfvars` thành `-var-file=prod` và `.tfvars`, terraform báo
"Too many command line arguments".

`prod.tfvars` copy từ `dev.tfvars`, đổi `env = "prod"`.

## 6. Deploy

```powershell
terraform init -reconfigure "-backend-config=backend.hcl"
terraform validate                        # kiểm cú pháp, không cần credential
terraform plan "-var-file=prod.tfvars"    # xem trước thay đổi
terraform apply "-var-file=prod.tfvars"   # gõ "yes" để triển khai
```

Trước khi apply, nên kiểm luồng Step Functions mà **không cần deploy** — xem
`statemachine-test/README.md` (2 mức: validate định nghĩa qua AWS API miễn phí,
và chạy thật luồng với Lambda mock bằng Step Functions Local; **không cần Docker**).

## 7. Kiểm tra

```powershell
terraform output api_url
```

Luồng đầy đủ (upload và xử lý là **hai bước riêng**, user chủ động bấm xử lý):

```powershell
$api = terraform output -raw api_url

# 1. Tạo project
POST {api_url}/projects                      {"name": "Gói thầu A"}

# 2. Xin presigned POST rồi gửi form thẳng lên S3 (KHÔNG phải PUT)
POST {api_url}/projects/{id}/documents       {"files":[{"file_name":"PO-001.pdf"},{"file_name":"INV-001.pdf"}]}
#    -> mỗi file trả về upload.url và upload.fields
POST {upload.url}                            multipart/form-data: mọi trường trong upload.fields TRƯỚC, `file` SAU CÙNG

# 3. User chủ động chạy xử lý (chỉ xử lý document CHƯA xử lý)
POST {api_url}/projects/{id}/process         {} | {"document_ids":[...], "force":false}

# 4. Poll tiến độ mỗi 2s
GET  {api_url}/projects/{id}

# 5. Đối chiếu lại bất cứ lúc nào (không đụng AI, không tốn tiền)
POST {api_url}/projects/{id}/reconcile

# 6. Human Review
GET   {api_url}/reconciliations/{reconciliation_id}
PATCH {api_url}/projects/{id}/documents/{document_id}   {"fields":{"seller":"ABC Technology"}}
#     PATCH không tự đối chiếu: kết quả cũ thành is_stale, phải đối chiếu lại rồi mới duyệt được
POST  {api_url}/projects/{id}/reconcile
POST  {api_url}/reconciliations/{reconciliation_id mới}/review   {"decision":"APPROVED"}
```

Thêm document vào project đã xử lý: lặp lại bước 2 → 3. Bước 3 **chỉ OCR file
mới**, các file cũ được skip (xem `skipped` trong response), rồi đối chiếu lại
trên toàn bộ document của project.

## 8. Frontend — Amplify Hosting (deploy thủ công)

Frontend **không nối GitHub** (token sẽ nằm trong tfstate local chưa mã hoá). Deploy bằng zip:

```powershell
# 1. Điền VITE_... vào frontend/.env (lấy từ terraform output)
terraform output -raw cognito_user_pool_id   # -> VITE_COGNITO_USER_POOL_ID
terraform output -raw cognito_client_id     # -> VITE_COGNITO_CLIENT_ID
terraform output -raw api_url               # -> VITE_API_URL

# 2. Build + upload
powershell -ExecutionPolicy Bypass -File .\scripts\deploy_frontend.ps1
# hoặc thủ công:
# cd ..\frontend; npm run build; cd ..\infra
# aws amplify create-deployment --app-id <amplify_app_id> --branch-name main
# aws amplify start-deployment ...
terraform output -raw amplify_app_url       # kiểm tra
```

## 9. Tạo tài khoản (Cognito)

Tài khoản **chỉ tạo bằng script**, không qua Terraform (mật khẩu sẽ vào tfstate).
Script không cầm mật khẩu — Cognito tự sinh mật khẩu tạm và gửi email mời:

```powershell
.\scripts\create_user.ps1 -Username tri -Email tri@example.com

# Lần đầu đăng nhập sẽ bị bắt đổi mật khẩu (NEW_PASSWORD_REQUIRED) — LoginGate đã xử lý.
```

## 10. Tài khoản chỉ xem dashboard (IAM)

Dành cho người hướng dẫn, giảng viên: đăng nhập AWS Console bằng mật khẩu và chỉ mở
được dashboard `recon-prod`. **Không có access key**, người xem không cần `aws configure`.

Quyền nằm ở nhóm IAM `recon-dashboard-viewer-prod` do Terraform khai
(`aws_iam_group.dashboard_viewer`). User và mật khẩu tạo bằng script để mật khẩu
không vào tfstate:

```powershell
.\scripts\create_viewer.ps1                          # tên mặc định: dashboard-viewer
.\scripts\create_viewer.ps1 -Username ten-nguoi-xem
```

Script in ra link dashboard, Account ID, tên đăng nhập và mật khẩu tạm (chỉ hiện một
lần). Người xem mở link dashboard → trang đăng nhập hỏi Account ID, tên, mật khẩu →
AWS bắt đổi mật khẩu ở lần đầu → vào thẳng dashboard.

| Được | Không được |
|---|---|
| Xem dashboard `recon-prod` | Sửa, xoá dashboard |
| Chạy Logs Insights trên 11 log group của hệ thống (ba ô log của dashboard) | Đọc log của dự án khác; xem từng dòng log, liệt kê log group |
| Đọc số đo (metric) | S3, DynamoDB, Lambda, Step Functions, IAM |
| Đổi mật khẩu của chính mình | Tạo access key |

`cloudwatch:GetMetricData`, `ListMetrics`, `ListDashboards` và `logs:GetQueryResults`,
`StopQuery` không giới hạn được theo tài nguyên (AWS chỉ nhận `*`): người xem thấy được
**số đo** của cả tài khoản AWS nếu tự tìm, nhưng không thấy nội dung log.

Gỡ người xem:

```powershell
aws iam delete-login-profile --user-name dashboard-viewer
aws iam remove-user-from-group --user-name dashboard-viewer --group-name recon-dashboard-viewer-prod
aws iam delete-user --user-name dashboard-viewer
```

## Xóa hạ tầng (cẩn thận)

Có tài khoản xem dashboard (§10) thì gỡ trước: nhóm IAM còn thành viên thì Terraform
không xoá được.

```powershell
terraform destroy "-var-file=dev.tfvars"
```

## Lưu ý

- `dev.tfvars`, `*.tfstate`, `artifacts/`, `build/` đã gitignore — không commit.
- Bảng DynamoDB dùng PAY_PER_REQUEST — không tốn phí khi idle.
- Document AI online giới hạn ~15 trang / 20MB mỗi file. `/process` từ chối sớm
  file vượt 20MB bằng `head_object` trước khi tốn tiền AI.
- Step Functions dùng loại **STANDARD**; `/process` đặt execution name = `run_id`
  nên gọi trùng không tạo execution thừa.
- Step Functions **không** chờ Human Review — execution kết thúc ở
  `AWAITING_REVIEW`, review chạy qua API độc lập.
