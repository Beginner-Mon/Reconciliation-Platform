import pytest
from botocore.exceptions import ClientError

from common.dynamodb import (
    DOCUMENTS_TABLE,
    PROJECTS_TABLE,
    RECONCILIATIONS_TABLE,
    RUNS_TABLE,
    claim_processing_run,
    get_item,
    put_item,
    query_document_names_by_project,
    query_documents_by_project,
    scan_keys_by_project,
    update_item,
)
from common.ids import new_run_id
from common.s3 import BUCKET, delete_prefix, get_s3, write_object
from tests.test_api import (
    INVOICE_DATA,
    PO_DATA,
    add_documents,
    call,
    make_project,
    mark_processed,
    put_file,
)
from tests.test_audit import audit_events


def _keys(prefix: str = "") -> list[str]:
    response = get_s3().list_objects_v2(Bucket=BUCKET, Prefix=prefix)
    return [item["Key"] for item in response.get("Contents", [])]


def test_delete_prefix_xoa_dung_project_va_khong_lan_sang_project_khac(aws):
    write_object("projects/prj-1/uploads/a.pdf", b"a")
    write_object("projects/prj-1/ocr/a.json", b"{}")
    write_object("projects/prj-10/uploads/b.pdf", b"b")

    assert delete_prefix("projects/prj-1/") == 2

    assert _keys() == ["projects/prj-10/uploads/b.pdf"]


@pytest.mark.parametrize("prefix", ["projects/prj-1", ""])
def test_delete_prefix_tu_choi_prefix_khong_ket_thuc_bang_gach_cheo(aws, prefix):
    write_object("projects/prj-10/uploads/b.pdf", b"b")

    with pytest.raises(ValueError):
        delete_prefix(prefix)

    assert _keys() == ["projects/prj-10/uploads/b.pdf"]


def test_delete_prefix_di_het_moi_trang(aws):
    for i in range(5):
        write_object(f"projects/prj-1/uploads/{i}.pdf", b"x")

    assert delete_prefix("projects/prj-1/", page_size=2) == 5

    assert _keys() == []


def test_delete_prefix_khong_co_gi_de_xoa_tra_0(aws):
    assert delete_prefix("projects/prj-khong-co/") == 0


def test_query_document_names_khong_hydrate_tu_s3(aws):
    put_item(
        DOCUMENTS_TABLE,
        {
            "document_id": "doc-1",
            "project_id": "prj-1",
            "file_name": "INV.pdf",
            "document_payload_s3_key": "projects/prj-1/document-payload/doc-1/da-mat.json",
        },
    )
    put_item(
        DOCUMENTS_TABLE,
        {"document_id": "doc-2", "project_id": "prj-2", "file_name": "PO.pdf"},
    )

    with pytest.raises(ClientError):
        query_documents_by_project("prj-1")

    assert query_document_names_by_project("prj-1") == [
        {"document_id": "doc-1", "file_name": "INV.pdf"}
    ]


def test_scan_keys_by_project_chi_lay_khoa_cua_dung_project(aws):
    put_item(RUNS_TABLE, {"run_id": "run-1", "project_id": "prj-1"})
    put_item(RUNS_TABLE, {"run_id": "run-2", "project_id": "prj-1"})
    put_item(RUNS_TABLE, {"run_id": "run-3", "project_id": "prj-2"})

    assert sorted(scan_keys_by_project(RUNS_TABLE, "run_id", "prj-1")) == ["run-1", "run-2"]
    assert scan_keys_by_project(RUNS_TABLE, "run_id", "prj-khong-co") == []


def _project_co_du_lieu() -> tuple[str, list[str]]:
    project_id = make_project()
    po, inv = add_documents(project_id, "PO.pdf", "INV.pdf")
    put_file(po["s3_key"])
    put_file(inv["s3_key"])
    mark_processed(po["document_id"], PO_DATA)
    mark_processed(inv["document_id"], INVOICE_DATA)
    status, _ = call("POST", f"/projects/{project_id}/reconcile")
    assert status == 200
    put_item(
        RUNS_TABLE, {"run_id": new_run_id(), "project_id": project_id, "status": "SUCCEEDED"}
    )
    return project_id, [po["document_id"], inv["document_id"]]


def test_xoa_project_xoa_het_du_lieu_cua_no_va_chi_cua_no(aws):
    project_id, document_ids = _project_co_du_lieu()
    khac_id, _ = _project_co_du_lieu()
    write_object(f"projects/{project_id}x/uploads/la.pdf", b"x")

    status, body = call("DELETE", f"/projects/{project_id}")

    assert status == 200
    assert body["deleted"] == {
        "documents": 2,
        "reconciliations": 1,
        "runs": 1,
        "s3_objects": 3,
    }
    assert call("GET", f"/projects/{project_id}")[0] == 404
    for document_id in document_ids:
        assert get_item(DOCUMENTS_TABLE, {"document_id": document_id}) is None
    assert scan_keys_by_project(RUNS_TABLE, "run_id", project_id) == []
    assert scan_keys_by_project(RECONCILIATIONS_TABLE, "reconciliation_id", project_id) == []
    assert _keys(f"projects/{project_id}/") == []

    assert _keys(f"projects/{project_id}x/") == [f"projects/{project_id}x/uploads/la.pdf"]
    assert call("GET", f"/projects/{khac_id}")[0] == 200
    assert len(_keys(f"projects/{khac_id}/")) == 3
    assert len(scan_keys_by_project(RUNS_TABLE, "run_id", khac_id)) == 1
    assert len(scan_keys_by_project(RECONCILIATIONS_TABLE, "reconciliation_id", khac_id)) == 1


def test_xoa_project_rong_roi_xoa_lan_hai_tra_404(aws):
    project_id = make_project()

    status, body = call("DELETE", f"/projects/{project_id}")
    assert status == 200
    assert body["deleted"] == {"documents": 0, "reconciliations": 0, "runs": 0, "s3_objects": 0}

    assert call("DELETE", f"/projects/{project_id}")[0] == 404
    assert get_item(PROJECTS_TABLE, {"project_id": project_id}) is None


def test_khong_xoa_duoc_project_dang_chay(aws, started_executions):
    project_id = make_project()
    (doc,) = add_documents(project_id, "INV.pdf")
    put_file(doc["s3_key"])
    assert call("POST", f"/projects/{project_id}/process")[0] == 202

    status, _ = call("DELETE", f"/projects/{project_id}")

    assert status == 409
    assert "deleting_at" not in get_item(PROJECTS_TABLE, {"project_id": project_id})
    assert get_item(DOCUMENTS_TABLE, {"document_id": doc["document_id"]}) is not None
    assert _keys(f"projects/{project_id}/") == [doc["s3_key"]]


def test_xoa_hong_giua_chung_thi_goi_lai_la_xong(aws, monkeypatch):
    import api.projects as projects_module

    project_id, _ = _project_co_du_lieu()
    that = projects_module.delete_prefix
    so_lan = []

    def hong_lan_dau(prefix):
        so_lan.append(prefix)
        if len(so_lan) == 1:
            raise RuntimeError("S3 sập")
        return that(prefix)

    monkeypatch.setattr(projects_module, "delete_prefix", hong_lan_dau)

    assert call("DELETE", f"/projects/{project_id}")[0] == 500
    assert get_item(PROJECTS_TABLE, {"project_id": project_id})["deleting_at"]
    assert call("GET", f"/projects/{project_id}")[0] == 200
    assert len(_keys(f"projects/{project_id}/")) == 3

    assert call("DELETE", f"/projects/{project_id}")[0] == 200
    assert get_item(PROJECTS_TABLE, {"project_id": project_id}) is None
    assert _keys(f"projects/{project_id}/") == []


def test_project_dang_xoa_do_thi_khong_process_khong_upload_duoc(aws, started_executions):
    project_id = make_project()
    (doc,) = add_documents(project_id, "INV.pdf")
    put_file(doc["s3_key"])
    update_item(
        PROJECTS_TABLE,
        {"project_id": project_id},
        {"deleting_at": "2026-10-06T08:00:00+00:00"},
    )

    assert call("POST", f"/projects/{project_id}/process")[0] == 409
    assert started_executions == []
    status, _ = call(
        "POST", f"/projects/{project_id}/documents", {"files": [{"file_name": "B.pdf"}]}
    )
    assert status == 409


def test_claim_khoa_bi_tu_choi_khi_project_dang_xoa(aws):
    project_id = make_project()
    update_item(
        PROJECTS_TABLE,
        {"project_id": project_id},
        {"deleting_at": "2026-10-06T08:00:00+00:00"},
    )

    assert claim_processing_run(project_id, "run-x") is False
    assert "processing_run_id" not in get_item(PROJECTS_TABLE, {"project_id": project_id})


def test_xoa_duoc_ca_khi_file_payload_da_mat(aws):
    project_id = make_project()
    (doc,) = add_documents(project_id, "INV.pdf")
    update_item(
        DOCUMENTS_TABLE,
        {"document_id": doc["document_id"]},
        {
            "document_payload_s3_key": (
                f"projects/{project_id}/document-payload/{doc['document_id']}/da-mat.json"
            )
        },
    )

    assert call("DELETE", f"/projects/{project_id}")[0] == 200
    assert get_item(PROJECTS_TABLE, {"project_id": project_id}) is None


def test_xoa_project_ghi_audit_truoc_va_sau(aws, capsys):
    project_id, document_ids = _project_co_du_lieu()
    capsys.readouterr()

    call("DELETE", f"/projects/{project_id}", claims={"cognito:username": "tri"})

    su_kien = audit_events(capsys)
    bat_dau = next(e for e in su_kien if e["action"] == "PROJECT_DELETE_STARTED")
    xong = next(e for e in su_kien if e["action"] == "PROJECT_DELETED")
    assert bat_dau["actor"] == "tri"
    assert xong["actor"] == "tri"
    assert bat_dau["detail"]["name"] == "Gói thầu A"
    assert sorted(d["document_id"] for d in bat_dau["detail"]["documents"]) == sorted(
        document_ids
    )
    assert xong["detail"]["documents"] == 2
    assert xong["detail"]["s3_objects"] == 3
