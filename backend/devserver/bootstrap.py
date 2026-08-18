"""Định nghĩa bucket + bảng DynamoDB cho môi trường giả lập.

Một định nghĩa duy nhất, hai nơi dùng: dev server và tests/conftest.py.
Nếu tách làm hai bản thì sớm muộn sẽ lệch nhau.

Nguồn sự thật cho môi trường THẬT vẫn là infra/modules/aws/main.tf — file này
chỉ dựng lại đủ để chạy cục bộ.
"""

import os

TABLE_DEFINITIONS = [
    {
        "env": "PROJECTS_TABLE",
        "default": "projects",
        "key_schema": [{"AttributeName": "project_id", "KeyType": "HASH"}],
        "attributes": [{"AttributeName": "project_id", "AttributeType": "S"}],
    },
    {
        "env": "DOCUMENTS_TABLE",
        "default": "documents",
        "key_schema": [{"AttributeName": "document_id", "KeyType": "HASH"}],
        "attributes": [
            {"AttributeName": "document_id", "AttributeType": "S"},
            {"AttributeName": "project_id", "AttributeType": "S"},
            {"AttributeName": "po_number", "AttributeType": "S"},
        ],
        "indexes": [
            {
                "IndexName": "project_id-index",
                "KeySchema": [{"AttributeName": "project_id", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "po_number-index",
                "KeySchema": [{"AttributeName": "po_number", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
    },
    {
        "env": "RUNS_TABLE",
        "default": "processing_runs",
        "key_schema": [{"AttributeName": "run_id", "KeyType": "HASH"}],
        "attributes": [{"AttributeName": "run_id", "AttributeType": "S"}],
    },
    {
        "env": "RECONCILIATIONS_TABLE",
        "default": "reconciliations",
        "key_schema": [{"AttributeName": "reconciliation_id", "KeyType": "HASH"}],
        "attributes": [{"AttributeName": "reconciliation_id", "AttributeType": "S"}],
    },
    {
        "env": "AUDIT_LOG_TABLE",
        "default": "audit_log",
        "key_schema": [
            {"AttributeName": "entity_id", "KeyType": "HASH"},
            {"AttributeName": "timestamp", "KeyType": "RANGE"},
        ],
        "attributes": [
            {"AttributeName": "entity_id", "AttributeType": "S"},
            {"AttributeName": "timestamp", "AttributeType": "S"},
        ],
    },
]


def create_tables(dynamodb) -> list[str]:
    created = []
    for spec in TABLE_DEFINITIONS:
        name = os.environ.get(spec["env"], spec["default"])
        kwargs = {
            "TableName": name,
            "KeySchema": spec["key_schema"],
            "AttributeDefinitions": spec["attributes"],
            "BillingMode": "PAY_PER_REQUEST",
        }
        if spec.get("indexes"):
            kwargs["GlobalSecondaryIndexes"] = spec["indexes"]
        dynamodb.create_table(**kwargs)
        created.append(name)
    return created


# Trình duyệt upload thẳng lên S3 nên bucket phải khai CORS. Giữ khớp với
# aws_s3_bucket_cors_configuration trong infra/modules/aws/main.tf.
CORS_RULES = [
    {
        "AllowedHeaders": ["*"],
        "AllowedMethods": ["POST", "PUT", "GET", "HEAD"],
        "AllowedOrigins": ["*"],
        "ExposeHeaders": ["ETag"],
        "MaxAgeSeconds": 3000,
    }
]


def create_bucket(s3_client, region: str) -> str:
    bucket = os.environ.get("DOCUMENTS_BUCKET", "documents-dev")
    kwargs = {"Bucket": bucket}
    if region != "us-east-1":
        kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
    s3_client.create_bucket(**kwargs)
    s3_client.put_bucket_cors(
        Bucket=bucket, CORSConfiguration={"CORSRules": CORS_RULES}
    )
    return bucket
