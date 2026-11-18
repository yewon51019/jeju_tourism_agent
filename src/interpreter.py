"""사용자 질문을 Gemini가 돌려줄 JSON 형식으로 정의하고, 받은 결과를 검증한다."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .data_pipeline import DataStore

ANALYSIS_TYPES = ["timing", "trend", "growth", "rank", "weekday"]
CLARIFY_KEYS = ["region", "theme", "age"]
# 조건 이름과 데이터 컬럼의 대응표. 허용값은 실행 중인 데이터에서 읽는다.
CONDITION_COLUMNS = {"region": "시군구", "theme": "테마", "industry": "업종", "age": "연령대",
                     "gender": "성별", "visitor": "관광객구분", "district": "지구"}


class Interpretation(BaseModel):
    """Gemini가 질문을 해석해 돌려주는 결과."""

    model_config = ConfigDict(extra="forbid")

    analysis_type: Literal["timing", "trend", "growth", "rank", "weekday"]
    purpose: str = Field(min_length=1)
    region: str | None
    theme: str | None
    industry: str | None
    age: str | None
    gender: str | None
    visitor: str | None
    district: str | None
    months: int | None
    needs_clarification: bool
    clarification_question: str | None
    missing_fields: list[Literal["region", "theme", "age"]]


class ReportAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    badge: str = Field(min_length=1)
    title: str = Field(min_length=1)
    desc: str = Field(min_length=1)


class ReportDraft(BaseModel):
    """Gemini가 build_report 도구로 제출하는 보고서 형식."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    result_ids: list[str] = Field(min_length=1)
    actions: list[ReportAction] = Field(min_length=4, max_length=4)


def _nullable(values: list[str]) -> dict[str, Any]:
    return {"anyOf": [{"type": "string", "enum": values}, {"type": "null"}]}


def interpretation_schema(store: DataStore) -> dict[str, Any]:
    """Gemini 응답을 제한할 JSON Schema를 현재 데이터의 값으로 만든다."""
    properties: dict[str, Any] = {
        "analysis_type": {"type": "string", "enum": ANALYSIS_TYPES,
                          "description": "timing=시기 추천, trend=추세, growth=증가율, rank=순위·비교, weekday=요일 패턴"},
        "purpose": {"type": "string", "description": "사용자가 알고 싶은 내용을 한 문장으로 정리"},
        **{name: _nullable(store.values(column)) for name, column in CONDITION_COLUMNS.items()},
        "months": {"anyOf": [{"type": "integer"}, {"type": "null"}], "description": "분석할 최근 개월 수(1~36). 언급이 없으면 null"},
        "needs_clarification": {"type": "boolean"},
        "clarification_question": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "missing_fields": {"type": "array", "items": {"type": "string", "enum": CLARIFY_KEYS}},
    }
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def parse_interpretation(text: str, store: DataStore, answers: dict[str, str] | None = None) -> Interpretation:
    """형식을 검증하고, 데이터에 없는 값을 제거한 뒤 사용자의 선택을 반영한다."""
    result = Interpretation.model_validate_json(text)
    updates: dict[str, Any] = {name: None for name, column in CONDITION_COLUMNS.items()
                               if getattr(result, name) not in (None, *store.values(column))}
    if result.months is not None:
        updates["months"] = min(max(result.months, 1), 36)
    answered = set()
    for key, value in (answers or {}).items():
        if key not in CLARIFY_KEYS or not value:
            continue
        chosen = None if value == "전체" else value
        if key == "theme" and chosen in store.values("업종") and chosen not in store.values("테마"):
            updates.update(theme=None, industry=chosen)
            answered.add(key)
        elif chosen is None or chosen in store.values(CONDITION_COLUMNS[key]):
            updates[key] = chosen
            if key == "theme":  # 테마를 다시 고르면 이전에 해석한 업종 조건은 적용하지 않는다.
                updates["industry"] = None
            answered.add(key)
    if answered:
        remaining = [key for key in result.missing_fields if key not in answered]
        updates.update(needs_clarification=bool(remaining), missing_fields=remaining)
        if not remaining:
            updates["clarification_question"] = None
    return result.model_copy(update=updates)
