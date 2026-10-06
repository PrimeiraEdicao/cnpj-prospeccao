from __future__ import annotations

import argparse
import io
import json
import os
import re
import zipfile
from collections import defaultdict
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from .constants import (
    CNAE_COLS,
    EMPRESA_COLS,
    ESTAB_COLS,
    NATUREZA_EMPRESARIO_INDIVIDUAL,
    QUALIFICACAO_COLS,
    SIMPLES_COLS,
    SITUACAO_ATIVA,
    SOCIO_COLS,
)
from .receita import TempDownload, list_zip_urls, resolve_release, select_files
from .utils import (
    cnpj_full,
    first_name,
    has_any_cnae,
    load_cnae_exclusions,
    normalize_code,
    normalize_text,
    phone_br,
    is_probable_mobile_br,
)

load_dotenv()


def _first_member_name(zip_path: Path) -> str:
    with zipfile.ZipFile(zip_path) as zf:
        members = [x for x in zf.namelist() if not x.endswith("/")]
        if not members:
            raise RuntimeError(f"ZIP vazio: {zip_path}")
        return members[0]


def iter_zip_csv(zip_path: Path, names: list[str], chunksize: int):
    member = _first_member_name(zip_path)
    with zipfile.ZipFile(zip_path) as zf, zf.open(member) as raw:
        # A Receita publica arquivos delimitados por ponto e vírgula, sem cabeçalho, Latin-1.
        reader = pd.read_csv(
            raw,
            sep=";",
            header=None,
            names=names,
            dtype=str,
            encoding="latin1",
            chunksize=chunksize,
            low_memory=False,
            keep_default_na=False,
        )
        yield from reader


def read_small_zip(zip_path: Path, names: list[str]) -> pd.DataFrame:
    return next(iter_zip_csv(zip_path, names, chunksize=10_000_000))


def collect_establishments(urls: list[str], uf: str, municipio_code: str, chunksize: int) -> pd.DataFrame:
    selected = select_files(urls, "Estabele")
    if not selected:
        raise RuntimeError("Arquivos de Estabelecimentos não encontrados na competência da Receita.")

    keep_cols = [
        "cnpj_basico", "cnpj_ordem", "cnpj_dv", "identificador_matriz_filial",
        "nome_fantasia", "situacao_cadastral", "data_inicio_atividade",
        "cnae_fiscal_principal", "cnae_fiscal_secundaria", "tipo_logradouro",
        "logradouro", "numero", "complemento", "bairro", "cep", "uf", "municipio",
        "ddd_1", "telefone_1", "ddd_2", "telefone_2", "correio_eletronico",
    ]
    frames: list[pd.DataFrame] = []
    for i, url in enumerate(selected, 1):
        print(f"[Estabelecimentos {i}/{len(selected)}] {Path(url).name}")
        with TempDownload(url) as path:
            for chunk in iter_zip_csv(path, ESTAB_COLS, chunksize):
                chunk["uf"] = chunk["uf"].str.upper().str.strip()
                chunk["municipio"] = chunk["municipio"].map(lambda x: normalize_code(x))
                chunk["situacao_cadastral"] = chunk["situacao_cadastral"].map(lambda x: normalize_code(x, 2))
                f = chunk[
                    (chunk["uf"] == uf.upper())
                    & (chunk["municipio"] == normalize_code(municipio_code))
                    & (chunk["situacao_cadastral"] == SITUACAO_ATIVA)
                ][keep_cols].copy()
                if not f.empty:
                    frames.append(f)
    if not frames:
        return pd.DataFrame(columns=keep_cols)
    df = pd.concat(frames, ignore_index=True)
    df["cnpj_basico"] = df["cnpj_basico"].map(lambda x: normalize_code(x, 8))
    df["cnpj_ordem"] = df["cnpj_ordem"].map(lambda x: normalize_code(x, 4))
    df["cnpj_dv"] = df["cnpj_dv"].map(lambda x: normalize_code(x, 2))
    df["cnpj"] = [cnpj_full(a, b, c) for a, b, c in zip(df.cnpj_basico, df.cnpj_ordem, df.cnpj_dv)]
    df["data_abertura"] = pd.to_datetime(df["data_inicio_atividade"], format="%Y%m%d", errors="coerce")
    return df


def collect_simple(urls: list[str], roots: set[str], chunksize: int) -> pd.DataFrame:
    selected = select_files(urls, "Simples")
    if not selected:
        raise RuntimeError("Arquivo Simples não encontrado na competência da Receita.")
    frames: list[pd.DataFrame] = []
    for i, url in enumerate(selected, 1):
        print(f"[Simples {i}/{len(selected)}] {Path(url).name}")
        with TempDownload(url) as path:
            for chunk in iter_zip_csv(path, SIMPLES_COLS, chunksize):
                chunk["cnpj_basico"] = chunk["cnpj_basico"].map(lambda x: normalize_code(x, 8))
                f = chunk[chunk["cnpj_basico"].isin(roots)].copy()
                if not f.empty:
                    frames.append(f)
    if not frames:
        return pd.DataFrame(columns=SIMPLES_COLS)
    return pd.concat(frames, ignore_index=True).drop_duplicates("cnpj_basico", keep="last")


def collect_companies(urls: list[str], roots: set[str], chunksize: int) -> pd.DataFrame:
    selected = select_files(urls, "Empresa")
    if not selected:
        raise RuntimeError("Arquivos de Empresas não encontrados na competência da Receita.")
    frames: list[pd.DataFrame] = []
    for i, url in enumerate(selected, 1):
        print(f"[Empresas {i}/{len(selected)}] {Path(url).name}")
        with TempDownload(url) as path:
            for chunk in iter_zip_csv(path, EMPRESA_COLS, chunksize):
                chunk["cnpj_basico"] = chunk["cnpj_basico"].map(lambda x: normalize_code(x, 8))
                f = chunk[chunk["cnpj_basico"].isin(roots)].copy()
                if not f.empty:
                    frames.append(f)
    if not frames:
        return pd.DataFrame(columns=EMPRESA_COLS)
    return pd.concat(frames, ignore_index=True).drop_duplicates("cnpj_basico", keep="last")


def collect_qualifications(urls: list[str]) -> dict[str, str]:
    selected = select_files(urls, "Qualifica")
    if not selected:
        return {}
    with TempDownload(selected[0]) as path:
        df = read_small_zip(path, QUALIFICACAO_COLS)
    return {normalize_code(k): normalize_text(v) for k, v in zip(df["codigo"], df["descricao"])}


def collect_cnaes(urls: list[str]) -> dict[str, str]:
    selected = select_files(urls, "Cnae")
    if not selected:
        return {}
    with TempDownload(selected[0]) as path:
        df = read_small_zip(path, CNAE_COLS)
    return {normalize_code(k): normalize_text(v) for k, v in zip(df["codigo"], df["descricao"])}


def _qualification_priority(description: str) -> int:
    d = normalize_text(description).upper()
    # Titular/empresário e sócio-administrador tendem a ser melhores candidatos de saudação.
    if "TITULAR" in d or "EMPRES" in d:
        return 0
    if "SÓCIO-ADMINISTRADOR" in d or "SOCIO-ADMINISTRADOR" in d:
        return 1
    if "ADMINISTRADOR" in d:
        return 2
    if "SÓCIO" in d or "SOCIO" in d:
        return 3
    return 9


def collect_partners(
    urls: list[str], roots: set[str], chunksize: int, qualification_map: dict[str, str]
) -> pd.DataFrame:
    selected = select_files(urls, "Socio")
    if not selected:
        raise RuntimeError("Arquivos de Sócios não encontrados na competência da Receita.")
    frames: list[pd.DataFrame] = []
    for i, url in enumerate(selected, 1):
        print(f"[Sócios {i}/{len(selected)}] {Path(url).name}")
        with TempDownload(url) as path:
            for chunk in iter_zip_csv(path, SOCIO_COLS, chunksize):
                chunk["cnpj_basico"] = chunk["cnpj_basico"].map(lambda x: normalize_code(x, 8))
                # identificador 2 = pessoa física no layout público.
                f = chunk[
                    chunk["cnpj_basico"].isin(roots)
                    & (chunk["identificador_socio"].map(normalize_code) == "2")
                ].copy()
                if not f.empty:
                    frames.append(f[["cnpj_basico", "nome_socio", "qualificacao_socio", "data_entrada_sociedade"]])
    if not frames:
        return pd.DataFrame(columns=["cnpj_basico", "nomes_socios", "nome_contato", "primeiro_nome", "qualificacao_contato"])

    df = pd.concat(frames, ignore_index=True)
    df["qualificacao_socio"] = df["qualificacao_socio"].map(normalize_code)
    df["qualificacao_desc"] = df["qualificacao_socio"].map(qualification_map).fillna("")
    df["priority"] = df["qualificacao_desc"].map(_qualification_priority)
    df["nome_socio"] = df["nome_socio"].map(normalize_text)
    df = df[df["nome_socio"] != ""]

    out_rows = []
    for root, g in df.groupby("cnpj_basico", sort=False):
        g = g.sort_values(["priority", "data_entrada_sociedade"], kind="stable")
        names = list(dict.fromkeys(g["nome_socio"].tolist()))
        chosen = g.iloc[0]
        out_rows.append({
            "cnpj_basico": root,
            "nomes_socios": " | ".join(names),
            "nome_contato": chosen["nome_socio"],
            "primeiro_nome": first_name(chosen["nome_socio"]),
            "qualificacao_contato": chosen["qualificacao_desc"],
            "origem_nome_contato": "qsa_pessoa_fisica",
        })
    return pd.DataFrame(out_rows)


def enrich_and_filter(
    estab: pd.DataFrame,
    simples: pd.DataFrame,
    empresas: pd.DataFrame,
    socios: pd.DataFrame,
    cnae_map: dict[str, str],
    excluded_cnaes: set[str],
) -> pd.DataFrame:
    if estab.empty:
        return estab

    df = estab.merge(simples, on="cnpj_basico", how="left", validate="many_to_one")
    # MEI é definido pelo indicador próprio do SIMEI; natureza jurídica 213-5 NÃO é sinônimo de MEI.
    df["opcao_pelo_mei"] = df["opcao_pelo_mei"].fillna("").str.upper().str.strip()
    df = df[df["opcao_pelo_mei"] != "S"].copy()

    df = df.merge(empresas, on="cnpj_basico", how="left", validate="many_to_one")
    if not socios.empty:
        df = df.merge(socios, on="cnpj_basico", how="left", validate="many_to_one")
    else:
        for col in ["nomes_socios", "nome_contato", "primeiro_nome", "qualificacao_contato", "origem_nome_contato"]:
            df[col] = ""

    # Fallback conservador para Empresário Individual não-MEI quando não há QSA PF.
    df["natureza_juridica"] = df["natureza_juridica"].map(normalize_code)
    missing = df["primeiro_nome"].fillna("").eq("")
    ei = df["natureza_juridica"].eq(NATUREZA_EMPRESARIO_INDIVIDUAL)
    fallback = missing & ei
    df.loc[fallback, "nome_contato"] = df.loc[fallback, "razao_social"].fillna("")
    df.loc[fallback, "primeiro_nome"] = df.loc[fallback, "razao_social"].map(first_name)
    df.loc[fallback, "origem_nome_contato"] = "razao_social_empresario_individual"

    for col in ["ddd_1", "telefone_1", "ddd_2", "telefone_2"]:
        df[col] = df[col].fillna("")
    df["whatsapp_1"] = [phone_br(d, n) for d, n in zip(df["ddd_1"], df["telefone_1"])]
    df["whatsapp_2"] = [phone_br(d, n) for d, n in zip(df["ddd_2"], df["telefone_2"])]
    df["celular_1_provavel"] = [is_probable_mobile_br(d, n) for d, n in zip(df["ddd_1"], df["telefone_1"])]
    df["celular_2_provavel"] = [is_probable_mobile_br(d, n) for d, n in zip(df["ddd_2"], df["telefone_2"])]
    df["tem_telefone"] = (df["whatsapp_1"] != "") | (df["whatsapp_2"] != "")

    df["cnae_fiscal_principal"] = df["cnae_fiscal_principal"].map(normalize_code)
    df["cnae_principal_descricao"] = df["cnae_fiscal_principal"].map(cnae_map).fillna("")
    df["is_contabilidade"] = [
        has_any_cnae(p, s, excluded_cnaes)
        for p, s in zip(df["cnae_fiscal_principal"], df["cnae_fiscal_secundaria"])
    ]

    # Higienização simples de texto para UI.
    for col in ["razao_social", "nome_fantasia", "bairro", "logradouro", "numero", "complemento", "correio_eletronico"]:
        if col in df.columns:
            df[col] = df[col].map(normalize_text)

    keep = [
        "cnpj", "cnpj_basico", "razao_social", "nome_fantasia", "data_abertura",
        "bairro", "tipo_logradouro", "logradouro", "numero", "complemento", "cep",
        "uf", "municipio", "cnae_fiscal_principal", "cnae_principal_descricao",
        "cnae_fiscal_secundaria", "natureza_juridica", "porte_empresa",
        "ddd_1", "telefone_1", "ddd_2", "telefone_2", "whatsapp_1", "whatsapp_2",
        "celular_1_provavel", "celular_2_provavel", "tem_telefone", "correio_eletronico",
        "nomes_socios", "nome_contato", "primeiro_nome", "qualificacao_contato",
        "origem_nome_contato", "opcao_pelo_simples", "data_opcao_simples",
        "opcao_pelo_mei", "data_opcao_mei", "data_exclusao_mei", "is_contabilidade",
    ]
    for col in keep:
        if col not in df.columns:
            df[col] = ""
    return df[keep].sort_values(["bairro", "razao_social", "cnpj"]).reset_index(drop=True)


def run_etl(
    uf: str,
    municipio_code: str,
    output: str | Path,
    release_name: str | None = None,
    chunksize: int = 250_000,
    exclusion_file: str | Path = "config/exclusion_cnaes.txt",
):
    release = resolve_release(release_name)
    print(f"Competência selecionada: {release.name}")
    urls = list_zip_urls(release)
    print(f"ZIPs publicados encontrados: {len(urls)}")

    estab = collect_establishments(urls, uf, municipio_code, chunksize)
    if estab.empty:
        raise RuntimeError(f"Nenhum estabelecimento ativo encontrado para UF={uf}, município={municipio_code}.")
    roots = set(estab["cnpj_basico"].astype(str))
    print(f"Estabelecimentos ativos no escopo: {len(estab):,}; raízes CNPJ: {len(roots):,}")

    simples = collect_simple(urls, roots, chunksize)
    # Raízes ausentes da tabela Simples também são tratadas como não-MEI.
    roots_after_mei = roots - set(simples.loc[simples["opcao_pelo_mei"].str.upper().str.strip().eq("S"), "cnpj_basico"])
    print(f"Raízes após remover MEI: {len(roots_after_mei):,}")

    empresas = collect_companies(urls, roots_after_mei, chunksize)
    qmap = collect_qualifications(urls)
    socios = collect_partners(urls, roots_after_mei, chunksize, qmap)
    cnae_map = collect_cnaes(urls)
    excluded = load_cnae_exclusions(exclusion_file)

    estab = estab[estab["cnpj_basico"].isin(roots_after_mei)].copy()
    simples = simples[simples["cnpj_basico"].isin(roots_after_mei)].copy()
    final = enrich_and_filter(estab, simples, empresas, socios, cnae_map, excluded)

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    final.to_parquet(output, index=False)
    meta = {
        "receita_release": release.name,
        "uf": uf.upper(),
        "municipio_code": normalize_code(municipio_code),
        "rows": int(len(final)),
        "non_mei_rule": "opcao_pelo_mei != 'S' na tabela Simples, join por CNPJ básico",
        "accounting_cnaes": sorted(excluded),
        "generated_at_utc": pd.Timestamp.utcnow().isoformat(),
    }
    meta_path = output.with_name("release.json")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Base final: {output} ({len(final):,} linhas)")
    print(f"Metadados: {meta_path}")
    return final, meta


def parse_args():
    p = argparse.ArgumentParser(description="ETL CNPJ/RFB para prospecção sem MEI")
    p.add_argument("--uf", default=os.getenv("TARGET_UF", "MG"))
    p.add_argument("--municipio-code", default=os.getenv("TARGET_MUNICIPIO_CODE", "4553"))
    p.add_argument("--release", default=os.getenv("RECEITA_RELEASE") or None)
    p.add_argument("--output", default="data/companies.parquet")
    p.add_argument("--chunksize", type=int, default=int(os.getenv("CSV_CHUNK_SIZE", "250000")))
    p.add_argument("--exclusion-file", default="config/exclusion_cnaes.txt")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_etl(
        uf=args.uf,
        municipio_code=args.municipio_code,
        output=args.output,
        release_name=args.release,
        chunksize=args.chunksize,
        exclusion_file=args.exclusion_file,
    )
