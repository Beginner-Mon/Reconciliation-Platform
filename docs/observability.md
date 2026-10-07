# Observability — Audit & Monitoring

> **Trạng thái: ĐÃ TRIỂN KHAI trong code, CHƯA deploy** (cập nhật 2026-09-16).
> Audit đã là dòng JSON trên stdout (`common/audit.py`), bảng DynamoDB `audit_log`
> **đã bỏ**, 10 log group giữ **10 năm** (`log_retention_days = 3653`) và dashboard đã khai trong Terraform
> (`terraform validate` Success, 257 test xanh). **Chưa `terraform apply`**, nên
> chưa có gì được xác minh trên AWS thật — xem §13.

## 1. Ba câu hỏi khác nhau, ba công cụ khác nhau

"Audit" và "monitor" bị gộp làm một thì chọn sai công cụ. Tách ra thành ba câu hỏi:

| Lớp | Câu hỏi | Ai hỏi | Công cụ |
|---|---|---|---|
| **1. Audit nghiệp vụ** | Ai upload chứng từ? Ai bấm `/process` với `force`? Ai sửa trường nào? Ai duyệt đợt đối chiếu? | Mentor, quản lý | CloudWatch Logs + Logs Insights |
| **2. Vận hành** | Có lỗi không? Gemini có bị 429? Hôm nay tốn bao nhiêu tiền AI? | Dev | CloudWatch Metrics + Dashboard |
| **3. Hạ tầng** | Ai đổi IAM? Ai xoá bảng? Ai đọc secret? | Dev/admin | CloudTrail |

## 2. Ba hiểu lầm phải gỡ trước

**a. AWS Audit Manager không dùng được.** Tài liệu AWS: *"AWS Audit Manager is no
longer open to new customers."* Dịch vụ đó cũng không làm việc ta cần — nó gom
bằng chứng tuân thủ SOC2/ISO cho cả tài khoản AWS, không ghi vết nghiệp vụ.
([what-is.html](https://docs.aws.amazon.com/audit-manager/latest/userguide/what-is.html))

**b. CloudTrail không biết người dùng cuối.** CloudTrail ghi lệnh gọi API của AWS
theo *IAM principal*. Khi người dùng bấm "Duyệt", bản ghi DynamoDB được thực hiện
bởi **role của Lambda**:

```json
"userIdentity": { "type": "AssumedRole",
                  "arn": "arn:aws:sts::…:assumed-role/recon-api-review-dev/…" }
```

Không có chỗ nào chứa `an@congty.vn`. Kể cả bật **data events** (tốn thêm tiền)
cũng chỉ thấy `PutItem by assumed-role/...`. Danh tính người dùng **chỉ app biết**,
qua JWT của Cognito (`api/http.py::request_user`). Vì vậy Lớp 1 phải do app ghi,
không phải CloudTrail.

**c. Grafana chỉ là lớp vẽ.** Nó không sinh dữ liệu; không có metric/log thì
không có gì để vẽ. Lý do loại **Amazon Managed Grafana là giá**: tối thiểu
**$9/editor/workspace/tháng**, và mỗi workspace bắt buộc có ít nhất một editor
license kể cả khi không ai đăng nhập ([pricing](https://aws.amazon.com/grafana/pricing/)).

Về xác thực thì AMG có **hai** đường: SAML 2.0 hoặc IAM Identity Center — chỉ
nhánh Identity Center mới kéo theo AWS Organizations
([SAML](https://docs.aws.amazon.com/grafana/latest/userguide/authentication-in-AMG-SAML.html),
[IAM Identity Center](https://docs.aws.amazon.com/grafana/latest/userguide/authentication-in-AMG-SSO.html)).
Điểm chung của cả hai: **không dùng được IAM user/role trực tiếp**. Làm dữ liệu
trước, Grafana nối vào sau cũng được, không phải sửa worker.

## 3. Kiến trúc đề xuất — một nguồn, một trang

```
common/audit.py ── print 1 dòng JSON ──┐
log_ai_call ── cùng dòng đó + khối EMF ─┤
Lambda/SFN/API GW ── metric có sẵn ─────┼──▶ CloudWatch Logs (10 log group, giữ 10 năm)
                                        │            │
                                        │      Logs Insights
                                        ▼            ▼
                           CloudWatch Dashboard "recon-{env}" (Terraform)
```

### Vì sao KHÔNG để audit trong DynamoDB
- **Không ai đọc được.** `audit_log` hiện không có route API nào đọc, và mentor
  không có tài khoản AWS để mở DynamoDB console. Audit không ai xem được thì
  không phải audit.
- **Thế mạnh của DynamoDB không dùng tới.** Nó mạnh ở tra cứu theo khoá trong
  đường request. Không code runtime nào tra audit; chỉ test đọc nó.
- **Chính app sửa được vết của mình.** Cả 5 IAM role đang có `PutItem` **và**
  `UpdateItem` trên bảng `audit_log`. Trong khi đó quyền log của đúng 5 role ấy
  chỉ gồm `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` —
  **ghi được, không sửa/xoá được**. Cùng một ứng dụng, cùng một bộ quyền, mà kho
  log cho tính bất biến còn kho DynamoDB thì không.

### Vì sao KHÔNG ghi thẳng lên S3
S3 không ghi nối (append) được: mỗi sự kiện thành **một object nhỏ** → hàng nghìn
file vụn, Athena quét chậm và tốn; Lambda lại phải có `s3:PutObject` lên đúng chỗ
lưu audit, tức vẫn ghi đè được. Muốn lưu trữ dài hạn thì đường đúng là
CloudWatch Logs → Firehose → S3. Hiện **chưa làm**: log group đã giữ 10 năm nên
đủ về thời gian; S3 chỉ cần khi phải chứng minh log **không sửa được** (§8).

### DynamoDB còn giữ gì
Bốn bảng còn lại giữ **trạng thái nghiệp vụ** mà app đọc mỗi request:
`reconciliation.review` (kết luận duyệt hiện hành), `document.edited_by` (người
sửa gần nhất), `document.status/step`. Đó là dữ liệu nghiệp vụ, không phải audit
trail. Chỉ *lịch sử sự kiện* chuyển sang CloudWatch Logs.

Việc chuyển **không làm một bước**: ghi kép trước, bỏ bảng sau khi dashboard đã
chạy thật trên AWS — xem §13.

## 4. Sự kiện audit

Mỗi sự kiện là **một dòng JSON** trên stdout của Lambda:

```json
{"audit": 1, "action": "REVIEW_DECISION", "actor": "an@congty.vn", "source": "api",
 "project_id": "prj-8f3a", "entity_id": "rec-2c91", "timestamp": "2026-09-16T09:01:29Z",
 "detail": {"decision": "APPROVED", "comment": null}}
```

`actor`, `source`, `project_id` để **top-level** để Logs Insights lọc trực tiếp.
Hiện "ai làm" đang nằm lồng trong `detail` dưới ba tên khác nhau (`reviewer`,
`triggered_by`, `edited_by`) — không lọc chung được.

| Action | Ghi khi | Hiện có? |
|---|---|---|
| `AI_CALL` | Mỗi lần gọi Document AI/Textract/Gemini — **rule cứng**, ghi cả khi lỗi và 429 | ✅ |
| `PIPELINE_STEP` | Vào/xong/lỗi từng bước, kèm `attempt` | ✅ |
| `PROCESS_RUN` | Mọi quyết định của `/process`, **kể cả quyết định bỏ qua** | ✅ |
| `EDIT_OVERWRITTEN` | `force_edited=true` cho AI ghi đè dữ liệu người đã sửa — thao tác phá huỷ duy nhất | ✅ |
| `REVIEW_EDIT` | Người sửa tay một chứng từ | ✅ |
| `REVIEW_DECISION` | Duyệt/từ chối một đợt đối chiếu | ✅ |
| `PROJECT_CREATED` | Tạo project | ✅ |
| `DOCUMENTS_UPLOADED` | Upload chứng từ (ai đưa file vào hệ thống) | ✅ |
| `RECONCILE_RUN` | Bấm đối chiếu | ✅ |
| `PROCESS_STOP_REQUESTED` | Bấm Dừng một run đang chạy | ✅ |
| `PROJECT_DELETE_STARTED` | Bắt đầu xoá project — ghi trước khi xoá | ✅ |
| `PROJECT_DELETED` | Xoá project xong, kèm số lượng đã xoá | ✅ |
| `PROCESS_RUN_UNSTUCK` | Bấm Dừng trên run đã chết — run được kết thúc và nhả khoá ngay | ✅ |
| `REQUEST_REJECTED` | Thao tác bị từ chối (400/404/409) ở bất kỳ route nào khác `GET` — ghi tại router (`api/handler.py`), kèm `method`, `path`, `status_code`, `error`. Thiếu nó thì "bấm Xử lý mà không thấy gì" không tra lại được | ✅ |

## 5. Metric AI (EMF)

**AWS không nhìn thấy các lệnh gọi sang Google.** Chi phí Gemini/Document AI
không nằm trong hoá đơn AWS, và 429 là lỗi hay gặp nhất của hệ thống này. Không
tự phát metric thì không có số nào để xem.

Dùng **EMF** (Embedded Metric Format): chính dòng `AI_CALL` mang thêm khối `_aws`,
CloudWatch tự bóc thành metric. Một lần ghi, hai công dụng, và **không thêm thư
viện** vào gói Lambda (chỉ `json` + `print`, giữ nguyên quy ước ở `packaging.py`).

| Metric | Đơn vị | Dùng để |
|---|---|---|
| `AiCostUsd` | None | Chi phí AI theo ngày (đường ngang $1) |
| `AiLatencyMs` | Milliseconds | Latency p90 |
| `AiRateLimited` | Count | Số lần 429 |

Giá trị metric phải nằm ở **root** của dòng JSON — đặt trong `detail` thì
CloudWatch không thấy.

**Đếm custom metric cho đúng:** CloudWatch tính tiền theo **từng tổ hợp
`namespace` + tên metric + giá trị dimension**, không phải theo số tên metric.
Thiết kế này dùng đúng một dimension `Service="recon"` → **3 metric**, nằm trong
10 cái miễn phí. Nhưng thêm dimension `Model` là **3 × số engine** (hệ thống có
5 engine OCR + Gemini) → **18 metric**, vượt trần ngay. Muốn tách theo model thì
dùng Logs Insights (`stats sum(AiCostUsd) by detail.model`) — miễn phí trong
hạn 5 GB, không sinh custom metric.

## 6. Dashboard

Một dashboard tên `{app_name}-{env}` (dev: `recon-dev`), khai bằng Terraform
(`aws_cloudwatch_dashboard.poc`), 4 hàng. Link lấy từ output `dashboard_url`:

| Hàng | Widget | Nguồn |
|---|---|---|
| **Audit** | Bảng 100 sự kiện gần nhất: thời gian, `actor`, `action`, `detail.step`, `detail.status`, `project_id`, `entity_id` · đếm theo `action` | Logs Insights |
| **AI** | Chi phí/ngày + **đường ngang $1** · số lần 429 · latency p90 | EMF `Recon/AI` |
| **Pipeline** | Step Functions Succeeded/Failed · API Gateway 5xx · Latency | Metric có sẵn |
| **Lỗi** | Lambda Errors theo function · bảng log lỗi gần nhất | Có sẵn + Logs Insights |

Query mẫu:

```sql
-- Nhật ký audit. detail.step chỉ có ở PIPELINE_STEP; detail.status có ở
-- PIPELINE_STEP và AI_CALL. Thiếu hai cột này thì mọi dòng PIPELINE_STEP trông
-- giống hệt nhau.
fields @timestamp, actor, action, detail.step, detail.status, project_id, entity_id
| filter audit = 1 | sort @timestamp desc | limit 100

-- Ai làm gì nhiều nhất
filter audit = 1 | stats count() by action, actor

-- Thao tác phá huỷ: AI ghi đè công review
filter action = "EDIT_OVERWRITTEN" | sort @timestamp desc

-- Chi phí AI theo model
filter action = "AI_CALL" | stats sum(AiCostUsd) by detail.model
```

## 7. Mentor xem bằng cách nào

Mentor **không có tài khoản AWS**, và account AWS này **dùng chung với project
khác**. Hai điều đó quyết định cách làm:

**Chính — demo + ảnh chụp (không cấp quyền cho ai):**
- Họp thì mở dashboard trực tiếp trong console.
- Báo cáo thì xuất ảnh widget bằng `aws cloudwatch get-metric-widget-image`, và
  xuất bảng audit từ Logs Insights ra CSV.

**Nếu mentor cần tự vào xem:** CloudWatch cho **chia sẻ dashboard** với tối đa 5
email, mỗi người tự đặt mật khẩu, không cần tài khoản AWS, không tốn phí
([dashboard-sharing](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/cloudwatch-dashboard-sharing.html)).
Hai cái giá phải biết trước:

1. **Người được chia sẻ query được mọi metric trong account.**
   `cloudwatch:GetMetricData` không giới hạn được theo metric → mentor thấy cả
   metric của project khác trong account.
2. **Widget log mặc định bị ẩn** với người được chia sẻ. Muốn mentor thấy bảng
   audit thì phải sửa tay policy của role `CWDBSharing*` do AWS tạo, thêm
   `logs:StartQuery`/`GetQueryResults`/… và **giới hạn đúng ARN 10 log group** của
   project này. Quên bước này thì mentor thấy biểu đồ nhưng bảng audit trống.

Cũng vì lý do 1: **không chia sẻ công khai** (ai có link là có những quyền trên).

## 8. Giữ log bao lâu

**Đang đặt: `log_retention_days = 3653` (10 năm)** — mức **tối đa** CloudWatch
Logs cho phép, chọn theo hạn lưu tài liệu kế toán. Là biến Terraform, hạ xuống
30 được nếu không coi audit là hồ sơ kế toán.

- `retentionInDays` chỉ nhận **đúng một danh sách** giá trị: 1, 3, 5, 7, 14, 30,
  60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288,
  3653 ([PutRetentionPolicy](https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_PutRetentionPolicy.html)).
  Số khác (10, 15, 45…) làm `apply` **chết**, không làm tròn — nên biến có
  `validation` chặn ngay lúc `plan`.
- Log group của Lambda mặc định **không bao giờ hết hạn** → vẫn phải khai
  `aws_cloudwatch_log_group` cho cả 10 function để nắm quyền quyết định.
- Log quá hạn có thể còn tới **72 giờ** trước khi bị xoá thật (tài liệu AWS).

**10 năm đủ về THỜI GIAN, chưa đủ về BẤT BIẾN.** Luật Kế toán và Nghị định
174/2016/NĐ-CP buộc lưu tài liệu kế toán tối thiểu 5–10 năm tuỳ loại, nhưng kiểm
toán còn hỏi "có sửa được không". CloudWatch Logs **không có WORM**: ai có
`logs:DeleteLogGroup` là xoá sạch. Muốn chứng minh không sửa được thì phải đẩy
sang **S3 + Object Lock** (Logs → Firehose → S3, rồi Athena để tra).

Hai điểm yếu nữa của cách giữ 10 năm ngay trong log group:
1. **Giữ cả log vận hành**: `START/END/REPORT` và traceback cũng nằm 10 năm cùng
   chỗ với audit, dù chúng hết giá trị sau vài tuần.
2. **Không tách được hạn**: một log group chỉ có một retention, nên không thể
   "audit 10 năm, log vận hành 30 ngày" nếu không tách kho.

Cả hai chỉ giải được bằng nhánh S3 — vẫn là câu hỏi §12.1 cho mentor.

## 9. Chi phí

Nằm trong free tier của CloudWatch ([pricing](https://aws.amazon.com/cloudwatch/pricing/)):

| Hạng mục | Free tier | Thiết kế này dùng |
|---|---|---|
| Logs (ingest + lưu + Insights scan) | 5 GB/tháng | Log JSON của POC rất nhỏ — nhưng giữ **10 năm** thì phần lưu **cộng dồn** chứ không reset hàng tháng; ở quy mô POC vẫn là vài cent, ở production thì phải tính lại |
| Custom metrics | 10 | 3 (§5) |
| Alarm | 10 | 0 |
| Dashboard | 3, mỗi cái ≤50 metric | 1 |
| Chia sẻ dashboard | Miễn phí | 0–1 |
| CloudTrail event history 90 ngày | Miễn phí, không cần tạo gì | dùng nguyên |

Chỗ có thể vượt: mở dashboard nhiều lần → query Logs Insights quét lặp lại;
log ingest nếu bật thêm access log của API Gateway.

## 10. Có sẵn · Cần làm · Để sau

| Nhóm | Hạng mục |
|---|---|
| ✅ **AWS có sẵn** (0 dòng code) | Lambda tự đẩy stdout vào CloudWatch Logs (cả 5 role đã có `CreateLogGroup`/`CreateLogStream`/`PutLogEvents` — đủ để ghi, **không** có quyền xoá) · metric Lambda/Step Functions/API Gateway/DynamoDB · **execution history** của Step Functions (đồ thị, state lỗi, input/output) · automatic dashboard theo dịch vụ · Cost Explorer · CloudTrail event history 90 ngày |
| ✅ **Đã làm xong trong code** | `actor`/`source`/`project_id` top-level · 3 action còn thiếu (§4) · EMF cho metric AI (§5) · bỏ bảng `audit_log` · 10 log group giữ 10 năm (biến `log_retention_days`) · dashboard 4 hàng (§6) + output `dashboard_url` |
| 🔧 **Còn lại** | `terraform apply` rồi xác minh trên AWS thật (§13) — chưa làm thì chưa ai xem được gì |
| ⏸ **Để sau, ngoài POC** | Alarm + SNS · lưu trữ dài hạn S3/Firehose/Athena · CloudTrail trail (chỉ cần nếu muốn giữ > 90 ngày) · access log API Gateway (thấy được request bị authorizer chặn — Lambda không bao giờ thấy) · Step Functions logging · X-Ray · Grafana |

## 11. Phương án đã loại

| Loại | Vì sao |
|---|---|
| AWS Audit Manager | Đóng với khách hàng mới; sai mục đích (§2a) |
| CloudTrail cho audit nghiệp vụ | Không biết người dùng cuối (§2b) |
| CloudTrail data events | Tốn tiền mà vẫn không định danh được người dùng |
| Audit API trong API người dùng | Người xem là admin/mentor, không phải user; mở route trên cùng API Gateway thì một lỗi phân quyền là lộ audit; và Logs Insights đã làm sẵn việc lọc/phân trang |
| Tab audit trong web người dùng | Dashboard phải là trang riêng, tách khỏi app |
| Giữ `audit_log` ở DynamoDB + thêm GSI | Vá chỗ sai thay vì đổi kho (§3) |
| Ghi audit thẳng lên S3 | S3 không append; file vụn; Lambda vẫn ghi đè được (§3) |
| Amazon Managed Grafana | **Giá**: $9/editor/workspace/tháng, mỗi workspace bắt buộc ≥1 editor license kể cả khi không ai đăng nhập (§2c). Không phải vì Identity Center — AMG có cả đường SAML |
| AWS Powertools (logger/metrics) | Thêm thư viện vào mọi gói Lambda, đổi lại chỉ tiết kiệm ~30 dòng |

> **Ghi kép (DynamoDB + dòng JSON)** từng được chọn làm bước chuyển tiếp, nhưng
> lúc triển khai đã **bị bỏ qua** — code đi thẳng tới đích. Hệ quả ở §13.

## 12. Cần mentor quyết

1. **Vết audit có cần BẤT BIẾN không?** Thời hạn đã xử lý: log giữ **10 năm**,
   khớp mức tối đa của Luật Kế toán / Nghị định 174/2016/NĐ-CP. Câu còn lại là
   kiểm toán có đòi chứng minh log **không sửa/xoá được** hay không — CloudWatch
   Logs không làm được điều đó (ai có `logs:DeleteLogGroup` là xoá sạch). Nếu
   "có", phải làm nhánh Firehose → S3 + Object Lock (§8).
2. Mentor muốn **tự vào xem dashboard** (chấp nhận thấy metric của project khác
   trong account), hay xem qua demo và ảnh trong báo cáo (§7)?
3. Có cần **cảnh báo tự động** (email khi run lỗi / chi phí AI vượt $1/ngày), hay
   dashboard là đủ cho POC?

## 13. Trạng thái triển khai và thứ còn phải xác minh

Kế hoạch ban đầu chia ba bước: **ghi kép** (giữ `put_item`, thêm dòng JSON) →
dashboard → bỏ bảng. Thực tế **bước ghi kép đã bị bỏ qua**: code đi thẳng tới
đích, `put_item` bị xoá cùng lúc với việc thêm dòng JSON.

**Đã đạt:** quyền của cả 5 role trên kho audit giờ chỉ là
`CreateLogGroup`/`CreateLogStream`/`PutLogEvents` — app **không sửa/xoá được vết
của chính nó**, đúng tính chất mong muốn ở §3. Test (257) xanh, `pyflakes` sạch,
`terraform validate` Success, `fmt -check` sạch.

**Cái giá đã trả:** không còn bảng DynamoDB để đối chứng. Nếu Logs Insights không
hiện đúng thứ cần, sẽ **không có nguồn thứ hai** để so. Vì vậy việc xác minh sau
`apply` là **bắt buộc**, không phải tuỳ chọn:

1. `terraform apply` (stack chưa apply lần nào → không cần import log group).
2. Chạy một lần `/process` với chứng từ thật.
3. Logs Insights `filter audit = 1 | sort @timestamp desc`: phải có `PROCESS_RUN`,
   `PIPELINE_STEP`, `AI_CALL`; `actor` ở sự kiện từ API phải là **tên người đăng
   nhập**, không phải `null`.
4. Metrics → `Recon/AI`: `AiCostUsd`, `AiLatencyMs`, `AiRateLimited` phải có số.
   Không thấy = EMF sai dạng hoặc log bị bọc (§5 và bẫy log format).
5. Dashboard đủ 4 hàng, không widget nào trống. Widget chi phí dùng `period =
   86400`, nên nếu khoảng thời gian của dashboard đang là 3 giờ thì nó **trông như
   rỗng** — đổi range sang 1 tuần trước khi kết luận là lỗi.
6. `aws logs describe-log-groups`: 10 log group, `retentionInDays: 3653`.

Chưa xong bước này thì tài liệu chỉ mô tả **ý định**, không mô tả hệ thống đang chạy.
