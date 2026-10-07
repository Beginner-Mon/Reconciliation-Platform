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
from core.locate import clean_sources
from core.position import still_valid

from .http import json_response
from .reconcile import must_get_reconciliation
from .views import da_cu, dismissed_key, document_view, unconfirmed_flag_keys

EDIT_BLOCKED_FIELDS = {"document_type"}


def _must_get_document(project_id: str, document_id: str) -> dict:
    document = get_item(DOCUMENTS_TABLE, {"document_id": document_id})
    if document is None:
        raise NotFound(f"Không tìm thấy document: {document_id}")
    if document.get("project_id") != project_id:
        raise NotFound(f"Document {document_id} không thuộc project {project_id}")
    return document


def _link_document(document: dict, sources: dict) -> dict:
    document_id = document["document_id"]
    update_document(
        document_id, sources=clean_sources(sources, document["extraction"]) or None
    )
    saved = get_item(DOCUMENTS_TABLE, {"document_id": document_id})
    return json_response(
        {"document": document_view(saved, with_url=True), "validation": saved.get("validation")}
    )


def _dismiss_flag(document: dict, dismiss: dict, user: str) -> dict:
    code = dismiss.get("code") if isinstance(dismiss, dict) else None
    field = dismiss.get("field") if isinstance(dismiss, dict) else None
    flags = (document.get("validation") or {}).get("flags") or []
    current = next(
        (f for f in flags if isinstance(f, dict) and f.get("code") == code and f.get("field") == field),
        None,
    )
    if not isinstance(code, str) or not isinstance(field, str) or current is None:
        raise BadRequest("Không tìm thấy cảnh báo cần tắt")
    kept = [
        e for e in (document.get("dismissed_flags") or [])
        if not (isinstance(e, dict) and e.get("code") == code and e.get("field") == field)
    ]
    kept.append({
        "code": code,
        "field": field,
        "values": current.get("values") or {},
        "by": user,
        "at": now_iso(),
    })
    update_document(document["document_id"], dismissed_flags=kept)
    log_review(
        document["document_id"],
        "REVIEW_DISMISS",
        {"code": code, "field": field},
        actor=user,
        source="api",
        project_id=document.get("project_id"),
    )
    saved = get_item(DOCUMENTS_TABLE, {"document_id": document["document_id"]})
    return json_response(
        {"document": document_view(saved, with_url=True), "validation": saved.get("validation")}
    )


def _reopen_flag(document: dict, undismiss: dict, user: str) -> dict:
    code = undismiss.get("code") if isinstance(undismiss, dict) else None
    field = undismiss.get("field") if isinstance(undismiss, dict) else None
    if not isinstance(code, str) or not isinstance(field, str):
        raise BadRequest("Thiếu code hoặc field để mở lại")
    before = document.get("dismissed_flags") or []
    kept = [
        e for e in before
        if not (isinstance(e, dict) and e.get("code") == code and e.get("field") == field)
    ]
    if len(kept) == len(before):
        raise BadRequest("Cảnh báo này không ở trạng thái đã tắt")
    update_document(document["document_id"], dismissed_flags=kept)
    log_review(
        document["document_id"],
        "REVIEW_REOPEN",
        {"code": code, "field": field},
        actor=user,
        source="api",
        project_id=document.get("project_id"),
    )
    saved = get_item(DOCUMENTS_TABLE, {"document_id": document["document_id"]})
    return json_response(
        {"document": document_view(saved, with_url=True), "validation": saved.get("validation")}
    )


def edit_document(params: dict, body: dict, user: str) -> dict:
    project_id = params["project_id"]
    document_id = params["document_id"]
    document = _must_get_document(project_id, document_id)

    fields = body.get("fields") or {}
    sources = body.get("sources")
    dismiss = body.get("dismiss")
    undismiss = body.get("undismiss")
    if not fields and isinstance(dismiss, dict):
        return _dismiss_flag(document, dismiss, user)
    if not fields and isinstance(undismiss, dict):
        return _reopen_flag(document, undismiss, user)
    if not fields and isinstance(sources, dict) and document.get("extraction"):
        return _link_document(document, sources)
    if not fields:
        raise BadRequest("Thiếu fields")
    if not document.get("extraction"):
        raise BadRequest("Document chưa có dữ liệu trích xuất để sửa")

    blocked = EDIT_BLOCKED_FIELDS & set(fields)
    if blocked:
        raise BadRequest(f"Không được sửa trường: {', '.join(sorted(blocked))}")

    extraction = {**document["extraction"], **fields}
    edited_fields = sorted(set(document.get("edited_fields") or []) | set(fields))
    con_lai = [
        muc for muc in (document.get("format_issues") or [])
        if isinstance(muc, dict) and muc.get("field") not in edited_fields
    ]
    vi_tri = still_valid(document.get("position_issues") or [], extraction)
    result = validate_document(extraction, con_lai, vi_tri)
    validation = {
        "valid": result["valid"],
        "schema_errors": result["schema_errors"],
        "rule_errors": result["rule_errors"],
        "flags": result["flags"],
        "warnings": result["warnings"],
        "comparison_incomplete": result["comparison_incomplete"],
    }

    errors = result["schema_errors"] + result["rule_errors"]

    con_hien = {
        dismissed_key(f.get("code"), f.get("field"))
        for f in result["flags"]
        if isinstance(f, dict)
    }
    con_tat = [
        e for e in (document.get("dismissed_flags") or [])
        if isinstance(e, dict) and dismissed_key(e.get("code"), e.get("field")) in con_hien
    ]

    updates = {
        "extraction": extraction,
        "validation": validation,
        "position_issues": vi_tri,
        "sources": clean_sources(sources, extraction) or None,
        "dismissed_flags": con_tat,
        "edited_fields": edited_fields,
        "edited_at": now_iso(),
        "edited_by": user,
        "updated_at": now_iso(),
        "status": "VALIDATED" if result["valid"] else "FAILED",
        "step": "validate",
        "step_status": "done" if result["valid"] else "failed",
        "error": None if result["valid"] else "; ".join(errors),
    }
    if extraction.get("po_number"):
        updates["po_number"] = extraction["po_number"]
    if extraction.get("order_reference"):
        updates["order_reference"] = extraction["order_reference"]
        updates["po_number"] = extraction["order_reference"]
    if extraction.get("doc_number"):
        updates["doc_number"] = extraction["doc_number"]

    update_document(document_id, **updates)
    log_review(
        document_id,
        "REVIEW_EDIT",
        {
            "fields": list(fields),
            "valid": result["valid"],
        },
        actor=user,
        source="api",
        project_id=project_id,
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
# thêm gì cho audit: `log_review` đã ghi `decision` vào dòng audit.
#
# Tách lại chỉ hợp lý khi duyệt sinh ra hệ quả mà từ chối không có (đẩy sang
# ERP, gửi thông báo) — lúc đó side effect mới thật sự khác nhau.
DECISIONS = ("APPROVED", "REJECTED")


def review_reconciliation(params: dict, body: dict, user: str) -> dict:
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
    if not record.get("document_ids"):
        raise Conflict("Đợt đối chiếu này không so chứng từ nào — không có gì để duyệt.")

    from common.dynamodb import PROJECTS_TABLE, get_item as _get_item
    project = _get_item(PROJECTS_TABLE, {"project_id": record["project_id"]})
    documents = query_documents_by_project(record["project_id"])
    if da_cu(record, documents, project):
        raise Conflict(
            "Có chứng từ được sửa sau lần đối chiếu này. Bấm Đối chiếu lại rồi "
            "hãy duyệt."
        )
    if decision == "APPROVED":
        trong_dot = set(record.get("document_ids") or [])
        cho = [
            d.get("file_name") or d.get("document_id") for d in documents
            if d.get("document_id") in trong_dot and unconfirmed_flag_keys(d)
        ]
        if cho:
            raise Conflict(
                "Còn chứng từ có cảnh báo vị trí hoặc định dạng chưa xử lý: " + ", ".join(cho)
                + ". Mở từng chứng từ, sửa rồi Lưu hoặc tắt từng cảnh báo đó rồi hãy duyệt."
            )

    review = {
        "decision": decision,
        "reviewer": user,
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
        {"reconciliation_id": reconciliation_id, "decision": decision, "comment": body.get("comment")},
        actor=user,
        source="api",
        project_id=record["project_id"],
    )
    return json_response({**record, "status": decision, "review": review})
