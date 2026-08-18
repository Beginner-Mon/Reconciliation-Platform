"""AI giả cho dev — không gọi Document AI/Gemini, không tốn tiền.

Sinh ra một BỘ CHỨNG TỪ KHỚP NHAU (đơn đặt hàng + hóa đơn + biên bản nghiệm thu
cùng một giao dịch) với vài mâu thuẫn cài sẵn, để cross-check có cái để tìm và
demo được đúng chức năng chính của hệ thống.

Loại chứng từ suy ra từ NỘI DUNG file (tìm từ khoá trong vài trăm byte đầu).
Không có từ khoá thì rơi vào loại theo hash nội dung — vẫn tất định, chạy lại
cho kết quả y hệt.

Lưu ý kỹ thuật: workers/ocr.py dùng `from common import ocr_with_document_ai`
nên tên đã bị bind lúc import. Phải patch thuộc tính TRÊN MODULE WORKER, patch
common.ai_clients sẽ không có tác dụng.
"""

import hashlib
import time

MARKER = "__DEV_DOC_TYPE__"

# Độ trễ giả lập, đặt ĐÚNG CHỖ mà AI thật tốn thời gian (trong bước OCR/extract),
# không phải giữa các bước. Nhờ vậy trạng thái step_status="running" tồn tại đủ
# lâu để frontend poll thấy — ở production OCR mất 5-30s nên nó rất rõ.
LATENCY = 0.0

KEYWORDS = {
    "purchase_order": ["purchase order", "don dat hang", "đơn đặt hàng", "po-"],
    "invoice": ["invoice", "hoa don", "hóa đơn", "inv-"],
    "acceptance_record": ["acceptance", "nghiem thu", "nghiệm thu", "bbnt"],
}
FAIL_KEYWORDS = ["__loi__", "corrupt", "loi-"]

PO_NUMBER = "PO-2026-001"
ITEM = "Laptop Dell XPS 13"
ORDERED_QTY = 100
ACCEPTED_QTY = 90            # < số lượng xuất hóa đơn -> invoiced_over_accepted
PO_UNIT_PRICE = 1_250_000
INVOICE_UNIT_PRICE = 1_280_000   # lệch đơn giá -> line_item_unit_price

DATA = {
    "purchase_order": {
        "document_type": "purchase_order",
        "po_number": PO_NUMBER,
        "po_date": "2026-08-01",
        "vendor": "Công ty TNHH ABC Technology",
        "vendor_tax_code": "0301234567",
        "buyer": "Công ty CP XYZ Việt Nam",
        "currency": "VND",
        "items": [
            {
                "item_name": ITEM,
                "quantity": ORDERED_QTY,
                "unit": "cái",
                "unit_price": PO_UNIT_PRICE,
            }
        ],
        "total_amount": ORDERED_QTY * PO_UNIT_PRICE,
        "delivery_date": "2026-09-01",
        "payment_terms": "30 ngày",
    },
    "invoice": {
        "document_type": "invoice",
        "invoice_number": "INV-2026-001",
        "invoice_date": "2026-08-05",
        "vendor": "Công ty TNHH ABC Technology",
        "vendor_tax_code": "0301234567",
        "buyer": "Công ty CP XYZ Việt Nam",
        "currency": "VND",
        "po_number": PO_NUMBER,
        "items": [
            {
                "item_name": ITEM,
                "quantity": ORDERED_QTY,
                "unit": "cái",
                "unit_price": INVOICE_UNIT_PRICE,
            }
        ],
        "total_amount": ORDERED_QTY * INVOICE_UNIT_PRICE,
        "payment_due_date": "2026-09-05",
    },
    "acceptance_record": {
        "document_type": "acceptance_record",
        "record_number": "BBNT-2026-001",
        "record_date": "2026-08-03",
        "vendor": "Công ty TNHH ABC Technology",
        "vendor_tax_code": "0301234567",
        "buyer": "Công ty CP XYZ Việt Nam",
        "po_number": PO_NUMBER,
        "items": [{"item_name": ITEM, "quantity": ACCEPTED_QTY, "unit": "cái"}],
        "accepted_by": "Nguyễn Văn A",
        "notes": "Nghiệm thu từng phần",
    },
}

CONFIDENCE = {
    "purchase_order": {"po_number": 0.98, "vendor": 0.95, "total_amount": 0.93},
    "invoice": {"invoice_number": 0.97, "vendor": 0.94, "total_amount": 0.88},
    "acceptance_record": {"record_number": 0.96, "vendor": 0.92},
}

ORDER = list(DATA)


def detect_type(content: bytes) -> str:
    head = content[:400].decode("utf-8", errors="ignore").lower()
    if any(k in head for k in FAIL_KEYWORDS):
        raise RuntimeError("File hỏng, không đọc được (giả lập lỗi OCR)")
    for document_type, words in KEYWORDS.items():
        if any(w in head for w in words):
            return document_type
    index = int(hashlib.sha256(content).hexdigest(), 16) % len(ORDER)
    return ORDER[index]


def _ocr_text(document_type: str) -> str:
    data = DATA[document_type]
    title = {
        "purchase_order": "ĐƠN ĐẶT HÀNG",
        "invoice": "HÓA ĐƠN GIÁ TRỊ GIA TĂNG",
        "acceptance_record": "BIÊN BẢN NGHIỆM THU",
    }[document_type]
    item = data["items"][0]
    lines = [
        title,
        f"{MARKER}:{document_type}",
        f"Nhà cung cấp: {data['vendor']}",
        f"Mã số thuế: {data.get('vendor_tax_code', '')}",
        f"Bên mua: {data.get('buyer', '')}",
        f"Số tham chiếu: {data.get('po_number', '')}",
        f"Mặt hàng: {item['item_name']}  SL: {item['quantity']}",
    ]
    if "unit_price" in item:
        lines.append(f"Đơn giá: {item['unit_price']:,}")
        lines.append(f"Tổng tiền: {data['total_amount']:,}")
    return "\n".join(lines)


def fake_ocr(content: bytes, mime_type: str = "application/pdf", processor_id=None) -> dict:
    time.sleep(LATENCY)
    document_type = detect_type(content)
    data = DATA[document_type]
    item = data["items"][0]

    header = ["Mặt hàng", "SL", "ĐVT"]
    row = [item["item_name"], str(item["quantity"]), item.get("unit") or ""]
    if "unit_price" in item:
        header += ["Đơn giá", "Thành tiền"]
        row += [f"{item['unit_price']:,}", f"{item['quantity'] * item['unit_price']:,}"]

    return {
        "text": _ocr_text(document_type),
        "pages": [
            {
                "page_number": 1,
                "lines": _ocr_text(document_type).split("\n"),
                "tables": [{"rows": [{"cells": header}, {"cells": row}]}],
                "key_value_pairs": [
                    {"key": "Nhà cung cấp", "value": data["vendor"], "confidence": 0.94},
                    {
                        "key": "Số tham chiếu",
                        "value": data.get("po_number", ""),
                        "confidence": 0.91,
                    },
                ],
                "token_count": 42,
                "mean_token_confidence": 0.93,
            }
        ],
    }


def fake_extract(ocr_json: dict) -> dict:
    time.sleep(LATENCY)
    text = ocr_json.get("text", "")
    document_type = ORDER[0]
    for line in text.splitlines():
        if line.startswith(MARKER):
            document_type = line.split(":", 1)[1].strip()
            break

    data = {k: v for k, v in DATA[document_type].items() if k != "document_type"}
    return {
        "document_type": document_type,
        "data": data,
        "confidence": CONFIDENCE[document_type],
        "_usage": {"prompt_tokens": 780, "output_tokens": 260},
    }


def install(latency: float = 0.0) -> None:
    """Thay AI thật bằng AI giả trên chính module worker đang dùng chúng."""
    global LATENCY
    LATENCY = latency

    import workers.extract as extract_module
    import workers.ocr as ocr_module

    ocr_module.ocr_with_document_ai = fake_ocr
    extract_module.extract_with_gemini = fake_extract


def sample_files() -> dict[str, bytes]:
    """Nội dung file mẫu để upload — đủ từ khoá cho detect_type nhận ra."""
    return {
        "PO-2026-001.pdf": "PURCHASE ORDER - ĐƠN ĐẶT HÀNG\n".encode("utf-8"),
        "INV-2026-001.pdf": "INVOICE - HÓA ĐƠN GIÁ TRỊ GIA TĂNG\n".encode("utf-8"),
        "BBNT-2026-001.pdf": "BIÊN BẢN NGHIỆM THU - ACCEPTANCE RECORD\n".encode("utf-8"),
    }
