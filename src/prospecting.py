"""Regras de prospecção aplicadas também às bases já publicadas."""
from __future__ import annotations

import json
import re
import string
import urllib.parse
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from .utils import digits, normalize_code, normalize_text, strip_accents

ROOT = Path(__file__).resolve().parents[1]
SAO_PAULO = ZoneInfo("America/Sao_Paulo")
PORTE_LABELS = {"01": "ME — Microempresa", "03": "EPP — Empresa de pequeno porte",
                "05": "Demais", "00": "Não informado"}
DEFAULT_TEMPLATE = "{saudacao}! Tudo bem? Sou {remetente}. Nesse contato falo com {nome}?"
EXCLUSIONS = json.loads((ROOT / "config/prospect_exclusions.json").read_text(encoding="utf-8"))


def now_local() -> datetime:
    return datetime.now(SAO_PAULO)


def greeting(now: datetime | None = None) -> str:
    now = now or now_local()
    hour = now.astimezone(SAO_PAULO).hour if now.tzinfo else now.hour
    return "Bom dia" if 6 <= hour < 12 else "Boa tarde" if 12 <= hour < 18 else "Boa noite"


def render_message(template: str, name: str, sender: str, salutation: str | None = None) -> str:
    values = {"saudacao": salutation or greeting(), "nome": normalize_text(name) or "a pessoa responsável",
              "remetente": sender.strip()}
    fields = [field for _, field, _, _ in string.Formatter().parse(template) if field is not None]
    if any(field not in values for field in fields):
        raise ValueError("Use apenas {saudacao}, {nome} e {remetente} na mensagem.")
    return template.format(**values)


def contact_link(row, phone: str, template: str, sender: str, name: str | None = None,
                 salutation: str | None = None, attempt_id: str | None = None) -> str:
    query = {"contact": str(row["cnpj"]), "attempt": attempt_id or uuid.uuid4().hex,
             "phone": phone, "name": normalize_text(row.get("primeiro_nome", "")) if name is None else name,
             "template": template, "sender": sender}
    if salutation is not None:
        query["salutation"] = salutation
    # A saudação automática é calculada novamente ao abrir o link, mesmo se a
    # tabela foi carregada de manhã e o clique só ocorrer à tarde/noite.
    return "?" + urllib.parse.urlencode(query)


def neighborhood_key(value) -> str:
    return strip_accents(normalize_text(value)).upper() or "SEM BAIRRO INFORMADO"


def cnae_codes(principal, secondary) -> list[str]:
    return [digits(principal), *re.findall(r"\d{7}", normalize_text(secondary))]


def exclusion_reasons(row) -> list[str]:
    codes = cnae_codes(row.get("cnae_fiscal_principal"), row.get("cnae_fiscal_secundaria"))
    nature = digits(row.get("natureza_juridica"))
    reasons = []
    for key, rule in EXCLUSIONS.items():
        cnae_match = any(code.startswith(prefix) for code in codes for prefix in rule["cnae_prefixes"])
        nature_match = nature in rule["naturezas"] or any(
            nature.startswith(prefix) for prefix in rule.get("natureza_prefixes", [])
        )
        if key == "governo":
            entity = normalize_text(row.get("ente_federativo_responsavel"))
            nature_match |= bool(entity and entity not in {"0", "00"})
        if cnae_match or nature_match:
            reasons.append(key)
    return reasons


def prepare_data(df: pd.DataFrame, meta: dict | None = None) -> pd.DataFrame:
    df = df.copy()
    defaults = {"uf": "", "municipio": "", "municipio_nome": "", "porte_empresa": "",
                "natureza_juridica": "", "cnae_fiscal_secundaria": "", "whatsapp_1": "",
                "whatsapp_2": "", "primeiro_nome": "", "nome_fantasia": "", "bairro": ""}
    for col, default in defaults.items():
        if col not in df:
            df[col] = default
    for col in defaults:
        df[col] = df[col].map(normalize_text)
    df["uf"] = df["uf"].str.upper()
    df["municipio"] = df["municipio"].map(normalize_code)
    scopes = (meta or {}).get("scopes", [])
    names = {(x["uf"], str(x["municipio_code"])): x.get("nome", "") for x in scopes}
    names.setdefault(("MG", "4553"), "Governador Valadares")
    df["cidade"] = [normalize_text(name) or names.get((uf, code)) or f"Município {code or 'não informado'}"
                     for name, uf, code in zip(df.municipio_nome, df.uf, df.municipio)]
    df["cidade_label"] = df["cidade"] + " / " + df["uf"]
    df["bairro_key"] = df["bairro"].map(neighborhood_key)
    df["porte_code"] = df["porte_empresa"].map(lambda v: normalize_code(v, 2))
    df["porte"] = df["porte_code"].map(PORTE_LABELS).fillna("Não informado")
    df["exclusion_reasons"] = df.apply(exclusion_reasons, axis=1)
    return df


def filter_data(df: pd.DataFrame, *, cities=(), neighborhoods=(), portes=("01", "03"),
                exclusions=tuple(EXCLUSIONS), exclude_accounting=True, min_age=1.0,
                max_age=None, only_phone=True, only_mobile=False, contact_status="Nunca tentado",
                search="") -> pd.DataFrame:
    mask = df["idade_anos"].fillna(-1).ge(min_age)
    if max_age is not None:
        mask &= df["idade_anos"].fillna(float("inf")).le(max_age)
    if cities:
        mask &= df["cidade_label"].isin(cities)
    if neighborhoods:
        mask &= df["bairro_key"].isin([neighborhood_key(x) for x in neighborhoods])
    # Seleção vazia significa nenhum porte; para incluir todos, selecione os quatro.
    mask &= df["porte_code"].isin(portes)
    excluded = set(exclusions)
    if excluded:
        mask &= df["exclusion_reasons"].map(lambda reasons: not (set(reasons) & excluded))
    if exclude_accounting:
        mask &= ~df["is_contabilidade"].fillna(False).astype(bool)
    if only_phone:
        mask &= df["tem_telefone"].fillna(False).astype(bool)
    if only_mobile:
        mask &= df["celular_1_provavel"].fillna(False) | df["celular_2_provavel"].fillna(False)
    attempted = df["attempt_count"].fillna(0).gt(0)
    if contact_status == "Nunca tentado":
        mask &= ~attempted
    elif contact_status == "Já tentado":
        mask &= attempted
    if search.strip():
        needle = strip_accents(search).lower()
        haystack = df[["razao_social", "nome_fantasia", "cnpj", "cnae_fiscal_principal",
                       "cnae_principal_descricao"]].fillna("").astype(str).agg(" ".join, axis=1)
        mask &= haystack.map(strip_accents).str.lower().str.contains(needle, regex=False)
    return df[mask].copy().reset_index(drop=True)


def preferred_phone(row) -> str:
    for i in (1, 2):
        if row.get(f"celular_{i}_provavel") and normalize_text(row.get(f"whatsapp_{i}")):
            return normalize_text(row[f"whatsapp_{i}"])
    return normalize_text(row.get("whatsapp_1")) or normalize_text(row.get("whatsapp_2"))
