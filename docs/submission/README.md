# 제주 관광 소비 인사이트 Agent

자연어 질문을 해석해 제주 관광 카드 소비 데이터를 분석하고, 검증된 수치와 실행 제안이 담긴 보고서를 만드는 AI Agent입니다.

## 빠른 실행

1. Python 3.12 이상을 설치합니다. 개발과 테스트는 Python 3.14에서 진행했습니다.
2. ZIP을 `C:\jeju_tourism_agent`처럼 경로가 짧은 폴더에 풀고 `run.bat`을 더블클릭합니다. 첫 실행 때 필요한 패키지를 자동으로 설치합니다.
3. 브라우저에서 `http://127.0.0.1:8501`이 열리면 예시 질문을 누릅니다.
4. Gemini로 실행하려면 화면 오른쪽 위 `API 키 입력`에 `EVALUATION_KEY.md`의 평가용 키를 입력합니다.
5. `data/raw/`의 실제 CSV가 있으면 데이터 API 키 없이 사용합니다. 없으면 사용자 매뉴얼 2.2~2.3절에 따라 원본을 명시적으로 수집하고 로컬 연결 명령을 실행합니다. 서버 시작 시 자동 수집하지 않습니다.

Gemini API 키가 없으면 규칙 기반 분석으로 실행됩니다. `data/raw/`에 데이터가 없으면 프로젝트 키 유무와 관계없이 합성 샘플로 표시됩니다. 일부 파일만 있으면 오류를 표시합니다.

## 처리 흐름

1. 사용자의 문장을 Gemini API로 보내 지역, 업종, 고객층, 기간, 분석 유형을 정해진 JSON 형식으로 받습니다.
2. 받은 JSON을 코드로 검증하고, 조건이 부족하면 사용자에게 선택지를 제시합니다.
3. Gemini가 분석 도구를 선택하면 Python 코드가 제주데이터허브 데이터를 집계하고 원본으로 재계산해 검증합니다.
4. Gemini가 정해진 보고서 형식으로 결과를 제출하면, 코드가 형식과 수치 근거를 확인한 뒤 화면에 표시합니다.

## 제출물 구성

| 구분 | 위치 |
| --- | --- |
| 실행 소스 코드 | `src/`, `static/`, `scripts/` |
| Prompt | `src/prompts.py` |
| 생성형 AI API 호출, 응답 형식 검증 | `src/agent.py`, `src/interpreter.py` |
| 제주데이터허브 API 호출 | `src/hub_api.py`, `scripts/fetch_hub_data.py` |
| 분석 Tool | `src/tools/` |
| API 키 입력 위치 | `.env` (`.env.example` 참고, 발급 방법은 `docs/user_manual.md` 2절) |
| 의존성 목록 | `requirements.txt` |
| 환경변수 예시 | `.env.example` |
| 사용자 매뉴얼, 오류·제약사항 | `docs/user_manual.md` |
| 평가용 API 키 안내 | `EVALUATION_KEY.md` |
| 데이터 활용 명세 | `docs/data_usage_spec.md` |
| 결과 설명자료 | `docs/result_report.md` |
| 평가 결과 | `docs/evaluation_result.md` |
| 사용 AI·외부 자원 내역 | `docs/disclosure.md` |
| 테스트 코드 | `tests/` |

## 외부 서비스 의존성

| 서비스 | 용도 | 필요한 인증 | 비용 |
| --- | --- | --- | --- |
| Google Gemini API (무료 등급) | 질문 해석, 분석 계획, 보고서 문장 작성 | Gemini API 키 | 무료, 등급별 사용량 한도 적용 |
| 제주데이터허브 Open API | 카드 소비 데이터 수집 | 프로젝트 키 | 무료, 데이터별 일일 1,000회 |

Gemini API 무료 등급에서는 입력 내용이 Google 제품 개선에 활용될 수 있으므로 질문에 개인정보나 민감정보를 입력하지 마세요. 제주데이터허브 프로젝트 키는 제출물에 포함하지 않았습니다. 발급 방법과 입력 위치는 `docs/user_manual.md` 2.2절에 있습니다.

## 테스트

```bat
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts\evaluate.py
```
