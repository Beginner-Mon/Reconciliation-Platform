import io
import json

import pytest
from botocore.exceptions import ClientError

from common.dynamodb import (
    PROJECTS_TABLE,
    RUNS_TABLE,
    get_item,
    put_item,
    release_processing_run,
    update_item,
)
from common.ids import new_project_id
from tests.test_api import add_documents, call, make_project, put_file
from tests.test_audit import audit_events

DINH_NGHIA = '{"StartAt":"X","States":{"X":{"Type":"Pass","End":true}}}'


def _project(project_id: str) -> dict:
    return get_item(PROJECTS_TABLE, {"project_id": project_id})


def _run(run_id: str) -> dict | None:
    return get_item(RUNS_TABLE, {"run_id": run_id})


def test_execution_is_running_doc_trang_thai_that(aws):
    from common.stepfunctions import execution_is_running, get_sfn

    may = get_sfn().create_state_machine(
        name="test-sm", definition=DINH_NGHIA, roleArn="arn:aws:iam::123456789012:role/x"
    )
    arn = get_sfn().start_execution(stateMachineArn=may["stateMachineArn"], name="run-1")[
        "executionArn"
    ]

    assert execution_is_running(arn) is True
    get_sfn().stop_execution(executionArn=arn)
    assert execution_is_running(arn) is False
    assert execution_is_running(arn.replace("run-1", "run-khong-co")) is False


def test_execution_is_running_khong_nuot_loi_khac(aws, monkeypatch):
    import common.stepfunctions as sfn_module

    class SfnHong:
        def describe_execution(self, **kwargs):
            raise ClientError(
                {"Error": {"Code": "ThrottlingException", "Message": "chậm lại"}},
                "DescribeExecution",
            )

    monkeypatch.setattr(sfn_module, "get_sfn", lambda: SfnHong())

    with pytest.raises(ClientError):
        sfn_module.execution_is_running("arn:aws:states:x:1:execution:sm:run-1")


def test_nha_khoa_co_dieu_kien_khong_dong_vao_khoa_cua_run_khac(aws):
    project_id = new_project_id()
    put_item(
        PROJECTS_TABLE,
        {"project_id": project_id, "name": "Gói thầu A", "processing_run_id": "run-moi"},
    )

    assert release_processing_run(project_id, "run-cu") is False
    assert _project(project_id)["processing_run_id"] == "run-moi"

    assert release_processing_run(project_id, "run-moi") is True
    assert "processing_run_id" not in _project(project_id)


def test_ket_thuc_run_bi_dung_khong_nha_khoa_cua_run_khac(aws):
    from workers.reconcile import lambda_handler

    project_id = new_project_id()
    put_item(
        PROJECTS_TABLE,
        {"project_id": project_id, "name": "Gói thầu A", "processing_run_id": "run-moi"},
    )
    put_item(
        RUNS_TABLE,
        {
            "run_id": "run-cu",
            "project_id": project_id,
            "document_ids": [],
            "status": "PROCESSING",
            "cancel_requested_at": "2026-10-06T08:00:00+00:00",
        },
    )

    lambda_handler({"project_id": project_id, "run_id": "run-cu"}, None)

    assert _project(project_id)["processing_run_id"] == "run-moi"


def test_invoke_reconcile_chi_gui_run_id_khi_co(monkeypatch):
    import common.reconcile_client as client

    da_gui = []

    class LambdaGia:
        def invoke(self, **kwargs):
            da_gui.append(json.loads(kwargs["Payload"]))
            return {"Payload": io.BytesIO(b'{"ok": true}')}

    monkeypatch.setattr(client, "RECONCILE_LAMBDA_ARN", "arn:aws:lambda:x:1:function:reconcile")
    monkeypatch.setattr(client, "get_lambda", lambda: LambdaGia())

    client.invoke_reconcile("prj-1")
    client.invoke_reconcile("prj-1", "run-1")

    assert da_gui == [{"project_id": "prj-1"}, {"project_id": "prj-1", "run_id": "run-1"}]


def test_execution_alive_cua_devserver_theo_thread():
    import threading

    from devserver.pipeline import execution_alive

    chan = threading.Event()
    song = threading.Thread(target=chan.wait, daemon=True)
    song.start()
    chet = threading.Thread(target=lambda: None)
    chet.start()
    chet.join()
    threads = {"run-song": song, "run-chet": chet}
    tien_to = "arn:aws:states:local:000000000000:execution:devserver:"

    try:
        assert execution_alive(threads, tien_to + "run-song") is True
        assert execution_alive(threads, tien_to + "run-chet") is False
        assert execution_alive(threads, tien_to + "run-khong-co") is False
    finally:
        chan.set()


def _project_dang_chay(*file_names: str) -> tuple[str, str]:
    project_id = make_project()
    for doc in add_documents(project_id, *file_names):
        put_file(doc["s3_key"])
    status, body = call("POST", f"/projects/{project_id}/process")
    assert status == 202
    return project_id, body["run_id"]


def test_run_con_song_thi_chi_dat_co_va_giu_khoa(aws, started_executions):
    project_id, run_id = _project_dang_chay("A.pdf")

    status, body = call("POST", f"/projects/{project_id}/process/stop")

    assert status == 202
    assert body["status"] == "STOPPING"
    assert _run(run_id)["status"] == "PROCESSING"
    assert _project(project_id)["processing_run_id"] == run_id


def test_dung_run_da_chet_thi_ket_thuc_ngay_va_nha_khoa(
    aws, started_executions, monkeypatch, capsys
):
    project_id, run_id = _project_dang_chay("A.pdf", "B.pdf")
    monkeypatch.setattr("api.process.execution_is_running", lambda arn: False)
    capsys.readouterr()

    status, body = call(
        "POST", f"/projects/{project_id}/process/stop", claims={"cognito:username": "tri"}
    )

    assert status == 200
    assert body["status"] == "CANCELLED"
    assert _run(run_id)["status"] == "CANCELLED"
    assert "processing_run_id" not in _project(project_id)
    (su_kien,) = audit_events(capsys, "PROCESS_RUN_UNSTUCK")
    assert su_kien["actor"] == "tri"
    assert su_kien["detail"]["run_id"] == run_id

    assert call("POST", f"/projects/{project_id}/process")[0] == 202


def test_bam_dung_lan_hai_go_duoc_run_chet_sau_lan_dau(aws, started_executions, monkeypatch):
    project_id, run_id = _project_dang_chay("A.pdf")
    assert call("POST", f"/projects/{project_id}/process/stop")[0] == 202

    monkeypatch.setattr("api.process.execution_is_running", lambda arn: False)
    status, body = call("POST", f"/projects/{project_id}/process/stop")

    assert status == 200
    assert body["status"] == "CANCELLED"
    assert "processing_run_id" not in _project(project_id)


def test_run_chua_co_execution_arn_thi_coi_la_con_song(aws, started_executions, monkeypatch):
    project_id, run_id = _project_dang_chay("A.pdf")
    update_item(RUNS_TABLE, {"run_id": run_id}, remove=["execution_arn"])

    def khong_duoc_goi(arn):
        raise AssertionError("không được hỏi Step Functions khi chưa có execution_arn")

    monkeypatch.setattr("api.process.execution_is_running", khong_duoc_goi)

    status, body = call("POST", f"/projects/{project_id}/process/stop")

    assert status == 202
    assert body["status"] == "STOPPING"


def test_run_da_ket_thuc_ma_khoa_con_thi_khong_go_theo_duong_run_chet(
    aws, started_executions, monkeypatch
):
    project_id, run_id = _project_dang_chay("A.pdf")
    update_item(RUNS_TABLE, {"run_id": run_id}, {"status": "SUCCEEDED"})
    monkeypatch.setattr("api.process.execution_is_running", lambda arn: False)

    status, _ = call("POST", f"/projects/{project_id}/process/stop")

    assert status == 202
    assert _run(run_id)["status"] == "SUCCEEDED"
    assert _project(project_id)["processing_run_id"] == run_id
