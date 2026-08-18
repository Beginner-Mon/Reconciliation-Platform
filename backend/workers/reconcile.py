from common import (
    PROJECTS_TABLE,
    RECONCILIATIONS_TABLE,
    RUNS_TABLE,
    log_pipeline_step,
    new_reconciliation_id,
    now_iso,
    put_item,
    query_documents_by_project,
    reconciliation_key,
    release_processing_run,
    update_item,
    write_json,
)
from core import run_crosscheck

def run_reconciliation(project_id: str) -> dict:
    documents = query_documents_by_project(project_id)
    candidates = [d for d in documents if d.get("extraction")]
    payload = [
        {"document_id": d["document_id"], "data": d["extraction"]} for d in candidates
    ]

    result = run_crosscheck(payload)
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
    log_pipeline_step(
        project_id,
        "reconcile",
        "done",
        {
            "reconciliation_id": reconciliation_id,
            "discrepancy_count": result["discrepancy_count"],
        },
    )
    return record


def lambda_handler(event: dict, context) -> dict:
    project_id = event["project_id"]
    run_id = event.get("run_id")

    record = run_reconciliation(project_id)

    if run_id:
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
