    function currentPanelPath() {
      const path = window.location.pathname.replace(/\/+$/, "");
      return path || "/";
    }

    function panelTabFromLocation() {
      return PANEL_TAB_BY_PATH[currentPanelPath()] || "operationsTab";
    }

    function panelPathForTab(tabId) {
      return PANEL_PATH_BY_TAB[tabId] || "/";
    }

    // Troca de aba sem recarregar a página: só muda o endereço e mostra a aba.
    // Os dados de cada aba ficam guardados (state.lazyTabs), então voltar a uma
    // aba já aberta é instantâneo.
    function navigatePanelPage(tabId, { replace = false } = {}) {
      const targetPath = panelPathForTab(tabId);
      if (currentPanelPath() !== targetPath) {
        window.history[replace ? "replaceState" : "pushState"]({ tabId }, "", targetPath);
      }
      showPanelTab(tabId);
    }

    function selectInitialPanelPage() {
      showPanelTab(panelTabFromLocation());
    }

    function isPlainLeftClick(event) {
      return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
    }

    // Grupos de abas (Operação, Financeiro, Dados, Admin). Cada <li> de #adminTabs
    // tem data-grupo; só as abas do grupo escolhido aparecem. Se o usuário só tem
    // abas de um grupo, a linha de grupos some e as abas aparecem direto.
    function abaLiberada(item) {
      return Boolean(item) && item.style.display !== "none";
    }

    function grupoDaAba(tabId) {
      const tab = document.getElementById(tabId);
      return tab && tab.parentElement ? String(tab.parentElement.dataset.grupo || "") : "";
    }

    function atualizarGruposAbas() {
      const barra = document.getElementById("panelGroups");
      if (!barra) return;
      const itens = Array.from(document.querySelectorAll("#adminTabs > .nav-item"));
      const ativa = document.querySelector("#adminTabs .nav-link.active");
      const grupoAtivo = ativa ? grupoDaAba(ativa.id) : "";
      const liberadasPorGrupo = {};
      itens.forEach(item => {
        if (!abaLiberada(item)) return;
        const grupo = String(item.dataset.grupo || "");
        (liberadasPorGrupo[grupo] = liberadasPorGrupo[grupo] || []).push(item);
      });
      let grupo = barra.dataset.selecionado || grupoAtivo;
      if (!liberadasPorGrupo[grupo]) grupo = liberadasPorGrupo[grupoAtivo] ? grupoAtivo : (Object.keys(liberadasPorGrupo)[0] || "");
      barra.dataset.selecionado = grupo;
      const botoes = Array.from(barra.querySelectorAll("[data-grupo]"));
      let gruposComAbas = 0;
      botoes.forEach(botao => {
        const temAbas = Boolean(liberadasPorGrupo[botao.dataset.grupo]);
        botao.hidden = !temAbas;
        if (temAbas) gruposComAbas += 1;
        const marcado = botao.dataset.grupo === grupo;
        botao.classList.toggle("active", marcado);
        botao.setAttribute("aria-pressed", marcado ? "true" : "false");
      });
      const agrupar = gruposComAbas > 1;
      barra.hidden = !agrupar;
      itens.forEach(item => item.classList.toggle("fora-do-grupo", agrupar && item.dataset.grupo !== grupo));
      renderNavCelular();
      if (ativa && grupoAtivo) {
        try { localStorage.setItem(`painel_aba_${grupoAtivo}`, ativa.id); } catch (_err) { /* sem armazenamento: ignora */ }
      }
    }

    function setupGruposAbas() {
      const barra = document.getElementById("panelGroups");
      if (!barra) return;
      barra.addEventListener("click", event => {
        const botao = event.target.closest("[data-grupo]");
        if (!botao) return;
        const grupo = String(botao.dataset.grupo || "");
        barra.dataset.selecionado = grupo;
        atualizarGruposAbas();
        const ativa = document.querySelector("#adminTabs .nav-link.active");
        if (ativa && grupoDaAba(ativa.id) === grupo) return;
        let ultima = "";
        try { ultima = localStorage.getItem(`painel_aba_${grupo}`) || ""; } catch (_err) { ultima = ""; }
        const ultimaTab = ultima ? document.getElementById(ultima) : null;
        const destino = ultimaTab && grupoDaAba(ultima) === grupo && abaLiberada(ultimaTab.parentElement)
          ? ultima
          : (Array.from(document.querySelectorAll(`#adminTabs > .nav-item[data-grupo="${grupo}"]`)).find(abaLiberada)?.querySelector(".nav-link")?.id || "");
        if (destino) navigatePanelPage(destino);
      });
      atualizarGruposAbas();
    }

    function setupTabNavigation() {
      document.querySelectorAll("#adminTabs .nav-link[data-admin-page-link='true']").forEach(tab => {
        tab.addEventListener("click", event => {
          if (tab.parentElement && tab.parentElement.style.display === "none") {
            event.preventDefault();
            return;
          }
          // Ctrl/meio-clique continuam abrindo a aba numa nova guia do navegador.
          if (!isPlainLeftClick(event)) return;
          event.preventDefault();
          navigatePanelPage(tab.id);
        });
        tab.addEventListener("shown.bs.tab", event => {
          event.target.scrollIntoView({ block: "nearest", inline: "nearest" });
          document.title = `${event.target.textContent.trim()} · Central Pau Brasil`;
          atualizarGruposAbas();
          syncVisibleTabData({ silent: true });
        });
      });
      window.addEventListener("popstate", () => showPanelTab(panelTabFromLocation()));
    }

    function ensureDevolucoesJustificativasTabs() {
      if (!E.entregaDevolucoesDetails) return;
      if (!document.getElementById('devolucoesSubtabs')) {
        const nav = document.createElement('div');
        nav.id = 'devolucoesSubtabs';
        nav.className = 'd-flex gap-2 flex-wrap mb-3';
        nav.setAttribute('aria-label', 'Visualização de devoluções');
        nav.innerHTML = '<button type="button" class="btn btn-sm" data-dev-tab="analise">Análise</button><button type="button" class="btn btn-sm" data-dev-tab="justificativas">Justificativas e consulta</button>';
        E.entregaDevolucoesDetails.before(nav);
        const panel = document.createElement('section');
        panel.id = 'devolucoesJustificativasPanel';
        panel.className = 'd-none';
        E.entregaDevolucoesDetails.after(panel);
        nav.addEventListener('click', event => {
          const button = event.target.closest('[data-dev-tab]');
          if (!button) return;
          state.devolucoesSubtab = button.dataset.devTab;
          renderEntregaDevolucoes(state.devolucoesOperacionais || {});
          if (state.devolucoesSubtab === 'justificativas') loadDevolucoesJustificativas();
        });
        panel.addEventListener('submit', event => {
          event.preventDefault();
          const filters = Object.fromEntries(new FormData(event.target));
          if (filters.inicio && filters.fim && filters.inicio > filters.fim) {
            panel.querySelector('[name="fim"]').setCustomValidity('A data final deve ser igual ou posterior à inicial.');
            panel.querySelector('[name="fim"]').reportValidity();
            return;
          }
          state.justificativasFilters = filters;
          state.justificativasQuery = panel.querySelector('[name="consulta"]').value.trim();
          loadDevolucoesJustificativas();
        });
        panel.addEventListener('input', event => {
          event.target.setCustomValidity?.('');
          const row = event.target.closest('[data-dev-record]');
          if (!row) return;
          state.justificativasDrafts ||= {};
          state.justificativasDrafts[row.dataset.devId] = {
            text: row.querySelector('[data-dev-text]').value,
            plan: row.querySelector('[data-dev-plan]').value,
          };
        });
        panel.addEventListener('click', async event => {
          if (event.target.closest('[data-dev-clear]')) {
            state.justificativasFilters = {};
            state.justificativasQuery = '';
            loadDevolucoesJustificativas();
            return;
          }
          if (event.target.closest('[data-dev-export]')) { exportDevolucoesJustificativas(); return; }
          const button = event.target.closest('[data-dev-save]');
          if (!button) return;
          const box = button.closest('[data-dev-record]');
          const text = box.querySelector('[data-dev-text]').value.trim();
          const actionPlan = box.querySelector('[data-dev-plan]').value.trim();
          const message = box.querySelector('[role="status"]');
          if (!text) { message.textContent = 'Informe a justificativa.'; return; }
          button.disabled = true;
          try {
            const result = await req('/api/admin/liga-entrega/devolucoes/justificativas/' + encodeURIComponent(button.dataset.devSave), {
              method: 'PUT', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({competencia: state.devolucoesOperacionais?.competencia || ensureLigaMesFilter(), texto: text, plano_acao: actionPlan, version: button.dataset.version || ''})
            });
            const item = result.item;
            (state.devolucoesOperacionais?.rows || []).forEach(row => { if (row.justificativa_id === item.id) row.justificativa = item; });
            state.justificativasSaved = [item, ...(state.justificativasSaved || []).filter(r => r.id !== item.id)];
            if (state.justificativasDrafts) delete state.justificativasDrafts[item.id];
            renderDevolucoesJustificativas();
            addLog('Justificativa e plano de ação salvos.', 'ok');
          } catch (err) { message.textContent = err.message; }
          finally { button.disabled = false; }
        });
      }
      const active = state.devolucoesSubtab === 'justificativas';
      E.entregaDevolucoesDetails.classList.toggle('d-none', active);
      if (E.entregaDevolucoesCards) E.entregaDevolucoesCards.classList.toggle('d-none', active);
      document.getElementById('devolucoesJustificativasPanel').classList.toggle('d-none', !active);
      document.querySelectorAll('[data-dev-tab]').forEach(b => {
        const selected = b.dataset.devTab === (active ? 'justificativas' : 'analise');
        b.className = 'btn btn-sm ' + (selected ? 'btn-primary' : 'btn-outline-primary');
        b.setAttribute('aria-pressed', String(selected));
      });
    }

    async function loadDevolucoesJustificativas() {
      const query = state.justificativasQuery || '';
      const requestId = (state.justificativasRequestId || 0) + 1;
      state.justificativasRequestId = requestId;
      try {
        const params = new URLSearchParams({q: query});
        for (const key of ['filial', 'inicio', 'fim', 'status', 'plano']) {
          const value = state.justificativasFilters?.[key];
          if (value) params.set(key, value);
        }
        const result = await req('/api/admin/liga-entrega/devolucoes/justificativas?' + params);
        if (state.justificativasRequestId !== requestId) return;
        state.justificativasSaved = result.items || [];
        state.justificativasTotal = result.total || 0;
        state.justificativasError = '';
      } catch (err) { state.justificativasError = err.message; }
      if (state.devolucoesSubtab === 'justificativas') renderDevolucoesJustificativas();
    }

    function renderDevolucoesJustificativas() {
      const panel = document.getElementById('devolucoesJustificativasPanel');
      if (!panel) return;
      const normalizeQuery = value => String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR');
      const query = normalizeQuery(state.justificativasQuery);
      const records = new Map();
      (state.devolucoesOperacionais?.rows || []).forEach(row => {
        if (row.justificativa_id) records.set(row.justificativa_id, {id: row.justificativa_id, devolucao: row, ...(row.justificativa || {})});
      });
      (state.justificativasSaved || []).forEach(item => records.set(item.id, item));
      const rows = [...records.values()].filter(item => !query || normalizeQuery(JSON.stringify(item)).includes(query));
      const filters = state.justificativasFilters || {};
      const filteredRows = rows.filter(item => {
        const row = item.devolucao || {};
        const day = String(row.data_devolucao || row.data || '').slice(0, 10);
        return (!filters.filial || row.filial === filters.filial) &&
          (!filters.inicio || day >= filters.inicio) && (!filters.fim || day && day <= filters.fim) &&
          (!filters.status || Boolean(item.text?.trim()) === (filters.status === 'justificada')) &&
          (!filters.plano || Boolean(item.action_plan?.trim()) === (filters.plano === 'com'));
      });
      state.justificativasVisibleRows = filteredRows;
      const selectFilter = (key, label, options) => `<div><label class="small form-label mb-1" for="dev-filter-${key}">${label}</label><select id="dev-filter-${key}" name="${key}" class="form-select form-select-sm">${options.map(([value, text]) => `<option value="${escapeHtml(value)}" ${filters[key] === value ? 'selected' : ''}>${escapeHtml(text)}</option>`).join('')}</select></div>`;
      const branches = [...new Set([...records.values()].map(r => r.devolucao?.filial).filter(Boolean)), 'PATOS', 'SUME'];
      if (filters.filial) branches.push(filters.filial);
      const controls = `<div class="d-flex align-items-end flex-wrap gap-2 mb-2">${selectFilter('filial', 'Filial', [['', 'Todas'], ...[...new Set(branches)].sort().map(v => [v, v])])}<div><label class="small form-label mb-1" for="dev-filter-inicio">Devolução de</label><input id="dev-filter-inicio" name="inicio" type="date" class="form-control form-control-sm" value="${escapeHtml(filters.inicio || '')}"></div><div><label class="small form-label mb-1" for="dev-filter-fim">Até</label><input id="dev-filter-fim" name="fim" type="date" class="form-control form-control-sm" value="${escapeHtml(filters.fim || '')}"></div>${selectFilter('status', 'Justificativa', [['', 'Todas'], ['pendente', 'Pendentes'], ['justificada', 'Justificadas']])}${selectFilter('plano', 'Plano de ação', [['', 'Todos'], ['com', 'Com plano'], ['sem', 'Sem plano']])}<button type="button" class="btn btn-sm btn-outline-secondary" data-dev-clear>Limpar filtros</button><button type="button" class="btn btn-sm btn-outline-primary" data-dev-export ${!filteredRows.length ? 'disabled' : ''}>Exportar tabela (CSV)</button></div>`;
      panel.innerHTML = `<form class="mb-2">${controls}<div class="d-flex align-items-center gap-2"><label class="visually-hidden" for="devolucaoConsulta">Consultar devolução ou justificativa</label><input id="devolucaoConsulta" name="consulta" class="form-control form-control-sm" maxlength="200" value="${escapeHtml(state.justificativasQuery || '')}" placeholder="Cliente, nota, data, justificativa ou plano de ação"><button class="btn btn-sm btn-outline-primary" type="submit">Aplicar filtros</button></div></form><div role="status" class="small text-secondary mb-2">${escapeHtml(state.justificativasError || `${filteredRows.length} registro(s) exibido(s) e exportado(s) · Salvas de todos os meses (até 200 por consulta); pendentes da competência selecionada.`)}</div><div class="table-responsive"><table class="table table-sm table-hover align-middle mb-0"><thead><tr><th>Devolução</th><th>Filial</th><th>Nota / série</th><th>Cliente</th><th>Status</th><th>Justificativa</th><th>Plano de ação</th><th></th></tr></thead><tbody>${filteredRows.map(item => {
        const row = item.devolucao || {};
        const id = escapeHtml(item.id);
        const draft = state.justificativasDrafts?.[item.id];
        return `<tr data-dev-record data-dev-id="${id}"><td class="text-nowrap">${escapeHtml(formatDate(row.data_devolucao || row.data))}</td><td>${escapeHtml(row.filial || '-')}</td><td class="text-nowrap">${escapeHtml(row.nota || '-')} / ${escapeHtml(row.serie || '-')}</td><td style="max-width:230px"><span class="small text-secondary">${escapeHtml(row.cliente_cod || '-')}</span> ${escapeHtml(row.cliente || '-')}<div class="small text-secondary mt-1">${escapeHtml(row.motorista || row.cod || '-')} · ${escapeHtml(row.motivo_operacional || row.motivo || row.resp || '-')}</div></td><td><span class="badge ${item.text ? 'text-bg-success' : 'text-bg-warning'}">${item.text ? 'Justificada' : 'Pendente'}</span></td><td style="min-width:220px"><label class="visually-hidden" for="justificativa-${id}">Justificativa da nota ${escapeHtml(row.nota || '')}</label><textarea id="justificativa-${id}" data-dev-text class="form-control form-control-sm" rows="2" maxlength="5000" style="resize:vertical" placeholder="Informe a justificativa">${escapeHtml(draft?.text ?? item.text ?? '')}</textarea></td><td style="min-width:220px"><label class="visually-hidden" for="plano-${id}">Plano de ação da nota ${escapeHtml(row.nota || '')}</label><textarea id="plano-${id}" data-dev-plan class="form-control form-control-sm" rows="2" maxlength="5000" style="resize:vertical" placeholder="Descreva o plano de ação">${escapeHtml(draft?.plan ?? item.action_plan ?? '')}</textarea></td><td><button class="btn btn-sm btn-primary" type="button" data-dev-save="${id}" data-version="${escapeHtml(item.version || '')}">Salvar</button><div role="status" class="small mt-1"></div>${item.text ? `<details class="mt-1"><summary class="small text-secondary">Histórico</summary><div class="small text-secondary">${escapeHtml(item.updated_by || '')} · ${escapeHtml(item.updated_at || '')}</div>${(item.history || []).slice().reverse().map(h => `<div class="border-top py-2 small" style="white-space:pre-wrap"><b>${escapeHtml(h.at)} · ${escapeHtml(h.actor)}</b><br>Justificativa: ${escapeHtml(h.text)}<br>Plano: ${escapeHtml(h.action_plan || 'Não informado')}</div>`).join('')}</details>` : ''}</td></tr>`;
      }).join('') || '<tr><td colspan="8" class="text-center text-secondary py-3">Nenhuma devolução encontrada. Selecione a competência para consultar outras pendências.</td></tr>'}</tbody></table></div>`;
    }

    function exportDevolucoesJustificativas() {
      const rows = state.justificativasVisibleRows || [];
      if (!rows.length) return;
      const columns = ['Data da devolução', 'Filial', 'Nota', 'Série', 'Código do cliente', 'Cliente', 'Motorista', 'Motivo', 'Status', 'Justificativa', 'Plano de ação', 'Atualizado por', 'Atualizado em'];
      const csvCell = value => {
        let text = String(value ?? '');
        // Evita executar fórmulas ao abrir dados importados/texto livre no Excel.
        if (/^[\s]*[=+@-]/.test(text) || /^[\t\r\n]/.test(text)) text = "'" + text;
        return '"' + text.replace(/"/g, '""') + '"';
      };
      const data = rows.map(item => {
        const row = item.devolucao || {};
        return [row.data_devolucao || row.data, row.filial, row.nota, row.serie, row.cliente_cod, row.cliente, row.motorista || row.cod, row.motivo_operacional || row.motivo || row.resp, item.text ? 'Justificada' : 'Pendente', item.text, item.action_plan, item.updated_by, item.updated_at];
      });
      const csv = '\uFEFF' + [columns, ...data].map(row => row.map(csvCell).join(';')).join('\r\n');
      const url = URL.createObjectURL(new Blob([csv], {type: 'text/csv;charset=utf-8;'}));
      const link = document.createElement('a');
      link.href = url;
      link.download = 'devolucoes_justificativas_' + new Date().toISOString().slice(0, 10) + '.csv';
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    async function syncDevolucoesOperacionais({ silent = true } = {}) {
      if (!hasPanelAuth()) return;
      try {
        const competencia = ensureLigaMesFilter();
        const query = competencia ? `?competencia=${encodeURIComponent(competencia)}` : "";
        state.devolucoesOperacionais = await req(`${CONFIG.endpoints.ligaEntrega.devolucoes}${query}`, { timeoutMs: 30000 }) || {};
        renderEntregaDevolucoes(state.devolucoesOperacionais);
        if (!silent) addLog("Devoluções operacionais atualizadas.", "ok");
      } catch (err) {
        if (E.entregaDevolucoesStatus) E.entregaDevolucoesStatus.textContent = `Falha ao carregar devoluções: ${err.message}`;
        if (!silent) addLog(`Falha ao carregar devoluções: ${err.message}`, "err");
      }
    }

    function renderDevolucoesCadastros(data = state.devolucoesCadastros || {}) {
      if (!E.entregaDevolucoesCadastrosDetails) return;
      const operation = String(state.devolucoesCadastrosOperation || "").trim().toUpperCase();
      const operations = data.catalogo && Array.isArray(data.catalogo.operacoes) ? data.catalogo.operacoes : [];
      const sourceRows = Array.isArray(state.devolucoesOperacionais?.rows) ? state.devolucoesOperacionais.rows : [];
      const hydrate = (kind, codeField) => {
        const existing = Array.isArray(data[kind]) ? data[kind] : [];
        const indexed = new Map(existing.map(item => [`${String(item.filial || "").toUpperCase()}|${String(item.codigo || "")}`, item]));
        (data.catalogo && Array.isArray(data.catalogo[kind]) ? data.catalogo[kind] : []).forEach(item => {
          const filial = String(item.filial || "").trim().toUpperCase();
          const codigo = String(item.codigo || "").trim();
          if (codigo && !indexed.has(`${filial}|${codigo}`)) indexed.set(`${filial}|${codigo}`, { filial, codigo, nome: "" });
        });
        sourceRows.forEach(row => {
          const filial = String(row.filial || "").trim().toUpperCase();
          const codigo = String(row[codeField] || "").trim();
          if (!codigo) return;
          const key = `${filial}|${codigo}`;
          if (!indexed.has(key)) indexed.set(key, { filial, codigo, nome: "" });
        });
        return [...indexed.values()].sort((a, b) => String(a.filial).localeCompare(String(b.filial), "pt-BR") || String(a.codigo).localeCompare(String(b.codigo), "pt-BR", { numeric: true }));
      };
      const visible = { setores: hydrate("setores", "setor"), gerentes: hydrate("gerentes", "gv") };
      const table = (kind, title) => {
        const rows = visible[kind].filter(row => !operation || String(row.filial || "").trim().toUpperCase() === operation);
        const body = rows.map(row => `<tr><td><input class="form-control form-control-sm dev-cadastro-filial" value="${escapeHtml(row.filial || "")}" placeholder="Todas/PATOS/SUME"></td><td><input class="form-control form-control-sm dev-cadastro-codigo" value="${escapeHtml(row.codigo || "")}" placeholder="Código"></td><td><input class="form-control form-control-sm dev-cadastro-nome" value="${escapeHtml(row.nome || "")}" placeholder="Nome exibido"></td><td><button type="button" class="btn btn-outline-danger btn-sm dev-cadastro-remove" data-kind="${kind}" data-key="${escapeHtml(`${row.filial || ""}|${row.codigo || ""}`)}">Remover</button></td></tr>`).join("");
        return `<div class="mb-4"><div class="d-flex justify-content-between align-items-center mb-2"><h3 class="h6 mb-0">${title}</h3><button type="button" class="btn btn-outline-primary btn-sm dev-cadastro-add" data-kind="${kind}">Adicionar</button></div><div class="table-scroll"><table class="table table-sm align-middle"><thead><tr><th>Filial</th><th>Código</th><th>Nome exibido</th><th></th></tr></thead><tbody data-kind="${kind}">${body || '<tr><td colspan="4" class="text-secondary">Nenhum cadastro.</td></tr>'}</tbody></table></div></div>`;
      };
      E.entregaDevolucoesCadastrosDetails.innerHTML = `<div class="d-flex flex-wrap gap-3 align-items-end mb-3"><div style="min-width:260px"><label class="form-label" for="devolucoesCadastrosOperation">Operação</label><select class="form-select form-select-sm" id="devolucoesCadastrosOperation"><option value="">Selecione uma operação</option>${operations.map(item => `<option value="${escapeHtml(item.codigo || "")}" ${operation === String(item.codigo || "").toUpperCase() ? "selected" : ""}>${escapeHtml(`${item.codigo || ""} - ${item.nome || ""}`)}</option>`).join("")}</select></div><div class="form-text mb-1">Escolha a operação para editar somente seus setores e GVs.</div></div><div class="form-text mb-3">A lista usa todo o cadastro ativo da dSetores; os códigos que aparecem nas devoluções do mês também são mantidos. Preencha apenas o nome exibido.</div>${operation ? `${table("setores", "Setores")} ${table("gerentes", "Gerentes (GV)")}` : '<div class="text-secondary py-4">Selecione uma operação acima para visualizar os setores e GVs.</div>'}`;
    }

    async function syncDevolucoesCadastros() {
      state.devolucoesCadastros = await req(CONFIG.endpoints.ligaEntrega.devolucoesCadastros, { timeoutMs: 30000 }) || { setores: [], gerentes: [], catalogo: { operacoes: [] } };
      renderDevolucoesCadastros();
    }

    function readDevolucoesCadastros() {
      const operation = String(state.devolucoesCadastrosOperation || "").trim().toUpperCase();
      const read = kind => [...(E.entregaDevolucoesCadastrosDetails?.querySelectorAll(`tbody[data-kind="${kind}"] tr`) || [])].map(row => ({
        filial: row.querySelector(".dev-cadastro-filial")?.value || "", codigo: row.querySelector(".dev-cadastro-codigo")?.value || "", nome: row.querySelector(".dev-cadastro-nome")?.value || ""
      })).filter(row => row.codigo.trim() || row.nome.trim());
      const merge = kind => [
        ...(Array.isArray(state.devolucoesCadastros?.[kind]) ? state.devolucoesCadastros[kind] : []).filter(item => String(item.filial || "").trim().toUpperCase() !== operation),
        ...read(kind),
      ];
      return { setores: merge("setores"), gerentes: merge("gerentes") };
    }

    function normalizeSearchText(value) {
      return String(value || "")
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .toLowerCase();
    }

    function formatQty(value) {
      const n = Number(String(value ?? "0").replace(",", "."));
      if (!Number.isFinite(n)) return "0";
      return n.toLocaleString("pt-BR", { maximumFractionDigits: 3 });
    }

    function setupNumberInputWheelGuard() {
      document.addEventListener("wheel", event => {
        const target = event.target;
        if (!(target instanceof HTMLInputElement) || target.type !== "number") return;
        event.preventDefault();
      }, { passive: false });
    }

    // Grade de números em que tudo é zero ou "--" vira uma mensagem só.
    // Evita mostrar 11 cartões com "0,00" antes de haver dados.
    const GRADE_NUMEROS_SELETOR = ".recolha-dashboard-grid, .usage-metric-grid";
    const GRADE_VAZIA_MSG = "Sem números para mostrar ainda. Ajuste os filtros e clique em Atualizar.";

    function gradeNumerosVazia(grade) {
      const valores = [...grade.querySelectorAll(".value")];
      if (!valores.length) return false;
      return valores.every(item => /^(R\$\s*)?[-–—0.,\s/%]*$/.test(item.textContent.trim()));
    }

    function atualizarGradesVazias() {
      document.querySelectorAll(GRADE_NUMEROS_SELETOR).forEach(grade => {
        if (!grade.hasAttribute("data-vazio-msg")) grade.setAttribute("data-vazio-msg", GRADE_VAZIA_MSG);
        grade.toggleAttribute("data-vazio", gradeNumerosVazia(grade));
      });
    }

    function setupEmptyKpiGrids() {
      let agendado = false;
      const observer = new MutationObserver(() => {
        if (agendado) return;
        agendado = true;
        requestAnimationFrame(() => { agendado = false; atualizarGradesVazias(); });
      });
      observer.observe(document.body, { childList: true, subtree: true, characterData: true });
      atualizarGradesVazias();
    }

    function init() {
      applyTheme(localStorage.getItem("bot_admin_theme") || "dark");
      setupNumberInputWheelGuard();
      setupEmptyKpiGrids();
      setupRecolhasPane();
      setupPayipPane();
      selectInitialPanelPage();
      setupTabNavigation();
      setupGruposAbas();

      localStorage.removeItem("bot_api_token");
      localStorage.removeItem("bot_admin_token");

      updateTokens();
      buildGrid();
      buildRolesOption();
      updateScopeHint();
      updateMetrics();
      renderEvolutionUsage();
      ensureGiroRecolhaSection();
      renderGiroRecolha();
      renderGiroRecolhaRoutes();
      renderCriticaDashboard();
      renderRecolhas();
      renderPayipBatch();
      renderProtestos();
      financeiroRender();
      renderPanelUserFeatureChecks();
      setupAllowedUsersCardSizing();
      ensureUsageFunctionDateRange();
      const today = formatDateInputValue(new Date());
      if (E.promaxStartDate && !E.promaxStartDate.value) E.promaxStartDate.value = today;
      if (E.promaxEndDate && !E.promaxEndDate.value) E.promaxEndDate.value = today;
      if (E.promaxScheduleStartDate && !E.promaxScheduleStartDate.value) E.promaxScheduleStartDate.value = today;
      if (E.promaxScheduleEndDate && !E.promaxScheduleEndDate.value) E.promaxScheduleEndDate.value = today;
      if (E.armazemGradeAuditDate && !E.armazemGradeAuditDate.value) E.armazemGradeAuditDate.value = today;
      if (E.promaxGradeManualDate && !E.promaxGradeManualDate.value) E.promaxGradeManualDate.value = today;
      addPromaxGrade020304ManualRow();
      addPromaxGradeManualRow();
      syncPromaxJobDateBounds();
      syncPromaxDateFields();
      syncPromaxScheduleFields();
      setupPromaxScheduleSlicerEvents("run");
      setupPromaxScheduleSlicerEvents("schedule");
      setupFinanceiroEvents();
      setupConferenciaControls();
      renderPromax();

      document.getElementById("refreshBtn").addEventListener("click", syncAll);
      E.themeToggle.addEventListener("click", toggleTheme);
      if (E.logoutBtn) E.logoutBtn.addEventListener("click", logoutPanel);
      if (E.promaxRefreshBtn) E.promaxRefreshBtn.addEventListener("click", () => syncPromax({ silent: false }));
      if (E.promaxPauseBtn) E.promaxPauseBtn.addEventListener("click", () => promaxQueueAction("pause"));
      if (E.promaxResumeBtn) E.promaxResumeBtn.addEventListener("click", () => promaxQueueAction("resume"));
      if (E.promaxClearBtn) E.promaxClearBtn.addEventListener("click", () => promaxQueueAction("pending"));
      if (E.promaxReprocessPublicationsBtn) E.promaxReprocessPublicationsBtn.addEventListener("click", promaxReprocessPublications);
      if (E.promaxSaveWorkerAssignmentsBtn) E.promaxSaveWorkerAssignmentsBtn.addEventListener("click", savePromaxWorkerAssignments);
      if (E.promaxCredentialsBody) E.promaxCredentialsBody.addEventListener("click", event => {
        const button = event.target.closest(".promax-save-credential");
        if (button) savePromaxCredentials(button.closest("tr"));
      });
      if (E.promaxCredentialsBody) E.promaxCredentialsBody.addEventListener("input", event => {
        const input = event.target.closest(".promax-credential-username");
        const row = input && input.closest("tr");
        const workerId = String(row && row.dataset.workerId || "").trim();
        if (workerId) state.promax.credentialUserDrafts[workerId] = input.value;
      });
      if (E.promaxRunBtn) E.promaxRunBtn.addEventListener("click", promaxRunNow);
      document.querySelectorAll("[data-armazem-routine]").forEach(button => button.addEventListener("click", () => setArmazemRoutine(button.dataset.armazemRoutine)));
      if (E.promaxGradeFile) E.promaxGradeFile.addEventListener("change", () => previewArmazemCsv(E.promaxGradeFile.files[0], E.promaxGradeStatus, "020105"));
      if (E.promaxGrade020304File) E.promaxGrade020304File.addEventListener("change", () => previewArmazemCsv(E.promaxGrade020304File.files[0], E.promaxGrade020304Status, "020304"));
      if (E.promaxGradeQueueBtn) E.promaxGradeQueueBtn.addEventListener("click", promaxQueueGradeCsv);
      if (E.promaxGrade020304QueueBtn) E.promaxGrade020304QueueBtn.addEventListener("click", promaxQueueGrade020304Csv);
      if (E.promaxGrade020304TemplateBtn) E.promaxGrade020304TemplateBtn.addEventListener("click", () => downloadGradeTemplate("modelo_grade_020304.csv", "grade;produto;quantidade\n1;9092;0\n1;10175;0\n1;8919;0\n"));
      if (E.promaxGradeTemplateBtn) E.promaxGradeTemplateBtn.addEventListener("click", () => downloadGradeTemplate("modelo_grade_020105.csv", "armazem;deposito;data_movimento;item;pallet;lastro;sku;unidade;garrafa\n01;02;08/10/2026;22177;0;0;1;0;\n"));
      if (E.promaxGrade020304AddRowBtn) E.promaxGrade020304AddRowBtn.addEventListener("click", () => addPromaxGrade020304ManualRow());
      if (E.promaxGradeAddRowBtn) E.promaxGradeAddRowBtn.addEventListener("click", () => addPromaxGradeManualRow());
      if (E.promaxGrade020304ManualRows) E.promaxGrade020304ManualRows.addEventListener("click", event => { const button = event.target.closest("[data-remove-grade-020304-row]"); if (button) { button.closest("tr").remove(); if (!E.promaxGrade020304ManualRows.children.length) addPromaxGrade020304ManualRow(); } });
      if (E.promaxGradeManualRows) E.promaxGradeManualRows.addEventListener("click", event => { const button = event.target.closest("[data-remove-grade-row]"); if (button) { button.closest("tr").remove(); if (!E.promaxGradeManualRows.children.length) addPromaxGradeManualRow(); } });
      if (E.promaxGrade020304ManualQueueBtn) E.promaxGrade020304ManualQueueBtn.addEventListener("click", queuePromaxGrade020304Manual);
      if (E.promaxGradeManualQueueBtn) E.promaxGradeManualQueueBtn.addEventListener("click", queuePromaxGradeManual);
      if (E.armazemGradeAuditDate) E.armazemGradeAuditDate.addEventListener("change", () => {
        state.promax.selectedGrade020304AuditJobId = "";
        syncArmazemGradeAudit({ silent: false });
      });
      if (E.armazemGradeAuditTodayBtn) E.armazemGradeAuditTodayBtn.addEventListener("click", () => {
        E.armazemGradeAuditDate.value = formatDateInputValue(new Date());
        state.promax.selectedGrade020304AuditJobId = "";
        syncArmazemGradeAudit({ silent: false });
      });
      if (E.armazemGradeAuditSearch) E.armazemGradeAuditSearch.addEventListener("input", () => renderArmazemGradeAudit());
      if (E.armazemGradeAuditErrorsOnly) E.armazemGradeAuditErrorsOnly.addEventListener("change", () => renderArmazemGradeAudit());
      if (E.entregaOpenLigaPromaxBtn) E.entregaOpenLigaPromaxBtn.addEventListener("click", openLigaEntregaPromax);
      if (E.entregaLigaReportsRefreshBtn) E.entregaLigaReportsRefreshBtn.addEventListener("click", () => syncLigaEntregaReports({ silent: false, force: true }));
      if (E.entregaLigaPeriodo) E.entregaLigaPeriodo.addEventListener("change", () => {
        syncLigaEntregaReports({ silent: false, force: true });
        syncIndicadores({ silent: false });
        syncJornadaMapas({ silent: false });
        syncMapasMensais({ silent: false });
        syncMapasOperacionais({ silent: false });
      });
      if (E.entregaLigaMes) {
        ensureLigaMesFilter();
        E.entregaLigaMes.addEventListener("change", () => {
          syncLigaEntregaReports({ silent: false, force: true });
          syncIndicadores({ silent: false });
          syncJornadaMapas({ silent: false });
          syncMapasMensais({ silent: false });
          syncMapasOperacionais({ silent: false });
        });
      }
      if (E.entregaLigaModuleTab) E.entregaLigaModuleTab.addEventListener("click", () => setEntregaModule("liga"));
      if (E.entregaIndicadoresModuleTab) E.entregaIndicadoresModuleTab.addEventListener("click", () => setEntregaModule("indicadores"));
      if (E.entregaFechamentoModuleTab) E.entregaFechamentoModuleTab.addEventListener("click", () => setEntregaModule("fechamento"));
      if (E.entregaIndicadoresRefreshBtn) E.entregaIndicadoresRefreshBtn.addEventListener("click", () => syncIndicadores({ silent: false }));
      [E.entregaIndicadoresFilial, E.entregaIndicadoresSituacao].forEach(input => input?.addEventListener("change", () => renderIndicadores(state.ligaIndicadores || {})));
      if (E.entregaIndicadoresLimparFiltrosBtn) E.entregaIndicadoresLimparFiltrosBtn.addEventListener("click", () => {
        if (E.entregaIndicadoresFilial) E.entregaIndicadoresFilial.value = "";
        if (E.entregaIndicadoresSituacao) E.entregaIndicadoresSituacao.value = "";
        renderIndicadores(state.ligaIndicadores || {});
      });
      if (E.entregaJornadaMapasRefreshBtn) E.entregaJornadaMapasRefreshBtn.addEventListener("click", () => syncJornadaMapas({ silent: false }));
      [E.entregaJornadaMapasFilial, E.entregaJornadaMapasJustificativa, E.entregaJornadaMapasDevolucao, E.entregaJornadaMapasOrdem, E.entregaJornadaMapasDe, E.entregaJornadaMapasAte].forEach(input => input?.addEventListener("change", () => renderJornadaMapas(state.ligaJornadaMapas || {})));
      if (E.entregaJornadaMapasBusca) E.entregaJornadaMapasBusca.addEventListener("input", () => renderJornadaMapas(state.ligaJornadaMapas || {}));
      if (E.entregaJornadaMapasLimparFiltrosBtn) E.entregaJornadaMapasLimparFiltrosBtn.addEventListener("click", () => {
        [E.entregaJornadaMapasFilial, E.entregaJornadaMapasJustificativa, E.entregaJornadaMapasDevolucao, E.entregaJornadaMapasBusca, E.entregaJornadaMapasDe, E.entregaJornadaMapasAte].forEach(input => { if (input) input.value = ""; });
        if (E.entregaJornadaMapasOrdem) E.entregaJornadaMapasOrdem.value = "data";
        renderJornadaMapas(state.ligaJornadaMapas || {});
      });
      [E.entregaOcupacaoVeiculosFilial, E.entregaOcupacaoVeiculosComparacao, E.entregaOcupacaoVeiculosValor, E.entregaOcupacaoVeiculosJustificativa, E.entregaOcupacaoVeiculosDe, E.entregaOcupacaoVeiculosAte, E.entregaOcupacaoVeiculosOrdem].forEach(input => input?.addEventListener("change", () => renderOcupacaoVeiculos(state.ligaJornadaMapas || {})));
      if (E.entregaOcupacaoVeiculosBusca) E.entregaOcupacaoVeiculosBusca.addEventListener("input", () => renderOcupacaoVeiculos(state.ligaJornadaMapas || {}));
      if (E.entregaOcupacaoVeiculosLimparFiltrosBtn) E.entregaOcupacaoVeiculosLimparFiltrosBtn.addEventListener("click", () => {
        if (E.entregaOcupacaoVeiculosFilial) E.entregaOcupacaoVeiculosFilial.value = "";
        if (E.entregaOcupacaoVeiculosComparacao) E.entregaOcupacaoVeiculosComparacao.value = "maior_igual";
        if (E.entregaOcupacaoVeiculosValor) E.entregaOcupacaoVeiculosValor.value = "0";
        if (E.entregaOcupacaoVeiculosBusca) E.entregaOcupacaoVeiculosBusca.value = "";
        if (E.entregaOcupacaoVeiculosJustificativa) E.entregaOcupacaoVeiculosJustificativa.value = "";
        [E.entregaOcupacaoVeiculosDe, E.entregaOcupacaoVeiculosAte].forEach(input => { if (input) input.value = ""; });
        if (E.entregaOcupacaoVeiculosOrdem) E.entregaOcupacaoVeiculosOrdem.value = "data";
        renderOcupacaoVeiculos(state.ligaJornadaMapas || {});
      });
      setupOpsJustificativaLargura();
      [E.entregaJornadaMapasBody, E.entregaOcupacaoVeiculosBody].forEach(body => {
        if (!body) return;
        body.addEventListener("input", event => { if (event.target.classList.contains("jornada-mapa-justificativa")) opsAjustarAltura(event.target); });
        body.addEventListener("click", event => {
          const button = event.target.closest(".jornada-mapa-salvar");
          if (button) saveJornadaMapaJustificativa(button);
        });
        body.addEventListener("keydown", event => {
          // Enter salva; Shift+Enter quebra a linha na justificativa.
          if (event.key !== "Enter" || event.shiftKey || !event.target.classList.contains("jornada-mapa-justificativa")) return;
          event.preventDefault();
          const button = event.target.closest(".ops-just")?.querySelector(".jornada-mapa-salvar");
          if (button) saveJornadaMapaJustificativa(button);
        });
      });
      if (E.entregaMapasMensaisRefreshBtn) E.entregaMapasMensaisRefreshBtn.addEventListener("click", () => syncMapasMensais({ silent: false }));
      if (E.entregaMapasOperacionaisRefreshBtn) E.entregaMapasOperacionaisRefreshBtn.addEventListener("click", () => syncMapasOperacionais({ silent: false }));
      if (E.entregaMapasOperacionaisPdfBtn) E.entregaMapasOperacionaisPdfBtn.addEventListener("click", downloadMapasOperacionaisPdf);
      [E.entregaMapasOperacionaisDataInicio, E.entregaMapasOperacionaisDataFim].forEach(input => input?.addEventListener("change", () => renderMapasOperacionais(state.ligaMapasOperacionais || {})));
      [E.entregaMapasOperacionaisFilial, E.entregaMapasOperacionaisSituacao, E.entregaMapasOperacionaisAlertas].forEach(input => input?.addEventListener("change", () => renderMapasOperacionais(state.ligaMapasOperacionais || {})));
      if (E.entregaMapasOperacionaisBusca) E.entregaMapasOperacionaisBusca.addEventListener("input", () => renderMapasOperacionais(state.ligaMapasOperacionais || {}));
      if (E.entregaMapasOperacionaisTodasDatasBtn) E.entregaMapasOperacionaisTodasDatasBtn.addEventListener("click", () => {
        if (E.entregaMapasOperacionaisDataInicio) E.entregaMapasOperacionaisDataInicio.value = "";
        if (E.entregaMapasOperacionaisDataFim) E.entregaMapasOperacionaisDataFim.value = "";
        state.ligaMapasOperacionaisSelectedDays = (state.ligaMapasOperacionais?.days || []).map(day => day.data).filter(Boolean);
        renderMapasOperacionais(state.ligaMapasOperacionais || {});
      });
      if (E.entregaMapasOperacionaisLimparFiltrosBtn) E.entregaMapasOperacionaisLimparFiltrosBtn.addEventListener("click", () => {
        [E.entregaMapasOperacionaisDataInicio, E.entregaMapasOperacionaisDataFim, E.entregaMapasOperacionaisFilial, E.entregaMapasOperacionaisSituacao, E.entregaMapasOperacionaisAlertas, E.entregaMapasOperacionaisBusca].forEach(input => { if (input) input.value = ""; });
        renderMapasOperacionais(state.ligaMapasOperacionais || {});
      });
      if (E.entregaMapasOperacionaisDias) E.entregaMapasOperacionaisDias.addEventListener("click", event => {
        const button = event.target.closest("[data-fechamento-dia]");
        if (!button) return;
        const selected = new Set(Array.isArray(state.ligaMapasOperacionaisSelectedDays) ? state.ligaMapasOperacionaisSelectedDays : []);
        const day = String(button.dataset.fechamentoDia || "");
        if (selected.has(day)) selected.delete(day); else selected.add(day);
        state.ligaMapasOperacionaisSelectedDays = [...selected];
        renderMapasOperacionais(state.ligaMapasOperacionais || {});
      });
      if (E.entregaMapasOperacionaisSelecionarTodosBtn) E.entregaMapasOperacionaisSelecionarTodosBtn.addEventListener("click", () => {
        state.ligaMapasOperacionaisSelectedDays = (state.ligaMapasOperacionais?.days || []).map(day => day.data).filter(Boolean);
        renderMapasOperacionais(state.ligaMapasOperacionais || {});
      });
      if (E.entregaMapasOperacionaisLimparDiasBtn) E.entregaMapasOperacionaisLimparDiasBtn.addEventListener("click", () => {
        state.ligaMapasOperacionaisSelectedDays = [];
        renderMapasOperacionais(state.ligaMapasOperacionais || {});
      });
      if (E.entregaLigaCollapseBtn) E.entregaLigaCollapseBtn.addEventListener("click", () => {
        const collapsed = E.entregaLigaModule && E.entregaLigaModule.classList.toggle("is-collapsed");
        E.entregaLigaCollapseBtn.setAttribute("aria-expanded", String(!collapsed));
        E.entregaLigaCollapseBtn.innerHTML = collapsed
          ? '<i class="bi bi-chevron-down me-1"></i>Restaurar'
          : '<i class="bi bi-chevron-up me-1"></i>Minimizar';
      });
      if (E.entregaDevolucoesModuleTab) E.entregaDevolucoesModuleTab.addEventListener("click", () => setEntregaModule("devolucoes"));
      if (E.entregaDevolucoesCadastrosModuleTab) E.entregaDevolucoesCadastrosModuleTab.addEventListener("click", () => setEntregaModule("devolucoes-cadastros"));
      if (E.entregaFrotaModuleTab) E.entregaFrotaModuleTab.addEventListener("click", () => setEntregaModule("frota"));
      if (E.entregaFrotaSaveBtn) E.entregaFrotaSaveBtn.addEventListener("click", saveEntregaFrota);
      if (E.entregaMetasModuleTab) E.entregaMetasModuleTab.addEventListener("click", () => setEntregaModule("metas"));
      if (E.entregaMetasSaveBtn) E.entregaMetasSaveBtn.addEventListener("click", saveEntregaMetas);
      if (E.entregaFrotaDetails) E.entregaFrotaDetails.addEventListener("click", event => {
        const add = event.target.closest(".frota-adicionar, .frota-adicionar-placa");
        const remove = event.target.closest(".frota-remover");
        if (!add && !remove) return;
        readEntregaFrotaOperacao();
        const operation = state.entregaFrotaOperation;
        const trucks = state.entregaFrota.caminhoes || [];
        if (add) {
          state.entregaFrota.caminhoes = [...trucks, { filial: operation, placa: add.dataset.placa || "", descricao: "", capacidade_pallets: "", ativo: true }];
        } else {
          const rows = [...E.entregaFrotaDetails.querySelectorAll("#entregaFrotaBody tr")];
          const index = rows.indexOf(remove.closest("tr"));
          const ofOperation = trucks.filter(item => String(item.filial || "").toUpperCase() === operation);
          const target = ofOperation[index];
          state.entregaFrota.caminhoes = trucks.filter(item => item !== target);
        }
        renderEntregaFrota();
        if (add && !add.dataset.placa) E.entregaFrotaDetails.querySelector("#entregaFrotaBody tr:last-child .frota-placa")?.focus();
      });
      if (E.entregaFrotaDetails) E.entregaFrotaDetails.addEventListener("change", event => {
        if (event.target.id !== "entregaFrotaOperation") return;
        readEntregaFrotaOperacao();
        state.entregaFrotaOperation = event.target.value || "";
        renderEntregaFrota();
      });
      if (E.entregaDevolucoesRefreshBtn) E.entregaDevolucoesRefreshBtn.addEventListener("click", async () => {
        E.entregaDevolucoesRefreshBtn.disabled = true;
        try {
          await syncDevolucoesOperacionais({ silent: false });
        } finally {
          E.entregaDevolucoesRefreshBtn.disabled = false;
        }
      });
      if (E.entregaDevolucoesCadastrosSaveBtn) E.entregaDevolucoesCadastrosSaveBtn.addEventListener("click", async () => {
        const button = E.entregaDevolucoesCadastrosSaveBtn;
        button.disabled = true;
        try {
          const result = await req(CONFIG.endpoints.ligaEntrega.devolucoesCadastros, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(readDevolucoesCadastros()) });
          state.devolucoesCadastros = { ...(state.devolucoesCadastros || {}), ...(result || { setores: [], gerentes: [] }) };
          renderDevolucoesCadastros();
          renderEntregaDevolucoes(state.devolucoesOperacionais || {});
          await syncDevolucoesOperacionais({ silent: true });
          addLog("Cadastros de setores e gerentes salvos.", "ok");
        } catch (err) { addLog(`Falha ao salvar cadastros: ${err.message}`, "err"); }
        finally { button.disabled = false; }
      });
      if (E.entregaDevolucoesCadastrosDetails) E.entregaDevolucoesCadastrosDetails.addEventListener("click", event => {
        const add = event.target.closest(".dev-cadastro-add");
        if (add) { const kind = add.dataset.kind; const filial = String(state.devolucoesCadastrosOperation || "").trim().toUpperCase(); state.devolucoesCadastros[kind] = [...(state.devolucoesCadastros[kind] || []), { filial, codigo: "", nome: "" }]; renderDevolucoesCadastros(); return; }
        const remove = event.target.closest(".dev-cadastro-remove");
        if (remove) { const kind = remove.dataset.kind; const key = remove.dataset.key || ""; state.devolucoesCadastros[kind] = (state.devolucoesCadastros[kind] || []).filter(item => `${item.filial || ""}|${item.codigo || ""}` !== key); renderDevolucoesCadastros(); }
      });
      if (E.entregaDevolucoesCadastrosDetails) E.entregaDevolucoesCadastrosDetails.addEventListener("change", event => {
        if (event.target.id !== "devolucoesCadastrosOperation") return;
        state.devolucoesCadastrosOperation = event.target.value || "";
        renderDevolucoesCadastros();
      });
      if (E.entregaLigaExpurgoTipo) E.entregaLigaExpurgoTipo.addEventListener("change", updateLigaEntregaExpurgoForm);
      if (E.entregaLigaExpurgoEscopo) E.entregaLigaExpurgoEscopo.addEventListener("change", updateLigaEntregaExpurgoForm);
      if (E.entregaLigaExpurgoForm) E.entregaLigaExpurgoForm.addEventListener("submit", event => {
        saveLigaEntregaExpurgo(event).catch(err => addLog(`Falha ao aplicar expurgo: ${err.message}`, "err"));
      });
      if (E.entregaLigaExpurgosList) E.entregaLigaExpurgosList.addEventListener("click", event => {
        const button = event.target.closest(".liga-expurgo-remove");
        if (button) removeLigaEntregaExpurgo(button.dataset.expurgoId || "").catch(err => addLog(`Falha ao remover expurgo: ${err.message}`, "err"));
      });
      if (E.entregaLigaDashboardDetails) E.entregaLigaDashboardDetails.addEventListener("click", async event => {
        const rulesToggle = event.target.closest(".liga-rule-toggle");
        if (rulesToggle) {
          updateLigaRuleInputs(rulesToggle.dataset.ligaRuleOperation || "PATOS");
          return;
        }
        const rulesOperationButton = event.target.closest(".liga-rules-operation");
        if (rulesOperationButton) {
          state.ligaEntregaRulesOperation = rulesOperationButton.dataset.ligaRulesOperation === "SUME" ? "SUME" : "PATOS";
          renderLigaEntregaDashboard((state.ligaEntregaReports || {}).items || [], (state.ligaEntregaReports || {}).summary || {});
          return;
        }
        const rulesSaveButton = event.target.closest(".liga-rules-save");
        if (rulesSaveButton) {
          rulesSaveButton.disabled = true;
          try {
            await saveLigaRules(rulesSaveButton.dataset.ligaRulesOperation || "");
          } catch (error) {
            rulesSaveButton.disabled = false;
            addLog(`Falha ao salvar regras da Liga: ${error && error.message ? error.message : error}`, "err");
          }
          return;
        }
        const saveTeamButton = event.target.closest(".liga-team-save");
        if (saveTeamButton) {
          saveTeamButton.disabled = true;
          saveLigaEntregaTeamChanges().catch(err => {
            saveTeamButton.disabled = false;
            addLog(`Falha ao salvar status da equipe: ${err.message}`, "err");
          });
          return;
        }
        const rosterAddButton = event.target.closest(".liga-roster-add");
        if (rosterAddButton) {
          addLigaRosterCandidate(rosterAddButton).catch(err => addLog(`Falha ao cadastrar colaborador: ${err.message || err}`, "error"));
          return;
        }
        const pdfButton = event.target.closest(".liga-dashboard-pdf");
        if (pdfButton) {
          pdfButton.disabled = true;
          downloadLigaDashboardPdf(pdfButton.dataset.ligaPdf || "motoristas").finally(() => { pdfButton.disabled = false; });
          return;
        }
        const printButton = event.target.closest(".liga-dashboard-print");
        if (printButton) {
          printLigaDashboard(printButton.dataset.ligaPrint || "motoristas");
          return;
        }
        const viewButton = event.target.closest(".liga-view");
        if (viewButton) {
          state.ligaEntregaView = viewButton.dataset.ligaView || "motoristas";
          renderLigaEntregaDashboard((state.ligaEntregaReports || {}).items || [], (state.ligaEntregaReports || {}).summary || {});
          return;
        }
        if (event.target.closest(".liga-copy-summary")) {
          const top = (state.ligaEntregaDashboard && state.ligaEntregaDashboard.rankings && state.ligaEntregaDashboard.rankings.motoristas || []).filter(row => row.elegivel).slice(0, 3);
          const summary = state.ligaEntregaDashboard && state.ligaEntregaDashboard.summary || {};
          const message = `Liga Entrega ${state.ligaEntregaDashboard && state.ligaEntregaDashboard.competencia || ""}\n${summary.rotas || 0} rotas • ${summary.devolucoes || 0} devoluções ativas\n${top.map((row, index) => `${index + 1}. ${row.nome} — ${row.total} pts`).join("\n")}`;
          navigator.clipboard.writeText(message).then(() => addLog("Resumo da Liga copiado.", "ok")).catch(() => addLog("Não foi possível copiar o resumo.", "warn"));
          return;
        }
        if (event.target.closest(".liga-export-snapshot")) {
          const payload = state.ligaEntregaDashboard || {};
          const html = `<!doctype html><meta charset="utf-8"><title>Liga Entrega ${payload.competencia || ""}</title><style>body{font:14px Arial;padding:24px;color:#172033}pre{white-space:pre-wrap;background:#f4f6fa;padding:16px;border-radius:8px}</style><h1>Liga Entrega ${escapeHtml(payload.competencia || "")}</h1><p>Gerado em ${escapeHtml(payload.generated_at || "")}</p><pre>${escapeHtml(JSON.stringify(payload, null, 2))}</pre>`;
          const link = document.createElement("a"); link.href = URL.createObjectURL(new Blob([html], { type: "text/html" })); link.download = `liga-entrega-${payload.competencia || "dados"}.html`; link.click(); URL.revokeObjectURL(link.href);
          return;
        }
        const devButton = event.target.closest(".liga-expurgo-dev");
        if (devButton) {
          setEntregaModule("liga");
          if (E.entregaLigaModule && E.entregaLigaModule.classList.contains("is-collapsed")) {
            E.entregaLigaModule.classList.remove("is-collapsed");
            if (E.entregaLigaCollapseBtn) {
              E.entregaLigaCollapseBtn.setAttribute("aria-expanded", "true");
              E.entregaLigaCollapseBtn.innerHTML = '<i class="bi bi-chevron-up me-1"></i>Minimizar';
            }
          }
          E.entregaLigaExpurgoTipo.value = "devolucao";
          if (E.entregaLigaExpurgoEscopo) E.entregaLigaExpurgoEscopo.value = "individual";
          E.entregaLigaExpurgoData.value = devButton.dataset.expurgoData || "";
          E.entregaLigaExpurgoFilial.value = devButton.dataset.expurgoFilial || "PATOS";
          E.entregaLigaExpurgoAlvo.value = devButton.dataset.expurgoCliente || "";
          updateLigaEntregaExpurgoForm();
          E.entregaLigaExpurgoForm.scrollIntoView({ behavior: "smooth", block: "center" });
          return;
        }
        const personButton = event.target.closest(".liga-person-detail");
        if (personButton) {
          state.ligaEntregaView = "rotas";
          state.ligaEntregaFilters = { ...(state.ligaEntregaFilters || {}), q: personButton.dataset.ligaPerson || "" };
          renderLigaEntregaDashboard((state.ligaEntregaReports || {}).items || [], (state.ligaEntregaReports || {}).summary || {});
          return;
        }
        const routeTeamButton = event.target.closest(".liga-route-team");
        if (routeTeamButton) {
          try {
            await editLigaEntregaRouteTeam(routeTeamButton);
          } catch (error) {
            addLog(error && error.message ? error.message : "Não foi possível atualizar a equipe da rota.", "error");
          }
          return;
        }
        const button = event.target.closest(".liga-expurgo-route");
        if (!button) return;
        E.entregaLigaExpurgoTipo.value = button.dataset.expurgoTipo || "km";
        if (E.entregaLigaExpurgoEscopo) E.entregaLigaExpurgoEscopo.value = "individual";
        E.entregaLigaExpurgoData.value = button.dataset.expurgoData || "";
        E.entregaLigaExpurgoFilial.value = button.dataset.expurgoFilial || "PATOS";
        E.entregaLigaExpurgoAlvo.value = button.dataset.expurgoMapa || "";
        updateLigaEntregaExpurgoForm();
        E.entregaLigaExpurgoForm.scrollIntoView({ behavior: "smooth", block: "center" });
      });
      if (E.entregaLigaDashboardDetails) E.entregaLigaDashboardDetails.addEventListener("change", event => {
        if (event.target.matches(".liga-team-status")) {
          const cod = String(event.target.dataset.ligaCode || "");
          if (!cod) return;
          state.ligaEntregaTeamChanges = { ...(state.ligaEntregaTeamChanges || {}), [cod]: event.target.value };
          renderLigaEntregaDashboard((state.ligaEntregaReports || {}).items || [], (state.ligaEntregaReports || {}).summary || {});
          return;
        }
        if (!event.target.matches(".liga-filter-branch")) return;
        state.ligaEntregaFilters = { ...(state.ligaEntregaFilters || {}), filial: event.target.value || "" };
        renderLigaEntregaDashboard((state.ligaEntregaReports || {}).items || [], (state.ligaEntregaReports || {}).summary || {});
      });
      if (E.entregaLigaDashboardDetails) E.entregaLigaDashboardDetails.addEventListener("input", event => {
        if (!event.target.matches(".liga-filter-search")) return;
        state.ligaEntregaFilters = { ...(state.ligaEntregaFilters || {}), q: event.target.value || "" };
        renderLigaEntregaDashboard((state.ligaEntregaReports || {}).items || [], (state.ligaEntregaReports || {}).summary || {});
      });
      if (E.entregaDevolucoesDetails) E.entregaDevolucoesDetails.addEventListener("input", event => {
        if (!event.target.matches(".entrega-devolucoes-filter")) return;
        state.entregaDevolucoesFilter = event.target.value || "";
        renderEntregaDevolucoes(state.devolucoesOperacionais || {});
      });
      if (E.entregaDevolucoesDetails) E.entregaDevolucoesDetails.addEventListener("change", event => {
        if (!event.target.matches(".entrega-devolucoes-control")) return;
        if (event.target.id === "entregaDevolucoesBranch") {
          state.entregaDevolucoesBranch = event.target.value || "";
          state.entregaDevolucoesResponsibility = "";
        }
        if (event.target.id === "entregaDevolucoesResponsibility") state.entregaDevolucoesResponsibility = event.target.value || "";
        if (event.target.id === "entregaDevolucoesMetric") state.entregaDevolucoesMetric = event.target.value || "volume_hl";
        if (event.target.id === "entregaDevolucoesDate") state.entregaDevolucoesDate = event.target.value || "";
        if (event.target.id === "entregaDevolucoesPeriod") state.entregaDevolucoesPeriod = event.target.value || "all";
        if (event.target.id === "entregaDevolucoesTopN") state.entregaDevolucoesTopN = event.target.value || "10";
        renderEntregaDevolucoes(state.devolucoesOperacionais || {});
      });
      if (E.entregaDevolucoesDetails) E.entregaDevolucoesDetails.addEventListener("click", event => {
        if (!event.target.closest(".entrega-devolucoes-print")) return;
        printEntregaDevolucoes();
      });
      updateLigaEntregaExpurgoForm();
      setEntregaModule("liga");
      if (E.promaxJobStatusFilter) E.promaxJobStatusFilter.addEventListener("change", applyPromaxJobFilters);
      if (E.promaxJobFromDate) E.promaxJobFromDate.addEventListener("change", applyPromaxJobFilters);
      if (E.promaxJobToDate) E.promaxJobToDate.addEventListener("change", applyPromaxJobFilters);
      if (E.promaxJobClearFiltersBtn) E.promaxJobClearFiltersBtn.addEventListener("click", clearPromaxJobFilters);
      if (E.promaxSendDates) E.promaxSendDates.addEventListener("change", syncPromaxDateFields);
      if (E.promaxScheduleSendDates) E.promaxScheduleSendDates.addEventListener("change", syncPromaxDateFields);
      if (E.promaxScheduleType) E.promaxScheduleType.addEventListener("change", syncPromaxScheduleFields);
      if (E.promaxScheduleTriggerType) E.promaxScheduleTriggerType.addEventListener("change", syncPromaxScheduleFields);
      if (E.promaxScheduleDailyDays) {
        E.promaxScheduleDailyDays.querySelectorAll(".promax-schedule-day").forEach(input => {
          input.addEventListener("change", updatePromaxActionState);
        });
      }
      [
        E.promaxScheduleSpecificHours,
        E.promaxScheduleSpecificStart,
        E.promaxScheduleSpecificEnd,
        E.promaxScheduleSpecificStep
      ].forEach(input => {
        if (input) input.addEventListener("input", () => {
          updatePromaxSpecificSchedulePreview();
          updatePromaxActionState();
        });
      });
      [
        E.promaxScheduleHourlyStart,
        E.promaxScheduleHourlyEnd,
        E.promaxScheduleHourlyStep
      ].forEach(input => {
        if (input) input.addEventListener("input", () => {
          updatePromaxHourlySchedulePreview();
          updatePromaxActionState();
        });
      });
      if (E.promaxScheduleCreateBtn) E.promaxScheduleCreateBtn.addEventListener("click", promaxCreateSchedule);
      if (E.promaxScheduleCancelBtn) E.promaxScheduleCancelBtn.addEventListener("click", resetPromaxScheduleForm);
      if (E.promaxScheduleGroupRunBtn) E.promaxScheduleGroupRunBtn.addEventListener("click", () => promaxRunScheduleGroup(state.promax.activeScheduleGroupKey));
      document.getElementById("clearLogBtn").addEventListener("click", () => { state.logs = []; renderLogs(); });
      document.getElementById("saveAccessBtn").addEventListener("click", saveAccess);
      document.getElementById("resetAccessBtn").addEventListener("click", resetAccessForm);
      document.getElementById("saveAccessBulkBtn").addEventListener("click", saveBulkAccess);
      document.getElementById("resetAccessBulkBtn").addEventListener("click", () => { E.accessBulk.value = ""; });
      if (E.panelUserSaveBtn) E.panelUserSaveBtn.addEventListener("click", savePanelUser);
      if (E.panelUserResetFormBtn) E.panelUserResetFormBtn.addEventListener("click", resetPanelUserForm);
      if (E.panelUserCopyPasswordBtn) E.panelUserCopyPasswordBtn.addEventListener("click", copyPanelUserTemporaryPassword);
      if (E.panelCredentialsCopyBtn) E.panelCredentialsCopyBtn.addEventListener("click", copyPanelUserTemporaryPassword);
      if (E.panelUserSearch) E.panelUserSearch.addEventListener("input", () => {
        state.panelUserFilter = E.panelUserSearch.value.trim().toLowerCase();
        renderPanelUsers();
      });
      if (E.panelUserAdmin) E.panelUserAdmin.addEventListener("change", () => {
        if (E.panelUserAdmin.checked) {
          renderPanelUserFeatureChecks(PANEL_FEATURES.map(feature => feature.id));
        } else {
          renderPanelUserFeatureChecks(selectedPanelUserFeatures());
        }
      });
      document.getElementById("usageRefreshBtn").addEventListener("click", () => syncEvolutionUsage({ silent: false }));
      if (E.usageExportReportBtn) {
        E.usageExportReportBtn.addEventListener("click", exportEvolutionAverageReport);
      }
      if (E.usageFunctionRefreshBtn) {
        E.usageFunctionRefreshBtn.addEventListener("click", () => syncEvolutionFunctionUsage({ silent: false }));
      }
      if (E.usageFunctionExportBtn) {
        E.usageFunctionExportBtn.addEventListener("click", exportEvolutionFunctionUsageReport);
      }
      if (E.panelAuditRefreshBtn) {
        E.panelAuditRefreshBtn.addEventListener("click", () => syncPanelAuditActions({ silent: false }));
      }
      if (E.panelAuditExportBtn) {
        E.panelAuditExportBtn.addEventListener("click", exportPanelAuditActionsReport);
      }
      [E.panelAuditDateFrom, E.panelAuditDateTo, E.panelAuditModule]
        .forEach(element => {
          if (element) element.addEventListener("change", () => syncPanelAuditActions({ silent: false }));
        });
      [E.panelAuditUser, E.panelAuditAction]
        .forEach(element => {
          if (element) element.addEventListener("input", debounce(() => syncPanelAuditActions({ silent: true }), 250));
        });
      if (E.usageFunctionFilter) {
        E.usageFunctionFilter.addEventListener("change", () => renderEvolutionFunctionUsage(state.evolutionUsage));
      }
      if (E.broadcastPreviewBtn) E.broadcastPreviewBtn.addEventListener("click", previewBroadcast);
      if (E.broadcastRunBtn) E.broadcastRunBtn.addEventListener("click", runBroadcast);
      if (E.broadcastRefreshBtn) E.broadcastRefreshBtn.addEventListener("click", () => syncBroadcastStatus({ silent: false }));
      if (E.broadcastFilial) E.broadcastFilial.addEventListener("change", resetBroadcastPreview);
      if (E.broadcastAudience) E.broadcastAudience.addEventListener("change", () => { renderBroadcastOptions(); resetBroadcastPreview(); });
      if (E.broadcastAction) E.broadcastAction.addEventListener("change", () => { syncBroadcastDayState(); resetBroadcastPreview(); });
      if (E.broadcastDay) E.broadcastDay.addEventListener("change", resetBroadcastPreview);
      if (E.broadcastTargetMode) E.broadcastTargetMode.addEventListener("change", () => { syncBroadcastTargetModeState(); resetBroadcastPreview(); });
      if (E.broadcastTargetNumber) E.broadcastTargetNumber.addEventListener("input", resetBroadcastPreview);
      if (E.broadcastSelectAll) E.broadcastSelectAll.addEventListener("change", toggleBroadcastSelectAll);
      if (E.payipBatchPreviewBtn) E.payipBatchPreviewBtn.addEventListener("click", previewPayipBatch);
      if (E.payipBatchRunBtn) E.payipBatchRunBtn.addEventListener("click", runPayipBatch);
      if (E.payipBatchStatusBtn) E.payipBatchStatusBtn.addEventListener("click", () => syncPayipBatchStatus({ silent: false }));
      if (E.payipBatchExportBtn) E.payipBatchExportBtn.addEventListener("click", exportPayipBatchCsv);
      if (E.protestosRefreshBtn) E.protestosRefreshBtn.addEventListener("click", () => syncProtestos({ silent: false }));
      if (E.protestosApplyBtn) E.protestosApplyBtn.addEventListener("click", () => syncProtestos({ silent: false }));
      [E.protestosFilial, E.protestosStatusFilter, E.protestosTitleDateFrom, E.protestosTitleDateTo, E.protestosActionDateFrom, E.protestosActionDateTo].forEach(element => {
        if (element) element.addEventListener("change", () => syncProtestos({ silent: true }));
      });
      if (E.protestosSearch) E.protestosSearch.addEventListener("input", debounce(() => syncProtestos({ silent: true }), 300));
      if (E.payipGeneratedRefreshBtn) E.payipGeneratedRefreshBtn.addEventListener("click", () => syncPayipGeneratedBatches({ silent: false }));
      if (E.payipGeneratedFilial) {
        E.payipGeneratedFilial.addEventListener("change", () => {
          state.payipGenerated.payload = null;
          state.payipGenerated.error = "";
          renderPayipGeneratedBatches();
          syncPayipGeneratedBatches({ silent: true });
        });
      }
      [E.payipImportFilial, E.payipImportStartDate, E.payipImportEndDate]
        .forEach(element => {
          if (element) element.addEventListener("change", resetPayipImportValidation);
        });
      if (E.payipBatchText) E.payipBatchText.addEventListener("input", resetPayipBatchPreview);
      [E.payipBatchText, E.payipBatchDefaultRate, E.payipBatchDefaultInterest, E.payipBatchIncludeNb, E.payipBatchIncludeNf, E.payipBatchAutoCreate]
        .forEach(element => {
          if (element) element.addEventListener("change", resetPayipBatchPreview);
        });
      if (E.recolhasExportBtn) E.recolhasExportBtn.addEventListener("click", exportRecolhasCsv);
      if (E.recolhasRefreshBtn) E.recolhasRefreshBtn.addEventListener("click", () => syncRecolhas({ silent: false }));
      if (E.recolhasStartDate) E.recolhasStartDate.addEventListener("change", updateRecolhasPeriodFilter);
      if (E.recolhasEndDate) E.recolhasEndDate.addEventListener("change", updateRecolhasPeriodFilter);
      if (E.recolhasPeriodClearBtn) E.recolhasPeriodClearBtn.addEventListener("click", clearRecolhasPeriodFilter);
      if (E.recolhasImportBtn) E.recolhasImportBtn.addEventListener("click", importRecolhasCsv);
      document.addEventListener("change", event => {
        const target = event.target;
        if (target && target.matches && target.matches(".recolha-motivo, .recolha-bulk-motivo")) {
          syncRecolhaPartialDetail(target.closest("td, .recolha-operation"));
        }
      });
      document.addEventListener("input", event => {
        const target = event.target;
        if (target && target.matches && target.matches(".recolha-partial-detail") && target.value.trim()) {
          target.classList.remove("recolha-partial-invalid");
        }
      });
      if (E.giroRecolhaRefreshBtn) E.giroRecolhaRefreshBtn.addEventListener("click", () => syncGiroRecolha({ silent: false }));
      if (E.giroRecolhaRoutesBtn) E.giroRecolhaRoutesBtn.addEventListener("click", () => syncGiroRecolhaRoutes({ silent: false }));
      setupGiroRecolhaSlicerEvents();
      if (E.giroRecolhaMinGap) E.giroRecolhaMinGap.addEventListener("change", () => syncGiroRecolha({ silent: false }));
      if (E.giroRecolhaLimit) E.giroRecolhaLimit.addEventListener("change", () => syncGiroRecolha({ silent: false }));
      if (E.giroRecolhaZeroOnly) E.giroRecolhaZeroOnly.addEventListener("change", () => syncGiroRecolha({ silent: false }));
      if (E.giroRecolhaMaxRouteSize) E.giroRecolhaMaxRouteSize.addEventListener("change", () => clearGiroRecolhaRoutes());
      if (E.giroRecolhaClearBtn) E.giroRecolhaClearBtn.addEventListener("click", clearGiroRecolhaFilters);
      if (E.giroRecolhaRouteSearch) E.giroRecolhaRouteSearch.addEventListener("input", scheduleGiroRouteFilterUpdate);
      if (E.giroRecolhaRouteDistrict) E.giroRecolhaRouteDistrict.addEventListener("change", updateGiroRecolhaRouteFilters);
      if (E.giroRecolhaRouteMinGap) E.giroRecolhaRouteMinGap.addEventListener("input", updateGiroRecolhaRouteFilters);
      if (E.giroRecolhaRouteClearBtn) E.giroRecolhaRouteClearBtn.addEventListener("click", clearGiroRecolhaRouteFilters);
      if (E.giroRecolhaRouteExportBtn) E.giroRecolhaRouteExportBtn.addEventListener("click", exportGiroRecolhaRoutesCsv);
      if (E.giroRecolhaActiveRoute) E.giroRecolhaActiveRoute.addEventListener("change", updateGiroRecolhaActiveRoute);
      if (E.giroRecolhaBlockSearch) E.giroRecolhaBlockSearch.addEventListener("input", scheduleGiroBlockSearchUpdate);
      if (E.giroRecolhaNewRouteBtn) E.giroRecolhaNewRouteBtn.addEventListener("click", createGiroRecolhaManualRoute);
      if (E.criticaDashboardRefreshBtn) E.criticaDashboardRefreshBtn.addEventListener("click", () => syncCriticaDashboard({ silent: false }));
      if (E.criticaGeralImportBtn) E.criticaGeralImportBtn.addEventListener("click", importCriticaGeral);
      if (E.criticaOperationPdfBtn) E.criticaOperationPdfBtn.addEventListener("click", () => exportCriticaOperationPdf({ summaryOnly: false }));
      if (E.criticaOperationSummaryPdfBtn) E.criticaOperationSummaryPdfBtn.addEventListener("click", () => exportCriticaOperationPdf({ summaryOnly: true }));
      if (E.criticaOperationSingle) E.criticaOperationSingle.addEventListener("change", () => syncCriticaDashboard({ silent: false }));
      if (E.criticaSectorPdfBtn) E.criticaSectorPdfBtn.addEventListener("click", () => exportCriticaSectorPdf({ summaryOnly: false }));
      if (E.criticaSectorSummaryPdfBtn) E.criticaSectorSummaryPdfBtn.addEventListener("click", () => exportCriticaSectorPdf({ summaryOnly: true }));
      if (E.criticaDashboardClearBtn) E.criticaDashboardClearBtn.addEventListener("click", clearCriticaDashboardFilters);
      setupCriticaDashboardSlicerEvents();
      [E.criticaDate, E.criticaLimit, E.criticaOnlyProblems]
        .forEach(element => {
          if (element) element.addEventListener("change", () => syncCriticaDashboard({ silent: false }));
        });
      if (E.criticaSearch) E.criticaSearch.addEventListener("input", scheduleCriticaDashboardSync);
      E.accessRole.addEventListener("change", updateScopeHint);
      E.accessUsersFilter.addEventListener("input", scheduleAccessRender);
      if (E.usageWindow) {
        E.usageWindow.addEventListener("change", () => {
          if (hasPanelAuth()) syncEvolutionUsage({ silent: false });
        });
      }

      document.addEventListener("keydown", (evt) => {
        if (evt.key === "/" && document.activeElement.tagName !== "INPUT" && document.activeElement.tagName !== "TEXTAREA") {
          evt.preventDefault();
          E.accessUsersFilter.focus();
        }
        if (evt.altKey && evt.key.toLowerCase() === "r") {
          evt.preventDefault();
          syncAll();
        }
      });

      syncAll();
      window.setInterval(() => {
        // Com a guia do navegador escondida, não há ninguém olhando: não consulta o servidor.
        if (document.hidden) return;
        if (isPaneActive("promaxPane") && state.panel && state.panel.canManagePromax) {
          syncPromax({ silent: true });
          if (state.promax.selectedJobId) promaxLoadLogs(state.promax.selectedJobId);
        }
        if (isPaneActive("armazemPane") && state.panel && state.panel.canArmazem) {
          syncArmazemGrade({ silent: true });
        }
      }, 15000);
    }

    function applyTheme(theme) {
      const normalized = theme === "dark" ? "dark" : "light";
      document.body.setAttribute("data-theme", normalized);
      // Faz os componentes do Bootstrap (avisos, menus, tabelas, campos) seguirem o mesmo tema.
      document.documentElement.setAttribute("data-bs-theme", normalized);
      localStorage.setItem("bot_admin_theme", normalized);
      if (!E.themeToggle) return;
      E.themeToggle.innerHTML = normalized === "dark"
        ? '<i class="bi bi-sun"></i>'
        : '<i class="bi bi-moon-stars"></i>';
      E.themeToggle.classList.toggle("btn-outline-light", normalized === "dark");
      E.themeToggle.classList.toggle("btn-outline-secondary", normalized !== "dark");
    }

    function toggleTheme() {
      const current = document.body.getAttribute("data-theme") === "dark" ? "dark" : "light";
      applyTheme(current === "dark" ? "light" : "dark");
    }

    function isPaneActive(paneId) {
      const pane = document.getElementById(paneId);
      return Boolean(pane && pane.classList.contains("active"));
    }

    function debounce(fn, waitMs = 150) {
      let timer = null;
      return (...args) => {
        window.clearTimeout(timer);
        timer = window.setTimeout(() => fn(...args), waitMs);
      };
    }

    function currentActiveTabId() {
      const active = document.querySelector("#adminTabs .nav-link.active");
      return active ? active.id : "operationsTab";
    }

    async function syncVisibleTabData({ silent = true, force = false } = {}) {
      if (!hasPanelAuth()) return false;
      const activeTabId = currentActiveTabId();
      if (!force && state.lazyTabs && state.lazyTabs[activeTabId]) {
        if (activeTabId === "payipTab") startPayipGeneratedPolling();
        if (activeTabId === "gerarCriticaTab") syncGerarCritica({ silent: true });
        return true;
      }

      const tasks = [];
      if (activeTabId === "operationsTab") {
        if (state.panel && state.panel.canBroadcast) tasks.push(syncBroadcastOptions({ silent }));
      } else if (activeTabId === "payipTab") {
        tasks.push(syncPayipBatchStatus({ silent }));
        tasks.push(syncPayipGeneratedBatches({ silent }));
      } else if (activeTabId === "usageEvolutionTab") {
        if (state.panel && state.panel.isAdmin) tasks.push(syncEvolutionUsage({ silent }));
        else renderEvolutionUsage();
        if (state.panel && state.panel.canViewUsage) tasks.push(syncPanelAuditActions({ silent }));
      } else if (activeTabId === "recolhasTab") {
        if (state.panel && state.panel.canManageRecolhas) tasks.push(syncRecolhas({ silent }));
      } else if (activeTabId === "financeiroTab") {
        if (state.panel && state.panel.canFinanceiro) tasks.push(syncFinanceiro({ silent }));
      } else if (activeTabId === "conferenciaTab") {
        if (state.panel && state.panel.canConferencia) tasks.push(syncConferencia({ silent }));
      } else if (activeTabId === "protestosTab") {
        if (state.panel && state.panel.canProtestos) tasks.push(syncProtestos({ silent }));
      } else if (activeTabId === "giroRecolhaTab") {
        if (state.panel && state.panel.canViewGiro) tasks.push(syncGiroRecolha({ silent }));
      } else if (activeTabId === "criticaTab") {
        if (state.panel && state.panel.canViewCritica) tasks.push(syncCriticaDashboard({ silent }));
      } else if (activeTabId === "gerarCriticaTab") {
        tasks.push(syncGerarCritica({ silent }));
      } else if (activeTabId === "entregaTab") {
        if (state.panel && state.panel.canManagePromax && !state.promax.catalog) tasks.push(syncPromax({ silent }));
        tasks.push(syncLigaEntregaReports({ silent, force }));
      } else if (activeTabId === "promaxTab") {
        if (state.panel && state.panel.canManagePromax) tasks.push(syncPromax({ silent }));
      } else if (activeTabId === "pedidosTab") {
        const scope = document.getElementById("pedidosScopeLabel");
        if (scope && state.panel) scope.textContent = state.panel.isAdmin ? "Acesso administrativo" : (state.panel.sellerScopes || []).length ? `Carteira: ${(state.panel.sellerScopes || []).join(", ")}` : "Carteira não configurada";
        const gerencialTab = document.getElementById("pedidoGerencialTab");
        if (gerencialTab) gerencialTab.hidden = !Boolean(state.panel?.isAdmin);
        if (!state.panel?.isAdmin) setPedidoSubtab("digitacao");
        configurePedidoFiliais();
        tasks.push(syncPedidoConfig());
        tasks.push(syncPedidoQueue({ silent }));
      } else if (activeTabId === "clientesTab") {
        atualizarEscopoClientes();
      } else if (activeTabId === "rotaFinanceiraTab") {
        if (state.panel && state.panel.canRotaFinanceira) tasks.push(syncRotaFinanceira({ pagina: rotaUi.pagina || 1 }));
      } else if (activeTabId === "estoqueTab") {
        configureEstoqueFiliais();
        tasks.push(syncEstoque({ silent }));
      } else if (activeTabId === "armazemTab") {
        if (state.panel && state.panel.canArmazem) tasks.push(syncArmazemGrade({ silent }));
      }

      if (!tasks.length) {
        state.lazyTabs[activeTabId] = true;
        return true;
      }
      const results = await Promise.allSettled(tasks);
      const allSucceeded = results.every(result => result.status === "fulfilled" && result.value !== false);
      if (allSucceeded) state.lazyTabs[activeTabId] = true;
      return allSucceeded;
    }

    function setSyncState(syncing) {
      const btn = document.getElementById("refreshBtn");
      btn.disabled = syncing;
      btn.innerHTML = syncing ? '<span class="spinner-border spinner-border-sm me-1"></span>Atualizando' : '<i class="bi bi-arrow-repeat me-1"></i>Atualizar';
      if (E.main) E.main.setAttribute("aria-busy", syncing ? "true" : "false");
      if (syncing) showSkeletonLoading();
    }

    function showSkeletonLoading() {
      if (isPaneActive("reportsPane")) {
        E.historyTable.innerHTML = [1,2,3].map(() => '<tr><td colspan="5" class="py-3"><div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line"></div></td></tr>').join("");
        if (E.jobsTable) E.jobsTable.innerHTML = [1,2,3].map(() => '<tr><td colspan="4" class="py-3"><div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line"></div></td></tr>').join("");
        CONFIG.datasets.filter(ds => !ds.disabled).forEach(ds => {
          const card = document.getElementById(`card-${ds.id}`);
          if (card) card.classList.add("is-loading");
        });
      }
      if (isPaneActive("operationsPane")) {
        E.accessUsersTable.innerHTML = [1,2,3].map(() => '<tr><td colspan="6" class="py-3"><div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line"></div></td></tr>').join("");
      }
      if (isPaneActive("recolhasPane") && E.recolhasContainer) {
        E.recolhasContainer.innerHTML = '<div class="py-3"><div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line"></div></div>';
      }
      if (isPaneActive("giroRecolhaPane") && E.giroRecolhaBody) {
        E.giroRecolhaBody.innerHTML = '<tr><td colspan="6" class="py-3"><div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line"></div></td></tr>';
      }
      if (isPaneActive("giroRecolhaPane") && E.giroRecolhaRoutesContainer) {
        E.giroRecolhaRoutesContainer.innerHTML = '<div class="py-2"><div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line"></div></div>';
      }
      if (isPaneActive("usageEvolutionPane")) renderEvolutionUsageLoading();
      if (isPaneActive("usageEvolutionPane")) renderPanelAuditLoading();
    }

    function updateMetrics() {
      E.metricDatasets.textContent = String(CONFIG.datasets.filter(ds => !ds.disabled).length);
      E.metricUsers.textContent = String(state.accessUsers.length);
      const running = Boolean(state.status && state.status.running);
      E.metricRunning.textContent = running ? "Rodando" : "Ocioso";
      E.metricLastSync.textContent = state.lastSyncAt ? state.lastSyncAt.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }) : "--:--";
    }

    function normalizeTextForSearch(value) {
      return String(value || "")
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .replace(/[^\p{L}\p{N}]+/gu, " ")
        .trim()
        .toLowerCase();
    }

    function normalizeStatusText(value) {
      return normalizeTextForSearch(value).replace(/\s+/g, "");
    }

    function hasPanelAuth() {
      return Boolean(state.tokens.admin || (state.panel && state.panel.mode));
    }

    function updateTokens() {
      const api = E.apiToken.value.trim();
      const admin = E.adminToken.value.trim();
      state.tokens.api = api;
      state.tokens.admin = admin;
      localStorage.removeItem("bot_api_token");
      localStorage.removeItem("bot_admin_token");
      if (admin) { E.authState.textContent = "Token informado"; E.authState.className = "pill warn"; }
      else if (state.panel && state.panel.mode) { E.authState.textContent = "Sessão ativa"; E.authState.className = "pill ok"; }
      else { E.authState.textContent = "Validando sessão"; E.authState.className = "pill warn"; }
    }

    async function logoutPanel() {
      try {
        await fetch(CONFIG.endpoints.panel.logout, { method: "POST", credentials: "same-origin" });
      } catch (_) {
        // Mesmo com falha de rede, sair da tela evita manter o painel aberto.
      }
      window.location.assign("/login");
    }

    function addLog(msg, type = "info") {
      const ts = new Date().toISOString().split("T")[1].substring(0, 8);
      const prefix = type === "err" ? "[ERR]" : type === "ok" ? "[OK]" : type === "warn" ? "[WRN]" : "[INF]";
      state.logs.push(`[${ts}] ${prefix} ${msg}`);
      if (state.logs.length > 400) state.logs.shift();
      renderLogs();
    }

    function renderLogs() {
      E.log.textContent = state.logs.length ? state.logs.join("\n") : "Sem logs.";
      E.log.scrollTop = E.log.scrollHeight;
    }

    async function req(path, opts = {}) {
      const timeoutMs = Number(opts.timeoutMs || 45000);
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

      if (!opts.headers) opts.headers = {};
      if (state.tokens.api) opts.headers["x-api-token"] = state.tokens.api;
      if (state.tokens.admin) opts.headers["x-admin-token"] = state.tokens.admin;

      const fetchOpts = { ...opts, credentials: "same-origin", signal: controller.signal };
      delete fetchOpts.timeoutMs;

      let res;
      try {
        res = await fetch(CONFIG.api + path, fetchOpts);
      } catch (err) {
        if (err && err.name === "AbortError") {
          throw new Error("Tempo de resposta excedido. Tente novamente.");
        }
        if (err && String(err.message || "").toLowerCase().includes("failed to fetch")) {
          throw new Error("Não consegui falar com a API do painel. Se você abriu o admin pelo gateway, atualize a página e tente novamente.");
        }
        throw err;
      } finally {
        clearTimeout(timeoutId);
      }

      const data = await res.json().catch(() => null);
      if (!res.ok) {
        if (res.status === 401 && !state.tokens.admin) {
          window.location.assign("/login");
        }
        throw new Error(data && data.detail ? data.detail : `HTTP ${res.status}`);
      }
      return data;
    }

    async function syncPanelSession() {
      const payload = await req(CONFIG.endpoints.panel.session, { timeoutMs: 20000 });
      state.panel = {
        mode: payload && payload.mode ? String(payload.mode) : "admin",
        isAdmin: Boolean(payload && payload.is_admin),
        userId: payload && payload.user_id ? String(payload.user_id) : "",
        username: payload && payload.username ? String(payload.username) : "",
        displayName: payload && payload.display_name ? String(payload.display_name) : "",
        features: Array.isArray(payload && payload.features) ? payload.features.map(String) : [],
        filiais: Array.isArray(payload && payload.filiais) ? payload.filiais.map(String) : [],
        sellerScopes: Array.isArray(payload && payload.seller_scopes) ? payload.seller_scopes.map(String) : [],
        canBroadcast: payload && Object.prototype.hasOwnProperty.call(payload, "can_broadcast")
          ? Boolean(payload.can_broadcast)
          : true,
        canImport: payload && Object.prototype.hasOwnProperty.call(payload, "can_import")
          ? Boolean(payload.can_import)
          : true,
        canImportCritica: payload && Object.prototype.hasOwnProperty.call(payload, "can_import_critica")
          ? Boolean(payload.can_import_critica)
          : true,
        canManageRecolhas: payload && Object.prototype.hasOwnProperty.call(payload, "can_manage_recolhas")
          ? Boolean(payload.can_manage_recolhas)
          : true,
        canFinanceiro: payload && Object.prototype.hasOwnProperty.call(payload, "can_financeiro")
          ? Boolean(payload.can_financeiro)
          : true,
        canConferencia: payload && Object.prototype.hasOwnProperty.call(payload, "can_conferencia")
          ? Boolean(payload.can_conferencia)
          : Boolean(payload && payload.is_admin),
        canProtestos: payload && Object.prototype.hasOwnProperty.call(payload, "can_protestos")
          ? Boolean(payload.can_protestos)
          : Boolean(payload && payload.is_admin),
        canArmazem: payload && Object.prototype.hasOwnProperty.call(payload, "can_armazem")
          ? Boolean(payload.can_armazem)
          : true,
        canPayip: payload && Object.prototype.hasOwnProperty.call(payload, "can_payip")
          ? Boolean(payload.can_payip)
          : true,
        canOperations: payload && Object.prototype.hasOwnProperty.call(payload, "can_operations")
          ? Boolean(payload.can_operations)
          : true,
        canReports: payload && Object.prototype.hasOwnProperty.call(payload, "can_reports")
          ? Boolean(payload.can_reports)
          : true,
        canViewGiro: payload && Object.prototype.hasOwnProperty.call(payload, "can_view_giro")
          ? Boolean(payload.can_view_giro)
          : true,
        canViewCritica: payload && Object.prototype.hasOwnProperty.call(payload, "can_view_critica")
          ? Boolean(payload.can_view_critica)
          : true,
        canViewUsage: payload && Object.prototype.hasOwnProperty.call(payload, "can_view_usage")
          ? Boolean(payload.can_view_usage)
          : Boolean(payload && payload.is_admin),
        canManagePromax: payload && Object.prototype.hasOwnProperty.call(payload, "can_manage_promax")
          ? Boolean(payload.can_manage_promax)
          : Boolean(payload && payload.is_admin),
        canEntrega: payload && Object.prototype.hasOwnProperty.call(payload, "can_entrega")
          ? Boolean(payload.can_entrega)
          : Boolean(payload && payload.is_admin),
        canPedidos: payload && Object.prototype.hasOwnProperty.call(payload, "can_pedidos")
          ? Boolean(payload.can_pedidos)
          : Boolean(payload && payload.is_admin),
        canClientes: payload && Object.prototype.hasOwnProperty.call(payload, "can_clientes")
          ? Boolean(payload.can_clientes)
          : Boolean(payload && payload.is_admin),
        canRotaFinanceira: payload && Object.prototype.hasOwnProperty.call(payload, "can_rota_financeira")
          ? Boolean(payload.can_rota_financeira)
          : Boolean(payload && payload.is_admin),
        canEstoque: payload && Object.prototype.hasOwnProperty.call(payload, "can_estoque")
          ? Boolean(payload.can_estoque)
          : Boolean(payload && payload.is_admin),
        canGerarCritica: payload && Object.prototype.hasOwnProperty.call(payload, "can_gerar_critica")
          ? Boolean(payload.can_gerar_critica)
          : Boolean(payload && payload.is_admin)
      };
      applyPanelPermissions();
      return state.panel;
    }

    function setPanelTabVisible(tabId, visible) {
      const tab = document.getElementById(tabId);
      if (tab && tab.parentElement) tab.parentElement.style.display = visible ? "" : "none";
    }

    function applySimplePanelMode() {
      document.body.classList.toggle("panel-simple-mode", isConferenciaOnlyPanelUser());
    }

    function showPanelTab(tabId) {
      const tab = document.getElementById(tabId);
      if (!tab) return;
      if (window.bootstrap) {
        bootstrap.Tab.getOrCreateInstance(tab).show();
        return;
      }
      document.querySelectorAll("#adminTabs .nav-link").forEach(item => {
        item.classList.remove("active");
        item.setAttribute("aria-selected", "false");
      });
      document.querySelectorAll(".tab-pane").forEach(item => item.classList.remove("show", "active"));
      tab.classList.add("active");
      tab.setAttribute("aria-selected", "true");
      const paneSelector = tab.getAttribute("data-bs-target");
      const pane = paneSelector ? document.querySelector(paneSelector) : null;
      if (pane) pane.classList.add("show", "active");
    }

    function applyPanelPermissions() {
      const isAdminPanel = Boolean(state.panel && state.panel.isAdmin);
      document.body.classList.toggle("panel-admin", isAdminPanel);
      const heroTitle = document.querySelector(".admin-hero .hero-title .text-gradient");
      if (heroTitle) heroTitle.textContent = "Central Pau Brasil";
      const isFinance = state.panel && state.panel.mode === "financeiro" && !state.panel.isAdmin;
      const isCritica = state.panel && state.panel.mode === "critica" && !state.panel.isAdmin;
      const adminOnlyDisplay = state.panel && state.panel.isAdmin ? "" : "none";
      const operationsVisible = Boolean(state.panel && state.panel.canOperations) && !isCritica;
      const reportsVisible = Boolean(state.panel && state.panel.canReports) && !isCritica;
      const broadcastDisplay = operationsVisible && !(state.panel && state.panel.canBroadcast === false) ? "" : "none";
      if (E.accessEditorCard) E.accessEditorCard.style.display = adminOnlyDisplay;
      if (E.allowedUsersCard) E.allowedUsersCard.style.display = adminOnlyDisplay;
      if (E.panelUsersPanel) E.panelUsersPanel.style.display = adminOnlyDisplay;
      if (E.accessUsersFilter && E.accessUsersFilter.parentElement) E.accessUsersFilter.parentElement.style.display = adminOnlyDisplay;
      if (E.broadcastPanel) E.broadcastPanel.style.display = broadcastDisplay;
      const payipVisible = Boolean(state.panel && state.panel.canPayip) && !isCritica;
      if (E.payipGeneratedBatchesPanel) E.payipGeneratedBatchesPanel.style.display = payipVisible ? "" : "none";
      if (E.payipBatchPanel) E.payipBatchPanel.style.display = payipVisible ? "" : "none";
      if (E.payipImportPanel) E.payipImportPanel.style.display = payipVisible ? "" : "none";
      if (E.usageEvolutionTab && E.usageEvolutionTab.parentElement) {
        E.usageEvolutionTab.parentElement.style.display = state.panel && state.panel.canViewUsage ? "" : "none";
      }
      setPanelTabVisible("operationsTab", operationsVisible);
      setPanelTabVisible("payipTab", payipVisible);
      setPanelTabVisible("reportsTab", reportsVisible);
      setPanelTabVisible("promaxTab", Boolean(state.panel && state.panel.canManagePromax));
      setPanelTabVisible("pedidosTab", Boolean(state.panel && state.panel.canPedidos));
      setPanelTabVisible("clientesTab", Boolean(state.panel && state.panel.canClientes));
      setPanelTabVisible("rotaFinanceiraTab", Boolean(state.panel && state.panel.canRotaFinanceira));
      setPanelTabVisible("estoqueTab", Boolean(state.panel && state.panel.canEstoque));
      const estoqueImportCard = document.getElementById("estoqueImportCard");
      if (estoqueImportCard) estoqueImportCard.style.display = state.panel && state.panel.isAdmin ? "" : "none";
      const importar030237Card = document.getElementById("importar030237Card");
      if (importar030237Card) importar030237Card.style.display = state.panel && state.panel.isAdmin ? "" : "none";
      setPanelTabVisible("armazemTab", Boolean(state.panel && state.panel.canArmazem));
      setPanelTabVisible("entregaTab", Boolean(state.panel && state.panel.canEntrega));
      setPanelTabVisible("criticaTab", Boolean(state.panel && state.panel.canViewCritica));
      setPanelTabVisible("gerarCriticaTab", Boolean(state.panel && state.panel.canGerarCritica));
      setPanelTabVisible("recolhasTab", Boolean(state.panel && state.panel.canManageRecolhas));
      setPanelTabVisible("financeiroTab", Boolean(state.panel && state.panel.canFinanceiro) && !isCritica);
      setPanelTabVisible("conferenciaTab", Boolean(state.panel && state.panel.canConferencia) && !isCritica);
      setPanelTabVisible("protestosTab", Boolean(state.panel && state.panel.canProtestos) && !isCritica);
      setPanelTabVisible("giroRecolhaTab", Boolean(state.panel && state.panel.canViewGiro));
      applySimplePanelMode();
      // Quem tem a Rota Financeira começa por ela (só na primeira carga e só na raiz /;
      // um endereço direto como /clientes continua abrindo a aba pedida).
      if (state.panel && !state.primeiraTelaDefinida) {
        state.primeiraTelaDefinida = true;
        if (!isCritica && currentPanelPath() === "/" && state.panel.canRotaFinanceira) {
          // Esquece o grupo escolhido antes, para a barra de grupos acompanhar a aba (Vendedor).
          const barraGrupos = document.getElementById("panelGroups");
          if (barraGrupos) delete barraGrupos.dataset.selecionado;
          showPanelTab("rotaFinanceiraTab");
        }
      }
      const activeTab = document.querySelector("#adminTabs .nav-link.active");
      // Na raiz (/) o endereço fica limpo; em outro endereço, ele passa a apontar para a aba aberta.
      const replaceAddress = currentPanelPath() !== "/";
      if (isCritica && activeTab && activeTab.id !== "criticaTab") {
        if (replaceAddress) navigatePanelPage("criticaTab", { replace: true }); else showPanelTab("criticaTab");
      } else if (activeTab && activeTab.parentElement && activeTab.parentElement.style.display === "none") {
        const firstVisible = Array.from(document.querySelectorAll("#adminTabs .nav-link"))
          .find(tab => tab.parentElement && tab.parentElement.style.display !== "none");
        if (firstVisible) {
          if (replaceAddress) navigatePanelPage(firstVisible.id, { replace: true }); else showPanelTab(firstVisible.id);
        }
      }
      if (isCritica) {
        const filiais = state.panel.filiais && state.panel.filiais.length
          ? state.panel.filiais.map(item => item === "*" ? "todas" : item).join(", ")
          : "-";
        E.authState.textContent = `APR Crítica: ${filiais}`;
        E.authState.className = "pill ok";
      } else if (isFinance) {
        const activeUsagePane = document.getElementById("usageEvolutionPane");
        if (activeUsagePane && activeUsagePane.classList.contains("active")) {
          const operationsTab = document.getElementById("operationsTab");
          if (operationsTab && window.bootstrap) bootstrap.Tab.getOrCreateInstance(operationsTab).show();
        }
        const filiais = state.panel.filiais && state.panel.filiais.length ? state.panel.filiais.join(", ") : "-";
        E.authState.textContent = `Financeiro: filial ${filiais}`;
        E.authState.className = "pill ok";
      } else if (state.panel && state.panel.isAdmin) {
        E.authState.textContent = "Admin: acesso total";
        E.authState.className = "pill ok";
      } else if (state.panel && state.panel.username) {
        E.authState.textContent = `Usuário: ${state.panel.displayName || state.panel.username}`;
        E.authState.className = "pill ok";
      }
      syncAllowedUsersCardSizing();
      atualizarGruposAbas();
    }

    function formatDateInputValue(date) {
      const yyyy = date.getFullYear();
      const mm = String(date.getMonth() + 1).padStart(2, "0");
      const dd = String(date.getDate()).padStart(2, "0");
      return `${yyyy}-${mm}-${dd}`;
    }

    // "SEG/QUI" -> "Segunda, Quinta" (dias de visita do cadastro, em ordem da semana).
    const DIAS_VISITA = [["SEG", "Segunda"], ["TER", "Terça"], ["QUA", "Quarta"], ["QUI", "Quinta"], ["SEX", "Sexta"], ["SAB", "Sábado"], ["DOM", "Domingo"]];
    function diasVisitaTexto(valor) {
      const texto = String(valor || "").trim();
      const siglas = new Set(texto.toUpperCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").split(/[^A-Z]+/).map(parte => parte.slice(0, 3)));
      const nomes = DIAS_VISITA.filter(([sigla]) => siglas.has(sigla)).map(([, nome]) => nome);
      return nomes.length ? nomes.join(", ") : texto;
    }

    function escapeHtml(value) {
      return String(value || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }

    function formatNumber(value) {
      const n = Number(value || 0);
      return Number.isFinite(n) ? n.toLocaleString("pt-BR") : "0";
    }

    function formatDate(value) {
      const text = String(value || "").trim();
      if (/^\d{4}-\d{2}-\d{2}$/.test(text)) {
        const parts = text.split("-");
        return `${parts[2]}/${parts[1]}`;
      }
      const dt = new Date(text);
      if (Number.isNaN(dt.getTime())) return "--/--";
      return dt.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
    }

    function formatDateTime(value) {
      const dt = new Date(value);
      if (Number.isNaN(dt.getTime())) return "-";
      return dt.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
    }

    function formatMoneyText(value) {
      const raw = financeiroNumber(value);
      if (!Number.isFinite(raw)) return String(value || "0");
      return raw.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
    }

    function cleanDisplayText(value) {
      return String(value || "")
        .replace(/Ã£/g, "ã")
        .replace(/Ã§/g, "ç")
        .replace(/Ã¡/g, "á")
        .replace(/Ã©/g, "é")
        .replace(/Ã­/g, "í")
        .replace(/Ã³/g, "ó")
        .replace(/Ãº/g, "ú");
    }

    async function writeTextToClipboard(text) {
      const value = String(text || "");
      if (!value.trim()) return false;
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(value);
          return true;
        }
      } catch (_) {}
      const textarea = document.createElement("textarea");
      textarea.value = value;
      textarea.setAttribute("readonly", "");
      textarea.style.position = "fixed";
      textarea.style.left = "-9999px";
      textarea.style.top = "0";
      document.body.appendChild(textarea);
      textarea.focus();
      textarea.select();
      let copied = false;
      try {
        copied = document.execCommand("copy");
      } catch (_) {
        copied = false;
      }
      textarea.remove();
      return copied;
    }

    function csvEscape(value) {
      const text = String(value == null ? "" : value).replace(/\r?\n/g, " ").trim();
      return /[;"\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
    }

    async function recordClientPanelAction(payload) {
      try {
        await req(CONFIG.endpoints.panel.actions, {
          method: "POST",
          body: JSON.stringify(payload || {}),
          timeoutMs: 10000
        });
      } catch (err) {
        console.warn("Falha ao registrar ação do painel", err);
      }
    }

    function renderOptions(options, selectedValue, emptyLabel = "") {
      const selected = cleanDisplayText(selectedValue || "").trim();
      const normalizedSelected = normalizeTextForSearch(selected);
      const seen = new Set();
      const rows = [];
      for (const option of options) {
        const value = cleanDisplayText(option || "").trim();
        const key = normalizeTextForSearch(value);
        if (seen.has(key)) continue;
        seen.add(key);
        const label = value || emptyLabel || "-";
        rows.push(`<option value="${escapeHtml(value)}" ${key === normalizedSelected ? "selected" : ""}>${escapeHtml(label)}</option>`);
      }
      if (selected && !seen.has(normalizedSelected)) {
        rows.push(`<option value="${escapeHtml(selected)}" selected>${escapeHtml(selected)}</option>`);
      }
      return rows.join("");
    }

    async function syncAll() {
      updateTokens();
      setSyncState(true);
      addLog("Atualizando painel...", "info");
      try {
        await syncPanelSession();
        const isCritica = state.panel && state.panel.mode === "critica" && !state.panel.isAdmin;
        if (isCritica) {
          const [statusPayload, historyPayload] = await Promise.all([
            req(CONFIG.endpoints.import.status, { timeoutMs: 30000 }),
            req(CONFIG.endpoints.import.history, { timeoutMs: 30000 })
          ]);
          state.status = statusPayload || {};
          state.history = (historyPayload && historyPayload.history) ? historyPayload.history : [];
          state.jobs = Array.isArray(state.status.jobs)
            ? state.status.jobs
            : ((historyPayload && Array.isArray(historyPayload.jobs)) ? historyPayload.jobs : []);
          state.accessUsers = [];
          state.panelUsers = [];
          state.recolhas = { total: 0, operations: [] };
          state.giroRecolha = { total: 0, summary: {}, records: [] };
          state.giroRecolhaOptions = emptyGiroRecolhaOptions();
          state.giroRecolhaSlicerOptions = emptyGiroRecolhaOptions();
          state.giroRecolhaRoutes = { generated: false, total: 0, summary: {}, routes: [] };
          state.lastSyncAt = new Date();
          syncDatasetsFromImportStatus(state.status);
          buildGrid();
          renderHistory();
          renderJobs();
          renderGridPanels();
          renderAccess();
          renderPanelUsers();
          await syncCriticaDashboard({ silent: true });
          updateGeneralState();
          updateMetrics();
          addLog("Atualização da crítica concluída.", "ok");
          return;
        }
        const isAdmin = state.panel && state.panel.isAdmin;
        const canLoadReports = Boolean(state.panel && (state.panel.canReports || state.panel.canViewCritica));
        // A aba aberta carrega junto com os dados gerais, sem esperar por eles.
        const visibleTabLoad = syncVisibleTabData({ silent: true, force: true }).catch(() => false);
        const [
          statusResult,
          historyResult,
          usersResult,
          panelUsersResult
        ] = await Promise.allSettled([
          canLoadReports ? req(CONFIG.endpoints.import.status, { timeoutMs: 30000 }) : Promise.resolve({}),
          canLoadReports ? req(CONFIG.endpoints.import.history, { timeoutMs: 30000 }) : Promise.resolve({ history: [], jobs: [] }),
          isAdmin ? req(CONFIG.endpoints.access.list, { timeoutMs: 30000 }) : Promise.resolve({ users: [] }),
          isAdmin ? req(CONFIG.endpoints.panel.users, { timeoutMs: 30000 }) : Promise.resolve({ users: [] })
        ]);
        const settledPayload = (result, fallback, label) => {
          if (result && result.status === "fulfilled") return result.value;
          if (label) addLog(`Falha parcial ao carregar ${label}.`, "warn");
          return fallback;
        };
        const statusPayload = settledPayload(statusResult, {}, "status");
        const historyPayload = settledPayload(historyResult, { history: [], jobs: [] }, "historico");
        const usersPayload = settledPayload(usersResult, { users: [] }, "usuarios");
        const panelUsersPayload = settledPayload(panelUsersResult, { users: [] }, "usuários do painel");
        state.status = statusPayload || {};
        state.history = (historyPayload && historyPayload.history) ? historyPayload.history : [];
        state.jobs = Array.isArray(state.status.jobs)
          ? state.status.jobs
          : ((historyPayload && Array.isArray(historyPayload.jobs)) ? historyPayload.jobs : []);
        state.accessUsers = (usersPayload && usersPayload.users) ? usersPayload.users : [];
        state.panelUsers = (panelUsersPayload && panelUsersPayload.users) ? panelUsersPayload.users : [];
        state.lastSyncAt = new Date();
        syncDatasetsFromImportStatus(state.status);
        buildGrid();
        renderHistory();
        renderJobs();
        renderGridPanels();
        renderAccess();
        renderPanelUsers();
        updateGeneralState();
        updateMetrics();
        await visibleTabLoad;
        addLog("Atualização concluída.", "ok");
      } catch (err) {
        addLog(`Falha ao atualizar: ${err.message}`, "err");
        renderHistory();
        renderJobs();
        renderGridPanels();
        renderAccess();
        renderPanelUsers();
        renderGiroRecolha();
        renderGiroRecolhaRoutes();
        renderRecolhas();
        updateGeneralState();
        updateMetrics();
        renderEvolutionUsage();
        renderBroadcastOptions();
        renderPayipBatch();
        financeiroRender();
      } finally {
        setSyncState(false);
      }
    }

    function updateGeneralState() {
      const running = Boolean(state.status && state.status.running);
      const activeJobs = state.status && Array.isArray(state.status.current_jobs) ? state.status.current_jobs : [];
      if (running) { E.runningState.textContent = activeJobs.length > 1 ? `${activeJobs.length} importações em andamento` : "Importação em andamento"; E.runningState.className = "pill warn"; }
      else { E.runningState.textContent = "Nenhuma importação ativa"; E.runningState.className = "pill ok"; }
      if (state.status && state.status.last_job && state.status.last_job.finished_at) {
        E.lastJobState.textContent = `Última carga: ${new Date(state.status.last_job.finished_at).toLocaleString()}`;
      } else if (state.history.length > 0) {
        E.lastJobState.textContent = `Última carga: ${new Date(state.history[0].imported_at).toLocaleString()}`;
      } else {
        E.lastJobState.textContent = "Sem execução recente";
      }
      E.lastJobState.className = "pill";
    }

    function parsePanelFiliais(value) {
      return String(value || "").split(/[,;\s]+/).map(item => item.trim()).filter(Boolean);
    }

    function panelFeatureLabel(featureId) {
      const found = PANEL_FEATURES.find(item => item.id === featureId);
      return found ? found.label : featureId;
    }

    function askConfirmation(message) {
      if (!confirmModalInstance || !E.confirmModalOk || !E.confirmModalCancel || !E.confirmModalText) {
        return Promise.resolve(window.confirm(message));
      }
      E.confirmModalText.textContent = message;
      return new Promise(resolve => {
        const onOk = () => {
          cleanup();
          resolve(true);
          confirmModalInstance.hide();
        };
        const onCancel = () => {
          cleanup();
          resolve(false);
        };
        const onHidden = () => {
          cleanup();
          resolve(false);
        };
        const cleanup = () => {
          E.confirmModalOk.removeEventListener("click", onOk);
          E.confirmModalCancel.removeEventListener("click", onCancel);
          document.getElementById("confirmModal").removeEventListener("hidden.bs.modal", onHidden);
        };

        E.confirmModalOk.addEventListener("click", onOk);
        E.confirmModalCancel.addEventListener("click", onCancel);
        document.getElementById("confirmModal").addEventListener("hidden.bs.modal", onHidden, { once: true });
        confirmModalInstance.show();
      });
    }
