"""연결된 실제 CSV의 수치를 원본에서 독립 합산하고 웹 API를 오프라인 검증한다.

실행: python scripts/verify_real_csv.py
결과는 stdout으로 출력한다. 데이터·인증 설정 파일은 수정하지 않는다.
"""
from __future__ import annotations

import csv
from decimal import Decimal
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from check_offline import block_external_connections  # noqa: E402


def read_rows(name):
    with (ROOT / "data/exports/jeju_20261119" / name).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main():
    for key in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "JEJU_HUB_PROJECT_KEY"):
        os.environ[key] = ""
    block_external_connections()
    from fastapi.testclient import TestClient
    from src import server
    from src.data_pipeline import load_store
    from src.tools.analysis import Analyzer

    store = load_store()
    assert not store.is_sample, "실제 CSV가 연결되어 있지 않습니다."
    monthly, weekday = read_rows("monthly_597.csv"), read_rows("weekday_608.csv")
    analyzer = Analyzer(store)
    selected = [r for r in monthly if r["sigungu"] == "서귀포시" and r["ageGroup"] == "30대"
                and r["gender"] == "여" and r["marketType"] == "식음료"
                and r["userType"] == "내국인관광객" and r["dtYearMonth"].startswith("2018")]
    expected = sum(Decimal(r["useCost"]) for r in selected)
    actual = analyzer.trend({"region": "서귀포시", "age": "30대", "gender": "여성", "industry": "식음료"}, 12)
    assert Decimal(str(actual.facts["total_amount"])) == expected
    selected_days = [r for r in weekday if r["districtType"] == "상업지" and r["userType"] == "내국인관광객"]
    expected_days = sum(Decimal(r["useCost"]) for r in selected_days)
    actual_days = analyzer.weekday(district="상업지", months=15)
    assert Decimal(str(actual_days.facts["total_amount"])) == expected_days
    assert analyzer.verify(actual.id).verified and analyzer.verify(actual_days.id).verified
    questions = ["서귀포시 30대 여성 식음료 소비 추세 알려줘", "제주시 20대 여성 관광객의 카페 소비 추세는?",
                 "제주시 구도심 요일별 소비 패턴을 알려줘", "상업지 요일별 소비 패턴을 알려줘",
                 "최근 1년 제주 전 지역에서 전년 대비 소비 증가율이 가장 높은 테마는?"]
    results = []
    with TestClient(server.app, base_url="http://127.0.0.1:8501") as client:
        status = client.get("/api/status").json()
        assert status["ready"] and status["dataMode"] == "local_csv"
        for question in questions:
            response = client.post("/api/analyze", json={"question": question})
            event = json.loads(response.text.splitlines()[-1])
            assert event["type"] == "report", event
            report = event["report"]
            assert not report["data"]["isSample"]
            assert all(c["status"] != "fail" for c in report["verification"]["items"])
            results.append({"question": question, "title": report["title"], "tags": report["tags"],
                            "checks": report["verification"]["total"], "warnings": report["verification"]["warnings"]})
    print(json.dumps({"monthly_rows": len(store.monthly), "weekday_rows": len(store.weekday),
                      "monthly_period": store.period, "weekday_period": status["weekdayPeriod"],
                      "female_30s_food_2018_amount": str(expected), "weekday_commercial_all_months_amount": str(expected_days),
                      "reports": results, "external_network": "blocked", "llm_calls": 0}, ensure_ascii=True))


if __name__ == "__main__":
    main()
