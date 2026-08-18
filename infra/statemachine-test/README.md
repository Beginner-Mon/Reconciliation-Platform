# Kiểm thử luồng Step Functions (không cần deploy, không cần Docker)

Có **hai mức** kiểm tra, giá trị khác nhau — nên làm cả hai.

## Mức 1 — Validate định nghĩa (1 giây, miễn phí, chỉ cần `aws configure`)

Bắt lỗi cú pháp ASL, JSONPath sai, state trỏ tới state không tồn tại.
Gọi API thật của AWS nhưng **không tạo tài nguyên**, không tốn tiền.

```powershell
cd infra
$asl = (Get-Content modules\aws\statemachine.asl.json -Raw) `
    -replace '\$\{\w+\}', 'arn:aws:lambda:ap-southeast-1:000000000000:function:fake'
Set-Content -Encoding utf8 $env:TEMP\rendered.asl.json $asl
aws stepfunctions validate-state-machine-definition `
    --definition file://$env:TEMP/rendered.asl.json --type STANDARD --severity WARNING
```

Kết quả mong đợi: `"result": "OK"`, `"diagnostics": []`.

## Mức 2 — Chạy thật luồng với Lambda mock (Step Functions Local)

Bắt lỗi **hành vi**: nhánh `Catch` có nhảy đúng chỗ không, Map có sống sót khi
1 document lỗi không, nhánh giải phóng `processing_run_id` có chạy không.
Đây là những thứ pytest **không** kiểm được.

### Cần gì

- **Java 17+** (Step Functions Local 2.0.0 biên dịch bằng Java 17).
  Java 8 sẽ báo `UnsupportedClassVersionError`.
  Không muốn cài vào máy thì tải JRE portable:
  `https://api.adoptium.net/v3/binary/latest/21/ga/windows/x64/jre/hotspot/normal/eclipse`
- **StepFunctionsLocal.jar**: `https://s3.amazonaws.com/stepfunctionslocal/StepFunctionsLocal.zip`
- **KHÔNG cần Docker.** Docker chỉ là một cách đóng gói khác của cùng công cụ này.

### Chạy

```powershell
# 1. Khởi động server (cửa sổ riêng). Mock config CHỈ đọc lúc khởi động —
#    sửa MockConfigFile.json thì phải restart.
$env:SFN_MOCK_CONFIG = "<đường dẫn tuyệt đối>\infra\statemachine-test\MockConfigFile.json"
java -jar StepFunctionsLocal.jar

# 2. Cửa sổ khác
cd infra\statemachine-test
..\..\backend\.venv\Scripts\python.exe run.py
```

Kết quả mong đợi:

```
OK   ThanhCong      SUCCEEDED  Ocr -> Extract -> Validate -> Reconcile
OK   DocLoiOcr      SUCCEEDED  Ocr -> MarkOcrFailed -> Reconcile
OK   ReconcileLoi   FAILED     Ocr -> Extract -> Validate -> Reconcile -> MarkRunFailed
```

### Ba tính chất đang được nghiệm thu

| Test case | Chứng minh điều gì |
|---|---|
| `ThanhCong` | Luồng thuận đi hết 4 state |
| `DocLoiOcr` | **1 document lỗi KHÔNG giết cả run** — Map vẫn thoát bình thường (`SUCCEEDED`) và `Reconcile` vẫn chạy, nhờ `Catch` nằm **bên trong** iterator |
| `ReconcileLoi` | Lỗi toàn cục vẫn chạy `MarkRunFailed` — state gọi `release_processing_run`. Thiếu nó thì project **kẹt vĩnh viễn**, không bấm xử lý lại được |

## Giới hạn đã biết của Step Functions Local 2.0.0

SFL **không hỗ trợ `ItemProcessor`**, chỉ hiểu key `Iterator` đã deprecated.
Đã bisect xác nhận: `ItemSelector` và `JitterStrategy` thì SFL chạy bình thường,
chỉ riêng `ItemProcessor` làm nó báo `Parse error` lúc `start-execution`
(trong khi `create-state-machine` vẫn nhận).

Vì vậy `run.py` **đổi `ItemProcessor` → `Iterator` cho bản chạy local** và giữ
nguyên file gốc. `statemachine.asl.json` dùng `ItemProcessor` là **đúng** —
AWS thật đã validate 0 diagnostic ở Mức 1. Đừng "sửa" file gốc theo SFL.
