"""제주데이터허브 데이터를 다시 내려받는다.

실행: download_data.bat 또는 python scripts/fetch_hub_data.py
프로젝트 키는 .env의 JEJU_HUB_PROJECT_KEY 값이나 실행 중 입력으로 전달한다.
"""
from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.hub_api import KEY_NAME, MONTHLY, WEEKDAY, HubError, download  # noqa: E402,F401


def main() -> int:
    load_dotenv(ROOT / ".env")
    project_key = os.getenv(KEY_NAME, "").strip() or getpass.getpass("제주데이터허브 프로젝트 키를 붙여넣고 Enter를 누르세요: ").strip()
    if not project_key:
        print("프로젝트 키가 입력되지 않았습니다.")
        return 1
    try:
        result = download(project_key)
    except HubError as exc:
        print(f"다운로드 실패: {exc}")
        return 1
    print(f"완료: 월간 {result['monthly']:,}행, 요일별 {result['weekday']:,}행을 data/raw에 저장했습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
