from core import validate_document

from .steps import begin_step, fail_step, finish_step, get_document


def lambda_handler(event: dict, context) -> dict:
    document_id = event["document_id"]
    project_id = event.get("project_id")

    begin_step(document_id, "validate", project_id)
    document = get_document(document_id)
    data = document.get("extraction") or {}
    if project_id is None:
        project_id = document.get("project_id")

    result = validate_document(data)
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
        fail_step(document_id, "validate", "; ".join(errors), project_id)
        return {**event, "status": "FAILED"}

    finish_step(document_id, "validate", project_id, validation=validation)
    return {**event, "status": "VALIDATED"}
