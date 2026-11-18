"""전년 실적이 일부 빠진 항목의 증감률 처리를 검증한다."""
import pandas as pd
import pytest

from src.data_pipeline import DataError, DataStore, preprocess_monthly
from src.tools.analysis import Analyzer


def row(month, theme, amount):
    return {"기준연월": month, "테마": theme, "업종": theme, "시군구": "제주시", "지역구분": "전체", "관광객구분": "관광객",
            "연령대": "30대", "성별": "여성", "이용자수": 100.0, "이용금액": float(amount)}


def make_store(rows):
    weekday = pd.DataFrame([{"날짜": "2025-02-03", "지구": "연동상권", "요일": "월", "이용자수": 1.0, "이용횟수": 1.0,
                             "이용금액": 1.0, "기준연월": "2025-02", "시군구": "제주시"}])
    return DataStore(monthly=pd.DataFrame(rows), weekday=weekday, is_sample=True)


def test_partial_prior_year_is_not_compared():
    store = make_store([
        row("2024-01", "A", 100), row("2025-01", "A", 100), row("2025-02", "A", 100),
        row("2024-01", "B", 100), row("2024-02", "B", 100), row("2025-01", "B", 110), row("2025-02", "B", 110),
        row("2024-01", "C", 100), row("2024-02", "C", 100), row("2025-01", "C", 90), row("2025-02", "C", 90),
    ])
    result = Analyzer(store).rank("테마", metric="growth", months=2)
    by_name = {r["name"]: r["yoy"] for r in result.rows}
    assert by_name == {"A": None, "B": 10.0, "C": -10.0}
    assert (result.facts["top_name"], result.facts["bottom_name"]) == ("B", "C")
    assert result.rows[-1]["name"] == "A"


def test_all_invalid_months_raise_a_data_error():
    frame = pd.DataFrame([{**row("202613", "A", 100), "이용자수": "100", "이용금액": "100"}])
    with pytest.raises(DataError):
        preprocess_monthly(frame.astype(str), [])
