"""독립된 월간/요일 데이터와 원본을 보존하는 정규화 로더."""

from dataclasses import dataclass
from itertools import product
from pathlib import Path
import math

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DIMENSIONS = {
    "monthly": ["year", "month", "region", "age", "gender", "sector", "theme"],
    "weekday": ["year", "month", "district", "weekday"],
}
METRICS = {"monthly": ["users", "amount"], "weekday": ["users", "transactions", "amount"]}
SOURCES = {
    "monthly": ("월간 내국인관광객 카드 사용 정보", "15056636"),
    "weekday": ("관광지 및 상업지구 요일별 카드 데이터", "15094893"),
}


@dataclass
class Dataset:
    name: str
    raw: pd.DataFrame
    frame: pd.DataFrame
    quality: dict
    source: dict


def synthetic_data() -> dict[str, pd.DataFrame]:
    """재현 가능한 교육용 합성값이며 실제 관측값이 아니다."""
    monthly = []
    for year, month, region, age, gender, sector in product(
        [2024, 2025], range(1, 13), ["제주시", "서귀포시"],
        ["20대", "30대", "40대", "50대", "60대"], ["남성", "여성"],
        ["음식점", "숙박", "쇼핑", "여가"],
    ):
        users = 50 + month * 7 + (year - 2024) * 9 + (30 if region == "서귀포시" else 0)
        users += ["20대", "30대", "40대", "50대", "60대"].index(age) * 3
        unit = {"음식점": 32000, "숙박": 115000, "쇼핑": 58000, "여가": 42000}[sector]
        monthly.append(dict(year=year, month=month, region=region, age=age, gender=gender,
                            sector=sector, theme="관광", users=users, amount=users * unit))
    weekday = []
    for year, month, district, day in product([2024, 2025], range(1, 13), ["중문관광단지", "성산일출봉", "연동상권"], range(7)):
        users = 150 + day * 25 + month * 3 + (year - 2024) * 5
        weekday.append(dict(year=year, month=month, district=district, weekday=["월", "화", "수", "목", "금", "토", "일"][day],
                            users=users, transactions=users * 2, amount=users * 48000))
    return {"monthly": pd.DataFrame(monthly), "weekday": pd.DataFrame(weekday)}


def normalize_frame(raw: pd.DataFrame, name: str) -> tuple[pd.DataFrame, dict]:
    """원본 수정 없이 결측/중복/음수를 제외하고 제외 사유를 기록한다."""
    if name not in DIMENSIONS:
        raise ValueError("알 수 없는 데이터셋")
    required = DIMENSIONS[name] + METRICS[name]
    missing = sorted(set(required) - set(raw.columns))
    if missing:
        raise ValueError(f"{name}: 필수 열 누락: {missing}")
    frame = raw.copy(deep=True)
    for column in required:
        frame[column] = frame[column].map(lambda x: x.strip() if isinstance(x, str) else x)
        frame[column] = frame[column].replace("", pd.NA)
    absent = frame[required].isna().any(axis=1)
    quality = {"input_rows": len(frame), "missing_excluded": int(absent.sum())}
    frame = frame.loc[~absent].copy()
    numeric = METRICS[name] + ["year", "month"]
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
        if not frame[column].map(lambda x: math.isfinite(float(x))).all():
            raise ValueError(f"{column}: 유한한 수치가 필요합니다")
        if column != "amount" and (frame[column] % 1 != 0).any():
            raise ValueError(f"{column}: 정수가 필요합니다")
    for column in set(DIMENSIONS[name]) - {"year", "month"}:
        if not frame[column].map(lambda x: isinstance(x, str)).all():
            raise ValueError(f"{column}: 문자열이 필요합니다")
    if not frame.month.between(1, 12).all() or not frame.year.between(1900, 2200).all():
        raise ValueError("연도 또는 월 범위 오류")
    if name == "weekday" and not frame.weekday.isin(["월", "화", "수", "목", "금", "토", "일"]).all():
        raise ValueError("weekday는 월/화/수/목/금/토/일 중 하나여야 합니다")
    # 부가 열까지 같은 행만 완전 중복으로 처리한다.
    duplicates = frame.duplicated()
    quality["duplicates_removed"] = int(duplicates.sum())
    frame = frame.loc[~duplicates].copy()
    negative = (frame[METRICS[name]] < 0).any(axis=1)
    quality["negative_excluded"] = int(negative.sum())
    quality["negative_row_indices"] = frame.index[negative].tolist()
    frame = frame.loc[~negative, required].reset_index(drop=True)
    quality["usable_rows"] = len(frame)
    return frame, quality


def load_datasets(demo: bool = True, data_dir: str | Path | None = None) -> dict[str, Dataset]:
    directory = Path(data_dir) if data_dir is not None else ROOT / "data" / "processed"
    generated = synthetic_data() if demo else {}
    datasets = {}
    for name in DIMENSIONS:
        path = directory / f"{name}.csv"
        # demo는 항상 합성 데이터를 선택하여 실데이터와 혼동하지 않는다.
        if demo:
            raw = generated[name]
        elif path.is_file():
            raw = pd.read_csv(path, encoding="utf-8-sig")
        else:
            continue
        frame, quality = normalize_frame(raw, name)
        title, portal_id = SOURCES[name]
        source = {
            "title": title, "provider": "제주특별자치도 (기획서 기재)",
            "reference_url": f"https://www.data.go.kr/data/{portal_id}/openapi.do",
            "mode": "synthetic" if demo else "local_csv",
            "is_synthetic": demo, "confirmed": False,
            "source_verified": False, "license_verified": False,
            "license": "기획서: 이용허락범위 제한 없음. 실제 이용조건 별도 확인 필요",
            "retrieved_at": None, "unit": "원 (정규화 입력 계약; 원 출처 단위 미확인)",
            "path": None if demo else str(path.resolve()),
            "notice": "교육용 합성 데이터: 실제 관광 소비 통계가 아닙니다" if demo else
                      "로컬 CSV: 출처·수집일·단위·이용조건은 자동 확인되지 않았습니다",
        }
        datasets[name] = Dataset(name, raw.copy(deep=True), frame, quality, source)
    return datasets
