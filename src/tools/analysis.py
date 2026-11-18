"""수치 계산과 검증을 담당한다. LLM은 이 모듈의 결과만 인용할 수 있다."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..data_pipeline import WEEKDAY_NAMES, DataStore

FILTER_COLUMNS = {
    "region": "시군구", "theme": "테마", "industry": "업종",
    "age": "연령대", "gender": "성별", "visitor": "관광객구분",
}
FILTER_LABELS = {
    "region": "지역", "theme": "테마", "industry": "업종",
    "age": "연령대", "gender": "성별", "visitor": "구분",
}
DIMENSIONS = {"시군구", "테마", "업종", "연령대", "성별"}
MIN_USERS = 1000  # 이 값보다 이용자가 적은 분석은 표본 부족 경고를 표시한다.
TOLERANCE = 1e-6


class AnalysisError(ValueError):
    """분석 조건이 데이터와 맞지 않을 때 발생한다."""


@dataclass
class Result:
    id: str
    kind: str
    spec: dict[str, Any]
    rows: list[dict[str, Any]]
    facts: dict[str, Any]
    checks: list[dict[str, Any]] = field(default_factory=list)

    @property
    def verified(self) -> bool:
        return bool(self.checks) and all(c["status"] != "fail" for c in self.checks)

    def brief(self) -> dict[str, Any]:
        return {"result_id": self.id, "kind": self.kind, "spec": self.spec, "facts": self.facts, "rows": self.rows}


def growth(current: float, previous: float) -> float | None:
    return None if not previous else round((current / previous - 1) * 100, 1)


def share(part: float, whole: float) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


def shift_year(month: str, years: int = 1) -> str:
    return f"{int(month[:4]) - years}{month[4:]}"


class Analyzer:
    def __init__(self, store: DataStore) -> None:
        self.store = store
        self.results: dict[str, Result] = {}

    def _save(self, kind: str, spec: dict, rows: list[dict], facts: dict) -> Result:
        result = Result(f"r{len(self.results) + 1}", kind, spec, rows, facts)
        self.results[result.id] = result
        return result

    def get(self, result_id: str) -> Result:
        if result_id not in self.results:
            raise AnalysisError(f"분석 결과 {result_id}를 찾을 수 없습니다. 먼저 분석 도구를 실행해 주세요.")
        return self.results[result_id]

    def _clean_filters(self, filters: dict | None) -> dict[str, str]:
        cleaned: dict[str, str] = {}
        for key, value in (filters or {}).items():
            if value in (None, "", "전체"):
                continue
            if key not in FILTER_COLUMNS:
                raise AnalysisError(f"지원하지 않는 조건입니다: {key}")
            available = self.store.values(FILTER_COLUMNS[key])
            if value not in available:
                raise AnalysisError(
                    f"{FILTER_LABELS[key]} 조건 '{value}'는 데이터에 없습니다. 사용 가능한 값: {', '.join(available)}"
                )
            cleaned[key] = value
        cleaned.setdefault("visitor", "관광객" if "관광객" in self.store.values("관광객구분") else self.store.values("관광객구분")[0])
        return cleaned

    def _filtered(self, filters: dict[str, str]) -> pd.DataFrame:
        frame = self.store.monthly
        for key, value in filters.items():
            frame = frame[frame[FILTER_COLUMNS[key]] == value]
        return frame

    def _window(self, months: int) -> list[str]:
        if not 1 <= int(months) <= 36:
            raise AnalysisError("분석 기간은 1~36개월로 지정해 주세요.")
        return self.store.months[-int(months):]

    def trend(self, filters: dict | None = None, months: int = 12) -> Result:
        """월별 이용금액과 전년 동월 대비 증감률을 계산한다."""
        cleaned = self._clean_filters(filters)
        window = self._window(months)
        frame = self._filtered(cleaned)
        grouped = frame.groupby("기준연월")[["이용금액", "이용자수"]].sum()
        rows = []
        for month in window:
            amount = float(grouped["이용금액"].get(month, 0))
            users = float(grouped["이용자수"].get(month, 0))
            previous = float(grouped["이용금액"].get(shift_year(month), 0))
            rows.append({"month": month, "amount": amount, "users": users,
                         "per_user": round(amount / users) if users else 0, "yoy": growth(amount, previous)})
        total = sum(r["amount"] for r in rows)
        if not total:
            raise AnalysisError("선택한 조건에 해당하는 데이터가 없습니다.")
        for row in rows:
            row["share"] = share(row["amount"], total)
        ordered = sorted(rows, key=lambda r: r["amount"], reverse=True)
        users = sum(r["users"] for r in rows)
        previous_total = sum(float(grouped["이용금액"].get(shift_year(m), 0)) for m in window)
        facts = {
            "total_amount": total, "total_users": users, "per_user": round(total / users) if users else 0,
            "yoy_total": growth(total, previous_total) if all(shift_year(m) in grouped.index for m in window) else None,
            "peak_month": ordered[0]["month"], "peak_amount": ordered[0]["amount"], "peak_share": ordered[0]["share"],
            "top3_months": [r["month"] for r in ordered[:3]],
            "top3_share": round(sum(r["share"] for r in ordered[:3]), 1),
            "low_month": ordered[-1]["month"], "low_share": ordered[-1]["share"],
        }
        return self._save("trend", {"filters": cleaned, "months": int(months)}, rows, facts)

    def rank(self, dimension: str, filters: dict | None = None, metric: str = "amount", months: int = 12) -> Result:
        """지역·테마·업종·고객층의 순위와 전년 동기 대비 증감률을 계산한다."""
        if dimension not in DIMENSIONS:
            raise AnalysisError(f"순위 기준은 {', '.join(sorted(DIMENSIONS))} 중 하나여야 합니다.")
        if metric not in ("amount", "growth"):
            raise AnalysisError("순위 지표는 amount 또는 growth여야 합니다.")
        cleaned = self._clean_filters(filters)
        window = self._window(months)
        previous_window = [shift_year(m) for m in window]
        frame = self._filtered(cleaned)
        current = frame[frame["기준연월"].isin(window)].groupby(dimension)[["이용금액", "이용자수"]].sum()
        previous = frame[frame["기준연월"].isin(previous_window)].groupby(dimension)["이용금액"].sum()
        total = float(current["이용금액"].sum())
        if not total:
            raise AnalysisError("선택한 조건에 해당하는 데이터가 없습니다.")
        monthly = frame.groupby([dimension, "기준연월"])["이용금액"].sum().to_dict()

        def comparable(name: Any) -> bool:
            """이용 실적이 있는 모든 달에 전년 같은 달 실적이 있어야 증감률을 비교할 수 있다."""
            active = [m for m in window if monthly.get((name, m), 0) > 0]
            return bool(active) and all(monthly.get((name, shift_year(m)), 0) > 0 for m in active)

        rows = [{
            "name": str(name), "amount": float(row["이용금액"]), "users": float(row["이용자수"]),
            "share": share(float(row["이용금액"]), total),
            "per_user": round(row["이용금액"] / row["이용자수"]) if row["이용자수"] else 0,
            "yoy": growth(float(row["이용금액"]), float(previous.get(name, 0))) if comparable(name) else None,
        } for name, row in current.iterrows()]
        compared = [r for r in rows if r["yoy"] is not None]
        if metric == "growth":
            if not compared:
                raise AnalysisError("전년 동기 데이터가 없어 증가율 순위를 계산할 수 없습니다.")
            rows.sort(key=lambda r: (r["yoy"] is not None, r["yoy"] or 0), reverse=True)
            first, last = rows[0], min(compared, key=lambda r: r["yoy"])
        else:
            rows.sort(key=lambda r: r["amount"], reverse=True)
            first, last = rows[0], rows[-1]
        facts = {"dimension": dimension, "metric": metric, "total_amount": total,
                 "total_users": float(current["이용자수"].sum()), "top_name": first["name"],
                 "top_share": first["share"], "top_yoy": first["yoy"], "bottom_name": last["name"],
                 "bottom_yoy": last["yoy"]}
        spec = {"dimension": dimension, "filters": cleaned, "metric": metric, "months": int(months)}
        return self._save("rank", spec, rows, facts)

    def weekday(self, district: str | None = None, region: str | None = None, months: int = 12) -> Result:
        """지구 또는 시군구의 요일별 이용금액 비중을 계산한다."""
        window = self._window(months)
        frame = self.store.weekday[self.store.weekday["기준연월"].isin(window)]
        if district:
            if district not in self.store.values("지구"):
                raise AnalysisError(f"지구 '{district}'는 데이터에 없습니다. 사용 가능한 값: {', '.join(self.store.values('지구'))}")
            frame = frame[frame["지구"] == district]
        elif region and region != "전체":
            frame = frame[frame["시군구"] == region]
        if frame.empty:
            raise AnalysisError("선택한 조건에 해당하는 요일별 데이터가 없습니다.")
        grouped = frame.groupby("요일")[["이용금액", "이용횟수", "이용자수"]].sum()
        total = float(grouped["이용금액"].sum())
        rows = []
        for name in WEEKDAY_NAMES:
            amount = float(grouped["이용금액"].get(name, 0))
            count = float(grouped["이용횟수"].get(name, 0))
            rows.append({"weekday": name, "amount": amount, "count": count,
                         "users": float(grouped["이용자수"].get(name, 0)), "share": share(amount, total),
                         "per_count": round(amount / count) if count else 0})
        ordered = sorted(rows, key=lambda r: r["amount"], reverse=True)
        weekend = sum(r["amount"] for r in rows if r["weekday"] in ("토", "일"))
        total_count = float(grouped["이용횟수"].sum())
        facts = {"total_amount": total, "total_count": total_count,
                 "total_users": float(grouped["이용자수"].sum()),
                 "per_count": round(total / total_count) if total_count else 0,
                 "top_days": [r["weekday"] for r in ordered[:2]],
                 "top_days_share": round(ordered[0]["share"] + ordered[1]["share"], 1),
                 "low_day": ordered[-1]["weekday"], "low_share": ordered[-1]["share"],
                 "weekend_share": share(weekend, total), "weekday_share": share(total - weekend, total)}
        spec = {"district": district, "region": None if district else region, "months": int(months)}
        return self._save("weekday", spec, rows, facts)

    def verify(self, result_id: str) -> Result:
        """pandas 집계와 별개로 원본 행을 직접 합산해 결과를 대조한다."""
        result = self.get(result_id)
        recomputed, matched, sample_users = {
            "trend": self._recompute_trend, "rank": self._recompute_rank, "weekday": self._recompute_weekday,
        }[result.kind](result)
        key = {"trend": "month", "rank": "name", "weekday": "weekday"}[result.kind]
        mismatches = [r[key] for r in result.rows if abs(recomputed.get(r[key], 0.0) - r["amount"]) > TOLERANCE]
        shares = sum(r["share"] for r in result.rows) if result.kind != "trend" or result.rows else 0
        checks = [
            {"name": "원본 재계산", "status": "fail" if mismatches else "pass",
             "detail": f"{len(result.rows)}개 항목 중 {len(result.rows) - len(mismatches)}개 일치"},
            {"name": "조건 일치", "status": "pass" if matched else "fail", "detail": f"조건에 해당하는 원본 {matched:,}행"},
            {"name": "비중 합계", "status": "pass" if abs(shares - 100) <= 1.0 else "fail", "detail": f"비중 합계 {shares:.1f}%"},
            {"name": "표본 크기", "status": "pass" if sample_users >= MIN_USERS else "warning",
             "detail": f"누적 이용자 {sample_users:,.0f}명 (기준 {MIN_USERS:,}명)"},
        ]
        result.checks = checks
        return result

    def _matching_rows(self, filters: dict[str, str], months: set[str]):
        columns = {FILTER_COLUMNS[k]: v for k, v in filters.items()}
        for row in self.store.monthly.to_dict("records"):
            if row["기준연월"] in months and all(row[c] == v for c, v in columns.items()):
                yield row

    def _recompute_trend(self, result: Result):
        totals: dict[str, float] = defaultdict(float)
        matched, users = 0, 0.0
        months = {r["month"] for r in result.rows}
        for row in self._matching_rows(result.spec["filters"], months):
            totals[row["기준연월"]] += row["이용금액"]
            users += row["이용자수"]
            matched += 1
        return totals, matched, users

    def _recompute_rank(self, result: Result):
        totals: dict[str, float] = defaultdict(float)
        matched, users = 0, 0.0
        months = set(self._window(result.spec["months"]))
        for row in self._matching_rows(result.spec["filters"], months):
            totals[str(row[result.spec["dimension"]])] += row["이용금액"]
            users += row["이용자수"]
            matched += 1
        return totals, matched, users

    def _recompute_weekday(self, result: Result):
        totals: dict[str, float] = defaultdict(float)
        matched, users = 0, 0.0
        months = set(self._window(result.spec["months"]))
        district, region = result.spec["district"], result.spec["region"]
        for row in self.store.weekday.to_dict("records"):
            if row["기준연월"] not in months or (district and row["지구"] != district):
                continue
            if region and region != "전체" and row["시군구"] != region:
                continue
            totals[row["요일"]] += row["이용금액"]
            users += row["이용자수"]
            matched += 1
        return totals, matched, users
