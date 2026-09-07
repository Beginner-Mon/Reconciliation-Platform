"""Kiểm neo: giá trị Gemini trả về có thật sự xuất hiện trong text OCR không.

Chuỗi kiểm tra của hệ thống trước đây thiếu đúng mắt xích này:

    Pydantic          -> kiểu dữ liệu, định dạng
    core/validate.py  -> số học TRONG một chứng từ
    core/rules.py     -> mâu thuẫn GIỮA nhiều chứng từ
    (trống)           -> giá trị có trong tài liệu không   <- ở đây

Prompt có dặn "Không bịa dữ liệu" nhưng đó chỉ là lời nhắc. Bịa ra thứ trông hợp
lý là kiểu lỗi đặc trưng của LLM, và không có gì cưỡng chế được nó.

CẢNH BÁO CHỨ KHÔNG CHẶN. Kết quả chỉ để đánh dấu cho người review, không được
đặt status=FAILED: giá trị suy ra (subtotal tính từ line items) có thể không xuất
hiện nguyên văn mà vẫn hợp lệ. Nguyên tắc xuyên suốt là THÀ BỎ SÓT CÒN HƠN BÁO
OAN — báo oan một lần là người dùng thôi tin vào cảnh báo.

Module này KHÔNG gọi AI và không import gì từ common/ — deterministic thuần,
test offline được (CLAUDE.md §7).
"""

import re
import unicodedata

# Không trích từ text nên không có gì để neo:
#   document_type  do LLM phân loại
#   confidence     do LLM tự chấm
#   currency       thường là mã chuẩn hoá (VND) chứ không phải chuỗi trong tài liệu
BO_QUA = {"document_type", "confidence", "currency"}

# Ngày tháng bỏ hẳn: "2026-08-05" có thể hiện ra dưới dạng "05/08/2026",
# "05-08-2026", "Ngày 05 tháng 08 năm 2026"... Kiểm là báo oan.
LA_NGAY = re.compile(r"_date$|^date$")

# Trong items[] chỉ neo tên mặt hàng. Số lượng và đơn giá là những con số lặp lại
# khắp tài liệu nên kiểm chúng nhiễu hơn là có ích.
ITEM_FIELD_CAN_NEO = "item_name"


def _chuan_hoa(text: str) -> str:
    """Bỏ dấu, hạ chữ thường, gộp mọi khoảng trắng thành một dấu cách.

    Gộp '\\n' là bắt buộc: text OCR ngắt dòng giữa "Công ty\\nABC" trong khi
    Gemini trả về "Công ty ABC". Không gộp thì kiểm chuỗi con luôn trượt.
    """
    khong_dau = "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", khong_dau).lower().strip()


def _cac_dang_be_mat(value: int | float) -> list[str]:
    """Một con số hiện ra trong tài liệu dưới nhiều dạng phân cách khác nhau."""
    nguyen = int(value) if float(value).is_integer() else None
    if nguyen is None:
        return [str(value)]
    tho = str(abs(nguyen))
    co_dau = f"{abs(nguyen):,}"
    return [tho, co_dau, co_dau.replace(",", ".")]


def _tim_thay(value, ocr: str) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return any(_chuan_hoa(dang) in ocr for dang in _cac_dang_be_mat(value))
    can_tim = _chuan_hoa(str(value))
    return not can_tim or can_tim in ocr


def check_grounding(data: dict, ocr_text: str | None) -> list[str]:
    """Trả về tên các trường KHÔNG tìm thấy trong text OCR.

    `ocr_text` rỗng thì trả về [] — không có nguồn để đối chiếu thì không kết
    luận được gì, và đánh dấu cả tài liệu là bịa còn tệ hơn im lặng.
    """
    if not ocr_text or not data:
        return []

    ocr = _chuan_hoa(ocr_text)
    thieu: list[str] = []

    for ten, value in data.items():
        if ten in BO_QUA or LA_NGAY.search(ten) or value is None or value == "":
            continue

        if ten == "items" and isinstance(value, list):
            for i, item in enumerate(value):
                if not isinstance(item, dict):
                    continue
                ten_hang = item.get(ITEM_FIELD_CAN_NEO)
                if ten_hang and not _tim_thay(ten_hang, ocr):
                    thieu.append(f"items[{i}].{ITEM_FIELD_CAN_NEO}")
            continue

        if isinstance(value, (list, dict)):
            continue

        if not _tim_thay(value, ocr):
            thieu.append(ten)

    return thieu
