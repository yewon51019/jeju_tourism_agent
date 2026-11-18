"""Streamlit 진입점. 데이터 계산은 src/jeju_agent의 도구에 위임합니다."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from src.jeju_agent.agent import AgentResponse, InsightAgent
from src.jeju_agent.tools import ToolRegistry
from src.jeju_agent.settings import clear_api_key, load_settings, save_settings, validate_settings

ROOT = Path(__file__).parent
st.set_page_config(page_title="제주 관광 소비 인사이트 Agent", page_icon="🍊", layout="wide")


def apply_page_style() -> None:
    """UI 스타일은 별도 파일에 둡니다. 입력 문자열을 CSS/HTML에 삽입하지 않습니다."""
    st.html((ROOT / "assets/streamlit.css").read_text(encoding="utf-8"))


def read_output_file(file_path: str | None) -> bytes | None:
    """도구가 반환한 파일도 출력 디렉터리 안에 있는지 확인합니다."""
    if not file_path:
        return None
    path = Path(file_path).resolve()
    output_root = (ROOT / "outputs").resolve()
    if not path.is_relative_to(output_root) or not path.is_file():
        return None
    return path.read_bytes()


def show_api_settings() -> dict[str, str]:
    """Key를 되표시하지 않는 설정 폼. 저장 후 바로 같은 세션에서 사용합니다."""
    if "api_settings" not in st.session_state:
        st.session_state.api_settings = load_settings()
    settings = st.session_state.api_settings
    with st.expander("🔑 API Key 설정", expanded=not bool(settings["api_key"])):
        st.caption("저장 위치: 이 앱이 실행되는 PC의 .env. GitHub에 올리지 않으며 암호화 파일은 아닙니다.")
        if settings["api_key"]:
            st.success("Key 저장됨 · 실제 API 인증은 아직 확인하지 않았습니다.")
        with st.form("api_settings_form", clear_on_submit=True):
            # 저장 직후 rerun에서도 이전 비밀 입력값이 남지 않도록 새 위젯을 사용합니다.
            input_revision = st.session_state.get("api_key_input_revision", 0)
            entered_key = st.text_input("Anthropic API Key", type="password",
                                        key=f"api_key_input_{input_revision}",
                                        placeholder="새 Key 입력 · 기존 Key 유지 시 비워 두세요")
            model = st.text_input("모델 ID", value=settings["model"])
            remember = st.checkbox("다음 실행에도 사용하도록 이 PC에 저장", value=True)
            submitted = st.form_submit_button("저장하고 Claude 모드로 전환", type="primary")
        if submitted:
            try:
                api_key, model = validate_settings(entered_key or settings["api_key"], model)
                if remember:
                    save_settings(api_key, model)
                st.session_state.api_settings = {"api_key": api_key, "model": model}
                st.session_state.execution_mode = "Claude Agent"
                st.session_state.api_key_input_revision = input_revision + 1
                st.rerun()
            except ValueError as error:
                st.error(str(error))
            except OSError:
                st.error("설정 파일을 저장하지 못했습니다. 폴더 쓰기 권한을 확인하세요.")
        if settings["api_key"] and st.button("저장된 Key 삭제"):
            try:
                clear_api_key()
                st.session_state.api_settings = {"api_key": "", "model": settings["model"]}
                st.session_state.execution_mode = "오프라인 데모"
                st.session_state.api_key_input_revision = input_revision + 1
                st.rerun()
            except OSError:
                st.error("설정 파일을 변경하지 못했습니다. 쓰기 권한을 확인하세요.")
    return st.session_state.api_settings


def show_response(response: AgentResponse) -> None:
    if response.status == "error":
        st.error(response.message)
    elif response.status in {"limited", "unsupported", "clarification"}:
        st.warning(response.message)
    else:
        st.success(response.message)

    report_tab, log_tab = st.tabs(["📊 분석 보고서", "🔍 판단 로그"])
    with report_tab:
        for result in response.results:
            st.caption(f"분석 결과 ID: {result.get('result_id', '')}")
            records = result.get("rows", result.get("data", result.get("table", [])))
            if isinstance(records, list) and records:
                st.dataframe(pd.DataFrame(records), hide_index=True, width="stretch")
            for warning in result.get("warnings", []):
                st.warning(warning)
        for log in response.logs:
            if log["tool"] == "create_chart":
                output = log["output"]
                image = read_output_file(output.get("path", output.get("file_path")))
                if image:
                    st.image(image, caption="코드로 계산한 결과의 시각화", width="stretch")
        if response.report:
            report = response.report
            content = report.get("markdown", report.get("content", ""))
            report_bytes = read_output_file(report.get("path", report.get("file_path")))
            if not content and report_bytes:
                content = report_bytes.decode("utf-8-sig")
            if content:
                st.markdown(content)
                st.download_button("보고서 내려받기 ↓", content, file_name="제주_소비_분석보고서.md", mime="text/markdown")
        elif not response.results:
            st.caption("아직 분석 결과가 없습니다. 조건을 보완하거나 지원되는 질문을 입력하세요.")
    with log_tab:
        for index, log in enumerate(response.logs, 1):
            with st.expander(f"{index:02d} · {log['tool']}", expanded=False):
                st.json(log)
        st.caption("이 로그는 도구 호출·검증 기록이며 모델 내부 사고 과정이 아닙니다.")


def main() -> None:
    apply_page_style()
    with st.sidebar:
        st.title("🍊 JEJU SIGNAL")
        st.caption("제주 관광 소비 인사이트 Agent")
        settings = show_api_settings()
        mode = st.radio("실행 모드", ["오프라인 데모", "Claude Agent"], key="execution_mode")
        data_mode = st.radio("분석 데이터", ["가상 데이터", "로컬 실데이터"])
        st.divider()
        st.caption("LLM 연결 상태")
        st.write("Key 입력됨 · 호출 검증 전" if settings["api_key"] else "API Key 미설정")
        st.caption(f"모델: {settings['model']}")
        if mode == "Claude Agent":
            st.info("질문과 도구 집계 결과가 Anthropic API로 전송되며 API 비용이 발생합니다.")
        with st.expander("기획서 및 실행 기준"):
            st.download_button("사용자 제공 기획서", (ROOT / "docs/user-proposal.md").read_text(encoding="utf-8"), file_name="제주_관광_소비_Agent_기획서.md")
            st.caption("필수 데이터 등재·이용조건과 실제 API 실행 검증은 별도 확인이 필요합니다.")

    st.html('<div class="hero"><span class="pill">🌿 상권 · 마케팅 · 정책 의사결정</span><h1>제주 관광객의 소비,<br><em>언제 · 누가 · 어디서 · 무엇을</em> 쓸까요?</h1><p>질문에서 분석까지, 계산 근거와 함께.<br>검증 가능한 코드로 집계하고 실행 가설을 확인하세요.</p></div>')
    demo = data_mode == "가상 데이터"
    if demo:
        st.warning("가상 데이터 시연입니다. 실제 제주 통계가 아니며 필수 데이터 사용 실적이 아닙니다.")
    try:
        # 각 브라우저 세션과 데이터 모드별로 결과 저장소를 분리합니다.
        if st.session_state.get("data_mode") != data_mode:
            st.session_state.registry = ToolRegistry(demo=demo)
            st.session_state.data_mode = data_mode
            st.session_state.pop("response", None)
            st.session_state.history = []
        registry = st.session_state.registry
    except (ValueError, FileNotFoundError) as error:
        st.error(f"데이터 준비가 필요합니다: {error}")
        st.caption("data/processed의 정규화 CSV와 출처 메타데이터를 준비하거나 가상 데이터를 선택하세요.")
        return
    with st.sidebar.expander("데이터 현황"):
        st.json(registry.execute("list_datasets", {}))

    examples = [
        "2025년 서귀포시 30대 음식점 소비 추세를 분석해 줘",
        "2025년 성별 소비 비중을 비교해 줘",
        "2025년 요일별 소비를 비교해 줘",
        "서귀포시에서 프로모션을 하려면 언제가 좋을까?",
    ]
    columns = st.columns(4)
    for column, example in zip(columns, examples):
        if column.button(example, use_container_width=True):
            st.session_state.question = example
    question = st.text_area("궁금한 소비 흐름을 입력하세요", key="question", value=examples[0], height=90)
    follow_up = st.checkbox("이전 대화에 이어 질문하기", value=False, disabled=mode != "Claude Agent")
    if st.button("인사이트 분석 실행 →", type="primary", use_container_width=True):
        st.session_state.pending_question = question
        with st.status("질문 확인 및 분석 실행", expanded=True) as progress:
            agent = InsightAgent(registry, on_step=st.write, api_key=settings["api_key"], model=settings["model"])
            if mode == "Claude Agent":
                history = st.session_state.get("history", []) if follow_up else []
                response = agent.run_claude(question, history)
                st.session_state.history = history + [{"role": "user", "content": question}, {"role": "assistant", "content": response.message}]
            else:
                response = agent.run_demo(question)
            st.session_state.response = response
            progress.update(label="분석 실행 종료", state="error" if response.status == "error" else "complete", expanded=False)

    response = st.session_state.get("response")
    if response and response.status == "clarification" and mode == "오프라인 데모":
        with st.form("clarification"):
            st.write(response.message)
            region = st.selectbox("분석 지역", ["서귀포시", "제주시"])
            year = st.selectbox("분석 연도", [2025, 2024])
            if st.form_submit_button("선택 조건으로 이어서 분석"):
                with st.spinner("조건을 반영해 분석합니다."):
                    st.session_state.response = InsightAgent(registry).run_demo(st.session_state.pending_question, {"region": region, "year": year})
                st.rerun()
    if response:
        show_response(response)
    st.caption("판단 로그와 수치 근거를 확인하세요. 실행 제안은 참고용이며 최종 사업·정책 판단은 사용자가 수행합니다.")


if __name__ == "__main__":
    main()
