from common.dynamodb import RECONCILIATIONS_TABLE, get_item, query_documents_by_project
from common.errors import NotFound
from common.s3 import read_json
from common.reconcile_client import invoke_reconcile

from .http import json_response
from .projects import must_get_project
from .views import reconciliation_view


def must_get_reconciliation(reconciliation_id: str) -> dict:
    record = get_item(RECONCILIATIONS_TABLE, {"reconciliation_id": reconciliation_id})
    if record is None:
        raise NotFound(f"Không tìm thấy reconciliation: {reconciliation_id}")
    return record


def reconcile_project(params: dict, body: dict) -> dict:
    """Chỉ đối chiếu — KHÔNG gọi AI, không tốn tiền, bấm lại thoải mái.

    Gọi sang Lambda đối chiếu chứ không tự chạy: cả hệ thống chỉ có MỘT chỗ chạy
    đối chiếu, nên một log group và một bộ quyền ghi. `RequestResponse` để giữ
    nguyên hợp đồng đồng bộ — giao diện hiện số mâu thuẫn ngay sau khi bấm.
    """
    project_id = params["project_id"]
    must_get_project(project_id)
    record = invoke_reconcile(project_id)
    return json_response(
        reconciliation_view(record, query_documents_by_project(project_id))
    )


def get_reconciliation(params: dict, body: dict) -> dict:
    record = must_get_reconciliation(params["reconciliation_id"])
    detail = read_json(record["s3_key"])
    # `is_stale` ở đây nữa chứ không chỉ ở GET /projects/{id}: chặn duyệt dựa
    # vào nó, nên hai endpoint phải nói cùng một điều.
    day_du = reconciliation_view(record, query_documents_by_project(record["project_id"]))
    return json_response({**day_du, "discrepancies": detail.get("discrepancies", [])})
