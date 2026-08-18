"""Đọc file .env cạnh thư mục này vào os.environ.

Viết tay 20 dòng thay vì thêm dependency, vì đây là công cụ dev.
Biến đã có sẵn trong môi trường thì KHÔNG bị ghi đè — cho phép tạm override
bằng `$env:X = "..."` mà không phải sửa file.
"""

import os
import pathlib

ENV_PATH = pathlib.Path(__file__).parent / ".env"


def load(path: pathlib.Path = ENV_PATH) -> list[str]:
    if not path.exists():
        return []

    loaded = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key or not value or value.startswith("<"):
            continue
        if key in os.environ:
            continue
        os.environ[key] = value
        loaded.append(key)
    return loaded
