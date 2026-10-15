"""core/numbers.py: đọc một ô bảng thành số, chỉ khi đọc chắc được."""
import pytest

from core.numbers import decimal_mark_of, parse_cell


@pytest.mark.parametrize("o,so", [
    (42, 42), (42.5, 42.5), (0, 0),
    ("42", 42), (" 42 ", 42),
    ("$42.00", 42), ("42.00 USD", 42), ("USD 42.00", 42), ("42.50", 42.5),
    ("$1,200.50", 1200.5), ("€1.200,50", 1200.5), ("199.000,00", 199000),
    ("3.354.200", 3354200), ("3.354.200 VND", 3354200), ("1,234,567", 1234567),
    ("0.125", 0.125), ("1234.567", 1234.567), ("0,5", 0.5),
    ("-42", -42), ("-$42.50", -42.5), ("$-42.50", -42.5), ("\u221242", -42),
    ("12 cái", 12), ("1.5 kg", 1.5), ("29.000,00đ", 29000), ("VND 29.000,00", 29000),
])
def test_doc_duoc(o, so):
    ket_qua = parse_cell(o)
    assert ket_qua == so
    assert type(ket_qua) is type(so)


@pytest.mark.parametrize("o", [
    None, True, False, "", "   ", "abc", "N/A", float("nan"), float("inf"), [], {},
    "29.000", "29.000 đ", "1,200",
    "A-100", "SP100", "INV-2026-1047", "Băng keo 5", "Rp 5", "USD -42",
    "10 m2", "2 x 5", "12/2025", "1 200",
    "(1.000)", "8%", "~42", ".5",
    "1,20.5", "1.2.3", "1.200,5,0",
])
def test_khong_doc_chac_duoc_thi_tra_None(o):
    assert parse_cell(o) is None


@pytest.mark.parametrize("o,dau,so", [
    ("29.000", ",", 29000), ("29.000", ".", 29), ("29.000 đ", ",", 29000),
    ("1,200", ".", 1200), ("1,200", ",", 1.2),
    ("$42.00", ",", 42),
])
def test_o_mo_ho_doc_theo_dau_thap_phan_cua_chung_tu(o, dau, so):
    assert parse_cell(o, decimal_mark=dau) == so


@pytest.mark.parametrize("cac_o,dau", [
    (["$42.00", "$1,200"], "."),
    (["1.200,50", "29.000"], ","),
    (["3.354.200", "58.000"], ","),
    (["29.000", "5", 12, None], None),
    (["42.00", "0,5"], None),
])
def test_dau_thap_phan_suy_tu_cac_o_cua_chung_tu(cac_o, dau):
    assert decimal_mark_of(cac_o) == dau
