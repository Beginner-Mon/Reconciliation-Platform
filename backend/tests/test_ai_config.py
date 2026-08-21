"""Chặn tái phát bug: response_schema rỗng làm Gemini luôn trả data = {}.

Đo thực tế trên ảnh hóa đơn thật:
  có response_schema với data = OBJECT rỗng  ->  31 output token, 0 field
  bỏ response_schema                          -> 447 output token, 7 field
"""

from common.ai_clients import GENERATION_CONFIG, build_extraction_prompt
from schemas import supported_types


def test_khong_dat_response_schema_rong():
    schema = GENERATION_CONFIG.get("response_schema")
    if schema is None:
        return
    data_schema = schema.get("properties", {}).get("data", {})
    assert data_schema.get("properties"), (
        "response_schema khai 'data' là OBJECT không có properties — "
        "Gemini sẽ luôn trả data rỗng. Xem comment trong ai_clients.py."
    )


def test_van_bat_buoc_tra_json():
    assert GENERATION_CONFIG["response_mime_type"] == "application/json"


def test_temperature_bang_0_de_ket_qua_on_dinh():
    assert GENERATION_CONFIG["temperature"] == 0


def test_prompt_mo_ta_du_moi_loai_chung_tu():
    prompt = build_extraction_prompt("noi dung ocr")
    for document_type in supported_types():
        assert document_type in prompt, f"prompt thiếu mô tả cho {document_type}"


def test_prompt_co_chen_noi_dung_ocr():
    prompt = build_extraction_prompt("NOI_DUNG_DAC_BIET_123")
    assert "NOI_DUNG_DAC_BIET_123" in prompt
    assert "<<OCR_TEXT>>" not in prompt


def test_prompt_dat_unknown_o_CUOI_va_kem_dieu_kien():
    """Gemini đọc hết các loại cụ thể rồi mới tới phương án dự phòng.

    Đặt "unknown" lên trước thì nó khớp ngay cái đầu tiên và không bao giờ
    phân loại đúng nữa. Ràng buộc nằm ở NHÃN trong registry, không viết tay vào
    prompt — prompt sinh từ registry (§5 CLAUDE.md).
    """
    from common.ai_clients import build_extraction_prompt

    prompt = build_extraction_prompt("nội dung ocr bất kỳ")
    assert prompt.index('"unknown"') > prompt.index('"invoice"')
    assert prompt.rindex("unknown") > prompt.rindex("acceptance_record")
    assert "KHÔNG khớp bất kỳ loại nào ở trên" in prompt


def test_nhan_hien_thi_khong_duoc_lan_vao_giai_thich_mau_thuan():
    """DOCUMENT_TYPE_LABELS đọc cho NGƯỜI, không phải chỗ nhét lệnh cho Gemini.

    Đã lộ khi chạy thật: giải thích mâu thuẫn hiện ra
    "currency không khớp: CHỈ dùng khi tài liệu KHÔNG khớp bất kỳ loại nào ở
    trên=VND" — vì một bảng bị dùng cho hai người đọc khác nhau.
    """
    from core.rules import label
    from schemas import DOCUMENT_TYPES

    for document_type in DOCUMENT_TYPES:
        rendered = label(document_type)
        assert len(rendered) <= 30, f"{document_type}: nhãn quá dài, {rendered!r}"
        assert "CHỈ" not in rendered and "KHÔNG khớp" not in rendered
