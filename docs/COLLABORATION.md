# 협업 작업 경계

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
