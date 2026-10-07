import pytest

from common.dynamodb import update_document
from tests.test_api import (
    INVOICE_DATA,
    PO_DATA,
    _reconciliation_id,
    add_documents,
    call,
    make_project,
    mark_processed,
)

CO_VI_TRI = {
    "code": "vi_tri", "field": "tables.0.rows.0.Chiết khấu",
    "message": "x", "values": {"gia_tri_ai": 58000}, "formula": None,
}
CO_DINH_DANG = {
    "code": "ai_format", "field": "doc_date",
    "message": "x", "values": {"gia_tri_goc": "28/12/2024"}, "formula": None,
}
CO_ON = {
    "code": "insufficient_data", "field": "subtotal",
    "message": "x", "values": {}, "formula": None,
}


def _gan_co(document_id, *flags):
    update_document(document_id, validation={
        "valid": True, "schema_errors": [], "rule_errors": [], "flags": list(flags),
    })


def _du_an(*flags):
    project_id = make_project()
    created = add_documents(project_id, "PO-001.pdf", "INV-001.pdf")
    mark_processed(created[0]["document_id"], PO_DATA)
    mark_processed(created[1]["document_id"], INVOICE_DATA)
    _gan_co(created[1]["document_id"], *flags)
    return project_id, created[1]["document_id"]


def _duyet(reconciliation_id, decision="APPROVED"):
    return call("POST", f"/reconciliations/{reconciliation_id}/review", {"decision": decision})


def _sua(project_id, document_id, body):
    return call("PATCH", f"/projects/{project_id}/documents/{document_id}", body)


def _tat(project_id, document_id, co=CO_VI_TRI):
    return _sua(project_id, document_id, {"dismiss": {"code": co["code"], "field": co["field"]}})


def test_khong_duyet_duoc_khi_con_canh_bao_khoa_chua_xu_ly(aws):
    project_id, _ = _du_an(CO_VI_TRI)

    status, body = _duyet(_reconciliation_id(project_id))

    assert status == 409
    assert "INV-001.pdf" in body["error"]
    assert "tắt" in body["error"]


def test_tu_choi_khong_bi_khoa_boi_canh_bao(aws):
    project_id, _ = _du_an(CO_VI_TRI)

    assert _duyet(_reconciliation_id(project_id), "REJECTED")[0] == 200


@pytest.mark.parametrize("co", [CO_VI_TRI, CO_DINH_DANG])
def test_tat_canh_bao_khoa_thi_duyet_duoc_va_ket_qua_khong_thanh_cu(aws, co):
    project_id, document_id = _du_an(co)
    reconciliation_id = _reconciliation_id(project_id)

    status, body = _tat(project_id, document_id, co)

    assert status == 200
    assert body["document"]["needs_confirmation"] is False
    latest = call("GET", f"/projects/{project_id}")[1]["latest_reconciliation"]
    assert latest["is_stale"] is False
    assert latest["unconfirmed_document_ids"] == []
    assert _duyet(reconciliation_id)[0] == 200


def test_project_bao_chung_tu_nao_con_canh_bao_khoa(aws):
    project_id, document_id = _du_an(CO_VI_TRI)
    _reconciliation_id(project_id)

    body = call("GET", f"/projects/{project_id}")[1]

    can = {d["document_id"]: d["needs_confirmation"] for d in body["documents"]}
    assert can[document_id] is True
    assert sum(can.values()) == 1
    assert body["latest_reconciliation"]["unconfirmed_document_ids"] == [document_id]


def test_co_on_khong_khoa_duyet(aws):
    project_id, _ = _du_an(CO_ON)

    assert _duyet(_reconciliation_id(project_id))[0] == 200


def test_xac_nhan_chung_khong_con_mo_khoa(aws):
    project_id, document_id = _du_an(CO_VI_TRI)
    reconciliation_id = _reconciliation_id(project_id)

    assert _sua(project_id, document_id, {"confirm": True})[0] == 400
    assert _duyet(reconciliation_id)[0] == 409


def test_con_mot_canh_bao_khoa_chua_tat_thi_van_khoa(aws):
    con_lai = {**CO_VI_TRI, "field": "tables.0.rows.1.Chiết khấu"}
    project_id, document_id = _du_an(CO_VI_TRI, con_lai)
    reconciliation_id = _reconciliation_id(project_id)

    status, body = _tat(project_id, document_id)

    assert status == 200
    assert body["document"]["needs_confirmation"] is True
    status, body = _duyet(reconciliation_id)
    assert status == 409
    assert "tắt" in body["error"]


def test_canh_bao_da_tat_ma_gia_tri_doi_thi_khoa_lai(aws):
    project_id, document_id = _du_an(CO_VI_TRI)
    reconciliation_id = _reconciliation_id(project_id)
    _tat(project_id, document_id)
    _gan_co(document_id, {**CO_VI_TRI, "values": {"gia_tri_ai": 0}})

    status, body = _duyet(reconciliation_id)

    assert status == 409
    assert "tắt" in body["error"]


def test_mo_lai_canh_bao_khoa_thi_khoa_lai(aws):
    project_id, document_id = _du_an(CO_VI_TRI)
    reconciliation_id = _reconciliation_id(project_id)
    _tat(project_id, document_id)

    status, body = _sua(
        project_id, document_id,
        {"undismiss": {"code": CO_VI_TRI["code"], "field": CO_VI_TRI["field"]}},
    )

    assert status == 200
    assert body["document"]["needs_confirmation"] is True
    assert _duyet(reconciliation_id)[0] == 409


def test_tat_canh_bao_khoa_ghi_vet_audit(aws, capsys):
    from tests.test_audit import audit_events

    project_id, document_id = _du_an(CO_VI_TRI)
    _tat(project_id, document_id)

    events = audit_events(capsys, "REVIEW_DISMISS")
    assert len(events) == 1
    assert events[0]["entity_id"] == document_id
