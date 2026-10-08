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
[5] POST /projects/{id}/process/stop -> đặt CỜ dừng trên run; KHÔNG gọi Step Functions
[6] DELETE /projects/{id}            -> xoá hẳn project; đang chạy thì 409
```

Full API surface: `docs/iac-plan.md` §3. Kịch bản chạy thật: `infra/README.md` §7.

## 3. Repo layout

```
backend/
  api/       handler.py (router theo template) + projects/documents/process/reconcile/review
             http.py (response helper), views.py (serialize + progress)
  workers/   ocr, extract, validate, reconcile, mark_failed + steps.py (begin/finish/fail)
  core/      validate.py (luật TRONG 1 doc) | rules.py + crosscheck.py (luật GIỮA nhiều doc)
             position.py (cờ vi_tri) | locate.py (ô nào lấy từ khung chữ nào)
  common/    s3, dynamodb, stepfunctions, ai_clients, audit, errors, ids
  schemas/   purchase_order, invoice, acceptance_record, unknown, registry.py
  devserver/ chạy backend ở localhost (moto server, AI THẬT) — KHÔNG vào Lambda zip
frontend/    React 19 + TS + Vite + Tailwind v4; 2 màn hình, gọi API dev server
             src/review/draft.ts = logic thuần của tab "Trích xuất & sửa"; hooks/useReview.ts
  tests/     conftest.py (moto), test_validate, test_crosscheck, test_api, test_devserver
docs/        architecture.md, data-model.md, schemas.md, iac-plan.md, observability.md
evaluation/  spike đo chất lượng AI + FINDINGS.md
infra/       Terraform; modules/aws/statemachine.asl.json là định nghĩa Step Functions
             statemachine-test/ verify ASL bằng Step Functions Local
```

## 4. Quyết định thiết kế đã chốt — đừng đảo ngược nếu không có lý do mới

- Validate nghiệp vụ tạo `validation.flags`, không làm `FAILED`. `valid` chỉ thể hiện cấu trúc xử lý được, không có nghĩa nghiệp vụ đã đúng hay được duyệt. Lỗi cấu trúc vẫn `FAILED` và giữ dữ liệu gốc.
- Extraction giữ toàn bộ trường ngoài bảng trong `other_fields`; không suy diễn để làm phép tính khớp. Không thêm công thức riêng cho từng loại phí.
- Validate KHÔNG kiểm số học bằng công thức (gỡ 2026-10-07): không `số lượng × đơn giá = thành tiền`, không `Σ dòng − chiết khấu = tiền trước thuế`, không `tiền trước thuế + thuế = tổng`. Vai trò `amount` có thể rơi vào cột trước hay sau chiết khấu, nên hoá đơn Golden Gate trích ĐÚNG vẫn ra 6 cờ oan. Đừng thêm lại, cũng đừng thêm biến thể "có trừ chiết khấu". Số AI chép nhầm trong bảng do cờ `vi_tri` bắt. Dòng thiếu hẳn số lượng vẫn có cờ `insufficient_data` (trỏ vào ô số lượng) vì `crosscheck.build_refs` dựa vào đó để đặt `comparison_incomplete`.
- Giới hạn 3 bảng, 25 cột/bảng, 500 dòng/bảng, 500 ký tự/ô. Có rút gọn thì ghi cảnh báo và không kết luận tổng dòng/thiếu-thừa của nhóm đó.
- Dữ liệu document lớn lưu S3 qua `document_payload_s3_key`; helper DynamoDB tự đọc lại đầy đủ. API review cần `s3:PutObject` để lưu bản sửa lớn. Payload cũ bất biến giúp tránh ghi đè dữ liệu trước khi cập nhật con trỏ.

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
- Hàm gọi, **đơn giá** và **nhãn audit** của mỗi engine OCR nằm chung MỘT bảng:
  `common/ocr_engines.py`. Tách ra là chỗ đã sai: ước tính chi phí lệch 20 lần
  vì lấy giá Form Parser cho Document OCR. `devserver.PROCESSORS`,
  `evaluation/flows.py` và `inspect_ocr.ENGINE_LABEL` đều **trỏ vào chính bảng
  đó**, không giữ bản sao.
- Engine OCR chọn theo **TỪNG LẦN CHẠY**, không theo tiến trình. `/process` nhận
  `engine` trong body → `payload["ocr_engine"]` → `ItemSelector` của Map →
  `event["ocr_engine"]` → `workers/ocr.py`. `OCR_ENGINE` (biến môi trường) chỉ
  còn là **mặc định** và là nước lui cho state machine đã deploy trước thay đổi
  này. Sửa `ItemSelector` thì phải sửa cả `devserver/pipeline.py` — test
  `test_event_cua_devserver_khop_voi_ItemSelector_cua_ASL` so hai bên với nhau.
  `payload` **luôn** phải mang khoá `ocr_engine`: thiếu là States.Runtime, chết
  cả run chứ không phải một chứng từ.
- Bảng `ENGINES` giữ đủ **5** engine nhưng app chỉ cho chọn **2**
  (`APP_ENGINES = ("textract", "dococr")`, mặc định `dococr`). Ba engine kia
  còn sống vì `evaluation/flows.py` sinh flow từ chính bảng đó — xoá là mất khả
  năng đo. Lối vào của app (`/process`, `--processor`, giao diện) đi qua
  `resolve_for_app()`; `evaluation/` vẫn dùng `resolve()`.
- Engine đã chạy được lưu vào `document.ocr_engine` và khai trong
  `DOCUMENT_FIELDS`. `audit_log` có nhãn engine nhưng **chưa route API nào đọc**,
  nên không lưu ở record document thì giao diện không biết chứng từ nào chạy
  bằng gì.
- **Mỗi Lambda MỘT gói riêng**, bảng gói ở `backend/packaging.py` và
  `tests/test_packaging.py` khoá nó khớp `local.workers` + `local.api_functions`
  bên `main.tf`. Mỗi gói khai `modules` (chép đúng code nó chạy) và `requires`
  (đúng thư viện nó cần).
  `boto3` KHÔNG vào gói nào (runtime Lambda đã có, 20 MB), nhưng vẫn ở
  `requirements.txt` cho dev server. Đo được: 340 MB → 39,6 MB, `mark-failed`
  0,1 MB, bốn `api-*` 2,5 MB. Cái tiết kiệm là **cold start**, KHÔNG phải phân
  quyền — IAM gắn vào function chứ không gắn vào gói, và 5 role đã tách sẵn.
- `common/__init__.py` và `workers/__init__.py` phải **RỖNG** — import thẳng
  submodule (`from common.dynamodb import ...`). `common/__init__` từng
  re-export cả 7 submodule, nên `from common import X` ở đâu cũng kéo theo
  `schemas/` → pydantic; đó là lý do `mark-failed` (chỉ đổi một dòng status)
  từng phải mang pydantic. Đã có test chặn.
- `common/ai_clients.py` import `schemas` **LƯỜI** trong thân
  `build_extraction_prompt` — chỉ prompt Gemini cần. Kéo lên mức module là
  `ocr` và `mark-failed` lại phải mang pydantic.
- **Đối chiếu chạy ở ĐÚNG MỘT Lambda** (`recon-reconcile`). `/reconcile` và
  nhánh early-return của `/process` gọi qua `common/reconcile_client.py`
  (`RequestResponse`, giữ hợp đồng đồng bộ). `PATCH` sửa tay **KHÔNG** đối
  chiếu — nó là thao tác review; kết quả cũ thành `is_stale`
  (`views.da_cu()`) và `review_reconciliation` **chặn duyệt/từ chối** cho tới
  khi chạy lại. Chặn ở SERVER, không chỉ làm mờ nút.
- `workers/__init__.py` phải **RỖNG**. Nó từng `from .reconcile import
  run_reconciliation`, mà Python chạy `__init__.py` cho mọi lần import
  `workers.xxx` — nghĩa là `workers.ocr` kéo theo `core/` → `schemas/` →
  pydantic dù không dùng, và gói `ocr`/`mark-failed` phình vô cớ. Đã có test chặn.
- Script build **kiểm sự HIỆN DIỆN** của module (`phai_co_module`), không nạp
  thử: wheel cài bằng `--platform manylinux2014` chứa phần biên dịch cho Linux
  (`pydantic_core._pydantic_core`), nạp trên Windows là chết dù gói hoàn toàn
  đúng cho Lambda. Và `Compress-Archive` của PS 5.1 hay dính "file is being used
  by another process" khi antivirus quét — dùng .NET `ZipArchive`.
- **Zip Lambda phải dùng dấu `/`, KHÔNG dùng `ZipFile::CreateFromDirectory`.**
  Trên PS 5.1 (.NET Framework) nó ghi entry bằng `\` (`workers\extract.py`).
  Lambda chạy Linux → không có thư mục `workers/` → cả 10 function chết lúc
  cold start với `No module named 'workers'`, trong khi `terraform apply` vẫn
  báo thành công và `phai_co_module` vẫn xanh (nó kiểm thư mục build, không kiểm
  zip). `build_backend.ps1` giờ tự tạo từng entry với `/` và **kiểm lại chính
  file zip**, gặp `\` là dừng.
- **Client Textract phải đi qua `common/aws_real.py`**, KHÔNG dùng
  `boto3.client("textract")` trơn. Mọi client khác trong repo đọc
  `AWS_ENDPOINT_URL` để trỏ vào moto; moto có Textract giả trả `Block` bịa kèm
  `JobStatus: SUCCEEDED`, nên dev server sẽ chạy êm và hiện chữ bịa mà không có
  dấu hiệu nào. Đúng thứ đã gỡ ở `fake_ai.py`. Botocore đời mới tự đọc biến đó
  nên phải chỉ endpoint **tường minh**, không chỉ bỏ tham số. Đã có test chặn.
- `devserver/__main__.py` **phải đặt `DEFAULTS` vào env TRƯỚC khi import
  `common`** (hiện đặt ngay mức module, không phải trong `main()`).
  `common/dynamodb.py` đọc tên bảng vào **hằng số lúc import**
  (`PROJECTS_TABLE = os.environ.get("PROJECTS_TABLE", "projects")`). Import
  trước rồi đặt env sau thì hằng số khoá vào `projects` trong khi bootstrap tạo
  `dev-projects`: dev server in "đã tạo 5 bảng" xong request đầu tiên chết vì
  `ResourceNotFoundException`. `tests/conftest.py` đặt env ở dòng đầu vì đúng lý
  do này. Đã có test chặn (chạy ở tiến trình con — trong pytest thì conftest đã
  đặt sẵn env nên test luôn xanh dù lỗi còn nguyên).
- `common/aws_real.py` **cũng phải bỏ qua CREDENTIAL của dev server**, không chỉ
  `AWS_ENDPOINT_URL`. `DEFAULTS` đặt `AWS_ACCESS_KEY_ID=dev` cho moto (moto
  không kiểm), mà boto3 xét biến môi trường **trước** `~/.aws/credentials` →
  Textract/S3 thật trả **403 Forbidden**, tức "không có quyền", làm người ta đi
  sửa IAM policy trong khi khoá gửi lên còn không tồn tại. `aws_real.session()`
  gỡ provider `env`, **trừ khi** đang chạy trên Lambda — ở đó biến môi trường
  chính là credential thật của role.
- **Textract async không nhận bytes**, chỉ nhận địa chỉ S3 (bản sync giới hạn
  PDF 1 trang nên không dùng được). Trên Lambda file đã nằm sẵn đúng chỗ; ở dev
  server (moto = RAM) và evaluation (ổ đĩa) thì phải đẩy lên một bucket THẬT
  (`TEXTRACT_S3_BUCKET`) rồi xoá. Xem `common/textract.py`.
- Confidence của **Textract là thang 0–100**, của Document AI là **0–1**. Quên
  chia 100 thì mọi ngưỡng cảnh báo trong Human Review không bao giờ chạm tới và
  hệ thống im lặng khẳng định "mọi thứ đều chắc chắn". `GetDocument*` còn phân
  trang bằng `NextToken` — quên vòng lặp là mất trang mà không lỗi nào nổ ra.
  Xem `tests/test_textract_parse.py`.
- `RATE_LIMIT_MARKERS` phải phủ **cả tên lỗi của AWS** (`ThrottlingException`,
  `ProvisionedThroughputExceeded`, `LimitExceeded`), không chỉ của Google. Thiếu
  thì throttle không thành `RateLimitError` và nhánh `Retry` trong
  `statemachine.asl.json` không bao giờ chạy — chứng từ chết thay vì thử lại.
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
- **CORS `allow_headers` phải có `authorization`**, nếu không mọi request có `Authorization` chết ở preflight. `OPTIONS` preflight không qua authorizer (HTTP API tự trả từ `cors_configuration`), không cần route OPTIONS riêng.
- **Phải gửi ID token, KHÔNG phải access token.** Authorizer khai `audience = [client_id]`, access token của Cognito mang `client_id` chứ không mang `aud` → gửi nhầm là 401 im lặng. Frontend `auth.ts` dùng `fetchAuthSession().tokens.idToken`.
- **Danh tính lấy từ `cognito:username` (và `sub` dự phòng), KHÔNG lấy `email`.** Người dùng tự sửa được `email` bằng access token nếu `write_attributes` chứa `email` (mặc định app client cho phép), nên audit sẽ ghi `sep@congty.vn` thay vì `tri` — đúng lỗ Task 1 định bịt. Dùng `cognito:username` do admin đặt, không đổi được, và đặt `write_attributes = []` ở `aws_cognito_user_pool_client`.
- **Nhãn "đã sửa tay" chỉ được xoá trong `workers/extract.py`**, cùng lần ghi với
  `extraction`. Trước đây không chỗ nào xoá: sau `force_edited=true` dữ liệu đã
  là của AI mà record vẫn mang `edited_fields`/`edited_by`. Xoá sớm hơn (lúc bấm
  `/process`) thì OCR hay Gemini hỏng giữa chừng sẽ để lại dữ liệu người sửa mà
  mất nhãn bảo vệ. Có test cho cả hai chiều (`test_worker_extract.py`,
  `test_worker_ocr.py`).
- **Dòng audit phải `print(..., flush=True)`.** stdout ghi ra file (không phải
  terminal) thì Python đệm theo khối — đo thật trên devserver, không dòng audit
  nào hiện ra cho tới khi bật `PYTHONUNBUFFERED`. Lambda timeout giữa chừng thì
  phần còn trong bộ đệm mất luôn.
- **Amplify deploy thủ công bằng zip**, không nối GitHub (token sẽ nằm trong tfstate local chưa mã hoá). Branch cố định `main`, URL `https://<branch>.<app_id>.amplifyapp.com` cho vào `local.cors_origins`.
- **`deploy_frontend.ps1` từ chối chạy khi `VITE_API_URL` trống hoặc là
  localhost**, và sau khi build thì kiểm chính bundle có chứa URL đó.
  `frontend/.env` bình thường là cấu hình dev; build nguyên trạng thì bản trên
  Amplify không đòi đăng nhập và gọi API về máy của chính người xem, trong khi
  deploy vẫn báo SUCCEED. Cấu hình prod truyền qua biến môi trường của lệnh
  (Vite ưu tiên biến môi trường hơn file `.env`; script đọc theo đúng thứ tự
  đó). Đừng sửa `.env` để deploy: dev server đang chạy sẽ tự khởi động lại sang
  API prod.
- **Luật rewrite của Amplify (`aws_amplify_app.custom_rule`) trả `index.html`
  cho mọi đuôi file KHÔNG nằm trong danh sách của nó.** Worker `.mjs` của pdf.js
  từng bị trả HTML 410 byte thay cho 1,4 MB JavaScript, deploy vẫn SUCCEED và
  `npm run dev` không lộ. Thêm loại file tĩnh mới thì thêm đuôi vào danh sách.
  Sửa luật xong PHẢI deploy lại frontend: CloudFront cache cả câu trả lời sai
  với `s-maxage` 1 năm, thêm `?t=` không phá được, chỉ deployment mới xoá cache.
  Kiểm bằng `curl -D -` xem `content-type`; muốn biết luật mới đã có hiệu lực
  chưa thì thử một đường dẫn CHƯA TỪNG được gọi.

- **Bucket state phải có trước `terraform init`**: backend không dùng được biến.
  Dùng stack `infra/bootstrap/` riêng, state bootstrap giữ local. `.gitignore`
  phải chặn cả thư mục con bằng `infra/bootstrap/*.tfstate*`.
- **Gemini key** đọc từ Secrets Manager qua `GEMINI_API_KEY_SECRET` và cache
  trong tiến trình; env `GEMINI_API_KEY` được ưu tiên khi nạp (devserver/evaluation).
  Test đụng tới phải reset `ai._gemini_api_key_cache`.
- **Script `.ps1` có ký tự ngoài ASCII phải có BOM UTF-8**. PowerShell 5.1
  đọc file không BOM theo codepage hệ thống (máy này là 1252); dấu `—` trong
  chuỗi có thể thành `”` và làm vỡ cú pháp.
- **`view_url` được ký lại mỗi lần `GET /projects/{id}`** nên `DocumentViewer`
  giữ URL theo `document_id` (`urlOnDinh`); gỡ đi thì mỗi lần Lưu/refresh PDF
  tải lại về trang 1. Frontend chưa có test nên không có gì chặn — đừng gỡ khi
  chưa chạy tay mục B.7.
- **Output Gemini được làm sạch ở `workers/extract.py` trước khi lưu**
  (`core/normalize.py:clean_extraction`), bản thô còn nguyên ở
  `extraction_s3_key`. Chỉ gỡ trường vô hướng ở gốc, mỗi mục thành cờ
  `ai_format`; `other_fields`/ô bảng/khoá lạ chỉ đổi hình dạng, không ghi nhận.
  Đường sửa tay (`api/review.py`) không được cứu — người nhập sai kiểu vẫn
  `FAILED`. Quá 10 trường bị gỡ (`MAX_GO`) thì trả nguyên để `FAILED` như cũ.
- **Đo lỗi định dạng bằng `evaluation/measure_format.py`, không đánh giá bằng
  demo tay.** `capture --from-devserver` giữ output RAM (miễn phí),
  `capture --engine` tốn tiền Gemini (Ngài chạy), `report [--khong-cuu]` chấm
  `hỏng X/N` trên cùng snapshot. Đáp án ô bảng ở
  `dataset/ground_truth_tables/` (định dạng khác `ground_truth/` của spike).

- **Dừng run bằng CỜ, không bằng `StopExecution`.** `POST /process/stop` chỉ ghi
  `cancel_requested_at` lên record run; worker `ocr`/`extract` kiểm cờ TRƯỚC
  `begin_step` và trả `{..., "skipped": "cancelled"}`. `StopExecution` không giết
  Lambda đang chạy (vẫn tốn tiền, vẫn ghi DynamoDB sau khi "dừng") và không chạy
  `Catch`, nên `processing_run_id` sẽ kẹt; dev server chạy run bằng thread cũng
  không abort được. Với cờ, run đi hết đường kết thúc sẵn có và `Reconcile` nhả
  khoá. Giới hạn: lời gọi AI đang bay (tối đa `MaxConcurrency` = 3 chứng từ)
  không thu hồi được.
- **`validate` KHÔNG kiểm cờ dừng**, chỉ tôn trọng `event["skipped"]`. Nó không
  tốn tiền, và chứng từ `EXTRACTED` mà không validate sẽ bị `/process` coi là đã
  xong mãi mãi (`PROCESSED_STATUSES`).
- **`status_before_run` do `api/process.py` ghi lúc xếp hàng, worker chỉ đọc.**
  Run bị dừng thì `workers/reconcile.py` trả chứng từ chưa kịp chạy về trạng thái
  đó. Thiếu nó, "chạy lại N chứng từ đã xong" rồi bấm Dừng để lại N chứng từ
  `PENDING`, và lần "Xử lý tất cả" kế tiếp trả tiền lại hết. Bộ
  `PROCESSED_STATUSES` vẫn chỉ nằm ở `api/views.py`.
- **Run bị dừng KHÔNG tự đối chiếu.** Kết quả cũ thành `is_stale`; người dùng bấm
  "Đối chiếu lại".
- **Lambda reconcile chỉ nhả khoá khi event có `run_id`.** `POST /reconcile` gọi
  chung handler đó mà không có `run_id`; nhả vô điều kiện là mở khoá của run đang chạy.
- **Xoá project theo đúng thứ tự: cờ `deleting_at` (conditional) → record
  documents/reconciliations/runs → S3 → record project.** Record project xoá SAU
  CÙNG nên hỏng giữa chừng thì bấm xoá lại là xong. Record trước S3 vì
  `GET /projects/{id}` hydrate chứng từ từ S3 — mất file trước là 500. Gom id
  chứng từ bằng `query_document_names_by_project` (không hydrate), KHÔNG dùng
  `query_documents_by_project`.
- **`claim_processing_run` có điều kiện `attribute_not_exists(deleting_at)`**, và
  `delete_project` có điều kiện `attribute_not_exists(processing_run_id)`. Hai
  conditional write trên cùng một item mới loại trừ nhau thật; kiểm bằng `if`
  trong handler thì bị race.
- **`delete_prefix` bắt buộc prefix kết thúc bằng `/`.** Thiếu thì
  `projects/prj-1` nuốt cả `projects/prj-10…`, rỗng thì xoá cả bucket. Quyết định
  "không discover S3 bằng `ListObjectsV2`" (§4) nói về đường NHẬP file; liệt kê để
  XOÁ là ngoại lệ có chủ đích, và `s3:ListBucket` chỉ cấp cho role `api-projects`.
- **Lambda reconcile trả BẢN GHI ĐẦY ĐỦ khi event không có `run_id`** (đường API
  gọi qua `invoke_reconcile`), và chỉ trả bản tóm tắt cho Step Functions. Trước
  đây nó luôn trả tóm tắt, nên trên cloud `/process` ở nhánh "không còn gì để xử
  lý" chết vì thiếu `severity_summary` và `/reconcile` trả bản ghi thiếu
  `status`/`document_ids`. Dev và test không lộ vì `invoke_reconcile` được vá
  thành `run_reconciliation` — test mới gọi thẳng `lambda_handler` qua một vòng
  `json.dumps`/`loads` để giữ đúng hợp đồng của cloud.
- **Dev server phải nhận mọi HTTP method có trong `handler.ROUTES`**
  (`do_<METHOD>` và `Access-Control-Allow-Methods`). Thiếu `PUT` thì
  `PUT /anchor` ở localhost trả 501 trong khi cloud chạy bình thường. Đã có test
  chặn.
- **Bấm Dừng gỡ được run đã CHẾT.** `stop_processing` coi run là chết khi đủ
  hai điều kiện: `run.status == "PROCESSING"` VÀ execution không còn `RUNNING`
  (`common/stepfunctions.py:execution_is_running`). Khi đó nó gọi Lambda
  reconcile kèm `run_id`, Lambda thấy cờ dừng nên chạy `_finish_cancelled_run`.
  Thiếu điều kiện thứ nhất thì run vừa kết thúc bình thường sẽ bị đánh
  `CANCELLED` đè lên. Lỗi Step Functions khác `ExecutionDoesNotExist` phải nổ
  ra, không được coi là "đã chết". Đường này CHƯA chạy lần nào trên Step
  Functions thật — test dùng moto và execution giả.
- **`_finish_cancelled_run` nhả khoá CÓ ĐIỀU KIỆN** (`processing_run_id` phải
  đúng là run đó). Nhả vô điều kiện thì đường gỡ run chết có thể mở khoá của một
  run khác vừa claim.
- **Shim đối chiếu của dev server và test đi qua `lambda_handler`**, không qua
  `run_reconciliation`, và test thêm một vòng `json.dumps`/`loads`. Sửa
  `devserver/pipeline.py:install` thì phải sửa `tests/conftest.py` cho khớp.

- **Kết quả OCR có `pages[].words = [[chữ, x0, y0, x1, y1]]`** (toạ độ chuẩn hoá
  0–1) từ cả hai parser. Prompt Gemini KHÔNG đọc `words` (đã có test chặn) — thêm
  vào là prompt phình mà Gemini vẫn gõ lại số như cũ.
- **Cờ `vi_tri` sinh ở `workers/extract.py` bằng `core/position.py`**, lúc
  `ocr_json` còn trong bộ nhớ. Nó lấy cấu trúc bảng từ chính kết quả Gemini rồi
  đối chiếu với vị trí chữ, KHÔNG dùng luật theo mẫu chứng từ (đã thử luật kiểu
  "dòng bắt đầu bằng STT, ít nhất 8 ô": đúng một hoá đơn, hỏng 6 chứng từ còn
  lại). Không chắc thì không kết luận; ô trống và ô 0 coi như nhau. Bộ kiểm hỏng
  thì ghi `POSITION_CHECK_FAILED` và coi như không có cảnh báo, không làm chứng từ
  `FAILED`. Chứng từ xử lý trước thay đổi này không có `words` nên không có cờ.
- **Chỉ cờ `ai_format` và `vi_tri` khoá Duyệt** (`views.BLOCKING_FLAG_CODES`).
  Các cờ khác (`format`, `quantity`, `insufficient_data`…) không khoá. Mở khoá
  bằng cách sửa ô rồi Lưu, hoặc tắt lẻ TỪNG cờ (`dismissed_flags`). KHÔNG còn nút
  "Xác nhận" chung cho cả chứng từ và `PATCH {"confirm": true}` (gỡ 2026-10-07:
  bấm xong không có gì đổi trên màn hình). Tắt cờ KHÔNG đóng dấu `updated_at` —
  đóng dấu là kết quả đối chiếu thành cũ và người dùng kẹt trong vòng tắt cờ →
  đối chiếu lại. Xử lý lại bằng AI thì cờ đã tắt bị xoá. Từ chối không bị khoá.
- **Cảnh báo lấy từ SERVER và chỉ tính lại khi bấm Lưu.** Sửa ô mới chỉ đổi bản
  nháp trong trình duyệt, nên cờ vẫn còn nguyên — hộp cảnh báo ghi "Đã sửa chỗ
  này — bấm Lưu…" cho cờ nào có ô đã đổi trong nháp (`choLuu` ở
  `ValidationFlags`). Gỡ dòng nhắc đó là người dùng tưởng sửa rồi mà cờ không mất.
- **`GET …/ocr` trả thêm `layout`** (`core/locate.py`): ô nào, trường nào, tiêu đề
  cột nào lấy từ khung chữ nào, dưới dạng `[trang, thứ tự chữ]`. Tính lại ở mỗi lần
  gọi từ kết quả trích xuất hiện tại; chỉ khi người dùng đã Lưu thì dùng bản
  `sources` lưu trên document. `at` (khung đang nằm đúng dòng–cột của ô) luôn tính
  lại, không lưu. Dò bằng cách khớp chữ và số với chính kết quả Gemini, KHÔNG dùng
  luật theo mẫu chứng từ; không tìm thấy thì để trống ("chưa rõ vị trí"), không
  đoán. `locate` dùng chung `_layout` với `check_positions` — sửa một bên phải chạy
  test của cả hai.
- **`sources` đánh chỉ số theo VỊ TRÍ** (`tables[t].rows[r][c]`), không theo tên
  cột, nên đổi tiêu đề không làm lệch. Nhưng cờ `vi_tri` và `dismissed_flags` gắn
  theo SỐ THỨ TỰ DÒNG, vì vậy giao diện chỉ cho thêm dòng ở cuối bảng và xoá dòng
  cuối. Muốn chèn hay xoá giữa bảng thì phải đánh lại chỉ số ở cả ba chỗ trước.
- **Cờ `vi_tri` mang `col` (chỉ số cột) và `still_valid` tra theo `col`.** Thiếu nó
  thì đổi tên một cột là cờ của ô chưa sửa biến mất và nút Duyệt mở khoá.
- **`PATCH` chỉ có `sources` (không có `fields`) KHÔNG đóng dấu `updated_at`** —
  gắn lại khung không đổi dữ liệu, nên không được làm kết quả đối chiếu thành cũ.
  `PATCH` có `fields` mà không kèm `sources` thì xoá `sources` (quay về dò tự động);
  worker extract cũng xoá. `clean_sources` bỏ mọi thứ lệch hình dạng với kết quả
  trích xuất, và trả rỗng khi quá `MAX_NODES` để record không vượt 400 KB.
- **Chứng từ gốc vẽ bằng pdf.js (`PdfPages.tsx`), không còn iframe** — iframe của
  trình duyệt không cho vẽ đè. `disableRange` + `disableStream` để chỉ có một GET
  trơn tới S3, không phụ thuộc vào việc S3 (và S3 giả lập ở dev) xử lý header
  `Range` và preflight ra sao. Khung vẽ bằng SVG `viewBox="0 0 1 1"`, khớp thẳng toạ
  độ chuẩn hoá của OCR. Ghim `pdfjs-dist@4.10.38`: bản 5 trở lên đổi tham số của
  `render`.
- **Chữ OCR đưa vào ô được đổi sang số theo `number_style`**, suy từ chính chứng từ
  (`29.000` ↔ 29000 là dấu nghìn; `30.000` ↔ 30 là thập phân). Chỉ ô người dùng
  chạm vào mới đổi kiểu. Ô không chạm phải giữ NGUYÊN kiểu và giá trị khi lưu, nếu
  không `still_valid` coi là đã sửa và bỏ cờ.
- **Bấm khung khi CHƯA chọn ô thì chỉ xem, không gán.** Gán chỉ xảy ra khi đã bấm
  chọn một ô ở bên phải. Gộp hai thao tác làm một thì người dùng bấm dạo qua các
  khung là dữ liệu bị đổi mà không biết.
- Frontend vẫn chưa có test. Logic thuần của tab "Trích xuất & sửa" nằm riêng ở
  `frontend/src/review/draft.ts` (không import React) để sau này thêm test dễ.
- **Mọi cờ đều tắt lẻ được, kể cả cờ khoá** (`dismissed_flags` top-level,
  KHÔNG nằm trong `validation` vì worker validate ghi đè cả dict đó). Tắt/mở qua
  `PATCH {dismiss/undismiss: {code, field}}`, không thêm route nên vẫn 15 route.
  Tắt KHÔNG đóng dấu `updated_at`. Sửa dữ liệu thì entry nào không còn
  `code:field` trong cờ mới sẽ bị tỉa; đổi giá trị mà cờ còn thì hiện lại (cờ
  khoá thì khoá lại) vì `values` snapshot lệch. AI trích lại thì xoá sạch.
- **Cờ dòng `tables.T.rows.R` bấm được tới ô Thành tiền** (`dichCuaTruong` chọn cột
  theo vai trò `amount → unit_price → quantity`). Cờ đối chiếu `items.Tên.role`
  dò qua `dichCuaDoiChieu` bằng tên hàng khớp cột `item_name`. Không dò được thì
  chỉ route như cũ, không đoán ô.
- **Sửa inline trong ô, cache nháp 90 phút** (`review/cache.ts`, key
  `nhap:project:doc`, kèm `updated_at` gốc). Ô đang sửa render `input` tại chỗ,
  nhãn đứng yên, bấm khung OCR vẫn điền vào ô đó. Hộp xanh sticky đã bỏ: nút
  "Lấy tại vị trí này" nằm gọn dưới input đang sửa, nút Để trống đã bỏ (xóa chữ
  + Enter là ra trống), gom khung chưa màu hiện dải mỏng trên thanh Lưu. Nháp chỉ chốt vào draft, nút Lưu cuối mới gọi
  API. Draft khác gốc thì ghi cache, bằng nhau hoặc hết hạn thì xoá.

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
- Mỗi lần gọi AI ghi 1 dòng `AI_CALL` vào CloudWatch Logs (kể cả khi lỗi/rate limit). Dùng `print`, không dùng `logging`; không bật `logging_config { log_format = "JSON" }` vì CloudWatch không đọc được EMF.
- S3 giữ raw + output lớn; DynamoDB giữ metadata/summary/reference.
- Tiếng Việt dùng Document AI (generic); specialized Invoice/PO Parser **không
  hỗ trợ tiếng Việt**. Giới hạn online ~15 trang / 20MB.
- **Amazon Textract KHÔNG hỗ trợ tiếng Việt** — AWS chỉ liệt kê English, French,
  German, Italian, Portuguese, Spanish ([limits-document.html]). Đo trên hoá đơn
  thật: mất gần hết dấu (`Phuring Khuong Mai` ← *Phường Khương Mai*,
  `Hinh there thanh toan` ← *Hình thức thanh toán*) nhưng **số đọc đúng hết** và
  Gemini vẫn trích xuất chính xác cả 7 dòng hàng.

  Vì vậy `dococr` là **mặc định** (chốt 2026-10-05). `textract` vẫn chọn được,
  và cảnh báo vẫn phải hiện **ngay chỗ người dùng chọn engine**
  (`app_choices()[...]["supports_vietnamese"]` → menu "Chạy lại với…" và dòng
  LƯU Ý lúc devserver khởi động), không được chôn trong tài liệu.

  [limits-document.html]: https://docs.aws.amazon.com/textract/latest/dg/limits-document.html
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
# validate offline (không đọc backend S3) cần init -backend=false
cd infra; .\bin\terraform.exe init -backend=false; .\bin\terraform.exe validate
cd infra; .\bin\terraform.exe plan -var-file=dev.tfvars

infra\scripts\build_backend.ps1        # -> 10 zip, MỖI Lambda một gói riêng
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

WebSocket · dataset 50–100 tài liệu + ground truth + evaluation.
