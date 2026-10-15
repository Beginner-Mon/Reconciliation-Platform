from common.dynamodb import (
    PROJECTS_TABLE,
    RECONCILIATIONS_TABLE,
    RUNS_TABLE,
    get_item,
    put_item,
    query_documents_by_project,
    release_processing_run,
    update_document,
    update_item,
)
from common.ids import new_reconciliation_id, now_iso
from common.s3 import reconciliation_key, write_json
from core import run_crosscheck

from .steps import run_cancel_requested

def run_reconciliation(project_id: str) -> dict:

    documents = query_documents_by_project(project_id)
    project = get_item(PROJECTS_TABLE, {"project_id": project_id}) or {}
    anchor_ids = project.get("anchor_document_ids")
    candidates = [d for d in documents if d.get("extraction")]
    payload = [
        {"document_id": d["document_id"], "data": d["extraction"]} for d in candidates
    ]

    result = run_crosscheck(payload, anchor_document_ids=anchor_ids if isinstance(anchor_ids, list) else None)
    reconciliation_id = new_reconciliation_id()
    s3_key = reconciliation_key(project_id, reconciliation_id)

    write_json(
        s3_key,
        {
            "reconciliation_id": reconciliation_id,
            "project_id": project_id,
            "created_at": now_iso(),
            **result,
        },
    )

    record = {
        "reconciliation_id": reconciliation_id,
        "project_id": project_id,
        "created_at": now_iso(),
        "document_ids": result["checked_document_ids"],
        "s3_key": s3_key,
        "discrepancy_count": result["discrepancy_count"],
        "severity_summary": result["severity_summary"],
        "groups": result["groups"],
        "skipped_documents": result["skipped_documents"],
        "status": "PENDING_REVIEW",
        "review": {"decision": None, "reviewer": None, "reviewed_at": None, "comment": None},
    }
    put_item(RECONCILIATIONS_TABLE, record)
    update_item(
        PROJECTS_TABLE,
        {"project_id": project_id},
        {"latest_reconciliation_id": reconciliation_id, "updated_at": now_iso()},
    )
    return record


def _finish_cancelled_run(project_id: str, run_id: str) -> dict:
    run = get_item(RUNS_TABLE, {"run_id": run_id}) or {}
    run_document_ids = set(run.get("document_ids") or [])
    finished, not_started, interrupted = [], [], []

    for document in query_documents_by_project(project_id):
        document_id = document["document_id"]
        if document_id not in run_document_ids:
            continue
        status = document.get("status")
        if status in ("VALIDATED", "FAILED"):
            finished.append(document_id)
        elif status == "PENDING":
            not_started.append(document_id)
            before = document.get("status_before_run")
            if before:
                update_document(document_id, status=before, updated_at=now_iso())
        else:
            interrupted.append(document_id)
            update_document(
                document_id,
                status="PENDING",
                step=None,
                step_status=None,
                updated_at=now_iso(),
            )

    update_item(
        RUNS_TABLE,
        {"run_id": run_id},
        {
            "status": "CANCELLED",
            "finished_at": now_iso(),
            "finished_document_ids": finished,
            "not_started_document_ids": not_started,
            "interrupted_document_ids": interrupted,
        },
    )
    update_item(
        PROJECTS_TABLE,
        {"project_id": project_id},
        {"last_run_id": run_id, "updated_at": now_iso()},
    )
    release_processing_run(project_id, run_id)
    return {"project_id": project_id, "run_id": run_id, "status": "CANCELLED"}


def lambda_handler(event: dict, context) -> dict:
    project_id = event["project_id"]
    run_id = event.get("run_id")

    if run_cancel_requested(run_id):
        return _finish_cancelled_run(project_id, run_id)

    record = run_reconciliation(project_id)

    if not run_id:
        return record

    update_item(
        RUNS_TABLE,
        {"run_id": run_id},
        {
            "status": "SUCCEEDED",
            "finished_at": now_iso(),
            "reconciliation_id": record["reconciliation_id"],
        },
    )
    update_item(
        PROJECTS_TABLE, {"project_id": project_id}, {"last_run_id": run_id}
    )
    release_processing_run(project_id)

    return {
        "project_id": project_id,
        "run_id": run_id,
        "reconciliation_id": record["reconciliation_id"],
        "discrepancy_count": record["discrepancy_count"],
    }
