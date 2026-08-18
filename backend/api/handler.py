import json
import logging

from common import AppError

from . import documents, process, projects, reconcile, review
from .http import (
    error_response,
    match_template,
    parse_body,
    request_method,
    request_path,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ROUTES = [
    ("POST", "/projects", projects.create_project),
    ("GET", "/projects", projects.list_projects),
    ("GET", "/projects/{project_id}", projects.get_project),
    ("POST", "/projects/{project_id}/documents", documents.create_documents),
    ("GET", "/projects/{project_id}/documents", documents.list_documents),
    ("GET", "/projects/{project_id}/documents/{document_id}/ocr", documents.get_document_ocr),
    ("POST", "/projects/{project_id}/process", process.process_project),
    ("POST", "/projects/{project_id}/reconcile", reconcile.reconcile_project),
    ("PATCH", "/projects/{project_id}/documents/{document_id}", review.edit_document),
    ("GET", "/reconciliations/{reconciliation_id}", reconcile.get_reconciliation),
    ("POST", "/reconciliations/{reconciliation_id}/approve", review.approve_reconciliation),
    ("POST", "/reconciliations/{reconciliation_id}/reject", review.reject_reconciliation),
]


def resolve(method: str, path: str):
    for route_method, template, handler in ROUTES:
        if route_method != method:
            continue
        params = match_template(template, path)
        if params is not None:
            return handler, params
    return None, None


def lambda_handler(event: dict, context) -> dict:
    method = request_method(event)
    path = request_path(event)

    handler, params = resolve(method, path)
    if handler is None:
        return error_response(f"Không có route: {method} {path}", 404)

    try:
        body = parse_body(event)
    except json.JSONDecodeError:
        return error_response("Body không phải JSON", 400)

    params = {**(event.get("pathParameters") or {}), **params}

    try:
        return handler(params, body)
    except AppError as exc:
        return error_response(exc.message, exc.status_code)
    except Exception as exc:
        logger.exception("Lỗi khi xử lý %s %s", method, path)
        return error_response(f"Lỗi hệ thống: {exc}", 500)
