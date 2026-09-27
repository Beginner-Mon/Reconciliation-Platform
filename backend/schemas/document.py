from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from .purchase_order import DOC_NUMBER_PATTERN as DOC_NUMBER_PATTERN, TAX_CODE_PATTERN as TAX_CODE_PATTERN

__all__ = ["Document", "Column", "Table", "enforce_limits", "DOC_NUMBER_PATTERN", "TAX_CODE_PATTERN"]

COLUMN_ROLES = {"item_name", "quantity", "unit", "unit_price", "amount"}
DOCUMENT_ROLES = {"order", "offer", "delivery", "billing", "other"}

MAX_TABLES = 3
MAX_COLS = 25
MAX_ROWS = 500
MAX_CELL = 500


class Column(BaseModel):
    header: str = Field(min_length=1, max_length=100)
    role: Literal["item_name", "quantity", "unit", "unit_price", "amount"] | None = None


class Table(BaseModel):
    columns: list[Column] = Field(min_length=1, max_length=25)
    rows: list[dict[str, str | int | float | None]] = Field(default_factory=list, max_length=500)


class Document(BaseModel):
    document_type: str = Field(min_length=1, max_length=100)
    role: Literal["order", "offer", "delivery", "billing", "other"] = "other"
    doc_number: str | None = None
    doc_date: date | None = None
    order_reference: str | None = None
    seller: str | None = Field(default=None, max_length=200)
    seller_tax_code: str | None = None
    buyer: str | None = Field(default=None, max_length=200)
    buyer_tax_code: str | None = None
    currency: str | None = None
    subtotal: int | None = None
    discount_amount: int | None = None
    tax_amount: int | None = None
    total_amount: int | None = None
    other_fields: dict[str, str] = Field(default_factory=dict)
    tables: list[Table] = Field(default_factory=list, max_length=3)

    model_config = {"extra": "forbid"}


def enforce_limits(data: dict) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    tables = data.get("tables") or []
    if not isinstance(tables, list):
        raise ValueError("tables phải là danh sách")
    for table in tables:
        if not isinstance(table, dict):
            raise ValueError("Mỗi bảng phải là object")
        if not isinstance(table.get("columns", []), list) or not isinstance(table.get("rows", []), list):
            raise ValueError("columns và rows phải là danh sách")
        if any(not isinstance(c, dict) for c in table.get("columns", [])):
            raise ValueError("Mỗi cột phải là object")
        if any(not isinstance(r, dict) for r in table.get("rows", [])):
            raise ValueError("Mỗi dòng phải là object")
    if not isinstance(data.get("other_fields", {}), dict):
        raise ValueError("other_fields phải là object")
    if len(tables) > MAX_TABLES:
        warnings.append(f"Chỉ giữ {MAX_TABLES} bảng đầu, bỏ {len(tables)-MAX_TABLES} bảng")
        tables = tables[:MAX_TABLES]
    new_tables = []
    for ti, table in enumerate(tables):
        cols = table.get("columns") or []
        rows = table.get("rows") or []
        if len(cols) > MAX_COLS:
            warnings.append(f"Bảng {ti}: chỉ giữ {MAX_COLS} cột đầu, bỏ {len(cols)-MAX_COLS} cột")
            cols = cols[:MAX_COLS]
            col_headers = {c.get("header") for c in cols}
            rows = [{k: v for k, v in r.items() if k in col_headers} for r in rows]
        if len(rows) > MAX_ROWS:
            warnings.append(f"Bảng {ti}: chỉ giữ {MAX_ROWS} dòng đầu, bỏ {len(rows)-MAX_ROWS} dòng")
            rows = rows[:MAX_ROWS]
        # cell truncation
        truncated_rows = []
        for ri, row in enumerate(rows):
            new_row = {}
            for k, v in row.items():
                if isinstance(v, str) and len(v) > MAX_CELL:
                    warnings.append(f"Bảng {ti} dòng {ri} cột '{k}' cắt từ {len(v)} về {MAX_CELL} ký tự")
                    new_row[k] = v[:MAX_CELL]
                else:
                    new_row[k] = v
            truncated_rows.append(new_row)
        # other_fields truncation
        new_tables.append({"columns": cols, "rows": truncated_rows})
    data = {**data, "tables": new_tables}
    # other_fields cell truncation
    other = data.get("other_fields") or {}
    new_other = {}
    for k, v in other.items():
        if isinstance(v, str) and len(v) > MAX_CELL:
            warnings.append(f"other_fields '{k}' cắt từ {len(v)} về {MAX_CELL} ký tự")
            new_other[k] = v[:MAX_CELL]
        else:
            new_other[k] = v
    data["other_fields"] = new_other
    return data, warnings
