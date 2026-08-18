"""Gửi file lên S3 bằng presigned POST, không cần thư viện ngoài.

Dựng multipart/form-data đúng như trình duyệt gửi FormData, để seed và test
đi qua chính con đường mà frontend sẽ đi.

Thứ tự quan trọng: mọi trường trong `fields` phải đứng TRƯỚC trường `file`.
S3 bỏ qua tất cả những gì đứng sau `file`.
"""

import urllib.request
import uuid


def build_multipart(fields: dict, content: bytes, filename: str, content_type: str) -> tuple[bytes, str]:
    boundary = "----recon" + uuid.uuid4().hex
    parts = []
    for key, value in fields.items():
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'
        )
    head = "".join(parts).encode("utf-8")
    file_head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    return head + file_head + content + tail, boundary


def upload(entry: dict, content: bytes) -> int:
    """`entry` là một phần tử trong `documents[]` mà POST /documents trả về."""
    body, boundary = build_multipart(
        entry["upload"]["fields"], content, entry["file_name"], entry["content_type"]
    )
    request = urllib.request.Request(
        entry["upload"]["url"],
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(request) as response:
        return response.status
