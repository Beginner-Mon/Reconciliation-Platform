from common.ai_clients import (
    GEMINI_MODEL,
    estimate_gemini_cost,
    extract_with_gemini,
    now_ms,
)
from common.audit import log_ai_call
from common.errors import RateLimitError
from common.s3 import extraction_key, read_json, write_json

from core import check_grounding
from core.normalize import clean_extraction
from core.position import check_positions

from .steps import SKIPPED_CANCELLED, begin_step, finish_step, run_cancel_requested


def lambda_handler(event: dict, context) -> dict:
    if event.get("skipped"):
        return event
    if run_cancel_requested(event.get("run_id")):
        return {**event, "skipped": SKIPPED_CANCELLED}

    project_id = event["project_id"]
    document_id = event["document_id"]

    begin_step(document_id, "extract")
    ocr_json = read_json(event["ocr_s3_key"])
    started = now_ms()

    try:
        extracted = extract_with_gemini(ocr_json)
    except RateLimitError as exc:
        log_ai_call(
            document_id,
            model=GEMINI_MODEL,
            started_at_ms=started,
            status="rate_limited",
            error=str(exc),
            latency_ms=now_ms() - started,
            source="worker",
            project_id=project_id,
        )
        raise
    except Exception as exc:
        log_ai_call(
            document_id,
            model=GEMINI_MODEL,
            started_at_ms=started,
            status="error",
            error=str(exc),
            latency_ms=now_ms() - started,
            source="worker",
            project_id=project_id,
        )
        raise

    usage = extracted.pop("_usage", None)
    log_ai_call(
        document_id,
        model=GEMINI_MODEL,
        started_at_ms=started,
        status="ok",
        usage=usage,
        estimated_cost_usd=estimate_gemini_cost(usage or {}),
        latency_ms=now_ms() - started,
        source="worker",
        project_id=project_id,
    )

    document_type = extracted.get("document_type")
    data = {**(extracted.get("data") or {}), "document_type": document_type}
    confidence = extracted.get("confidence") or {}

    key = extraction_key(project_id, document_id)
    write_json(key, extracted)

    data, format_issues = clean_extraction(data)

    try:
        position_issues = check_positions(data, ocr_json.get("pages"))
    except Exception as exc:
        print(
            f"POSITION_CHECK_FAILED {document_id}: {type(exc).__name__}: {exc}",
            flush=True,
        )
        position_issues = []

    # Neo output của LLM về nguồn: giá trị nào không tìm thấy trong text OCR thì
    # nhiều khả năng bị bịa. CẢNH BÁO chứ không chặn — giá trị suy ra (subtotal
    # tính từ line items) có thể không xuất hiện nguyên văn mà vẫn đúng.
    #
    # Gọi ở ĐÂY chứ không ở worker validate: `ocr_json` đang sẵn trong bộ nhớ
    # (vừa đọc để dựng prompt) nên tốn 0 lời gọi S3 thêm. Kèm theo một hệ quả
    # đúng ý: sửa tay chạy lại validate chứ không chạy lại extract, nên giá trị
    # người sửa KHÔNG bị kiểm neo — người sửa chính là để sửa chỗ OCR đọc sai.
    ungrounded = check_grounding(data, ocr_json.get("text"))

    updates = {
        "extraction_s3_key": key,
        "extraction": data,
        "confidence": confidence,
        "format_issues": format_issues,
        "position_issues": position_issues,
        "dismissed_flags": [],
        "sources": None,
        "document_type": document_type,
        "role": data.get("role") or "other",
        "ungrounded_fields": ungrounded,
        "edited_fields": [],
        "edited_by": None,
        "edited_at": None,
    }
    if data.get("order_reference"):
        updates["po_number"] = data["order_reference"]
    elif data.get("po_number"):
        updates["po_number"] = data["po_number"]
    if data.get("doc_number"):
        updates["doc_number"] = data["doc_number"]
    if data.get("order_reference"):
        updates["order_reference"] = data["order_reference"]

    finish_step(document_id, "extract", **updates)

    return {**event, "extraction_s3_key": key, "document_type": document_type}
