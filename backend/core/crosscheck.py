from .rules import (
    CROSS_RULES,
    SEVERITY_ORDER,
    Discrepancy,
    DiscrepancyValue,
    DocumentGroup,
    DocumentRef,
)
from .validate import validate_document

UNLINKED_KEY = None


def _correlation_key(ref: DocumentRef) -> str | None:
    return ref.get("po_number")


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
        refs.append(
            DocumentRef(
                document_id=document_id,
                document_type=result["document_type"],
                model=result["model"],
            )
        )
    return refs, skipped


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


def run_crosscheck(documents: list[dict]) -> dict:
    refs, skipped = build_refs(documents)
    groups, unlinked = group_documents(refs)

    discrepancies: list[Discrepancy] = _unlinked_discrepancies(unlinked)
    for group in groups:
        if len(group.documents) < 2:
            continue
        for rule in CROSS_RULES:
            discrepancies.extend(rule.evaluate(group))

    discrepancies.sort(key=lambda d: (SEVERITY_ORDER.get(d.severity, 9), d.rule_id, d.field))

    severity_summary: dict[str, int] = {}
    for item in discrepancies:
        severity_summary[item.severity] = severity_summary.get(item.severity, 0) + 1

    return {
        "checked_document_ids": [r.document_id for r in refs],
        "skipped_documents": skipped,
        "groups": [
            {
                "key": group.key,
                "document_ids": [d.document_id for d in group.documents],
                "document_types": sorted(group.types),
            }
            for group in groups
        ],
        "discrepancies": [d.to_dict() for d in discrepancies],
        "discrepancy_count": len(discrepancies),
        "severity_summary": severity_summary,
    }
