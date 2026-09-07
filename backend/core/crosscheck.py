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
from .validate import validate_document

UNLINKED_KEY = None

# Chứng từ chưa phân loại KHÔNG được tham gia đối chiếu.
#
# `AgreeRule`/`NumericRule` lọc theo TRƯỜNG, không theo LOẠI — hễ hai chứng từ
# cùng có `currency` hay `total_amount` là chúng đem ra so, bất kể đó là gì.
# Với loại `unknown` thì mình không biết tài liệu nói về cái gì, nên phép so đó
# vô nghĩa: chạy thật đã thấy hai chứng từ của hai lô hàng khác nhau, hai khách
# hàng khác nhau bị báo "lệch tiền 43 triệu".
#
# Bỏ qua ở tầng LOẠI chứ không phải bỏ bớt trường trong schema: thêm trường mới
# vào `Unknown` sau này sẽ lại làm vỡ nếu chặn theo trường.
NON_COMPARABLE_TYPES = {"unknown"}


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
        if result["document_type"] in NON_COMPARABLE_TYPES:
            # Bỏ qua nhưng PHẢI báo ra, không được im lặng biến mất.
            skipped.append(
                {
                    "document_id": document_id,
                    "reason": "chưa phân loại được nên không đối chiếu",
                    "errors": [],
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


def run_crosscheck(documents: list[dict]) -> dict:
    refs, skipped = build_refs(documents)
    groups, unlinked = group_documents(refs)

    group_discrepancies: list[Discrepancy] = []
    for group in groups:
        if len(group.documents) < 2:
            continue
        for rule in CROSS_RULES:
            group_discrepancies.extend(rule.evaluate(group))

    # Tầng project: gộp mọi chứng từ thành một nhóm ảo, bỏ qua ranh giới
    # po_number. Trả lời câu hỏi "tổng thể project có hợp lệ không".
    #
    # Chỉ chạy khi có TỪ 2 NHÓM trở lên — một nhóm thì tổng project chính là
    # tổng nhóm, chạy thêm chỉ nhân đôi cùng một cảnh báo.
    project_discrepancies: list[Discrepancy] = []
    hint: list[Discrepancy] = []
    if len(groups) > 1:
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
