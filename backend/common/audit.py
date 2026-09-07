from .dynamodb import AUDIT_LOG_TABLE, put_item
from .ids import new_request_id, now_iso


def _log(entity_id: str, action: str, detail: dict) -> None:
    put_item(
        AUDIT_LOG_TABLE,
        {
            "entity_id": entity_id,
            "timestamp": now_iso(),
            "action": action,
            "detail": detail,
        },
    )


def log_ai_call(
    document_id: str,
    model: str,
    started_at_ms: int,
    status: str,
    usage: dict | None = None,
    estimated_cost_usd: float | None = None,
    error: str | None = None,
    latency_ms: int | None = None,
) -> None:
    _log(
        document_id,
        "AI_CALL",
        {
            "request_id": new_request_id(),
            "model": model,
            "started_at_ms": started_at_ms,
            "latency_ms": latency_ms,
            "status": status,
            "error": error,
            "token_usage": usage,
            "estimated_cost_usd": estimated_cost_usd,
        },
    )


def log_pipeline_step(entity_id: str, step: str, status: str, detail: dict | None = None) -> None:
    _log(
        entity_id,
        "PIPELINE_STEP",
        {"step": step, "status": status, **({"detail": detail} if detail else {})},
    )


def log_review(entity_id: str, action: str, detail: dict) -> None:
    _log(entity_id, action, detail)


def log_process_decision(project_id: str, detail: dict) -> None:
    """Ghi lại MỌI quyết định của /process, nhất là quyết định BỎ QUA.

    Tính idempotent tiết kiệm tiền bằng cách âm thầm không làm gì — nên nếu
    không ghi lại thì vài tuần sau không ai trả lời được "vì sao chứng từ này
    dữ liệu vẫn cũ". Danh sách skip kèm lý do trước đây chỉ nằm trong HTTP
    response rồi mất theo tab trình duyệt.

    Cờ `force` cũng vào đây: nó chạy lại OCR + Gemini, tốn tiền thật.
    """
    _log(project_id, "PROCESS_RUN", detail)


def log_edit_overwritten(document_id: str, detail: dict) -> None:
    """`force_edited=true` sắp cho AI ghi đè lên dữ liệu người đã sửa tay.

    Ghi theo TỪNG document (không gộp vào PROCESS_RUN) để tra được lịch sử của
    đúng chứng từ đó: bảng audit_log có PK là entity_id.

    Đây là thao tác phá huỷ duy nhất trong hệ thống — công review biến mất và
    không có cách nào lấy lại.
    """
    _log(document_id, "EDIT_OVERWRITTEN", detail)
