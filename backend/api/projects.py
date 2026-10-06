from common.audit import (
    log_project_created,
    log_project_delete_started,
    log_project_deleted,
)
from common.dynamodb import (
    DOCUMENTS_TABLE,
    PROJECTS_TABLE,
    RECONCILIATIONS_TABLE,
    RUNS_TABLE,
    delete_item,
    get_item,
    put_item,
    query_document_names_by_project,
    query_documents_by_project,
    scan_keys_by_project,
    scan_table,
    update_item,
)
from common.errors import BadRequest, Conflict, NotFound
from common.ids import new_project_id, now_iso
from common.s3 import delete_prefix

from .http import json_response
from .views import document_view, progress_view, reconciliation_view


def must_get_project(project_id: str) -> dict:
    project = get_item(PROJECTS_TABLE, {"project_id": project_id})
    if project is None:
        raise NotFound(f"Không tìm thấy project: {project_id}")
    return project


def create_project(params: dict, body: dict, user: str) -> dict:
    name = (body.get("name") or "").strip()
    if not name:
        raise BadRequest("Thiếu name")

    project_id = new_project_id()
    project = {
        "project_id": project_id,
        "name": name,
        "description": body.get("description") or "",
        "created_at": now_iso(),
        "created_by": user,
        "document_count": 0,
    }
    put_item(PROJECTS_TABLE, project)
    log_project_created(
        project_id, {"name": name}, actor=user, source="api",
    )
    return json_response(project, 201)


def list_projects(params: dict, body: dict, user: str) -> dict:
    projects = scan_table(PROJECTS_TABLE)
    projects.sort(key=lambda p: p.get("created_at") or "", reverse=True)
    return json_response({"items": projects})


def get_project(params: dict, body: dict, user: str) -> dict:
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
            "latest_reconciliation": reconciliation_view(reconciliation, documents, project),
        }
    )


def delete_project(params: dict, body: dict, user: str) -> dict:
    project_id = params["project_id"]
    project = must_get_project(project_id)

    marked = update_item(
        PROJECTS_TABLE,
        {"project_id": project_id},
        {"deleting_at": now_iso(), "deleting_by": user},
        condition="attribute_exists(project_id) AND attribute_not_exists(processing_run_id)",
    )
    if not marked:
        raise Conflict("Project đang chạy xử lý — bấm Dừng, đợi run kết thúc rồi hãy xoá")

    documents = query_document_names_by_project(project_id)
    reconciliation_ids = scan_keys_by_project(
        RECONCILIATIONS_TABLE, "reconciliation_id", project_id
    )
    run_ids = scan_keys_by_project(RUNS_TABLE, "run_id", project_id)

    log_project_delete_started(
        project_id,
        {
            "name": project.get("name"),
            "documents": documents,
            "reconciliation_ids": reconciliation_ids,
            "run_ids": run_ids,
            "latest_reconciliation_id": project.get("latest_reconciliation_id"),
        },
        actor=user,
        source="api",
    )

    for document in documents:
        delete_item(DOCUMENTS_TABLE, {"document_id": document["document_id"]})
    for reconciliation_id in reconciliation_ids:
        delete_item(RECONCILIATIONS_TABLE, {"reconciliation_id": reconciliation_id})
    for run_id in run_ids:
        delete_item(RUNS_TABLE, {"run_id": run_id})

    s3_objects = delete_prefix(f"projects/{project_id}/")
    delete_item(PROJECTS_TABLE, {"project_id": project_id})

    deleted = {
        "documents": len(documents),
        "reconciliations": len(reconciliation_ids),
        "runs": len(run_ids),
        "s3_objects": s3_objects,
    }
    log_project_deleted(
        project_id, {"name": project.get("name"), **deleted}, actor=user, source="api"
    )
    return json_response({"project_id": project_id, "deleted": deleted})
