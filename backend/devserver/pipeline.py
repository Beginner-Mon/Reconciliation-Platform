"""Chạy lại luồng Step Functions ở máy, KHÔNG cần AWS.

Thứ tự bước đọc TỪ CHÍNH file statemachine.asl.json, không hardcode — thêm state
vào ASL thì dev tự chạy theo, không sợ dev và cloud chạy khác nhau. Tên state
chưa có worker tương ứng sẽ báo lỗi NGAY LÚC KHỞI ĐỘNG, không âm thầm bỏ qua.

GIỚI HẠN — đây là bản mô phỏng, KHÔNG phải state machine thật:
  - không có Retry/backoff/jitter
  - không có TimeoutSeconds từng state
  - chạy tuần tự, không mô phỏng MaxConcurrency
Muốn verify hành vi thật của ASL thì dùng infra/statemachine-test/.
"""

import json
import pathlib
import threading
import time
import traceback

import workers.extract
import workers.mark_failed
import workers.ocr
import workers.reconcile
import workers.validate

ASL_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "infra"
    / "modules"
    / "aws"
    / "statemachine.asl.json"
)

STATE_TO_WORKER = {
    "Ocr": workers.ocr.lambda_handler,
    "Extract": workers.extract.lambda_handler,
    "Validate": workers.validate.lambda_handler,
    "MarkOcrFailed": workers.mark_failed.lambda_handler,
    "MarkExtractFailed": workers.mark_failed.lambda_handler,
    "MarkValidateFailed": workers.mark_failed.lambda_handler,
    "Reconcile": workers.reconcile.lambda_handler,
    "MarkRunFailed": workers.mark_failed.mark_run_failed,
}


def load_asl(path: pathlib.Path = ASL_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_map(states: dict) -> tuple[str, dict]:
    for name, state in states.items():
        if state.get("Type") == "Map":
            return name, state
    raise RuntimeError("Không tìm thấy Map state trong ASL")


def _iterator_states(map_state: dict) -> dict:
    # ItemProcessor là dạng hiện hành; Iterator là tên cũ đã deprecated.
    inner = map_state.get("ItemProcessor") or map_state.get("Iterator")
    if not inner:
        raise RuntimeError("Map state không có ItemProcessor/Iterator")
    return inner


def _walk(states: dict, start: str) -> list[str]:
    """Đi theo chuỗi Next từ `start`, chỉ lấy Task state."""
    order = []
    name = start
    seen = set()
    while name and name not in seen:
        seen.add(name)
        state = states[name]
        if state.get("Type") == "Task":
            order.append(name)
        if state.get("End"):
            break
        name = state.get("Next")
    return order


def _catch_target(state: dict) -> str | None:
    for rule in state.get("Catch") or []:
        if rule.get("Next"):
            return rule["Next"]
    return None


def _step_label(states: dict, state_name: str) -> str:
    params = states.get(state_name, {}).get("Parameters") or {}
    return params.get("step") or "ocr"


def build_plan(asl: dict | None = None) -> dict:
    """Rút kế hoạch chạy từ ASL và kiểm tra mọi Task state đều có worker."""
    asl = asl or load_asl()
    states = asl["States"]
    map_name, map_state = _find_map(states)
    inner = _iterator_states(map_state)
    inner_states = inner["States"]

    per_document = _walk(inner_states, inner["StartAt"])
    after_map = _walk(states, map_state.get("Next")) if map_state.get("Next") else []

    catches = {name: _catch_target(inner_states[name]) for name in per_document}
    steps = {name: _step_label(inner_states, catches[name]) for name in per_document}

    # Mọi Task state ở cả hai tầng đều phải có worker. Catch target bản thân nó
    # cũng là state trong hai dict này nên không cần gom riêng.
    all_tasks = [n for n, s in inner_states.items() if s.get("Type") == "Task"]
    all_tasks += [n for n, s in states.items() if s.get("Type") == "Task"]
    missing = sorted({n for n in all_tasks if n not in STATE_TO_WORKER})
    if missing:
        raise RuntimeError(
            f"ASL có Task state chưa có worker trong dev server: {', '.join(missing)}. "
            f"Thêm vào STATE_TO_WORKER trong devserver/pipeline.py."
        )

    return {
        "map_state": map_name,
        "per_document": per_document,
        "after_map": after_map,
        "catch_of": catches,
        "step_of": steps,
        "run_failed": _catch_target(map_state),
    }


def run_local(payload: dict, slow: float = 0.0, plan: dict | None = None) -> None:
    plan = plan or build_plan()
    project_id = payload["project_id"]
    run_id = payload.get("run_id")

    def pause():
        if slow:
            time.sleep(slow)

    try:
        for document in payload.get("documents", []):
            event = {
                "project_id": project_id,
                "run_id": run_id,
                "document_id": document["document_id"],
                "s3_key": document["s3_key"],
            }
            for state_name in plan["per_document"]:
                pause()
                try:
                    result = STATE_TO_WORKER[state_name](event, None)
                    if isinstance(result, dict):
                        event = result
                except Exception as exc:  # giống Catch BÊN TRONG iterator
                    catch_state = plan["catch_of"].get(state_name)
                    if not catch_state:
                        raise
                    STATE_TO_WORKER[catch_state](
                        {
                            "project_id": project_id,
                            "document_id": event["document_id"],
                            "step": plan["step_of"].get(state_name, "ocr"),
                            "error": {
                                "Error": type(exc).__name__,
                                "Cause": str(exc),
                            },
                        },
                        None,
                    )
                    break  # document này dừng, các document khác vẫn chạy tiếp

        for state_name in plan["after_map"]:
            pause()
            STATE_TO_WORKER[state_name]({"project_id": project_id, "run_id": run_id}, None)

    except Exception as exc:
        traceback.print_exc()
        run_failed = plan.get("run_failed")
        if run_failed:
            STATE_TO_WORKER[run_failed](
                {
                    "project_id": project_id,
                    "run_id": run_id,
                    "error": {"Error": type(exc).__name__, "Cause": str(exc)},
                },
                None,
            )


def install(slow: float = 0.0) -> dict:
    """Thay StartExecution bằng orchestrator cục bộ chạy trong thread nền."""
    import api.process as process_module

    plan = build_plan()

    def start_execution(name: str, payload: dict) -> str:
        thread = threading.Thread(
            target=run_local, args=(payload, slow, plan), daemon=True, name=f"run-{name}"
        )
        thread.start()
        return f"arn:aws:states:local:000000000000:execution:devserver:{name}"

    process_module.start_execution = start_execution
    return plan
