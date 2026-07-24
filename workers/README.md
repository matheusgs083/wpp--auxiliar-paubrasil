# Promax Windows Worker

Este worker roda no host Windows porque o driver Promax depende do ambiente
local. A API e os demais servicos continuam no Docker. O worker processa um job
por vez e usa apenas HTTP da stdlib para falar com o `bot_api`.

## Configuracao

Defina as variaveis no `.env` da raiz do `bot_api`. O token deve existir somente
no ambiente, nunca no `start_homelab.bat` ou em atalhos.

```dotenv
PROMAX_API_BASE_URL=http://127.0.0.1:8080
PROMAX_WORKER_TOKEN=troque-por-um-token-longo
PROMAX_WORKER_ID=homelab-patos
PROMAX_DRIVER_DIR=C:\Users\cadcom.patos\Documents\promax-web-driver
PROMAX_PYTHON=C:\Users\cadcom.patos\Documents\promax-web-driver\venv\Scripts\python.exe
```

Opcoes com valores padrao:

```dotenv
PROMAX_WORKER_LEASE_SECONDS=360
PROMAX_WORKER_HTTP_TIMEOUT_SECONDS=10
PROMAX_WORKER_BOLETO_IMPORT_TIMEOUT_SECONDS=300
PROMAX_WORKER_HEARTBEAT_SECONDS=15
PROMAX_WORKER_CONTROL_SECONDS=5
PROMAX_WORKER_POLL_SECONDS=5
PROMAX_WORKER_BACKOFF_INITIAL_SECONDS=2
PROMAX_WORKER_BACKOFF_MAX_SECONDS=60
PROMAX_WORKER_LOG_LEVEL=INFO
PROMAX_VISUAL_LOCK_ENABLED=1
PROMAX_VISUAL_LOCK_FILE=
```

`PROMAX_DRIVER_DIR` deve conter `cli.py`, e `PROMAX_PYTHON` deve apontar para o
executavel Python usado pelo driver. Sem esses valores, o worker procura o
repositorio `promax-web-driver` ao lado do `bot_api` e usa primeiro `venv`,
depois `.venv`. O worker descobre os grupos declarados em
`PROMAX_DRIVER_DIR\report_groups\*.py`, publica o catalogo no heartbeat e parte
do formato:

```text
PROMAX_PYTHON cli.py relatorios --perfil <grupo>
```

Unidades, rotinas, publicacao e `job_id` sao acrescentados somente apos
validacao contra o catalogo anunciado e contra identificadores seguros. As
datas so sao enviadas quando `send_dates=true`; no painel, isso corresponde ao
checkbox **Enviar data**, desmarcado por padrao. Sem essa opcao, cada rotina
mantem seu periodo configurado no driver. Os argumentos sao enviados ao
`subprocess` como lista e com `shell=False`. Um pedido de cancelamento encerra
somente a arvore do PID filho com:

```text
taskkill /PID <pid> /T /F
```

Jobs de manutencao usam o mesmo controle. O reprocessamento de publicacoes
executa `cli.py reprocessar-publicacao` e tenta reenviar somente os arquivos
guardados em `logs/publicacao_pendente`.

## Concorrencia visual

O Promax depende de janela, sessao, foco e downloads locais. Por isso o worker
usa uma trava local antes de reivindicar qualquer job. Se outro worker, outra
sessao ou outro processo do mesmo host ja estiver executando automacao Promax,
o worker fica aguardando e nao pega novo job da fila.

Por padrao a trava fica em `ProgramData\bot_api\locks\promax_visual.lock`.
Se o usuario do Windows nao tiver permissao para criar essa pasta, o worker
usa `LocalAppData` ou a pasta temporaria. Para fixar o caminho manualmente:

```dotenv
PROMAX_VISUAL_LOCK_FILE=C:\ProgramData\bot_api\locks\promax_visual.lock
```

Mantenha `PROMAX_VISUAL_LOCK_ENABLED=1` em producao. Desativar essa trava so
faz sentido em teste local sem Promax visual.

## Execucao

Para validar manualmente:

```powershell
cd C:\Users\cadcom.patos\Documents\bot_api
.\venv\Scripts\python.exe -m workers.promax_worker
```

Para subir o Docker Compose e iniciar o worker minimizado:

```bat
start_homelab.bat
```

O script usa `venv\Scripts\python.exe` do `bot_api`. O modulo carrega
`BOT_ENV_FILE` quando definido ou `.env` por padrao.

## Inicializacao com o Windows

1. Pressione `Win+R`, informe `shell:startup` e confirme.
2. Crie nessa pasta um atalho para
   `C:\Users\cadcom.patos\Documents\bot_api\start_homelab.bat`.
3. Mantenha tokens e caminhos no `.env`; o atalho nao precisa de argumentos.

O Docker Desktop precisa estar pronto para aceitar `docker compose up -d`.
Quando o Compose falha, o script nao inicia o worker.
Se `PROMAX_WORKER_TOKEN` estiver vazio ou ausente, o script gera um token
aleatorio no `.env` antes de subir o Compose. Uma trava local impede duas
instancias do worker no mesmo Windows.
