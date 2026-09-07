import os

from common import (
    RateLimitError,
    log_ai_call,
    now_ms,
    ocr_engines,
    ocr_key,
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


def _engine_name(event: dict) -> str:
    """Engine của LẦN CHẠY này, không phải của cả tiến trình.

    `OCR_ENGINE` là biến môi trường nên nó cố định cho cả một deployment Lambda
    và cả một phiên dev server. Chỉ đọc biến đó thì không thể chạy hai engine
    trên hai chứng từ của cùng một project — tức không so được engine nào đọc
    tiếng Việt tốt hơn trên CÙNG một tờ hoá đơn, đúng câu cần trả lời.

    Vẫn giữ biến môi trường làm nước lui: state machine đã deploy trước thay đổi
    này không truyền `ocr_engine`, và phải chạy y như cũ chứ không được nổ.
    """
    return (
        event.get("ocr_engine")
        or os.environ.get("OCR_ENGINE")
        or ocr_engines.DEFAULT_ENGINE
    )


def lambda_handler(event: dict, context) -> dict:
    project_id = event["project_id"]
    document_id = event["document_id"]
    s3_key = event["s3_key"]

    # Tra registry TRƯỚC khi đụng vào document: tên engine sai là lỗi cấu hình
    # deployment, mọi chứng từ sẽ hỏng như nhau. Nổ ngay và nổ rõ, thay vì đánh
    # dấu PROCESSING rồi mới chết.
    #
    # Nhãn ghi vào audit_log và đơn giá đều lấy TỪ CÙNG registry với hàm được
    # gọi. Tách ra là chỗ đã sai một lần: log nói một đằng, tiền trả một nẻo, và
    # chính chỗ đó làm ước tính chi phí lệch 20 lần.
    engine = _engine_name(event)
    label = ocr_engines.resolve(engine)["label"]

    begin_step(document_id, "ocr")
    content = read_object(s3_key)
    started = now_ms()

    try:
        # s3_key đi kèm vì Textract async đọc file TỪ S3 chứ không nhận bytes.
        # Trên Lambda file đã nằm sẵn đúng chỗ nên không phải copy lại.
        ocr_json = ocr_engines.run(engine, content, _mime_for(s3_key), s3_key)
    except RateLimitError as exc:
        log_ai_call(
            document_id,
            model=label,
            started_at_ms=started,
            status="rate_limited",
            error=str(exc),
            latency_ms=now_ms() - started,
        )
        raise
    except Exception as exc:
        log_ai_call(
            document_id,
            model=label,
            started_at_ms=started,
            status="error",
            error=str(exc),
            latency_ms=now_ms() - started,
        )
        raise

    page_count = len(ocr_json.get("pages") or [])
    log_ai_call(
        document_id,
        model=label,
        started_at_ms=started,
        status="ok",
        estimated_cost_usd=ocr_engines.estimate_cost(engine, page_count),
        latency_ms=now_ms() - started,
    )

    key = ocr_key(project_id, document_id)
    write_json(key, ocr_json)
    # Lưu engine vào chính record document: `audit_log` có nhãn nhưng chưa route
    # API nào đọc được, nên không lưu ở đây thì giao diện không có cách nào biết
    # chứng từ này đã chạy bằng engine gì.
    finish_step(
        document_id, "ocr", ocr_s3_key=key, page_count=page_count, ocr_engine=engine
    )

    return {**event, "ocr_s3_key": key, "page_count": page_count}
