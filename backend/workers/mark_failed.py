from common import PROJECTS_TABLE, RUNS_TABLE, now_iso, release_processing_run, update_item

from .steps import fail_step


def _error_text(error: dict | None) -> str:
    if not error:
        return "Lỗi không xác định"
    cause = error.get("Cause") or ""
    return f"{error.get('Error', 'Error')}: {cause}"[:900]


def lambda_handler(event: dict, context) -> dict:
    document_id = event.get("document_id", "")
    step = event.get("step") or "ocr"
    message = _error_text(event.get("error"))

    if document_id:
        fail_step(document_id, step, message)

    return {
        "project_id": event.get("project_id"),
        "document_id": document_id,
        "status": "FAILED",
        "error": message,
    }


def mark_run_failed(event: dict, context) -> dict:
    project_id = event.get("project_id", "")
    run_id = event.get("run_id", "")
    message = _error_text(event.get("error"))

    if run_id:
        update_item(
            RUNS_TABLE,
            {"run_id": run_id},
            {"status": "FAILED", "finished_at": now_iso(), "error": message},
        )
    if project_id:
        update_item(
            PROJECTS_TABLE,
            {"project_id": project_id},
            {"last_run_id": run_id, "updated_at": now_iso()},
        )
        release_processing_run(project_id)

    return {"project_id": project_id, "run_id": run_id, "status": "FAILED", "error": message}
