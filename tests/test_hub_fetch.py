"""제주데이터허브 API 응답 형식으로 다운로드와 분석 흐름을 검증한다."""
from __future__ import annotations

import importlib.util
from itertools import product
from pathlib import Path

import httpx
import pytest

from src.data_pipeline import load_store
from src.rule_engine import run_rules

SPEC = importlib.util.spec_from_file_location("fetch_hub_data", Path(__file__).parent.parent / "scripts" / "fetch_hub_data.py")
hub = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hub)

PROJECT_KEY = "project-key-for-test"
MONTHS = [f"{y}{m:02d}" for y, m in [(2017, m) for m in range(1, 13)] + [(2018, m) for m in range(1, 13)]]


def monthly_data():
    rows = []
    for month, region, market, age, gender in product(MONTHS, ["제주시", "서귀포시"], ["식음료", "숙박", "문화/레져", "전체"],
                                                      ["20대", "30대", "60대이상"], ["남", "여"]):
        base = 2000 if month.startswith("2018") else 1000
        rows.append({"sido": "제주도", "sigungu": region, "cityGubun": "도심", "marketType": market, "userType": "내국인관광객",
                     "ageGroup": age, "gender": gender, "dtYearMonth": month, "userCount": base, "useCount": base * 2,
                     "useCost": base * 50000})
    return rows


def weekday_data():
    return [{"districtType": district, "userType": "내국인관광객", "dtYearMonth": month, "dtWeek": day, "userCount": 5000,
             "useCount": 8000, "useCost": 300000000 if day == "토" else 100000000}
            for month, district, day in product(MONTHS[:11], ["상업지", "제주시 구도심", "서귀포시 구도심"], ["월", "화", "수", "목", "금", "토", "일"])]


def transport(monthly=None, weekday=None, status=200):
    monthly_rows, weekday_rows = monthly_data() if monthly is None else monthly, weekday_data() if weekday is None else weekday

    def handler(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status)
        rows = monthly_rows if hub.MONTHLY["key"] in request.url.path else weekday_rows
        number, limit = int(request.url.params["number"]), int(request.url.params["limit"])
        assert limit <= 100
        page = rows[(number - 1) * limit:number * limit]
        return httpx.Response(200, json={"totCnt": len(rows), "hasMore": number * limit < len(rows), "data": page})

    return httpx.MockTransport(handler)


@pytest.fixture
def store(tmp_path):
    hub.download(PROJECT_KEY, tmp_path, transport(), delay=0)
    return load_store(tmp_path, tmp_path / "unused")


def test_download_pages_all_rows_and_drops_total_rows(tmp_path):
    result = hub.download(PROJECT_KEY, tmp_path, transport(), delay=0)
    assert result == {"monthly": 24 * 2 * 3 * 3 * 2, "weekday": 11 * 3 * 7}
    assert "전체" not in (tmp_path / "card_monthly.csv").read_text(encoding="utf-8-sig")


def test_real_schema_is_loaded(store):
    assert not store.is_sample and store.period == "2017-01 ~ 2018-12"
    assert store.weekday_months[-1] == "2017-11"
    assert store.values("성별") == ["남성", "여성"]
    assert set(store.weekday[store.weekday["지구"] == "제주시 구도심"]["시군구"]) == {"제주시"}


@pytest.mark.parametrize("question", [
    "서귀포시에서 30대 관광객을 대상으로 식음료 프로모션을 하려면 언제가 좋을까?",
    "제주시 20대 여성 관광객의 카페·디저트 소비 추세는 어때?",
    "제주시 구도심의 요일별 소비 패턴을 주말과 평일로 비교해줘",
    "최근 1년 제주 전 지역에서 전년 대비 소비 증가율이 가장 높은 테마는?",
])
def test_example_questions_work_on_real_schema(store, question):
    event = list(run_rules(question, None, store))[-1]
    assert event["type"] == "report", event
    assert event["report"]["verification"]["passed"] > 0
    assert any("수록 기간" in item for item in event["report"]["limitations"])


def test_different_weekday_period_is_disclosed(store):
    report = list(run_rules("서귀포시 30대 식음료 프로모션 언제가 좋을까?", None, store))[-1]["report"]
    assert any("요일별 분석 기간(2016" in item or "요일별 분석 기간(2017" in item for item in report["limitations"])
    assert any("서귀포시 구도심 기준" in item for item in report["limitations"])


def test_saturday_share_is_calculated_from_month_weekday_rows(store):
    report = list(run_rules("제주시 구도심의 요일별 소비 패턴 알려줘", None, store))[-1]["report"]
    assert report["charts"]["secondary"]["data"][5] == 33.3


def test_failed_download_keeps_existing_files_and_hides_the_key(tmp_path):
    existing = tmp_path / "card_monthly.csv"
    existing.write_text("old", encoding="utf-8")
    with pytest.raises(hub.HubError) as error:
        hub.download(PROJECT_KEY, tmp_path, transport(status=403), delay=0)
    assert PROJECT_KEY not in str(error.value) and existing.read_text(encoding="utf-8") == "old"


def test_row_count_mismatch_is_rejected(tmp_path):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"totCnt": 5, "hasMore": False, "data": [monthly_data()[0]]})

    with pytest.raises(hub.HubError):
        hub.download(PROJECT_KEY, tmp_path, httpx.MockTransport(handler), delay=0)
