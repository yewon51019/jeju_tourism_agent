"""실제 데이터가 없을 때 쓰는 합성 샘플 데이터를 만든다.

여기서 만든 수치는 실제 통계가 아니다. 화면과 보고서에도 합성 데이터임을 표시한다.
같은 시드로 항상 같은 결과를 만든다.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20261119
START = "2024-01-01"
END = "2026-08-31"

INDUSTRIES = {
    "음식점": ("식음료", 9.0),
    "카페·디저트": ("식음료", 3.2),
    "호텔·리조트": ("숙박", 7.5),
    "소매·기념품": ("쇼핑", 4.6),
    "체험·레저": ("문화·레저", 2.8),
    "렌터카": ("교통", 3.9),
}
REGIONS = {"제주시": 1.25, "서귀포시": 0.95}
AGES = {"20대": 0.9, "30대": 1.15, "40대": 1.2, "50대": 1.0, "60대 이상": 0.65}
GENDERS = {"여성": 1.05, "남성": 0.95}
VISITORS = {"관광객": 1.0, "도민": 0.45}
SEASON = {1: 0.82, 2: 0.86, 3: 0.92, 4: 1.06, 5: 1.14, 6: 1.0,
          7: 1.12, 8: 1.2, 9: 0.98, 10: 1.18, 11: 1.04, 12: 0.88}
GROWTH = {"음식점": 0.03, "카페·디저트": 0.08, "호텔·리조트": 0.01,
          "소매·기념품": -0.03, "체험·레저": 0.13, "렌터카": 0.02}
DISTRICTS = {
    "중문관광단지": 1.5, "성산일출봉": 1.0, "서귀포매일올레시장": 1.15, "표선해변": 0.6,
    "연동상권": 1.6, "함덕해변": 1.05, "애월해안": 1.2, "협재해변": 0.9,
}
WEEKDAY = {0: 0.86, 1: 0.8, 2: 0.83, 3: 0.92, 4: 1.2, 5: 1.42, 6: 1.05}
WEEKDAY_NAMES = ["월", "화", "수", "목", "금", "토", "일"]


def build_monthly(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for period in pd.period_range(START[:7], END[:7], freq="M"):
        years = (period.year - 2024) + (period.month - 1) / 12
        for industry, (theme, scale) in INDUSTRIES.items():
            trend = (1 + GROWTH[industry]) ** years
            for region, region_w in REGIONS.items():
                for age, age_w in AGES.items():
                    for gender, gender_w in GENDERS.items():
                        for visitor, visitor_w in VISITORS.items():
                            weight = scale * region_w * age_w * gender_w * visitor_w
                            noise = rng.normal(1, 0.035)
                            users = int(1800 * weight * SEASON[period.month] * trend * noise)
                            per_user = rng.normal(52000, 2500) * (1 + 0.02 * years)
                            rows.append({
                                "기준연월": period.strftime("%Y%m"), "테마": theme, "업종": industry,
                                "시군구": region, "지역구분": "전체", "관광객구분": visitor,
                                "연령대": age, "성별": gender, "이용자수": users,
                                "이용금액": int(users * per_user),
                            })
    return pd.DataFrame(rows)


def build_weekday(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for day in pd.date_range(START, END, freq="D"):
        years = (day.year - 2024) + (day.dayofyear - 1) / 365
        for district, scale in DISTRICTS.items():
            weight = scale * SEASON[day.month] * WEEKDAY[day.dayofweek] * (1.03 ** years)
            users = int(2400 * weight * rng.normal(1, 0.06))
            count = int(users * rng.normal(1.45, 0.05))
            rows.append({
                "날짜": day.strftime("%Y-%m-%d"), "지구": district,
                "요일": WEEKDAY_NAMES[day.dayofweek], "이용자수": users, "이용횟수": count,
                "이용금액": int(count * rng.normal(31000, 1500)),
            })
    return pd.DataFrame(rows)


def write_sample(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    build_monthly(rng).to_csv(directory / "card_monthly.csv", index=False, encoding="utf-8-sig")
    build_weekday(rng).to_csv(directory / "card_weekday.csv", index=False, encoding="utf-8-sig")
