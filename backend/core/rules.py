from dataclasses import dataclass, field
from datetime import date

from pydantic import BaseModel

from schemas import DATE_FIELD_BY_TYPE, DOCUMENT_TYPE_LABELS, NUMBER_FIELD_BY_TYPE

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


# --- Cộng dồn cho đối chiếu n–m ---------------------------------------------
#
# Một đơn hàng giao nhiều đợt sinh nhiều hóa đơn. So từng cặp thì đợt nào cũng
# nhỏ hơn đơn hàng và rule nào cũng báo lệch. Phải cộng TỔNG theo vai trò.


def _quantity_by_name(docs: list[DocumentRef]) -> dict[str, float]:
    """Tổng số lượng theo tên mặt hàng, gộp qua NHIỀU chứng từ.

    Khác `_items_by_name`: hàm kia trả về item cuối cùng gặp (dùng để so đôi
    một), ở đây phải cộng dồn chứ không ghi đè.
    """
    totals: dict[str, float] = {}
    for doc in docs:
        for item in doc.get("items") or []:
            name = item.item_name.lower().strip()
            totals[name] = totals.get(name, 0) + (item.quantity or 0)
    return totals


def _item_quantity(doc: DocumentRef, key: str) -> float:
    return sum(
        item.quantity or 0
        for item in doc.get("items") or []
        if item.item_name.lower().strip() == key
    )


def _display_name(docs: list[DocumentRef], key: str) -> str:
    """Tên gốc để hiện cho người đọc — khoá gộp đã bị lowercase/strip."""
    for doc in docs:
        for item in doc.get("items") or []:
            if item.item_name.lower().strip() == key:
                return item.item_name
    return key


def _side(docs: list[DocumentRef], total: float) -> str:
    kinds = " + ".join(sorted({label(d.document_type) for d in docs}))
    return f"{kinds} {_fmt(total)} ({len(docs)} chứng từ)"


class AggregateRule(Rule):
    """ĐẲNG THỨC trên tổng: sum(nguồn) phải khớp sum(đích).

    "Nguồn/đích" là vai trò của rule này, không phải nhãn cố định của loại chứng
    từ — cùng một loại có thể là đích ở rule này và nguồn ở rule khác.

    Chạy đúng cả khi n=1, m=1: tổng của một phần tử là chính nó.
    """

    def __init__(
        self,
        sources: list[str],
        targets: list[str],
        field_name: str,
        rule_id: str,
        tolerance: float = 0,
        severity: str = "high",
    ):
        self.sources = sources
        self.targets = targets
        self.field_name = field_name
        self.rule_id = rule_id
        self.tolerance = tolerance
        self.severity = severity

    def _collect(self, group: DocumentGroup, types: list[str]):
        docs = [
            doc
            for document_type in types
            for doc in group.by_type(document_type)
            if isinstance(doc.get(self.field_name), (int, float))
        ]
        return docs, sum(doc.get(self.field_name) for doc in docs)

    def evaluate(self, group: DocumentGroup) -> list[Discrepancy]:
        sources, source_total = self._collect(group, self.sources)
        targets, target_total = self._collect(group, self.targets)
        if not sources or not targets:
            return []

        difference = target_total - source_total
        if abs(difference) <= self.tolerance:
            return []

        return [
            Discrepancy(
                rule_id=self.rule_id,
                field=self.field_name,
                severity=self.severity,
                values=[
                    DiscrepancyValue(d.document_id, d.document_type, d.get(self.field_name))
                    for d in sources + targets
                ],
                difference=difference,
                explanation=(
                    f"Tổng {self.field_name} không khớp: "
                    f"{_side(sources, source_total)} so với "
                    f"{_side(targets, target_total)} — lệch {_fmt(difference)}"
                ),
            )
        ]


class CoverageRule(Rule):
    """BẤT ĐẲNG THỨC trên tổng số lượng: `more` không được vượt `less`.

    Giao thiếu là bình thường trong mua bán, nên chỉ báo khi VƯỢT — khác hẳn
    AggregateRule vốn đòi bằng nhau.

    `missing_is_zero=True`: mặt hàng có ở `more` mà không có ở `less` thì coi
    như `less` bằng 0 và báo (xuất hóa đơn cho thứ chưa hề nghiệm thu).
    `False`: bỏ qua (nghiệm thu thứ ngoài đơn hàng là chuyện khác, không phải
    việc của rule này).
    """

    def __init__(
        self,
        more: str,
        less: str,
        rule_id: str,
        severity: str,
        more_verb: str,
        less_verb: str,
        missing_is_zero: bool = True,
    ):
        self.more = more
        self.less = less
        self.rule_id = rule_id
        self.severity = severity
        self.more_verb = more_verb
        self.less_verb = less_verb
        self.missing_is_zero = missing_is_zero

    def evaluate(self, group: DocumentGroup) -> list[Discrepancy]:
        more_docs = group.by_type(self.more)
        less_docs = group.by_type(self.less)
        if not more_docs or not less_docs:
            return []

        more_totals = _quantity_by_name(more_docs)
        less_totals = _quantity_by_name(less_docs)

        found: list[Discrepancy] = []
        for name, quantity in more_totals.items():
            if name not in less_totals and not self.missing_is_zero:
                continue
            allowed = less_totals.get(name, 0)
            if quantity <= allowed:
                continue
            display = _display_name(more_docs, name)
            found.append(
                Discrepancy(
                    rule_id=self.rule_id,
                    field=f"items.{display}.quantity",
                    severity=self.severity,
                    values=[
                        DiscrepancyValue(d.document_id, d.document_type, _item_quantity(d, name))
                        for d in less_docs + more_docs
                    ],
                    difference=quantity - allowed,
                    explanation=(
                        f"'{display}': {self.more_verb} tổng {_fmt(quantity)} "
                        f"nhưng {self.less_verb} tổng {_fmt(allowed)}"
                    ),
                )
            )
        return found


class LineItemRule(Rule):
    """So ĐƠN GIÁ và DANH MỤC mặt hàng. Số lượng do `CoverageRule` lo.

    Đơn giá phải bằng nhau bất kể chia bao nhiêu đợt giao, nên vẫn so trực tiếp.
    Số lượng thì KHÔNG được so đôi một: giao hàng từng phần là bình thường, và
    bản cũ so từng hóa đơn với `priced[0]` nên đợt giao nào cũng báo lệch.
    """

    rule_id = "line_item_match"
    severity = "high"

    def evaluate(self, group: DocumentGroup) -> list[Discrepancy]:
        priced = [d for d in group.documents if _is_priced(d)]
        if len(priced) < 2:
            return []
        return self._unit_price(priced) + self._catalogue(group)

    def _unit_price(self, priced: list[DocumentRef]) -> list[Discrepancy]:
        holders: dict[str, list[tuple[DocumentRef, float]]] = {}
        for doc in priced:
            for name, item in _items_by_name(doc).items():
                price = getattr(item, "unit_price", None)
                if price is not None:
                    holders.setdefault(name, []).append((doc, price))

        found: list[Discrepancy] = []
        for name, entries in holders.items():
            prices = {price for _, price in entries}
            if len(prices) < 2:
                continue
            display = _display_name(priced, name)
            rendered = " / ".join(
                f"{label(d.document_type)}={_fmt(p)}" for d, p in entries
            )
            found.append(
                Discrepancy(
                    rule_id="line_item_unit_price",
                    field=f"items.{display}.unit_price",
                    severity="high",
                    values=[DiscrepancyValue(d.document_id, d.document_type, p) for d, p in entries],
                    difference=max(prices) - min(prices),
                    explanation=f"'{display}' lệch đơn giá: {rendered}",
                )
            )
        return found

    def _catalogue(self, group: DocumentGroup) -> list[Discrepancy]:
        """Mặt hàng có ở bên này mà không có ở bên kia — so theo TẬP HỢP gộp.

        Gộp trước rồi mới so, nếu không thì hóa đơn đợt 1 thiếu mặt hàng của
        đợt 2 sẽ bị báo nhầm là "thiếu mặt hàng".
        """
        ordered_docs = group.by_type("purchase_order")
        invoiced_docs = group.by_type("invoice")
        if not ordered_docs or not invoiced_docs:
            return []

        ordered = _quantity_by_name(ordered_docs)
        invoiced = _quantity_by_name(invoiced_docs)
        found: list[Discrepancy] = []

        for name in ordered.keys() - invoiced.keys():
            display = _display_name(ordered_docs, name)
            found.append(
                Discrepancy(
                    rule_id="line_item_missing",
                    field=f"items.{display}",
                    severity="high",
                    values=[
                        DiscrepancyValue(d.document_id, d.document_type, _item_quantity(d, name))
                        for d in ordered_docs
                    ],
                    explanation=(
                        f"Mặt hàng '{display}' có trong đơn đặt hàng "
                        f"nhưng không có trong hóa đơn nào"
                    ),
                )
            )

        for name in invoiced.keys() - ordered.keys():
            display = _display_name(invoiced_docs, name)
            found.append(
                Discrepancy(
                    rule_id="line_item_extra",
                    field=f"items.{display}",
                    severity="high",
                    values=[
                        DiscrepancyValue(d.document_id, d.document_type, _item_quantity(d, name))
                        for d in invoiced_docs
                    ],
                    explanation=(
                        f"Mặt hàng '{display}' có trong hóa đơn "
                        f"nhưng không có trong đơn đặt hàng nào"
                    ),
                )
            )
        return found


class DateOrderRule(Rule):
    rule_id = "date_order"
    severity = "medium"

    def __init__(self, sequence: list[str] | None = None):
        self.sequence = sequence or ["purchase_order", "acceptance_record", "invoice"]

    def _dated(self, group: DocumentGroup, document_type: str) -> list[tuple[DocumentRef, date]]:
        field_name = DATE_FIELD_BY_TYPE.get(document_type, "")
        return [
            (doc, doc.get(field_name))
            for doc in group.by_type(document_type)
            if isinstance(doc.get(field_name), date)
        ]

    def evaluate(self, group: DocumentGroup) -> list[Discrepancy]:
        # Mỗi giai đoạn có thể có NHIỀU chứng từ; lấy mốc sớm nhất làm chuẩn rồi
        # soi từng chứng từ giai đoạn sau. Bản cũ dùng first() nên chỉ kiểm được
        # đúng một chứng từ mỗi giai đoạn.
        stages = [
            (document_type, dated)
            for document_type in self.sequence
            if (dated := self._dated(group, document_type))
        ]

        found: list[Discrepancy] = []
        for (_, earlier_docs), (_, later_docs) in zip(stages, stages[1:]):
            earliest_doc, earliest = min(earlier_docs, key=lambda pair: pair[1])
            for later_doc, later in later_docs:
                if earliest <= later:
                    continue
                found.append(
                    Discrepancy(
                        rule_id=self.rule_id,
                        field="date_order",
                        severity=self.severity,
                        values=[
                            DiscrepancyValue(
                                earliest_doc.document_id, earliest_doc.document_type, earliest.isoformat()
                            ),
                            DiscrepancyValue(
                                later_doc.document_id, later_doc.document_type, later.isoformat()
                            ),
                        ],
                        difference=(earliest - later).days,
                        explanation=(
                            f"Ngày {label(later_doc.document_type)} ({later.isoformat()}) "
                            f"sớm hơn ngày {label(earliest_doc.document_type)} sớm nhất "
                            f"({earliest.isoformat()})"
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
        if group.by_type("purchase_order"):
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


class DuplicateNumberRule(Rule):
    """Hai chứng từ CÙNG LOẠI mang cùng số hiệu nghiệp vụ.

    Việc cộng tổng n–m khiến upload trùng nguy hiểm hơn trước: hai bản của cùng
    một hóa đơn được cộng vào nhau như hai đợt giao khác nhau. Rule tiền có thể
    nổ, nhưng nó chỉ sai chỗ — người review đi tìm ai đòi thừa tiền trong khi
    vấn đề thật là bấm upload hai lần.

    BÁO CHỨ KHÔNG CHẶN: một PO sửa đổi hợp lệ có thể giữ nguyên số hiệu, và chỉ
    người mới biết bản nào là bản đúng.

    Số hiệu đọc từ `NUMBER_FIELD_BY_TYPE` của registry nên rule không hardcode
    loại nào — thêm loại chứng từ thứ tư là nó tự có kiểm trùng.
    """

    rule_id = "trung_so_hieu"
    severity = "medium"

    def evaluate(self, group: DocumentGroup) -> list[Discrepancy]:
        # Khoá gồm CẢ LOẠI: hóa đơn ghi po_number trùng số PO là THAM CHIẾU
        # hợp lệ, không phải trùng lặp.
        seen: dict[tuple[str, str], list[DocumentRef]] = {}
        for doc in group.documents:
            field_name = NUMBER_FIELD_BY_TYPE.get(doc.document_type)
            if not field_name:
                continue
            number = doc.get(field_name)
            if not number:
                continue
            seen.setdefault((doc.document_type, str(number)), []).append(doc)

        return [
            Discrepancy(
                rule_id=self.rule_id,
                field=NUMBER_FIELD_BY_TYPE[document_type],
                severity=self.severity,
                values=[DiscrepancyValue(d.document_id, d.document_type, number) for d in docs],
                difference=len(docs),
                explanation=(
                    f"Có {len(docs)} {label(document_type)} cùng số hiệu {number} — "
                    "có thể là upload trùng hoặc bản sửa đổi chưa đánh dấu"
                ),
            )
            for (document_type, number), docs in seen.items()
            if len(docs) > 1
        ]


TOTAL_AMOUNT_FIELD = "total_amount"


def _total_amount_rule(rule_id: str, severity: str = "critical") -> AggregateRule:
    """Đơn đặt hàng cam kết bao nhiêu thì hóa đơn đòi đúng bấy nhiêu — tính TỔNG.

    Dùng lại được ở hai tầng: trong từng nhóm po_number, và trên toàn project.
    """
    return AggregateRule(
        sources=["purchase_order"],
        targets=["invoice"],
        field_name=TOTAL_AMOUNT_FIELD,
        rule_id=rule_id,
        severity=severity,
    )


CROSS_RULES: list[Rule] = [
    AgreeRule("vendor", severity="critical"),
    AgreeRule("currency", severity="critical"),
    AgreeRule("vendor_tax_code", severity="medium"),
    AgreeRule("buyer", severity="medium"),
    _total_amount_rule("aggregate_total_amount"),
    LineItemRule(),
    # Chuỗi nghiệp vụ: hóa đơn ≤ nghiệm thu ≤ đặt hàng. Chỉ báo khi VƯỢT.
    CoverageRule(
        more="invoice",
        less="acceptance_record",
        rule_id="invoiced_over_accepted",
        severity="critical",
        more_verb="xuất hóa đơn",
        less_verb="nghiệm thu",
    ),
    CoverageRule(
        more="acceptance_record",
        less="purchase_order",
        rule_id="accepted_over_ordered",
        severity="high",
        more_verb="nghiệm thu",
        less_verb="đặt hàng",
        # Nghiệm thu thứ ngoài đơn hàng là vấn đề khác, không phải việc của rule này.
        missing_is_zero=False,
    ),
    DateOrderRule(),
    ReferenceExistsRule(),
    DuplicateNumberRule(),
]

# Chạy MỘT LẦN trên toàn bộ chứng từ của project, bỏ qua ranh giới nhóm.
PROJECT_RULES: list[Rule] = [_total_amount_rule("project_total_amount")]
