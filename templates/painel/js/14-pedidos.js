    function pedidosSetStatus(message, kind = "") {
      const element = document.getElementById("pedidoStatus");
      if (!element) return;
      element.textContent = message;
      element.className = `form-text ${kind === "err" ? "text-danger" : kind === "ok" ? "text-success" : ""}`;
    }

    function setPedidoTitle(client = null) {
      const title = document.getElementById("pedidoTitle");
      if (!title) return;
      const nb = String(client?.cliente || "").trim();
      title.textContent = nb ? `Pedido do NB ${nb}` : "Novo pedido";
    }

    function pedidoQueueStatus(status) {
      const normalized = String(status || "pending").toLowerCase();
      const labels = { pending: "Na fila", queued: "Na fila", running: "Em digitação", success: "Concluído", partial_success: "Parcial", failed: "Falhou", cancelled: "Cancelado" };
      return { key: normalized, label: labels[normalized] || normalized };
    }

    function renderPedidoQueue(rows = []) {
      const target = document.getElementById("pedidoFila");
      if (!target) return;
      if (!rows.length) {
        target.innerHTML = '<div class="pedido-queue-empty"><i class="bi bi-inbox me-1"></i>Nenhum pedido enviado por você nesta fila.</div>';
        return;
      }
      target.innerHTML = rows.map(job => {
        const status = pedidoQueueStatus(job.status);
        const time = job.finished_at || job.started_at || job.created_at;
        const isFailure = ["failed", "partial_success", "cancelled"].includes(status.key);
        const detail = String(job.detail || "").trim();
        const message = detail || String(job.message || "Aguardando execução.");
        const caption = isFailure ? (detail ? "Motivo da recusa" : "Resultado da digitação") : "Resultado da digitação";
        return `<article class="pedido-queue-row"><span class="pedido-queue-status" data-status="${escapeHtml(status.key)}">${escapeHtml(status.label)}</span><div class="pedido-queue-main"><strong>Pedido do NB ${escapeHtml(job.cliente || "-")}</strong><span>${job.motivo_digitacao ? `Motivo: ${escapeHtml(job.motivo_digitacao)}` : "Motivo não informado"}</span></div><span class="pedido-queue-message${isFailure ? " is-error" : ""}"><small>${escapeHtml(caption)}</small>${escapeHtml(message)}</span><time class="pedido-queue-time" datetime="${escapeHtml(String(time || ""))}">${time ? escapeHtml(formatDateTime(time)) : "—"}</time></article>`;
      }).join("");
    }

    async function syncPedidoQueue({ silent = false } = {}) {
      const button = document.getElementById("pedidoFilaAtualizarBtn");
      const status = document.getElementById("pedidoFilaStatus");
      if (button) button.disabled = true;
      if (!silent && status) status.textContent = "Atualizando sua fila...";
      try {
        const response = await req("/api/admin/pedidos/jobs?limit=50");
        pedidosUi.queue = Array.isArray(response.jobs) ? response.jobs : [];
        renderPedidoQueue(pedidosUi.queue);
        if (status) status.textContent = pedidosUi.queue.length ? `${pedidosUi.queue.length} pedido(s) seu(s) encontrado(s).` : "Nenhum pedido seu na fila.";
        return true;
      } catch (error) {
        if (status) status.textContent = error.message || "Não foi possível carregar sua fila agora.";
        return false;
      } finally {
        if (button) button.disabled = false;
      }
    }

    function renderPedidoMotivos(config) {
      const select = document.getElementById("pedidoMotivo");
      if (!select) return;
      const selected = select.value;
      const motivos = Array.isArray(config?.motivos) ? config.motivos : [];
      select.innerHTML = `<option value="">Selecione o motivo</option>${motivos.map(motivo => `<option value="${escapeHtml(motivo)}">${escapeHtml(motivo)}</option>`).join("")}`;
      if (motivos.includes(selected)) select.value = selected;
    }

    function renderPedidoBloqueio(config) {
      const aviso = document.getElementById("pedidoBloqueioAviso");
      const texto = document.getElementById("pedidoBloqueioTexto");
      const horario = String(config?.horario_bloqueio || "");
      const encerrada = Boolean(config?.bloqueado);
      const podeIgnorar = Boolean(config?.pode_ignorar_bloqueio);
      pedidosUi.bloqueadoPorHorario = encerrada && !podeIgnorar;
      clearTimeout(pedidosUi.bloqueioTimer);
      const segundos = Number(config?.segundos_ate_bloqueio);
      // Ao chegar o horário, pergunta de novo ao servidor (o relógio dele é o que vale).
      if (horario && !encerrada && Number.isFinite(segundos) && segundos > 0) pedidosUi.bloqueioTimer = setTimeout(syncPedidoConfig, (segundos + 2) * 1000);
      if (aviso && texto) {
        aviso.hidden = !horario;
        aviso.classList.toggle("alert-warning", pedidosUi.bloqueadoPorHorario);
        aviso.classList.toggle("alert-info", !pedidosUi.bloqueadoPorHorario);
        texto.textContent = encerrada && podeIgnorar
          ? `A digitação foi encerrada às ${horario} para os vendedores. Como administrador, você ainda pode enviar pedidos.`
          : String(config?.mensagem || "");
      }
      syncPedidoControls();
    }

    // Bonificação (operação 2 da 03.01.04) só aparece para administrador; venda não muda.
    function configurePedidoOperacao(config) {
      const wrap = document.getElementById("pedidoOperacaoWrap");
      const select = document.getElementById("pedidoOperacao");
      if (!wrap || !select) return;
      wrap.hidden = !config?.pode_bonificar;
      if (wrap.hidden) select.value = "1";
      aplicarPedidoOperacao();
    }

    function pedidoBonificacao() {
      const wrap = document.getElementById("pedidoOperacaoWrap");
      return Boolean(wrap && !wrap.hidden && document.getElementById("pedidoOperacao")?.value === "2");
    }

    function aplicarPedidoOperacao() {
      document.querySelector(".pedido-items-table")?.classList.toggle("pedido-sem-preco", pedidoBonificacao());
    }

    async function syncPedidoConfig() {
      try {
        const response = await req("/api/admin/pedidos/config");
        pedidosUi.config = response;
        configurePedidoFiliais();
        configurePedidoOperacao(response);
        renderPedidoMotivos(response);
        renderPedidoBloqueio(response);
        return true;
      } catch (error) {
        pedidosSetStatus(error.message || "Não foi possível carregar as regras de digitação.", "err");
        return false;
      }
    }

    function formatPedidoMoney(value) {
      return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(Number(value || 0));
    }

    function renderPedidoManagerBars(targetId, items, emptyText) {
      const target = document.getElementById(targetId);
      if (!target) return;
      const total = Math.max(...items.map(item => Number(item.value || 0)), 1);
      target.innerHTML = items.length ? items.map(item => `<div class="pedido-manager-bar"><span title="${escapeHtml(item.label)}">${escapeHtml(item.label)}</span><div class="pedido-manager-bar-track"><i style="width:${Math.max(3, Number(item.value || 0) / total * 100)}%"></i></div><strong>${escapeHtml(String(item.value || 0))}</strong></div>`).join("") : `<div class="text-secondary small">${escapeHtml(emptyText)}</div>`;
    }

    function renderPedidoManagerLine(items = []) {
      const target = document.getElementById("pedidoGerencialDiaChart");
      if (!target) return;
      if (!items.length) { target.innerHTML = '<div class="text-secondary small py-4">Não há pedidos no período.</div>'; return; }
      const width = 540; const height = 172; const pad = { left: 30, right: 12, top: 15, bottom: 28 }; const max = Math.max(...items.map(item => Number(item.value || 0)), 1); const innerW = width - pad.left - pad.right; const innerH = height - pad.top - pad.bottom;
      const point = (item, index) => `${(pad.left + (items.length === 1 ? innerW / 2 : index * innerW / (items.length - 1))).toFixed(1)},${(pad.top + innerH - Number(item.value || 0) / max * innerH).toFixed(1)}`;
      const points = items.map(point).join(" "); const area = `${pad.left},${pad.top + innerH} ${points} ${pad.left + innerW},${pad.top + innerH}`;
      const labels = items.filter((_, index) => index === 0 || index === items.length - 1 || index === Math.floor((items.length - 1) / 2)).map((item, index, selected) => `<text x="${point(item, items.indexOf(item)).split(",")[0]}" y="${height - 7}" text-anchor="middle">${escapeHtml(formatDate(item.date).slice(0, 5))}</text>`).join("");
      const dots = items.map((item, index) => { const [x, y] = point(item, index).split(","); return `<circle class="trend-dot" cx="${x}" cy="${y}" r="3.5"><title>${escapeHtml(formatDate(item.date))}: ${escapeHtml(String(item.value))} pedido(s)</title></circle>`; }).join("");
      target.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Pedidos por dia"><defs><linearGradient id="pedidoTrendFill" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#7c5cff"/><stop offset="1" stop-color="#7c5cff" stop-opacity="0"/></linearGradient></defs><line class="trend-grid" x1="${pad.left}" x2="${pad.left + innerW}" y1="${pad.top + innerH}" y2="${pad.top + innerH}"/><polygon class="trend-area" fill="url(#pedidoTrendFill)" points="${area}"/><polyline class="trend-line" points="${points}"/>${dots}${labels}</svg>`;
    }

    function fillPedidoManagerFilter(id, values, placeholder) {
      const select = document.getElementById(id); if (!select) return;
      const current = select.value;
      const existing = [...select.options].map(option => option.value).filter(Boolean);
      const choices = [...new Set([...(values || []), ...existing, current].filter(Boolean))].sort((a, b) => String(a).localeCompare(String(b), "pt-BR"));
      select.innerHTML = `<option value="">${escapeHtml(placeholder)}</option>${choices.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("")}`;
      if (current) select.value = current;
    }

    function renderPedidoManagerAudit(payload) {
      const summary = payload.summary || {};
      document.getElementById("pedidoGerencialPedidos").textContent = formatStockNumber(summary.pedidos);
      document.getElementById("pedidoGerencialCaixas").textContent = formatStockNumber(summary.caixas);
      document.getElementById("pedidoGerencialValor").textContent = formatPedidoMoney(summary.valor);
      document.getElementById("pedidoGerencialExcecoes").textContent = formatStockNumber(Number(summary.pendentes || 0) + Number(summary.falhos || 0));
      renderPedidoManagerBars("pedidoGerencialMotivosChart", payload.motivos || [], "Não há pedidos no filtro.");
      renderPedidoManagerBars("pedidoGerencialStatusChart", payload.statuses || [], "Não há status no filtro.");
      renderPedidoManagerBars("pedidoGerencialUsuariosChart", (payload.usuarios || []).slice(0, 8), "Não há usuários no filtro.");
      renderPedidoManagerLine(payload.por_dia || []);
      const filters = payload.filters || {};
      fillPedidoManagerFilter("pedidoGerencialGv", filters.gvs, "Todos");
      fillPedidoManagerFilter("pedidoGerencialRn", filters.rns, "Todos");
      fillPedidoManagerFilter("pedidoGerencialCondicao", filters.condicoes, "Todas");
      const rows = Array.isArray(payload.rows) ? payload.rows : [];
      pedidosUi.audit = rows;
      const table = document.getElementById("pedidoGerencialTabela");
      const meta = document.getElementById("pedidoGerencialAuditoriaMeta");
      if (meta) meta.textContent = `${rows.length} pedido(s) no recorte`;
      if (!table) return;
      table.innerHTML = rows.length ? rows.map(row => `<tr><td>${escapeHtml(row.criado_em ? formatDateTime(row.criado_em) : "-")}</td><td><span class="pedido-queue-status" data-status="${escapeHtml(String(row.status || ""))}">${escapeHtml(pedidoQueueStatus(row.status).label)}</span></td><td>${escapeHtml(row.filial || "-")}</td><td class="mono">${escapeHtml(row.cliente || "-")}</td><td class="mono">${escapeHtml(row.mapa || "-")}</td><td>${escapeHtml(row.vendedor || "-")}</td><td>${escapeHtml(row.criado_por || "-")}</td><td class="mono">${escapeHtml(row.condicao || "Padrão")}</td><td>${escapeHtml(row.motivo || "-")}</td><td class="mono text-end">${escapeHtml(formatStockNumber(row.caixas))}</td><td class="mono text-end">${escapeHtml(formatPedidoMoney(row.valor))}</td><td class="mono">${escapeHtml(row.produtos || "-")}</td><td class="mono small">${escapeHtml(row.job_id || "-")}</td></tr>`).join("") : '<tr><td colspan="13" class="text-secondary text-center py-4">Nenhum pedido encontrado neste filtro.</td></tr>';
    }

    function renderPedidoManagerConfig(config) {
      const motivos = document.getElementById("pedidoGerencialMotivosTexto");
      const maxCaixas = document.getElementById("pedidoGerencialMaxCaixas");
      const meta = document.getElementById("pedidoGerencialConfigMeta");
      const motivoFilter = document.getElementById("pedidoGerencialMotivo");
      if (motivos) motivos.value = (config.motivos || []).join("\n");
      if (maxCaixas) maxCaixas.value = config.max_caixas_por_produto || "";
      const horarioBloqueio = document.getElementById("pedidoGerencialHorarioBloqueio");
      if (horarioBloqueio) horarioBloqueio.value = config.horario_bloqueio || "";
      if (meta) meta.textContent = config.updated_at ? `Atualizado por ${config.updated_by || "admin"} em ${formatDateTime(config.updated_at)}` : "Regra padrão";
      if (motivoFilter) {
        const current = motivoFilter.value;
        motivoFilter.innerHTML = `<option value="">Todos</option>${(config.motivos || []).map(motivo => `<option value="${escapeHtml(motivo)}">${escapeHtml(motivo)}</option>`).join("")}`;
        if ((config.motivos || []).includes(current)) motivoFilter.value = current;
      }
      pedidosUi.productLimits = Array.isArray(config.limites_por_produto) ? config.limites_por_produto.map(item => ({ ...item })) : [];
      renderPedidoProductLimits();
    }

    function renderPedidoProductLimits() {
      const table = document.getElementById("pedidoGerencialLimitesTabela");
      if (!table) return;
      table.innerHTML = pedidosUi.productLimits.length ? pedidosUi.productLimits.map((item, index) => `<tr><td class="mono">${escapeHtml(item.produto)}</td><td>${escapeHtml(item.descricao || "-")}</td><td class="text-end mono">${escapeHtml(formatStockNumber(item.limite))}</td><td class="text-end"><button class="btn btn-outline-danger btn-sm pedido-gerencial-limit-remove" data-index="${index}" type="button"><i class="bi bi-trash"></i><span class="visually-hidden">Remover</span></button></td></tr>`).join("") : '<tr><td colspan="4" class="text-secondary text-center py-3">Nenhum limite específico configurado.</td></tr>';
      table.querySelectorAll(".pedido-gerencial-limit-remove").forEach(button => button.addEventListener("click", () => { pedidosUi.productLimits.splice(Number(button.dataset.index), 1); renderPedidoProductLimits(); }));
    }

    function renderPedidoProductSearch(rows) {
      const wrap = document.getElementById("pedidoGerencialProdutoResultadosWrap"); const body = document.getElementById("pedidoGerencialProdutoResultados");
      if (!wrap || !body) return;
      wrap.hidden = false;
      body.innerHTML = rows.length ? rows.map((item, index) => `<button class="pedido-client-result pedido-gerencial-product-select" data-index="${index}" type="button"><span class="nb mono">${escapeHtml(item.produto)}</span><span><strong>${escapeHtml(item.descricao || "-")}</strong><span class="meta">Selecionar para aplicar um limite específico</span></span><i class="bi bi-plus-circle go"></i></button>`).join("") : '<div class="text-secondary small py-2">Nenhum produto encontrado na grade desta revenda.</div>';
      body.querySelectorAll(".pedido-gerencial-product-select").forEach(button => button.addEventListener("click", () => { const product = rows[Number(button.dataset.index)]; pedidosUi.selectedLimitProduct = product; const input = document.getElementById("pedidoGerencialProdutoBusca"); if (input) input.value = `${product.produto} · ${product.descricao}`; wrap.hidden = true; document.getElementById("pedidoGerencialProdutoAdicionarBtn").disabled = false; document.getElementById("pedidoGerencialProdutoLimite")?.focus(); }));
    }

    async function searchPedidoLimitProduct() {
      const filial = document.getElementById("pedidoGerencialProdutoFilial")?.value || ""; const busca = document.getElementById("pedidoGerencialProdutoBusca")?.value.trim() || "";
      pedidosUi.selectedLimitProduct = null; document.getElementById("pedidoGerencialProdutoAdicionarBtn").disabled = true;
      if (!filial || busca.length < 2) { document.getElementById("pedidoGerencialProdutoResultadosWrap").hidden = true; return; }
      try { const response = await req(`/api/admin/pedidos/gerencial/produtos?filial=${encodeURIComponent(filial)}&busca=${encodeURIComponent(busca)}`); renderPedidoProductSearch(response.items || []); } catch (error) { document.getElementById("pedidoGerencialConfigStatus").textContent = error.message || "Não foi possível consultar produtos."; }
    }

    function addPedidoProductLimit() {
      const product = pedidosUi.selectedLimitProduct; const limit = Number(document.getElementById("pedidoGerencialProdutoLimite")?.value || 0);
      if (!product || !Number.isInteger(limit) || limit < 1) { document.getElementById("pedidoGerencialConfigStatus").textContent = "Selecione um produto e informe um limite válido."; return; }
      const existing = pedidosUi.productLimits.findIndex(item => String(item.produto) === String(product.produto));
      const row = { produto: String(product.produto), descricao: String(product.descricao || ""), limite: limit };
      if (existing >= 0) pedidosUi.productLimits[existing] = row; else pedidosUi.productLimits.push(row);
      pedidosUi.productLimits.sort((a, b) => String(a.descricao || a.produto).localeCompare(String(b.descricao || b.produto), "pt-BR"));
      pedidosUi.selectedLimitProduct = null; document.getElementById("pedidoGerencialProdutoBusca").value = ""; document.getElementById("pedidoGerencialProdutoLimite").value = ""; document.getElementById("pedidoGerencialProdutoAdicionarBtn").disabled = true; renderPedidoProductLimits();
    }

    async function syncPedidoManagerConfig() {
      const response = await req("/api/admin/pedidos/gerencial/config");
      pedidosUi.config = response;
      renderPedidoMotivos(response);
      renderPedidoBloqueio(response);
      renderPedidoManagerConfig(response);
      return response;
    }

    async function syncPedidoManagerAudit() {
      const query = new URLSearchParams();
      const controls = [["data_de", "pedidoGerencialDataDe"], ["data_ate", "pedidoGerencialDataAte"], ["filial", "pedidoGerencialFilial"], ["gv", "pedidoGerencialGv"], ["rn", "pedidoGerencialRn"], ["condicao", "pedidoGerencialCondicao"], ["motivo", "pedidoGerencialMotivo"], ["status", "pedidoGerencialStatus"]];
      controls.forEach(([key, id]) => { const value = document.getElementById(id)?.value || ""; if (value) query.set(key, value); });
      const response = await req(`/api/admin/pedidos/gerencial/auditoria?${query.toString()}`);
      renderPedidoManagerAudit(response);
      return response;
    }

    async function syncPedidoManager({ silent = false } = {}) {
      const status = document.getElementById("pedidoGerencialConfigStatus");
      if (!silent && status) status.textContent = "Atualizando regras e auditoria...";
      try {
        // Os bloqueados têm o próprio aviso de erro; uma falha lá não derruba o resto do gerencial.
        await Promise.all([syncPedidoManagerConfig(), syncPedidoManagerAudit(), syncPedidoBloqueados({ silent: true })]);
        if (status) status.textContent = "Dados atualizados.";
        return true;
      } catch (error) {
        if (status) status.textContent = error.message || "Não foi possível carregar o gerencial.";
        return false;
      }
    }

    function exportPedidoManagerAudit() {
      const rows = pedidosUi.audit || [];
      if (!rows.length) { document.getElementById("pedidoGerencialConfigStatus").textContent = "Não há pedidos no filtro para exportar."; return; }
      const columns = [["criado_em", "Criado em"], ["status", "Status"], ["filial", "Filial"], ["cliente", "NB"], ["mapa", "Mapa"], ["vendedor", "GV"], ["criado_por", "RN"], ["condicao", "Condição"], ["motivo", "Motivo"], ["caixas", "Caixas"], ["valor", "Valor informado"], ["produtos", "Produtos"], ["job_id", "Job"]];
      const escapeCsv = value => `"${String(value ?? "").replaceAll('"', '""')}"`;
      const csv = "\uFEFF" + [columns.map(([, label]) => escapeCsv(label)).join(";"), ...rows.map(row => columns.map(([key]) => escapeCsv(row[key])).join(";"))].join("\r\n");
      const link = document.createElement("a"); link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" })); link.download = `auditoria-pedidos-${new Date().toISOString().slice(0, 10)}.csv`; link.click(); URL.revokeObjectURL(link.href);
    }

    async function salvarPedidoManagerConfig() {
      const status = document.getElementById("pedidoGerencialConfigStatus");
      const motivos = (document.getElementById("pedidoGerencialMotivosTexto")?.value || "").split(/\r?\n/).map(value => value.trim()).filter(Boolean);
      const max_caixas_por_produto = Number(document.getElementById("pedidoGerencialMaxCaixas")?.value || 0);
      const horario_bloqueio = (document.getElementById("pedidoGerencialHorarioBloqueio")?.value || "").slice(0, 5);
      if (horario_bloqueio === "00:00") { if (status) status.textContent = "Use um horário depois de 00:00, ou deixe vazio para não bloquear."; return; }
      if (!motivos.length || !Number.isInteger(max_caixas_por_produto) || max_caixas_por_produto < 1) { if (status) status.textContent = "Informe ao menos um motivo e um limite válido."; return; }
      if (!await askConfirmation("Salvar as regras da digitação? Elas passarão a valer para os próximos pedidos.")) return;
      if (status) status.textContent = "Salvando regras...";
      try {
        const response = await req("/api/admin/pedidos/gerencial/config", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ motivos, max_caixas_por_produto, limites_por_produto: pedidosUi.productLimits, horario_bloqueio }) });
        pedidosUi.config = response; renderPedidoMotivos(response); renderPedidoBloqueio(response); renderPedidoManagerConfig(response);
        if (status) status.textContent = "Regras salvas e aplicadas aos próximos pedidos.";
      } catch (error) { if (status) status.textContent = error.message || "Não foi possível salvar as regras."; }
    }

    function setPedidoSubtab(tab) {
      const isManager = tab === "gerencial" && Boolean(state.panel?.isAdmin);
      document.getElementById("pedidoDigitacaoWorkspace").hidden = isManager;
      document.getElementById("pedidoGerencialPane").hidden = !isManager;
      document.querySelectorAll(".pedido-subtab").forEach(button => { const active = button.dataset.pedidoSubtab === (isManager ? "gerencial" : "digitacao"); button.classList.toggle("is-active", active); button.setAttribute("aria-selected", String(active)); });
      if (isManager) syncPedidoManager();
    }

    function pedidoPodeDigitar() {
      return Boolean(pedidosUi.client && pedidosUi.client.pedido_liberado && !pedidosUi.loadingClient && !pedidosUi.bloqueadoPorHorario);
    }

    function syncPedidoControls() {
      const liberado = pedidoPodeDigitar();
      document.getElementById("pedidoEnviarBtn")?.toggleAttribute("disabled", !liberado);
      document.getElementById("pedidoAdicionarItemBtn")?.toggleAttribute("disabled", !liberado);
      document.querySelectorAll(".pedido-item-produto, .pedido-item-qtd, .pedido-item-preco, .pedido-item-remove, #pedidoCondicao, #pedidoMotivo").forEach(element => {
        element.toggleAttribute("disabled", !liberado || (element.classList.contains("pedido-item-remove") && pedidosUi.items.length === 1));
      });
    }

    // 600 retornável: digitado em dúzias, só sai em caixa fechada (2 dúzias). Mesma regra do servidor
    // (services/pedido_caixa_fechada.py); o servidor confere de novo no envio.
    const PEDIDO_DUZIAS_POR_CAIXA = 2;
    function pedidoTextoBusca(valor) {
      return String(valor || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toUpperCase().replace(/\s+/g, " ").trim();
    }
    // Só pela descrição: o litrão também vem em DZ na grade, mas a caixa dele é de 1 dúzia.
    function pedidoCaixaFechada(item) {
      const texto = pedidoTextoBusca(item.descricao);
      return /\b600\s*(ML|M\b|\b)/.test(texto) && !/ONE\s*WAY|\bPET\b|\bLATA\b|\bLT\b|C\/\s*\d+|\bCAIXA\b|\bCX\b/.test(texto);
    }

    function renderPedidoItens(focusProductIndex = null) {
      const body = document.getElementById("pedidoItensBody");
      if (!body) return;
      if (!pedidosUi.items.length) pedidosUi.items.push({ produto: "", quantidade: 1 });
      const disabled = pedidoPodeDigitar() ? "" : "disabled";
      body.innerHTML = pedidosUi.items.map((item, index) => {
        const stock = item.saldo_disponivel === undefined || item.saldo_disponivel === null ? "" : `<span class="${Number(item.saldo_disponivel) > 0 ? "pedido-stock-available" : "pedido-stock-empty"}">Disponível: ${escapeHtml(formatStockNumber(item.saldo_disponivel))}</span>`;
        const caixa = Boolean(item.produto) && pedidoCaixaFechada(item);
        const aviso = caixa ? `<div class="pedido-caixa-aviso" id="pedidoCaixaAviso${index}"><i class="bi bi-box-seam me-1" aria-hidden="true"></i>Só caixa fechada: digite dúzias em número par (1 caixa = ${PEDIDO_DUZIAS_POR_CAIXA} dz).</div>` : "";
        const selected = item.produto ? `<div class="pedido-product-selected"><strong class="mono">${escapeHtml(item.produto)}</strong>${item.descricao ? ` · ${escapeHtml(item.descricao)}` : ""}${stock ? ` · ${stock}` : ""}</div>${aviso}` : "";
        const suggestions = Array.isArray(item.suggestions) && item.suggestions.length ? `<div class="pedido-product-suggestions" role="listbox" aria-label="Produtos encontrados">${item.suggestions.map((product, productIndex) => `<button class="pedido-product-option" data-index="${index}" data-product-index="${productIndex}" type="button" role="option"><span class="code mono">${escapeHtml(product.codigo_produto)}</span><span class="name">${escapeHtml(product.descricao_produto)}</span><span class="stock">${escapeHtml(formatStockNumber(product.saldo_disponivel))}</span></button>`).join("")}</div>` : "";
        const max = item.saldo_disponivel !== undefined && Number(item.saldo_disponivel) >= 0 ? `max="${Math.floor(Number(item.saldo_disponivel))}"` : "max=\"99999\"";
        return `<tr><td class="pedido-product-cell"><label class="d-md-none small text-secondary">Produto na grade</label><input class="form-control form-control-sm pedido-item-produto" data-index="${index}" value="${escapeHtml(item.busca || item.produto || "")}" autocomplete="off" placeholder="Nome (3 letras) ou código" ${disabled}>${selected}${suggestions}</td><td><label class="d-md-none small text-secondary">Quantidade</label><input class="form-control form-control-sm mono pedido-item-qtd" data-index="${index}" value="${escapeHtml(String(item.quantidade || 1))}" inputmode="numeric" type="number" ${caixa ? `min="${PEDIDO_DUZIAS_POR_CAIXA}" step="${PEDIDO_DUZIAS_POR_CAIXA}" aria-describedby="pedidoCaixaAviso${index}"` : 'min="1"'} ${max} ${disabled}></td><td class="pedido-col-preco"><label class="d-md-none small text-secondary">Preço unitário</label><div class="input-group input-group-sm"><span class="input-group-text">R$</span><input class="form-control mono pedido-item-preco" data-index="${index}" value="${escapeHtml(String(item.preco || ""))}" inputmode="decimal" placeholder="0,00" ${disabled}></div></td><td class="text-end"><button class="btn btn-outline-danger btn-sm pedido-item-remove" data-index="${index}" type="button" ${disabled || pedidosUi.items.length === 1 ? "disabled" : ""} aria-label="Remover item"><i class="bi bi-trash"></i></button></td></tr>`;
      }).join("");
      body.querySelectorAll(".pedido-item-produto").forEach(input => input.addEventListener("input", event => pesquisarProdutoPedido(Number(event.target.dataset.index), event.target.value, event.target)));
      body.querySelectorAll(".pedido-item-qtd").forEach(input => input.addEventListener("input", event => { pedidosUi.items[Number(event.target.dataset.index)].quantidade = Number(event.target.value || 0); }));
      body.querySelectorAll(".pedido-item-preco").forEach(input => input.addEventListener("input", event => { pedidosUi.items[Number(event.target.dataset.index)].preco = event.target.value; }));
      body.querySelectorAll(".pedido-item-remove").forEach(button => button.addEventListener("click", () => { pedidosUi.items.splice(Number(button.dataset.index), 1); renderPedidoItens(); }));
      body.querySelectorAll(".pedido-product-option").forEach(button => button.addEventListener("click", () => {
        const item = pedidosUi.items[Number(button.dataset.index)];
        const product = (item.suggestions || [])[Number(button.dataset.productIndex)];
        if (!product) return;
        item.produto = String(product.codigo_produto || "");
        item.descricao = String(product.descricao_produto || "");
        item.unidade = String(product.unidade_medida || "");
        item.saldo_disponivel = Number(product.saldo_disponivel || 0);
        item.busca = `${item.produto} · ${item.descricao}`;
        item.suggestions = [];
        if (Number(item.quantidade || 1) > item.saldo_disponivel) item.quantidade = Math.max(1, Math.floor(item.saldo_disponivel));
        // Caixa fechada: arredonda para cima até a caixa inteira (2 dúzias).
        if (pedidoCaixaFechada(item) && Number(item.quantidade || 0) % PEDIDO_DUZIAS_POR_CAIXA) item.quantidade = Number(item.quantidade || 0) + 1;
        renderPedidoItens();
      }));
      syncPedidoControls();
      if (Number.isInteger(focusProductIndex)) {
        const input = body.querySelector(`.pedido-item-produto[data-index="${focusProductIndex}"]`);
        if (input && !input.disabled) {
          input.focus();
          input.setSelectionRange(input.value.length, input.value.length);
        }
      }
    }

    async function pesquisarProdutoPedido(index, value, inputElement = null) {
      const item = pedidosUi.items[index];
      if (!item) return;
      item.busca = String(value || "");
      item.produto = "";
      item.descricao = "";
      item.unidade = "";
      item.saldo_disponivel = undefined;
      item.suggestions = [];
      const rowCell = inputElement?.closest(".pedido-product-cell");
      rowCell?.querySelector(".pedido-product-suggestions")?.remove();
      rowCell?.querySelector(".pedido-product-selected")?.remove();
      const filial = document.getElementById("pedidoFilial")?.value || "";
      const busca = item.busca.trim();
      clearTimeout(pedidosUi.stockTimers[index]);
      const minChars = /^\d+$/.test(busca) ? 2 : 3;
      if (!filial || busca.length < minChars) return;
      pedidosUi.stockTimers[index] = setTimeout(async () => {
        try {
          const result = await req(`/api/admin/pedidos/estoque?filial=${encodeURIComponent(filial)}&busca=${encodeURIComponent(busca)}`);
          if (!result.ready) throw new Error("A grade desta filial ainda não foi atualizada.");
          if (!pedidosUi.items[index] || pedidosUi.items[index].busca !== busca) return;
          pedidosUi.items[index].suggestions = result.items || [];
          renderPedidoItens(index);
        } catch (error) {
          pedidosSetStatus(error.message || "Não foi possível consultar a grade.", "err");
        }
      }, 650);
    }

    function renderPedidoClientResults(rows) {
      const wrap = document.getElementById("pedidoClienteResultadosWrap");
      const body = document.getElementById("pedidoClienteResultados");
      if (!wrap || !body) return;
      wrap.hidden = false;
      if (!rows.length) { body.innerHTML = '<div class="text-center text-secondary py-3">Nenhum cliente encontrado na sua carteira.</div>'; return; }
      body.innerHTML = rows.map((item, index) => `<button class="pedido-client-result pedido-client-select" data-index="${index}" type="button"><span class="nb mono">${escapeHtml(item.cliente)}</span><span><strong>${escapeHtml(item.nome || item.razao_social || "-")}</strong><span class="meta">${escapeHtml(item.cidade || "Sem cidade")} · Setor ${escapeHtml(item.vendedor || "-")}</span></span><i class="bi bi-chevron-right go" aria-hidden="true"></i></button>`).join("");
      body.querySelectorAll(".pedido-client-select").forEach(button => button.addEventListener("click", () => selectPedidoClient(rows[Number(button.dataset.index)])));
    }

    function dataBrPedidoLiberacao(valor) {
      const partes = String(valor || "").split("-");
      return partes.length === 3 ? `${partes[2]}/${partes[1]}/${partes[0]}` : "-";
    }

    function renderPedidoClientDetails(client) {
      const selected = document.getElementById("pedidoClienteSelecionado");
      if (!selected) return;
      const inad = client.inadimplencia || {};
      // Cliente com título em aberto pode ter sido liberado pelo administrador (gerencial).
      const liberacao = inad.bloqueado && inad.liberacao ? inad.liberacao : null;
      const blocked = Boolean(inad.bloqueado) && !liberacao;
      const facts = [
        ["NB", client.cliente], ["Filial", client.filial], ["Cidade", client.cidade || "-"], ["Setor", client.vendedor || "-"],
        ["Telefone", client.telefone || "-"], ["Visita", diasVisitaTexto(client.dia_visita) || "-"], ["Condição", client.cond_pagto || "Não informada"], ["Status", client.status || "-"],
        ["Limite crédito", client.limite_credito || "-"], ["Valor em aberto", client.total_pendente || "-"], ["Comodatos", client.comodatos_pendentes || "0"], ["Atualizado em", client.atualizado_em || "-"]
      ];
      const titles = Array.isArray(inad.titulos) ? inad.titulos.slice(0, 5) : [];
      selected.className = "pedido-client-card";
      selected.dataset.state = blocked ? "blocked" : "ready";
      selected.innerHTML = `<div class="pedido-client-head"><div class="pedido-client-title"><h3>${escapeHtml(client.nome || client.razao_social || "Cliente")}</h3><p>${escapeHtml(client.razao_social || "")}</p></div><span class="pedido-eligibility ${blocked ? "blocked" : "ready"}"><i class="bi ${blocked ? "bi-slash-circle" : "bi-check2-circle"}"></i>${blocked ? "Bloqueado · títulos em aberto" : liberacao ? "Liberado pelo administrador" : "Liberado para digitação"}</span></div><div class="pedido-client-facts">${facts.map(([label, value]) => `<div class="pedido-client-fact"><span class="label">${escapeHtml(label)}</span><span class="value">${escapeHtml(String(value))}</span></div>`).join("")}</div>${blocked ? `<div class="pedido-block-reason"><i class="bi bi-shield-exclamation me-1"></i>Este cliente tem ${escapeHtml(String(inad.quantidade_titulos || titles.length))} título(s) em aberto. A digitação está bloqueada.<ul>${titles.map(title => `<li>NF ${escapeHtml(title.nota_fiscal || "-")} · vence ${escapeHtml(title.vencimento || "-")} · ${escapeHtml(title.valor_pendente || "-")}${title.dias ? ` · ${escapeHtml(title.dias)}` : ""}</li>`).join("")}</ul></div>` : ""}${liberacao ? `<div class="pedido-liberacao-aviso"><i class="bi bi-unlock me-1" aria-hidden="true"></i>Tem ${escapeHtml(String(inad.quantidade_titulos || titles.length))} título(s) em aberto, mas foi liberado por ${escapeHtml(liberacao.liberado_por || "administrador")} até ${escapeHtml(dataBrPedidoLiberacao(liberacao.valida_ate))}. Motivo: ${escapeHtml(liberacao.motivo || "-")}</div>` : ""}`;
    }

    function clearPedidoClient(message = "Selecione um cliente para ver o cadastro e os títulos em aberto.") {
      pedidosUi.client = null;
      pedidosUi.loadingClient = false;
      pedidosUi.conditions = [];
      setPedidoTitle();
      renderPedidoConditions();
      const selected = document.getElementById("pedidoClienteSelecionado");
      if (selected) { selected.className = "alert alert-info mb-0"; selected.dataset.state = ""; selected.innerHTML = `<i class="bi bi-person-vcard me-2"></i>${escapeHtml(message)}`; }
      renderPedidoItens();
      pedidosSetStatus("Escolha um cliente elegível para liberar a digitação.");
    }

    function renderPedidoConditions({ message = "Condições liberadas para este cliente." } = {}) {
      const select = document.getElementById("pedidoCondicao");
      const hint = document.getElementById("pedidoCondicaoHint");
      if (!select) return;
      const previous = select.value;
      const defaultLabel = pedidosUi.client?.cond_pagto ? `Padrão atual do cliente (${pedidosUi.client.cond_pagto})` : "Padrão atual do cliente";
      const options = [`<option value="">${escapeHtml(defaultLabel)}</option>`];
      const clientCondition = String(pedidosUi.client?.cond_pagto || "").trim();
      const listedConditions = pedidosUi.conditions.some(item => String(item?.codigo || "").trim() === "2")
        ? pedidosUi.conditions
        : [{ codigo: "2", descricao: "Dinheiro" }, ...pedidosUi.conditions];
      listedConditions.forEach(item => {
        const code = String(item.codigo || "").trim();
        if (!code) return;
        const label = code === clientCondition ? `${code} · Condição atual` : `${code}${item.descricao ? ` · ${item.descricao}` : ""}`;
        options.push(`<option value="${escapeHtml(code)}">${escapeHtml(label)}</option>`);
      });
      select.innerHTML = options.join("");
      if (pedidosUi.conditions.some(item => String(item.codigo) === previous)) select.value = previous;
      if (hint) hint.textContent = message;
    }

    async function loadPedidoConditions(filial, cliente) {
      // Dinheiro é uma condição liberada operacionalmente e fica visível
      // desde o carregamento, inclusive se o catálogo Promax falhar.
      pedidosUi.conditions = [{ codigo: "2", descricao: "Dinheiro" }];
      renderPedidoConditions({ message: "Carregando as demais condições liberadas..." });
      try {
        const response = await req(`/api/admin/pedidos/condicoes?filial=${encodeURIComponent(filial)}&cliente=${encodeURIComponent(cliente)}`);
        const conditions = Array.isArray(response.condicoes) ? response.condicoes : [];
        pedidosUi.conditions = conditions.some(item => String(item?.codigo || "").trim() === "2")
          ? conditions
          : [{ codigo: "2", descricao: "Dinheiro" }, ...conditions];
        const when = response.atualizado_em ? ` Atualizada em ${formatDateTime(response.atualizado_em)}.` : "";
        renderPedidoConditions({ message: `${response.mensagem || "Mantenha a condição padrão do cliente."}${when}` });
      } catch (error) {
        renderPedidoConditions({ message: "Não foi possível carregar as condições permitidas agora. Mantenha a condição padrão do cliente." });
      }
    }

    // Filiais da carteira do usuário (setores, GVs ou operações), vindas de /pedidos/config.
    function configurePedidoFiliais() {
      const select = document.getElementById("pedidoFilial");
      const filiais = pedidosUi.config?.filiais;
      if (!select || !Array.isArray(filiais)) return;
      const atual = select.value;
      const opcoes = filiais.map(item => `<option value="${escapeHtml(item.codigo)}">${escapeHtml(item.nome)}</option>`).join("");
      select.innerHTML = filiais.length === 1 ? opcoes : `<option value="">${filiais.length ? "Selecione" : "Nenhuma filial na sua carteira"}</option>${opcoes}`;
      const codigos = filiais.map(item => item.codigo);
      if (codigos.includes(atual)) {
        select.value = atual;
      } else if (codigos.length === 1) {
        select.value = codigos[0];
        clearPedidoClient("Filial definida pela sua carteira. Pesquise o cliente.");
      } else if (atual) {
        clearPedidoClient("Selecione uma filial da sua carteira.");
      }
    }

    async function selectPedidoClient(client) {
      const wrap = document.getElementById("pedidoClienteResultadosWrap"); if (wrap) wrap.hidden = true;
      pedidosUi.client = null;
      pedidosUi.loadingClient = true;
      renderPedidoItens();
      pedidosSetStatus("Consultando o cliente...");
      const selected = document.getElementById("pedidoClienteSelecionado");
      if (selected) { selected.className = "alert alert-info mb-0"; selected.innerHTML = '<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>Consultando o cliente...'; }
      try {
        const response = await req(`/api/admin/pedidos/clientes/${encodeURIComponent(client.filial)}/${encodeURIComponent(client.cliente)}`);
        pedidosUi.client = response.cliente || null;
        pedidosUi.loadingClient = false;
        if (!pedidosUi.client) throw new Error("Cliente não encontrado.");
        setPedidoTitle(pedidosUi.client);
        renderPedidoClientDetails(pedidosUi.client);
        await loadPedidoConditions(pedidosUi.client.filial, pedidosUi.client.cliente);
        renderPedidoItens();
        pedidosSetStatus(pedidosUi.client.pedido_liberado ? "Cliente liberado. Informe os itens e envie o pedido." : "Cliente bloqueado pela 12.06.01. A digitação não é permitida.", pedidosUi.client.pedido_liberado ? "ok" : "err");
      } catch (error) {
        clearPedidoClient(error.message || "Não foi possível consultar o cliente.");
        pedidosSetStatus(error.message || "Não foi possível consultar o cliente.", "err");
      }
    }

    async function buscarPedidoCliente() {
      const filial = document.getElementById("pedidoFilial")?.value || "";
      const busca = document.getElementById("pedidoClienteBusca")?.value.trim() || "";
      if (busca.length < 2) { pedidosSetStatus("Informe ao menos 2 caracteres para buscar o cliente.", "err"); return; }
      if (/^\d+$/.test(busca) && !filial) { pedidosSetStatus("Selecione a filial ao buscar pelo NB.", "err"); return; }
      pedidosSetStatus("Buscando clientes autorizados...");
      try {
        const response = await req(`/api/admin/pedidos/clientes?busca=${encodeURIComponent(busca)}${filial ? `&filial=${encodeURIComponent(filial)}` : ""}`);
        const scope = document.getElementById("pedidosScopeLabel");
        if (scope) scope.textContent = response.seller_scopes && response.seller_scopes.length ? `Carteira: ${response.seller_scopes.join(", ")}` : "Acesso administrativo";
        renderPedidoClientResults(response.clientes || []);
        pedidosSetStatus(`${Number(response.total || 0)} cliente(s) encontrado(s).`, "ok");
      } catch (error) { pedidosSetStatus(error.message, "err"); }
    }

    async function enviarPedido() {
      const filial = document.getElementById("pedidoFilial")?.value || "";
      const condPagto = document.getElementById("pedidoCondicao")?.value.trim() || "";
      const motivo = document.getElementById("pedidoMotivo")?.value.trim() || "";
      const bonificacao = pedidoBonificacao();
      const operacao = bonificacao ? "2" : "1";
      const foraDaCaixa = pedidosUi.items.find(item => item.produto && Number(item.quantidade) > 0 && pedidoCaixaFechada(item) && Number(item.quantidade) % PEDIDO_DUZIAS_POR_CAIXA);
      const itens = pedidosUi.items.filter(item => item.produto && Number(item.quantidade) > 0).map(item => ({ produto: item.produto, quantidade: Number(item.quantidade), preco: bonificacao ? "" : String(item.preco || "").trim() }));
      if (pedidosUi.bloqueadoPorHorario) { pedidosSetStatus(pedidosUi.config?.mensagem || "A digitação de novos pedidos está encerrada.", "err"); return; }
      if (!pedidosUi.client || !filial) { pedidosSetStatus("Selecione a filial e um cliente autorizado.", "err"); return; }
      if (!pedidosUi.client.pedido_liberado) { pedidosSetStatus("Cliente com títulos em aberto. Não é possível digitar pedido.", "err"); return; }
      if (String(pedidosUi.client.filial) !== String(filial)) { pedidosSetStatus("A filial escolhida é diferente da filial do cliente.", "err"); return; }
      if (!itens.length) { pedidosSetStatus("Inclua ao menos um item válido.", "err"); return; }
      if (foraDaCaixa) { pedidosSetStatus(`${foraDaCaixa.descricao || foraDaCaixa.produto}: o 600 só sai em caixa fechada. Digite um número par de dúzias (1 caixa = ${PEDIDO_DUZIAS_POR_CAIXA} dz).`, "err"); return; }
      if (!motivo) { pedidosSetStatus("Selecione o motivo da digitação.", "err"); return; }
      if (!bonificacao && itens.some(item => !item.preco)) { pedidosSetStatus("Informe o preço unitário de cada item.", "err"); return; }
      if (!await askConfirmation(`Enviar ${bonificacao ? "bonificação" : "pedido"} para ${pedidosUi.client.nome || pedidosUi.client.razao_social}?`)) return;
      pedidosSetStatus("Validando e enviando para a fila...");
      try {
        const result = await req("/api/admin/pedidos/jobs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ filial, cliente: pedidosUi.client.cliente, itens, cond_pagto: condPagto, motivo_digitacao: motivo, operacao }) });
        const cliente = pedidosUi.client.cliente;
        clearTimeoutsPedidoStock();
        pedidosUi.items = [{ produto: "", quantidade: 1 }];
        const busca = document.getElementById("pedidoClienteBusca"); if (busca) busca.value = "";
        const resultados = document.getElementById("pedidoClienteResultadosWrap"); if (resultados) resultados.hidden = true;
        const resultadoBody = document.getElementById("pedidoClienteResultados"); if (resultadoBody) resultadoBody.innerHTML = "";
        const motivoInput = document.getElementById("pedidoMotivo"); if (motivoInput) motivoInput.value = "";
        const operacaoInput = document.getElementById("pedidoOperacao"); if (operacaoInput) { operacaoInput.value = "1"; aplicarPedidoOperacao(); }
        clearPedidoClient(`Pedido do NB ${cliente} enviado para a fila. Você já pode iniciar um novo pedido.`);
        pedidosSetStatus(`Pedido do NB ${cliente} enviado para a fila.`, "ok");
        addLog(`Pedido enviado: cliente ${cliente}.`, "ok");
        await syncPedidoQueue({ silent: true });
      } catch (error) {
        pedidosSetStatus(error.message, "err");
        // Se o horário de bloqueio chegou com a tela aberta, o aviso aparece já.
        syncPedidoConfig();
      }
    }

    function clearTimeoutsPedidoStock() {
      Object.values(pedidosUi.stockTimers).forEach(timer => clearTimeout(timer));
      pedidosUi.stockTimers = {};
    }

    function setupPedidosPanel() {
      setPedidoTitle();
      renderPedidoItens();
      document.getElementById("pedidoAdicionarItemBtn")?.addEventListener("click", () => { if (pedidoPodeDigitar()) { pedidosUi.items.push({ produto: "", quantidade: 1 }); renderPedidoItens(); } });
      document.getElementById("pedidoClienteBuscarBtn")?.addEventListener("click", buscarPedidoCliente);
      document.getElementById("pedidoClienteBusca")?.addEventListener("keydown", event => { if (event.key === "Enter") { event.preventDefault(); buscarPedidoCliente(); } });
      document.getElementById("pedidoEnviarBtn")?.addEventListener("click", enviarPedido);
      document.getElementById("pedidoOperacao")?.addEventListener("change", aplicarPedidoOperacao);
      document.getElementById("pedidoFilaAtualizarBtn")?.addEventListener("click", () => syncPedidoQueue());
      document.getElementById("pedidoFilial")?.addEventListener("change", () => clearPedidoClient("A filial foi alterada. Pesquise novamente o cliente."));
      document.querySelectorAll(".pedido-subtab").forEach(button => button.addEventListener("click", () => setPedidoSubtab(button.dataset.pedidoSubtab || "digitacao")));
      document.getElementById("pedidoGerencialAtualizarBtn")?.addEventListener("click", () => syncPedidoManager());
      document.getElementById("pedidoGerencialSalvarBtn")?.addEventListener("click", salvarPedidoManagerConfig);
      document.getElementById("pedidoGerencialExportarBtn")?.addEventListener("click", exportPedidoManagerAudit);
      ["pedidoGerencialDataDe", "pedidoGerencialDataAte", "pedidoGerencialFilial", "pedidoGerencialGv", "pedidoGerencialRn", "pedidoGerencialCondicao", "pedidoGerencialMotivo", "pedidoGerencialStatus"].forEach(id => document.getElementById(id)?.addEventListener("change", () => syncPedidoManagerAudit()));
      document.getElementById("pedidoGerencialProdutoBusca")?.addEventListener("input", () => { clearTimeout(pedidosUi.managerProductTimer); pedidosUi.managerProductTimer = setTimeout(searchPedidoLimitProduct, 450); });
      document.getElementById("pedidoGerencialProdutoFilial")?.addEventListener("change", () => { pedidosUi.selectedLimitProduct = null; document.getElementById("pedidoGerencialProdutoBusca").value = ""; document.getElementById("pedidoGerencialProdutoResultadosWrap").hidden = true; document.getElementById("pedidoGerencialProdutoAdicionarBtn").disabled = true; });
      document.getElementById("pedidoGerencialProdutoAdicionarBtn")?.addEventListener("click", addPedidoProductLimit);
    }
