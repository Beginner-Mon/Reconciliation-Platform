import json
import os
import time

from schemas import describe_all_types, supported_types

from .errors import RateLimitError

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
DOCAI_PROJECT = os.environ.get("DOCAI_PROJECT", "")
DOCAI_LOCATION = os.environ.get("DOCAI_LOCATION", "us")
DOCAI_PROCESSOR_ID = os.environ.get("DOCAI_PROCESSOR_ID", "")
OCR_MIME_TYPE = os.environ.get("OCR_MIME_TYPE", "application/pdf")

PROMPT_TEMPLATE = """Bạn là hệ thống trích xuất chứng từ doanh nghiệp tiếng Việt.
Tài liệu thuộc một trong các loại: <<DOC_TYPES>>.
Trả về DUY NHẤT một JSON object, không kèm text khác, đúng cấu trúc:

{
  "document_type": <<DOC_TYPE_ENUM>>,
  "data": { ... các trường theo loại ... },
  "confidence": { "tên_trường": 0.0-1.0 }
}

<<DOC_TYPE_FIELDS>>

Quy tắc:
- Số tiền trả về dạng int (VND không có phần lẻ); quantity là int.
- Ngày theo định dạng YYYY-MM-DD.
- Trường không tìm thấy trong tài liệu thì bỏ qua (không đưa vào data).
- Không bịa dữ liệu: nếu không chắc, để confidence thấp hơn 0.8.
- Đọc kỹ bảng line items nếu có.

Nội dung OCR của tài liệu:
<<OCR_TEXT>>
"""

# KHÔNG đặt response_schema với "data": {"type": "OBJECT"} rỗng.
# Structured output của Gemini hiểu OBJECT không có `properties` là "không có
# trường nào" và luôn trả về {} — đo thực tế: 31 output token, data rỗng, so với
# 447 token và 7 field khi bỏ response_schema.
# Không thể khai schema cụ thể vì 1 call vừa classify vừa extract, chưa biết loại
# chứng từ trước khi gọi. Ràng buộc kiểu dữ liệu do Pydantic ở core/validate.py
# đảm nhiệm — LLM chỉ cần trả JSON hợp lệ.
GENERATION_CONFIG = {
    "response_mime_type": "application/json",
    "temperature": 0,
}

RATE_LIMIT_MARKERS = (
    "429",
    "resource_exhausted",
    "resourceexhausted",
    "rate limit",
    "ratelimit",
    "quota exceeded",
    "too many requests",
    "503",
    "unavailable",
)


def _raise_if_rate_limited(exc: Exception) -> None:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if any(marker in text or marker in name for marker in RATE_LIMIT_MARKERS):
        raise RateLimitError(f"{type(exc).__name__}: {exc}") from exc


def build_extraction_prompt(ocr_text: str) -> str:
    types = supported_types()
    return (
        PROMPT_TEMPLATE.replace("<<DOC_TYPES>>", ", ".join(types))
        .replace("<<DOC_TYPE_ENUM>>", " | ".join(f'"{t}"' for t in types))
        .replace("<<DOC_TYPE_FIELDS>>", describe_all_types())
        .replace("<<OCR_TEXT>>", ocr_text)
    )


def ocr_with_document_ai(
    content: bytes, mime_type: str = OCR_MIME_TYPE, processor_id: str | None = None
) -> dict:
    from google.api_core.client_options import ClientOptions
    from google.cloud import documentai
    from google.oauth2 import service_account

    processor_id = processor_id or DOCAI_PROCESSOR_ID
    if not DOCAI_PROJECT or not processor_id:
        raise RuntimeError("Thiếu DOCAI_PROJECT / DOCAI_PROCESSOR_ID")

    credentials = None
    secret_name = os.environ.get("GOOGLE_SA_KEY_SECRET", "")
    if secret_name:
        import boto3

        response = boto3.client("secretsmanager").get_secret_value(SecretId=secret_name)
        credentials = service_account.Credentials.from_service_account_info(
            json.loads(response["SecretString"])
        )

    client = documentai.DocumentProcessorServiceClient(
        client_options=ClientOptions(api_endpoint=f"{DOCAI_LOCATION}-documentai.googleapis.com"),
        credentials=credentials,
    )
    name = client.processor_path(DOCAI_PROJECT, DOCAI_LOCATION, processor_id)
    raw_document = documentai.RawDocument(content=content, mime_type=mime_type)
    try:
        response = client.process_document(
            request=documentai.ProcessRequest(name=name, raw_document=raw_document)
        )
    except Exception as exc:
        _raise_if_rate_limited(exc)
        raise

    return _parse_documentai(response.document)


def _layout_text(layout, full_text: str) -> str:
    """Document AI không trả text trên từng phần tử.

    Nó trả `text_anchor` chứa offset trỏ vào `document.text`; phải tự cắt chuỗi.
    Đây là chỗ code v1 sai: giả định có thuộc tính `.text`.
    """
    anchor = getattr(layout, "text_anchor", None)
    if anchor is None:
        return ""
    parts = []
    for segment in anchor.text_segments:
        start = int(segment.start_index or 0)
        end = int(segment.end_index or 0)
        parts.append(full_text[start:end])
    return "".join(parts).strip()


def _layout_confidence(layout) -> float | None:
    value = getattr(layout, "confidence", None)
    return round(float(value), 4) if value else None


def _parse_documentai(doc) -> dict:
    text = doc.text or ""
    pages = []

    for page in doc.pages:
        tokens = list(getattr(page, "tokens", []) or [])
        token_confidences = [
            c for c in (_layout_confidence(t.layout) for t in tokens) if c is not None
        ]

        rows_of = lambda table: list(getattr(table, "header_rows", []) or []) + list(
            getattr(table, "body_rows", []) or []
        )

        pages.append(
            {
                "page_number": page.page_number,
                # Kèm confidence TỪNG DÒNG để người review nhìn ra chỗ OCR không
                # chắc, thay vì một khối text phẳng không biết tin chỗ nào.
                # An toàn về chi phí: _build_ocr_text KHÔNG đọc `lines` (nó dùng
                # `text`), nên prompt gửi Gemini không phình theo.
                "lines": [
                    {
                        "text": _layout_text(line.layout, text),
                        "confidence": _layout_confidence(line.layout),
                    }
                    for line in (page.lines or [])
                ],
                "tables": [
                    {
                        "rows": [
                            {"cells": [_layout_text(cell.layout, text) for cell in row.cells]}
                            for row in rows_of(table)
                        ]
                    }
                    for table in (page.tables or [])
                ],
                # Document AI gọi là form_fields, KHÔNG phải key_value_pairs.
                "key_value_pairs": [
                    {
                        "key": _layout_text(field.field_name, text),
                        "value": _layout_text(field.field_value, text),
                        "confidence": _layout_confidence(field.field_value),
                    }
                    for field in (getattr(page, "form_fields", []) or [])
                ],
                # Confidence THẬT từ OCR — khác với confidence do LLM tự khai.
                "token_count": len(tokens),
                "mean_token_confidence": (
                    round(sum(token_confidences) / len(token_confidences), 4)
                    if token_confidences
                    else None
                ),
            }
        )

    return {"text": text, "pages": pages}


def ocr_with_layout_parser(content: bytes, mime_type: str = OCR_MIME_TYPE) -> dict:
    """Gemini Layout Parser — $10/1000 trang.

    Khác hai processor kia: xử lý được bảng phức tạp (merge cell, header lồng)
    và trả về document đã chia chunk theo cấu trúc, không phải theo page/token.
    Vì response khác hình dạng nên không dùng chung parser với Form Parser.
    """
    from google.api_core.client_options import ClientOptions
    from google.cloud import documentai
    from google.oauth2 import service_account

    processor_id = os.environ.get("DOCAI_LAYOUT_PROCESSOR_ID", "")
    if not DOCAI_PROJECT or not processor_id:
        raise RuntimeError("Thiếu DOCAI_PROJECT / DOCAI_LAYOUT_PROCESSOR_ID")

    credentials = None
    secret_name = os.environ.get("GOOGLE_SA_KEY_SECRET", "")
    if secret_name:
        import boto3

        response = boto3.client("secretsmanager").get_secret_value(SecretId=secret_name)
        credentials = service_account.Credentials.from_service_account_info(
            json.loads(response["SecretString"])
        )

    client = documentai.DocumentProcessorServiceClient(
        client_options=ClientOptions(api_endpoint=f"{DOCAI_LOCATION}-documentai.googleapis.com"),
        credentials=credentials,
    )
    try:
        response = client.process_document(
            request=documentai.ProcessRequest(
                name=client.processor_path(DOCAI_PROJECT, DOCAI_LOCATION, processor_id),
                raw_document=documentai.RawDocument(content=content, mime_type=mime_type),
                process_options=documentai.ProcessOptions(
                    layout_config=documentai.ProcessOptions.LayoutConfig(
                        chunking_config=documentai.ProcessOptions.LayoutConfig.ChunkingConfig(
                            chunk_size=1000, include_ancestor_headings=True
                        )
                    )
                ),
            )
        )
    except Exception as exc:
        _raise_if_rate_limited(exc)
        raise

    doc = response.document
    chunks = [c.content for c in getattr(doc.chunked_document, "chunks", [])]
    return {
        "text": doc.text,
        "chunks": chunks,
        "pages": [{"page_number": i + 1} for i in range(len(doc.pages) or 1)],
    }


def _build_ocr_text(ocr_json: dict) -> str:
    """Gộp output OCR thành prompt cho Gemini.

    Bảng được giữ dạng markdown có header thay vì nối phẳng bằng '|', và được
    đánh dấu rõ ranh giới — nếu không, cấu trúc bảng mà Form Parser tách ra
    (thứ đắt nhất mình trả tiền) sẽ bị làm phẳng trước khi Gemini nhìn thấy.
    """
    parts = [ocr_json.get("text", "")]

    for chunk in ocr_json.get("chunks") or []:
        parts.append(chunk)

    for page in ocr_json.get("pages", []):
        kvs = page.get("key_value_pairs") or []
        if kvs:
            parts.append("--- Trường điền trong biểu mẫu ---")
            parts.extend(f"{kv['key']}: {kv['value']}" for kv in kvs)

        for index, table in enumerate(page.get("tables") or [], start=1):
            rows = table.get("rows") or []
            if not rows:
                continue
            parts.append(f"--- Bảng {index} (trang {page.get('page_number', '?')}) ---")
            header, *body = rows
            parts.append("| " + " | ".join(header["cells"]) + " |")
            parts.append("|" + "---|" * len(header["cells"]))
            for row in body:
                parts.append("| " + " | ".join(row["cells"]) + " |")
            parts.append("--- Hết bảng ---")

    return "\n".join(p for p in parts if p)


def extract_with_gemini(ocr_json: dict) -> dict:
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Thiếu GEMINI_API_KEY")

    client = genai.Client(api_key=api_key)
    prompt = build_extraction_prompt(_build_ocr_text(ocr_json))
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=GENERATION_CONFIG,
        )
    except Exception as exc:
        _raise_if_rate_limited(exc)
        raise

    usage = response.usage_metadata
    result = json.loads(response.text)
    result["_usage"] = {
        "prompt_tokens": usage.prompt_token_count,
        "output_tokens": usage.candidates_token_count,
    }
    return result


# Đơn giá USD, kiểm tra 2026-08-17. Nguồn:
#   https://ai.google.dev/gemini-api/docs/pricing
#   https://cloud.google.com/document-ai/pricing
# Đặt qua biến môi trường khi giá đổi, không sửa code.
GEMINI_INPUT_USD_PER_1M = float(os.environ.get("GEMINI_INPUT_USD_PER_1M", "0.30"))
GEMINI_OUTPUT_USD_PER_1M = float(os.environ.get("GEMINI_OUTPUT_USD_PER_1M", "2.50"))

# Giá theo processor, $/trang:
#   Enterprise Document OCR $1.50/1000 | Layout Parser $10/1000
#   Form Parser $30/1000    | Custom Extractor $30/1000
# Đổi processor thì PHẢI đổi biến này, nếu không chi phí trong audit_log sẽ sai.
DOCAI_USD_PER_PAGE = float(os.environ.get("DOCAI_USD_PER_PAGE", "0.030"))
DOCAI_OCR_USD_PER_PAGE = float(os.environ.get("DOCAI_OCR_USD_PER_PAGE", "0.0015"))


def extract_with_gemini_pdf(content: bytes, mime_type: str = "application/pdf") -> dict:
    """Gemini đọc thẳng file gốc, KHÔNG qua Document AI.

    Dùng cho spike so sánh chi phí/độ chính xác với luồng có OCR. Nếu luồng này
    thắng thì bỏ được Document AI khỏi pipeline (rẻ hơn ~20-50 lần mỗi trang).
    """
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Thiếu GEMINI_API_KEY")

    client = genai.Client(api_key=api_key)
    prompt = build_extraction_prompt("(đọc trực tiếp từ file đính kèm)")
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                types.Part.from_bytes(data=content, mime_type=mime_type),
                prompt,
            ],
            config=GENERATION_CONFIG,
        )
    except Exception as exc:
        _raise_if_rate_limited(exc)
        raise

    usage = response.usage_metadata
    result = json.loads(response.text)
    result["_usage"] = {
        "prompt_tokens": usage.prompt_token_count,
        "output_tokens": usage.candidates_token_count,
    }
    return result


def estimate_gemini_cost(usage: dict) -> float:
    prompt_tokens = usage.get("prompt_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    return (
        prompt_tokens * GEMINI_INPUT_USD_PER_1M + output_tokens * GEMINI_OUTPUT_USD_PER_1M
    ) / 1_000_000


def estimate_docai_cost(page_count: int) -> float:
    return page_count * DOCAI_USD_PER_PAGE


def now_ms() -> int:
    return int(time.time() * 1000)
