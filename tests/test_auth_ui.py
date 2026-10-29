from pathlib import Path
from time import time
import pytest
from streamlit.testing.v1 import AppTest
from src.auth import AuthSession,Identity
from src.user_store import StoreError
from src.demo import demo_data
from src.prospecting import now_local

APP=Path(__file__).resolve().parents[1]/'app.py'
UID='11111111-1111-4111-8111-111111111111'
SESSION=AuthSession(Identity(UID,'owner@example.test'),'access-token','refresh-token',int(time())+600)

@pytest.fixture
def production(monkeypatch,tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('AUTH_MODE','supabase');monkeypatch.setenv('APP_ENV','production')
    monkeypatch.setenv('SUPABASE_URL','https://project.supabase.co');monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY','sb_publishable_test')
    monkeypatch.setenv('DATABASE_URL','invalid://never-connect')
    return tmp_path

def test_no_data_or_admin_ui_before_login(production):
    at=AppTest.from_file(str(APP)).run(timeout=15)
    assert not at.exception
    assert at.title[0].value=='Entre na sua conta'
    assert not at.metric and not at.file_uploader and not at.download_button
    assert not (production/'data').exists()

def test_missing_config_closes_application(production,monkeypatch):
    monkeypatch.delenv('SUPABASE_URL')
    at=AppTest.from_file(str(APP)).run(timeout=15)
    assert not at.exception and at.error
    assert not at.metric

class FakeStore:
    user_id=UID
    status='active'
    def __init__(self,*a,**kw):pass
    def provision(self):return {'email':'owner@example.test'}
    def require_active(self):
        if self.status!='active':raise StoreError('Acesso pendente')
        return {'role':'user','status':self.status}
    def preferences(self):return {}
    def get_reviews(self):return []
    def get_states(self,cnpjs):return []
class FakeAuth:
    def __init__(self,*a,**kw):pass
    def verify(self,session):return session.identity
    def login(self,email,password):return SESSION
    def logout(self,session):pass

def setup_fakes(monkeypatch):
    monkeypatch.setattr('src.auth_ui.AuthClient',FakeAuth)
    monkeypatch.setattr('src.auth_ui.SupabaseStore',FakeStore)

def test_login_logout_clears_private_state(production,monkeypatch):
    setup_fakes(monkeypatch)
    at=AppTest.from_file(str(APP)).run(timeout=15)
    at.text_input(key='login_email').set_value('owner@example.test')
    at.text_input(key='login_password').set_value('some-password-long')
    next(b for b in at.button if b.label=='Entrar').click().run(timeout=15)
    assert not at.exception and at.metric
    assert not any(e.label=='Administrar acessos' for e in at.expander)
    assert not any(b.label=='Incluir cidade e atualizar base' for b in at.button)
    at.session_state['sender']='private value'
    at.button(key='auth_logout').click().run(timeout=15)
    assert not at.exception and not at.metric
    assert 'sender' not in at.session_state
    assert 'auth_session' not in at.session_state

def test_pending_account_has_no_contacts(production,monkeypatch):
    setup_fakes(monkeypatch);monkeypatch.setattr(FakeStore,'status','pending')
    at=AppTest.from_file(str(APP));at.session_state['auth_session']=SESSION
    at.run(timeout=15)
    assert not at.exception and not at.metric and not at.download_button
    assert at.title[0].value=='Acesso à plataforma'

def test_production_never_reads_global_csv_or_legacy_db(production,monkeypatch):
    setup_fakes(monkeypatch)
    data=production/'data';data.mkdir()
    demo_data(now_local().date()).to_parquet(data/'companies.parquet',index=False)
    monkeypatch.setattr('src.state.init_db',lambda:(_ for _ in ()).throw(AssertionError('legacy DB')))
    monkeypatch.setattr('src.reviews.load_review_registry',lambda *a:(_ for _ in ()).throw(AssertionError('global CSV')))
    at=AppTest.from_file(str(APP));at.session_state['auth_session']=SESSION
    at.run(timeout=15)
    assert not at.exception and at.metric
