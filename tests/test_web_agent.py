"""Agent 루프, 수치 차단, API Key 저장 동작을 검증한다."""
from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src import server, settings
from src.agent import ClaudeAgent, run_agent
from src.data_pipeline import load_store
from src.report import unsupported_numbers
from src.rule_engine import parse_question
from src.tools.analysis import Analyzer

GOOD_KEY = "sk-ant-api03-" + "a" * 40


@pytest.fixture(scope="module")
def store():
    return load_store()


def tool(name, args, block_id):
    return SimpleNamespace(type="tool_use", name=name, input=args, id=block_id)


def reply(*blocks, stop="tool_use"):
    return SimpleNamespace(content=list(blocks), stop_reason=stop)


class FakeClient:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return next(self.replies)


def report_args(summary):
    actions = [{"badge": "제안", "title": f"제안 {i}", "desc": "분석 결과를 참고해 검토하세요."} for i in range(4)]
    return {"title": "테스트", "summary": summary, "intent": "추세", "result_ids": ["r1"], "actions": actions}


def test_agent_rejects_invented_number_then_accepts_verified_report(store):
    facts = Analyzer(store).trend({"region": "서귀포시"}).facts
    client = FakeClient([
        reply(tool("analyze_trend", {"filters": {"region": "서귀포시"}}, "t1")),
        reply(tool("verify_result", {"result_id": "r1"}, "t2")),
        reply(tool("build_report", report_args("최고 달의 비중은 **99.9%**입니다."), "t3")),
        reply(tool("build_report", report_args(f"최고 달의 비중은 **{facts['peak_share']}%**입니다."), "t4")),
    ])
    events = list(ClaudeAgent(store, client=client).run("서귀포시 소비 추세"))
    assert events[-1]["type"] == "report"
    rejected = client.requests[3]["messages"][-1]["content"][0]
    assert rejected["is_error"] is True and "99.9%" in rejected["content"]


def test_agent_refuses_report_before_verification(store):
    client = FakeClient([
        reply(tool("analyze_trend", {}, "t1")),
        reply(tool("build_report", report_args("요약입니다."), "t2")),
        reply(tool("verify_result", {"result_id": "r1"}, "t3")),
        reply(tool("build_report", report_args("요약입니다."), "t4")),
    ])
    events = list(ClaudeAgent(store, client=client).run("제주 소비 추세"))
    assert events[-1]["type"] == "report"
    assert client.requests[2]["messages"][-1]["content"][0]["is_error"] is True


def test_agent_clarification_stops_the_loop(store):
    fields = [{"key": "region", "label": "지역", "options": ["제주시", "서귀포시"]}]
    client = FakeClient([reply(tool("ask_user", {"question": "어느 지역인가요?", "fields": fields}, "t1"))])
    events = list(ClaudeAgent(store, client=client).run("장사 잘 되는 곳"))
    assert events[-1]["type"] == "clarify" and len(client.requests) == 1


def test_agent_failure_falls_back_to_rules(store):
    client = FakeClient([reply(stop="refusal")])
    events = list(run_agent("서귀포시 30대 식음료 프로모션 언제가 좋을까?", None, store, client=client))
    assert any(e["type"] == "notice" for e in events) and events[-1]["type"] == "report"
    assert events[-1]["report"]["mode"] == "규칙 기반 분석"


def test_number_guard_handles_units(store):
    result = Analyzer(store).trend({"region": "제주시"})
    eok = round(result.facts["peak_amount"] / 1e8, 1)
    assert unsupported_numbers(f"최고 금액은 {eok}억 원입니다.", [result]) == []
    assert unsupported_numbers("최고 금액은 0.1억 원입니다.", [result]) == ["0.1억 원"]


def test_number_guard_checks_sign_and_unit(store):
    result = Analyzer(store).rank("테마", metric="growth")
    worst = result.facts["bottom_yoy"]
    assert worst < 0
    assert unsupported_numbers(f"증감률은 {worst:+.1f}%입니다.", [result]) == []
    assert unsupported_numbers(f"증감률은 +{abs(worst):.1f}%입니다.", [result]) != []
    users = f"{result.rows[0]['users']:,.0f}"
    assert unsupported_numbers(f"이용자는 {users}명입니다.", [result]) == []
    assert unsupported_numbers(f"이용은 {users}건입니다.", [result]) != []
    assert unsupported_numbers("금액은 ₩999입니다.", [result]) == ["₩999"]


def test_two_regions_are_compared_not_filtered(store):
    parsed = parse_question("제주시와 서귀포시 소비 비교해줘", None, store)
    assert "region" not in parsed.filters and parsed.dimension == "시군구" and parsed.intent == "rank"
    report = list(run_agent("제주시와 서귀포시 소비 비교해줘", None, store))[-1]["report"]
    assert {"1위 · 제주시", "2위 · 서귀포시"} <= {row["label"] for row in report["table"]}


def test_single_industry_growth_reports_its_own_change(store):
    report = list(run_agent("제주시 카페 증가율 알려줘", None, store))[-1]["report"]
    expected = Analyzer(store).trend({"region": "제주시", "industry": "카페·디저트"}).facts["yoy_total"]
    assert f"{expected:+.1f}%" in report["summary"] and "가장 낮은" not in report["summary"]


def test_short_period_does_not_claim_top_three_months(store):
    report = list(run_agent("제주시 최근 1개월 소비 추세", None, store))[-1]["report"]
    assert "상위 3개월" not in report["summary"]


def test_weekday_summary_states_its_population(store):
    report = list(run_agent("제주시 도민 주말 소비 패턴", None, store))[-1]["report"]
    assert "제주시 전체 소비 기준" in report["summary"]
    assert any("도민과 관광객 구분이 없어" in item for item in report["limitations"])


def test_validation_error_does_not_echo_the_key(web):
    secret = "sk-ant-" + "x" * 400
    response = web.post("/api/settings/api-key", json={"api_key": secret})
    assert response.status_code == 422 and secret not in response.text


def test_other_local_ports_cannot_use_the_api(web):
    headers = {"Origin": "http://127.0.0.1:9000"}
    assert web.post("/api/settings/api-key", json={"api_key": GOOD_KEY}, headers=headers).status_code == 403
    assert web.post("/api/analyze", json={"question": "제주시 소비 추세"}, headers=headers).status_code == 403


def test_rank_dimension_skips_fixed_filter(store):
    assert parse_question("제주시 20대 여성 카페 순위 알려줘", None, store).dimension is None
    events = list(run_agent("제주시 20대 여성 관광객의 카페·디저트 소비 추세는 어때?", None, store))
    shares = [row["note"] for row in events[-1]["report"]["table"]]
    assert "전체의 100.0%" not in shares


@pytest.fixture
def web(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(settings, "check_key", lambda key, model: (True, "API Key를 확인하고 저장했습니다."))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    yield TestClient(server.app, base_url="http://127.0.0.1:8501")
    os.environ.pop("ANTHROPIC_API_KEY", None)


def test_key_is_saved_and_never_returned(web):
    response = web.post("/api/settings/api-key", json={"api_key": GOOD_KEY})
    assert response.status_code == 200 and GOOD_KEY not in response.text
    assert GOOD_KEY in settings.ENV_PATH.read_text(encoding="utf-8")
    status = web.get("/api/status")
    assert status.json()["llm"] is True and GOOD_KEY not in status.text


def test_key_can_be_deleted(web):
    web.post("/api/settings/api-key", json={"api_key": GOOD_KEY})
    assert web.delete("/api/settings/api-key").status_code == 200
    assert GOOD_KEY not in settings.ENV_PATH.read_text(encoding="utf-8")
    assert web.get("/api/status").json()["llm"] is False


def test_malformed_key_is_rejected_without_saving(web):
    response = web.post("/api/settings/api-key", json={"api_key": "wrong\nINJECTED=1"})
    assert response.status_code == 400 and not settings.ENV_PATH.exists()


@pytest.mark.parametrize("headers", [{"Origin": "https://evil.example"}, {"Host": "evil.example"}])
def test_other_sites_cannot_change_the_key(web, headers):
    response = web.post("/api/settings/api-key", json={"api_key": GOOD_KEY}, headers=headers)
    assert response.status_code == 403 and not settings.ENV_PATH.exists()


def test_analyze_streams_a_report(web):
    response = web.post("/api/analyze", json={"question": "최근 1년 제주 전 지역 소비 증가율 1위 테마는?"})
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]["type"] == "report" and events[-1]["report"]["verification"]["total"] > 0
