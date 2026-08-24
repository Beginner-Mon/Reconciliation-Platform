# IaC — Terraform (AWS + GCP)

## 1. Vì sao Terraform (thay vì CDK)

Stack trải **2 cloud**: AWS (S3, Lambda, DynamoDB, Step Functions, API GW) +
Google (Document AI, Gemini, service account). Provider `google` của Terraform
là first-class; AWS CDK không có construct native cho Google. Một ngôn ngữ (HCL)
quản cả hai cloud.

## 2. Bố cục hiện tại

```
infra/
├── main.tf                      providers (aws, google, random) + gọi module
├── variables.tf / outputs.tf
├── dev.tfvars.example
├── scripts/build_backend.ps1    đóng gói backend.zip
└── modules/
    ├── aws/
    │   ├── main.tf              toàn bộ tài nguyên AWS
    │   ├── statemachine.asl.json  định nghĩa Step Functions (templatefile)
    │   ├── variables.tf / outputs.tf
    └── gcp/                     project + enable API + Document AI + SA
```

## 3. Tài nguyên AWS

### S3
`documents-{env}`: gom hết dưới `projects/{project_id}/`
(`uploads/`, `ocr/`, `extraction/`, `reconciliation/`).
Lifecycle rule dọn multipart upload dở dang sau 3 ngày.
**Không có** S3 event notification — v2 kích hoạt xử lý bằng endpoint, không
bằng event.

### DynamoDB (PAY_PER_REQUEST)
`projects`, `documents` (+ GSI `project_id-index`, `po_number-index`),
`processing_runs`, `reconciliations`, `audit_log` (PK `entity_id`, SK `timestamp`).

### Lambda (Python 3.11) — 10 function, dùng chung 1 zip
| Function | Handler | Timeout | Memory |
|---|---|---|---|
| `api-projects` | `api.handler.projects_handler` | 30 | 512 |
| `api-documents` | `api.handler.documents_handler` | 30 | 512 |
| `api-review` | `api.handler.review_handler` | 30 | 512 |
| `api-process` | `api.handler.process_handler` | 30 | 512 |
| `ocr` | `workers.ocr.lambda_handler` | 600 | 1024 |
| `extract` | `workers.extract.lambda_handler` | 300 | 512 |
| `validate` | `workers.validate.lambda_handler` | 60 | 256 |
| `reconcile` | `workers.reconcile.lambda_handler` | 120 | 512 |
| `mark-failed` | `workers.mark_failed.lambda_handler` | 30 | 256 |
| `mark-run-failed` | `workers.mark_failed.mark_run_failed` | 30 | 256 |

Timeout Lambda khớp với `TimeoutSeconds` của state tương ứng trong ASL.

### Step Functions
Type **STANDARD** (OCR có thể vượt 5 phút; cần exactly-once + execution history).
Định nghĩa ở `statemachine.asl.json`, ARN Lambda inject bằng `templatefile`.

Điểm bắt buộc đúng:
- `MaxConcurrency: 3` — tránh tự bắn quota Document AI/Gemini.
- `Retry` với `RateLimitError` (backoff 2x, `JitterStrategy: FULL`, 4 lần) tách
  khỏi nhóm `Lambda.ServiceException`.
- `Catch` **bên trong** iterator → `MarkOcrFailed`/`MarkExtractFailed`/
  `MarkValidateFailed` → `End` (không throw lên Map), nên 1 document lỗi không
  giết cả run.
- `Catch` toàn cục → `MarkRunFailed`, **bắt buộc** `REMOVE processing_run_id`,
  nếu không project kẹt vĩnh viễn không chạy lại được.

### IAM
Mỗi Lambda `api` một role riêng, quyền cắt theo đúng việc nó làm
(`local.api_functions` trong `main.tf` giữ handler và bộ quyền **cùng một chỗ**):

| Role | dynamodb | s3 | states |
|---|---|---|---|
| `api-projects` | GetItem, Query, **Scan**, PutItem | GetObject | — |
| `api-documents` | GetItem, Query, PutItem, UpdateItem | GetObject, PutObject | — |
| `api-review` | GetItem, Query, PutItem, UpdateItem | GetObject, PutObject | — |
| `api-process` | GetItem, Query, PutItem, UpdateItem | GetObject, PutObject | **StartExecution, DescribeExecution** |

- `states:*` **chỉ** ở `api-process` — đó là quyền tiêu tiền AI, và chỉ
  `api/process.py` gọi tới.
- `dynamodb:Scan` **chỉ** ở `api-projects` — chỉ `list_projects` dùng `scan_table`.
- Không role `api` nào cần Secrets Manager.
- Worker role (`lambda_role`, dùng chung 6 worker): S3 get/put, DynamoDB
  GetItem/PutItem/UpdateItem/Query trên `.../index/*`, Secrets Manager read,
  logs. **Không** có `states:*` lẫn `Scan` — worker không dùng.
- SFN role: `lambda:InvokeFunction` lên đúng 6 worker.

### API Gateway
HTTP API (rẻ, đơn giản) — **chưa có auth** (giới hạn cố ý của POC). CORS mở cho
frontend. 12 route, mỗi route trỏ tới **một trong 4 integration** theo bảng
`local.api_routes`:

```
projects    POST   /projects
            GET    /projects
            GET    /projects/{project_id}

documents   POST   /projects/{project_id}/documents
            GET    /projects/{project_id}/documents
            GET    /projects/{project_id}/documents/{document_id}/ocr

review      POST   /projects/{project_id}/reconcile
            PATCH  /projects/{project_id}/documents/{document_id}
            GET    /reconciliations/{reconciliation_id}
            POST   /reconciliations/{reconciliation_id}/approve
            POST   /reconciliations/{reconciliation_id}/reject

process     POST   /projects/{project_id}/process
```

Bảng này nằm ở hai nơi — `local.api_routes` và 4 danh sách trong
`api/handler.py` — nên `backend/tests/test_routes.py` đọc thẳng `main.tf` và
khoá lại. Lệch một bên là 404 rất khó truy.

## 4. Google (GCP)

Enable API `documentai.googleapis.com`, `generativelanguage.googleapis.com`.
Document AI: processor **Form Parser** (tiếng Việt dùng generic, KHÔNG dùng
specialized Invoice/PO Parser vì không hỗ trợ tiếng Việt).
Service account quyền tối thiểu, key → `aws_secretsmanager_secret`.

## 5. Đóng gói backend

`scripts/build_backend.ps1` cài dependency runtime (`requirements.txt`, KHÔNG
gồm pytest/moto ở `requirements-dev.txt`), copy `schemas/ core/ common/
workers/ api/`, xoá `__pycache__`, nén thành `artifacts/backend.zip`.

## 6. Lưu ý

- Không commit secret thật; `dev.tfvars`, `*.tfstate`, `artifacts/`, `build/`
  đã gitignore.
- Version pin provider (AWS ~> 5.x, Google ~> 6.x, Random ~> 3.6).
- Remote state: S3 backend + DynamoDB lock (tạo thủ công lần đầu) — chưa cấu hình.
- **Chưa có**: Cognito/auth, WebSocket API, EventBridge (progress dùng polling).

## 7. Thứ tự triển khai

1. GCP: project, enable API, Document AI processor, SA + key.
2. Spike test thủ công trên 5–10 file tiếng Việt → chốt chất lượng OCR/extract.
3. `build_backend.ps1` → `terraform init` → `plan` → `apply`.
4. Chạy kịch bản end-to-end ở `infra/README.md` mục 7.
5. Frontend hosting: S3 + CloudFront (chưa làm).
