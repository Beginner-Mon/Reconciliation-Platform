import json


def audit_events(capsys, action=None):
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
    events = audit_events(capsys, "AI_CALL")
    assert len(events) == 1
    event = events[0]
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
    events = audit_events(capsys, "AI_CALL")
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
    assert audit_events(capsys, "AI_CALL")[0]["AiCostUsd"] == 0.001423
