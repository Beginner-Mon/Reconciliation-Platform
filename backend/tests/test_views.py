"""Tiến độ phải tăng mượt theo BƯỚC, không nhảy theo document.

Bug gốc: `begin_step()` đặt status="PROCESSING" ở mọi bước, ghi đè mất
OCR_DONE/EXTRACTED. Nếu `steps_done()` chỉ nhìn status thì tiến độ đứng im ở 0
suốt cả document rồi nhảy một phát — với AI thật (5-30s/bước) thì thanh tiến
trình treo cả phút. Phát hiện khi chạy dev server, không test nào bắt được.
"""

from api.views import progress_view, steps_done

# Đúng thứ tự worker ghi state trong một lần chạy 1 document.
VONG_DOI = [
    ({"status": "PENDING"}, 0),
    ({"status": "PROCESSING", "step": "ocr", "step_status": "running"}, 0),
    ({"status": "PROCESSING", "step": "ocr", "step_status": "done"}, 1),
    ({"status": "OCR_DONE", "step": "ocr", "step_status": "done"}, 1),
    ({"status": "PROCESSING", "step": "extract", "step_status": "running"}, 1),
    ({"status": "PROCESSING", "step": "extract", "step_status": "done"}, 2),
    ({"status": "EXTRACTED", "step": "extract", "step_status": "done"}, 2),
    ({"status": "PROCESSING", "step": "validate", "step_status": "running"}, 2),
    ({"status": "VALIDATED", "step": "validate", "step_status": "done"}, 3),
]


def test_tien_do_khong_bao_gio_tut_lui():
    values = [steps_done(doc) for doc, _ in VONG_DOI]
    assert all(b >= a for a, b in zip(values, values[1:])), values


def test_tung_moc_dung_so_buoc():
    for document, expected in VONG_DOI:
        assert steps_done(document) == expected, document


def test_dang_extract_thi_ocr_da_xong():
    dang_extract = {"status": "PROCESSING", "step": "extract", "step_status": "running"}
    assert steps_done(dang_extract) == 1


def test_that_bai_giu_so_buoc_da_qua():
    assert steps_done({"status": "FAILED", "step": "ocr"}) == 0
    assert steps_done({"status": "FAILED", "step": "extract"}) == 1
    assert steps_done({"status": "FAILED", "step": "validate"}) == 2


def test_progress_percent_tinh_theo_buoc_khong_theo_document():
    documents = [
        {"status": "PROCESSING", "step": "validate", "step_status": "running"},
        {"status": "PENDING"},
    ]
    # 2 trong 3 bước của doc đầu đã xong -> 2/6, KHÔNG phải 0/2 document
    assert progress_view(documents)["progress_percent"] == 33


def test_progress_rong_thi_100():
    assert progress_view([])["progress_percent"] == 100
