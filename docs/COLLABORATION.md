# 협업 작업 경계

## 요일 API 재검증 정정 (2026-11-19 08:44 KST)

사용자가 이전 403 결과의 재확인을 요청하여 실제 외부 네트워크로 읽기 전용 요청 3건을 수행했다. 로컬 설정의 프로젝트 키를 사용했으며 키·요청 URL·원본 데이터는 기록하거나 저장하지 않았다.

| 조회 | 조건 | 최신 결과 |
| --- | --- | --- |
| 요일 API, 관광객 구분 미지정 | startDate=endDate=201711, number=1, limit=1 | HTTP 200, 1행 수신, totCnt=70, hasMore=true |
| 요일 API, 내국인관광객 | 같은 기간·페이지 조건, userType=내국인관광객 | HTTP 200, 1행 수신, totCnt=35, hasMore=true |
| 월간 API 대조 조회 | startDate=endDate=201812, number=1, limit=1, userType=내국인관광객 | HTTP 200, 1행 수신, totCnt=335, hasMore=true |

요일 응답에서 districtType, userType, dtYearMonth, dtWeek, userCount, useCount, useCost 필드를 확인했다. 총건수는 서버가 알린 값이며 전체 수집·검증한 행 수가 아니다. 이전 403 원인은 확정하지 못했다. 현재 권한 거부가 재현되지 않으므로 **403을 이유로 요일 분석을 비활성화한다는 계획은 철회**한다. 이는 앱에 실데이터를 탑재하거나 전체 기간을 수집했다는 뜻이 아니다. 월·요일 집계와 월간 연령·업종별 집계를 직접 결합해서는 안 된다.

직전 사용자 승인으로 월간 실제 데이터의 일회성 수집·로컬 분석 전환을 진행할 수 있게 되었으나, 이번 재검증에서는 위 3건만 요청했다. 지속 자동 수집이나 유료 LLM 호출을 실행하지 않았다.

문서 충돌·인계: proposal.md, proposal.html, verification-notes.md, result_report.md, evaluation_result.md, README.md, user_manual.md 등이 다른 작업에서 수정 중이므로 이번 진단에서는 덮어쓰지 않는다. 담당자는 기획서 4장·6장·7장의 "요일 API 403/권한 미확인"을 위 최신 결과로 갱신하고, 과거 403은 이력으로 구분해야 한다. proposal.html은 scripts/build-proposal.cjs로 동기화해야 한다. 원본 user-proposal.md는 변경하지 않는다. 이 기록은 직접 Claude 검토 완료를 의미하지 않는다.

## 최신 사용자 지시 및 인계 (2026-11-19)

- 변경할 때마다 사용자 기획서의 1~7장 순서에 맞춰 문서를 갱신한다. 목표·구현·실측·보류를 구분한다.
- 원본 user-proposal.md는 보존한다. proposal.md/proposal.html은 구현 반영본이며 verification-notes.md에 근거를 남긴다.
- 실제 데이터 API는 소량 확인 후 임시 코드를 제거한 상태다. 자동 수집·지속 연결을 승인받은 것으로 확대 해석하지 않는다.
- 월간 API 201812 내국인관광객 5행 HTTP 200, 총건수 표시335. 요일별 API 201711 HTTP 403. 실데이터 앱 반영은 미완료.
- Codex는 app.py 키 입력칸 초기화, tests/test_streamlit_ui.py, .gitignore 테스트 임시 경로, README와 위 문서를 담당한다.
- 주 FastAPI 서버의 자동 수집과 Claude JSON 해석기, 관련 문서는 동시 작업 변경으로 관찰했다. 임의로 덮어쓰거나 커밋하지 않는다.
- 자동 수집 변경은 사용자의 임시 연결·롤백 요청과 충돌 가능성이 있어 주 서버를 실행하지 않았다. 담당자는 이 조건을 먼저 확인할 것.
- 최종 로컬 작업 트리 Python 141건·정적 데모 JS 6건·문서 검사 4건 통과. 실제 LLM은 호출하지 않았다.
- Claude와 직접 통신은 확인되지 않았다. 이 인계문은 협업 요청이지 Claude의 검토 완료 증거가 아니다.
- 사용자는 잠든 동안 직접 권한 요청이 필요한 작업을 미루라고 지시했다. 신규 유료 호출·권한 승인·외부 배포·제출은 보류한다.
- 사용자 요청으로 주 웹 앱의 생성형 AI를 Gemini API 무료 등급으로 교체했다. Streamlit 보조 앱은 제출 ZIP에 없어 Claude 설정을 유지한다. 정상 키로 Gemini를 호출한 검증은 남아 있다.

아래는 이전 작업 기록이다. 최신 상태는 이 절과 verification-notes.md를 우선한다.

## Codex 작업 (2026-11-19)

- 사용자 요청: 기획서 기반 구현, agent_mvp.html 디자인 참조, 사람이 읽기 쉬운 코드, 웹에서 API Key 저장, GitHub yewon51019/jeju_tourism_agent에 단계별 push.
- Codex 소유: app.py (Streamlit), src/jeju_agent/*, assets/streamlit.css, start.bat/start.ps1, demo/*, tests/test_agent.py/test_tools.py/test_settings.py/test_streamlit_ui.py/analysis.test.cjs, docs/user-proposal.md, evaluation/*.
- 별도 진행 중인 것으로 관찰한 작업: src/server.py 및 src/*.py, src/tools/*, static/*, run.bat, tests/test_analysis.py/test_web_agent.py, Firebase workflow. 작성자 확인 없이 수정하거나 삭제하지 않는다.
- 공통 requirements.txt는 현재 두 앱 의존성을 합친 상태로 관찰했다. .gitignore는 Key·가상환경·생성물 제외를 유지한다.
- Streamlit Key는 프로젝트 .env에 저장하고 화면에는 재출력하지 않는다. 비밀번호 입력, 저장·삭제, 세션별 명시 전달 구현.
- 실제 유료 LLM 호출은 하지 않는다. 테스트는 임시 가짜 Key와 Mock으로 검증한다.
- 최초 remote 확인 시 빈 저장소였으며 Git 초기화만 완료. push 완료 여부는 별도 확인 필요.

## 주의

원본 사용자 기획서는 user-proposal.md이다. proposal.md/proposal.html은 앞서 만든 초기 초안이며 최신 요구사항의 기준이 아니다. 실제 데이터 등재·API 승인·Claude 실제 호출은 미확인 상태를 유지한다.
