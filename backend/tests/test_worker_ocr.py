"""Worker OCR chọn engine bằng `OCR_ENGINE` — và ghi audit theo ĐÚNG engine đó.

Đây là chỗ đã sai một lần: nhãn ghi cứng "documentai-form-parser" trong khi
tiền trả cho processor khác, làm ước tính chi phí lệch 20 lần (§5 CLAUDE.md).
Với năm engine, nhãn và đơn giá phải luôn lấy từ cùng một chỗ với hàm được gọi.
"""

import pytest

from common.dynamodb import DOCUMENTS_TABLE, put_item
from common.ids import new_document_id, new_project_id
from common.s3 import write_object
from common.dynamodb import AUDIT_LOG_TABLE, scan_table
from common.s3 import upload_key

OCR_GIA = {
    "text": "Joma Bakery",
    "pages": [{"page_number": 1, "lines": []}, {"page_number": 2, "lines": []}],
}


@pytest.fixture
def tai_lieu(aws):
    project_id, document_id = new_project_id(), new_document_id()
    key = upload_key(project_id, document_id, ".pdf")
    write_object(key, b"%PDF-1.4 gia lap", content_type="application/pdf")
    put_item(
        DOCUMENTS_TABLE,
        {"document_id": document_id, "project_id": project_id, "s3_key": key},
    )
    return {"project_id": project_id, "document_id": document_id, "s3_key": key}


@pytest.fixture
def engine_gia(monkeypatch):
    """Ghi lại engine nào được gọi, thay vì thật sự gọi Google/AWS."""
    da_goi = []

    def fake_run(name, content, mime_type, s3_key=None):
        da_goi.append({"engine": name, "mime_type": mime_type, "s3_key": s3_key})
        return OCR_GIA

    monkeypatch.setattr("common.ocr_engines.run", fake_run)
    return da_goi


def _ai_calls() -> list[dict]:
    return [
        item["detail"]
        for item in scan_table(AUDIT_LOG_TABLE)
        if item.get("action") == "AI_CALL"
    ]


def test_khong_khai_gi_thi_dung_engine_mac_dinh(tai_lieu, engine_gia, monkeypatch):
    monkeypatch.delenv("OCR_ENGINE", raising=False)
    from common import ocr_engines
    from workers.ocr import lambda_handler

    lambda_handler(tai_lieu, None)

    assert engine_gia[0]["engine"] == ocr_engines.DEFAULT_ENGINE


# --- Engine đi theo LẦN CHẠY, không theo tiến trình ------------------------


def test_engine_trong_event_thang_bien_moi_truong(tai_lieu, engine_gia, monkeypatch):
    """Đây là cả điểm của thay đổi này.

    `OCR_ENGINE` là biến môi trường nên nó cố định cho cả một deployment Lambda
    / cả một phiên devserver. Không đọc từ event thì KHÔNG THỂ chạy hai engine
    trên hai chứng từ của cùng một project — tức không so được engine nào đọc
    tiếng Việt tốt hơn trên cùng một tờ hoá đơn.
    """
    monkeypatch.setenv("OCR_ENGINE", "dococr")
    from workers.ocr import lambda_handler

    lambda_handler({**tai_lieu, "ocr_engine": "textract"}, None)

    assert engine_gia[0]["engine"] == "textract"
    assert _ai_calls()[0]["model"] == "textract-detect-document-text"


def test_khong_co_trong_event_thi_roi_ve_bien_moi_truong(
    tai_lieu, engine_gia, monkeypatch
):
    """Nước lui cho production đã deploy: state machine cũ không truyền khoá này."""
    monkeypatch.setenv("OCR_ENGINE", "dococr")
    from workers.ocr import lambda_handler

    lambda_handler(tai_lieu, None)

    assert engine_gia[0]["engine"] == "dococr"


def test_luu_lai_engine_da_chay_vao_document(tai_lieu, engine_gia, monkeypatch):
    """Không lưu thì giao diện không có cách nào biết chứng từ này chạy bằng gì.

    Nhãn CÓ vào audit_log, nhưng bảng đó chưa có route API nào đọc.
    """
    from common.dynamodb import DOCUMENTS_TABLE, get_item
    from workers.ocr import lambda_handler

    lambda_handler({**tai_lieu, "ocr_engine": "textract"}, None)

    document = get_item(DOCUMENTS_TABLE, {"document_id": tai_lieu["document_id"]})
    assert document["ocr_engine"] == "textract"


def test_engine_sai_trong_event_cung_no(tai_lieu, engine_gia, monkeypatch):
    monkeypatch.setenv("OCR_ENGINE", "dococr")
    from workers.ocr import lambda_handler

    with pytest.raises(ValueError, match="textrakt"):
        lambda_handler({**tai_lieu, "ocr_engine": "textrakt"}, None)

    assert engine_gia == []


def test_OCR_ENGINE_chon_dung_engine_va_ghi_dung_nhan(tai_lieu, engine_gia, monkeypatch):
    monkeypatch.setenv("OCR_ENGINE", "textract")
    from workers.ocr import lambda_handler

    lambda_handler(tai_lieu, None)

    assert engine_gia[0]["engine"] == "textract"
    ghi = _ai_calls()[0]
    assert ghi["model"] == "textract-detect-document-text"
    assert ghi["status"] == "ok"


def test_chi_phi_tinh_theo_don_gia_cua_dung_engine(tai_lieu, engine_gia, monkeypatch):
    """2 trang x $0,065 = $0,13. Lấy nhầm đơn giá dococr sẽ ra $0,003."""
    monkeypatch.setenv("OCR_ENGINE", "textract-analyze")
    from workers.ocr import lambda_handler

    lambda_handler(tai_lieu, None)

    assert float(_ai_calls()[0]["estimated_cost_usd"]) == pytest.approx(0.13)


def test_truyen_s3_key_xuong_engine(tai_lieu, engine_gia, monkeypatch):
    """Textract async đọc file TỪ S3. Không truyền s3_key thì trên Lambda nó
    phải copy lại file đã nằm sẵn đúng chỗ — tốn tiền và tốn thời gian vô ích."""
    monkeypatch.setenv("OCR_ENGINE", "textract")
    from workers.ocr import lambda_handler

    lambda_handler(tai_lieu, None)

    assert engine_gia[0]["s3_key"] == tai_lieu["s3_key"]
    assert engine_gia[0]["mime_type"] == "application/pdf"


def test_ten_engine_sai_thi_no_chu_khong_am_tham_chay_engine_khac(
    tai_lieu, engine_gia, monkeypatch
):
    monkeypatch.setenv("OCR_ENGINE", "textrakt")
    from workers.ocr import lambda_handler

    with pytest.raises(ValueError, match="textrakt"):
        lambda_handler(tai_lieu, None)

    assert engine_gia == []
