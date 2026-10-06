from copy import deepcopy

import pytest

from core import validate_document, run_crosscheck


def document():
    return {
        "document_type": "invoice", "role": "billing",
        "subtotal": 570, "tax_amount": 57, "total_amount": 677,
        "other_fields": {"Shipping": "50", "Phụ phí bất kỳ": "10"},
        "tables": [{"columns": [
            {"header": "Tên", "role": "item_name"},
            {"header": "SL", "role": "quantity"},
            {"header": "Giá", "role": "unit_price"},
            {"header": "Tiền", "role": "amount"},
        ], "rows": [{"Tên": "Hàng", "SL": 1, "Giá": 570, "Tiền": 570}]}],
    }


def test_arithmetic_flags_do_not_block_reconciliation():
    data = document()
    result = validate_document(data)
    assert result["valid"]
    assert result["rule_errors"] == []
    assert any(f["code"] == "total_formula" for f in result["flags"])
    assert all("?" not in f["message"] for f in result["flags"])
    assert result["model"].other_fields == data["other_fields"]
    checked = run_crosscheck([{"document_id": "d", "data": data}])
    assert checked["checked_document_ids"] == ["d"]
    assert checked["validation_flags"]["d"]


@pytest.mark.parametrize("field,value", [
    ("subtotal", -5), ("seller_tax_code", "abc"),
    ("doc_date", "2099-01-01"), ("currency", "XXX"),
    ("doc_number", "số / bất kỳ"),
])
def test_business_constraints_are_flags(field, value):
    data = document()
    data[field] = value
    result = validate_document(data)
    assert result["valid"]
    assert any(f["field"] == field for f in result["flags"])


def test_decimal_row_and_missing_subtotal():
    data = document()
    data.pop("subtotal")
    data["tables"][0]["rows"] = [{"Tên": "Hàng", "SL": 3, "Giá": 0.1, "Tiền": 0.3}]
    result = validate_document(data)
    assert result["valid"]
    assert not any(f["code"] in ("row_amount", "total_formula") for f in result["flags"])
    assert any(f["code"] == "insufficient_data" for f in result["flags"])


def test_limits_and_incomplete_data_do_not_create_false_totals():
    data = document()
    data["tables"][0]["rows"] = [{"Tên": "x" * 500, "SL": 1, "Tiền": 1}] * 500
    result = validate_document(data)
    assert len(result["model"].tables[0].rows) == 500
    assert len(result["model"].tables[0].rows[0]["Tên"]) == 500
    assert not result["warnings"]
    data["tables"][0]["rows"].append({"Tên": "extra", "SL": 1, "Tiền": 1})
    result = validate_document(data)
    assert result["valid"] and result["warnings"]
    assert result["comparison_incomplete"]
    assert not any(f["code"] == "subtotal_formula" for f in result["flags"])


@pytest.mark.parametrize("bad", [None, [], {"tables": [None]}, {"tables": [{"columns": [], "rows": [42]}]}])
def test_malformed_structure_is_a_processing_error(bad):
    data = bad if not isinstance(bad, dict) else {**document(), **bad}
    result = validate_document(data)
    assert not result["valid"]
    assert result["schema_errors"]


def test_legacy_migration_preserves_other_fields_and_explicit_amount():
    data = {"document_type": "invoice", "other_fields": {"Shipping": "50"},
            "shipping_amount": 50,
            "items": [{"item_name": "Hàng", "quantity": 2, "unit_price": 10, "amount": 19}]}
    original = deepcopy(data)
    result = validate_document(data)
    assert result["model"].other_fields["Shipping"] == "50"
    assert result["model"].tables[0].rows[0]["amount"] == 19
    assert data == original


def test_large_document_roundtrip_and_small_replacement(aws):
    from common.dynamodb import DOCUMENTS_TABLE, get_item, get_table, put_item, query_documents_by_project, update_document
    from common.s3 import read_json
    put_item(DOCUMENTS_TABLE, {"document_id": "d", "project_id": "p"})
    data = document()
    data["other_fields"] = {str(i): "ữ" * 500 for i in range(400)}
    update_document("d", extraction=data)
    stored = get_table(DOCUMENTS_TABLE).get_item(Key={"document_id": "d"})["Item"]
    assert "extraction" not in stored
    assert read_json(stored["document_payload_s3_key"])["extraction"] == data
    assert get_item(DOCUMENTS_TABLE, {"document_id": "d"})["extraction"] == data
    assert query_documents_by_project("p")[0]["extraction"] == data
    update_document("d", extraction=document())
    assert get_item(DOCUMENTS_TABLE, {"document_id": "d"})["extraction"] == document()


def test_worker_and_edit_preserve_flags(aws):
    from common.dynamodb import DOCUMENTS_TABLE, get_item, put_item
    from workers.validate import lambda_handler
    from api.review import edit_document
    put_item(DOCUMENTS_TABLE, {"document_id": "d", "project_id": "p", "extraction": document()})
    assert lambda_handler({"document_id": "d", "project_id": "p"}, None)["status"] == "VALIDATED"
    assert get_item(DOCUMENTS_TABLE, {"document_id": "d"})["validation"]["flags"]
    edit_document({"document_id": "d", "project_id": "p"}, {"fields": {"total_amount": 627}}, "tri")
    saved = get_item(DOCUMENTS_TABLE, {"document_id": "d"})
    assert saved["status"] == "VALIDATED"
    assert not any(f["code"] == "total_formula" for f in saved["validation"]["flags"])


def test_sua_dung_truong_bao_loi_thi_tat_co(aws):
    from common.dynamodb import DOCUMENTS_TABLE, get_item, put_item
    from api.review import edit_document
    van_de = [
        {"field": "doc_date", "value": "28/12/2024", "reason": "x"},
        {"field": "total_amount", "value": "3.734.640", "reason": "y"},
    ]
    put_item(DOCUMENTS_TABLE, {"document_id": "d", "project_id": "p", "extraction": document(), "format_issues": van_de})
    edit_document({"document_id": "d", "project_id": "p"}, {"fields": {"doc_date": "2024-12-28"}}, "tri")
    saved = get_item(DOCUMENTS_TABLE, {"document_id": "d"})
    assert saved["status"] == "VALIDATED"
    co = saved["validation"]["flags"]
    assert not any(f["code"] == "ai_format" and f["field"] == "doc_date" for f in co)
    assert any(f["code"] == "ai_format" and f["field"] == "total_amount" for f in co)


def test_sua_tay_sai_kieu_khong_duoc_cuu(aws):
    from common.dynamodb import DOCUMENTS_TABLE, get_item, put_item
    from api.review import edit_document
    put_item(DOCUMENTS_TABLE, {"document_id": "d", "project_id": "p", "extraction": document()})
    edit_document({"document_id": "d", "project_id": "p"}, {"fields": {"doc_date": "28/12/2024"}}, "tri")
    saved = get_item(DOCUMENTS_TABLE, {"document_id": "d"})
    assert saved["status"] == "FAILED"


def test_truncated_group_does_not_report_missing_rows():
    data = document()
    data["tables"][0]["rows"] *= 501
    other = document()
    result = run_crosscheck([{"document_id": "a", "data": data}, {"document_id": "b", "data": other}])
    assert set(result["checked_document_ids"]) == {"a", "b"}
    assert {d["rule_id"] for d in result["discrepancies"]} == {"comparison_incomplete"}


def test_numeric_strings_from_manual_edit_do_not_break_rules():
    data = document()
    data["tables"][0]["rows"][0].update({"SL": "2.5", "Giá": "228", "Tiền": "570"})
    result = run_crosscheck([{"document_id": "a", "data": data}, {"document_id": "b", "data": document()}])
    assert len(result["checked_document_ids"]) == 2


def test_negative_quantity_flags_do_not_disable_comparison():
    data = document()
    data["tables"][0]["rows"][0]["SL"] = -1
    result = run_crosscheck([{"document_id": "a", "data": data}, {"document_id": "b", "data": document()}])
    assert len(result["checked_document_ids"]) == 2
    assert any(f["code"] == "quantity" for f in result["validation_flags"]["a"])
    assert not any(d["rule_id"] == "comparison_incomplete" for d in result["discrepancies"])


def test_extract_worker_preserves_unknown_fields(aws, monkeypatch):
    from common.dynamodb import DOCUMENTS_TABLE, get_item, put_item
    from common.s3 import write_json, read_json
    from workers.extract import lambda_handler
    put_item(DOCUMENTS_TABLE, {"document_id": "d", "project_id": "p"})
    write_json("ocr.json", {"text": "Shipping 50", "pages": []})
    monkeypatch.setattr("workers.extract.extract_with_gemini", lambda ocr: {"document_type": "invoice", "data": document()})
    lambda_handler({"document_id": "d", "project_id": "p", "ocr_s3_key": "ocr.json"}, None)
    saved = get_item(DOCUMENTS_TABLE, {"document_id": "d"})
    assert saved["extraction"]["other_fields"] == document()["other_fields"]
    assert read_json(saved["extraction_s3_key"])["data"]["other_fields"] == document()["other_fields"]


def test_large_payload_write_failure_keeps_previous_version(aws, monkeypatch):
    import common.dynamodb as db
    db.put_item(db.DOCUMENTS_TABLE, {"document_id": "d", "project_id": "p"})
    data = document()
    data["other_fields"] = {str(i): "ữ" * 500 for i in range(400)}
    db.update_document("d", extraction=data)

    def fail(*args, **kwargs):
        raise RuntimeError("DynamoDB unavailable")

    monkeypatch.setattr(db, "update_item", fail)
    with pytest.raises(RuntimeError):
        db.update_document("d", extraction=document())
    assert db.get_item(db.DOCUMENTS_TABLE, {"document_id": "d"})["extraction"] == data


def test_schema_failure_is_stored_for_review(aws):
    from common.dynamodb import DOCUMENTS_TABLE, get_item, put_item
    from workers.validate import lambda_handler
    data = document()
    data["tables"] = [None]
    put_item(DOCUMENTS_TABLE, {"document_id": "d", "project_id": "p", "extraction": data})
    result = lambda_handler({"document_id": "d", "project_id": "p"}, None)
    assert result["status"] == "FAILED"
    saved = get_item(DOCUMENTS_TABLE, {"document_id": "d"})
    assert saved["validation"]["schema_errors"]
    assert saved["extraction"] == data
