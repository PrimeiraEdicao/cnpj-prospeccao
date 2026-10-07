"""Configuração de municípios Receita, preservando pares UF/código."""
from __future__ import annotations

import json
import re
from pathlib import Path

UFS = set("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())


def validate_scopes(scopes: list[dict]) -> list[dict]:
    if not isinstance(scopes, list) or not scopes:
        raise ValueError("Configure pelo menos um município em config/scopes.json.")
    result = {}
    for item in scopes:
        uf = str(item.get("uf", "")).strip().upper()
        code = str(item.get("municipio_code", "")).strip()
        if uf not in UFS or not re.fullmatch(r"\d{4}", code):
            raise ValueError(f"Escopo inválido: {uf}/{code}. Use UF e código Receita de quatro dígitos, não código IBGE.")
        result[(uf, code)] = {"uf": uf, "municipio_code": code, "nome": str(item.get("nome", "")).strip()}
    return list(result.values())


def load_scopes(path: str | Path) -> list[dict]:
    return validate_scopes(json.loads(Path(path).read_text(encoding="utf-8")))


def add_scopes(scopes: list[dict], uf: str, municipalities: str, name: str = "") -> list[dict]:
    if not uf and not municipalities and not name:
        return validate_scopes(scopes)
    if not uf or not municipalities:
        raise ValueError("Para adicionar uma cidade, informe a UF e os códigos Receita.")
    codes = [x.strip() for x in municipalities.split(",") if x.strip()]
    if not codes:
        raise ValueError("Informe pelo menos um código Receita de quatro dígitos.")
    additions = [{"uf": uf, "municipio_code": code, "nome": name if len(codes) == 1 else ""} for code in codes]
    return validate_scopes([*scopes, *additions])


def geographic_mask(frame, scopes: list[dict]):
    import pandas as pd
    # Compara pares. MG/4553 + ES/5705 não pode incluir MG/5705 ou ES/4553.
    pairs = {(x["uf"], x["municipio_code"]) for x in scopes}
    return pd.MultiIndex.from_frame(frame[["uf", "municipio"]]).isin(pairs)
