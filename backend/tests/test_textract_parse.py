"""Chặn bug parse Textract — cùng vai trò với test_docai_parse.py.

Textract trả về hình dạng KHÁC HẲN Document AI: một DANH SÁCH PHẲNG, trong đó
mỗi chữ, mỗi dòng, mỗi ô bảng đều là một "Block" rời, nối với nhau bằng
`Relationships` trỏ theo Id. Không có `text` tổng, không có `pages[]`.

Parser phải dịch nó về ĐÚNG hợp đồng OCR hiện có — thứ mà `_build_ocr_text`,
`api/views.py` và frontend đang đọc:

    {"text", "pages": [{page_number, lines, blocks, tables,
                        key_value_pairs, token_count, mean_token_confidence}]}

Ba chỗ dễ sai, mỗi chỗ một test bên dưới:
  1. Confidence của Textract là thang 0-100; của Document AI là 0-1.
  2. `GetDocument*` phân trang bằng NextToken — quên vòng lặp là mất trang.
  3. DetectDocumentText không có LAYOUT_* nên `blocks` rỗng, phải rơi về `text`.
"""

from common.textract import _collect_blocks, _parse_textract

# --- Dựng Blocks giả đúng hình dạng Textract thật -------------------------
#
# Cùng nội dung với test_docai_parse.py để so được hai parser cạnh nhau.

WORD_CONFIDENCE = 90.0


def word(block_id: str, text: str, confidence: float = WORD_CONFIDENCE, page: int = 1):
    return {
        "BlockType": "WORD",
        "Id": block_id,
        "Text": text,
        "Confidence": confidence,
        "Page": page,
    }


def line(block_id: str, text: str, confidence: float, word_ids: list[str], page: int = 1):
    return {
        "BlockType": "LINE",
        "Id": block_id,
        "Text": text,
        "Confidence": confidence,
        "Page": page,
        "Relationships": [{"Type": "CHILD", "Ids": word_ids}],
    }


def layout(block_id: str, line_ids: list[str], page: int = 1):
    """LAYOUT_TEXT — khối ngữ nghĩa, tương đương `blocks` của Document AI."""
    return {
        "BlockType": "LAYOUT_TEXT",
        "Id": block_id,
        "Page": page,
        "Relationships": [{"Type": "CHILD", "Ids": line_ids}],
    }


def cell(block_id: str, row: int, column: int, word_ids: list[str], page: int = 1):
    return {
        "BlockType": "CELL",
        "Id": block_id,
        "RowIndex": row,
        "ColumnIndex": column,
        "Page": page,
        "Relationships": [{"Type": "CHILD", "Ids": word_ids}],
    }


def fake_blocks() -> list[dict]:
    return [
        {"BlockType": "PAGE", "Id": "p1", "Page": 1},
        # Sáu dòng chữ nhìn thấy trên tờ giấy.
        line("L1", "Joma Bakery", 97.0, ["w1", "w2"]),
        line("L2", "43 Tô Ngọc Vân", 42.0, ["w3", "w4", "w5", "w6"]),
        line("L3", "TOTAL", 88.0, ["w7"]),
        line("L4", "305,000", 53.0, ["w8"]),
        line("L5", "SL", 91.0, ["w9"]),
        line("L6", "2", 99.0, ["w10"]),
        word("w1", "Joma"),
        word("w2", "Bakery", confidence=80.0),
        word("w3", "43"),
        word("w4", "Tô"),
        word("w5", "Ngọc"),
        word("w6", "Vân"),
        word("w7", "TOTAL"),
        word("w8", "305,000"),
        word("w9", "SL"),
        word("w10", "2"),
        # Khối ngữ nghĩa: tên công ty + địa chỉ dính liền một cục.
        layout("z1", ["L1", "L2"]),
        layout("z2", ["L3", "L4"]),
        # Bảng: 1 cột, dòng 1 là header.
        {
            "BlockType": "TABLE",
            "Id": "t1",
            "Page": 1,
            "Relationships": [{"Type": "CHILD", "Ids": ["c2", "c1"]}],
        },
        cell("c1", row=1, column=1, word_ids=["w9"]),
        cell("c2", row=2, column=1, word_ids=["w10"]),
        # Cặp key-value: KEY trỏ sang VALUE bằng quan hệ "VALUE".
        {
            "BlockType": "KEY_VALUE_SET",
            "Id": "k1",
            "EntityTypes": ["KEY"],
            "Page": 1,
            "Relationships": [
                {"Type": "CHILD", "Ids": ["w7"]},
                {"Type": "VALUE", "Ids": ["v1"]},
            ],
        },
        {
            "BlockType": "KEY_VALUE_SET",
            "Id": "v1",
            "EntityTypes": ["VALUE"],
            "Confidence": 53.0,
            "Page": 1,
            "Relationships": [{"Type": "CHILD", "Ids": ["w8"]}],
        },
    ]


# --- Bẫy 1: hai thang confidence khác nhau --------------------------------


def test_confidence_doi_tu_thang_100_ve_thang_1():
    """Textract trả 0-100, Document AI trả 0-1. Quên chia là hỏng Human Review.

    `mean_token_confidence` và confidence từng dòng là thứ giao diện dùng để
    tô vàng chỗ OCR đọc không chắc. Để nguyên thang 100 thì mọi ngưỡng cảnh
    báo (< 0.8) không bao giờ chạm tới, và hệ thống im lặng nói "mọi thứ đều
    chắc chắn" — sai mà không ai thấy.
    """
    page = _parse_textract(fake_blocks())["pages"][0]

    assert page["lines"][0]["confidence"] == 0.97
    assert page["lines"][1]["confidence"] == 0.42
    assert page["key_value_pairs"][0]["confidence"] == 0.53
    assert all(0.0 <= dong["confidence"] <= 1.0 for dong in page["lines"])


def test_mean_token_confidence_tinh_tu_WORD():
    page = _parse_textract(fake_blocks())["pages"][0]

    # 10 WORD: chín cái 90.0 và một cái 80.0 -> trung bình 89.0 -> 0.89
    assert page["token_count"] == 10
    assert page["mean_token_confidence"] == 0.89


# --- Dịch về đúng hợp đồng OCR hiện có ------------------------------------


def test_text_gop_tu_cac_LINE():
    """Textract KHÔNG trả text tổng — phải tự nối từ các LINE."""
    assert _parse_textract(fake_blocks())["text"] == (
        "Joma Bakery\n43 Tô Ngọc Vân\nTOTAL\n305,000\nSL\n2"
    )


def test_lines_giu_nguyen_thu_tu_va_kem_confidence():
    page = _parse_textract(fake_blocks())["pages"][0]

    assert page["lines"][:2] == [
        {"text": "Joma Bakery", "confidence": 0.97},
        {"text": "43 Tô Ngọc Vân", "confidence": 0.42},
    ]


def test_blocks_lay_tu_LAYOUT_TEXT():
    """LAYOUT_* của Textract đóng đúng vai `blocks` của Document AI.

    Giữ '\\n' bên trong khối y hệt Document AI để `_build_ocr_text` xử lý
    CHUNG một đường, không phải rẽ nhánh theo engine.
    """
    page = _parse_textract(fake_blocks())["pages"][0]

    assert page["blocks"] == ["Joma Bakery\n43 Tô Ngọc Vân", "TOTAL\n305,000"]


def test_tables_sap_theo_RowIndex_ColumnIndex():
    """Quan hệ CHILD của TABLE KHÔNG bảo đảm thứ tự — fixture cố tình đảo.

    `_build_ocr_text` lấy dòng ĐẦU TIÊN làm header của bảng markdown. Đọc theo
    thứ tự Ids trả về thì header thành "2" và bảng vô nghĩa.
    """
    page = _parse_textract(fake_blocks())["pages"][0]

    assert page["tables"][0]["rows"] == [{"cells": ["SL"]}, {"cells": ["2"]}]


def test_key_value_pairs_lan_theo_quan_he_VALUE():
    page = _parse_textract(fake_blocks())["pages"][0]

    assert page["key_value_pairs"] == [
        {"key": "TOTAL", "value": "305,000", "confidence": 0.53}
    ]


def test_tach_dung_tung_trang():
    blocks = fake_blocks() + [
        {"BlockType": "PAGE", "Id": "p2", "Page": 2},
        line("L7", "Trang hai", 95.0, ["w11"], page=2),
        word("w11", "Trang", page=2),
    ]
    result = _parse_textract(blocks)

    assert [p["page_number"] for p in result["pages"]] == [1, 2]
    assert result["pages"][1]["lines"] == [{"text": "Trang hai", "confidence": 0.95}]
    assert result["pages"][0]["token_count"] == 10


# --- Bẫy 3: DetectDocumentText không có LAYOUT ------------------------------


def test_khong_co_LAYOUT_thi_blocks_rong_chu_khong_vo():
    """DetectDocumentText chỉ trả PAGE/LINE/WORD — rẻ 43 lần, không có khối."""
    blocks = [b for b in fake_blocks() if not b["BlockType"].startswith("LAYOUT")]
    page = _parse_textract(blocks)["pages"][0]

    assert page["blocks"] == []
    assert page["lines"]


def test_prompt_gemini_dung_duoc_ngay_khong_sua_gi():
    """Hợp đồng OCR phải khớp đến mức `_build_ocr_text` chạy y nguyên.

    Đây là điểm mấu chốt của cả việc thêm engine: nếu parser trả sai hình
    dạng thì extract/validate/frontend đều phải sửa theo, và "thêm 1 option"
    biến thành sửa cả pipeline.
    """
    from common.ai_clients import _build_ocr_text

    prompt = _build_ocr_text(_parse_textract(fake_blocks()))

    # Khối được ép về MỘT dòng, y như đường Document AI.
    assert "Joma Bakery 43 Tô Ngọc Vân" in prompt
    # text phẳng KHÔNG gửi kèm, nếu không mỗi trang đi hai lần, tiền gấp đôi.
    assert prompt.count("Tô Ngọc Vân") == 1
    # Bảng dựng thành markdown có header.
    assert "| SL |" in prompt
    assert "TOTAL: 305,000" in prompt


def test_khong_vo_khi_trang_rong():
    page = _parse_textract([{"BlockType": "PAGE", "Id": "p1", "Page": 1}])["pages"][0]

    assert page["lines"] == []
    assert page["blocks"] == []
    assert page["token_count"] == 0
    assert page["mean_token_confidence"] is None


# --- Bẫy 2: NextToken -------------------------------------------------------


def test_collect_blocks_gom_du_moi_trang_NextToken():
    """Doc nhiều trang có bảng vượt 1.000 block rất dễ.

    Quên vòng lặp NextToken thì mất trang mà KHÔNG có lỗi nào nổ ra — kết quả
    cụt trông y hệt một tài liệu ngắn.
    """
    trang = [
        {"Blocks": [word("w1", "một")], "NextToken": "t2", "DocumentMetadata": {"Pages": 3}},
        {"Blocks": [word("w2", "hai")], "NextToken": "t3"},
        {"Blocks": [word("w3", "ba")]},
    ]
    da_goi = []

    def fetch(next_token):
        da_goi.append(next_token)
        return trang[len(da_goi) - 1]

    blocks, page_count = _collect_blocks(fetch)

    assert [b["Text"] for b in blocks] == ["một", "hai", "ba"]
    assert da_goi == [None, "t2", "t3"]
    assert page_count == 3


def test_words_lay_tu_Geometry_cua_WORD():
    blocks = fake_blocks()
    next(b for b in blocks if b.get("Id") == "w1")["Geometry"] = {
        "BoundingBox": {"Left": 0.1, "Top": 0.2, "Width": 0.15, "Height": 0.03}
    }

    page = _parse_textract(blocks)["pages"][0]

    assert page["words"] == [["Joma", 0.1, 0.2, 0.25, 0.23]]


def test_WORD_khong_co_Geometry_thi_words_rong():
    assert _parse_textract(fake_blocks())["pages"][0]["words"] == []
