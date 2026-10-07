from __future__ import annotations

import base64
import html
import json
import math
import os
import urllib.parse
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

from src.demo import demo_data
from src.prospecting import (DEFAULT_TEMPLATE, EXCLUSIONS, PORTE_LABELS, cnpj_query, contact_link,
                             filter_data, greeting, now_local, preferred_phone,
                             prepare_data, render_message)
from src.reviews import (REVIEW_LABELS, apply_reviews, combine_reviews, export_reviews,
                         load_review_registry, parse_review_files)
from src.state import get_reviews, get_states, import_reviews, init_db, record_attempt
from src.theme import theme_css
from src.utils import age_years, digits, normalize_text

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="AlphaLab | Prospecção", page_icon=str(ROOT / "assets/alphalab-symbol.svg"), layout="wide")
load_dotenv()
DATA_PATH = Path("data/companies.parquet")
META_PATH = Path("data/release.json")
REVIEW_PATH = ROOT / "config/reviewed_cnpjs.csv"


def _secret_or_env(name: str, default: str = "") -> str:
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return os.getenv(name, default)


if _secret_or_env("DATABASE_URL"):
    os.environ["DATABASE_URL"] = _secret_or_env("DATABASE_URL")


@st.cache_resource
def contact_engine(database_url: str):
    return init_db()


@st.cache_data(show_spinner=False)
def load_data(path: str, file_version: tuple[int, int]) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df["data_abertura"] = pd.to_datetime(df["data_abertura"], errors="coerce")
    return df


def handle_contact_redirect(df: pd.DataFrame, engine):
    qp = st.query_params
    cnpj, attempt_id, phone = qp.get("contact"), qp.get("attempt"), qp.get("phone")
    if not all([cnpj, attempt_id, phone]) or not (qp.get("msg") or qp.get("template")):
        return False
    valid = df[df["cnpj"].astype(str) == str(cnpj)]
    if valid.empty:
        st.error("CNPJ não encontrado na base local. O contato não foi registrado.")
        return True
    if bool(valid.iloc[0].get("reviewed", False)):
        st.warning("Esta empresa está na lista de revisão e não deve receber nova abordagem. Nenhuma tentativa foi registrada.")
        return True
    allowed = {normalize_text(valid.iloc[0].get(f"whatsapp_{i}")) for i in (1, 2)} - {""}
    if str(phone) not in allowed:
        st.error("Telefone não corresponde ao CNPJ na base local. O contato não foi registrado.")
        return True
    name = str(qp.get("name", ""))
    try:
        # Links novos recalculam a saudação no clique; links antigos com msg
        # continuam compatíveis, preservando %, +, acentos e tentativas idempotentes.
        message = (render_message(str(qp["template"]), name, str(qp.get("sender", "")),
                                  qp.get("salutation")) if qp.get("template") else str(qp["msg"]))
    except (ValueError, KeyError) as exc:
        st.error(f"Mensagem inválida: {exc}")
        return True
    record_attempt(attempt_id=str(attempt_id), cnpj=str(cnpj), phone=str(phone),
                   contact_name=name, message=message, engine=engine)
    wa_url = f"https://wa.me/{urllib.parse.quote(str(phone))}?text={urllib.parse.quote(message)}"
    st.caption("Abertura registrada. Abrindo WhatsApp…")
    components.html(f"<script>window.parent.location.replace({json.dumps(wa_url)});</script>", height=0)
    st.link_button("Abrir WhatsApp manualmente", wa_url)
    st.caption("O histórico registra a abertura do contato; o envio é confirmado no WhatsApp.")
    return True


def action_link(url: str, label: str) -> str:
    return (f'<a class="contact-action" href="{html.escape(url, quote=True)}" '
            f'target="cnpj-whatsapp">{html.escape(label)}</a>')


def render_table(page: pd.DataFrame, template: str, sender: str, salutation: str | None, demo: bool):
    rows = []
    for _, row in page.iterrows():
        phones = list(dict.fromkeys(normalize_text(row.get(f"whatsapp_{i}")) for i in (1, 2)))
        phones = [phone for phone in phones if phone]
        actions = '<span class="muted">Demonstração</span>' if demo else " ".join(
            action_link(contact_link(row, phone, template, sender, salutation=salutation),
                        "WhatsApp" if len(phones) == 1 else f"WhatsApp {i}")
            for i, phone in enumerate(phones, 1)) or '<span class="muted">Sem telefone</span>'
        if row.get("reviewed", False):
            actions = '<span class="muted">Revisado — não contatar</span>'
        company = html.escape(normalize_text(row.get("razao_social")))
        cnpj = html.escape(str(row["cnpj"]))
        name = html.escape(normalize_text(row.get("primeiro_nome")) or "Nome a revisar")
        bairro = html.escape(normalize_text(row.get("bairro")) or "Sem bairro informado")
        city = html.escape(str(row["cidade_label"]))
        porte = html.escape(str(row["porte"]))
        cnae = html.escape(normalize_text(row.get("cnae_principal_descricao")) or str(row.get("cnae_fiscal_principal", "")))
        age = f"{row['idade_anos']:.1f}" if pd.notna(row['idade_anos']) else "—"
        attempts = int(row.get("attempt_count", 0))
        rows.append(f'<tr><td class="actions">{actions}</td><td class="company"><strong>{company}</strong>'
                    f'<small>{cnpj} · {name}</small></td><td>{bairro}<small>{city}</small></td>'
                    f'<td>{porte}</td><td class="activity">{cnae}</td><td>{age}</td><td>{attempts}</td></tr>')
    markup = ('<div class="prospect-table"><table><thead><tr><th>Contato</th><th>Empresa / responsável</th>'
              '<th>Bairro / cidade</th><th>Porte</th><th>Atividade</th><th>Anos</th><th>Aberturas</th>'
              '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>')
    st.markdown(markup, unsafe_allow_html=True)


with st.sidebar:
    appearance = st.radio("Aparência", ["Claro", "Escuro"], horizontal=True, key="appearance")
logo_path = ROOT / "assets" / ("alphalab-logo-reverse.svg" if appearance == "Escuro" else "alphalab-logo.svg")
logo = base64.b64encode(logo_path.read_bytes()).decode()
st.markdown("<style>" + theme_css(appearance) + "</style>", unsafe_allow_html=True)
st.markdown(f'<div class="brand-header"><img src="data:image/svg+xml;base64,{logo}" alt="AlphaLab">'
            '<span>Dados · Prospecção · Relacionamento</span></div>', unsafe_allow_html=True)
st.markdown('<div class="eyebrow">INTELIGÊNCIA PARA SEU PRÓXIMO CONTATO</div>', unsafe_allow_html=True)
st.title("Encontre empresas. Inicie conversas.")
st.caption("Escolha seu território, refine o público e organize seus contatos em um só lugar.")

meta = {}
if META_PATH.exists():
    try:
        meta = json.loads(META_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        pass
now = now_local()
today = now.date()
demo_mode = not DATA_PATH.exists()
if demo_mode:
    st.info("Demonstração com empresas fictícias. A base real ainda está sendo preparada; os contatos estão desativados.")
    df = demo_data(today)
    engine = None
else:
    version = DATA_PATH.stat()
    df = load_data(str(DATA_PATH), (version.st_mtime_ns, version.st_size))
    engine = contact_engine(_secret_or_env("DATABASE_URL", "sqlite:///data/contact_state.db"))
df = prepare_data(df, meta)
reviews = combine_reviews(load_review_registry(REVIEW_PATH), [] if demo_mode else get_reviews(engine))
df = apply_reviews(df, reviews)
if not demo_mode and handle_contact_redirect(df, engine):
    st.stop()
df["idade_anos"] = df["data_abertura"].map(lambda opening: age_years(opening, today))
if meta and not demo_mode:
    st.caption(f"Receita Federal · {meta.get('receita_release', '—')} · {len(df):,} estabelecimentos ativos não-MEI na base")

if not demo_mode:
    st.button("Atualizar histórico", help="Recarrega as aberturas de contato registradas em outras abas.")
states = pd.DataFrame() if demo_mode else pd.DataFrame(get_states(df["cnpj"].astype(str).tolist(), engine=engine))
if not states.empty:
    df = df.merge(states, on="cnpj", how="left")
else:
    df["attempt_count"], df["last_attempt_at"] = 0, ""
df["attempt_count"] = pd.to_numeric(df["attempt_count"], errors="coerce").fillna(0).astype(int)

with st.sidebar:
    st.image(str(logo_path), width=155)
    with st.expander("Importar empresas já revisadas"):
        st.caption("Oculta empresas já contatadas ou descartadas, sem registrar mensagens enviadas. Aceita ZIP, Excel (.xlsx), CSV e TXT com CNPJ.")
        files = st.file_uploader("Listas de empresas", type=["zip", "xlsx", "csv", "txt"],
                                 accept_multiple_files=True, disabled=demo_mode)
        review_status = st.selectbox("Motivo da revisão", list(REVIEW_LABELS), format_func=REVIEW_LABELS.get,
                                     disabled=demo_mode)
        if result := st.session_state.pop("review_import_result", None):
            st.success(result)
        if files and not demo_mode:
            try:
                report = parse_review_files([(f.name, f.getvalue()) for f in files], review_status)
                st.write(f"{len(report.records):,} CNPJs únicos · {report.duplicates:,} repetições · {report.invalid_rows:,} inválidos.")
                if report.invalid_rows or report.blank_rows:
                    st.warning(f"Ignorados: {report.invalid_rows} CNPJs inválidos e {report.blank_rows} células vazias.")
                for ignored in report.ignored:
                    st.caption(f"Ignorado: {ignored}")
                if report.records:
                    preview = pd.DataFrame(list(report.records.values())[:10])[["cnpj", "status"]]
                    preview["status"] = preview["status"].map(REVIEW_LABELS)
                    st.dataframe(preview, hide_index=True)
                    if st.button("Importar CNPJs revisados"):
                        added, existing = import_reviews(report.records.values(), engine)
                        st.session_state["review_import_result"] = f"{added} novos registros salvos; {existing} já estavam importados. A lista acompanha as próximas cargas da Receita."
                        st.rerun()
                else:
                    st.warning("Nenhum CNPJ válido encontrado. Use a coluna CNPJ ou uma lista de 14 dígitos.")
            except (ValueError, zipfile.BadZipFile, OSError) as exc:
                st.error(f"Não foi possível importar: {exc}")
        st.download_button("Baixar lista de revisão", export_reviews(reviews), "cnpjs_revisados.csv",
                           "text/csv", disabled=demo_mode or not reviews)
        st.caption("Novas importações são salvas no banco de contatos. Guarde o CSV como backup. Na hospedagem, use um banco persistente.")
    st.subheader("Seu público")
    cities = sorted(df["cidade_label"].unique())
    city_sel = st.multiselect("Cidade / UF", cities, help="Sem seleção: todas as cidades já carregadas.")
    geographic = df[df["cidade_label"].isin(city_sel)] if city_sel else df
    bairros = sorted(geographic["bairro_key"].unique())
    # Retira seleções que deixaram de existir ao trocar a cidade.
    st.session_state["bairros"] = [x for x in st.session_state.get("bairros", []) if x in bairros]
    bairro_sel = st.multiselect("Bairro", bairros, key="bairros", help="Selecione um ou vários bairros. Variações de acento e espaços são agrupadas.")
    portes = st.multiselect("Porte da empresa", list(PORTE_LABELS), default=["01", "03"], format_func=PORTE_LABELS.get)
    st.caption("ME e EPP selecionados por padrão. O enquadramento vem do cadastro CNPJ.")
    min_age = st.number_input("Idade mínima da empresa (anos)", min_value=0.0, max_value=100.0, value=1.0, step=0.5)
    max_age_enabled = st.checkbox("Limitar idade máxima")
    max_age = st.number_input("Idade máxima (anos)", min_value=0.0, max_value=200.0, value=2.0, step=0.5, disabled=not max_age_enabled)
    st.divider()
    st.markdown("**Atividades fora do foco**")
    exclude_accounting = st.checkbox("Remover escritórios/serviços contábeis", value=True)
    exclusions = st.multiselect("Remover também", list(EXCLUSIONS), default=list(EXCLUSIONS), format_func=lambda k: EXCLUSIONS[k]["label"])
    only_phone = st.checkbox("Somente com telefone", value=True)
    only_mobile = st.checkbox("Somente celular provável", value=False)
    contact_status = st.selectbox("Histórico de contato", ["Nunca tentado", "Todos", "Já tentado"])
    hide_reviewed = st.checkbox("Ocultar empresas já revisadas", value=True)
    st.caption(f"Lista de revisão: {len(reviews):,} CNPJs; {int(df['reviewed'].sum()):,} presentes nesta base. Ao exibir, os links de contato continuam desativados.")
    search = st.text_input("Buscar empresa/CNPJ/CNAE", placeholder="Nome, CNPJ ou atividade")
    st.caption("CNPJ aceito: 12.345.678/0001-90 ou 12345678000190 (14 dígitos). A busca respeita os filtros selecionados.")
    with st.expander("Como incluir outra cidade"):
        st.write("No GitHub: Actions → Atualizar base Receita CNPJ → Run workflow. Informe a UF e o código do município na Receita. A cidade será adicionada à configuração e à próxima carga.")
        st.caption("Os códigos da Receita têm quatro dígitos e diferem dos códigos de sete dígitos do IBGE. A carga processa os arquivos nacionais e pode demorar.")

filtered = filter_data(df, cities=city_sel, neighborhoods=bairro_sel, portes=portes, exclusions=exclusions,
                       exclude_accounting=exclude_accounting, min_age=min_age,
                       max_age=max_age if max_age_enabled else None, only_phone=only_phone,
                       only_mobile=only_mobile, contact_status=contact_status, search=search,
                       hide_reviewed=hide_reviewed)
# Retira também contatos revisados de filas abertas antes da importação.
eligible_contacts = set(filtered.loc[~filtered["reviewed"], "cnpj"].astype(str))
st.session_state["contact_queue"] = [n for n in st.session_state.get("contact_queue", []) if n in eligible_contacts]
c1, c2, c3 = st.columns(3)
c1.metric("Empresas no filtro", f"{len(filtered):,}")
c2.metric("Bairros no filtro", str(filtered["bairro_key"].nunique()))
c3.metric("Cidades carregadas", str(df["cidade_label"].nunique()))

with st.expander("Mensagem e saudação", expanded=True):
    left, right = st.columns(2)
    with left:
        mode = st.selectbox("Saudação", ["Automática pelo horário", "Personalizada"])
        manual = st.text_input("Saudação personalizada", value="Olá", disabled=mode != "Personalizada")
        salutation = manual.strip() if mode == "Personalizada" else None
        sender = st.text_input("Sua apresentação", value=_secret_or_env("CONTACT_SENDER", "Daniel do Sebrae"))
    with right:
        template = st.text_area("Mensagem", value=_secret_or_env("CONTACT_TEMPLATE", DEFAULT_TEMPLATE), height=110,
                                help="Campos disponíveis: {saudacao}, {nome} e {remetente}.")
        st.caption(f"Agora: {greeting(now)} · {now:%H:%M} em Brasília. Bom dia das 6h às 11h59; boa tarde até 17h59; boa noite das 18h às 5h59.")
    try:
        st.code(render_message(template, "Maria", sender, salutation), language=None)
    except (ValueError, KeyError) as exc:
        st.error(str(exc))
        st.stop()
    st.caption("A saudação automática é atualizada ao abrir cada contato, inclusive quando a página ficou aberta por horas.")

st.subheader("Empresas para contato")
st.caption("Os links ficam na primeira coluna e reutilizam a mesma aba do WhatsApp. Confira a mensagem antes de enviar.")
if filtered.empty:
    searched_cnpj = cnpj_query(search)
    reviewed_match = df[df["cnpj"].map(digits).eq(searched_cnpj)] if searched_cnpj else pd.DataFrame()
    if not reviewed_match.empty and reviewed_match["reviewed"].any():
        st.info("Este CNPJ está marcado como revisado anteriormente e foi retirado da prospecção. Para consultar, desmarque ‘Ocultar empresas já revisadas’ e confira os demais filtros.")
    elif searched_cnpj and df["cnpj"].map(digits).eq(searched_cnpj).any():
        st.info("CNPJ encontrado na base, mas oculto pelos filtros atuais. Confira cidade, bairro, porte, idade, atividades, telefone e histórico de contato.")
    elif searched_cnpj:
        st.info("Este CNPJ não consta na base carregada. A base contém estabelecimentos ativos não-MEI das cidades já carregadas.")
    else:
        st.info("Nenhuma empresa atende aos filtros atuais. Amplie os bairros, portes ou atividades selecionados.")
    st.stop()
page_size = 50
pages = math.ceil(len(filtered) / page_size)
# Mudar um filtro retorna à página 1 em vez de manter uma página fora do resultado.
signature = (tuple(filtered["cnpj"]),)
if st.session_state.get("filter_signature") != signature:
    st.session_state["page"] = 1
    st.session_state["filter_signature"] = signature
page_num = st.number_input("Página", min_value=1, max_value=pages, value=1, step=1, key="page")
page = filtered.iloc[(page_num - 1) * page_size:page_num * page_size]
st.caption(f"Página {page_num} de {pages} · até {page_size} empresas por página")
render_table(page, template, sender, salutation, demo_mode)

with st.expander("Fila de contatos — organize vários de uma vez"):
    labels = {str(r.cnpj): f"{r.razao_social} · {r.bairro} · {r.cnpj}" for r in page.itertuples() if not r.reviewed}
    st.session_state["chosen_contacts"] = [x for x in st.session_state.get("chosen_contacts", []) if x in labels]
    selected = st.multiselect("Contatos desta página", list(labels), format_func=labels.get, key="chosen_contacts")
    a, b, c = st.columns(3)
    if a.button("Adicionar selecionados à fila", disabled=demo_mode or not selected):
        st.session_state["contact_queue"] = list(dict.fromkeys(st.session_state.get("contact_queue", []) + selected))
    if b.button("Adicionar esta página à fila", disabled=demo_mode):
        st.session_state["contact_queue"] = list(dict.fromkeys(st.session_state.get("contact_queue", []) + list(labels)))
    if c.button("Limpar fila", disabled=demo_mode):
        st.session_state["contact_queue"] = []
    eligible = eligible_contacts
    queue = [cnpj for cnpj in st.session_state.get("contact_queue", []) if cnpj in eligible]
    st.session_state["contact_queue"] = queue
    if queue:
        current = filtered[filtered["cnpj"].astype(str).eq(queue[0])].iloc[0]
        st.write(f"**{len(queue)} na fila · Próximo:** {current['razao_social']} — {current['bairro']}")
        phone = preferred_phone(current)
        if phone:
            st.code(render_message(template, current["primeiro_nome"], sender, salutation), language=None)
            st.markdown(action_link(contact_link(current, phone, template, sender, salutation=salutation), "Abrir contato da fila"), unsafe_allow_html=True)
        else:
            st.warning("Este registro não tem telefone válido.")
        if st.button("Próximo contato"):
            st.session_state["contact_queue"] = queue[1:]
            st.rerun()
    else:
        st.caption("Selecione empresas ou adicione a página inteira. A fila acompanha os filtros atuais e fica disponível nesta sessão.")
    st.caption("Adicionar à fila ou avançar não registra envio. O histórico registra a abertura de cada contato.")

with st.expander("Revisar nome e telefone de uma empresa"):
    options = filtered["cnpj"].astype(str).tolist()
    all_labels = {str(r.cnpj): f"{r.razao_social} — {r.bairro} — {r.cnpj}" for r in filtered.itertuples()}
    selected_cnpj = st.selectbox("Empresa", options, format_func=all_labels.get)
    row = filtered[filtered["cnpj"].astype(str).eq(selected_cnpj)].iloc[0]
    contact_name = st.text_input("Nome usado na saudação", value=normalize_text(row["primeiro_nome"]), key=f"contact_name_{selected_cnpj}")
    st.caption(f"Sócios PF: {normalize_text(row.get('nomes_socios')) or '—'} · Origem: {normalize_text(row.get('origem_nome_contato')) or '—'}")
    if not contact_name:
        st.warning("Nome não identificado. A mensagem usa ‘a pessoa responsável’; revise antes do contato.")
    st.code(render_message(template, contact_name, sender, salutation), language=None)
    phones = list(dict.fromkeys(normalize_text(row.get(f"whatsapp_{i}")) for i in (1, 2)))
    phones = [phone for phone in phones if phone]
    if row["reviewed"]:
        st.info(f"{row['review_label']}. Este contato foi retirado da prospecção.")
    elif demo_mode:
        st.button("Abrir WhatsApp e registrar tentativa", disabled=True)
    elif phones:
        phone = st.selectbox("Número", phones)
        st.markdown(action_link(contact_link(row, phone, template, sender, name=contact_name, salutation=salutation), "Abrir WhatsApp e registrar tentativa"), unsafe_allow_html=True)
    else:
        st.warning("Não há telefone válido neste registro.")

with st.expander("Envio automático para vários contatos"):
    st.write("A fila organiza a revisão e reutiliza uma aba. Para enviar sem abrir cada conversa, a integração adequada é a WhatsApp Business Platform (Cloud API), com contatos que autorizaram receber mensagens e modelos aprovados.")
    st.caption("A base pública do CNPJ não registra essa autorização. A integração de envio depende de configurar a conta/API e uma lista autorizada. Conta verificada também está sujeita às regras do WhatsApp.")
