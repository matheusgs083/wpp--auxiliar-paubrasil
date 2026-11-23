# Ficha do cliente em blocos (Rota Financeira e Clientes)

Origem: pedido de 23/11/2026, "Corrija o desenho da experiência da Rota Financeira".
Trabalho em `C:\Users\cadcom.patos\Documents\bot_api`. Sem publicar, sem Docker, sem alterar produção.

Fluxo alvo: **Rota Financeira (primeira tela)** → cliente selecionado → cabeçalho com resumo rápido → blocos empilhados → ação no bloco.

A primeira tela de quem tem a Rota Financeira é a própria Rota Financeira: ao entrar no painel ou na área Vendedor, ela abre direto, e a ficha do cliente sai de lá.

## O que já existe (levantado no código em 23/11)

| Bloco | Fonte | Situação |
| --- | --- | --- |
| Cabeçalho | `DClientesQueryService` (+ `DClientePayipProfile` para endereço, CEP, e-mail) | pronto |
| Títulos em aberto | `InadimplenciaQueryService` (12.06.01): emissão, vencimento, original, pendente, corrigido, dias, NF | pronto; cruzamento com boleto já existe em `routes/admin_clientes.py` (`_cruzar_titulos_boletos`) |
| Boletos | `BoletosQueryService` (03.02.06): NF, nosso número, linha digitável, valor, vencimento, PDF | pronto |
| Análise de crédito | `PrazoLimiteQueryService`: KPI, % pag. em atraso, prazo, cond. pag., limite total, faturamento com PDV, pedidos | pronto; **não traz limite utilizado nem disponível** |
| Compras | 03.02.37 com itens já gravada linha a linha em `reports.liga_entrega_raw_rows` (Filial, Cliente, Dt. Operacao, Emissao, Nota, Serie, Status, Produto, Qtde, Total, Mapa) pela importação da Liga | **falta a base agregada por cliente** |
| Vasilhames | `GiroQueryService.search_by_registration`: total, real, gap e giro de litrinho, inteira e litrão | pronto |
| Equipamentos | nenhuma fonte encontrada | estado vazio |
| Comodatos | `ComodatosQueryService` (02.02.20): nº, material, subtipo, saldo. A importação guarda a linha inteira em `payload`, então a **data de vencimento** do comodato já está no banco | falta expor o vencimento e marcar os vencidos |
| Devoluções | **03.02.37, status D** (mesma base de Compras): data, NF, NF de referência, código do motivo, produto, qtde, total. Motivo e responsabilidade saem de `liga_entrega_motivos.MOTIVOS_DEVOLUCAO`; justificativa de `DevolucoesJustificativasService` | o histórico SQL hoje **não guarda** `Mot. Cancelamento` nem `NF Referencia`: entram em `COLUNAS_HISTORICO` |
| Cadastro e documentos | dClientes + `DocumentacaoPendenteQueryService` (contrato social, CPF, RG, comprovante, fachada, ficha) | pronto |

Inspeção da amostra `030237_ligacomitens.csv` (Patos, 43.738 linhas, emissão 01–20/11):
- Status: A 39.699, E 3.551, D 354 (devolução, tem NF de referência), C 134 (cancelada, tem motivo).
- Filial + Nota + Série + Produto **não é única**: 828 repetições legítimas (mesmo produto em duas linhas da nota com preços diferentes). 71 linhas idênticas, também dentro da mesma nota.
- A exportação filtra por **emissão**: 3.094 linhas com Dt. Operacao 31/10 e Emissão 03/11 estão no arquivo de novembro.

## Fases

### Fase 1 — Base de Compras 03.02.37 (risco maior, primeiro)
Verificada quando: reimportar o mesmo acumulado não muda o total do cliente, e a média de 3 meses bate na mão com a amostra.
Arquivos: `services/compras_030237_service.py` (novo), `services/app_runtime.py`, `tests/test_compras_030237_service.py` (novo).

#### Passo 1.1: tabela agregada e regra de deduplicação (Tamanho: M)
- Critérios: tabela `reports.cliente_compras_030237` (filial, cliente, competência pela Dt. Operacao, produto, descrição, unidade, qtde, total, notas, última entrega, origem, atualizado_em) com status A e E; tabela `reports.cliente_devolucoes_030237` (filial, cliente, data, nota, série, NF de referência, motivo, qtde, total) com status D; para cada (filial, mês de emissão) entra só o arquivo mais recente que tem linhas daquele mês; reconstrução só dos meses tocados pela carga.
- Verificação: `python -m pytest tests/test_compras_030237_service.py`
- Seams: função pura de seleção e agregação (sem banco) + SQL testado com conexão falsa, no padrão de `test_rota_financeira_query_service.py`.
- Bloqueado por: nenhum.

#### Passo 1.2: gatilho pós-importação e carga inicial (Tamanho: S)
- Critérios: `COLUNAS_HISTORICO["030237"]` passa a guardar também `Mot. Cancelamento`, `NF Referencia` e `Data NF Referencia` (só vale das próximas cargas; devoluções antigas aparecem com "motivo não informado"); `liga_entrega_raw_sql_import_service` chama a reconstrução depois do commit (encadeado ao callback atual de `app_runtime.py`, sem substituí-lo); comando `python -m bot_api.scripts.reconstruir_compras_030237` para a carga inicial; falha na reconstrução nunca desfaz a importação da Liga.
- Verificação: teste do encadeamento do callback + execução a seco do script com conexão falsa.
- Bloqueado por: 1.1.

#### Passo 1.3: consulta por cliente (Tamanho: S)
- Critérios: `devolucoes_cliente(filial, cliente, desde)` devolve as devoluções da janela por nota, com motivo e responsabilidade traduzidos; `resumo_cliente(filial, cliente, hoje)` devolve mês atual, 3 meses fechados, média = soma ÷ 3 (mês sem compra = 0), qtde, notas, última entrega, top produtos por valor e por quantidade, série mensal para o gráfico, data da última carga e mês inicial da base.
- Verificação: testes 8 e 9 da lista obrigatória.
- Bloqueado por: 1.1.

### Fase 2 — API dos blocos
Verificada quando: todos os blocos respondem com escopo validado e uma fonte fora do ar devolve só aquele bloco com erro.
Arquivos: `routes/admin_clientes_blocos.py` (novo), `routes/admin_registry.py`, `services/app_runtime.py`, `services/clientes_escopo.py` (só se faltar helper), `tests/test_admin_clientes_blocos_routes.py` (novo).

#### Passo 2.1: esqueleto, escopo e cabeçalho (Tamanho: S)
- Critérios: `GET /api/admin/clientes/{filial}/{cliente}/cabecalho` e `GET …/blocos/{bloco}`; toda chamada valida o cliente no dClientes com `allowed_sectors` + `allowed_gv_vdes` do `EscopoClientes` antes de tocar outra fonte; fora do escopo = 403 com a mesma mensagem de "não encontrado" (não revela existência); auditoria e evento de segurança em cada abertura.
- Verificação: testes 1, 2 e 5.
- Bloqueado por: nenhum (pode correr junto com a Fase 1).

#### Passo 2.2: blocos de leitura direta (Tamanho: M)
- Critérios: títulos (reaproveita o cruzamento NF → nosso número → valor + vencimento já existente; sem vínculo = "Boleto não importado"), crédito, vasilhames, comodatos com vencimento (resumo "X item(ns), Y com contrato vencido"; vencido = vencimento antes de hoje; sem data = "sem vencimento informado"), cadastro e documentos, equipamentos (vazio); cada bloco devolve `{resumo, itens, fonte: {nome, atualizado_em, disponivel}}`.
- Verificação: testes 3, 4, 6, 7, 10 e 11.
- Bloqueado por: 2.1.

#### Passo 2.3: blocos Compras e Devoluções (Tamanho: S)
- Critérios: Compras e Devoluções leem só as tabelas da Fase 1 (nada do painel da Liga); Devoluções traz a justificativa quando existir.
- Verificação: teste de Compras e de Devoluções pela rota com serviço falso.
- Bloqueado por: 1.3, 2.1.

### Fase 3 — Ficha em blocos no painel
Verificada quando: em 1300 px e em 375 px, claro e escuro, a ficha abre, carrega bloco a bloco e respeita o limite de blocos abertos.
Arquivos: `templates/painel/abas/ficha-cliente.html` (novo), `templates/painel/js/24-ficha-cliente.js` (novo), `templates/painel/js/21-clientes.js`, `templates/painel/js/22-rota-financeira.js`, `templates/painel/js/00-estado.js`, `templates/painel/estilos/03-componentes.css`, `templates/admin_import_panel.html`.

#### Passo 3.0: Rota Financeira como primeira tela (Tamanho: XS)
- Critérios: quem tem a permissão Rota Financeira cai nela ao entrar no painel (sem caminho na URL) e ao clicar na área Vendedor; quem não tem segue a regra atual de primeira aba visível; um link direto para outra aba continua abrindo a aba pedida.
- Verificação: Playwright entrando em `/` com perfis "só vendedor" e "admin".
- Bloqueado por: nenhum.

#### Passo 3.1: casca da ficha e cabeçalho (Tamanho: S)
- Critérios: painel lateral no desktop, tela cheia no celular com "Voltar"; cabeçalho com NB, nome, filial, setor/RN, GV, cidade, dia de visita, status e telefone; ações WhatsApp (só com celular válido), Ligar (`tel:`), Mapa (endereço completo), Fechar; a ficha atual com abas sai.
- Verificação: render com Playwright e dados falsos, prints claro/escuro.
- Bloqueado por: 2.1.

#### Passo 3.2: blocos expansíveis (Tamanho: M)
- Critérios: cartão com ícone, título, resumo numa linha e chevron; carga sob demanda com loading próprio e erro próprio; rodapé com data da fonte; abre Títulos quando há pendência, senão Compras, senão Cadastro; no máximo 2 abertos no desktop e 1 no celular; ações no título: abrir boleto e copiar linha digitável.
- Verificação: Playwright clicando blocos e conferindo quantos ficam abertos; `node --check` do JS montado.
- Bloqueado por: 2.2, 3.1.

#### Passo 3.3: Compras com gráfico (Tamanho: S)
- Critérios: barras simples de faturamento mensal (SVG próprio, sem biblioteca nova), rótulos "Faturamento entregue" e "Média mensal entregue", top produtos.
- Verificação: print do bloco aberto nos dois temas.
- Bloqueado por: 2.3, 3.2.

### Fase 4 — Fechamento
- Rodar todos os testes novos e os de Clientes e Rota já existentes; gravar no PC com conferência byte a byte; relatório final com arquivos, fontes, regra de deduplicação, testes e limitações.

## Testes obrigatórios → onde ficam

| # | Teste | Arquivo |
| --- | --- | --- |
| 1 | só blocos de clientes do próprio escopo (vendedor, GV, operação) | test_admin_clientes_blocos_routes |
| 2 | fora do escopo não devolve nenhum bloco nem cabeçalho | idem |
| 3 | título com boleto vinculado mostra linha digitável | idem |
| 4 | título sem vínculo mostra "Boleto não importado" | idem |
| 5 | PDF exige escopo | idem (e o teste já existente de admin_clientes) |
| 6 | comodatos no bloco Comodatos, com vencidos contados pela data de vencimento | idem |
| 7 | documentos pendentes no bloco Cadastro | idem |
| 8 | reimportação cumulativa não duplica faturamento | test_compras_030237_service |
| 9 | média ÷ 3 com mês zerado | idem |
| 10 | giro comercial (Compras) separado do giro de vasilhames | test_admin_clientes_blocos_routes |
| 11 | fonte fora do ar não derruba os outros blocos | idem |
| extra | devolução (status D) aparece em Devoluções e não soma em Compras | test_compras_030237_service |

## Decisões (confirmadas em 23/11/2026)

| Decisão | Opção recomendada | Por quê |
| --- | --- | --- |
| Onde usar a ficha nova | Rota Financeira **e** Clientes | é a mesma ficha hoje; duas fichas diferentes viram retrabalho |
| Status que contam como entregue | A e E | mesma regra da Liga Entrega; D é devolução e C é cancelamento |
| Deduplicação da 03.02.37 | arquivo mais recente por (filial, mês de emissão); sem cortar linhas dentro do arquivo | a exportação é por emissão e acumulada; linhas repetidas dentro da nota são vendas reais |
| Base com menos de 3 meses | mostrar "Base desde mm/aaaa" e não calcular a média | dividir por 3 com mês que nem foi importado subestima o cliente |
| Limite disponível | limite total (dClientes/prazo e limite) − pendente da 12.06.01, rotulado "calculado" | nenhuma base traz o disponível pronto |
| Permissão | blocos abrem com "Clientes" ou "Rota Financeira" | hoje quem só tem a Rota já abre a ficha |
| Devoluções "recentes" | últimos 60 dias | cobre o mês atual e o anterior |
| Fonte das devoluções | 03.02.37, status D (decidido em 23/11) | mesma base de Compras; dispensa o resumo da Liga |
| Comodato vencido | vencimento do comodato (coluna da 02.02.20 no `payload`) antes de hoje (decidido em 23/11) | a data já vem na importação |
| Primeira tela | Rota Financeira (decidido em 23/11) | é por onde o vendedor começa |

## Ainda não especificado
- Fase 2.2: nome exato da coluna de vencimento na 02.02.20 e o formato da data; conferir no `payload` de `comodatos` ao pegar o passo.
- Fase 1.3: se a devolução usa a Dt. Operacao ou a Data NF Referencia como data mostrada; recomendo Dt. Operacao (dia em que voltou).
- Fase 1.1: desde quando a 03.02.37 com itens está no `liga_entrega_raw_rows` em cada filial (só dá para saber no banco de produção; o bloco mostra a data inicial que encontrar).
- Vasilhames: sinal do gap (positivo = falta?) a confirmar nos dados do Giro ao implementar; o resumo conta os tipos com falta.

## Sempre / Nunca
- Sempre: validar escopo no servidor antes de cada bloco; uma fonte por bloco; loading e erro por bloco; data da fonte no rodapé.
- Nunca: abas internas na ficha; score ou recomendação de crédito inventados; "contrato vencido" sem data de vencimento; devoluções tiradas do painel da Liga; boleto buscado no Promax ou gerado; giro de vasilhame calculado pela 03.02.37; linhas cruas da 03.02.37 no navegador; publicar, Docker ou produção.

## Progresso
| Fase | Situação |
| --- | --- |
| 1 Base de Compras e Devoluções | feita em 23/11 |
| 2 API dos blocos | feita em 23/11 |
| 3 Ficha no painel | feita em 23/11 |
| 4 Fechamento | testes locais ok; falta publicar, rodar o pytest no PC e a carga inicial |

## Registro da execução (23/11/2026)
- Regra da 03.02.37 conferida num Postgres 16 local com a amostra real de Patos (43.738 linhas) carregada em duas versões do mesmo acumulado: total A+E de R$ 11.513.704,41 e 85 notas de devolução, iguais ao cálculo direto do CSV; a versão antiga não somou.
- Ficha conferida com Playwright em 1300 px e 390 px, temas claro e escuro: Rota Financeira abre primeiro na raiz, Títulos abre sozinho, no máximo 2 blocos abertos no computador e 1 no celular; /clientes continua abrindo Clientes.
- Fora do plano: as funções de carga da ficha saíram de `routes/admin_clientes.py` para `services/clientes_fontes.py`, para os blocos e a ficha antiga usarem as mesmas.
- A tela de detalhe antiga da Rota (painel com títulos) e a ficha com abas da aba Clientes foram removidas; as duas abas abrem a ficha em blocos.
