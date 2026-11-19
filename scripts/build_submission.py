"""공모전 제출용 ZIP을 dist 폴더에 만든다.

실행: python scripts/build_submission.py
평가용 Gemini API 키는 프로젝트 폴더의 EVALUATION_KEY.txt에 한 줄로 저장해 두면 ZIP에 포함된다.
"""
from __future__ import annotations

import os
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dotenv import load_dotenv  # noqa: E402

from evaluate import evaluate, to_markdown  # noqa: E402
from src.data_pipeline import load_store  # noqa: E402
from src.rule_engine import run_rules  # noqa: E402
from src.settings import KEY_PATTERN  # noqa: E402

PACKAGE = "jeju_tourism_agent"
DIST = ROOT / "dist"
SKIP_REQUIREMENTS = ("streamlit", "matplotlib", "anthropic")
FILES = [".env.example", "run.bat", "download_data.bat", "pytest.ini", "docs/user_manual.md", "docs/data_usage_spec.md",
         "docs/disclosure.md", "scripts/fetch_hub_data.py", "scripts/evaluate.py", "tests/test_analysis.py",
         "tests/test_web_agent.py", "tests/test_rank_coverage.py", "tests/test_hub_fetch.py",
         "tests/test_hub_export.py", "tests/test_real_csv_connection.py", "docs/csv-export.md",
         "docs/real-data-connection.md", "scripts/refresh_reports.py", "scripts/check_offline.py"]
TREES = {"src": "*.py", "static": "*"}
EXCLUDED_DIRS = {"jeju_agent", "__pycache__"}
SECRET = re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}|ghp_[A-Za-z0-9]{30,}|AIza[0-9A-Za-z_\-]{30,}")
TEXT_SUFFIXES = {".py", ".md", ".txt", ".bat", ".ini", ".html", ".css", ".csv", ".example", ".json", ".js", ".mjs"}


def evaluation_key_doc() -> tuple[str, bool]:
    path = ROOT / "EVALUATION_KEY.txt"
    key = path.read_text(encoding="utf-8").strip() if path.exists() else ""
    if key and not KEY_PATTERN.fullmatch(key):
        raise SystemExit("EVALUATION_KEY.txt의 키 형식이 올바르지 않습니다.")
    value = key or "[제출 전 평가용 Gemini API 키 입력]"
    return ("# 평가용 Gemini API 키\n\n"
            "심사위원 평가를 위해 참가자가 준비한 외부 AI API 키입니다.\n\n"
            f"```text\n{value}\n```\n\n"
            "## 사용 방법\n\n"
            "1. `run.bat`을 실행합니다.\n"
            "2. 화면 오른쪽 위 `API 키 입력`을 누릅니다.\n"
            "3. 위 키를 붙여넣고 `확인 후 저장`을 누릅니다.\n\n"
            "화면 대신 프로젝트 폴더의 `.env` 파일에서 `GEMINI_API_KEY=` 뒤에 키를 입력해도 됩니다.\n\n"
            "## 안내\n\n"
            "- 이 키는 평가 전용이며 결제를 연결하지 않은 Gemini API 무료 등급 키입니다. 평가 중 비용이 발생하지 않습니다.\n"
            "- 무료 등급 사용량을 초과하면 규칙 기반 분석으로 전환됩니다.\n"
            "- 무료 등급에서는 입력 내용이 Google 제품 개선에 활용될 수 있으므로 개인정보나 민감정보를 입력하지 마세요.\n"
            "- 평가 기간 종료 후 이 키는 삭제·폐기합니다.\n"
            "- 제주데이터허브 프로젝트 키는 제출물에 포함하지 않았습니다. 발급과 설정 방법은 `docs/user_manual.md` 2.2절에 있습니다.\n"), bool(key)


def result_report(store, evaluation: str) -> str:
    source = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    questions = re.findall(r"query: '([^']+)'", source)
    notice = ("> 이 문서의 실행 결과는 **합성 샘플 데이터**로 계산했으며 실제 제주 관광 통계가 아닙니다.\n\n" if store.is_sample
              else f"> 이 문서의 실행 결과는 제주데이터허브 실제 CSV로 계산했습니다. 월간 {store.period}, 요일별 {store.weekday_months[0]} ~ {store.weekday_months[-1]}. 현재 통계가 아닙니다.\n\n")
    lines = ["# 결과 설명자료", "", notice,
             "원본 CSV 취득은 [수집 결과](csv-export.md), 실제 연결·독립 합산 검증은 [연결 기록](real-data-connection.md)에 기록합니다. 아래 분석 사례의 데이터와 합성 데이터 회귀 평가를 구분합니다.", "",
             "## 1. 문제 정의", "",
             "제주 관광 소비 데이터는 공개되어 있지만, 분석 경험이 없는 소상공인과 센터 이용자는 데이터를 고르고 집계해 의사결정에 활용하기 어렵습니다. "
             "본 Agent는 자연어 질문만으로 소비 시기, 고객층, 지역, 업종을 분석하고 근거가 있는 보고서를 제공합니다.", "",
             "## 2. Agent 구조", "",
             "| 단계 | 담당 | 내용 |", "| --- | --- | --- |",
             "| 질문 해석 | Gemini + Python | 지역, 업종, 고객층, 기간, 분석 유형을 정해진 JSON 형식으로 받아 코드로 검증 |",
             "| 조건 확인 | Gemini | 조건이 모호하면 사용자에게 선택지 제시 |",
             "| 데이터 준비 | Python | 승인된 원본 CSV를 로컬에서 변환·검증. 서버 시작 시 데이터 API 자동 호출 없음 |",
             "| 분석 계획 | Gemini | 데이터와 도구 선택 |",
             "| 집계·분석 | Python | 추세, 순위, 비중, 증감률, 요일 패턴 계산 |",
             "| 결과 검증 | Python | 원본 재계산, 조건 일치, 비중 합계, 표본 크기 점검 |",
             "| 보고서 생성 | Gemini + Python | 검증된 수치로 보고서 작성, 근거 없는 수치 차단 |", "",
             "Gemini API를 사용할 수 없으면 규칙 기반 분석으로 전환해 같은 계산과 검증을 수행합니다.", "",
             "## 3. 주요 기능", "",
             "- 자연어 질의와 조건 되묻기", "- 월별 추세, 순위, 전년 대비 증감률, 요일별 패턴 분석",
             "- 원본 데이터 재계산 검증과 판단 로그", "- 차트, 수치 근거, 실행 제안이 포함된 보고서", "- 요약 복사와 PDF 저장", "",
             "## 4. 실행 결과", "", "아래 결과는 규칙 기반 분석 경로로 실행했습니다.", ""]
    for number, question in enumerate(questions, start=1):
        event = list(run_rules(question, None, store))[-1]
        lines += [f"### 사례 {number}. {question}", ""]
        if event["type"] != "report":
            lines += [f"결과: {event.get('question') or event.get('message')}", ""]
            continue
        report = event["report"]
        checks = report["verification"]
        lines += [f"**{report['title']}**", "", report["summary"].replace("**", ""), "",
                  *[f"- {k['label']}: {k['value']} ({k['sub']})" for k in report["kpis"]],
                  f"- 검증 결과: {checks['total']}건 중 {checks['passed']}건 통과, 경고 {checks['warnings']}건", "",
                  "해석 시 주의사항:", "", *[f"- {item}" for item in report["limitations"]], ""]
    body = evaluation.replace("# 평가 결과", "## 5. 검증 방법 및 결과", 1)
    lines += [body, "",
              "검증 항목은 원본 재계산, 조건 일치, 비중 합계, 표본 크기입니다. 자동 테스트는 `tests/` 폴더에 있습니다.", "",
              "## 6. 한계", "",
              "- 필수 데이터의 수록 기간이 2016~2018년이어서 최근 소비 동향을 반영하지 않습니다.",
              "- 카드 이용 내역만 분석하며 현금 등 다른 결제 수단은 포함하지 않습니다.",
              "- 요일별 데이터에는 업종, 연령, 성별이 없고 월간 데이터와 수록 기간이 다릅니다.",
              "- 분석 결과는 상관관계에 기반하며 실행 제안의 매출 효과를 보장하지 않습니다.",
              "- 위 평가는 규칙 기반 경로를 측정한 것이며 Gemini API 경로의 성능은 포함하지 않습니다.", "",
              "## 7. 센터 활용 방안", "",
              "- 방문 이용자의 셀프 분석 도구와 소상공인 상담 자료로 활용합니다.",
              "- 판단 로그를 데이터 분석 입문 교육 자료로 활용합니다.",
              "- 데이터와 Tool을 추가해 교통, 환경 등 다른 분야로 확장합니다.", ""]
    return "\n".join(lines)


def collect() -> dict[str, Path]:
    files = {name: ROOT / name for name in FILES}
    for folder, pattern in TREES.items():
        for path in (ROOT / folder).rglob(pattern):
            if path.is_file() and path.name != ".env" and not EXCLUDED_DIRS & set(path.relative_to(ROOT).parts):
                files[path.relative_to(ROOT).as_posix()] = path
    for name in ("card_monthly.csv", "card_weekday.csv"):
        path = ROOT / "data" / "raw" / name
        if path.exists():
            files[f"data/raw/{name}"] = path
    return files


def scan(contents: dict[str, bytes]) -> None:
    load_dotenv(ROOT / ".env")
    hub_key = os.getenv("JEJU_HUB_PROJECT_KEY", "").strip()
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    for name, data in contents.items():
        if Path(name).name == ".env" or Path(name).suffix not in TEXT_SUFFIXES:
            continue
        text = data.decode("utf-8", "ignore")
        if name != "EVALUATION_KEY.md" and SECRET.search(text):
            raise SystemExit(f"제출물에 인증 정보로 보이는 값이 있습니다: {name}")
        if name != "EVALUATION_KEY.md" and gemini_key and gemini_key in text:
            raise SystemExit(f"제출물에 Gemini API 키가 있습니다: {name}")
        if hub_key and hub_key in text:
            raise SystemExit(f"제출물에 제주데이터허브 프로젝트 키가 있습니다: {name}")


def main() -> int:
    store = load_store()
    evaluation = to_markdown(evaluate())
    report = result_report(store, evaluation)
    (ROOT / "docs" / "evaluation_result.md").write_text(evaluation, encoding="utf-8")
    (ROOT / "docs" / "result_report.md").write_text(report, encoding="utf-8")
    key_doc, has_key = evaluation_key_doc()
    requirements = [line for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
                    if line and not line.startswith(SKIP_REQUIREMENTS)]
    contents = {name: path.read_bytes() for name, path in collect().items()}
    contents.update({"README.md": (ROOT / "docs" / "submission" / "README.md").read_bytes(),
                     "requirements.txt": ("\n".join(requirements) + "\n").encode("utf-8"),
                     "EVALUATION_KEY.md": key_doc.encode("utf-8"),
                     "docs/evaluation_result.md": evaluation.encode("utf-8"),
                     "docs/result_report.md": report.encode("utf-8"),
                     "data/raw/README.md": "제주데이터허브 데이터 CSV를 저장하는 폴더입니다. `docs/user_manual.md` 2.2절을 참고하세요.\n".encode("utf-8")})
    scan(contents)
    DIST.mkdir(exist_ok=True)
    target = DIST / f"{PACKAGE}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(contents):
            archive.writestr(f"{PACKAGE}/{name}", contents[name])
    print(f"ZIP: {target} ({target.stat().st_size / 1024 / 1024:.1f}MB, {len(contents)}개 파일)")
    print(f"데이터: {'합성 샘플 (실제 데이터 없음)' if store.is_sample else '제주데이터허브 실제 데이터'}")
    print(f"평가용 Gemini API 키: {'포함됨' if has_key else '미포함 (EVALUATION_KEY.md에 입력 필요)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
