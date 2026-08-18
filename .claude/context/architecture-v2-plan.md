# Document Processing Architecture — Bản v2 (revised)

> Nguồn: `document_processing_architecture_plan_v2.md` do Ngài cung cấp
> (2026-08-17). Đây là **kế hoạch thay đổi** so với hệ thống hiện tại (v1),
> chưa được implement. Bản dưới là nội dung gốc, đã chuẩn hoá lại encoding.

## 1. Mục tiêu

- User upload 3–4 documents.
- Upload trực tiếp lên S3 bằng Presigned URL.
- **Upload và Processing là hai lifecycle/API riêng biệt.**
- User chủ động bấm Process OCR sau khi upload.
- Step Functions Map xử lý các document parallel.
- Step Functions giữ workflow state.
- Human Review có thể sửa và re-process.
- Frontend nhận progress realtime qua WebSocket.
- S3 lưu raw documents và output lớn.
- State/database chỉ giữ metadata và business state cần thiết.

## 2. Endpoint #1 — Upload documents

```text
POST /batches
```

```text
Frontend
   |
   | POST /batches
   v
API Gateway
   |
   v
Lambda #1
   |
   +-- Create batch/document metadata
   +-- Generate S3 Presigned URLs
   |
   v
Frontend
   |
   +---- PUT File A -----------------> S3
   +---- PUT File B -----------------> S3
   +---- PUT File C -----------------> S3
```

Lambda không upload raw files. Frontend upload trực tiếp lên S3.

Upload endpoint **không tự động Start Step Functions**.

## 3. Endpoint #2 — User chủ động bắt đầu OCR

```text
POST /batches/{batch_id}/process
```

```text
Frontend
   |
   | POST /batches/{batch_id}/process
   v
API Gateway
   |
   v
Lambda
   |
   +-- Verify batch
   +-- Verify documents
   +-- Verify S3 objects
   +-- Check batch chưa processing
   |
   +-- StartExecution()
   |
   v
Step Functions
```

Không cần dùng S3/EventBridge để aggregate upload rồi tự động quyết định thời
điểm Start Step Functions.

## 4. Step Functions Map State

Input chỉ chứa reference:

```json
{
  "batch_id": "batch_123",
  "documents": [
    {"document_id": "A", "s3_key": "uploads/batch_123/A.pdf"},
    {"document_id": "B", "s3_key": "uploads/batch_123/B.pdf"},
    {"document_id": "C", "s3_key": "uploads/batch_123/C.pdf"}
  ]
}
```

```text
Step Functions
      |
     MAP
  +---+---+
  |   |   |
  A   B   C
  |   |   |
 Lambda Lambda Lambda
  |   |   |
  +---+---+
      |
 Processing
```

Mỗi worker Lambda đọc document trực tiếp từ S3.

## 5. Progress notification

```text
Step Functions / Lambda
        |
        v
EventBridge
        |
        v
Notification Lambda
        |
        v
WebSocket
        |
        v
Frontend
```

EventBridge ở đây chỉ làm event transport/notification, không aggregate upload.

## 6. Human Review

Dùng Step Functions callback/task token để chờ user, không giữ Lambda chạy.

```text
Step Functions
      |
      v
Human Review Task
      |
      v
WAIT
      |
      | User reviews
      v
Frontend
      |
      v
Backend API
      |
      v
SendTaskSuccess / callback
      |
      v
Step Functions continues
```

Nếu user edit:

```text
Human Review
      |
      +---- APPROVE ------> Comparison
      |
      +---- EDIT
              |
              v
          Re-process
              |
              v
         Human Review
```

## 7. Document mới ở phase sau

```text
User -> Upload new document -> S3 -> Process endpoint
     -> Step Functions / processing -> Human Review -> Comparison
```

Document mới được process độc lập rồi đưa lại vào Review/Comparison.

## 8. Tổng architecture

```text
                         FRONTEND
                            |
                            | POST /batches
                            v
                       API Gateway
                            |
                            v
                     Lambda #1
                            |
                 +----------+----------+
                 |                     |
                 v                     v
          Create metadata       Presigned URLs
                                        |
                                        v
                                     FRONTEND
                                  /     |     \
                                 A      B      C
                                 |      |      |
                                 +------+------+
                                        |
                                        v
                                       S3


                         USER CHỦ ĐỘNG XỬ LÝ
                                  |
                                  | POST /batches/{id}/process
                                  v
                             API Gateway
                                  |
                                  v
                               Lambda
                                  |
                         verify batch/files
                                  |
                                  v
                         Start Step Functions
                                  |
                                  v
                              MAP STATE
                         +--------+--------+
                         |        |        |
                         A        B        C
                         |        |        |
                       Lambda   Lambda   Lambda
                         |        |        |
                         +--------+--------+
                                  |
                            Processing done
                                  |
                                  v
                            HUMAN REVIEW
                               /     \
                            EDIT     APPROVE
                             |          |
                             v          v
                         Re-process  Comparison
                             |          |
                             +-->Review |
                                        v
                                  Final Result


Progress:
Step Functions / Lambda -> EventBridge -> Notification Lambda
                        -> WebSocket -> Frontend
```

## 9. Phân vai

| Component | Vai trò |
|---|---|
| S3 | Raw documents và large outputs |
| State/DB | Upload metadata và business state cần thiết |
| Step Functions | Workflow execution state |
| EventBridge | Event transport / progress notification |
| Lambda | API handler, event handler, processing worker |
| WebSocket | Realtime notification |
| API Gateway | REST API entry point |

## 10. Nguyên tắc chính

1. Upload và processing là **hai endpoint/lifecycle riêng**.
2. Lambda không upload raw file.
3. Presigned URL cho phép frontend upload trực tiếp S3.
4. User chủ động gọi `/process` khi muốn bắt đầu OCR.
5. Backend verify batch/documents/S3 objects trước khi Start Step Functions.
6. Không cần EventBridge aggregate upload để tự động Start Step Functions.
7. Step Functions giữ workflow execution state.
8. Map State xử lý documents parallel.
9. Lambda worker đọc documents trực tiếp từ S3.
10. EventBridge dùng cho progress notification.
11. WebSocket dùng cho realtime progress.
12. Human Review dùng callback/task token.
13. Raw documents không đi qua Step Functions payload.
14. Kết quả lớn lưu S3; state/DB lưu metadata/reference cần thiết.
