"""웹 화면에서 입력한 Claude API Key를 이 PC의 .env 파일에 저장한다."""
from __future__ import annotations

import os
import re
from pathlib import Path

import anthropic
from dotenv import set_key, unset_key

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
KEY_NAME = "ANTHROPIC_API_KEY"
KEY_PATTERN = re.compile(r"^sk-ant-[A-Za-z0-9_\-]{20,250}$")


class KeyRejected(ValueError):
    """입력한 API Key를 저장할 수 없을 때 발생한다."""


def check_key(api_key: str, model: str) -> tuple[bool, str]:
    """Claude API로 키를 확인한다. 네트워크 문제면 저장은 허용하고 미확인으로 알린다."""
    client = anthropic.Anthropic(api_key=api_key, max_retries=0, timeout=15.0)
    try:
        client.models.retrieve(model)
    except anthropic.AuthenticationError as exc:
        raise KeyRejected("API Key가 올바르지 않습니다. 키를 다시 확인해 주세요.") from exc
    except anthropic.PermissionDeniedError as exc:
        raise KeyRejected("이 API Key에는 Claude API 사용 권한이 없습니다.") from exc
    except anthropic.NotFoundError as exc:
        raise KeyRejected(f"이 API Key로 {model} 모델을 사용할 수 없습니다.") from exc
    except (anthropic.APIConnectionError, anthropic.APIStatusError):
        return False, "API Key를 저장했지만 연결을 확인하지 못했습니다. 인터넷 연결을 확인해 주세요."
    return True, "API Key를 확인하고 저장했습니다."


def save_key(api_key: str, model: str) -> dict[str, object]:
    key = api_key.strip()
    if not KEY_PATTERN.fullmatch(key):
        raise KeyRejected("API Key 형식이 올바르지 않습니다. sk-ant-로 시작하는 키를 입력해 주세요.")
    verified, message = check_key(key, model)
    ENV_PATH.touch(exist_ok=True)
    set_key(str(ENV_PATH), KEY_NAME, key)
    os.environ[KEY_NAME] = key
    return {"saved": True, "verified": verified, "message": message}


def delete_key() -> dict[str, object]:
    if ENV_PATH.exists():
        unset_key(str(ENV_PATH), KEY_NAME)
    os.environ.pop(KEY_NAME, None)
    return {"saved": False, "verified": False, "message": "저장된 API Key를 삭제했습니다."}
