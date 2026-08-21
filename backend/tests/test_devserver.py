"""Dev server phải chạy đúng luồng mà state machine thật định nghĩa.

Rủi ro cần chặn: ai đó sửa statemachine.asl.json mà quên sửa dev server, dẫn
tới dev chạy một đằng cloud chạy một nẻo. Test này bắt lỗi đó offline.
"""

import json
import pathlib

import pytest

from devserver import bootstrap
from devserver.pipeline import STATE_TO_WORKER, build_plan, load_asl


def task_states(states: dict) -> set[str]:
    return {name for name, s in states.items() if s.get("Type") == "Task"}


def test_moi_task_state_trong_asl_deu_co_worker():
    asl = load_asl()
    inner = asl["States"]["ProcessDocuments"]["ItemProcessor"]["States"]
    thieu = (task_states(asl["States"]) | task_states(inner)) - set(STATE_TO_WORKER)
    assert not thieu, f"ASL có Task state chưa có worker trong dev server: {thieu}"


def test_thu_tu_buoc_lay_tu_asl_chu_khong_hardcode():
    plan = build_plan()
    assert plan["per_document"] == ["Ocr", "Extract", "Validate"]
    assert plan["after_map"] == ["Reconcile"]
    assert plan["run_failed"] == "MarkRunFailed"


def test_moi_buoc_deu_co_nhanh_catch():
    plan = build_plan()
    for state in plan["per_document"]:
        assert plan["catch_of"].get(state), f"{state} thiếu Catch trong ASL"


def test_step_label_lay_dung_tu_parameters_cua_asl():
    plan = build_plan()
    assert plan["step_of"] == {"Ocr": "ocr", "Extract": "extract", "Validate": "validate"}


def test_bao_loi_ngay_neu_asl_them_state_la():
    asl = load_asl()
    asl["States"]["ProcessDocuments"]["ItemProcessor"]["States"]["Classify"] = {
        "Type": "Task",
        "Resource": "arn:aws:lambda:x",
        "End": True,
    }
    with pytest.raises(RuntimeError, match="Classify"):
        build_plan(asl)


def test_bang_dinh_nghia_dung_chung_khop_voi_moi_truong():
    import os

    names = {spec["env"] for spec in bootstrap.TABLE_DEFINITIONS}
    assert names == {
        "PROJECTS_TABLE",
        "DOCUMENTS_TABLE",
        "RUNS_TABLE",
        "RECONCILIATIONS_TABLE",
        "AUDIT_LOG_TABLE",
    }
    for spec in bootstrap.TABLE_DEFINITIONS:
        assert os.environ.get(spec["env"]), f"conftest chưa đặt {spec['env']}"


def test_documents_co_du_hai_gsi():
    spec = next(s for s in bootstrap.TABLE_DEFINITIONS if s["env"] == "DOCUMENTS_TABLE")
    assert {i["IndexName"] for i in spec["indexes"]} == {
        "project_id-index",
        "po_number-index",
    }


def test_event_dung_hinh_dang_ma_api_handler_mong_doi():
    from api.handler import lambda_handler

    event = {
        "requestContext": {"http": {"method": "GET"}},
        "rawPath": "/khong-ton-tai",
        "body": None,
    }
    result = lambda_handler(event, None)
    assert result["statusCode"] == 404
    assert json.loads(result["body"])["error"]


def test_khong_con_duong_nao_chay_bang_ai_gia():
    """Dev server chỉ được có MỘT chế độ: AI thật.

    Dữ liệu mẫu nhìn y hệt lỗi hệ thống. Test này chặn việc ai đó thêm lại một
    chế độ dự phòng "cho tiện" rồi quên mất mình đang xem dữ liệu bịa.
    """
    import devserver.__main__ as entry

    assert not hasattr(entry, "load_real_ai_env")
    for name in ("fake_ai", "replay_ocr", "minipdf", "seed"):
        assert not (pathlib.Path(entry.__file__).parent / f"{name}.py").exists(),             f"devserver/{name}.py phải bị xoá"


def test_thieu_credential_thi_thoat_chu_khong_chay_tiep(monkeypatch):
    import devserver.__main__ as entry

    for name in ("DOCAI_PROJECT", "DOCAI_OCR_PROCESSOR_ID", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit) as exc:
        entry.setup_ai("dococr")
    assert exc.value.code == 2


def test_moi_processor_deu_co_don_gia_di_kem():
    """Processor và đơn giá phải nằm chung một chỗ.

    Tách ra là chỗ đã sai một lần: ước tính chi phí lệch 20 lần vì lấy đơn giá
    Form Parser cho Enterprise Document OCR.
    """
    import devserver.__main__ as entry

    for name, spec in entry.PROCESSORS.items():
        assert spec["env"] and spec["label"]
        assert float(spec["usd_per_page"]) > 0, name
    assert float(entry.PROCESSORS["dococr"]["usd_per_page"]) == 0.0015
    assert float(entry.PROCESSORS["formparser"]["usd_per_page"]) == 0.030


def test_setup_ai_dat_dung_processor_va_don_gia(monkeypatch):
    import devserver.__main__ as entry

    monkeypatch.setenv("DOCAI_PROJECT", "du-an-gia-lap")
    monkeypatch.setenv("DOCAI_OCR_PROCESSOR_ID", "proc-ocr-123")
    monkeypatch.setenv("GEMINI_API_KEY", "khoa-gia-lap")
    monkeypatch.delenv("DOCAI_PROCESSOR_ID", raising=False)

    entry.setup_ai("dococr")
    import os

    assert os.environ["DOCAI_PROCESSOR_ID"] == "proc-ocr-123"
    assert os.environ["DOCAI_USD_PER_PAGE"] == "0.0015"
    assert os.environ["DOCAI_PROCESSOR_LABEL"] == "documentai-enterprise-document-ocr"
