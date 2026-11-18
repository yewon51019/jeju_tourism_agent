"""웹 화면과 분석 API를 제공한다. 실행: python -m src.server"""
from __future__ import annotations

import json
import os
import threading
import webbrowser
from pathlib import Path
from typing import Iterator

import uvicorn
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent import llm_available, run_agent
from .data_pipeline import DataError, DataStore, load_store
from .events import error
from .hub_api import ensure_hub_data
from .settings import DEFAULT_MODEL, MODEL_NAME, KeyRejected, delete_key, save_key

ROOT = Path(__file__).resolve().parent.parent
LOCAL_HOSTS = {"127.0.0.1", "localhost"}
STATIC_DIR = ROOT / "static"
load_dotenv(ROOT / ".env")

app = FastAPI(title="제주 관광 소비 인사이트 Agent")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
_store: DataStore | None = None
_store_error: str | None = None
_data_notice: str | None = None
_lock = threading.Lock()


class AnalyzeRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    answers: dict[str, str] | None = None


class ApiKeyRequest(BaseModel):
    api_key: str = Field(min_length=1, max_length=300)


def require_local(request: Request) -> None:
    """다른 웹사이트가 이 PC의 설정을 바꾸지 못하도록 로컬 화면의 요청만 허용한다."""
    host = request.headers.get("host", "")
    origin = request.headers.get("origin")
    if host.rsplit(":", 1)[0] not in LOCAL_HOSTS or (origin is not None and origin.split("://")[-1] != host):
        raise HTTPException(status_code=403, detail="이 PC의 화면에서만 사용할 수 있습니다.")


@app.exception_handler(RequestValidationError)
async def invalid_request(_: Request, __: RequestValidationError) -> JSONResponse:
    """입력값이 응답에 되돌아가지 않도록 일반 오류 문구만 보낸다."""
    return JSONResponse(status_code=422, content={"detail": "요청 형식이 올바르지 않습니다."})


def get_store() -> DataStore:
    global _store, _store_error
    with _lock:
        if _store is None:
            try:
                _store = load_store()
                _store_error = None
            except DataError as exc:
                _store_error = str(exc)
                raise
        return _store


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
def status() -> dict:
    try:
        store = get_store()
    except DataError as exc:
        return {"ready": False, "error": str(exc)}
    return {
        "ready": True, "llm": llm_available(), "model": os.getenv(MODEL_NAME) or DEFAULT_MODEL,
        "source": store.source, "period": store.period, "isSample": store.is_sample, "quality": store.quality,
        "dataNotice": _data_notice,
    }


@app.post("/api/settings/api-key", dependencies=[Depends(require_local)])
def store_api_key(request: ApiKeyRequest) -> dict:
    try:
        return save_key(request.api_key, os.getenv(MODEL_NAME) or DEFAULT_MODEL)
    except KeyRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/settings/api-key", dependencies=[Depends(require_local)])
def remove_api_key() -> dict:
    return delete_key()


@app.post("/api/analyze", dependencies=[Depends(require_local)])
def analyze(request: AnalyzeRequest) -> StreamingResponse:
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="질문을 입력해 주세요.")

    def stream() -> Iterator[str]:
        try:
            store = get_store()
            for event in run_agent(question, request.answers, store):
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except DataError as exc:
            yield json.dumps(error(str(exc)), ensure_ascii=False) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


def main() -> None:
    global _data_notice
    _data_notice = ensure_hub_data()
    if _data_notice:
        print(_data_notice, flush=True)
    port = int(os.getenv("PORT", "8501"))
    if os.getenv("OPEN_BROWSER", "1") == "1":
        threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
