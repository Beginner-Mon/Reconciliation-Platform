import pytest

from common import ocr_engines
from common.dynamodb import (
    DOCUMENTS_TABLE,
    PROJECTS_TABLE,
    RUNS_TABLE,
    get_item,
    put_item,
    update_document,
    update_item,
)
from common.ids import new_document_id, new_project_id, new_run_id
from common.s3 import ocr_key, upload_key, write_json, write_object
from tests.test_api import (
    INVOICE_DATA,
    PO_DATA,
    add_documents,
    call,
    make_project,
    mark_processed,
    put_file,
)
from tests.test_audit import audit_events, log_events

OCR_GIA = {"text": "3126818 0102721191-068", "pages": [{"page_number": 1, "lines": []}]}
GEMINI_GIA = {
    "document_type": "invoice",
    "data": {"invoice_number": "3126818"},
    "confidence": {"invoice_number": 0.9},
}
CO = "2026-10-06T08:00:00+00:00"


def _doc(document_id: str) -> dict:
    return get_item(DOCUMENTS_TABLE, {"document_id": document_id})


def _run(run_id: str) -> dict | None:
    return get_item(RUNS_TABLE, {"run_id": run_id})


def _project(project_id: str) -> dict:
    return get_item(PROJECTS_TABLE, {"project_id": project_id})


def _dat_co(run_id: str) -> None:
    update_item(RUNS_TABLE, {"run_id": run_id}, {"cancel_requested_at": CO})


@pytest.fixture
def su_kien_worker(aws):
    project_id, run_id, document_id = new_project_id(), new_run_id(), new_document_id()
    key = upload_key(project_id, document_id, ".pdf")
    write_object(key, b"%PDF-1.4 gia lap", content_type="application/pdf")
    put_item(
        PROJECTS_TABLE,
        {"project_id": project_id, "name": "Gói thầu A", "processing_run_id": run_id},
    )
    put_item(
        RUNS_TABLE,
        {
            "run_id": run_id,
            "project_id": project_id,
            "document_ids": [document_id],
            "status": "PROCESSING",
        },
    )
    put_item(
        DOCUMENTS_TABLE,
        {"document_id": document_id, "project_id": project_id, "s3_key": key, "status": "PENDING"},
    )
    return {
        "project_id": project_id,
        "run_id": run_id,
        "ocr_engine": ocr_engines.DEFAULT_ENGINE,
        "document_id": document_id,
        "s3_key": key,
    }


@pytest.fixture
def ocr_gia(monkeypatch):
    da_goi = []

    def fake_run(name, content, mime_type, s3_key=None):
        da_goi.append(s3_key)
        return OCR_GIA

    monkeypatch.setattr("common.ocr_engines.run", fake_run)
    return da_goi


@pytest.fixture
def gemini_gia(monkeypatch):
    da_goi = []

    def fake_extract(ocr_json):
        da_goi.append(1)
        return dict(GEMINI_GIA)

    monkeypatch.setattr("workers.extract.extract_with_gemini", fake_extract)
    return da_goi


def test_ocr_bo_qua_khi_run_da_co_co_dung(su_kien_worker, ocr_gia, capsys):
    from workers.ocr import lambda_handler

    _dat_co(su_kien_worker["run_id"])

    ket_qua = lambda_handler(dict(su_kien_worker), None)

    assert ocr_gia == []
    assert ket_qua["skipped"] == "cancelled"
    doc = _doc(su_kien_worker["document_id"])
    assert doc["status"] == "PENDING"
    assert "step" not in doc
    assert log_events(capsys, "AI_CALL") == []


def test_ocr_van_chay_khi_run_chua_co_co(su_kien_worker, ocr_gia):
    from workers.ocr import lambda_handler

    ket_qua = lambda_handler(dict(su_kien_worker), None)

    assert len(ocr_gia) == 1
    assert "skipped" not in ket_qua
    assert _doc(su_kien_worker["document_id"])["status"] == "OCR_DONE"


def test_extract_bo_qua_khi_buoc_truoc_da_bo_qua(su_kien_worker, gemini_gia):
    from workers.extract import lambda_handler

    su_kien = {**su_kien_worker, "skipped": "cancelled"}

    assert lambda_handler(su_kien, None) == su_kien
    assert gemini_gia == []
    assert _doc(su_kien_worker["document_id"])["status"] == "PENDING"


def test_extract_bo_qua_khi_co_dung_duoc_dat_sau_ocr(su_kien_worker, gemini_gia):
    from workers.extract import lambda_handler

    key = ocr_key(su_kien_worker["project_id"], su_kien_worker["document_id"])
    write_json(key, OCR_GIA)
    update_document(
        su_kien_worker["document_id"], status="OCR_DONE", step="ocr", step_status="done"
    )
    _dat_co(su_kien_worker["run_id"])

    ket_qua = lambda_handler({**su_kien_worker, "ocr_s3_key": key}, None)

    assert gemini_gia == []
    assert ket_qua["skipped"] == "cancelled"
    assert _doc(su_kien_worker["document_id"])["status"] == "OCR_DONE"


def test_validate_bo_qua_khi_buoc_truoc_da_bo_qua(su_kien_worker):
    from workers.validate import lambda_handler

    su_kien = {**su_kien_worker, "skipped": "cancelled"}

    assert lambda_handler(su_kien, None) == su_kien
    assert _doc(su_kien_worker["document_id"])["status"] == "PENDING"


def test_validate_KHONG_kiem_co_dung(su_kien_worker):
    from workers.validate import lambda_handler

    update_document(
        su_kien_worker["document_id"],
        status="EXTRACTED",
        step="extract",
        step_status="done",
        extraction=INVOICE_DATA,
    )
    _dat_co(su_kien_worker["run_id"])

    ket_qua = lambda_handler(dict(su_kien_worker), None)

    assert "skipped" not in ket_qua
    assert _doc(su_kien_worker["document_id"])["step"] == "validate"


def _chung_tu(project_id: str, run_ids: list, **fields) -> str:
    document_id = new_document_id()
    put_item(
        DOCUMENTS_TABLE, {"document_id": document_id, "project_id": project_id, **fields}
    )
    run_ids.append(document_id)
    return document_id


def _run_co_co(project_id: str, run_id: str, document_ids: list) -> None:
    put_item(
        PROJECTS_TABLE,
        {
            "project_id": project_id,
            "name": "Gói thầu A",
            "processing_run_id": run_id,
            "latest_reconciliation_id": "rec-cu",
        },
    )
    put_item(
        RUNS_TABLE,
        {
            "run_id": run_id,
            "project_id": project_id,
            "document_ids": document_ids,
            "status": "PROCESSING",
            "cancel_requested_at": CO,
        },
    )


def test_ket_thuc_run_bi_dung_don_dung_tung_loai_chung_tu(aws, capsys):
    from workers.reconcile import lambda_handler

    project_id, run_id = new_project_id(), new_run_id()
    ids: list = []
    da_xong = _chung_tu(project_id, ids, status="VALIDATED", step="validate", step_status="done")
    loi = _chung_tu(
        project_id, ids, status="FAILED", step="ocr", step_status="failed", error="OCR sập"
    )
    chay_lai_chua_kip = _chung_tu(
        project_id, ids, status="PENDING", status_before_run="VALIDATED"
    )
    chua_chay = _chung_tu(project_id, ids, status="PENDING", status_before_run=None)
    do_dang = _chung_tu(project_id, ids, status="OCR_DONE", step="ocr", step_status="done")
    ngoai_run = new_document_id()
    put_item(
        DOCUMENTS_TABLE,
        {"document_id": ngoai_run, "project_id": project_id, "status": "OCR_DONE"},
    )
    _run_co_co(project_id, run_id, ids)

    ket_qua = lambda_handler({"project_id": project_id, "run_id": run_id}, None)

    assert ket_qua == {"project_id": project_id, "run_id": run_id, "status": "CANCELLED"}
    assert _doc(da_xong)["status"] == "VALIDATED"
    assert _doc(loi)["status"] == "FAILED"
    assert _doc(loi)["error"] == "OCR sập"
    assert _doc(chay_lai_chua_kip)["status"] == "VALIDATED"
    assert _doc(chua_chay)["status"] == "PENDING"
    assert _doc(do_dang)["status"] == "PENDING"
    assert _doc(do_dang).get("step") is None
    assert _doc(do_dang).get("step_status") is None
    assert _doc(ngoai_run)["status"] == "OCR_DONE"

    run = _run(run_id)
    assert run["status"] == "CANCELLED"
    assert run["finished_at"]
    project = _project(project_id)
    assert "processing_run_id" not in project
    assert project["last_run_id"] == run_id
    assert project["latest_reconciliation_id"] == "rec-cu"

    # Chứng từ nào xong, chưa chạy, đang dở lúc dừng: ghi trên record run, không ở log.
    assert sorted(run["finished_document_ids"]) == sorted([da_xong, loi])
    assert sorted(run["not_started_document_ids"]) == sorted([chay_lai_chua_kip, chua_chay])
    assert run["interrupted_document_ids"] == [do_dang]


def test_dung_sau_khi_moi_chung_tu_da_xong_thi_khong_dong_vao_chung_tu(aws):
    from workers.reconcile import lambda_handler

    project_id, run_id = new_project_id(), new_run_id()
    ids: list = []
    da_xong = _chung_tu(project_id, ids, status="VALIDATED", extraction=INVOICE_DATA)
    _run_co_co(project_id, run_id, ids)

    lambda_handler({"project_id": project_id, "run_id": run_id}, None)

    assert _doc(da_xong)["status"] == "VALIDATED"
    assert _run(run_id)["status"] == "CANCELLED"
    assert _project(project_id)["latest_reconciliation_id"] == "rec-cu"


def test_run_khong_bi_dung_van_doi_chieu_va_SUCCEEDED(aws):
    from workers.reconcile import lambda_handler

    project_id, run_id = new_project_id(), new_run_id()
    ids: list = []
    _chung_tu(project_id, ids, status="VALIDATED", extraction={"document_type": "unknown"})
    put_item(
        PROJECTS_TABLE,
        {"project_id": project_id, "name": "Gói thầu A", "processing_run_id": run_id},
    )
    put_item(
        RUNS_TABLE,
        {"run_id": run_id, "project_id": project_id, "document_ids": ids, "status": "PROCESSING"},
    )

    ket_qua = lambda_handler({"project_id": project_id, "run_id": run_id}, None)

    assert _run(run_id)["status"] == "SUCCEEDED"
    project = _project(project_id)
    assert "processing_run_id" not in project
    assert project["latest_reconciliation_id"] == ket_qua["reconciliation_id"]


def test_doi_chieu_khong_co_run_id_thi_KHONG_nha_khoa_cua_run_dang_chay(aws):
    from workers.reconcile import lambda_handler

    project_id = new_project_id()
    _chung_tu(project_id, [], status="VALIDATED", extraction={"document_type": "unknown"})
    put_item(
        PROJECTS_TABLE,
        {"project_id": project_id, "name": "Gói thầu A", "processing_run_id": "run-dang-chay"},
    )

    lambda_handler({"project_id": project_id}, None)

    assert _project(project_id)["processing_run_id"] == "run-dang-chay"


def test_process_ghi_status_before_run_chi_cho_chung_tu_da_xong(aws, started_executions):
    project_id = make_project()
    da_xong, moi, tung_loi = add_documents(project_id, "PO.pdf", "INV.pdf", "BB.pdf")
    for doc in (da_xong, moi, tung_loi):
        put_file(doc["s3_key"])
    mark_processed(da_xong["document_id"], PO_DATA)
    update_document(
        tung_loi["document_id"], status="FAILED", step="ocr", step_status="failed", error="OCR sập"
    )

    status, _ = call(
        "POST",
        f"/projects/{project_id}/process",
        {
            "document_ids": [da_xong["document_id"], moi["document_id"], tung_loi["document_id"]],
            "force": True,
        },
    )

    assert status == 202
    assert _doc(da_xong["document_id"])["status_before_run"] == "VALIDATED"
    assert _doc(moi["document_id"]).get("status_before_run") is None
    assert _doc(tung_loi["document_id"]).get("status_before_run") is None


def _project_dang_chay(*file_names: str) -> tuple[str, str, list[dict]]:
    project_id = make_project()
    docs = add_documents(project_id, *file_names)
    for doc in docs:
        put_file(doc["s3_key"])
    status, body = call("POST", f"/projects/{project_id}/process")
    assert status == 202
    return project_id, body["run_id"], docs


def test_dung_khi_khong_co_run_tra_409(aws):
    project_id = make_project()

    status, _ = call("POST", f"/projects/{project_id}/process/stop")

    assert status == 409


def test_dung_dat_co_tren_run_va_ghi_audit(aws, started_executions, capsys):
    project_id, run_id, _ = _project_dang_chay("INV.pdf")
    capsys.readouterr()

    status, body = call(
        "POST",
        f"/projects/{project_id}/process/stop",
        claims={"cognito:username": "tri"},
    )

    assert status == 202
    assert body["run_id"] == run_id
    run = _run(run_id)
    assert run["cancel_requested_at"] == body["cancel_requested_at"]
    assert run["cancel_requested_by"] == "tri"
    assert run["status"] == "PROCESSING"
    (su_kien,) = audit_events(capsys, "PROCESS_STOP_REQUESTED")
    assert su_kien["actor"] == "tri"
    assert su_kien["detail"]["run_id"] == run_id


def test_dung_lan_hai_khong_doi_gi_va_khong_ghi_audit_them(aws, started_executions, capsys):
    project_id, _, _ = _project_dang_chay("INV.pdf")
    _, lan_mot = call("POST", f"/projects/{project_id}/process/stop")
    capsys.readouterr()

    status, lan_hai = call("POST", f"/projects/{project_id}/process/stop")

    assert status == 202
    assert lan_hai["cancel_requested_at"] == lan_mot["cancel_requested_at"]
    assert audit_events(capsys, "PROCESS_STOP_REQUESTED") == []


def test_dung_khi_run_chua_co_record_tra_409_va_khong_sinh_record_ma(aws):
    project_id = make_project()
    update_item(
        PROJECTS_TABLE, {"project_id": project_id}, {"processing_run_id": "run-chua-ghi"}
    )

    status, _ = call("POST", f"/projects/{project_id}/process/stop")

    assert status == 409
    assert _run("run-chua-ghi") is None


def test_dung_giua_chung_qua_pipeline_cuc_bo(aws, started_executions, monkeypatch):
    from devserver import pipeline

    project_id, run_id, docs = _project_dang_chay("A.pdf", "B.pdf", "C.pdf")
    ocr_da_goi, gemini_da_goi = [], []

    def ocr_roi_bam_dung(name, content, mime_type, s3_key=None):
        ocr_da_goi.append(s3_key)
        call("POST", f"/projects/{project_id}/process/stop")
        return OCR_GIA

    def gemini(ocr_json):
        gemini_da_goi.append(1)
        return dict(GEMINI_GIA)

    monkeypatch.setattr("common.ocr_engines.run", ocr_roi_bam_dung)
    monkeypatch.setattr("workers.extract.extract_with_gemini", gemini)

    pipeline.run_local(started_executions[0]["payload"])

    assert len(ocr_da_goi) == 1
    assert gemini_da_goi == []
    assert _run(run_id)["status"] == "CANCELLED"
    project = _project(project_id)
    assert "processing_run_id" not in project
    assert "latest_reconciliation_id" not in project
    for doc in docs:
        assert _doc(doc["document_id"])["status"] == "PENDING"

    status, _ = call("POST", f"/projects/{project_id}/process")
    assert status == 202
