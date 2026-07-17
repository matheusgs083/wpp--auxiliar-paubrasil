# Acesso da Central na Rede Local

Este passo a passo serve para abrir a Central do bot em outra maquina da mesma rede, sem usar ngrok.

Exemplo usado:

- IP do computador do bot: `172.16.54.90`
- Porta da Central: `8080`
- URL da Central: `http://172.16.54.90:8080/admin/imports`

## 1. Descobrir o IP e a rede da maquina

No computador onde o Docker esta rodando:

```powershell
ipconfig
```

Procure o `Endereco IPv4`.

Para ver tambem o tamanho da rede:

```powershell
Get-NetIPAddress -AddressFamily IPv4
```

Exemplo:

```text
IPAddress    PrefixLength
172.16.54.90 23
```

Nesse caso, a rede correta e:

```text
172.16.54.0/23
```

Ela cobre os IPs `172.16.54.x` e `172.16.55.x`.

## 2. Configurar o bot para escutar na rede

No arquivo `.env`, deixe:

```env
APP_PORT=8080
BOT_API_BIND_IP=0.0.0.0
```

Depois suba o container:

```powershell
docker compose up -d --build --no-deps bot_api
```

Verifique se a porta ficou publicada em `0.0.0.0`:

```powershell
docker ps --filter name=bot_api --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

O esperado:

```text
0.0.0.0:8080->8080/tcp
```

## 3. Liberar a porta no Firewall do Windows

Abra o PowerShell como Administrador.

Se ja existir regra antiga, remova:

```powershell
Remove-NetFirewallRule -DisplayName "Central Bot API 8080 LAN"
```

Crie a regra liberando apenas a rede local:

```powershell
New-NetFirewallRule -DisplayName "Central Bot API 8080 LAN" -Direction Inbound -Protocol TCP -LocalPort 8080 -RemoteAddress 172.16.54.0/23 -Action Allow
```

Se sua rede for outra, troque `172.16.54.0/23` pela faixa correta.

## 4. Se ainda der timeout

Em alguns Windows, a regra de bloqueio do Docker Desktop pode impedir acesso vindo de outros PCs.

No computador do bot, com PowerShell como Administrador:

```powershell
Disable-NetFirewallRule -DisplayName "Docker Desktop Backend"
```

Depois teste novamente.

## 5. Testar de outro computador

Em outro PC da mesma rede:

```powershell
Test-NetConnection 172.16.54.90 -Port 8080
```

O esperado:

```text
TcpTestSucceeded : True
```

Depois acesse:

```text
http://172.16.54.90:8080/admin/imports
```

Tambem pode testar a saude da API:

```text
http://172.16.54.90:8080/health
```

## 6. Cuidados

- Nao faca redirecionamento de porta no roteador para a porta `8080`.
- Esta configuracao e para rede interna.
- Nao use `0.0.0.0` junto com firewall aberto para `Any` se nao for necessario.
- Se a maquina mudar de IP, atualize o firewall e o DNS interno.

# DNS interno para acessar por nome

Com DNS interno, os usuarios podem acessar algo como:

```text
http://central-bot:8080/admin/imports
```

ou:

```text
http://central-bot.grupopaubrasil.com.br:8080/admin/imports
```

## Opcao 1. DNS Manager no Windows Server

No servidor DNS da empresa:

```powershell
dnsmgmt.msc
```

Depois:

1. Abra `Forward Lookup Zones`.
2. Selecione a zona interna, por exemplo `grupopaubrasil.com.br`.
3. Clique com o botao direito e escolha `New Host (A or AAAA)`.
4. Preencha:

```text
Name: central-bot
IP address: 172.16.54.90
```

5. Salve.

Teste em outro PC:

```powershell
nslookup central-bot
```

ou:

```powershell
nslookup central-bot.grupopaubrasil.com.br
```

## Opcao 2. Criar DNS por PowerShell no servidor

No servidor DNS, como Administrador:

```powershell
Add-DnsServerResourceRecordA -ZoneName "grupopaubrasil.com.br" -Name "central-bot" -IPv4Address "172.16.54.90"
```

Teste:

```powershell
nslookup central-bot.grupopaubrasil.com.br
```

Se a rede usar sufixo DNS automatico, tambem pode funcionar:

```powershell
nslookup central-bot
```

## Opcao 3. Sem servidor DNS

Se nao houver DNS interno, use o arquivo `hosts` em cada PC.

Abra o Bloco de Notas como Administrador e edite:

```text
C:\Windows\System32\drivers\etc\hosts
```

Adicione:

```text
172.16.54.90 central-bot
```

Depois acesse:

```text
http://central-bot:8080/admin/imports
```

## Como descobrir se existe DNS interno

Em qualquer PC da rede:

```powershell
ipconfig /all
```

Veja os campos:

```text
DNS Servers
Primary Dns Suffix
Connection-specific DNS Suffix
```

Se aparecer um DNS interno, normalmente um IP `172.16.x.x`, e houver zona da empresa, e possivel criar o registro centralizado.
