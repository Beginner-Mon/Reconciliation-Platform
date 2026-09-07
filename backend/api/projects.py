from common import (
    PROJECTS_TABLE,
    RECONCILIATIONS_TABLE,
    RUNS_TABLE,
    BadRequest,
    NotFound,
    get_item,
    new_project_id,
    now_iso,
    put_item,
    query_documents_by_project,
)
from common.dynamodb import scan_table

from .http import json_response
from .views import document_view, progress_view


def must_get_project(project_id: str) -> dict:
    project = get_item(PROJECTS_TABLE, {"project_id": project_id})
    if project is None:
        raise NotFound(f"Không tìm thấy project: {project_id}")
    return project


def create_project(params: dict, body: dict) -> dict:
    name = (body.get("name") or "").strip()
    if not name:
        raise BadRequest("Thiếu name")

    project_id = new_project_id()
    project = {
        "project_id": project_id,
        "name": name,
        "description": body.get("description") or "",
        "created_at": now_iso(),
        "created_by": body.get("created_by") or "poc-user",
        "document_count": 0,
    }
    put_item(PROJECTS_TABLE, project)
    return json_response(project, 201)


def list_projects(params: dict, body: dict) -> dict:
    projects = scan_table(PROJECTS_TABLE)
    projects.sort(key=lambda p: p.get("created_at") or "", reverse=True)
    return json_response({"items": projects})


def get_project(params: dict, body: dict) -> dict:
    project_id = params["project_id"]
    project = must_get_project(project_id)
    documents = query_documents_by_project(project_id)
    documents.sort(key=lambda d: d.get("uploaded_at") or "")

    run = None
    run_id = project.get("processing_run_id") or project.get("last_run_id")
    if run_id:
        run = get_item(RUNS_TABLE, {"run_id": run_id})
    if run:
        run_documents = [d for d in documents if d["document_id"] in set(run.get("document_ids") or [])]
        run = {**run, **progress_view(run_documents), "is_active": bool(project.get("processing_run_id"))}

    reconciliation = None
    if project.get("latest_reconciliation_id"):
        reconciliation = get_item(
            RECONCILIATIONS_TABLE, {"reconciliation_id": project["latest_reconciliation_id"]}
        )

    return json_response(
        {
            "project": project,
            "run": run,
            "progress": progress_view(documents),
            "documents": [document_view(d, with_url=True) for d in documents],
            "latest_reconciliation": reconciliation,
        }
    )
