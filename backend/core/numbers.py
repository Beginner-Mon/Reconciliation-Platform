"""Đọc một ô của bảng thành số.

Mô hình ngôn ngữ có lúc trả ô số dưới dạng chữ: "$42.00", "29.000 đ", "1,200.50".
Trước đây mỗi chỗ cần số tự gọi float() hay Decimal(); gặp chữ như vậy thì coi là
ô trống, và phép so đơn giá bị bỏ qua mà không ai biết. Lượt chạy trên AWS ngày
2026-10-08 sót chỗ lệch đơn giá 40 và 42 vì đúng lý do đó. Lớp làm sạch, bước kiểm
tra và các luật đối chiếu nay cùng đọc số qua module này.

Chỉ trả về số khi đọc chắc được. "29.000" có thể là hai mươi chín nghìn hoặc hai
mươi chín: không có căn cứ thì trả None để bước kiểm tra gắn cờ, không đoán.
"""
import math
import re
import unicodedata
from decimal import Decimal

_CUM_SO = re.compile(r"\d[\d.,]*")
_MA_TIEN = re.compile(r"[A-Z]{2,4}")
_DAU_AM = "-\u2212"
_MO_HO = object()


def _chu_hoac_tien(ky_tu: str) -> bool:
    return ky_tu.isalpha() or ky_tu.isspace() or unicodedata.category(ky_tu) == "Sc"


def _tach(chuoi: str):
    """(âm?, cụm số) nếu ô gồm đúng MỘT con số kèm ký hiệu cho phép; ngược lại None.

    Đứng trước con số được có: ký hiệu tiền tệ, dấu âm, hoặc một mã tiền viết hoa
    ("USD", "VND") cách con số một dấu cách. Đứng sau được có chữ hoặc ký hiệu tiền
    tệ ("29.000đ", "12 cái", "42.00 USD"). Chữ khác đứng trước ("SP100", "A-100",
    "Băng keo 5") hay hai con số trong một ô ("10 m2", "2 x 5") thì không nhận.
    """
    text = chuoi.strip()
    cum = _CUM_SO.findall(text)
    if len(cum) != 1:
        return None
    truoc, _, sau = text.partition(cum[0])
    if not all(_chu_hoac_tien(k) for k in sau):
        return None
    chu_truoc = "".join(k for k in truoc if k.isalpha())
    if chu_truoc and not (_MA_TIEN.fullmatch(chu_truoc) and truoc[-1].isspace()):
        return None
    am = False
    for k in truoc:
        if k in _DAU_AM:
            if am or chu_truoc:
                return None
            am = True
        elif not _chu_hoac_tien(k):
            return None
    return am, cum[0].rstrip(".,")


def _nhom_nghin(phan: list[str]) -> bool:
    return 1 <= len(phan[0]) <= 3 and all(len(p) == 3 for p in phan[1:])


def _gia_tri(nguyen: str, le: str):
    if not le.strip("0"):
        return int(nguyen)
    return float(f"{nguyen}.{le}")


def _doc_cum(so: str, dau_thap_phan: str | None = None):
    """Giá trị của một cụm chữ số có dấu chấm, dấu phẩy.

    Trả (giá trị, dấu thập phân mà chính cụm này cho thấy hoặc None). Trả _MO_HO khi
    cụm có đúng một dấu ngăn và đúng ba chữ số sau nó ("29.000") mà chưa biết dấu
    thập phân của chứng từ. Trả None khi các nhóm chữ số không đúng dạng.
    """
    cham, phay = so.count("."), so.count(",")
    if not cham and not phay:
        return int(so), None
    if cham and phay:
        dau = "." if so.rfind(".") > so.rfind(",") else ","
        nghin = "," if dau == "." else "."
        nguyen, le = so.rsplit(dau, 1)
        if so.count(dau) != 1 or not _nhom_nghin(nguyen.split(nghin)):
            return None
        return _gia_tri(nguyen.replace(nghin, ""), le), dau
    dau = "." if cham else ","
    phan = so.split(dau)
    if len(phan) > 2:
        if not _nhom_nghin(phan):
            return None
        return int("".join(phan)), ("," if dau == "." else ".")
    nguyen, le = phan
    if len(le) != 3 or len(nguyen) > 3 or nguyen.startswith("0"):
        return _gia_tri(nguyen, le), dau
    if dau_thap_phan is None:
        return _MO_HO
    if dau_thap_phan == dau:
        return _gia_tri(nguyen, le), None
    return int(nguyen + le), None


def parse_cell(value, decimal_mark: str | None = None):
    """Số của một ô bảng, hoặc None nếu không đọc chắc được.

    `decimal_mark` là dấu thập phân của chứng từ ("." hoặc ","), dùng để đọc các ô
    như "29.000"; không truyền thì những ô đó trả None.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        if not value.is_finite():
            return None
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (int, float)):
        return value if math.isfinite(value) else None
    if not isinstance(value, str):
        return None
    tach = _tach(value)
    if tach is None:
        return None
    am, so = tach
    ket_qua = _doc_cum(so, decimal_mark)
    if ket_qua is None or ket_qua is _MO_HO:
        return None
    return -ket_qua[0] if am else ket_qua[0]


def decimal_mark_of(values) -> str | None:
    """Dấu thập phân mà các ô của MỘT chứng từ cùng cho thấy.

    None khi không ô nào cho căn cứ, hoặc khi các ô cho căn cứ ngược nhau.
    """
    thay = set()
    for value in values:
        if not isinstance(value, str):
            continue
        tach = _tach(value)
        if tach is None:
            continue
        ket_qua = _doc_cum(tach[1])
        if ket_qua is not None and ket_qua is not _MO_HO and ket_qua[1]:
            thay.add(ket_qua[1])
    return thay.pop() if len(thay) == 1 else None
