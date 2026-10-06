# Arquitetura

```text
Receita Federal — Dados Abertos CNPJ
        |
        +-- Estabelecimentos ---- bairro, abertura, CNAE, telefone, e-mail, CNPJ completo
        |
        +-- Simples ------------- cnpj_basico, opcao_pelo_mei
        |
        +-- Empresas ------------ razão social, natureza jurídica, porte
        |
        +-- Sócios -------------- QSA / nome de pessoa física
        |
        +-- CNAEs --------------- descrições
        |
        v
ETL semestral (streaming; sem ReceitaWS)
        |
        +-- join por cnpj_basico
        +-- remove opcao_pelo_mei == S
        +-- marca CNAE contábil
        +-- escolhe nome de contato
        v
data/companies.parquet
        |
        v
Streamlit
  filtros dinâmicos de idade/bairro/CNAE/histórico
        |
        +--> link interno ?contact=...
                |
                +--> grava tentativa em DB persistente
                +--> redireciona para wa.me
```

## Por que o CNPJ básico resolve o MEI

A tabela `Simples` é empresarial, por raiz de CNPJ. O campo de 8 dígitos não é informação incompleta para esse join: ele é a chave publicada para vincular o regime tributário aos estabelecimentos da mesma raiz. Para MEI, o enquadramento é SIMEI e o empreendedor deve ter um único estabelecimento.

## O que deixa de existir

- consulta ReceitaWS individual;
- `sleep(20)` por CNPJ;
- cache JSON por API;
- filtro de MEI por natureza jurídica 213-5;
- copiar/colar listas de telefones e sócios entre notebooks;
- listas manuais de links de WhatsApp.
