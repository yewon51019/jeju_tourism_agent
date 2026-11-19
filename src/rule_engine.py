"""API Key가 없거나 LLM 호출이 실패할 때 쓰는 규칙 기반 분석 경로."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterator

from .data_pipeline import DISTRICT_REGION, DataStore
from .events import clarify, report, step
from .report import build_payload, month_label, money, signed, unsupported_numbers, won
from .tools.analysis import Result
from .tools.registry import ToolBox

LEISURE_WORDS = ["레저", "레져", "체험", "문화", "액티비티"]
THEME_WORDS = {"식음료": ["식음료", "외식", "먹거리", "맛집", "음식", "카페", "디저트", "커피", "식당"],
               "숙박": ["숙박", "호텔", "리조트", "펜션"], "쇼핑": ["쇼핑", "기념품"], "소매": ["소매"],
               "문화·레저": LEISURE_WORDS, "문화/레져": LEISURE_WORDS, "문화/레저": LEISURE_WORDS,
               "교통": ["교통", "렌터카"], "유흥": ["유흥", "주점"]}
INDUSTRY_WORDS = {"카페·디저트": ["카페", "디저트", "커피"], "음식점": ["음식점", "식당"]}
DISTRICT_WORDS = {"중문": "중문관광단지", "성산": "성산일출봉", "올레시장": "서귀포매일올레시장", "표선": "표선해변",
                  "연동": "연동상권", "함덕": "함덕해변", "애월": "애월해안", "협재": "협재해변"}
TOWN_REGION = {"한림": "제주시", "구좌": "제주시", "조천": "제주시", "한경": "제주시", "우도": "제주시",
               "남원": "서귀포시", "안덕": "서귀포시", "대정": "서귀포시"}
MODE_LABEL = "규칙 기반 분석"


@dataclass
class Parsed:
    question: str
    filters: dict[str, str] = field(default_factory=dict)
    district: str | None = None
    intent: str = "trend"
    months: int = 12
    dimension: str | None = None
    notices: list[str] = field(default_factory=list)
    ambiguous: bool = False


def _match_district(question: str, store: DataStore) -> str | None:
    available = store.values("지구")
    direct = next((d for d in available if d in question), None)
    if direct:
        return direct
    return next((d for word, d in DISTRICT_WORDS.items() if word in question and d in available), None)


def _detect_intent(q: str) -> str:
    if re.search(r"증가율|성장|많이 늘|증가한", q):
        return "growth"
    if re.search(r"요일|주말|평일", q):
        return "weekday"
    if re.search(r"언제|시기|프로모션|성수기|시즌", q):
        return "timing"
    if re.search(r"추세|변화|흐름", q):
        return "trend"
    if re.search(r"어디|순위|비교|많은|1위|잘 ?돼|잘 ?되", q):
        return "rank"
    return "trend"


def _free_dimension(preferred: list[str], filters: dict[str, str]) -> str | None:
    """이미 한 값으로 고정한 조건은 순위를 매겨도 의미가 없으므로 제외한다."""
    fixed = {"region": "시군구", "theme": "테마", "industry": "업종", "age": "연령대", "gender": "성별"}
    blocked = {fixed[key] for key in filters if key in fixed}
    if "industry" in filters:
        blocked.add("테마")
    return next((d for d in [*preferred, "업종", "연령대", "성별", "시군구"] if d not in blocked), None)


def _detect_dimension(q: str, filters: dict[str, str]) -> str | None:
    if re.search(r"연령|고객층|누가", q):
        return _free_dimension(["연령대"], filters)
    if "테마" in q:
        return _free_dimension(["테마"], filters)
    if "업종" in q or "region" in filters:
        return _free_dimension(["업종"], filters)
    return _free_dimension(["시군구"], filters)


def parse_question(question: str, answers: dict[str, str] | None, store: DataStore) -> Parsed:
    q = question.strip()
    answers = {k: v for k, v in (answers or {}).items() if v}
    parsed = Parsed(question=q, intent=_detect_intent(q))
    filters = parsed.filters

    regions = store.values("시군구")
    mentioned = [r for r in regions if r in q or (r == "서귀포시" and "서귀포" in q and "올레시장" not in q)]
    compare_regions = len(mentioned) > 1
    region = mentioned[0] if len(mentioned) == 1 else None
    if compare_regions:
        parsed.intent = "rank"
    parsed.district = _match_district(q, store)
    town = next((t for t in TOWN_REGION if t in q), None)
    if region:
        filters["region"] = region

    age = re.search(r"([2-9])0\s*대", q)
    if age:
        ages = store.values("연령대")
        wanted = f"{age.group(1)}0대"
        match = wanted if wanted in ages else next((a for a in ages if a.startswith(wanted)), None)
        if match is None and int(age.group(1)) >= 6:
            match = next((a for a in ages if "이상" in a), None)
        if match:
            filters["age"] = match
    if re.search(r"여성|여자", q) and "여성" in store.values("성별"):
        filters["gender"] = "여성"
    elif re.search(r"남성|남자", q) and "남성" in store.values("성별"):
        filters["gender"] = "남성"
    resident = next((v for v in store.values("관광객구분") if "도민" in v), None)
    if "도민" in q and resident:
        filters["visitor"] = resident

    industries, themes = store.values("업종"), store.values("테마")
    industry = next((i for i in industries if i in q), None) or next(
        (i for i, words in INDUSTRY_WORDS.items() if i in industries and any(w in q for w in words)), None)
    theme = next((t for t in themes if t in q), None) or next(
        (t for t, words in THEME_WORDS.items() if t in themes and any(w in q for w in words)), None)
    if industry:
        filters["industry"] = industry
    elif theme:
        filters["theme"] = theme
    if re.search(r"카페|디저트|커피", q) and "카페·디저트" not in industries and theme:
        parsed.notices.append(f"카페·디저트는 별도 업종으로 제공되지 않아 {theme} 전체로 분석했습니다.")

    for key in ("region", "theme", "age"):
        if key in answers:
            if answers[key] == "전체":
                filters.pop(key, None)
            else:
                filters[key] = answers[key]
    if filters.get("theme") in industries:  # 테마와 업종이 같은 값이면 하나의 조건으로 다룬다.
        filters["industry"] = filters.pop("theme")

    span = re.search(r"최근\s*(\d+)\s*(개월|달|년)", q)
    if span:
        parsed.months = max(1, min(36, int(span.group(1)) * (12 if span.group(2) == "년" else 1)))

    needs_grain = any(k in filters for k in ("age", "gender", "theme", "industry"))
    if parsed.district and "region" not in filters:
        mapped_region = DISTRICT_REGION.get(parsed.district)
        if mapped_region:
            filters["region"] = mapped_region
        if not mapped_region:
            parsed.notices.append(f"{parsed.district}는 특정 시군구로 연결할 수 없어 월간 분석은 제주 전체 기준입니다.")
        elif needs_grain:
            parsed.notices.append(f"업종·고객층은 시군구 단위로만 제공되어 {parsed.district} 대신 {filters['region']} 전체로 분석했습니다.")
        else:
            parsed.notices.append(f"요일 패턴은 {parsed.district} 기준이고, 월별 추세는 {filters['region']} 전체 기준입니다.")
    if town and "region" not in filters:
        filters["region"] = TOWN_REGION[town]
        parsed.notices.append(f"읍면 단위 데이터가 없어 {town} 대신 {filters['region']} 전체로 분석했습니다.")
    if "도민" in filters.get("visitor", "") and parsed.intent in ("weekday", "timing"):
        parsed.notices.append("요일별 데이터에는 도민과 관광객 구분이 없어 요일 비중은 지역 전체 소비 기준입니다." if store.is_sample else
                              "요일별 연결 자료는 내국인관광객 기준으로, 제주도민의 요일 패턴을 뜻하지 않습니다.")
    if "외국인" in q:
        parsed.notices.append("외국인 관광객 데이터가 없어 내국인 관광객 기준으로 분석했습니다.")
    if re.search(r"시간대|오전|오후|저녁|점심", q):
        parsed.notices.append("시간대별 데이터가 없어 월·요일 단위로 분석했습니다.")
    if re.search(r"\d+\s*~\s*\d+\s*월|여름|겨울|봄철|가을", q):
        parsed.notices.append("특정 계절만 따로 집계하지 않고 최근 기간 전체의 월별 흐름으로 분석했습니다.")

    all_region = bool(re.search(r"전\s*지역|전체|전역", q)) or bool(answers) or compare_regions
    has_target = any(k in filters for k in ("region", "theme", "industry", "age")) or parsed.district or all_region
    parsed.ambiguous = len(q) < 6 or (not has_target and parsed.intent != "growth")
    parsed.dimension = "시군구" if compare_regions else _detect_dimension(q, filters)
    return parsed


def clarification_fields(store: DataStore) -> list[dict[str, Any]]:
    return [{"key": "region", "label": "희망 분석 지역", "options": ["전체", *store.values("시군구")]},
            {"key": "theme", "label": "관심 업종" if store.theme_is_industry_alias else "관심 업종 테마", "options": ["전체", *store.values("테마")]},
            {"key": "age", "label": "주요 고객 연령대", "options": ["전체", *store.values("연령대")]}]


def _execute(parsed: Parsed, box: ToolBox) -> list[Result]:
    filters, months = dict(parsed.filters), parsed.months
    region = filters.get("region")
    run = box.run
    ids: list[str] = []

    def add(name: str, args: dict[str, Any]) -> dict[str, Any]:
        output = run(name, args)
        ids.append(output["result_id"])
        return output

    if parsed.intent == "timing":
        add("analyze_trend", {"filters": filters, "months": months})
        add("weekday_pattern", {"district": parsed.district, "region": region, "months": months})
    elif parsed.intent == "weekday":
        add("weekday_pattern", {"district": parsed.district, "region": region, "months": months})
        add("analyze_trend", {"filters": filters, "months": months})
    elif parsed.intent == "growth":
        target = filters
        if "industry" not in filters:
            dimension = "업종" if "theme" in filters or box.store.theme_is_industry_alias else "테마"
            ranking = run("rank_segments", {"dimension": dimension, "filters": filters, "metric": "growth", "months": months})
            if len(ranking["rows"]) > 1:
                ids.append(ranking["result_id"])
                key = "industry" if dimension == "업종" else "theme"
                target = {**filters, key: ranking["facts"]["top_name"]}
        add("analyze_trend", {"filters": target, "months": months})
    elif parsed.intent == "rank":
        if parsed.dimension:
            add("rank_segments", {"dimension": parsed.dimension, "filters": filters, "months": months})
        add("analyze_trend", {"filters": filters, "months": months})
    else:
        add("analyze_trend", {"filters": filters, "months": months})
        dimension = _free_dimension(["업종", "연령대"], filters)
        if dimension:
            add("rank_segments", {"dimension": dimension, "filters": filters, "months": months})
    for result_id in ids:
        run("verify_result", {"result_id": result_id})
    return [box.analyzer.get(i) for i in ids]


def _scope(parsed: Parsed) -> str:
    f = parsed.filters
    default_visitor = "관광객" if not f.get("visitor") else f["visitor"]
    parts = [f.get("region") or parsed.district or "제주 전체", f.get("age"), f.get("gender"), default_visitor,
             f.get("industry") or f.get("theme")]
    return " ".join(p for p in parts if p)


def _find(results: list[Result], kind: str) -> Result | None:
    return next((r for r in results if r.kind == kind), None)


def narrate(parsed: Parsed, results: list[Result]) -> tuple[str, str, list[dict[str, str]]]:
    scope = _scope(parsed)
    trend, weekday, rank = _find(results, "trend"), _find(results, "weekday"), _find(results, "rank")
    sentences: list[str] = []
    actions: list[dict[str, str]] = []
    title = f"{scope} 소비 분석 리포트"

    if rank and parsed.intent == "growth":
        f = rank.facts
        title = f"최근 {parsed.months}개월 {f['dimension']}별 소비 증가율 분석"
        all_down = f["top_yoy"] < 0
        if all_down:
            sentences.append(f"전년 비교가 가능한 모든 {f['dimension']}의 소비가 전년 동기보다 감소했으며, 감소폭이 가장 작은 {f['dimension']}는 "
                             f"**{f['top_name']}({signed(f['top_yoy'])})**이고, 가장 큰 {f['dimension']}는 {f['bottom_name']}({signed(f['bottom_yoy'])})입니다.")
        else:
            sentences.append(f"전년 동기 대비 증가율이 가장 높은 {f['dimension']}는 **{f['top_name']}({signed(f['top_yoy'])})**이고, "
                             f"가장 낮은 {f['dimension']}는 {f['bottom_name']}({signed(f['bottom_yoy'])})입니다.")
        actions.append({"badge": "상대적 강세" if all_down else "성장 분야", "title": f"{f['top_name']} 연계 상품 검토",
                        "desc": f"{f['top_name']}의 이용금액이 전년 동기보다 {signed(f['top_yoy'])} 변했습니다. 기존 상품과 결합할 수 있는지 검토하세요."})
        actions.append({"badge": "위험 점검", "title": f"{f['bottom_name']} 수요 변화 점검",
                        "desc": f"{f['bottom_name']}의 전년 대비 증감률은 {signed(f['bottom_yoy'])}입니다. 관련 사업자는 상품 구성과 판매 경로를 점검하세요."})
    elif rank:
        f = rank.facts
        if parsed.intent == "rank":
            title = f"{scope} {f['dimension']}별 소비 순위 분석"
        sentences.append(f"{f['dimension']} 기준으로는 **{f['top_name']}**의 이용금액이 가장 많고 전체의 **{f['top_share']}%**를 차지합니다.")
        actions.append({"badge": "핵심 대상", "title": f"{f['top_name']} 중심으로 우선 실행",
                        "desc": f"{f['top_name']}이 전체 이용금액의 {f['top_share']}%를 차지하므로 홍보와 상품 기획의 우선 대상으로 삼으세요."})

    if trend:
        f = trend.facts
        tops = ", ".join(month_label(m) for m in f["top3_months"])
        top_text = f" 상위 3개월({tops})의 비중은 {f['top3_share']}%입니다." if len(trend.rows) > 3 else ""
        if parsed.intent == "timing":
            title = f"{scope} 소비 분석 및 프로모션 적기 제안"
        sentences.insert(0 if parsed.intent != "growth" else 1,
                         f"{scope} 소비는 **{month_label(f['peak_month'])}**에 가장 많아 분석 기간 이용금액의 **{f['peak_share']}%**를 차지합니다.{top_text}")
        if parsed.intent == "growth" and not rank:
            title = f"{scope} 전년 대비 소비 증감 분석"
            sentences.insert(0, f"{scope} 소비의 전년 동기 대비 증감률은 **{signed(f['yoy_total'])}**입니다.")
        actions.append({"badge": "시기 전략", "title": f"{month_label(f['peak_month'])} 이전 사전 홍보",
                        "desc": f"소비가 가장 많은 달의 이용금액은 {money(f['peak_amount'])}입니다. 해당 시기가 시작되기 전에 쿠폰과 예약 홍보를 준비하세요."})
        actions.append({"badge": "상품 전략", "title": f"1인당 {won(f['per_user'])} 기준 상품 구성",
                        "desc": f"분석 대상의 1인당 평균 이용금액은 {won(f['per_user'])}입니다. 이 금액을 기준으로 세트 상품과 가격대를 설계하세요."})
        actions.append({"badge": "비수기 전략", "title": f"{month_label(f['low_month'])} 수요 보완",
                        "desc": f"소비 비중이 가장 낮은 달의 비중은 {f['low_share']}%입니다. 이 시기에는 재방문 혜택이나 지역 연계 행사를 검토하세요."})
    if weekday:
        f = weekday.facts
        days = "·".join(f["top_days"])
        base = parsed.district or parsed.filters.get("region") or "제주"
        if parsed.intent == "weekday":
            title = f"{base} 요일별 소비 패턴 분석"
        sentence = (f"{base} 요일별 데이터 기준으로 **{days}요일**에 주간 소비의 **{f['top_days_share']}%**가 집중되고, "
                    f"주말(토·일) 비중은 {f['weekend_share']}%, 평일(월~금) 비중은 {f['weekday_share']}%입니다.")
        sentences.insert(0 if parsed.intent == "weekday" else len(sentences), sentence)
        actions.insert(1, {"badge": "요일 전략", "title": f"{days}요일 집중 운영",
                           "desc": f"{base} 요일별 데이터 기준으로 {days}요일의 비중이 {f['top_days_share']}%로 가장 높습니다. 이 요일에 인력과 재고를 우선 배치하고, {f['low_day']}요일에는 할인 혜택을 검토하세요."})
    return title, " ".join(sentences), actions[:4]


def run_rules(question: str, answers: dict[str, str] | None, store: DataStore,
              notice: str | None = None) -> Iterator[dict[str, Any]]:
    yield step(1, "running", "질문의 지역·업종·고객층·기간을 해석하고 있습니다.")
    parsed = parse_question(question, answers, store)
    if parsed.ambiguous:
        yield clarify(f"\"{question}\" 질문은 범위가 넓어 분석 조건 확인이 필요합니다. 아래 조건을 선택해 주세요.",
                      clarification_fields(store))
        return
    notices = ([notice] if notice else []) + parsed.notices

    yield step(1, "done", "조건 해석 완료")
    yield step(2, "running", "질문에 맞는 데이터와 분석 도구를 선택하고 있습니다.")
    yield step(2, "done", f"분석 유형: {parsed.intent} · 데이터 기간: {store.period}")
    yield step(3, "running", "코드로 집계하고 원본 데이터로 재계산하고 있습니다.")

    box = ToolBox(store)
    results = _execute(parsed, box)
    for key, label in (("gender", "성별"), ("age", "연령대")):
        low_sample = any(c["status"] == "warning" for r in results for c in r.checks)
        if low_sample and key in parsed.filters:
            parsed.filters.pop(key)
            notices.append(f"표본이 부족해 {label} 조건을 제외하고 다시 분석했습니다.")
            results = _execute(parsed, box)

    checks = [c for r in results for c in r.checks]
    passed = sum(1 for c in checks if c["status"] == "pass")
    if any(c["status"] == "fail" for c in checks):
        raise RuntimeError("분석 결과가 원본 재계산과 일치하지 않아 보고서를 생성하지 않았습니다.")
    yield step(3, "done", f"검증 {len(checks)}건 중 {passed}건 통과")
    yield step(4, "running", "검증된 수치로 보고서를 작성하고 있습니다.")

    title, summary, actions = narrate(parsed, results)
    if not store.is_sample:
        # 과거 통계의 최고 월을 앞으로 다가올 행사 일정처럼 제안하지 않는다.
        for action in actions:
            if action["badge"] == "시기 전략":
                action.update(title="과거 소비 집중 월을 참고", desc="과거 자료에서 관찰한 집중 시기입니다. 현재 행사 일정과 최신 수요를 확인한 뒤 홍보 시기를 정하세요.")
            elif action["badge"] == "상품 전략":
                action.update(title="누적 이용자수 대비 금액을 참고", desc="집계 금액을 누적 이용자수로 나눈 비율이며 개인별 여행 예산이 아닙니다. 이 값만으로 상품 가격을 정하지 마세요.")
            elif action["badge"] == "비수기 전략":
                action.update(title="과거 저소비 월의 현재 수요 확인", desc="과거에 비중이 낮았던 달이 현재에도 비수기인지 최신 자료를 확인한 뒤 행사를 검토하세요.")
    text = " ".join([summary, *[a["desc"] for a in actions]])
    invalid = unsupported_numbers(text, results)
    if invalid:
        raise RuntimeError(f"보고서에 분석 결과와 다른 수치가 있습니다: {', '.join(invalid)}")
    payload = build_payload(question, title, summary, parsed.intent, actions, results, box.calls, store, MODE_LABEL, notices)
    yield step(4, "done", "보고서 생성 완료")
    yield report(payload)
