from __future__ import annotations

import html
import json
import os
import urllib.parse
import uuid
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from src.state import get_states, init_db, record_attempt
from src.utils import age_years, normalize_text

st.set_page_config(page_title="Prospecção CNPJ", layout="wide")

DATA_PATH = Path("data/companies.parquet")
META_PATH = Path("data/release.json")


def _secret_or_env(name: str, default: str = "") -> str:
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return os.getenv(name, default)


if _secret_or_env("DATABASE_URL"):
    os.environ["DATABASE_URL"] = _secret_or_env("DATABASE_URL")

engine = init_db()


@st.cache_data(show_spinner=False)
def load_data(path: str) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df["data_abertura"] = pd.to_datetime(df["data_abertura"], errors="coerce")
    today = pd.Timestamp(date.today())
    df["idade_anos"] = (today - df["data_abertura"]).dt.days / 365.2425
    return df


def handle_contact_redirect(df: pd.DataFrame):
    qp = st.query_params
    cnpj = qp.get("contact")
    attempt_id = qp.get("attempt")
    phone = qp.get("phone")
    msg = qp.get("msg")
    contact_name = qp.get("name", "")
    if not all([cnpj, attempt_id, phone, msg]):
        return False

    valid = df[df["cnpj"].astype(str) == str(cnpj)]
    if valid.empty:
        st.error("CNPJ não encontrado na base local. O contato não foi registrado.")
        return True

    # Não aceita um telefone arbitrário injetado na query string: o número precisa
    # pertencer ao registro selecionado na base vigente.
    allowed_phones = {
        str(v) for v in [valid.iloc[0].get("whatsapp_1", ""), valid.iloc[0].get("whatsapp_2", "")]
        if v and str(v) != "nan"
    }
    if str(phone) not in allowed_phones:
        st.error("Telefone não corresponde ao CNPJ na base local. O contato não foi registrado.")
        return True

    message = urllib.parse.unquote(str(msg))
    record_attempt(
        attempt_id=str(attempt_id),
        cnpj=str(cnpj),
        phone=str(phone),
        contact_name=str(contact_name),
        message=message,
        engine=engine,
    )
    wa_url = f"https://wa.me/{urllib.parse.quote(str(phone))}?text={urllib.parse.quote(message)}"
    st.caption("Tentativa registrada. Abrindo WhatsApp…")
    # Executa no contexto do novo separador aberto pelo link relativo.
    components.html(
        f"<script>window.parent.location.replace({json.dumps(wa_url)});</script>",
        height=0,
    )
    st.link_button("Abrir WhatsApp manualmente", wa_url)
    return True


st.title("Prospecção de empresas — CNPJ público")

if not DATA_PATH.exists():
    st.error("Base ainda não gerada. Execute `python -m src.etl` antes de abrir o app.")
    st.stop()

df = load_data(str(DATA_PATH))

if handle_contact_redirect(df):
    st.stop()

meta = {}
if META_PATH.exists():
    try:
        meta = json.loads(META_PATH.read_text(encoding="utf-8"))
    except Exception:
        meta = {}

if meta:
    st.caption(
        f"Receita Federal: competência {meta.get('receita_release', '—')} · "
        f"{meta.get('rows', len(df)):,} estabelecimentos não-MEI no escopo"
    )

states = pd.DataFrame(get_states(df["cnpj"].astype(str).tolist(), engine=engine))
if not states.empty:
    df = df.merge(states, on="cnpj", how="left")
else:
    df["attempt_count"] = 0
    df["last_attempt_at"] = ""

df["attempt_count"] = pd.to_numeric(df.get("attempt_count", 0), errors="coerce").fillna(0).astype(int)
df["ja_tentado"] = df["attempt_count"] > 0

with st.sidebar:
    st.subheader("Filtros")
    min_age = st.number_input("Idade mínima da empresa (anos)", min_value=0.0, max_value=100.0, value=1.0, step=0.5)
    max_age_enabled = st.checkbox("Limitar idade máxima")
    max_age = st.number_input("Idade máxima (anos)", min_value=0.0, max_value=200.0, value=2.0, step=0.5, disabled=not max_age_enabled)

    bairros = sorted([x for x in df["bairro"].dropna().astype(str).unique() if x])
    bairro_sel = st.multiselect("Bairro", bairros)
    exclude_accounting = st.checkbox("Remover escritórios/serviços contábeis", value=True)
    only_phone = st.checkbox("Somente com telefone", value=True)
    only_probable_mobile = st.checkbox("Somente celular provável", value=False)
    status_contact = st.selectbox("Histórico de contato", ["Nunca tentado", "Todos", "Já tentado"], index=0)
    search = st.text_input("Buscar empresa/CNPJ/CNAE")

filtered = df[df["idade_anos"].fillna(-1) >= min_age].copy()
if max_age_enabled:
    filtered = filtered[filtered["idade_anos"].fillna(999) <= max_age]
if bairro_sel:
    filtered = filtered[filtered["bairro"].isin(bairro_sel)]
if exclude_accounting:
    filtered = filtered[~filtered["is_contabilidade"].fillna(False)]
if only_phone:
    filtered = filtered[filtered["tem_telefone"].fillna(False)]
if only_probable_mobile:
    filtered = filtered[
        filtered["celular_1_provavel"].fillna(False) | filtered["celular_2_provavel"].fillna(False)
    ]
if status_contact == "Nunca tentado":
    filtered = filtered[~filtered["ja_tentado"]]
elif status_contact == "Já tentado":
    filtered = filtered[filtered["ja_tentado"]]
if search.strip():
    s = search.strip().lower()
    mask = (
        filtered["razao_social"].fillna("").str.lower().str.contains(s, regex=False)
        | filtered["nome_fantasia"].fillna("").str.lower().str.contains(s, regex=False)
        | filtered["cnpj"].fillna("").astype(str).str.contains(s, regex=False)
        | filtered["cnae_fiscal_principal"].fillna("").astype(str).str.contains(s, regex=False)
        | filtered["cnae_principal_descricao"].fillna("").str.lower().str.contains(s, regex=False)
    )
    filtered = filtered[mask]

st.metric("Empresas no filtro", f"{len(filtered):,}")

show_cols = [
    "cnpj", "razao_social", "nome_fantasia", "bairro", "idade_anos",
    "cnae_principal_descricao", "primeiro_nome", "whatsapp_1", "whatsapp_2",
    "attempt_count",
]
st.dataframe(
    filtered[show_cols].rename(columns={
        "cnpj": "CNPJ",
        "razao_social": "Razão social",
        "nome_fantasia": "Fantasia",
        "bairro": "Bairro",
        "idade_anos": "Idade (anos)",
        "cnae_principal_descricao": "CNAE",
        "primeiro_nome": "Nome sugerido",
        "whatsapp_1": "Telefone 1",
        "whatsapp_2": "Telefone 2",
        "attempt_count": "Tentativas",
    }),
    use_container_width=True,
    hide_index=True,
    column_config={"Idade (anos)": st.column_config.NumberColumn(format="%.1f")},
)

if filtered.empty:
    st.info("Nenhuma empresa atende aos filtros atuais.")
    st.stop()

st.subheader("Gerar contato")
options = filtered["cnpj"].astype(str).tolist()
labels = {
    str(r.cnpj): f"{r.razao_social} — {r.bairro or 'sem bairro'} — {r.cnpj}"
    for r in filtered.itertuples()
}
selected_cnpj = st.selectbox("Empresa", options, format_func=lambda x: labels.get(str(x), str(x)))
row = filtered[filtered["cnpj"].astype(str) == str(selected_cnpj)].iloc[0]

c1, c2 = st.columns(2)
with c1:
    st.write(f"**Razão social:** {row['razao_social']}")
    st.write(f"**Sócios PF:** {row.get('nomes_socios', '') or '—'}")
    st.write(f"**Nome sugerido:** {row.get('primeiro_nome', '') or '—'}")
    st.write(f"**Origem:** {row.get('origem_nome_contato', '') or '—'}")
with c2:
    st.write(f"**Bairro:** {row.get('bairro', '') or '—'}")
    st.write(f"**CNAE:** {row.get('cnae_principal_descricao', '') or row.get('cnae_fiscal_principal', '')}")
    st.write(f"**Tentativas anteriores:** {int(row.get('attempt_count', 0) or 0)}")
    if row.get("last_attempt_at"):
        st.write(f"**Última tentativa:** {row.get('last_attempt_at')}")

saudacao = st.text_input("Saudação", value="Bom dia")
default_name = normalize_text(row.get("primeiro_nome", ""))
contact_name = st.text_input("Nome usado na saudação", value=default_name)
if not default_name:
    st.warning("Não há um primeiro nome confiável derivado de sócio pessoa física. Revise manualmente antes do contato.")

template = st.text_area(
    "Mensagem",
    value="{saudacao}! Sou Daniel do Sebrae. Nesse contato falo com {nome}?",
    height=100,
)
try:
    message = template.format(saudacao=saudacao.strip(), nome=contact_name.strip())
except Exception:
    message = template
st.code(message, language=None)

phones = []
if row.get("whatsapp_1"):
    phones.append((str(row["whatsapp_1"]), bool(row.get("celular_1_provavel")), "Telefone 1"))
if row.get("whatsapp_2") and row.get("whatsapp_2") != row.get("whatsapp_1"):
    phones.append((str(row["whatsapp_2"]), bool(row.get("celular_2_provavel")), "Telefone 2"))
if not phones:
    st.warning("Não há telefone válido neste registro.")
    st.stop()

phone_labels = {p[0]: f"{p[2]} — {p[0]}" + (" (celular provável)" if p[1] else "") for p in phones}
selected_phone = st.selectbox("Número", [p[0] for p in phones], format_func=lambda x: phone_labels[x])

attempt_id = uuid.uuid4().hex
query = urllib.parse.urlencode({
    "contact": str(row["cnpj"]),
    "attempt": attempt_id,
    "phone": selected_phone,
    "name": contact_name.strip(),
    "msg": message,
})
link = f"?{query}"

st.markdown(
    f'<a href="{html.escape(link, quote=True)}" target="_blank" '
    'style="display:inline-block;padding:.55rem .9rem;border:1px solid #999;border-radius:.5rem;text-decoration:none;">'
    'Abrir WhatsApp e registrar tentativa</a>',
    unsafe_allow_html=True,
)
st.caption("O histórico é gravado quando o link acima é efetivamente aberto, não apenas quando é gerado.")
