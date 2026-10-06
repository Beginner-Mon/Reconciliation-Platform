import os
import json
from uuid import uuid4
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

PROJECTS_TABLE = os.environ.get("PROJECTS_TABLE", "projects")
DOCUMENTS_TABLE = os.environ.get("DOCUMENTS_TABLE", "documents")
RUNS_TABLE = os.environ.get("RUNS_TABLE", "processing_runs")
RECONCILIATIONS_TABLE = os.environ.get("RECONCILIATIONS_TABLE", "reconciliations")

PROJECT_INDEX = os.environ.get("DOCUMENTS_PROJECT_INDEX", "project_id-index")
PO_NUMBER_INDEX = os.environ.get("DOCUMENTS_PO_NUMBER_INDEX", "po_number-index")

_dynamodb = None


def get_dynamodb():
    global _dynamodb
    if _dynamodb is None:
        if os.environ.get("AWS_ENDPOINT_URL"):
            _dynamodb = boto3.resource("dynamodb", endpoint_url=os.environ["AWS_ENDPOINT_URL"])
        else:
            _dynamodb = boto3.resource("dynamodb")
    return _dynamodb


def get_table(name: str):
    return get_dynamodb().Table(name)


def to_dynamo(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, list):
        return [to_dynamo(v) for v in value]
    if isinstance(value, dict):
        return {k: to_dynamo(v) for k, v in value.items()}
    return value


def from_dynamo(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, list):
        return [from_dynamo(v) for v in value]
    if isinstance(value, dict):
        return {k: from_dynamo(v) for k, v in value.items()}
    return value


def put_item(table: str, item: dict) -> None:
    get_table(table).put_item(Item=to_dynamo(item))


def get_item(table: str, key: dict) -> dict | None:
    response = get_table(table).get_item(Key=key)
    item = response.get("Item")
    result = from_dynamo(item) if item is not None else None
    return _hydrate_document(result) if table == DOCUMENTS_TABLE and result else result


def _hydrate_document(item: dict) -> dict:
    key = item.get("document_payload_s3_key")
    if key:
        from .s3 import read_json
        return {**item, **read_json(key)}
    return item


def update_item(
    table: str,
    key: dict,
    updates: dict | None = None,
    remove: list[str] | None = None,
    condition: str | None = None,
    condition_values: dict | None = None,
) -> bool:
    updates = updates or {}
    remove = remove or []
    names = {}
    values = {}
    set_parts = []
    remove_parts = []

    for field, value in updates.items():
        names[f"#{field}"] = field
        values[f":{field}"] = to_dynamo(value)
        set_parts.append(f"#{field} = :{field}")

    for field in remove:
        names[f"#{field}"] = field
        remove_parts.append(f"#{field}")

    expression = " ".join(
        part
        for part in (
            "SET " + ", ".join(set_parts) if set_parts else "",
            "REMOVE " + ", ".join(remove_parts) if remove_parts else "",
        )
        if part
    )
    if not expression:
        return True

    for name, value in (condition_values or {}).items():
        values[name] = to_dynamo(value)

    kwargs = {
        "Key": key,
        "UpdateExpression": expression,
        "ExpressionAttributeNames": names,
    }
    if values:
        kwargs["ExpressionAttributeValues"] = values
    if condition:
        kwargs["ConditionExpression"] = condition

    try:
        get_table(table).update_item(**kwargs)
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def query_index(table: str, index: str, key_field: str, key_value) -> list[dict]:
    items = []
    kwargs = {
        "IndexName": index,
        "KeyConditionExpression": "#k = :v",
        "ExpressionAttributeNames": {"#k": key_field},
        "ExpressionAttributeValues": {":v": key_value},
    }
    while True:
        response = get_table(table).query(**kwargs)
        items.extend(response.get("Items", []))
        token = response.get("LastEvaluatedKey")
        if not token:
            break
        kwargs["ExclusiveStartKey"] = token
    result = from_dynamo(items)
    return [_hydrate_document(item) for item in result] if table == DOCUMENTS_TABLE else result


def scan_table(table: str) -> list[dict]:
    items = []
    kwargs = {}
    while True:
        response = get_table(table).scan(**kwargs)
        items.extend(response.get("Items", []))
        token = response.get("LastEvaluatedKey")
        if not token:
            break
        kwargs["ExclusiveStartKey"] = token
    result = from_dynamo(items)
    return [_hydrate_document(item) for item in result] if table == DOCUMENTS_TABLE else result


def query_documents_by_project(project_id: str) -> list[dict]:
    return query_index(DOCUMENTS_TABLE, PROJECT_INDEX, "project_id", project_id)


def query_documents_by_po_number(po_number: str) -> list[dict]:
    return query_index(DOCUMENTS_TABLE, PO_NUMBER_INDEX, "po_number", po_number)


def query_document_names_by_project(project_id: str) -> list[dict]:
    items = []
    kwargs = {
        "IndexName": PROJECT_INDEX,
        "KeyConditionExpression": "#k = :v",
        "ProjectionExpression": "#id, #name",
        "ExpressionAttributeNames": {
            "#k": "project_id",
            "#id": "document_id",
            "#name": "file_name",
        },
        "ExpressionAttributeValues": {":v": project_id},
    }
    while True:
        response = get_table(DOCUMENTS_TABLE).query(**kwargs)
        items.extend(response.get("Items", []))
        token = response.get("LastEvaluatedKey")
        if not token:
            break
        kwargs["ExclusiveStartKey"] = token
    return from_dynamo(items)


def scan_keys_by_project(table: str, key_field: str, project_id: str) -> list[str]:
    keys = []
    kwargs = {
        "FilterExpression": "#p = :p",
        "ProjectionExpression": "#k",
        "ExpressionAttributeNames": {"#p": "project_id", "#k": key_field},
        "ExpressionAttributeValues": {":p": project_id},
    }
    while True:
        response = get_table(table).scan(**kwargs)
        keys.extend(item[key_field] for item in response.get("Items", []))
        token = response.get("LastEvaluatedKey")
        if not token:
            break
        kwargs["ExclusiveStartKey"] = token
    return keys


def update_document(document_id: str, **updates) -> bool:
    payload_fields = {"extraction", "validation", "confidence", "ungrounded_fields"}
    if not payload_fields.intersection(updates):
        return update_item(DOCUMENTS_TABLE, {"document_id": document_id}, updates)
    current = get_item(DOCUMENTS_TABLE, {"document_id": document_id}) or {}
    merged = {**current, **updates, "document_id": document_id}
    from boto3.dynamodb.types import TypeSerializer
    serialized = TypeSerializer().serialize(to_dynamo(merged))
    size = len(json.dumps(serialized, ensure_ascii=False, default=str).encode("utf-8"))
    if size < 300 * 1024 and not current.get("document_payload_s3_key"):
        return update_item(DOCUMENTS_TABLE, {"document_id": document_id}, updates)
    from .s3 import write_json
    key = f"projects/{merged['project_id']}/document-payload/{document_id}/{uuid4().hex}.json"
    payload = {field: merged[field] for field in payload_fields if field in merged}
    write_json(key, payload)
    metadata = {field: value for field, value in updates.items() if field not in payload_fields}
    metadata["document_payload_s3_key"] = key
    return update_item(DOCUMENTS_TABLE, {"document_id": document_id}, metadata, remove=sorted(payload_fields))


def update_project(project_id: str, **updates) -> bool:
    return update_item(PROJECTS_TABLE, {"project_id": project_id}, updates)


def claim_processing_run(project_id: str, run_id: str) -> bool:
    return update_item(
        PROJECTS_TABLE,
        {"project_id": project_id},
        {"processing_run_id": run_id},
        condition=(
            "attribute_exists(project_id) AND attribute_not_exists(processing_run_id) "
            "AND attribute_not_exists(deleting_at)"
        ),
    )


def release_processing_run(project_id: str, run_id: str | None = None) -> bool:
    if run_id is None:
        return update_item(
            PROJECTS_TABLE,
            {"project_id": project_id},
            remove=["processing_run_id"],
        )
    return update_item(
        PROJECTS_TABLE,
        {"project_id": project_id},
        remove=["processing_run_id"],
        condition="processing_run_id = :run_id",
        condition_values={":run_id": run_id},
    )


def delete_item(table: str, key: dict, condition: str | None = None) -> None:
    kwargs: dict = {"Key": key}
    if condition:
        kwargs["ConditionExpression"] = condition
    try:
        get_table(table).delete_item(**kwargs)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise
        raise
