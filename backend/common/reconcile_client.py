"""Gọi Lambda đối chiếu — MỘT chỗ chạy đối chiếu trong cả hệ thống.

Trước file này, `run_reconciliation()` chạy ở BA Lambda khác nhau:
`recon-reconcile-dev` (Step Functions gọi), `api-review` (`POST /reconcile` và
`PATCH` sửa tay), `api-process` (nhánh không còn gì để xử lý). Cùng một logic,
log rải ở ba log group, ba role phải mang quyền ghi của đối chiếu, và `api/`
buộc phải kéo `workers/` vào gói Lambda.

Giờ mọi đường đều về `recon-reconcile-dev`. `PATCH` thì THÔI đối chiếu hẳn — sửa
tay là thao tác review, không phải thao tác đối chiếu; kết quả cũ được đánh dấu
`is_stale` và người dùng bấm "Đối chiếu lại".

`RequestResponse` chứ không phải `Event`: `/reconcile` và nhánh early-return của
`/process` đều trả kết quả ngay trong HTTP response, hợp đồng đó giữ nguyên.
"""

import json
import os

import boto3

RECONCILE_LAMBDA_ARN = os.environ.get("RECONCILE_LAMBDA_ARN", "")

_lambda = None


def get_lambda():
    global _lambda
    if _lambda is None:
        if os.environ.get("AWS_ENDPOINT_URL"):
            _lambda = boto3.client("lambda", endpoint_url=os.environ["AWS_ENDPOINT_URL"])
        else:
            _lambda = boto3.client("lambda")
    return _lambda


def invoke_reconcile(project_id: str) -> dict:
    """Chạy đối chiếu cho project, trả về bản ghi reconciliation.

    Payload khớp `workers/reconcile.py lambda_handler` — cùng hình dạng mà Step
    Functions gửi, để một handler phục vụ cả hai đường gọi.
    """
    if not RECONCILE_LAMBDA_ARN:
        raise RuntimeError("Thiếu RECONCILE_LAMBDA_ARN")

    response = get_lambda().invoke(
        FunctionName=RECONCILE_LAMBDA_ARN,
        InvocationType="RequestResponse",
        Payload=json.dumps({"project_id": project_id}, ensure_ascii=False, default=str),
    )

    # Lambda trả 200 kể cả khi hàm bên trong ném lỗi — phải soi FunctionError,
    # nếu không lỗi đối chiếu biến thành "thành công" với payload là traceback.
    if response.get("FunctionError"):
        chi_tiet = response["Payload"].read().decode("utf-8", "replace")
        raise RuntimeError(f"Lambda đối chiếu lỗi: {chi_tiet[:500]}")

    return json.loads(response["Payload"].read() or b"{}")
