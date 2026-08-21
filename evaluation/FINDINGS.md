# Kết quả spike — vòng 2: chứng từ doanh nghiệp thật

**Ngày:** 2026-08-20 · **Dữ liệu:** 6 chứng từ thật do công ty cung cấp
(14 trang) · **Chi phí:** $0,021 (chỉ Enterprise Document OCR)

## 1. Chứng từ nhận được KHÔNG phải loại hệ thống đang thiết kế

Sáu file đều là **chứng từ vận tải biển**, không phải PO / hóa đơn GTGT /
biên bản nghiệm thu:

| File | Loại thật | Hãng |
|---|---|---|
| `BKGCONF_ASC0483717` | Booking Confirmation | CMA CGM |
| `BL2311728600` | Arrival Notice / Sea WayBill | OOCL |
| `BL6420901630` | Arrival Notice / Bill of Lading | COSCO |
| `HASLS21250901217` | Booking Notice | Heung-A Line |
| `NIHON CANPACK-SECLI…` | Thông báo hàng đến | AG Consolidation |
| `SG2514576` | Booking Receipt Notice | CK Line |

**Và chúng không đối chiếu được với nhau:** không có container, booking hay
B/L nào trùng — sáu lô hàng khác nhau, khách hàng khác nhau (Samsung SDS, LDC
Australia, Nihon Canpack…). Cross-check cần ≥2 chứng từ về **cùng một lô hàng**.

Ngài xác nhận đề tài **chủ yếu về hóa đơn**, nên bộ này chỉ dùng để **đo chất
lượng OCR**, chưa dùng cho phần trích xuất và đối chiếu.

## 2. Enterprise Document OCR trên chứng từ thật

Sáu file đều là **PDF sinh số** (có text layer), nên text nhúng sẵn trong file
đóng vai trò **đáp án đúng** — đo được độ chính xác mà không cần ground truth
viết tay.

| File | Trang | Confidence | Chính xác | Dấu tiếng Việt |
|---|---|---|---|---|
| BKGCONF_ASC0483717 | 5 | 0,964 | 99,2% | 1/1 |
| BL2311728600 | 2 | 0,975 | 98,8% | — |
| BL6420901630 | 3 | 0,971 | **100,0%** | 39/39 |
| HASLS21250901217 | 1 | 0,968 | 94,4% | — |
| NIHON CANPACK | 2 | 0,973 | 98,7% | 160/161 |
| SG2514576 | 1 | 0,972 | 94,4% | — |
| **Trung bình** | **14** | **0,970** | **97,6%** | **200/201 = 99,5%** |

**Dấu tiếng Việt đọc gần như tuyệt đối**: 200/201 từ có dấu khớp chính xác.

### Đính chính cách đo

Lần đo đầu cho 93,4%, trong đó hai file chỉ 80,6% và 88,6%. Xem kỹ thì **phần
lệch hầu hết không phải lỗi OCR**: text layer của PDF dính nhãn form vào giá trị
(`closing2025-10-17`, `09-october-25booking`, `2025-10-01date`) do file được
sinh bằng định vị tuyệt đối không có dấu cách, trong khi **OCR tách đúng** thành
`2025-10-17` + `closing`.

Tức OCR đọc **tốt hơn chính text layer của file**, còn thước đo lại phạt nó.
Đo lại bằng cách so không phân biệt khoảng trắng → **97,6%**.

Lỗi OCR thật rất ít, ví dụ `booking` → `poking` ở một chỗ.

## 3. So với vòng 1 (ảnh chụp điện thoại)

| | Ảnh chụp MC-OCR | Chứng từ thật (PDF sinh số) |
|---|---|---|
| Confidence trung bình | 0,942 | **0,970** |
| Loại đầu vào | ảnh nghiêng, mờ | PDF có text layer |

Chứng từ doanh nghiệp thật là **ca dễ hơn nhiều** so với ảnh chụp. Nghĩa là câu
hỏi "processor nào đọc tiếng Việt tốt hơn" **ít quan trọng hơn dự đoán** trên
loại dữ liệu này — Document OCR ($1,50/1.000 trang) đã đạt 97,6%.

## 4. Còn thiếu để chốt processor

Chưa chạy Form Parser và Layout Parser trên bộ này (~$0,56) nên **chưa so được**.
Nhưng với 97,6% và confidence 0,970 từ cái rẻ nhất, cần cân nhắc: hai cái đắt
hơn phải hơn được bao nhiêu mới đáng gấp 7–20 lần tiền?

Câu hỏi thật sự còn lại là **tách bảng** — line item của hóa đơn nằm trong bảng,
mà Document OCR không tách bảng. Chỉ trả lời được khi có **hóa đơn thật**.

---

# Kết quả spike — vòng 1

**Ngày:** 2026-08-17 · **Dữ liệu:** 5 ảnh MC-OCR 2021 (hóa đơn bán lẻ tiếng Việt,
chụp điện thoại) · **Chi phí:** $0,158 (Form Parser $0,15 + Document OCR $0,0075)

> Vòng này **chưa có ground truth**, nên chưa đo được độ chính xác tuyệt đối.
> Các so sánh dưới đây là đối chiếu output hai processor với nhau và đọc bằng
> mắt xem cái nào đúng tiếng Việt hơn. Đủ để định hướng, **chưa đủ để chốt**.

---

## 1. Hai bug production phát hiện nhờ chạy thật

Cả hai đều **không test nào bắt được** vì chỉ lộ khi gọi API thật. Nếu deploy
thẳng thay vì chạy spike thì pipeline chết ngay và rất khó truy nguyên.

### Bug 1 — `response_schema` rỗng làm Gemini luôn trả `data: {}`

`response_schema` khai `data` là `{"type": "OBJECT"}` **không có `properties`**.
Structured output hiểu là "object không có trường nào" → luôn trả `{}`.

| | output token | field trong `data` |
|---|---|---|
| Trước | 31 | **0** |
| Sau | 447 | **7 + 5 line item** |

Không thể khai schema cụ thể vì 1 call vừa classify vừa extract, chưa biết loại
chứng từ trước khi gọi. Ràng buộc kiểu để Pydantic ở `core/validate.py` lo.
Chặn tái phát: `tests/test_ai_config.py`.

### Bug 2 — parse Document AI sai hoàn toàn

Code v1 giả định mỗi phần tử có `.text`, và dùng tên `page.key_value_pairs`.
Thực tế Document AI trả **offset trong `text_anchor`** trỏ vào `document.text`,
và trường đúng tên là **`page.form_fields`**.
Chặn tái phát: `tests/test_docai_parse.py` (giả lập đúng hình dạng proto).

---

## 2. Form Parser vs Enterprise Document OCR

| Ảnh | ký tự FP/OCR | conf TB FP/OCR | key-value FP/OCR | bảng FP/OCR |
|---|---|---|---|---|
| anqqj | 672 / 676 | 0,943 / **0,966** | 16 / 0 | 2 / 0 |
| aszbc | 555 / 560 | 0,882 / **0,933** | 13 / 0 | 1 / 0 |
| babwd | 855 / 862 | 0,893 / **0,945** | 13 / 0 | 4 / 0 |
| budzl | 687 / 636 | 0,827 / **0,918** | 2 / 0 | 5 / 0 |
| cijwj | 484 / 470 | 0,861 / **0,951** | 11 / 0 | 4 / 0 |
| **TB** | | **0,881 / 0,942** | | |

**Giá:** Form Parser $0,03/trang · Document OCR **$0,0015/trang** (rẻ 20 lần).
**Tốc độ:** 6,6s vs 3,7s trên cùng ảnh.

### Khác biệt text cụ thể (ảnh budzl)

| Form Parser | Document OCR | Nhận xét |
|---|---|---|
| `Chợ Sùi Phi Thị Gia Lâm` | `Chợ Sửi Phú Thị Gia Lâm` | OCR đúng, FP sai 2 dấu |
| `Sữa túi firo dâu` | `Sữa túi fino dâu` | OCR đúng, FP đọc n→r |
| `SL` `DVT` rời, mất dấu | `SL ĐVT Đơn giá Thành tiến` | OCR giữ được chữ Đ |

Cả hai cùng sai `Thành tiến` (đúng: "Thành tiền").

### Bảng và key-value của Form Parser trên loại ảnh này: kém

```
| # Item\nQty\n1 Mango | Discount\nTotal\n70, |
| Tea |  |
```
Nhiều key-value thực chất là header bảng bị hiểu nhầm:
`Tên hàng = SL DVT Đơn giá Thành` (conf 0,384).

**Tức là thứ khiến Form Parser đắt gấp 20 lần lại là phần kém nhất trên input này.**

---

## 3. Confidence: dùng của OCR, KHÔNG dùng của LLM

Xếp key-value theo confidence tăng dần — các mục thấp nhất **đúng là các mục
đọc sai**:

```
0,384  Tên hàng        = SL DVT Đơn giá Thành    <- header bảng hiểu nhầm
0,402  ơn giá          = SL vi bơ 80gt56 22.0    <- mất chữ Đ
0,406  TIẾN TRẢ LẠI    = 350.900                 <- đúng là "TIỀN"
0,436  CHANGE (VND)    = Ο                       <- đọc nhầm ký tự
```

Đối chiếu Gemini tự khai confidence: **0,9–1,0** cho cùng loại dữ liệu, và
**đổi giữa hai lần chạy trên cùng ảnh dù `temperature=0`**.

**Kết luận:** confidence do LLM tự khai không ổn định và không hiệu chỉnh →
không dùng làm ngưỡng cảnh báo trong Human Review. Dùng `confidence` từ
Document AI (`mean_token_confidence` và confidence từng form field), đã được
thêm vào output parse.

---

## 4. Còn thiếu để chốt được

1. **Ground truth** cho 5 ảnh này → mới đo được độ chính xác thật thay vì đối
   chiếu bằng mắt.
2. **Chứng từ đúng loại** — PO / hóa đơn GTGT / biên bản nghiệm thu, có bảng kẻ
   ô đàng hoàng. Hóa đơn bán lẻ chụp điện thoại là **ca xấu nhất** cho khả năng
   tách bảng của Form Parser; trên chứng từ có cấu trúc nó có thể thắng.
3. **Layout Parser** ($10/1.000) chưa đo — nó là cái duy nhất xử lý được bảng
   merge cell.

## 5. Hướng nghiêng hiện tại

Giả định ban đầu "Form Parser xứng đáng $30/1.000" **chưa được dữ liệu ủng hộ**:
OCR text kém hơn, chậm hơn, đắt hơn 20 lần, và phần giá trị gia tăng (bảng,
key-value) thì hỏng trên input này.

**Chưa đổi production.** Cần chứng từ đúng loại rồi đo lại. Nhưng nếu kết quả
giữ nguyên xu hướng thì đổi sang Document OCR chỉ là sửa một biến môi trường
`DOCAI_PROCESSOR_ID` — không đụng code.
