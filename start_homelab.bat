@echo off
setlocal
cd /d "%~dp0"

if not exist ".env" (
    echo Arquivo .env nao encontrado.
    exit /b 3
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$path = Join-Path (Get-Location) '.env';" ^
  "$content = [IO.File]::ReadAllText($path);" ^
  "$match = [regex]::Match($content, '(?m)^PROMAX_WORKER_TOKEN=(.*)$');" ^
  "if (-not $match.Success -or [string]::IsNullOrWhiteSpace($match.Groups[1].Value)) {" ^
  "  $bytes = New-Object byte[] 48;" ^
  "  $rng = [Security.Cryptography.RandomNumberGenerator]::Create();" ^
  "  try { $rng.GetBytes($bytes) } finally { $rng.Dispose() };" ^
  "  $token = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_');" ^
  "  if ($match.Success) { $content = [regex]::Replace($content, '(?m)^PROMAX_WORKER_TOKEN=.*$', ('PROMAX_WORKER_TOKEN=' + $token), 1) }" ^
  "  else { $content = $content.TrimEnd() + [Environment]::NewLine + 'PROMAX_WORKER_TOKEN=' + $token + [Environment]::NewLine };" ^
  "  [IO.File]::WriteAllText($path, $content, [Text.UTF8Encoding]::new($false));" ^
  "}"
if errorlevel 1 (
    echo Falha ao preparar o token do worker Promax.
    exit /b 4
)

docker compose up -d
if errorlevel 1 (
    echo Falha ao iniciar os servicos Docker.
    exit /b 1
)

set "BOT_PYTHON=%~dp0venv\Scripts\python.exe"
if not exist "%BOT_PYTHON%" (
    echo Python do bot_api nao encontrado em "%BOT_PYTHON%".
    exit /b 2
)

start "Promax Worker" /min "%BOT_PYTHON%" -m workers.promax_worker
exit /b 0
