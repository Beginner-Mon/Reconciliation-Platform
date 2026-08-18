from common import (
    RateLimitError,
    estimate_docai_cost,
    log_ai_call,
    now_ms,
    ocr_key,
    ocr_with_document_ai,
    read_object,
    write_json,
)

from .steps import begin_step, finish_step

MIME_BY_EXT = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "tiff": "image/tiff",
}


def _mime_for(s3_key: str) -> str:
    ext = s3_key.rsplit(".", 1)[-1].lower() if "." in s3_key else "pdf"
    return MIME_BY_EXT.get(ext, "application/pdf")


def lambda_handler(event: dict, context) -> dict:
    project_id = event["project_id"]
    document_id = event["document_id"]
    s3_key = event["s3_key"]

    begin_step(document_id, "ocr")
    content = read_object(s3_key)
    started = now_ms()

    try:
        ocr_json = ocr_with_document_ai(content, _mime_for(s3_key))
    except RateLimitError as exc:
        log_ai_call(
            document_id,
            model="documentai-form-parser",
            started_at_ms=started,
            status="rate_limited",
            error=str(exc),
            latency_ms=now_ms() - started,
        )
        raise
    except Exception as exc:
        log_ai_call(
            document_id,
            model="documentai-form-parser",
            started_at_ms=started,
            status="error",
            error=str(exc),
            latency_ms=now_ms() - started,
        )
        raise

    page_count = len(ocr_json.get("pages") or [])
    log_ai_call(
        document_id,
        model="documentai-form-parser",
        started_at_ms=started,
        status="ok",
        estimated_cost_usd=estimate_docai_cost(page_count),
        latency_ms=now_ms() - started,
    )

    key = ocr_key(project_id, document_id)
    write_json(key, ocr_json)
    finish_step(document_id, "ocr", ocr_s3_key=key, page_count=page_count)

    return {**event, "ocr_s3_key": key, "page_count": page_count}
