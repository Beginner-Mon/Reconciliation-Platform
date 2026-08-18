import json
import os

import boto3
from botocore.exceptions import ClientError

BUCKET = os.environ.get("DOCUMENTS_BUCKET", "documents-dev")

_s3 = None


def get_s3():
    global _s3
    if _s3 is None:
        if os.environ.get("AWS_ENDPOINT_URL"):
            _s3 = boto3.client("s3", endpoint_url=os.environ["AWS_ENDPOINT_URL"])
        else:
            _s3 = boto3.client("s3")
    return _s3


def upload_key(project_id: str, document_id: str, ext: str) -> str:
    return f"projects/{project_id}/uploads/{document_id}{ext}"


def ocr_key(project_id: str, document_id: str) -> str:
    return f"projects/{project_id}/ocr/{document_id}.json"


def extraction_key(project_id: str, document_id: str) -> str:
    return f"projects/{project_id}/extraction/{document_id}.json"


def reconciliation_key(project_id: str, reconciliation_id: str) -> str:
    return f"projects/{project_id}/reconciliation/{reconciliation_id}.json"


MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 20 * 1024 * 1024))


def create_upload_post(
    key: str, content_type: str, expires_in: int = 600, max_bytes: int = MAX_UPLOAD_BYTES
) -> dict:
    """Presigned POST — dạng form, trình duyệt upload thẳng lên S3.

    Dùng POST thay vì PUT vì hai lý do:

    1. POST + multipart/form-data là "simple request" theo CORS nên trình duyệt
       KHÔNG gửi preflight OPTIONS. Presigned PUT thì có, và preflight đó phải
       trả 2xx — điều kiện mà môi trường giả lập không đáp ứng được.
    2. Chỉ POST mới đặt được `content-length-range`. Presigned PUT không giới
       hạn được kích thước: ai cầm URL có thể đẩy file bao nhiêu GB tùy thích.
    """
    return get_s3().generate_presigned_post(
        Bucket=BUCKET,
        Key=key,
        Fields={"Content-Type": content_type},
        Conditions=[{"Content-Type": content_type}, ["content-length-range", 1, max_bytes]],
        ExpiresIn=expires_in,
    )


def create_upload_url(key: str, content_type: str, expires_in: int = 600) -> str:
    return get_s3().generate_presigned_url(
        "put_object",
        Params={"Bucket": BUCKET, "Key": key, "ContentType": content_type},
        ExpiresIn=expires_in,
    )


def create_view_url(key: str, expires_in: int = 3600) -> str:
    if not key:
        return ""
    return get_s3().generate_presigned_url(
        "get_object",
        Params={"Bucket": BUCKET, "Key": key},
        ExpiresIn=expires_in,
    )


def head_object(key: str) -> dict | None:
    try:
        response = get_s3().head_object(Bucket=BUCKET, Key=key)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise
    return {
        "size_bytes": response["ContentLength"],
        "content_type": response.get("ContentType", ""),
        "last_modified": response.get("LastModified"),
    }


def read_object(key: str) -> bytes:
    return get_s3().get_object(Bucket=BUCKET, Key=key)["Body"].read()


def read_json(key: str) -> dict:
    return json.loads(read_object(key).decode("utf-8"))


def write_object(key: str, body: bytes | str, content_type: str = "application/json") -> None:
    if isinstance(body, str):
        body = body.encode("utf-8")
    get_s3().put_object(Bucket=BUCKET, Key=key, Body=body, ContentType=content_type)


def write_json(key: str, data: dict) -> None:
    write_object(key, json.dumps(data, ensure_ascii=False, default=str))
