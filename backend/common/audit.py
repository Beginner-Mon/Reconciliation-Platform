import json
import time

from .ids import new_request_id, now_iso


def _log(entity_id, action, detail, *, actor=None, source="api", project_id=None, extra=None):
    record = {
        "audit": 1,
        "action": action,
        "actor": actor,
        "source": source,
        "project_id": project_id,
        "entity_id": entity_id,
        "timestamp": now_iso(),
        "detail": detail or {},
    }
    if extra:
        record.update(extra)
    try:
        print(json.dumps(record, ensure_ascii=False, default=str), flush=True)
    except UnicodeEncodeError:
        print(json.dumps(record, ensure_ascii=True, default=str), flush=True)


def log_ai_call(
    document_id,
    model,
    started_at_ms,
    status,
    usage=None,
    estimated_cost_usd=None,
    error=None,
    latency_ms=None,
    *,
    actor=None,
    source="worker",
    project_id=None,
):
    cost = round(float(estimated_cost_usd or 0), 6)
    latency = latency_ms or 0
    rate_limited = 1 if status == "rate_limited" else 0
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
        actor=actor,
        source=source,
        project_id=project_id,
        extra={
            "AiCostUsd": cost,
            "AiLatencyMs": latency,
            "AiRateLimited": rate_limited,
            "Service": "recon",
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": "Recon/AI",
                        "Dimensions": [["Service"]],
                        "Metrics": [
                            {"Name": "AiCostUsd"},
                            {"Name": "AiLatencyMs", "Unit": "Milliseconds"},
                            {"Name": "AiRateLimited", "Unit": "Count"},
                        ],
                    }
                ],
            },
        },
    )


def log_pipeline_step(entity_id, step, status, detail=None, *, actor=None, source="worker", project_id=None):
    _log(
        entity_id,
        "PIPELINE_STEP",
        {"step": step, "status": status, **({"detail": detail} if detail else {})},
        actor=actor,
        source=source,
        project_id=project_id,
    )


def log_review(entity_id, action, detail, *, actor=None, source="api", project_id=None):
    _log(entity_id, action, detail, actor=actor, source=source, project_id=project_id)


def log_process_decision(project_id, detail, *, actor=None, source="api"):
    """Ghi lại MỌI quyết định của /process, nhất là quyết định BỎ QUA.

    Tính idempotent tiết kiệm tiền bằng cách âm thầm không làm gì — nên nếu
    không ghi lại thì vài tuần sau không ai trả lời được "vì sao chứng từ này
    dữ liệu vẫn cũ". Danh sách skip kèm lý do trước đây chỉ nằm trong HTTP
    response rồi mất theo tab trình duyệt.

    Cờ `force` cũng vào đây: nó chạy lại OCR + Gemini, tốn tiền thật.
    """
    _log(project_id, "PROCESS_RUN", detail, actor=actor, source=source, project_id=project_id)


def log_edit_overwritten(document_id, detail, *, actor=None, source="api", project_id=None):
    """`force_edited=true` sắp cho AI ghi đè lên dữ liệu người đã sửa tay.

    Ghi theo TỪNG document (không gộp vào PROCESS_RUN) để tra được lịch sử của
    đúng chứng từ đó: trước đây tra theo PK entity_id của bảng audit_log, giờ
    lọc theo entity_id trong Logs Insights.

    Đây là thao tác phá huỷ duy nhất trong hệ thống — công review biến mất và
    không có cách nào lấy lại.
    """
    du_an = project_id
    if du_an is None and isinstance(detail, dict):
        du_an = detail.get("project_id")
    _log(
        document_id,
        "EDIT_OVERWRITTEN",
        detail,
        actor=actor,
        source=source,
        project_id=du_an,
    )


def log_project_created(project_id, detail, *, actor=None, source="api"):
    _log(project_id, "PROJECT_CREATED", detail, actor=actor, source=source, project_id=project_id)


def log_documents_uploaded(project_id, detail, *, actor=None, source="api"):
    _log(project_id, "DOCUMENTS_UPLOADED", detail, actor=actor, source=source, project_id=project_id)


def log_reconcile_run(project_id, detail, *, actor=None, source="api"):
    _log(project_id, "RECONCILE_RUN", detail, actor=actor, source=source, project_id=project_id)


def log_document_deleted(project_id, detail, *, actor=None, source="api"):
    _log(project_id, "DOCUMENT_DELETED", detail, actor=actor, source=source, project_id=project_id)
