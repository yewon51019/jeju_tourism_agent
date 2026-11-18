"""평가 질문 30개로 규칙 기반 경로의 조건 해석과 보고서 검증을 측정한다.

실행: python scripts/evaluate.py
Gemini API는 호출하지 않으므로 이 결과는 규칙 기반 분석 경로의 성능이다.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.data_pipeline import load_store  # noqa: E402
from src.report import unsupported_numbers  # noqa: E402,F401
from src.rule_engine import parse_question, run_rules  # noqa: E402

# 질문, 분석 유형, 지역, 연령대, 성별, 업종·테마, 되묻기 여부, 한계 안내 여부
CASES = [
    ("서귀포시에서 30대 관광객 대상 식음료 프로모션은 언제가 좋을까?", "timing", "서귀포시", "30대", None, "식음료", False, False),
    ("제주시 20대 여성 숙박 소비 추세 알려줘", "trend", "제주시", "20대", "여성", "숙박", False, False),
    ("서귀포시 40대 남성 쇼핑 소비 추세는?", "trend", "서귀포시", "40대", "남성", "쇼핑", False, False),
    ("제주시 교통 업종 소비 흐름을 보여줘", "trend", "제주시", None, None, "교통", False, False),
    ("제주시 식음료 성수기가 언제야?", "timing", "제주시", None, None, "식음료", False, False),
    ("서귀포시 숙박 프로모션 시기를 추천해줘", "timing", "서귀포시", None, None, "숙박", False, False),
    ("제주시 50대 쇼핑 프로모션은 언제 해야 해?", "timing", "제주시", "50대", None, "쇼핑", False, False),
    ("서귀포시 30대 여성 레저 체험 프로모션 시기는?", "timing", "서귀포시", "30대", "여성", "문화", False, False),
    ("제주시 요일별 소비 패턴 알려줘", "weekday", "제주시", None, None, None, False, False),
    ("서귀포시 주말과 평일 소비를 비교해줘", "weekday", "서귀포시", None, None, None, False, False),
    ("제주시 평일 소비 비중은 얼마나 돼?", "weekday", "제주시", None, None, None, False, False),
    ("서귀포시 요일별 소비 비중 보여줘", "weekday", "서귀포시", None, None, None, False, False),
    ("최근 1년 제주 전 지역 소비 증가율이 가장 높은 테마는?", "growth", None, None, None, None, False, False),
    ("제주시에서 성장한 테마가 뭐야?", "growth", "제주시", None, None, None, False, False),
    ("서귀포시 30대 소비 증가율이 높은 테마 알려줘", "growth", "서귀포시", "30대", None, None, False, False),
    ("제주시 식음료 소비 증가율은 얼마야?", "growth", "제주시", None, None, "식음료", False, False),
    ("제주시와 서귀포시 소비 비교해줘", "rank", None, None, None, None, False, False),
    ("제주시 업종별 소비 순위 알려줘", "rank", "제주시", None, None, None, False, False),
    ("서귀포시 숙박 소비의 연령대 순위는?", "rank", "서귀포시", None, None, "숙박", False, False),
    ("제주 전체에서 소비가 많은 지역은 어디야?", "rank", None, None, None, None, False, False),
    ("제주시 식음료 고객층 순위 보여줘", "rank", "제주시", None, None, "식음료", False, False),
    ("요즘 제주도 장사 어디가 잘 돼?", "rank", None, None, None, None, True, False),
    ("어디가 제일 좋아?", "rank", None, None, None, None, True, False),
    ("소비 추세 알려줘", "trend", None, None, None, None, True, False),
    ("요즘 뭐가 잘 팔려?", "trend", None, None, None, None, True, False),
    ("제주시 외국인 관광객 식음료 소비 추세는?", "trend", "제주시", None, None, "식음료", False, True),
    ("서귀포시 식음료 점심 시간대 소비 추세 알려줘", "trend", "서귀포시", None, None, "식음료", False, True),
    ("한림 30대 식음료 프로모션 시기는?", "timing", "제주시", "30대", None, "식음료", False, True),
    ("대정 숙박 소비 추세 알려줘", "trend", "서귀포시", None, None, "숙박", False, True),
    ("제주시 여름 숙박 성수기 언제야?", "timing", "제주시", None, None, "숙박", False, True),
]


def matches(expected: str | None, actual: str | None) -> bool:
    return actual is None if expected is None else bool(actual) and actual.startswith(expected)


def evaluate() -> dict[str, object]:
    store = load_store()
    condition_ok = intent_ok = clarify_ok = notice_ok = reports = verified = 0
    failures: list[str] = []
    for question, intent, region, age, gender, target, ambiguous, notice in CASES:
        parsed = parse_question(question, None, store)
        f = parsed.filters
        conditions = (matches(region, f.get("region")) and matches(age, f.get("age")) and matches(gender, f.get("gender"))
                      and matches(target, f.get("industry") or f.get("theme")))
        condition_ok += conditions
        intent_ok += parsed.intent == intent
        clarify_ok += parsed.ambiguous == ambiguous
        notice_ok += bool(parsed.notices) == notice
        if not (conditions and parsed.intent == intent and parsed.ambiguous == ambiguous and bool(parsed.notices) == notice):
            failures.append(f"{question} -> intent={parsed.intent}, filters={f}, ambiguous={parsed.ambiguous}, notices={len(parsed.notices)}")
        if not ambiguous:
            last = list(run_rules(question, None, store))[-1]
            if last["type"] == "report":
                reports += 1
                checks = last["report"]["verification"]
                verified += checks["passed"] + checks["warnings"] == checks["total"]
            else:
                failures.append(f"{question} -> 보고서 미생성: {last.get('message', last['type'])}")
    total = len(CASES)
    answerable = sum(1 for case in CASES if not case[6])
    return {"total": total, "answerable": answerable, "condition": condition_ok, "intent": intent_ok, "clarify": clarify_ok,
            "notice": notice_ok, "reports": reports, "verified": verified, "failures": failures,
            "source": store.source, "period": store.period, "is_sample": store.is_sample}


def to_markdown(r: dict[str, object]) -> str:
    total, answerable = r["total"], r["answerable"]
    rate = lambda n, d: f"{n}/{d} ({n / d * 100:.1f}%)"
    lines = ["# 평가 결과", "",
             "원본 CSV 취득·검증은 [수집 결과](csv-export.md)에 별도 기록합니다. 아래 수치의 데이터 출처는 다음 항목을 따르며 CSV 취득 성공을 모델 평가 성공으로 간주하지 않습니다.", "",
             f"- 데이터: {r['source']} ({r['period']})",
             "- 측정 대상: 규칙 기반 분석 경로. Gemini API 경로는 이 평가에 포함되지 않습니다.",
             "- 평가 질문은 규칙을 만든 참가자가 직접 작성했으므로 처음 보는 질문에서는 정확도가 더 낮을 수 있습니다.", "",
             "| 지표 | 결과 | 기획서 목표 |", "| --- | --- | --- |",
             f"| 질문 조건 추출 정확도 | {rate(r['condition'], total)} | 90% 이상 |",
             f"| 분석 유형·도구 선택 정확도 | {rate(r['intent'], total)} | 90% 이상 |",
             f"| 조건 되묻기 판단 정확도 | {rate(r['clarify'], total)} | 별도 목표 없음 |",
             f"| 데이터 한계 안내 정확도 | {rate(r['notice'], total)} | 별도 목표 없음 |",
             f"| 보고서 생성 성공률 | {rate(r['reports'], answerable)} | 별도 목표 없음 |",
             f"| 원본 재계산 검증 통과율 | {rate(r['verified'], answerable)} | 100% |", ""]
    if r["failures"]:
        lines += ["## 오답 사례", "", *[f"- {item}" for item in r["failures"]], ""]
    return "\n".join(lines)


if __name__ == "__main__":
    print(to_markdown(evaluate()))
