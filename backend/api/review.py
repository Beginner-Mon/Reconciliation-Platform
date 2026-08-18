from common import (
    DOCUMENTS_TABLE,
    RECONCILIATIONS_TABLE,
    BadRequest,
    Conflict,
    NotFound,
    get_item,
    log_review,
    now_iso,
    update_document,
    update_item,
)
from core import validate_document
from workers.reconcile import run_reconciliation

from .http import json_response
from .reconcile import must_get_reconciliation
from .views import document_view

EDIT_BLOCKED_FIELDS = {"document_type"}


def _must_get_document(project_id: str, document_id: str) -> dict:
    document = get_item(DOCUMENTS_TABLE, {"document_id": document_id})
    if document is None:
        raise NotFound(f"Không tìm thấy document: {document_id}")
    if document.get("project_id") != project_id:
        raise NotFound(f"Document {document_id} không thuộc project {project_id}")
    return document


def edit_document(params: dict, body: dict) -> dict:
    project_id = params["project_id"]
    document_id = params["document_id"]
    document = _must_get_document(project_id, document_id)

    fields = body.get("fields") or {}
    if not fields:
        raise BadRequest("Thiếu fields")
    if not document.get("extraction"):
        raise BadRequest("Document chưa có dữ liệu trích xuất để sửa")

    blocked = EDIT_BLOCKED_FIELDS & set(fields)
    if blocked:
        raise BadRequest(f"Không được sửa trường: {', '.join(sorted(blocked))}")

    extraction = {**document["extraction"], **fields}
    result = validate_document(extraction)
    validation = {
        "valid": result["valid"],
        "schema_errors": result["schema_errors"],
        "rule_errors": result["rule_errors"],
    }

    edited_fields = sorted(set(document.get("edited_fields") or []) | set(fields))
    errors = result["schema_errors"] + result["rule_errors"]

    updates = {
        "extraction": extraction,
        "validation": validation,
        "edited_fields": edited_fields,
        "edited_at": now_iso(),
        "edited_by": body.get("reviewer") or "poc-user",
        "updated_at": now_iso(),
        "status": "VALIDATED" if result["valid"] else "FAILED",
        "step": "validate",
        "step_status": "done" if result["valid"] else "failed",
        "error": None if result["valid"] else "; ".join(errors),
    }
    if extraction.get("po_number"):
        updates["po_number"] = extraction["po_number"]

    update_document(document_id, **updates)
    log_review(
        document_id,
        "REVIEW_EDIT",
        {
            "reviewer": updates["edited_by"],
            "fields": list(fields),
            "valid": result["valid"],
        },
    )

    record = run_reconciliation(project_id)
    document = get_item(DOCUMENTS_TABLE, {"document_id": document_id})

    return json_response(
        {
            "document": document_view(document, with_url=True),
            "validation": validation,
            "reconciliation": {
                "reconciliation_id": record["reconciliation_id"],
                "discrepancy_count": record["discrepancy_count"],
                "severity_summary": record["severity_summary"],
            },
        }
    )


def _decide(reconciliation_id: str, decision: str, body: dict) -> dict:
    record = must_get_reconciliation(reconciliation_id)
    if record.get("status") != "PENDING_REVIEW":
        raise Conflict(f"Reconciliation đang ở trạng thái {record.get('status')}")

    reviewer = body.get("reviewer") or "poc-user"
    review = {
        "decision": decision,
        "reviewer": reviewer,
        "reviewed_at": now_iso(),
        "comment": body.get("comment"),
    }
    status = "APPROVED" if decision == "APPROVED" else "REJECTED"
    update_item(
        RECONCILIATIONS_TABLE,
        {"reconciliation_id": reconciliation_id},
        {"status": status, "review": review},
    )
    log_review(
        record["project_id"],
        "REVIEW_DECISION",
        {"reconciliation_id": reconciliation_id, **review},
    )
    return json_response({**record, "status": status, "review": review})


def approve_reconciliation(params: dict, body: dict) -> dict:
    return _decide(params["reconciliation_id"], "APPROVED", body)


def reject_reconciliation(params: dict, body: dict) -> dict:
    return _decide(params["reconciliation_id"], "REJECTED", body)
