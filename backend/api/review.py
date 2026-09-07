from common.audit import log_review
from common.dynamodb import (
    DOCUMENTS_TABLE,
    RECONCILIATIONS_TABLE,
    get_item,
    query_documents_by_project,
    update_document,
    update_item,
)
from common.errors import BadRequest, Conflict, NotFound
from common.ids import now_iso
from core import validate_document

from .http import json_response
from .reconcile import must_get_reconciliation
from .views import da_cu, document_view

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

    # KHÔNG đối chiếu ở đây. Sửa tay là thao tác REVIEW, không phải thao tác đối
    # chiếu — trước đây PATCH tự chạy `run_reconciliation`, khiến cùng một logic
    # chạy ở ba Lambda và `api/` buộc phải kéo `workers/` vào gói.
    #
    # Kết quả đối chiếu cũ thành `is_stale` (xem `views.reconciliation_view`) và
    # `review_reconciliation` chặn duyệt cho tới khi chạy lại. Đổi một tính chất
    # "đúng nhờ may" thành ràng buộc được cưỡng chế.
    document = get_item(DOCUMENTS_TABLE, {"document_id": document_id})

    return json_response(
        {
            "document": document_view(document, with_url=True),
            "validation": validation,
        }
    )


# Duyệt và từ chối ghi CÙNG một bảng, CÙNG một shape, khác đúng một enum —
# không có side effect nào riêng nên một route là đủ. Tách làm hai cũng không
# thêm gì cho audit: `log_review` đã ghi `decision` vào `audit_log`.
#
# Tách lại chỉ hợp lý khi duyệt sinh ra hệ quả mà từ chối không có (đẩy sang
# ERP, gửi thông báo) — lúc đó side effect mới thật sự khác nhau.
DECISIONS = ("APPROVED", "REJECTED")


def review_reconciliation(params: dict, body: dict) -> dict:
    reconciliation_id = params["reconciliation_id"]

    # Gộp route thì `decision` thành dữ liệu đầu vào, phải kiểm. Coi mọi thứ
    # khác APPROVED là từ chối thì một lỗi gõ phím sẽ âm thầm từ chối cả đợt
    # đối chiếu — và bản ghi audit trông y như người ta cố ý làm vậy.
    decision = body.get("decision")
    if decision not in DECISIONS:
        raise BadRequest(
            f"decision phải là một trong: {', '.join(DECISIONS)} (nhận {decision!r})"
        )

    record = must_get_reconciliation(reconciliation_id)
    if record.get("status") != "PENDING_REVIEW":
        raise Conflict(f"Reconciliation đang ở trạng thái {record.get('status')}")

    # Duyệt một kết luận tính TRƯỚC lần sửa cuối là duyệt dữ liệu đã sai. Chặn ở
    # SERVER chứ không chỉ làm mờ nút trên giao diện — đây là quyết định nghiệp
    # vụ được ghi vào audit_log, không được phép sai vì một request gọi tay.
    if da_cu(record, query_documents_by_project(record["project_id"])):
        raise Conflict(
            "Có chứng từ được sửa sau lần đối chiếu này. Bấm Đối chiếu lại rồi "
            "hãy duyệt."
        )

    review = {
        "decision": decision,
        "reviewer": body.get("reviewer") or "poc-user",
        "reviewed_at": now_iso(),
        "comment": body.get("comment"),
    }
    update_item(
        RECONCILIATIONS_TABLE,
        {"reconciliation_id": reconciliation_id},
        {"status": decision, "review": review},
    )
    log_review(
        record["project_id"],
        "REVIEW_DECISION",
        {"reconciliation_id": reconciliation_id, **review},
    )
    return json_response({**record, "status": decision, "review": review})
