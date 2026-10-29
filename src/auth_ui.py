"""Entrada e administração de contas. O bloqueio ocorre antes de carregar dados privados."""
from datetime import datetime, time as daytime, timedelta
import time
from zoneinfo import ZoneInfo

import streamlit as st

from .auth import AuthClient, AuthConfig, AuthError, AuthSession, auth_enabled
from .user_store import StoreError, SupabaseStore


def _clear_identity():
    # Inclui seleção, nomes, mensagens e filtros: outra conta não herda a tela anterior.
    st.session_state.clear()


def access_gate(secret):
    try:
        if not auth_enabled(secret):
            return None
        config = AuthConfig.read(secret)
    except AuthError as exc:
        st.title("Configuração de acesso pendente")
        st.error(str(exc))
        st.caption("Configure a autenticação e aplique as migrações conforme docs/DEPLOY.md. Os dados permanecem protegidos enquanto a configuração não estiver pronta.")
        st.stop()
    client = AuthClient(config)
    if notice := st.session_state.pop("auth_notice", None):
        st.info(notice)
    session = st.session_state.get("auth_session")
    if session is not None:
        try:
            if not isinstance(session, AuthSession):
                raise AuthError("Sessão inválida. Entre novamente.")
            if session.expires_at <= time.time() + 60:
                session = client.refresh(session)
                st.session_state["auth_session"] = session
            client.verify(session)
            store = SupabaseStore(config, session)
            account = store.provision()
        except (AuthError, StoreError) as exc:
            _clear_identity()
            st.session_state["auth_notice"] = str(exc)
            st.rerun()
        with st.sidebar:
            st.caption(f"Conectado como {account['email']}")
            if st.button("Sair", key="auth_logout"):
                try:
                    client.logout(session)
                except AuthError:
                    pass
                _clear_identity()
                st.rerun()
        try:
            store.require_active()
        except StoreError as exc:
            st.title("Acesso à plataforma")
            st.info(str(exc))
            st.caption("Seu cadastro não libera acesso automaticamente. O administrador pode ativar sua conta e definir a validade.")
            if st.button("Verificar liberação", key="check_access"):
                st.rerun()
            st.stop()
        return store

    st.title("Entre na sua conta")
    st.caption("Seus contatos, revisões e preferências ficam separados dos demais usuários.")
    options = ["Entrar", "Confirmar e-mail", "Recuperar senha"]
    if secret("ALLOW_SIGNUP", "true").lower() == "true":
        options.insert(1, "Criar conta")
    mode = st.radio("Acesso", options, horizontal=True, key="auth_screen")
    try:
        if mode == "Entrar":
            with st.form("login_form", clear_on_submit=True):
                email = st.text_input("E-mail", key="login_email")
                password = st.text_input("Senha", type="password", key="login_password")
                submit = st.form_submit_button("Entrar", type="primary")
            if submit:
                session = client.login(email, password)
                _clear_identity()
                st.session_state["auth_session"] = session
                st.rerun()
        elif mode == "Criar conta":
            with st.form("signup_form", clear_on_submit=True):
                email = st.text_input("E-mail", key="signup_email")
                password = st.text_input("Senha (mínimo de 12 caracteres)", type="password", key="signup_password")
                repeat = st.text_input("Repita a senha", type="password", key="signup_repeat")
                submit = st.form_submit_button("Criar conta")
            if submit:
                if password != repeat:
                    raise AuthError("As senhas não coincidem.")
                client.signup(email, password)
                st.success("Solicitação recebida. Confira seu e-mail para confirmar o cadastro; depois aguarde a liberação do administrador.")
        elif mode == "Confirmar e-mail":
            with st.form("confirm_email_form", clear_on_submit=True):
                email = st.text_input("E-mail", key="confirm_email")
                code = st.text_input("Código recebido por e-mail", max_chars=6, key="confirm_code")
                verify = st.form_submit_button("Confirmar e-mail")
                resend = st.form_submit_button("Reenviar código")
            if verify:
                client.confirm_email(email, code)
                st.success("E-mail confirmado. Você já pode entrar com sua senha.")
            elif resend:
                client.resend_confirmation(email)
                st.info("Se o endereço puder receber a confirmação, um novo código será enviado.")
        else:
            st.caption("Solicite o código e depois informe a nova senha. Use apenas o código enviado pelo serviço para o seu e-mail.")
            with st.form("recovery_request_form", clear_on_submit=True):
                email = st.text_input("E-mail", key="recover_email")
                send = st.form_submit_button("Enviar código de recuperação")
            if send:
                client.request_recovery(email)
                st.info("Se houver uma conta elegível para este endereço, o código será enviado.")
            with st.form("recovery_verify_form", clear_on_submit=True):
                email = st.text_input("E-mail da conta", key="recover_verify_email")
                code = st.text_input("Código de recuperação", max_chars=6, key="recover_code")
                password = st.text_input("Nova senha (mínimo de 12 caracteres)", type="password", key="recover_password")
                repeat = st.text_input("Repita a nova senha", type="password", key="recover_repeat")
                submit = st.form_submit_button("Redefinir senha")
            if submit:
                if password != repeat:
                    raise AuthError("As senhas não coincidem.")
                client.reset_password(email, code, password)
                st.success("Senha alterada e sessões revogadas. Entre com a nova senha.")
    except AuthError as exc:
        st.error(str(exc))
    st.stop()


def admin_accounts(store):
    if store is None or store.require_active()["role"] != "admin":
        return
    with st.sidebar.expander("Administrar acessos"):
        try:
            accounts = [row for row in store.list_accounts() if row["user_id"] != store.user_id]
            if not accounts:
                st.caption("Ainda não há outras contas cadastradas.")
                return
            labels = {row["user_id"]: f"{row['email']} · {row['status']}" for row in accounts}
            user_id = st.selectbox("Conta", list(labels), format_func=labels.get, key="admin_account")
            account = next(row for row in accounts if row["user_id"] == user_id)
            with st.form("manage_access_" + user_id):
                role = st.selectbox("Perfil", ["user", "admin"], index=["user", "admin"].index(account["role"]),
                                    format_func=lambda v: {"user": "Usuário", "admin": "Administrador"}[v])
                status = st.selectbox("Situação", ["pending", "active", "blocked"],
                                      index=["pending", "active", "blocked"].index(account["status"]),
                                      format_func=lambda v: {"pending": "Pendente", "active": "Ativo", "blocked": "Bloqueado"}[v])
                unlimited = st.checkbox("Sem data de vencimento", value=account["access_until"] is None)
                current = datetime.now(ZoneInfo("America/Sao_Paulo")).date() + timedelta(days=30)
                if account["access_until"]:
                    current = datetime.fromisoformat(account["access_until"].replace("Z", "+00:00")).astimezone(ZoneInfo("America/Sao_Paulo")).date()
                until = st.date_input("Acesso válido até (Brasília)", value=current, disabled=unlimited)
                save = st.form_submit_button("Salvar acesso")
            if save:
                expiry = None if unlimited else datetime.combine(until, daytime.max, ZoneInfo("America/Sao_Paulo")).isoformat()
                store.set_access(user_id, role, status, expiry)
                st.success("Acesso atualizado.")
        except (StoreError, ValueError) as exc:
            st.error(str(exc))
