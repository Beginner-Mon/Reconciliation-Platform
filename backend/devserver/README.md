# Dev server — chạy toàn bộ backend ở máy

Dựng đủ 12 endpoint ở `localhost`, **không cần AWS**. Dùng để làm frontend và
click thử luồng nghiệp vụ trước khi deploy.

```powershell
cd backend
.venv\Scripts\python.exe -m devserver --upload ..\evaluation\dataset\documents
```

```
API          : http://127.0.0.1:8000
AWS giả lập  : http://127.0.0.1:5000   (moto server)
```

## AWS thì giả, AI thì THẬT

Chỉ hạ tầng AWS được giả lập. Document AI và Gemini **luôn được gọi thật, và
luôn tốn tiền thật**. Không có chế độ dữ liệu mẫu.

Từng có, và đã bị gỡ: AI giả trả cùng một bộ "ABC Technology / Laptop Dell XPS
13" cho mọi file. Nhìn vào giao diện thì **không phân biệt được với hệ thống
hỏng**. Một băng cảnh báo màu vàng cũng không đủ — vẫn mất hàng giờ đi tìm bug
không tồn tại. Nên bây giờ chỉ còn một chế độ.

Hệ quả: **thiếu credential thì dev server thoát ngay lúc khởi động** (exit 2),
in rõ thiếu biến nào. Không có đường lui.

Điền vào `evaluation/.env` (đã gitignore):
`DOCAI_PROJECT`, `DOCAI_OCR_PROCESSOR_ID`, `GEMINI_API_KEY`,
`GOOGLE_APPLICATION_CREDENTIALS`.

## Tuỳ chọn

| Cờ | Ý nghĩa |
|---|---|
| `--processor {dococr,formparser,layout}` | processor Document AI, mặc định `dococr` |
| `--upload <thư mục>` | tạo project + upload sẵn file thật trong thư mục (**không** xử lý, nên $0) |
| `--port` / `--aws-port` | đổi cổng (mặc định 8000 / 5000) |
| `--quiet` | không in từng request |

## Chi phí

Processor và **đơn giá đi cùng một chỗ** trong `PROCESSORS` ở `__main__.py`.
Tách hai thứ đó ra là chỗ đã sai một lần: ước tính chi phí lệch **20 lần** vì
lấy đơn giá Form Parser gán cho Enterprise Document OCR.

| `--processor` | Processor | $/trang | 6 chứng từ mẫu (14 trang) |
|---|---|---|---|
| `dococr` *(mặc định)* | Enterprise Document OCR | $0,0015 | **$0,021** |
| `layout` | Layout Parser | $0,010 | $0,14 |
| `formparser` | Form Parser | $0,030 | $0,42 |

Cộng thêm ~$0,01 tiền Gemini cho bước trích xuất.

**Chạy lại không tốn thêm tiền:** `/process` bỏ qua document đã `VALIDATED`
(§1 CLAUDE.md). Chỉ `force=true` mới xử lý lại. Cơ chế chống tính tiền lặp nằm
ở DynamoDB + S3, không cần cache riêng nào ở tầng dev.

## Vì sao cần moto ở chế độ SERVER, không phải in-process

Luồng upload là: API trả presigned POST URL → frontend POST **thẳng lên S3**.
Nếu dùng `mock_aws()` in-process như trong test thì presigned URL sinh ra trỏ về
**AWS thật** và frontend không upload được. Chạy moto như một HTTP server thì URL
trỏ về `localhost:5000` và dùng được thật.

## Dev và Cloud tách biệt thế nào

`devserver/` là nơi **duy nhất** biết mình đang chạy ở dev. Không có `if dev:`
nào trong `api/`, `workers/`, `core/`, `common/`, `schemas/`.

| Tầng | Dev | Cloud |
|---|---|---|
| `core/`, `schemas/`, `api/`, `workers/`, `common/` | **y hệt** | **y hệt** |
| Vận chuyển | `http_server.py` | API Gateway |
| Điều phối | `pipeline.py` | Step Functions |
| Hạ tầng AWS | moto server | AWS thật |
| AI | **Document AI + Gemini thật** | Document AI + Gemini |

Chuyển môi trường chỉ bằng biến môi trường:
`AWS_ENDPOINT_URL` có → moto; không có → AWS thật.

`infra/scripts/build_backend.ps1` chỉ đóng gói `schemas core common workers api`,
nên `devserver/` **không thể** lọt vào Lambda zip.

## Điều phối đọc từ ASL, không hardcode

`pipeline.py` đọc `infra/modules/aws/statemachine.asl.json` để lấy thứ tự bước
và nhánh `Catch`. Thêm state vào ASL thì dev tự chạy theo; state chưa có worker
tương ứng sẽ **báo lỗi ngay lúc khởi động**. `tests/test_devserver.py` chặn
việc này offline.

**Giới hạn — không phải state machine thật:** không có Retry/backoff/jitter,
không có `TimeoutSeconds` từng state, chạy tuần tự không mô phỏng
`MaxConcurrency`. Muốn verify hành vi thật của ASL thì dùng
[`infra/statemachine-test/`](../../infra/statemachine-test/).

## Cho frontend

Base URL `http://127.0.0.1:8000`, CORS mở sẵn cho mọi origin, `OPTIONS`
preflight trả 204.

```
POST   /projects                                  tạo project
GET    /projects                                  danh sách
GET    /projects/{id}                             chi tiết + tiến độ  (poll 2s)
POST   /projects/{id}/documents                   xin presigned POST URL
GET    /projects/{id}/documents/{doc_id}/ocr      text OCR thô + confidence từng dòng
GET    /projects/{id}/documents                   danh sách document
POST   /projects/{id}/process                     chạy xử lý (skip doc đã xong)
POST   /projects/{id}/reconcile                   đối chiếu lại
PATCH  /projects/{id}/documents/{doc_id}          sửa tay + đối chiếu lại
GET    /reconciliations/{id}                      kết quả đối chiếu đầy đủ
POST   /reconciliations/{id}/approve | /reject    duyệt / từ chối
```

Tiến độ nằm ở `GET /projects/{id}` → `progress.progress_percent` (tính theo
**bước**, mỗi document 3 bước) và `documents[].step` / `.step_status` /
`.attempt`. Dừng poll khi `run.is_active` là `false`.

## Dữ liệu không được giữ lại

moto server giữ mọi thứ trong RAM. Tắt dev server là mất sạch project, document,
file — và **xử lý lại sẽ tốn tiền OCR lại**, vì kết quả cũ nằm trong S3 giả lập
cũng mất theo.

Dùng `--upload <thư mục>` để khỏi phải kéo tay từng file sau mỗi lần khởi động.
