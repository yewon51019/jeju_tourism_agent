# 사용 AI 및 외부 자원 내역

## 1. 서비스 실행에 사용하는 AI

| 모델 | 제공사 | 활용 범위 |
| --- | --- | --- |
| Claude Opus 5.5 (`claude-opus-5-5`) | Anthropic | 질문 해석, 분석 계획, 도구 선택, 결과 해석, 보고서 문장 작성 |

수치 계산과 검증은 AI가 아니라 Python 코드가 수행합니다.

## 2. 개발 과정에서 사용한 AI 도구

| 도구 | 활용 범위 |
| --- | --- |
| Claude Code (Claude Opus 5.5) | 주제 검토, 기획서 초안, 코드 작성, 문서 작성 |
| OpenAI Codex | 계산 엔진 테스트 코드 작성, 코드 검토 |
| ChatGPT | 제출물 구성 검토 |

## 3. 외부 API 및 서비스

| 서비스 | 제공처 | 용도 |
| --- | --- | --- |
| Claude API | Anthropic | Agent의 LLM 호출 |
| 제주데이터허브 Open API | 제주데이터허브 | 필수 데이터 수집 |

## 4. 외부 데이터

필수 데이터 외의 외부 데이터는 사용하지 않았습니다. 필수 데이터의 출처는 `docs/data_usage_spec.md`에 있습니다.

## 5. 오픈소스

| 이름 | 버전 | 라이선스 | 용도 |
| --- | --- | --- | --- |
| anthropic | 2.10.0 | Apache-2.0 | Claude API 연동 |
| FastAPI | 0.164.0 | MIT | 웹 API 서버 |
| Uvicorn | 0.54.0 | BSD-3-Clause | 웹 서버 실행 |
| pandas | 3.1.1 | BSD-3-Clause | 데이터 처리 |
| NumPy | 2.5.5 | BSD-3-Clause 등 | 수치 계산 |
| python-dotenv | 1.2.4 | BSD-3-Clause | 환경변수 관리 |
| HTTPX | 0.28.1 | BSD-3-Clause | 데이터 API 호출, 테스트 |
| pytest | 9.2.0 | MIT | 테스트 |
| Chart.js | 4.4.9 | MIT | 차트 |
| Tailwind CSS | 3.4.17 | MIT | 화면 스타일 |
| Pretendard | 1.3.9 | OFL-1.1 | 화면 글꼴 |

화면 구성은 참가자가 준비한 디자인 시안을 바탕으로 구현했습니다. 위 오픈소스 외의 외부 코드는 사용하지 않았습니다.
