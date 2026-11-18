# 제주 관광 소비 인사이트 Agent

자연어 질문을 해석해 제주 관광 카드 소비 데이터를 분석하고, 검증된 수치와 실행 제안이 담긴 보고서를 만드는 AI Agent입니다.

## 빠른 실행

1. Python 3.12 이상을 설치합니다. 개발과 테스트는 Python 3.14에서 진행했습니다.
2. ZIP을 `C:\jeju_tourism_agent`처럼 경로가 짧은 폴더에 풀고 `run.bat`을 더블클릭합니다. 첫 실행 때 필요한 패키지를 자동으로 설치합니다.
3. 브라우저에서 `http://127.0.0.1:8501`이 열리면 예시 질문을 누릅니다.
4. Claude로 실행하려면 화면 오른쪽 위 `API 키 입력`에 `EVALUATION_KEY.md`의 평가용 키를 입력합니다.

API 키가 없으면 규칙 기반 분석으로 실행됩니다. `data/raw/`에 데이터가 없으면 합성 샘플 데이터로 실행되며 화면에 그 사실을 표시합니다.

## 제출물 구성

| 구분 | 위치 |
| --- | --- |
| 실행 소스 코드 | `src/`, `static/`, `scripts/` |
| Prompt | `src/prompts.py` |
| Tool/API 연동 | `src/tools/`, `src/agent.py`, `scripts/fetch_hub_data.py` |
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
| Anthropic Claude API | 질문 해석, 분석 계획, 보고서 문장 작성 | Claude API 키 | 평가 중 비용은 참가자 부담 |
| 제주데이터허브 Open API | 카드 소비 데이터 수집 | 프로젝트 키 | 무료, 데이터별 일일 1,000회 |

제주데이터허브 프로젝트 키는 제출물에 포함하지 않았습니다. 발급과 설정 방법은 `docs/user_manual.md`에 있습니다.

## 테스트

```bat
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts\evaluate.py
```
