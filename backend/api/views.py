from common.s3 import create_view_url

STEP_SEQUENCE = ["ocr", "extract", "validate"]
STEPS_PER_DOCUMENT = len(STEP_SEQUENCE)

STATUS_STEPS_DONE = {
    "PENDING": 0,
    "PROCESSING": 0,
    "OCR_DONE": 1,
    "EXTRACTED": 2,
    "VALIDATED": 3,
}

PROCESSED_STATUSES = {"EXTRACTED", "VALIDATED"}

DOCUMENT_FIELDS = [
    "document_id",
    "project_id",
    "file_name",
    "file_type",
    "size_bytes",
    "uploaded_at",
    "status",
    "step",
    "step_status",
    "step_started_at",
    "attempt",
    "updated_at",
    "document_type",
    "po_number",
    "doc_number",
    "order_reference",
    "role",
    "ocr_engine",
    "extraction",
    "confidence",
    "validation",
    "ungrounded_fields",
    "edited_fields",
    "edited_at",
    "dismissed_flags",
    "error",
]


def steps_done(document: dict) -> int:
    """Số bước đã hoàn thành của 1 document.

    KHÔNG suy được chỉ từ `status`: workers/steps.py `begin_step()` đặt
    status="PROCESSING" ở MỌI bước, ghi đè mất OCR_DONE/EXTRACTED. Nếu chỉ nhìn
    status thì tiến độ đứng im ở 0 suốt cả document rồi nhảy một phát — đúng
    thứ mà cách tính theo bước sinh ra để tránh. Phải suy từ `step` đang chạy.
    """
    status = document.get("status")
    step = document.get("step")

    if status == "FAILED":
        return STEP_SEQUENCE.index(step) if step in STEP_SEQUENCE else 0

    if status == "PROCESSING" and step in STEP_SEQUENCE:
        done_before = STEP_SEQUENCE.index(step)
        return done_before + 1 if document.get("step_status") == "done" else done_before

    return STATUS_STEPS_DONE.get(status, 0)


def is_processed(document: dict) -> bool:
    return document.get("status") in PROCESSED_STATUSES


BLOCKING_FLAG_CODES = ("ai_format", "vi_tri")


def dismissed_key(code: str, field: str) -> str:
    return f"{code}:{field}"


def dismissed_map(document: dict) -> dict:
    entries = document.get("dismissed_flags")
    out = {}
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict) and entry.get("code") and entry.get("field"):
                out[dismissed_key(entry["code"], entry["field"])] = entry
    return out


def is_dismissed(document: dict, flag: dict) -> dict | None:
    if not isinstance(flag, dict):
        return None
    entry = dismissed_map(document).get(dismissed_key(flag.get("code"), flag.get("field")))
    if not entry:
        return None
    if entry.get("values", {}) != (flag.get("values") or {}):
        return None
    return entry


def unconfirmed_flag_keys(document: dict) -> list[str]:
    flags = (document.get("validation") or {}).get("flags") or []
    return sorted({
        dismissed_key(flag.get("code"), flag.get("field"))
        for flag in flags
        if isinstance(flag, dict)
        and flag.get("code") in BLOCKING_FLAG_CODES
        and not is_dismissed(document, flag)
    })


def document_view(document: dict, with_url: bool = False) -> dict:
    view = {key: document.get(key) for key in DOCUMENT_FIELDS if key in document}
    view["needs_confirmation"] = bool(unconfirmed_flag_keys(document))
    if with_url:
        view["view_url"] = create_view_url(document.get("s3_key", ""))
    return view


def progress_view(documents: list[dict]) -> dict:
    total_steps = len(documents) * STEPS_PER_DOCUMENT
    done_steps = sum(steps_done(d) for d in documents)
    failed = [d for d in documents if d.get("status") == "FAILED"]
    return {
        "total_documents": len(documents),
        "done_documents": sum(1 for d in documents if is_processed(d)),
        "failed_documents": len(failed),
        "total_steps": total_steps,
        "done_steps": done_steps,
        "progress_percent": round(done_steps * 100 / total_steps) if total_steps else 100,
    }


def da_cu(reconciliation: dict, documents: list[dict], project: dict | None = None) -> bool:
    """Kết quả đối chiếu này có bị lỗi thời không.

    Cũ = có chứng từ nào được sửa SAU khi đối chiếu chạy. Trước đây không cần
    khái niệm này vì `PATCH` tự chạy lại đối chiếu — nhưng đó là việc không
    thuộc về nó, và nó khiến cùng một logic chạy ở ba Lambda.

    KHÔNG cần thêm trường lưu trữ nào: `updated_at` được đóng dấu ở MỌI chỗ sửa
    document (`api/documents.py` lúc tạo, `api/process.py` lúc xếp hàng,
    `workers/steps.py` mỗi bước, `api/review.py` lúc sửa tay), và `now_iso()`
    trả ISO nên so chuỗi ra đúng thứ tự thời gian.

    Xoá chứng từ cũng làm đợt cũ thành stale: reconciliation lưu `document_ids`
    tại thời điểm đối chiếu, nếu có id không còn tồn tại trong documents hiện tại
    thì đó là đợt cũ trước khi xoá (P1).
    Đổi gốc cũng làm stale: project.anchor_updated_at > reconciliation.created_at (P2).
    """
    if not reconciliation:
        return False
    # P1: đợt cũ chứa document đã bị xoá → stale để chặn duyệt
    doc_ids = reconciliation.get("document_ids")
    if isinstance(doc_ids, list) and doc_ids:
        existing = {d.get("document_id") for d in documents}
        if any(doc_id not in existing for doc_id in doc_ids):
            return True
    if project and project.get("anchor_updated_at"):
        if project["anchor_updated_at"] > (reconciliation.get("created_at") or ""):
            return True
    moi_nhat = max((d.get("updated_at") or "" for d in documents), default="")
    if moi_nhat > (reconciliation.get("created_at") or ""):
        return True
    return False


def reconciliation_view(reconciliation: dict | None, documents: list[dict], project: dict | None = None) -> dict | None:
    """Bản ghi đối chiếu kèm cờ `is_stale` cho giao diện."""
    if not reconciliation:
        return None
    trong_dot = set(reconciliation.get("document_ids") or [])
    cho = [
        d.get("document_id") for d in documents
        if d.get("document_id") in trong_dot and unconfirmed_flag_keys(d)
    ]
    return {
        **reconciliation,
        "is_stale": da_cu(reconciliation, documents, project),
        "unconfirmed_document_ids": cho,
    }
