"""Streamlit 폼을 실제 실행하되 Key 저장은 테스트 임시 위치로 대체합니다."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.jeju_agent import settings


def test_api_form_save_switches_mode_without_exposing_key(monkeypatch, tmp_path):
    path = tmp_path / '.env'
    original_save = settings.save_settings
    original_load = settings.load_settings
    monkeypatch.setattr(settings, 'load_settings', lambda: {'api_key': '', 'model': 'claude-opus-5-5'})
    monkeypatch.setattr(settings, 'save_settings', lambda key, model: original_save(key, model, path))
    app = AppTest.from_file(str(Path(__file__).parents[1] / 'app.py')).run(timeout=30)
    assert not app.exception
    next(widget for widget in app.text_input if widget.label == 'Anthropic API Key').input('synthetic-ui-test-token')
    next(button for button in app.button if button.label == '저장하고 Claude 모드로 전환').click()
    app.run(timeout=30)
    assert not app.exception
    assert app.session_state['api_settings']['api_key'] == 'synthetic-ui-test-token'
    assert app.session_state['execution_mode'] == 'Claude Agent'
    assert next(widget for widget in app.text_input if widget.label == 'Anthropic API Key').value == ''
    assert original_load(path)['api_key'] == 'synthetic-ui-test-token'
    assert all('synthetic-ui-test-token' not in element.value for element in app.markdown)


def test_default_demo_generates_report(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, 'load_settings', lambda: {'api_key': '', 'model': 'claude-opus-5-5'})
    app = AppTest.from_file(str(Path(__file__).parents[1] / 'app.py')).run(timeout=30)
    assert not app.exception
    next(button for button in app.button if button.label == '인사이트 분석 실행 →').click()
    app.run(timeout=30)
    assert not app.exception
    assert app.session_state['response'].status == 'complete'
    assert app.session_state['response'].report
