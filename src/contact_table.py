"""Tabela com seleção local e abertura de contatos no gesto do usuário."""
from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd

from .prospecting import whatsapp_link, preferred_phone
from .theme import PALETTES
from .utils import normalize_text

FRONTEND = Path(__file__).with_name("contact_table_frontend")


def build_contact_table(page: pd.DataFrame, template: str, sender: str,
                        salutation: str | None, demo: bool, appearance: str,
                        *, standalone: bool = True) -> str:
    """Uma aba por empresa, usando o celular preferencial no lote.

    Gerar a tabela, selecionar e encontrar pop-ups bloqueados não grava tentativas.
    As abas apontam ao WhatsApp Web; o histórico depende de confirmação explícita.
    """
    escape = lambda value: html.escape(str(value), quote=True)
    rows = []
    for _, row in page.iterrows():
        company = normalize_text(row.get("razao_social"))
        cnpj = str(row["cnpj"])
        phones = list(dict.fromkeys(normalize_text(row.get(f"whatsapp_{i}")) for i in (1, 2)))
        phones = [phone for phone in phones if phone]
        reviewed = bool(row.get("reviewed", False))
        enabled = not demo and not reviewed and bool(phones)
        phone = preferred_phone(row) if enabled else ""
        def payload(p):
            return escape(json.dumps({"cnpj": cnpj, "phone": p, "template": template,
                                      "sender": sender, "name": normalize_text(row.get("primeiro_nome")),
                                      "salutation": salutation}, ensure_ascii=False))
        links = {p: whatsapp_link(row, p, template, sender, salutation=salutation)
                 for p in phones} if enabled else {}
        checkbox = (f'<input type="checkbox" class="row-select" '
                    f'aria-label="Selecionar {escape(company)}" '
                    f'data-contact="{payload(phone) if enabled else ""}"'
                    + ("" if enabled else " disabled") + ">")
        actions = " ".join(
            f'<a class="contact-action" href="{escape(url)}" data-contact="{payload(p)}" '
            f'target="_blank" rel="noopener noreferrer">'
            f'{"WhatsApp" if len(phones) == 1 else f"WhatsApp {i}"}</a>'
            for i, (p, url) in enumerate(links.items(), 1))
        if not enabled:
            actions = ('Revisado — não contatar' if reviewed else
                       'Demonstração' if demo else 'Sem telefone')
            actions = f'<span class="muted">{actions}</span>'
        name = normalize_text(row.get("primeiro_nome")) or "Nome a revisar"
        bairro = normalize_text(row.get("bairro")) or "Sem bairro informado"
        cnae = normalize_text(row.get("cnae_principal_descricao")) or row.get("cnae_fiscal_principal", "")
        age = f"{row['idade_anos']:.1f}" if pd.notna(row['idade_anos']) else "—"
        rows.append(
            f'<tr><td class="select-cell">{checkbox}</td><td class="company"><strong>{escape(company)}</strong>'
            f'<small>{escape(cnpj)} · {escape(name)}</small></td><td class="actions">{actions}'
            f'<small class="open-status"></small></td><td>{escape(bairro)}<small>{escape(row["cidade_label"])}</small></td>'
            f'<td>{escape(row["porte"])}</td><td class="activity">{escape(cnae)}</td>'
            f'<td>{age}</td><td>{escape(row.get("review_label") or "A contatar")}</td></tr>')
    palette = PALETTES[appearance]
    variables = ";".join(f"--al-{key}:{value}" for key, value in palette.items())
    css = (FRONTEND / "style.css").read_text(encoding="utf-8")
    script = (FRONTEND / "table.js").read_text(encoding="utf-8")
    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<style>:root{{{variables};color-scheme:{palette["scheme"]};}}{css}</style></head>'
        '<body><section class="batch-toolbar" aria-label="Contatos em lote">'
        '<div class="toolbar-summary"><strong id="selection-count" aria-live="polite">Nenhuma empresa selecionada</strong>'
        '<span>Marque as empresas e abra uma aba por contato.</span></div><div class="toolbar-actions">'
        '<button id="select-page" type="button">Selecionar esta página</button>'
        '<button id="clear-selection" type="button" disabled>Limpar seleção</button>'
        '<button id="open-selected" class="primary" type="button" disabled>Abrir WhatsApps selecionados (0)</button>'
        '<button id="mark-contacted" type="button" disabled>Marcar selecionadas como contatadas</button>'
        '</div><p class="hint">O lote usa um número por empresa, priorizando o celular. '
        'Permita pop-ups deste aplicativo no navegador para abrir todas as abas.</p></section>'
        '<p id="batch-status" role="status" aria-live="polite" hidden></p>'
        '<div class="prospect-table" tabindex="0" role="region" aria-label="Empresas desta página">'
        '<table><thead><tr><th class="select-cell"><input id="select-all" type="checkbox" '
        'aria-label="Selecionar todas as empresas disponíveis desta página"></th>'
        '<th>Empresa / responsável</th><th>Contato</th><th>Bairro / cidade</th>'
        '<th>Porte</th><th>Atividade</th><th>Anos</th><th>Situação</th></tr></thead><tbody>'
        + "".join(rows) + '</tbody></table></div>'
        '<p class="footer">A seleção vale apenas para esta página e é limpa ao atualizar a lista. '
        'Abrir abas não marca contato. Depois das conversas, use “Marcar selecionadas como contatadas” para retirá-las das próximas listas.</p>'
        + (f'<script>{script}</script>' if standalone else '') + '</body></html>')


def render_contact_table(page, template, sender, salutation, demo, appearance):
    import hashlib
    import streamlit as st
    import streamlit.components.v1 as components
    markup = build_contact_table(page, template, sender, salutation, demo, appearance, standalone=False)
    component = components.declare_component("contact_table", path=str(FRONTEND))
    return component(markup=markup, identity=hashlib.sha256(markup.encode()).hexdigest(),
                     height=min(850, 330 + len(page) * 88), ack=st.session_state.get("last_contact_event"),
                     key="contact_table", default=None)
