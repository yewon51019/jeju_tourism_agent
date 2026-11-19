"""이미 저장한 원본 CSV를 검증하고 주 웹 앱의 로컬 데이터로 연결한다.

사용: python -m src.activate_data data/exports/jeju_20261119
네트워크·인증키를 사용하지 않으며 기존 앱 CSV는 덮어쓰지 않는다.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import tempfile

from .data_pipeline import RAW_DIR, load_store
from .hub_export import FIELDS, FILE_NAMES, validate_row

MONTHLY_MAPPING = {
    "dtYearMonth": "기준연월", "sido": "시도", "sigungu": "시군구", "cityGubun": "지역구분",
    "marketType": "업종", "userType": "관광객구분", "ageGroup": "연령대", "gender": "성별",
    "userCount": "이용자수", "useCount": "이용횟수", "useCost": "이용금액",
}
WEEKDAY_MAPPING = {"dtYearMonth": "기준연월", "districtType": "지구", "userType": "관광객구분",
                   "dtWeek": "요일", "userCount": "이용자수", "useCount": "이용횟수", "useCost": "이용금액"}
TOTAL_FIELDS = ("marketType", "ageGroup", "gender", "sigungu", "userType", "cityGubun")


def read_verified(source: Path, dataset: str, receipt: dict) -> list[dict]:
    path = source / FILE_NAMES[dataset]
    metadata = receipt["datasets"][dataset]
    if hashlib.sha256(path.read_bytes()).hexdigest() != metadata["sha256"]:
        raise ValueError(f"{dataset}: 원본 해시가 수집 기록과 다릅니다.")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        if reader.fieldnames != FIELDS[dataset] or len(rows) != metadata["rows"]:
            raise ValueError(f"{dataset}: 원본 필드 또는 건수가 수집 기록과 다릅니다.")
    for row in rows:
        validate_row(row, dataset, receipt["query"]["startDate"], receipt["query"]["endDate"])
    return rows


def write_rows(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError("연결할 데이터가 없습니다.")
    with path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def activate(source: Path, target: Path = RAW_DIR) -> dict:
    names = ("card_monthly.csv", "card_weekday.csv", "source_manifest.json")
    if any((target / name).exists() for name in names):
        raise ValueError("앱 데이터가 이미 있습니다. 기존 파일을 보존하고 연결을 중단합니다.")
    receipt = json.loads((source / "receipt.json").read_text(encoding="utf-8"))
    monthly = read_verified(source, "597", receipt)
    weekday = read_verified(source, "608", receipt)
    detail = [r for r in monthly if all(r[field] != "전체" for field in TOTAL_FIELDS)]
    prepared_monthly = []
    for row in detail:
        renamed = {label: row[field] for field, label in MONTHLY_MAPPING.items()}
        # 기존 질문 인터페이스의 호환 컬럼. 독립 테마 데이터가 아니며 UI에서도 업종으로 안내한다.
        renamed["테마"] = renamed["업종"]
        prepared_monthly.append(renamed)
    domestic = [r for r in weekday if r["userType"] == "내국인관광객"]
    prepared_weekday = [{label: r[field] for field, label in WEEKDAY_MAPPING.items()} for r in domestic]
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".activate-", dir=target) as temporary:
        staging = Path(temporary)
        write_rows(staging / names[0], prepared_monthly)
        write_rows(staging / names[1], prepared_weekday)
        store = load_store(staging)
        if len(store.monthly) != len(detail) or len(store.weekday) != len(domestic):
            raise ValueError("전처리 중 행이 제외되었습니다. 자동 연결하지 않습니다.")
        manifest = {
            "source_snapshot": source.name,
            "source_sha256": {d: receipt["datasets"][d]["sha256"] for d in FIELDS},
            "monthly_rows": len(detail), "monthly_total_rows_removed": len(monthly) - len(detail),
            "weekday_rows": len(domestic), "weekday_other_visitors_excluded": len(weekday) - len(domestic),
            "theme_is_industry_alias": True, "weekday_population": "내국인관광객",
            "monthly_period": store.period, "weekday_period": f"{store.weekday_months[0]} ~ {store.weekday_months[-1]}",
            "files_sha256": {name: hashlib.sha256((staging / name).read_bytes()).hexdigest() for name in names[:2]},
        }
        (staging / names[2]).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for name in names:
            # rename은 이 Windows 환경에서 기존 파일을 덮어쓰지 않는다.
            if (target / name).exists():
                raise ValueError("동시에 앱 데이터가 생성되어 연결을 중단합니다.")
            (staging / name).rename(target / name)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    try:
        manifest = activate(args.source)
    except (ValueError, OSError, KeyError, RuntimeError) as exc:
        print(f"연결 실패: {type(exc).__name__}. 원본 기록·형식과 기존 앱 파일을 확인하세요.")
        return 1
    print(json.dumps(manifest, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
