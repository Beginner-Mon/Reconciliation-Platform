from common import RECONCILIATIONS_TABLE, NotFound, get_item, read_json
from workers.reconcile import run_reconciliation

from .http import json_response
from .projects import must_get_project


def must_get_reconciliation(reconciliation_id: str) -> dict:
    record = get_item(RECONCILIATIONS_TABLE, {"reconciliation_id": reconciliation_id})
    if record is None:
        raise NotFound(f"Không tìm thấy reconciliation: {reconciliation_id}")
    return record


def reconcile_project(params: dict, body: dict) -> dict:
    project_id = params["project_id"]
    must_get_project(project_id)
    record = run_reconciliation(project_id)
    return json_response(record)


def get_reconciliation(params: dict, body: dict) -> dict:
    record = must_get_reconciliation(params["reconciliation_id"])
    detail = read_json(record["s3_key"])
    return json_response({**record, "discrepancies": detail.get("discrepancies", [])})
