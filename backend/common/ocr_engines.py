"""Bảng tra engine OCR — MỘT nguồn duy nhất cho hàm gọi, đơn giá và nhãn audit.

Trước file này, cùng một thông tin bị khai lại ở bốn chỗ rời nhau: `PROCESSORS`
(devserver/__main__.py), `OCR_ONLY` / `OCR_ONLY_ENV` / `OCR_ONLY_USD_PER_PAGE`
(evaluation/flows.py) và `ENGINE_LABEL` (evaluation/inspect_ocr.py). Thêm một
engine là phải sửa đúng bốn chỗ, và bốn chỗ phải khớp nhau.

Gõ lệch một chỗ thì dòng audit ghi sai tiền. Đã xảy ra rồi — §5 CLAUDE.md:
"ước tính chi phí lệch 20 lần vì lấy đơn giá Form Parser cho Document OCR".

ĐƠN GIÁ (USD/trang), kiểm tra 2026-09-04:
  Document AI  https://cloud.google.com/document-ai/pricing
    Enterprise Document OCR $0,0015 | Layout Parser $0,010 | Form Parser $0,030
  Textract     https://aws.amazon.com/textract/pricing  (us-west-2, ≤1M trang/tháng)
    DetectDocumentText $0,0015
    AnalyzeDocument FORMS $0,05 + TABLES $0,015 = $0,065; LAYOUT miễn phí kèm TABLES
  Triển khai ở us-east-1. Giá Textract KHÁC NHAU THEO REGION — đổi vùng thì
  kiểm lại bảng giá, nếu không dòng audit ghi sai tiền.

CẢNH BÁO NGHIỆP VỤ: Textract KHÔNG hỗ trợ tiếng Việt (chỉ English, French,
German, Italian, Portuguese, Spanish). Document AI đo được 99,5% dấu tiếng Việt
trên chứng từ thật — xem evaluation/FINDINGS.md.
"""

import os

from .ai_clients import ocr_with_document_ai, ocr_with_layout_parser
from .textract import ocr_with_textract, ocr_with_textract_analyze

# Mặc định là Textract vì đang có free tier của AWS.
#
# ĐÁNH ĐỔI CÓ Ý THỨC, không phải trôi vào: đo trên hoá đơn thật thì Textract mất
# gần hết dấu tiếng Việt (`Phuring Khuong Mai` <- `Phường Khương Mai`), nhưng số
# đọc đúng hết và Gemini vẫn trích xuất chính xác. Cảnh báo phải hiện NGAY chỗ
# người dùng chọn engine — `app_choices()[...]["supports_vietnamese"]` — chứ
# không chôn trong tài liệu.
DEFAULT_ENGINE = "textract"

# Engine mà APP được phép chọn: API, dev server và giao diện chỉ biết hai tên
# này. Thứ tự ở đây là thứ tự hiện trên giao diện.
#
# Bảng `ENGINES` bên dưới vẫn giữ ĐỦ NĂM. Xoá ba engine kia thì
# `evaluation/flows.py` mất luôn khả năng đo — nó sinh flow từ chính bảng này —
# còn tách làm hai bảng là đúng cái sai §5 CLAUDE.md cấm: hàm gọi, đơn giá và
# nhãn audit phải nằm CÙNG một chỗ, nếu không lại lệch tiền như lần trước.
APP_ENGINES = ("textract", "dococr")


def _document_ai(processor_env: str):
    def call(content: bytes, mime_type: str, s3_key: str | None = None) -> dict:
        return ocr_with_document_ai(
            content, mime_type, processor_id=os.environ.get(processor_env, "")
        )

    return call


def _layout(content: bytes, mime_type: str, s3_key: str | None = None) -> dict:
    return ocr_with_layout_parser(content, mime_type)


def _textract(content: bytes, mime_type: str, s3_key: str | None = None) -> dict:
    return ocr_with_textract(content, mime_type, s3_key=s3_key)


def _textract_analyze(content: bytes, mime_type: str, s3_key: str | None = None) -> dict:
    return ocr_with_textract_analyze(content, mime_type, s3_key=s3_key)


ENGINES = {
    "dococr": {
        "fn": _document_ai("DOCAI_OCR_PROCESSOR_ID"),
        "processor_env": "DOCAI_OCR_PROCESSOR_ID",
        "price_env": "DOCAI_OCR_USD_PER_PAGE",
        "usd_per_page": 0.0015,
        "label": "documentai-enterprise-document-ocr",
        "note": "Google Document AI Enterprise OCR",
        "cloud": "google",
        "supports_vietnamese": True,
    },
    "formparser": {
        "fn": _document_ai("DOCAI_PROCESSOR_ID"),
        "processor_env": "DOCAI_PROCESSOR_ID",
        "price_env": "DOCAI_USD_PER_PAGE",
        "usd_per_page": 0.030,
        "label": "documentai-form-parser",
        "note": "Form Parser",
        "cloud": "google",
        "supports_vietnamese": True,
    },
    "layout": {
        "fn": _layout,
        "processor_env": "DOCAI_LAYOUT_PROCESSOR_ID",
        "price_env": "DOCAI_LAYOUT_USD_PER_PAGE",
        "usd_per_page": 0.010,
        "label": "documentai-layout-parser",
        "note": "Layout Parser",
        "cloud": "google",
        "supports_vietnamese": True,
    },
    "textract": {
        "fn": _textract,
        "processor_env": None,
        "price_env": "TEXTRACT_USD_PER_PAGE",
        "usd_per_page": 0.0015,
        "label": "textract-detect-document-text",
        "note": "Amazon Textract DetectDocumentText",
        "cloud": "aws",
        "supports_vietnamese": False,
    },
    "textract-analyze": {
        "fn": _textract_analyze,
        "processor_env": None,
        "price_env": "TEXTRACT_ANALYZE_USD_PER_PAGE",
        "usd_per_page": 0.065,
        "label": "textract-analyze-document",
        "note": "Amazon Textract AnalyzeDocument FORMS+TABLES+LAYOUT",
        "cloud": "aws",
        "supports_vietnamese": False,
    },
}


def resolve(name: str) -> dict:
    """Tên sai thì NỔ NGAY kèm danh sách tên đúng.

    Im lặng rơi về engine mặc định là kiểu hỏng tệ nhất: hệ thống chạy đúng,
    tính sai tiền, và dòng audit ghi một engine thật ra không hề chạy.
    """
    spec = ENGINES.get(name)
    if spec is None:
        raise ValueError(
            f"Không có engine OCR {name!r}. Chọn trong: {', '.join(ENGINES)}"
        )
    return spec


def resolve_for_app(name: str) -> dict:
    """Như `resolve` nhưng CHỈ nhận engine mà app được phép chọn.

    `resolve` vẫn mở cho cả năm vì `evaluation/` cần đo. Còn lối vào của app —
    `/process`, `--processor`, giao diện — phải hẹp hơn: chọn nhầm một engine
    chỉ dùng để đo là chạy một luồng chưa ai kiểm trên chứng từ thật.
    """
    if name not in APP_ENGINES:
        raise ValueError(
            f"Engine OCR {name!r} không dùng được trong app. "
            f"Chọn trong: {', '.join(APP_ENGINES)}"
        )
    return resolve(name)


def usd_per_page(name: str) -> float:
    """Đơn giá đọc từ biến môi trường — giá đổi thì không phải sửa code."""
    spec = resolve(name)
    return float(os.environ.get(spec["price_env"], spec["usd_per_page"]))


def estimate_cost(name: str, page_count: int) -> float:
    return page_count * usd_per_page(name)


def missing_env(name: str) -> list[str]:
    """Biến môi trường còn thiếu để chạy được engine này."""
    spec = resolve(name)

    if spec["cloud"] == "google":
        thieu = [] if os.environ.get("DOCAI_PROJECT") else ["DOCAI_PROJECT"]
        if not os.environ.get(spec["processor_env"]):
            thieu.append(spec["processor_env"])
        return thieu

    # Textract async chỉ đọc file TỪ S3 thật. Trên Lambda file đã nằm sẵn ở đó
    # với đúng s3_key; ở devserver (moto) và evaluation (ổ đĩa) thì không, nên
    # phải có một bucket thật để đẩy file lên tạm. Xem common/textract.py.
    if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return []
    return [] if os.environ.get("TEXTRACT_S3_BUCKET") else ["TEXTRACT_S3_BUCKET"]


def run(name: str, content: bytes, mime_type: str, s3_key: str | None = None) -> dict:
    return resolve(name)["fn"](content, mime_type, s3_key)
