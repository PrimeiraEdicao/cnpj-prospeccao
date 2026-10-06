from __future__ import annotations

import re
import unicodedata
from datetime import date
from pathlib import Path


def digits(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\D", "", str(value))


def normalize_code(value: object, width: int | None = None) -> str:
    s = digits(value)
    if width:
        return s.zfill(width)
    return s


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if not s or s.lower() in {"nan", "none", "null"}:
        return ""
    return re.sub(r"\s+", " ", s)


def strip_accents(value: str) -> str:
    value = normalize_text(value)
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(ch)
    )


def first_name(full_name: object) -> str:
    name = normalize_text(full_name)
    if not name:
        return ""
    # Para nomes compostos e QSA, usa o primeiro nome do primeiro registro.
    name = name.split("|")[0].split(",")[0].strip()
    token = re.split(r"\s+", name)[0]
    if not token or any(ch.isdigit() for ch in token):
        return ""
    token = token.title()
    if len(token) < 2:
        return ""
    return token


def parse_yyyymmdd(value: object):
    import pandas as pd
    s = normalize_text(value)
    return pd.to_datetime(s, format="%Y%m%d", errors="coerce")


def age_years(opening_date, today: date | None = None) -> float | None:
    import pandas as pd
    if opening_date is None or pd.isna(opening_date):
        return None
    today = today or date.today()
    d = pd.Timestamp(opening_date).date()
    return (today - d).days / 365.2425


def load_cnae_exclusions(path: str | Path) -> set[str]:
    path = Path(path)
    if not path.exists():
        return set()
    codes: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        code = digits(line)
        if code:
            codes.add(code)
    return codes


def has_any_cnae(principal: object, secundarios: object, excluded: set[str]) -> bool:
    if not excluded:
        return False
    p = digits(principal)
    if p in excluded:
        return True
    sec = normalize_text(secundarios)
    # A coluna pública costuma vir como lista delimitada; extrair sequências de 7 dígitos
    # é mais robusto do que depender de um delimitador específico.
    sec_codes = set(re.findall(r"\d{7}", sec))
    return bool(sec_codes & excluded)


def cnpj_full(cnpj_basico: object, cnpj_ordem: object, cnpj_dv: object) -> str:
    return (
        normalize_code(cnpj_basico, 8)
        + normalize_code(cnpj_ordem, 4)
        + normalize_code(cnpj_dv, 2)
    )


def phone_br(ddd: object, number: object) -> str:
    d = digits(ddd)
    n = digits(number)
    if len(d) != 2 or len(n) not in {8, 9}:
        return ""
    return f"55{d}{n}"


def is_probable_mobile_br(ddd: object, number: object) -> bool:
    n = digits(number)
    return len(digits(ddd)) == 2 and len(n) == 9 and n.startswith("9")
