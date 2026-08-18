"""Tạo sẵn một project demo đã upload đủ 3 loại chứng từ.

Để mở dev server lên là frontend có dữ liệu ngay, không phải bấm tay từ đầu.
Dùng chính API thật (qua api.handler) chứ không ghi thẳng vào DynamoDB — nếu
API hỏng thì seed cũng hỏng, đó là điều mong muốn.
"""

import json

from devserver.fake_ai import sample_files
from devserver.upload import upload


def _call(method: str, path: str, body: dict | None = None) -> dict:
    from api.handler import lambda_handler

    event = {
        "requestContext": {"http": {"method": method}},
        "rawPath": path,
        "body": json.dumps(body) if body is not None else None,
    }
    result = lambda_handler(event, None)
    parsed = json.loads(result["body"])
    if result["statusCode"] >= 400:
        raise RuntimeError(f"{method} {path} -> {result['statusCode']}: {parsed}")
    return parsed


def create_demo_project(name: str = "Gói thầu thiết bị CNTT 2026") -> str:
    project = _call("POST", "/projects", {"name": name, "description": "Dữ liệu demo"})
    project_id = project["project_id"]

    files = sample_files()
    created = _call(
        "POST",
        f"/projects/{project_id}/documents",
        {"files": [{"file_name": n} for n in files]},
    )

    for entry in created["documents"]:
        status = upload(entry, files[entry["file_name"]])
        if status not in (200, 204):
            raise RuntimeError(f"Upload {entry['file_name']} -> {status}")

    return project_id
