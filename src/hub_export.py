"""제주 카드 API를 원본 필드 그대로 CSV로 내보낸다.

앱 시작 시 실행하지 않는다. 명시적 CLI 실행만 네트워크를 사용한다.
두 자료의 페이지·값·파일 재읽기 검증이 끝나야 결과 폴더를 확정한다.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import time

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
FIELDS = {
    "597": ["sido", "sigungu", "cityGubun", "marketType", "userType", "ageGroup",
            "gender", "dtYearMonth", "userCount", "useCount", "useCost"],
    "608": ["districtType", "userType", "dtYearMonth", "dtWeek", "userCount", "useCount", "useCost"],
}
ENDPOINTS = {"597": "5D5a577taba7tbb71at1b1bt9tatata9", "608": "868ttD1tbDb8tbt00tDtaba6t0Db1110"}
FILE_NAMES = {"597": "monthly_597.csv", "608": "weekday_608.csv"}
NUMBERS = ("userCount", "useCount", "useCost")
PAGE_SIZE = 100


class ExportError(RuntimeError):
    """키나 인증 URL을 포함하지 않는 수집 오류."""


def valid_month(value: str) -> str:
    if not re.fullmatch(r"[0-9]{6}", value):
        raise ExportError("기간은 YYYYMM 형식이어야 합니다.")
    try:
        datetime.strptime(value, "%Y%m")
    except ValueError:
        raise ExportError("올바르지 않은 연월입니다.") from None
    return value


def validate_row(row: dict, dataset: str, start: str, end: str) -> None:
    if not isinstance(row, dict) or set(row) != set(FIELDS[dataset]):
        raise ExportError(f"{dataset}: API 필드가 명세와 다릅니다.")
    for value in row.values():
        if type(value) not in (str, int, float) or str(value).strip() == "":
            raise ExportError(f"{dataset}: 결측 또는 지원하지 않는 값이 있습니다.")
        # 원본을 임의로 수정하는 대신 수식 주입 가능성이 있으면 중단한다.
        if isinstance(value, str) and value.lstrip().startswith(("=", "+", "@")):
            raise ExportError(f"{dataset}: CSV에서 수식으로 해석될 수 있는 값입니다.")
    month = valid_month(str(row["dtYearMonth"]))
    if not start <= month <= end:
        raise ExportError(f"{dataset}: 요청 기간 밖의 행입니다.")
    for field in NUMBERS:
        try:
            number = Decimal(str(row[field]))
        except InvalidOperation:
            raise ExportError(f"{dataset}: {field} 값이 숫자가 아닙니다.") from None
        if not number.is_finite() or number != number.to_integral_value():
            raise ExportError(f"{dataset}: {field} 값이 유한한 정수가 아닙니다.")
    if dataset == "608" and row["dtWeek"] not in list("월화수목금토일"):
        raise ExportError("608: 알 수 없는 요일 값입니다.")


def collect(client: httpx.Client, dataset: str, key: str, start: str, end: str,
            max_pages: int = 400, delay: float = 0.1) -> tuple[list[dict], int]:
    """관광객 구분 등은 필터하지 않는다. 합계 행도 원본에 보존한다."""
    rows, seen = [], set()
    expected_total = None
    for page in range(1, max_pages + 1):
        try:
            response = client.get(
                f"https://open.jejudatahub.net/api/proxy/{ENDPOINTS[dataset]}/{key}",
                params={"startDate": start, "endDate": end, "number": page, "limit": PAGE_SIZE},
            )
        except httpx.HTTPError:
            raise ExportError(f"{dataset}: 네트워크 오류. 재시도 없이 중단했습니다.") from None
        if response.status_code != 200:
            raise ExportError(f"{dataset}: HTTP {response.status_code}. 재시도 없이 중단했습니다.")
        try:
            payload = response.json()
        except ValueError:
            raise ExportError(f"{dataset}: JSON 응답이 아닙니다.") from None
        if not isinstance(payload, dict):
            raise ExportError(f"{dataset}: 응답 구조 오류입니다.")
        total, more, batch = payload.get("totCnt"), payload.get("hasMore"), payload.get("data")
        if type(total) is not int or total <= 0 or type(more) is not bool or not isinstance(batch, list):
            raise ExportError(f"{dataset}: 총건수·페이지 정보가 없거나 빈 데이터입니다.")
        if total > PAGE_SIZE * max_pages:
            raise ExportError(f"{dataset}: 총 {total}행으로 설정한 호출 상한을 초과합니다.")
        if expected_total is None:
            expected_total = total
        if total != expected_total or not batch or len(batch) > PAGE_SIZE:
            raise ExportError(f"{dataset}: 총건수가 바뀌었거나 페이지 크기가 잘못되었습니다.")
        for row in batch:
            validate_row(row, dataset, start, end)
            identity = tuple(str(row[field]) for field in FIELDS[dataset])
            if identity in seen:
                raise ExportError(f"{dataset}: 중복 행/반복 페이지를 발견해 중단했습니다.")
            seen.add(identity)
            rows.append(row)
        if len(rows) > total or more != (len(rows) < total):
            raise ExportError(f"{dataset}: 페이지 종료 정보와 누적 건수가 다릅니다.")
        if page == 1 or page % 10 == 0 or not more:
            print(f"{dataset}: {len(rows):,}/{total:,} rows, {page} requests", flush=True)
        if not more:
            return rows, page
        time.sleep(delay)
    raise ExportError(f"{dataset}: 호출 상한에 도달했습니다.")


def save_csv(path: Path, dataset: str, rows: list[dict], key: str) -> dict:
    """UTF-8 BOM으로 저장하고 전체 행·필드를 다시 읽어 대조한다."""
    fields = FIELDS[dataset]
    if key in json.dumps(rows, ensure_ascii=False):
        raise ExportError("결과에 인증정보가 포함되어 저장하지 않습니다.")
    with path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        restored = list(reader)
        if reader.fieldnames != fields or restored != [{f: str(r[f]) for f in fields} for r in rows]:
            raise ExportError("저장 후 재읽기 결과가 원본과 다릅니다.")
    months = sorted({str(row["dtYearMonth"]) for row in rows})
    dimensions = [field for field in fields if field not in NUMBERS and field != "dtYearMonth"]
    return {
        "file": path.name, "rows": len(rows), "fields": fields,
        "observed_start": months[0], "observed_end": months[-1], "months": months,
        "categories": {f: sorted({str(r[f]) for r in rows}) for f in dimensions},
        "negative_rows": sum(any(Decimal(str(r[f])) < 0 for f in NUMBERS) for r in rows),
        "missing_values": 0, "duplicate_rows": 0, "roundtrip_equal": True,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "source": f"https://jejudatahub.net/data/view/data/{dataset}",
    }


def export(key: str, output: Path, start: str, end: str,
           transport: httpx.BaseTransport | None = None, max_pages: int = 400) -> dict:
    if not key.strip():
        raise ExportError("JEJU_HUB_PROJECT_KEY가 없습니다.")
    if valid_month(start) > valid_month(end):
        raise ExportError("시작월이 종료월보다 늦습니다.")
    if not 1 <= max_pages <= 400:
        raise ExportError("호출 상한은 데이터별 1~400회입니다.")
    if output.exists():
        raise ExportError("출력 폴더가 이미 존재합니다. 새 폴더를 지정해 주세요.")
    # HTTP 디버그 로그도 인증 URL을 포함할 수 있으므로 차단한다.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    output.parent.mkdir(parents=True, exist_ok=True)
    receipt = {"retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
               "query": {"startDate": start, "endDate": end, "population_filter": None},
               "encoding": "utf-8-sig", "app_activated": False, "datasets": {}}
    with tempfile.TemporaryDirectory(prefix=".pending-", dir=output.parent) as temporary:
        pending = Path(temporary)
        with httpx.Client(timeout=30, follow_redirects=False, transport=transport) as client:
            for dataset in FIELDS:
                rows, calls = collect(client, dataset, key, start, end, max_pages)
                summary = save_csv(pending / FILE_NAMES[dataset], dataset, rows, key)
                summary["requests"] = calls
                receipt["datasets"][dataset] = summary
        serialized = json.dumps(receipt, ensure_ascii=False, indent=2)
        if key in serialized:
            raise ExportError("메타데이터에 인증정보가 포함되어 저장하지 않습니다.")
        (pending / "receipt.json").write_text(serialized + "\n", encoding="utf-8")
        pending.rename(output)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, help="조회 시작월 YYYYMM")
    parser.add_argument("--end", required=True, help="조회 종료월 YYYYMM")
    parser.add_argument("--output", type=Path, required=True, help="새 결과 폴더")
    args = parser.parse_args()
    key = os.getenv("JEJU_HUB_PROJECT_KEY") or dotenv_values(ROOT / ".env").get("JEJU_HUB_PROJECT_KEY") or ""
    try:
        receipt = export(key.strip(), args.output, args.start, args.end)
    except (ExportError, OSError) as exc:
        # OSError도 전체 경로 대신 예외 유형만 기록한다.
        print(str(exc) if isinstance(exc, ExportError) else type(exc).__name__)
        return 1
    print(json.dumps(receipt, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
