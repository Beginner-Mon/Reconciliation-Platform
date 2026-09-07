from common import create_view_url

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
    # Engine OCR đã chạy cho chứng từ này. Engine giờ chọn được theo TỪNG lần
    # chạy, nên không lưu ra đây thì màn hình không phân biệt được chứng từ nào
    # đọc bằng Textract, chứng từ nào bằng Document AI.
    "ocr_engine",
    "extraction",
    # confidence từ OCR — màn review dùng để tô trường AI đọc không chắc.
    # Spike đo được: conf 0,38 đúng là chỗ đọc sai. Thiếu trường này thì người
    # review không biết nên soi chỗ nào trước.
    "confidence",
    "validation",
    # Trường LLM trả về mà không tìm thấy trong text OCR — nhiều khả năng bị bịa.
    # Để TOP-LEVEL chứ không nhét vào `validation`: worker validate ghi đè nguyên
    # cả dict `validation` và nó chạy SAU extract, nhét vào đó là mất sạch.
    "ungrounded_fields",
    "edited_fields",
    "edited_at",
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


def document_view(document: dict, with_url: bool = False) -> dict:
    view = {key: document.get(key) for key in DOCUMENT_FIELDS if key in document}
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


def da_cu(reconciliation: dict, documents: list[dict]) -> bool:
    """Kết quả đối chiếu này có bị lỗi thời không.

    Cũ = có chứng từ nào được sửa SAU khi đối chiếu chạy. Trước đây không cần
    khái niệm này vì `PATCH` tự chạy lại đối chiếu — nhưng đó là việc không
    thuộc về nó, và nó khiến cùng một logic chạy ở ba Lambda.

    KHÔNG cần thêm trường lưu trữ nào: `updated_at` được đóng dấu ở MỌI chỗ sửa
    document (`api/documents.py` lúc tạo, `api/process.py` lúc xếp hàng,
    `workers/steps.py` mỗi bước, `api/review.py` lúc sửa tay), và `now_iso()`
    trả ISO nên so chuỗi ra đúng thứ tự thời gian.
    """
    if not reconciliation:
        return False
    moi_nhat = max((d.get("updated_at") or "" for d in documents), default="")
    return moi_nhat > (reconciliation.get("created_at") or "")


def reconciliation_view(reconciliation: dict | None, documents: list[dict]) -> dict | None:
    """Bản ghi đối chiếu kèm cờ `is_stale` cho giao diện."""
    if not reconciliation:
        return None
    return {**reconciliation, "is_stale": da_cu(reconciliation, documents)}
