# Schemas chứng từ + Rule đối chiếu (v2)

## Hợp đồng validate hiện tại (2026-09-22)

Phần này thay thế các điều kiện từ chối nghiệp vụ trong mô tả schema cũ bên dưới.
Schema chung ở `backend/schemas/document.py`. `valid=true` nghĩa là dữ liệu có cấu trúc xử lý được,
không khẳng định chứng từ đúng hoặc đã được phê duyệt. `rule_errors` giữ mảng rỗng để tương thích API.
MST/số chứng từ sai mẫu, ngày tương lai, tiền/số lượng bất thường đều là `flags`.
Mỗi flag có `code`, `field`, `message`, `values`, `formula` (có thể null).
Sai JSON/cấu trúc/kiểu không xử lý được vẫn là `schema_errors`, trạng thái `FAILED`.

Validate KHÔNG kiểm số học bằng công thức (gỡ 2026-10-07): không còn `quantity × unit_price = amount`,
`Σ amount − discount_amount = subtotal` hay `subtotal + tax_amount = total_amount`. Chiết khấu từng
dòng và phí ngoài thuế làm các công thức đó báo oan trên chứng từ trích đúng.
Không dò từ khóa shipping hoặc thêm rule cho từng loại phí.
Trường `shipping_amount` từ dữ liệu cũ được chuyển sang `other_fields` khi validate để giữ dữ liệu.

Prompt yêu cầu trích mọi nhãn–giá trị ngoài bảng, cả phần tổng kết và ghi chú, vào `other_fields`;
không tự tính bù/sửa số để làm công thức khớp. Giao diện cho xem và thêm/sửa/xóa trường bổ sung.
Sửa tay chạy lại validate, lưu flag mới; đối chiếu cũ trở thành stale theo luồng hiện có.

Giới hạn: 3 bảng, 25 cột/bảng, 500 dòng/bảng, 500 ký tự/ô.
Vượt giới hạn: bản đầy đủ vẫn được lưu, validate có warnings và `comparison_incomplete`.
Nhóm có dữ liệu rút gọn hoặc không đủ cột/số lượng sẽ có cảnh báo `comparison_incomplete`,
không tạo kết luận thiếu/thừa dựa trên bản rút gọn. Chứng từ vẫn nằm trong `checked_document_ids`.
`validation_flags` được lưu cùng kết quả đối chiếu S3 để giữ ngữ cảnh của từng lần chạy.

Giới hạn trên không bảo đảm dưới 400 KB; xem cơ chế S3 trong `docs/data-model.md`.
Sau triển khai cần chạy lại validate hoặc lưu bản sửa để cập nhật flag của chứng từ cũ.
Muốn bổ sung trường từng bị AI bỏ sót cần trích xuất lại hoặc bổ sung bằng Human Review.

Ba loại chứng từ hiện hỗ trợ. Registry ở `backend/schemas/registry.py` là
**nguồn sự thật duy nhất**: `validate`, prompt Gemini, và cross-check engine
đều đọc từ đó.

## 1. Thêm loại chứng từ mới cần làm gì

1. Thêm file `backend/schemas/<loại>.py` (Pydantic model, có `document_type`
   dạng `Literal`).
2. Đăng ký vào `DOCUMENT_TYPES`, `DOCUMENT_TYPE_LABELS`, `DATE_FIELD_BY_TYPE`,
   `NUMBER_FIELD_BY_TYPE` trong `registry.py`.
3. Thêm rule cross-check nếu cần (`backend/core/rules.py`).

**Không** phải sửa: prompt Gemini (sinh từ `model_json_schema()`), Step
Functions, API, data model. Rule cũ tự bỏ qua loại mới nếu không liên quan.

## 2. Purchase Order — `purchase_order`

```json
{
  "document_type": "purchase_order",
  "po_number": "PO-2026-001",
  "po_date": "2026-08-01",
  "vendor": "ABC Technology",
  "vendor_tax_code": "0301234567",
  "buyer": "Công ty TNHH XYZ",
  "currency": "VND",
  "items": [{ "item_name": "Laptop Dell XPS", "quantity": 100, "unit": "cái", "unit_price": 1250000 }],
  "total_amount": 125000000,
  "delivery_date": "2026-09-01",
  "payment_terms": "30 days"
}
```

## 3. Invoice — `invoice`

```json
{
  "document_type": "invoice",
  "invoice_number": "INV-001",
  "invoice_date": "2026-08-05",
  "vendor": "ABC Technology",
  "vendor_tax_code": "0301234567",
  "buyer": "Công ty TNHH XYZ",
  "currency": "VND",
  "po_number": "PO-2026-001",
  "items": [{ "item_name": "Laptop Dell XPS", "quantity": 100, "unit": "cái", "unit_price": 1280000 }],
  "subtotal": 128000000,
  "discount_amount": 0,
  "tax_rate": 0.08,
  "tax_amount": 10240000,
  "total_amount": 138240000,
  "payment_due_date": "2026-09-05"
}
```

`discount_amount` là tổng chiết khấu thương mại của hoá đơn, số nguyên không âm,
tuỳ chọn (mặc định `null`, khi kiểm tra coi như 0). `subtotal` là tiền hàng sau
chiết khấu, chưa thuế. Không áp dụng chiết khấu từng dòng hoặc cho PO.

## 4. Biên bản nghiệm thu — `acceptance_record`

```json
{
  "document_type": "acceptance_record",
  "record_number": "BBNT-001",
  "record_date": "2026-08-03",
  "vendor": "ABC Technology",
  "vendor_tax_code": "0301234567",
  "buyer": "Công ty TNHH XYZ",
  "po_number": "PO-2026-001",
  "items": [{ "item_name": "Laptop Dell XPS", "quantity": 100, "unit": "cái" }],
  "accepted_by": "Nguyễn Văn A",
  "notes": ""
}
```

**Dùng `AcceptedItem` riêng, không dùng lại `LineItem`**: biên bản nghiệm thu
thường **không có đơn giá**, trong khi `LineItem` bắt buộc `unit_price > 0` →
dùng chung sẽ fail validate oan.

## 5. Quy tắc chung

- Tiền tệ: **số nguyên** (VND không có phần lẻ); không dùng float cho tiền.
- Ngày: ISO 8601 `YYYY-MM-DD`.
- `currency` ∈ `VND, USD, EUR, JPY, SGD` (`CURRENCIES` trong `purchase_order.py`).
- Số chứng từ: `^[A-Z0-9][A-Z0-9\-/ ]{2,50}$`.
- Mã số thuế: `^(\d{10}(-?\d{3})?|\d{12})$` — 10 số (doanh nghiệp), 10-3 số
  (chi nhánh; nhận cả dạng in liền 13 số), 12 số (cá nhân/hộ kinh doanh). Lưu
  **nguyên văn**; `agree_vendor_tax_code` so chuỗi thô nên `0102721191-068` và
  `0102721191068` bị báo lệch dù cùng một mã — giới hạn đã chấp nhận ở POC.

## 6. Validate — trong 1 document (`core/validate.py`)

| Kiểm tra | Áp dụng |
|---|---|
| Schema Pydantic (kiểu, required, regex, `> 0`) | mọi loại |
| `currency` hợp lệ | loại nào có `currency` |
| Ngày không ở tương lai | dùng `DATE_FIELD_BY_TYPE` |
| Số lượng của từng dòng hàng là số dương; dòng thiếu số lượng thì báo | bảng có cột tên hàng và số lượng |

## 7. Cross-check — giữa nhiều document (`core/rules.py`)

Document được gom nhóm theo `po_number`. Document thiếu `po_number` được gộp
vào nhóm duy nhất nếu project chỉ có 1 giao dịch; nếu có nhiều giao dịch thì bị
báo `document_unlinked` để người review gán tay (fail-loud, không im lặng bỏ qua).

| `rule_id` | Kiểm tra | Severity | Bỏ qua khi |
|---|---|---|---|
| `agree_vendor` | vendor giống nhau mọi chứng từ | critical | <2 doc có field |
| `agree_currency` | currency giống nhau | critical | <2 doc có field |
| `agree_vendor_tax_code` | mã số thuế giống nhau | medium | <2 doc có field |
| `agree_buyer` | bên mua giống nhau | medium | <2 doc có field |
| `match_total_amount` | tổng tiền khớp | high | <2 doc có field |
| `line_item_unit_price` | đơn giá từng mặt hàng khớp | high | <2 doc có đơn giá |
| `line_item_quantity` | số lượng từng mặt hàng khớp | high | <2 doc có đơn giá |
| `line_item_missing` | mặt hàng có ở doc này, thiếu ở doc kia | high | — |
| `line_item_extra` | mặt hàng thừa | high | — |
| `invoiced_over_accepted` | SL xuất hóa đơn > SL nghiệm thu | **critical** | thiếu biên bản nghiệm thu |
| `accepted_over_ordered` | SL nghiệm thu > SL đặt hàng | high | thiếu PO |
| `date_order` | `po_date ≤ record_date ≤ invoice_date` | medium | thiếu ngày |
| `po_reference_missing` | tham chiếu PO không có trong project | high | không doc nào có `po_number` |
| `document_unlinked` | không xác định được thuộc giao dịch nào | medium | project chỉ có 1 giao dịch |

`line_item_*` chỉ so giữa các chứng từ **có đơn giá** (PO, Invoice) — nếu so cả
biên bản nghiệm thu sẽ báo sai khi nghiệm thu từng phần là hợp lệ. Quan hệ với
biên bản nghiệm thu do `invoiced_over_accepted` / `accepted_over_ordered` lo.

## 8. Cấu trúc `Discrepancy` (N document, không phải 2)

```json
{
  "rule_id": "match_total_amount",
  "field": "total_amount",
  "severity": "high",
  "values": [
    { "document_id": "doc-a", "document_type": "purchase_order", "value": 125000000 },
    { "document_id": "doc-b", "document_type": "invoice",        "value": 128000000 }
  ],
  "difference": 3000000,
  "explanation": "total_amount lệch 3,000,000: đơn đặt hàng=125,000,000 / hóa đơn=128,000,000"
}
```

Khác v1: v1 dùng `expected`/`actual` nên **về bản chất chỉ biểu diễn được 2
document**. `values[]` cho phép flag mâu thuẫn giữa số lượng document bất kỳ.
