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


def layout_range(dau: str, cuoi: str):
    """Một segment TRẢI DÀI qua nhiều dòng — đúng hình dạng block thật.

    `_layout_text` cắt chuỗi nguyên văn nên block giữ luôn ký tự xuống dòng bên
    trong. Đây chính là cái bẫy: nối block bằng '\\n' sẽ tái tạo y hệt text
    phẳng và việc gom khối thành vô nghĩa.
    """
    start = FULL_TEXT.index(dau)
    end = FULL_TEXT.index(cuoi) + len(cuoi)
    return SimpleNamespace(
        text_anchor=SimpleNamespace(
            text_segments=[SimpleNamespace(start_index=start, end_index=end)]
        ),
        confidence=None,
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
            SimpleNamespace(layout=layout("Joma Bakery", confidence=0.97)),
            SimpleNamespace(layout=layout("43 Tô Ngọc Vân", confidence=0.42)),
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
        # Document AI gom dòng rời thành khối ngữ nghĩa và trả về trong CÙNG
        # response. Ở đây khối 1 gộp hai dòng lại — đó là giá trị của `blocks`.
        blocks=[
            # Block THẬT trải qua nhiều dòng và giữ luôn '\n' bên trong.
            SimpleNamespace(layout=layout_range("Joma Bakery", "43 Tô Ngọc Vân")),
            SimpleNamespace(layout=layout_range("TOTAL", "305,000")),
        ],
    )
    return SimpleNamespace(text=FULL_TEXT, pages=[page])


def test_parse_lay_dung_lines_va_tables():
    result = _parse_documentai(_fake_document())
    page = result["pages"][0]

    assert result["text"] == FULL_TEXT
    # Mỗi dòng kèm confidence riêng — giao diện tô vàng dòng đọc không chắc.
    assert page["lines"] == [
        {"text": "Joma Bakery", "confidence": 0.97},
        {"text": "43 Tô Ngọc Vân", "confidence": 0.42},
    ]
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


def test_lines_khong_lam_phinh_prompt_gui_gemini():
    """`lines` chỉ để hiển thị. Prompt dựng từ `blocks` (hoặc `text` nếu không có).

    Nếu prompt nuốt thêm `lines` hoặc vừa lấy `blocks` vừa lấy `text` thì mỗi
    trang bị gửi HAI LẦN, tiền token gấp đôi mà không thêm thông tin gì.
    """
    from common.ai_clients import _build_ocr_text

    ocr = _parse_documentai(_fake_document())
    prompt_text = _build_ocr_text(ocr)
    assert prompt_text.count("Joma Bakery") == 1
    assert "confidence" not in prompt_text


# --- Gom khối để prompt không phải là danh sách từ rời ----------------------
#
# Đo trên chứng từ thật: text phẳng có 45–50% dòng chỉ MỘT TỪ, và thứ tự đọc
# trộn lẫn các khối — chữ trong logo ("COSCO SHIPPING") chen vào giữa khối địa
# chỉ của bên nhận hàng, đủ để giá trị bị gán nhầm nhãn.
#
# `blocks` gom chúng thành đơn vị ngữ nghĩa và đến kèm CÙNG response nên không
# tốn thêm tiền. `paragraphs` đã thử và KHÔNG tách được logo — xem plan.


def test_parse_lay_duoc_blocks():
    page = _parse_documentai(_fake_document())["pages"][0]
    # Parser giữ NGUYÊN VĂN, gồm cả xuống dòng bên trong khối.
    assert page["blocks"] == ["Joma Bakery\n43 Tô Ngọc Vân", "TOTAL\n305,000"]


def test_parse_khong_vo_khi_khong_co_blocks():
    """Layout Parser và processor cũ không trả `blocks` — không được nổ."""
    page_khong_block = SimpleNamespace(
        page_number=1, lines=[], tables=[], form_fields=[], tokens=[]
    )
    page = _parse_documentai(SimpleNamespace(text="x", pages=[page_khong_block]))["pages"][0]
    assert page["blocks"] == []


def test_prompt_gop_moi_block_thanh_MOT_dong():
    """Đây là toàn bộ giá trị của việc dùng block — và là chỗ dễ tưởng đã xong.

    `_layout_text` cắt chuỗi nguyên văn nên block giữ luôn '\\n' bên trong. Nếu
    prompt nối block bằng '\\n' mà không gộp khoảng trắng bên trong, kết quả tái
    tạo Y HỆT text phẳng: đo trên chứng từ thật ra chênh lệch 0,0%, tức không
    được gì. Phải ép mỗi khối về một dòng thì ranh giới khối mới thấy được.
    """
    from common.ai_clients import _build_ocr_text

    prompt_text = _build_ocr_text(_parse_documentai(_fake_document()))

    assert "Joma Bakery 43 Tô Ngọc Vân" in prompt_text
    assert "Joma Bakery\n43 Tô Ngọc Vân" not in prompt_text
    # text phẳng KHÔNG được gửi kèm, nếu không là mỗi trang đi hai lần
    assert prompt_text.count("Tô Ngọc Vân") == 1


def test_prompt_roi_ve_text_khi_khong_co_blocks():
    """gemini_direct không qua OCR, Layout Parser trả `chunks` — phải còn chạy."""
    from common.ai_clients import _build_ocr_text

    assert _build_ocr_text({"text": "nội dung thô", "pages": []}) == "nội dung thô"
