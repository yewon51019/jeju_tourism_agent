# 협업 작업 경계

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
