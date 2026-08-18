# Frontend — dashboard đối soát chứng từ

React 19 + TypeScript + Vite + Tailwind v4. Hai màn hình, không dùng thư viện
state management.

## Chạy

Cần **hai** terminal — frontend gọi API của dev server:

```powershell
# 1. Backend
cd backend
.venv\Scripts\python.exe -m devserver --slow 2

# 2. Frontend
cd frontend
npm install      # lần đầu
npm run dev
```

Mở http://localhost:5173

`--slow 2` giả lập độ trễ AI để nhìn rõ thanh tiến trình nhích từng bước.
Bỏ đi thì chạy gần như tức thì.

Backend ở nơi khác thì tạo file `.env`:
```
VITE_API_URL=http://127.0.0.1:8000
```

## ⚠ Dev server dùng AI GIẢ

Mặc định `devserver` **không đọc nội dung file thật** — nó trả một bộ dữ liệu mẫu
cố định để việc làm giao diện không tốn tiền Document AI. Tải một PDF thật lên
vẫn ra "ABC Technology / Laptop Dell XPS 13".

UI hiện **băng vàng cảnh báo** ở đầu trang khi gặp trường hợp này. Muốn kết quả
thật từ file thật:

```powershell
cd backend
.venv\Scripts\python.exe -m devserver --real-ai
```

Cần credential trong `evaluation/.env`, và **có tính phí** (~$0,03/trang với
Form Parser). Băng cảnh báo sẽ tự biến mất.

Frontend biết được nhờ gọi `GET /__dev__` — route **chỉ dev server có**;
production trả 404 nên không bao giờ hiện băng.

## Hai màn hình

**`/`** — danh sách project dạng lưới card. Trên card chỉ có tên và icon xoay
khi đang xử lý.

**`/projects/:id`** — workspace hai khung:

- **Sidebar trái**: chỉ danh sách chứng từ (icon + tên) và nút Xử lý dưới cùng.
  Cố ý **không** có thanh tiến độ ở đây.
- **Khung phải**: mọi thứ còn lại. Đang xử lý thì hiện sơ đồ tiến trình; xong thì
  chuyển sang 4 tab.

| Tab | Nội dung |
|---|---|
| **Tài liệu** | file gốc nhúng iframe (PDF) hoặc thẻ img (ảnh) |
| **Kết quả OCR** | text OCR đọc được + các trường AI trích ra, đặt cạnh nhau |
| **Cảnh báo** | mâu thuẫn xếp theo mức nghiêm trọng, nút duyệt/từ chối |
| **Sửa** | sửa tay, tô vàng trường confidence thấp, lưu xong tự đối soát lại |

Tab **Kết quả OCR** đặt "OCR đọc ra gì" cạnh "AI hiểu thành gì" để biết lỗi nằm
ở khâu đọc hay khâu hiểu — hai khâu đó sửa bằng hai cách khác nhau.

## Upload dùng presigned POST, không phải PUT

Đây là điểm dễ làm sai nhất, xem [`src/api.ts`](src/api.ts) `uploadFile()`.

```
POST /projects/{id}/documents  ->  { upload: { url, fields }, max_bytes }
POST <upload.url>  body = FormData(fields... + file)
```

Hai lý do dùng POST:

1. **POST + `multipart/form-data` là "simple request"** theo CORS nên trình
   duyệt **không gửi preflight `OPTIONS`**. Presigned PUT thì có, và preflight
   đó bị S3 giả lập từ chối (nó đòi chữ ký trên `OPTIONS`, S3 thật thì không).
2. Chỉ POST mới đặt được `content-length-range` để **giới hạn kích thước file**.
   Presigned PUT không giới hạn được.

**Thứ tự trong FormData quan trọng**: mọi trường trong `fields` phải append
**trước** `file`. S3 bỏ qua tất cả những gì đứng sau `file`.

## Tiến độ

[`src/hooks/useProject.ts`](src/hooks/useProject.ts) poll `GET /projects/{id}`
mỗi 2 giây, **tự dừng** khi `run.is_active` false.

Thanh tiến độ đọc `progress.progress_percent` — backend tính theo **bước**
(mỗi chứng từ 3 bước), không theo số chứng từ, nên nó nhích đều thay vì đứng im
rồi nhảy. Mỗi dòng chứng từ hiện bước đang chạy, và hiện "thử lại lần N" khi
`attempt > 1` (lúc Gemini trả 429).

## Tô vàng chỗ AI đọc không chắc

Hộp thoại sửa tô vàng trường có `confidence` dưới **0,75**
([`src/format.ts`](src/format.ts) `LOW_CONFIDENCE`).

Đây là confidence **từ OCR**, không phải do LLM tự khai. Spike đo được: các
trường confidence 0,38–0,44 đúng là các trường đọc sai, trong khi LLM tự chấm
mình 0,9–1,0 cho cùng loại dữ liệu và còn đổi giá trị giữa hai lần chạy.
Xem [`evaluation/FINDINGS.md`](../evaluation/FINDINGS.md).

## Cấu trúc

```
src/
  types.ts      kiểu response API — cũng là tài liệu API
  api.ts        12 endpoint + uploadFile() + getDevMeta()
  format.ts     tiền VND, ngày, nhãn tiếng Việt, màu theo mức nghiêm trọng
  hooks/useProject.ts
  pages/        ProjectList, ProjectDetail
  components/   DocumentSidebar  WorkflowView  DocumentViewer
                OcrPanel  EditPanel  DiscrepancyCard
                ProgressBar  FakeAiBanner
```

## Lệnh

```powershell
npm run dev         # dev server
npm run typecheck   # tsc --noEmit
npm run build       # ra thư mục dist/
```

## Chưa làm

Đăng nhập · xem trước PDF trong trang · phân trang · xoá project · dark mode ·
deploy lên S3/CloudFront (làm cùng `terraform apply`).
