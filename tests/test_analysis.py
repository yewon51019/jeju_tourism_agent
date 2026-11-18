import pandas as pd
import pytest

from src.data_pipeline import DataError, DataStore, preprocess_monthly, preprocess_weekday
from src.tools.analysis import AnalysisError, Analyzer


@pytest.fixture
def analyzer():
    monthly = pd.DataFrame(
        [
            ("2023-01", "A", "제주시", "관광객", 10, 100),
            ("2023-01", "B", "제주시", "관광객", 10, 50),
            ("2023-01", "C", "서귀포시", "관광객", 10, 0),
            ("2024-01", "B", "제주시", "관광객", 10, 100),
            ("2024-01", "A", "제주시", "관광객", 15, 150),
            ("2024-01", "C", "서귀포시", "관광객", 5, 150),
            ("2024-01", "A", "제주시", "거주민", 100, 900),
            ("2024-02", "A", "제주시", "관광객", 20, 100),
        ],
        columns=["기준연월", "테마", "시군구", "관광객구분", "이용자수", "이용금액"],
    )
    weekday = pd.DataFrame(
        [
            ("2024-01", "일", "함덕해변", "제주시", 6, 8, 40),
            ("2024-01", "토", "중문관광단지", "서귀포시", 9, 10, 100),
            ("2024-01", "토", "연동상권", "제주시", 3, 6, 30),
            ("2024-01", "월", "연동상권", "제주시", 2, 5, 20),
            ("2024-01", "월", "함덕해변", "제주시", 1, 2, 10),
        ],
        columns=["기준연월", "요일", "지구", "시군구", "이용자수", "이용횟수", "이용금액"],
    )
    return Analyzer(DataStore(monthly=monthly, weekday=weekday, is_sample=True))


def test_trend_monthly_growth_and_shares(analyzer):
    result = analyzer.trend(months=2)
    assert result.spec["filters"] == {"visitor": "관광객"}
    assert result.rows == [
        {"month": "2024-01", "amount": 400, "users": 30, "per_user": 13,
         "yoy": 166.7, "share": 80.0},
        {"month": "2024-02", "amount": 100, "users": 20, "per_user": 5,
         "yoy": None, "share": 20.0},
    ]
    assert result.facts["total_amount"] == 500
    assert result.facts["total_users"] == 50
    assert result.facts["per_user"] == 10
    assert result.facts["yoy_total"] is None
    assert result.facts["top3_share"] == 100.0
    assert sum(row["share"] for row in result.rows) == 100.0


def test_trend_zero_prior_amount(analyzer):
    result = analyzer.trend({"theme": "C"}, months=2)
    assert result.rows[0]["month"] == "2024-01"
    assert result.rows[0]["amount"] == 150
    assert result.rows[0]["yoy"] is None


def test_trend_explicit_visitor_overrides_default(analyzer):
    result = analyzer.trend({"visitor": "거주민"}, months=2)
    assert result.facts["total_amount"] == 900


@pytest.mark.parametrize(
    ("metric", "expected"),
    [
        ("amount", [("A", 150, 37.5, 50.0), ("C", 150, 37.5, None),
                    ("B", 100, 25.0, 100.0)]),
        ("growth", [("B", 100, 25.0, 100.0), ("A", 150, 37.5, 50.0),
                    ("C", 150, 37.5, None)]),
    ],
)
def test_rank_amount_tie_and_growth_with_undefined_yoy(analyzer, metric, expected):
    # The region-wide January comparison has complete prior-month coverage.
    # Remove February from the store so a one-month window selects January.
    analyzer.store.monthly = analyzer.store.monthly.query("기준연월 != '2024-02'")
    result = analyzer.rank("테마", metric=metric, months=1)
    assert [(row["name"], row["amount"], row["share"], row["yoy"])
            for row in result.rows] == expected
    assert result.facts["total_amount"] == 400
    assert sum(row["share"] for row in result.rows) == 100.0


def test_rank_missing_prior_month(analyzer):
    assert analyzer.rank("테마", months=1).rows[0]["yoy"] is None
    with pytest.raises(AnalysisError, match="전년"):
        analyzer.rank("테마", metric="growth", months=1)


@pytest.mark.parametrize(
    ("filters", "message"),
    [({"district": "연동상권"}, "district"), ({"theme": "unknown"}, "unknown")],
)
def test_trend_rejects_invalid_filters(analyzer, filters, message):
    with pytest.raises(AnalysisError, match=message):
        analyzer.trend(filters)


def test_valid_filters_with_no_matching_rows(analyzer):
    filters = {"theme": "B", "region": "서귀포시"}
    with pytest.raises(AnalysisError, match="데이터가 없습니다"):
        analyzer.trend(filters)
    with pytest.raises(AnalysisError, match="데이터가 없습니다"):
        analyzer.rank("테마", filters)


def test_weekday_region_and_district(analyzer):
    region = analyzer.weekday(region="제주시", months=2)
    assert [row["weekday"] for row in region.rows] == ["월", "화", "수", "목", "금", "토", "일"]
    assert [row["amount"] for row in region.rows] == [30, 0, 0, 0, 0, 30, 40]
    assert [row["share"] for row in region.rows] == [30, 0, 0, 0, 0, 30, 40]
    assert sum(row["share"] for row in region.rows) == 100.0
    assert region.facts["total_amount"] == 100
    assert region.facts["total_count"] == 21
    assert region.facts["weekend_share"] == 70.0
    assert region.facts["weekday_share"] == 30.0

    district = analyzer.weekday(district="연동상권", region="서귀포시", months=2)
    assert district.spec["region"] is None
    assert [row["amount"] for row in district.rows] == [20, 0, 0, 0, 0, 30, 0]
    assert district.facts["total_amount"] == 50
    assert district.facts["weekend_share"] == 60.0


def test_weekday_invalid_district_and_empty_window(analyzer):
    with pytest.raises(AnalysisError, match="unknown"):
        analyzer.weekday(district="unknown", months=2)
    with pytest.raises(AnalysisError, match="요일별 데이터가 없습니다"):
        analyzer.weekday(region="없는지역", months=1)


def test_weekday_uses_its_own_latest_months(analyzer):
    # The weekday dataset ends earlier than the monthly dataset in the hub data.
    assert analyzer.weekday(region="제주시", months=1).facts["period"] == "2024-01 ~ 2024-01"


def test_weekday_zero_transaction_count(analyzer):
    analyzer.store.weekday = analyzer.store.weekday.assign(이용횟수=0)
    result = analyzer.weekday(district="연동상권", months=2)
    assert result.facts["total_count"] == 0
    assert result.facts["per_count"] == 0


@pytest.mark.parametrize("kind", ["trend", "rank", "weekday"])
def test_verify_detects_tampered_amount_and_warns_for_low_sample(analyzer, kind):
    if kind == "rank":
        result = analyzer.rank("테마", months=2)
    elif kind == "weekday":
        result = analyzer.weekday(region="제주시", months=2)
    else:
        result = analyzer.trend(months=2)

    verified = analyzer.verify(result.id)
    assert verified.verified
    assert {check["name"]: check["status"] for check in verified.checks} == {
        "원본 재계산": "pass",
        "조건 일치": "pass",
        "비중 합계": "pass",
        "표본 크기": "warning",
    }
    result.rows[0]["amount"] += 1
    verified = analyzer.verify(result.id)
    assert not verified.verified
    assert {check["name"]: check["status"] for check in verified.checks} == {
        "원본 재계산": "fail",
        "조건 일치": "pass",
        "비중 합계": "pass",
        "표본 크기": "warning",
    }


def test_preprocess_monthly_aliases_and_cleaning():
    first = ("2024/01", " 해변 ", "식음료", "제주시", "동부", "관광객", "20", " M ", "1,200", "24,000")
    second = ("202402", "시장", "소매", "서귀포시", "서부", "관광객", "30대", "여", "2,000", "30,000")
    frame = pd.DataFrame(
        [first, first, (*first[:-1], None), second],
        columns=[" 년월 ", "테마명", "업종명", "시군구명", "지역구분명", "관광객구분명",
                 "연령", "성별", "이용자 수", "이용 금액"],
    )
    quality = []
    result = preprocess_monthly(frame, quality)
    assert result.to_dict("records") == [
        {"기준연월": "2024-01", "테마": "해변", "업종": "식음료", "시군구": "제주시",
         "지역구분": "동부", "관광객구분": "관광객", "연령대": "20대", "성별": "남성",
         "이용자수": 1200, "이용금액": 24000},
        {"기준연월": "2024-02", "테마": "시장", "업종": "소매", "시군구": "서귀포시",
         "지역구분": "서부", "관광객구분": "관광객", "연령대": "30대", "성별": "여성",
         "이용자수": 2000, "이용금액": 30000},
    ]
    assert len(quality) == 1


def test_preprocess_weekday_aliases_cleaning_and_date_based_weekday():
    monday = ("2024/01/01", " 연동상권 ", "일", "1,000", "1,200", "30,000")
    saturday = ("20240106", "중문관광단지", "월", "2,000", "2,500", "50,000")
    frame = pd.DataFrame(
        [monday, monday, (*monday[:-1], None), saturday],
        columns=["기준일자", "지구명", "요일", "이용자 수", "이용건수", "이용 금액"],
    )
    quality = []
    result = preprocess_weekday(frame, quality)
    assert result.to_dict("records") == [
        {"날짜": "2024-01-01", "기준연월": "2024-01", "지구": "연동상권", "요일": "월",
         "시군구": "제주시", "이용자수": 1000, "이용횟수": 1200, "이용금액": 30000},
        {"날짜": "2024-01-06", "기준연월": "2024-01", "지구": "중문관광단지", "요일": "토",
         "시군구": "서귀포시", "이용자수": 2000, "이용횟수": 2500, "이용금액": 50000},
    ]
    assert len(quality) == 1


@pytest.mark.parametrize("preprocess", [preprocess_monthly, preprocess_weekday])
def test_preprocess_rejects_missing_amount_column(preprocess):
    frame = pd.DataFrame(columns=[
        "기준연월", "테마", "업종", "시군구", "지역구분", "관광객구분", "연령대", "성별",
        "이용자수", "날짜", "지구", "요일", "이용횟수",
    ])
    with pytest.raises(DataError, match="이용금액"):
        preprocess(frame, [])
