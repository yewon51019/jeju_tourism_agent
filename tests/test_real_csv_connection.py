"""실제 형식의 합성 CSV로 연결·모집단 분리·웹 응답을 검증한다."""
import csv
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from src.activate_data import activate
from src.data_pipeline import load_store
from src.hub_export import FIELDS, FILE_NAMES
from src.rule_engine import parse_question, run_rules
from src.tools.analysis import Analyzer
from src.tools.registry import describe_store


@pytest.fixture
def source(tmp_path):
    folder = tmp_path / "snapshot"
    folder.mkdir()
    rows = {
        "597": [{"sido": "제주도", "sigungu": "서귀포시", "cityGubun": "도심", "marketType": industry,
                 "userType": visitor, "ageGroup": "30대", "gender": gender, "dtYearMonth": "201812",
                 "userCount": 2000, "useCount": 2500, "useCost": amount}
                for industry, visitor, gender, amount in [("식음료", "내국인관광객", "여", 10000),
                                                          ("식음료", "내국인관광객", "남", 20000),
                                                          ("식음료", "제주도민", "여", 90000),
                                                          ("전체", "내국인관광객", "여", 999999)]],
        "608": [{"districtType": "상업지", "userType": visitor, "dtYearMonth": "201711", "dtWeek": day,
                 "userCount": 2000, "useCount": 3000, "useCost": amount}
                for visitor, day, amount in [("내국인관광객", "월", 100), ("내국인관광객", "토", 300),
                                             ("중국인관광객", "월", 90000)]],
    }
    receipt = {"query": {"startDate": "201701", "endDate": "201812"}, "datasets": {}}
    for dataset in rows:
        path = folder / FILE_NAMES[dataset]
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS[dataset])
            writer.writeheader()
            writer.writerows(rows[dataset])
        receipt["datasets"][dataset] = {"rows": len(rows[dataset]), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    (folder / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    return folder


def test_local_activation_filters_totals_and_weekday_population(source, tmp_path):
    target = tmp_path / "active"
    result = activate(source, target)
    assert result["monthly_rows"] == 3 and result["monthly_total_rows_removed"] == 1
    assert result["weekday_rows"] == 2 and result["weekday_other_visitors_excluded"] == 1
    store = load_store(target)
    analyzer = Analyzer(store)
    female = analyzer.trend({"region": "서귀포시", "age": "30대", "gender": "여성", "industry": "식음료"}, 1)
    assert female.facts["total_amount"] == 10000
    assert female.spec["filters"]["visitor"] == "내국인관광객"
    assert analyzer.trend({"visitor": "제주도민"}, 1).facts["total_amount"] == 90000
    weekday = analyzer.weekday(district="상업지", months=1)
    assert weekday.facts["total_amount"] == 400
    assert analyzer.verify(weekday.id).verified
    assert analyzer.rank("테마", months=1).facts["dimension"] == "업종"
    metadata = describe_store(store)
    assert metadata["datasets"]["weekday"]["grain"] == "월·요일·지구"
    assert metadata["datasets"]["weekday"]["period"] == "2017-11 ~ 2017-11"
    parsed = parse_question("상업지 요일별 소비 패턴 알려줘", None, store)
    assert "region" not in parsed.filters


def test_tampered_original_is_not_activated(source, tmp_path):
    path = source / FILE_NAMES["597"]
    path.write_text("changed", encoding="utf-8")
    target = tmp_path / "active"
    with pytest.raises(ValueError, match="해시"):
        activate(source, target)
    assert not target.exists()


def test_activation_never_overwrites_existing_data(source, tmp_path):
    target = tmp_path / "active"
    activate(source, target)
    before = (target / "card_monthly.csv").read_bytes()
    with pytest.raises(ValueError, match="이미"):
        activate(source, target)
    assert (target / "card_monthly.csv").read_bytes() == before


def test_sample_fixture_can_be_selected_even_with_real_files(source, tmp_path):
    target = tmp_path / "active"
    activate(source, target)
    assert load_store(target, sample_only=True).is_sample
    assert not load_store(target).is_sample


def test_web_reports_local_data_and_gender_filters(source, tmp_path, monkeypatch):
    from src import server

    target = tmp_path / "active"
    activate(source, target)
    store = load_store(target)
    monkeypatch.setattr(server, "get_store", lambda: store)
    monkeypatch.setenv("GEMINI_API_KEY", "")
    with TestClient(server.app, base_url="http://127.0.0.1:8501") as client:
        status = client.get("/api/status").json()
        assert status["dataMode"] == "local_csv" and not status["isSample"]
        assert status["monthlyRows"] == 3 and status["weekdayRows"] == 2
        response = client.post("/api/analyze", json={"question": "서귀포시 30대 여성 식음료 소비 추세 알려줘"})
        result = json.loads(response.text.splitlines()[-1])
    assert result["type"] == "report"
    assert not result["report"]["data"]["isSample"]
    assert any("성별: 여성" in tag["label"] for tag in result["report"]["tags"])
    assert any("개인별 여행 예산이 아닙니다" in a["desc"] for a in result["report"]["actions"])


def test_server_start_does_not_request_data(monkeypatch):
    import httpx
    from src import server

    def forbidden(*args, **kwargs):
        pytest.fail("서버 시작은 데이터 API를 호출하면 안 됩니다.")

    monkeypatch.setattr(httpx.Client, "get", forbidden)
    monkeypatch.setenv("OPEN_BROWSER", "0")
    monkeypatch.setenv("JEJU_HUB_PROJECT_KEY", "fake-key")
    calls = []
    monkeypatch.setattr(server.uvicorn, "run", lambda *args, **kwargs: calls.append(kwargs))
    server.main()
    assert calls[0]["host"] == "127.0.0.1"
