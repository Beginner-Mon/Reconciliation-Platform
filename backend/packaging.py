"""Mỗi Lambda MỘT gói riêng — chỉ chứa thư viện chính nó cần.

Trước file này cả 10 function dùng chung một zip 77 MB. Hậu quả đo được:
8/10 function cõng 44 MB thư viện Google mà không bao giờ chạm tới, và cả 10
cõng 20 MB boto3 mà Lambda runtime đã cấp sẵn.

    trước:  10 × 77 MB  = 769 MB
    sau  :               155 MB

Cái tốn nhất là COLD START — Lambda phải tải và giải nén cả gói trước khi chạy
dòng code đầu tiên. Bốn function `api-*` nằm ngay trên đường request, chúng đi
từ 77 MB xuống 9 MB.

Đây KHÔNG phải chuyện phân quyền: IAM gắn vào function chứ không gắn vào gói, và
5 role đã tách sẵn từ trước. Gói quyết định code NÀO CÓ MẶT; IAM quyết định code
đó LÀM ĐƯỢC GÌ.

CODE ỨNG DỤNG THÌ CHÉP HẾT VÀO MỌI GÓI — cả `api/ common/ core/ schemas/
workers/` cộng lại chỉ 150 KB, tách ra không tiết kiệm được gì mà lại phải bổ
`common/` thành nhiều mảnh. Chỉ THƯ VIỆN mới chia.

`boto3` KHÔNG có trong gói nào: runtime python3.11 của Lambda đã có sẵn. Nó vẫn
nằm trong `requirements.txt` vì dev server chạy ở máy thì cần.
"""

# Tên khoá ở đây phải trùng khít tên function bên Terraform:
#   worker  ->  local.workers        (ocr, extract, ...)
#   api     ->  local.api_functions  (projects, ...) nhưng thêm tiền tố "api-"
# `tests/test_packaging.py` đọc thẳng main.tf và khoá hai bên lại với nhau.
#
# `phai_co_module` là thứ bảo vệ thật sự: thiếu một gói thì Lambda chỉ chết LÚC
# CHẠY, và với import lười (Google nằm trong thân hàm ở `ai_clients.py`) thì
# import module handler thôi KHÔNG phát hiện được. Script build kiểm từng tên
# dưới đây CÓ MẶT trong thư mục vừa dựng hay không.
#
# Kiểm SỰ HIỆN DIỆN chứ không nạp thử: wheel cài bằng `--platform manylinux2014`
# chứa phần biên dịch cho Linux (`pydantic_core._pydantic_core`), nạp trên
# Windows là chết dù gói hoàn toàn đúng cho Lambda.
PACKAGES = {
    # --- worker chạy trong Step Functions ---------------------------------
    "ocr": {
        # Textract đi qua boto3 (runtime cấp sẵn) nên không khai ở đây.
        "requires": ["google-cloud-documentai>=3.0", "pydantic>=2.7"],
        "phai_co_module": [
            "workers.ocr",
            "google.cloud.documentai",
            "google.oauth2.service_account",
        ],
    },
    "extract": {
        "requires": ["google-genai>=1.0", "pydantic>=2.7"],
        "phai_co_module": ["workers.extract", "google.genai", "pydantic"],
    },
    "validate": {
        "requires": ["pydantic>=2.7"],
        "phai_co_module": ["workers.validate", "pydantic"],
    },
    "reconcile": {
        "requires": ["pydantic>=2.7"],
        "phai_co_module": ["workers.reconcile", "pydantic"],
    },
    # Hai cái này chỉ đổi status trong DynamoDB, KHÔNG dùng schema — nhưng vẫn
    # phải có pydantic: `from common import ...` chạy `common/__init__.py`, file
    # đó import `ai_clients`, mà `ai_clients` import `schemas` -> pydantic.
    # Chuỗi này nạp NGAY lúc import, thiếu là chết cold start.
    # `test_moi_goi_du_thu_vien_nap_ngay_luc_import` suy ra bằng AST, không để
    # ai khai tay nữa — đó đúng là chỗ bản đầu tiên đã sai.
    "mark-failed": {
        "requires": ["pydantic>=2.7"],
        "phai_co_module": ["workers.mark_failed", "pydantic"],
    },
    "mark-run-failed": {
        "requires": ["pydantic>=2.7"],
        "phai_co_module": ["workers.mark_failed", "pydantic"],
    },
    # --- api sau API Gateway ----------------------------------------------
    # Cả bốn đều cần pydantic vì `api/handler.py` import cả bốn miền, mà miền
    # review/process gọi tới `core/` -> `schemas/`. Tách sâu hơn phải bổ
    # handler.py ra, đổi lại chỉ tiết kiệm 9 MB cho projects + documents.
    "api-projects": {
        "requires": ["pydantic>=2.7"],
        "phai_co_module": ["api.handler", "pydantic"],
    },
    "api-documents": {
        "requires": ["pydantic>=2.7"],
        "phai_co_module": ["api.handler", "pydantic"],
    },
    "api-review": {
        "requires": ["pydantic>=2.7"],
        "phai_co_module": ["api.handler", "pydantic"],
    },
    "api-process": {
        "requires": ["pydantic>=2.7"],
        "phai_co_module": ["api.handler", "pydantic"],
    },
}

# Code ứng dụng chép vào MỌI gói (150 KB, không đáng để chia).
APP_MODULES = ["api", "common", "core", "schemas", "workers"]
