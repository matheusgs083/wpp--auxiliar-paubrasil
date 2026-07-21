# Atualizacao do Worker Promax no servidor funcional

Este guia considera que o servidor de producao ja esta funcionando com:

- `bot_api` rodando no Docker;
- PostgreSQL ja criado e com dados;
- Evolution/API ja configurada;
- `promax-web-driver` ja instalado em uma pasta irma ao `bot_api`;
- painel admin ja acessivel.

O objetivo aqui e aplicar somente a atualizacao do Promax Admin/worker, sem
reinstalar a stack inteira e sem perder dados.

## Arquitetura esperada

```text
C:\Users\SEU_USUARIO\Documents\
|-- wpp--auxiliar-paubrasil\    # bot_api, Docker, painel e fila Promax
`-- promax-web-driver\          # automacao Windows do Promax
```

- O `bot_api` e o PostgreSQL rodam no Docker.
- O worker Promax roda no Windows, fora do Docker.
- O worker busca jobs no `bot_api` e executa o `promax-web-driver`.
- Cada worker processa um job por vez.
- O `PROMAX_WORKER_TOKEN` autentica o worker com a API local.

## 1. Antes de atualizar

Confirme que nao tem rotina Promax em execucao no painel:

```text
http://127.0.0.1:8080/admin/promax
```

Se houver job rodando, pause a fila e espere terminar.

Depois confira o estado dos repositorios:

```powershell
$Bot = "C:\Users\SEU_USUARIO\Documents\wpp--auxiliar-paubrasil"
$Driver = "C:\Users\SEU_USUARIO\Documents\promax-web-driver"

git -C $Bot status --short
git -C $Driver status --short
```

Se aparecerem arquivos alterados que voce nao reconhece, revise antes de dar
`pull`.

## 2. Parar somente o worker

Nao pare o Docker e nao use `docker compose down -v`.

Pare apenas o processo do worker Promax:

```powershell
$processos = @(
    Get-CimInstance Win32_Process |
    Where-Object {
        $_.Name -match '^pythonw?\.exe$' -and
        $_.CommandLine -match 'workers\.promax_worker'
    }
)

$ids = @($processos.ProcessId)

$processos |
Where-Object { $ids -notcontains $_.ParentProcessId } |
ForEach-Object {
    taskkill.exe /PID $_.ProcessId /T /F
}
```

## 3. Atualizar os codigos

Atualize os dois repositorios:

```powershell
git -C $Driver pull --ff-only origin main
git -C $Bot pull --ff-only origin main
```

Atualize as dependencias Python, caso tenha mudanca em `requirements.txt`:

```powershell
& "$Driver\venv\Scripts\python.exe" -m pip install -r "$Driver\requirements.txt"
& "$Bot\venv\Scripts\python.exe" -m pip install -r "$Bot\requirements.txt"
```

## 4. Conferir variaveis Promax no `.env`

No servidor funcional, o `.env` normalmente ja possui banco, Evolution e demais
tokens. Para o Promax, confira apenas estas variaveis:

```dotenv
PROMAX_API_BASE_URL=http://127.0.0.1:8080
PROMAX_WORKER_TOKEN=preenchido_no_servidor
PROMAX_WORKER_ID=promax-producao
PROMAX_DRIVER_DIR=C:\Users\SEU_USUARIO\Documents\promax-web-driver
PROMAX_PYTHON=C:\Users\SEU_USUARIO\Documents\promax-web-driver\venv\Scripts\python.exe
```

As demais configuracoes do worker podem usar os padroes do codigo. So altere se
houver necessidade operacional:

```dotenv
PROMAX_WORKER_POLL_SECONDS=5
PROMAX_WORKER_LEASE_SECONDS=360
PROMAX_WORKER_HEARTBEAT_SECONDS=15
PROMAX_WORKER_CONTROL_SECONDS=5
PROMAX_WORKER_HTTP_TIMEOUT_SECONDS=10
PROMAX_WORKER_BOLETO_IMPORT_TIMEOUT_SECONDS=300
PROMAX_WORKER_BACKOFF_INITIAL_SECONDS=2
PROMAX_WORKER_BACKOFF_MAX_SECONDS=60
PROMAX_WORKER_LOG_LEVEL=INFO
```

Regras importantes:

- nao troque `PROMAX_WORKER_TOKEN` se o servidor ja esta funcionando;
- o token do worker nao e a API key do webhook da Evolution;
- `PROMAX_WORKER_ID` deve ser fixo para essa maquina;
- nao coloque tokens em atalhos, `.bat` novos ou Git.

## 5. Rebuild seguro do `bot_api`

Use rebuild somente do container da API. Isso preserva Postgres e volumes:

```powershell
Set-Location $Bot
docker compose up -d --build --no-deps bot_api
```

Nao use:

```text
docker compose down -v
docker volume rm
git reset --hard
git clean -fd
```

## 6. Iniciar o worker atualizado

Se voce ja usa `start_homelab.bat`, use ele:

```powershell
Set-Location $Bot
.\start_homelab.bat
```

Se preferir iniciar manualmente:

```powershell
Start-Process `
    -FilePath "$Bot\venv\Scripts\python.exe" `
    -ArgumentList "-m", "workers.promax_worker" `
    -WorkingDirectory $Bot `
    -WindowStyle Hidden
```

O worker se registra automaticamente no painel por heartbeat. Nao precisa criar
cadastro manual no banco.

## 7. Validar depois da atualizacao

Valide a API:

```powershell
Invoke-RestMethod "http://127.0.0.1:8080/health"
docker compose ps
docker compose logs --tail 100 bot_api
```

Valide o processo do worker:

```powershell
Get-CimInstance Win32_Process |
Where-Object { $_.CommandLine -match 'workers\.promax_worker' } |
Select-Object ProcessId, Name, CommandLine
```

Abra:

```text
http://127.0.0.1:8080/admin/promax
```

Confira:

- worker online;
- catalogo de relatorios carregado;
- fila sem job preso;
- agendamentos preservados;
- botao de reprocessar publicacoes disponivel;
- log de execucao com data, status, grupo, rotinas e unidade.

## 8. Teste recomendado

Antes de liberar a agenda, execute um relatorio pequeno pelo painel:

1. Abra `Promax Admin`.
2. Va em `Executar agora`.
3. Escolha uma revenda e um grupo pequeno.
4. Execute.
5. Confira o log em tempo real.
6. Confira se o status final nao ficou apenas `parcial` sem detalhe.
7. Se baixou mas nao publicou, use `Reprocessar publicacoes`.

## 9. Se o worker nao aparecer

Rode em primeiro plano para ver o erro:

```powershell
Set-Location $Bot
.\venv\Scripts\python.exe -m workers.promax_worker
```

Erros comuns:

- `PROMAX_WORKER_TOKEN is required`: token ausente no `.env`;
- `HTTP 401`: token do worker diferente do token carregado pelo container;
- `PROMAX_DRIVER_DIR is not a directory`: caminho do driver incorreto;
- `PROMAX_PYTHON is not a file`: ambiente virtual do driver incorreto;
- `Outro worker Promax ja esta em execucao`: ja existe uma instancia ativa;
- `Promax API indisponivel`: API local parada ou URL incorreta.

Depois de corrigir `.env`, recrie somente o `bot_api` e reinicie o worker:

```powershell
Set-Location $Bot
docker compose up -d --force-recreate --no-deps bot_api
.\start_homelab.bat
```

## 10. Inicializacao com Windows

Se o servidor ja tinha o worker iniciando com Windows, normalmente nao precisa
refazer.

Para conferir:

1. Pressione `Win+R`.
2. Execute `shell:startup`.
3. Confirme se existe atalho para `$Bot\start_homelab.bat`.
4. Confirme se o Docker Desktop inicia com o Windows.

O atalho deve apontar para o `.bat`; os caminhos e tokens ficam no `.env`.

## Checklist final

- [ ] fila Promax pausada antes da atualizacao;
- [ ] nenhum job em execucao antes do `pull`;
- [ ] repositorios atualizados;
- [ ] dependencias Python atualizadas;
- [ ] `.env` manteve o token Promax correto;
- [ ] `bot_api` recriado com `--no-deps`;
- [ ] PostgreSQL nao foi removido;
- [ ] worker iniciado;
- [ ] worker online no painel;
- [ ] teste pequeno executado;
- [ ] fila reativada.
