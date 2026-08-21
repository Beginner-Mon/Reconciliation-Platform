# AI Document Intelligence & Reconciliation Platform

Đề tài thực tập 2 tháng: hệ thống AI trích xuất – kiểm tra – đối soát chứng từ
doanh nghiệp **tiếng Việt** (Purchase Order / Hóa đơn / Biên bản nghiệm thu).
Serverless trên AWS, AI chạy trên Google Cloud.

Quy tắc làm việc/xưng hô/critical-thinking: xem @AGENTS.md (file cá nhân, đang
gitignore). File này chỉ mô tả **project context kỹ thuật**.

## 1. Ba khái niệm cốt lõi (đọc kỹ trước khi sửa bất cứ gì)

| Khái niệm | Vòng đời | Ghi chú |
|---|---|---|
| **Project** | Sống lâu dài | Chứa N document, được bồi thêm theo thời gian |
| **Processing Run** | Một lần chạy | OCR/Extract/Validate cho document **chưa xử lý** |
| **Reconciliation** | Một lần đối chiếu | Chạy trên toàn bộ document đã xử lý của project |

> Xử lý per-document là **idempotent, cache được**.
> Đối chiếu là thao tác **project-level, chạy lại được độc lập**.

Thêm 1 biên bản nghiệm thu vào project đã xử lý → **chỉ OCR file mới**, file cũ
được skip. Đây là yêu cầu nghiệp vụ, không phải tối ưu. Bất kỳ thay đổi nào phá
tính chất này là sai.

## 2. Ba endpoint, ba lifecycle

```
[1] POST /projects/{id}/documents   -> N presigned PUT URL, frontend PUT thẳng lên S3
[2] POST /projects/{id}/process     -> user chủ động; SKIP doc đã VALIDATED
[3] POST /projects/{id}/reconcile   -> deterministic, KHÔNG đụng AI, gọi lại thoải mái
[4] Human Review                    -> API độc lập, KHÔNG nằm trong Step Functions
```

Full API surface: `docs/iac-plan.md` §3. Kịch bản chạy thật: `infra/README.md` §7.

## 3. Repo layout

```
backend/
  api/       handler.py (router theo template) + projects/documents/process/reconcile/review
             http.py (response helper), views.py (serialize + progress)
  workers/   ocr, extract, validate, reconcile, mark_failed + steps.py (begin/finish/fail)
  core/      validate.py (luật TRONG 1 doc) | rules.py + crosscheck.py (luật GIỮA nhiều doc)
  common/    s3, dynamodb, stepfunctions, ai_clients, audit, errors, ids
  schemas/   purchase_order, invoice, acceptance_record, unknown, registry.py
  devserver/ chạy backend ở localhost (moto server, AI THẬT) — KHÔNG vào Lambda zip
frontend/    React 19 + TS + Vite + Tailwind v4; 2 màn hình, gọi API dev server
  tests/     conftest.py (moto), test_validate, test_crosscheck, test_api, test_devserver
docs/        architecture.md, data-model.md, schemas.md, iac-plan.md
evaluation/  spike đo chất lượng AI + FINDINGS.md
infra/       Terraform; modules/aws/statemachine.asl.json là định nghĩa Step Functions
             statemachine-test/ verify ASL bằng Step Functions Local
```

## 4. Quyết định thiết kế đã chốt — đừng đảo ngược nếu không có lý do mới

1. **Step Functions KHÔNG chờ Human Review** (không dùng task token). Review là
   bước cuối và EDIT là người sửa tay → không còn gì để orchestrate. Execution
   kết thúc ở `AWAITING_REVIEW`.
2. **Progress dùng polling**, không WebSocket/EventBridge. Nâng cấp sau bằng
   DynamoDB Streams mà **không phải sửa worker**.
3. **Map iterator tách 3 state** (Ocr → Extract → Validate) để Gemini 429 chỉ
   retry Gemini, không chạy lại Document AI.
4. **Review gắn vào `reconciliation`, không gắn vào project** — thêm doc mới sinh
   reconciliation mới, lịch sử cũ còn nguyên.
5. **Cross-check là rule engine N-way**, không phải `reconcile(PO, Invoice)`.
   `Discrepancy.values[]` chứa N document, không dùng `expected`/`actual`.
6. **File chỉ vào hệ thống qua endpoint upload** — không discover S3 bằng
   `ListObjectsV2`.

## 5. Bẫy đã xử lý — đừng phá

- `/process` claim `project.processing_run_id` bằng **conditional update**
  (read-then-write bị race). Execution name = `run_id` → gọi trùng không tạo
  execution thừa.
- Mọi nhánh kết thúc của Step Functions (kể cả `MarkRunFailed`) **bắt buộc**
  `REMOVE processing_run_id`, nếu không project kẹt vĩnh viễn.
- `Catch` nằm **bên trong** Map iterator → 1 doc lỗi không giết cả run.
- `force=true` **vẫn bỏ qua** doc có `edited_fields` — cần thêm `force_edited=true`.
  Nếu không, một lần re-process xoá sạch công review.
- DynamoDB không nhận `float` → `common/dynamodb.py` có `to_dynamo`/`from_dynamo`
  chuyển Decimal. `confidence` của Gemini là float nên chỗ này bắt buộc.
- `po_number` nhân bản lên **top-level** vì GSI không index được attribute lồng;
  chỉ ghi khi có giá trị (giữ GSI sparse).
- `AcceptedItem` tách khỏi `LineItem` vì biên bản nghiệm thu không có đơn giá.
- Prompt Gemini **sinh từ registry**, không viết tay — v1 từng lệch giữa
  `SUPPORTED_DOC_TYPES` và nội dung prompt.
- **KHÔNG** đặt `response_schema` với `"data": {"type":"OBJECT"}` rỗng — Gemini
  hiểu là "không có trường nào" và luôn trả `{}`. Đo thật: 31 token vs 447 token.
  Ràng buộc kiểu để Pydantic lo. Xem `tests/test_ai_config.py`.
- Document AI **không** trả `.text` trên từng phần tử — phải cắt chuỗi theo
  offset trong `text_anchor`; trường đúng tên là `page.form_fields` chứ không
  phải `key_value_pairs`. Xem `tests/test_docai_parse.py`.
- `steps_done()` trong `api/views.py` **không** suy được chỉ từ `status`, vì
  `begin_step()` đặt `PROCESSING` ở mọi bước, ghi đè mất `OCR_DONE`/`EXTRACTED`.
  Phải suy từ `step` đang chạy, nếu không thanh tiến trình nhảy theo document.
- `devserver/pipeline.py` đọc thứ tự bước **từ file ASL**, không hardcode — sửa
  ASL mà quên dev server thì nó báo lỗi lúc khởi động chứ không chạy sai âm thầm.
- Upload dùng **presigned POST**, KHÔNG phải PUT. POST + `multipart/form-data`
  là "simple request" nên trình duyệt không gửi preflight; presigned PUT thì có
  và S3 giả lập từ chối preflight đó. POST còn đặt được `content-length-range`
  để giới hạn kích thước file — PUT không làm được.
- Bucket S3 **phải khai CORS** (`aws_s3_bucket_cors_configuration` +
  `devserver/bootstrap.py CORS_RULES`) vì frontend upload thẳng lên S3. Thiếu
  thì `curl` vẫn chạy nhưng trình duyệt bị chặn — test cũ không bắt được.
- `devserver` **KHÔNG còn chế độ AI giả** (đã gỡ `fake_ai.py`, `replay_ocr.py`,
  `minipdf.py`, `seed.py`, route `/__dev__`, `FakeAiBanner`). AWS thì giả lập,
  AI thì luôn thật và luôn tốn tiền. Lý do gỡ: dữ liệu mẫu cố định nhìn **không
  phân biệt được với hệ thống hỏng**, và một băng cảnh báo màu vàng cũng không
  đủ để cứu. Thiếu credential → **thoát ngay lúc khởi động (exit 2)**, không có
  đường lui về dữ liệu mẫu. Đừng thêm lại "cho tiện"; đã có test chặn.
- Processor và **đơn giá phải đi cùng một chỗ** (`PROCESSORS` trong
  `devserver/__main__.py`, và `DOCAI_PROCESSOR_LABEL` cho audit log). Tách ra là
  chỗ đã sai: ước tính chi phí lệch 20 lần vì lấy giá Form Parser cho Document
  OCR. Mặc định `--processor dococr` = Enterprise Document OCR $0,0015/trang.
- Chống tính tiền lặp **đã nằm sẵn trong hệ thống**: `/process` bỏ qua doc đã
  `VALIDATED`. Không cần cache riêng ở tầng dev — cache đĩa từng có là thừa.
- `AgreeRule`/`NumericRule` trong `core/rules.py` lọc theo **TRƯỜNG**, không theo
  **LOẠI** — hễ hai chứng từ cùng có `currency`/`total_amount` là đem ra so, bất
  kể là gì. Nên câu "rule cũ tự bỏ qua loại mới" **chỉ đúng với rule khai rõ
  loại** (LineItem/QuantityCoverage/ReferenceExists). Loại `unknown` vì vậy bị
  chặn ở tầng LOẠI bằng `NON_COMPARABLE_TYPES` trong `core/crosscheck.py`, chứ
  không phải bằng cách bớt trường trong schema. Thêm loại mới nào không so sánh
  được thì thêm vào set đó. Chạy thật mới lộ: 2 chứng từ của 2 lô hàng khác nhau
  bị báo "lệch tiền 43 triệu".
- `DOCUMENT_TYPE_LABELS` đọc **cho người** (`core/rules.py` in vào giải thích
  mâu thuẫn). Chỉ dẫn cho Gemini để ở `DOCUMENT_TYPE_PROMPT_NOTES`. Gộp hai bảng
  thì câu lệnh "CHỈ dùng khi..." lọt vào giải thích hiện cho người dùng.
- `page["lines"]` của kết quả OCR là `[{text, confidence}]`, không phải list
  chuỗi. Chỉ để hiển thị: `_build_ocr_text` dựng prompt Gemini từ `text`, KHÔNG
  đọc `lines` — nếu không prompt phình gấp đôi. Đã chặn bằng test.
- Bước `validate` **không gọi AI** nên `step_status="running"` của nó chỉ tồn
  tại vài micro giây, không quan sát được khi poll. Đúng cả ở production — đừng
  coi là lỗi.

## 6. Thêm loại chứng từ mới

Thêm `schemas/<loại>.py` → đăng ký vào `schemas/registry.py` → thêm rule ở
`core/rules.py` nếu cần. Chứng từ không khớp loại nào rơi vào `unknown`
(`schemas/unknown.py`) — mọi trường tùy chọn, đi hết pipeline nhưng gần như
không kiểm tra được gì. Nhãn của `unknown` trong `DOCUMENT_TYPE_LABELS` viết
như một mệnh lệnh và nó phải đứng **CUỐI** `DOCUMENT_TYPES`: prompt sinh theo
đúng thứ tự đó, đảo lên đầu là Gemini không phân loại đúng nữa. **Không** phải sửa prompt, Step Functions, API, data
model. Rule cũ tự bỏ qua loại mới. Xem `docs/schemas.md` §1.

## 7. Quy ước kỹ thuật (rule cứng)

- AI **không** tự phê duyệt/thay đổi dữ liệu nghiệp vụ — phải qua Human Review.
- LLM chỉ trả structured output, bắt buộc qua Pydantic validation.
- `core/` **không được gọi AI** (deterministic thuần, test offline được).
- Mỗi lần gọi AI ghi 1 record `AI_CALL` vào `audit_log` (kể cả khi lỗi/rate limit).
- S3 giữ raw + output lớn; DynamoDB giữ metadata/summary/reference.
- Tiếng Việt dùng Document AI **Form Parser** (generic); specialized Invoice/PO
  Parser **không hỗ trợ tiếng Việt**. Giới hạn online ~15 trang / 20MB.
- Comment/message trong code viết tiếng Việt (theo code hiện có).

## 8. Lệnh

```powershell
# Chạy cả hệ thống ở máy (2 terminal): backend rồi frontend
cd backend;  .venv\Scripts\python.exe -m devserver --upload ..\evaluation\dataset\documents
cd frontend; npm run dev                                      # UI  :5173

# Test backend — PHẢI chạy từ trong backend/ (import cần CWD ở đó)
cd backend; .venv\Scripts\python.exe -m pytest -q          # 86 test, offline
cd backend; .venv\Scripts\python.exe -m pyflakes api common core schemas workers tests devserver

# Terraform: binary nằm ở infra\bin\ (gitignore), KHÔNG cài vào máy
cd infra; .\bin\terraform.exe validate
cd infra; .\bin\terraform.exe plan -var-file=dev.tfvars

infra\scripts\build_backend.ps1                            # -> artifacts/backend.zip
```

Terraform **không** cài được vào `.venv` — `.venv` chỉ chứa package PyPI, còn
terraform là binary Go. Cách giữ cục bộ là tải binary vào `infra/bin/`.

Test backend không cần AWS thật (moto) và không cần Google credential
(`ai_clients.py` import lazy bên trong hàm).

## 8b. Kiểm thử Step Functions — xem `infra/statemachine-test/README.md`

Hai mức, **không cần Docker**:
1. `aws stepfunctions validate-state-machine-definition` — 1 giây, miễn phí,
   không tạo tài nguyên. Bắt lỗi cú pháp ASL/JSONPath.
2. Step Functions Local (JAR, cần **Java 17+**) + `run.py` — chạy thật luồng với
   Lambda mock, xác minh `Catch` trong iterator và nhánh `MarkRunFailed`.

**Bẫy đã gặp:** SFL 2.0.0 không hỗ trợ `ItemProcessor` (chỉ hiểu `Iterator` đã
deprecated) → `run.py` tự đổi cho bản local, **đừng sửa file ASL gốc theo SFL**.
Chuỗi `Cause` tiếng Việt làm AWS CLI chết trên console cp1252 — đã xử lý bằng
`--query` + `PYTHONIOENCODING=utf-8`.

## 9. Chưa làm

Frontend React (chưa có dòng nào) · auth/Cognito · WebSocket · remote tfstate ·
dataset 50–100 tài liệu + ground truth + evaluation.
