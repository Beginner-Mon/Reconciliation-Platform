"""Chặn tái phát bug: response_schema rỗng làm Gemini luôn trả data = {}.

Đo thực tế trên ảnh hóa đơn thật:
  có response_schema với data = OBJECT rỗng  ->  31 output token, 0 field
  bỏ response_schema                          -> 447 output token, 7 field
"""

import pytest

from common.ai_clients import GENERATION_CONFIG, _raise_if_rate_limited, build_extraction_prompt
from common.errors import RateLimitError
from schemas import supported_types


# --- Throttle của AWS phải được nhận ra, không chỉ của Google --------------
#
# `RATE_LIMIT_MARKERS` viết cho Document AI/Gemini nên chỉ có "429",
# "quota exceeded", "rate limit"... KHÔNG chuỗi nào khớp tên lỗi của Textract.
# Không nhận ra thì lỗi không thành `RateLimitError`, và nhánh
#     "Retry": [{"ErrorEquals": ["RateLimitError"], ...}]
# trong statemachine.asl.json KHÔNG BAO GIỜ chạy — chứng từ chết luôn thay vì
# được thử lại. Bị throttle là chuyện thường khi Map chạy 3 doc song song.


@pytest.mark.parametrize(
    "loi",
    [
        "ThrottlingException",
        "ProvisionedThroughputExceededException",
        "LimitExceededException",
    ],
)
def test_throttle_cua_aws_duoc_coi_la_rate_limit(loi):
    exc = type(loi, (Exception,), {})("Rate exceeded")
    with pytest.raises(RateLimitError):
        _raise_if_rate_limited(exc)


def test_throttle_dang_ClientError_cung_bat_duoc():
    """botocore gói lỗi vào ClientError, tên thật nằm trong CHUỖI thông báo."""
    exc = Exception(
        "An error occurred (ThrottlingException) when calling the "
        "StartDocumentAnalysis operation: Rate exceeded"
    )
    with pytest.raises(RateLimitError):
        _raise_if_rate_limited(exc)


def test_loi_thuong_khong_bi_nham_thanh_rate_limit():
    """Nhận nhầm thì Step Functions retry 4 lần một lỗi không bao giờ tự khỏi."""
    _raise_if_rate_limited(ValueError("file PDF hỏng"))


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


def test_prompt_giu_truong_ngoai_bang_va_khong_tu_tinh():
    prompt = build_extraction_prompt("Shipping 50\nPhụ phí bất kỳ 20")
    assert "TOÀN BỘ nhãn–giá trị ngoài bảng" in prompt
    assert "Không tự tính bù, sửa số" in prompt
    assert "Số lượng, đơn giá, thành tiền phải khớp khi đủ dữ liệu" not in prompt
    assert "Shipping 50" in prompt


def test_prompt_giai_thich_chiet_khau_hoa_don():
    prompt = build_extraction_prompt("nội dung OCR")
    assert "discount_amount (int)" in prompt
    assert "tổng chiết khấu thương mại" in prompt
    assert "subtotal = tiền hàng sau chiết khấu, chưa thuế" in prompt


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


def test_gemini_key_uu_tien_env_truoc_secret(monkeypatch):
    """Env thắng secret — devserver và evaluation vẫn chạy bằng evaluation/.env."""
    import common.ai_clients as ai

    monkeypatch.setenv("GEMINI_API_KEY", "k-tu-env")
    monkeypatch.setenv("GEMINI_API_KEY_SECRET", "ten-secret-nao-do")
    ai._gemini_api_key_cache = None
    assert ai.get_gemini_api_key() == "k-tu-env"


def test_gemini_key_doc_secret_mot_lan_roi_cache(monkeypatch):
    """Không có env thì đọc secret đúng 1 lần rồi cache trong tiến trình."""
    import common.ai_clients as ai

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY_SECRET", "ten-secret")
    ai._gemini_api_key_cache = None

    goi = []

    class FakeSecrets:
        def get_secret_value(self, SecretId):
            goi.append(SecretId)
            return {"SecretString": "k-tu-secret"}

    monkeypatch.setattr("boto3.client", lambda *a, **k: FakeSecrets())
    assert ai.get_gemini_api_key() == "k-tu-secret"
    assert ai.get_gemini_api_key() == "k-tu-secret"
    assert goi == ["ten-secret"]


def test_gemini_key_thieu_ca_hai_thi_loi(monkeypatch):
    import common.ai_clients as ai

    import pytest

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY_SECRET", raising=False)
    ai._gemini_api_key_cache = None
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        ai.get_gemini_api_key()


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
