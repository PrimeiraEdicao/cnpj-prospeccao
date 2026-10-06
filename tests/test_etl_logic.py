import pandas as pd

from src.etl import enrich_and_filter


def _estab():
    return pd.DataFrame([
        {
            "cnpj": "11111111000111", "cnpj_basico": "11111111", "nome_fantasia": "MEI",
            "data_abertura": pd.Timestamp("2020-01-01"), "bairro": "CENTRO", "tipo_logradouro": "RUA",
            "logradouro": "A", "numero": "1", "complemento": "", "cep": "35000000", "uf": "MG",
            "municipio": "4553", "cnae_fiscal_principal": "4712100", "cnae_fiscal_secundaria": "",
            "ddd_1": "33", "telefone_1": "999999999", "ddd_2": "", "telefone_2": "",
            "correio_eletronico": "a@a.com",
        },
        {
            "cnpj": "22222222000122", "cnpj_basico": "22222222", "nome_fantasia": "EI NAO MEI",
            "data_abertura": pd.Timestamp("2020-01-01"), "bairro": "CENTRO", "tipo_logradouro": "RUA",
            "logradouro": "B", "numero": "2", "complemento": "", "cep": "35000000", "uf": "MG",
            "municipio": "4553", "cnae_fiscal_principal": "4712100", "cnae_fiscal_secundaria": "",
            "ddd_1": "33", "telefone_1": "988888888", "ddd_2": "", "telefone_2": "",
            "correio_eletronico": "b@b.com",
        },
        {
            "cnpj": "33333333000133", "cnpj_basico": "33333333", "nome_fantasia": "CONTABIL",
            "data_abertura": pd.Timestamp("2020-01-01"), "bairro": "CENTRO", "tipo_logradouro": "RUA",
            "logradouro": "C", "numero": "3", "complemento": "", "cep": "35000000", "uf": "MG",
            "municipio": "4553", "cnae_fiscal_principal": "6920601", "cnae_fiscal_secundaria": "",
            "ddd_1": "33", "telefone_1": "977777777", "ddd_2": "", "telefone_2": "",
            "correio_eletronico": "c@c.com",
        },
    ])


def test_mei_removed_but_non_mei_empresario_individual_is_kept_and_accounting_flagged():
    simples = pd.DataFrame([
        {"cnpj_basico": "11111111", "opcao_pelo_simples": "S", "data_opcao_simples": "20200101",
         "data_exclusao_simples": "", "opcao_pelo_mei": "S", "data_opcao_mei": "20200101", "data_exclusao_mei": ""},
        {"cnpj_basico": "22222222", "opcao_pelo_simples": "S", "data_opcao_simples": "20200101",
         "data_exclusao_simples": "", "opcao_pelo_mei": "N", "data_opcao_mei": "", "data_exclusao_mei": ""},
        {"cnpj_basico": "33333333", "opcao_pelo_simples": "N", "data_opcao_simples": "",
         "data_exclusao_simples": "", "opcao_pelo_mei": "N", "data_opcao_mei": "", "data_exclusao_mei": ""},
    ])
    empresas = pd.DataFrame([
        {"cnpj_basico": "11111111", "razao_social": "JOAO TESTE", "natureza_juridica": "2135", "qualificacao_responsavel": "", "capital_social": "", "porte_empresa": "01", "ente_federativo_responsavel": ""},
        {"cnpj_basico": "22222222", "razao_social": "MARIA SILVA", "natureza_juridica": "2135", "qualificacao_responsavel": "", "capital_social": "", "porte_empresa": "01", "ente_federativo_responsavel": ""},
        {"cnpj_basico": "33333333", "razao_social": "CONTABIL TESTE LTDA", "natureza_juridica": "2062", "qualificacao_responsavel": "", "capital_social": "", "porte_empresa": "01", "ente_federativo_responsavel": ""},
    ])
    socios = pd.DataFrame(columns=["cnpj_basico", "nomes_socios", "nome_contato", "primeiro_nome", "qualificacao_contato", "origem_nome_contato"])
    out = enrich_and_filter(_estab(), simples, empresas, socios, {"6920601": "Atividades de contabilidade"}, {"6920601"})

    assert "11111111000111" not in set(out["cnpj"])
    assert "22222222000122" in set(out["cnpj"])
    ei = out[out["cnpj"] == "22222222000122"].iloc[0]
    assert ei["primeiro_nome"] == "Maria"
    assert ei["origem_nome_contato"] == "razao_social_empresario_individual"
    accounting = out[out["cnpj"] == "33333333000133"].iloc[0]
    assert bool(accounting["is_contabilidade"]) is True
