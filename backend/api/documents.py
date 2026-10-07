from pathlib import Path

from common.dynamodb import (
    DOCUMENTS_TABLE,
    delete_item,
    get_item,
    put_item,
    query_documents_by_project,
    update_project,
)
from common.audit import log_document_deleted, log_documents_uploaded
from common.errors import BadRequest, Conflict, NotFound
from common.ids import new_document_id, now_iso
from common.reconcile_client import invoke_reconcile
from common.s3 import MAX_UPLOAD_BYTES, create_upload_post, delete_object, read_json, upload_key
from core.locate import clean_sources, locate

from .http import json_response
from .projects import must_get_project
from .views import document_view, reconciliation_view

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff"}
CONTENT_TYPE_BY_EXT = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tiff": "image/tiff",
}
MAX_FILES_PER_REQUEST = 20


def create_documents(params: dict, body: dict, user: str) -> dict:
    project_id = params["project_id"]
    project = must_get_project(project_id)
    if project.get("deleting_at"):
        raise Conflict("Project đang bị xoá dở — bấm xoá lại để hoàn tất")

    files = body.get("files") or []
    if not files:
        raise BadRequest("Thiếu danh sách files")
    if len(files) > MAX_FILES_PER_REQUEST:
        raise BadRequest(f"Tối đa {MAX_FILES_PER_REQUEST} file mỗi lần")

    prepared = []
    for entry in files:
        file_name = (entry.get("file_name") or "").strip()
        if not file_name:
            raise BadRequest("Thiếu file_name")
        ext = Path(file_name).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise BadRequest(
                f"Loại file không hỗ trợ: {ext or file_name} "
                f"(hỗ trợ: {', '.join(sorted(ALLOWED_EXTENSIONS))})"
            )
        prepared.append(
            (
                file_name,
                ext,
                entry.get("content_type") or CONTENT_TYPE_BY_EXT[ext],
            )
        )

    created = []
    for file_name, ext, content_type in prepared:
        document_id = new_document_id()
        s3_key = upload_key(project_id, document_id, ext)
        put_item(
            DOCUMENTS_TABLE,
            {
                "document_id": document_id,
                "project_id": project_id,
                "s3_key": s3_key,
                "file_name": file_name,
                "file_type": ext.lstrip("."),
                "content_type": content_type,
                "uploaded_at": now_iso(),
                "updated_at": now_iso(),
                "status": "PENDING",
                "edited_fields": [],
            },
        )
        upload = create_upload_post(s3_key, content_type)
        created.append(
            {
                "document_id": document_id,
                "file_name": file_name,
                "s3_key": s3_key,
                "content_type": content_type,
                # Presigned POST: gửi FormData gồm `fields` rồi tới trường `file`.
                # Thứ tự quan trọng — S3 bỏ qua mọi thứ đứng sau `file`.
                "upload": {"url": upload["url"], "fields": upload["fields"]},
                "max_bytes": MAX_UPLOAD_BYTES,
            }
        )

    update_project(
        project_id,
        document_count=(project.get("document_count") or 0) + len(created),
        updated_at=now_iso(),
    )
    log_documents_uploaded(
        project_id,
        {
            "document_ids": [c["document_id"] for c in created],
            "file_names": [c["file_name"] for c in created],
        },
        actor=user,
        source="api",
    )
    return json_response({"project_id": project_id, "documents": created}, 201)


def _layout(document: dict, pages) -> dict | None:
    extraction = document.get("extraction")
    if not isinstance(extraction, dict):
        return None
    try:
        layout = locate(extraction, pages)
    except Exception as exc:
        print(
            f"LOCATE_FAILED {document.get('document_id')}: {type(exc).__name__}: {exc}",
            flush=True,
        )
        tables = extraction.get("tables")
        layout = {
            "fields": {},
            "other": {},
            "tables": [None] * (len(tables) if isinstance(tables, list) else 0),
            "number_style": None,
        }
    stored = clean_sources(document.get("sources"), extraction)
    if stored:
        layout["fields"] = stored["fields"]
        layout["other"] = stored["other"]
        for index, table in enumerate(stored["tables"]):
            if table is None or index >= len(layout["tables"]):
                continue
            computed = layout["tables"][index] or {}
            layout["tables"][index] = {
                **table,
                "at": computed.get("at") or [[[] for _ in row] for row in table["rows"]],
            }
    return layout


def get_document_ocr(params: dict, body: dict, user: str) -> dict:
    """Text OCR thô của 1 document.

    Người review cần đối chiếu "OCR đọc ra gì" với "AI hiểu thành gì" để biết
    lỗi nằm ở khâu đọc hay khâu trích xuất. Nội dung nằm ở S3 chứ không ở
    DynamoDB vì nó lớn.
    """
    project_id = params["project_id"]
    document_id = params["document_id"]

    document = get_item(DOCUMENTS_TABLE, {"document_id": document_id})
    if document is None or document.get("project_id") != project_id:
        raise NotFound(f"Không tìm thấy document: {document_id}")

    ocr_key = document.get("ocr_s3_key")
    if not ocr_key:
        raise NotFound(
            f"{document.get('file_name')} chưa chạy OCR "
            f"(trạng thái: {document.get('status')})"
        )

    ocr = read_json(ocr_key)
    pages = ocr.get("pages", [])
    return json_response(
        {
            "document_id": document_id,
            "file_name": document.get("file_name"),
            "text": ocr.get("text", ""),
            "pages": pages,
            "layout": _layout(document, pages),
        }
    )


def list_documents(params: dict, body: dict, user: str) -> dict:
    project_id = params["project_id"]
    must_get_project(project_id)
    documents = query_documents_by_project(project_id)
    documents.sort(key=lambda d: d.get("uploaded_at") or "")
    return json_response({"items": [document_view(d, with_url=True) for d in documents]})


def delete_document(params: dict, body: dict, user: str) -> dict:
    project_id = params["project_id"]
    document_id = params["document_id"]
    project = must_get_project(project_id)

    document = get_item(DOCUMENTS_TABLE, {"document_id": document_id})
    if document is None or document.get("project_id") != project_id:
        raise NotFound(f"Không tìm thấy document: {document_id}")

    if project.get("processing_run_id"):
        raise Conflict("Project đang chạy xử lý, đợi run hiện tại kết thúc rồi hãy xoá")

    file_name = document.get("file_name") or document_id
    doc_status = document.get("status") or "PENDING"
    edited_fields = document.get("edited_fields") or []
    s3_key = document.get("s3_key")
    ocr_s3_key = document.get("ocr_s3_key")
    extraction_s3_key = document.get("extraction_s3_key")

    for key in (s3_key, ocr_s3_key, extraction_s3_key, document.get("document_payload_s3_key")):
        if key:
            delete_object(key)

    delete_item(DOCUMENTS_TABLE, {"document_id": document_id})

    new_count = max(0, (project.get("document_count") or 0) - 1)
    updates: dict = {"document_count": new_count, "updated_at": now_iso()}
    anchor_ids = project.get("anchor_document_ids")
    if isinstance(anchor_ids, list) and document_id in anchor_ids:
        updates["anchor_document_ids"] = [i for i in anchor_ids if i != document_id]
        updates["anchor_updated_at"] = now_iso()
    update_project(project_id, **updates)

    log_document_deleted(
        project_id,
        {
            "document_id": document_id,
            "file_name": file_name,
            "status": doc_status,
            "edited_fields": edited_fields,
            "s3_key": s3_key,
            "ocr_s3_key": ocr_s3_key,
            "extraction_s3_key": extraction_s3_key,
        },
        actor=user,
        source="api",
    )

    reconciliation = None
    try:
        record = invoke_reconcile(project_id)
        remaining = query_documents_by_project(project_id)
        reconciliation = reconciliation_view(record, remaining)
        if reconciliation is None:
            reconciliation = record
    except Exception:
        pass

    return json_response(
        {"project_id": project_id, "document_id": document_id, "reconciliation": reconciliation}
    )
