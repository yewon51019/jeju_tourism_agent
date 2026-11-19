# 제주 관광 소비 인사이트 — JEJU SIGNAL

## 바로 보기

- [키 없이 보는 정적 데모](demo/index.html): 합성 데이터로 작동합니다.
- [구현 반영 기획서](docs/proposal.md) / [인쇄용 기획서](docs/proposal.html): 사용자 기획서의 1~7장 형식, 표지 포함 8개 인쇄 섹션.
- [사용자 제공 원본 기획서](docs/user-proposal.md): 수정하지 않고 보존합니다.
- [실제 CSV 수집 결과](docs/csv-export.md): 월간 19,573행·요일별 1,050행, 수록 기간·검증·재현 방법.
- [변경·검증 기록](docs/verification-notes.md): 실제 조회 이력, 검증 결과와 미완료 항목.

## 현재 구현과 실행 경로

| 경로 | 용도 | 데이터·API |
| --- | --- | --- |
| [demo/index.html](demo/index.html) | 파일을 열어 바로 보는 초기 정적 데모 | 합성 데이터, 외부 API 없음 |
| [app.py](app.py) / [start.bat](start.bat) | Streamlit 보조 앱, 키 설정·분석 검증 | 기본 합성 데이터, Claude 모드만 외부 AI 호출 (제출 ZIP 미포함) |
| [src/server.py](src/server.py) / [run.bat](run.bat) | 디자인 시안 기반 FastAPI 주 웹 앱 | 실제 로컬 CSV 연결, 데이터 API 자동 호출 없음 |

**주 웹 앱에 실제 로컬 CSV를 연결했습니다.** 월간 19,573행과 내국인관광객 요일 자료 525행을 사용합니다. 성별·연령대·업종·관광객/도민 구분을 보존하며, 월간 기본값은 내국인관광객입니다. 원본은 월간 19,573행·요일별 1,050행 그대로 보존했습니다. 상세 검증은 [실제 연결 기록](docs/real-data-connection.md)에 있습니다.

서버 시작 시 데이터 API를 자동 호출하지 않습니다. `run.bat` 또는 설치된 환경에서 `.venv\Scripts\python.exe -m src.server`로 실행하고 http://127.0.0.1:8501 에 접속하세요. 화면에 실제 CSV와 두 데이터의 기간이 표시됩니다. Gemini 키가 없으면 규칙 기반 분석으로 동작합니다. 정적 데모·Streamlit 보조 앱은 이번 실데이터 연결 대상이 아닙니다.

2026-11-19 연결 후 검증: Python 168건 통과, 실제 CSV 웹 API 질문 5건 보고서 생성 및 독립 합산 일치. 이번 연결에서는 데이터 API·LLM을 호출하지 않았습니다. 앞선 원본 수집의 데이터 API 207회 호출 및 별도 작업의 Gemini 합성 데이터 시연과 구분합니다. 향후 기능 변경 시 [문서 동기화 규칙](AGENTS.md)을 따릅니다.

## 저장한 원본을 앱에 연결

```powershell
.venv\Scripts\python.exe -m src.activate_data data/exports/jeju_20261119
.venv\Scripts\python.exe scripts/verify_real_csv.py
```

이 PC에서는 연결 완료했습니다. 연결기는 원본 해시와 형식을 검증하고 `data/raw/card_monthly.csv`, `card_weekday.csv`를 생성합니다. 기존 앱 CSV가 있으면 덮어쓰지 않고 중단합니다. 공개 GitHub에는 실제 CSV와 키가 없으므로 다른 PC에서는 원본을 별도로 준비해야 합니다.

## 실제 원본 CSV 생성

```powershell
.venv\Scripts\python.exe -m src.hub_export --start 200001 --end 202611 --output data/exports/jeju_20261119
```

키는 `.env`의 `JEJU_HUB_PROJECT_KEY`에서 읽습니다. 기존 폴더를 덮어쓰지 않으므로 재실행 시 새 출력 폴더를 지정하세요. UTF-8 BOM CSV 2개와 출처·기간·건수·SHA-256을 담은 `receipt.json`을 만듭니다. 원본 CSV는 Git에서 제외하며 `data/raw/card_*.csv`와 달리 앱에서 자동으로 읽지 않습니다. 자세한 필드·한계는 [수집 결과](docs/csv-export.md)를 참고하세요.

아래 사용 설명은 **초기 정적 데모**에 한정합니다. 주 웹 앱이나 Streamlit의 기능 범위와 혼동하지 마세요.

## 1분 시연

1. 데모를 열고 기본 질문의 해석 결과를 확인합니다.
2. `선택 조건으로 월별 분석 실행`을 누릅니다.
3. 금액·최대 월·전년 대비·월별 수치 표·판단 로그를 확인합니다.
4. `보고서 저장`으로 Markdown 결과를 내려받습니다.
5. `조건이 부족한 질문`을 선택하면 연령·연도를 요청하는지 확인합니다.
6. 2024년을 선택하면 전년도 자료가 없어 `비교 불가`로 나오는지 확인합니다.

## 코드를 읽는 순서

1. [analysis.js](demo/analysis.js): 합성 데이터 생성, 질문 해석, 조건 필터링, 월별 집계, 검증.
2. [app.js](demo/app.js): 입력 이벤트, 분석 함수 호출, 화면과 보고서 출력.
3. [index.html](demo/index.html): 화면 구성.
4. [style.css](demo/style.css): 색상·레이아웃·반응형 스타일.
5. [계산 테스트](tests/analysis.test.cjs): 수작업 정답과 실패 조건 검증.

정적 데모를 실제 데이터로 교체하려면 스키마·금액 단위·모집단을 먼저 확인해야 합니다. 정적 데모 자체에는 CSV 업로드나 실제 API 연결이 없습니다.

## 개발 명령

Python 회귀 테스트는 `.venv\Scripts\python.exe scripts\check_offline.py`로 재현합니다. 실제 API 키와 외부 네트워크를 사용하지 않는 검증용 실행입니다.

Node.js 20 이상 권장. 런타임 패키지 설치는 필요 없습니다.

```sh
node --test tests/analysis.test.cjs tests/documents.test.cjs
node scripts/build-proposal.cjs
```

Markdown 기획서 변경 후 두 번째 명령을 실행하면 인쇄용 HTML이 갱신됩니다. 표지와 1~7장의 8개 인쇄 섹션이며 실제 출력이 15페이지 이하인지 확인하세요. 브라우저 인쇄 설정이나 글꼴에 따라 실제 페이지 수는 달라질 수 있습니다.

## 제약 및 제출 전 남은 일

- 키워드 기반 해석만 제공합니다. 복합 질문·요일·특정 월·시간대 분석은 지원하지 않습니다.
- 정적 데모는 실데이터 미사용입니다. 필수 데이터 활용 증빙과 이용조건 확인이 남아 있습니다.
- 주 웹 앱의 LLM은 Google Gemini API 무료 등급(`gemini-3.5-flash-lite`)이며 평가용 키 준비와 실제 호출 평가는 별도 확인이 필요합니다.
- 기획서의 참가자명·역할을 입력하고 실제 실행 결과로 보완해야 합니다.
- 센터 PC에서 직접 성능을 검증하지 않았습니다.
- 외부 AI 평가용 Key의 예외를 제외하고 실제 인증정보를 제출하지 마세요.

## 데이터 및 외부 자원

데모 데이터는 임의 계수로 자체 생성한 합성 데이터이며 매번 같은 결과를 냅니다. 2024–2025년 × 12개월 × 2개 지역 × 5개 연령 × 3개 업종 = 720행입니다. 외부 폰트·이미지·네트워크 라이브러리·API를 사용하지 않습니다. 브라우저 및 Node.js 기본 API를 사용합니다.

후보 데이터의 출처와 확인 상태는 [기획서](docs/proposal.md)에 기재했습니다. 작성에 AI 코딩 도구를 활용했으며, 실제 도구·모델명과 사용 범위는 제출자가 확인해 최종 명세에 반영해야 합니다.
