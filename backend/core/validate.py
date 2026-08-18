from datetime import date

from pydantic import BaseModel, ValidationError

from schemas import (
    CURRENCIES,
    DATE_FIELD_BY_TYPE,
    AcceptanceRecord,
    Invoice,
    PurchaseOrder,
    model_for,
    supported_types,
)


def validate_document(data: dict) -> dict:
    document_type = data.get("document_type")
    schema = model_for(document_type)
    if schema is None:
        return {
            "valid": False,
            "document_type": document_type,
            "model": None,
            "schema_errors": [
                f"document_type không được hỗ trợ: {document_type} "
                f"(hỗ trợ: {', '.join(supported_types())})"
            ],
            "rule_errors": [],
        }

    try:
        model = schema.model_validate(data)
    except ValidationError as exc:
        return {
            "valid": False,
            "document_type": document_type,
            "model": None,
            "schema_errors": [
                f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()
            ],
            "rule_errors": [],
        }

    rule_errors = check_business_rules(model)
    return {
        "valid": not rule_errors,
        "document_type": document_type,
        "model": model,
        "schema_errors": [],
        "rule_errors": rule_errors,
    }


def _rules_purchase_order(model: PurchaseOrder) -> list[str]:
    errors = []
    if model.item_total != model.total_amount:
        errors.append(
            f"Tổng item ({model.item_total}) không khớp total_amount ({model.total_amount})"
        )
    return errors


def _rules_invoice(model: Invoice) -> list[str]:
    errors = []
    expected_item_total = model.subtotal if model.subtotal is not None else model.total_amount
    if model.item_total != expected_item_total:
        label = "subtotal" if model.subtotal is not None else "total_amount"
        errors.append(
            f"Tổng item ({model.item_total}) không khớp {label} ({expected_item_total})"
        )
    if model.subtotal is not None and model.tax_amount is not None:
        if model.subtotal + model.tax_amount != model.total_amount:
            errors.append("subtotal + tax_amount != total_amount")
    return errors


def _rules_acceptance_record(model: AcceptanceRecord) -> list[str]:
    return []


RULES_BY_TYPE = {
    "purchase_order": _rules_purchase_order,
    "invoice": _rules_invoice,
    "acceptance_record": _rules_acceptance_record,
}


def check_business_rules(model: BaseModel) -> list[str]:
    errors: list[str] = []
    document_type = getattr(model, "document_type", None)

    currency = getattr(model, "currency", None)
    if currency is not None and currency not in CURRENCIES:
        errors.append(f"currency không hợp lệ: {currency}")

    date_field = DATE_FIELD_BY_TYPE.get(document_type)
    if date_field:
        value = getattr(model, date_field, None)
        if isinstance(value, date) and value > date.today():
            errors.append(f"{date_field} ở tương lai")

    checker = RULES_BY_TYPE.get(document_type)
    if checker:
        errors.extend(checker(model))

    return errors
