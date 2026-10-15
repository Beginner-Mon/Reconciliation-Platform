from common.audit import log_review
from common.dynamodb import DOCUMENTS_TABLE, get_item, update_project
from common.errors import BadRequest, Conflict, NotFound
from common.ids import now_iso
from common.reconcile_client import invoke_reconcile

from .http import json_response
from .projects import must_get_project
from .views import reconciliation_view
from common.dynamodb import query_documents_by_project


def set_anchor(params: dict, body: dict, user: str) -> dict:
    project_id = params["project_id"]
    project = must_get_project(project_id)

    if project.get("processing_run_id"):
        raise Conflict("Project đang chạy xử lý, đợi xong rồi hãy đổi gốc")

    document_id = body.get("document_id")
    if not document_id:
        raise BadRequest("Thiếu document_id")

    doc = get_item(DOCUMENTS_TABLE, {"document_id": document_id})
    if doc is None or doc.get("project_id") != project_id:
        raise NotFound(f"Không tìm thấy document: {document_id}")

    # Chỉ cho phép đặt gốc cho doc đã VALIDATED
    if doc.get("status") not in ("VALIDATED", "EXTRACTED"):
        raise BadRequest("Chỉ đặt gốc cho chứng từ đã xử lý")

    anchor_ids = [document_id]
    update_project(project_id, anchor_document_ids=anchor_ids, anchor_updated_at=now_iso(), updated_at=now_iso())

    log_review(
        project_id,
        "ANCHOR_CHANGED",
        {"document_id": document_id, "file_name": doc.get("file_name")},
        actor=user,
        source="api",
        project_id=project_id,
    )

    # Đối chiếu lại đồng bộ (P2), P3 sẽ đổi sang Event
    try:
        record = invoke_reconcile(project_id)
        remaining = query_documents_by_project(project_id)
        reconciliation = reconciliation_view(record, remaining)
        if reconciliation is None:
            reconciliation = record
    except Exception as err:
        print(f"Đã đổi gốc nhưng đối chiếu lại lỗi: {err!r}", flush=True)
        reconciliation = None

    return json_response({"project_id": project_id, "anchor_document_ids": anchor_ids, "reconciliation": reconciliation})
