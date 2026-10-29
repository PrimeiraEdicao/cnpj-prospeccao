"""Controles da base, disponíveis também antes da primeira carga."""
from pathlib import Path

import streamlit as st

from .data_updates import DataUpdateError, GitHubDataClient, city_catalog
from .user_store import StoreError
from .user_data_updates import UserDataUpdates


def configured_client(secret):
    token = secret("GITHUB_DATA_TOKEN")
    if not token:
        return None
    return GitHubDataClient(token, secret("GITHUB_DATA_REPOSITORY", "PrimeiraEdicao/cnpj-prospeccao"),
                            secret("GITHUB_DATA_BRANCH", "main"))


@st.cache_data(ttl=30, show_spinner=False)
def remote_reviews(token, repository, branch):
    return GitHubDataClient(token, repository, branch).contact_registry()


def render_data_management(root: Path, secret, store=None):
    if store is not None and store.require_active()["role"] != "admin":
        return None
    client = configured_client(secret)
    if client is not None and store is not None:
        client = UserDataUpdates(client, store)
    with st.sidebar.expander("Cidades e atualização da Receita"):
        st.caption("Escolha uma cidade para incluí-la na base, ou atualize todas as cidades já carregadas. O processamento ocorre em segundo plano e pode levar horas.")
        catalog = city_catalog()
        ufs = sorted(catalog.uf.unique())
        uf = st.selectbox("Estado da nova cidade", ufs, index=ufs.index("MG"), key="load_uf")
        cities = catalog[catalog.uf.eq(uf)]
        choices = cities.municipio_code.tolist()
        names = dict(zip(cities.municipio_code, cities.nome))
        city = st.selectbox("Cidade para incluir", choices, format_func=names.get, key=f"load_city_{uf}")
        if client is None:
            st.info("Para habilitar as cargas pela interface, configure GITHUB_DATA_TOKEN nos Secrets. O histórico individual já utiliza o Supabase." if store else
                    "Para habilitar as cargas pela interface e salvar o histórico entre reinicializações, configure GITHUB_DATA_TOKEN nos Secrets do aplicativo.")
        admin_key = secret("DATA_UPDATE_ADMIN_KEY") if store is None else ""
        authorized = True
        if admin_key:
            import hmac
            supplied = st.text_input("Chave para atualizar a base", type="password", key="data_admin_key")
            authorized = hmac.compare_digest(supplied, admin_key)
        add = st.button("Incluir cidade e atualizar base", disabled=client is None or not authorized, key="request_city")
        refresh = st.button("Atualizar cidades já carregadas", disabled=client is None or not authorized, key="request_base")
        if add or refresh:
            try:
                with st.spinner("Solicitando processamento…"):
                    request = client.request_update({"uf": uf, "municipio_code": city} if add else None)
                st.session_state["base_request"] = request
                st.session_state.pop("base_run", None)
                st.success("Solicitação aceita. A lista atual continua disponível enquanto a nova base é preparada.")
            except (DataUpdateError, StoreError, ValueError) as exc:
                st.error(str(exc))
        if request := st.session_state.get("base_request"):
            scope = request.get("scope")
            st.caption(f"Solicitação: {scope['nome']} / {scope['uf']}" if scope else "Solicitação: atualização das cidades cadastradas")
        if st.button("Verificar andamento", disabled=client is None, key="base_status"):
            try:
                runs = client.runs()
                request = st.session_state.get("base_request")
                matching = [r for r in runs if request and request["id"] in r.get("display_title", "")]
                fallback = [r for r in runs if r.get("event") != "pull_request"]
                st.session_state["base_run"] = (matching or [None])[0] if request else (fallback or [None])[0]
                if request and not matching:
                    st.info("Solicitação recebida; aguardando o processamento aparecer na fila. Verifique novamente em alguns instantes.")
            except (DataUpdateError, StoreError) as exc:
                st.error(str(exc))
        if run := st.session_state.get("base_run"):
            status = run["status"]
            conclusion = run.get("conclusion")
            if status == "completed" and conclusion == "success":
                st.success("Processamento concluído. Carregue a última base pronta abaixo.")
            elif status == "completed":
                st.error("A atualização não concluiu com sucesso. A base anterior foi mantida. Consulte os detalhes para corrigir e solicitar novamente.")
            else:
                st.info("Atualização em andamento. Use ‘Verificar andamento’ para acompanhar.")
            # O endereço é construído pelo servidor, não aceito da resposta remota.
            st.link_button("Detalhes do processamento", f"https://github.com/{client.repository}/actions/runs/{int(run['id'])}")
        if st.button("Carregar última base pronta", disabled=client is None, key="sync_base"):
            try:
                with st.spinner("Baixando e validando a base publicada…"):
                    meta = client.download_snapshot(root)
                st.session_state["base_loaded_message"] = f"Base atualizada: {int(meta['rows']):,} empresas. Os filtros e as exclusões foram reaplicados."
                st.rerun()
            except (DataUpdateError, StoreError, ValueError) as exc:
                st.error(str(exc))
        st.caption("A carga usa arquivos públicos da Receita. A cidade só aparece nos filtros após o processamento e o carregamento da base pronta.")
    return client
