from .compare import build_deterministic_alignment, check_chain_billing_vs_delivery, compare_pair
from .rules import (
    CROSS_RULES,
    PROJECT_RULES,
    SEVERITY_ORDER,
    TOTAL_AMOUNT_FIELD,
    Discrepancy,
    DiscrepancyValue,
    DocumentGroup,
    DocumentRef,
)
from .validate import _number, validate_document

UNLINKED_KEY = None

ROLE_PRIORITY = {"order": 0, "offer": 1, "delivery": 2, "billing": 3, "other": 99}


def _correlation_key(ref: DocumentRef) -> str | None:
    role = getattr(ref.model, "role", None)
    if role == "order":
        return getattr(ref.model, "doc_number", None) or getattr(ref.model, "order_reference", None)
    return getattr(ref.model, "order_reference", None)


def build_refs(documents: list[dict]) -> tuple[list[DocumentRef], list[dict]]:
    refs: list[DocumentRef] = []
    skipped: list[dict] = []
    for entry in documents:
        document_id = entry.get("document_id", "")
        data = entry.get("data") or {}
        result = validate_document(data)
        if not result["valid"] or result["model"] is None:
            skipped.append(
                {
                    "document_id": document_id,
                    "reason": "không qua được validate",
                    "errors": result["schema_errors"] + result["rule_errors"],
                }
            )
            continue
        model = result["model"]
        role = getattr(model, "role", None)
        if role == "other" or result["document_type"] in ("other", "unknown"):
            skipped.append(
                {
                    "document_id": document_id,
                    "reason": "chưa phân loại được nên không đối chiếu (role=other)",
                    "errors": [],
                }
            )
            continue
        refs.append(
            DocumentRef(
                document_id=document_id,
                document_type=result["document_type"],
                model=model,
                comparison_incomplete=result["comparison_incomplete"] or any(
                    f["field"].startswith("tables") and f["code"] in ("quantity", "insufficient_data")
                    and (".rows." not in f["field"] or _number(f["values"].get("quantity")) is None)
                    for f in result["flags"]
                ),
                validation_flags=result["flags"],
            )
        )
    return refs, skipped


def _select_anchor(group: DocumentGroup, anchor_ids: list[str] | None) -> DocumentRef | None:
    if not group.documents:
        return None
    # Người dùng chọn thắng
    if anchor_ids:
        for doc_id in anchor_ids:
            for ref in group.documents:
                if ref.document_id == doc_id:
                    return ref
    # Mặc định theo role
    def sort_key(ref: DocumentRef):
        role = getattr(ref.model, "role", "other")
        prio = ROLE_PRIORITY.get(role, 99)
        # cùng role lấy upload sớm nhất — document_id chứa timestamp? dùng document_id sort
        return (prio, ref.document_id)
    return sorted(group.documents, key=sort_key)[0]


def group_documents(refs: list[DocumentRef]) -> tuple[list[DocumentGroup], list[DocumentRef]]:
    keyed: dict[str, list[DocumentRef]] = {}
    unlinked: list[DocumentRef] = []

    for ref in refs:
        key = _correlation_key(ref)
        if key:
            keyed.setdefault(key, []).append(ref)
        else:
            unlinked.append(ref)

    if len(keyed) <= 1 and unlinked:
        key = next(iter(keyed), UNLINKED_KEY)
        keyed.setdefault(key, []).extend(unlinked)
        unlinked = []

    groups = [DocumentGroup(key=key, documents=docs) for key, docs in keyed.items()]
    return groups, unlinked


def _unlinked_discrepancies(unlinked: list[DocumentRef]) -> list[Discrepancy]:
    return [
        Discrepancy(
            rule_id="document_unlinked",
            field="po_number",
            severity="medium",
            values=[DiscrepancyValue(ref.document_id, ref.document_type, None)],
            explanation=(
                "Không xác định được chứng từ này thuộc giao dịch nào "
                "(thiếu po_number, trong khi project có nhiều giao dịch)"
            ),
        )
        for ref in unlinked
    ]


def _mislabeled_hint(
    group_discrepancies: list[Discrepancy],
    project_discrepancies: list[Discrepancy],
) -> list[Discrepancy]:
    """Nhiều nhóm lệch tiền nhưng TỔNG TOÀN PROJECT lại khớp.

    Hai sai số triệt tiêu nhau — dấu hiệu điển hình của ghi nhầm `po_number`
    (tiền gán sai đơn hàng), chứ không phải ai đó đòi thừa tiền. Chỉ cộng theo
    nhóm thì không thấy; chỉ cộng toàn project thì im lặng hoàn toàn. Phải có cả
    hai mới nói được điều này.

    CHỈ gọi khi project có từ 2 nhóm trở lên. Một nhóm thì tổng project chính là
    tổng nhóm, không thể triệt tiêu, và hàm này sẽ báo nhầm mọi lệch tiền thường.
    """
    lech_nhom = [d for d in group_discrepancies if d.field == TOTAL_AMOUNT_FIELD]
    lech_project = [d for d in project_discrepancies if d.field == TOTAL_AMOUNT_FIELD]
    if not lech_nhom or lech_project:
        return []

    return [
        Discrepancy(
            rule_id="po_number_co_the_ghi_nham",
            field="po_number",
            severity="medium",
            values=[
                value
                for discrepancy in lech_nhom
                for value in discrepancy.values
            ],
            explanation=(
                f"{len(lech_nhom)} nhóm lệch tiền nhưng tổng toàn project khớp — "
                "nhiều khả năng ghi nhầm po_number chứ không phải sai số tiền"
            ),
        )
    ]


def run_crosscheck(documents: list[dict], anchor_document_ids: list[str] | None = None) -> dict:
    refs, skipped = build_refs(documents)
    groups, unlinked = group_documents(refs)

    # Gán anchor mỗi nhóm
    anchor_map: dict[str | None, str | None] = {}
    for group in groups:
        anchor = _select_anchor(group, anchor_document_ids)
        anchor_map[group.key] = anchor.document_id if anchor else None

    group_discrepancies: list[Discrepancy] = []
    for group in groups:
        if len(group.documents) < 2:
            continue
        if any(d.comparison_incomplete for d in group.documents):
            group_discrepancies.append(Discrepancy(
                rule_id="comparison_incomplete", field="tables", severity="medium",
                values=[DiscrepancyValue(d.document_id, d.document_type, None) for d in group.documents],
                explanation="Chưa đủ dữ liệu để đối chiếu nhóm; cần kiểm tra flag của chứng từ, không kết luận thiếu/thừa từ bản rút gọn.",
            ))
            continue
        anchor = _select_anchor(group, anchor_document_ids)
        if anchor is None:
            continue
        # P2: nhóm >2 là n-m (nhiều invoice cho 1 PO) — rule cũ đã cộng dồn đúng, compare mới theo từng cặp sẽ báo giả
        if len(group.documents) == 2:
            others = [d for d in group.documents if d.document_id != anchor.document_id]
            for other in others:
                alignment = build_deterministic_alignment(anchor, other)
                group_discrepancies.extend(compare_pair(anchor, other, alignment))
            group_discrepancies.extend(check_chain_billing_vs_delivery(group.documents, anchor))
        for rule in CROSS_RULES:
            group_discrepancies.extend(rule.evaluate(group))

    project_discrepancies: list[Discrepancy] = []
    hint: list[Discrepancy] = []
    if len(groups) > 1 and not any(r.comparison_incomplete for r in refs):
        whole = DocumentGroup(key=None, documents=refs)
        for rule in PROJECT_RULES:
            project_discrepancies.extend(rule.evaluate(whole))
        hint = _mislabeled_hint(group_discrepancies, project_discrepancies)

    discrepancies = (
        _unlinked_discrepancies(unlinked)
        + group_discrepancies
        + project_discrepancies
        + hint
    )

    discrepancies.sort(key=lambda d: (SEVERITY_ORDER.get(d.severity, 9), d.rule_id, d.field))

    severity_summary: dict[str, int] = {}
    for item in discrepancies:
        severity_summary[item.severity] = severity_summary.get(item.severity, 0) + 1

    return {
        "validation_flags": {r.document_id: r.validation_flags for r in refs},
        "checked_document_ids": [r.document_id for r in refs],
        "skipped_documents": skipped,
        "groups": [
            {
                "key": group.key,
                "document_ids": [d.document_id for d in group.documents],
                "document_types": sorted(group.types),
                "anchor_document_id": anchor_map.get(group.key),
            }
            for group in groups
        ],
        "discrepancies": [d.to_dict() for d in discrepancies],
        "discrepancy_count": len(discrepancies),
        "severity_summary": severity_summary,
    }
