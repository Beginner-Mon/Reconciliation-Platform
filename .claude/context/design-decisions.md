# Nhật ký quyết định thiết kế (v1 → v2)

Ghi lại **vì sao**, để lần sau không phải tranh luận lại. Cập nhật 2026-08-17.

Kế hoạch gốc của Ngài: `architecture-v2-plan.md` (bản v2 nguyên văn).
Bản này ghi những chỗ **đã đi khác** kế hoạch gốc và lý do.

---

## QĐ-1. Bỏ "batch", dùng "project"

**Kế hoạch gốc:** batch = một lần upload 3–4 file, reconcile nằm cứng trong workflow.

**Đổi thành:** Project (lâu dài) + Processing Run (một lần chạy) + Reconciliation
(một lần đối chiếu) — ba khái niệm tách biệt.

**Vì sao:** Ngài chỉ ra kịch bản thêm 1 biên bản nghiệm thu vào project đã xử lý.
Mô hình batch không diễn tả được: nó buộc phải hoặc tạo batch mới (mất ngữ cảnh
các doc cũ) hoặc chạy lại cả batch (OCR lại 3 file cũ, tốn tiền và thời gian vô ích).

**Hệ quả:** `/process` có logic skip doc đã `VALIDATED`; cross-check tách hẳn ra
endpoint riêng.

---

## QĐ-2. Step Functions KHÔNG chờ Human Review

**Kế hoạch gốc:** §6 dùng `waitForTaskToken`.

**Đổi thành:** execution kết thúc ở `AWAITING_REVIEW`; review là API độc lập.

**Vì sao:** Ngài xác nhận review là **bước cuối** và EDIT là **người sửa tay**
(không có AI chạy lại). Sau APPROVE không còn gì để orchestrate. Giữ execution
mở nhiều ngày kéo theo bảng lưu token, xử lý token hết hạn, `SendTaskFailure`
khi user bỏ ngang, execution treo ăn quota, debug khó — không đổi lại lợi ích nào.

**Nếu sau này cần bước hậu-approve** (đẩy ERP, xuất báo cáo): khởi động
execution thứ hai ngắn từ API approve. Hai execution ngắn > một execution treo.

---

## QĐ-3. Progress dùng polling, không WebSocket + EventBridge

**Kế hoạch gốc:** §5 EventBridge → notification Lambda → WebSocket.

**Đổi thành:** `GET /projects/{id}` poll 2s.

**Vì sao:** độ realtime do **backend ghi progress đủ mịn** quyết định, không do
transport. OCR ~5–30s/doc, Gemini ~3–15s/doc → bước ngắn nhất còn 3s, polling 2s
là thừa đủ. WebSocket thêm 1 API Gateway + bảng `ws_connections` + 3 Lambda +
reconnect/ping, mà **vẫn phải** giữ endpoint state để resync khi mất event —
tức làm cả hai chứ không thay thế. Chưa có auth nên WebSocket còn mở bề mặt
nghe lén progress project bất kỳ.

**Đường nâng cấp:** bật DynamoDB Streams trên bảng `documents` + notification
Lambda. Worker **không phải sửa dòng nào** vì vốn chỉ ghi state. Cách này cũng
bỏ luôn EventBridge — nó chỉ là hop trung gian mà Streams làm thay.

---

## QĐ-4. Map iterator tách 3 state thay vì 1 Lambda/doc

**Kế hoạch gốc:** §4 một worker Lambda cho mỗi document.

**Đổi thành:** `Ocr → Extract → Validate` là 3 task state riêng.

**Vì sao:** Gemini trả 429 rất thường xuyên. Gộp 1 Lambda thì retry sẽ chạy lại
**cả Document AI** — tốn tiền thật và thêm 5–30s mỗi lần. Tách ra thì retry chỉ
đúng bước hỏng. Phụ thêm: progress chi tiết hơn, timeout riêng từng bước. Chi
phí state transition không đáng kể.

---

## QĐ-5. Cross-check là rule engine N-way

**Kế hoạch gốc + code v1:** `reconcile(po, invoice)` — chữ ký cứng 2 tham số,
`Mismatch` có `expected`/`actual`.

**Đổi thành:** `CROSS_RULES` registry; `Discrepancy.values[]` chứa N document.

**Vì sao:** Ngài nêu mục tiêu là *flag mâu thuẫn giữa các doc*, hiện 3 loại,
sau này có thể thêm. `expected`/`actual` về bản chất **chỉ biểu diễn được 2
document**. Rule tự khai báo cần loại doc nào và **tự bỏ qua** khi thiếu → thêm
loại thứ 4 chỉ cần thêm schema + rule.

**Chi tiết đáng nhớ:** `line_item_*` chỉ so giữa chứng từ **có đơn giá**
(PO, Invoice). Nếu so cả biên bản nghiệm thu sẽ báo sai khi nghiệm thu từng
phần là hợp lệ — quan hệ với nghiệm thu do `invoiced_over_accepted` /
`accepted_over_ordered` lo.

---

## QĐ-6. File chỉ vào hệ thống qua endpoint upload

**Không** discover S3 bằng `ListObjectsV2`. DynamoDB là nguồn sự thật duy nhất.
File ai đó copy thẳng vào S3 sẽ không được thấy — chấp nhận, đổi lại không phải
đoán `file_name`/`content_type` từ key và không mất khả năng verify nguồn gốc.

---

## QĐ-7. Review gắn vào reconciliation, không gắn vào project

Thêm doc mới → sinh reconciliation mới → cần review mới, lịch sử cũ còn nguyên.
Nếu gắn review vào project thì trạng thái `APPROVED` bị đá qua lại vô nghĩa mỗi
lần thêm doc.

---

## Bốn best-practice gap của kế hoạch gốc (đã bịt)

| Gap | Xử lý |
|---|---|
| "Check batch chưa processing" bị race | Conditional update claim `processing_run_id` + execution name = `run_id` |
| Không nhắc retry cho AI call | `RateLimitError` + backoff 2x + `JitterStrategy: FULL` + `MaxConcurrency: 3` |
| 1 doc lỗi giết cả run | `Catch` **bên trong** iterator |
| Document AI online giới hạn ~15 trang/20MB | Reject sớm bằng `ContentLength` từ `head_object` — bịt luôn lỗ hổng presigned PUT không giới hạn kích thước |

## Bẫy phát hiện lúc implement

- **DynamoDB không nhận `float`** → `to_dynamo`/`from_dynamo` chuyển Decimal.
  Bắt buộc vì `confidence` của Gemini là float.
- **GSI không index được attribute lồng** → `po_number` phải nhân bản lên
  top-level, và chỉ ghi khi có giá trị để giữ GSI sparse.
- **`AcceptedItem` phải tách khỏi `LineItem`** — `LineItem` bắt buộc
  `unit_price > 0` nhưng biên bản nghiệm thu thường không có đơn giá.
- **Prompt Gemini phải sinh từ registry** — v1 đã lệch sẵn:
  `SUPPORTED_DOC_TYPES` liệt kê `acceptance_record` nhưng prompt chỉ mô tả 2 loại.
- **`force=true` vẫn phải bỏ qua doc đã sửa tay**, cần thêm `force_edited=true`.
  Không có chốt này thì một lần re-process xoá sạch công review.
- **Mọi nhánh kết thúc của SFN phải `REMOVE processing_run_id`**, kể cả nhánh
  lỗi, nếu không project kẹt vĩnh viễn không chạy lại được.
