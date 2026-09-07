"""Dev server phải chạy đúng luồng mà state machine thật định nghĩa.

Rủi ro cần chặn: ai đó sửa statemachine.asl.json mà quên sửa dev server, dẫn
tới dev chạy một đằng cloud chạy một nẻo. Test này bắt lỗi đó offline.
"""

import json
import os
import pathlib
import subprocess
import sys

import pytest

from devserver import bootstrap
from devserver.pipeline import STATE_TO_WORKER, build_plan, load_asl


def task_states(states: dict) -> set[str]:
    return {name for name, s in states.items() if s.get("Type") == "Task"}


def test_moi_task_state_trong_asl_deu_co_worker():
    asl = load_asl()
    inner = asl["States"]["ProcessDocuments"]["ItemProcessor"]["States"]
    thieu = (task_states(asl["States"]) | task_states(inner)) - set(STATE_TO_WORKER)
    assert not thieu, f"ASL có Task state chưa có worker trong dev server: {thieu}"


def test_thu_tu_buoc_lay_tu_asl_chu_khong_hardcode():
    plan = build_plan()
    assert plan["per_document"] == ["Ocr", "Extract", "Validate"]
    assert plan["after_map"] == ["Reconcile"]
    assert plan["run_failed"] == "MarkRunFailed"


def test_moi_buoc_deu_co_nhanh_catch():
    plan = build_plan()
    for state in plan["per_document"]:
        assert plan["catch_of"].get(state), f"{state} thiếu Catch trong ASL"


def test_step_label_lay_dung_tu_parameters_cua_asl():
    plan = build_plan()
    assert plan["step_of"] == {"Ocr": "ocr", "Extract": "extract", "Validate": "validate"}


def test_bao_loi_ngay_neu_asl_them_state_la():
    asl = load_asl()
    asl["States"]["ProcessDocuments"]["ItemProcessor"]["States"]["Classify"] = {
        "Type": "Task",
        "Resource": "arn:aws:lambda:x",
        "End": True,
    }
    with pytest.raises(RuntimeError, match="Classify"):
        build_plan(asl)


def test_bang_dinh_nghia_dung_chung_khop_voi_moi_truong():
    import os

    names = {spec["env"] for spec in bootstrap.TABLE_DEFINITIONS}
    assert names == {
        "PROJECTS_TABLE",
        "DOCUMENTS_TABLE",
        "RUNS_TABLE",
        "RECONCILIATIONS_TABLE",
        "AUDIT_LOG_TABLE",
    }
    for spec in bootstrap.TABLE_DEFINITIONS:
        assert os.environ.get(spec["env"]), f"conftest chưa đặt {spec['env']}"


def test_documents_co_du_hai_gsi():
    spec = next(s for s in bootstrap.TABLE_DEFINITIONS if s["env"] == "DOCUMENTS_TABLE")
    assert {i["IndexName"] for i in spec["indexes"]} == {
        "project_id-index",
        "po_number-index",
    }


def test_event_dung_hinh_dang_ma_api_handler_mong_doi():
    from api.handler import lambda_handler

    event = {
        "requestContext": {"http": {"method": "GET"}},
        "rawPath": "/khong-ton-tai",
        "body": None,
    }
    result = lambda_handler(event, None)
    assert result["statusCode"] == 404
    assert json.loads(result["body"])["error"]


def test_khong_con_duong_nao_chay_bang_ai_gia():
    """Dev server chỉ được có MỘT chế độ: AI thật.

    Dữ liệu mẫu nhìn y hệt lỗi hệ thống. Test này chặn việc ai đó thêm lại một
    chế độ dự phòng "cho tiện" rồi quên mất mình đang xem dữ liệu bịa.
    """
    import devserver.__main__ as entry

    assert not hasattr(entry, "load_real_ai_env")
    for name in ("fake_ai", "replay_ocr", "minipdf", "seed"):
        assert not (pathlib.Path(entry.__file__).parent / f"{name}.py").exists(),             f"devserver/{name}.py phải bị xoá"


def test_client_textract_khong_bao_gio_tro_vao_moto(monkeypatch):
    """Textract là dịch vụ AWS -> gọi bằng boto3 -> dễ dính moto y như S3.

    Dev server đặt AWS_ENDPOINT_URL trỏ vào moto, và mọi client trong repo đều
    đọc biến đó (common/s3.py, dynamodb.py, stepfunctions.py). moto CÓ Textract
    giả: nó trả Block bịa sẵn kèm JobStatus SUCCEEDED. Viết theo nếp cũ thì dev
    server chạy êm, giao diện hiện chữ, không tốn xu nào — mà chữ đó là bịa.

    Đúng thứ đã bị gỡ ở test_khong_con_duong_nao_chay_bang_ai_gia, lần này còn
    không có băng cảnh báo màu vàng nào.
    """
    from common.aws_real import textract_client

    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://127.0.0.1:5000")
    endpoint = textract_client().meta.endpoint_url

    assert "127.0.0.1" not in endpoint, f"client Textract dính moto: {endpoint}"
    assert endpoint.startswith("https://textract."), endpoint


def _event_dau_tien_cua_devserver(payload: dict) -> dict:
    """Chạy `run_local` với worker giả, trả về event mà document đầu tiên nhận."""
    from devserver import pipeline

    nhan_duoc: list[dict] = []

    def ghi_lai(event, context):
        nhan_duoc.append(event)
        return event

    plan = {
        "per_document": ["Ocr"],
        "after_map": [],
        "catch_of": {},
        "step_of": {},
        "run_failed": None,
    }
    goc = dict(pipeline.STATE_TO_WORKER)
    pipeline.STATE_TO_WORKER["Ocr"] = ghi_lai
    try:
        pipeline.run_local(payload, plan)
    finally:
        pipeline.STATE_TO_WORKER.clear()
        pipeline.STATE_TO_WORKER.update(goc)
    return nhan_duoc[0]


def test_event_cua_devserver_khop_voi_ItemSelector_cua_ASL():
    """Map ItemSelector quyết định worker THẬT nhận được những khoá nào.

    `run_local` dựng event bằng tay. Lệch một khoá là dev chạy một đằng cloud
    chạy một nẻo — thêm `ocr_engine` vào ASL mà quên dev server thì ở máy engine
    im lặng rơi về biến môi trường, và bài so hai engine cho kết quả sai mà
    không có dấu hiệu gì.
    """
    selector = load_asl()["States"]["ProcessDocuments"]["ItemSelector"]
    khoa_asl = {name.removesuffix(".$") for name in selector}

    event = _event_dau_tien_cua_devserver(
        {
            "project_id": "prj-1",
            "run_id": "run-1",
            "ocr_engine": "dococr",
            "documents": [{"document_id": "doc-1", "s3_key": "projects/prj-1/a.pdf"}],
        }
    )

    assert set(event) == khoa_asl
    assert event["ocr_engine"] == "dococr"


def test_ten_bang_khong_bi_khoa_truoc_khi_devserver_dat_env():
    """`common/dynamodb.py` đọc tên bảng vào HẰNG SỐ ngay lúc import module:

        PROJECTS_TABLE = os.environ.get("PROJECTS_TABLE", "projects")

    Nên thứ tự là bắt buộc: đặt env TRƯỚC, import `common` SAU. `devserver/
    __main__.py` từng import `common` ở mức module (để lấy bảng engine OCR) rồi
    mới đặt DEFAULTS trong `main()` — hằng số khoá vào giá trị mặc định
    `projects`/`documents` trong khi bootstrap tạo `dev-projects`/`dev-documents`.

    Hậu quả: bootstrap in ra "đã tạo 5 bảng" rồi request đầu tiên chết vì
    ResourceNotFoundException — thông báo trỏ vào DynamoDB chứ không hé lộ gì về
    thứ tự import. `tests/conftest.py` né được vì nó đặt env ở dòng đầu tiên.

    Phải chạy ở TIẾN TRÌNH CON: trong pytest thì conftest đã đặt sẵn env nên
    hằng số luôn khớp, test sẽ xanh kể cả khi lỗi còn nguyên.
    """
    backend = pathlib.Path(__file__).resolve().parents[1]
    # Đúng trình tự `main()`: import module -> đặt DEFAULTS -> dùng common.
    ma = (
        "import os, sys; sys.path.insert(0, '.');"
        "import devserver.__main__ as e;"
        "[os.environ.setdefault(k, v) for k, v in e.DEFAULTS.items()];"
        "import common.dynamodb as d;"
        "print(d.PROJECTS_TABLE, e.DEFAULTS['PROJECTS_TABLE'])"
    )
    ket_qua = subprocess.run(
        [sys.executable, "-c", ma],
        cwd=backend,
        capture_output=True,
        text=True,
        # Môi trường sạch: bỏ đúng biến mà conftest đã đặt sẵn.
        env={k: v for k, v in os.environ.items() if not k.endswith("_TABLE")},
    )

    assert ket_qua.returncode == 0, ket_qua.stderr
    hang_so, bien_moi_truong = ket_qua.stdout.split()
    assert hang_so == bien_moi_truong, (
        f"common.dynamodb.PROJECTS_TABLE={hang_so!r} nhưng bootstrap tạo bảng "
        f"{bien_moi_truong!r} — devserver import `common` trước khi đặt env"
    )


def test_cau_hinh_AI_khong_bi_khoa_truoc_khi_nap_env_file():
    """Cùng cái bẫy của test trên, nhưng với `.env` thay vì DEFAULTS.

    `common/ai_clients.py` đọc DOCAI_PROJECT / DOCAI_PROCESSOR_ID / GEMINI_MODEL
    vào HẰNG SỐ lúc import. `devserver` nạp `evaluation/.env` — import `common`
    trước khi nạp thì cả cấu hình AI khoá vào chuỗi rỗng, và triệu chứng là:
    chọn Document AI trên giao diện thì nổ "Thiếu DOCAI_PROJECT" giữa chừng
    trong khi `.env` đã điền đủ. Đã xảy ra thật.

    Bỏ qua nếu máy chưa có `.env` — không có gì để nạp thì không kiểm được gì.
    """
    import devserver.__main__ as entry

    if not entry.ENV_PATH.exists():
        pytest.skip("máy này chưa có evaluation/.env")

    backend = pathlib.Path(__file__).resolve().parents[1]
    # Gọi `load_env_file()` một lần nữa cho chắc: bản ĐÚNG đã nạp lúc import nên
    # đây là no-op, còn bản HỎNG (nạp trong `main()`) thì tới đây os.environ mới
    # có giá trị — trong khi hằng số đã khoá vào chuỗi rỗng từ lúc import.
    # Thiếu dòng này thì hai bên cùng rỗng và test xanh vô nghĩa.
    ma = (
        "import os, sys; sys.path.insert(0, '.');"
        "import devserver.__main__ as e;"
        "import common.ai_clients as ai;"
        "e.load_env_file();"
        "print(ai.DOCAI_PROJECT == os.environ.get('DOCAI_PROJECT', ''),"
        "      ai.DOCAI_PROCESSOR_ID == os.environ.get('DOCAI_PROCESSOR_ID', ''))"
    )
    ket_qua = subprocess.run(
        [sys.executable, "-c", ma],
        cwd=backend,
        capture_output=True,
        text=True,
        # Bỏ biến sẵn có để `.env` là nguồn DUY NHẤT — nếu không thì test xanh
        # nhờ môi trường của người chạy chứ không nhờ code đúng.
        env={k: v for k, v in os.environ.items() if not k.startswith("DOCAI_")},
    )

    assert ket_qua.returncode == 0, ket_qua.stderr
    assert ket_qua.stdout.split() == ["True", "True"], (
        "hằng số trong common/ai_clients.py lệch với os.environ — devserver "
        "import `common` trước khi nạp .env"
    )


def test_bootstrap_tao_tai_nguyen_dung_region_ma_client_se_di_tim(monkeypatch):
    """`evaluation/.env` đặt AWS_REGION theo region bucket Textract THẬT
    (us-east-1), còn devserver đặt AWS_DEFAULT_REGION cho moto (ap-southeast-1).

    Hai biến chỏi nhau, và moto tách hẳn dữ liệu theo region — bootstrap tạo
    bảng ở region này mà client đi tìm ở region kia là ResourceNotFoundException.
    Đo được: botocore lấy AWS_DEFAULT_REGION, nên bootstrap phải lấy đúng biến
    đó chứ không phải AWS_REGION.
    """
    import boto3

    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-southeast-1")
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    assert boto3.client("dynamodb").meta.region_name == "ap-southeast-1"


def test_client_that_khong_dung_credential_gia_cua_devserver(monkeypatch):
    """Nửa còn lại của cùng cái bẫy: không chỉ ENDPOINT, mà cả CREDENTIAL.

    `devserver/__main__.py DEFAULTS` đặt AWS_ACCESS_KEY_ID='dev' để moto có cái
    mà ký — moto không kiểm nên giá trị gì cũng được. Nhưng boto3 xét biến môi
    trường TRƯỚC ~/.aws/credentials, nên client "AWS thật" ở đây cũng vớ luôn
    cặp khoá giả đó và AWS trả 403 Forbidden.

    403 là thông báo tệ nhất có thể: nó nói "không có quyền", làm người ta đi
    sửa IAM policy, trong khi khoá gửi lên còn chẳng tồn tại.
    """
    from common import aws_real

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "dev")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "dev")
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)

    credentials = aws_real.session().get_credentials()

    # None = máy này chưa `aws configure`; chấp nhận được. Điều KHÔNG chấp nhận
    # được là lấy đúng cặp khoá giả mà devserver vừa bịa ra cho moto.
    assert credentials is None or credentials.access_key != "dev"


def test_tren_lambda_van_phai_doc_credential_tu_bien_moi_truong(monkeypatch):
    """Trên Lambda thì biến môi trường CHÍNH LÀ nguồn credential thật.

    Role của function bơm AWS_ACCESS_KEY_ID/SECRET/SESSION_TOKEN vào env. Bỏ
    provider 'env' ở đó là function mất sạch quyền — sửa dev server mà làm chết
    production.
    """
    from common import aws_real

    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "recon-ocr")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "ASIA-role-cua-lambda")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")

    assert aws_real.session().get_credentials().access_key == "ASIA-role-cua-lambda"


def test_region_theo_cau_hinh_aws_chu_khong_doan_bua(monkeypatch):
    """Textract BẮT bucket phải cùng region với job.

    Đoán bừa một region trong khi ~/.aws/config nói region khác thì bucket nằm
    một nơi, job chạy một nơi, và lỗi báo về là InvalidS3ObjectException — nhìn
    như file hỏng chứ không nói gì về region.
    """
    from types import SimpleNamespace

    from common import aws_real

    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.setattr(
        "boto3.Session", lambda *a, **k: SimpleNamespace(region_name="us-east-1")
    )

    assert aws_real.region() == "us-east-1"


def test_bien_moi_truong_van_uu_tien_hon_cau_hinh(monkeypatch):
    from types import SimpleNamespace

    from common import aws_real

    monkeypatch.setenv("AWS_REGION", "ap-southeast-1")
    monkeypatch.setattr(
        "boto3.Session", lambda *a, **k: SimpleNamespace(region_name="us-east-1")
    )

    assert aws_real.region() == "ap-southeast-1"


def test_textract_khong_tu_dung_client_rieng():
    """Chặn việc ai đó viết thẳng boto3.client('textract') trong common/textract.py.

    Client viết thẳng sẽ đọc AWS_ENDPOINT_URL và rơi vào moto — xem test trên.
    Mọi lối vào Textract phải đi qua common/aws_real.py.
    """
    import common.textract as textract_module

    nguon = pathlib.Path(textract_module.__file__).read_text(encoding="utf-8")
    assert "boto3.client" not in nguon, "phải dùng common/aws_real.py"


def test_thieu_credential_thi_thoat_chu_khong_chay_tiep(monkeypatch):
    import devserver.__main__ as entry

    for name in ("DOCAI_PROJECT", "DOCAI_OCR_PROCESSOR_ID", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit) as exc:
        entry.setup_ai("dococr")
    assert exc.value.code == 2


def test_moi_processor_deu_co_don_gia_di_kem():
    """Processor và đơn giá phải nằm chung một chỗ.

    Tách ra là chỗ đã sai một lần: ước tính chi phí lệch 20 lần vì lấy đơn giá
    Form Parser cho Enterprise Document OCR. Giờ chỗ chung đó là
    common/ocr_engines.py, và dev server dùng CHÍNH nó chứ không giữ bản sao.
    """
    import devserver.__main__ as entry
    from common import ocr_engines

    assert entry.PROCESSORS is ocr_engines.ENGINES

    for name, spec in entry.PROCESSORS.items():
        assert spec["label"] and spec["note"], name
        assert float(spec["usd_per_page"]) > 0, name
        # Engine Google định danh bằng processor id; Textract thì không có.
        if spec["cloud"] == "google":
            assert spec["processor_env"], name
        else:
            assert spec["processor_env"] is None, name

    assert float(entry.PROCESSORS["dococr"]["usd_per_page"]) == 0.0015
    assert float(entry.PROCESSORS["formparser"]["usd_per_page"]) == 0.030


def test_setup_ai_dat_OCR_ENGINE_cho_worker(monkeypatch):
    """Dev server và worker production phải chạy CÙNG một engine.

    Trước đây dev server chép processor id + đơn giá + nhãn vào ba biến môi
    trường riêng — ba chỗ có thể lệch nhau. Giờ chỉ truyền TÊN engine, còn hàm
    gọi, đơn giá và nhãn audit đều tra từ registry.
    """
    import os

    import devserver.__main__ as entry
    from common import ocr_engines

    monkeypatch.setenv("DOCAI_PROJECT", "du-an-gia-lap")
    monkeypatch.setenv("DOCAI_OCR_PROCESSOR_ID", "proc-ocr-123")
    monkeypatch.setenv("GEMINI_API_KEY", "khoa-gia-lap")

    entry.setup_ai("dococr")

    assert os.environ["OCR_ENGINE"] == "dococr"
    assert ocr_engines.resolve(os.environ["OCR_ENGINE"])["label"] == (
        "documentai-enterprise-document-ocr"
    )


def test_setup_ai_textract_khong_doi_credential_google(monkeypatch):
    """Thử engine mới không được bắt người dùng có sẵn tài khoản Google."""
    import devserver.__main__ as entry

    for name in ("DOCAI_PROJECT", "DOCAI_OCR_PROCESSOR_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "khoa-gia-lap")
    monkeypatch.setenv("TEXTRACT_S3_BUCKET", "bucket-tam")

    assert entry.setup_ai("textract")["cloud"] == "aws"


def test_setup_ai_textract_thieu_bucket_thi_thoat(monkeypatch):
    """Bẫy B: thiếu bucket thật thì Textract không đọc được file — thoát ngay,
    đừng để chạy tới lúc gọi API rồi nhận InvalidS3ObjectException khó hiểu."""
    import devserver.__main__ as entry

    monkeypatch.setenv("GEMINI_API_KEY", "khoa-gia-lap")
    monkeypatch.delenv("TEXTRACT_S3_BUCKET", raising=False)
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)

    with pytest.raises(SystemExit) as exc:
        entry.setup_ai("textract")
    assert exc.value.code == 2
