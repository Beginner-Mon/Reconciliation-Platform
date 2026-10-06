"""Worker extract: dữ liệu AI thay dữ liệu người sửa thì nhãn "đã sửa tay" mất theo.

Chạy thật mới lộ: sau `force_edited=true`, record vẫn mang `edited_fields` dù dữ
liệu đã là của AI. Giao diện hiện "đã sửa tay" trên dữ liệu AI, và lần `force`
sau vẫn bỏ qua chứng từ như thể còn công review để bảo vệ.

Nhãn chỉ được xoá ĐÚNG LÚC `extraction` bị thay. Xoá sớm hơn (lúc bấm chạy) thì
OCR hay Gemini hỏng giữa chừng sẽ để lại dữ liệu người sửa mà mất nhãn bảo vệ.
Lịch sử không mất: `EDIT_OVERWRITTEN` đã ghi ai, lúc nào, trường nào.
"""

import pytest

from common.dynamodb import DOCUMENTS_TABLE, get_item, put_item
from common.ids import new_document_id, new_project_id
from common.s3 import ocr_key, write_json

KET_QUA_GIA = {
    "document_type": "invoice",
    "data": {"invoice_number": "3126818", "vendor_tax_code": "0102721191-068"},
    "confidence": {"vendor_tax_code": 0.9},
}


@pytest.fixture
def da_sua_tay(aws):
    project_id, document_id = new_project_id(), new_document_id()
    key = ocr_key(project_id, document_id)
    write_json(key, {"text": "3126818 0102721191-068", "pages": []})
    put_item(
        DOCUMENTS_TABLE,
        {
            "document_id": document_id,
            "project_id": project_id,
            "edited_fields": ["vendor_tax_code"],
            "edited_by": "tri",
            "edited_at": "2026-09-16T08:00:00+00:00",
        },
    )
    return {"project_id": project_id, "document_id": document_id, "ocr_s3_key": key}


def _doc(document_id: str) -> dict:
    return get_item(DOCUMENTS_TABLE, {"document_id": document_id})


def test_ai_ghi_de_thi_xoa_nhan_sua_tay(da_sua_tay, monkeypatch):
    monkeypatch.setattr("workers.extract.extract_with_gemini", lambda ocr_json: dict(KET_QUA_GIA))
    from workers.extract import lambda_handler

    lambda_handler(da_sua_tay, None)

    doc = _doc(da_sua_tay["document_id"])
    assert doc["edited_fields"] == []
    assert doc.get("edited_by") is None
    assert doc.get("edited_at") is None


def test_gemini_loi_thi_giu_nguyen_nhan_sua_tay(da_sua_tay, monkeypatch):
    def hong(ocr_json):
        raise RuntimeError("Gemini sập")

    monkeypatch.setattr("workers.extract.extract_with_gemini", hong)
    from workers.extract import lambda_handler

    with pytest.raises(RuntimeError):
        lambda_handler(da_sua_tay, None)

    doc = _doc(da_sua_tay["document_id"])
    assert doc["edited_fields"] == ["vendor_tax_code"]
    assert doc["edited_by"] == "tri"


def test_ngay_sai_duoc_go_ban_tho_con_nguyen(aws, monkeypatch):
    from common.s3 import read_json

    project_id, document_id = new_project_id(), new_document_id()
    key = ocr_key(project_id, document_id)
    write_json(key, {"text": "hoa don ngay 28/12/2024", "pages": []})
    put_item(DOCUMENTS_TABLE, {"document_id": document_id, "project_id": project_id})
    trich_tho = {
        "document_type": "invoice",
        "role": "billing",
        "doc_number": "INV-1",
        "doc_date": "28/12/2024",
        "other_fields": {},
        "tables": [],
    }
    monkeypatch.setattr(
        "workers.extract.extract_with_gemini",
        lambda ocr_json: {"document_type": "invoice", "data": dict(trich_tho)},
    )
    from workers.extract import lambda_handler

    lambda_handler({"document_id": document_id, "project_id": project_id, "ocr_s3_key": key}, None)

    doc = _doc(document_id)
    assert "doc_date" not in doc["extraction"]
    assert [m["field"] for m in doc["format_issues"]] == ["doc_date"]
    assert doc["format_issues"][0]["value"] == "28/12/2024"
    assert read_json(doc["extraction_s3_key"])["data"] == trich_tho

    from workers.validate import lambda_handler as kiem_tra

    assert kiem_tra({"document_id": document_id, "project_id": project_id}, None)["status"] == "VALIDATED"
    co = _doc(document_id)["validation"]["flags"]
    assert any(
        f["code"] == "ai_format" and f["field"] == "doc_date"
        and f["values"] == {"gia_tri_goc": "28/12/2024"}
        for f in co
    )
