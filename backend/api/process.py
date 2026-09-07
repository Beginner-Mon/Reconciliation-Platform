from common import (
    RUNS_TABLE,
    BadRequest,
    Conflict,
    claim_processing_run,
    head_object,
    log_edit_overwritten,
    log_process_decision,
    new_run_id,
    now_iso,
    ocr_engines,
    put_item,
    query_documents_by_project,
    release_processing_run,
    update_document,
    update_item,
)
from common.stepfunctions import start_execution
from common.reconcile_client import invoke_reconcile

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


def _engine_choice(body: dict) -> str:
    """Engine OCR cho lần chạy này. Không khai thì dùng mặc định.

    Chỉ nhận engine trong `APP_ENGINES`: ba engine còn lại trong bảng chỉ để
    `evaluation/` đo, chưa chạy trên đường production nào.
    """
    name = body.get("engine")
    if not name:
        return ocr_engines.DEFAULT_ENGINE
    try:
        ocr_engines.resolve_for_app(name)
    except ValueError as exc:
        raise BadRequest(str(exc)) from exc
    return name


def _audit_decision(
    project_id: str,
    run_id: str | None,
    targets: list[dict],
    skipped: list[dict],
    force: bool,
    force_edited: bool,
    engine: str,
) -> None:
    """Ghi lại quyết định của /process — kể cả khi nó quyết định KHÔNG làm gì.

    Đây là nơi ra mọi quyết định tiêu tiền và mọi quyết định bỏ qua, nhưng trước
    đây không để lại dấu vết nào: danh sách skip kèm lý do chỉ nằm trong HTTP
    response rồi mất theo tab trình duyệt.
    """
    log_process_decision(
        project_id,
        {
            "run_id": run_id,
            "force": force,
            "force_edited": force_edited,
            # Không ghi thì vài tuần sau không ai biết con số đo được là của
            # engine nào — mà giờ engine đổi được theo từng lần chạy.
            "ocr_engine": engine,
            "processed": [d["document_id"] for d in targets],
            "skipped": [
                {"document_id": s["document_id"], "reason": s["reason"]} for s in skipped
            ],
        },
    )


def _audit_overwrites(project_id: str, run_id: str, targets: list[dict]) -> None:
    """Document có `edited_fields` mà vẫn lọt vào targets = force_edited đã bật.

    Ghi riêng từng document vì đây là thao tác PHÁ HUỶ duy nhất trong hệ thống:
    AI sắp ghi đè lên dữ liệu người sửa tay, và không có cách nào lấy lại.
    """
    for document in targets:
        edited_fields = document.get("edited_fields")
        if not edited_fields:
            continue
        log_edit_overwritten(
            document["document_id"],
            {
                "project_id": project_id,
                "run_id": run_id,
                "file_name": document.get("file_name"),
                "edited_fields": list(edited_fields),
                "edited_by": document.get("edited_by"),
                "edited_at": document.get("edited_at"),
            },
        )


def _split_duplicate_files(
    verified: list[tuple[dict, dict]], documents: list[dict]
) -> tuple[list[tuple[dict, dict]], list[tuple[dict, dict]]]:
    """Tách file TRÙNG NỘI DUNG ra khỏi danh sách sắp xử lý.

    Bấm upload hai lần sinh hai document_id khác nhau nhưng cùng một file. Trước
    đây cả hai đều bị OCR — trả tiền hai lần — rồi cộng vào nhau khi đối chiếu
    như thể là hai đợt giao hàng.

    Nhận diện bằng ETag mà `head_object` vốn đã trả về, nên không tốn thêm lời
    gọi API nào. So với CẢ document đã xử lý ở run trước (qua `content_hash` đã
    lưu) lẫn các document trong chính run này.
    """
    by_hash: dict[str, dict] = {
        d["content_hash"]: d for d in documents if d.get("content_hash")
    }

    keep: list[tuple[dict, dict]] = []
    duplicates: list[tuple[dict, dict]] = []
    for document, head in verified:
        etag = head.get("etag")
        original = by_hash.get(etag) if etag else None
        # Chạy lại chính nó (force=true) không phải là trùng.
        if original is not None and original["document_id"] != document["document_id"]:
            duplicates.append((document, original))
            continue
        keep.append((document, head))
        if etag:
            by_hash.setdefault(etag, document)
    return keep, duplicates


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

    # KHÔNG KHAI `document_ids` nghĩa là cả project — "chạy hết" chỉ là trường
    # hợp suy biến của "chạy những cái này", không phải nhánh code riêng.
    #
    # Nhưng phải phân biệt "không khai" (None) với "khai rỗng" ([]). Viết
    # `if requested:` thì `[]` là falsy và rơi vào nhánh chạy TẤT CẢ — ngược
    # hoàn toàn ý định. Giao diện có chọn nhiều chứng từ thì bỏ chọn hết rồi bấm
    # nhầm sẽ tiêu tiền AI cho cả project.
    requested = body.get("document_ids")
    if requested is None:
        candidates = documents
    else:
        if not isinstance(requested, list):
            raise BadRequest("document_ids phải là danh sách")
        if not requested:
            raise BadRequest(
                "document_ids rỗng — chưa chọn chứng từ nào. Bỏ hẳn trường này "
                "nếu muốn xử lý cả project."
            )
        by_id = {d["document_id"]: d for d in documents}
        missing = [i for i in requested if i not in by_id]
        if missing:
            raise BadRequest(f"document_id không thuộc project: {', '.join(missing)}")
        candidates = [by_id[i] for i in requested]

    force = bool(body.get("force"))
    force_edited = bool(body.get("force_edited"))
    engine = _engine_choice(body)

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

    # Loại file trùng nội dung TRƯỚC khi chốt targets — nếu không, chúng đi tiếp
    # vào Step Functions và tốn tiền OCR lần thứ hai cho cùng một file.
    verified, duplicates = _split_duplicate_files(verified, documents)
    for document, original in duplicates:
        skipped.append(
            {
                "document_id": document["document_id"],
                "file_name": document.get("file_name"),
                "reason": (
                    "trùng nội dung với "
                    f"{original.get('file_name') or original['document_id']}"
                ),
            }
        )
    targets = [document for document, _ in verified]

    if not targets:
        _audit_decision(project_id, None, targets, skipped, force, force_edited, engine)
        record = invoke_reconcile(project_id)
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
            "ocr_engine": engine,
            "status": "PROCESSING",
            "started_at": now_iso(),
        },
    )

    # Ghi vết TRƯỚC khi worker chạy: nếu run hỏng giữa chừng thì audit vẫn cho
    # biết đã định làm gì, đối chiếu với status FAILED của run là ra.
    _audit_decision(project_id, run_id, targets, skipped, force, force_edited, engine)
    _audit_overwrites(project_id, run_id, targets)

    for document, head in verified:
        update_document(
            document["document_id"],
            status="PENDING",
            step=None,
            step_status=None,
            attempt=0,
            error=None,
            size_bytes=head["size_bytes"],
            # Lưu lại để run SAU phát hiện được upload trùng, không phải chỉ
            # trong phạm vi một lần chạy.
            content_hash=head.get("etag"),
            updated_at=now_iso(),
        )

    # `ocr_engine` phải LUÔN có mặt, kể cả khi dùng mặc định: ItemSelector của
    # state machine khai `"ocr_engine.$": "$.ocr_engine"`, thiếu khoá là
    # States.Runtime và chết CẢ RUN chứ không phải một chứng từ.
    payload = {
        "project_id": project_id,
        "run_id": run_id,
        "ocr_engine": engine,
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
