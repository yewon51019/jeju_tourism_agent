"""Claude에 공개하는 도구 정의와 실행기."""
from __future__ import annotations

from typing import Any

from ..data_pipeline import DataStore
from .analysis import MIN_USERS, AnalysisError, Analyzer

_FILTERS = {
    "type": "object",
    "description": "분석 조건. 지정하지 않은 항목은 전체로 분석한다. 값은 list_datasets의 값을 그대로 쓴다.",
    "properties": {
        "region": {"type": "string", "description": "시군구"},
        "theme": {"type": "string", "description": "테마"},
        "industry": {"type": "string", "description": "업종"},
        "age": {"type": "string", "description": "연령대"},
        "gender": {"type": "string", "description": "성별"},
        "visitor": {"type": "string", "description": "관광객구분. 생략하면 관광객"},
    },
    "additionalProperties": False,
}
_MONTHS = {"type": "integer", "description": "최근 몇 개월을 분석할지 지정한다. 기본값은 12", "minimum": 1, "maximum": 36}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_datasets",
        "description": "사용 가능한 데이터, 조건 값, 데이터 기간을 조회한다. 분석을 시작할 때 먼저 호출한다.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "analyze_trend",
        "description": "조건별 월간 이용금액, 이용자수, 1인당 금액, 전년 동월 대비 증감률을 계산한다.",
        "input_schema": {"type": "object", "properties": {"filters": _FILTERS, "months": _MONTHS},
                         "additionalProperties": False},
    },
    {
        "name": "rank_segments",
        "description": "시군구, 테마, 업종, 연령대, 성별의 이용금액 또는 전년 대비 증가율 순위를 계산한다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dimension": {"type": "string", "enum": ["시군구", "테마", "업종", "연령대", "성별"]},
                "metric": {"type": "string", "enum": ["amount", "growth"]},
                "filters": _FILTERS, "months": _MONTHS,
            },
            "required": ["dimension"], "additionalProperties": False,
        },
    },
    {
        "name": "weekday_pattern",
        "description": "지구 또는 시군구의 요일별 이용금액 비중을 계산한다. 업종과 고객층 구분은 제공되지 않는다.",
        "input_schema": {
            "type": "object",
            "properties": {"district": {"type": "string", "description": "지구명"},
                           "region": {"type": "string", "description": "시군구"}, "months": _MONTHS},
            "additionalProperties": False,
        },
    },
    {
        "name": "verify_result",
        "description": "분석 결과를 원본 행에서 다시 합산해 대조하고 조건 일치, 비중 합계, 표본 크기를 점검한다.",
        "input_schema": {"type": "object", "properties": {"result_id": {"type": "string"}},
                         "required": ["result_id"], "additionalProperties": False},
    },
    {
        "name": "ask_user",
        "description": "조건이 모호할 때 사용자에게 선택지를 제시한다. 호출하면 사용자의 답을 받을 때까지 분석을 멈춘다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "fields": {
                    "type": "array", "minItems": 1, "maxItems": 3,
                    "items": {
                        "type": "object",
                        "properties": {"key": {"type": "string", "enum": ["region", "theme", "age"]},
                                       "label": {"type": "string"},
                                       "options": {"type": "array", "items": {"type": "string"}, "minItems": 2}},
                        "required": ["key", "label", "options"], "additionalProperties": False,
                    },
                },
            },
            "required": ["question", "fields"], "additionalProperties": False,
        },
    },
    {
        "name": "build_report",
        "description": "검증을 통과한 결과로 보고서를 제출한다. 도구 결과에 없는 수치가 있으면 거부된다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "summary": {"type": "string", "description": "결론 중심 요약. 핵심 표현은 **굵게** 표시"},
                "intent": {"type": "string", "description": "해석한 분석 목적"},
                "result_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "actions": {
                    "type": "array", "minItems": 4, "maxItems": 4,
                    "items": {
                        "type": "object",
                        "properties": {"badge": {"type": "string"}, "title": {"type": "string"},
                                       "desc": {"type": "string"}},
                        "required": ["badge", "title", "desc"], "additionalProperties": False,
                    },
                },
            },
            "required": ["title", "summary", "intent", "result_ids", "actions"], "additionalProperties": False,
        },
    },
]


def describe_store(store: DataStore) -> dict[str, Any]:
    return {
        "source": store.source,
        "is_sample": store.is_sample,
        "period": store.period,
        "datasets": {
            "monthly": {"grain": "월·시군구·테마·업종·연령대·성별·관광객구분",
                        "values": {column: store.values(column) for column in
                                   ("시군구", "테마", "업종", "연령대", "성별", "관광객구분")}},
            "weekday": {"grain": "일·지구", "values": {"지구": store.values("지구")}},
        },
        "min_users_for_reliable_result": MIN_USERS,
    }


class ToolBox:
    """분석 도구를 실행하고 호출 이력을 판단 로그로 남긴다."""

    def __init__(self, store: DataStore) -> None:
        self.store = store
        self.analyzer = Analyzer(store)
        self.calls: list[str] = []

    def _record(self, name: str, args: dict[str, Any]) -> None:
        shown = ", ".join(f"{k}={v!r}" for k, v in args.items() if v not in (None, {}, ""))
        self.calls.append(f"{name}({shown})")

    def run(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        self._record(name, args)
        if name == "list_datasets":
            return describe_store(self.store)
        if name == "analyze_trend":
            return self.analyzer.trend(args.get("filters"), args.get("months", 12)).brief()
        if name == "rank_segments":
            return self.analyzer.rank(args["dimension"], args.get("filters"), args.get("metric", "amount"),
                                      args.get("months", 12)).brief()
        if name == "weekday_pattern":
            return self.analyzer.weekday(args.get("district"), args.get("region"), args.get("months", 12)).brief()
        if name == "verify_result":
            result = self.analyzer.verify(args["result_id"])
            return {"result_id": result.id, "verified": result.verified, "checks": result.checks}
        raise AnalysisError(f"알 수 없는 도구입니다: {name}")
