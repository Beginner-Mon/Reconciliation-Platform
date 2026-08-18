# Dev server — chạy toàn bộ backend ở máy

Dựng đủ 11 endpoint ở `localhost`, **không cần AWS, không cần Google, không tốn
tiền**. Dùng để làm frontend và click thử luồng nghiệp vụ trước khi deploy.

```powershell
cd backend
.venv\Scripts\python.exe -m devserver
```

```
API          : http://127.0.0.1:8000
AWS giả lập  : http://127.0.0.1:5000   (moto server)
```

Mở lên là có sẵn một project demo với 3 chứng từ đã upload — bấm `/process` là
chạy được ngay.

## Tuỳ chọn

| Cờ | Ý nghĩa |
|---|---|
| `--slow 2` | giả lập độ trễ AI 2 giây mỗi bước, để nhìn rõ trạng thái `running` khi poll |
| `--real-ai` | dùng Document AI/Gemini **thật** (TỐN TIỀN), đọc credential từ `evaluation/.env` |
| `--no-seed` | không tạo project demo |
| `--port` / `--aws-port` | đổi cổng (mặc định 8000 / 5000) |
| `--quiet` | không in từng request |

## Vì sao cần moto ở chế độ SERVER, không phải in-process

Luồng upload là: API trả presigned PUT URL → frontend PUT **thẳng lên S3**.
Nếu dùng `mock_aws()` in-process như trong test thì presigned URL sinh ra trỏ về
**AWS thật** và frontend không PUT được. Chạy moto như một HTTP server thì URL
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
| AI | `fake_ai.py` | Document AI + Gemini |

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

## AI giả sinh bộ chứng từ khớp nhau

Loại chứng từ suy từ **nội dung file** (từ khoá `purchase order` / `invoice` /
`nghiệm thu`; không có thì rơi vào loại theo hash, vẫn tất định).

Ba loại thuộc **cùng một giao dịch** `PO-2026-001`, với mâu thuẫn cài sẵn:

| Mâu thuẫn | Mức |
|---|---|
| đơn giá PO 1.250.000 vs hóa đơn 1.280.000 | high |
| tổng tiền lệch 3.000.000 | high |
| xuất hóa đơn 100 nhưng chỉ nghiệm thu 90 | **critical** (3 chiều) |

Nội dung file chứa `__LOI__` sẽ ném lỗi — dùng để thử nhánh document `FAILED`.

## Cho frontend

Base URL `http://127.0.0.1:8000`, CORS mở sẵn cho mọi origin, `OPTIONS`
preflight trả 204.

```
POST   /projects                                  tạo project
GET    /projects                                  danh sách
GET    /projects/{id}                             chi tiết + tiến độ  (poll 2s)
POST   /projects/{id}/documents                   xin presigned PUT URL
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
file. Mở lại thì có project demo mới. Đây là chủ ý — mỗi lần chạy là một môi
trường sạch.
