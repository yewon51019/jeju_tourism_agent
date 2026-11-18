"""작은 수작업 기대값으로 집계 및 검증 경계를 확인한다."""

from pathlib import Path
import sys

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jeju_agent import TOOL_SCHEMAS, ToolRegistry
from jeju_agent.data import normalize_frame


def monthly_row(**changes):
    return dict(dict(year=2024, month=1, region="제주시", age="30대", gender="여성",
                     sector="음식점", theme="관광", users=40, amount=100), **changes)


@pytest.fixture
def engine(tmp_path):
    pd.DataFrame([
        monthly_row(), monthly_row(month=2, amount=300),
        monthly_row(year=2025, amount=150), monthly_row(year=2025, month=2, amount=600),
        monthly_row(region="서귀포시", amount=850),
    ]).to_csv(tmp_path / "monthly.csv", index=False)
    pd.DataFrame([
        dict(year=2025, month=1, district="중문", weekday="월", users=50, transactions=100, amount=200),
        dict(year=2025, month=1, district="중문", weekday="토", users=70, transactions=0, amount=0),
    ]).to_csv(tmp_path / "weekday.csv", index=False)
    return ToolRegistry(False, data_dir=tmp_path, output_dir=tmp_path / "outputs")


def test_query_independent_expected(engine):
    result = engine.execute("query_spending", {"filters": {"region": "제주시"}, "group_by": ["year"]})
    assert result["ok"]
    assert result["totals"] == {"users_sum": 160.0, "amount": 1150.0}
    assert [r["amount"] for r in result["rows"]] == [400, 750]
    assert result["rows"][0]["amount_per_user"] == 5
    assert result["rows"][0]["share_pct"] == pytest.approx(400 / 1150 * 100)
    assert engine.execute("verify_result", {"result_id": result["result_id"]})["passed"]


def test_rank_and_trend(engine):
    ranked = engine.execute("rank_segments", {"group_by": "region"})
    assert [r["amount"] for r in ranked["rows"]] == [1150, 850]
    assert ranked["rows"][0]["share_pct"] == pytest.approx(57.5)
    trend = engine.execute("analyze_trend", {"filters": {"region": "제주시"}})
    assert [r["yoy_pct"] for r in trend["rows"]] == [None, None, 50, 100]
    for result in [ranked, trend]:
        assert engine.verify_result(result["result_id"])["passed"]
    # 출력 기간은 유지하되 기준연도는 같은 비기간 조건으로 별도 조회한다.
    recent = engine.analyze_trend({"year": 2025, "region": "제주시"})
    assert [r["year"] for r in recent["rows"]] == [2025, 2025]
    assert [r["yoy_pct"] for r in recent["rows"]] == [50, 100]
    assert engine.verify_result(recent["result_id"])["passed"]
    uneven = engine.analyze_trend({"year": 2025})
    assert uneven["rows"][0]["yoy_pct"] is None
    assert uneven["rows"][0]["yoy_status"] == "unequal_segment_coverage"


@pytest.mark.parametrize("name,args", [
    ("query_spending", {"dataset": "weekday", "filters": {"age": "30대"}}),
    ("query_spending", {"filters": {"district": "중문"}}),
    ("query_spending", {"filters": {"year": True}}),
    ("query_spending", {"filters": {"month": 13}}),
    ("query_spending", {"filters": {"year": []}}),
    ("query_spending", {"filters": {"year": {"min": 2024}}}),
    ("query_spending", {"group_by": "region"}),
    ("query_spending", {"group_by": ["region", "region"]}),
    ("rank_segments", {"group_by": ["region"]}),
    ("analyze_trend", {"dataset": "weekday"}),
    ("verify_result", {"result_id": "missing"}),
    ("unsupported", {}),
])
def test_invalid_arguments(engine, name, args):
    assert engine.execute(name, args)["ok"] is False


def test_snapshot_and_tamper_gate(engine):
    args = {"filters": {"year": [2025]}, "group_by": ["region"]}
    result = engine.execute("query_spending", args)
    rid = result["result_id"]
    args["filters"]["year"].append(2024)
    result["rows"][0]["amount"] = -500
    assert engine.verify_result(rid)["passed"]  # 호출자 반환 사전은 별도 사본이다.
    engine.results[rid]["rows"][0]["amount"] = 1
    assert not engine.verify_result(rid)["passed"]
    assert not engine.execute("create_chart", {"result_id": rid})["ok"]
    assert not engine.execute("build_report", {"result_id": rid})["ok"]


def test_filter_tamper_and_source_snapshot(engine):
    result = engine.query_spending(filters={"year": 2025})
    rid = result["result_id"]
    engine.datasets["monthly"].raw.loc[:, "amount"] = 0
    assert engine.verify_result(rid)["passed"]
    engine.results[rid]["filters"]["year"] = 2024
    assert engine.verify_result(rid)["checks"]["filters_match"] is False


def test_independent_raw_recalculation_catches_wrong_working_frame(engine):
    engine.datasets["monthly"].frame.loc[:, "amount"] = 999
    result = engine.query_spending()
    assert not engine.verify_result(result["result_id"])["checks"]["independent_recalculation"]


def test_zero_denominators_and_empty(engine):
    result = engine.query_spending("weekday", {"weekday": "토", "year": 2025})
    assert result["rows"][0]["share_pct"] is None
    assert result["rows"][0]["amount_per_transaction"] is None
    assert engine.verify_result(result["result_id"])["passed"]
    empty = engine.query_spending(filters={"region": "없는지역"})
    assert empty["rows"] == []
    assert not engine.verify_result(empty["result_id"])["passed"]


def test_cleaning_preserves_raw_and_logs():
    raw = pd.DataFrame([monthly_row(), monthly_row(), monthly_row(users=None),
                        monthly_row(amount=-1), monthly_row(month=2, users=0, amount=0)])
    before = raw.copy(deep=True)
    clean, quality = normalize_frame(raw, "monthly")
    pd.testing.assert_frame_equal(raw, before)
    assert len(clean) == 2
    assert quality["missing_excluded"] == 1
    assert quality["duplicates_removed"] == 1
    assert quality["negative_excluded"] == 1
    assert quality["negative_row_indices"] == [3]


@pytest.mark.parametrize("change", [{"month": 0}, {"users": 1.5}, {"amount": float("inf")}, {"amount": "bad"}])
def test_bad_csv_schema(change):
    with pytest.raises((ValueError, TypeError)):
        normalize_frame(pd.DataFrame([monthly_row(**change)]), "monthly")
    with pytest.raises(ValueError, match="필수 열 누락"):
        normalize_frame(pd.DataFrame({"amount": [10]}), "monthly")


@pytest.mark.parametrize("users", [0, 29])
def test_suppression_and_no_complement_leak(tmp_path, users):
    pd.DataFrame([monthly_row(users=users), monthly_row(region="서귀포시")]).to_csv(tmp_path / "monthly.csv", index=False)
    registry = ToolRegistry(False, data_dir=tmp_path)
    result = registry.query_spending(group_by=["region"])
    assert result["suppressed"]
    assert result["rows"] == [] and result["totals"] == {}
    assert not registry.verify_result(result["result_id"])["passed"]
    assert not registry.execute("build_report", {"result_id": result["result_id"]})["ok"]


def test_metadata_report_and_chart(engine):
    catalog = engine.list_datasets()
    assert catalog["ok"] and len(catalog["datasets"]) == 2
    assert all(not d["source"]["confirmed"] for d in catalog["datasets"])
    assert catalog["datasets"][1]["period"] == {"start": "2025-01", "end": "2025-01"}
    result = engine.query_spending(group_by=["region"])
    report = engine.execute("build_report", {"result_id": result["result_id"], "commentary": "매출 효과 99%는 가설"})
    assert report["ok"]
    assert "미검증" in report["markdown"]
    assert "1150" in report["markdown"] and "850" in report["markdown"]
    assert Path(report["path"]).read_text(encoding="utf-8") == report["markdown"]
    pytest.importorskip("matplotlib")
    chart = engine.execute("create_chart", {"result_id": result["result_id"]})
    assert chart["ok"]
    assert Path(chart["path"]).read_bytes().startswith(b"\x89PNG")


def test_demo_is_explicit_and_schemas_complete():
    registry = ToolRegistry()
    catalog = registry.list_datasets()
    assert all(d["source"]["is_synthetic"] and not d["source"]["source_verified"] for d in catalog["datasets"])
    assert len(TOOL_SCHEMAS) == 7
    assert len({s["name"] for s in TOOL_SCHEMAS}) == 7
    result = registry.query_spending("weekday", {"year": 2025}, ["weekday"])
    assert result["rows"] and registry.verify_result(result["result_id"])["passed"]
    assert registry.query_spending(filters={"sector": "음식점", "age": "60대"})["row_count"] > 0


@pytest.mark.parametrize("baseline_amount,baseline_users,status", [
    (0, 40, "zero_baseline"), (100, 29, "insufficient_baseline_users"),
])
def test_yoy_zero_and_small_baseline(tmp_path, baseline_amount, baseline_users, status):
    pd.DataFrame([monthly_row(amount=baseline_amount, users=baseline_users),
                  monthly_row(year=2025, amount=200)]).to_csv(tmp_path / "monthly.csv", index=False)
    registry = ToolRegistry(False, data_dir=tmp_path)
    result = registry.analyze_trend({"year": 2025})
    assert result["rows"][0]["yoy_pct"] is None
    assert result["rows"][0]["yoy_status"] == status
    if status == "insufficient_baseline_users":
        assert result["rows"][0]["previous_year_amount"] is None
    assert registry.verify_result(result["result_id"])["passed"]


def test_real_mode_never_silently_falls_back(tmp_path):
    registry = ToolRegistry(False, data_dir=tmp_path)
    assert registry.list_datasets()["datasets"] == []
    assert not registry.execute("query_spending", {})["ok"]


def test_missing_prior_month_is_not_positional_shift(tmp_path):
    pd.DataFrame([monthly_row(month=2, amount=100),
                  monthly_row(year=2025, month=1, amount=200)]).to_csv(tmp_path / "monthly.csv", index=False)
    registry = ToolRegistry(False, data_dir=tmp_path)
    row = registry.analyze_trend({"year": 2025})["rows"][0]
    assert row["yoy_pct"] is None
    assert row["yoy_status"] == "missing_baseline"
