"""Chặn tái phát bug parse Document AI.

Bug gốc (code v1): giả định mỗi phần tử có thuộc tính `.text`, và dùng tên
`page.key_value_pairs`. Thực tế Document AI trả offset trong `text_anchor` trỏ
vào `document.text`, và trường đúng tên là `page.form_fields`.
Lỗi này CHỈ lộ khi gọi API thật — nên phải có test giả lập đúng hình dạng proto.
"""

from types import SimpleNamespace

from common.ai_clients import _layout_text, _parse_documentai

FULL_TEXT = "Joma Bakery\n43 Tô Ngọc Vân\nTOTAL\n305,000\nSL\n2\n"


def span(word: str):
    """Offset thật của `word` trong FULL_TEXT — tính ra thay vì gõ tay."""
    start = FULL_TEXT.index(word)
    return SimpleNamespace(start_index=start, end_index=start + len(word))


def layout(*words, confidence=None):
    return SimpleNamespace(
        text_anchor=SimpleNamespace(text_segments=[span(w) for w in words]),
        confidence=confidence,
    )


def test_layout_text_cat_dung_doan_theo_offset():
    assert _layout_text(layout("Joma Bakery"), FULL_TEXT) == "Joma Bakery"
    assert _layout_text(layout("43 Tô Ngọc Vân"), FULL_TEXT) == "43 Tô Ngọc Vân"


def test_layout_text_ghep_nhieu_segment():
    assert _layout_text(layout("Joma", "TOTAL"), FULL_TEXT) == "JomaTOTAL"


def test_layout_text_khong_co_anchor_thi_tra_rong():
    assert _layout_text(SimpleNamespace(text_anchor=None), FULL_TEXT) == ""
    assert _layout_text(None, FULL_TEXT) == ""


def _fake_document():
    page = SimpleNamespace(
        page_number=1,
        lines=[
            SimpleNamespace(layout=layout("Joma Bakery")),
            SimpleNamespace(layout=layout("43 Tô Ngọc Vân")),
        ],
        tables=[
            SimpleNamespace(
                header_rows=[SimpleNamespace(cells=[SimpleNamespace(layout=layout("SL"))])],
                body_rows=[SimpleNamespace(cells=[SimpleNamespace(layout=layout("2"))])],
            )
        ],
        form_fields=[
            SimpleNamespace(
                field_name=layout("TOTAL"),
                field_value=layout("305,000", confidence=0.53),
            )
        ],
        tokens=[
            SimpleNamespace(layout=layout("Joma", confidence=0.9)),
            SimpleNamespace(layout=layout("Bakery", confidence=0.8)),
        ],
    )
    return SimpleNamespace(text=FULL_TEXT, pages=[page])


def test_parse_lay_dung_lines_va_tables():
    result = _parse_documentai(_fake_document())
    page = result["pages"][0]

    assert result["text"] == FULL_TEXT
    assert page["lines"] == ["Joma Bakery", "43 Tô Ngọc Vân"]
    # header_rows phải đứng TRƯỚC body_rows để _build_ocr_text dựng markdown đúng
    assert page["tables"][0]["rows"] == [{"cells": ["SL"]}, {"cells": ["2"]}]


def test_parse_doc_form_fields_chu_khong_phai_key_value_pairs():
    page = _parse_documentai(_fake_document())["pages"][0]
    assert page["key_value_pairs"] == [
        {"key": "TOTAL", "value": "305,000", "confidence": 0.53}
    ]


def test_parse_tinh_confidence_that_tu_token():
    page = _parse_documentai(_fake_document())["pages"][0]
    assert page["token_count"] == 2
    assert page["mean_token_confidence"] == 0.85


def test_parse_khong_vo_khi_trang_rong():
    empty = SimpleNamespace(
        page_number=1, lines=[], tables=[], form_fields=[], tokens=[]
    )
    page = _parse_documentai(SimpleNamespace(text="", pages=[empty]))["pages"][0]
    assert page["mean_token_confidence"] is None
    assert page["lines"] == []
