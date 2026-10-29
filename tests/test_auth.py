from types import SimpleNamespace
from time import time
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from src.auth import AuthClient, AuthConfig, AuthError, AuthSession, Identity, auth_enabled

UID='11111111-1111-4111-8111-111111111111'
CONFIG=AuthConfig('https://project.supabase.co','sb_publishable_test')

@pytest.fixture
def signed():
    key=ec.generate_private_key(ec.SECP256R1())
    claims={'sub':UID,'iss':CONFIG.url+'/auth/v1','aud':'authenticated','exp':int(time())+300,'role':'authenticated'}
    def make(**changes):
        return AuthSession(Identity(UID,'a@example.test'),jwt.encode(claims|changes,key,algorithm='ES256'),'refresh-secret',int(time())+300)
    client=AuthClient(CONFIG,jwks=SimpleNamespace(get_signing_key_from_jwt=lambda _:SimpleNamespace(key=key.public_key())))
    return client, make

def test_asymmetric_identity_verified(signed):
    client,make=signed
    session=make(user_metadata={'role':'admin'})
    assert client.verify(session).user_id==UID
    assert 'refresh-secret' not in repr(session)
    assert session.access_token not in repr(session)

@pytest.mark.parametrize('changes',[{'exp':1},{'iss':'https://evil.test/auth/v1'},{'aud':'anon'}, {'role':'service_role'}, {'is_anonymous':True},{'sub':'22222222-2222-4222-8222-222222222222'}])
def test_invalid_claims_rejected(signed,changes):
    client,make=signed
    with pytest.raises(AuthError): client.verify(make(**changes))

def test_signature_and_algorithm_rejected(signed):
    client,make=signed
    good=make()
    foreign=ec.generate_private_key(ec.SECP256R1())
    payload=jwt.decode(good.access_token,options={'verify_signature':False})
    for token in [jwt.encode(payload,foreign,algorithm='ES256'), jwt.encode(payload,key='',algorithm='none')]:
        with pytest.raises(AuthError): client.verify(AuthSession(good.identity,token,'secret',good.expires_at))

def test_legacy_jwt_requires_provider_verification(monkeypatch):
    client=AuthClient(CONFIG)
    monkeypatch.setattr(client,'get_user',lambda _: (_ for _ in ()).throw(AuthError('revoked')))
    session=AuthSession(Identity(UID,'a@example.test'),jwt.encode({'sub':UID},'x'*32,algorithm='HS256'),'secret',9999999999)
    with pytest.raises(AuthError,match='revoked'):client.verify(session)

def test_config_fails_closed():
    with pytest.raises(AuthError):auth_enabled(lambda k,d='':{'AUTH_MODE':'disabled','APP_ENV':'production'}.get(k,d))
    assert auth_enabled(lambda k,d='':d)
    for key in ['sb_secret_anything',jwt.encode({'role':'service_role'},'x'*32,algorithm='HS256'),'invalid']:
        with pytest.raises(AuthError):AuthConfig.read(lambda k,d='':{'SUPABASE_URL':CONFIG.url,'SUPABASE_PUBLISHABLE_KEY':key}.get(k,d))

def test_http_errors_never_expose_provider_secrets():
    response=SimpleNamespace(status_code=400,content=b'leaked',json=lambda:{'msg':'password=secret'})
    client=AuthClient(CONFIG,transport=SimpleNamespace(request=lambda *a,**kw:response))
    with pytest.raises(AuthError) as error:client.login('a@example.test','secret')
    assert 'secret' not in str(error.value)

def test_refresh_cannot_change_identity(monkeypatch,signed):
    client,make=signed
    other=AuthSession(Identity('22222222-2222-4222-8222-222222222222','b@example.test'),'a','b',9999999999)
    monkeypatch.setattr(client,'_request',lambda *a,**kw:{})
    monkeypatch.setattr(client,'_session',lambda _:other)
    with pytest.raises(AuthError):client.refresh(make())
