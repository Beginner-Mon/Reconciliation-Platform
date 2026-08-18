from common import (
    RUNS_TABLE,
    BadRequest,
    Conflict,
    claim_processing_run,
    head_object,
    new_run_id,
    now_iso,
    put_item,
    query_documents_by_project,
    release_processing_run,
    update_document,
    update_item,
)
from common.stepfunctions import start_execution
from workers.reconcile import run_reconciliation

from .http import json_response
from .projects import must_get_project
from .views import PROCESSED_STATUSES, document_view

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def _skip_reason(document: dict, force: bool, force_edited: bool) -> str | None:
    if document.get("status") in PROCESSED_STATUSES and not force:
        return "đã xử lý xong"
    if document.get("edited_fields") and not force_edited:
        return "đã được sửa tay, bỏ qua để không mất dữ liệu review"
    return None


def _verify_uploaded(document: dict) -> dict:
    head = head_object(document["s3_key"])
    if head is None:
        raise BadRequest(
            f"Chưa upload file lên S3: {document.get('file_name')} ({document['s3_key']})"
        )
    if head["size_bytes"] == 0:
        raise BadRequest(f"File rỗng: {document.get('file_name')}")
    if head["size_bytes"] > MAX_UPLOAD_BYTES:
        raise BadRequest(
            f"File {document.get('file_name')} nặng {head['size_bytes']} bytes, "
            f"vượt giới hạn {MAX_UPLOAD_BYTES} bytes của Document AI"
        )
    return head


def process_project(params: dict, body: dict) -> dict:
    project_id = params["project_id"]
    must_get_project(project_id)

    documents = query_documents_by_project(project_id)
    if not documents:
        raise BadRequest("Project chưa có document nào")
    documents.sort(key=lambda d: (d.get("uploaded_at") or "", d["document_id"]))

    requested = body.get("document_ids")
    if requested:
        by_id = {d["document_id"]: d for d in documents}
        missing = [i for i in requested if i not in by_id]
        if missing:
            raise BadRequest(f"document_id không thuộc project: {', '.join(missing)}")
        candidates = [by_id[i] for i in requested]
    else:
        candidates = documents

    force = bool(body.get("force"))
    force_edited = bool(body.get("force_edited"))

    targets = []
    skipped = []
    for document in candidates:
        reason = _skip_reason(document, force, force_edited)
        if reason:
            skipped.append(
                {
                    "document_id": document["document_id"],
                    "file_name": document.get("file_name"),
                    "reason": reason,
                }
            )
        else:
            targets.append(document)

    verified = [(document, _verify_uploaded(document)) for document in targets]

    if not targets:
        record = run_reconciliation(project_id)
        return json_response(
            {
                "project_id": project_id,
                "run_id": None,
                "processing": [],
                "skipped": skipped,
                "message": "Tất cả document đã được xử lý, chỉ chạy lại đối chiếu",
                "reconciliation": {
                    "reconciliation_id": record["reconciliation_id"],
                    "discrepancy_count": record["discrepancy_count"],
                    "severity_summary": record["severity_summary"],
                },
            }
        )

    run_id = new_run_id()
    if not claim_processing_run(project_id, run_id):
        raise Conflict("Project đang chạy xử lý, đợi run hiện tại kết thúc")

    document_ids = [d["document_id"] for d in targets]
    put_item(
        RUNS_TABLE,
        {
            "run_id": run_id,
            "project_id": project_id,
            "document_ids": document_ids,
            "skipped_document_ids": [s["document_id"] for s in skipped],
            "status": "PROCESSING",
            "started_at": now_iso(),
        },
    )

    for document, head in verified:
        update_document(
            document["document_id"],
            status="PENDING",
            step=None,
            step_status=None,
            attempt=0,
            error=None,
            size_bytes=head["size_bytes"],
            updated_at=now_iso(),
        )

    payload = {
        "project_id": project_id,
        "run_id": run_id,
        "documents": [
            {"document_id": d["document_id"], "s3_key": d["s3_key"]} for d in targets
        ],
    }

    try:
        execution_arn = start_execution(run_id, payload)
    except Exception as exc:
        update_item(
            RUNS_TABLE,
            {"run_id": run_id},
            {"status": "FAILED", "finished_at": now_iso(), "error": str(exc)},
        )
        release_processing_run(project_id)
        raise

    update_item(RUNS_TABLE, {"run_id": run_id}, {"execution_arn": execution_arn})

    return json_response(
        {
            "project_id": project_id,
            "run_id": run_id,
            "execution_arn": execution_arn,
            "processing": [document_view(d) for d in targets],
            "skipped": skipped,
        },
        202,
    )
