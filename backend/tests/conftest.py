import os

os.environ.setdefault("AWS_DEFAULT_REGION", "ap-southeast-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ["PROJECTS_TABLE"] = "test-projects"
os.environ["DOCUMENTS_TABLE"] = "test-documents"
os.environ["RUNS_TABLE"] = "test-runs"
os.environ["RECONCILIATIONS_TABLE"] = "test-reconciliations"
os.environ["AUDIT_LOG_TABLE"] = "test-audit-log"
os.environ["DOCUMENTS_BUCKET"] = "test-documents-bucket"
os.environ["STATE_MACHINE_ARN"] = (
    "arn:aws:states:ap-southeast-1:123456789012:stateMachine:test-sm"
)

import boto3  # noqa: E402
import pytest  # noqa: E402
from moto import mock_aws  # noqa: E402

# Định nghĩa bảng/bucket dùng chung với dev server — một nguồn duy nhất.
from devserver.bootstrap import create_bucket, create_tables  # noqa: E402

REGION = os.environ["AWS_DEFAULT_REGION"]


@pytest.fixture
def aws():
    import common.dynamodb as dynamodb_module
    import common.s3 as s3_module
    import common.stepfunctions as sfn_module

    with mock_aws():
        dynamodb_module._dynamodb = None
        s3_module._s3 = None
        sfn_module._sfn = None

        create_bucket(boto3.client("s3", region_name=REGION), REGION)
        create_tables(boto3.resource("dynamodb", region_name=REGION))
        yield

        dynamodb_module._dynamodb = None
        s3_module._s3 = None
        sfn_module._sfn = None


@pytest.fixture
def started_executions(monkeypatch):
    calls = []

    def fake_start_execution(name, payload):
        calls.append({"name": name, "payload": payload})
        return f"arn:aws:states:{REGION}:123456789012:execution:test-sm:{name}"

    import api.process as process_module

    monkeypatch.setattr(process_module, "start_execution", fake_start_execution)
    return calls


@pytest.fixture(autouse=True)
def doi_chieu_tai_cho(monkeypatch):
    """Đối chiếu chạy TẠI CHỖ trong test, thay vì gọi Lambda thật.

    Production gọi `recon-reconcile-dev` để cả hệ thống chỉ có MỘT chỗ chạy đối
    chiếu. moto không chạy được code của mình trong Lambda giả, nên test thay
    lời gọi đó bằng chính hàm mà Lambda kia sẽ chạy.

    Vá theo TÊN ĐÃ BIND trong từng module gọi (`api.reconcile`, `api.process`),
    không vá `common.reconcile_client` — vì các module đó dùng
    `from ... import invoke_reconcile`, mỗi module giữ một tham chiếu riêng.
    Cùng cách `started_executions` vá `api.process.start_execution`.

    `autouse` vì gần như test API nào cũng chạm tới đối chiếu; để tự khai thì
    quên một chỗ là lỗi khó hiểu chứ không phải lỗi rõ ràng.
    """
    from workers.reconcile import run_reconciliation

    for ten in ("api.reconcile", "api.process"):
        module = __import__(ten, fromlist=["invoke_reconcile"])
        if hasattr(module, "invoke_reconcile"):
            monkeypatch.setattr(module, "invoke_reconcile", run_reconciliation)
