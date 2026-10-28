from pathlib import Path

from streamlit.testing.v1 import AppTest

from src import data_management_ui as ui
from src.data_updates import checked_scope

APP = Path(__file__).resolve().parents[1] / 'app.py'


def test_city_can_be_requested_in_demo_and_status_does_not_confuse_old_runs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('GITHUB_DATA_TOKEN', 'test-only')
    ui.remote_reviews.clear()
    calls = []

    class Client:
        repository, branch = 'PrimeiraEdicao/cnpj-prospeccao', 'main'
        ready = False

        def __init__(self, *args):
            pass

        def contact_registry(self):
            return []

        def request_update(self, scope=None):
            scope = checked_scope(scope) if scope else None
            calls.append(scope)
            return {'id': 'request-for-this-session', 'scope': scope}

        def runs(self):
            return [{'id': 123, 'event': 'workflow_dispatch', 'status': 'completed', 'conclusion': 'success',
                     'display_title': 'CNPJ | request-for-this-session' if self.ready else 'another request'}]

    monkeypatch.setattr(ui, 'GitHubDataClient', Client)
    at = AppTest.from_file(str(APP)).run(timeout=15)
    assert not at.exception
    next(w for w in at.selectbox if w.key == 'load_uf').set_value('ES').run()
    at.button(key='request_city').click().run()
    assert not at.exception
    assert calls[0]['uf'] == 'ES'
    assert any('Solicitação aceita' in w.value for w in at.success)
    at.button(key='base_status').click().run()
    assert any('aguardando' in w.value for w in at.info)
    assert not any('Processamento concluído' in w.value for w in at.success)
    Client.ready = True
    at.button(key='base_status').click().run()
    assert any('Processamento concluído' in w.value for w in at.success)
    assert not at.exception
    ui.remote_reviews.clear()


def test_without_secret_city_controls_are_disabled_and_existing_app_still_opens(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('GITHUB_DATA_TOKEN', raising=False)
    at = AppTest.from_file(str(APP)).run(timeout=15)
    assert not at.exception
    assert at.button(key='request_city').disabled
    assert at.button(key='sync_base').disabled
    assert at.metric[0].value == '3'
