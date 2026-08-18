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
    "extraction",
    # confidence từ OCR — màn review dùng để tô trường AI đọc không chắc.
    # Spike đo được: conf 0,38 đúng là chỗ đọc sai. Thiếu trường này thì người
    # review không biết nên soi chỗ nào trước.
    "confidence",
    "validation",
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
