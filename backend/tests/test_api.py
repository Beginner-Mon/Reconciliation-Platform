import json

from api.handler import lambda_handler


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    event = {
        "requestContext": {"http": {"method": method}},
        "rawPath": path,
        "body": json.dumps(body) if body is not None else None,
    }
    response = lambda_handler(event, None)
    return response["statusCode"], json.loads(response["body"])


def put_file(s3_key: str, content: bytes = b"%PDF-1.4 fake") -> None:
    from common.s3 import BUCKET, get_s3

    get_s3().put_object(Bucket=BUCKET, Key=s3_key, Body=content)


def make_project(name: str = "Gói thầu A") -> str:
    status, body = call("POST", "/projects", {"name": name})
    assert status == 201
    return body["project_id"]


def add_documents(project_id: str, *file_names: str) -> list[dict]:
    status, body = call(
        "POST",
        f"/projects/{project_id}/documents",
        {"files": [{"file_name": name} for name in file_names]},
    )
    assert status == 201
    return body["documents"]


def mark_processed(document_id: str, data: dict) -> None:
    from common import update_document

    update_document(
        document_id,
        status="VALIDATED",
        step="validate",
        step_status="done",
        document_type=data["document_type"],
        extraction=data,
        validation={"valid": True, "schema_errors": [], "rule_errors": []},
        **({"po_number": data["po_number"]} if data.get("po_number") else {}),
    )


PO_DATA = {
    "document_type": "purchase_order",
    "po_number": "PO-2026-001",
    "po_date": "2026-08-01",
    "vendor": "ABC Technology",
    "currency": "VND",
    "items": [{"item_name": "Laptop Dell XPS", "quantity": 100, "unit_price": 1250000}],
    "total_amount": 125000000,
}

INVOICE_DATA = {
    "document_type": "invoice",
    "invoice_number": "INV-001",
    "invoice_date": "2026-08-05",
    "vendor": "ABC Technology",
    "currency": "VND",
    "po_number": "PO-2026-001",
    "items": [{"item_name": "Laptop Dell XPS", "quantity": 100, "unit_price": 1250000}],
    "total_amount": 125000000,
}


def test_tao_project_va_xin_presigned_url(aws):
    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf", "INV-001.pdf")

    assert len(created) == 2
    # Presigned POST: có url + fields để dựng FormData, KHÔNG phải upload_url.
    assert all(d["upload"]["url"] for d in created)
    assert all("policy" in d["upload"]["fields"] for d in created)
    assert all(d["upload"]["fields"]["Content-Type"] == "application/pdf" for d in created)
    assert all(d["max_bytes"] == 20 * 1024 * 1024 for d in created)
    assert all(d["s3_key"].startswith(f"projects/{project_id}/uploads/") for d in created)

    status, body = call("GET", f"/projects/{project_id}")
    assert status == 200
    assert body["project"]["document_count"] == 2
    assert body["progress"]["progress_percent"] == 0


def test_loai_file_khong_ho_tro_bi_tu_choi(aws):
    project_id = make_project()
    status, body = call(
        "POST", f"/projects/{project_id}/documents", {"files": [{"file_name": "hop_dong.docx"}]}
    )
    assert status == 400
    assert "không hỗ trợ" in body["error"]


def test_process_thieu_file_tren_s3_tra_400(aws, started_executions):
    project_id = make_project()
    add_documents(project_id, "PO-001.pdf")

    status, body = call("POST", f"/projects/{project_id}/process")
    assert status == 400
    assert "Chưa upload file" in body["error"]
    assert started_executions == []


def test_process_file_rong_tra_400(aws, started_executions):
    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf")
    put_file(created[0]["s3_key"], b"")

    status, body = call("POST", f"/projects/{project_id}/process")
    assert status == 400
    assert "rỗng" in body["error"]
    assert started_executions == []


def test_process_start_execution_va_ghi_run(aws, started_executions):
    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf", "INV-001.pdf")
    for document in created:
        put_file(document["s3_key"])

    status, body = call("POST", f"/projects/{project_id}/process")
    assert status == 202
    assert len(body["processing"]) == 2
    assert body["skipped"] == []
    assert len(started_executions) == 1
    assert started_executions[0]["name"] == body["run_id"]
    assert {d["document_id"] for d in started_executions[0]["payload"]["documents"]} == {
        d["document_id"] for d in created
    }


def test_goi_process_hai_lan_thi_lan_hai_tra_409(aws, started_executions):
    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf")
    put_file(created[0]["s3_key"])

    assert call("POST", f"/projects/{project_id}/process")[0] == 202
    status, body = call("POST", f"/projects/{project_id}/process")
    assert status == 409
    assert "đang chạy" in body["error"]
    assert len(started_executions) == 1


def test_doc_da_xu_ly_thi_bi_skip_va_khong_start_execution(aws, started_executions):
    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf", "INV-001.pdf")
    for document in created:
        put_file(document["s3_key"])
    mark_processed(created[0]["document_id"], PO_DATA)
    mark_processed(created[1]["document_id"], INVOICE_DATA)

    status, body = call("POST", f"/projects/{project_id}/process")

    assert status == 200
    assert body["processing"] == []
    assert {s["reason"] for s in body["skipped"]} == {"đã xử lý xong"}
    assert started_executions == []
    assert body["reconciliation"]["discrepancy_count"] == 0


def test_them_doc_moi_chi_xu_ly_doc_moi(aws, started_executions):
    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf", "INV-001.pdf")
    for document in created:
        put_file(document["s3_key"])
    mark_processed(created[0]["document_id"], PO_DATA)
    mark_processed(created[1]["document_id"], INVOICE_DATA)

    moi = add_documents(project_id, "BBNT-001.pdf")
    put_file(moi[0]["s3_key"])

    status, body = call("POST", f"/projects/{project_id}/process")

    assert status == 202
    assert [d["document_id"] for d in body["processing"]] == [moi[0]["document_id"]]
    assert {s["document_id"] for s in body["skipped"]} == {
        created[0]["document_id"],
        created[1]["document_id"],
    }
    payload_ids = [d["document_id"] for d in started_executions[0]["payload"]["documents"]]
    assert payload_ids == [moi[0]["document_id"]]


def test_khong_co_ai_call_moi_cho_doc_da_xu_ly(aws, started_executions):
    from common import AUDIT_LOG_TABLE
    from common.dynamodb import scan_table

    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf", "INV-001.pdf")
    for document in created:
        put_file(document["s3_key"])
    mark_processed(created[0]["document_id"], PO_DATA)
    mark_processed(created[1]["document_id"], INVOICE_DATA)

    moi = add_documents(project_id, "BBNT-001.pdf")
    put_file(moi[0]["s3_key"])
    call("POST", f"/projects/{project_id}/process")

    da_xu_ly = {created[0]["document_id"], created[1]["document_id"]}
    ai_calls = [
        item
        for item in scan_table(AUDIT_LOG_TABLE)
        if item["action"] == "AI_CALL" and item["entity_id"] in da_xu_ly
    ]
    assert ai_calls == []


def test_force_van_bo_qua_doc_da_sua_tay(aws, started_executions):
    from common import update_document

    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf", "INV-001.pdf")
    for document in created:
        put_file(document["s3_key"])
    mark_processed(created[0]["document_id"], PO_DATA)
    mark_processed(created[1]["document_id"], INVOICE_DATA)
    update_document(created[0]["document_id"], edited_fields=["vendor"])

    status, body = call("POST", f"/projects/{project_id}/process", {"force": True})

    assert status == 202
    assert {s["document_id"] for s in body["skipped"]} == {created[0]["document_id"]}
    assert "sửa tay" in body["skipped"][0]["reason"]
    assert {d["document_id"] for d in body["processing"]} == {created[1]["document_id"]}


def test_force_edited_thi_xu_ly_ca_doc_da_sua_tay(aws, started_executions):
    from common import update_document

    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf")
    put_file(created[0]["s3_key"])
    mark_processed(created[0]["document_id"], PO_DATA)
    update_document(created[0]["document_id"], edited_fields=["vendor"])

    status, body = call(
        "POST", f"/projects/{project_id}/process", {"force": True, "force_edited": True}
    )
    assert status == 202
    assert [d["document_id"] for d in body["processing"]] == [created[0]["document_id"]]


def test_reconcile_endpoint_chay_doc_lap(aws):
    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf", "INV-001.pdf")
    mark_processed(created[0]["document_id"], PO_DATA)
    mark_processed(created[1]["document_id"], {**INVOICE_DATA, "vendor": "XYZ Corp"})

    status, body = call("POST", f"/projects/{project_id}/reconcile")
    assert status == 200
    assert body["discrepancy_count"] >= 1

    status, detail = call("GET", f"/reconciliations/{body['reconciliation_id']}")
    assert status == 200
    assert any(d["rule_id"] == "agree_vendor" for d in detail["discrepancies"])


def test_sua_tay_thi_doi_chieu_chay_lai_ngay(aws):
    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf", "INV-001.pdf")
    mark_processed(created[0]["document_id"], PO_DATA)
    mark_processed(created[1]["document_id"], {**INVOICE_DATA, "vendor": "XYZ Corp"})
    call("POST", f"/projects/{project_id}/reconcile")

    status, body = call(
        "PATCH",
        f"/projects/{project_id}/documents/{created[1]['document_id']}",
        {"fields": {"vendor": "ABC Technology"}, "reviewer": "tri"},
    )

    assert status == 200
    assert body["validation"]["valid"] is True
    assert body["document"]["edited_fields"] == ["vendor"]
    assert body["reconciliation"]["discrepancy_count"] == 0


def test_approve_reconciliation(aws):
    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf", "INV-001.pdf")
    mark_processed(created[0]["document_id"], PO_DATA)
    mark_processed(created[1]["document_id"], INVOICE_DATA)
    _, recon = call("POST", f"/projects/{project_id}/reconcile")

    status, body = call(
        "POST", f"/reconciliations/{recon['reconciliation_id']}/approve", {"reviewer": "tri"}
    )
    assert status == 200
    assert body["status"] == "APPROVED"

    status, body = call("POST", f"/reconciliations/{recon['reconciliation_id']}/approve")
    assert status == 409


def test_xem_ocr_tho_cua_document(aws):
    from common import update_document, write_json

    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf")
    document_id = created[0]["document_id"]

    ocr_key = f"projects/{project_id}/ocr/{document_id}.json"
    write_json(
        ocr_key,
        {
            "text": "ĐƠN ĐẶT HÀNG\nNhà cung cấp: ABC Technology",
            "pages": [{"page_number": 1, "mean_token_confidence": 0.94, "tables": []}],
        },
    )
    update_document(document_id, ocr_s3_key=ocr_key)

    status, body = call("GET", f"/projects/{project_id}/documents/{document_id}/ocr")
    assert status == 200
    assert "ABC Technology" in body["text"]
    assert body["pages"][0]["mean_token_confidence"] == 0.94
    assert body["file_name"] == "PO-001.pdf"


def test_xem_ocr_khi_chua_xu_ly_tra_404(aws):
    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf")

    status, body = call(
        "GET", f"/projects/{project_id}/documents/{created[0]['document_id']}/ocr"
    )
    assert status == 404
    assert "chưa chạy OCR" in body["error"]


def test_xem_ocr_cua_document_khong_thuoc_project_tra_404(aws):
    project_a = make_project("A")
    project_b = make_project("B")
    created = add_documents(project_a, "PO-001.pdf")

    status, _ = call(
        "GET", f"/projects/{project_b}/documents/{created[0]['document_id']}/ocr"
    )
    assert status == 404


def test_project_khong_ton_tai_tra_404(aws):
    status, body = call("GET", "/projects/prj-khong-co")
    assert status == 404


def test_route_khong_ton_tai_tra_404(aws):
    status, body = call("GET", "/khong-co-gi")
    assert status == 404
