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
├── scripts/build_backend.ps1    đóng gói 11 zip, mỗi Lambda một gói
├── scripts/deploy_frontend.ps1  build frontend rồi đẩy zip lên Amplify
├── scripts/create_user.ps1      tạo tài khoản Cognito
├── bootstrap/                   stack riêng tạo bucket chứa state
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
`processing_runs`, `reconciliations`.

> Audit là dòng JSON trong CloudWatch Logs (11 log group giữ 10 năm theo biến
> `log_retention_days`, + 1 dashboard).
> Thiết kế và lý do: `observability.md`.

### Lambda (Python 3.11) — 11 function, **mỗi cái một zip riêng**

Bảng gói ở `backend/packaging.py`; mỗi gói khai `modules` (chỉ chép code nó
chạy) và `requires` (chỉ cài thư viện nó cần). `boto3` không nằm trong gói nào —
runtime Lambda đã có. Lúc còn 10 gói đo được 340 MB → 39,6 MB. Đo lại
2026-10-07 với 11 gói: tổng **42,2 MB**; `ocr` 14,2 · `extract` 10,4 · năm
`api-*` mỗi gói 2,5 · `validate` và `reconcile` mỗi gói 2,5 · hai `mark-*` mỗi
gói 0,03.

| Function | Handler | Timeout | Memory |
|---|---|---|---|
| `api-projects` | `api.handler.projects_handler` | 30 | 512 |
| `api-documents` | `api.handler.documents_handler` | 30 | 512 |
| `api-review` | `api.handler.review_handler` | 30 | 512 |
| `api-process` | `api.handler.process_handler` | 30 | 512 |
| `api-anchor` | `api.handler.anchor_handler` | 30 | 512 |
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

| Role | dynamodb | s3 | states | lambda:InvokeFunction |
|---|---|---|---|---|
| `api-projects` | GetItem, Query, **Scan**, PutItem, UpdateItem, DeleteItem | GetObject, DeleteObject, **ListBucket** (prefix `projects/*`) | — | — |
| `api-documents` | GetItem, Query, PutItem, UpdateItem, DeleteItem | GetObject, PutObject, DeleteObject | — | **reconcile** |
| `api-review` | GetItem, Query, PutItem, UpdateItem | GetObject | — | **reconcile** |
| `api-process` | GetItem, Query, PutItem, UpdateItem | GetObject | **StartExecution, DescribeExecution** | **reconcile** |
| `api-anchor` | GetItem, Query, UpdateItem | GetObject | — | **reconcile** |

- `states:*` **chỉ** ở `api-process` — đó là quyền tiêu tiền AI, và chỉ
  `api/process.py` gọi tới.
- `dynamodb:Scan` **chỉ** ở `api-projects` — `list_projects` quét bảng projects, `delete_project` quét `processing_runs` và `reconciliations` theo `project_id`.
- Không role `api` nào cần Secrets Manager.
- Worker role (`lambda_role`, dùng chung 6 worker): S3 get/put, DynamoDB
  GetItem/PutItem/UpdateItem/Query trên `.../index/*`, Secrets Manager read,
  logs. **Không** có `states:*` lẫn `Scan` — worker không dùng.
- SFN role: `lambda:InvokeFunction` lên đúng 6 worker.

### API Gateway
HTTP API (rẻ, đơn giản) — **có auth** (Cognito JWT authorizer, `authorization_type=JWT` trên cả 15 route; `allow_headers` gồm `authorization`). CORS mở cho
frontend (`local.cors_origins` gồm `var.frontend_origins` + Amplify URL). 15 route, mỗi route trỏ tới **một trong 5 integration** theo bảng
`local.api_routes`:

```
projects    POST   /projects
            GET    /projects
            GET    /projects/{project_id}
            DELETE /projects/{project_id}

documents   POST   /projects/{project_id}/documents
            GET    /projects/{project_id}/documents
            GET    /projects/{project_id}/documents/{document_id}/ocr
            DELETE /projects/{project_id}/documents/{document_id}

review      POST   /projects/{project_id}/reconcile
            PATCH  /projects/{project_id}/documents/{document_id}
            GET    /reconciliations/{reconciliation_id}
            POST   /reconciliations/{reconciliation_id}/review

anchor      PUT    /projects/{project_id}/anchor

process     POST   /projects/{project_id}/process
            POST   /projects/{project_id}/process/stop
```

Bảng này nằm ở hai nơi — `local.api_routes` và 5 danh sách trong
`api/handler.py` — nên `backend/tests/test_routes.py` đọc thẳng `main.tf` và
khoá lại. Lệch một bên là 404 rất khó truy.

## 4. Google (GCP)

Document AI: processor generic (tiếng Việt KHÔNG dùng được specialized Invoice/PO
Parser). Terraform chỉ tạo **service account + key**, key → `aws_secretsmanager_secret`.

Bật API và gán `roles/documentai.apiUser` là **thao tác tay một lần**
(`infra/README.md` §3) — cố ý, vì để Terraform làm thì tài khoản chạy nó phải có
`Service Usage Admin` và `Project IAM Admin`; vai trò thứ hai cho phép tự gán
Owner. Tài khoản chạy Terraform chỉ cần Service Account Admin + Key Admin.

## 5. Đóng gói backend

`scripts/build_backend.ps1` cài dependency runtime (`requirements.txt`, KHÔNG
gồm pytest/moto ở `requirements-dev.txt`), copy `schemas/ core/ common/
workers/ api/`, xoá `__pycache__`, nén thành `artifacts/<tên function>.zip` —
mỗi Lambda MỘT gói, chỉ chứa thư viện chính nó cần (bảng ở `backend/packaging.py`).

## 6. Lưu ý

- Không commit secret thật; `dev.tfvars`, `*.tfstate`, `artifacts/`, `build/`,
  `backend.hcl` đã gitignore.
- Version pin provider (AWS ~> 5.x, Google ~> 6.x, Random ~> 3.6).
- Remote state: S3 backend + khoá file S3 (`use_lockfile`, không dùng DynamoDB đã
  deprecated) — bucket tạo bằng stack `infra/bootstrap/` riêng, state bootstrap
  để local. 4 bảng DynamoDB bật PITR; bucket chứng từ bật versioning, bản cũ
  hết hạn sau 30 ngày.
- **Chưa có**: WebSocket API, EventBridge (progress dùng polling). **Đã có**: Cognito User Pool + JWT authorizer (chỉ bypass khi `VITE_API_URL` localhost và thiếu `VITE_COGNITO_*`).

## 7. Thứ tự triển khai

1. GCP: project, enable API, Document AI processor, SA + key.
2. Spike test thủ công trên 5–10 file tiếng Việt → chốt chất lượng OCR/extract.
3. `build_backend.ps1` → `terraform init` → `plan` → `apply`.
4. Chạy kịch bản end-to-end ở `infra/README.md` mục 7.
5. Frontend hosting: **Amplify Hosting** (deploy thủ công bằng zip, không nối GitHub). Xem `infra/scripts/deploy_frontend.ps1`.
