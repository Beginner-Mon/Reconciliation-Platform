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
# region: ap-southeast-1
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

## 3. Tạo Document AI processor (thủ công, 2 phút)

1. Vào https://console.cloud.google.com/ai/document-ai/processor-library
2. Chọn **Form Parser** → Create
3. Copy processor ID (dạng `xxxxxxxxxxxxx`) → dán vào `dev.tfvars`

## 4. Điền giá trị vào dev.tfvars

```powershell
Copy-Item dev.tfvars.example dev.tfvars
```

Mở `dev.tfvars`, dán vào 2 chỗ đánh dấu:
- `gcp_project_id` = project ID Google Cloud
- `gcp_docai_processor_id` = processor ID ở bước 3

## 5. Build code backend thành zip

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_backend.ps1
```

Tạo ra `artifacts/backend.zip` (code Python chạy trong Lambda).

## 6. Deploy

```powershell
terraform init
terraform validate                      # kiểm cú pháp, không cần credential
terraform plan -var-file=dev.tfvars     # xem trước thay đổi
terraform apply -var-file=dev.tfvars    # gõ "yes" để triển khai
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

# 2. Xin presigned URL rồi PUT file thẳng lên S3
POST {api_url}/projects/{id}/documents       {"files":[{"file_name":"PO-001.pdf"},{"file_name":"INV-001.pdf"}]}
PUT  {upload_url}                            <nội dung file>

# 3. User chủ động chạy xử lý (chỉ xử lý document CHƯA xử lý)
POST {api_url}/projects/{id}/process         {} | {"document_ids":[...], "force":false}

# 4. Poll tiến độ mỗi 2s
GET  {api_url}/projects/{id}

# 5. Đối chiếu lại bất cứ lúc nào (không đụng AI, không tốn tiền)
POST {api_url}/projects/{id}/reconcile

# 6. Human Review
GET   {api_url}/reconciliations/{reconciliation_id}
PATCH {api_url}/projects/{id}/documents/{document_id}   {"fields":{"vendor":"ABC Technology"}}
POST  {api_url}/reconciliations/{reconciliation_id}/approve
```

Thêm document vào project đã xử lý: lặp lại bước 2 → 3. Bước 3 **chỉ OCR file
mới**, các file cũ được skip (xem `skipped` trong response), rồi đối chiếu lại
trên toàn bộ document của project.

## Xóa hạ tầng (cẩn thận)

```powershell
terraform destroy -var-file=dev.tfvars
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
