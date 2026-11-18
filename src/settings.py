"""Gemini API 클라이언트를 만들고, 웹 화면에서 입력한 키를 이 PC의 .env 파일에 저장한다."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import httpx
import httpx2
from dotenv import set_key, unset_key
from google import genai
from google.genai import errors, types

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
KEY_NAME = "GEMINI_API_KEY"
MODEL_NAME = "GEMINI_MODEL"
DEFAULT_MODEL = "gemini-3.5-flash-lite"
# Google이 키 접두사를 공개 규격으로 정하지 않았으므로 문자 종류와 길이만 확인한다.
KEY_PATTERN = re.compile(r"^[A-Za-z0-9_\-.]{20,250}$")
# 무료 등급의 분당 한도에 걸리면 잠시 기다렸다가 다시 시도한다.
RETRY = types.HttpRetryOptions(attempts=3, initial_delay=5.0, max_delay=30.0, http_status_codes=[429, 500, 503, 504])
# SDK는 환경변수에 따라 두 HTTP 라이브러리 중 하나를 사용한다.
CONNECTION_ERRORS = (httpx.TransportError, httpx2.TransportError)


class KeyRejected(ValueError):
    """입력한 API Key를 저장할 수 없을 때 발생한다."""


def create_client(api_key: str, timeout_ms: int = 60_000, retry: bool = True) -> genai.Client:
    options = types.HttpOptions(timeout=timeout_ms, retry_options=RETRY if retry else None)
    return genai.Client(enterprise=False, api_key=api_key, http_options=options)  # PC 환경변수와 무관하게 Gemini API를 쓴다.


def check_key(api_key: str, model: str) -> tuple[bool, str]:
    """Gemini API로 키를 확인한다. 네트워크 문제면 저장은 허용하고 미확인으로 알린다."""
    unverified = "API Key를 저장했지만 연결을 확인하지 못했습니다. 인터넷 연결을 확인해 주세요."
    client = create_client(api_key, timeout_ms=15_000, retry=False)  # 변수에 담지 않으면 요청 전에 연결이 닫힌다.
    try:
        client.models.get(model=model)
    except errors.ClientError as exc:
        if exc.code == 404:
            raise KeyRejected(f"이 API Key로 {model} 모델을 사용할 수 없습니다.") from exc
        if exc.code in (400, 401, 403):
            raise KeyRejected("API Key가 올바르지 않거나 사용 권한이 없습니다. 키를 다시 확인해 주세요.") from exc
        return False, unverified
    except (errors.APIError, *CONNECTION_ERRORS, json.JSONDecodeError):
        return False, unverified
    return True, "API Key를 확인하고 저장했습니다."


def save_key(api_key: str, model: str) -> dict[str, object]:
    key = api_key.strip()
    if not KEY_PATTERN.fullmatch(key):
        raise KeyRejected("API Key 형식이 올바르지 않습니다. Google AI Studio에서 복사한 키를 입력해 주세요.")
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
