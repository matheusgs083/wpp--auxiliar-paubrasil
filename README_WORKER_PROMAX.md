it

# Worker Promax no servidor de producao

Este guia mostra como instalar e manter o worker Promax em uma maquina Windows
onde o `bot_api` e o `promax-web-driver` ficam em pastas irmas.

O worker nao precisa ser criado manualmente no banco. Quando o processo
`workers.promax_worker` inicia com uma configuracao valida, ele envia um
heartbeat para o `bot_api` e aparece automaticamente no painel Promax.

## Arquitetura

```text
C:\Users\SEU_USUARIO\Documents\
|-- wpp--auxiliar-paubrasil\    # bot_api, Docker e worker
`-- promax-web-driver\          # automacao do Promax
```

- O `bot_api` e o PostgreSQL rodam no Docker.
- O worker roda no Windows, fora do Docker.
- O worker busca os jobs na API e executa o `promax-web-driver`.
- Cada worker processa apenas um job por vez.
- O `PROMAX_WORKER_TOKEN` autentica a comunicacao entre o host e o container.

## 1. Pre-requisitos

Confirme no servidor:

```powershell
docker version
docker compose version
py --version
git --version
```

Tambem sao necessarios:

- Docker Desktop iniciado;
- Python instalado no Windows;
- `bot_api` e `promax-web-driver` atualizados;
- acesso local ao `bot_api` em `http://127.0.0.1:8080`;
- configuracoes e credenciais do Promax existentes no `promax-web-driver`.

## 2. Preparar os ambientes Python

Ajuste os caminhos para o usuario do servidor:

```powershell
$Bot = "C:\Users\SEU_USUARIO\Documents\wpp--auxiliar-paubrasil"
$Driver = "C:\Users\SEU_USUARIO\Documents\promax-web-driver"
```

Crie ou atualize o ambiente do `bot_api`:

```powershell
Set-Location $Bot
if (-not (Test-Path ".\venv\Scripts\python.exe")) {
    py -3 -m venv venv
}
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

Crie ou atualize o ambiente do driver:

```powershell
Set-Location $Driver
if (-not (Test-Path ".\venv\Scripts\python.exe")) {
    py -3 -m venv venv
}
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

Valide os arquivos usados pelo worker:

```powershell
Test-Path "$Bot\workers\promax_worker.py"
Test-Path "$Driver\cli.py"
Test-Path "$Driver\venv\Scripts\python.exe"
```

Os tres comandos devem retornar `True`.

## 3. Configurar o `.env`

Edite o arquivo `$Bot\.env` e mantenha estas variaveis:

```dotenv
PROMAX_API_BASE_URL=http://127.0.0.1:8080
PROMAX_WORKER_TOKEN=
PROMAX_WORKER_ID=promax-producao
PROMAX_DRIVER_DIR=C:\Users\SEU_USUARIO\Documents\promax-web-driver
PROMAX_PYTHON=C:\Users\SEU_USUARIO\Documents\promax-web-driver\venv\Scripts\python.exe

PROMAX_WORKER_POLL_SECONDS=5
PROMAX_WORKER_LEASE_SECONDS=120
PROMAX_WORKER_HEARTBEAT_SECONDS=15
PROMAX_WORKER_CONTROL_SECONDS=5
PROMAX_WORKER_HTTP_TIMEOUT_SECONDS=10
PROMAX_WORKER_BACKOFF_INITIAL_SECONDS=2
PROMAX_WORKER_BACKOFF_MAX_SECONDS=60
PROMAX_WORKER_LOG_LEVEL=INFO
```

Substitua `SEU_USUARIO` pelo usuario real do Windows.

Regras importantes:

- `PROMAX_WORKER_ID` deve ser estavel e identificar a maquina.
- Se houver mais de uma maquina, cada uma deve ter um ID diferente.
- O token nao e a API key do webhook da Evolution.
- O mesmo `PROMAX_WORKER_TOKEN` precisa ser lido pelo container e pelo worker.
- Nao grave o token em atalhos, arquivos `.bat` ou no Git.

Na primeira inicializacao, `start_homelab.bat` gera um token aleatorio caso
`PROMAX_WORKER_TOKEN` esteja ausente ou vazio. O script grava o token no `.env`
antes de subir o Compose, garantindo que o container e o worker usem o mesmo
valor.

## 4. Subir o container e criar o worker

Na primeira instalacao ou depois de uma atualizacao:

```powershell
Set-Location $Bot
docker compose up -d --build --no-deps bot_api
.\start_homelab.bat
```

O `start_homelab.bat`:

1. valida o `.env`;
2. gera o token se necessario;
3. garante que o Compose esteja iniciado;
4. inicia `workers.promax_worker` minimizado;
5. impede uma segunda instancia do worker na mesma maquina.

Depois de iniciado, o worker envia o primeiro heartbeat e se registra
automaticamente. Nao existe etapa de cadastro manual.

## 5. Validar

Valide a API:

```powershell
Invoke-RestMethod "http://127.0.0.1:8080/health"
docker compose ps
docker compose logs --tail 100 bot_api
```

Confirme que o processo do worker esta ativo:

```powershell
Get-CimInstance Win32_Process |
Where-Object { $_.CommandLine -match 'workers\.promax_worker' } |
Select-Object ProcessId, Name, CommandLine
```

Abra o painel:

```text
http://127.0.0.1:8080/admin/promax
```

Em ate alguns segundos o worker deve aparecer como online. Antes de liberar as
agendas, execute um relatorio pequeno pelo painel e confira:

- job recebido pelo worker;
- logs exibidos durante a execucao;
- status final detalhado;
- arquivo publicado no destino;
- botao **Reprocessar publicacoes** disponivel para pendencias.

## 6. Executar em primeiro plano para diagnostico

Se o worker nao aparecer no painel, pare a instancia minimizada e execute em
primeiro plano:

```powershell
Set-Location $Bot
.\venv\Scripts\python.exe -m workers.promax_worker
```

Mensagens comuns:

- `PROMAX_WORKER_TOKEN is required`: token ausente no `.env`;
- `HTTP 401`: token do worker diferente do token carregado pelo container;
- `PROMAX_DRIVER_DIR is not a directory`: caminho do driver incorreto;
- `PROMAX_PYTHON is not a file`: ambiente virtual do driver incorreto;
- `Outro worker Promax ja esta em execucao`: ja existe uma instancia ativa;
- `Promax API indisponivel`: API local parada ou URL incorreta.

Depois de alterar o token no `.env`, recrie somente o `bot_api` e reinicie o
worker:

```powershell
Set-Location $Bot
docker compose up -d --force-recreate --no-deps bot_api
```

## 7. Parar e reiniciar o worker

Pause a fila no painel e espere o job atual terminar. Depois:

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

Para iniciar novamente:

```powershell
Set-Location $Bot
Start-Process `
    -FilePath "$Bot\venv\Scripts\python.exe" `
    -ArgumentList "-m", "workers.promax_worker" `
    -WorkingDirectory $Bot `
    -WindowStyle Hidden
```

## 8. Iniciar junto com o Windows

1. Pressione `Win+R`.
2. Execute `shell:startup`.
3. Crie um atalho para `$Bot\start_homelab.bat`.
4. Configure o Docker Desktop para iniciar com o Windows.
5. Reinicie a maquina e confirme o worker no painel Promax.

O atalho deve apontar somente para o `.bat`. Tokens e caminhos permanecem no
`.env`.

## 9. Atualizar em producao

Pause a fila e espere o job atual terminar. Em seguida:

```powershell
$Bot = "C:\Users\SEU_USUARIO\Documents\wpp--auxiliar-paubrasil"
$Driver = "C:\Users\SEU_USUARIO\Documents\promax-web-driver"

git -C $Bot status --short
git -C $Driver status --short
```

Se os repositorios estiverem limpos, pare o worker conforme a secao anterior e
atualize:

```powershell
git -C $Driver pull --ff-only origin main
git -C $Bot pull --ff-only origin main

& "$Driver\venv\Scripts\python.exe" -m pip install -r "$Driver\requirements.txt"
& "$Bot\venv\Scripts\python.exe" -m pip install -r "$Bot\requirements.txt"

Set-Location $Bot
docker compose up -d --build --no-deps bot_api

Start-Process `
    -FilePath "$Bot\venv\Scripts\python.exe" `
    -ArgumentList "-m", "workers.promax_worker" `
    -WorkingDirectory $Bot `
    -WindowStyle Hidden
```

Nao use:

```text
git reset --hard
git clean -fd
docker compose down -v
docker volume rm
```

Esses comandos podem apagar alteracoes locais, arquivos pendentes ou volumes de
dados. As publicacoes que falharam ficam preservadas em:

```text
promax-web-driver\logs\publicacao_pendente
```

## 10. Checklist final

- [ ] Docker Desktop iniciado;
- [ ] `bot_api` saudavel;
- [ ] `promax-web-driver` acessivel no caminho configurado;
- [ ] ambientes `venv` dos dois repositorios instalados;
- [ ] token existente no `.env`;
- [ ] `PROMAX_WORKER_ID` unico e estavel;
- [ ] worker visivel como online no painel;
- [ ] fila reativada;
- [ ] job de teste concluido e publicado;
- [ ] inicializacao automatica configurada.
