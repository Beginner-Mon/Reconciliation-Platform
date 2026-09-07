"""Registry engine OCR — một bảng duy nhất, thay cho bốn bảng khai trùng nhau.

Trước đây cùng một thông tin bị khai lại ở bốn chỗ rời: `PROCESSORS`
(devserver), `OCR_ONLY` / `OCR_ONLY_ENV` / `OCR_ONLY_USD_PER_PAGE`
(evaluation/flows.py) và `ENGINE_LABEL` (evaluation/inspect_ocr.py). Thêm một
engine là phải sửa đúng bốn chỗ và bốn chỗ phải khớp nhau.

Gõ lệch một chỗ thì `audit_log` ghi sai tiền — ĐÃ XẢY RA RỒI: §5 CLAUDE.md ghi
"ước tính chi phí lệch 20 lần vì lấy giá Form Parser cho Document OCR".
Lên năm engine mà vẫn để rời là chắc chắn lệch lại.
"""

import pytest

from common import ocr_engines


def test_moi_engine_khai_du_ham_nhan_va_don_gia():
    for name, spec in ocr_engines.ENGINES.items():
        assert callable(spec["fn"]), name
        assert spec["label"], name
        assert spec["note"], name
        assert ocr_engines.usd_per_page(name) > 0, name


def test_don_gia_dung_bang_da_kiem_chung():
    """Đổi số ở đây là đổi số tiền ghi vào audit_log. Nguồn ghi trong docstring
    của ocr_engines.py — sửa thì phải sửa cả nguồn."""
    assert ocr_engines.usd_per_page("dococr") == 0.0015
    assert ocr_engines.usd_per_page("formparser") == 0.030
    assert ocr_engines.usd_per_page("layout") == 0.010
    # Textract DetectDocumentText NGANG GIÁ Enterprise Document OCR -> so sạch.
    assert ocr_engines.usd_per_page("textract") == 0.0015
    assert ocr_engines.usd_per_page("textract-analyze") == 0.065


def test_nhan_audit_khong_duoc_trung_nhau():
    """Hai engine cùng nhãn thì audit_log không phân biệt được đã chạy cái nào."""
    nhan = [spec["label"] for spec in ocr_engines.ENGINES.values()]
    assert len(nhan) == len(set(nhan))


def test_doi_gia_bang_bien_moi_truong_khong_phai_sua_code(monkeypatch):
    monkeypatch.setenv("TEXTRACT_USD_PER_PAGE", "0.0020")
    assert ocr_engines.usd_per_page("textract") == 0.0020


def test_ten_engine_sai_thi_no_ngay_kem_danh_sach_ten_dung():
    """Im lặng rơi về Document AI là kiểu hỏng tệ nhất: chạy đúng, tính sai tiền,
    và audit_log ghi một engine mà thật ra không hề chạy."""
    with pytest.raises(ValueError) as exc:
        ocr_engines.resolve("textrakt")

    thong_bao = str(exc.value)
    assert "textrakt" in thong_bao
    for name in ocr_engines.ENGINES:
        assert name in thong_bao


def test_uoc_tinh_chi_phi_theo_dung_engine():
    """Đây chính là chỗ đã lệch 20 lần: lấy đơn giá engine này cho engine kia."""
    assert ocr_engines.estimate_cost("dococr", 14) == pytest.approx(0.021)
    assert ocr_engines.estimate_cost("textract-analyze", 14) == pytest.approx(0.91)


def test_mac_dinh_la_textract():
    """Đổi từ dococr sang textract vì đang có free tier của AWS.

    ĐÁNH ĐỔI CÓ Ý THỨC: Textract KHÔNG hỗ trợ tiếng Việt (đo trên hoá đơn thật:
    `Phuring Khuong Mai` <- `Phường Khương Mai`). Số thì vẫn đọc đúng, nên chấp
    nhận được cho POC — nhưng cảnh báo phải hiện ngay chỗ chọn engine, xem
    `app_choices()`, chứ không chôn trong tài liệu.
    """
    assert ocr_engines.DEFAULT_ENGINE == "textract"


# --- Engine cho APP vs engine cho ĐO ĐẠC ----------------------------------


def test_app_chi_cho_chon_hai_engine():
    """Giao diện, API và devserver chỉ được biết tới hai engine này."""
    assert ocr_engines.APP_ENGINES == ("textract", "dococr")
    assert ocr_engines.DEFAULT_ENGINE in ocr_engines.APP_ENGINES


def test_bang_van_du_nam_engine_de_evaluation_con_do_duoc():
    """KHÔNG xoá ba engine kia khỏi bảng, dù app không cho chọn nữa.

    `evaluation/flows.py` sinh flow từ chính bảng này. Xoá entry là mất luôn khả
    năng trả lời "sao không dùng Form Parser?" bằng số đo. Và tách làm hai bảng
    là đúng cái sai §5 CLAUDE.md cấm — giá và nhãn phải ở CÙNG một chỗ với hàm.
    """
    assert set(ocr_engines.ENGINES) == {
        "dococr",
        "formparser",
        "layout",
        "textract",
        "textract-analyze",
    }


def test_engine_ngoai_danh_sach_app_bi_tu_choi():
    """`resolve` vẫn nhận (evaluation cần), nhưng lối vào của app thì không."""
    assert ocr_engines.resolve("formparser")["label"]

    with pytest.raises(ValueError) as exc:
        ocr_engines.resolve_for_app("formparser")

    thong_bao = str(exc.value)
    assert "formparser" in thong_bao
    for name in ocr_engines.APP_ENGINES:
        assert name in thong_bao


def test_moi_engine_khai_ro_co_ho_tro_tieng_viet_hay_khong():
    """Cờ này lái hai cảnh báo: dòng LƯU Ý lúc devserver khởi động, và nhãn đỏ
    trong menu "Chạy lại với…" (frontend khai cứng, `test_routes.py` khoá lại).

    Cảnh báo sai chỗ còn tệ hơn không có: người dùng chọn nhầm engine mất dấu
    cho chứng từ tiếng Việt mà tưởng là an toàn.
    """
    for name, spec in ocr_engines.ENGINES.items():
        assert isinstance(spec["supports_vietnamese"], bool), name
        # Google Document AI đọc được tiếng Việt; AWS Textract thì không —
        # tài liệu AWS chỉ liệt kê 6 thứ tiếng, không có tiếng Việt.
        assert spec["supports_vietnamese"] is (spec["cloud"] == "google"), name


# --- Kiểm credential trước khi chạy ---------------------------------------


def test_engine_google_doi_credential_google(monkeypatch):
    for name in ("DOCAI_PROJECT", "DOCAI_OCR_PROCESSOR_ID"):
        monkeypatch.delenv(name, raising=False)

    thieu = ocr_engines.missing_env("dococr")

    assert "DOCAI_PROJECT" in thieu
    assert "DOCAI_OCR_PROCESSOR_ID" in thieu


def test_engine_textract_KHONG_doi_credential_google(monkeypatch):
    """Chạy Textract mà bắt khai DOCAI_PROJECT là vô lý — và sẽ chặn người dùng
    thử engine mới chỉ vì họ chưa có tài khoản Google."""
    for name in ("DOCAI_PROJECT", "DOCAI_OCR_PROCESSOR_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TEXTRACT_S3_BUCKET", "bucket-tam")

    assert ocr_engines.missing_env("textract") == []


def test_textract_o_moi_truong_local_doi_bucket_that(monkeypatch):
    """Bẫy B: Textract async chỉ đọc file từ S3 thật, không nhận bytes."""
    monkeypatch.delenv("TEXTRACT_S3_BUCKET", raising=False)
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)

    assert "TEXTRACT_S3_BUCKET" in ocr_engines.missing_env("textract")


def test_tren_lambda_khong_doi_bucket_tam(monkeypatch):
    """Trên Lambda file đã nằm sẵn trên S3 thật với đúng s3_key — không copy."""
    monkeypatch.delenv("TEXTRACT_S3_BUCKET", raising=False)
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "reconciliation-ocr-dev")

    assert ocr_engines.missing_env("textract") == []


# --- Bốn bảng cũ phải đọc từ registry, không tự khai lại -------------------


def test_devserver_lay_processor_tu_registry():
    import devserver.__main__ as entry

    assert set(entry.PROCESSORS) == set(ocr_engines.ENGINES)
    for name, spec in entry.PROCESSORS.items():
        assert float(spec["usd_per_page"]) == ocr_engines.usd_per_page(name)
        assert spec["label"] == ocr_engines.ENGINES[name]["label"]


def test_devserver_chi_cho_chon_engine_cua_app():
    """`--processor formparser` phải bị argparse từ chối.

    devserver LÀ app chạy ở máy, không phải công cụ đo — ba engine kia chỉ còn
    sống trong `evaluation/`.
    """
    import devserver.__main__ as entry

    parser = entry.build_parser()
    action = next(a for a in parser._actions if a.dest == "processor")

    assert list(action.choices) == list(ocr_engines.APP_ENGINES)
    assert action.default == ocr_engines.DEFAULT_ENGINE
