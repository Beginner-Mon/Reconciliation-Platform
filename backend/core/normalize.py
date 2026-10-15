import copy
import json

from pydantic import ValidationError

from schemas.document import COLUMN_ROLES

from .numbers import decimal_mark_of, parse_cell
from .validate import _LoiDung, _dung_model

MAX_GO = 10
VONG_TOI_DA = 5


def _thanh_chuoi(gia_tri):
    if gia_tri is None:
        return ""
    if isinstance(gia_tri, bool):
        return str(gia_tri)
    if isinstance(gia_tri, float) and gia_tri.is_integer():
        return str(int(gia_tri))
    if isinstance(gia_tri, (list, dict)):
        return json.dumps(gia_tri, ensure_ascii=False)
    return str(gia_tri)


def _sua_hinh_dang(du_lieu):
    bang = du_lieu.get("tables")
    if not isinstance(bang, list):
        return
    for b in bang:
        if not isinstance(b, dict):
            continue
        cot = b.get("columns")
        if not isinstance(cot, list):
            continue
        tieu_de = [c.get("header") for c in cot if isinstance(c, dict)]
        for c in cot:
            if isinstance(c, dict) and c.get("role") is not None and c.get("role") not in COLUMN_ROLES:
                c["role"] = None
        if all(isinstance(h, str) for h in tieu_de) and len(set(tieu_de)) == len(tieu_de):
            hang = b.get("rows")
            if isinstance(hang, list):
                for i, dong in enumerate(hang):
                    if isinstance(dong, list) and len(dong) == len(tieu_de):
                        hang[i] = dict(zip(tieu_de, dong))


COT_SO = ("quantity", "unit_price", "amount")


def _so_hoa_o_bang(du_lieu):
    """Ô ở cột số lượng, đơn giá, thành tiền mà AI trả dạng chữ thì đổi thành số.

    "$42.00" thành 42, "1.200,50" thành 1200.5. Ô như "29.000" đọc theo dấu thập phân
    mà các ô khác của CHÍNH chứng từ này cho thấy; không có căn cứ thì để nguyên và
    bước validate gắn cờ. Bản AI trả vẫn còn nguyên trên S3 ở extraction_s3_key.
    """
    bang = du_lieu.get("tables")
    if not isinstance(bang, list):
        return
    o = []
    for b in bang:
        if not isinstance(b, dict) or not isinstance(b.get("columns"), list) or not isinstance(b.get("rows"), list):
            continue
        tieu_de = [
            c.get("header") for c in b["columns"]
            if isinstance(c, dict) and c.get("role") in COT_SO and isinstance(c.get("header"), str)
        ]
        for dong in b["rows"]:
            if isinstance(dong, dict):
                o.extend((dong, h) for h in tieu_de if isinstance(dong.get(h), str))
    dau = decimal_mark_of(dong[h] for dong, h in o)
    for dong, h in o:
        so = parse_cell(dong[h], dau)
        if so is not None:
            dong[h] = so


def _dinh_vi(du_lieu, loc):
    dau = list(loc)
    while dau:
        hien = du_lieu
        thong = True
        for khoa in dau[:-1]:
            if isinstance(hien, dict) and khoa in hien:
                hien = hien[khoa]
            elif isinstance(hien, list) and isinstance(khoa, int) and 0 <= khoa < len(hien):
                hien = hien[khoa]
            else:
                thong = False
                break
        if not thong:
            return None
        cuoi = dau[-1]
        if isinstance(hien, dict) and cuoi in hien:
            return (tuple(dau), hien, cuoi)
        if isinstance(hien, list) and isinstance(cuoi, int) and 0 <= cuoi < len(hien):
            return (tuple(dau), hien, cuoi)
        dau = dau[:-1]
    return None


def _sua_mot_cho(du_lieu, duong, loi_nhom, go):
    dinh = _dinh_vi(du_lieu, duong)
    if dinh is None:
        return False
    _, cha, khoa = dinh
    if len(duong) >= 2 and duong[0] == "other_fields":
        cha[khoa] = _thanh_chuoi(cha[khoa])
        return True
    if len(duong) == 5 and duong[0] == "tables" and duong[2] == "rows":
        cha[khoa] = _thanh_chuoi(cha[khoa])
        return True
    if len(duong) == 4 and duong[0] == "tables" and duong[2] == "totals":
        cha[khoa] = _thanh_chuoi(cha[khoa])
        return True
    if len(duong) == 1 and any(e.get("type") == "extra_forbidden" for e in loi_nhom):
        gia_tri = cha.pop(khoa)
        other = du_lieu.get("other_fields")
        if not isinstance(other, dict):
            other = {}
            du_lieu["other_fields"] = other
        if khoa not in other:
            other[khoa] = _thanh_chuoi(gia_tri)
        return True
    if (
        len(duong) == 1
        and any(e.get("type") == "string_type" for e in loi_nhom)
        and isinstance(cha[khoa], (int, float))
        and not isinstance(cha[khoa], bool)
    ):
        cha[khoa] = _thanh_chuoi(cha[khoa])
        return True
    if len(duong) == 1:
        gia_tri = cha.pop(khoa)
        go.append({"field": khoa, "value": str(gia_tri)[:200], "reason": loi_nhom[0].get("msg") or ""})
        return True
    return False


def clean_extraction(data):
    if not isinstance(data, dict):
        return (data, [])
    goc = data
    lam = copy.deepcopy(data)
    _sua_hinh_dang(lam)
    _so_hoa_o_bang(lam)
    go = []
    for _ in range(VONG_TOI_DA):
        try:
            _dung_model(lam)
        except ValidationError as exc:
            loi = exc.errors()
        except (_LoiDung, ValueError, TypeError, AttributeError):
            return (goc, [])
        else:
            if len(go) > MAX_GO:
                return (goc, [])
            return (lam, go)
        nhom = {}
        for e in loi:
            dinh = _dinh_vi(lam, e["loc"])
            if dinh is None:
                continue
            nhom.setdefault(dinh[0], []).append(e)
        sua = False
        for duong, loi_nhom in nhom.items():
            if _sua_mot_cho(lam, duong, loi_nhom, go):
                sua = True
        if not sua:
            return (goc, [])
    return (goc, [])
