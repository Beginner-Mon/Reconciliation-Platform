# Data Model — DynamoDB (v2)

## Payload document lớn và flag (2026-09-22)

`validation` gồm `valid`, `schema_errors`, `rule_errors` (rỗng), `warnings`, `flags`,
`comparison_incomplete`. Flag nghiệp vụ không chuyển document sang `FAILED`.
Worker không đưa danh sách flag vào output Step Functions để tránh vượt giới hạn payload.

`update_document` đo kích thước biểu diễn DynamoDB đã serialize bằng TypeSerializer
(tính cả tên trường, wrapper và UTF-8). Từ 300 KiB, chuyển `extraction`, `validation`,
`confidence`, `ungrounded_fields` sang một object S3 bất biến:
`projects/{project_id}/document-payload/{document_id}/{uuid}.json`.
DynamoDB giữ `document_payload_s3_key`; `get_item`/query document đọc lại dữ liệu đầy đủ.
Ngưỡng có dư địa cho metadata và nhỏ hơn giới hạn 400 KiB; không cắt extraction để vừa bản ghi.
Document đã chuyển sang S3 tiếp tục dùng S3 cho các bản sửa sau.

Ghi S3 trước, cập nhật con trỏ sau; nếu ghi DynamoDB thất bại, con trỏ cũ vẫn đọc được.
Các payload cũ được giữ, có thể phát sinh object không còn tham chiếu; chưa có tác vụ dọn tự động.
Xóa document xóa object payload đang được tham chiếu, cùng upload/OCR/extraction hiện tại.
Không thay đổi schema bảng hay migration dữ liệu cũ. API review cần `s3:PutObject`;
cần triển khai quyền cùng backend trước khi sửa document lớn.

## 1. Bốn bảng

| Bảng | Mục đích | PK | SK |
|---|---|---|---|
| `projects` | Container lâu dài chứa document | `project_id` | — |
| `documents` | Trạng thái + kết quả trích xuất 1 chứng từ | `document_id` | — |
| `processing_runs` | Lịch sử mỗi lần bấm `/process` | `run_id` | — |
| `reconciliations` | Mỗi lần đối chiếu + kết quả review | `reconciliation_id` | — |

> Audit không còn bảng riêng: mỗi sự kiện là một dòng JSON trên stdout
> (`common/audit.py` dùng `print`), xem `observability.md`.

JSON nặng (OCR, extraction đầy đủ, danh sách discrepancy) đẩy lên S3; DynamoDB
chỉ giữ trường cần truy vấn và summary.

## 2. `projects`

```json
{
  "project_id": "prj-a1b2c3d4e5f6",
  "name": "Gói thầu A",
  "description": "",
  "created_at": "2026-08-17T09:00:00Z",
  "created_by": "poc-user",
  "document_count": 3,
  "processing_run_id": "run-...",
  "last_run_id": "run-...",
  "latest_reconciliation_id": "rec-..."
}
```

`processing_run_id` là **khoá chống double-start**: `/process` claim bằng
conditional update `attribute_not_exists(processing_run_id)`; ai thua nhận 409.
Bước cuối của Step Functions (kể cả nhánh lỗi) **bắt buộc** `REMOVE` nó, nếu
không project kẹt vĩnh viễn.

`deleting_at` / `deleting_by` xuất hiện khi `DELETE /projects/{id}` đã bắt đầu.
Có nó thì `/process` và upload trả 409; `claim_processing_run` cũng từ chối bằng
điều kiện `attribute_not_exists(deleting_at)`. Xoá hỏng giữa chừng thì record
project còn lại kèm cờ này — gọi xoá lại để hoàn tất.

## 3. `documents`

```json
{
  "document_id": "doc-2026-0002",
  "project_id": "prj-a1b2c3d4e5f6",
  "s3_key": "projects/prj-.../uploads/doc-....pdf",
  "file_name": "INV-001.pdf",
  "file_type": "pdf",
  "content_type": "application/pdf",
  "size_bytes": 245000,
  "uploaded_at": "2026-08-17T09:00:00Z",
  "updated_at": "2026-08-17T09:01:29Z",

  "status": "VALIDATED",
  "step": "validate",
  "step_status": "done",
  "step_started_at": "2026-08-17T09:01:20Z",
  "attempt": 1,

  "document_type": "invoice",
  "po_number": "PO-2026-001",
  "ocr_s3_key": "projects/prj-.../ocr/doc-....json",
  "extraction_s3_key": "projects/prj-.../extraction/doc-....json",
  "extraction": { "invoice_number": "INV-001", "...": "..." },
  "confidence": { "vendor": 0.99, "total_amount": 0.87 },
  "validation": { "valid": true, "schema_errors": [], "rule_errors": [] },

  "edited_fields": ["vendor"],
  "edited_at": "2026-08-17T10:00:00Z",
  "edited_by": "tri",
  "error": null
}
```

**Status**: `PENDING → PROCESSING → OCR_DONE → EXTRACTED → VALIDATED | FAILED`
**Step**: `ocr | extract | validate`, **step_status**: `running | done | failed`

`status_before_run`: `/process` ghi lúc xếp hàng — bằng `status` cũ nếu chứng từ
đã xử lý xong, ngược lại `null`. Run bị dừng thì chứng từ chưa kịp chạy được trả
về trạng thái này.

`step`/`step_status`/`attempt` là nguồn dữ liệu cho progress polling — worker
ghi 2 lần mỗi bước (vào bước / xong bước) → 6 mốc mỗi document.

`po_number` được **nhân bản lên top-level** vì DynamoDB GSI không index được
attribute lồng trong map.

`edited_fields` khác rỗng nghĩa là người đã sửa tay → `/process` **bỏ qua**
document này ngay cả khi `force=true`, trừ khi truyền thêm `force_edited=true`.

### GSI

| Index | PK | Dùng cho |
|---|---|---|
| `project_id-index` | `project_id` | Liệt kê document của project (thay cho `scan`) |
| `po_number-index` | `po_number` | Tra PO đã duyệt ở project/batch cũ (sparse) |

## 4. `processing_runs`

```json
{
  "run_id": "run-7f3a2b1c",
  "project_id": "prj-...",
  "document_ids": ["doc-c"],
  "skipped_document_ids": ["doc-a", "doc-b"],
  "status": "SUCCEEDED",
  "started_at": "...", "finished_at": "...",
  "execution_arn": "arn:aws:states:...:execution:...:run-7f3a2b1c",
  "reconciliation_id": "rec-...",
  "error": null
}
```

`run_id` được dùng làm **execution name** của Step Functions → gọi trùng không
tạo execution thừa (Standard workflow idempotent theo name trong 90 ngày).

**Status**: `PROCESSING → SUCCEEDED | FAILED | CANCELLED`.
`cancel_requested_at` / `cancel_requested_by` do `POST /process/stop` ghi; worker
đọc cờ này để bỏ qua. Run có cờ kết thúc ở `CANCELLED` và không sinh
reconciliation.

## 5. `reconciliations`

```json
{
  "reconciliation_id": "rec-9d8c7b6a",
  "project_id": "prj-...",
  "created_at": "...",
  "document_ids": ["doc-a", "doc-b", "doc-c"],
  "s3_key": "projects/prj-.../reconciliation/rec-....json",
  "discrepancy_count": 3,
  "severity_summary": { "critical": 1, "high": 2 },
  "groups": [
    { "key": "PO-2026-001",
      "document_ids": ["doc-a", "doc-b", "doc-c"],
      "document_types": ["acceptance_record", "invoice", "purchase_order"] }
  ],
  "skipped_documents": [],
  "status": "PENDING_REVIEW",
  "review": { "decision": null, "reviewer": null, "reviewed_at": null, "comment": null }
}
```

**Review gắn vào `reconciliation`, KHÔNG gắn vào project.** Thêm document mới →
sinh reconciliation mới → cần review mới, lịch sử cũ vẫn còn nguyên. Nếu gắn
review vào project thì `APPROVED` sẽ bị đá qua lại vô nghĩa mỗi lần thêm doc.

Danh sách `discrepancies` đầy đủ nằm ở S3 (`s3_key`), lấy qua
`GET /reconciliations/{id}`.

## 6. Audit (CloudWatch Logs, không phải bảng)

Mỗi sự kiện là một dòng JSON trên stdout:

```json
{"audit": 1, "action": "AI_CALL", "actor": null, "source": "worker",
 "project_id": "prj-...", "entity_id": "doc-2026-0002",
 "timestamp": "2026-08-17T09:01:29Z",
 "detail": {"request_id": "req-8f3a", "model": "gemini-2.5-flash", "status": "ok"}}
```

| Action | Ghi khi |
|---|---|
| `AI_CALL` | Mỗi lần gọi Document AI/Gemini — **rule cứng**, ghi cả khi lỗi và rate limit |
| `PIPELINE_STEP` | Vào/xong/lỗi từng bước, có `attempt` |
| `PROCESS_RUN` | Mọi quyết định của `/process`, kể cả quyết định **bỏ qua** |
| `EDIT_OVERWRITTEN` | `force_edited=true` cho AI ghi đè dữ liệu người đã sửa tay |
| `REVIEW_EDIT` | Người sửa tay một document |
| `REVIEW_DECISION` | Approve/reject một reconciliation |
| `PROJECT_CREATED` | Tạo project |
| `DOCUMENTS_UPLOADED` | Upload chứng từ |
| `RECONCILE_RUN` | Bấm đối chiếu |
| `PROCESS_STOP_REQUESTED` | Bấm Dừng một run đang chạy |
| `PROJECT_DELETE_STARTED` | Bắt đầu xoá project — ghi TRƯỚC khi xoá: tên, chứng từ, id run/reconciliation |
| `PROJECT_DELETED` | Xoá project xong — số lượng thật đã xoá |
| `PROCESS_RUN_UNSTUCK` | Bấm Dừng trên run đã chết, run được kết thúc ngay |

Chi tiết: `observability.md`.

## 7. S3 layout

Gom hết dưới prefix project để dễ xoá và dễ đặt lifecycle rule:

```
projects/{project_id}/uploads/{document_id}.{pdf|png|jpg}
projects/{project_id}/ocr/{document_id}.json
projects/{project_id}/extraction/{document_id}.json
projects/{project_id}/reconciliation/{reconciliation_id}.json
```
