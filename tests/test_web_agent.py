"""Agent 루프, 수치 차단, API Key 저장 동작을 검증한다."""
from __future__ import annotations

import json
import os
from types import SimpleNamespace

import httpx
import httpx2
import pytest
from fastapi.testclient import TestClient
from google.genai import errors, types

from src import server, settings
from src.agent import GeminiAgent, run_agent
from src.data_pipeline import load_store
from src.interpreter import parse_interpretation
from src.report import unsupported_numbers
from src.rule_engine import narrate, parse_question
from src.tools.analysis import Analyzer

GOOD_KEY = "AIza" + "a" * 35


@pytest.fixture(scope="module")
def store():
    return load_store()


def tool(name, args, call_id):
    return types.Part(function_call=types.FunctionCall(id=call_id, name=name, args=args))


def reply(*parts, stop=types.FinishReason.STOP):
    content = types.Content(role="model", parts=list(parts))
    return types.GenerateContentResponse(candidates=[types.Candidate(content=content, finish_reason=stop)])


def tool_response(request, index=0):
    return request["contents"][-1].parts[index].function_response.response


class FakeClient:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []
        self.models = SimpleNamespace(generate_content=self._generate)

    def _generate(self, model, contents, config):
        self.requests.append({"model": model, "contents": list(contents) if isinstance(contents, list) else contents, "config": config})
        item = next(self.replies)
        if isinstance(item, Exception):
            raise item
        return item


def interpreted(**changes):
    values = {"analysis_type": "trend", "purpose": "소비 추세 확인", "region": None, "theme": None, "industry": None, "age": None,
              "gender": None, "visitor": None, "district": None, "months": None, "needs_clarification": False,
              "clarification_question": None, "missing_fields": []}
    text = json.dumps({**values, **changes}, ensure_ascii=False)
    return reply(types.Part(text=text))


def report_args(summary):
    actions = [{"badge": "제안", "title": f"제안 {i}", "desc": "분석 결과를 참고해 검토하세요."} for i in range(4)]
    return {"title": "테스트", "summary": summary, "intent": "추세", "result_ids": ["r1"], "actions": actions}


def test_agent_rejects_invented_number_then_accepts_verified_report(store):
    facts = Analyzer(store).trend({"region": "서귀포시"}).facts
    client = FakeClient([
        interpreted(region="서귀포시"),
        reply(tool("analyze_trend", {"filters": {"region": "서귀포시"}}, "t1")),
        reply(tool("verify_result", {"result_id": "r1"}, "t2")),
        reply(tool("build_report", report_args("최고 달의 비중은 **99.9%**입니다."), "t3")),
        reply(tool("build_report", report_args(f"최고 달의 비중은 **{facts['peak_share']}%**입니다."), "t4")),
    ])
    events = list(GeminiAgent(store, client=client).run("서귀포시 소비 추세"))
    assert events[-1]["type"] == "report"
    assert "99.9%" in tool_response(client.requests[4])["error"]


def test_agent_refuses_report_before_verification(store):
    client = FakeClient([
        interpreted(),
        reply(tool("analyze_trend", {}, "t1")),
        reply(tool("build_report", report_args("요약입니다."), "t2")),
        reply(tool("verify_result", {"result_id": "r1"}, "t3")),
        reply(tool("build_report", report_args("요약입니다."), "t4")),
    ])
    events = list(GeminiAgent(store, client=client).run("제주 소비 추세"))
    assert events[-1]["type"] == "report"
    assert "verify_result" in tool_response(client.requests[3])["error"]


def test_agent_clarification_stops_the_loop(store):
    fields = [{"key": "region", "label": "지역", "options": ["제주시", "서귀포시"]}]
    client = FakeClient([interpreted(), reply(tool("ask_user", {"question": "어느 지역인가요?", "fields": fields}, "t1"))])
    events = list(GeminiAgent(store, client=client).run("장사 잘 되는 곳"))
    assert events[-1]["type"] == "clarify" and len(client.requests) == 2


def test_question_is_requested_as_json_and_passed_to_the_agent(store):
    client = FakeClient([interpreted(region="제주시", months=12), reply(tool("ask_user", {"question": "확인", "fields": []}, "t1"))])
    list(GeminiAgent(store, client=client).run("제주시 최근 1년 소비 추세"))
    config = client.requests[0]["config"]
    schema = config.response_json_schema
    assert config.response_mime_type == "application/json" and schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert "제주시" in schema["properties"]["region"]["anyOf"][0]["enum"]
    assert '"region": "제주시"' in client.requests[1]["contents"][0].parts[0].text


def test_interpreter_can_ask_for_missing_conditions(store):
    client = FakeClient([interpreted(needs_clarification=True, clarification_question="어느 지역인가요?", missing_fields=["region"])])
    event = list(GeminiAgent(store, client=client).run("장사 잘 되는 곳"))[-1]
    assert event["type"] == "clarify" and [f["key"] for f in event["fields"]] == ["region"] and len(client.requests) == 1


def test_selected_answers_override_interpretation(store):
    text = interpreted(region="제주시", needs_clarification=True, missing_fields=["age"]).candidates[0].content.parts[0].text
    parsed = parse_interpretation(text, store, {"region": "전체", "age": store.values("연령대")[0]})
    assert parsed.region is None and parsed.age == store.values("연령대")[0] and parsed.needs_clarification is False


def test_values_outside_the_data_are_removed(store):
    parsed = parse_interpretation(interpreted(region="부산시", months=99).candidates[0].content.parts[0].text, store)
    assert parsed.region is None and parsed.months == 36


def test_partial_answers_keep_the_remaining_question(store):
    text = interpreted(needs_clarification=True, clarification_question="조건 선택", missing_fields=["region", "age"]).candidates[0].content.parts[0].text
    parsed = parse_interpretation(text, store, {"region": "제주시"})
    assert parsed.needs_clarification is True and parsed.missing_fields == ["age"]
    invalid = parse_interpretation(text, store, {"region": "부산시"})
    assert invalid.region is None and invalid.missing_fields == ["region", "age"]


def test_choosing_all_themes_clears_the_interpreted_industry(store):
    text = interpreted(industry=store.values("업종")[0]).candidates[0].content.parts[0].text
    parsed = parse_interpretation(text, store, {"theme": "전체"})
    assert parsed.theme is None and parsed.industry is None


def test_all_negative_growth_is_described_as_a_decline(store):
    parsed = parse_question("최근 1년 전 지역 증가율이 가장 높은 테마는?", None, store)
    result = Analyzer(store).rank("테마", metric="growth")
    result.facts.update(top_yoy=-0.8, bottom_yoy=-10.3)
    _, summary, actions = narrate(parsed, [result])
    assert "모든 테마의 소비가 전년 동기보다 감소" in summary and "증가율이 가장 높은" not in summary
    assert actions[0]["badge"] == "상대적 강세"


def test_interpreted_period_is_applied_when_the_tool_call_omits_it(store):
    client = FakeClient([interpreted(months=3), reply(tool("analyze_trend", {}, "t1")),
                         reply(tool("ask_user", {"question": "확인", "fields": []}, "t2"))])
    list(GeminiAgent(store, client=client).run("최근 3개월 소비 추세"))
    assert len(tool_response(client.requests[2])["result"]["rows"]) == 3


def test_invalid_theme_answer_keeps_the_interpreted_industry(store):
    industry = store.values("업종")[0]
    parsed = parse_interpretation(interpreted(industry=industry).candidates[0].content.parts[0].text, store, {"theme": "없는 테마"})
    assert parsed.industry == industry


def test_zero_month_question_still_produces_a_report(store):
    assert list(run_agent("제주시 최근 0개월 소비 추세", None, store))[-1]["type"] == "report"


@pytest.mark.parametrize("text", ["자유 형식 답변", '{"analysis_type": "trend"}'])
def test_malformed_interpretation_falls_back_to_rules(store, text):
    client = FakeClient([reply(types.Part(text=text))])
    events = list(run_agent("서귀포시 30대 식음료 프로모션 언제가 좋을까?", None, store, client=client))
    assert any(e["type"] == "notice" for e in events) and events[-1]["report"]["mode"] == "규칙 기반 분석"


def test_report_with_wrong_action_count_is_rejected(store):
    args = report_args("요약입니다.")
    args["actions"] = args["actions"][:3]
    client = FakeClient([
        interpreted(),
        reply(tool("analyze_trend", {}, "t1")),
        reply(tool("verify_result", {"result_id": "r1"}, "t2")),
        reply(tool("build_report", args, "t3")),
        reply(tool("build_report", report_args("요약입니다."), "t4")),
    ])
    assert list(GeminiAgent(store, client=client).run("제주 소비 추세"))[-1]["type"] == "report"
    assert "actions" in tool_response(client.requests[4])["error"]


def test_agent_failure_falls_back_to_rules(store):
    client = FakeClient([types.GenerateContentResponse(candidates=[])])
    events = list(run_agent("서귀포시 30대 식음료 프로모션 언제가 좋을까?", None, store, client=client))
    assert any(e["type"] == "notice" for e in events) and events[-1]["type"] == "report"
    assert events[-1]["report"]["mode"] == "규칙 기반 분석"


def test_every_agent_turn_must_call_a_declared_tool(store):
    client = FakeClient([interpreted(), reply(tool("ask_user", {"question": "확인", "fields": []}, "t1"))])
    list(GeminiAgent(store, client=client).run("제주 소비 추세"))
    config = client.requests[1]["config"]
    assert config.tool_config.function_calling_config.mode == types.FunctionCallingConfigMode.ANY
    names = {item.name for item in config.tools[0].function_declarations}
    assert {"list_datasets", "analyze_trend", "verify_result", "ask_user", "build_report"} <= names


def test_model_turn_is_returned_unchanged_with_its_thought_signature(store):
    signed = types.Part(function_call=types.FunctionCall(id="t1", name="list_datasets", args={}), thought_signature=b"signature")
    client = FakeClient([interpreted(), reply(signed), reply(tool("ask_user", {"question": "확인", "fields": []}, "t2"))])
    list(GeminiAgent(store, client=client).run("제주 소비 추세"))
    assert client.requests[2]["contents"][1].parts[0].thought_signature == b"signature"
    answer = client.requests[2]["contents"][2].parts[0].function_response
    assert answer.id == "t1" and answer.name == "list_datasets" and "result" in answer.response


def test_decimal_months_from_the_model_are_accepted(store):
    client = FakeClient([interpreted(), reply(tool("analyze_trend", {"months": 3.0}, "t1")),
                         reply(tool("ask_user", {"question": "확인", "fields": []}, "t2"))])
    list(GeminiAgent(store, client=client).run("최근 3개월 소비 추세"))
    assert len(tool_response(client.requests[2])["result"]["rows"]) == 3


@pytest.mark.parametrize("failure, expected", [
    (errors.ClientError(400, {"error": {"status": "INVALID_ARGUMENT", "message": "API key not valid."}}), "인증"),
    (errors.ClientError(429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "quota"}}), "무료 사용량"),
    (errors.ServerError(503, {"error": {"status": "UNAVAILABLE", "message": "busy"}}), "503"),
    (httpx2.ConnectError("offline"), "연결"),
    (httpx.ConnectError("offline"), "연결"),
    (json.JSONDecodeError("not json", "<html>", 0), "해석"),
])
def test_gemini_failures_fall_back_to_rules(store, failure, expected):
    events = list(run_agent("서귀포시 30대 식음료 프로모션 언제가 좋을까?", None, store, client=FakeClient([failure])))
    assert expected in next(e for e in events if e["type"] == "notice")["message"]
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
    assert "제주시 요일별 데이터 기준" in report["summary"]
    assert any("도민과 관광객 구분이 없어" in item for item in report["limitations"])


def test_validation_error_does_not_echo_the_key(web):
    secret = "AIza" + "x" * 400
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
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    yield TestClient(server.app, base_url="http://127.0.0.1:8501")
    os.environ.pop("GEMINI_API_KEY", None)


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
