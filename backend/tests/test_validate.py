from datetime import date

from core import validate_document
from schemas import Invoice, PurchaseOrder


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
    assert isinstance(result["model"], PurchaseOrder)


def test_validate_invoice_ok():
    result = validate_document(make_invoice())
    assert result["valid"] is True
    assert isinstance(result["model"], Invoice)


def test_validate_unknown_type():
    result = validate_document({"document_type": "contract"})
    assert result["valid"] is False
    assert any("không được hỗ trợ" in e for e in result["schema_errors"])


def test_validate_missing_required_field():
    data = make_po()
    del data["vendor"]
    result = validate_document(data)
    assert result["valid"] is False
    assert any("vendor" in e for e in result["schema_errors"])


def test_validate_bad_tax_code():
    data = make_po(vendor_tax_code="abc")
    result = validate_document(data)
    assert result["valid"] is False
    assert any("vendor_tax_code" in e for e in result["schema_errors"])


def test_validate_negative_quantity():
    data = make_po()
    data["items"][0]["quantity"] = -5
    result = validate_document(data)
    assert result["valid"] is False
    assert any("quantity" in e for e in result["schema_errors"])


def test_validate_item_total_mismatch():
    data = make_po(total_amount=999999999)
    result = validate_document(data)
    assert result["valid"] is False
    assert any("Tổng item" in e for e in result["rule_errors"])


def test_validate_invoice_subtotal_tax_mismatch():
    data = make_invoice(total_amount=999999999)
    result = validate_document(data)
    assert result["valid"] is False
    assert any("subtotal" in e for e in result["rule_errors"])


def test_validate_future_date():
    data = make_invoice(invoice_date=date(2099, 1, 1))
    result = validate_document(data)
    assert result["valid"] is False
    assert any("tương lai" in e for e in result["rule_errors"])


def test_validate_bad_currency():
    data = make_po(currency="XXX")
    result = validate_document(data)
    assert result["valid"] is False
    assert any("currency" in e for e in result["rule_errors"])


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
    """Nới lỏng trường, KHÔNG nới lỏng luật chung."""
    result = validate_document({"document_type": "unknown", "doc_date": "2099-01-01"})
    assert not result["valid"]
    assert any("tương lai" in e for e in result["rule_errors"])


def test_unknown_khong_lam_ba_loai_cu_nong_theo():
    """Thêm loại dự phòng không được biến hóa đơn thiếu trường thành hợp lệ."""
    result = validate_document({"document_type": "invoice"})
    assert not result["valid"]
    assert result["schema_errors"]


def test_document_type_bia_van_bi_tu_choi():
    """'unknown' là một loại CÓ THẬT trong registry, không phải cái sọt rác."""
    result = validate_document({"document_type": "bill_of_lading"})
    assert not result["valid"]
    assert any("không được hỗ trợ" in e for e in result["schema_errors"])
