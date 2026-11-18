"""Agent가 화면으로 보내는 진행 이벤트."""
from __future__ import annotations

from typing import Any


def step(number: int, status: str, detail: str = "") -> dict[str, Any]:
    return {"type": "step", "step": number, "status": status, "detail": detail}


def clarify(question: str, fields: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "clarify", "question": question, "fields": fields}


def report(payload: dict[str, Any]) -> dict[str, Any]:
    return {"type": "report", "report": payload}


def notice(message: str) -> dict[str, Any]:
    return {"type": "notice", "message": message}


def error(message: str) -> dict[str, Any]:
    return {"type": "error", "message": message}
