# Produção: domínio próprio, Supabase e contas individuais

Esta versão mantém a interface Streamlit e a base pública Parquet. Supabase Auth identifica cada usuário, e PostgreSQL guarda as revisões, confirmações e preferências com RLS. Novos cadastros ficam **pendentes** até um administrador liberar o acesso. Não há cobrança automática nesta entrega.

## 1. Preparar o Supabase

Use um projeto exclusivo para esta aplicação, inicialmente de homologação. O aplicativo usa apenas **Project URL** e **publishable key**, encontradas no painel do projeto, em **Connect / API Keys**. A antiga chave `anon` também é aceita. Não coloque `service_role`, `sb_secret_...`, senha SQL ou chave de assinatura JWT no aplicativo.

Instale/use a CLI Supabase 2.122.0. Na raiz do repositório:

```bash
npx --yes supabase@2.122.0 login
npx --yes supabase@2.122.0 link --project-ref SEU_PROJECT_REF
npx --yes supabase@2.122.0 db push --dry-run --skip-vault
npx --yes supabase@2.122.0 db push --skip-vault
```

A CLI solicitará as credenciais fora do código. Confira o projeto vinculado antes de aplicar. Em projetos existentes, reconcilie primeiro o histórico remoto de migrações; não use `--include-all` ou `db reset` em produção. A migração é aditiva: não apaga tabelas antigas, CSVs nem históricos.

Em **Authentication**:

- Habilite login por e-mail/senha e confirmação obrigatória de e-mail; desabilite login anônimo. Senhas: mínimo 12 caracteres.
- Configure **Site URL** com `https://prospeccao.seudominio.com.br`. Não use curingas nos redirecionamentos.
- Em **Email Templates**, substitua **Confirm signup** e **Reset password** pelos arquivos de `supabase/templates/`. Ambos precisam exibir `{{ .Token }}`. A interface pede o código de seis dígitos; não depende de links com sessão na URL.
- Configure um SMTP de produção e remetente verificado. O remetente padrão limita destinatários/envios; projetos gratuitos novos podem impedir personalização dos templates sem SMTP próprio. Teste confirmação e recuperação com um destinatário real antes de liberar cadastros.
- Use validade de OTP de 600 segundos e limites de envio adequados. Mantenha rotação de refresh tokens habilitada.

O `supabase/config.toml` configura o ambiente local; ele **não configura automaticamente o Auth do projeto hospedado** com `db push`. Faça as configurações acima no painel. Exponha apenas o schema `public` na Data API, nunca `app_private`. As migrações dão os grants explicitamente. Não desabilite RLS para resolver erros.

## 2. Configurar o aplicativo

Para Streamlit Community Cloud: abra o aplicativo → **Manage app → Settings → Secrets** e copie o modelo `.streamlit/secrets.toml.example`. São Secrets do **aplicativo Streamlit**, não a tela Settings/Secrets do repositório GitHub.

```toml
APP_ENV = "production"
AUTH_MODE = "supabase"
SUPABASE_URL = "https://SEU-PROJETO.supabase.co"
SUPABASE_PUBLISHABLE_KEY = "sb_publishable_PREENCHA"
ALLOW_SIGNUP = "true"
```

O **Main file path** continua `app.py`, na branch `main` após integrar o PR. Enquanto as credenciais não estiverem configuradas, a tela de configuração bloqueia o carregamento dos dados. Para domínio próprio com controle de infraestrutura, use o servidor descrito na etapa 5.

`GITHUB_DATA_TOKEN` é opcional e passa a servir apenas para as cargas da Receita: token fine-grained restrito a este repositório, **Actions: read/write** e **Contents: read**, mais Metadata automático. O workflow usa seu próprio `GITHUB_TOKEN` para publicar a base. Somente administradores podem solicitar cargas ou sincronizar arquivos pela interface. O histórico dos usuários nunca é escrito no GitHub em modo Supabase.

O login permanece no servidor durante a sessão Streamlit. Ao recarregar completamente a página, fechar a sessão WebSocket ou reiniciar o servidor, é necessário entrar novamente. O histórico e as preferências permanecem no banco. Uma sessão aberta renova seu token quando necessário; Sair limpa seleção, formulários e dados privados da memória da sessão.

## 3. Ativar o primeiro administrador

Crie sua conta na interface e confirme o código por e-mail. Copie o UUID em **Authentication → Users**. Em um terminal de operação, fora do container web, defina `MIGRATIONS_DATABASE_URL` com a conexão PostgreSQL **direta ou pooler em modo sessão** do projeto e TLS. Não use pooler em modo transação para dumps/migrações. Não comite essa variável nem a exponha nos Secrets do app.

```bash
python scripts/bootstrap_admin.py --user-id SEU_UUID --email seu@email.com
python scripts/bootstrap_admin.py --user-id SEU_UUID --email seu@email.com --apply
```

A primeira chamada só verifica a conta. A segunda libera seu acesso como administrador. O UUID e o e-mail confirmado devem coincidir; o script recusa substituir outro administrador ativo. Depois, use **Administrar acessos** na barra lateral para liberar/bloquear outras contas, mudar o perfil e definir validade. Não pode bloquear/rebaixar sua própria conta por essa tela. Administradores gerenciam acessos e a base pública; não ganham permissão para consultar os contatos privados de outras contas pela Data API.

## 4. Importar o histórico anterior do dono

Em produção, os CSVs globais e o SQLite anterior deixam de ser aplicados a todas as contas. A migração exige um dono explícito; usuários novos começam com histórico vazio. Guarde uma cópia do banco legado antes de migrar. Pause as confirmações no aplicativo antigo durante a transferência.

```bash
python scripts/migrate_legacy_history.py --user-id SEU_UUID --email seu@email.com
python scripts/migrate_legacy_history.py --user-id SEU_UUID --email seu@email.com --apply
```

Use `--sqlite /caminho/contact_state.db` se o banco antigo estiver fora de `data/`. Se o legado usa PostgreSQL, exporte os dados antes e faça uma migração específica; este importador lê os dois CSVs versionados e SQLite. Sem `--apply`, nada é gravado. Com `--apply`, a transação importa revisões, tentativas e estados **somente para esse UUID**, preserva datas disponíveis e não duplica chaves. Registros já existentes no destino prevalecem; o relatório mostra totais de origem, não quantidade de novas inserções. Arquivos/tabelas originais não são alterados. Uma importação de revisões não inventa tentativas ou mensagens enviadas.

Confirme com duas contas de teste que a lista importada desaparece apenas para o dono. Depois, encerre as escritas do protótipo e remova o token antigo com Contents:write se não for mais usado.

## 5. Servidor com domínio e HTTPS

Requisitos: Linux com Docker Engine e Compose v2, DNS sob seu controle, portas 80/443 abertas, saída HTTPS para Supabase/GitHub e espaço para a base Parquet. Não abra 8501 nem PostgreSQL publicamente. Dimensione memória conforme o tamanho da base; cada sessão mantém seus filtros, enquanto o Parquet é compartilhado em cache.

1. Aponte o DNS **A** do subdomínio para o IP do servidor. Configure AAAA somente se o IPv6 estiver funcionando. Evite um proxy DNS durante a emissão inicial do certificado.
2. Clone o repositório em `/opt/cnpj-prospeccao` e integre esta versão.
3. Copie `.env.production.example` para `.env.production`, preencha domínio/URL/chave e restrinja as permissões: `chmod 600 .env.production`.
4. Construa e inicie:

```bash
docker compose --env-file .env.production config --quiet
docker compose --env-file .env.production build app
docker compose --env-file .env.production up -d --wait
docker compose --env-file .env.production ps
```

Caddy emite/renova certificados e encaminha WebSockets do Streamlit. O app roda sem root, sem porta pública, com sistema de arquivos somente leitura. O volume `snapshots` guarda cargas baixadas; uma imagem nova também pode fornecer uma base pública mais recente. O histórico fica no Supabase e não depende desse volume. Nunca execute `down -v` sem ter avaliado os volumes/certificados.

Verifique `https://SEU_DOMINIO/_stcore/health`, login, logout, e-mail, acesso pendente/vencido e confirmação de contatos. O health check mede o processo; não atesta que as credenciais/Supabase/DNS estejam corretos. Não abra o cadastro comercial antes de concluir esses testes.

## 6. CI e implantação automatizada

O workflow **Validar aplicação e imagem** executa Python, DOM, testes RLS em PostgreSQL 17 e construção/smoke do container. Em `main`, publica `ghcr.io/primeiraedicao/cnpj-prospeccao:sha-SHA_COMPLETO`. PRs validam sem publicar. A primeira publicação GHCR depende da permissão Packages:write do `GITHUB_TOKEN` e das configurações da organização.

Para consumir uma imagem privada, faça `docker login ghcr.io` no servidor com credencial de **leitura de pacotes**, sem colocar esse token no app. Prepare o checkout/Compose no servidor; atualizações de arquivos de infraestrutura exigem atualizar esse checkout também.

Em **GitHub → Settings → Environments → production**, configure:

| Secret | Valor |
|---|---|
| `DEPLOY_HOST` | IP ou hostname do servidor |
| `DEPLOY_USER` | Usuário SSH com acesso ao Docker e ao checkout |
| `DEPLOY_SSH_KEY` | Chave privada dedicada à implantação |
| `DEPLOY_KNOWN_HOSTS` | Linha da chave pública do host, verificada por um canal confiável |

Não use `StrictHostKeyChecking=no`. Execute **Actions → Implantar no servidor → Run workflow**, informando o SHA completo de uma imagem aprovada. O script baixa a imagem, aguarda saúde e tenta restaurar a imagem anterior se falhar. Não reverte dados/migrações do banco. Migrações futuras devem ser compatíveis com a versão anterior durante a troca. A primeira implantação não terá uma imagem anterior para restauração.

## 7. Backups e recuperação

Ative backups/PITR do Supabase conforme o plano e confirme a retenção. O histórico é dado operacional: o backup CSV de cada usuário ajuda, mas não substitui backup do banco inteiro com Auth e permissões. Revise os **Security/Performance Advisors** do Supabase após aplicar a migração.

Como cópia adicional, `scripts/backup_database.py` usa `pg_dump` + `age`, sem arquivo de dump em texto claro. Instale clientes PostgreSQL compatíveis com a versão do servidor (iguais ou mais novos) e `age`. Crie a chave age em local separado; apenas a chave **pública** de criptografia vai ao servidor de backup. Guarde a identidade privada em cofre/offline. O dump integral contém dados de autenticação: mantenha criptografado e restrito.

Defina, em arquivo de operação restrito:

```dotenv
BACKUP_DATABASE_URL=postgresql://USUARIO:SENHA@HOST:5432/postgres?sslmode=require
BACKUP_AGE_RECIPIENT=age1SUA_CHAVE_PUBLICA
```

```bash
python3 scripts/backup_database.py backup --directory /var/backups/cnpj
```

Os modelos systemd `infra/cnpj-backup.service` e `.timer` agendam diariamente às 03:00 UTC. Antes de ativá-los, crie o usuário de sistema `cnpj-backup`, diretório `/var/backups/cnpj` com dono correspondente e `/etc/cnpj-prospeccao/backup.env` modo 600, acessível ao serviço. Instale as unidades em `/etc/systemd/system/` e use `systemctl enable --now cnpj-backup.timer`. Monitore falhas no journal; um timer sozinho não alerta o operador. Copie regularmente os arquivos `.age` e `.sha256` para armazenamento externo com retenção definida. Esta entrega não cria um bucket externo nem contrata PITR.

Faça um ensaio de restauração **fora da produção**, em banco isolado e vazio, com extensões e roles Supabase necessárias previamente preparadas. Um dump completo não deve ser carregado por cima dos schemas gerenciados de um projeto Supabase novo; para restaurar em Supabase hospedado, siga o procedimento oficial de migração/restauração compatível com seu projeto/plano.

```bash
python3 scripts/backup_database.py restore --file /backup/ARQUIVO.dump.age \
  --identity /cofre/backup.agekey --confirm-database NOME_EXATO_DO_BANCO
```

A conexão de destino vem de `RESTORE_DATABASE_URL`. O script exige checksum, descriptografa em fluxo e usa `pg_restore --single-transaction --exit-on-error`, sem `--clean`. Valide totais, login, RLS e funções depois. Uma recuperação completa inclui a configuração do Auth, SMTP, DNS e segredos externos, que devem ter seu próprio registro seguro. Nenhum backup/restauração real é validado apenas pelos testes de código.

## Limites desta entrega

A liberação e validade de acesso são manuais; pagamentos, assinatura automática e multiempresa ficam para outra etapa. Atualização da Receita continua no GitHub Actions; há uma reserva global no banco, no máximo uma carga simultânea e três solicitações por dia UTC feitas pelo app. Isso não controla execuções iniciadas fora do app. Se o volume crescer, mova o ETL para um worker próprio e a base pública para storage/consulta paginada.

As integrações de e-mail do Auth têm limites por IP; chamadas do Streamlit saem do servidor. Ajuste limites e monitore abuso antes de abrir o cadastro ao público. Não habilite CAPTCHA no Supabase sem integrar seu desafio na interface. Não há faturamento, painel de métricas externo ou disponibilidade gerenciada contratada por este código.

Referências: [Supabase Auth](https://supabase.com/docs/guides/auth), [RLS](https://supabase.com/docs/guides/database/postgres/row-level-security), [e-mails](https://supabase.com/docs/guides/auth/auth-email-templates), [backups](https://supabase.com/docs/guides/platform/backups), [Caddy](https://caddyserver.com/docs/automatic-https).
