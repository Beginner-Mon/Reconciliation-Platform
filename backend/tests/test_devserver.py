"""Dev server phải chạy đúng luồng mà state machine thật định nghĩa.

Rủi ro cần chặn: ai đó sửa statemachine.asl.json mà quên sửa dev server, dẫn
tới dev chạy một đằng cloud chạy một nẻo. Test này bắt lỗi đó offline.
"""

import json

import pytest

from devserver import bootstrap, fake_ai
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


def test_ai_gia_sinh_bo_chung_tu_khop_nhau():
    from core import run_crosscheck, validate_document

    documents = []
    for index, (name, content) in enumerate(fake_ai.sample_files().items()):
        extracted = fake_ai.fake_extract(fake_ai.fake_ocr(content))
        data = {**extracted["data"], "document_type": extracted["document_type"]}
        assert validate_document(data)["valid"], f"{name} không qua validate"
        documents.append({"document_id": f"doc-{index}", "data": data})

    assert {d["data"]["document_type"] for d in documents} == {
        "purchase_order",
        "invoice",
        "acceptance_record",
    }

    result = run_crosscheck(documents)
    rules = {d["rule_id"] for d in result["discrepancies"]}
    assert "line_item_unit_price" in rules
    assert "invoiced_over_accepted" in rules, "thiếu mâu thuẫn 3 chiều để demo"
    assert len(result["groups"]) == 1, "3 chứng từ phải cùng một giao dịch"


def test_ai_gia_nem_loi_theo_tu_khoa():
    with pytest.raises(RuntimeError):
        fake_ai.fake_ocr(b"__LOI__ file hong")


def test_ai_gia_tat_dinh():
    content = b"noi dung khong co tu khoa nao"
    assert fake_ai.detect_type(content) == fake_ai.detect_type(content)


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
