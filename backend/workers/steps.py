from common.audit import log_pipeline_step
from common.dynamodb import DOCUMENTS_TABLE, get_item, update_document
from common.ids import now_iso

STATUS_AFTER_STEP = {
    "ocr": "OCR_DONE",
    "extract": "EXTRACTED",
    "validate": "VALIDATED",
}


def get_document(document_id: str) -> dict:
    document = get_item(DOCUMENTS_TABLE, {"document_id": document_id})
    if document is None:
        raise RuntimeError(f"Không tìm thấy document: {document_id}")
    return document


def begin_step(document_id: str, step: str, project_id: str | None = None) -> int:
    document = get_document(document_id)
    repeated = document.get("step") == step and document.get("step_status") in {"running", "failed"}
    attempt = (document.get("attempt") or 1) + 1 if repeated else 1

    update_document(
        document_id,
        status="PROCESSING",
        step=step,
        step_status="running",
        step_started_at=now_iso(),
        updated_at=now_iso(),
        attempt=attempt,
        error=None,
    )
    if project_id is None:
        project_id = document.get("project_id")
    log_pipeline_step(
        document_id, step, "started", {"attempt": attempt}, source="worker", project_id=project_id
    )
    return attempt


def finish_step(document_id: str, step: str, project_id: str | None = None, **updates) -> None:
    update_document(
        document_id,
        status=STATUS_AFTER_STEP[step],
        step=step,
        step_status="done",
        updated_at=now_iso(),
        **updates,
    )
    if project_id is None and "project_id" in updates:
        project_id = updates.get("project_id")
    log_pipeline_step(document_id, step, "done", source="worker", project_id=project_id)


def fail_step(document_id: str, step: str, error: str, project_id: str | None = None) -> None:
    update_document(
        document_id,
        status="FAILED",
        step=step,
        step_status="failed",
        updated_at=now_iso(),
        error=error,
    )
    log_pipeline_step(
        document_id, step, "failed", {"error": error}, source="worker", project_id=project_id
    )
