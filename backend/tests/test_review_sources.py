from common.dynamodb import DOCUMENTS_TABLE, get_item, update_document
from common.s3 import ocr_key, write_json
from core.position import check_positions
from tests.test_api import add_documents, call, make_project
from tests.test_position import DUNG, HEADERS, bang, sua, trang


def cot(ten):
    return HEADERS.index(ten)


def _chung_tu(data, position_issues=None):
    project_id = make_project()
    document_id = add_documents(project_id, "INV-001.pdf")[0]["document_id"]
    key = ocr_key(project_id, document_id)
    write_json(key, {"text": "", "pages": trang()})
    update_document(
        document_id,
        status="VALIDATED",
        ocr_s3_key=key,
        extraction={"document_type": "invoice", **data},
        validation={"valid": True, "schema_errors": [], "rule_errors": [], "flags": []},
        position_issues=position_issues or [],
    )
    return project_id, document_id


def _ocr(project_id, document_id):
    status, body = call("GET", f"/projects/{project_id}/documents/{document_id}/ocr")
    assert status == 200
    return body


def _sua(project_id, document_id, body):
    return call("PATCH", f"/projects/{project_id}/documents/{document_id}", body)


def _nguon(dong, ten_cot, refs):
    hang = [[[] for _ in HEADERS] for _ in DUNG]
    hang[dong][cot(ten_cot)] = refs
    return {"fields": {}, "other": {}, "tables": [{"headers": [[] for _ in HEADERS], "rows": hang}]}


def test_ocr_tra_ve_vi_tri_cua_tung_o(aws):
    project_id, document_id = _chung_tu(bang(*DUNG))

    body = _ocr(project_id, document_id)

    words = body["pages"][0]["words"]
    o = body["layout"]["tables"][0]["rows"][0][cot("Đơn giá")]
    assert [words[i][0] for _, i in o] == ["29.000"]
    assert body["layout"]["number_style"] == "thousands"


def test_chung_tu_chua_trich_xuat_thi_layout_la_null(aws):
    project_id = make_project()
    document_id = add_documents(project_id, "INV-001.pdf")[0]["document_id"]
    key = ocr_key(project_id, document_id)
    write_json(key, {"text": "", "pages": trang()})
    update_document(document_id, ocr_s3_key=key)

    assert _ocr(project_id, document_id)["layout"] is None


def test_luu_kem_sources_thi_lan_sau_tra_dung_ban_da_luu(aws):
    project_id, document_id = _chung_tu(bang(*DUNG))
    bang_moi = bang(*DUNG)["tables"]
    bang_moi[0]["rows"][0]["Đơn giá"] = 30000
    sources = _nguon(0, "Đơn giá", [[0, 2], [0, 3]])

    status, _ = _sua(project_id, document_id, {"fields": {"tables": bang_moi}, "sources": sources})

    assert status == 200
    bang_0 = _ocr(project_id, document_id)["layout"]["tables"][0]
    assert bang_0["rows"][0][cot("Đơn giá")] == [[0, 2], [0, 3]]
    assert bang_0["rows"][1][cot("Đơn giá")] == []
    assert bang_0["at"][1][cot("Đơn giá")] != []


def test_luu_khong_kem_sources_thi_quay_ve_tu_do(aws):
    project_id, document_id = _chung_tu(bang(*DUNG))
    update_document(document_id, sources={"fields": {}, "other": {}, "tables": [None]})

    _sua(project_id, document_id, {"fields": {"doc_number": "3126818"}})

    assert get_item(DOCUMENTS_TABLE, {"document_id": document_id}).get("sources") is None
    assert _ocr(project_id, document_id)["layout"]["tables"][0]["rows"][0][cot("Đơn giá")] != []


def test_chi_gan_lai_khung_thi_khong_lam_ket_qua_doi_chieu_thanh_cu(aws):
    project_id, document_id = _chung_tu(bang(*DUNG))
    truoc = get_item(DOCUMENTS_TABLE, {"document_id": document_id})

    status, body = _sua(project_id, document_id, {"sources": _nguon(2, "Tên", [[0, 9]])})

    assert status == 200
    assert body["document"]["document_id"] == document_id
    sau = get_item(DOCUMENTS_TABLE, {"document_id": document_id})
    assert sau["sources"]["tables"][0]["rows"][2][cot("Tên")] == [[0, 9]]
    assert sau.get("updated_at") == truoc.get("updated_at")
    assert sau.get("edited_fields") == truoc.get("edited_fields")


def test_khong_co_fields_va_sources_khong_hop_le_thi_400(aws):
    project_id, document_id = _chung_tu(bang(*DUNG))

    assert _sua(project_id, document_id, {"sources": "x"})[0] == 400
    assert _sua(project_id, document_id, {})[0] == 400


def test_doi_tieu_de_cot_van_giu_canh_bao_cua_o_chua_sua(aws):
    sai = sua(0, {"Chiết khấu": None, "Trước thuế": 58000})
    project_id, document_id = _chung_tu(sai, check_positions(sai, trang()))
    bang_moi = sai["tables"]
    bang_moi[0]["columns"][cot("Trước thuế")]["header"] = "Giá trước thuế"
    for row in bang_moi[0]["rows"]:
        row["Giá trước thuế"] = row.pop("Trước thuế")

    status, body = _sua(project_id, document_id, {"fields": {"tables": bang_moi}})

    assert status == 200
    assert sorted(f["field"] for f in body["validation"]["flags"] if f["code"] == "vi_tri") == [
        "tables.0.rows.0.Chiết khấu",
        "tables.0.rows.0.Giá trước thuế",
    ]


def _co_cong_thuc():
    project_id, document_id = _chung_tu(bang(*DUNG))
    co = {
        "code": "format",
        "field": "seller_tax_code",
        "message": "x",
        "values": {"seller_tax_code": "abc"},
        "formula": None,
    }
    update_document(
        document_id,
        validation={"valid": True, "schema_errors": [], "rule_errors": [], "flags": [co]},
    )
    return project_id, document_id, co


def test_tat_co_cong_thuc_luu_server_va_khong_doi_updated_at(aws):
    project_id, document_id, co = _co_cong_thuc()
    truoc = get_item(DOCUMENTS_TABLE, {"document_id": document_id})

    status, body = _sua(
        project_id, document_id, {"dismiss": {"code": co["code"], "field": co["field"]}}
    )

    assert status == 200
    sau = get_item(DOCUMENTS_TABLE, {"document_id": document_id})
    assert sau["dismissed_flags"] == [{
        "code": "format",
        "field": "seller_tax_code",
        "values": {"seller_tax_code": "abc"},
        "by": "dev",
        "at": sau["dismissed_flags"][0]["at"],
    }]
    assert sau.get("updated_at") == truoc.get("updated_at")
    assert body["document"]["dismissed_flags"] == sau["dismissed_flags"]


def test_tat_co_khong_ton_tai_tra_400(aws):
    project_id, document_id, co = _co_cong_thuc()

    assert _sua(project_id, document_id, {"dismiss": {"code": "vi_tri", "field": "x"}})[0] == 400
    assert _sua(project_id, document_id, {"dismiss": {"code": "format", "field": "khong_co"}})[0] == 400
    assert _sua(project_id, document_id, {"dismiss": "x"})[0] == 400


def test_mo_lai_va_sua_du_lieu_xoa_tat_cu(aws):
    project_id, document_id, co = _co_cong_thuc()
    _sua(project_id, document_id, {"dismiss": {"code": co["code"], "field": co["field"]}})

    status, _ = _sua(project_id, document_id, {"undismiss": {"code": co["code"], "field": co["field"]}})

    assert status == 200
    assert get_item(DOCUMENTS_TABLE, {"document_id": document_id}).get("dismissed_flags") == []
    assert _sua(project_id, document_id, {"undismiss": {"code": co["code"], "field": co["field"]}})[0] == 400

    _sua(project_id, document_id, {"dismiss": {"code": co["code"], "field": co["field"]}})
    _sua(project_id, document_id, {"fields": {"doc_number": "3126818"}})

    assert get_item(DOCUMENTS_TABLE, {"document_id": document_id}).get("dismissed_flags") == []
