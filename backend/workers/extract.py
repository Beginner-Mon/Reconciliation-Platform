from common import (
    GEMINI_MODEL,
    RateLimitError,
    estimate_gemini_cost,
    extract_with_gemini,
    extraction_key,
    log_ai_call,
    now_ms,
    read_json,
    write_json,
)

from core import check_grounding

from .steps import begin_step, finish_step


def lambda_handler(event: dict, context) -> dict:
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
    )

    document_type = extracted.get("document_type")
    data = {**(extracted.get("data") or {}), "document_type": document_type}
    confidence = extracted.get("confidence") or {}

    key = extraction_key(project_id, document_id)
    write_json(key, extracted)

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
        "document_type": document_type,
        "ungrounded_fields": ungrounded,
    }
    if data.get("po_number"):
        updates["po_number"] = data["po_number"]

    finish_step(document_id, "extract", **updates)

    return {**event, "extraction_s3_key": key, "document_type": document_type}
