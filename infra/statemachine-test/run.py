"""Kiểm thử luồng Step Functions bằng Step Functions Local + Lambda mock.

Xác minh 3 tính chất quan trọng nhất, thứ không test được bằng pytest:
  1. Luồng thành công đi hết Ocr -> Extract -> Validate -> Reconcile.
  2. 1 document lỗi KHÔNG giết cả run: Map vẫn thoát bình thường và
     Reconcile vẫn chạy (nhờ Catch nằm BÊN TRONG iterator).
  3. Lỗi ở Reconcile thì MarkRunFailed phải chạy — đây là state gọi
     release_processing_run, thiếu nó project kẹt vĩnh viễn.

Chạy: xem README.md cùng thư mục.
"""

import json
import os
import pathlib
import re
import subprocess
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = pathlib.Path(__file__).parent
ASL = HERE.parent / "modules" / "aws" / "statemachine.asl.json"
ENDPOINT = ["--endpoint-url", "http://localhost:8083", "--region", "us-east-1"]
ROLE = "arn:aws:iam::123456789012:role/DummyRole"
NAME = "ProcessSM"
FAKE_LAMBDA = "arn:aws:lambda:us-east-1:123456789012:function:fake-{}"

EXECUTION_INPUT = json.dumps(
    {
        "project_id": "prj-1",
        "run_id": "run-1",
        "documents": [
            {"document_id": "doc-a", "s3_key": "projects/prj-1/uploads/doc-a.pdf"}
        ],
    }
)

EXPECTED = {
    "ThanhCong": {
        "status": "SUCCEEDED",
        "states": ["Ocr", "Extract", "Validate", "Reconcile"],
        "absent": ["MarkOcrFailed", "MarkRunFailed"],
    },
    "DocLoiOcr": {
        "status": "SUCCEEDED",
        "states": ["Ocr", "MarkOcrFailed", "Reconcile"],
        "absent": ["MarkRunFailed"],
    },
    "ReconcileLoi": {
        "status": "FAILED",
        "states": ["Ocr", "Extract", "Validate", "Reconcile", "MarkRunFailed"],
        "absent": ["MarkOcrFailed"],
    },
}


def render_local_definition() -> str:
    """Đổi ItemProcessor -> Iterator cho bản chạy local.

    Step Functions Local 2.0.0 chỉ hiểu key `Iterator` (đã deprecated trên AWS
    thật). File gốc GIỮ NGUYÊN `ItemProcessor` vì đó mới là dạng đúng hiện nay;
    hai key có cùng ngữ nghĩa về nhánh Catch/Retry nên phép đổi này không làm
    sai thứ đang được kiểm thử.
    """
    raw = ASL.read_text(encoding="utf-8")
    definition = json.loads(
        re.sub(r"\$\{(\w+)\}", lambda m: FAKE_LAMBDA.format(m.group(1)), raw)
    )
    map_state = definition["States"]["ProcessDocuments"]
    iterator = map_state.pop("ItemProcessor")
    iterator.pop("ProcessorConfig", None)
    map_state["Iterator"] = iterator
    return json.dumps(definition)


def aws(*args: str) -> subprocess.CompletedProcess:
    # ASL có Cause tiếng Việt; console Windows mặc định cp1252 sẽ làm AWS CLI
    # chết lúc IN kết quả (không phải lúc gọi API).
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        ["aws", "stepfunctions", *args, *ENDPOINT],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )


def entered_states(execution_arn: str) -> list[str]:
    # Dùng --query để chỉ lấy tên state, tránh kéo cả Cause tiếng Việt ra stdout.
    result = aws(
        "get-execution-history",
        "--execution-arn", execution_arn,
        "--query", "events[?type=='TaskStateEntered'].stateEnteredEventDetails.name",
    )
    result.check_returncode()
    return json.loads(result.stdout)


def main() -> int:
    create = aws(
        "create-state-machine",
        "--name", NAME,
        "--role-arn", ROLE,
        "--definition", render_local_definition(),
    )
    if create.returncode == 0:
        state_machine_arn = json.loads(create.stdout)["stateMachineArn"]
    elif "StateMachineAlreadyExists" in create.stderr:
        # Tên phải cố định để khớp MockConfigFile.json, nên dùng lại bản đã có.
        state_machine_arn = f"arn:aws:states:us-east-1:123456789012:stateMachine:{NAME}"
        aws("update-state-machine", "--state-machine-arn", state_machine_arn,
            "--definition", render_local_definition())
    else:
        print("Không tạo được state machine. Step Functions Local đã chạy chưa?")
        print(create.stderr.strip())
        return 2

    failures = []
    for case, expected in EXPECTED.items():
        start = aws(
            "start-execution",
            "--state-machine-arn", f"{state_machine_arn}#{case}",
            "--name", f"e-{case}-{int(time.time())}",
            "--input", EXECUTION_INPUT,
        )
        if start.returncode != 0:
            failures.append(f"{case}: start-execution lỗi — {start.stderr.strip()[-200:]}")
            continue
        execution_arn = json.loads(start.stdout)["executionArn"]

        status = "RUNNING"
        for _ in range(30):
            time.sleep(1)
            described = aws("describe-execution", "--execution-arn", execution_arn)
            described.check_returncode()
            status = json.loads(described.stdout)["status"]
            if status != "RUNNING":
                break

        states = entered_states(execution_arn)
        problems = []
        if status != expected["status"]:
            problems.append(f"status={status}, mong đợi {expected['status']}")
        missing = [s for s in expected["states"] if s not in states]
        if missing:
            problems.append(f"thiếu state {missing}")
        unexpected = [s for s in expected["absent"] if s in states]
        if unexpected:
            problems.append(f"state không được phép chạy {unexpected}")

        mark = "FAIL" if problems else "OK  "
        print(f"{mark} {case:14s} {status:10s} {' -> '.join(states)}")
        if problems:
            failures.append(f"{case}: {'; '.join(problems)}")

    if failures:
        print("\nFAILED:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("\nTất cả test case đúng như thiết kế.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
