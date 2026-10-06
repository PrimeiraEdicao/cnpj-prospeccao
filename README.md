# Prospecção CNPJ — pipeline único (Receita + Streamlit)

Este projeto substitui os três notebooks originais por um fluxo único e reproduzível. Ele usa apenas os **Dados Abertos do CNPJ da Receita Federal** para montar a base de prospecção, sem consultar ReceitaWS CNPJ por CNPJ.

## O ponto-chave do MEI

O arquivo público **Simples** possui o campo `cnpj_basico` (os 8 primeiros dígitos do CNPJ) e o indicador `opcao_pelo_mei`. O arquivo **Estabelecimentos** também possui `cnpj_basico`, além de ordem e DV. Portanto, o join correto é:

```text
Estabelecimentos.cnpj_basico = Simples.cnpj_basico
```

Para o objetivo deste projeto, a empresa é removida quando `opcao_pelo_mei == "S"`.

Não use `natureza_juridica == 2135` como sinônimo de MEI: `213-5` identifica **Empresário (Individual)**, categoria que também contém empresas que não estão enquadradas no SIMEI.

## O que o pipeline faz

1. Descobre automaticamente a competência mais recente pela Receita (WebDAV), com espelho público de contingência.
2. Processa os ZIPs de **Estabelecimentos** em streaming e retém somente empresas ativas do município/UF configurados.
3. Reconstrói o CNPJ de 14 dígitos (`básico + ordem + DV`).
4. Faz join com **Simples** pelo CNPJ básico e remove MEI.
5. Faz join com **Empresas** para razão social, natureza jurídica, porte etc.
6. Faz join com **Sócios**, também pelo CNPJ básico, e seleciona um sócio pessoa física como candidato de saudação.
7. Usa **CNAE** para descrição e sinaliza escritórios/serviços contábeis.
8. Salva uma base Parquet compacta em `data/companies.parquet`.
9. O Streamlit permite filtrar por bairro, idade da empresa, CNAE, telefone e histórico de contato.
10. Ao abrir o link de WhatsApp pelo app, a tentativa é registrada antes do redirecionamento.

## Escopo padrão

O notebook original usa município Receita `4553`, correspondente a **Governador Valadares/MG**. Esse é o padrão em `.env.example` e no workflow, mas pode ser alterado.

## Idade da empresa

O ETL **não exclui empresas com menos de 1 ano**. O Streamlit calcula a idade diariamente a partir da data de abertura e usa 1 ano como filtro padrão. Isso evita uma deficiência do fluxo antigo: uma empresa presente na última carga passa a ficar elegível automaticamente quando completa 1 ano, sem depender de uma nova execução do ETL naquele dia.

## Atualização semestral

O workflow `.github/workflows/update-receita.yml` roda em **10 de janeiro e 10 de julho**, além de permitir execução manual (`workflow_dispatch`). Janeiro/julho é um intervalo efetivo de seis meses.

A **primeira carga também começa automaticamente após um push de código para `main` enquanto `data/companies.parquet` estiver ausente**. Quando a base já existe, os pushes validam o código e a fonte sem refazer o processamento nacional. As atualizações completas continuam semestrais ou manuais.

Os jobs aparecem separadamente no GitHub Actions:

- `testes`: regressões do ETL, downloads, histórico e interface;
- `validar-fonte`: lista a competência, verifica as partes obrigatórias e baixa/lê o ZIP pequeno de CNAEs;
- `update`: baixa e processa o recorte real, depois publica Parquet e metadados.

Um resultado verde em `validar-fonte` **não significa que a base real já está pronta**. Para isso, o passo `Atualizar base filtrada` e o commit dos dois arquivos precisam terminar com sucesso. O processamento completo lê dezenas de ZIPs nacionais e pode levar horas.

**Não reexecute o run vermelho antigo para testar uma correção nova:** o botão de reexecução usa o commit original daquele run. Abra uma execução do novo commit ou use `Actions → Atualizar base Receita CNPJ → Run workflow` na branch `main`.

O workflow:

- verifica a competência mais recente publicada;
- baixa/processa os arquivos um a um para reduzir uso de disco;
- gera somente a base filtrada do município;
- apaga temporários automaticamente;
- versiona `companies.parquet` e `release.json`.

Se um download oficial falhar, a contingência procura o **mesmo nome de ZIP na mesma competência** no espelho. Bytes parciais da origem anterior são descartados antes da troca. A carga rejeita ZIPs inválidos, tamanhos incompletos e catálogos sem todas as partes de Estabelecimentos, Empresas, Sócios ou Simples. A origem do catálogo fica registrada em `release.json`; o espelho é uma cópia pública de terceiros, não uma API oficial.

> Recomendação: use repositório **privado** se for versionar a base final, pois ela contém contatos publicados no cadastro CNPJ e histórico operacional de prospecção.

## Instalação local

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
python -m src.etl
streamlit run app.py
```

Para visualizar a interface imediatamente, basta instalar as dependências e executar `streamlit run app.py`. Quando a base real não existe, o app abre em **modo de demonstração**, com empresas fictícias, filtros e prévia da mensagem. Os contatos ficam desativados e o banco de histórico não é usado. Após a geração do Parquet, o app usa a base real automaticamente no próximo carregamento.

## Filtros disponíveis no app

- idade mínima e máxima da empresa;
- bairro;
- remover ou manter escritórios/serviços contábeis;
- somente registros com telefone;
- somente celular provável;
- nunca tentado / já tentado / todos;
- busca textual por empresa, CNPJ ou CNAE.

A idade usa aniversários de calendário (incluindo o tratamento de 29 de fevereiro), e é recalculada a cada interação no horário de Brasília. A substituição do Parquet invalida o cache. O botão **Atualizar histórico** recarrega tentativas abertas em outras abas.

## CNAEs de contabilidade

A lista fica em `config/exclusion_cnaes.txt` e começa com:

- `6920601` — atividades de contabilidade;
- `6920602` — consultoria e auditoria contábil e tributária.

O sinal considera CNAE principal **ou secundário**. A lista é configurável sem alterar código.

## Nome para saudação

O pipeline evita inferir nomes a partir de texto arbitrário sempre que possível:

- considera só registros da tabela Sócios marcados como **pessoa física**;
- prioriza titular/empresário, sócio-administrador e administrador quando a qualificação está disponível;
- extrai o primeiro nome apenas desse registro;
- para Empresário Individual não-MEI sem QSA PF, usa a razão social como fallback e sinaliza a origem;
- se não houver candidato confiável, o app deixa o campo vazio para revisão manual.

Isso é mais seguro do que uma “proxy de nomes” genérica, porque o próprio tipo do registro na base pública informa se o sócio é pessoa física.

## Registro de tentativa de WhatsApp

O app gera um link relativo para ele próprio. Quando o link é aberto:

1. o app recebe `CNPJ + attempt_id`;
2. grava a tentativa no banco;
3. redireciona o novo separador para `wa.me`.

O `attempt_id` torna o registro idempotente: um rerun do Streamlit não duplica a tentativa.

### Persistência

Localmente, o padrão é SQLite:

```env
DATABASE_URL=sqlite:///data/contact_state.db
```

Para deploy em **Streamlit Community Cloud**, o filesystem local não deve ser tratado como armazenamento permanente. Configure `DATABASE_URL` com PostgreSQL persistente (por exemplo, Supabase ou Neon) nos Secrets do app. O mesmo código funciona sem alteração.

## Observações de escala

Este projeto foi desenhado para processar a base nacional da Receita em streaming, mas **persistir somente o recorte geográfico necessário**. Não é recomendável colocar a base nacional bruta no GitHub ou carregá-la inteira no Streamlit.

Se futuramente o produto precisar atender várias cidades/usuários, a evolução natural é:

- ETL nacional em máquina/serviço com mais disco;
- Parquet particionado por UF/município em object storage;
- PostgreSQL para estado e usuários;
- API/FastAPI ou consultas DuckDB/Polars sobre as partições.

## Testes

```bash
python -m pytest -q
```
