"""30개 고정 질문의 오프라인 해석 계약. 실제 LLM 정확도와 분리합니다."""
import json
from pathlib import Path

import pytest

from src.jeju_agent.agent import InsightAgent, interpret_demo_question
from src.jeju_agent.tools import ToolRegistry

CASES = json.loads((Path(__file__).parents[1] / "evaluation/questions.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=lambda case: str(case["id"]))
def test_demo_question_contract(case):
    plan = interpret_demo_question(case["question"])
    actual = "unsupported" if plan["unsupported"] else "clarification" if plan["missing"] else plan["tool"]
    assert actual == case["expected"]
    assert plan["filters"] == case["filters"]


def test_missing_key_is_explicit(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    response = InsightAgent(ToolRegistry()).run_claude("2025년 서귀포시 소비")
    assert response.status == "error"
    assert "ANTHROPIC_API_KEY" in response.message


def test_demo_workflow_outputs_verified_report(tmp_path):
    registry = ToolRegistry(output_dir=tmp_path)
    response = InsightAgent(registry).run_demo("2025년 서귀포시 30대 음식점 소비")
    assert response.status == "complete", response
    assert response.report and "error" not in response.report
    assert [log["tool"] for log in response.logs] == ["list_datasets", "analyze_trend", "verify_result", "create_chart", "build_report"]
