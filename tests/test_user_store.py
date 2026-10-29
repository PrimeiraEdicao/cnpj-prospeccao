from types import SimpleNamespace
from time import time
import pandas as pd
import pytest
from src.auth import AuthConfig,AuthSession,Identity
from src.user_store import SupabaseStore,StoreError

A='11111111-1111-4111-8111-111111111111'
B='22222222-2222-4222-8222-222222222222'
CNPJ='00000000000191'
class Transport:
    def __init__(self,results):self.results=iter(results);self.calls=[]
    def request(self,*args,**kwargs):
        self.calls.append((args,kwargs));result=next(self.results)
        return SimpleNamespace(status_code=200,content=b'json',json=lambda:result)
def store(uid=A,token='token-a',results=()):
    transport=Transport(results)
    session=AuthSession(Identity(uid,uid+'@example.test'),token,'secret-refresh',int(time())+600)
    return SupabaseStore(AuthConfig('https://project.supabase.co','sb_publishable_test'),session,transport),transport

def test_requests_do_not_share_credentials():
    a,ta=store(results=[[]]);b,tb=store(B,'token-b',[[]])
    a.get_reviews();b.get_reviews()
    for t,uid,token in [(ta,A,'token-a'),(tb,B,'token-b')]:
        options=t.calls[0][1]
        assert options['headers']['Authorization']=='Bearer '+token
        assert options['params']['user_id']=='eq.'+uid

def test_reviews_paginate_beyond_postgrest_limit():
    s,t=store(results=[[{'cnpj':str(i)} for i in range(500)]]*2+[[]])
    assert len(s.get_reviews())==1000
    assert [call[1]['params']['offset'] for call in t.calls]==[0,500,1000]

def test_import_strips_foreign_ownership_and_is_atomic():
    s,t=store(results=[{'added':1,'existing':0}])
    assert s.import_reviews([{'user_id':B,'cnpj':CNPJ,'status':'contatado'}])==(1,0)
    assert 'user_id' not in t.calls[0][1]['json']['p_records'][0]
    with pytest.raises(ValueError):s.import_reviews([{'cnpj':CNPJ,'status':'contatado'},{'cnpj':'invalid','status':'contatado'}])
    assert len(t.calls)==1

def test_confirmation_rejects_stale_or_foreign_selection():
    s,t=store()
    visible=pd.DataFrame([{'cnpj':CNPJ,'reviewed':True}])
    with pytest.raises(ValueError):s.confirm_contacts([CNPJ],visible)
    assert not t.calls

@pytest.mark.parametrize('account',[{'role':'user','status':'active','access_until':None},{'role':'admin','status':'blocked','access_until':None},{'role':'admin','status':'active','access_until':'2020-01-01T00:00:00Z'}])
def test_admin_operations_validate_current_db_access(account):
    s,t=store(results=[[account]])
    with pytest.raises(StoreError):s.reserve_data_update(None)
    assert len(t.calls)==1

def test_failed_save_not_reported_as_success():
    s,t=store()
    t.request=lambda *a,**kw:SimpleNamespace(status_code=500,content=b'bad',json=lambda:{'message':'postgres://secret'})
    with pytest.raises(StoreError) as error:s.import_reviews([{'cnpj':CNPJ,'status':'contatado'}])
    assert 'secret' not in str(error.value)
