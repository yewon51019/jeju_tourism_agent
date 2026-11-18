"""실제 Key 없이 임시 파일로 저장·재시작·삭제와 세션 격리를 확인합니다."""
from src.jeju_agent.settings import clear_api_key, load_settings, save_settings
from src.jeju_agent.agent import InsightAgent
from src.jeju_agent.tools import ToolRegistry


def test_saved_settings_survive_reload_and_preserve_other_settings(tmp_path):
    path = tmp_path / '.env'
    path.write_text('OTHER_SETTING=keep\n', encoding='utf-8')
    save_settings('synthetic-test-token-not-a-real-key', 'test-model', path)
    settings = load_settings(path)
    assert settings['api_key'] == 'synthetic-test-token-not-a-real-key'
    assert settings['model'] == 'test-model'
    assert 'OTHER_SETTING=keep' in path.read_text(encoding='utf-8')


def test_deleted_key_does_not_return_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'environment-test-token')
    path = tmp_path / '.env'
    save_settings('local-test-token', 'test-model', path)
    clear_api_key(path)
    assert load_settings(path)['api_key'] == ''


def test_explicit_session_keys_are_not_shared(monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'environment-test-token')
    registry = ToolRegistry()
    first = InsightAgent(registry, api_key='session-one', model='model-one')
    second = InsightAgent(registry, api_key='session-two', model='model-two')
    assert first.api_key == 'session-one'
    assert second.api_key == 'session-two'
    assert first.model != second.model
    assert InsightAgent(registry, api_key='').api_key == ''


def test_session_key_is_passed_to_client_without_real_api_call(monkeypatch):
    import anthropic
    from types import SimpleNamespace

    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.messages = SimpleNamespace(create=self.create)

        def create(self, **kwargs):
            captured['model'] = kwargs['model']
            return SimpleNamespace(content=[])

    monkeypatch.setattr(anthropic, 'Anthropic', FakeClient)
    agent = InsightAgent(ToolRegistry(), api_key='synthetic-session-token', model='test-model')
    response = agent.run_claude('분석 지역을 알려줘')
    assert captured['api_key'] == 'synthetic-session-token'
    assert captured['model'] == 'test-model'
    assert 'synthetic-session-token' not in response.message
