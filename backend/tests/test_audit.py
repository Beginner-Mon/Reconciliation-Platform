import json


def log_events(capsys, action=None):
    """Mọi dòng JSON trên stdout, kể cả dòng không mang nhãn audit (AI_CALL)."""
    events = []
    for line in capsys.readouterr().out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if action is None or event.get("action") == action:
            events.append(event)
    return events


def audit_events(capsys, action=None):
    # AI_CALL không mang nhãn audit: lọc nó ở đây luôn ra [] và test "không gọi AI"
    # sẽ xanh dù AI có bị gọi. Dùng log_events.
    assert action != "AI_CALL", "AI_CALL không phải dòng audit — dùng log_events"
    events = []
    for line in capsys.readouterr().out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("audit") and (action is None or event["action"] == action):
            events.append(event)
    return events


def test_moi_su_kien_la_mot_dong_json(capsys):
    from common.audit import log_review

    log_review(
        "doc-1",
        "REVIEW_EDIT",
        {"fields": ["vendor"], "note": "dòng1\ndòng2"},
        actor="tri",
        source="api",
        project_id="prj-1",
    )
    events = audit_events(capsys, "REVIEW_EDIT")
    assert len(events) == 1
    assert events[0]["entity_id"] == "doc-1"


def test_co_truong_top_level(capsys):
    from common.audit import log_review

    log_review(
        "doc-1",
        "REVIEW_EDIT",
        {"fields": []},
        actor="tri",
        source="api",
        project_id="prj-1",
    )
    events = audit_events(capsys, "REVIEW_EDIT")
    assert len(events) == 1
    event = events[0]
    for truong in ("audit", "action", "actor", "source", "project_id", "entity_id", "timestamp"):
        assert truong in event, f"thiếu {truong}"
    assert event["audit"] == 1
    assert event["actor"] == "tri"
    assert event["source"] == "api"
    assert event["project_id"] == "prj-1"


def test_tieng_viet_khong_bi_escape(capsys):
    from common.audit import log_review

    log_review(
        "doc-1",
        "REVIEW_EDIT",
        {"note": "xử lý ỗ"},
        actor="tri",
        source="api",
        project_id="prj-1",
    )
    out = capsys.readouterr().out
    assert "xử lý ỗ" in out
    assert "\\u" not in out


def test_khong_ghi_dynamodb_nua():
    import pathlib

    nguon = (pathlib.Path(__file__).resolve().parents[1] / "common" / "audit.py").read_text(
        encoding="utf-8"
    )
    assert "common.dynamodb" not in nguon
    assert "put_item" not in nguon
    assert "AUDIT_LOG_TABLE" not in nguon


def test_ai_call_co_emf_va_metric_o_root(capsys):
    from common.audit import log_ai_call

    log_ai_call(
        "doc-1",
        model="gemini-2.5-flash",
        started_at_ms=1,
        status="ok",
        estimated_cost_usd=0.0041,
        latency_ms=4210,
        project_id="prj-1",
    )
    events = log_events(capsys, "AI_CALL")
    assert len(events) == 1
    event = events[0]
    assert "audit" not in event, "AI_CALL là dòng metric, không phải thao tác của người"
    assert "_aws" in event
    assert event["AiCostUsd"] == 0.0041
    assert event["AiLatencyMs"] == 4210
    assert event["AiRateLimited"] == 0
    assert isinstance(event["_aws"]["Timestamp"], int)


def test_ai_call_rate_limited_bat_1(capsys):
    from common.audit import log_ai_call

    log_ai_call(
        "doc-1",
        model="gemini-2.5-flash",
        started_at_ms=1,
        status="rate_limited",
        project_id="prj-1",
    )
    events = log_events(capsys, "AI_CALL")
    assert events[0]["AiRateLimited"] == 1


def test_dong_audit_duoc_flush_ngay(monkeypatch):
    """Chạy devserver với stdout ghi ra file: KHÔNG dòng audit nào hiện ra cho tới
    khi bật PYTHONUNBUFFERED — Python đệm stdout theo khối khi không phải terminal.
    Lambda bị timeout giữa chừng thì phần còn trong bộ đệm mất luôn."""
    import builtins

    goi = []
    print_that = builtins.print

    def ghi_lai(*args, **kwargs):
        goi.append(kwargs)
        print_that(*args, **kwargs)

    monkeypatch.setattr(builtins, "print", ghi_lai)
    from common.audit import log_review

    log_review("doc-1", "REVIEW_EDIT", {}, actor="tri", project_id="prj-1")

    assert goi and goi[-1].get("flush") is True


def test_ai_cost_lam_tron(capsys):
    """Cộng dồn float cho ra 0.0014230999999999998 — làm bẩn metric và dashboard."""
    from common.audit import log_ai_call

    log_ai_call(
        "doc-1",
        model="gemini-2.5-flash",
        started_at_ms=1,
        status="ok",
        estimated_cost_usd=0.0014230999999999998,
        project_id="prj-1",
    )
    assert log_events(capsys, "AI_CALL")[0]["AiCostUsd"] == 0.001423


def test_khong_con_ghi_vet_tung_buoc_cua_may():
    """Vết từng bước (PIPELINE_STEP) trùng với lịch sử execution của Step Functions
    Standard (tên execution = run_id), không có actor, và làm bảng audit rối: một
    người, một lượt mà 9/11 dòng là của máy."""
    import pathlib

    import common.audit as audit

    assert not hasattr(audit, "log_pipeline_step")
    backend = pathlib.Path(__file__).resolve().parents[1]
    con = [
        str(p.relative_to(backend))
        for thu_muc in ("api", "common", "core", "workers", "devserver")
        for p in (backend / thu_muc).rglob("*.py")
        if "PIPELINE_STEP" in p.read_text(encoding="utf-8")
    ]
    assert con == []


def test_buoc_cua_worker_khong_in_dong_nao(aws, capsys):
    from common.dynamodb import DOCUMENTS_TABLE, put_item
    from workers.steps import begin_step, fail_step, finish_step

    put_item(DOCUMENTS_TABLE, {"document_id": "doc-1", "project_id": "prj-1", "status": "PENDING"})
    capsys.readouterr()

    begin_step("doc-1", "ocr")
    finish_step("doc-1", "ocr", ocr_s3_key="k")
    fail_step("doc-1", "extract", "Gemini sập")

    assert log_events(capsys) == []
