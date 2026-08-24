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

# Route chia theo MIỀN NGHIỆP VỤ, mỗi miền là 1 Lambda riêng trên cloud. Lý do là
# IAM: chỉ PROCESS_ROUTES cần `states:StartExecution` (quyền tiêu tiền AI) và chỉ
# PROJECT_ROUTES cần `dynamodb:Scan`. Gộp hết vào một function thì mọi route đều
# mang hợp của mọi quyền — kể cả route GET chỉ đọc.
#
# Ranh giới trùng đúng với file trong api/ nên không phải tra bảng: projects.py
# -> PROJECT_ROUTES, documents.py -> DOCUMENT_ROUTES, reconcile.py + review.py
# -> REVIEW_ROUTES, process.py -> PROCESS_ROUTES.
#
# Thứ tự BÊN TRONG mỗi danh sách không quan trọng: match_template() đối chiếu
# literal chính xác và bắt buộc cùng số đoạn, nên không template nào che template
# khác. Nhưng một route KHÔNG được nằm ở hai danh sách, và tập 12 route phải
# trùng khít `local.api_routes` trong infra/modules/aws/main.tf —
# tests/test_routes.py chặn cả hai lỗi đó offline.

PROJECT_ROUTES = [
    ("POST", "/projects", projects.create_project),
    ("GET", "/projects", projects.list_projects),
    ("GET", "/projects/{project_id}", projects.get_project),
]

DOCUMENT_ROUTES = [
    ("POST", "/projects/{project_id}/documents", documents.create_documents),
    ("GET", "/projects/{project_id}/documents", documents.list_documents),
    ("GET", "/projects/{project_id}/documents/{document_id}/ocr", documents.get_document_ocr),
]

# reconcile.py và review.py đi cùng nhau: đây là một tính năng liền mạch (hai tab
# "Cảnh báo" và "Sửa" của giao diện) và dùng chung đúng một bộ quyền. PATCH gọi
# run_reconciliation() vì sửa tay làm mọi mâu thuẫn tính trước đó thành lỗi thời.
REVIEW_ROUTES = [
    ("POST", "/projects/{project_id}/reconcile", reconcile.reconcile_project),
    ("PATCH", "/projects/{project_id}/documents/{document_id}", review.edit_document),
    ("GET", "/reconciliations/{reconciliation_id}", reconcile.get_reconciliation),
    ("POST", "/reconciliations/{reconciliation_id}/approve", review.approve_reconciliation),
    ("POST", "/reconciliations/{reconciliation_id}/reject", review.reject_reconciliation),
]

# Route DUY NHẤT gọi Step Functions trong toàn hệ thống.
PROCESS_ROUTES = [
    ("POST", "/projects/{project_id}/process", process.process_project),
]

ROUTES = PROJECT_ROUTES + DOCUMENT_ROUTES + REVIEW_ROUTES + PROCESS_ROUTES


def resolve(routes: list, method: str, path: str):
    for route_method, template, handler in routes:
        if route_method != method:
            continue
        params = match_template(template, path)
        if params is not None:
            return handler, params
    return None, None


def _dispatch(routes: list, event: dict) -> dict:
    method = request_method(event)
    path = request_path(event)

    handler, params = resolve(routes, method, path)
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


def _make_handler(routes: list, name: str):
    def handler(event: dict, context) -> dict:
        return _dispatch(routes, event)

    # Đặt tên thật để traceback trong CloudWatch chỉ ra đúng function nào lỗi,
    # thay vì "handler" cho cả bốn.
    handler.__name__ = name
    return handler


projects_handler = _make_handler(PROJECT_ROUTES, "projects_handler")
documents_handler = _make_handler(DOCUMENT_ROUTES, "documents_handler")
review_handler = _make_handler(REVIEW_ROUTES, "review_handler")
process_handler = _make_handler(PROCESS_ROUTES, "process_handler")

# GỘP đủ 12 route — KHÔNG được xoá. Dev server dựng một cửa duy nhất ở localhost
# (devserver/http_server.py, devserver/__main__.py) và test API gọi trực tiếp vào
# đây. Cloud có bốn cửa, dev có một; đó là chỗ duy nhất hai môi trường khác nhau,
# và nó nằm ở tầng vận chuyển chứ không phải tầng nghiệp vụ.
lambda_handler = _make_handler(ROUTES, "lambda_handler")
