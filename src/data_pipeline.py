"""카드 소비 데이터를 읽고 검사해 분석 가능한 형태로 만든다."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .sample_data import write_sample

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
SAMPLE_DIR = ROOT / "data" / "sample"
MONTHLY_FILE = "card_monthly.csv"
WEEKDAY_FILE = "card_weekday.csv"

MONTHLY_NAME = "월간 내국인관광객 카드 사용 정보"
WEEKDAY_NAME = "관광지 및 상업지구 요일별 카드 데이터"
WEEKDAY_NAMES = ["월", "화", "수", "목", "금", "토", "일"]

# 실제 파일의 컬럼명이 다르면 이 표에 별칭을 추가한다.
MONTHLY_COLUMNS = {
    "기준연월": ["기준연월", "기준년월", "년월", "연월"],
    "테마": ["테마", "테마명"],
    "업종": ["업종", "업종명"],
    "시군구": ["시군구", "시군구명"],
    "지역구분": ["지역구분", "지역구분명"],
    "관광객구분": ["관광객구분", "관광객구분명"],
    "연령대": ["연령대", "연령"],
    "성별": ["성별"],
    "이용자수": ["이용자수", "이용자 수"],
    "이용금액": ["이용금액", "이용 금액"],
}
WEEKDAY_COLUMNS = {
    "날짜": ["날짜", "일자", "기준일자"],
    "지구": ["지구", "지구명"],
    "요일": ["요일"],
    "이용자수": ["이용자수", "이용자 수"],
    "이용횟수": ["이용횟수", "이용 횟수", "이용건수"],
    "이용금액": ["이용금액", "이용 금액"],
}
# 요일별 데이터에는 시군구가 없어 지구가 속한 시군구를 이 표로 연결한다.
DISTRICT_REGION = {
    "중문관광단지": "서귀포시", "성산일출봉": "서귀포시", "서귀포매일올레시장": "서귀포시",
    "표선해변": "서귀포시", "연동상권": "제주시", "함덕해변": "제주시",
    "애월해안": "제주시", "협재해변": "제주시",
}


class DataError(RuntimeError):
    """데이터 파일을 분석에 사용할 수 없을 때 발생한다."""


@dataclass
class DataStore:
    monthly: pd.DataFrame
    weekday: pd.DataFrame
    is_sample: bool
    quality: list[str] = field(default_factory=list)

    @property
    def months(self) -> list[str]:
        return sorted(self.monthly["기준연월"].unique().tolist())

    @property
    def period(self) -> str:
        return f"{self.months[0]} ~ {self.months[-1]}"

    @property
    def source(self) -> str:
        if self.is_sample:
            return "합성 샘플 데이터 (실제 통계 아님)"
        return f"제주특별자치도 · {MONTHLY_NAME}, {WEEKDAY_NAME}"

    def values(self, column: str) -> list[str]:
        frame = self.weekday if column == "지구" else self.monthly
        return sorted(frame[column].dropna().unique().tolist())


def _read_csv(path: Path) -> pd.DataFrame:
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return pd.read_csv(path, encoding=encoding, dtype=str)
        except UnicodeDecodeError:
            continue
    raise DataError(f"{path.name} 파일의 인코딩을 읽을 수 없습니다. UTF-8 또는 CP949로 저장해 주세요.")


def _standardize(frame: pd.DataFrame, columns: dict[str, list[str]], name: str) -> pd.DataFrame:
    frame = frame.rename(columns=lambda c: str(c).strip())
    renames, missing = {}, []
    for target, aliases in columns.items():
        found = next((alias for alias in aliases if alias in frame.columns), None)
        if found is None:
            missing.append(target)
        else:
            renames[found] = target
    if missing:
        raise DataError(f"{name} 파일에 필수 컬럼이 없습니다: {', '.join(missing)}")
    frame = frame.rename(columns=renames)[list(columns)].copy()
    for column in frame.columns:
        frame[column] = frame[column].astype("string").str.strip()
    return frame


def _to_number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.str.replace(",", "", regex=False), errors="coerce")


def _clean(frame: pd.DataFrame, numeric: list[str], name: str, quality: list[str]) -> pd.DataFrame:
    before = len(frame)
    for column in numeric:
        frame[column] = _to_number(frame[column])
    frame = frame.dropna()
    missing = before - len(frame)
    deduped = frame.drop_duplicates()
    duplicates = len(frame) - len(deduped)
    negative = int((deduped[numeric] < 0).any(axis=1).sum())
    quality.append(
        f"{name}: 원본 {before:,}행, 결측 제외 {missing:,}행, 중복 제거 {duplicates:,}행, 음수 경고 {negative:,}행"
    )
    if deduped.empty:
        raise DataError(f"{name} 파일에 분석할 수 있는 행이 없습니다.")
    return deduped.reset_index(drop=True)


def _normalize_age(value: str) -> str:
    text = str(value).strip()
    return f"{text}대" if text.isdigit() else text


def _normalize_gender(value: str) -> str:
    return {"M": "남성", "F": "여성", "남": "남성", "여": "여성"}.get(str(value).strip(), str(value).strip())


def preprocess_monthly(frame: pd.DataFrame, quality: list[str]) -> pd.DataFrame:
    frame = _standardize(frame, MONTHLY_COLUMNS, "월간 카드")
    frame = _clean(frame, ["이용자수", "이용금액"], "월간 카드", quality)
    digits = frame["기준연월"].str.replace(r"\D", "", regex=True).str[:6]
    parsed = pd.to_datetime(digits, format="%Y%m", errors="coerce")
    invalid = int(parsed.isna().sum())
    if invalid:
        quality.append(f"월간 카드: 기준연월 형식 오류 {invalid:,}행 제외")
    frame = frame.loc[parsed.notna()].copy()
    if frame.empty:
        raise DataError("월간 카드 파일에 올바른 기준연월이 없습니다.")
    frame["기준연월"] = parsed.dropna().dt.strftime("%Y-%m").astype(str).to_numpy()
    frame["연령대"] = frame["연령대"].map(_normalize_age).astype(str)
    frame["성별"] = frame["성별"].map(_normalize_gender).astype(str)
    for column in ("테마", "업종", "시군구", "지역구분", "관광객구분"):
        frame[column] = frame[column].astype(str)
    return frame.reset_index(drop=True)


def preprocess_weekday(frame: pd.DataFrame, quality: list[str]) -> pd.DataFrame:
    frame = _standardize(frame, WEEKDAY_COLUMNS, "요일별 카드")
    frame = _clean(frame, ["이용자수", "이용횟수", "이용금액"], "요일별 카드", quality)
    parsed = pd.to_datetime(frame["날짜"].str.replace(r"\D", "", regex=True).str[:8], format="%Y%m%d", errors="coerce")
    invalid = int(parsed.isna().sum())
    if invalid:
        quality.append(f"요일별 카드: 날짜 형식 오류 {invalid:,}행 제외")
    frame = frame.loc[parsed.notna()].copy()
    if frame.empty:
        raise DataError("요일별 카드 파일에 올바른 날짜가 없습니다.")
    dates = parsed.dropna()
    frame["날짜"] = dates.dt.strftime("%Y-%m-%d").astype(str).to_numpy()
    frame["기준연월"] = dates.dt.strftime("%Y-%m").astype(str).to_numpy()
    # 원본 요일 표기 대신 날짜에서 계산한 요일을 기준으로 삼는다.
    frame["요일"] = [WEEKDAY_NAMES[d] for d in dates.dt.day_of_week]
    frame["지구"] = frame["지구"].astype(str)
    frame["시군구"] = frame["지구"].map(DISTRICT_REGION).fillna("미분류").astype(str)
    return frame.reset_index(drop=True)


def load_store(raw_dir: Path = RAW_DIR, sample_dir: Path = SAMPLE_DIR) -> DataStore:
    """실제 데이터가 있으면 사용하고, 없으면 합성 샘플을 사용한다."""
    has_monthly = (raw_dir / MONTHLY_FILE).exists()
    has_weekday = (raw_dir / WEEKDAY_FILE).exists()
    if has_monthly != has_weekday:
        absent = WEEKDAY_FILE if has_monthly else MONTHLY_FILE
        raise DataError(f"data/raw 폴더에 {absent} 파일이 없습니다. 두 파일을 함께 넣어 주세요.")
    is_sample = not has_monthly
    directory = sample_dir if is_sample else raw_dir
    if is_sample and not (sample_dir / MONTHLY_FILE).exists():
        write_sample(sample_dir)
    quality: list[str] = []
    monthly = preprocess_monthly(_read_csv(directory / MONTHLY_FILE), quality)
    weekday = preprocess_weekday(_read_csv(directory / WEEKDAY_FILE), quality)
    return DataStore(monthly=monthly, weekday=weekday, is_sample=is_sample, quality=quality)
