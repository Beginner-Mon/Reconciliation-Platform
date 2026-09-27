from pydantic import BaseModel

from .document import Document

DOCUMENT_TYPES: dict[str, type[BaseModel]] = {
    "document": Document,
    "purchase_order": Document,
    "invoice": Document,
    "acceptance_record": Document,
    "unknown": Document,
    "quotation": Document,
    "delivery_note": Document,
    "contract": Document,
    "other": Document,
}

# Nhãn ĐỌC CHO NGƯỜI.
DOCUMENT_TYPE_LABELS = {
    "document": "chứng từ",
    "purchase_order": "đơn đặt hàng",
    "invoice": "hóa đơn",
    "acceptance_record": "biên bản nghiệm thu",
    "unknown": "chưa phân loại",
}

DOCUMENT_TYPE_PROMPT_NOTES = {
    "document": "Trích nguyên văn tên cột bảng, gán role cho cột: item_name, quantity, unit, unit_price, amount. discount_amount (int) - tổng chiết khấu thương mại; subtotal = tiền hàng sau chiết khấu, chưa thuế",
    "invoice": "discount_amount (int) - tổng chiết khấu thương mại; subtotal = tiền hàng sau chiết khấu, chưa thuế",
    "unknown": "CHỈ chọn loại này khi tài liệu KHÔNG khớp bất kỳ loại nào ở trên",
}

DATE_FIELD_BY_TYPE = {
    "document": "doc_date",
    "purchase_order": "doc_date",
    "invoice": "doc_date",
    "acceptance_record": "doc_date",
    "unknown": "doc_date",
}

NUMBER_FIELD_BY_TYPE = {
    "document": "doc_number",
    "purchase_order": "doc_number",
    "invoice": "doc_number",
    "acceptance_record": "doc_number",
    "unknown": "doc_number",
}

ROLE_LABELS = {
    "order": "đặt hàng",
    "offer": "báo giá",
    "delivery": "giao/ nghiệm thu",
    "billing": "thanh toán",
    "other": "khác",
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
        note = DOCUMENT_TYPE_PROMPT_NOTES.get(document_type)
        heading = f'Nếu loại "{document_type}" ({label})'
        if note:
            heading += f" — {note}"
        blocks.append(f"{heading}, các trường data:\n{describe_type(document_type)}")
    return "\n\n".join(blocks)
