ESTAB_COLS = [
    "cnpj_basico", "cnpj_ordem", "cnpj_dv", "identificador_matriz_filial",
    "nome_fantasia", "situacao_cadastral", "data_situacao_cadastral",
    "motivo_situacao_cadastral", "nome_cidade_exterior", "pais",
    "data_inicio_atividade", "cnae_fiscal_principal", "cnae_fiscal_secundaria",
    "tipo_logradouro", "logradouro", "numero", "complemento", "bairro", "cep",
    "uf", "municipio", "ddd_1", "telefone_1", "ddd_2", "telefone_2",
    "ddd_fax", "fax", "correio_eletronico", "situacao_especial",
    "data_situacao_especial",
]

EMPRESA_COLS = [
    "cnpj_basico", "razao_social", "natureza_juridica",
    "qualificacao_responsavel", "capital_social", "porte_empresa",
    "ente_federativo_responsavel",
]

SOCIO_COLS = [
    "cnpj_basico", "identificador_socio", "nome_socio", "cnpj_cpf_socio",
    "qualificacao_socio", "data_entrada_sociedade", "pais",
    "representante_legal", "nome_representante", "qualificacao_representante",
    "faixa_etaria",
]

SIMPLES_COLS = [
    "cnpj_basico", "opcao_pelo_simples", "data_opcao_simples",
    "data_exclusao_simples", "opcao_pelo_mei", "data_opcao_mei",
    "data_exclusao_mei",
]

CNAE_COLS = ["codigo", "descricao"]
QUALIFICACAO_COLS = ["codigo", "descricao"]

# Situação cadastral 02 = ativa no layout aberto do CNPJ.
SITUACAO_ATIVA = "02"

# Natureza jurídica 213-5 = Empresário (Individual). Não equivale a MEI.
NATUREZA_EMPRESARIO_INDIVIDUAL = "2135"
