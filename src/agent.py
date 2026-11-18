"""Gemini Function Calling 기반 Agent 루프."""
from __future__ import annotations

import json
import os
from typing import Any, Iterator

from google.genai import errors, types
from pydantic import ValidationError

from .data_pipeline import DataStore
from .events import clarify, error, notice, report, step
from .interpreter import Interpretation, ReportDraft, interpretation_schema, parse_interpretation
from .prompts import INTERPRET_PROMPT, SYSTEM_PROMPT
from .report import build_payload, unsupported_numbers
from .rule_engine import clarification_fields, run_rules
from .settings import CONNECTION_ERRORS, DEFAULT_MODEL, KEY_NAME, MODEL_NAME, create_client
from .tools.analysis import AnalysisError
from .tools.registry import TOOLS, ToolBox

MAX_TURNS = 14
ANALYSIS_TOOLS = {"analyze_trend", "rank_segments", "weekday_pattern"}
# 함수 호출 형식이 깨진 응답은 한 번 더 요청하면 복구될 수 있다.
RETRYABLE_FINISH = {types.FinishReason.MALFORMED_FUNCTION_CALL, types.FinishReason.UNEXPECTED_TOOL_CALL}


class AgentError(RuntimeError):
    """Agent가 정상적으로 보고서를 완성하지 못했을 때 발생한다."""


def _reject_report(args: dict[str, Any], box: ToolBox) -> str | None:
    """보고서를 거부할 이유를 돌려준다. 문제가 없으면 None을 돌려준다."""
    try:
        ReportDraft.model_validate(args)
    except ValidationError as exc:
        fields = ", ".join(sorted({str(item["loc"][0]) for item in exc.errors() if item["loc"]}))
        return f"보고서 형식이 올바르지 않습니다: {fields}. 도구 정의에 맞게 다시 제출해 주세요."
    try:
        results = [box.analyzer.get(i) for i in args["result_ids"]]
    except AnalysisError as exc:
        return str(exc)
    unverified = [r.id for r in results if not r.verified]
    if unverified:
        return f"검증을 통과하지 않은 결과입니다: {', '.join(unverified)}. verify_result를 먼저 실행해 주세요."
    text = " ".join([args["title"], args["summary"], args["intent"],
                     *[f"{a['badge']} {a['title']} {a['desc']}" for a in args["actions"]]])
    invalid = unsupported_numbers(text, results)
    if invalid:
        return f"분석 결과에 없는 수치입니다: {', '.join(invalid)}. 도구 결과의 값으로 고쳐 다시 제출해 주세요."
    return None


def _model_content(response: types.GenerateContentResponse) -> types.Content | None:
    """응답 본문을 꺼낸다. 차단되었거나 잘린 응답은 오류로 처리한다."""
    if not response.candidates:
        raise AgentError("모델이 이 요청의 처리를 거절했습니다.")
    candidate = response.candidates[0]
    reason = candidate.finish_reason
    if reason == types.FinishReason.MAX_TOKENS:
        raise AgentError("모델 응답이 길이 제한을 넘었습니다.")
    if reason not in (None, types.FinishReason.STOP, *RETRYABLE_FINISH):
        raise AgentError("모델이 이 요청의 처리를 거절했습니다.")
    return candidate.content


def _arguments(call: types.FunctionCall, months: int | None) -> dict[str, Any]:
    """모델이 보낸 인자를 분석 도구가 받는 형태로 정리한다."""
    args = {key: value for key, value in (call.args or {}).items() if value is not None}
    if isinstance(args.get("months"), float):
        args["months"] = int(args["months"])  # JSON 숫자가 12.0처럼 실수로 올 수 있다.
    if call.name in ANALYSIS_TOOLS and months and "months" not in args:
        args["months"] = months  # 사용자가 말한 기간이 기본값으로 바뀌지 않게 한다.
    return args


def _tool_result(call: types.FunctionCall, payload: dict[str, Any]) -> types.Part:
    return types.Part(function_response=types.FunctionResponse(id=call.id, name=call.name, response=payload))


class GeminiAgent:
    def __init__(self, store: DataStore, client: Any = None, model: str | None = None) -> None:
        self.store = store
        self.client = client or create_client(os.environ[KEY_NAME])
        self.model = model or os.getenv(MODEL_NAME) or DEFAULT_MODEL

    def _interpret(self, question: str, answers: dict[str, str] | None) -> Interpretation:
        """사용자 문장을 Gemini에 보내 정해진 JSON 형식의 분석 조건으로 받는다."""
        response = self.client.models.generate_content(
            model=self.model,
            contents=question,
            config=types.GenerateContentConfig(
                system_instruction=INTERPRET_PROMPT,
                max_output_tokens=8000,
                response_mime_type="application/json",
                response_json_schema=interpretation_schema(self.store),
            ),
        )
        content = _model_content(response)
        text = "".join(part.text for part in (content.parts or []) if part.text and not part.thought) if content else ""
        try:
            return parse_interpretation(text, self.store, answers)
        except ValueError as exc:
            raise AgentError("질문 해석 결과가 정해진 형식과 다릅니다.") from exc

    def _create(self, contents: list[types.Content]) -> types.GenerateContentResponse:
        return self.client.models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                max_output_tokens=16000,
                tools=[types.Tool(function_declarations=TOOLS)],
                # 모든 단계는 도구 호출로 진행되고 build_report 또는 ask_user로 끝난다.
                tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode="ANY")),
            ),
        )

    def run(self, question: str, answers: dict[str, str] | None = None) -> Iterator[dict[str, Any]]:
        box = ToolBox(self.store)
        yield step(1, "running", "Gemini가 질문의 의도와 조건을 해석하고 있습니다.")
        parsed = self._interpret(question, answers)
        conditions = parsed.model_dump(exclude={"needs_clarification", "clarification_question", "missing_fields"}, exclude_none=True)
        box.calls.append(f"interpret_question({json.dumps(conditions, ensure_ascii=False)})")
        if parsed.needs_clarification:
            fields = [f for f in clarification_fields(self.store) if f["key"] in parsed.missing_fields]
            if fields:
                yield clarify(parsed.clarification_question or "분석 조건을 선택해 주세요.", fields)
                return
        text = f"{question}\n\n구조화된 질문 해석 결과: {json.dumps(conditions, ensure_ascii=False)}"
        contents = [types.Content(role="user", parts=[types.Part(text=text)])]
        stage, nudged = 1, False

        for _ in range(MAX_TURNS):
            content = _model_content(self._create(contents))
            parts = content.parts or [] if content else []
            if parts:
                contents.append(content)  # thought signature가 유지되도록 응답을 바꾸지 않고 그대로 넣는다.

            calls = [part.function_call for part in parts if part.function_call]
            if not calls:
                if nudged:
                    raise AgentError("모델이 보고서를 제출하지 않았습니다.")
                nudged = True
                contents.append(types.Content(role="user", parts=[types.Part(text="build_report 또는 ask_user 도구로 작업을 마무리해 주세요.")]))
                continue

            tool_results = []
            for call in calls:
                args = _arguments(call, parsed.months)
                if call.name == "ask_user":
                    yield clarify(args.get("question", "분석 조건을 선택해 주세요."), args.get("fields", []))
                    return
                if call.name == "build_report":
                    reason = _reject_report(args, box)
                    if reason is None:
                        if stage < 4:
                            yield step(3, "done", "코드 집계와 원본 재계산 검증 완료")
                        yield step(4, "done", "보고서 생성 완료")
                        results = [box.analyzer.get(i) for i in args["result_ids"]]
                        yield report(build_payload(question, args["title"], args["summary"], args["intent"], args["actions"],
                                                   results, box.calls, self.store, f"Gemini Agent · {self.model}"))
                        return
                    tool_results.append(_tool_result(call, {"error": reason}))
                    continue
                if call.name in ANALYSIS_TOOLS and stage < 3:
                    yield step(1, "done", "조건 해석 완료")
                    yield step(2, "done", f"{call.name} 도구 선택")
                    yield step(3, "running", "코드로 집계하고 원본 데이터로 재계산하고 있습니다.")
                    stage = 3
                try:
                    tool_results.append(_tool_result(call, {"result": box.run(call.name, args)}))
                except (AnalysisError, KeyError, TypeError, ValueError) as exc:
                    tool_results.append(_tool_result(call, {"error": str(exc)}))
            contents.append(types.Content(role="user", parts=tool_results))
        raise AgentError("분석 단계가 허용 횟수를 초과했습니다.")


def llm_available() -> bool:
    return bool(os.getenv(KEY_NAME))


def _api_failure(exc: errors.APIError) -> str:
    """Gemini API 오류를 사용자에게 보여줄 문장으로 바꾼다. 응답 원문은 노출하지 않는다."""
    detail = f"{exc.status or ''} {exc.message or ''}".lower()
    if exc.code in (401, 403) or "api key" in detail or "api_key" in detail:
        return "API Key 인증에 실패했습니다."
    if exc.code == 429:
        return "Gemini 무료 사용량 한도에 도달했습니다."
    if exc.code == 404:
        return "설정한 Gemini 모델을 사용할 수 없습니다."
    return f"Gemini API 오류가 발생했습니다 (상태 코드 {exc.code})."


def run_agent(question: str, answers: dict[str, str] | None, store: DataStore, client: Any = None) -> Iterator[dict[str, Any]]:
    """Gemini로 분석하고, 사용할 수 없으면 규칙 기반 분석으로 전환한다."""
    try:
        if client is None and not llm_available():
            yield from run_rules(question, answers, store)
            return
        try:
            yield from GeminiAgent(store, client=client).run(question, answers)
            return
        except errors.APIError as exc:
            reason = _api_failure(exc)
        except CONNECTION_ERRORS:
            reason = "Gemini API에 연결할 수 없습니다."
        except (errors.UnknownApiResponseError, json.JSONDecodeError):
            reason = "Gemini API 응답을 해석할 수 없습니다."
        except AgentError as exc:
            reason = str(exc)
        message = f"{reason} 규칙 기반 분석으로 전환했습니다."
        yield notice(message)
        yield from run_rules(question, answers, store, notice=message)
    except (AnalysisError, RuntimeError) as exc:
        yield error(str(exc))
