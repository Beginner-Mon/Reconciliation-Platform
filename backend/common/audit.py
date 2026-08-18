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
