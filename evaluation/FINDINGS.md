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
