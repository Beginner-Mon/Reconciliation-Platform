import uuid
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new(prefix: str, size: int = 12) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:size]}"


def new_project_id() -> str:
    return _new("prj")


def new_document_id() -> str:
    return _new("doc")


def new_run_id() -> str:
    return _new("run")


def new_reconciliation_id() -> str:
    return _new("rec")


def new_request_id() -> str:
    return _new("req", 8)
