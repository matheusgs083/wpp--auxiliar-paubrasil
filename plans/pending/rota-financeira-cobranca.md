# Rota Financeira: registrar a cobrança do cliente

Pedido (24/11/2026): hoje o vendedor não tem como registrar "já cobrei" ou "prometeu
pagar dia 28". A ideia é um registro rápido por cliente. Com ele, o cliente sai do topo
da fila no dia e o histórico fica na ficha.

## Objetivo

- Registrar a cobrança em dois toques, direto da linha da rota ou da ficha.
- A fila do dia mostra quem já foi cobrado e põe esses clientes depois dos que faltam cobrar.
- A ficha do cliente mostra o histórico de cobranças, para quem vier depois (GV, outro
  vendedor) saber o que já foi combinado.

## Fases

### Fase 1: base e serviço (Tamanho: S)
- **Pronto quando:** o serviço grava, lista e desfaz registros no Postgres; testes de unidade e um teste no Postgres local passam.
- **Arquivos:** `services/rota_cobrancas_service.py` (novo), `services/app_runtime.py`, `tests/test_rota_cobrancas_service.py` (novo).
- **Tabela** `reports.rota_cobrancas`: id, filial, cliente, tipo, data_promessa, observacao, usuario, criado_em, desfeito_em. Índice em (filial, cliente, criado_em).
- **Métodos:** `registrar`, `desfazer` (só o autor, no mesmo dia), `historico(filial, cliente, dias=90)`, `situacao_do_dia(filial, chaves)` (último registro de hoje e promessa ativa, para a fila).
- **Bloqueado por:** nada.

### Fase 2: API (Tamanho: S)
- **Pronto quando:** as rotas recusam cliente fora da carteira, registram a ação no histórico do painel e têm testes de rota.
- **Arquivos:** `routes/admin_rota_financeira.py`, `routes/admin_registry.py`, `tests/test_admin_rota_financeira_routes.py`.
- **Rotas:**
  - `POST /api/admin/rota-financeira/cobrancas`: tipo, data da promessa e observação de até 200 caracteres.
  - `DELETE /api/admin/rota-financeira/cobrancas/{id}`: desfazer.
  - `GET /api/admin/clientes/{filial}/{cliente}/blocos/cobrancas`: novo bloco da ficha.
- **Bloqueado por:** fase 1.

### Fase 3: a fila do dia passa a considerar a cobrança (Tamanho: M)
- **Pronto quando:** o teste de SQL cobre a ordem e o filtro novo, e no Postgres local um cliente cobrado hoje desce na fila.
- **Arquivos:** `services/rota_financeira_query_service.py`, `tests/test_rota_financeira_query_service.py`.
- **O que muda:**
  - Um CTE `cobranca` com o último registro de hoje por cliente e a promessa ativa.
  - A ordem passa a ser: não cobrados primeiro, dentro da faixa atual.
  - Novo filtro "Falta cobrar", com contagem no resumo.
  - A linha devolve `cobranca: {tipo, hora, data_promessa}`.
- **Bloqueado por:** fase 1.

### Fase 4: tela (Tamanho: M)
- **Pronto quando:** a tela foi conferida no celular e no computador, nos temas claro e escuro; o registro sai em 2 toques e o desfazer funciona.
- **Arquivos:** `templates/painel/abas/rota-financeira.html`, `templates/painel/js/22-rota-financeira.js`, `templates/painel/js/24-ficha-cliente.js`, `services/ficha_cliente_blocos.py`, `templates/painel/estilos/03-componentes.css`.
- **O que muda:**
  - Botão "Registrar" na linha e na ficha, abrindo uma janela curta com tipo, data da promessa e observação.
  - Etiqueta "Cobrado às 10:32" ou "Prometeu pagar 28/11" na linha.
  - Filtro "Falta cobrar".
  - Bloco "Cobranças" na ficha.
- **Bloqueado por:** fases 2 e 3.

### Fase 5: verificação (Tamanho: S)
- **Pronto quando:** a suíte da rota e da ficha passa, o roteiro manual foi feito no Postgres local e as telas foram conferidas.
- **Roteiro manual:** registrar, ver o cliente descer na fila, desfazer, ver a promessa voltar ao topo depois da data.

## Decisões (a confirmar com o usuário)

| # | Decisão | Recomendação | Por quê |
|---|---|---|---|
| 1 | Tipos de registro | Cobrado · Prometeu pagar (com data) · Não atendeu · Observação | Cobre o dia a dia sem virar formulário |
| 2 | Efeito na fila | Cobrado ou "Não atendeu" hoje: vai para o fim da faixa no dia. Promessa: fica no fim até a data e volta ao normal depois dela | A fila mostra primeiro quem falta cobrar |
| 3 | Quem vê | Todos que já enxergam o cliente (vendedor, GV, admin) | O GV acompanha o que foi combinado |
| 4 | Onde guardar | Tabela no Postgres (reports) | Vários usuários ao mesmo tempo; o histórico é consultável |
| 5 | WhatsApp ou Ligar registram sozinhos? | Não; ao voltar para a tela, aparece "Registrar cobrança?" na linha tocada | Tocar não garante que houve conversa |
| 6 | Histórico na ficha | Últimos 90 dias, como as devoluções | Mesma janela que o vendedor já conhece |
| 7 | Desfazer | Só quem registrou, no mesmo dia | Evita apagar o histórico de outra pessoa |
| 8 | Filtro "Falta cobrar" | Sim, com contagem | Fecha o ciclo do dia |

## Ainda não especificado
- Fase 4: se o GV terá uma visão consolidada do tipo "quantos foram cobrados por vendedor". Fica fora da versão 1 e pode virar um card na Gestão depois.

## Sempre / Nunca
- **Sempre:** checar a carteira em toda rota; guardar quem registrou e quando; usar textos de uso comum.
- **Nunca:** apagar registros (desfazer só marca `desfeito_em`); registrar sozinho só porque o vendedor tocou no WhatsApp; mexer na importação dos relatórios.

## Progresso
| Fase | Status |
|---|---|
| 1 Base e serviço | pendente |
| 2 API | pendente |
| 3 Fila do dia | pendente |
| 4 Tela | pendente |
| 5 Verificação | pendente |
