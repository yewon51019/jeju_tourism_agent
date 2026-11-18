"""질문 해석과 도구 실행을 연결합니다. 계산 자체는 tools.py가 담당합니다."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .tools import TOOL_SCHEMAS, ToolRegistry

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class AgentResponse:
    """UI가 표시하는 실행 결과. 실패와 조건 확인도 정상적인 응답 상태입니다."""

    status: str
    message: str
    logs: list[dict[str, Any]] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    report: dict[str, Any] | None = None


def interpret_demo_question(question: str) -> dict[str, Any]:
    """오프라인 데모용 제한된 해석기. LLM 성능 평가와 혼동하면 안 됩니다."""
    filters: dict[str, Any] = {}
    for region in ("제주시", "서귀포시"):
        if region in question:
            filters["region"] = region
    if "서귀포" in question:
        filters["region"] = "서귀포시"
    year = re.search(r"(20\d{2})년", question)
    if year:
        filters["year"] = int(year.group(1))
    for age in ("20대", "30대", "40대", "50대", "60대"):
        if age in question:
            filters["age"] = age
    for keyword, sector in (("음식점", "음식점"), ("식음료", "음식점"), ("식당", "음식점"), ("숙박", "숙박"), ("쇼핑", "쇼핑")):
        if keyword in question:
            filters["sector"] = sector
    if "여성" in question:
        filters["gender"] = "여성"
    elif "남성" in question:
        filters["gender"] = "남성"

    # 데이터에 없는 예측·인과효과·읍면·시간대는 유사한 결과로 대신하지 않습니다.
    unsupported = any(word in question for word in ("예측", "내년", "현금", "외국인", "시간대", "애월", "한림", "효과 보장", "개인별", "지난달", "최근", "이번", "성수기", "분기"))
    missing = [] if "year" in filters else ["연도"]
    dataset = "weekday" if any(word in question for word in ("요일", "주말", "평일")) else "monthly"
    if dataset == "weekday":
        # 요일 데이터에는 연령·성별·업종 정보가 없어 교차 질문에 답하지 않습니다.
        if any(key in filters for key in ("age", "gender", "sector", "region")):
            unsupported = True
        for district in ("서귀포시 구도심", "제주시 구도심", "상업지", "내국인 주요관광지"):
            if district in question:
                filters["district"] = district
        filters.pop("region", None)
        tool = "query_spending"
        group_by: str | list[str] = ["weekday"]
    elif any(word in question for word in ("순위", "비중", "고객층", "어느 지역", "성별", "테마")):
        tool = "rank_segments"
        group_by = "gender" if "성별" in question else "age" if any(word in question for word in ("연령", "고객층")) else "theme" if "테마" in question else "sector" if "업종" in question else "region"
    else:
        tool = "analyze_trend"
        group_by = "month"
        if "region" not in filters:
            missing.append("지역")
    if re.search(r"\d{1,2}월", question):
        unsupported = True  # 데모 해석기는 연간 분석만 지원합니다.
    return {"filters": filters, "dataset": dataset, "tool": tool, "group_by": group_by, "missing": missing, "unsupported": unsupported}


class InsightAgent:
    """실제 Claude 모드와 오프라인 데모 모드를 명시적으로 분리합니다."""

    def __init__(self, registry: ToolRegistry, on_step: Callable[[str], None] | None = None,
                 *, api_key: str | None = None, model: str | None = None):
        self.registry = registry
        self.on_step = on_step or (lambda message: None)
        self.logs: list[dict[str, Any]] = []
        # 웹 세션의 키를 명시적으로 전달합니다. 프로세스 전역 환경변수는 바꾸지 않습니다.
        self.api_key = api_key if api_key is not None else os.getenv("ANTHROPIC_API_KEY", "")
        self.model = model or os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5")

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.on_step(f"도구 실행: {name}")
        try:
            output = self.registry.execute(name, arguments)
        except (ValueError, KeyError, TypeError, OSError) as error:
            output = {"error": str(error)}
        self.logs.append({"tool": name, "input": arguments, "output": output})
        return output

    def run_demo(self, question: str, confirmed_filters: dict[str, Any] | None = None) -> AgentResponse:
        self.logs = []
        plan = interpret_demo_question(question)
        if plan["unsupported"]:
            return AgentResponse("unsupported", "이 질문은 오프라인 해석기의 지원 범위를 벗어나거나 서로 다른 데이터의 항목을 결합합니다. 예시 질문 또는 Claude 모드를 사용하세요.")
        if confirmed_filters:
            plan["filters"].update(confirmed_filters)
            plan["missing"] = [name for name in plan["missing"] if ("year" if name == "연도" else "region") not in confirmed_filters]
        if plan["missing"]:
            return AgentResponse("clarification", f"분석할 {', '.join(plan['missing'])}를 아래에서 선택해 주세요.")
        self.call_tool("list_datasets", {})
        arguments = {"filters": plan["filters"]}
        if plan["tool"] != "analyze_trend":
            arguments.update(dataset=plan["dataset"], group_by=plan["group_by"])
        result = self.call_tool(plan["tool"], arguments)
        if "error" in result:
            return AgentResponse("error", result["error"], self.logs)
        result_id = result.get("result_id")
        verification = self.call_tool("verify_result", {"result_id": result_id})
        if verification.get("passed") is not True:
            return AgentResponse("limited", "검증 기준을 충족하지 못했습니다. 조건을 임의로 넓히지 않고 경고를 표시합니다.", self.logs, [result])
        self.call_tool("create_chart", {"result_id": result_id, "chart_type": "bar"})
        report = self.call_tool("build_report", {"result_id": result_id})
        return AgentResponse("complete", "가상 데이터 데모 분석이 완료되었습니다. 실제 제주 통계가 아닙니다.", self.logs, [result], report)

    def run_claude(self, question: str, history: list[dict[str, Any]] | None = None) -> AgentResponse:
        """Tool Use 루프. 재분석은 최대 2회, API 턴은 최대 12회로 제한합니다."""
        import anthropic

        self.logs = []
        api_key = self.api_key
        if not api_key:
            return AgentResponse("error", "ANTHROPIC_API_KEY가 없습니다. 웹 화면의 API 설정에 입력하거나 오프라인 데모를 선택하세요.")
        model = self.model
        client = anthropic.Anthropic(api_key=api_key, max_retries=2, timeout=60)
        system_prompt = (ROOT / "prompts/system.md").read_text(encoding="utf-8")
        messages = list(history or []) + [{"role": "user", "content": question}]
        analysis_calls = 0
        verified_ids: set[str] = set()
        outputs: list[dict[str, Any]] = []
        final_report = None
        try:
            for _ in range(12):
                self.on_step("Claude가 질문과 도구 결과를 검토하고 있습니다.")
                response = client.messages.create(model=model, max_tokens=4096, system=system_prompt, tools=TOOL_SCHEMAS, messages=messages)
                messages.append({"role": "assistant", "content": [block.model_dump(exclude_none=True) for block in response.content]})
                tool_results = []
                text_parts = []
                for block in response.content:
                    if block.type == "text":
                        text_parts.append(block.text)
                        continue
                    if block.type != "tool_use":
                        continue
                    name, arguments = block.name, block.input
                    if name in {"query_spending", "analyze_trend", "rank_segments"}:
                        analysis_calls += 1
                    if analysis_calls > 3 and name in {"query_spending", "analyze_trend", "rank_segments"}:
                        output = {"error": "초기 분석 1회와 재분석 2회 한도에 도달했습니다. 한계를 명시하고 종료하세요."}
                        self.logs.append({"tool": name, "input": arguments, "output": output})
                    elif name in {"create_chart", "build_report"} and arguments.get("result_id") not in verified_ids:
                        output = {"error": "해당 결과는 verify_result를 통과하지 않았습니다."}
                        self.logs.append({"tool": name, "input": arguments, "output": output})
                    else:
                        output = self.call_tool(name, arguments)
                    if name == "verify_result" and output.get("passed") is True:
                        verified_ids.add(arguments["result_id"])
                    if name in {"query_spending", "analyze_trend", "rank_segments"} and "error" not in output:
                        outputs.append(output)
                    if name == "build_report" and "error" not in output:
                        final_report = output
                    tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(output, ensure_ascii=False, default=str), "is_error": "error" in output})
                if not tool_results:
                    # 모델이 만든 자유 문장을 검증된 수치 보고서로 오인하지 않도록 분리합니다.
                    message = "\n".join(text_parts)
                    if final_report:
                        return AgentResponse("complete", "검증된 코드 보고서를 생성했습니다. 수치와 근거는 아래 보고서를 확인하세요.", self.logs, outputs, final_report)
                    if outputs:
                        return AgentResponse("limited", "분석은 수행했으나 검증된 최종 보고서를 완성하지 못했습니다. 판단 로그를 확인하세요.", self.logs, outputs)
                    return AgentResponse("clarification", message or "분석할 지역·업종·기간을 구체적으로 알려 주세요.", self.logs)
                messages.append({"role": "user", "content": tool_results})
        except anthropic.APIError as error:
            # 인증 정보나 서버 응답 본문은 화면에 노출하지 않습니다.
            return AgentResponse("error", f"Claude API 호출 실패 ({type(error).__name__}). 연결·모델 접근 권한·사용 한도를 확인하세요. 오프라인 예시 데모를 별도로 실행할 수 있습니다.", self.logs)
        return AgentResponse("limited", "도구 호출 턴 제한에 도달했습니다. 요청 범위를 줄여 다시 실행하세요.", self.logs, outputs, final_report)
