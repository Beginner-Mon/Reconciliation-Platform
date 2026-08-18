from pydantic import BaseModel

from .acceptance_record import AcceptanceRecord
from .invoice import Invoice
from .purchase_order import PurchaseOrder

DOCUMENT_TYPES: dict[str, type[BaseModel]] = {
    "purchase_order": PurchaseOrder,
    "invoice": Invoice,
    "acceptance_record": AcceptanceRecord,
}

DOCUMENT_TYPE_LABELS = {
    "purchase_order": "đơn đặt hàng",
    "invoice": "hóa đơn",
    "acceptance_record": "biên bản nghiệm thu",
}

DATE_FIELD_BY_TYPE = {
    "purchase_order": "po_date",
    "invoice": "invoice_date",
    "acceptance_record": "record_date",
}

NUMBER_FIELD_BY_TYPE = {
    "purchase_order": "po_number",
    "invoice": "invoice_number",
    "acceptance_record": "record_number",
}


def supported_types() -> list[str]:
    return list(DOCUMENT_TYPES)


def model_for(document_type: str) -> type[BaseModel] | None:
    return DOCUMENT_TYPES.get(document_type)


def _describe_field(name: str, spec: dict, defs: dict) -> str:
    ref = spec.get("$ref") or next(
        (o.get("$ref") for o in spec.get("anyOf", []) if "$ref" in o), None
    )
    if spec.get("type") == "array":
        item_ref = spec.get("items", {}).get("$ref")
        if item_ref:
            nested = defs.get(item_ref.rsplit("/", 1)[-1], {})
            inner = ", ".join(nested.get("properties", {}))
            return f"{name} [{{{inner}}}]"
        return f"{name} []"
    if ref:
        nested = defs.get(ref.rsplit("/", 1)[-1], {})
        inner = ", ".join(nested.get("properties", {}))
        return f"{name} {{{inner}}}"

    types = [spec["type"]] if "type" in spec else [
        o["type"] for o in spec.get("anyOf", []) if o.get("type") != "null"
    ]
    hint = {"integer": "int", "number": "float", "string": "str", "boolean": "bool"}
    rendered = "|".join(hint.get(t, t) for t in types) or "str"
    if spec.get("format") == "date" or any(
        o.get("format") == "date" for o in spec.get("anyOf", [])
    ):
        rendered = "YYYY-MM-DD"
    return f"{name} ({rendered})"


def describe_type(document_type: str) -> str:
    model = DOCUMENT_TYPES[document_type]
    schema = model.model_json_schema()
    defs = schema.get("$defs", {})
    required = set(schema.get("required", []))
    fields = []
    for name, spec in schema.get("properties", {}).items():
        if name == "document_type":
            continue
        text = _describe_field(name, spec, defs)
        fields.append(text if name in required else f"{text} [tùy chọn]")
    return ", ".join(fields)


def describe_all_types() -> str:
    blocks = []
    for document_type in DOCUMENT_TYPES:
        label = DOCUMENT_TYPE_LABELS.get(document_type, document_type)
        blocks.append(
            f'Nếu loại "{document_type}" ({label}), các trường data:\n{describe_type(document_type)}'
        )
    return "\n\n".join(blocks)
