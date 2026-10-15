from core import validate_document

from .steps import begin_step, fail_step, finish_step, get_document


def lambda_handler(event: dict, context) -> dict:
    if event.get("skipped"):
        return event

    document_id = event["document_id"]

    begin_step(document_id, "validate")
    document = get_document(document_id)
    data = document.get("extraction") or {}

    result = validate_document(
        data, document.get("format_issues"), document.get("position_issues")
    )
    validation = {
        "valid": result["valid"],
        "schema_errors": result["schema_errors"],
        "rule_errors": result["rule_errors"],
        "flags": result["flags"],
        "comparison_incomplete": result["comparison_incomplete"],
        "warnings": result.get("warnings", []),
    }

    if not result["valid"]:
        from common.dynamodb import update_document
        update_document(document_id, validation=validation)
        errors = result["schema_errors"] + result["rule_errors"]
        fail_step(document_id, "validate", "; ".join(errors))
        return {**event, "status": "FAILED"}

    finish_step(document_id, "validate", validation=validation)
    return {**event, "status": "VALIDATED"}
