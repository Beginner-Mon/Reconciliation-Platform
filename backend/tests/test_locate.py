from core.locate import clean_sources, locate
from tests.test_position import COT, DUNG, HEADERS, bang, chu, so, sua, trang


def chu_cua(pages, refs):
    return [pages[p]["words"][i][0] for p, i in refs]


def cot(ten):
    return HEADERS.index(ten)


def tieu_de(y=0.26):
    words = chu("STT", 0.04, y) + chu("Tên", 0.10, y)
    for ten in ("SL", "Đơn giá", "Tổng tiền", "Chiết khấu", "Trước thuế", "Sau thuế"):
        words += chu(ten, round(COT[ten] - len(ten) * 0.007, 4), y)
    return words


def trang_day_du():
    words = (
        chu("Số: 3126818", 0.60, 0.05)
        + chu("Ngày 28 tháng 12 năm 2024", 0.30, 0.08)
        + chu("Ký hiệu: 1C24MGG", 0.60, 0.11)
        + chu("Số bill: 9", 0.60, 0.14)
        + trang()[0]["words"]
        + chu("Tổng cộng", 0.10, 0.60)
        + [so("143.000", COT["Tổng tiền"], 0.60)]
    )
    return [{"words": words}]


def test_o_so_va_o_chu_tro_dung_khung_tren_trang():
    pages = trang()
    layout = locate(bang(*DUNG), pages)
    dong_1 = layout["tables"][0]["rows"][0]

    assert chu_cua(pages, dong_1[cot("Tên")]) == ["Coca", "Cola"]
    assert chu_cua(pages, dong_1[cot("Đơn giá")]) == ["29.000"]
    assert chu_cua(pages, dong_1[cot("Tổng tiền")]) == ["58.000"]
    assert chu_cua(pages, dong_1[cot("Chiết khấu")]) == ["58.000"]
    assert dong_1[cot("Tổng tiền")] != dong_1[cot("Chiết khấu")]
    assert chu_cua(pages, dong_1[cot("Trước thuế")]) == ["0"]
    assert chu_cua(pages, layout["tables"][0]["rows"][1][cot("Tên")]) == ["Nước", "suối", "Dasani"]


def test_o_xep_nham_cot_khong_co_khung_nhung_biet_cho_do_dang_ghi_gi():
    pages = trang()
    bang_0 = locate(sua(0, {"Chiết khấu": None, "Trước thuế": 58000}), pages)["tables"][0]

    assert bang_0["rows"][0][cot("Chiết khấu")] == []
    assert chu_cua(pages, bang_0["at"][0][cot("Chiết khấu")]) == ["58.000"]
    assert bang_0["rows"][0][cot("Trước thuế")] == []
    assert chu_cua(pages, bang_0["at"][0][cot("Trước thuế")]) == ["0"]
    assert bang_0["at"][0][cot("Chiết khấu")] != bang_0["rows"][0][cot("Tổng tiền")]


def test_tieu_de_cot_duoc_gan_dung_cot():
    pages = [{"words": tieu_de() + trang()[0]["words"]}]

    bang_0 = locate(bang(*DUNG), pages)["tables"][0]

    assert chu_cua(pages, bang_0["headers"][cot("Tên")]) == ["Tên"]
    assert chu_cua(pages, bang_0["headers"][cot("Chiết khấu")]) == ["Chiết", "khấu"]
    assert chu_cua(pages, bang_0["headers"][cot("Trước thuế")]) == ["Trước", "thuế"]
    assert chu_cua(pages, bang_0["headers"][cot("Sau thuế")]) == ["Sau", "thuế"]


def test_truong_ngoai_bang_va_truong_bo_sung():
    pages = trang_day_du()
    data = {
        **bang(*DUNG),
        "doc_number": "3126818",
        "doc_date": "2024-12-28",
        "total_amount": 143000,
        "seller": "Công ty không có trên trang",
        "other_fields": {"Ký hiệu": "1C24MGG", "Số bill": "9", "Fax": ""},
    }

    layout = locate(data, pages)

    assert chu_cua(pages, layout["fields"]["doc_number"]) == ["3126818"]
    assert chu_cua(pages, layout["fields"]["doc_date"]) == ["28", "12", "2024"]
    assert chu_cua(pages, layout["fields"]["total_amount"]) == ["143.000"]
    assert "seller" not in layout["fields"]
    assert chu_cua(pages, layout["other"]["Ký hiệu"]["k"]) == ["Ký", "hiệu:"]
    assert chu_cua(pages, layout["other"]["Ký hiệu"]["v"]) == ["1C24MGG"]
    assert chu_cua(pages, layout["other"]["Số bill"]["v"]) == ["9"]
    assert "Fax" not in layout["other"]


def test_tong_tien_trung_voi_o_trong_bang_thi_dung_chung_khung():
    pages = trang()

    layout = locate({**bang(*DUNG), "total_amount": 9720}, pages)

    assert chu_cua(pages, layout["fields"]["total_amount"]) == ["9.720"]
    assert layout["fields"]["total_amount"] == layout["tables"][0]["rows"][2][cot("Sau thuế")]


def test_ngay_viet_bang_ten_thang_tieng_anh():
    pages = [{"words": chu("Issued Date : 06 Oct 2025", 0.10, 0.05) + chu("ETA : Oct 09 , 2025", 0.10, 0.08)}]

    assert chu_cua(pages, locate({"doc_date": "2025-10-06"}, pages)["fields"]["doc_date"]) == ["06", "Oct", "2025"]
    assert chu_cua(pages, locate({"doc_date": "2025-10-09"}, pages)["fields"]["doc_date"]) == ["Oct", "09", "2025"]
    assert "doc_date" not in locate({"doc_date": "2025-11-06"}, pages)["fields"]


def test_o_chu_khong_can_dung_thu_tu_cot():
    def dong(y, ma, phi, tien):
        return chu(phi, 0.10, y) + chu("C VND", 0.50, y) + chu(ma, 0.62, y) + [so(tien, 0.95, y)]

    pages = [{"words": dong(0.30, "TGBU4903849", "Equipment Cleaning", "1.800.000")
              + dong(0.33, "OOCU8220213", "Equipment Imbalance Surcharge", "13.000.000")}]
    data = {"tables": [{
        "columns": [{"header": h, "role": None} for h in ("P/C", "CCY", "Container", "Charge", "Amount")],
        "rows": [
            {"P/C": "C", "CCY": "VND", "Container": "TGBU4903849", "Charge": "Equipment Cleaning", "Amount": 1800000},
            {"P/C": "C", "CCY": "VND", "Container": "OOCU8220213", "Charge": "Equipment Imbalance Surcharge", "Amount": 13000000},
        ],
    }]}

    dong_1 = locate(data, pages)["tables"][0]["rows"][0]

    assert [chu_cua(pages, refs) for refs in dong_1] == [
        ["C"], ["VND"], ["TGBU4903849"], ["Equipment", "Cleaning"], ["1.800.000"],
    ]


def test_kieu_so_suy_tu_chinh_chung_tu():
    assert locate(bang(*DUNG), trang())["number_style"] == "thousands"

    def phi(y, ten):
        return chu(ten, 0.10, y) + [so("1.000", 0.50, y), so("30.000", 0.70, y), so("32.400", 0.90, y)]

    pages = [{"words": phi(0.50, "D/O FEE") + phi(0.53, "CFS CHARGE") + phi(0.56, "HANDLING FEE")}]
    data = {"tables": [{
        "columns": [{"header": h, "role": None} for h in ("Dịch vụ", "Số lượng", "Đơn giá", "Thành tiền")],
        "rows": [
            {"Dịch vụ": ten, "Số lượng": 1, "Đơn giá": 30, "Thành tiền": 32.4}
            for ten in ("D/O FEE", "CFS CHARGE", "HANDLING FEE")
        ],
    }]}

    assert locate(data, pages)["number_style"] == "decimal"


def test_ocr_cu_khong_co_words_thi_khong_co_vi_tri():
    layout = locate(bang(*DUNG), [{"page_number": 1, "lines": []}])

    assert layout == {"fields": {}, "other": {}, "tables": [None], "number_style": None}


def test_du_lieu_la_khong_lam_vo():
    rong = {"fields": {}, "other": {}, "tables": [], "number_style": None}
    assert locate(None, None) == rong
    assert locate({"tables": "x", "other_fields": 3}, trang()) == rong
    rac = {
        "tables": [None, {"columns": [], "rows": [1]}],
        "doc_number": 7,
        "other_fields": {"a": None, "b": "x"},
    }
    assert locate(rac, trang())["tables"] == [None, None]


def test_clean_sources_giu_dung_hinh_dang_cua_ket_qua_trich_xuat():
    data = {**bang(*DUNG), "doc_number": "3126818", "other_fields": {"Ký hiệu": "1C24MGG"}}
    hang = [[[] for _ in HEADERS] for _ in DUNG]
    hang[0][cot("Đơn giá")] = [[0, 5]]
    data["currency"] = "VND"
    gui = {
        "fields": {"doc_number": [[0, 1]], "seller": [[0, 2]], "la": [[0, 3]], "currency": [[0, 4]]},
        "other": {
            "Ký hiệu": {"k": [[0, 7]], "v": [[0, 8], [0, -1], "x", [1.5, 2]]},
            "Không còn": {"k": [], "v": []},
        },
        "tables": [{"headers": [[] for _ in HEADERS], "rows": hang, "at": "bỏ"}],
        "number_style": "x",
    }

    assert clean_sources(gui, data) == {
        "fields": {"doc_number": [[0, 1]], "currency": [[0, 4]]},
        "other": {"Ký hiệu": {"k": [[0, 7]], "v": [[0, 8]]}},
        "tables": [{"headers": [[] for _ in HEADERS], "rows": hang}],
    }


def test_clean_sources_bo_bang_lech_hinh_dang_va_du_lieu_rac():
    data = bang(*DUNG)
    thieu_dong = {"tables": [{"headers": [[] for _ in HEADERS], "rows": [[[] for _ in HEADERS]]}]}

    assert clean_sources(thieu_dong, data) == {"fields": {}, "other": {}, "tables": [None]}
    assert clean_sources({"tables": "x"}, data) == {"fields": {}, "other": {}, "tables": [None]}
    assert clean_sources(None, data) == {}
    assert clean_sources({}, None) == {}


def test_clean_sources_qua_lon_thi_khong_luu():
    data = bang(*DUNG)
    hang = [[[[0, n] for n in range(60)] for _ in HEADERS] for _ in DUNG]
    nhieu = {"tables": [{"headers": [[] for _ in HEADERS], "rows": hang}]}
    assert clean_sources(nhieu, data)["tables"][0]["rows"] == hang

    import core.locate as module
    cu = module.MAX_NODES
    module.MAX_NODES = 100
    try:
        assert clean_sources(nhieu, data) == {}
    finally:
        module.MAX_NODES = cu
