from pathlib import Path

from common import (
    DOCUMENTS_TABLE,
    MAX_UPLOAD_BYTES,
    BadRequest,
    NotFound,
    create_upload_post,
    get_item,
    new_document_id,
    now_iso,
    put_item,
    query_documents_by_project,
    read_json,
    update_project,
    upload_key,
)

from .http import json_response
from .projects import must_get_project
from .views import document_view

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff"}
CONTENT_TYPE_BY_EXT = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tiff": "image/tiff",
}
MAX_FILES_PER_REQUEST = 20


def create_documents(params: dict, body: dict) -> dict:
    project_id = params["project_id"]
    project = must_get_project(project_id)

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
    return json_response({"project_id": project_id, "documents": created}, 201)


def get_document_ocr(params: dict, body: dict) -> dict:
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
    return json_response(
        {
            "document_id": document_id,
            "file_name": document.get("file_name"),
            "text": ocr.get("text", ""),
            "pages": ocr.get("pages", []),
        }
    )


def list_documents(params: dict, body: dict) -> dict:
    project_id = params["project_id"]
    must_get_project(project_id)
    documents = query_documents_by_project(project_id)
    documents.sort(key=lambda d: d.get("uploaded_at") or "")
    return json_response({"items": [document_view(d, with_url=True) for d in documents]})
