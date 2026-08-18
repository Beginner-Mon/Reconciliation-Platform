"""Ba luồng OCR/extract đem ra so sánh trong spike.

Mục đích: quyết định có cần Document AI trong pipeline hay không. Chênh lệch
chi phí giữa luồng 1 và luồng 3 khoảng 20-50 lần mỗi trang, nên đây là quyết
định kiến trúc chứ không phải tối ưu vặt.
"""

import os
import time

from common.ai_clients import (
    DOCAI_OCR_USD_PER_PAGE,
    estimate_docai_cost,
    estimate_gemini_cost,
    extract_with_gemini,
    extract_with_gemini_pdf,
    ocr_with_document_ai,
    ocr_with_layout_parser,
)

import ocr_cache

OCR_PROCESSOR_ID = os.environ.get("DOCAI_OCR_PROCESSOR_ID", "")
LAYOUT_USD_PER_PAGE = float(os.environ.get("DOCAI_LAYOUT_USD_PER_PAGE", "0.010"))

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


def formparser_gemini(content: bytes, path) -> dict:
    """Luồng hiện tại: Document AI Form Parser -> Gemini đọc text OCR."""
    started = time.time()
    ocr_json, cached = ocr_cache.run(
        "formparser", content, lambda: ocr_with_document_ai(content, mime_for(path))
    )
    pages = len(ocr_json.get("pages") or [])
    extracted = extract_with_gemini(ocr_json)
    usage = extracted.pop("_usage", {}) or {}
    cost = (0 if cached else estimate_docai_cost(pages)) + estimate_gemini_cost(usage)
    return _result(
        {**(extracted.get("data") or {}), "document_type": extracted.get("document_type")},
        extracted.get("confidence") or {},
        cost,
        pages,
        usage,
        time.time() - started,
    )


def dococr_gemini(content: bytes, path) -> dict:
    """Enterprise Document OCR -> Gemini. Ứng viên chính.

    Vẫn là OCR thật, vẫn có bounding box (cần cho việc bôi sáng vị trí và cắt
    vùng chữ ký sau này), nhưng $1.50/1000 trang thay vì $30/1000 của Form
    Parser. Câu hỏi spike phải trả lời: key-value pairs của Form Parser có làm
    Gemini trích xuất chính xác hơn đủ để bù 20 lần chi phí không?
    """
    started = time.time()
    ocr_json, cached = ocr_cache.run(
        "dococr",
        content,
        lambda: ocr_with_document_ai(content, mime_for(path), processor_id=OCR_PROCESSOR_ID),
    )
    pages = len(ocr_json.get("pages") or [])
    extracted = extract_with_gemini(ocr_json)
    usage = extracted.pop("_usage", {}) or {}
    cost = (0 if cached else pages * DOCAI_OCR_USD_PER_PAGE) + estimate_gemini_cost(usage)
    return _result(
        {**(extracted.get("data") or {}), "document_type": extracted.get("document_type")},
        extracted.get("confidence") or {},
        cost,
        pages,
        usage,
        time.time() - started,
    )


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


def layout_gemini(content: bytes, path) -> dict:
    """Gemini Layout Parser -> Gemini. $10/1000 trang.

    Điểm giữa: xử lý được bảng PHỨC TẠP (merge cell, header lồng) — thứ cả
    Form Parser lẫn Document OCR đều không làm được. Đáng quan tâm vì line item
    của PO/hóa đơn nằm trong bảng.
    """
    started = time.time()
    ocr_json, cached = ocr_cache.run(
        "layout", content, lambda: ocr_with_layout_parser(content, mime_for(path))
    )
    pages = len(ocr_json.get("pages") or [])
    extracted = extract_with_gemini(ocr_json)
    usage = extracted.pop("_usage", {}) or {}
    cost = (0 if cached else pages * LAYOUT_USD_PER_PAGE) + estimate_gemini_cost(usage)
    return _result(
        {**(extracted.get("data") or {}), "document_type": extracted.get("document_type")},
        extracted.get("confidence") or {},
        cost,
        pages,
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


def ocr_formparser(content: bytes, path) -> dict:
    return ocr_with_document_ai(content, mime_for(path))


def ocr_dococr(content: bytes, path) -> dict:
    return ocr_with_document_ai(content, mime_for(path), processor_id=OCR_PROCESSOR_ID)


def ocr_layout(content: bytes, path) -> dict:
    return ocr_with_layout_parser(content, mime_for(path))


# Chỉ bước OCR, chưa gọi LLM — dùng để xem output thô trả về những gì.
OCR_ONLY = {
    "formparser": ocr_formparser,
    "layout": ocr_layout,
    "dococr": ocr_dococr,
}

OCR_ONLY_ENV = {
    "formparser": "DOCAI_PROCESSOR_ID",
    "layout": "DOCAI_LAYOUT_PROCESSOR_ID",
    "dococr": "DOCAI_OCR_PROCESSOR_ID",
}

OCR_ONLY_USD_PER_PAGE = {
    "formparser": 0.030,
    "layout": LAYOUT_USD_PER_PAGE,
    "dococr": DOCAI_OCR_USD_PER_PAGE,
}


FLOWS = {
    "formparser_gemini": formparser_gemini,
    "layout_gemini": layout_gemini,
    "dococr_gemini": dococr_gemini,
    "formparser_kv_only": formparser_kv_only,
    "gemini_direct": gemini_direct,
}

# Env var mà mỗi luồng cần, ngoài GEMINI_API_KEY và DOCAI_PROJECT.
PROCESSOR_ENV = {
    "formparser_gemini": "DOCAI_PROCESSOR_ID",
    "formparser_kv_only": "DOCAI_PROCESSOR_ID",
    "layout_gemini": "DOCAI_LAYOUT_PROCESSOR_ID",
    "dococr_gemini": "DOCAI_OCR_PROCESSOR_ID",
    "gemini_direct": None,
}
