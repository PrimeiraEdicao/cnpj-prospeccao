# Prospecção CNPJ — pipeline único (Receita + Streamlit)

## Produção com login e domínio próprio

O aplicativo usa Supabase Auth e histórico individual protegido por RLS. Cadastros novos aguardam liberação; administradores podem definir validade e bloquear contas. **Main file path: `app.py`.** Veja [o guia de implantação](docs/DEPLOY.md) para Secrets do Streamlit, migrações, primeiro administrador, importação do legado, Docker/Caddy, CI, domínio e backups.

A configuração padrão exige login. Para executar o protótipo local sem autenticação, copie `.env.example` para `.env` (`APP_ENV=development`, `AUTH_MODE=disabled`). Não use esse modo em produção. As instruções de histórico compartilhado no GitHub abaixo se aplicam apenas a esse modo legado; com Supabase, o token do GitHub serve somente às cargas da Receita.


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
10. Os links abrem diretamente o WhatsApp Web. Após abordar as empresas, marque as selecionadas como contatadas para salvá-las e retirá-las das próximas listas.

## Escopo padrão

A base atual é de **Governador Valadares/MG**, código Receita `4553`. A configuração persistente está em `config/scopes.json` e aceita vários municípios de várias UFs. O ETL percorre os ZIPs nacionais uma vez e retém os pares UF/município configurados.

Pela interface, abra **Cidades e atualização da Receita**, selecione o estado e o nome do município e clique em **Incluir cidade e atualizar base**. O aplicativo converte a seleção para o código Receita e solicita a carga em segundo plano. É necessário configurar os Secrets descritos na seção de hospedagem abaixo. Use **Verificar andamento** e, quando concluído, **Carregar última base pronta**. A base atual continua disponível enquanto a nova é preparada.

Como alternativa administrativa, abra **Actions → Atualizar base Receita CNPJ → Run workflow** e preencha `adicionar_uf` e `adicionar_municipios`. Os códigos Receita têm **quatro dígitos**; não use o código IBGE de sete dígitos. É possível informar vários códigos da mesma UF separados por vírgula. O campo `nome_cidade` é opcional, e o nome da tabela Municípios da Receita prevalece. Deixe os campos vazios para atualizar apenas o escopo existente.

A cidade será acrescentada a `config/scopes.json` **após a carga concluir com sucesso**, preservando Valadares e as demais cidades. As atualizações semestrais usam essa configuração. O filtro **Cidade / UF** mostra as cidades já carregadas; o painel **Cidades e atualização da Receita** permite incluir uma nova. O catálogo `config/municipalities.csv` vem da [tabela oficial TOM/IBGE da Receita](https://www.gov.br/receitafederal/dados/municipios.csv/view), consultada em 28/10/2026 (5.570 municípios brasileiros). Atualize esse catálogo com `python -m scripts.update_city_catalog` quando a tabela oficial mudar.

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

Para visualizar a interface local sem login, copie primeiro `.env.example` para `.env`, instale as dependências e execute `streamlit run app.py`. Quando a base real não existe, o app abre em **modo de demonstração**, com empresas fictícias, filtros e prévia da mensagem. Os contatos ficam desativados e o banco de histórico não é usado. Após a geração do Parquet, o app usa a base real automaticamente no próximo carregamento.

## Abrir no GitHub Codespaces

No repositório, abra **Code → Codespaces → Create codespace on main**. Os novos ambientes usam Python 3.12 através de `.devcontainer/devcontainer.json`.

No terminal do Codespaces, execute:

```bash
git pull origin main
# Apenas para desenvolvimento local sem login, se .env ainda não existir:
cp -n .env.example .env
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

A saudação usa `America/Sao_Paulo`: **Bom dia** das 6h às 11h59, **Boa tarde** das 12h às 17h59 e **Boa noite** das 18h às 5h59. Na tabela, ela é recalculada no clique, inclusive se a lista tiver sido carregada antes da mudança de horário. A fila e a revisão individual usam a mensagem da prévia atual. É possível escolher uma saudação personalizada. O texto padrão inclui **Tudo bem?**:

```text
{saudacao}! Tudo bem? Sou {remetente}. Nesse contato falo com {nome}?
```

A apresentação e a mensagem são editáveis no app. `CONTACT_SENDER` e `CONTACT_TEMPLATE` no `.env` ou Secrets definem os padrões para outros projetos. O nome pode ser revisado individualmente; sem nome identificado, usa-se “a pessoa responsável”.

Na **Fila de contatos**, selecione empresas ou adicione a página inteira. Os links abrem diretamente o WhatsApp Web. Use **Próximo contato** para avançar ou **Marcar contato da fila como contatado** para confirmar a abordagem e retirar a empresa da prospecção. A fila fica na sessão atual e acompanha os filtros.

**Abrir WhatsApps selecionados** navega diretamente para `https://web.whatsapp.com/send`, sem abrir outra sessão Streamlit ou exigir o botão “Abrir WhatsApp manualmente”. Após as conversas, clique em **Marcar selecionadas como contatadas**. Essa confirmação é validada no servidor contra os CNPJs da página atual e salva com status `contatado` em `company_reviews`. Ela não inventa envio ou entrega. As confirmações retiram as empresas das próximas listas e se mantêm em novas cargas da Receita. O filtro **Contatadas** permite consultá-las, com links desativados. As antigas aberturas continuam no banco, mas a lista padrão **Não contatadas** depende das confirmações e revisões, não de simples cliques. Links antigos com `?contact=` mantêm compatibilidade; os novos não usam esse redirecionamento.

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

O histórico legado, importado somente para o dono pelo procedimento em [docs/DEPLOY.md](docs/DEPLOY.md), inclui `config/reviewed_cnpjs.csv`. Essa lista contém os **1.544 CNPJs únicos** das 50 planilhas enviadas em `Empresas filtradas.zip`: 1.634 linhas válidas e 90 repetições, sem CNPJs inválidos. Como as planilhas não distinguem contato de descarte, o lote está marcado como **Revisado anteriormente — contato ou descarte**. O TXT de memória contém telefones e não foi interpretado como CNPJ. A lista versiona somente CNPJ, motivo e arquivo de origem; nomes, telefones e e-mails das planilhas não são publicados.

**Ocultar empresas já revisadas** vem ativado por padrão, independentemente do filtro de histórico. A base da Receita é preservada: a lista é aplicada por CNPJ completo de 14 dígitos a cada carregamento, inclusive quando uma empresa ausente aparece numa nova competência ou uma nova cidade é incluída. Desmarque a opção para consultar esses registros, respeitando os demais filtros. Links de contato ficam desativados, a fila remove empresas revisadas e links antigos não registram abertura nem redirecionam para o WhatsApp.

Para novas listas, abra **Importar empresas já revisadas** na barra lateral. Envie ZIP com planilhas, Excel `.xlsx`, CSV com coluna `CNPJ` ou TXT com um CNPJ por linha. Confira os totais e selecione **Revisado anteriormente**, **Já contatado** ou **Fora do perfil**, conforme o lote. Clique em **Importar CNPJs revisados**. Os dígitos verificadores são validados; duplicatas não criam novos registros. A importação não altera o número de aberturas nem inventa mensagem, telefone ou data de envio. A data salva corresponde à importação da revisão.

Novas importações e confirmações ficam em `app_reviews` no Supabase, vinculadas à conta. Use **Baixar lista de revisão** para exportar seus registros. Em produção, os CSVs versionados não são aplicados automaticamente às contas. No modo legado de desenvolvimento, continua sendo usada a tabela `company_reviews` via `DATABASE_URL` e a união com os CSVs globais.

Para incorporar uma lista ao protótipo legado de desenvolvimento (em produção, importe pela interface da conta):

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

Em produção, o histórico está no PostgreSQL do Supabase, com RLS e JWT do usuário, e sobrevive às reinicializações do Streamlit. As credenciais e a migração estão em [docs/DEPLOY.md](docs/DEPLOY.md). `DATABASE_URL` é usado apenas no modo legado de desenvolvimento, com SQLite ou SQLAlchemy; não habilita isolamento de usuários por si só. A migração do legado exige UUID e e-mail do dono e não compartilha seu histórico com clientes novos.

## Observações de escala

Este projeto foi desenhado para processar a base nacional da Receita em streaming, mas **persistir somente o recorte geográfico necessário**. Não é recomendável colocar a base nacional bruta no GitHub ou carregá-la inteira no Streamlit.

Se futuramente o produto precisar atender várias cidades/usuários, a evolução natural é:

- ETL nacional em máquina/serviço com mais disco;
- Parquet particionado por UF/município em object storage;
- consulta paginada da base pública no servidor;
- API/FastAPI ou consultas DuckDB/Polars sobre as partições.

## Testes

```bash
python -m pytest -q
```


### Abrir WhatsApps em lote

1. Escolha 20, 50 ou 100 empresas por página e marque as que deseja abordar, ou use **Selecionar esta página**.
2. Clique em **Abrir WhatsApps selecionados (N)** para abrir uma aba por empresa, priorizando o celular provável. Os links individuais permitem escolher outro telefone.
3. Permita pop-ups deste aplicativo no navegador. O botão repete somente as aberturas bloqueadas; não repete as que já abriram nesta lista.
4. Depois das conversas, desmarque as empresas que não foram abordadas e clique em **Marcar selecionadas como contatadas**. As selecionadas ficam marcadas após abrir as abas justamente para essa confirmação.
5. O aplicativo salva as confirmações e atualiza a lista automaticamente. Empresas revisadas/contatadas, registros sem telefone e dados fictícios não podem receber contato pela tabela.

A seleção vale apenas para a página visível e é limpa ao atualizar a lista. Aberturas não marcam contato, e a confirmação manual não é um comprovante de envio/entrega. O controle do navegador pode apresentar abas ou janelas conforme suas preferências. Não há automação de envio.

Testes de DOM e do protocolo do componente: `npm ci` e `npm test` em `tests/frontend` (Node 22), após instalar as dependências Python. O workflow executa esses testes junto com a suíte Python. Os testes simulam pop-ups; a permissão real deve ser verificada no navegador usado.

## Publicar no Streamlit Community Cloud

No [Streamlit Community Cloud](https://share.streamlit.io/), entre na sua conta e escolha **Create app / Deploy a public app from GitHub** (ou a opção de repositório privado disponível na sua conta). Configure:

| Campo | Valor |
| --- | --- |
| Repository | `PrimeiraEdicao/cnpj-prospeccao` |
| Branch | `main` |
| Main file path | `app.py` |
| Python | `3.12` em Advanced settings |

A base `data/companies.parquet` já faz parte do repositório. A publicação não precisa rodar a carga nacional novamente. O aplicativo usa `requirements.txt`; Node/npm são usados apenas pelos testes e não são necessários para executar o app.

Em **Advanced settings → Secrets**, use [.streamlit/secrets.toml.example](.streamlit/secrets.toml.example) e siga [docs/DEPLOY.md](docs/DEPLOY.md). O login, a confirmação de e-mail, as migrações e a ativação do primeiro administrador precisam estar configurados antes do acesso à base. `GITHUB_DATA_TOKEN` é opcional para cargas administrativas; o histórico usa o Supabase.

Para um domínio próprio, use o Compose com Caddy e as instruções do mesmo guia. As etapas de DNS, SMTP, Secrets, primeiro acesso, backup e teste de recuperação exigem os dados reais da sua infraestrutura.
