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
