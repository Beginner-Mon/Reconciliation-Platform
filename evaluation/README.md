# Spike test chất lượng AI + Evaluation

Trả lời câu hỏi quyết định kiến trúc: **dùng processor Document AI nào?**

> **Production chỉ dùng MỘT processor.** [`workers/ocr.py`](../backend/workers/ocr.py)
> có đúng một lời gọi `ocr_with_document_ai()`, hiện trỏ tới Form Parser qua
> `DOCAI_PROCESSOR_ID`. Thư mục này chạy nhiều processor trên **cùng một ảnh**
> chỉ để so sánh rồi **chọn một** — giống thử ba cái thước trên cùng một vật.
> Đo xong, production vẫn một.
>
> Ngài **không cần tạo cả ba processor**. Tạo một cái, chạy `--ocr <tên>`.

## Câu hỏi spike phải trả lời

**Hệ thống đang trả $30/1.000 trang cho Form Parser rồi vứt đi đúng cái làm nó đắt.**

Form Parser đắt hơn Enterprise Document OCR 20 lần vì nó cho thêm key-value
pairs, bảng và selection mark. Nhưng [`_build_ocr_text()`](../backend/common/ai_clients.py)
gộp tất cả thành một chuỗi phẳng nhét vào prompt rồi để Gemini trích xuất lại
từ đầu — key-value pairs không được dùng như dữ liệu có cấu trúc.

> Key-value pairs của Form Parser có làm Gemini trích xuất chính xác hơn **đủ để
> bù 20 lần chi phí** không?

### Bảng giá Document AI ([nguồn](https://cloud.google.com/document-ai/pricing), kiểm tra 2026-08-17)

| Processor | $/1.000 trang | Cho ra gì |
|---|---|---|
| **Enterprise Document OCR** | **$1,50** | text + **bounding box** block/dòng/từ/symbol, checkbox, font |
| Layout Parser | $10 | + cấu trúc layout |
| **Form Parser** (đang dùng) | **$30** | + key-value pairs, bảng, selection mark |
| Custom Extractor | $30 | + **phát hiện chữ ký** |

Gemini 2.5 Flash: $0,30/1M input, $2,50/1M output, **có free tier**
([nguồn](https://ai.google.dev/gemini-api/docs/pricing)).

Với dataset 100 tài liệu × 2 trang: Form Parser **$6,34** so với Document OCR
**$0,37** — cùng một chất lượng OCR, cùng có toạ độ.

## Năng lực từng processor — cái nào mất gì

| | Document OCR $1,50 | Layout Parser $10 | Form Parser $30 |
|---|---|---|---|
| Text + bounding box | ✅ | ✅ | ✅ |
| **Chữ viết tay** | ✅ **best-in-class, 50 ngôn ngữ** | — | không nêu |
| Checkbox | ✅ | — | ✅ selection mark |
| **Bảng** | ❌ | ✅ **bảng phức tạp, merge cell** | ✅ chỉ bảng đơn giản |
| **Trường điền form (key-value)** | ❌ | ❌ | ✅ |
| Phát hiện chữ ký | ❌ | ❌ | ❌ (chỉ Custom Extractor) |

Đáng chú ý: **chữ viết tay là thế mạnh của cái RẺ nhất**, không phải cái đắt nhất.
Ngược lại, **bảng và trường điền form là thứ Document OCR không có** — mà line
item của PO/hóa đơn lại nằm trong bảng. Đây chính là lý do phải đo chứ không đoán.

## Năm luồng đem so

| Tên | Mô tả | Env cần thêm |
|---|---|---|
| `formparser_gemini` | Form Parser → Gemini (**luồng hiện tại**) | `DOCAI_PROCESSOR_ID` |
| `layout_gemini` | Layout Parser → Gemini. Bảng phức tạp, giá giữa | `DOCAI_LAYOUT_PROCESSOR_ID` |
| `dococr_gemini` | Document OCR → Gemini. Rẻ nhất, **không có bảng/KV** | `DOCAI_OCR_PROCESSOR_ID` |
| `formparser_kv_only` | Chỉ key-value Form Parser, không gọi LLM | `DOCAI_PROCESSOR_ID` |
| `gemini_direct` | Gemini đọc thẳng file, **không có OCR** | — |

**`gemini_direct` là mốc so sánh, KHÔNG phải ứng viên.** Không toạ độ, không
confidence từng từ, có thể bịa, và yếu đúng ở chỗ OCR chuyên dụng mạnh: bảng,
trường điền, chữ tay. Chạy nó chỉ để có một con số trả lời "bỏ hẳn OCR thì sao".

`formparser_kv_only` gần như chắc chắn thua, chạy để trả lời "Form Parser tự nó
đã đủ chưa".

## Nhận dạng chữ ký (yêu cầu tương lai)

Document AI **có** phát hiện chữ ký, nhưng chỉ trong **Custom Extractor**
(pretrained-foundation-model v1.4/v1.5, $30/1.000 trang). Giới hạn cần biết
trước: nó nhận biết **có chữ ký hay không** bằng thị giác và **không trả về
`textAnchor`/`pageAnchor`** — tức **không cho toạ độ chữ ký**
([tài liệu](https://docs.cloud.google.com/document-ai/docs/ce-derived-signature)).

**Form Parser không làm chữ ký.** Nên yêu cầu chữ ký không phải lý do giữ Form
Parser — nó là lý do thêm một Custom Extractor chạy **song song** với OCR ở giai
đoạn sau, trả tiền đúng cho những tài liệu cần kiểm chữ ký (biên bản nghiệm thu)
thay vì trả cho mọi trang.

## Chuẩn bị dataset

```
evaluation/dataset/
  documents/     <- file gốc: .pdf .png .jpg .jpeg .tiff
  ground_truth/  <- mỗi file 1 JSON CÙNG TÊN, ví dụ INV-001.pdf -> INV-001.json
```

**Thư mục `dataset/` đã gitignore** — không phân phối lại dữ liệu bên thứ ba
(MC-OCR) lẫn chứng từ thật của doanh nghiệp qua repo. Mỗi người tự tải về theo
hướng dẫn bên dưới.

Ground truth viết đúng schema ở `docs/schemas.md`. Điền **giá trị đúng do người
đọc xác nhận**, không phải kết quả của AI:

```json
{
  "document_type": "invoice",
  "invoice_number": "INV-001",
  "invoice_date": "2026-08-05",
  "vendor": "Công ty TNHH ABC Technology",
  "vendor_tax_code": "0301234567",
  "buyer": "Công ty TNHH XYZ",
  "currency": "VND",
  "po_number": "PO-2026-001",
  "items": [
    { "item_name": "Laptop Dell XPS 13", "quantity": 100,
      "unit": "cái", "unit_price": 1250000 }
  ],
  "subtotal": 125000000,
  "tax_rate": 0.08,
  "tax_amount": 10000000,
  "total_amount": 135000000
}
```

**Không dùng dữ liệu nhạy cảm** (rule cứng của project). Chứng từ thật phải được
ẩn danh: đổi tên công ty, mã số thuế, số tiền trước khi bỏ vào đây.

Bắt đầu với **5–10 tài liệu** đủ để chốt hướng. Dataset đầy đủ 50–100 tài liệu
là deliverable riêng, làm sau.

### Bắt buộc: dataset phải có CẢ HAI loại chất lượng

| Loại | Ví dụ | Vai trò |
|---|---|---|
| **Sinh số (digital-born)** | PDF hóa đơn điện tử tải từ nhà cung cấp | Ca dễ. Mọi OCR đều ~99% |
| **Ảnh chụp / scan** | Chụp điện thoại, scan lệch, mờ, bóng | **Ca quyết định** |

Nếu dataset chỉ có PDF sinh số thì mọi luồng đều gần 100% và spike **không kết
luận được gì** — khác biệt giữa Document OCR và Form Parser chỉ lộ ra trên ảnh
chụp thật. Đây là lỗi phương pháp dễ mắc nhất.

### Bước 0 — chỉ xem OCR trả về gì (chưa cần ground truth)

Trước khi chấm điểm, nên nhìn tận mắt output thô. `inspect_ocr.py` **không chấm
điểm, không validate, không cross-check** — chỉ chạy OCR và in ra những gì nhận
được, kèm **đúng đoạn text mà Gemini thực sự nhận**:

```powershell
cd evaluation

# XEM OCR THẬT trả về gì — KHÔNG gọi Gemini một lần nào:
..\backend\.venv\Scripts\python.exe inspect_ocr.py --all --ocr-only

# chỉ một engine
..\backend\.venv\Scripts\python.exe inspect_ocr.py --all --ocr dococr --ocr-only

# bỏ --ocr-only thì chạy tiếp Gemini để xem nó trích xuất ra JSON gì
..\backend\.venv\Scripts\python.exe inspect_ocr.py duong_dan\tai_lieu.jpg
```

### Chi phí — chỉ trả tiền OCR MỘT lần cho mỗi ảnh

Kết quả OCR được **cache ra đĩa** (`results/ocr-cache/`), key = sha256 nội dung
file + tên engine. Cùng ảnh cùng processor thì lần chạy sau **không gọi API,
không tốn tiền**. Sửa 1 byte trong file thì cache tự trượt.

Nhờ vậy sửa prompt rồi chấm điểm lại bao nhiêu lần cũng chỉ tốn phần gọi LLM
(Gemini có free tier), không tốn lại tiền OCR.

```powershell
..\backend\.venv\Scripts\python.exe inspect_ocr.py --all --ocr-only      # lần 2 trở đi: $0
..\backend\.venv\Scripts\python.exe inspect_ocr.py --all --refresh       # ép gọi lại, TỐN TIỀN
..\backend\.venv\Scripts\python.exe inspect_ocr.py --clear-cache         # xoá cache
```

Cuối mỗi lần chạy in ra `OCR: N lần gọi API, M lần dùng cache (miễn phí)`.

Chi phí thật cho 5 ảnh, **chỉ lần đầu**: Form Parser $0,15 · Layout Parser $0,05 ·
Document OCR **$0,0075**. Tài khoản GCP mới có $300 credit.

### Engine nào cần gì

| Engine | Là gì | Cần |
|---|---|---|
| `dococr` | Enterprise Document OCR — **OCR thật** | `DOCAI_PROJECT` + `DOCAI_OCR_PROCESSOR_ID` + đăng nhập GCP |
| `formparser` | Form Parser — **OCR thật** | `DOCAI_PROJECT` + `DOCAI_PROCESSOR_ID` + đăng nhập GCP |
| `layout` | Layout Parser — **OCR thật** | `DOCAI_PROJECT` + `DOCAI_LAYOUT_PROCESSOR_ID` + đăng nhập GCP |
| `gemini_direct` | **KHÔNG PHẢI OCR** — Gemini nhìn thẳng ảnh | `GEMINI_API_KEY` |

**Ba engine OCR không dùng Gemini.** `GEMINI_API_KEY` chỉ cần cho bước trích
xuất (bỏ qua bằng `--ocr-only`) và cho `gemini_direct`. Thiếu engine nào thì báo
rõ rồi bỏ qua, không hỏng cả lần chạy.

In ra: số trang, số ký tự text, **số key-value**, **số bảng**, 25 dòng text đầu,
10 cặp key-value đầu, 6 dòng bảng đầu, rồi đoạn prompt gửi cho Gemini và JSON
Gemini trả về. Bản đầy đủ lưu ở `results/inspect/`.

Đây là cách nhanh nhất thấy được điều quan trọng: **Document OCR trả `bảng: 0`
và `key-value: 0`**, còn Form Parser thì có — tận mắt thay vì đọc tài liệu.

### Nguồn lấy tài liệu

1. **Công ty thực tập** — nguồn tốt nhất và nên hỏi đầu tiên. Chỉ nơi này mới có
   đúng loại chứng từ (PO / hóa đơn / biên bản nghiệm thu), đúng chất lượng
   scan thực tế, đúng nghiệp vụ. Phải ẩn danh trước khi đưa vào repo.
2. **MC-OCR 2021** — 2.436 hóa đơn bán lẻ tiếng Việt **chụp bằng điện thoại**:
   [Kaggle](https://www.kaggle.com/datasets/domixi1989/vietnamese-receipts-mc-ocr-2021) ·
   [trang gốc RIVF2021](https://rivf2021-mc-ocr.vietnlp.com/).
   Chỉ có 4 trường (SELLER, ADDRESS, TIMESTAMP, TOTAL) nên **không dùng để đo
   extraction theo schema của mình**, nhưng là nguồn tốt nhất để đo **OCR đọc
   dấu tiếng Việt trong điều kiện ảnh chụp thật**.
   Bản đã gắn nhãn thêm: [5CD-AI/Viet-Receipt-VQA](https://huggingface.co/datasets/5CD-AI/Viet-Receipt-VQA)
   (2.034 ảnh từ chính MC-OCR, có mô tả và KIE).
3. **[Receipt OCR Vietnamese](https://www.kaggle.com/datasets/blyatfk/receipt-ocr)** —
   hóa đơn tiếng Việt trên Kaggle, nguồn thay thế MC-OCR.
4. **[5CD-AI/Viet-OCR-VQA](https://huggingface.co/datasets/5CD-AI/Viet-OCR-VQA)** —
   137k ảnh có chữ tiếng Việt, gồm cả **văn bản hành chính**. Dùng để lấy vài
   trang có dấu má và bố cục hành chính, không phải hóa đơn.
5. **Chữ viết tay tiếng Việt** — cần cho biên bản nghiệm thu có ghi chú tay:
   [5CD-AI/Viet-Handwriting-OCR](https://huggingface.co/datasets/5CD-AI/Viet-Handwriting-OCR)
   (23.403 ảnh) hoặc bộ **Cinnamon AI Marathon** (1.838 ảnh, xem
   [repo tham chiếu](https://github.com/TomHuynhSG/Vietnamese-Handwriting-Recognition-OCR)).
6. **Mẫu hóa đơn điện tử của nhà cung cấp VN** (Viettel Invoice, VNPT Invoice,
   MISA meInvoice, BKAV, EasyInvoice) — PDF mẫu công khai, sinh số, ca dễ.
7. **Mẫu biểu theo quy định** — hóa đơn điện tử theo Nghị định 123/2020/NĐ-CP và
   Thông tư 78/2021/TT-BTC; biểu mẫu kế toán theo Thông tư 200/2014/TT-BTC;
   biên bản nghiệm thu theo Nghị định 06/2021/NĐ-CP. Điền dữ liệu giả vào mẫu.
8. **Tự sinh** — chỉ dùng để kiểm harness chạy đúng. PDF sinh bằng code có text
   layer sạch, **số đo sẽ đẹp giả** và không quyết định được gì.

**Lưu ý về các dataset công khai:** chúng là **hóa đơn bán lẻ** (receipt), không
phải hóa đơn GTGT / PO / biên bản nghiệm thu. Dùng để đo **OCR đọc tiếng Việt**
thì rất tốt; để đo **extraction theo schema của project** thì vẫn phải có chứng
từ đúng loại từ nguồn 1.

## Đặt credential — điền vào file `.env`

```powershell
cd evaluation
Copy-Item .env.example .env
notepad .env          # điền giá trị, xem chú thích ngay trong file
```

`.env` đã được gitignore. **Không commit, không dán nội dung vào chat.**
Script tự nạp file này; dòng nào còn `<...>` thì bỏ qua, không gây lỗi.
Muốn tạm ghi đè một biến thì `$env:X = "..."` — biến môi trường thắng `.env`.

### Lấy từng giá trị ở đâu

| Biến | Lấy ở đâu |
|---|---|
| `GEMINI_API_KEY` | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) → Create API key. **Miễn phí, không cần thẻ, không cần project GCP** |
| `DOCAI_PROJECT` | [console.cloud.google.com](https://console.cloud.google.com/) → ô chọn project → cột **ID** (không phải tên hiển thị, không phải number) |
| `DOCAI_LOCATION` | `us` hoặc `eu` — phải trùng vùng lúc tạo processor |
| `GOOGLE_APPLICATION_CREDENTIALS` | Để trống nếu chạy `gcloud auth application-default login` (khuyến nghị, không có file key để lộ). Hoặc đường dẫn file key service account JSON |
| `DOCAI_*_PROCESSOR_ID` | [Processor library](https://console.cloud.google.com/ai/document-ai/processor-library) → chọn loại → **Create** → copy phần **ID** |

Trước khi tạo processor phải bật Document AI API:
```powershell
gcloud services enable documentai.googleapis.com --project=<project-id>
```

Chỉ cần `GEMINI_API_KEY` là đã chạy được luồng `gemini_direct`. Mỗi processor
tạo thêm mở khoá thêm một luồng — không cần đủ cả ba.

**Chi phí thử vài file:** 5 trang qua Form Parser ≈ $0,15; qua Document OCR
≈ $0,0075. Tài khoản GCP mới có $300 credit dùng thử.

Gemini **có free tier** — spike 5–10 tài liệu nhiều khả năng không tốn đồng nào.

## Chạy

```powershell
cd evaluation
..\backend\.venv\Scripts\python.exe run_spike.py --dry-run        # xem sẽ chạy gì
..\backend\.venv\Scripts\python.exe run_spike.py --flows gemini_direct
..\backend\.venv\Scripts\python.exe run_spike.py                  # mọi luồng đủ credential
```

Luồng nào thiếu credential sẽ bị bỏ qua kèm lý do, không làm hỏng cả lần chạy.

## Đọc kết quả

```
luồng                   chính xác   bỏ dấu  classify     $/doc  giây/doc
gemini_direct                92.3%    94.1%    100.0%   0.00061       3.4
formparser_gemini            93.8%    95.2%    100.0%   0.06340       9.1
```

- **chính xác** — khớp tuyệt đối, tính trên tổng số field của ground truth
- **bỏ dấu** — tính cả trường hợp chỉ sai dấu tiếng Việt. Khoảng cách giữa hai
  cột này chính là **thiệt hại do OCR sai dấu**
- **classify** — đoán đúng `document_type`
- **field hay sai nhất** — in kèm, chỉ ra nên sửa prompt ở đâu

Chi tiết từng tài liệu ở `results/<luồng>.json`.

## Quyết định thế nào

Mốc là `formparser_gemini` (luồng hiện tại). Nhìn **`field_hay_sai`** chứ không
chỉ nhìn con số tổng:

| Kết quả quan sát | Kết luận |
|---|---|
| `dococr_gemini` chênh dưới ~2 điểm | **Đổi sang Document OCR.** Rẻ 20 lần, và chứng tỏ Gemini tự dựng lại được line item từ text thuần |
| `dococr_gemini` thua rõ, lỗi **tập trung ở `items.*`** | Đúng như dự đoán: mất cấu trúc bảng. So tiếp `layout_gemini` — nếu nó bắt kịp Form Parser thì chọn nó ($10 thay vì $30) |
| `layout_gemini` ≥ `formparser_gemini` | **Chọn Layout Parser.** Rẻ hơn 3 lần và xử lý được bảng merge cell mà Form Parser chịu thua |
| Form Parser thắng rõ ở mọi mặt | Giữ nguyên. Ghi vào báo cáo: trả thêm 20 lần chi phí đổi lấy bao nhiêu điểm chính xác |
| Chứng từ có **chữ viết tay** đọc kém ở mọi luồng | Cân nhắc chạy Document OCR **song song** riêng cho phần chữ tay (nó best-in-class khoản này) |

Đổi processor thì **phải** đổi `DOCAI_USD_PER_PAGE` trong Lambda env, nếu không
chi phí ghi vào `audit_log` sẽ sai — rule cứng của project yêu cầu lưu vết chi
phí đúng.

Khoảng cách giữa cột **chính xác** và **bỏ dấu** cho biết OCR đọc dấu tiếng Việt
tệ đến đâu. Nếu khoảng cách này lớn ở mọi luồng thì vấn đề nằm ở chất lượng ảnh
đầu vào, không phải ở lựa chọn processor.

Dù chọn hướng nào, ghi số đo vào báo cáo kỹ thuật — đây là loại bằng chứng đề
tài yêu cầu, không được thay bằng demo thủ công.
