from core.position import check_positions, still_valid

RONG = 0.007
CAO = 0.012
COT = {
    "STT": 0.06, "SL": 0.42, "Đơn giá": 0.54, "Tổng tiền": 0.64,
    "Chiết khấu": 0.74, "Trước thuế": 0.84, "Sau thuế": 0.96,
}
HEADERS = ["STT", "Tên", "SL", "Đơn giá", "Tổng tiền", "Chiết khấu", "Trước thuế", "Sau thuế"]
BA_DONG = (
    ("1", "Coca Cola", "2", "29.000", "58.000", "58.000", "0", "0"),
    ("2", "Nước suối Dasani", "3", "25.000", "75.000", "25.000", "50.000", "54.000"),
    ("3", "Khăn ướt", "2", "5.000", "10.000", "1.000", "9.000", "9.720"),
)
DUNG = (
    [1, "Coca Cola", 2, 29000, 58000, 58000, 0, 0],
    [2, "Nước suối Dasani", 3, 25000, 75000, 25000, 50000, 54000],
    [3, "Khăn ướt", 2, 5000, 10000, 1000, 9000, 9720],
)


def so(text, phai, y):
    return [text, round(phai - len(text) * RONG, 4), y, phai, round(y + CAO, 4)]


def chu(text, trai, y):
    words, x = [], trai
    for tu in text.split():
        words.append([tu, round(x, 4), y, round(x + len(tu) * RONG, 4), round(y + CAO, 4)])
        x += (len(tu) + 1) * RONG
    return words


def dong(y, stt, ten, sl, gia, tong, ck, truoc, sau, y_sau=None):
    words = [so(stt, COT["STT"], y)] + chu(ten, 0.10, y)
    cac_o = ((sl, "SL"), (gia, "Đơn giá"), (tong, "Tổng tiền"), (ck, "Chiết khấu"), (truoc, "Trước thuế"))
    for text, cot in cac_o:
        if text:
            words.append(so(text, COT[cot], y))
    if sau:
        words.append(so(sau, COT["Sau thuế"], y if y_sau is None else y_sau))
    return words


def trang(sau_xuong_dong=False):
    words = []
    for i, d in enumerate(BA_DONG):
        y = round(0.30 + i * 0.03, 4)
        if sau_xuong_dong:
            duoi = round(y + 0.014, 4)
            words += dong(y, *d, y_sau=duoi) + chu("Lon", 0.40, duoi)
        else:
            words += dong(y, *d)
    return [{"words": words}]


def bang(*rows):
    return {"tables": [{
        "columns": [{"header": h, "role": None} for h in HEADERS],
        "rows": [dict(zip(HEADERS, r)) for r in rows],
    }]}


def sua(chi_so, thay):
    rows = [list(r) for r in DUNG]
    for header, value in thay.items():
        rows[chi_so][HEADERS.index(header)] = value
    return bang(*rows)


def truong(issues):
    return {m["field"] for m in issues}


def test_bang_dung_thi_khong_canh_bao():
    assert check_positions(bang(*DUNG), trang()) == []


def test_chiet_khau_bi_day_sang_cot_ben_canh_thi_bao_dung_hai_o():
    issues = check_positions(sua(0, {"Chiết khấu": None, "Trước thuế": 58000}), trang())

    assert truong(issues) == {"tables.0.rows.0.Chiết khấu", "tables.0.rows.0.Trước thuế"}
    theo_cot = {m["column"]: m for m in issues}
    assert "58.000" in theo_cot["Chiết khấu"]["message"]
    assert "Chiết khấu" in theo_cot["Trước thuế"]["message"]
    assert theo_cot["Trước thuế"]["value"] == 58000
    assert (theo_cot["Chiết khấu"]["table"], theo_cot["Chiết khấu"]["row"]) == (0, 0)


def test_o_trong_va_so_0_coi_nhu_nhau():
    assert check_positions(sua(0, {"Trước thuế": None, "Sau thuế": None}), trang()) == []

    khong_co_so_0 = [{"words": [w for w in trang()[0]["words"] if w[0] != "0"]}]
    assert check_positions(bang(*DUNG), khong_co_so_0) == []


def test_gia_tri_khong_co_tren_dong_thi_bao():
    issues = check_positions(sua(2, {"Sau thuế": 9999}), trang())

    assert truong(issues) == {"tables.0.rows.2.Sau thuế"}
    assert "Không thấy giá trị 9999" in issues[0]["message"]


def test_gia_tri_chep_trung_tu_cot_khac_thi_bao_tai_cot_nay():
    issues = check_positions(sua(2, {"Trước thuế": 10000}), trang())

    assert truong(issues) == {"tables.0.rows.2.Trước thuế"}
    assert "tại cột này" in issues[0]["message"]


def test_dong_hai_hang_chu_khong_bao_oan():
    assert check_positions(bang(*DUNG), trang(sau_xuong_dong=True)) == []


def test_dong_hai_hang_chu_van_bat_duoc_o_sai():
    issues = check_positions(
        sua(0, {"Chiết khấu": None, "Trước thuế": 58000}), trang(sau_xuong_dong=True)
    )

    assert truong(issues) == {"tables.0.rows.0.Chiết khấu", "tables.0.rows.0.Trước thuế"}


def test_so_dinh_lien_voi_chu_khong_bao_oan():
    def phi(y, ten, so_luong_dinh=False):
        words = chu(ten, 0.10, y) + [so("30.000", 0.70, y), so("32.400", 0.90, y)]
        if so_luong_dinh:
            words.append(["1.000SHIPMENT", 0.465, y, 0.556, round(y + CAO, 4)])
        else:
            words += [so("1.000", 0.50, y)] + chu("SET", 0.51, y)
        return words

    pages = [{"words": phi(0.50, "D/O FEE") + phi(0.53, "CFS CHARGE")
              + phi(0.56, "HANDLING FEE", so_luong_dinh=True)}]
    data = {"tables": [{
        "columns": [{"header": h, "role": None} for h in ("Dịch vụ", "Số lượng", "Đơn giá", "Thành tiền")],
        "rows": [
            {"Dịch vụ": "D/O FEE", "Số lượng": 1, "Đơn giá": 30, "Thành tiền": 32.4},
            {"Dịch vụ": "CFS CHARGE", "Số lượng": 1, "Đơn giá": 30, "Thành tiền": 32.4},
            {"Dịch vụ": "HANDLING FEE", "Số lượng": 1, "Đơn giá": 30, "Thành tiền": 32.4},
        ],
    }]}

    assert check_positions(data, pages) == []


def test_bang_khong_co_tren_trang_thi_khong_ket_luan():
    la = {"tables": [{
        "columns": [{"header": h, "role": None} for h in ("Tên", "SL", "Tiền")],
        "rows": [
            {"Tên": "Thép tấm", "SL": 7, "Tiền": 123456},
            {"Tên": "Xi măng", "SL": 9, "Tiền": 654321},
        ],
    }]}

    assert check_positions(la, trang()) == []


def test_bang_trai_hai_trang_khong_bao_oan():
    mot = trang()[0]["words"]
    hai_trang = [
        {"words": [w for w in mot if w[2] < 0.35]},
        {"words": [[w[0], w[1], 0.10, w[3], round(0.10 + CAO, 4)] for w in mot if w[2] >= 0.35]},
    ]

    assert check_positions(bang(*DUNG), hai_trang) == []


def test_ocr_cu_khong_co_words_thi_tra_rong():
    assert check_positions(bang(*DUNG), [{"page_number": 1, "lines": []}]) == []
    assert check_positions(bang(*DUNG), None) == []


def test_du_lieu_la_khong_lam_vo():
    assert check_positions(None, None) == []
    assert check_positions({"tables": "x"}, trang()) == []
    rac = {"tables": [None, {"columns": [], "rows": [1]}, {"columns": [{"header": "A"}], "rows": [[1]]}]}
    assert check_positions(rac, trang()) == []


def test_still_valid_bo_canh_bao_cua_o_da_doi_gia_tri():
    sai = sua(0, {"Chiết khấu": None, "Trước thuế": 58000})
    issues = check_positions(sai, trang())
    assert len(still_valid(issues, sai)) == 2

    sai["tables"][0]["rows"][0]["Chiết khấu"] = 58000
    assert truong(still_valid(issues, sai)) == {"tables.0.rows.0.Trước thuế"}


def test_still_valid_bo_canh_bao_khi_dong_khong_con():
    sai = sua(2, {"Sau thuế": 9999})
    issues = check_positions(sai, trang())
    sai["tables"][0]["rows"] = sai["tables"][0]["rows"][:2]

    assert still_valid(issues, sai) == []
    assert still_valid(issues, None) == []
    assert still_valid(None, sai) == []


def test_canh_bao_mang_chi_so_cot():
    issues = check_positions(sua(0, {"Chiết khấu": None, "Trước thuế": 58000}), trang())

    assert {m["column"]: m["col"] for m in issues} == {
        "Chiết khấu": HEADERS.index("Chiết khấu"),
        "Trước thuế": HEADERS.index("Trước thuế"),
    }


def test_doi_tieu_de_cot_khong_lam_mat_canh_bao():
    sai = sua(0, {"Chiết khấu": None, "Trước thuế": 58000})
    issues = check_positions(sai, trang())
    bang_moi = sai["tables"][0]
    bang_moi["columns"][HEADERS.index("Trước thuế")]["header"] = "Giá trước thuế"
    for row in bang_moi["rows"]:
        row["Giá trước thuế"] = row.pop("Trước thuế")

    con = still_valid(issues, sai)

    assert truong(con) == {"tables.0.rows.0.Chiết khấu", "tables.0.rows.0.Giá trước thuế"}
    assert {m["column"] for m in con} == {"Chiết khấu", "Giá trước thuế"}
