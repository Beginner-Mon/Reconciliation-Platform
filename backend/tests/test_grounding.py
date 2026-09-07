"""Buộc giá trị Gemini trả về phải có thật trong text OCR.

Đây là lỗ hổng cuối trong chuỗi kiểm tra: Pydantic lo kiểu dữ liệu,
`core/validate.py` lo số học trong một chứng từ, `core/rules.py` lo mâu thuẫn
giữa nhiều chứng từ — nhưng KHÔNG ai hỏi "giá trị này có trong tài liệu không".

Prompt có dặn "Không bịa dữ liệu" nhưng đó chỉ là lời nhắc, không cưỡng chế được.
Bịa ra thứ trông hợp lý đúng là kiểu lỗi đặc trưng của LLM.

Nguyên tắc: THÀ BỎ SÓT CÒN HƠN BÁO OAN. Báo oan một lần là người dùng mất tin
vào cảnh báo, và kết quả này chỉ để cảnh báo chứ không chặn document.
"""

from core.grounding import check_grounding

OCR = """HÓA ĐƠN GIÁ TRỊ GIA TĂNG
Đơn vị bán hàng: Công ty TNHH ABC Technology
Mã số thuế: 0301234567
Ngày 05 tháng 08 năm 2026
Tổng cộng: 125.000.000
Laptop Dell XPS 13
"""


def test_gia_tri_co_nguyen_van_thi_khong_bi_danh_dau():
    thieu = check_grounding({"vendor": "Công ty TNHH ABC Technology"}, OCR)
    assert thieu == []


def test_gia_tri_khong_he_co_trong_tai_lieu_thi_bi_danh_dau():
    """Ca quan trọng nhất — Gemini bịa ra một nhà cung cấp khác."""
    thieu = check_grounding({"vendor": "Công ty XYZ Corporation"}, OCR)
    assert thieu == ["vendor"]


def test_ocr_ngat_dong_giua_ten_thi_van_tim_thay():
    """Text OCR xuống dòng giữa chừng, Gemini trả về một chuỗi liền."""
    ocr = "Đơn vị bán hàng: Công ty TNHH\nABC Technology\nMã số thuế: 0301234567"
    assert check_grounding({"vendor": "Công ty TNHH ABC Technology"}, ocr) == []


def test_khac_dau_va_hoa_thuong_thi_khong_bi_danh_dau():
    """OCR đọc mất dấu là lỗi OCR, không phải LLM bịa."""
    ocr = "DON VI BAN HANG: CONG TY TNHH ABC TECHNOLOGY"
    assert check_grounding({"vendor": "Công ty TNHH ABC Technology"}, ocr) == []


def test_so_tien_co_dau_phan_cach_thi_van_tim_thay():
    """OCR ghi 125.000.000, Gemini trả int 125000000."""
    assert check_grounding({"total_amount": 125000000}, OCR) == []


def test_so_tien_khong_co_trong_tai_lieu_thi_bi_danh_dau():
    assert check_grounding({"total_amount": 999999999}, OCR) == ["total_amount"]


def test_truong_ngay_khong_bao_gio_bi_danh_dau():
    """`2026-08-05` vs `05/08/2026` vs `Ngày 05 tháng 08` — quá nhiều biến thể.

    Kiểm ngày chắc chắn báo oan nên bỏ hẳn, kể cả khi giá trị thật sự không có.
    """
    assert check_grounding({"invoice_date": "2020-01-01"}, OCR) == []
    assert check_grounding({"po_date": "2020-01-01"}, OCR) == []


def test_bo_qua_truong_khong_trich_tu_text():
    data = {"document_type": "invoice", "currency": "VND", "vendor": None, "buyer": ""}
    # document_type do LLM phân loại chứ không đọc từ text; None/rỗng thì không xét
    assert "document_type" not in check_grounding(data, OCR)
    assert "vendor" not in check_grounding(data, OCR)
    assert "buyer" not in check_grounding(data, OCR)


def test_ocr_rong_thi_khong_ket_luan_gi():
    """Không có nguồn để đối chiếu thì không được kết tội cả tài liệu."""
    assert check_grounding({"vendor": "Công ty ABC", "total_amount": 5}, "") == []
    assert check_grounding({"vendor": "Công ty ABC"}, None) == []


def test_kiem_ten_mat_hang_trong_items():
    co = check_grounding({"items": [{"item_name": "Laptop Dell XPS 13", "quantity": 100}]}, OCR)
    assert co == []
    khong = check_grounding({"items": [{"item_name": "Máy in Canon", "quantity": 100}]}, OCR)
    assert khong == ["items[0].item_name"]


def test_so_luong_trong_items_khong_bi_kiem():
    """Số lượng lặp lại khắp nơi trong tài liệu, kiểm thì nhiễu hơn là có ích."""
    thieu = check_grounding(
        {"items": [{"item_name": "Laptop Dell XPS 13", "quantity": 777}]}, OCR
    )
    assert thieu == []


def test_ket_qua_di_duoc_ra_toi_API():
    """Ghi vào DynamoDB thôi chưa đủ — không khai trong DOCUMENT_FIELDS thì màn
    review không bao giờ thấy.

    KHÔNG nhét vào `validation`: worker validate ghi đè nguyên cả dict đó và nó
    chạy SAU extract, nhét vào là mất sạch.
    """
    from api.views import document_view

    view = document_view({"document_id": "doc-1", "ungrounded_fields": ["vendor"]})
    assert view["ungrounded_fields"] == ["vendor"]
