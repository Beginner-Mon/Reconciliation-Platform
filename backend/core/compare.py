import re
import unicodedata
from dataclasses import dataclass, field

from .numbers import parse_cell
from .rules import Discrepancy, DiscrepancyValue, DocumentRef, label, _fmt


@dataclass
class Alignment:
    row_pairs: list[tuple[int, int]] = field(default_factory=list)
    field_pairs: list[tuple[str, str]] = field(default_factory=list)


def _chuan_hoa(text: str) -> str:
    if not isinstance(text, str):
        text = str(text)
    # NFD bỏ dấu, lower, gộp whitespace
    nfd = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    collapsed = re.sub(r"\s+", " ", stripped).strip().lower()
    return collapsed


def _get_role_header(table, role: str) -> str | None:
    for col in table.columns:
        if col.role == role:
            return col.header
    return None


def _extract_items(model):
    items = []
    for ti, table in enumerate(getattr(model, "tables", []) or []):
        h_name = _get_role_header(table, "item_name")
        h_qty = _get_role_header(table, "quantity")
        h_unit = _get_role_header(table, "unit")
        h_price = _get_role_header(table, "unit_price")
        h_amount = _get_role_header(table, "amount")
        if not h_name or not h_qty:
            continue
        for ri, row in enumerate(table.rows):
            name = row.get(h_name)
            qty = row.get(h_qty)
            if name is None or qty is None:
                continue
            # Đọc số qua core/numbers.py: ô "$42.00" là 42 chứ không phải ô trống.
            qty_f = parse_cell(qty)
            if qty_f is None:
                continue
            qty_f = float(qty_f)
            price = parse_cell(row.get(h_price)) if h_price else None
            price_i = int(price) if price is not None else None
            amount = parse_cell(row.get(h_amount)) if h_amount else None
            amount_i = int(amount) if amount is not None else None
            unit = row.get(h_unit) if h_unit else None
            items.append({
                "table_idx": ti,
                "row_idx": ri,
                "item_name": str(name),
                "quantity": qty_f,
                "unit": str(unit) if unit else None,
                "unit_price": price_i,
                "amount": amount_i,
                "row": row,
                "header_name": h_name,
            })
    return items


def _quantity_by_key(items: list[dict]) -> dict[tuple[str, str], float]:
    totals: dict[tuple[str, str], float] = {}
    for it in items:
        key = (_chuan_hoa(it["item_name"]), _chuan_hoa(it["unit"] or ""))
        totals[key] = totals.get(key, 0) + (it["quantity"] or 0)
    return totals


def _unit_price_by_key(items: list[dict]) -> dict[tuple[str, str], set[int]]:
    prices: dict[tuple[str, str], set[int]] = {}
    for it in items:
        if it["unit_price"] is not None:
            key = (_chuan_hoa(it["item_name"]), _chuan_hoa(it["unit"] or ""))
            prices.setdefault(key, set()).add(it["unit_price"])
    return prices


def _display_for_key(items: list[dict], key: tuple[str, str]) -> str:
    for it in items:
        if (_chuan_hoa(it["item_name"]), _chuan_hoa(it["unit"] or "")) == key:
            return it["item_name"]
    return key[0]


def build_deterministic_alignment(anchor: DocumentRef, other: DocumentRef) -> Alignment:
    # P2: ghép dự phòng deterministic theo (tên chuẩn hoá, đơn vị)
    anchor_items = _extract_items(anchor.model)
    other_items = _extract_items(other.model)
    anchor_keys = list(_quantity_by_key(anchor_items).keys())
    other_keys = list(_quantity_by_key(other_items).keys())
    # row_pairs ở mức key — mỗi key là một nhóm dòng
    # Để giữ dạng row index, ta map từng key tới list row idx, nhưng ở đây dùng key index
    # Đơn giản: pair theo key giao nhau
    paired_keys = set(anchor_keys) & set(other_keys)
    # field_pairs: header fields chung
    field_pairs = []
    for f in ["seller", "seller_tax_code", "buyer", "currency"]:
        if anchor.has(f) and other.has(f):
            field_pairs.append((f, f))
    # row_pairs: dùng index của key trong danh sách unique
    # Để tương thích với spec row index, ta dùng vị trí key
    row_pairs = []
    for idx, key in enumerate(sorted(paired_keys)):
        # tìm vị trí key trong anchor/other unique lists
        try:
            ai = sorted(anchor_keys).index(key)
            oi = sorted(other_keys).index(key)
            row_pairs.append((ai, oi))
        except ValueError:
            continue
    return Alignment(row_pairs=row_pairs, field_pairs=field_pairs)


def _has_priced_items(model) -> bool:
    for it in _extract_items(model):
        if it["unit_price"] is not None:
            return True
    return False


def compare_pair(anchor: DocumentRef, other: DocumentRef, alignment: Alignment | None = None) -> list[Discrepancy]:
    if alignment is None:
        alignment = build_deterministic_alignment(anchor, other)

    anchor_items = _extract_items(anchor.model)
    other_items = _extract_items(other.model)

    # Nếu một trong hai không có bảng so được → vẫn VALIDATED nhưng báo lý do
    anchor_has_table = bool(anchor_items)
    other_has_table = bool(other_items)
    if not anchor_has_table or not other_has_table:
        # Không so dòng, chỉ so header
        pass

    found: list[Discrepancy] = []
    anchor_id = anchor.document_id

    # So header fields với gốc
    for f in ["seller", "seller_tax_code", "buyer", "currency"]:
        av = anchor.get(f)
        ov = other.get(f)
        if av is None or ov is None:
            continue
        if str(av).strip() != str(ov).strip():
            found.append(Discrepancy(
                rule_id=f"anchor_{f}_mismatch",
                field=f,
                severity="critical" if f in ("seller", "currency") else "medium",
                values=[
                    DiscrepancyValue(anchor.document_id, anchor.document_type, av),
                    DiscrepancyValue(other.document_id, other.document_type, ov),
                ],
                explanation=f"{f} không khớp: Gốc ({label(anchor.document_type)})={_fmt(av)} — Bên kia ({label(other.document_type)})={_fmt(ov)}",
                anchor_document_id=anchor_id,
                source="rule",
            ))

    # So total_amount chỉ khi cả 2 có đơn giá
    if _has_priced_items(anchor.model) and _has_priced_items(other.model):
        av = anchor.get("total_amount")
        ov = other.get("total_amount")
        if isinstance(av, (int, float)) and isinstance(ov, (int, float)) and av != ov:
            found.append(Discrepancy(
                rule_id="anchor_total_amount_mismatch",
                field="total_amount",
                severity="high",
                values=[
                    DiscrepancyValue(anchor.document_id, anchor.document_type, av),
                    DiscrepancyValue(other.document_id, other.document_type, ov),
                ],
                difference=ov - av,
                explanation=f"Tổng tiền không khớp: Gốc={_fmt(av)} — Bên kia={_fmt(ov)} lệch {_fmt(ov-av)}",
                anchor_document_id=anchor_id,
                source="rule",
            ))

    # So dòng theo key
    anchor_totals = _quantity_by_key(anchor_items)
    other_totals = _quantity_by_key(other_items)
    anchor_prices = _unit_price_by_key(anchor_items)
    other_prices = _unit_price_by_key(other_items)

    all_keys = set(anchor_totals) | set(other_totals)

    for key in all_keys:
        display = _display_for_key(anchor_items + other_items, key)
        a_qty = anchor_totals.get(key, 0)
        o_qty = other_totals.get(key, 0)
        # Thiếu / thừa so với gốc
        if key not in other_totals:
            found.append(Discrepancy(
                rule_id="line_missing_vs_anchor",
                field=f"items.{display}.quantity",
                severity="high",
                values=[
                    DiscrepancyValue(anchor.document_id, anchor.document_type, a_qty),
                    DiscrepancyValue(other.document_id, other.document_type, 0),
                ],
                difference=o_qty - a_qty,
                explanation=f"'{display}': thiếu so với gốc — Gốc: {_fmt(a_qty)} — Bên kia: 0",
                anchor_document_id=anchor_id,
                source="rule",
            ))
            continue
        if key not in anchor_totals:
            found.append(Discrepancy(
                rule_id="line_extra_vs_anchor",
                field=f"items.{display}.quantity",
                severity="high",
                values=[
                    DiscrepancyValue(anchor.document_id, anchor.document_type, 0),
                    DiscrepancyValue(other.document_id, other.document_type, o_qty),
                ],
                difference=o_qty,
                explanation=f"'{display}': thừa so với gốc — Gốc: 0 — Bên kia: {_fmt(o_qty)}",
                anchor_document_id=anchor_id,
                source="rule",
            ))
            continue
        # Đã ghép: so số lượng dung sai 0
        if abs(a_qty - o_qty) > 1e-9:
            found.append(Discrepancy(
                rule_id="line_quantity_mismatch",
                field=f"items.{display}.quantity",
                severity="high",
                values=[
                    DiscrepancyValue(anchor.document_id, anchor.document_type, a_qty),
                    DiscrepancyValue(other.document_id, other.document_type, o_qty),
                ],
                difference=o_qty - a_qty,
                explanation=f"'{display}': số lượng lệch — Gốc: {_fmt(a_qty)} — Bên kia: {_fmt(o_qty)}",
                anchor_document_id=anchor_id,
                source="rule",
            ))
        # So đơn giá khi cả 2 có
        a_prices = anchor_prices.get(key, set())
        o_prices = other_prices.get(key, set())
        if a_prices and o_prices:
            # Nếu mỗi bên có 1 giá duy nhất và khác nhau
            if len(a_prices) == 1 and len(o_prices) == 1 and next(iter(a_prices)) != next(iter(o_prices)):
                ap = next(iter(a_prices)); op = next(iter(o_prices))
                found.append(Discrepancy(
                    rule_id="line_unit_price_mismatch",
                    field=f"items.{display}.unit_price",
                    severity="high",
                    values=[
                        DiscrepancyValue(anchor.document_id, anchor.document_type, ap),
                        DiscrepancyValue(other.document_id, other.document_type, op),
                    ],
                    difference=op - ap,
                    explanation=f"'{display}' lệch đơn giá: Gốc={_fmt(ap)} — Bên kia={_fmt(op)}",
                    anchor_document_id=anchor_id,
                    source="rule",
                ))
        # So đơn vị
        a_units = { _chuan_hoa(it["unit"] or "") for it in anchor_items if (_chuan_hoa(it["item_name"]), _chuan_hoa(it["unit"] or "")) == key }
        o_units = { _chuan_hoa(it["unit"] or "") for it in other_items if (_chuan_hoa(it["item_name"]), _chuan_hoa(it["unit"] or "")) == key }
        if a_units != o_units:
            # đơn vị khác nhau đã thể hiện qua key, nhưng nếu cùng tên khác đơn vị thì key đã khác → đã báo missing/extra rồi
            pass

    return found


def check_chain_billing_vs_delivery(group_docs: list[DocumentRef], anchor: DocumentRef) -> list[Discrepancy]:
    # billing ≤ delivery qua gốc chung
    # Tìm tất cả delivery và billing trong group
    delivery_docs = [d for d in group_docs if getattr(d.model, "role", None) == "delivery"]
    billing_docs = [d for d in group_docs if getattr(d.model, "role", None) == "billing"]
    if not delivery_docs or not billing_docs:
        return []
    # Tổng theo key
    delivery_totals = {}
    for d in delivery_docs:
        for k, v in _quantity_by_key(_extract_items(d.model)).items():
            delivery_totals[k] = delivery_totals.get(k, 0) + v
    billing_totals = {}
    for d in billing_docs:
        for k, v in _quantity_by_key(_extract_items(d.model)).items():
            billing_totals[k] = billing_totals.get(k, 0) + v
    found = []
    for key, b_qty in billing_totals.items():
        allowed = delivery_totals.get(key, 0)
        # missing_is_zero True: nếu billing có mà delivery không có → coi delivery 0 và báo
        if b_qty > allowed + 1e-9:
            display = _display_for_key(
                [it for d in delivery_docs + billing_docs for it in _extract_items(d.model)], key
            )
            found.append(Discrepancy(
                rule_id="billing_over_delivery",
                field=f"items.{display}.quantity",
                severity="critical",
                values=[
                    DiscrepancyValue(d.document_id, d.document_type, _quantity_by_key(_extract_items(d.model)).get(key, 0))
                    for d in delivery_docs + billing_docs
                ],
                difference=b_qty - allowed,
                explanation=f"'{display}': hoá đơn tổng {_fmt(b_qty)} nhưng nghiệm thu tổng {_fmt(allowed)} — vượt {_fmt(b_qty-allowed)}",
                anchor_document_id=anchor.document_id if anchor else None,
                source="rule",
            ))
    return found
