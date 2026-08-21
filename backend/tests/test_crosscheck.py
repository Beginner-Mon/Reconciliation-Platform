import pytest
from pydantic import BaseModel, Field
from typing import Literal

from core import run_crosscheck
from core.crosscheck import group_documents, build_refs
from schemas import registry


def po(**overrides) -> dict:
    document_id = overrides.pop("document_id", "doc-po")
    data = {
        "document_type": "purchase_order",
        "po_number": "PO-2026-001",
        "po_date": "2026-08-01",
        "vendor": "ABC Technology",
        "vendor_tax_code": "0301234567",
        "currency": "VND",
        "items": [
            {"item_name": "Laptop Dell XPS", "quantity": 100, "unit": "cái", "unit_price": 1250000}
        ],
        "total_amount": 125000000,
    }
    data.update(overrides)
    return {"document_id": document_id, "data": data}


def invoice(**overrides) -> dict:
    document_id = overrides.pop("document_id", "doc-inv")
    data = {
        "document_type": "invoice",
        "invoice_number": "INV-001",
        "invoice_date": "2026-08-05",
        "vendor": "ABC Technology",
        "vendor_tax_code": "0301234567",
        "currency": "VND",
        "po_number": "PO-2026-001",
        "items": [
            {"item_name": "Laptop Dell XPS", "quantity": 100, "unit": "cái", "unit_price": 1250000}
        ],
        "total_amount": 125000000,
    }
    data.update(overrides)
    return {"document_id": document_id, "data": data}


def acceptance(**overrides) -> dict:
    document_id = overrides.pop("document_id", "doc-bbnt")
    data = {
        "document_type": "acceptance_record",
        "record_number": "BBNT-001",
        "record_date": "2026-08-03",
        "vendor": "ABC Technology",
        "po_number": "PO-2026-001",
        "items": [{"item_name": "Laptop Dell XPS", "quantity": 100, "unit": "cái"}],
    }
    data.update(overrides)
    return {"document_id": document_id, "data": data}


def rule_ids(result: dict) -> set[str]:
    return {d["rule_id"] for d in result["discrepancies"]}


def test_po_invoice_khop_thi_khong_co_discrepancy():
    result = run_crosscheck([po(), invoice()])
    assert result["discrepancy_count"] == 0


def test_chi_po_va_invoice_thi_rule_nghiem_thu_skip_em():
    result = run_crosscheck([po(), invoice()])
    assert "invoiced_over_accepted" not in rule_ids(result)
    assert "accepted_over_ordered" not in rule_ids(result)
    assert result["skipped_documents"] == []


def test_lech_don_gia():
    result = run_crosscheck(
        [
            po(),
            invoice(
                items=[{"item_name": "Laptop Dell XPS", "quantity": 100, "unit_price": 1280000}],
                total_amount=128000000,
            ),
        ]
    )
    found = next(d for d in result["discrepancies"] if d["rule_id"] == "line_item_unit_price")
    assert found["difference"] == 30000
    assert {v["document_type"] for v in found["values"]} == {"purchase_order", "invoice"}


def test_lech_vendor_la_critical():
    result = run_crosscheck([po(), invoice(vendor="XYZ Corp")])
    found = next(d for d in result["discrepancies"] if d["rule_id"] == "agree_vendor")
    assert found["severity"] == "critical"
    assert len(found["values"]) == 2


def test_thieu_mat_hang_trong_invoice():
    result = run_crosscheck(
        [
            po(
                items=[
                    {"item_name": "Laptop Dell XPS", "quantity": 100, "unit_price": 1250000},
                    {"item_name": "Chuột Logitech", "quantity": 50, "unit_price": 200000},
                ],
                total_amount=135000000,
            ),
            invoice(),
        ]
    )
    assert "line_item_missing" in rule_ids(result)


def test_ba_loai_chung_tu_xuat_hoa_don_vuot_nghiem_thu():
    result = run_crosscheck(
        [
            po(),
            invoice(),
            acceptance(items=[{"item_name": "Laptop Dell XPS", "quantity": 80, "unit": "cái"}]),
        ]
    )
    found = next(d for d in result["discrepancies"] if d["rule_id"] == "invoiced_over_accepted")
    assert found["severity"] == "critical"
    assert found["difference"] == 20


def test_nghiem_thu_vuot_so_luong_dat_hang():
    result = run_crosscheck(
        [
            po(),
            invoice(),
            acceptance(items=[{"item_name": "Laptop Dell XPS", "quantity": 120, "unit": "cái"}]),
        ]
    )
    assert "accepted_over_ordered" in rule_ids(result)


def test_ba_loai_chung_tu_khop_thi_sach():
    result = run_crosscheck([po(), invoice(), acceptance()])
    assert result["discrepancy_count"] == 0
    assert len(result["groups"]) == 1
    assert set(result["groups"][0]["document_types"]) == {
        "purchase_order",
        "invoice",
        "acceptance_record",
    }


def test_sai_thu_tu_ngay():
    result = run_crosscheck([po(po_date="2026-08-10"), invoice(invoice_date="2026-08-05")])
    assert "date_order" in rule_ids(result)


def test_invoice_tro_toi_po_khong_ton_tai():
    result = run_crosscheck([invoice(), acceptance()])
    assert "po_reference_missing" in rule_ids(result)


def test_hai_invoice_cho_mot_po():
    result = run_crosscheck(
        [
            po(),
            invoice(document_id="doc-inv-1"),
            invoice(
                document_id="doc-inv-2",
                invoice_number="INV-002",
                items=[{"item_name": "Laptop Dell XPS", "quantity": 1, "unit_price": 999000}],
                total_amount=999000,
            ),
        ]
    )
    assert result["skipped_documents"] == []
    assert len(result["groups"]) == 1
    assert len(result["groups"][0]["document_ids"]) == 3
    assert "match_total_amount" in rule_ids(result)


def test_doc_khong_qua_validate_bi_loai_khoi_doi_chieu():
    broken = {"document_id": "doc-rac", "data": {"document_type": "invoice"}}
    result = run_crosscheck([po(), invoice(), broken])
    assert "doc-rac" not in result["checked_document_ids"]
    assert [s["document_id"] for s in result["skipped_documents"]] == ["doc-rac"]
    assert result["discrepancy_count"] == 0


def test_doc_khong_co_po_number_van_duoc_gom_khi_chi_co_mot_giao_dich():
    result = run_crosscheck([po(), invoice(po_number=None, vendor="XYZ Corp")])
    assert len(result["groups"]) == 1
    assert "agree_vendor" in rule_ids(result)


def test_doc_khong_co_po_number_bi_bao_khi_co_nhieu_giao_dich():
    result = run_crosscheck(
        [
            po(),
            po(document_id="doc-po-2", po_number="PO-2026-002"),
            invoice(document_id="doc-mo-coi", po_number=None),
        ]
    )
    found = next(d for d in result["discrepancies"] if d["rule_id"] == "document_unlinked")
    assert found["values"][0]["document_id"] == "doc-mo-coi"


@pytest.fixture
def delivery_note_type():
    class DeliveryNote(BaseModel):
        document_type: Literal["delivery_note"]
        note_number: str = Field(min_length=1)
        vendor: str = Field(min_length=1)
        po_number: str | None = None
        currency: str | None = None

    registry.DOCUMENT_TYPES["delivery_note"] = DeliveryNote
    registry.DOCUMENT_TYPE_LABELS["delivery_note"] = "phiếu giao hàng"
    yield
    del registry.DOCUMENT_TYPES["delivery_note"]
    del registry.DOCUMENT_TYPE_LABELS["delivery_note"]


def test_them_loai_chung_tu_thu_tu_khong_lam_vo_engine(delivery_note_type):
    extra = {
        "document_id": "doc-pgh",
        "data": {
            "document_type": "delivery_note",
            "note_number": "PGH-001",
            "vendor": "XYZ Corp",
            "po_number": "PO-2026-001",
            "currency": "VND",
        },
    }
    result = run_crosscheck([po(), invoice(), extra])

    assert "doc-pgh" in result["checked_document_ids"]
    assert len(result["groups"]) == 1
    found = next(d for d in result["discrepancies"] if d["rule_id"] == "agree_vendor")
    assert {v["document_id"] for v in found["values"]} == {"doc-po", "doc-inv", "doc-pgh"}


def test_group_documents_tach_theo_po_number():
    refs, _ = build_refs(
        [
            po(),
            invoice(),
            po(document_id="doc-po-2", po_number="PO-2026-002"),
            invoice(document_id="doc-inv-2", po_number="PO-2026-002", invoice_number="INV-002"),
        ]
    )
    groups, unlinked = group_documents(refs)
    assert unlinked == []
    assert {g.key for g in groups} == {"PO-2026-001", "PO-2026-002"}
    assert all(len(g.documents) == 2 for g in groups)


# --- Chứng từ chưa phân loại không được kéo vào đối chiếu -------------------


def _unknown(document_id: str, **fields) -> dict:
    return {"document_id": document_id, "data": {"document_type": "unknown", **fields}}


def test_hai_chung_tu_unknown_khong_bi_dem_so_tien_voi_nhau():
    """Lỗi bắt được khi chạy thật trên 6 chứng từ vận tải biển.

    AgreeRule/NumericRule lọc theo TRƯỜNG chứ không theo LOẠI, nên hai chứng từ
    của hai lô hàng, hai khách hàng khác nhau bị báo "lệch tiền 43 triệu" chỉ
    vì cùng có trường total_amount.
    """
    result = run_crosscheck([
        _unknown("doc-a", currency="VND", total_amount=43_350_000),
        _unknown("doc-b", currency="USD", total_amount=104_760),
    ])
    assert result["discrepancy_count"] == 0, result["discrepancies"]


def test_unknown_bi_bo_qua_nhung_phai_bao_ra_chu_khong_im_lang():
    result = run_crosscheck([_unknown("doc-a", total_amount=1_000)])
    assert "doc-a" not in result["checked_document_ids"]
    skipped = {s["document_id"]: s["reason"] for s in result["skipped_documents"]}
    assert "chưa phân loại" in skipped["doc-a"]


def test_unknown_khong_lam_hong_doi_chieu_cua_cac_loai_that():
    """Thêm một chứng từ lạ vào project không được đổi kết quả đối chiếu."""
    that = [po(), invoice()]
    truoc = run_crosscheck(that)
    sau = run_crosscheck(that + [_unknown("doc-la", currency="USD", total_amount=7)])
    assert sau["discrepancy_count"] == truoc["discrepancy_count"]
