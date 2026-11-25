# Nomes dos gerentes de vendas (GV) e filtros de GV/setor legíveis

Pedido (24/11/2026): os filtros mostram códigos internos ("3-107", "1-2"). O GV 99 aparece
em todas as filiais (é o GV dos setores de Tratamento). O ideal é poder dar nome aos GVs,
mostrar só os GVs da filial escolhida (ou todos) e tratar o gerente que atua em mais de
uma filial.

## Ideia central

O código de GV continua sendo `filial + GV` (ex.: `3_2`), como hoje em todo o sistema e
nas permissões. Por cima dele entra um **nome** que o administrador cadastra. **Códigos com
o mesmo nome viram um gerente só** nos filtros: a "Maria" com `3_2` e `4_1` aparece uma vez,
e escolher a Maria traz os setores dela nas duas filiais. O GV 99 já nasce com o nome
"Tratamento" em todas as filiais.

O nome **não** mexe em permissão: o acesso de cada usuário continua preso aos códigos.

## Fases

### Fase 1: cadastro dos nomes (servidor)
Verificado quando: os testes do serviço e das rotas passam; o arquivo é criado e lido.
Arquivos: `services/gerentes_vendas_service.py` (novo), `routes/admin_gerentes_vendas.py` (novo),
`routes/admin_registry.py`, `services/app_runtime.py`, `tests/test_gerentes_vendas.py` (novo).

#### Passo 1.1: serviço de nomes (Tamanho: S)
- `GerentesVendasService` guarda `{ "3_2": "Maria", ... }` em `exports/gerentes_vendas.json`,
  no mesmo padrão das justificativas de jornada e das liberações de pedido.
- `nome(chave)`: nome cadastrado; sem cadastro, `99` vira "Tratamento"; senão vazio.
- `agrupar(chaves)`: junta as chaves pelo nome → `[{nome, chaves: ["3_2","4_1"], filiais}]`;
  chave sem nome vira um grupo próprio com o rótulo "GV 2 · Patos".
- Testes: mesmo nome junta; 99 sem cadastro = Tratamento; nome vazio volta ao rótulo do código.
- Bloqueado por: nada.

#### Passo 1.2: rotas de gestão (Tamanho: S)
- `GET /api/admin/gerentes-vendas`: todos os códigos de GV da dSetores (filial, código,
  quantidade de setores, nome atual). Só administrador.
- `PUT /api/admin/gerentes-vendas`: grava a lista de nomes (texto até 60 caracteres;
  vazio apaga). Só administrador; fica registrado em ações do painel.
- Testes: admin lê e grava; vendedor recebe 403.
- Bloqueado por: 1.1.

### Fase 2: tela "Gerentes de vendas" (Gestão)
Verificado quando: o administrador nomeia, salva e o nome aparece na Rota sem recarregar o serviço.
Arquivos: `templates/painel/abas/gerentes-vendas.html` (novo), `templates/painel/js/28-gerentes-vendas.js` (novo),
`templates/admin_import_panel.html`, `templates/painel/js/00-estado.js`, `templates/painel/js/99-inicio.js`,
`templates/painel/estilos/03-componentes.css`.

#### Passo 2.1: tela de nomes (Tamanho: M)
- Tabela agrupada por filial (nome da dRevendas): código do GV, setores, campo Nome.
- Sugestão automática: ao digitar um nome que já existe, a lista sugere (datalist), para não
  criar "Maria" e "MARIA" separados (a comparação ignora maiúsculas e acentos).
- Um botão "Salvar nomes" grava tudo de uma vez.
- Bloqueado por: 1.2.

### Fase 3: filtros legíveis (Rota Financeira e Gerar crítica)
Verificado quando: no celular e no computador o filtro mostra nomes, agrupados por filial,
e filtrar pela Maria traz os setores das duas filiais.
Arquivos: `routes/admin_rota_financeira.py`, `services/rota_financeira_query_service.py`,
`routes/admin_critica_carteira.py`, `templates/painel/js/22-rota-financeira.js`,
`templates/painel/js/26-critica-carteira.js`, testes das duas rotas.

#### Passo 3.1: opções da Rota com nomes (Tamanho: M)
- `opcoes` passa a devolver `gerentes: [{nome, chaves, filiais}]` e cada setor com
  `rotulo: "Setor 107"` e a filial.
- O filtro GV vira "Gerente": lista pelo nome; com filial escolhida, só quem tem código nela.
- O filtro de setor mostra "Setor 107", agrupado por filial (optgroup com o nome da revenda),
  só os setores da filial e do gerente escolhidos.
- `listar` aceita várias chaves de GV (as do gerente escolhido), sempre dentro do escopo do usuário.
- Na tabela, a coluna "GV / Setor" mostra o nome do gerente e "Setor 107".
- Testes: gerente com duas filiais filtra as duas; chave fora do escopo é ignorada.
- Bloqueado por: 1.1.

#### Passo 3.2: Gerar crítica com nomes (Tamanho: S)
- "Crítica do GV 10" vira "Crítica de Maria (GV 10)"; o PDF continua saindo por código.
- Bloqueado por: 1.1.

### Fase 4: verificação
- Testes de todas as rotas tocadas.
- Navegador de teste: vendedor, gerente e administrador; celular e computador; claro e escuro.
- Primeira validação real: o administrador nomeia 2 ou 3 GVs e confere na Rota.

## Decisões

| Decisão | Escolha | Por quê |
| --- | --- | --- |
| Como juntar gerente de várias filiais | Pelo mesmo nome digitado | Não precisa de tela de "vincular códigos"; quem nomeia já está dizendo quem é |
| GV 99 | Nome padrão "Tratamento" em todas as filiais, editável | Pedido do usuário; evita um GV 99 por filial |
| Onde guardar os nomes | Arquivo `exports/gerentes_vendas.json` | Mesmo padrão já usado; poucos registros; sem migração de banco |
| Quem nomeia | Só administrador | O nome aparece para todo mundo |
| Permissões | Continuam por código | Renomear não pode abrir nem fechar acesso |

## A confirmar antes de aplicar

1. Juntar pelo mesmo nome (recomendado: sim).
2. Só administrador nomeia (recomendado: sim).
3. Nomes de setores (vendedores) ficam para depois; se a dSetores tiver o nome do vendedor,
   puxar de lá em vez de digitar (precisa de um arquivo de exemplo).
4. A pasta `exports` precisa ser preservada no Docker (volume), senão os nomes somem ao
   recriar o container. Confirmar.

## Não está definido ainda
- Nomes de setores: depende das colunas da dSetores (fase futura).
- Hoje as opções da Rota leem no máximo 200 combinações setor/GV; para administrador com
  todas as filiais pode cortar. A fase 3 passa a ler os GVs da dSetores, que não tem esse limite.

## Sempre / Nunca
- Sempre: o código continua visível em algum lugar (ex.: "Maria (GV 2)") para quem precisa conferir.
- Sempre: filtro respeita o escopo do usuário no servidor.
- Nunca: mudar permissões de usuário, o PDF da crítica ou a digitação de pedidos neste plano.

## Progresso
| Fase | Situação |
| --- | --- |
| 1. Cadastro dos nomes | Aguardando aprovação |
| 2. Tela Gerentes de vendas | Aguardando aprovação |
| 3. Filtros legíveis | Aguardando aprovação |
| 4. Verificação | Aguardando aprovação |
