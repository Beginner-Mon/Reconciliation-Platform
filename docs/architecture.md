# Architecture — AI Document Intelligence & Reconciliation Platform (v2)

## 1. Tổng quan

Hệ thống serverless (AWS) cho phép upload chứng từ doanh nghiệp **tiếng Việt**
(PDF/image) theo **project**, chạy OCR + AI extraction (Google Cloud), validate,
đối chiếu chéo nhiều chứng từ và Human Review trước khi chốt kết quả.

## 2. Ba khái niệm tách biệt

Đây là điểm cốt lõi của v2 và là thứ phân biệt nó với v1:

| Khái niệm | Vòng đời | Ghi chú |
|---|---|---|
| **Project** | Sống lâu dài | Chứa N document, được bồi thêm theo thời gian |
| **Processing Run** | Một lần chạy | OCR/Extract/Validate cho các document **chưa xử lý** |
| **Reconciliation** | Một lần đối chiếu | Chạy trên toàn bộ document đã xử lý của project |

Hệ quả bắt buộc:

> Xử lý per-document là **idempotent, cache được**.
> Đối chiếu là thao tác **project-level, chạy lại được độc lập**.

Vì thế thêm 1 biên bản nghiệm thu vào project đã xử lý sẽ **chỉ OCR file mới**,
không chạy lại các file cũ. Đây là yêu cầu nghiệp vụ, không phải tối ưu.

## 3. Ba endpoint, ba lifecycle

```
[1] POST /projects/{id}/documents   -> N presigned PUT URL
       frontend PUT thẳng lên S3, Lambda không cầm raw file

[2] POST /projects/{id}/process     -> user CHỦ ĐỘNG bấm
       verify head_object + size
       -> conditional claim project.processing_run_id (chống double-start)
       -> StartExecution(name = run_id)
       -> Map(MaxConcurrency 3): Ocr -> Extract -> Validate, Catch per-document
       -> Reconcile
       doc đã VALIDATED => BỎ QUA

[3] POST /projects/{id}/reconcile   -> đối chiếu lại, deterministic, KHÔNG đụng AI

[4] Human Review (API độc lập, KHÔNG nằm trong Step Functions)
       GET   /projects/{id}                              poll 2s
       PATCH /projects/{id}/documents/{doc_id}           sửa tay -> tự đối chiếu lại
       POST  /reconciliations/{id}/approve | /reject
```

## 4. Vì sao dùng Step Functions (đảo ngược quyết định của v1)

v1 lập luận không cần Step Functions vì đơn vị xử lý là 1 document và S3 event
tự tạo 1 invocation cho mỗi file. Lập luận đó **không còn đúng** khi đơn vị là
project:

- Cần biết khi nào **toàn bộ document của run** xong để chạy đối chiếu — S3
  event không cho biết điều đó.
- Cần **retry riêng cho từng bước**: Gemini trả 429 thì chỉ chạy lại Gemini,
  không chạy lại Document AI (tốn tiền thật).
- Cần **cô lập lỗi per-document**: 1 file hỏng không được giết cả run.
- Cần **workflow execution state** để debug, thứ DynamoDB status không thay được.

## 5. Vì sao Human Review KHÔNG dùng task token

Review là **bước cuối**, và EDIT là **người sửa tay** (không có AI chạy lại).
Sau APPROVE không còn gì để Step Functions điều phối. Giữ execution mở nhiều
giờ/ngày chỉ để chờ người sẽ kéo theo bảng lưu token, xử lý token hết hạn,
`SendTaskFailure` khi user bỏ ngang, execution treo ăn quota, và debug khó hơn —
đổi lại không được lợi ích nào.

Nếu sau này có bước hậu-approve (đẩy ERP, xuất báo cáo), khởi động **execution
thứ hai ngắn** từ API approve. Hai execution ngắn tốt hơn một execution treo.

## 6. Progress realtime — polling

Độ "realtime" **không** do transport quyết định mà do backend ghi progress đủ
mịn. Mỗi worker ghi state 2 lần (vào bước / xong bước) → 6 mốc mỗi document.
`GET /projects/{id}` trả `step`, `step_status`, `attempt`, `progress_percent`
(tính theo **số bước**, không theo số document).

Số liệu: OCR ~5–30s/doc, Gemini ~3–15s/doc → 1 run 3–4 doc mất ~30–90s. Polling
2s cho độ trễ ≤2s trong khi bước ngắn nhất còn kéo dài 3s, chi phí ~$0.00003/run.

Nâng cấp WebSocket sau này: bật DynamoDB Streams trên bảng `documents` +
notification Lambda — **không phải sửa worker**, vì worker vốn chỉ ghi state.

## 7. AI Design

### 7.1 OCR — Document AI Form Parser
Tài liệu tiếng Việt dùng Form Parser (generic); specialized parsers
(Invoice/PO Parser) **không hỗ trợ tiếng Việt**.
Giới hạn online: ~15 trang / 20MB → `/process` từ chối sớm bằng `head_object`.

### 7.2 Extraction — Gemini (1 model + N schema)
1 call vừa classify vừa extract, trả `{document_type, data, confidence}` theo
structured output. **Prompt được sinh từ registry schema**
(`schemas/registry.py`) — thêm loại chứng từ mới chỉ cần thêm file schema,
không sửa prompt bằng tay.

### 7.3 Lỗi tạm thời
429 / quota / 503 được bọc thành `RateLimitError` để Step Functions `Retry`
phân biệt được với lỗi logic (backoff 2x + full jitter, tối đa 4 lần).

## 8. Validate và Cross-check — hai tầng khác nhau

| Tầng | File | Phạm vi |
|---|---|---|
| Schema + business rule | `core/validate.py` | **Trong 1 document** (`item_total == total_amount`) |
| Cross-check | `core/rules.py` + `core/crosscheck.py` | **Giữa nhiều document** |

Cả hai đều **deterministic, không gọi AI** (rule cứng của project).

Cross-check là **rule engine N-way**, không phải hàm `reconcile(PO, Invoice)`:
mỗi rule tự khai báo cần loại document nào và **tự bỏ qua** khi không đủ. Thêm
loại chứng từ thứ 4 = thêm 1 schema + vài rule, không sửa engine/Step
Functions/API. Xem `docs/schemas.md` cho danh sách rule.

## 9. Thành phần

| Thành phần | Công nghệ | Ghi chú |
|---|---|---|
| Frontend | React (Vite) + S3/CloudFront | Chưa làm |
| API | API Gateway HTTP + 1 Lambda | POC: **chưa có auth** (giới hạn cố ý) |
| Orchestration | Step Functions STANDARD | Map + retry + catch per-document |
| Worker | 6 Lambda | ocr, extract, validate, reconcile, mark-failed, mark-run-failed |
| Storage | S3 | gom hết dưới `projects/{project_id}/` |
| Database | DynamoDB | 5 bảng, xem `data-model.md` |
| AI | Document AI Form Parser + Gemini | Google Cloud |
| IaC | Terraform | AWS + GCP providers |
| Logging | CloudWatch | Grafana cân nhắc sau |

## 10. Lưu vết AI call (rule cứng)

Mỗi lần gọi Document AI/Gemini → 1 record `AI_CALL` trong `audit_log`:
request_id, entity_id, model, thời gian, latency, status, token usage,
estimated cost. Ghi cả khi lỗi và khi bị rate limit.

## 11. Giới hạn cố ý của POC

- Không auth (Cognito ở giai đoạn sau) → **chưa dùng WebSocket** cũng vì lý do này.
- Chưa có Grafana/Loki — dùng CloudWatch trước.
- `GET /projects` dùng `scan` bảng projects (số project nhỏ); mọi truy vấn
  document đều qua GSI, **không scan**.
