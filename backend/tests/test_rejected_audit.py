from tests.test_api import add_documents, call, make_project, put_file
from tests.test_audit import audit_events

TRI = {"cognito:username": "tri"}


def test_process_tren_project_rong_ghi_request_rejected(aws, capsys):
    project_id = make_project()
    capsys.readouterr()
    path = f"/projects/{project_id}/process"

    status, body = call("POST", path, claims=TRI)

    assert status == 400
    (su_kien,) = audit_events(capsys, "REQUEST_REJECTED")
    assert su_kien["actor"] == "tri"
    assert su_kien["project_id"] == project_id
    assert su_kien["entity_id"] == project_id
    assert su_kien["detail"] == {
        "method": "POST",
        "path": path,
        "status_code": 400,
        "error": body["error"],
    }


def test_process_khi_dang_co_run_ghi_dung_mot_dong_tu_choi(aws, started_executions, capsys):
    """Không xoá output trước lời gọi bị từ chối: ba request thành công đứng
    trước (tạo project, upload, /process) không được sinh dòng nào."""
    project_id = make_project()
    document = add_documents(project_id, "PO-001.pdf")[0]
    put_file(document["s3_key"])
    assert call("POST", f"/projects/{project_id}/process")[0] == 202

    status, _ = call("POST", f"/projects/{project_id}/process", claims=TRI)

    assert status == 409
    (su_kien,) = audit_events(capsys, "REQUEST_REJECTED")
    assert su_kien["detail"]["status_code"] == 409


def test_duyet_bi_tu_choi_lay_ma_doi_chieu_lam_entity(aws, capsys):
    status, _ = call(
        "POST",
        "/reconciliations/rec-khong-co/review",
        {"decision": "APPROVED"},
        claims=TRI,
    )

    assert status == 404
    (su_kien,) = audit_events(capsys, "REQUEST_REJECTED")
    assert su_kien["entity_id"] == "rec-khong-co"
    assert su_kien["project_id"] is None


def test_get_bi_tu_choi_khong_ghi_audit(aws, capsys):
    """Audit trả lời "ai LÀM gì". Đọc hỏng không phải thao tác, và giao diện
    poll GET liên tục nên ghi là thành rác."""
    status, _ = call("GET", "/projects/prj-khong-co", claims=TRI)

    assert status == 404
    assert audit_events(capsys, "REQUEST_REJECTED") == []
