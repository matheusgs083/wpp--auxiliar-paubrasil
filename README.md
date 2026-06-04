# bot_api

API FastAPI para consulta de clientes no `dClientes` via Evolution API, com filtro por setor (`setor_vde`) vinculado ao numero do vendedor. A rota de planilha CSV/XLSX continua disponivel como apoio local.

Tutoriais principais:
- `TUTORIAL_CSV_DO_ZERO.md`
- `TUTORIAL_DOCKER_IMAGENS.md`
- `TUTORIAL_TESTE_REAL_APOS_CONEXAO.md`
- `TUTORIAL_TERMINAL_RBAC.md`

Resumos curtos:
- `resumos/README.md`
- `resumos/RESUMO_OPERACIONAL_DCLIENTES.md`
- `resumos/MODO_EVOLUTION_AGORA_META_DEPOIS.md`
- `resumos/CHECKLIST_FINAL_VPS.md`

## 1) Executar local

### Pre-requisitos
- Python 3.11+ (recomendado 3.13)

### Setup
```powershell
cd .\bot_api
python -m venv .venv
.\.venv\Scripts\python -m pip install -r .\requirements.txt
Copy-Item .env.example .env
```

### Rodar
```powershell
cd .\bot_api
.\.venv\Scripts\python .\run.py
```

API disponivel em `http://127.0.0.1:8080`.

## 2) Executar com Docker

```powershell
cd .\bot_api
Copy-Item .env.example .env
docker compose up --build -d
docker compose ps
```

O compose principal sobe:
- `postgres`
- `redis`
- `evolution-api`
- `bot_api`
- `bot_api_gateway`

Separacao aplicada:
- `bot_api` fica em bind local no host para uso privado
- `bot_api_gateway` expoe `/webhook/evolution`, `/webhook/meta` e um `/health` minimo

Logs uteis:
```powershell
docker compose logs -f bot_api
docker compose logs -f evolution-api
docker compose logs -f postgres
```

Parar:
```powershell
docker compose down
```

## 3) Variaveis de ambiente

Arquivo base: `.env.example`

Para VPS em producao:
- template dedicado: `.env.vps.example`

Variaveis principais:
- `APP_HOST` e `APP_PORT`: bind da API.
- `BOT_API_BIND_IP`: IP de bind da API real no host. Padrao recomendado: `127.0.0.1`.
- `EVOLUTION_API_BIND_IP`: IP de bind da Evolution API no host. Padrao recomendado: `127.0.0.1`.
- `PUBLIC_WEBHOOK_BIND_IP`: IP de bind do gateway publico. Padrao recomendado para VPS com proxy externo: `127.0.0.1`.
- `PUBLIC_WEBHOOK_PORT`: porta publicada pelo gateway de webhook.
- `PUBLIC_WEBHOOK_RATE_LIMIT_RPM`: limite por IP no gateway publico.
- `PUBLIC_META_WEBHOOK_RATE_LIMIT_RPM`: limite por IP do webhook da Meta exposto para a Evolution.
- `DOCKER_LOG_MAX_SIZE` e `DOCKER_LOG_MAX_FILE`: rotacao dos logs `json-file` dos containers.
- `API_AUTH_ENABLED`: exige autenticacao nas rotas `/api/*`.
- `API_AUTH_TOKENS`: lista de tokens da API separados por virgula.
- `EVOLUTION_*`: integracao com Evolution API.
- `EVOLUTION_SERVER_URL`: URL publica HTTPS da Evolution, usada na homologacao da Cloud API.
- `EVOLUTION_WA_BUSINESS_TOKEN_WEBHOOK`: token de validacao do webhook da Meta na Evolution.
- `EVOLUTION_WEBHOOK_API_KEYS`: chaves dedicadas para webhook quando a Evolution enviar `apikey` no payload.
- `EVOLUTION_LIST_PATH`: endpoint de lista interativa na Evolution.
- `EVOLUTION_BUTTONS_PATH`: endpoint de botoes na Evolution.
- `META_CLOUD_ENABLED`: habilita o recebimento direto da Meta Cloud API no bot.
- `META_CLOUD_API_VERSION`: versao da Graph API usada no envio.
- `META_CLOUD_PHONE_NUMBER_ID`: `phone_number_id` da Cloud API.
- `META_CLOUD_ACCESS_TOKEN`: token de envio da Cloud API.
- `META_CLOUD_VERIFY_TOKEN`: token de verificacao do webhook direto da Meta.
- `EVOLUTION_CLOUDAPI_HML_INSTANCE`: nome da instancia oficial de homologacao.
- `EVOLUTION_CLOUDAPI_NUMBER_ID`: Number ID da Meta.
- `EVOLUTION_CLOUDAPI_BUSINESS_ID`: Business ID da Meta.
- `EVOLUTION_CLOUDAPI_PERMANENT_TOKEN`: token permanente da Cloud API.
- `EVOLUTION_CLOUDAPI_INSTANCE_WEBHOOK_URL`: URL que a instancia da Evolution vai usar para chamar o bot.
- `UPSTREAM_META_HOST` e `UPSTREAM_META_PORT`: destino do `/webhook/meta` no gateway. Padrao atual: `evolution-api:8080`.
- `BOT_VERIFY_TOKEN`: token obrigatorio para aceitar chamadas no webhook.
- `ACCESS_CONTROL_ENABLED`: habilita bloqueio por numero no webhook (`1`/`0`).
- `ACCESS_DATABASE_URL`: conexao PostgreSQL usada pelo RBAC.
- `ACCESS_DB_SCHEMA`: schema exclusivo do `bot_api` dentro do Postgres.
- `ACCESS_PUBLIC_ENABLED`: se `1`, libera acesso sem validar numero.
- `ACCESS_DATABASE_TIMEOUT_SECONDS`: timeout de conexao com o Postgres do RBAC.
- `SECURITY_AUDIT_ENABLED`: habilita trilha de auditoria e throttle persistente no Postgres.
- `ADMIN_API_TOKEN`: token obrigatorio para rotas administrativas.
- `REPORTS_DATABASE_URL`: conexao PostgreSQL para carga e manutencao dos relatorios.
- `REPORTS_RUNTIME_DATABASE_URL`: conexao PostgreSQL de leitura usada pelo runtime do bot.
- `REPORTS_DB_SCHEMA`: schema dos relatorios importados.
- `BACKUP_OUTPUT_DIR`: pasta de saida dos backups operacionais.
- `BACKUP_RETENTION_DAYS`: dias de retencao dos backups.
- `BACKUP_ACCESS_SCHEMA`: schema salvo no backup operacional. Padrao recomendado: `bot_access`.
- `BACKUP_INCLUDE_VOLUMES`: se `1`, inclui volumes da Evolution. Padrao recomendado: `0`.
- `BACKUP_EXTERNAL_DIR`: segunda pasta de destino para espelhar o backup pronto.
- `FULL_BACKUP_OUTPUT_DIR`: pasta de saida dos backups completos com dump full do PostgreSQL.
- `FULL_BACKUP_RETENTION_COUNT`: quantidade de backups completos a manter.
- `FULL_BACKUP_RETENTION_DAYS`: retencao por idade dos backups completos. `0` desativa corte por data.
- `FULL_BACKUP_EXTERNAL_DIR`: segunda pasta de destino para espelhar o backup completo.
- `STACK_MONITOR_MIN_FREE_GB`: espaco livre minimo esperado na VPS.
- `STACK_ALERT_NUMBERS`: numeros que recebem alerta de falha do healthcheck.
- `STACK_ALERT_COOLDOWN_MINUTES`: intervalo minimo entre alertas repetidos.
- `STACK_ALERT_STATE_FILE`: arquivo local que guarda o estado do ultimo alerta.

Observacoes:
- O projeto carrega `.env` automaticamente no start.
- Em Docker, o compose força `APP_HOST=0.0.0.0`.
- Em Docker, o compose força `EVOLUTION_BASE_URL=http://evolution-api:8080`.
- Em Docker, o compose força `ACCESS_DATABASE_URL` e `REPORTS_DATABASE_URL` para `postgres`.
- O valor de `EVOLUTION_API_KEY` do `.env` e usado apenas na autenticacao da Evolution API.
- O webhook do bot aceita `x-bot-token` e, opcionalmente, chaves dedicadas em `EVOLUTION_WEBHOOK_API_KEYS`.
- Se usar o mesmo Postgres do Evolution, prefira schema separado para o `bot_api`.
- Em Docker, o compose injeta apenas as variaveis necessarias no `bot_api`.
- Em Docker, o runtime usa `ACCESS_DATABASE_URL` para `bot_access` e `REPORTS_RUNTIME_DATABASE_URL` para leitura de `reports`.

### PayIP

A integracao PayIP fica em `integrations/payip_client.py` e a fachada para uso pelo bot fica em `services/payip_payments_service.py`.

Configure no `.env`:

```env
PAYIP_BASE_URL=https://api.prod.payip.com.br
PAYIP_CLIENT_ID=payip-auth-portal
PAYIP_USERNAME=seu-email
PAYIP_PASSWORD=sua-senha
PAYIP_COMPANY_ID=bdfee22b-ac11-4355-909a-54bd348c87cc
PAYIP_COMPANY_IDS=3:bdfee22b-ac11-4355-909a-54bd348c87cc,4:aa11f5fe-38dd-4bf5-86e3-71d874cdc24c
PAYIP_COMPANY_TAX_IDS=3:20983885000101
PAYIP_TOKEN_CACHE_FILE=exports/payip/tokens.json
PAYIP_TIMEOUT_SECONDS=30
PAYIP_MFA_CODE=
```

`PAYIP_COMPANY_IDS` segue o mesmo codigo de filial usado no bot: `3` para Patos e `4` para Sume hoje. Para novas revendas, adicione no mesmo formato `filial:companyId`.
`PAYIP_COMPANY_TAX_IDS` usa o mesmo codigo de filial e informa o CNPJ da empresa para emissao de cobrancas.

Mecanica adotada:
- usa `access_token` cacheado enquanto estiver valido;
- renova com `refresh_token` antes de expirar;
- se o refresh falhar ou expirar, limpa o cache e exige novo bootstrap com MFA;
- nao grava tokens em log.
- o menu fica dentro de `Financeiro > Pagamentos PayIP` e e liberado para `financeiro` e `admin`;
- a emissao de cobranca exige confirmacao textual `CONFIRMAR` antes de chamar `POST /v1/payments`;
- na confirmacao da emissao, taxa e juros ficam com os padroes `R$ 3,92` e `10% ao dia`, mas podem ser alterados com `taxa 5,00`, `taxa 0`, `juros 8`, `juros 0` ou `vencimento 31/12/2026`;
- a nota fiscal e opcional na emissao e pode ser informada antes de confirmar com `nf 147478` ou removida com `sem nf`.
- o NB/identificador ERP tambem e opcional no payload de emissao; o bot ainda pode usar o NB para localizar o cliente, mas antes de confirmar voce pode alterar com `nb 16883` ou remover com `sem nb`.
- apos emitir uma cobranca PIX, o bot usa o `emv` retornado pela PayIP para enviar o copia e cola e gerar o QR Code localmente quando a API nao enviar `linkImage`; nao depende do `GET /v1/payments/{id}` para montar o PIX.
- a busca por valor e dia usa `paidDateStart`/`paidDateEnd` no `GET /v1/payments` e valida localmente o JSON por `paidDate` e `amountPaid`, com tolerancia padrao de `R$ 0,05`; atalhos: `valor 3 0,99 13/04/2026` ou `valor 3 0,99 13/04/2026 tolerancia 0,10`.

`PAYIP_MFA_CODE` deve ser usado apenas para iniciar uma sessao manualmente. Depois disso, o bot deve operar com `refresh_token` e cache.

Bootstrap manual do cache:

```powershell
.\venv\Scripts\python.exe .\ops\payip_bootstrap_session.py --mfa-code 123456
```

## 4) Rotas

- `GET /health` (detalhado, apenas na API privada)
- `GET /api/dclientes/search?number=5583991964911&fantasia=SKINA%20BAR`
- `GET /api/access/check?number=5585999990001&area=inadimplencia`
- `GET /api/admin/access/users`
- `POST /api/admin/access/users`
- `GET /api/admin/access/roles`
- `POST /api/admin/access/roles`
- `GET /api/admin/access/permissions`
- `POST /api/admin/access/seed`
- `POST /webhook/evolution`
- `GET|POST /webhook/meta`

As rotas `/api/*` exigem autenticacao por token quando `API_AUTH_ENABLED=1`.
Header aceito:
- `Authorization: Bearer <token>`
- `x-api-token: <token>`

As rotas `/api/admin/*` continuam exigindo tambem `x-admin-token`.
Se `ADMIN_API_TOKEN` nao estiver configurado, essas rotas respondem `503`.
O `/webhook/evolution` exige `x-bot-token`.
No gateway publico, `/api/*` nao e exposto.
No gateway publico, `/health` responde apenas `ok`.
O `/webhook/meta` pode funcionar em dois modos:
- `UPSTREAM_META_HOST=evolution-api`: a Meta atinge a Evolution
- `UPSTREAM_META_HOST=bot_api`: a Meta atinge o bot diretamente

Exemplo de busca local na planilha:
```text
```

Exemplo de busca no `dClientes` filtrando pelo setor do numero informado:
```text
/api/dclientes/search?number=5583991964911&filial=7&cod_pdv=795
```

Exemplo com autenticacao:
```powershell
Invoke-WebRequest `
  -Uri "http://127.0.0.1:8080/api/dclientes/search?number=5583991964911&filial=7&cod_pdv=795" `
  -Headers @{ Authorization = "Bearer SEU_TOKEN_API" }
```

Exemplo de webhook:
```powershell
Invoke-WebRequest `
  -Uri "http://127.0.0.1:8090/webhook/evolution" `
  -Method Post `
  -ContentType "application/json" `
  -Headers @{ "x-bot-token" = "SEU_TOKEN_WEBHOOK" } `
  -Body "{}"
```

Arquivos base em `data/dClientes`:
- `data/dClientes/clientes.csv`
- `data/dClientes/dClientes.csv`

## 5) Carga diaria de relatorios CSV

Base inicial preparada para `dClientes`:
- script de carga: `ops/import_dclientes.py`
- schema padrao: `reports`

Organizacao recomendada:
- manter um subdiretorio por relatorio dentro de `data/`
- `dClientes` ja foi separado em `data/dClientes/`

Analise sem importar:
```powershell
.\.venv\Scripts\python .\ops\import_dclientes.py
```

Validacao estrutural dos tres relatórios antes da carga:
```powershell
.\.venv\Scripts\python .\ops\validate_report_csvs.py
```

Importacao para PostgreSQL:
```powershell
.\.venv\Scripts\python .\ops\import_dclientes.py --import-db
```

Normalizacao de codigos no banco e refresh da view mais recente:
```powershell
.\.venv\Scripts\python .\ops\normalize_database_codes.py --refresh-view
```

Fixando a data de referencia do lote:
```powershell
.\.venv\Scripts\python .\ops\import_dclientes.py --import-db --reference-date 2026-03-25
```

## 6) Controle de acesso por numero

O webhook usa o numero do remetente para autorizar acesso por area, consultando o PostgreSQL.

Schema bootstrapado no banco:
- `users`
- `roles`
- `permissions`
- `user_roles`
- `role_permissions`
- `user_sectors`

Seed padrao:
- `admin` -> `*`
- `financeiro` -> `inadimplencia`, `comodato`, `cliente`, `conhecimento`
- `gerente_vendas` -> `inadimplencia`, `comodato`, `cliente`, `conhecimento`
- `diretor_comercial` -> `inadimplencia`, `comodato`, `cliente`, `conhecimento`
- `vendedor` -> `inadimplencia`, `comodato`, `cliente`

Fluxo recomendado:
1. Configurar `ACCESS_DATABASE_URL`, `REPORTS_DATABASE_URL` e `REPORTS_RUNTIME_DATABASE_URL`.
2. Subir a API.
3. Chamar `POST /api/admin/access/seed`.
4. Cadastrar numeros em `POST /api/admin/access/users`.
5. Ajustar cargos/permissoes em `POST /api/admin/access/roles`.

Quando um numero ja possui a role `admin`, ele tambem pode cadastrar outros usuarios diretamente pelo WhatsApp:
- `menu` -> `Admin`
- informar o numero
- escolher `Vendedor`, `Gerente de Vendas`, `Diretor Comercial`, `Financeiro` ou `Admin`
- informar setor(es) para vendedor ou GV(s) para gerente/diretor
- confirmar

Envie sempre o header `x-admin-token` nas rotas administrativas.
Se `API_AUTH_ENABLED=1`, envie tambem `Authorization: Bearer <token>` ou `x-api-token`.

Terminal local para administrar RBAC sem usar HTTP:

```powershell
.\.venv\Scripts\python .\ops\access_cli.py shell
```

Exemplo direto:

```powershell
.\.venv\Scripts\python .\ops\access_cli.py user-set 5583991964911 --name "Teste Real" --role vendedor --sector 206
```

Modelo recomendado de privilegio:
- `ACCESS_DATABASE_URL`: usuario com escrita apenas em `bot_access`
- `REPORTS_RUNTIME_DATABASE_URL`: usuario somente leitura em `reports`
- `REPORTS_DATABASE_URL`: usuario de manutencao/importacao dos relatorios

## 7) Homologacao Cloud API via Evolution

O projeto ja pode ser preparado para migrar o canal para a Cloud API oficial sem reescrever o bot.

Premissas:
- a Meta chama a Evolution em `/webhook/meta`
- a Evolution continua chamando o bot em `/webhook/evolution`
- o bot continua enviando mensagens pela Evolution

Checklist inicial:

```powershell
.\.venv\Scripts\python .\ops\evolution_cloudapi_homologation.py check
.\.venv\Scripts\python .\ops\evolution_cloudapi_homologation.py show-meta-webhook
```

Criacao da instancia oficial em homologacao:

```powershell
.\.venv\Scripts\python .\ops\evolution_cloudapi_homologation.py create-instance --dry-run
.\.venv\Scripts\python .\ops\evolution_cloudapi_homologation.py create-instance
```

Webhook da instancia apontando para o bot:

```powershell
.\.venv\Scripts\python .\ops\evolution_cloudapi_homologation.py set-instance-webhook --dry-run
.\.venv\Scripts\python .\ops\evolution_cloudapi_homologation.py set-instance-webhook
```

Observacoes:
- mantenha a instancia atual em paralelo ate a homologacao fechar
- o gateway publico precisa expor `/webhook/meta` com HTTPS para a Meta
- homologue antes como a Evolution oficial vai autenticar o `/webhook/evolution` no bot

Replay local de payload salvo para homologacao:

```powershell
.\.venv\Scripts\python .\ops\replay_whatsapp_payload.py evolution .\payload_evolution.json
.\.venv\Scripts\python .\ops\replay_whatsapp_payload.py meta .\payload_meta.json
```

## 8) Producao

Backup operacional:

```powershell
.\.venv\Scripts\python .\ops\backup_stack.py --dry-run
.\.venv\Scripts\python .\ops\backup_stack.py
```

O backup padrao salva apenas o schema `bot_access`, que contem:
- usuarios
- cargos e permissoes
- logs de auditoria
- controle de cooldown de respostas negadas

Se `BACKUP_EXTERNAL_DIR` estiver preenchido, o backup pronto tambem e espelhado para uma segunda pasta.

Se um dia voce quiser levar tambem os volumes da Evolution:

```powershell
.\.venv\Scripts\python .\ops\backup_stack.py --include-volumes
```

Healthcheck operacional:

```powershell
.\.venv\Scripts\python .\ops\check_stack_health.py
.\.venv\Scripts\python .\ops\check_stack_health.py --preview-alert
```

Na VPS, a ideia pratica fica assim:
- rodar `backup_stack.py` por `cron` uma vez por dia
- rodar `check_stack_health.py` a cada poucos minutos
- manter a rotacao de logs do Docker ativa pelo proprio `docker-compose.yml`
- preencher `STACK_ALERT_NUMBERS` com os numeros que devem receber aviso

Quando for subir para VPS:
1. Copiar o projeto para o servidor.
2. Criar `.env` de producao.
3. Subir com `docker compose up --build -d`.
4. Expor via proxy reverso com HTTPS.

Sugestoes:
- manter `restart: unless-stopped`
- usar dominio com TLS
- manter `BOT_VERIFY_TOKEN` obrigatorio e girado antes da producao
- proteger rotas administrativas com `ADMIN_API_TOKEN` configurado e girado
- manter `API_AUTH_ENABLED=1` e girar os tokens antes da producao
- publicar externamente apenas o `bot_api_gateway`
- bindar o `bot_api_gateway` em `127.0.0.1` quando houver outro proxy TLS na frente
- manter `evolution-api` em bind local e nao publicar para internet
- deixar a porta privada do `bot_api` acessivel so localmente, VPN ou rede interna
