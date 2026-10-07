"""Amazon Textract — engine OCR thứ hai, bên cạnh Google Document AI.

Textract trả về hình dạng KHÁC HẲN Document AI: một DANH SÁCH PHẲNG, trong đó
mỗi chữ (WORD), mỗi dòng (LINE), mỗi ô bảng (CELL) là một "Block" rời, nối với
nhau bằng `Relationships` trỏ theo `Id`. Không có `text` tổng, không có `pages[]`.

Việc của file này là dịch danh sách phẳng đó về ĐÚNG hợp đồng OCR hiện có, để
`_build_ocr_text`, `api/views.py` và frontend không phải sửa một dòng nào:

    {"text", "pages": [{page_number, lines, blocks, tables,
                        key_value_pairs, token_count, mean_token_confidence}]}

CẢNH BÁO NGHIỆP VỤ: Textract KHÔNG hỗ trợ tiếng Việt. Tài liệu chính thức
(textract/latest/dg/limits-document.html) chỉ liệt kê English, French, German,
Italian, Portuguese, Spanish. Document AI đo được 99,5% dấu tiếng Việt trên
chứng từ thật (evaluation/FINDINGS.md). Engine này để ĐỐI CHỨNG CÓ SỐ ĐO và làm
phương án dự phòng, không phải để thay Document AI.
"""

import hashlib
import os
import time

from . import aws_real
from .ai_clients import _raise_if_rate_limited

# LAYOUT cho ra `blocks` (khối ngữ nghĩa) và MIỄN PHÍ khi đi kèm TABLES — bỏ nó
# đi thì mất khối mà không tiết kiệm được đồng nào. Nguồn: pricing example 16,
# aws.amazon.com/textract/pricing.
ANALYZE_FEATURES = ["FORMS", "TABLES", "LAYOUT"]

# Bản async là bắt buộc: bản sync giới hạn PDF 1 TRANG, mà chứng từ thật 1-5
# trang. Đổi lại, async chỉ đọc file TỪ S3 chứ không nhận bytes trong request.
POLL_SECONDS = 2.0
POLL_TIMEOUT_SECONDS = float(os.environ.get("TEXTRACT_TIMEOUT_SECONDS", "480"))

EXT_BY_MIME = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/tiff": ".tiff",
}

STAGING_PREFIX = "textract-staging/"


def _stage_target(content: bytes, mime_type: str, s3_key: str | None) -> tuple[str, str, bool]:
    """Trả (bucket, key, phai_upload) — file phải nằm ở đâu để Textract đọc được.

    Ba môi trường để file ở ba nơi khác nhau:

      Lambda production : S3 thật, đã có sẵn s3_key  -> dùng thẳng, không copy
      devserver         : moto = RAM máy mình        -> AWS thật không thấy
      evaluation        : ổ đĩa                      -> AWS thật không thấy

    Nên hễ có `TEXTRACT_S3_BUCKET` là LUÔN upload, kể cả khi đã có `s3_key`:
    ở devserver cái key đó trỏ vào bucket giả nằm trong RAM.
    """
    staging_bucket = os.environ.get("TEXTRACT_S3_BUCKET", "")

    if not staging_bucket:
        if s3_key:
            return os.environ.get("DOCUMENTS_BUCKET", ""), s3_key, False
        raise RuntimeError(
            "Thiếu TEXTRACT_S3_BUCKET. Textract async chỉ đọc file từ S3 THẬT, "
            "không nhận bytes — file trên đĩa hoặc trong moto phải được đẩy lên "
            "một bucket thật trước. Đặt TEXTRACT_S3_BUCKET=<tên bucket>."
        )

    ext = EXT_BY_MIME.get(mime_type, ".pdf")
    digest = hashlib.sha256(content).hexdigest()[:32]
    return staging_bucket, f"{STAGING_PREFIX}{digest}{ext}", True


def _await_blocks(fetch) -> tuple[list[dict], int]:
    """Chờ job xong rồi gom Block. `fetch(next_token) -> response`."""
    han_chot = time.monotonic() + POLL_TIMEOUT_SECONDS
    response = fetch(None)

    while response.get("JobStatus") == "IN_PROGRESS":
        if time.monotonic() > han_chot:
            raise RuntimeError(f"Textract job quá {POLL_TIMEOUT_SECONDS}s vẫn IN_PROGRESS")
        time.sleep(POLL_SECONDS)
        response = fetch(None)

    status = response.get("JobStatus")
    if status != "SUCCEEDED":
        # PARTIAL_SUCCESS trả kết quả CỤT kèm Warnings. Nuốt nó thì mấy trang
        # bị bỏ qua biến mất không dấu vết, và chứng từ đi tiếp vào Gemini với
        # nội dung thiếu — sai ở chỗ không ai nghĩ để nhìn.
        chi_tiet = response.get("Warnings") or response.get("StatusMessage") or ""
        raise RuntimeError(f"Textract job {status}: {chi_tiet}")

    # Gọi lại từ đầu để gom cả các trang NextToken. Get* không tính tiền (chỉ
    # số trang xử lý mới tính) nên lần gọi thừa này không tốn gì.
    return _collect_blocks(fetch)


def _collect_blocks(fetch) -> tuple[list[dict], int]:
    """Gom Block qua MỌI trang NextToken. `fetch(next_token) -> response`.

    Doc nhiều trang có bảng vượt 1.000 block rất dễ. Quên vòng lặp này thì mất
    trang mà KHÔNG có lỗi nào nổ ra — kết quả cụt trông y hệt tài liệu ngắn.
    """
    blocks: list[dict] = []
    page_count = 0
    next_token = None

    while True:
        response = fetch(next_token)
        blocks.extend(response.get("Blocks") or [])
        if not page_count:
            page_count = int((response.get("DocumentMetadata") or {}).get("Pages") or 0)
        next_token = response.get("NextToken")
        if not next_token:
            return blocks, page_count


def _confidence(block: dict) -> float | None:
    """Textract trả thang 0-100, Document AI trả thang 0-1.

    Quên chia 100 là mọi ngưỡng cảnh báo trong Human Review (< 0.8) không bao
    giờ chạm tới: hệ thống im lặng khẳng định "mọi thứ đều chắc chắn".
    """
    value = block.get("Confidence")
    return round(float(value) / 100, 4) if value is not None else None


def _related(block: dict, kind: str) -> list[str]:
    for relationship in block.get("Relationships") or []:
        if relationship.get("Type") == kind:
            return list(relationship.get("Ids") or [])
    return []


def _child_text(block: dict, by_id: dict, separator: str = " ") -> str:
    parts = []
    for child_id in _related(block, "CHILD"):
        child = by_id.get(child_id)
        if child is None:
            continue
        if child["BlockType"] == "SELECTION_ELEMENT":
            parts.append("[X]" if child.get("SelectionStatus") == "SELECTED" else "[ ]")
        elif child.get("Text"):
            parts.append(child["Text"])
    return separator.join(parts).strip()


def _table_rows(table: dict, by_id: dict) -> list[dict]:
    """Quan hệ CHILD KHÔNG bảo đảm thứ tự — phải sắp theo RowIndex/ColumnIndex.

    `_build_ocr_text` lấy dòng ĐẦU TIÊN làm header của bảng markdown. Đọc theo
    thứ tự Ids trả về thì header rơi vào một ô bất kỳ và cả bảng vô nghĩa.
    """
    rows: dict[int, list[tuple[int, str]]] = {}
    for cell_id in _related(table, "CHILD"):
        cell = by_id.get(cell_id)
        if cell is None or cell["BlockType"] != "CELL":
            continue
        row_index = int(cell.get("RowIndex") or 0)
        rows.setdefault(row_index, []).append(
            (int(cell.get("ColumnIndex") or 0), _child_text(cell, by_id))
        )

    return [
        {"cells": [text for _, text in sorted(rows[index])]} for index in sorted(rows)
    ]


def _key_value_pairs(page_blocks: list[dict], by_id: dict) -> list[dict]:
    pairs = []
    for block in page_blocks:
        if block["BlockType"] != "KEY_VALUE_SET":
            continue
        if "KEY" not in (block.get("EntityTypes") or []):
            continue
        for value_id in _related(block, "VALUE"):
            value = by_id.get(value_id)
            if value is None:
                continue
            pairs.append(
                {
                    "key": _child_text(block, by_id),
                    "value": _child_text(value, by_id),
                    "confidence": _confidence(value),
                }
            )
    return pairs


def _word_boxes(word_blocks: list[dict]) -> list[list]:
    boxes = []
    for block in word_blocks:
        box = (block.get("Geometry") or {}).get("BoundingBox") or {}
        chu = block.get("Text") or ""
        if not chu or not {"Left", "Top", "Width", "Height"} <= box.keys():
            continue
        x0, y0 = float(box["Left"]), float(box["Top"])
        boxes.append([
            chu,
            round(x0, 4),
            round(y0, 4),
            round(x0 + float(box["Width"]), 4),
            round(y0 + float(box["Height"]), 4),
        ])
    return boxes


def _parse_textract(blocks: list[dict]) -> dict:
    by_id = {block["Id"]: block for block in blocks if "Id" in block}

    per_page: dict[int, list[dict]] = {}
    for block in blocks:
        per_page.setdefault(int(block.get("Page") or 1), []).append(block)

    pages = []
    text_parts = []

    for page_number in sorted(per_page):
        page_blocks = per_page[page_number]
        of_type = lambda kind: [b for b in page_blocks if b["BlockType"] == kind]

        lines = of_type("LINE")
        words = of_type("WORD")
        word_confidences = [c for c in (_confidence(w) for w in words) if c is not None]

        text_parts.extend(line.get("Text", "") for line in lines)

        pages.append(
            {
                "page_number": page_number,
                "lines": [
                    {"text": line.get("Text", ""), "confidence": _confidence(line)}
                    for line in lines
                ],
                # LAYOUT_* đóng đúng vai `blocks` của Document AI: gom dòng rời
                # thành khối ngữ nghĩa, nhờ đó tên công ty và địa chỉ dính liền
                # thay vì bị chữ trong logo chen vào giữa. Giữ '\n' bên trong
                # khối y hệt Document AI để `_build_ocr_text` xử lý CHUNG một
                # đường, không phải rẽ nhánh theo engine.
                #
                # DetectDocumentText KHÔNG trả LAYOUT_* (rẻ hơn 43 lần) nên
                # danh sách này rỗng, và `_build_ocr_text` tự rơi về `text`.
                "blocks": [
                    khoi
                    for khoi in (
                        _child_text(block, by_id, separator="\n")
                        for block in page_blocks
                        if block["BlockType"].startswith("LAYOUT_")
                    )
                    if khoi
                ],
                "tables": [
                    {"rows": _table_rows(table, by_id)} for table in of_type("TABLE")
                ],
                "key_value_pairs": _key_value_pairs(page_blocks, by_id),
                "words": _word_boxes(words),
                # Confidence THẬT từ OCR — khác với confidence do LLM tự khai.
                "token_count": len(words),
                "mean_token_confidence": (
                    round(sum(word_confidences) / len(word_confidences), 4)
                    if word_confidences
                    else None
                ),
            }
        )

    # Textract không trả text tổng — phải tự nối từ các LINE theo thứ tự đọc.
    return {"text": "\n".join(text_parts), "pages": pages}


def _run_job(content: bytes, mime_type: str, s3_key: str | None, features: list[str] | None) -> dict:
    bucket, key, phai_upload = _stage_target(content, mime_type, s3_key)
    s3 = aws_real.s3_client() if phai_upload else None

    if phai_upload:
        s3.put_object(Bucket=bucket, Key=key, Body=content, ContentType=mime_type)

    try:
        client = aws_real.textract_client()
        location = {"S3Object": {"Bucket": bucket, "Name": key}}

        if features:
            job_id = client.start_document_analysis(
                DocumentLocation=location, FeatureTypes=features
            )["JobId"]
            get_result = client.get_document_analysis
        else:
            job_id = client.start_document_text_detection(DocumentLocation=location)["JobId"]
            get_result = client.get_document_text_detection

        def fetch(next_token):
            # boto3 từ chối NextToken=None — chỉ gửi khi thật sự có.
            kwargs = {"JobId": job_id}
            if next_token:
                kwargs["NextToken"] = next_token
            return get_result(**kwargs)

        blocks, _ = _await_blocks(fetch)
    except Exception as exc:
        # Throttle phải thành RateLimitError, nếu không nhánh Retry của Step
        # Functions (ErrorEquals ["RateLimitError"]) không bao giờ chạy.
        _raise_if_rate_limited(exc)
        raise
    finally:
        # Job hỏng vẫn phải dọn, nếu không bucket tạm phình mãi.
        if phai_upload:
            s3.delete_object(Bucket=bucket, Key=key)

    return _parse_textract(blocks)


def ocr_with_textract(
    content: bytes, mime_type: str = "application/pdf", *, s3_key: str | None = None
) -> dict:
    """DetectDocumentText — $0,0015/trang, ngang giá Enterprise Document OCR.

    Chỉ text + dòng + confidence: KHÔNG key-value, KHÔNG bảng, KHÔNG khối ngữ
    nghĩa. Đây là đối thủ trực tiếp của `dococr` để so sạch cùng một mức giá.
    """
    return _run_job(content, mime_type, s3_key, features=None)


def ocr_with_textract_analyze(
    content: bytes, mime_type: str = "application/pdf", *, s3_key: str | None = None
) -> dict:
    """AnalyzeDocument FORMS+TABLES+LAYOUT — $0,065/trang.

    Đắt hơn Form Parser ($0,030) hai lần và hơn Document OCR 43 lần. Đổi lại có
    đủ key-value, bảng và khối ngữ nghĩa — tức là toàn bộ hợp đồng OCR.
    """
    return _run_job(content, mime_type, s3_key, features=ANALYZE_FEATURES)
