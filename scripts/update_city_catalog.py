"""Atualiza o catálogo de seleção pela tabela oficial TOM/IBGE da Receita."""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import requests

URL = "https://www.gov.br/receitafederal/dados/municipios.csv/@@download/file"


def main():
    response = requests.get(URL, timeout=(10, 60))
    response.raise_for_status()
    data = pd.read_csv(io.BytesIO(response.content), sep=";", encoding="latin1", dtype=str).fillna("")
    if data.shape[1] != 5 or len(data) < 5000:
        raise ValueError("A tabela oficial não tem o formato esperado. O catálogo anterior foi mantido.")
    data.columns = ["municipio_code", "ibge_code", "tom_name", "nome", "uf"]
    data["municipio_code"] = data["municipio_code"].str.zfill(4)
    data["nome"] = data["nome"].where(data["nome"].ne(""), data["tom_name"].str.title())
    data = data[data.uf.str.fullmatch("[A-Z]{2}") & data.ibge_code.str.fullmatch("[0-9]{7}")]
    if data.duplicated(["uf", "municipio_code"]).any():
        raise ValueError("Códigos de municípios repetidos. O catálogo anterior foi mantido.")
    path = Path(__file__).resolve().parents[1] / "config/municipalities.csv"
    data[["uf", "municipio_code", "ibge_code", "nome"]].sort_values(["uf", "nome"]).to_csv(path, index=False)
    print(f"Catálogo oficial atualizado: {len(data)} municípios.")


if __name__ == "__main__":
    main()
