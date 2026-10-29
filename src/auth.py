"""Supabase Auth: credenciais por sessão, identidade verificada e nenhuma chave administrativa."""
from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import urlparse
from uuid import UUID

import jwt
import requests


class AuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class AuthConfig:
    url: str
    publishable_key: str = field(repr=False)

    @classmethod
    def read(cls, secret):
        url = secret("SUPABASE_URL").rstrip("/")
        key = secret("SUPABASE_PUBLISHABLE_KEY") or secret("SUPABASE_ANON_KEY")
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
            raise AuthError("Configure SUPABASE_URL com o endereço HTTPS do projeto Supabase.")
        if not key or key.startswith("sb_secret_"):
            raise AuthError("Configure a chave publishable do Supabase. Chaves secret/service_role não são aceitas no aplicativo.")
        if not key.startswith("sb_publishable_"):
            try:
                payload = json.loads(base64.urlsafe_b64decode(key.split(".")[1] + "=="))
                if payload.get("role") != "anon":
                    raise ValueError()
            except (ValueError, IndexError, TypeError):
                raise AuthError("Use a chave publishable ou a antiga anon; não use service_role.") from None
        return cls(url, key)


def auth_enabled(secret) -> bool:
    mode = secret("AUTH_MODE", "supabase").lower()
    environment = secret("APP_ENV", "production").lower()
    if mode == "supabase":
        return True
    if mode == "disabled" and environment in {"development", "test"}:
        return False
    raise AuthError("Login obrigatório em produção. O modo sem autenticação é exclusivo de desenvolvimento/testes.")


@dataclass(frozen=True)
class Identity:
    user_id: str
    email: str


@dataclass(frozen=True)
class AuthSession:
    identity: Identity
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_at: int


@lru_cache(maxsize=8)
def public_jwks(url):
    # O único cache compartilhado de autenticação contém chaves PÚBLICAS.
    return jwt.PyJWKClient(url + "/auth/v1/.well-known/jwks.json", lifespan=300, timeout=10)


class AuthClient:
    def __init__(self, config: AuthConfig, transport=None, jwks=None):
        self.config = config
        self.transport = transport or requests.Session()
        self.jwks = jwks or public_jwks(config.url)

    def _request(self, method, path, *, token=None, body=None, params=None):
        headers = {"apikey": self.config.publishable_key, "Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            response = self.transport.request(method, self.config.url + "/auth/v1/" + path,
                                              headers=headers, json=body, params=params, timeout=(5, 15))
            if response.status_code == 429:
                raise AuthError("Muitas tentativas. Aguarde alguns instantes antes de tentar novamente.")
            if not 200 <= response.status_code < 300:
                raise AuthError("Não foi possível autenticar. Confira os dados ou solicite um novo código.")
            return response.json() if response.content else {}
        except (requests.RequestException, ValueError):
            raise AuthError("O serviço de autenticação não respondeu. Tente novamente.") from None

    def get_user(self, token) -> Identity:
        user = self._request("GET", "user", token=token)
        try:
            identity = Identity(str(UUID(user["id"])), str(user["email"]))
            if not user.get("email_confirmed_at") or user.get("is_anonymous"):
                raise AuthError("Confirme seu e-mail antes de entrar.")
            return identity
        except (KeyError, TypeError, ValueError):
            raise AuthError("Identidade inválida. Entre novamente.") from None

    def verify(self, session: AuthSession) -> Identity:
        try:
            header = jwt.get_unverified_header(session.access_token)
            if header.get("alg") in {"ES256", "RS256"}:
                key = self.jwks.get_signing_key_from_jwt(session.access_token).key
                claims = jwt.decode(session.access_token, key, algorithms=["ES256", "RS256"],
                                    issuer=self.config.url + "/auth/v1", audience="authenticated",
                                    options={"require": ["exp", "iss", "sub", "aud"]})
                if claims.get("role") != "authenticated" or claims.get("is_anonymous"):
                    raise AuthError("Sessão inválida. Entre novamente.")
                user_id = str(UUID(claims["sub"]))
                identity = Identity(user_id, session.identity.email)
            elif header.get("alg") == "HS256":
                # Projetos legados: o servidor valida o JWT; nunca decodificamos sem assinatura.
                identity = self.get_user(session.access_token)
            else:
                raise AuthError("Sessão inválida. Entre novamente.")
            if identity.user_id != session.identity.user_id:
                raise AuthError("A identidade da sessão mudou. Entre novamente.")
            return identity
        except (jwt.PyJWTError, ValueError, KeyError):
            raise AuthError("Sua sessão expirou ou é inválida. Entre novamente.") from None

    def _session(self, data):
        try:
            access, refresh = data["access_token"], data["refresh_token"]
            expires = int(data.get("expires_at") or time.time() + int(data["expires_in"]))
            result = AuthSession(self.get_user(access), access, refresh, expires)
            self.verify(result)
            return result
        except (KeyError, ValueError, TypeError):
            raise AuthError("O serviço retornou uma sessão incompleta. Entre novamente.") from None

    def login(self, email, password):
        return self._session(self._request("POST", "token", params={"grant_type": "password"},
                                           body={"email": email.strip(), "password": password}))

    def refresh(self, session):
        refreshed = self._session(self._request("POST", "token", params={"grant_type": "refresh_token"},
                                                body={"refresh_token": session.refresh_token}))
        if refreshed.identity.user_id != session.identity.user_id:
            raise AuthError("A identidade da sessão mudou. Entre novamente.")
        return refreshed

    def logout(self, session, *, global_scope=False):
        self._request("POST", "logout", token=session.access_token,
                      params={"scope": "global" if global_scope else "local"})

    def signup(self, email, password):
        validate_password(password)
        self._request("POST", "signup", body={"email": email.strip(), "password": password})

    def resend_confirmation(self, email):
        self._request("POST", "resend", body={"email": email.strip(), "type": "signup"})

    def confirm_email(self, email, code):
        session = self._session(self._request("POST", "verify", body={"email": email.strip(), "token": code.strip(), "type": "email"}))
        self.logout(session)

    def request_recovery(self, email):
        self._request("POST", "recover", body={"email": email.strip()})

    def reset_password(self, email, code, password):
        validate_password(password)
        session = self._session(self._request("POST", "verify", body={"email": email.strip(), "token": code.strip(), "type": "recovery"}))
        self._request("PUT", "user", token=session.access_token, body={"password": password})
        self.logout(session, global_scope=True)


def validate_password(password):
    if not isinstance(password, str) or len(password) < 12:
        raise AuthError("Use uma senha com pelo menos 12 caracteres.")
