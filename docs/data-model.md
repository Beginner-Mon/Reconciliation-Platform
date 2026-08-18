# Data Model — DynamoDB (v2)

## 1. Năm bảng

| Bảng | Mục đích | PK | SK |
|---|---|---|---|
| `projects` | Container lâu dài chứa document | `project_id` | — |
| `documents` | Trạng thái + kết quả trích xuất 1 chứng từ | `document_id` | — |
| `processing_runs` | Lịch sử mỗi lần bấm `/process` | `run_id` | — |
| `reconciliations` | Mỗi lần đối chiếu + kết quả review | `reconciliation_id` | — |
| `audit_log` | Lưu vết AI call, pipeline step, thao tác review | `entity_id` | `timestamp` |

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

## 6. `audit_log`

```json
{
  "entity_id": "doc-2026-0002",
  "timestamp": "2026-08-17T09:01:29Z",
  "action": "AI_CALL",
  "detail": {
    "request_id": "req-8f3a",
    "model": "gemini-2.5-flash",
    "status": "ok",
    "latency_ms": 4210,
    "token_usage": { "prompt_tokens": 1200, "output_tokens": 350 },
    "estimated_cost_usd": 0.0041
  }
}
```

`entity_id` là `document_id` hoặc `project_id` tùy loại sự kiện.

| Action | Ghi khi |
|---|---|
| `AI_CALL` | Mỗi lần gọi Document AI/Gemini — **rule cứng**, ghi cả khi lỗi và rate limit |
| `PIPELINE_STEP` | Vào/xong/lỗi từng bước, có `attempt` |
| `REVIEW_EDIT` | Người sửa tay một document |
| `REVIEW_DECISION` | Approve/reject một reconciliation |

## 7. S3 layout

Gom hết dưới prefix project để dễ xoá và dễ đặt lifecycle rule:

```
projects/{project_id}/uploads/{document_id}.{pdf|png|jpg}
projects/{project_id}/ocr/{document_id}.json
projects/{project_id}/extraction/{document_id}.json
projects/{project_id}/reconciliation/{reconciliation_id}.json
```
