"""Chấm điểm field-level giữa dữ liệu trích xuất và ground truth.

Nguyên tắc: đo bằng chương trình, không đánh giá bằng mắt (rule cứng của project).
"""

import re
import unicodedata

SCALAR_IGNORE = {"confidence"}
ITEM_FIELDS = ["quantity", "unit_price", "unit"]


def normalize(value):
    """Chuẩn hoá nhẹ để không phạt oan khác biệt vô nghĩa.

    Số: bỏ dấu phân cách. Chuỗi: gộp khoảng trắng, bỏ hoa/thường và dấu tiếng
    Việt. KHÔNG chuẩn hoá quá tay — nếu bỏ dấu tiếng Việt mà vẫn sai thì lỗi
    thật, còn nếu chỉ khác dấu thì OCR vẫn có vấn đề nên được tính riêng.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    text = str(value).strip()
    if re.fullmatch(r"-?[\d.,\s]+", text) and any(c.isdigit() for c in text):
        cleaned = re.sub(r"[^\d\-]", "", text)
        if cleaned not in ("", "-"):
            return round(float(cleaned), 2)
    text = re.sub(r"\s+", " ", text).lower()
    return text


def strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )


def compare_value(expected, actual) -> str:
    """Trả về: 'exact' | 'accent' | 'wrong' | 'missing'."""
    if actual is None or actual == "":
        return "missing" if expected not in (None, "") else "exact"
    left, right = normalize(expected), normalize(actual)
    if left == right:
        return "exact"
    if isinstance(left, str) and isinstance(right, str):
        if strip_accents(left) == strip_accents(right):
            return "accent"
    return "wrong"


def _flatten(data: dict) -> dict:
    """Trải phẳng document thành {field_path: value}, gồm cả line items."""
    flat = {}
    for key, value in (data or {}).items():
        if key in SCALAR_IGNORE:
            continue
        if key == "items" and isinstance(value, list):
            for item in value:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("item_name", "")).strip().lower()
                flat[f"items[{name}]"] = item.get("item_name")
                for field in ITEM_FIELDS:
                    if field in item:
                        flat[f"items[{name}].{field}"] = item[field]
        elif not isinstance(value, (dict, list)):
            flat[key] = value
    return flat


def score_document(expected: dict, actual: dict) -> dict:
    """So 1 document. Mẫu số là số field trong ground truth."""
    expected_flat = _flatten(expected)
    actual_flat = _flatten(actual)

    per_field = {}
    for field, value in expected_flat.items():
        per_field[field] = compare_value(value, actual_flat.get(field))

    extra = sorted(set(actual_flat) - set(expected_flat))
    counts = {"exact": 0, "accent": 0, "wrong": 0, "missing": 0}
    for verdict in per_field.values():
        counts[verdict] += 1

    total = len(per_field) or 1
    return {
        "per_field": per_field,
        "counts": counts,
        "total_fields": len(per_field),
        "extra_fields": extra,
        "accuracy": counts["exact"] / total,
        "accuracy_bo_dau": (counts["exact"] + counts["accent"]) / total,
        "document_type_dung": expected.get("document_type") == actual.get("document_type"),
    }


def aggregate(results: list[dict]) -> dict:
    """Gộp điểm nhiều document. Cộng dồn field, không lấy trung bình của trung bình."""
    counts = {"exact": 0, "accent": 0, "wrong": 0, "missing": 0}
    total = 0
    type_dung = 0
    field_errors: dict[str, int] = {}

    for result in results:
        for key, value in result["counts"].items():
            counts[key] += value
        total += result["total_fields"]
        type_dung += 1 if result["document_type_dung"] else 0
        for field, verdict in result["per_field"].items():
            if verdict != "exact":
                key = field.split("[")[0] if "[" in field else field
                field_errors[key] = field_errors.get(key, 0) + 1

    denominator = total or 1
    return {
        "so_document": len(results),
        "tong_field": total,
        "counts": counts,
        "accuracy": counts["exact"] / denominator,
        "accuracy_bo_dau": (counts["exact"] + counts["accent"]) / denominator,
        "classify_accuracy": type_dung / (len(results) or 1),
        "field_hay_sai": sorted(field_errors.items(), key=lambda kv: -kv[1])[:10],
    }
