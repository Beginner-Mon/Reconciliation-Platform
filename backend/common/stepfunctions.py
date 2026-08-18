import json
import os

import boto3
from botocore.exceptions import ClientError

STATE_MACHINE_ARN = os.environ.get("STATE_MACHINE_ARN", "")

_sfn = None


def get_sfn():
    global _sfn
    if _sfn is None:
        if os.environ.get("AWS_ENDPOINT_URL"):
            _sfn = boto3.client("stepfunctions", endpoint_url=os.environ["AWS_ENDPOINT_URL"])
        else:
            _sfn = boto3.client("stepfunctions")
    return _sfn


def start_execution(name: str, payload: dict) -> str:
    if not STATE_MACHINE_ARN:
        raise RuntimeError("Thiếu STATE_MACHINE_ARN")
    try:
        response = get_sfn().start_execution(
            stateMachineArn=STATE_MACHINE_ARN,
            name=name,
            input=json.dumps(payload, ensure_ascii=False, default=str),
        )
        return response["executionArn"]
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ExecutionAlreadyExists":
            prefix = STATE_MACHINE_ARN.replace(":stateMachine:", ":execution:")
            return f"{prefix}:{name}"
        raise
