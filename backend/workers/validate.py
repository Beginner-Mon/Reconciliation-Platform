from core import validate_document

from .steps import begin_step, fail_step, finish_step, get_document


def lambda_handler(event: dict, context) -> dict:
    document_id = event["document_id"]

    begin_step(document_id, "validate")
    document = get_document(document_id)
    data = document.get("extraction") or {}

    result = validate_document(data)
    validation = {
        "valid": result["valid"],
        "schema_errors": result["schema_errors"],
        "rule_errors": result["rule_errors"],
    }

    if not result["valid"]:
        errors = result["schema_errors"] + result["rule_errors"]
        fail_step(document_id, "validate", "; ".join(errors))
        return {**event, "status": "FAILED", "validation": validation}

    finish_step(document_id, "validate", validation=validation)
    return {**event, "status": "VALIDATED", "validation": validation}
