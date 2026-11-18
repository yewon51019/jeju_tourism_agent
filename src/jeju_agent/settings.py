"""이 PC에서 사용하는 API 설정. 키는 화면/로그에 출력하지 않습니다.

로컬 단일 사용자 앱용이며 .env는 암호화 저장소가 아닙니다.
공개 서버에 배포한다면 사용자별 비밀 저장소로 교체해야 합니다.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values, set_key

DEFAULT_MODEL = "claude-opus-5-5"
SETTINGS_PATH = Path(__file__).resolve().parents[2] / ".env"


def load_settings(path: Path = SETTINGS_PATH) -> dict[str, str]:
    """로컬 설정을 우선 읽습니다. 빈 Key를 저장했다면 환경변수로 되살리지 않습니다."""
    values = dotenv_values(path) if path.exists() else {}
    return {
        "api_key": str(values.get("ANTHROPIC_API_KEY", os.getenv("ANTHROPIC_API_KEY", "")) or ""),
        "model": str(values.get("ANTHROPIC_MODEL", os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL)) or DEFAULT_MODEL),
    }


def validate_settings(api_key: str, model: str) -> tuple[str, str]:
    """형식만 검사합니다. 실제 인증 성공은 API 호출 전까지 보장하지 않습니다."""
    api_key, model = api_key.strip(), model.strip()
    if not api_key or any(character.isspace() for character in api_key):
        raise ValueError("API Key를 공백 없이 입력해 주세요.")
    if not model or any(character.isspace() for character in model):
        raise ValueError("사용할 모델 ID를 입력해 주세요.")
    return api_key, model


def save_settings(api_key: str, model: str, path: Path = SETTINGS_PATH) -> None:
    """기존 .env의 다른 설정을 유지하면서 두 항목만 갱신합니다."""
    api_key, model = validate_settings(api_key, model)
    path.parent.mkdir(parents=True, exist_ok=True)
    set_key(path, "ANTHROPIC_API_KEY", api_key)
    set_key(path, "ANTHROPIC_MODEL", model)
    if os.name != "nt":
        path.chmod(0o600)


def clear_api_key(path: Path = SETTINGS_PATH) -> None:
    """빈 값을 저장해 다음 실행에서도 Key가 불러와지지 않도록 합니다."""
    set_key(path, "ANTHROPIC_API_KEY", "")
