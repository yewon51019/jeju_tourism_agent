"""Claude Tool Use 기반 Agent 루프."""
from __future__ import annotations

import json
import os
from typing import Any, Iterator

import anthropic
from pydantic import ValidationError

from .data_pipeline import DataStore
from .events import clarify, error, notice, report, step
from .interpreter import Interpretation, ReportDraft, interpretation_schema, parse_interpretation
from .prompts import INTERPRET_PROMPT, SYSTEM_PROMPT
from .report import build_payload, unsupported_numbers
from .rule_engine import clarification_fields, run_rules
from .tools.analysis import AnalysisError
from .tools.registry import TOOLS, ToolBox

DEFAULT_MODEL = "claude-opus-5-5"
MAX_TURNS = 14
ANALYSIS_TOOLS = {"analyze_trend", "rank_segments", "weekday_pattern"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"


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


class ClaudeAgent:
    def __init__(self, store: DataStore, client: Any = None, model: str | None = None) -> None:
        self.store = store
        self.client = client or anthropic.Anthropic()
        self.model = model or os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL)

    def _interpret(self, question: str, answers: dict[str, str] | None) -> Interpretation:
        """사용자 문장을 Claude에 보내 정해진 JSON 형식의 분석 조건으로 받는다."""
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=4000,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": interpretation_schema(self.store)}},
            system=INTERPRET_PROMPT,
            messages=[{"role": "user", "content": question}],
        )
        if response.stop_reason in ("refusal", "max_tokens"):
            raise AgentError("질문 해석 응답을 완성하지 못했습니다.")
        text = "".join(block.text for block in response.content if block.type == "text")
        try:
            return parse_interpretation(text, self.store, answers)
        except ValueError as exc:
            raise AgentError("질문 해석 결과가 정해진 형식과 다릅니다.") from exc

    def _create(self, messages: list[dict[str, Any]]) -> Any:
        return self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            output_config={"effort": "medium"},
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            tools=TOOLS,
            messages=messages,
        )

    def run(self, question: str, answers: dict[str, str] | None = None) -> Iterator[dict[str, Any]]:
        box = ToolBox(self.store)
        yield step(1, "running", "Claude가 질문의 의도와 조건을 해석하고 있습니다.")
        parsed = self._interpret(question, answers)
        conditions = parsed.model_dump(exclude={"needs_clarification", "clarification_question", "missing_fields"}, exclude_none=True)
        box.calls.append(f"interpret_question({json.dumps(conditions, ensure_ascii=False)})")
        if parsed.needs_clarification:
            fields = [f for f in clarification_fields(self.store) if f["key"] in parsed.missing_fields]
            if fields:
                yield clarify(parsed.clarification_question or "분석 조건을 선택해 주세요.", fields)
                return
        text = f"{question}\n\n구조화된 질문 해석 결과: {json.dumps(conditions, ensure_ascii=False)}"
        messages: list[dict[str, Any]] = [{"role": "user", "content": text}]
        stage, nudged = 1, False

        for _ in range(MAX_TURNS):
            response = self._create(messages)
            if response.stop_reason == "refusal":
                raise AgentError("모델이 이 요청의 처리를 거절했습니다.")
            if response.stop_reason == "max_tokens":
                raise AgentError("모델 응답이 길이 제한을 넘었습니다.")
            messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason == "pause_turn":
                continue

            tool_uses = [block for block in response.content if block.type == "tool_use"]
            if not tool_uses:
                if nudged:
                    raise AgentError("모델이 보고서를 제출하지 않았습니다.")
                nudged = True
                messages.append({"role": "user", "content": "build_report 또는 ask_user 도구로 작업을 마무리해 주세요."})
                continue

            tool_results = []
            for block in tool_uses:
                args = block.input if isinstance(block.input, dict) else {}
                if block.name in ANALYSIS_TOOLS and parsed.months and "months" not in args:
                    args = {**args, "months": parsed.months}  # 사용자가 말한 기간이 기본값으로 바뀌지 않게 한다.
                if block.name == "ask_user":
                    yield clarify(args.get("question", "분석 조건을 선택해 주세요."), args.get("fields", []))
                    return
                if block.name == "build_report":
                    reason = _reject_report(args, box)
                    if reason is None:
                        if stage < 4:
                            yield step(3, "done", "코드 집계와 원본 재계산 검증 완료")
                        yield step(4, "done", "보고서 생성 완료")
                        results = [box.analyzer.get(i) for i in args["result_ids"]]
                        yield report(build_payload(question, args["title"], args["summary"], args["intent"], args["actions"],
                                                   results, box.calls, self.store, f"Claude Agent · {self.model}"))
                        return
                    tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": reason, "is_error": True})
                    continue
                if block.name in ANALYSIS_TOOLS and stage < 3:
                    yield step(1, "done", "조건 해석 완료")
                    yield step(2, "done", f"{block.name} 도구 선택")
                    yield step(3, "running", "코드로 집계하고 원본 데이터로 재계산하고 있습니다.")
                    stage = 3
                try:
                    output = box.run(block.name, args)
                    tool_results.append({"type": "tool_result", "tool_use_id": block.id,
                                         "content": json.dumps(output, ensure_ascii=False)})
                except (AnalysisError, KeyError, TypeError) as exc:
                    tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(exc), "is_error": True})
            messages.append({"role": "user", "content": tool_results})
        raise AgentError("분석 단계가 허용 횟수를 초과했습니다.")


def llm_available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def run_agent(question: str, answers: dict[str, str] | None, store: DataStore, client: Any = None) -> Iterator[dict[str, Any]]:
    """Claude로 분석하고, 사용할 수 없으면 규칙 기반 분석으로 전환한다."""
    try:
        if client is None and not llm_available():
            yield from run_rules(question, answers, store)
            return
        try:
            yield from ClaudeAgent(store, client=client).run(question, answers)
            return
        except anthropic.AuthenticationError:
            reason = "API Key 인증에 실패했습니다."
        except anthropic.RateLimitError:
            reason = "API 사용량 한도에 도달했습니다."
        except anthropic.APIStatusError as exc:
            reason = f"Claude API 오류가 발생했습니다 (상태 코드 {exc.status_code})."
        except anthropic.APIConnectionError:
            reason = "Claude API에 연결할 수 없습니다."
        except AgentError as exc:
            reason = str(exc)
        message = f"{reason} 규칙 기반 분석으로 전환했습니다."
        yield notice(message)
        yield from run_rules(question, answers, store, notice=message)
    except (AnalysisError, RuntimeError) as exc:
        yield error(str(exc))
