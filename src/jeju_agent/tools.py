"""검증 가능한 도구 API. LLM은 조건을 선택하고 수치는 이 모듈이 계산한다."""

from copy import deepcopy
from collections import Counter
import json
import math
from pathlib import Path
from uuid import uuid4

import pandas as pd

from .data import DIMENSIONS, METRICS, ROOT, load_datasets, normalize_frame

MIN_USERS = 30
LIMITATION = "users_sum은 집계 이용자수의 합이며 월간·연간 고유 관광객수가 아닙니다. 인당 지표도 이 합을 분모로 사용합니다."


def _schema(name: str, description: str, properties: dict, required: list | None = None) -> dict:
    return {"name": name, "description": description, "input_schema": {
        "type": "object", "properties": properties, "required": required or [], "additionalProperties": False}}


_dataset = {"type": "string", "enum": ["monthly", "weekday"], "default": "monthly"}
_filter_value = {"anyOf": [{"type": "string"}, {"type": "integer"},
                            {"type": "array", "minItems": 1, "items": {"type": ["string", "integer"]}}]}
_filters = {"type": "object", "properties": {
    key: _filter_value for key in dict.fromkeys(DIMENSIONS["monthly"] + DIMENSIONS["weekday"])},
    "additionalProperties": False}
_id = {"type": "string", "minLength": 1}
TOOL_SCHEMAS = [
    _schema("list_datasets", "데이터 차원·기간·출처·품질 확인. 월간/요일 데이터는 결합하지 않습니다.", {}),
    _schema("query_spending", "필터 후 합계·비중·집계 이용자당 금액 계산. users_sum은 고유인원이 아닙니다.",
            {"dataset": _dataset, "filters": _filters, "group_by": {"type": "array", "items": {"type": "string"}, "uniqueItems": True}}),
    _schema("analyze_trend", "월간 데이터의 연월별 금액과 전년 동월 대비 증감률. 기준연도는 같은 조건으로 별도 조회합니다.",
            {"filters": _filters}),
    _schema("rank_segments", "한 차원별 금액 내림차순 순위와 전체 필터 결과 대비 비중.",
            {"dataset": _dataset, "filters": _filters, "group_by": {"type": "string"}}, ["group_by"]),
    _schema("verify_result", "불변 입력과 원본 행으로 독립 재계산. 소규모 집단은 제공 차단.", {"result_id": _id}, ["result_id"]),
    _schema("create_chart", "검증을 통과한 분석 결과의 차트 파일 생성.",
            {"result_id": _id, "chart_type": {"type": "string", "enum": ["bar", "line"]}}, ["result_id"]),
    _schema("build_report", "검증된 결과로 수치 근거 보고서 생성. commentary는 미검증 의견으로 분리합니다.",
            {"result_id": _id, "result_ids": {"type": "array", "items": _id, "minItems": 1},
             "commentary": {"type": "string"}}),
]
TOOL_SCHEMAS[-1]["input_schema"]["anyOf"] = [{"required": ["result_id"]}, {"required": ["result_ids"]}]


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


class ToolRegistry:
    """execute가 공개 호출 경계이며 실패도 JSON 사전으로 반환한다.

    results는 UI용 캐시다. 별도 불변 JSON 스냅샷으로 캐시 변조를 탐지한다.
    """

    def __init__(self, demo: bool = True, *, data_dir: str | Path | None = None,
                 output_dir: str | Path | None = None):
        self.datasets = load_datasets(demo, data_dir)
        self.results: dict[str, dict] = {}
        self._snapshots: dict[str, str] = {}
        self._requests: dict[str, str] = {}
        self._raw = {name: ds.raw.copy(deep=True) for name, ds in self.datasets.items()}
        self._sources = {name: deepcopy(ds.source) for name, ds in self.datasets.items()}
        self._quality = {name: deepcopy(ds.quality) for name, ds in self.datasets.items()}
        self.output_dir = Path(output_dir) if output_dir is not None else ROOT / "outputs"

    def execute(self, name: str, arguments: dict) -> dict:
        if name not in {schema["name"] for schema in TOOL_SCHEMAS}:
            return {"ok": False, "error": f"지원하지 않는 도구: {name}"}
        if not isinstance(arguments, dict):
            return {"ok": False, "error": "arguments는 객체여야 합니다"}
        try:
            return deepcopy(getattr(self, name)(**deepcopy(arguments)))
        except (ValueError, TypeError, KeyError, OSError, ImportError, OverflowError) as exc:
            return {"ok": False, "error": str(exc)}

    def list_datasets(self) -> dict:
        items = []
        for name, ds in self.datasets.items():
            frame = ds.frame
            period = None
            if not frame.empty:
                dates = frame.year.astype(int).astype(str) + "-" + frame.month.astype(int).astype(str).str.zfill(2)
                period = {"start": dates.min(), "end": dates.max()}
            items.append({"id": name, "name": name, "dimensions": DIMENSIONS[name],
                          "metrics": METRICS[name], "period": period,
                          "values": {c: sorted(frame[c].unique().tolist()) for c in DIMENSIONS[name]},
                          "quality": deepcopy(self._quality[name]), "source": deepcopy(self._sources[name])})
        return {"ok": True, "datasets": items, "warnings": [LIMITATION,
                "요일 데이터에는 인구통계 차원이 없습니다. 월간 데이터와 결합할 수 없습니다."]}

    def _request(self, dataset: str, filters: dict | None, group_by: list, kind: str) -> dict:
        if dataset not in self.datasets:
            raise ValueError(f"사용 가능한 데이터셋이 아닙니다: {dataset}")
        filters = {} if filters is None else deepcopy(filters)
        if not isinstance(filters, dict) or not isinstance(group_by, list):
            raise ValueError("filters는 객체, group_by는 목록이어야 합니다")
        if any(not isinstance(c, str) for c in group_by) or len(set(group_by)) != len(group_by):
            raise ValueError("group_by는 중복 없는 차원 이름 목록이어야 합니다")
        unsupported = (set(filters) | set(group_by)) - set(DIMENSIONS[dataset])
        if unsupported:
            raise ValueError(f"{dataset}에서 지원하지 않는 차원: {sorted(unsupported)}")
        for key, value in filters.items():
            values = value if isinstance(value, list) else [value]
            if not values:
                raise ValueError("빈 필터 목록은 허용하지 않습니다")
            for item in values:
                if key in {"year", "month"}:
                    if type(item) is not int or not (1900 <= item <= 2200 if key == "year" else 1 <= item <= 12):
                        raise ValueError(f"{key}: 유효한 정수가 필요합니다")
                elif not isinstance(item, str) or not item.strip():
                    raise ValueError(f"{key}: 비어 있지 않은 문자열이 필요합니다")
        return {"dataset": dataset, "filters": filters, "group_by": deepcopy(group_by), "kind": kind}

    @staticmethod
    def _filter(frame: pd.DataFrame, filters: dict) -> pd.DataFrame:
        for key, value in filters.items():
            frame = frame.loc[frame[key].isin(value if isinstance(value, list) else [value])]
        return frame

    @staticmethod
    def _decorate(rows: list[dict], totals: dict, request: dict) -> list[dict]:
        for row in rows:
            row["share_pct"] = row["amount"] / totals["amount"] * 100 if totals["amount"] else None
            row["amount_per_user"] = row["amount"] / row["users_sum"] if row["users_sum"] else None
            if "transactions" in row:
                row["amount_per_transaction"] = row["amount"] / row["transactions"] if row["transactions"] else None
        if request["kind"] == "rank_segments":
            dimension = request["group_by"][0]
            rows.sort(key=lambda r: (-r["amount"], r[dimension]))
            previous = None
            rank = 0
            for position, row in enumerate(rows, 1):
                if row["amount"] != previous:
                    rank = position
                row["rank"] = rank
                previous = row["amount"]
        return rows

    def _trend_baselines(self, rows: list[dict], request: dict, independent: bool) -> None:
        """출력 연도와 별개로 동월·동일 세부집단의 기준연도를 조회한다."""
        frame = normalize_frame(self._raw["monthly"], "monthly")[0] if independent else self.datasets["monthly"].frame
        dimensions = [c for c in DIMENSIONS["monthly"] if c != "year"]
        filters = {k: v for k, v in request["filters"].items() if k != "year"}
        records = [r for r in frame.to_dict("records") if all(
            r[k] in (v if isinstance(v, list) else [v]) for k, v in filters.items())]
        for row in rows:
            current = [r for r in records if r["year"] == row["year"] and r["month"] == row["month"]]
            prior = [r for r in records if r["year"] == row["year"] - 1 and r["month"] == row["month"]]
            row["baseline_year"] = row["year"] - 1
            row["previous_year_amount"] = None
            row["yoy_pct"] = None
            if not prior:
                row["yoy_status"] = "missing_baseline"
                continue
            coverage = lambda data: Counter(tuple(r[c] for c in dimensions) for r in data)
            if coverage(current) != coverage(prior):
                row["yoy_status"] = "unequal_segment_coverage"
                continue
            if math.fsum(r["users"] for r in prior) < MIN_USERS:
                row["yoy_status"] = "insufficient_baseline_users"
                continue
            baseline = math.fsum(float(r["amount"]) for r in prior)
            row["previous_year_amount"] = baseline
            row["yoy_status"] = "ok" if baseline else "zero_baseline"
            row["yoy_pct"] = (row["amount"] - baseline) / baseline * 100 if baseline else None

    def _calculate(self, request: dict, independent: bool = False) -> tuple[list, dict, int]:
        name, groups = request["dataset"], request["group_by"]
        metrics = METRICS[name]
        if independent:
            # 검증 경로는 공개 캐시·집계 프레임을 읽지 않고 원본을 다시 정제한다.
            raw, _ = normalize_frame(self._raw[name], name)
            selected = [row for row in raw.to_dict("records") if all(
                row[key] in (value if isinstance(value, list) else [value])
                for key, value in request["filters"].items())]
            buckets: dict[tuple, list] = {}
            for row in selected:
                buckets.setdefault(tuple(row[c] for c in groups), []).append(row)
            def sums(records: list) -> dict:
                return {"users_sum" if c == "users" else c: math.fsum(float(r[c]) for r in records) for c in metrics}
            rows = [dict(zip(groups, key), **sums(records)) for key, records in sorted(buckets.items())]
            totals, count = sums(selected), len(selected)
        else:
            frame = self._filter(self.datasets[name].frame, request["filters"])
            totals = {"users_sum" if c == "users" else c: float(frame[c].sum()) for c in metrics}
            if groups:
                aggregated = frame.groupby(groups, as_index=False, sort=True)[metrics].sum()
                rows = aggregated.rename(columns={"users": "users_sum"}).to_dict("records")
            else:
                rows = [deepcopy(totals)] if not frame.empty else []
            count = len(frame)
        rows = self._decorate(rows, totals, request)
        if request["kind"] == "analyze_trend":
            self._trend_baselines(rows, request, independent)
        return rows, totals, count

    def _analyze(self, request: dict) -> dict:
        rows, totals, count = self._calculate(request)
        warnings = [LIMITATION, self._sources[request["dataset"]]["notice"]]
        suppressed = any(row["users_sum"] < MIN_USERS for row in rows)
        if suppressed:
            warnings.append("소규모 집단이 포함되어 수치를 차단했습니다. 더 넓은 범주로 재분석하세요.")
            # 합계로 비공개 집단을 역산하지 못하도록 결과 전체를 차단한다.
            rows, totals = [], {}
        if not count:
            warnings.append("조건에 맞는 데이터가 없습니다")
        quality = self._quality[request["dataset"]]
        if any(quality.get(k, 0) for k in ["missing_excluded", "duplicates_removed", "negative_excluded"]):
            warnings.append("결측·중복·음수 제외 이력이 있습니다. quality를 확인하세요.")
        result_id = uuid4().hex
        result = {"ok": True, "result_id": result_id, **deepcopy(request), "rows": rows,
                  "totals": totals, "row_count": count, "suppressed": suppressed,
                  "minimum_users": MIN_USERS, "warnings": warnings,
                  "source": deepcopy(self._sources[request["dataset"]]), "quality": deepcopy(quality)}
        self._requests[result_id] = _json(request)
        self._snapshots[result_id] = _json(result)
        self.results[result_id] = deepcopy(result)
        return deepcopy(result)

    def query_spending(self, dataset: str = "monthly", filters: dict | None = None,
                       group_by: list | None = None) -> dict:
        return self._analyze(self._request(dataset, filters, [] if group_by is None else group_by, "query_spending"))

    def analyze_trend(self, filters: dict | None = None) -> dict:
        return self._analyze(self._request("monthly", filters, ["year", "month"], "analyze_trend"))

    def rank_segments(self, group_by: str, dataset: str = "monthly", filters: dict | None = None) -> dict:
        if not isinstance(group_by, str):
            raise ValueError("순위 group_by는 단일 차원 문자열이어야 합니다")
        return self._analyze(self._request(dataset, filters, [group_by], "rank_segments"))

    def verify_result(self, result_id: str) -> dict:
        if result_id not in self._snapshots:
            raise ValueError("알 수 없는 분석 결과 ID")
        original = json.loads(self._snapshots[result_id])
        request = json.loads(self._requests[result_id])
        current = self.results.get(result_id)
        rows, totals, count = self._calculate(request, independent=True)
        cache_intact = _json(current) == self._snapshots[result_id]
        filters_match = isinstance(current, dict) and all(current.get(k) == v for k, v in request.items())
        enough = bool(rows) and all(row["users_sum"] >= MIN_USERS for row in rows)
        # 독립 합산의 부동소수점 덧셈 순서 차이만 허용한다.
        def equal(a: object, b: object) -> bool:
            if isinstance(a, dict) and isinstance(b, dict):
                return a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a)
            if isinstance(a, list) and isinstance(b, list):
                return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
            if type(a) in (float, int) and type(b) in (float, int):
                return math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-8)
            return a == b
        recalculated = count == original["row_count"] and (
            original["suppressed"] and not enough or
            equal(rows, original["rows"]) and equal(totals, original["totals"]))
        checks = {"cache_intact": cache_intact, "filters_match": filters_match,
                  "independent_recalculation": bool(recalculated), "minimum_users": enough}
        return {"ok": True, "result_id": result_id, "passed": all(checks.values()),
                "checks": checks, "warnings": original["warnings"], "minimum_users": MIN_USERS}

    def _verified(self, result_id: str) -> dict:
        verification = self.verify_result(result_id)
        if not verification["passed"]:
            raise ValueError(f"검증 미통과: {verification['checks']}")
        return json.loads(self._snapshots[result_id])

    def create_chart(self, result_id: str, chart_type: str = "bar") -> dict:
        if chart_type not in {"bar", "line"}:
            raise ValueError("chart_type은 bar 또는 line이어야 합니다")
        result = self._verified(result_id)
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib import font_manager, pyplot as plt
        font = "Malgun Gothic" if any(f.name == "Malgun Gothic" for f in font_manager.fontManager.ttflist) else "DejaVu Sans"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"chart_{uuid4().hex}.png"
        with plt.rc_context({"font.family": font, "axes.unicode_minus": False}):
            fig, ax = plt.subplots(figsize=(10, 5))
            try:
                labels = [" / ".join(str(row[c]) for c in result["group_by"]) or "전체" for row in result["rows"]]
                amounts = [row["amount"] for row in result["rows"]]
                getattr(ax, "bar" if chart_type == "bar" else "plot")(range(len(labels)), amounts)
                ax.set_xticks(range(len(labels)), labels, rotation=45, ha="right")
                ax.set_ylabel("이용금액 (정규화 원 단위)")
                ax.set_title("합성 데이터 예시" if result["source"]["is_synthetic"] else "로컬 CSV 분석 (출처 미확인)")
                fig.tight_layout()
                fig.savefig(path, dpi=140)
            finally:
                plt.close(fig)
        return {"ok": True, "result_id": result_id, "path": str(path.resolve())}

    def build_report(self, result_id: str | None = None, result_ids: list[str] | None = None,
                     commentary: str = "") -> dict:
        if result_id is not None:
            if result_ids is not None:
                raise ValueError("result_id와 result_ids 중 하나만 지정하세요")
            result_ids = [result_id]
        if not isinstance(result_ids, list) or not result_ids or any(not isinstance(i, str) for i in result_ids):
            raise ValueError("result_ids는 비어 있지 않은 ID 목록이어야 합니다")
        if not isinstance(commentary, str):
            raise ValueError("commentary는 문자열이어야 합니다")
        results = [self._verified(i) for i in result_ids]
        parts = ["# 제주 관광 소비 분석", "", LIMITATION,
                 "카드 소비 범위의 분석이며 현금·외국인 소비 및 인과 효과를 입증하지 않습니다."]
        for result in results:
            parts.extend(["", f"## {result['dataset']}", result["source"]["notice"],
                          "출처 메타데이터와 적용 조건:", "```json",
                          json.dumps({"source": result["source"], "filters": result["filters"],
                                      "quality": result["quality"]}, ensure_ascii=False, indent=2), "```",
                          "검증된 계산 결과 (users_sum은 중복 가능 합계):", "```json",
                          json.dumps({"totals": result["totals"], "rows": result["rows"]}, ensure_ascii=False, indent=2), "```"])
        if commentary:
            # 의견을 근거 수치와 혼합하지 않는다. 숫자 포함 의견도 미검증임을 명시한다.
            parts.extend(["", "## 작성자 의견 — 미검증, 계산 근거로 사용 금지",
                          *["> " + line for line in commentary.splitlines()]])
        markdown = "\n".join(parts) + "\n"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"report_{uuid4().hex}.md"
        path.write_text(markdown, encoding="utf-8")
        return {"ok": True, "path": str(path.resolve()), "markdown": markdown, "result_ids": result_ids}
