# Painel dividido por aba

`templates/admin_import_panel.html` é só o esqueleto. Cada linha
`<!--#include caminho -->` é trocada pelo arquivo indicado quando o painel é
servido (`services/admin_templates.py`, função `montar_template`).

- `estilos/` — CSS, em ordem: `01-base`, `02-entrega` (paleta escura da Liga), `03-componentes`.
  A ordem importa para a cascata: regra nova vai no arquivo e na posição de onde ela pertence.
- `abas/` — HTML de cada aba (uma `tab-pane` por arquivo).
- `modais.html` — janelas modais compartilhadas.
- `js/` — um único script, montado nesta ordem:
  - `00-estado.js`: constantes, `state`, `E` e todo comando que roda ao carregar. A ordem aqui importa.
  - `01-nucleo.js`: funções gerais (log, sessão, formatação, abas).
  - `02-…` a `20-…`: funções de cada aba.
  - `99-inicio.js`: chamada final de `init()`.

Arquivos de `js/` (exceto `00` e `99`) só têm declarações `function`, que valem para o
script inteiro; por isso uma função pode chamar outra de qualquer arquivo.
Testes que procuram texto no painel devem usar `montar_template(...)`, não `read_text()`.

## Abas e endereços
- As abas ficam em `#adminTabs` (no esqueleto). Cada `<li>` tem `data-grupo`
  (`operacao`, `financeiro`, `dados`, `admin`); a linha `#panelGroups` escolhe o grupo.
  Aba nova: coloque o `<li>` com o `data-grupo` certo.
- Endereços: o painel abre na raiz (`/`) e cada aba tem um endereço curto
  (`/entrega`, `/promax`, `/uso`…). A lista fica em `routes/admin_panel.py`
  (`PAINEL_PAGINAS`) e em `js/00-estado.js` (`PANEL_TAB_BY_PATH` / `PANEL_PATH_BY_TAB`).
  Os endereços antigos `/admin/...` redirecionam (`ENDERECOS_ANTIGOS`).
