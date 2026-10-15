from copy import deepcopy

from core.normalize import clean_extraction
from core.validate import validate_document


def hoa_don():
    return {
        "document_type": "invoice",
        "role": "billing",
        "doc_number": "INV-1",
        "doc_date": "2024-12-28",
        "seller": "Cong ty A",
        "other_fields": {},
        "tables": [],
    }


def bang(hang_mau):
    return [
        {
            "columns": [
                {"header": "Ten", "role": "item_name"},
                {"header": "SL", "role": "quantity"},
            ],
            "rows": hang_mau,
        }
    ]


def xem_qua(du_lieu):
    goc = deepcopy(du_lieu)
    sach, van_de = clean_extraction(du_lieu)
    assert du_lieu == goc
    return sach, van_de, validate_document(sach)


def test_other_fields_null_thanh_chuoi_rong():
    sach, van_de, ket_qua = xem_qua({**hoa_don(), "other_fields": {"X": None}})
    assert ket_qua["valid"]
    assert van_de == []
    assert sach["other_fields"] == {"X": ""}


def test_other_fields_so_thanh_chuoi():
    sach, van_de, ket_qua = xem_qua({**hoa_don(), "other_fields": {"X": 5}})
    assert ket_qua["valid"]
    assert van_de == []
    assert sach["other_fields"] == {"X": "5"}


def test_other_fields_list_dict_thanh_json():
    sach, van_de, ket_qua = xem_qua(
        {**hoa_don(), "other_fields": {"X": [1, 2], "Y": {"a": 1}}}
    )
    assert ket_qua["valid"]
    assert van_de == []
    assert sach["other_fields"] == {"X": "[1, 2]", "Y": '{"a": 1}'}


def test_khoa_la_o_goc_chuyen_ve_other_fields():
    sach, van_de, ket_qua = xem_qua({**hoa_don(), "ghi_chu": "abc"})
    assert ket_qua["valid"]
    assert van_de == []
    assert "ghi_chu" not in sach
    assert sach["other_fields"] == {"ghi_chu": "abc"}


def test_so_hoa_don_va_mst_la_so_thanh_chuoi():
    sach, van_de, ket_qua = xem_qua(
        {**hoa_don(), "doc_number": 3126818, "seller_tax_code": 1234567890}
    )
    assert ket_qua["valid"]
    assert van_de == []
    assert sach["doc_number"] == "3126818"
    assert sach["seller_tax_code"] == "1234567890"


def test_so_thuc_nguyen_bo_cham_0():
    sach, van_de, ket_qua = xem_qua({**hoa_don(), "doc_number": 3126818.0})
    assert ket_qua["valid"]
    assert van_de == []
    assert sach["doc_number"] == "3126818"


def test_role_cot_chuoi_null_va_la_thanh_none():
    du_lieu = hoa_don()
    du_lieu["tables"] = [
        {
            "columns": [
                {"header": "A", "role": "null"},
                {"header": "B", "role": "discount"},
            ],
            "rows": [],
        }
    ]
    sach, van_de, ket_qua = xem_qua(du_lieu)
    assert ket_qua["valid"]
    assert van_de == []
    assert [c["role"] for c in sach["tables"][0]["columns"]] == [None, None]


def test_dong_bang_dang_mang_thanh_dict():
    sach, van_de, ket_qua = xem_qua({**hoa_don(), "tables": bang([["Coca", 2]])})
    assert ket_qua["valid"]
    assert van_de == []
    assert sach["tables"][0]["rows"] == [{"Ten": "Coca", "SL": 2}]


def test_o_bang_list_thanh_json():
    sach, van_de, ket_qua = xem_qua(
        {**hoa_don(), "tables": bang([{"Ten": ["a"], "SL": 2}])}
    )
    assert ket_qua["valid"]
    assert van_de == []
    assert sach["tables"][0]["rows"] == [{"Ten": '["a"]', "SL": 2}]


def test_tien_chuoi_co_dau_cham_bi_go_va_ghi_nhan():
    sach, van_de, ket_qua = xem_qua({**hoa_don(), "total_amount": "3.734.640"})
    assert "total_amount" not in sach
    assert [m["field"] for m in van_de] == ["total_amount"]
    assert van_de[0]["value"] == "3.734.640"
    assert ket_qua["valid"]
    co = validate_document(sach, van_de)["flags"]
    assert any(
        f["code"] == "ai_format"
        and f["field"] == "total_amount"
        and f["values"] == {"gia_tri_goc": "3.734.640"}
        for f in co
    )


def test_tien_le_thap_phan_bi_go():
    sach, van_de, ket_qua = xem_qua({**hoa_don(), "total_amount": 3734640.5})
    assert "total_amount" not in sach
    assert [m["field"] for m in van_de] == ["total_amount"]
    assert ket_qua["valid"]


def test_ngay_sai_dinh_dang_bi_go():
    sach, van_de, ket_qua = xem_qua({**hoa_don(), "doc_date": "28/12/2024"})
    assert "doc_date" not in sach
    assert [m["field"] for m in van_de] == ["doc_date"]
    assert van_de[0]["value"] == "28/12/2024"
    assert ket_qua["valid"]


def test_ten_dai_qua_200_ky_tu_bi_go_va_cat_ngan():
    sach, van_de, ket_qua = xem_qua({**hoa_don(), "seller": "x" * 250})
    assert "seller" not in sach
    assert [m["field"] for m in van_de] == ["seller"]
    assert van_de[0]["value"] == "x" * 200
    assert ket_qua["valid"]


def test_role_chung_tu_la_bi_go_ve_mac_dinh_other():
    sach, van_de, ket_qua = xem_qua({**hoa_don(), "role": "giao_hang"})
    assert "role" not in sach
    assert [m["field"] for m in van_de] == ["role"]
    assert ket_qua["valid"]
    assert ket_qua["model"].role == "other"


def test_header_cot_dai_150_ky_tu_khong_cuu_duoc():
    du_lieu = {
        **hoa_don(),
        "tables": [
            {"columns": [{"header": "y" * 150, "role": None}], "rows": []}
        ],
    }
    sach, van_de, ket_qua = xem_qua(du_lieu)
    assert sach == du_lieu
    assert van_de == []
    assert not ket_qua["valid"]


def test_dong_mang_lech_do_dai_khong_cuu_duoc():
    du_lieu = {
        **hoa_don(),
        "tables": [
            {
                "columns": [{"header": "Ten", "role": "item_name"}],
                "rows": [["Coca", 2, 3]],
            }
        ],
    }
    sach, van_de, ket_qua = xem_qua(du_lieu)
    assert sach == du_lieu
    assert van_de == []
    assert not ket_qua["valid"]


def test_11_truong_hong_vuot_nguong_tra_nguyen_ban_dau():
    du_lieu = {
        **hoa_don(),
        "total_amount": "a",
        "subtotal": "b",
        "discount_amount": "c",
        "tax_amount": "d",
        "doc_date": "32/13/2024",
        "seller": "x" * 250,
        "buyer": "y" * 250,
        "role": "zzz",
        "doc_number": True,
        "seller_tax_code": True,
        "currency": True,
    }
    sach, van_de, ket_qua = xem_qua(du_lieu)
    assert sach == du_lieu
    assert van_de == []
    assert not ket_qua["valid"]


def test_van_don_8_cot_role_null_chuoi_qua_duoc():
    du_lieu = hoa_don()
    du_lieu["tables"] = [
        {
            "columns": [{"header": f"C{i}", "role": "null"} for i in range(8)],
            "rows": [{f"C{i}": "v" for i in range(8)}],
        }
    ]
    sach, van_de, ket_qua = xem_qua(du_lieu)
    assert ket_qua["valid"]
    assert van_de == []
    assert all(c["role"] is None for c in sach["tables"][0]["columns"])


def test_booking_31_truong_other_co_1_null_qua_duoc():
    other = {f"K{i}": "v" for i in range(30)}
    other["Container Number"] = None
    sach, van_de, ket_qua = xem_qua({**hoa_don(), "other_fields": other})
    assert ket_qua["valid"]
    assert van_de == []
    assert sach["other_fields"]["Container Number"] == ""


def test_dong_hoa_don_dang_mang_du_do_dai_thanh_dict():
    du_lieu = hoa_don()
    du_lieu["tables"] = [
        {
            "columns": [
                {"header": "Ten", "role": "item_name"},
                {"header": "SL", "role": "quantity"},
                {"header": "Gia", "role": None},
            ],
            "rows": [[1, "Coca Cola (Lon)", "Lon"]],
        }
    ]
    sach, van_de, ket_qua = xem_qua(du_lieu)
    assert ket_qua["valid"]
    assert sach["tables"][0]["rows"] == [
        {"Ten": 1, "SL": "Coca Cola (Lon)", "Gia": "Lon"}
    ]


def test_khong_phai_dict_tra_nguyen():
    for xau in (None, [], "chuoi"):
        sach, van_de = clean_extraction(xau)
        assert sach == xau
        assert van_de == []


def test_loai_chung_tu_khong_ho_tro_khong_cuu_duoc():
    du_lieu = {"document_type": "bill_of_lading"}
    sach, van_de, ket_qua = xem_qua(du_lieu)
    assert sach == du_lieu
    assert van_de == []
    assert not ket_qua["valid"]


def bang_gia(hang_mau):
    return [
        {
            "columns": [
                {"header": "SKU", "role": None},
                {"header": "Ten", "role": "item_name"},
                {"header": "SL", "role": "quantity"},
                {"header": "Gia", "role": "unit_price"},
                {"header": "Tien", "role": "amount"},
            ],
            "rows": hang_mau,
        }
    ]


def test_o_so_dang_chu_co_ky_hieu_tien_duoc_doi_thanh_so():
    # Đúng dạng Gemini trả cho hoá đơn tiếng Anh trong lượt chạy trên AWS ngày 2026-10-08.
    du_lieu = {**hoa_don(), "tables": bang_gia([
        {"SKU": "A-100", "Ten": "Industrial Storage Bin", "SL": "12", "Gia": "$25.00", "Tien": "$300.00"},
        {"SKU": "B-200", "Ten": "Packing Tape - Heavy Duty", "SL": "5", "Gia": "$42.00", "Tien": "$210.00"},
    ])}
    sach, van_de, ket_qua = xem_qua(du_lieu)
    assert ket_qua["valid"]
    assert van_de == []
    assert sach["tables"][0]["rows"] == [
        {"SKU": "A-100", "Ten": "Industrial Storage Bin", "SL": 12, "Gia": 25, "Tien": 300},
        {"SKU": "B-200", "Ten": "Packing Tape - Heavy Duty", "SL": 5, "Gia": 42, "Tien": 210},
    ]
    assert ket_qua["flags"] == []


def test_o_mo_ho_doc_theo_cac_o_khac_cua_chinh_chung_tu():
    du_lieu = {**hoa_don(), "tables": bang_gia([
        {"SKU": "1", "Ten": "Menu", "SL": "19", "Gia": "199.000,00", "Tien": "3.781.000"},
        {"SKU": "2", "Ten": "Khan lanh", "SL": "6", "Gia": "5.000", "Tien": "30.000"},
    ])}
    sach, _, _ = xem_qua(du_lieu)
    assert [d["Gia"] for d in sach["tables"][0]["rows"]] == [199000, 5000]
    assert [d["Tien"] for d in sach["tables"][0]["rows"]] == [3781000, 30000]


def test_o_mo_ho_khong_co_can_cu_thi_de_nguyen_va_bi_gan_co():
    du_lieu = {**hoa_don(), "tables": bang_gia([
        {"SKU": "1", "Ten": "Khan lanh", "SL": 6, "Gia": "5.000", "Tien": 30000},
    ])}
    sach, _, ket_qua = xem_qua(du_lieu)
    assert sach["tables"][0]["rows"][0]["Gia"] == "5.000"
    assert [(f["code"], f["field"]) for f in ket_qua["flags"]] == [("insufficient_data", "tables.0.rows.0.Gia")]


def test_cot_khong_phai_cot_so_khong_bi_dong_toi():
    du_lieu = {**hoa_don(), "tables": bang_gia([
        {"SKU": "100", "Ten": "12", "SL": 1, "Gia": 5, "Tien": 5},
    ])}
    sach, _, _ = xem_qua(du_lieu)
    assert sach["tables"][0]["rows"][0]["SKU"] == "100"
    assert sach["tables"][0]["rows"][0]["Ten"] == "12"
