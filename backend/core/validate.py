from datetime import date
from decimal import Decimal, InvalidOperation
import re

from pydantic import BaseModel, ValidationError

from schemas import CURRENCIES, model_for, supported_types
from schemas.document import enforce_limits


def _migrate_legacy(data: dict) -> dict:
    # Dịch extraction cũ (items, po_number...) sang schema mới tables
    if "tables" in data:
        return data
    items = data.get("items")
    if not isinstance(items, list):
        return data
    # Map legacy fields per type
    dt = data.get("document_type")
    if dt == "purchase_order":
        doc_number = data.get("po_number")
        doc_date = data.get("po_date")
        order_ref = None
    elif dt == "invoice":
        doc_number = data.get("invoice_number")
        doc_date = data.get("invoice_date")
        order_ref = data.get("po_number")
    elif dt == "acceptance_record":
        doc_number = data.get("record_number")
        doc_date = data.get("record_date")
        order_ref = data.get("po_number")
    else:
        # Custom type như delivery_note: note_number là số chứng từ riêng
        doc_number = data.get("doc_number") or data.get("note_number") or data.get("invoice_number") or data.get("record_number") or data.get("po_number")
        doc_date = data.get("doc_date") or data.get("po_date") or data.get("invoice_date") or data.get("record_date")
        order_ref = data.get("po_number") or data.get("order_reference")
        # Gán role mặc định cho loại mới: nếu có po_number thì coi là delivery, không thì other
        if data.get("document_type") not in ("other", "unknown"):
            role = "delivery" if order_ref else "other"
        else:
            role = "other"
    seller = data.get("vendor") or data.get("issuer")
    buyer = data.get("buyer") or data.get("recipient")
    seller_tax = data.get("vendor_tax_code")
    buyer_tax = data.get("buyer_tax_code")
    # role mapping
    role_map = {"purchase_order": "order", "invoice": "billing", "acceptance_record": "delivery", "unknown": "other"}
    role = role_map.get(data.get("document_type"), "other")
    if data.get("document_type") == "unknown":
        role = "other"
    # Build table
    cols = [
        {"header": "item_name", "role": "item_name"},
        {"header": "quantity", "role": "quantity"},
        {"header": "unit", "role": "unit"},
        {"header": "unit_price", "role": "unit_price"},
        {"header": "amount", "role": "amount"},
    ]
    rows = []
    for it in items:
        if not isinstance(it, dict):
            continue
        rows.append({
            "item_name": it.get("item_name"),
            "quantity": it.get("quantity"),
            "unit": it.get("unit"),
            "unit_price": it.get("unit_price"),
            "amount": it.get("amount"),
        })
    tables = [{"columns": cols, "rows": rows}] if rows else []
    new_data = {
        "document_type": data.get("document_type"),
        "role": role,
        "doc_number": doc_number,
        "doc_date": doc_date,
        "order_reference": order_ref,
        "seller": seller,
        "seller_tax_code": seller_tax,
        "buyer": buyer,
        "buyer_tax_code": buyer_tax,
        "currency": data.get("currency"),
        "total_amount": data.get("total_amount"),
        "subtotal": data.get("subtotal"),
        "discount_amount": data.get("discount_amount"),
        "tax_amount": data.get("tax_amount"),
        "other_fields": dict(data.get("other_fields") or {}),
        "tables": tables,
    }
    # keep original other fields
    for k in ["payment_terms", "delivery_date", "payment_due_date", "accepted_by", "notes", "summary"]:
        if data.get(k):
            new_data["other_fields"][k] = str(data[k])
    if data.get("shipping_amount") is not None:
        new_data["other_fields"].setdefault("shipping_amount", str(data["shipping_amount"]))
    return new_data


class _LoiDung(Exception):
    def __init__(self, loi):
        super().__init__("; ".join(loi))
        self.loi = loi


def _dung_model(data):
    loai = data.get("document_type")
    schema = model_for(loai) if isinstance(loai, str) else None
    if schema is None:
        raise _LoiDung([f"document_type không được hỗ trợ: {loai} (hỗ trợ: {', '.join(supported_types())})"])
    migrated = _migrate_legacy(dict(data))
    if "shipping_amount" in migrated:
        migrated = {**migrated, "other_fields": dict(migrated.get("other_fields") or {})}
        value = migrated.pop("shipping_amount")
        if value is not None:
            migrated["other_fields"].setdefault("shipping_amount", str(value))
    truncated, warnings = enforce_limits(migrated)
    return schema.model_validate(truncated), warnings


def validate_document(data, format_issues=None, position_issues=None):
    result = {"valid": False, "document_type": None, "model": None,
              "schema_errors": [], "rule_errors": [], "warnings": [], "flags": [],
              "comparison_incomplete": False}
    if not isinstance(data, dict):
        result["schema_errors"] = ["Dữ liệu trích xuất phải là object"]
        return result
    document_type = data.get("document_type")
    result["document_type"] = document_type
    try:
        model, warnings = _dung_model(data)
    except ValidationError as exc:
        result["schema_errors"] = [f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()]
        return result
    except _LoiDung as exc:
        result["schema_errors"] = exc.loi
        return result
    except (ValueError, TypeError, AttributeError) as exc:
        result["schema_errors"] = [f"Cấu trúc dữ liệu không hợp lệ: {exc}"]
        return result
    result.update(valid=True, model=model, comparison_incomplete=bool(warnings))
    result["warnings"] = warnings
    co = business_flags(model, incomplete=bool(warnings))
    for muc in format_issues or []:
        truong = muc.get("field") if isinstance(muc, dict) else None
        if truong:
            co.append({"code": "ai_format", "field": truong,
                       "message": f"AI trả {truong} sai định dạng nên đã bỏ trống — xem chứng từ gốc và nhập lại",
                       "values": {"gia_tri_goc": muc.get("value")}, "formula": None})
    for muc in position_issues or []:
        if isinstance(muc, dict) and muc.get("field") and muc.get("message"):
            co.append({"code": "vi_tri", "field": muc["field"], "message": muc["message"],
                       "values": {"gia_tri_ai": muc.get("value")}, "formula": None})
    result["flags"] = co
    return result


def _number(value):
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def business_flags(model: BaseModel, incomplete: bool = False) -> list[dict]:
    from schemas.document import DOC_NUMBER_PATTERN, TAX_CODE_PATTERN
    from types import SimpleNamespace
    model = SimpleNamespace(**{name: getattr(model, name, default) for name, default in {
        "currency": None, "doc_date": None, "seller_tax_code": None, "buyer_tax_code": None,
        "doc_number": None, "order_reference": None, "subtotal": None, "total_amount": None,
        "discount_amount": None, "tax_amount": None, "tables": [],
    }.items()})
    flags = []

    def flag(code, field, message, values=None, formula=None):
        flags.append({"code": code, "field": field, "message": message,
                      "values": values or {}, "formula": formula})

    if model.currency is not None and model.currency not in CURRENCIES:
        flag("currency", "currency", "Cần kiểm tra mã tiền tệ ngoài danh sách hỗ trợ", {"currency": model.currency})
    if isinstance(model.doc_date, date) and model.doc_date > date.today():
        flag("future_date", "doc_date", "Cần kiểm tra doc_date ở tương lai", {"doc_date": str(model.doc_date)})
    for field, pattern in [("seller_tax_code", TAX_CODE_PATTERN), ("buyer_tax_code", TAX_CODE_PATTERN),
                           ("doc_number", DOC_NUMBER_PATTERN), ("order_reference", DOC_NUMBER_PATTERN)]:
        value = getattr(model, field)
        if value is not None and not re.fullmatch(pattern, value):
            flag("format", field, f"Cần kiểm tra định dạng {field}", {field: value})
    for field in ("subtotal", "total_amount", "discount_amount", "tax_amount"):
        value = getattr(model, field)
        if value is not None and (value < 0 or (field in ("subtotal", "total_amount") and value == 0)):
            flag("amount_sign", field, f"Cần kiểm tra giá trị {field}", {field: value})

    for ti, table in enumerate(model.tables):
        headers = {c.role: c.header for c in table.columns if c.role}
        if not {"item_name", "quantity"} <= headers.keys():
            flag("insufficient_data", f"tables.{ti}", "Thiếu cột tên hàng hoặc số lượng; chưa đủ dữ liệu để đối chiếu dòng hàng")
            continue
        if len(headers) != sum(c.role is not None for c in table.columns):
            flag("insufficient_data", f"tables.{ti}", "Nhiều cột cùng vai trò; chưa xác định được cột dùng để đối chiếu")
            continue
        for ri, row in enumerate(table.rows):
            field = f"tables.{ti}.rows.{ri}.{headers['quantity']}"
            so_luong = row.get(headers["quantity"])
            qty = _number(so_luong)
            if so_luong is None:
                flag("insufficient_data", field, "Dòng này chưa có số lượng nên chưa so được với chứng từ khác", {"quantity": None})
            elif qty is None or qty <= 0:
                flag("quantity", field, "Cần kiểm tra quantity không phải số dương", {"quantity": so_luong})
    if incomplete:
        flag("incomplete_document", "tables", "Dữ liệu vượt giới hạn và đã rút gọn; không kết luận tổng hoặc thiếu/thừa trên bản này")
    return flags


def check_business_rules(model: BaseModel) -> list[str]:
    return [flag["message"] for flag in business_flags(model)]
