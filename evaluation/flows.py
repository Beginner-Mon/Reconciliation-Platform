"""Ba luồng OCR/extract đem ra so sánh trong spike.

Mục đích: quyết định có cần Document AI trong pipeline hay không. Chênh lệch
chi phí giữa luồng 1 và luồng 3 khoảng 20-50 lần mỗi trang, nên đây là quyết
định kiến trúc chứ không phải tối ưu vặt.
"""

import os
import time

from common import ocr_engines
from common.ai_clients import (
    estimate_docai_cost,
    estimate_gemini_cost,
    extract_with_gemini,
    extract_with_gemini_pdf,
    ocr_with_document_ai,
)

import ocr_cache

MIME_BY_EXT = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "tiff": "image/tiff",
}


def mime_for(path) -> str:
    return MIME_BY_EXT.get(str(path).rsplit(".", 1)[-1].lower(), "application/pdf")


def _result(data, confidence, cost, pages, usage, elapsed) -> dict:
    return {
        "data": data,
        "confidence": confidence,
        "cost_usd": cost,
        "pages": pages,
        "usage": usage,
        "latency_s": round(elapsed, 2),
    }


def _engine_gemini(engine: str):
    """<engine OCR> -> Gemini đọc text OCR. Cùng một khung cho MỌI engine.

    Trước đây mỗi engine có một hàm chép tay, khác nhau đúng hai chỗ: gọi hàm
    nào và nhân đơn giá nào. Đó chính là chỗ đơn giá lệch được — nay cả hai đều
    tra từ common/ocr_engines.py.
    """

    def flow(content: bytes, path) -> dict:
        started = time.time()
        ocr_json, cached = ocr_cache.run(
            engine, content, lambda: ocr_engines.run(engine, content, mime_for(path))
        )
        pages = len(ocr_json.get("pages") or [])
        extracted = extract_with_gemini(ocr_json)
        usage = extracted.pop("_usage", {}) or {}
        cost = (0 if cached else ocr_engines.estimate_cost(engine, pages))
        cost += estimate_gemini_cost(usage)
        return _result(
            {**(extracted.get("data") or {}), "document_type": extracted.get("document_type")},
            extracted.get("confidence") or {},
            cost,
            pages,
            usage,
            time.time() - started,
        )

    return flow


def gemini_direct(content: bytes, path) -> dict:
    """Gemini đọc thẳng file gốc, bỏ hẳn Document AI."""
    started = time.time()
    extracted = extract_with_gemini_pdf(content, mime_for(path))
    usage = extracted.pop("_usage", {}) or {}
    cost = estimate_gemini_cost(usage)
    return _result(
        {**(extracted.get("data") or {}), "document_type": extracted.get("document_type")},
        extracted.get("confidence") or {},
        cost,
        None,
        usage,
        time.time() - started,
    )


def formparser_kv_only(content: bytes, path) -> dict:
    """Chỉ dùng key-value pairs của Form Parser, KHÔNG gọi LLM.

    Luồng này gần như chắc chắn thua về độ chính xác, nhưng chạy để có số liệu
    trả lời câu 'Form Parser tự nó đã đủ chưa' trong báo cáo kỹ thuật.
    """
    started = time.time()
    ocr_json = ocr_with_document_ai(content, mime_for(path))
    pages = len(ocr_json.get("pages") or [])
    data = {}
    for page in ocr_json.get("pages", []):
        for kv in page.get("key_value_pairs", []):
            key = str(kv.get("key", "")).strip().rstrip(":").lower()
            if key:
                data.setdefault(key, kv.get("value"))
    return _result(data, {}, estimate_docai_cost(pages), pages, {}, time.time() - started)


def _ocr_only(engine: str):
    def call(content: bytes, path) -> dict:
        return ocr_engines.run(engine, content, mime_for(path))

    return call


# Chỉ bước OCR, chưa gọi LLM — dùng để xem output thô trả về những gì.
# Ba bảng dưới đây SINH TỪ registry, không khai tay: đây đúng chỗ đơn giá từng
# lệch 20 lần vì được chép sang một bảng khác rồi quên sửa.
OCR_ONLY = {name: _ocr_only(name) for name in ocr_engines.ENGINES}

OCR_ONLY_ENV = {
    name: spec["processor_env"] for name, spec in ocr_engines.ENGINES.items()
}

OCR_ONLY_USD_PER_PAGE = {
    name: ocr_engines.usd_per_page(name) for name in ocr_engines.ENGINES
}


FLOWS = {
    **{f"{name}_gemini": _engine_gemini(name) for name in ocr_engines.ENGINES},
    "formparser_kv_only": formparser_kv_only,
    "gemini_direct": gemini_direct,
}


def missing_env(flow_name: str) -> list[str]:
    """Biến môi trường còn thiếu để chạy được luồng này.

    Mỗi engine đòi thứ khác nhau: engine Google cần DOCAI_PROJECT + processor
    id, engine Textract cần một bucket S3 THẬT (Textract async không nhận bytes
    — xem backend/common/textract.py).
    """
    thieu = [] if os.environ.get("GEMINI_API_KEY") else ["GEMINI_API_KEY"]
    if flow_name == "gemini_direct":
        return thieu

    engine = "formparser" if flow_name == "formparser_kv_only" else flow_name[: -len("_gemini")]
    return thieu + ocr_engines.missing_env(engine)
