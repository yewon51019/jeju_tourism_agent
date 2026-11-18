"""검증된 분석 결과로 화면에 표시할 보고서를 구성한다."""
from __future__ import annotations

import re
from typing import Any

from .data_pipeline import DataStore
from .tools.analysis import FILTER_LABELS, Result

_NUMBER = re.compile(r"(?<![\d.,])([+\-−]?)(\d[\d,]*(?:\.\d+)?)\s*(%|퍼센트|억\s*원|억|만\s*원|만\s*명|만\s*건|만|원|명|건)")
_WON_PREFIX = re.compile(r"₩\s*(\d[\d,]*(?:\.\d+)?)")
_SCALE = {"억": 1e8, "만": 1e4}


def month_label(month: str) -> str:
    return f"{month[:4]}년 {int(month[5:7])}월"


def short_month(month: str) -> str:
    return f"{month[2:4]}.{month[5:7]}"


def money(amount: float) -> str:
    if abs(amount) >= 1e8:
        return f"{amount / 1e8:,.1f}억 원"
    if abs(amount) >= 1e4:
        return f"{amount / 1e4:,.0f}만 원"
    return f"{amount:,.0f}원"


def won(amount: float) -> str:
    return f"{amount:,.0f}원"


def signed(value: float | None) -> str:
    return "비교 불가" if value is None else f"{value:+.1f}%"


def _pools(results: list[Result]) -> dict[str, list[float]]:
    pools: dict[str, list[float]] = {"percent": [], "money": [], "users": [], "count": []}

    def collect(key: str, value: Any) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return
        if "share" in key or "yoy" in key:
            pools["percent"].append(float(value))
        elif "amount" in key or key.startswith("per_"):
            pools["money"].append(abs(float(value)))
        elif "users" in key:
            pools["users"].append(abs(float(value)))
        elif "count" in key:
            pools["count"].append(abs(float(value)))

    for result in results:
        for key, value in result.facts.items():
            collect(key, value)
        for row in result.rows:
            for key, value in row.items():
                collect(key, value)
    return pools


def _pool_for(unit: str, pools: dict[str, list[float]]) -> list[float]:
    if unit in ("%", "퍼센트"):
        return pools["percent"]
    if unit in ("명", "만명"):
        return pools["users"]
    if unit in ("건", "만건"):
        return pools["count"]
    if unit == "만":
        return pools["money"] + pools["users"] + pools["count"]
    return pools["money"]


def _is_supported(sign: str, raw: str, unit: str, pools: dict[str, list[float]]) -> bool:
    value, decimals = float(raw), len(raw.split(".")[1]) if "." in raw else 0
    scale = _SCALE.get(unit[0], 1)
    for item in _pool_for(unit, pools):
        if round(abs(item) / scale, decimals) != value:
            continue
        if unit not in ("%", "퍼센트") or not sign or (item < 0) == (sign in "-−"):
            return True
    return False


def unsupported_numbers(text: str, results: list[Result]) -> list[str]:
    """문장 속 단위가 붙은 수치 중 분석 결과에 없는 값을 찾는다."""
    pools = _pools(results)
    invalid = []
    for match in _NUMBER.finditer(text):
        raw, unit = match.group(2).replace(",", ""), match.group(3).replace(" ", "")
        if not _is_supported(match.group(1), raw, unit, pools):
            invalid.append(match.group(0))
    for match in _WON_PREFIX.finditer(text):
        if not _is_supported("", match.group(1).replace(",", ""), "원", pools):
            invalid.append(match.group(0))
    return invalid


def _first(results: list[Result], kind: str) -> Result | None:
    return next((r for r in results if r.kind == kind), None)


def _scope_of(result: Result) -> str:
    if result.kind == "weekday":
        return result.spec["district"] or result.spec["region"] or "제주 전체"
    return " · ".join(result.spec["filters"].values())


def build_kpis(results: list[Result]) -> list[dict[str, str]]:
    trend, weekday, rank = _first(results, "trend"), _first(results, "weekday"), _first(results, "rank")
    kpis: list[dict[str, str]] = []
    if rank and rank.spec["metric"] == "growth":
        kpis.append({"label": f"전년 대비 증가율 1위 {rank.facts['dimension']}", "accent": "tangerine",
                     "value": f"{rank.facts['top_name']} ({signed(rank.facts['top_yoy'])})",
                     "sub": f"최저: {rank.facts['bottom_name']} ({signed(rank.facts['bottom_yoy'])})"})
    if trend:
        facts = trend.facts
        kpis.append({"label": "분석 기간 최고 소비 시기", "accent": "tangerine" if not kpis else "leaf",
                     "value": month_label(facts["peak_month"]),
                     "sub": f"분석 기간 이용금액의 {facts['peak_share']}% · {money(facts['peak_amount'])}"})
    if weekday:
        facts = weekday.facts
        kpis.append({"label": "소비 집중 요일", "accent": "leaf",
                     "value": f"{'·'.join(facts['top_days'])}요일 ({facts['top_days_share']}%)",
                     "sub": f"최저 {facts['low_day']}요일 {facts['low_share']}% · {_scope_of(weekday)} 기준"})
    if trend:
        facts = trend.facts
        kpis.append({"label": "1인당 평균 이용금액", "accent": "charcoal", "value": won(facts["per_user"]),
                     "sub": f"전년 동기 대비 총 이용금액 {signed(facts['yoy_total'])}"})
    if rank and rank.spec["metric"] == "amount":
        kpis.append({"label": f"이용금액 1위 {rank.facts['dimension']}", "accent": "leaf",
                     "value": rank.facts["top_name"], "sub": f"전체의 {rank.facts['top_share']}% · 전년 대비 {signed(rank.facts['top_yoy'])}"})
    return kpis[:3]


def build_charts(results: list[Result]) -> dict[str, Any]:
    trend, weekday, rank = _first(results, "trend"), _first(results, "weekday"), _first(results, "rank")
    primary: dict[str, Any] | None = None
    if rank and (rank.spec["metric"] == "growth" or not trend):
        primary = {"kicker": f"Chart 01 · {rank.facts['dimension']}별 비교", "title": f"{rank.facts['dimension']}별 이용금액 및 전년 대비 증감률",
                   "labels": [r["name"] for r in rank.rows], "bars": [round(r["amount"] / 1e8, 1) for r in rank.rows],
                   "line": [r["yoy"] for r in rank.rows]}
    elif trend:
        primary = {"kicker": "Chart 01 · 월별 소비 추세", "title": f"{_scope_of(trend)} 월별 이용금액 및 전년 대비 증감률",
                   "labels": [short_month(r["month"]) for r in trend.rows],
                   "bars": [round(r["amount"] / 1e8, 1) for r in trend.rows], "line": [r["yoy"] for r in trend.rows]}
    secondary: dict[str, Any] | None = None
    if weekday:
        secondary = {"kicker": "Chart 02 · 실행 시점 분석", "title": f"{_scope_of(weekday)} 요일별 소비 비중", "unit": "%",
                     "labels": [r["weekday"] for r in weekday.rows], "data": [r["share"] for r in weekday.rows]}
    elif rank and trend:
        secondary = {"kicker": f"Chart 02 · {rank.facts['dimension']} 구성", "title": f"{rank.facts['dimension']}별 이용금액 비중", "unit": "%",
                     "labels": [r["name"] for r in rank.rows], "data": [r["share"] for r in rank.rows]}
    return {"primary": primary, "secondary": secondary}


def build_table(results: list[Result]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rank = _first(results, "rank")
    if rank:
        for position, row in enumerate(rank.rows[:4], start=1):
            rows.append({"label": f"{position}위 · {row['name']}", "amount": money(row["amount"]), "yoy": signed(row["yoy"]),
                         "average": f"1인당 {won(row['per_user'])}", "note": f"전체의 {row['share']}%", "highlight": position == 1})
    trend = _first(results, "trend")
    if trend:
        for position, row in enumerate(sorted(trend.rows, key=lambda r: r["amount"], reverse=True)[:3], start=1):
            rows.append({"label": f"{month_label(row['month'])} (소비 {position}위)", "amount": money(row["amount"]),
                         "yoy": signed(row["yoy"]), "average": f"1인당 {won(row['per_user'])}",
                         "note": f"분석 기간의 {row['share']}%", "highlight": position == 1})
    weekday = _first(results, "weekday")
    if weekday:
        for row in sorted(weekday.rows, key=lambda r: r["amount"], reverse=True)[:2]:
            rows.append({"label": f"{row['weekday']}요일", "amount": money(row["amount"]), "yoy": "해당 없음",
                         "average": f"건당 {won(row['per_count'])}", "note": f"주간 소비의 {row['share']}% · {_scope_of(weekday)} 기준",
                         "highlight": False})
    return rows


def build_limitations(results: list[Result], store: DataStore, notices: list[str]) -> list[str]:
    items = list(notices)
    if store.is_sample:
        items.insert(0, "현재 결과는 합성 샘플 데이터로 계산했으며 실제 제주 관광 통계가 아닙니다.")
    items.append("카드 이용 내역만 분석하므로 현금 등 다른 결제 수단은 반영되지 않습니다.")
    trend, weekday = _first(results, "trend"), _first(results, "weekday")
    if trend and weekday:
        items.append("요일별 데이터에는 업종·연령·성별이 없어 요일 비중은 해당 지역 전체 소비 기준입니다.")
        first, last = trend.rows[0]["month"], trend.rows[-1]["month"]
        if weekday.facts["period"] != f"{first} ~ {last}":
            items.append(f"월별 분석 기간({first} ~ {last})과 요일별 분석 기간({weekday.facts['period']})이 다릅니다.")
    if weekday and weekday.spec["region"] and not store.is_sample:
        items.append(f"{weekday.spec['region']} 요일 비중은 제공되는 지구 중 {weekday.spec['region']} 구도심 기준입니다.")
    if not store.is_sample:
        items.append(f"제공 데이터의 수록 기간은 {store.period}이며 최근 소비 동향을 반영하지 않습니다.")
    if any(c["status"] == "warning" for r in results for c in r.checks):
        items.append("일부 결과는 표본이 적어 변동성이 클 수 있습니다.")
    items.append("실행 제안은 소비 패턴에 근거한 참고 자료이며 매출 효과를 보장하지 않습니다.")
    return items


def condition_tags(results: list[Result]) -> list[dict[str, str]]:
    tags: list[dict[str, str]] = []
    source = next((r for r in results if r.kind != "weekday"), results[0])
    if source.kind == "weekday":
        tags.append({"label": f"지역: {_scope_of(source)}", "type": "leaf"})
    else:
        for key, value in source.spec["filters"].items():
            tags.append({"label": f"{FILTER_LABELS[key]}: {value}", "type": "tangerine" if key in ("age", "gender") else "leaf"})
    tags.append({"label": f"기간: 최근 {source.spec['months']}개월", "type": "gray"})
    return tags


def build_payload(question: str, title: str, summary: str, intent: str, actions: list[dict[str, str]],
                  results: list[Result], calls: list[str], store: DataStore, mode: str,
                  notices: list[str] | None = None) -> dict[str, Any]:
    checks = [{"result": r.id, **c} for r in results for c in r.checks]
    passed = sum(1 for c in checks if c["status"] == "pass")
    warnings = sum(1 for c in checks if c["status"] == "warning")
    filters =" / ".join(_scope_of(r) or "전체" for r in results)
    return {
        "title": title, "question": question, "summary": summary, "mode": mode,
        "meta": f"분석 기준: {filters}", "tags": condition_tags(results),
        "kpis": build_kpis(results), "charts": build_charts(results), "table": build_table(results),
        "actions": actions[:4], "limitations": build_limitations(results, store, notices or []),
        "verification": {"passed": passed, "warnings": warnings, "total": len(checks), "items": checks},
        "data": {"source": store.source, "period": store.period, "isSample": store.is_sample},
        "log": {"intent": intent, "tools": calls, "filters": filters,
                "validation": f"검증 {len(checks)}건 중 통과 {passed}건, 경고 {warnings}건"},
    }
