from dataclasses import dataclass, field
from datetime import date

from pydantic import BaseModel

from schemas import DATE_FIELD_BY_TYPE, DOCUMENT_TYPE_LABELS

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def label(document_type: str) -> str:
    return DOCUMENT_TYPE_LABELS.get(document_type, document_type)


def _fmt(value: object) -> str:
    if isinstance(value, bool) or value is None:
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


@dataclass
class DocumentRef:
    document_id: str
    document_type: str
    model: BaseModel

    def get(self, name: str):
        return getattr(self.model, name, None)

    def has(self, name: str) -> bool:
        return self.get(name) is not None


@dataclass
class DiscrepancyValue:
    document_id: str
    document_type: str
    value: object

    def to_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "document_type": self.document_type,
            "value": self.value,
        }


@dataclass
class Discrepancy:
    rule_id: str
    field: str
    severity: str
    values: list[DiscrepancyValue] = field(default_factory=list)
    difference: object | None = None
    explanation: str = ""

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "field": self.field,
            "severity": self.severity,
            "values": [v.to_dict() for v in self.values],
            "difference": self.difference,
            "explanation": self.explanation,
        }


@dataclass
class DocumentGroup:
    key: str | None
    documents: list[DocumentRef] = field(default_factory=list)

    def by_type(self, document_type: str) -> list[DocumentRef]:
        return [d for d in self.documents if d.document_type == document_type]

    def first(self, document_type: str) -> DocumentRef | None:
        found = self.by_type(document_type)
        return found[0] if found else None

    def having(self, name: str) -> list[DocumentRef]:
        return [d for d in self.documents if d.has(name)]

    @property
    def types(self) -> set[str]:
        return {d.document_type for d in self.documents}


class Rule:
    rule_id = "rule"
    severity = "medium"

    def evaluate(self, group: DocumentGroup) -> list[Discrepancy]:
        raise NotImplementedError


class AgreeRule(Rule):
    def __init__(self, field_name: str, severity: str = "high"):
        self.field_name = field_name
        self.rule_id = f"agree_{field_name}"
        self.severity = severity

    def evaluate(self, group: DocumentGroup) -> list[Discrepancy]:
        holders = group.having(self.field_name)
        if len(holders) < 2:
            return []
        values = {d.get(self.field_name) for d in holders}
        if len(values) == 1:
            return []
        rendered = " / ".join(
            f"{label(d.document_type)}={_fmt(d.get(self.field_name))}" for d in holders
        )
        return [
            Discrepancy(
                rule_id=self.rule_id,
                field=self.field_name,
                severity=self.severity,
                values=[
                    DiscrepancyValue(d.document_id, d.document_type, d.get(self.field_name))
                    for d in holders
                ],
                explanation=f"{self.field_name} không khớp giữa các chứng từ: {rendered}",
            )
        ]


class NumericRule(Rule):
    def __init__(self, field_name: str, severity: str = "high", tolerance: int = 0):
        self.field_name = field_name
        self.rule_id = f"match_{field_name}"
        self.severity = severity
        self.tolerance = tolerance

    def evaluate(self, group: DocumentGroup) -> list[Discrepancy]:
        holders = [d for d in group.having(self.field_name) if isinstance(d.get(self.field_name), (int, float))]
        if len(holders) < 2:
            return []
        amounts = [d.get(self.field_name) for d in holders]
        spread = max(amounts) - min(amounts)
        if spread <= self.tolerance:
            return []
        rendered = " / ".join(
            f"{label(d.document_type)}={_fmt(d.get(self.field_name))}" for d in holders
        )
        return [
            Discrepancy(
                rule_id=self.rule_id,
                field=self.field_name,
                severity=self.severity,
                values=[
                    DiscrepancyValue(d.document_id, d.document_type, d.get(self.field_name))
                    for d in holders
                ],
                difference=spread,
                explanation=f"{self.field_name} lệch {_fmt(spread)}: {rendered}",
            )
        ]


def _items_by_name(doc: DocumentRef) -> dict[str, object]:
    items = doc.get("items") or []
    return {i.item_name.lower().strip(): i for i in items}


def _is_priced(doc: DocumentRef) -> bool:
    items = doc.get("items") or []
    return bool(items) and hasattr(items[0], "unit_price")


class LineItemRule(Rule):
    rule_id = "line_item_match"
    severity = "high"

    def evaluate(self, group: DocumentGroup) -> list[Discrepancy]:
        priced = [d for d in group.documents if _is_priced(d)]
        if len(priced) < 2:
            return []

        base = priced[0]
        found: list[Discrepancy] = []
        base_items = _items_by_name(base)

        for other in priced[1:]:
            other_items = _items_by_name(other)

            for name, item in base_items.items():
                counterpart = other_items.get(name)
                if counterpart is None:
                    found.append(
                        Discrepancy(
                            rule_id="line_item_missing",
                            field=f"items.{item.item_name}",
                            severity="high",
                            values=[
                                DiscrepancyValue(base.document_id, base.document_type, item.quantity),
                                DiscrepancyValue(other.document_id, other.document_type, None),
                            ],
                            explanation=(
                                f"Mặt hàng '{item.item_name}' có trong {label(base.document_type)} "
                                f"nhưng thiếu trong {label(other.document_type)}"
                            ),
                        )
                    )
                    continue
                for attr, severity in (("unit_price", "high"), ("quantity", "high")):
                    left = getattr(item, attr, None)
                    right = getattr(counterpart, attr, None)
                    if left is None or right is None or left == right:
                        continue
                    found.append(
                        Discrepancy(
                            rule_id=f"line_item_{attr}",
                            field=f"items.{item.item_name}.{attr}",
                            severity=severity,
                            values=[
                                DiscrepancyValue(base.document_id, base.document_type, left),
                                DiscrepancyValue(other.document_id, other.document_type, right),
                            ],
                            difference=right - left,
                            explanation=(
                                f"'{item.item_name}' lệch {attr}: "
                                f"{label(base.document_type)}={_fmt(left)}, "
                                f"{label(other.document_type)}={_fmt(right)}"
                            ),
                        )
                    )

            for name, item in other_items.items():
                if name in base_items:
                    continue
                found.append(
                    Discrepancy(
                        rule_id="line_item_extra",
                        field=f"items.{item.item_name}",
                        severity="high",
                        values=[
                            DiscrepancyValue(base.document_id, base.document_type, None),
                            DiscrepancyValue(other.document_id, other.document_type, item.quantity),
                        ],
                        explanation=(
                            f"Mặt hàng '{item.item_name}' có trong {label(other.document_type)} "
                            f"nhưng không có trong {label(base.document_type)}"
                        ),
                    )
                )

        return found


class QuantityCoverageRule(Rule):
    rule_id = "quantity_coverage"
    severity = "critical"

    def evaluate(self, group: DocumentGroup) -> list[Discrepancy]:
        acceptance = group.first("acceptance_record")
        invoice = group.first("invoice")
        purchase_order = group.first("purchase_order")
        if acceptance is None or invoice is None:
            return []

        accepted = _items_by_name(acceptance)
        invoiced = _items_by_name(invoice)
        ordered = _items_by_name(purchase_order) if purchase_order else {}
        found: list[Discrepancy] = []

        for name, invoice_item in invoiced.items():
            accepted_item = accepted.get(name)
            accepted_qty = accepted_item.quantity if accepted_item else 0
            if invoice_item.quantity > accepted_qty:
                found.append(
                    Discrepancy(
                        rule_id="invoiced_over_accepted",
                        field=f"items.{invoice_item.item_name}.quantity",
                        severity="critical",
                        values=[
                            DiscrepancyValue(acceptance.document_id, "acceptance_record", accepted_qty),
                            DiscrepancyValue(invoice.document_id, "invoice", invoice_item.quantity),
                        ],
                        difference=invoice_item.quantity - accepted_qty,
                        explanation=(
                            f"'{invoice_item.item_name}': xuất hóa đơn {_fmt(invoice_item.quantity)} "
                            f"nhưng chỉ nghiệm thu {_fmt(accepted_qty)}"
                        ),
                    )
                )

        for name, accepted_item in accepted.items():
            ordered_item = ordered.get(name)
            if ordered_item is None:
                continue
            if accepted_item.quantity > ordered_item.quantity:
                found.append(
                    Discrepancy(
                        rule_id="accepted_over_ordered",
                        field=f"items.{accepted_item.item_name}.quantity",
                        severity="high",
                        values=[
                            DiscrepancyValue(purchase_order.document_id, "purchase_order", ordered_item.quantity),
                            DiscrepancyValue(acceptance.document_id, "acceptance_record", accepted_item.quantity),
                        ],
                        difference=accepted_item.quantity - ordered_item.quantity,
                        explanation=(
                            f"'{accepted_item.item_name}': nghiệm thu {_fmt(accepted_item.quantity)} "
                            f"vượt số lượng đặt hàng {_fmt(ordered_item.quantity)}"
                        ),
                    )
                )

        return found


class DateOrderRule(Rule):
    rule_id = "date_order"
    severity = "medium"

    def __init__(self, sequence: list[str] | None = None):
        self.sequence = sequence or ["purchase_order", "acceptance_record", "invoice"]

    def evaluate(self, group: DocumentGroup) -> list[Discrepancy]:
        points = []
        for document_type in self.sequence:
            doc = group.first(document_type)
            if doc is None:
                continue
            value = doc.get(DATE_FIELD_BY_TYPE.get(document_type, ""))
            if isinstance(value, date):
                points.append((doc, value))

        found: list[Discrepancy] = []
        for (earlier_doc, earlier), (later_doc, later) in zip(points, points[1:]):
            if earlier <= later:
                continue
            found.append(
                Discrepancy(
                    rule_id=self.rule_id,
                    field="date_order",
                    severity=self.severity,
                    values=[
                        DiscrepancyValue(earlier_doc.document_id, earlier_doc.document_type, earlier.isoformat()),
                        DiscrepancyValue(later_doc.document_id, later_doc.document_type, later.isoformat()),
                    ],
                    difference=(earlier - later).days,
                    explanation=(
                        f"Ngày {label(later_doc.document_type)} ({later.isoformat()}) "
                        f"sớm hơn ngày {label(earlier_doc.document_type)} ({earlier.isoformat()})"
                    ),
                )
            )
        return found


class ReferenceExistsRule(Rule):
    rule_id = "po_reference_missing"
    severity = "high"

    def evaluate(self, group: DocumentGroup) -> list[Discrepancy]:
        if group.key is None:
            return []
        if group.first("purchase_order") is not None:
            return []
        referrers = [d for d in group.documents if d.has("po_number")]
        if not referrers:
            return []
        return [
            Discrepancy(
                rule_id=self.rule_id,
                field="po_number",
                severity=self.severity,
                values=[
                    DiscrepancyValue(d.document_id, d.document_type, group.key) for d in referrers
                ],
                explanation=(
                    f"Đơn đặt hàng {group.key} được tham chiếu nhưng không có trong project"
                ),
            )
        ]


CROSS_RULES: list[Rule] = [
    AgreeRule("vendor", severity="critical"),
    AgreeRule("currency", severity="critical"),
    AgreeRule("vendor_tax_code", severity="medium"),
    AgreeRule("buyer", severity="medium"),
    NumericRule("total_amount", severity="high"),
    LineItemRule(),
    QuantityCoverageRule(),
    DateOrderRule(),
    ReferenceExistsRule(),
]
