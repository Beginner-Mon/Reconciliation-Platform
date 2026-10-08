# Schemas chứng từ + Rule đối chiếu (v2)

## Hợp đồng validate hiện tại (2026-09-22)

Phần này là hợp đồng validate; các mục bên dưới mô tả schema chung và rule theo đúng code.
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

Mọi loại chứng từ dùng chung MỘT schema: `Document` ở
`backend/schemas/document.py`. Registry ở `backend/schemas/registry.py` là
**nguồn sự thật duy nhất** về tên loại: `validate`, prompt Gemini và cross-check
đều đọc từ đó.

## 1. Schema chung — `Document`

```json
{
  "document_type": "invoice",
  "role": "billing",
  "doc_number": "INV-001",
  "doc_date": "2026-08-05",
  "order_reference": "PO-2026-001",
  "seller": "ABC Technology",
  "seller_tax_code": "0301234567",
  "buyer": "Công ty TNHH XYZ",
  "buyer_tax_code": null,
  "currency": "VND",
  "subtotal": 128000000,
  "discount_amount": 0,
  "tax_amount": 10240000,
  "total_amount": 138240000,
  "other_fields": { "Hình thức thanh toán": "CK" },
  "tables": [
    {
      "columns": [
        { "header": "Tên hàng hoá", "role": "item_name" },
        { "header": "SL", "role": "quantity" },
        { "header": "ĐVT", "role": "unit" },
        { "header": "Đơn giá", "role": "unit_price" },
        { "header": "Thành tiền", "role": "amount" }
      ],
      "rows": [
        { "Tên hàng hoá": "Laptop Dell XPS", "SL": 100, "ĐVT": "cái",
          "Đơn giá": 1280000, "Thành tiền": 128000000 }
      ]
    }
  ]
}
```

| Trường | Kiểu | Ghi chú |
|---|---|---|
| `document_type` | chuỗi 1–100 ký tự, bắt buộc | nhãn loại do AI gán; phải có trong registry (§2) |
| `role` | `order`, `offer`, `delivery`, `billing`, `other` | vai trò của chứng từ trong giao dịch; mặc định `other` |
| `doc_number`, `doc_date` | chuỗi, ngày | số và ngày của chính chứng từ |
| `order_reference` | chuỗi | số đơn hàng mà chứng từ tham chiếu tới |
| `seller`, `buyer` | chuỗi tối đa 200 ký tự | |
| `seller_tax_code`, `buyer_tax_code` | chuỗi | lưu nguyên văn |
| `currency` | chuỗi | |
| `subtotal`, `discount_amount`, `tax_amount`, `total_amount` | số nguyên | `subtotal` là tiền hàng sau chiết khấu, chưa thuế |
| `other_fields` | object nhãn → chuỗi | mọi nhãn–giá trị ngoài bảng mà schema chưa có |
| `tables` | danh sách bảng | mỗi bảng có `columns` (`header`, `role`) và `rows` (object `header` → giá trị) |

Mọi trường trừ `document_type` đều tuỳ chọn. Schema không nhận trường lạ ở gốc
(`extra = forbid`); `core/normalize.py` dọn output của Gemini trước khi validate.

Vai trò của chứng từ (`ROLE_LABELS`): `order` đặt hàng · `offer` báo giá ·
`delivery` giao / nghiệm thu · `billing` thanh toán · `other` khác.

Vai trò của cột: `item_name`, `quantity`, `unit`, `unit_price`, `amount`, hoặc
`null`. Bảng muốn đem đối chiếu phải có cột `item_name` và cột `quantity`.

## 2. Registry và tên loại

`DOCUMENT_TYPES` có 9 tên, tất cả cùng trỏ vào `Document`: `document`,
`purchase_order`, `invoice`, `acceptance_record`, `unknown`, `quotation`,
`delivery_note`, `contract`, `other`. `document_type` không nằm trong danh sách
này thì validate báo lỗi cấu trúc và chứng từ `FAILED`.

Thêm loại chứng từ mới:

1. Thêm tên vào `DOCUMENT_TYPES` (trỏ vào `Document`).
2. Thêm nhãn đọc cho người vào `DOCUMENT_TYPE_LABELS`; cần dặn riêng Gemini thì
   thêm vào `DOCUMENT_TYPE_PROMPT_NOTES`.
3. Muốn rule `date_order` và `trung_so_hieu` áp dụng thì thêm vào
   `DATE_FIELD_BY_TYPE` và `NUMBER_FIELD_BY_TYPE`.
4. Thêm rule cross-check nếu cần (`backend/core/rules.py`).

**Không** phải sửa Step Functions, API, data model.

Bốn file `purchase_order.py`, `invoice.py`, `acceptance_record.py`, `unknown.py`
là model cũ, không còn trong registry. Chúng còn được import vì `CURRENCIES`,
`DOC_NUMBER_PATTERN` và `TAX_CODE_PATTERN` khai ở `purchase_order.py`.

## 3. Dữ liệu trích xuất kiểu cũ

Extraction có `items` mà không có `tables` là dữ liệu của schema cũ.
`_migrate_legacy` trong `core/validate.py` đổi nó sang schema chung trước khi
validate: `po_number` / `invoice_number` / `record_number` thành `doc_number`,
`vendor` thành `seller`, `items` thành một bảng năm cột có vai trò. `role` suy từ
loại: `purchase_order` → `order`, `invoice` → `billing`, `acceptance_record` →
`delivery`, còn lại → `other`.

## 4. Quy tắc chung

- Tiền tệ: **số nguyên** (VND không có phần lẻ); không dùng float cho tiền. Số
  lượng là số thực (m², kg).
- Ngày: ISO 8601 `YYYY-MM-DD`.
- `currency` ∈ `VND, USD, EUR, JPY, SGD` (`CURRENCIES` trong `purchase_order.py`).
  Ngoài danh sách thì có cờ `currency`, chứng từ không `FAILED`.
- Số chứng từ: `^[A-Z0-9][A-Z0-9\-/ ]{2,50}$`. Sai mẫu thì có cờ `format`.
- Mã số thuế: `^(\d{10}(-?\d{3})?|\d{12})$` — 10 số (doanh nghiệp), 10-3 số
  (chi nhánh; nhận cả dạng in liền 13 số), 12 số (cá nhân/hộ kinh doanh). Lưu
  **nguyên văn**; `agree_vendor_tax_code` so chuỗi thô nên `0102721191-068` và
  `0102721191068` bị báo lệch dù cùng một mã — giới hạn đã chấp nhận ở POC.

## 5. Validate — trong 1 document (`core/validate.py`)

Hai bước. Bước một dựng model `Document`: sai cấu trúc hoặc sai kiểu thì ghi
`schema_errors` và chứng từ `FAILED`. Bước hai sinh cờ; cờ **không** làm `FAILED`.

| `code` | `field` | Khi nào |
|---|---|---|
| `currency` | `currency` | mã tiền tệ ngoài `CURRENCIES` |
| `future_date` | `doc_date` | ngày ở tương lai |
| `format` | `seller_tax_code`, `buyer_tax_code`, `doc_number`, `order_reference` | giá trị sai mẫu ở §4 |
| `amount_sign` | `subtotal`, `total_amount`, `discount_amount`, `tax_amount` | số âm; riêng `subtotal` và `total_amount` thì bằng 0 cũng báo |
| `insufficient_data` | `tables.T` | bảng thiếu cột `item_name` hoặc `quantity`, hoặc có nhiều cột cùng vai trò |
| `insufficient_data` | `tables.T.rows.R.<cột số lượng>` | dòng không có số lượng |
| `quantity` | `tables.T.rows.R.<cột số lượng>` | số lượng không phải số dương |
| `incomplete_document` | `tables` | dữ liệu vượt giới hạn và đã rút gọn |
| `ai_format` | tên trường | AI trả sai định dạng, trường đã bị bỏ trống (`core/normalize.py`) |
| `vi_tri` | ô trong bảng | số AI chép không khớp vị trí chữ OCR (`core/position.py`) |

Chỉ `ai_format` và `vi_tri` khoá nút Duyệt (`BLOCKING_FLAG_CODES` trong
`api/views.py`). Không có kiểm số học bằng công thức.

## 6. Cross-check — giữa nhiều document

Mã nằm ở `core/crosscheck.py` (điều phối), `core/compare.py` (so cặp với chứng
từ gốc) và `core/rules.py` (rule theo nhóm).

### 6.1 Chứng từ nào được đem so

Chứng từ không qua validate, có `role = other`, hoặc thuộc loại `other` /
`unknown` thì **không** được so. Chúng nằm trong `skipped_documents` kèm lý do,
không bị im lặng bỏ qua.

### 6.2 Gom nhóm

Khoá nhóm của chứng từ `role = order` là `doc_number` (không có thì
`order_reference`); của các chứng từ khác là `order_reference`. Chứng từ không
có khoá được gộp vào nhóm duy nhất nếu project có nhiều nhất một khoá; nếu
project có nhiều khoá thì bị báo `document_unlinked` để người review gán tay.

### 6.3 Chứng từ gốc

Mỗi nhóm có một chứng từ gốc. Người dùng chọn qua `PUT /projects/{id}/anchor`
(lưu ở `project.anchor_document_ids`). Không chọn thì lấy theo vai trò: `order`,
rồi `offer`, `delivery`, `billing`; cùng vai trò thì lấy `document_id` nhỏ nhất.

### 6.4 So cặp với gốc — chỉ khi nhóm có ĐÚNG 2 chứng từ

Mặt hàng được ghép theo tên và đơn vị đã chuẩn hoá (bỏ dấu, chữ thường, gộp
khoảng trắng). Nhóm từ 3 chứng từ trở lên không so cặp, vì một đơn hàng giao
nhiều đợt sẽ bị báo lệch ở mọi đợt; khi đó chỉ chạy rule cộng dồn ở §6.5.

| `rule_id` | Kiểm tra | Severity | Bỏ qua khi |
|---|---|---|---|
| `anchor_seller_mismatch` | bên bán khác gốc | critical | một bên thiếu trường |
| `anchor_currency_mismatch` | tiền tệ khác gốc | critical | một bên thiếu trường |
| `anchor_seller_tax_code_mismatch` | mã số thuế bên bán khác gốc | medium | một bên thiếu trường |
| `anchor_buyer_mismatch` | bên mua khác gốc | medium | một bên thiếu trường |
| `anchor_total_amount_mismatch` | tổng tiền khác gốc | high | một bên không có đơn giá |
| `line_missing_vs_anchor` | mặt hàng có ở gốc, không có ở bên kia | high | — |
| `line_extra_vs_anchor` | mặt hàng có ở bên kia, không có ở gốc | high | — |
| `line_quantity_mismatch` | số lượng lệch với gốc | high | — |
| `line_unit_price_mismatch` | đơn giá lệch với gốc | high | một bên không có giá, hoặc một bên có nhiều giá cho cùng mặt hàng |
| `billing_over_delivery` | tổng số lượng ở chứng từ `billing` vượt chứng từ `delivery` | critical | nhóm thiếu một trong hai vai trò |

### 6.5 Rule theo nhóm — mọi nhóm từ 2 chứng từ (`CROSS_RULES`)

| `rule_id` | Kiểm tra | Severity | Bỏ qua khi |
|---|---|---|---|
| `agree_vendor` | bên bán giống nhau ở mọi chứng từ | critical | dưới 2 chứng từ có trường |
| `agree_currency` | tiền tệ giống nhau | critical | dưới 2 chứng từ có trường |
| `agree_vendor_tax_code` | mã số thuế bên bán giống nhau | medium | dưới 2 chứng từ có trường |
| `agree_buyer` | bên mua giống nhau | medium | dưới 2 chứng từ có trường |
| `aggregate_total_amount` | tổng `total_amount` của các `purchase_order` bằng tổng của các `invoice` | critical | thiếu một trong hai loại |
| `line_item_unit_price` | đơn giá từng mặt hàng giống nhau giữa các chứng từ | high | dưới 2 chứng từ có bảng hàng |
| `line_item_missing` | mặt hàng có trong đơn đặt hàng, không có trong hoá đơn nào | high | thiếu `purchase_order` hoặc `invoice` |
| `line_item_extra` | mặt hàng có trong hoá đơn, không có trong đơn đặt hàng nào | high | thiếu `purchase_order` hoặc `invoice` |
| `invoiced_over_accepted` | tổng số lượng xuất hoá đơn vượt tổng số lượng nghiệm thu | critical | thiếu `invoice` hoặc `acceptance_record` |
| `accepted_over_ordered` | tổng số lượng nghiệm thu vượt tổng số lượng đặt hàng | high | thiếu `acceptance_record` hoặc `purchase_order`; mặt hàng ngoài đơn hàng |
| `date_order` | ngày đơn hàng ≤ ngày nghiệm thu ≤ ngày hoá đơn | medium | thiếu ngày |
| `po_reference_missing` | nhóm có số đơn hàng nhưng không có `purchase_order` nào | high | nhóm không có khoá |
| `trung_so_hieu` | hai chứng từ cùng loại mang cùng số hiệu | medium | loại không có trong `NUMBER_FIELD_BY_TYPE` |

Số lượng **không** so đôi một: giao hàng từng phần là hợp lệ, nên chỉ báo khi
tổng vượt. Các rule có nhắc tên loại (`purchase_order`, `invoice`,
`acceptance_record`) chỉ chạy với đúng các loại đó.

### 6.6 Các mục báo khác

| `rule_id` | Khi nào | Severity |
|---|---|---|
| `comparison_incomplete` | một chứng từ trong nhóm thiếu dữ liệu hoặc đã bị rút gọn; nhóm đó không được so tiếp | medium |
| `document_unlinked` | không xác định được chứng từ thuộc giao dịch nào (§6.2) | medium |
| `project_total_amount` | chạy trên toàn project khi có từ 2 nhóm: tổng `total_amount` của `purchase_order` khác tổng của `invoice` | critical |
| `po_number_co_the_ghi_nham` | có nhóm lệch tiền nhưng tổng toàn project khớp, nhiều khả năng ghi nhầm số đơn hàng | medium |

## 7. Cấu trúc `Discrepancy` (N document, không phải 2)

```json
{
  "rule_id": "anchor_total_amount_mismatch",
  "field": "total_amount",
  "severity": "high",
  "values": [
    { "document_id": "doc-a", "document_type": "purchase_order", "value": 125000000 },
    { "document_id": "doc-b", "document_type": "invoice",        "value": 128000000 }
  ],
  "difference": 3000000,
  "explanation": "Tổng tiền không khớp: Gốc=125,000,000 — Bên kia=128,000,000 lệch 3,000,000",
  "anchor_document_id": "doc-a",
  "source": "rule"
}
```

`values[]` chứa số lượng chứng từ bất kỳ, không dùng cặp `expected` / `actual`.
`anchor_document_id` chỉ có giá trị ở các mục so cặp với gốc; `confidence` chỉ
xuất hiện khi có giá trị. Danh sách trả về đã sắp theo severity (`critical`,
`high`, `medium`, `low`), rồi `rule_id`, rồi `field`.
