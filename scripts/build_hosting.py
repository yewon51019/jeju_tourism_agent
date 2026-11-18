"""Firebase Hosting에 올릴 정적 데모를 public 폴더에 만든다.

실행: python scripts/build_hosting.py
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent import DEFAULT_MODEL  # noqa: E402
from src.data_pipeline import load_store  # noqa: E402
from src.rule_engine import clarification_fields, run_rules  # noqa: E402

STATIC = ROOT / "static"
PUBLIC = ROOT / "public"
DEMO_FLAG = "<script>window.JEJU_STATIC_DEMO = true;</script>\n  <script src=\"/static/app.js\"></script>"


def demo_questions() -> tuple[list[str], str]:
    source = (STATIC / "app.js").read_text(encoding="utf-8")
    presets = re.findall(r"query: '([^']+)'", source)
    ambiguous = re.search(r"AMBIGUOUS_QUERY = '([^']+)'", source)
    if not presets or ambiguous is None:
        raise RuntimeError("static/app.js에서 예시 질문을 찾을 수 없습니다.")
    return presets, ambiguous.group(1)


def build() -> dict[str, int]:
    store = load_store()
    if not store.is_sample:
        raise RuntimeError("공개 데모는 합성 샘플 데이터로만 만듭니다. data/raw의 파일을 제외하고 다시 실행해 주세요.")
    presets, ambiguous = demo_questions()
    runs = {question: list(run_rules(question, None, store)) for question in [*presets, ambiguous]}
    fields = {field["key"]: field["options"] for field in clarification_fields(store)}
    for region, theme, age in product(fields["region"], fields["theme"], fields["age"]):
        answers = {"region": region, "theme": theme, "age": age}
        runs["||".join([ambiguous, region, theme, age])] = list(run_rules(ambiguous, answers, store))

    if PUBLIC.exists():
        shutil.rmtree(PUBLIC)
    shutil.copytree(STATIC, PUBLIC / "static")
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    if '<script src="/static/app.js"></script>' not in index:
        raise RuntimeError("static/index.html에서 app.js 태그를 찾을 수 없습니다.")
    (PUBLIC / "static" / "index.html").unlink()
    (PUBLIC / "index.html").write_text(index.replace('<script src="/static/app.js"></script>', DEMO_FLAG), encoding="utf-8")
    status = {"ready": True, "llm": False, "model": DEFAULT_MODEL, "source": store.source, "period": store.period,
              "isSample": True, "quality": store.quality}
    payload = json.dumps({"status": status, "runs": runs}, ensure_ascii=False, separators=(",", ":"))
    (PUBLIC / "static" / "demo.json").write_text(payload, encoding="utf-8")
    failed = sum(1 for events in runs.values() if events[-1]["type"] not in ("report", "clarify"))
    return {"runs": len(runs), "failed": failed, "bytes": len(payload.encode("utf-8"))}


if __name__ == "__main__":
    print(build())
