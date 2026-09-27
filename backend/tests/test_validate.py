from datetime import date

import pytest

from core import validate_document


def make_po(**overrides) -> dict:
    data = {
        "document_type": "purchase_order",
        "po_number": "PO-2026-001",
        "po_date": date(2026, 8, 1),
        "vendor": "ABC Technology",
        "vendor_tax_code": "0301234567",
        "buyer": "Công ty TNHH XYZ",
        "currency": "VND",
        "items": [
            {"item_name": "Laptop Dell XPS", "quantity": 100, "unit": "cái", "unit_price": 1250000}
        ],
        "total_amount": 125000000,
    }
    data.update(overrides)
    return data


def make_invoice(**overrides) -> dict:
    data = {
        "document_type": "invoice",
        "invoice_number": "INV-001",
        "invoice_date": date(2026, 8, 5),
        "vendor": "ABC Technology",
        "vendor_tax_code": "0301234567",
        "buyer": "Công ty TNHH XYZ",
        "currency": "VND",
        "po_number": "PO-2026-001",
        "items": [
            {"item_name": "Laptop Dell XPS", "quantity": 100, "unit": "cái", "unit_price": 1280000}
        ],
        "subtotal": 128000000,
        "tax_rate": 0.08,
        "tax_amount": 10240000,
        "total_amount": 138240000,
    }
    data.update(overrides)
    return data


def test_validate_po_ok():
    result = validate_document(make_po())
    assert result["valid"] is True
    from schemas import Document
    assert isinstance(result["model"], Document)


def test_validate_invoice_ok():
    result = validate_document(make_invoice())
    assert result["valid"] is True
    from schemas import Document
    assert isinstance(result["model"], Document)


@pytest.mark.parametrize("discount", [250000, None, -1])
def test_hoa_don_co_chiet_khau(discount):
    data = make_invoice(discount_amount=discount)
    result = validate_document(data)
    assert result["valid"]
    if discount == -1:
        assert any(f["code"] == "amount_sign" and f["field"] == "discount_amount" for f in result["flags"])
    elif discount is None:
        assert any(f["code"] == "insufficient_data" and f["field"] == "subtotal" for f in result["flags"])
    else:
        assert result["model"].discount_amount == discount


def test_validate_unknown_type():
    result = validate_document({"document_type": "bill_of_lading"})
    assert result["valid"] is False
    assert any("không được hỗ trợ" in e for e in result["schema_errors"])


def test_validate_missing_required_field():
    # P2: mọi trường đầu tuỳ chọn nên thiếu vendor vẫn VALIDATED (chỉ cảnh báo khi thiếu cột bắt buộc)
    data = make_po()
    del data["vendor"]
    result = validate_document(data)
    assert result["valid"] is True


def test_validate_bad_tax_code():
    result = validate_document(make_po(vendor_tax_code="abc"))
    assert result["valid"]
    assert result["rule_errors"] == []
    assert any(f["code"] == "format" for f in result["flags"])


# Chạy thật mới lộ: hoá đơn của chi nhánh Golden Gate in MST "0102721191-068"
# và bị đánh FAILED, trong khi pattern cũ lại nhận 11 chữ số vô nghĩa.
@pytest.mark.parametrize(
    "ma",
    [
        "0301234567",  # doanh nghiệp: 10 số
        "0102721191-068",  # chi nhánh / đơn vị phụ thuộc: 10 số - 3 số
        "0102721191068",  # cùng mã đó nhưng in liền
        "001203012345",  # cá nhân, hộ kinh doanh: số định danh 12 số
    ],
)
def test_ma_so_thue_hop_le(ma):
    assert validate_document(make_invoice(vendor_tax_code=ma))["valid"] is True


@pytest.mark.parametrize(
    "ma",
    ["03012345678", "0102721191-06", "0102721191-0689", "0102721191 068", "abc"],
)
def test_ma_so_thue_sai_dang(ma):
    result = validate_document(make_invoice(vendor_tax_code=ma))
    assert result["valid"]
    assert result["rule_errors"] == []
    assert any(f["code"] == "format" for f in result["flags"])


def test_validate_negative_quantity():
    result = validate_document(make_po(items=[{"item_name": "A", "quantity": -5, "unit_price": 10}]))
    assert result["valid"]
    assert result["rule_errors"] == []
    assert any(f["code"] == "quantity" for f in result["flags"])


def test_validate_item_total_mismatch():
    result = validate_document(make_po(total_amount=999999999))
    assert result["valid"]
    assert result["rule_errors"] == []
    assert any(f["code"] == "insufficient_data" for f in result["flags"])


def test_validate_invoice_subtotal_tax_mismatch():
    result = validate_document(make_invoice(total_amount=999999999))
    assert result["valid"]
    assert result["rule_errors"] == []
    assert any(f["code"] == "total_formula" for f in result["flags"])


def test_validate_future_date():
    result = validate_document(make_invoice(invoice_date=date(2099, 1, 1)))
    assert result["valid"]
    assert result["rule_errors"] == []
    assert any(f["code"] == "future_date" for f in result["flags"])


def test_validate_bad_currency():
    result = validate_document(make_po(currency="XXX"))
    assert result["valid"]
    assert result["rule_errors"] == []
    assert any(f["code"] == "currency" for f in result["flags"])


# --- Loại "unknown": chứng từ không khớp loại nào đã định nghĩa -------------


def test_unknown_qua_duoc_validate_du_gan_nhu_trong():
    """Chỉ cần document_type là đủ. Đây là chỗ chứa thứ chưa hiểu rõ."""
    result = validate_document({"document_type": "unknown"})
    assert result["valid"], result["schema_errors"] + result["rule_errors"]


def test_unknown_nhan_duoc_so_hieu_chung_tu_that():
    """Số hiệu thật của chứng từ vận tải, không phải dạng PO-2026-001."""
    for so_hieu in ("ASC0483717", "SG2514576-6501066247", "HASLS21250901217-6501060532"):
        result = validate_document(
            {"document_type": "unknown", "doc_number": so_hieu, "doc_date": "2025-10-17"}
        )
        assert result["valid"], f"{so_hieu}: {result['schema_errors']}"


def test_unknown_van_chan_ngay_tuong_lai():
    result = validate_document({"document_type": "unknown", "doc_date": "2099-01-01"})
    assert result["valid"]
    assert result["rule_errors"] == []
    assert any(f["code"] == "future_date" for f in result["flags"])


def test_unknown_khong_lam_ba_loai_cu_nong_theo():
    # P2: document_type invoice mà không có tables vẫn VALIDATED (thiếu cột bắt buộc thì skip so dòng, không FAILED)
    result = validate_document({"document_type": "invoice", "role": "billing", "tables": []})
    assert result["valid"] is True


def test_document_type_bia_van_bi_tu_choi():
    """'unknown' là một loại CÓ THẬT trong registry, không phải cái sọt rác."""
    result = validate_document({"document_type": "bill_of_lading"})
    assert not result["valid"]
    assert any("không được hỗ trợ" in e for e in result["schema_errors"])
