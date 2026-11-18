"""제주데이터허브 Open API를 호출해 카드 데이터를 data/raw에 CSV로 저장한다.

프로젝트 키는 .env 파일의 JEJU_HUB_PROJECT_KEY 값에서 읽는다.
"""
from __future__ import annotations

import csv
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
KEY_NAME = "JEJU_HUB_PROJECT_KEY"
BASE_URL = "https://open.jejudatahub.net/api/proxy"
PAGE_SIZE = 100
RETRIES = 3
logging.getLogger("httpx").setLevel(logging.WARNING)  # 요청 URL에 프로젝트 키가 있어 INFO 로그를 남기지 않는다.

MONTHLY ={"name": "월간 카드 데이터(597번)", "key": "5D5a577taba7tbb71at1b1bt9tatata9", "start": "201609", "end": "201812", "params": {}}
WEEKDAY = {"name": "요일별 카드 데이터(608번)", "key": "868ttD1tbDb8tbt00tDtaba6t0Db1110", "start": "201609", "end": "201711",
           "params": {"userType": "내국인관광객"}}
MONTHLY_HEADER = ["기준연월", "테마", "업종", "시군구", "지역구분", "관광객구분", "연령대", "성별", "이용자수", "이용금액"]
WEEKDAY_HEADER = ["기준연월", "지구", "관광객구분", "요일", "이용자수", "이용횟수", "이용금액"]


class HubError(RuntimeError):
    """데이터를 받지 못했을 때 발생한다. 메시지에는 프로젝트 키를 넣지 않는다."""


def _request(client: httpx.Client, url: str, params: dict[str, Any]) -> dict[str, Any]:
    for attempt in range(1, RETRIES + 1):
        try:
            response = client.get(url, params=params)
        except httpx.HTTPError as exc:
            if attempt == RETRIES:
                raise HubError(f"제주데이터허브에 연결할 수 없습니다 ({type(exc).__name__}).") from None
            time.sleep(attempt)
            continue
        if response.status_code in (401, 403, 404):
            raise HubError("프로젝트 키를 확인하고, 두 데이터를 프로젝트에 담았는지 확인해 주세요.")
        if response.status_code == 429:
            raise HubError("일일 호출 한도를 초과했습니다. 내일 다시 실행해 주세요.")
        if response.status_code >= 500 and attempt < RETRIES:
            time.sleep(attempt)
            continue
        if response.status_code != 200:
            raise HubError(f"제주데이터허브 응답 오류입니다 (상태 코드 {response.status_code}).")
        try:
            payload = response.json()
        except ValueError:
            raise HubError("응답을 읽을 수 없습니다. 프로젝트 키와 프로젝트 담기 상태를 확인해 주세요.") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise HubError("예상과 다른 응답입니다. 프로젝트 키와 프로젝트 담기 상태를 확인해 주세요.")
        return payload
    raise HubError("제주데이터허브 요청에 실패했습니다.")


def check_access(client: httpx.Client, dataset: dict[str, Any], project_key: str) -> None:
    """전체 수집 전에 한 행만 요청해, 권한이 없을 때 일일 호출 한도를 낭비하지 않는다."""
    params = {"startDate": dataset["start"], "endDate": dataset["end"], "number": 1, "limit": 1, **dataset["params"]}
    try:
        _request(client, f"{BASE_URL}/{dataset['key']}/{project_key}", params)
    except HubError as exc:
        raise HubError(f"{dataset['name']}: {exc}") from None


def fetch_all(client: httpx.Client, dataset: dict[str, Any], project_key: str, delay: float = 0.1) -> list[dict[str, Any]]:
    url = f"{BASE_URL}/{dataset['key']}/{project_key}"
    rows: list[dict[str, Any]] = []
    number = 1
    while True:
        params = {"startDate": dataset["start"], "endDate": dataset["end"], "number": number, "limit": PAGE_SIZE, **dataset["params"]}
        payload = _request(client, url, params)
        rows.extend(payload["data"])
        total = payload.get("totCnt")
        print(f"  {len(rows):,}/{total if total is not None else '?'}행", flush=True)
        if not payload.get("hasMore"):
            break
        if not payload["data"]:
            raise HubError("빈 페이지가 반환되어 수집을 중단했습니다. 다시 실행해 주세요.")
        number += 1
        time.sleep(delay)
    if total is not None and len(rows) != int(total):
        raise HubError(f"받은 행 수({len(rows):,})가 전체 행 수({int(total):,})와 다릅니다. 다시 실행해 주세요.")
    if not rows:
        raise HubError("받은 데이터가 없습니다.")
    return rows


def monthly_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    """'전체' 합계 행은 세부 행과 중복 집계되므로 제외한다."""
    output = []
    for r in rows:
        if "전체" in (r.get("marketType"), r.get("ageGroup"), r.get("gender"), r.get("sigungu"), r.get("userType")):
            continue
        output.append([r["dtYearMonth"], r["marketType"], r["marketType"], r["sigungu"], r["cityGubun"], r["userType"],
                       r["ageGroup"], r["gender"], r["userCount"], r["useCost"]])
    return output


def weekday_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    return [[r["dtYearMonth"], r["districtType"], r["userType"], r["dtWeek"], r["userCount"], r["useCount"], r["useCost"]]
            for r in rows]


def write_csv(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def download(project_key: str, raw_dir: Path = RAW_DIR, transport: httpx.BaseTransport | None = None, delay: float = 0.1) -> dict[str, int]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=30.0, transport=transport) as client:
        check_access(client, MONTHLY, project_key)
        check_access(client, WEEKDAY, project_key)
        print("월간 카드 데이터를 받는 중입니다.", flush=True)
        monthly = monthly_rows(fetch_all(client, MONTHLY, project_key, delay))
        print("요일별 카드 데이터를 받는 중입니다.", flush=True)
        weekday = weekday_rows(fetch_all(client, WEEKDAY, project_key, delay))
    if not monthly or not weekday:
        raise HubError("저장할 데이터가 없습니다.")
    monthly_temp, weekday_temp = raw_dir / "card_monthly.csv.tmp", raw_dir / "card_weekday.csv.tmp"
    write_csv(monthly_temp, MONTHLY_HEADER, monthly)
    write_csv(weekday_temp, WEEKDAY_HEADER, weekday)
    monthly_temp.replace(raw_dir / "card_monthly.csv")
    weekday_temp.replace(raw_dir / "card_weekday.csv")
    return {"monthly": len(monthly), "weekday": len(weekday)}


def ensure_hub_data(raw_dir: Path = RAW_DIR, transport: httpx.BaseTransport | None = None, delay: float = 0.1) -> str | None:
    """프로젝트 키가 있고 CSV가 없으면 내려받는다. 실패하면 화면에 보여 줄 안내 문구를 돌려준다."""
    if (raw_dir / "card_monthly.csv").exists() and (raw_dir / "card_weekday.csv").exists():
        return None
    project_key = os.getenv(KEY_NAME, "").strip()
    if not project_key:
        return None
    try:
        result = download(project_key, raw_dir, transport, delay)
    except HubError as exc:
        return f"제주데이터허브 데이터를 받지 못했습니다. {exc}"
    except (AttributeError, KeyError, TypeError, ValueError, OSError) as exc:
        return f"제주데이터허브 데이터를 저장하지 못했습니다 ({type(exc).__name__}). 다시 실행해 주세요."
    print(f"완료: 월간 {result['monthly']:,}행, 요일별 {result['weekday']:,}행을 저장했습니다.", flush=True)
    return None
