"""Chặn hai cái bẫy của việc chạy job Textract — xem plan §2.2.

BẪY B: Textract async KHÔNG nhận bytes, nó chỉ nhận ĐỊA CHỈ S3 và tự vào lấy
file. Ba môi trường để file ở ba nơi khác nhau:

    Lambda production : S3 thật, đã có sẵn s3_key   -> đưa địa chỉ, không copy
    devserver         : moto = RAM máy mình         -> AWS ngoài kia không thấy
    evaluation        : ổ đĩa D:\\                   -> AWS ngoài kia không thấy

Nên devserver/evaluation phải đẩy file lên một bucket THẬT rồi xoá đi.

Ngoài ra: job có thể kết thúc ở PARTIAL_SUCCESS — trả kết quả cụt kèm Warnings.
Coi đó là thành công thì hệ thống nuốt mất mấy trang mà không ai biết.
"""

import pytest

from common.textract import (
    _await_blocks,
    _stage_target,
    ocr_with_textract,
    ocr_with_textract_analyze,
)


# --- Bẫy B: file đang nằm ở đâu -------------------------------------------


def test_production_dung_thang_file_da_co_tren_s3_khong_copy(monkeypatch):
    """Lambda: file đã nằm đúng chỗ rồi, copy thêm là tốn tiền và tốn thời gian."""
    monkeypatch.delenv("TEXTRACT_S3_BUCKET", raising=False)
    monkeypatch.setenv("DOCUMENTS_BUCKET", "prod-documents")

    bucket, key, phai_upload = _stage_target(
        b"noi dung", "application/pdf", "projects/p1/uploads/d1.pdf"
    )

    assert (bucket, key) == ("prod-documents", "projects/p1/uploads/d1.pdf")
    assert phai_upload is False


def test_co_TEXTRACT_S3_BUCKET_thi_luon_upload_du_da_co_s3_key(monkeypatch):
    """devserver: s3_key CÓ tồn tại, nhưng nó trỏ vào moto trong RAM.

    Đây là chỗ dễ sai nhất: thấy có s3_key rồi tưởng xong. Textract là AWS
    thật, nó không nhìn thấy được bucket giả nằm trong RAM máy mình.
    """
    monkeypatch.setenv("TEXTRACT_S3_BUCKET", "bucket-tam")
    monkeypatch.setenv("DOCUMENTS_BUCKET", "dev-documents")

    bucket, key, phai_upload = _stage_target(
        b"noi dung", "application/pdf", "projects/p1/uploads/d1.pdf"
    )

    assert bucket == "bucket-tam"
    assert key.startswith("textract-staging/")
    assert key.endswith(".pdf")
    assert phai_upload is True


def test_key_staging_theo_noi_dung_file_nen_on_dinh(monkeypatch):
    monkeypatch.setenv("TEXTRACT_S3_BUCKET", "bucket-tam")

    mot = _stage_target(b"AAA", "image/png", None)[1]
    hai = _stage_target(b"AAA", "image/png", None)[1]
    khac = _stage_target(b"BBB", "image/png", None)[1]

    assert mot == hai
    assert mot != khac
    assert mot.endswith(".png")


def test_thieu_ca_hai_thi_bao_loi_ro_rang_chu_khong_chay_tiep(monkeypatch):
    """evaluation chạy từ ổ đĩa: không có s3_key, không có bucket tạm.

    Phải nổ ngay với lời chỉ dẫn, không được gọi Textract rồi nhận lỗi
    InvalidS3ObjectException khó hiểu.
    """
    monkeypatch.delenv("TEXTRACT_S3_BUCKET", raising=False)

    with pytest.raises(RuntimeError, match="TEXTRACT_S3_BUCKET"):
        _stage_target(b"noi dung", "application/pdf", None)


# --- Chờ job xong ----------------------------------------------------------


def test_poll_cho_den_khi_SUCCEEDED_roi_moi_gom_block(monkeypatch):
    monkeypatch.setattr("common.textract.POLL_SECONDS", 0)
    phan_hoi = [
        {"JobStatus": "IN_PROGRESS"},
        {"JobStatus": "IN_PROGRESS"},
        {"JobStatus": "SUCCEEDED", "Blocks": [{"Id": "b1"}], "DocumentMetadata": {"Pages": 2}},
    ]
    lan_goi = {"n": 0}

    def fetch(next_token):
        if next_token is None and lan_goi["n"] < len(phan_hoi):
            lan_goi["n"] += 1
        return phan_hoi[min(lan_goi["n"], len(phan_hoi)) - 1]

    blocks, page_count = _await_blocks(fetch)

    assert blocks == [{"Id": "b1"}]
    assert page_count == 2
    assert lan_goi["n"] == 3


def test_job_FAILED_thi_nem_loi(monkeypatch):
    monkeypatch.setattr("common.textract.POLL_SECONDS", 0)

    with pytest.raises(RuntimeError, match="FAILED"):
        _await_blocks(lambda _: {"JobStatus": "FAILED", "StatusMessage": "hong roi"})


def test_PARTIAL_SUCCESS_KHONG_duoc_coi_la_thanh_cong(monkeypatch):
    """Textract trả kết quả CỤT kèm Warnings.

    Nuốt nó thì mấy trang bị bỏ qua biến mất không dấu vết, và chứng từ đi
    tiếp vào Gemini với nội dung thiếu — sai ở chỗ không ai nghĩ để nhìn.
    """
    monkeypatch.setattr("common.textract.POLL_SECONDS", 0)

    with pytest.raises(RuntimeError, match="PARTIAL_SUCCESS"):
        _await_blocks(
            lambda _: {
                "JobStatus": "PARTIAL_SUCCESS",
                "Blocks": [{"Id": "b1"}],
                "Warnings": [{"ErrorCode": "PAGE_LIMIT", "Pages": [3]}],
            }
        )


# --- Ghép cả luồng: dàn file -> chạy job -> parse -> dọn ------------------

BLOCKS_MOT_DONG = [
    {"BlockType": "PAGE", "Id": "p1", "Page": 1},
    {
        "BlockType": "LINE",
        "Id": "L1",
        "Text": "Joma Bakery",
        "Confidence": 97.0,
        "Page": 1,
    },
]


class FakeTextract:
    def __init__(self, blocks=None, job_status="SUCCEEDED"):
        self.blocks = BLOCKS_MOT_DONG if blocks is None else blocks
        self.job_status = job_status
        self.calls = []

    def _start(self, ten, kwargs):
        self.calls.append((ten, kwargs))
        return {"JobId": "job-1"}

    def _get(self, ten, kwargs):
        self.calls.append((ten, kwargs))
        return {
            "JobStatus": self.job_status,
            "Blocks": self.blocks,
            "DocumentMetadata": {"Pages": 1},
        }

    def start_document_analysis(self, **kwargs):
        return self._start("start_analysis", kwargs)

    def get_document_analysis(self, **kwargs):
        return self._get("get_analysis", kwargs)

    def start_document_text_detection(self, **kwargs):
        return self._start("start_detection", kwargs)

    def get_document_text_detection(self, **kwargs):
        return self._get("get_detection", kwargs)


class FakeS3:
    def __init__(self):
        self.calls = []

    def put_object(self, **kwargs):
        self.calls.append(("put", kwargs["Bucket"], kwargs["Key"]))

    def delete_object(self, **kwargs):
        self.calls.append(("delete", kwargs["Bucket"], kwargs["Key"]))


@pytest.fixture
def aws_gia(monkeypatch):
    monkeypatch.setattr("common.textract.POLL_SECONDS", 0)
    textract, s3 = FakeTextract(), FakeS3()
    monkeypatch.setattr("common.aws_real.textract_client", lambda: textract)
    monkeypatch.setattr("common.aws_real.s3_client", lambda: s3)
    return textract, s3


def test_analyze_bat_dung_FORMS_TABLES_LAYOUT(aws_gia, monkeypatch):
    """LAYOUT là thứ cho ra `blocks` — và MIỄN PHÍ khi đi kèm TABLES.

    Quên bật LAYOUT thì mất khối ngữ nghĩa mà không tiết kiệm được đồng nào.
    """
    monkeypatch.setenv("TEXTRACT_S3_BUCKET", "bucket-tam")
    textract, _ = aws_gia

    ocr_with_textract_analyze(b"pdf", "application/pdf")

    ten, kwargs = textract.calls[0]
    assert ten == "start_analysis"
    assert sorted(kwargs["FeatureTypes"]) == ["FORMS", "LAYOUT", "TABLES"]


def test_detect_khong_gui_FeatureTypes(aws_gia, monkeypatch):
    """DetectDocumentText rẻ hơn 43 lần và KHÔNG nhận FeatureTypes."""
    monkeypatch.setenv("TEXTRACT_S3_BUCKET", "bucket-tam")
    textract, _ = aws_gia

    ocr_with_textract(b"pdf", "application/pdf")

    ten, kwargs = textract.calls[0]
    assert ten == "start_detection"
    assert "FeatureTypes" not in kwargs


def test_tra_ve_dung_hop_dong_ocr(aws_gia, monkeypatch):
    monkeypatch.setenv("TEXTRACT_S3_BUCKET", "bucket-tam")

    ocr_json = ocr_with_textract(b"pdf", "application/pdf")

    assert ocr_json["text"] == "Joma Bakery"
    assert ocr_json["pages"][0]["lines"][0]["confidence"] == 0.97


def test_don_file_staging_sau_khi_chay(aws_gia, monkeypatch):
    monkeypatch.setenv("TEXTRACT_S3_BUCKET", "bucket-tam")
    _, s3 = aws_gia

    ocr_with_textract(b"pdf", "application/pdf")

    thao_tac = [c[0] for c in s3.calls]
    assert thao_tac == ["put", "delete"]
    assert s3.calls[0][1] == "bucket-tam"
    assert s3.calls[0][2] == s3.calls[1][2]


def test_don_file_staging_CA_KHI_job_loi(monkeypatch):
    """Job hỏng vẫn phải dọn, nếu không bucket tạm phình mãi và tốn tiền lưu."""
    monkeypatch.setattr("common.textract.POLL_SECONDS", 0)
    monkeypatch.setenv("TEXTRACT_S3_BUCKET", "bucket-tam")
    s3 = FakeS3()
    monkeypatch.setattr("common.aws_real.textract_client", lambda: FakeTextract(job_status="FAILED"))
    monkeypatch.setattr("common.aws_real.s3_client", lambda: s3)

    with pytest.raises(RuntimeError, match="FAILED"):
        ocr_with_textract(b"pdf", "application/pdf")

    assert [c[0] for c in s3.calls] == ["put", "delete"]


def test_production_khong_upload_khong_xoa(aws_gia, monkeypatch):
    """Lambda: file đã nằm đúng chỗ. Đụng vào file gốc của người ta là sai."""
    monkeypatch.delenv("TEXTRACT_S3_BUCKET", raising=False)
    monkeypatch.setenv("DOCUMENTS_BUCKET", "prod-documents")
    textract, s3 = aws_gia

    ocr_with_textract(b"pdf", "application/pdf", s3_key="projects/p1/uploads/d1.pdf")

    assert s3.calls == []
    assert textract.calls[0][1]["DocumentLocation"] == {
        "S3Object": {"Bucket": "prod-documents", "Name": "projects/p1/uploads/d1.pdf"}
    }


def test_throttle_thanh_RateLimitError_de_step_functions_retry(monkeypatch):
    """Map chạy 3 doc song song nên bị Textract throttle là chuyện thường.

    Không đổi thành RateLimitError thì nhánh Retry ErrorEquals ["RateLimitError"]
    trong statemachine.asl.json không chạy, và chứng từ chết thay vì thử lại.
    """
    from common.errors import RateLimitError

    monkeypatch.setattr("common.textract.POLL_SECONDS", 0)
    monkeypatch.setenv("TEXTRACT_S3_BUCKET", "bucket-tam")

    class Throttled(FakeTextract):
        def start_document_text_detection(self, **kwargs):
            raise Exception(
                "An error occurred (ThrottlingException) when calling the "
                "StartDocumentTextDetection operation: Rate exceeded"
            )

    s3 = FakeS3()
    monkeypatch.setattr("common.aws_real.textract_client", lambda: Throttled())
    monkeypatch.setattr("common.aws_real.s3_client", lambda: s3)

    with pytest.raises(RateLimitError):
        ocr_with_textract(b"pdf", "application/pdf")

    assert [c[0] for c in s3.calls] == ["put", "delete"]


def test_khong_gui_NextToken_rong_o_lan_goi_dau(aws_gia, monkeypatch):
    """boto3 từ chối NextToken=None. Lần đầu phải KHÔNG có tham số đó."""
    monkeypatch.setenv("TEXTRACT_S3_BUCKET", "bucket-tam")
    textract, _ = aws_gia

    ocr_with_textract(b"pdf", "application/pdf")

    lan_get = [kwargs for ten, kwargs in textract.calls if ten == "get_detection"]
    assert lan_get and all("NextToken" not in kwargs for kwargs in lan_get)
