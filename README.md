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

A base atual é de **Governador Valadares/MG**, código Receita `4553`. A configuração persistente está em `config/scopes.json` e aceita vários municípios de várias UFs. O ETL percorre os ZIPs nacionais uma vez e retém os pares UF/município configurados.

Para adicionar uma cidade, abra **Actions → Atualizar base Receita CNPJ → Run workflow** e preencha `adicionar_uf` e `adicionar_municipios`. Os códigos Receita têm **quatro dígitos**; não use o código IBGE de sete dígitos. É possível informar vários códigos da mesma UF separados por vírgula. O campo `nome_cidade` é opcional, e o nome da tabela Municípios da Receita prevalece. Deixe os campos vazios para atualizar apenas o escopo existente.

A cidade será acrescentada a `config/scopes.json` **após a carga concluir com sucesso**, preservando Valadares e as demais cidades. As atualizações semestrais usam essa configuração. O filtro da interface lista somente cidades já presentes no Parquet; a seleção não baixa uma nova cidade.

Alternativa no terminal:

```bash
.venv-cnpj312/bin/python -m src.etl --scopes-file config/scopes.json \
  --add-uf SUA_UF --add-municipios CODIGO_RECEITA --output data/companies.parquet
```

Substitua os dois valores pelos dados reais. Para atualizar a configuração sem acrescentar cidades, omita `--add-uf` e `--add-municipios`. A leitura do catálogo Municípios valida o código antes dos ZIPs grandes; uma combinação UF/código sem estabelecimentos ativos interrompe a publicação.

## Idade da empresa

O ETL **não exclui empresas com menos de 1 ano**. O Streamlit calcula a idade diariamente a partir da data de abertura e usa 1 ano como filtro padrão. Isso evita uma deficiência do fluxo antigo: uma empresa presente na última carga passa a ficar elegível automaticamente quando completa 1 ano, sem depender de uma nova execução do ETL naquele dia.

## Atualização semestral

O workflow `.github/workflows/update-receita.yml` roda em **10 de janeiro e 10 de julho**, além de permitir execução manual (`workflow_dispatch`). Janeiro/julho é um intervalo efetivo de seis meses.

A **primeira carga também começa automaticamente após um push de código para `main` enquanto `data/companies.parquet` estiver ausente**. Quando a base já existe e o conjunto de municípios configurados é igual ao da última carga, os pushes validam o código e a fonte sem refazer o processamento nacional. Alterar os municípios em `config/scopes.json` também inicia uma carga. As atualizações completas continuam semestrais ou manuais.

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

Use **Python 3.12**, a mesma versão validada no GitHub Actions. O limite atual `pyarrow<20` não oferece wheel para Python 3.14; nesse Python o pip tenta compilar Arrow/C++ e a instalação falha.

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

## Abrir no GitHub Codespaces

No repositório, abra **Code → Codespaces → Create codespace on main**. Os novos ambientes usam Python 3.12 através de `.devcontainer/devcontainer.json`.

No terminal do Codespaces, execute:

```bash
git pull origin main
bash scripts/run_app.sh
```

O script instala as dependências em `.venv-cnpj312` e abre o Streamlit na porta 8501. Se um Codespace antigo ainda usar Python 3.14, ele obtém Python 3.12 com `uv` quando necessário, sem exigir reconstrução do ambiente. Se o Python 3.12 estiver disponível, mas faltar `ensurepip`/`python3.12-venv`, o script também usa `uv` para recriar o ambiente incompleto e instalar `pip`, sem precisar de `sudo apt install`. As dependências do app ficam no ambiente do projeto.

Na aba **Ports**, abra a porta **8501** no navegador. Para encerrar, pressione `Ctrl+C` no terminal. Para instalar sem iniciar a interface, use `bash scripts/run_app.sh --setup-only`.

## Filtros disponíveis no app

- idade mínima e máxima da empresa;
- cidade/UF e bairro (seleção múltipla, com agrupamento de variações de espaços, caixa e acentos);
- porte cadastral: `01` ME, `03` EPP, `05` Demais e `00` Não informado; ME/EPP vêm selecionados;
- remover ou manter escritórios/serviços contábeis;
- excluir escolas/creches/educação, igrejas, partidos e entidades governamentais;
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

## Contatos na tabela, saudação e fila

A tabela permite marcar empresas e clicar em **Abrir WhatsApps selecionados (N)** para abrir uma aba por empresa. A lista começa com **20 empresas por página**, com opções de 50 e 100. Os links individuais para os telefones válidos continuam disponíveis. A abertura em lote usa um número por empresa, priorizando o celular provável.

A saudação usa `America/Sao_Paulo`: **Bom dia** das 6h às 11h59, **Boa tarde** das 12h às 17h59 e **Boa noite** das 18h às 5h59. Ela é recalculada na abertura de cada contato, inclusive se a tabela tiver sido carregada antes da mudança de horário. É possível escolher uma saudação personalizada. O texto padrão inclui **Tudo bem?**:

```text
{saudacao}! Tudo bem? Sou {remetente}. Nesse contato falo com {nome}?
```

A apresentação e a mensagem são editáveis no app. `CONTACT_SENDER` e `CONTACT_TEMPLATE` no `.env` ou Secrets definem os padrões para outros projetos. O nome pode ser revisado individualmente; sem nome identificado, usa-se “a pessoa responsável”.

Na **Fila de contatos**, selecione empresas ou adicione a página inteira. Abra cada contato na mesma aba e use **Próximo contato** para avançar. A fila fica na sessão atual e acompanha os filtros; não envia mensagens nem registra tentativas ao adicionar ou avançar.

Ao abrir um link, o app valida CNPJ e telefone, registra a abertura no histórico e redireciona para `wa.me`. O `attempt_id` torna essa abertura idempotente. **Uma abertura não confirma envio ou entrega**: a mensagem deve ser conferida e enviada no WhatsApp. O histórico pode ser atualizado sem recarregar os dados.

### Regras das atividades fora do foco

As regras de `config/prospect_exclusions.json` são aplicadas na interface à base já carregada; não é necessário refazer o ETL para remover esse público. Considere os CNAEs principal **e secundários**:

| Público | CNAE | Natureza jurídica adicional |
| --- | --- | --- |
| Escolas, creches e educação | Divisão `85`, incluindo outros tipos de ensino | — |
| Igrejas e organizações religiosas | `9491000` | `3220` |
| Partidos e organizações políticas | `9492800` | `3255`, `3263`, `3271` |
| Governo | Divisão `84` | Grupo `1`, `2011` (empresa pública), `2038` (economia mista); ente federativo responsável informado quando disponível |

As quatro categorias vêm removidas por padrão e podem ser reabilitadas no filtro. As naturezas adicionais são importantes porque entidades públicas também podem ter CNAE de saúde, ensino ou outros setores. A classificação se baseia nos campos publicados; não infere controle governamental pelo nome da empresa.

Fontes: [layout CNPJ/RFB](https://www.gov.br/receitafederal/dados/cnpj-metadados.pdf), [CNAE/IBGE](https://cnae.ibge.gov.br/?view=estrutura) e [natureza jurídica/IBGE](https://cnae.ibge.gov.br/documentacao/cronologia/3051-concla/estrutura/natureza-juridica-2021.html).

### Automação de envio

O caminho para envio sem abrir cada conversa é a **WhatsApp Business Platform / Cloud API**, com conta configurada, autorização dos destinatários e templates aprovados. A base pública do CNPJ não contém essa autorização, e a verificação da conta não elimina as regras nem assegura imunidade a bloqueios. Nesta versão, a fila organiza os contatos e o envio continua no WhatsApp; não há disparo automático nem integração API configurada.

Fonte: [política oficial de mensagens do WhatsApp Business](https://business.whatsapp.com/policy).

## Identidade visual

Use **Aparência → Claro / Escuro** no topo da barra lateral para alternar o tema. A escolha é mantida durante a sessão e preserva filtros, busca e fila. O modo escuro inclui campos, seletores, tabela, mensagens e a versão branca oficial do logo.

A busca aceita CNPJ completo com pontuação (`12.345.678/0001-90`) ou apenas os 14 dígitos (`12345678000190`), inclusive zeros à esquerda. Nome e CNAE continuam disponíveis no mesmo campo. A busca respeita os filtros; se um CNPJ existir na base e estiver excluído por eles, o app informa isso em vez de indicar ausência na base.

O app usa os SVGs oficiais de [PrimeiraEdicao/alphalab-site](https://github.com/PrimeiraEdicao/alphalab-site), preservados sem alteração. Azul-marinho `#0F2D5B`, azul de apoio `#315FC3`, destaque `#4F8CFF`, fundo `#F6F8FC` e divisórias `#E0E7F1`. O tema está em `.streamlit/config.toml`; os ativos ficam em `assets/` e não dependem de um site externo para carregar.

## Empresas já contatadas ou descartadas

A lista `config/reviewed_cnpjs.csv` contém os **1.544 CNPJs únicos** das 50 planilhas enviadas em `Empresas filtradas.zip`: 1.634 linhas válidas e 90 repetições, sem CNPJs inválidos. Como as planilhas não distinguem contato de descarte, o lote está marcado como **Revisado anteriormente — contato ou descarte**. O TXT de memória contém telefones e não foi interpretado como CNPJ. A lista versiona somente CNPJ, motivo e arquivo de origem; nomes, telefones e e-mails das planilhas não são publicados.

**Ocultar empresas já revisadas** vem ativado por padrão, independentemente do filtro de histórico. A base da Receita é preservada: a lista é aplicada por CNPJ completo de 14 dígitos a cada carregamento, inclusive quando uma empresa ausente aparece numa nova competência ou uma nova cidade é incluída. Desmarque a opção para consultar esses registros, respeitando os demais filtros. Links de contato ficam desativados, a fila remove empresas revisadas e links antigos não registram abertura nem redirecionam para o WhatsApp.

Para novas listas, abra **Importar empresas já revisadas** na barra lateral. Envie ZIP com planilhas, Excel `.xlsx`, CSV com coluna `CNPJ` ou TXT com um CNPJ por linha. Confira os totais e selecione **Revisado anteriormente**, **Já contatado** ou **Fora do perfil**, conforme o lote. Clique em **Importar CNPJs revisados**. Os dígitos verificadores são validados; duplicatas não criam novos registros. A importação não altera o número de aberturas nem inventa mensagem, telefone ou data de envio. A data salva corresponde à importação da revisão.

Novas importações feitas na interface ficam na tabela `company_reviews` do banco definido por `DATABASE_URL`. Use **Baixar lista de revisão** para guardar um CSV de backup com a união da lista versionada e das novas importações. Esse CSV pode ser reimportado sem perder o motivo de revisão. Em hospedagem com disco temporário, configure PostgreSQL persistente; uploads não fazem commits automáticos no GitHub.

Para incorporar uma nova lista ao próprio repositório, sem depender do banco de contatos:

```bash
python -m scripts.import_reviews "caminho/lista.zip"
# Quando o lote inteiro representa empresas fora do perfil:
python -m scripts.import_reviews "caminho/lista.xlsx" --status fora_perfil
git add config/reviewed_cnpjs.csv
git commit -m "Atualizar empresas já revisadas"
git push
```

Importar novamente preserva os motivos de registros anteriores. A lista usa CNPJ completo; outra filial da mesma raiz não é automaticamente excluída.

## Persistência do banco de contatos

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


### Abrir WhatsApps em lote

- A lista começa com 20 empresas por página; escolha também 50 ou 100.
- Marque as empresas na tabela ou use **Selecionar esta página**. O contador e o destaque das linhas acompanham a seleção.
- Clique em **Abrir WhatsApps selecionados (N)**: será aberta uma aba por empresa, com um número por empresa, priorizando o celular provável. Os links individuais continuam disponíveis para escolher o outro telefone.
- Permita **pop-ups e redirecionamentos** deste aplicativo no navegador. Se alguma abertura for bloqueada, ela continua selecionada; clique novamente depois de liberar os pop-ups. As abas que já abriram saem da seleção e não são repetidas pelo lote nesta lista.
- A seleção vale apenas para a página visível e é limpa quando a lista é atualizada (página, filtros, mensagem ou aparência). Contatos revisados, sem telefone e dados de demonstração ficam desativados.
- Cada aba usa a mesma rota de contato dos links individuais: valida CNPJ/telefone/revisão, atualiza a saudação e registra a abertura com ID idempotente. Selecionar, limpar ou ter uma abertura bloqueada não registra tentativa.
- Confira a mensagem e confirme o envio em cada conversa do WhatsApp. A abertura da aba não confirma entrega nem envio.

O controle do navegador pode apresentar abas ou janelas conforme suas preferências. O lote faz as aberturas diretamente no clique, sem temporizadores ou automação de envio.

Testes da seleção e dos bloqueios de pop-up simulados: com as dependências Python instaladas, execute `npm ci` e `npm test` em `tests/frontend` (Node 22). O workflow executa esses testes junto com a suíte Python. Esses testes de DOM não substituem a verificação das permissões de pop-up no navegador usado em produção.
