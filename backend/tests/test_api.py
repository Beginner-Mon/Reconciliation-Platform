import json

import pytest

from api.handler import lambda_handler


def call(
    method: str,
    path: str,
    body: dict | None = None,
    claims: dict | None = None,
) -> tuple[int, dict]:
    event: dict = {
        "requestContext": {"http": {"method": method}},
        "rawPath": path,
        "body": json.dumps(body) if body is not None else None,
    }
    if claims is not None:
        event["requestContext"]["authorizer"] = {"jwt": {"claims": dict(claims)}}
    response = lambda_handler(event, None)
    return response["statusCode"], json.loads(response["body"])


def put_file(s3_key: str, content: bytes | None = None) -> None:
    """Mặc định mỗi file một nội dung KHÁC nhau.

    Trước đây mọi file dùng chung `b"%PDF-1.4 fake"`. Hai chứng từ nghiệp vụ khác
    nhau không bao giờ trùng từng byte, nên fixture đó phi thực tế — và nó làm
    kiểm trùng nội dung tưởng cả project là một file upload đi upload lại.
    Test nào cần trùng thật thì truyền `content` giống nhau một cách tường minh.
    """
    from common.s3 import BUCKET, get_s3

    if content is None:
        content = b"%PDF-1.4 " + s3_key.encode()
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
    from common.dynamodb import update_document

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


def test_khong_co_ai_call_moi_cho_doc_da_xu_ly(aws, started_executions, capsys):
    from tests.test_audit import audit_events

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
        item for item in audit_events(capsys, "AI_CALL") if item["entity_id"] in da_xu_ly
    ]
    assert ai_calls == []


def test_force_van_bo_qua_doc_da_sua_tay(aws, started_executions):
    from common.dynamodb import update_document

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
    from common.dynamodb import update_document

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


# --- Chọn engine OCR cho từng lần chạy -------------------------------------
#
# Trước đây engine là biến môi trường của tiến trình, cố định cho cả một
# deployment. Không so được hai engine trên CÙNG một chứng từ, mà đó lại đúng là
# câu hỏi cần trả lời: engine nào đọc tiếng Việt tốt hơn trên tờ hoá đơn này.


def test_chay_lai_dung_MOT_chung_tu_voi_engine_da_chon(aws, started_executions):
    """Đây là luồng của nút "Chạy lại với…" trên giao diện."""
    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf", "INV-001.pdf")
    for document in created:
        put_file(document["s3_key"])
    mark_processed(created[0]["document_id"], PO_DATA)
    mark_processed(created[1]["document_id"], INVOICE_DATA)

    status, body = call(
        "POST",
        f"/projects/{project_id}/process",
        {"document_ids": [created[0]["document_id"]], "force": True, "engine": "dococr"},
    )

    assert status == 202
    assert [d["document_id"] for d in body["processing"]] == [created[0]["document_id"]]
    assert started_executions[0]["payload"]["ocr_engine"] == "dococr"


def test_khong_khai_engine_thi_dung_mac_dinh(aws, started_executions):
    """Payload phải LUÔN mang khoá `ocr_engine`.

    ASL `ItemSelector` khai `"ocr_engine.$": "$.ocr_engine"` — thiếu khoá là
    States.Runtime, cả run chết chứ không phải một chứng từ.
    """
    from common import ocr_engines

    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf")
    put_file(created[0]["s3_key"])

    call("POST", f"/projects/{project_id}/process")

    assert started_executions[0]["payload"]["ocr_engine"] == ocr_engines.DEFAULT_ENGINE


def test_engine_ngoai_danh_sach_app_tra_400(aws, started_executions):
    """Server là chốt chặn DUY NHẤT cho tên engine.

    Giao diện khai cứng hai tên, nhưng `/process` là API công khai — không thể
    tin vào phía gọi. Kiểm ở đây phải bắt cả ba loại:

      formparser   có thật trong bảng, nhưng app không cho chọn
      textrackt    gõ sai
      rác          giá trị bịa

    Im lặng rơi về engine mặc định là kiểu hỏng tệ nhất: chạy trót lọt, tính
    tiền theo engine này, ghi audit theo engine kia.
    """
    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf")
    put_file(created[0]["s3_key"])

    for ten in ("formparser", "layout", "textract-analyze", "textrackt", "DOCOCR", "1"):
        status, body = call(
            "POST", f"/projects/{project_id}/process", {"engine": ten}
        )

        assert status == 400, f"engine {ten!r} phải bị từ chối"
        assert ten in body["error"]
        # Danh sách hợp lệ phải nằm trong thông báo, nếu không người gọi mù.
        assert "textract, dococr" in body["error"]

    assert started_executions == []


def test_engine_duoc_ghi_vao_audit(aws, started_executions, capsys):
    """Không ghi thì vài tuần sau không ai biết con số đo được là của engine nào."""
    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf")
    put_file(created[0]["s3_key"])

    call("POST", f"/projects/{project_id}/process", {"engine": "dococr"})

    assert audit_records(capsys, "PROCESS_RUN")[0]["detail"]["ocr_engine"] == "dococr"


def test_khong_co_endpoint_liet_ke_engine(aws):
    """Hai hằng số tĩnh không đáng một endpoint. Giao diện khai cứng hai tên;
    `test_routes.py` khoá chúng khớp với `APP_ENGINES`.

    Bỏ endpoint KHÔNG được làm yếu kiểm tra phía server — xem test dưới.
    """
    assert call("GET", "/ocr-engines")[0] == 404


# --- Audit cho quyết định idempotent ---------------------------------------
#
# Tính idempotent tiết kiệm tiền bằng cách âm thầm KHÔNG làm gì. Không ghi lại
# thì vài tuần sau không ai trả lời được "vì sao chứng từ này dữ liệu vẫn cũ",
# và tệ hơn: `force_edited` cho AI ghi đè công review mà không để lại vết nào.


def audit_records(capsys, action: str) -> list[dict]:
    from tests.test_audit import audit_events

    return audit_events(capsys, action)


def test_process_ghi_audit_kem_ly_do_skip(aws, started_executions, capsys):
    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf", "INV-001.pdf")
    for document in created:
        put_file(document["s3_key"])
    mark_processed(created[0]["document_id"], PO_DATA)
    mark_processed(created[1]["document_id"], INVOICE_DATA)

    call("POST", f"/projects/{project_id}/process")

    runs = audit_records(capsys, "PROCESS_RUN")
    assert len(runs) == 1
    detail = runs[0]["detail"]
    assert runs[0]["entity_id"] == project_id
    assert detail["processed"] == []
    assert {s["document_id"] for s in detail["skipped"]} == {
        created[0]["document_id"],
        created[1]["document_id"],
    }
    assert all("đã xử lý xong" in s["reason"] for s in detail["skipped"])


def test_process_ghi_lai_co_force(aws, started_executions, capsys):
    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf")
    put_file(created[0]["s3_key"])
    mark_processed(created[0]["document_id"], PO_DATA)

    call("POST", f"/projects/{project_id}/process", {"force": True})

    detail = audit_records(capsys, "PROCESS_RUN")[0]["detail"]
    assert detail["force"] is True
    assert detail["run_id"]
    assert detail["processed"] == [created[0]["document_id"]]


def test_force_edited_ghi_vet_ghi_de_cong_review(aws, started_executions, capsys):
    """Thao tác phá huỷ duy nhất trong hệ thống phải có dấu vết riêng."""
    from common.dynamodb import update_document

    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf")
    put_file(created[0]["s3_key"])
    mark_processed(created[0]["document_id"], PO_DATA)
    update_document(
        created[0]["document_id"], edited_fields=["vendor"], edited_by="tri"
    )

    call(
        "POST", f"/projects/{project_id}/process", {"force": True, "force_edited": True}
    )

    overwritten = audit_records(capsys, "EDIT_OVERWRITTEN")
    assert len(overwritten) == 1
    assert overwritten[0]["entity_id"] == created[0]["document_id"]
    detail = overwritten[0]["detail"]
    assert detail["edited_fields"] == ["vendor"]
    assert detail["edited_by"] == "tri"
    assert overwritten[0]["project_id"] == project_id


def test_process_binh_thuong_khong_sinh_canh_bao_ghi_de(aws, started_executions, capsys):
    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf")
    put_file(created[0]["s3_key"])

    call("POST", f"/projects/{project_id}/process")

    assert audit_records(capsys, "EDIT_OVERWRITTEN") == []


# --- Upload trùng nội dung --------------------------------------------------
#
# Bấm upload hai lần sinh hai document_id khác nhau nhưng cùng một file. Trước
# đây cả hai đều bị OCR (trả tiền hai lần) rồi cộng vào nhau khi đối chiếu như
# thể là hai đợt giao hàng.

TRUNG = b"%PDF-1.4 cung mot file"


def test_upload_trung_file_thi_chi_xu_ly_mot_ban(aws, started_executions):
    project_id = make_project()
    created = add_documents(project_id, "INV-001.pdf", "INV-001-copy.pdf")
    for document in created:
        put_file(document["s3_key"], TRUNG)

    status, body = call("POST", f"/projects/{project_id}/process")

    assert status == 202
    assert [d["document_id"] for d in body["processing"]] == [created[0]["document_id"]]
    assert [s["document_id"] for s in body["skipped"]] == [created[1]["document_id"]]
    assert "trùng nội dung với INV-001.pdf" in body["skipped"][0]["reason"]
    # bản trùng KHÔNG được lọt vào Step Functions — đó là chỗ tốn tiền
    payload_ids = [d["document_id"] for d in started_executions[0]["payload"]["documents"]]
    assert payload_ids == [created[0]["document_id"]]


def test_file_khac_nhau_thi_khong_bi_coi_la_trung(aws, started_executions):
    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf", "INV-001.pdf")
    for document in created:
        put_file(document["s3_key"])

    status, body = call("POST", f"/projects/{project_id}/process")

    assert status == 202
    assert len(body["processing"]) == 2
    assert body["skipped"] == []


def _md5(content: bytes) -> str:
    """ETag của S3 cho upload một phần chính là md5 hex của nội dung."""
    import hashlib

    return hashlib.md5(content).hexdigest()


def test_upload_trung_bi_bat_o_ca_run_sau(aws, started_executions):
    """content_hash lưu lại nên run sau vẫn nhận ra, không chỉ trong một lần chạy."""
    from common.dynamodb import update_document

    project_id = make_project()
    dau = add_documents(project_id, "INV-001.pdf")
    put_file(dau[0]["s3_key"], TRUNG)
    mark_processed(dau[0]["document_id"], INVOICE_DATA)
    update_document(dau[0]["document_id"], content_hash=_md5(TRUNG))

    sau = add_documents(project_id, "INV-001-lai.pdf")
    put_file(sau[0]["s3_key"], TRUNG)
    status, body = call("POST", f"/projects/{project_id}/process")

    # mọi ứng viên đều bị loại nên không tạo run mới, chỉ đối chiếu lại
    assert status == 200
    ly_do = {s["document_id"]: s["reason"] for s in body["skipped"]}
    assert "trùng nội dung" in ly_do[sau[0]["document_id"]]
    assert "đã xử lý xong" in ly_do[dau[0]["document_id"]]
    assert started_executions == []


def test_chay_lai_chinh_no_khong_bi_coi_la_trung(aws, started_executions):
    """force=true trên cùng document: hash của nó khớp CHÍNH NÓ, không phải trùng."""
    from common.dynamodb import update_document

    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf")
    put_file(created[0]["s3_key"], TRUNG)
    mark_processed(created[0]["document_id"], PO_DATA)
    update_document(created[0]["document_id"], content_hash=_md5(TRUNG))

    status, body = call("POST", f"/projects/{project_id}/process", {"force": True})

    assert status == 202
    assert [d["document_id"] for d in body["processing"]] == [created[0]["document_id"]]
    assert body["skipped"] == []


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


def test_sua_tay_lam_bien_mat_mau_thuan_sau_khi_doi_chieu_lai(aws):
    """Sửa tay KHÔNG còn tự đối chiếu — nhưng bấm Đối chiếu lại thì mâu thuẫn
    do chính chỗ sửa gây ra phải biến mất.

    Trước đây PATCH tự chạy đối chiếu nên test này kiểm được ngay trong response.
    Giờ tách làm hai bước, vì đối chiếu không phải việc của thao tác review.
    """
    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf", "INV-001.pdf")
    mark_processed(created[0]["document_id"], PO_DATA)
    mark_processed(created[1]["document_id"], {**INVOICE_DATA, "vendor": "XYZ Corp"})

    truoc = call("POST", f"/projects/{project_id}/reconcile")[1]
    assert truoc["discrepancy_count"] > 0, "vendor lệch thì phải có mâu thuẫn"

    status, body = call(
        "PATCH",
        f"/projects/{project_id}/documents/{created[1]['document_id']}",
        {"fields": {"vendor": "ABC Technology"}, "reviewer": "tri"},
    )
    assert status == 200
    assert body["validation"]["valid"] is True
    assert body["document"]["edited_fields"] == ["vendor"]
    assert "reconciliation" not in body

    sau = call("POST", f"/projects/{project_id}/reconcile")[1]
    assert sau["discrepancy_count"] == 0
    assert sau["is_stale"] is False


def _reconciliation_id(project_id: str) -> str:
    return call("POST", f"/projects/{project_id}/reconcile")[1]["reconciliation_id"]


def _project_da_doi_chieu() -> str:
    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf", "INV-001.pdf")
    mark_processed(created[0]["document_id"], PO_DATA)
    mark_processed(created[1]["document_id"], INVOICE_DATA)
    return project_id


def test_duyet_va_tu_choi_dung_CHUNG_mot_endpoint(aws):
    """Duyệt và từ chối ghi cùng một bảng, cùng một shape, khác đúng một enum —
    không có side effect nào riêng nên không đáng tách làm hai route.

    Vết audit không mất gì: `log_review` đã ghi `decision` vào dòng audit.
    """
    for quyet_dinh in ("APPROVED", "REJECTED"):
        reconciliation_id = _reconciliation_id(_project_da_doi_chieu())

        status, body = call(
            "POST",
            f"/reconciliations/{reconciliation_id}/review",
            {"decision": quyet_dinh},
            claims={"cognito:username": "tri"},
        )

        assert status == 200
        assert body["status"] == quyet_dinh
        assert body["review"]["decision"] == quyet_dinh
        assert body["review"]["reviewer"] == "tri"


def test_review_lan_hai_tra_409(aws):
    reconciliation_id = _reconciliation_id(_project_da_doi_chieu())
    body = {"decision": "APPROVED"}

    assert call("POST", f"/reconciliations/{reconciliation_id}/review", body)[0] == 200
    assert call("POST", f"/reconciliations/{reconciliation_id}/review", body)[0] == 409


@pytest.mark.parametrize("decision", ["APPROVED", "REJECTED"])
def test_khong_review_dot_doi_chieu_rong(aws, capsys, decision):
    from common.dynamodb import RECONCILIATIONS_TABLE, get_item
    from test_audit import audit_events

    project_id = make_project()
    document = add_documents(project_id, "unknown.pdf")[0]
    mark_processed(document["document_id"], {"document_type": "unknown"})
    reconciliation_id = _reconciliation_id(project_id)
    key = {"reconciliation_id": reconciliation_id}
    before = get_item(RECONCILIATIONS_TABLE, key)
    assert before["document_ids"] == []
    assert before["status"] == "PENDING_REVIEW"

    status, body = call(
        "POST", f"/reconciliations/{reconciliation_id}/review", {"decision": decision}
    )

    assert status == 409
    assert "không có gì để duyệt" in body["error"]
    assert get_item(RECONCILIATIONS_TABLE, key) == before
    assert audit_events(capsys, "REVIEW_DECISION") == []


def test_quyet_dinh_chi_nhan_APPROVED_hoac_REJECTED(aws):
    """Gộp route thì `decision` thành dữ liệu đầu vào — phải kiểm, không được
    im lặng coi mọi thứ khác APPROVED là từ chối."""
    reconciliation_id = _reconciliation_id(_project_da_doi_chieu())

    for xau in ({}, {"decision": ""}, {"decision": "approved"}, {"decision": "MAYBE"}):
        status, body = call("POST", f"/reconciliations/{reconciliation_id}/review", xau)
        assert status == 400, f"{xau} phải bị từ chối"
        assert "decision" in body["error"]


def test_khong_con_route_approve_reject_rieng(aws):
    reconciliation_id = _reconciliation_id(_project_da_doi_chieu())

    for duoi in ("approve", "reject"):
        assert call("POST", f"/reconciliations/{reconciliation_id}/{duoi}")[0] == 404


def test_xem_ocr_tho_cua_document(aws):
    from common.dynamodb import update_document
    from common.s3 import write_json

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


def test_document_ids_rong_KHONG_duoc_hieu_la_tat_ca(aws, started_executions):
    """`if requested:` coi `[]` là falsy nên rơi vào nhánh "chạy tất cả" — ngược
    hoàn toàn ý định của người gọi.

    Hôm nay chưa ai gửi mảng rỗng nên lỗi chưa lộ. Nhưng giao diện sắp có chọn
    nhiều chứng từ: bỏ chọn hết rồi bấm nhầm là chạy cả project và tiêu tiền AI
    cho mọi chứng từ. Phải phân biệt "không khai" với "khai rỗng".
    """
    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf", "INV-001.pdf")
    for document in created:
        put_file(document["s3_key"])

    status, body = call("POST", f"/projects/{project_id}/process", {"document_ids": []})

    assert status == 400
    assert "document_ids" in body["error"]
    assert started_executions == [], "KHÔNG được chạy chứng từ nào"


def test_khong_khai_document_ids_van_la_chay_tat_ca(aws, started_executions):
    """Nửa còn lại của cùng một luật: bỏ trống vẫn phải nghĩa là cả project."""
    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf", "INV-001.pdf")
    for document in created:
        put_file(document["s3_key"])

    status, body = call("POST", f"/projects/{project_id}/process")

    assert status == 202
    assert len(body["processing"]) == 2


def test_document_ids_sai_kieu_bi_tu_choi(aws, started_executions):
    project_id = make_project()
    put_file(add_documents(project_id, "PO-001.pdf")[0]["s3_key"])

    status, body = call(
        "POST", f"/projects/{project_id}/process", {"document_ids": "doc-1"}
    )

    assert status == 400
    assert started_executions == []


# --- Sửa tay KHÔNG còn tự đối chiếu ----------------------------------------
#
# Sửa tay là thao tác REVIEW, không phải thao tác đối chiếu. Trước đây PATCH tự
# chạy `run_reconciliation` — nghĩa là logic đối chiếu chạy ở ba Lambda khác
# nhau, và `api/` buộc phải kéo `workers/` vào gói.
#
# Giờ PATCH chỉ lưu. Kết quả đối chiếu cũ bị đánh dấu `is_stale`, và duyệt bị
# chặn cho tới khi chạy lại — đổi một tính chất "đúng nhờ may" thành một ràng
# buộc được cưỡng chế.


def _sua_tay(project_id: str, document_id: str, fields: dict) -> tuple[int, dict]:
    return call(
        "PATCH", f"/projects/{project_id}/documents/{document_id}",
        {"fields": fields, "reviewer": "tri"},
    )


def test_patch_khong_con_tra_ve_reconciliation(aws):
    project_id = _project_da_doi_chieu()
    doc = call("GET", f"/projects/{project_id}")[1]["documents"][0]
    _reconciliation_id(project_id)

    status, body = _sua_tay(project_id, doc["document_id"], {"vendor": "ABC Technology"})

    assert status == 200
    assert body["document"]["edited_fields"] == ["vendor"]
    assert "reconciliation" not in body, "PATCH thôi đối chiếu — không được trả khoá này"


def test_sua_tay_lam_doi_chieu_thanh_cu(aws):
    project_id = _project_da_doi_chieu()
    doc = call("GET", f"/projects/{project_id}")[1]["documents"][0]
    _reconciliation_id(project_id)

    assert call("GET", f"/projects/{project_id}")[1]["latest_reconciliation"]["is_stale"] is False

    _sua_tay(project_id, doc["document_id"], {"vendor": "ABC Technology"})

    assert call("GET", f"/projects/{project_id}")[1]["latest_reconciliation"]["is_stale"] is True


def test_khong_duyet_duoc_ket_qua_da_cu(aws):
    """Duyệt một kết luận tính TRƯỚC lần sửa cuối là duyệt dữ liệu sai."""
    project_id = _project_da_doi_chieu()
    doc = call("GET", f"/projects/{project_id}")[1]["documents"][0]
    reconciliation_id = _reconciliation_id(project_id)
    _sua_tay(project_id, doc["document_id"], {"vendor": "ABC Technology"})

    for quyet_dinh in ("APPROVED", "REJECTED"):
        status, body = call(
            "POST", f"/reconciliations/{reconciliation_id}/review", {"decision": quyet_dinh}
        )
        assert status == 409, quyet_dinh
        assert "Đối chiếu lại" in body["error"]


def test_doi_chieu_lai_xong_thi_duyet_duoc(aws):
    project_id = _project_da_doi_chieu()
    doc = call("GET", f"/projects/{project_id}")[1]["documents"][0]
    _reconciliation_id(project_id)
    _sua_tay(project_id, doc["document_id"], {"vendor": "ABC Technology"})

    moi = _reconciliation_id(project_id)
    assert call("GET", f"/projects/{project_id}")[1]["latest_reconciliation"]["is_stale"] is False

    status, _ = call("POST", f"/reconciliations/{moi}/review", {"decision": "APPROVED"})
    assert status == 200


def test_api_khong_duoc_import_workers_reconcile():
    """Đối chiếu chỉ chạy ở MỘT Lambda. `api/` gọi qua `common/reconcile_client`,
    không import thẳng — nếu không thì gói `api-*` lại phải kéo `workers/`.
    """
    import pathlib

    api_dir = pathlib.Path(__file__).resolve().parents[1] / "api"
    pham = [
        f"{p.name}:{i}"
        for p in api_dir.glob("*.py")
        for i, dong in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if "workers.reconcile" in dong or "from workers import" in dong
    ]
    assert not pham, f"api/ đang import thẳng workers: {pham}"


# --- Danh tính lấy từ TOKEN, không lấy từ body (Task 1) --------------------


def test_request_user_lay_username_tu_token(aws):
    from api.http import request_user

    event = {
        "requestContext": {
            "authorizer": {"jwt": {"claims": {"cognito:username": "tri", "sub": "abc"}}}
        }
    }
    assert request_user(event) == "tri"
    event2 = {"requestContext": {"authorizer": {"jwt": {"claims": {"sub": "sub-123"}}}}}
    assert request_user(event2) == "sub-123"
    event3 = {
        "requestContext": {
            "authorizer": {"jwt": {"claims": {"email": "tri@example.com", "sub": "abc"}}}
        }
    }
    assert request_user(event3) == "abc"


def test_request_user_uu_tien_cognito_username_truoc_email(aws):
    from api.http import request_user

    event = {
        "requestContext": {
            "authorizer": {
                "jwt": {"claims": {"email": "a@b.com", "cognito:username": "tri", "sub": "s"}}
            }
        }
    }
    assert request_user(event) == "tri"


def test_email_gia_mao_khong_doi_duoc_username(aws):
    """Token có username tri nhưng email sep@congty.vn thì danh tính phải là tri.

    App client không khai write_attributes chứa email nên người dùng tự sửa
    email bằng access token cũng không đổi được danh tính audit.
    """
    from api.http import request_user

    event = {
        "requestContext": {
            "authorizer": {
                "jwt": {
                    "claims": {
                        "cognito:username": "tri",
                        "email": "sep@congty.vn",
                        "sub": "sub-123",
                    }
                }
            }
        }
    }
    assert request_user(event) == "tri"


def test_request_user_khong_co_claims_ve_DEV_USER(aws):
    from api.http import DEV_USER, request_user

    assert request_user({}) == DEV_USER
    assert request_user({"requestContext": {}}) == DEV_USER
    assert request_user({"requestContext": {"authorizer": {}}}) == DEV_USER
    assert request_user({"requestContext": {"authorizer": {"jwt": {"claims": {}}}}}) == DEV_USER


def test_body_reviewer_bi_bo_qua_khi_co_token(aws):
    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf", "INV-001.pdf")
    mark_processed(created[0]["document_id"], PO_DATA)
    mark_processed(created[1]["document_id"], INVOICE_DATA)
    reconciliation_id = _reconciliation_id(project_id)

    status, body = call(
        "POST",
        f"/reconciliations/{reconciliation_id}/review",
        {"decision": "APPROVED", "reviewer": "ai-do-khac"},
        claims={"cognito:username": "tri"},
    )
    assert status == 200
    assert body["review"]["reviewer"] == "tri"
    assert body["review"]["reviewer"] != "ai-do-khac"

    from common.dynamodb import RECONCILIATIONS_TABLE, get_item

    record = get_item(RECONCILIATIONS_TABLE, {"reconciliation_id": reconciliation_id})
    assert record["review"]["reviewer"] == "tri"


def test_edit_document_body_reviewer_bi_bo_qua(aws, capsys):
    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf")
    mark_processed(created[0]["document_id"], PO_DATA)

    status, body = call(
        "PATCH",
        f"/projects/{project_id}/documents/{created[0]['document_id']}",
        {"fields": {"vendor": "XYZ"}, "reviewer": "ai-do-khac"},
        claims={"cognito:username": "tri"},
    )
    assert status == 200
    from common.dynamodb import DOCUMENTS_TABLE, get_item

    doc = get_item(DOCUMENTS_TABLE, {"document_id": created[0]["document_id"]})
    assert doc["edited_by"] == "tri"

    logs = audit_records(capsys, "REVIEW_EDIT")
    assert any(l["actor"] == "tri" for l in logs)
    assert not any(l["actor"] == "ai-do-khac" for l in logs)
    assert all("reviewer" not in l["detail"] for l in logs)


def test_create_project_lay_created_by_tu_token(aws):
    status, body = call("POST", "/projects", {"name": "X"}, claims={"cognito:username": "tri"})
    assert status == 201
    assert body["created_by"] == "tri"

    status2, body2 = call(
        "POST", "/projects", {"name": "Y", "created_by": "ai-do-khac"}, claims={"cognito:username": "tri2"}
    )
    assert body2["created_by"] == "tri2"


def test_khong_co_token_thi_roi_ve_DEV_USER(aws, started_executions, capsys):
    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf")
    mark_processed(created[0]["document_id"], PO_DATA)

    status, body = call(
        "PATCH",
        f"/projects/{project_id}/documents/{created[0]['document_id']}",
        {"fields": {"vendor": "XYZ"}},
    )
    assert status == 200
    from common.dynamodb import DOCUMENTS_TABLE, get_item

    doc = get_item(DOCUMENTS_TABLE, {"document_id": created[0]["document_id"]})
    assert doc["edited_by"] == "dev"

    status2, body2 = call("POST", "/projects", {"name": "NoAuth"})
    assert body2["created_by"] == "dev"

    project_id2 = make_project()
    created2 = add_documents(project_id2, "PO-001.pdf")
    from common.s3 import get_s3

    get_s3().put_object(Bucket="test-documents-bucket", Key=created2[0]["s3_key"], Body=b"%PDF fake2")
    status3, body3 = call("POST", f"/projects/{project_id2}/process", {})
    assert status3 == 202
    logs = audit_records(capsys, "PROCESS_RUN")
    assert any(l["actor"] == "dev" for l in logs)


def test_process_ghi_triggered_by_tu_token(aws, started_executions, capsys):
    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf")
    from common.s3 import get_s3

    get_s3().put_object(Bucket="test-documents-bucket", Key=created[0]["s3_key"], Body=b"%PDF 123")
    status, body = call(
        "POST", f"/projects/{project_id}/process", {}, claims={"cognito:username": "tri"}
    )
    assert status == 202
    logs = audit_records(capsys, "PROCESS_RUN")
    assert logs[0]["actor"] == "tri"


def test_khong_con_poc_user_trong_backend():
    import pathlib

    backend = pathlib.Path(__file__).resolve().parents[1]
    found = []
    for p in backend.rglob("*.py"):
        if "tests" in p.parts:
            continue
        if "poc-user" in p.read_text(encoding="utf-8"):
            found.append(str(p))
    assert not found, f"còn poc-user trong: {found}"
