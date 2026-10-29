# Arquitetura de produção

- Interface: Streamlit, com gate de autenticação antes da base e dos componentes privados.
- Autenticação: Supabase Auth; senha e códigos de confirmação/recuperação por e-mail. Sessões e refresh tokens ficam na sessão do servidor, sem cache global.
- Autorização: `app_accounts` controla perfil, situação e validade. Cadastro não concede acesso. O primeiro administrador é ativado por operação SQL fora do app.
- Dados privados: Data API com publishable key e JWT do usuário. RLS em todas as tabelas expostas. `user_id` faz parte das chaves de revisões e tentativas; `auth.uid()` define o dono. Nenhuma chave administrativa no processo web.
- Banco: `app_reviews`, `app_contact_attempts`, `app_contact_state`, `app_preferences`, `app_accounts`, `app_data_requests`. Helpers privilegiados ficam em `app_private`, com search_path fixo e EXECUTE restrito. Sessões revogadas deixam de acessar dados mesmo antes do vencimento do JWT.
- Base pública: Parquet compartilhado em cache. GitHub Actions executa ETL e publica snapshots; só administradores acionam cargas pelo app. Reservas e quota ficam no PostgreSQL. O volume Docker guarda snapshots baixados.
- Contatos: links diretos preservados. Abrir WhatsApp não confirma envio. O usuário marca explicitamente os contatos tratados, que somem apenas de suas próximas listas.
- Infra: container sem root, Caddy com TLS/WebSockets e domínio próprio, checks de saúde, CI com testes Python/DOM/RLS, imagem GHCR com SHA e deploy SSH com rollback da imagem.
- Operação: migração aditiva, importador do legado com dono explícito e simulação, backups criptografados e ensaio de recuperação documentado.

O modo de desenvolvimento sem Auth preserva o protótipo SQLite/CSV/GitHub abaixo. É bloqueado quando `APP_ENV=production`. Ele não deve ser oferecido a clientes. Pagamentos e liberação por assinatura não fazem parte desta versão.

O procedimento operacional está em [docs/DEPLOY.md](docs/DEPLOY.md).

---

## Referência do protótipo legado

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
