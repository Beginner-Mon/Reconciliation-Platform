"""Cache kết quả OCR ra đĩa — OCR cùng file cùng processor thì kết quả không đổi.

Cùng nguyên tắc với production: xử lý per-document là idempotent, cache được.
Nhờ vậy sửa prompt rồi chấm lại bao nhiêu lần cũng KHÔNG tốn thêm tiền OCR,
vì chỉ bước gọi LLM chạy lại.

Key cache = sha256 nội dung file + tên engine. Đổi 1 byte trong file thì cache
tự trượt, không sợ ăn nhầm kết quả cũ.
"""

import hashlib
import json
import pathlib

CACHE_DIR = pathlib.Path(__file__).parent / "results" / "ocr-cache"

_stats = {"hit": 0, "miss": 0}


def _key(content: bytes, engine: str) -> str:
    return f"{engine}.{hashlib.sha256(content).hexdigest()[:16]}"


def path_for(content: bytes, engine: str) -> pathlib.Path:
    return CACHE_DIR / f"{_key(content, engine)}.json"


def get(content: bytes, engine: str) -> dict | None:
    path = path_for(content, engine)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def put(content: bytes, engine: str, ocr_json: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path_for(content, engine).write_text(
        json.dumps(ocr_json, ensure_ascii=False, default=str), encoding="utf-8"
    )


def run(engine: str, content: bytes, call, refresh: bool = False) -> tuple[dict, bool]:
    """Trả về (ocr_json, tu_cache). `call` chỉ được gọi khi cache trượt."""
    if not refresh:
        cached = get(content, engine)
        if cached is not None:
            _stats["hit"] += 1
            return cached, True

    ocr_json = call()
    put(content, engine, ocr_json)
    _stats["miss"] += 1
    return ocr_json, False


def stats() -> dict:
    return dict(_stats)


def clear() -> int:
    if not CACHE_DIR.is_dir():
        return 0
    files = list(CACHE_DIR.glob("*.json"))
    for path in files:
        path.unlink()
    return len(files)
