    function isConferenciaProduto(item) {
      return String(item && item.grupo_contagem || "").toUpperCase() === "PRODUTO";
    }

    function isConferenciaGarrafeira(item) {
      return CONFERENCIA_GARRAFEIRA_GROUPS.includes(String(item && item.grupo_contagem || "").toUpperCase());
    }

    function conferenciaNumberAttrs() {
      return 'type="number" step="1" min="0" inputmode="numeric" pattern="[0-9]*"';
    }

    function renderConferenciaCountFields(item) {
      if (isConferenciaProduto(item)) {
        const factor = Number(item.unidades_por_caixa || 0);
        const cxLabel = factor > 1 ? `Cx (${factor} un)` : "Cx";
        return `
          <div class="conference-count-pair">
            <label>${escapeHtml(cxLabel)}<input class="form-control form-control-sm" ${conferenciaNumberAttrs()} data-conferencia-field="contagem_caixas" value="${escapeHtml(item.contagem_caixas || "")}" placeholder="0"></label>
            <label>Un<input class="form-control form-control-sm" ${conferenciaNumberAttrs()} data-conferencia-field="contagem_unidades" value="${escapeHtml(item.contagem_unidades || "")}" placeholder="0"></label>
          </div>
          <input type="hidden" data-conferencia-field="contagem_real" value="${escapeHtml(item.contagem_real || "")}">
        `;
      }
      if (isConferenciaGarrafeira(item)) {
        return `
          <div class="conference-count-pair">
            <label>Cheia<input class="form-control form-control-sm" ${conferenciaNumberAttrs()} data-conferencia-field="contagem_real" value="${escapeHtml(item.contagem_real || "")}" placeholder="0"></label>
            <label>Vazia<input class="form-control form-control-sm" ${conferenciaNumberAttrs()} data-conferencia-field="contagem_vazia" value="${escapeHtml(item.contagem_vazia || "")}" placeholder="0"></label>
          </div>
        `;
      }
      const integerCount = CONFERENCIA_INTEGER_GROUPS.includes(String(item && item.grupo_contagem || "").toUpperCase());
      const countInputAttrs = integerCount ? 'type="number" step="1" inputmode="numeric" pattern="[0-9]*"' : 'type="number" step="0.001" inputmode="decimal"';
      return `<input class="form-control form-control-sm conference-count-input" ${countInputAttrs} min="0" data-conferencia-field="contagem_real" value="${escapeHtml(item.contagem_real || "")}" placeholder="Digite">`;
    }

    function conferenciaElements() {
      return {
        data: document.getElementById("conferenciaData"),
        filial: document.getElementById("conferenciaFilial"),
        search: document.getElementById("conferenciaSearch"),
        grupo: document.getElementById("conferenciaGrupo"),
        status: document.getElementById("conferenciaStatus"),
        refresh: document.getElementById("conferenciaRefreshBtn"),
        save: document.getElementById("conferenciaSaveBtn"),
        count: document.getElementById("conferenciaMapCount"),
        list: document.getElementById("conferenciaMapList"),
        editor: document.getElementById("conferenciaEditor"),
        views: document.getElementById("conferenciaViews"),
        mapasView: document.getElementById("conferenciaMapasView"),
        garrafeirasView: document.getElementById("conferenciaGarrafeirasView")
      };
    }

    function canViewConferenciaGarrafeiras() {
      return Boolean(state.panel && (state.panel.isAdmin || state.panel.canFinanceiro));
    }

    function setupConferenciaControls() {
      const els = conferenciaElements();
      if (els.data && !els.data.value) els.data.value = formatDateInputValue(new Date());
      if (els.filial) {
        const previous = els.filial.value || "";
        const allowed = Array.isArray(state.panel && state.panel.filiais) ? state.panel.filiais : [];
        const hasAll = !allowed.length || allowed.includes("*");
        const options = ['<option value="">Todas liberadas</option>'].concat(PROMAX_RESELLERS.map(item => {
          const filial = promaxFilialFromUnit(item.id);
          if (!hasAll && !allowed.includes(filial) && !allowed.includes(item.id)) return "";
          return `<option value="${escapeHtml(filial)}">${escapeHtml(filial)} - ${escapeHtml(item.name)}</option>`;
        })).join("");
        els.filial.innerHTML = options;
        if (previous && Array.from(els.filial.options).some(option => option.value === previous)) {
          els.filial.value = previous;
        }
      }
      if (els.refresh && !els.refresh.dataset.bound) {
        els.refresh.addEventListener("click", () => {
          if (state.conferencia.view === "garrafeiras") syncConferenciaGarrafeiras({ silent: false });
          else syncConferencia({ silent: false, forceDetail: true });
        });
        els.refresh.dataset.bound = "1";
      }
      if (els.save && !els.save.dataset.bound) {
        els.save.addEventListener("click", saveConferenciaCounts);
        els.save.dataset.bound = "1";
      }
      if (els.data && !els.data.dataset.bound) {
        els.data.addEventListener("change", () => {
          if (state.conferencia.view === "garrafeiras") syncConferenciaGarrafeiras({ silent: true });
          else syncConferencia({ silent: true });
        });
        els.data.dataset.bound = "1";
      }
      if (els.filial && !els.filial.dataset.bound) {
        els.filial.addEventListener("change", () => {
          if (state.conferencia.view === "garrafeiras") syncConferenciaGarrafeiras({ silent: true });
          else syncConferencia({ silent: true });
        });
        els.filial.dataset.bound = "1";
      }
      if (els.search && !els.search.dataset.bound) {
        els.search.addEventListener("input", scheduleConferenciaSearch);
        els.search.dataset.bound = "1";
      }
      if (els.grupo && !els.grupo.dataset.bound) {
        els.grupo.addEventListener("change", scheduleConferenciaItemSearch);
        els.grupo.dataset.bound = "1";
      }
      if (els.views) {
        const allowed = canViewConferenciaGarrafeiras();
        els.views.hidden = !allowed;
        if (!allowed && state.conferencia.view === "garrafeiras") state.conferencia.view = "mapas";
        els.views.querySelectorAll("[data-conferencia-view]").forEach(button => {
          if (button.dataset.bound) return;
          button.addEventListener("click", () => {
            const next = String(button.dataset.conferenciaView || "mapas");
            if (next === "garrafeiras" && !canViewConferenciaGarrafeiras()) return;
            state.conferencia.view = next;
            renderConferenciaViewState();
            if (next === "garrafeiras") syncConferenciaGarrafeiras({ silent: true });
          });
          button.dataset.bound = "1";
        });
      }
      renderConferenciaViewState();
    }

    function renderConferenciaViewState() {
      const els = conferenciaElements();
      const view = state.conferencia.view || "mapas";
      if (els.mapasView) els.mapasView.hidden = view !== "mapas";
      if (els.garrafeirasView) els.garrafeirasView.hidden = view !== "garrafeiras";
      if (els.save) els.save.hidden = view === "garrafeiras";
      const grupoLabel = els.grupo ? els.grupo.closest("label") : null;
      const searchLabel = els.search ? els.search.closest("label") : null;
      if (grupoLabel) grupoLabel.hidden = view === "garrafeiras";
      if (searchLabel) searchLabel.hidden = view === "garrafeiras";
      if (els.views) {
        els.views.querySelectorAll("[data-conferencia-view]").forEach(button => {
          button.classList.toggle("is-active", String(button.dataset.conferenciaView || "") === view);
        });
      }
    }

    function conferenciaQueryParams(includeSearch = true) {
      const els = conferenciaElements();
      setupConferenciaControls();
      const params = new URLSearchParams();
      params.set("data", els.data && els.data.value ? els.data.value : formatDateInputValue(new Date()));
      if (els.filial && els.filial.value) params.set("filial", els.filial.value);
      if (includeSearch && els.search && els.search.value.trim()) params.set("search", els.search.value.trim());
      return params;
    }

    function conferenciaGarrafeiraQueryParams() {
      const els = conferenciaElements();
      setupConferenciaControls();
      const params = new URLSearchParams();
      params.set("data", els.data && els.data.value ? els.data.value : formatDateInputValue(new Date()));
      if (els.filial && els.filial.value) params.set("filial", els.filial.value);
      return params;
    }

    async function syncConferenciaGarrafeiras({ silent = true } = {}) {
      setupConferenciaControls();
      const els = conferenciaElements();
      if (!canViewConferenciaGarrafeiras()) {
        if (els.garrafeirasView) els.garrafeirasView.innerHTML = '<div class="p-3 empty-state">Consolidado liberado apenas para financeiro.</div>';
        return false;
      }
      try {
        if (els.status) {
          els.status.textContent = "Carregando consolidado";
          els.status.className = "pill warn";
        }
        const payload = await req(`${CONFIG.endpoints.conferencia.garrafeiras}?${conferenciaGarrafeiraQueryParams().toString()}`, { timeoutMs: 30000 });
        state.conferencia.garrafeiras = payload || {};
        renderConferenciaGarrafeiras();
        const total = Array.isArray(payload && payload.rows) ? payload.rows.length : 0;
        if (els.status) {
          els.status.textContent = `${total} mapa(s)`;
          els.status.className = "pill ok";
        }
        return true;
      } catch (err) {
        if (!silent) addLog(`Falha ao carregar consolidado de garrafeiras: ${err.message}`, "err");
        if (els.status) {
          els.status.textContent = "Falha no consolidado";
          els.status.className = "pill warn";
        }
        if (els.garrafeirasView) els.garrafeirasView.innerHTML = `<div class="p-3 empty-state text-danger">${escapeHtml(err.message)}</div>`;
        return false;
      }
    }

    function renderGarrafeiraDiff(value) {
      const number = Number(value || 0);
      const className = number < 0 ? "diff-negative" : number > 0 ? "diff-positive" : "";
      return `<td class="${className}">${escapeHtml(formatQty(value || 0))}</td>`;
    }

    function renderConferenciaGarrafeiras() {
      const els = conferenciaElements();
      if (!els.garrafeirasView) return;
      const payload = state.conferencia.garrafeiras || {};
      const rows = Array.isArray(payload.rows) ? payload.rows : [];
      const groups = Array.isArray(payload.groups) && payload.groups.length ? payload.groups : ["300", "600", "1L", "51"];
      if (!rows.length) {
        els.garrafeirasView.innerHTML = '<div class="p-3 empty-state">Nenhuma garrafeira encontrada para os filtros.</div>';
        return;
      }
      const groupHeaders = groups.map(group => `<th colspan="3">${escapeHtml(group)}</th>`).join("");
      const subHeaders = groups.map(() => "<th>total</th><th>cont</th><th>dif</th>").join("");
      const bodyRows = rows.map(row => {
        const cells = groups.map(group => {
          const values = row.groups && row.groups[group] ? row.groups[group] : {};
          return `
            <td>${escapeHtml(formatQty(values.total || 0))}</td>
            <td>${escapeHtml(formatQty(values.cont || 0))}</td>
            ${renderGarrafeiraDiff(values.dif || 0)}
          `;
        }).join("");
        return `
          <tr>
            <td class="map-col">${escapeHtml(row.placa || "-")}</td>
            <td class="map-col">${escapeHtml(row.mapa || "-")}</td>
            ${cells}
            <td class="value-col">${escapeHtml(formatMoneyText(row.valor_total || 0))}</td>
          </tr>
        `;
      }).join("");
      const totalCells = groups.map(group => {
        const values = payload.totals && payload.totals[group] ? payload.totals[group] : {};
        return `
          <td>${escapeHtml(formatQty(values.total || 0))}</td>
          <td>${escapeHtml(formatQty(values.cont || 0))}</td>
          ${renderGarrafeiraDiff(values.dif || 0)}
        `;
      }).join("");
      els.garrafeirasView.innerHTML = `
        <div class="p-3">
          <div class="d-flex flex-wrap gap-2 align-items-start justify-content-between mb-3">
            <div>
              <h3 class="h6 fw-bold mb-1">Consolidado de garrafeiras</h3>
              <div class="form-text">Financeiro: totais esperados, contagem real e diferenÃ§a por mapa.</div>
            </div>
            <span class="pill">Valor faltante: ${escapeHtml(formatMoneyText(payload.valor_total || 0))}</span>
          </div>
          <div class="conference-garrafeira-wrap">
            <table class="conference-garrafeira-table">
              <thead>
                <tr class="title-row"><th colspan="${escapeHtml(String(3 + groups.length * 3))}">VASILHAMES</th></tr>
                <tr>
                  <th rowspan="2">PLACA</th>
                  <th rowspan="2">MAPA</th>
                  ${groupHeaders}
                  <th rowspan="2">VALOR TOTAL</th>
                </tr>
                <tr>${subHeaders}</tr>
              </thead>
              <tbody>
                ${bodyRows}
                <tr>
                  <td class="map-col" colspan="2">TOTAL</td>
                  ${totalCells}
                  <td class="value-col">${escapeHtml(formatMoneyText(payload.valor_total || 0))}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      `;
    }

    async function syncConferencia({ silent = true, forceDetail = false } = {}) {
      setupConferenciaControls();
      const els = conferenciaElements();
      if (!state.panel || !state.panel.canConferencia) {
        if (els.editor) els.editor.innerHTML = '<div class="p-3 empty-state">Acesso não liberado para conferência.</div>';
        return false;
      }
      try {
        state.conferencia.loading = true;
        if (els.status) {
          els.status.textContent = "Carregando mapas";
          els.status.className = "pill warn";
        }
        const payload = await req(`${CONFIG.endpoints.conferencia.mapas}?${conferenciaQueryParams(true).toString()}`, { timeoutMs: 30000 });
        state.conferencia.payload = payload || {};
        const maps = Array.isArray(payload && payload.mapas) ? payload.mapas : [];
        if (!maps.some(map => String(map.id) === String(state.conferencia.selectedId))) {
          state.conferencia.selectedId = "";
          state.conferencia.detail = null;
        }
        renderConferenciaMapList();
        if (state.conferencia.selectedId && (forceDetail || !state.conferencia.detail || String(state.conferencia.detail?.mapa?.id) !== String(state.conferencia.selectedId))) {
          await loadConferenciaMapa(state.conferencia.selectedId);
        } else {
          renderConferenciaEditor();
        }
        if (els.status) {
          els.status.textContent = `${maps.length} mapa(s)`;
          els.status.className = "pill ok";
        }
        return true;
      } catch (err) {
        if (!silent) addLog(`Falha ao carregar conferência: ${err.message}`, "err");
        if (els.status) {
          els.status.textContent = "Falha na conferência";
          els.status.className = "pill warn";
        }
        if (els.editor) els.editor.innerHTML = `<div class="p-3 empty-state text-danger">${escapeHtml(err.message)}</div>`;
        return false;
      } finally {
        state.conferencia.loading = false;
      }
    }

    function renderConferenciaMapList() {
      const els = conferenciaElements();
      const maps = Array.isArray(state.conferencia.payload && state.conferencia.payload.mapas) ? state.conferencia.payload.mapas : [];
      if (els.count) els.count.textContent = String(maps.length);
      if (!els.list) return;
      if (!maps.length) {
        els.list.innerHTML = '<div class="empty-state py-3">Nenhum mapa encontrado para os filtros.</div>';
        return;
      }
      els.list.innerHTML = maps.map(map => {
        const active = String(map.id) === String(state.conferencia.selectedId) ? " is-active" : "";
        const done = Number(map.conferidos || 0);
        const total = Number(map.itens || 0);
        return `
          <button type="button" class="conference-map-btn${active}" data-conferencia-map="${escapeHtml(map.id)}">
            <strong>Mapa ${escapeHtml(map.mapa || "-")}</strong>
            <span class="meta">${escapeHtml(map.filial_label || map.filial || "-")} | ${escapeHtml(map.placa || "sem placa")}</span>
            <span class="meta">${escapeHtml(map.motorista || "sem motorista")}</span>
            <span class="meta">${done}/${total} item(ns) conferidos</span>
            <span class="status-line">${escapeHtml(map.source_status || (total ? "Itens carregados" : "Aguardando 030302"))}</span>
            <span class="open-line"><i class="bi bi-box-arrow-in-right me-1"></i>Abrir conferência</span>
          </button>
        `;
      }).join("");
      els.list.querySelectorAll("[data-conferencia-map]").forEach(button => {
        button.addEventListener("click", () => selectConferenciaMapa(String(button.dataset.conferenciaMap || "")));
      });
    }

    async function selectConferenciaMapa(mapaId) {
      const cleanId = String(mapaId || "").trim();
      if (!cleanId) return;
      const els = conferenciaElements();
      state.conferencia.selectedId = cleanId;
      state.conferencia.detail = null;
      state.conferencia.manualRows = [];
      renderConferenciaMapList();
      if (els.editor) {
        els.editor.innerHTML = '<div class="p-3 empty-state"><span class="spinner-border spinner-border-sm me-2"></span>Carregando mapa para conferência...</div>';
      }
      await loadConferenciaMapa(cleanId);
      if (els.editor) {
        els.editor.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }

    function addConferenciaManualRow(group = "OUTROS MATERIAIS", description = "", quantity = "", unidade = "") {
      syncConferenciaManualRowsFromDom();
      if (!state.conferencia.manualRows) state.conferencia.manualRows = [];
      const cleanGroup = String(group || "OUTROS MATERIAIS").toUpperCase();
      if (focusConferenciaGroupRow(cleanGroup, quantity)) return;
      const existing = state.conferencia.manualRows.find(item => String(item.grupo_contagem || "").toUpperCase() === cleanGroup && cleanGroup !== "PRODUTO");
      if (existing) {
        if (quantity !== "") existing.contagem_real = quantity;
        renderConferenciaEditor();
        return;
      }
      state.conferencia.manualRows.push({
        key: `manual-${Date.now()}-${Math.random().toString(16).slice(2)}`,
        cod_item: "",
        descricao: description || cleanGroup,
        grupo_contagem: cleanGroup,
        unidade: unidade || "",
        contagem_real: quantity,
        contagem_vazia: "",
        contagem_caixas: "",
        contagem_unidades: "",
        observacao: ""
      });
      renderConferenciaEditor();
    }

    function focusConferenciaGroupRow(group, quantity = "") {
      const cleanGroup = String(group || "").toUpperCase();
      if (!cleanGroup) return false;
      const row = Array.from(document.querySelectorAll("[data-conferencia-row-group]"))
        .find(element => String(element.dataset.conferenciaRowGroup || "").toUpperCase() === cleanGroup);
      if (!row) return false;
      const input = row.querySelector("[data-conferencia-field='contagem_caixas'], [data-conferencia-field='contagem_real']:not([type='hidden']), [data-conferencia-field='contagem_unidades']");
      if (input) {
        if (quantity !== "") input.value = quantity;
        input.focus();
        input.select();
      }
      return true;
    }

    function focusConferenciaProductRow(code, quantity = "") {
      const cleanCode = String(code || "").replace(/\D/g, "");
      if (!cleanCode) return false;
      const row = Array.from(document.querySelectorAll("[data-conferencia-row-code]"))
        .find(element => String(element.dataset.conferenciaRowCode || "").replace(/\D/g, "") === cleanCode);
      if (!row) return false;
      const input = row.querySelector("[data-conferencia-field='contagem_caixas'], [data-conferencia-field='contagem_unidades'], [data-conferencia-field='contagem_real']:not([type='hidden'])");
      if (input) {
        if (quantity !== "") input.value = quantity;
        input.focus();
        input.select();
      }
      return true;
    }

    function removeConferenciaManualRow(key) {
      syncConferenciaManualRowsFromDom();
      state.conferencia.manualRows = (state.conferencia.manualRows || []).filter(item => item.key !== key);
      renderConferenciaEditor();
    }

    function syncConferenciaManualRowsFromDom() {
      const els = conferenciaElements();
      if (!els.editor) return;
      const rows = Array.from(els.editor.querySelectorAll("[data-conferencia-manual-item]"));
      if (!rows.length) return;
      state.conferencia.manualRows = rows.map(row => {
        const code = row.querySelector("[data-conferencia-field='cod_item']");
        const desc = row.querySelector("[data-conferencia-field='descricao']");
        const group = row.querySelector("[data-conferencia-field='grupo_contagem']");
        const count = row.querySelector("[data-conferencia-field='contagem_real']");
        const empty = row.querySelector("[data-conferencia-field='contagem_vazia']");
        const boxes = row.querySelector("[data-conferencia-field='contagem_caixas']");
        const units = row.querySelector("[data-conferencia-field='contagem_unidades']");
        const unidade = row.querySelector("[data-conferencia-field='unidade']");
        const obs = row.querySelector("[data-conferencia-field='observacao']");
        return {
          key: String(row.dataset.conferenciaManualItem || ""),
          cod_item: code ? code.value : "",
          descricao: desc ? desc.value : "",
          grupo_contagem: group ? group.value : "OUTROS MATERIAIS",
          unidade: unidade ? unidade.value : "",
          contagem_real: count ? count.value : "",
          contagem_vazia: empty ? empty.value : "",
          contagem_caixas: boxes ? boxes.value : "",
          contagem_unidades: units ? units.value : "",
          observacao: obs ? obs.value : ""
        };
      });
    }

    async function searchConferenciaProducts() {
      const input = document.getElementById("conferenciaProductSearch");
      const select = document.getElementById("conferenciaProductSelect");
      const query = input ? input.value.trim() : "";
      if (!select) return;
      if (query.length < 2) {
        state.conferencia.productResults = [];
        select.innerHTML = '<option value="">Digite pelo menos 2 caracteres</option>';
        return;
      }
      try {
        select.innerHTML = '<option value="">Buscando...</option>';
        const params = new URLSearchParams({ search: query, limit: "20" });
        const payload = await req(`${CONFIG.endpoints.conferencia.produtos}?${params.toString()}`, { timeoutMs: 20000 });
        state.conferencia.productResults = Array.isArray(payload && payload.products) ? payload.products : [];
        if (!state.conferencia.productResults.length) {
          select.innerHTML = '<option value="">Nenhum produto encontrado</option>';
          return;
        }
        select.innerHTML = '<option value="">Selecione o produto</option>' + state.conferencia.productResults.map(item => (
          `<option value="${escapeHtml(item.codigo || "")}">${escapeHtml(item.codigo || "-")} - ${escapeHtml(item.descricao || item.descricao_completa || "-")}</option>`
        )).join("");
      } catch (err) {
        select.innerHTML = `<option value="">Falha: ${escapeHtml(err.message)}</option>`;
      }
    }

    function addConferenciaProductRow() {
      syncConferenciaManualRowsFromDom();
      const select = document.getElementById("conferenciaProductSelect");
      const selectedCode = select ? String(select.value || "") : "";
      const product = (state.conferencia.productResults || []).find(item => String(item.codigo || "") === selectedCode);
      if (!product) {
        addLog("Selecione um produto da lista antes de adicionar.", "warn");
        return;
      }
      if (focusConferenciaProductRow(product.codigo || "")) return;
      if (!state.conferencia.manualRows) state.conferencia.manualRows = [];
      const existing = state.conferencia.manualRows.find(item => String(item.cod_item || "").replace(/\D/g, "") === String(product.codigo || "").replace(/\D/g, ""));
      if (existing) {
        renderConferenciaEditor();
        return;
      }
      state.conferencia.manualRows.push({
        key: `manual-prod-${Date.now()}-${Math.random().toString(16).slice(2)}`,
        cod_item: product.codigo || "",
        descricao: product.descricao || product.descricao_completa || product.codigo || "",
        grupo_contagem: "PRODUTO",
        unidade: product.embalagem || "",
        contagem_real: "",
        contagem_vazia: "",
        contagem_caixas: "",
        contagem_unidades: "",
        observacao: ""
      });
      renderConferenciaEditor();
    }

    async function loadConferenciaMapa(mapaId) {
      const els = conferenciaElements();
      if (!mapaId) {
        state.conferencia.detail = null;
        renderConferenciaEditor();
        return;
      }
      const params = new URLSearchParams();
      const search = els.search && els.search.value ? els.search.value.trim() : "";
      const grupo = els.grupo && els.grupo.value ? els.grupo.value.trim() : "";
      if (search) params.set("search", search);
      if (grupo) params.set("grupo", grupo);
      const suffix = params.toString() ? `?${params.toString()}` : "";
      const payload = await req(`${CONFIG.endpoints.conferencia.mapas}/${encodeURIComponent(mapaId)}${suffix}`, { timeoutMs: 30000 });
      state.conferencia.detail = payload || null;
      renderConferenciaEditor();
    }

    function renderConferenciaEditor() {
      const els = conferenciaElements();
      const detail = state.conferencia.detail || {};
      const mapa = detail.mapa || null;
      const items = Array.isArray(detail.items) ? detail.items : [];
      const manualRows = Array.isArray(state.conferencia.manualRows) ? state.conferencia.manualRows : [];
      const reveal = Boolean(detail.reveal_totals);
      if (els.save) els.save.disabled = !mapa;
      if (!els.editor) return;
      if (!mapa) {
        els.editor.innerHTML = '<div class="p-3 empty-state">Selecione um mapa para iniciar a conferência.</div>';
        return;
      }
      const groups = CONFERENCIA_GRUPOS.map(group => {
        const total = items.filter(item => String(item.grupo_contagem || "") === group).length;
        return `<div class="conference-kpi"><span>${escapeHtml(group)}</span><strong>${escapeHtml(String(total))}</strong></div>`;
      }).join("");
      const groupSummaryHtml = reveal && groups ? `<div class="conference-kpis mb-3">${groups}</div>` : "";
      const totalHeaders = reveal ? '<th>Total</th><th>Dif.</th><th>Valor</th>' : "";
      const materialQuick = CONFERENCIA_MATERIAL_QUICK_GROUPS.map(group => `
        <button class="btn btn-outline-primary btn-sm" type="button" data-conferencia-add-group="${escapeHtml(group)}">
          <i class="bi bi-plus-lg me-1"></i>${escapeHtml(group)}
        </button>
      `).join("");
      const productOptions = (state.conferencia.productResults || []).map(item => (
        `<option value="${escapeHtml(item.codigo || "")}">${escapeHtml(item.codigo || "-")} - ${escapeHtml(item.descricao || item.descricao_completa || "-")}</option>`
      )).join("");
      const rows = items.length ? items.map(item => {
        const diff = Number(item.diferenca || 0);
        const diffClass = diff === 0 ? "text-success" : "text-danger";
        return `
          <tr data-conferencia-item="${escapeHtml(item.id)}">
            <td data-label="Cod." class="mono fw-bold">${escapeHtml(item.cod_item || "-")}</td>
            <td data-label="Item">
              <div class="fw-bold">${escapeHtml(item.descricao || "-")}</div>
              <div class="text-secondary small">${escapeHtml(item.categoria || item.tipo_item || "-")}</div>
            </td>
            <td data-label="Grupo"><span class="pill">${escapeHtml(item.grupo_contagem || "-")}</span></td>
            <td data-label="Un.">${escapeHtml(item.unidade || "-")}</td>
            ${reveal ? `<td data-label="Total" class="fw-bold">${escapeHtml(formatQty(item.total_sistema || 0))}</td><td data-label="Dif." class="fw-bold ${diffClass}">${escapeHtml(formatQty(item.diferenca || 0))}</td><td data-label="Valor">${escapeHtml(formatMoneyText(item.valor_unitario || 0))}</td>` : ""}
            <td data-label="Contagem">${renderConferenciaCountFields(item)}</td>
            <td data-label="Obs."><input class="form-control form-control-sm conference-note-input" type="text" data-conferencia-field="observacao" value="${escapeHtml(item.observacao || "")}" placeholder="Observação"></td>
          </tr>
        `;
      }).join("") : "";
      const manualHtml = manualRows.map(item => {
        const isProduct = String(item.grupo_contagem || "").toUpperCase() === "PRODUTO";
        const codeCell = isProduct
          ? `<span class="mono fw-bold">${escapeHtml(item.cod_item || "-")}</span><input type="hidden" data-conferencia-field="cod_item" value="${escapeHtml(item.cod_item || "")}">`
          : `<span class="text-secondary small fw-bold">Sem código</span><input type="hidden" data-conferencia-field="cod_item" value="">`;
        const groupCell = isProduct
          ? '<span class="pill">PRODUTO</span><input type="hidden" data-conferencia-field="grupo_contagem" value="PRODUTO">'
          : `<select class="form-select form-select-sm" data-conferencia-field="grupo_contagem">
                ${CONFERENCIA_MANUAL_GROUPS.map(group => `<option value="${escapeHtml(group)}" ${String(item.grupo_contagem || "") === group ? "selected" : ""}>${escapeHtml(group)}</option>`).join("")}
              </select>`;
        const itemHint = isProduct ? "Produto da tabela 0111." : "Lançamento manual sem código.";
        return `
          <tr data-conferencia-manual-item="${escapeHtml(item.key)}">
            <td data-label="Cod.">${codeCell}</td>
            <td data-label="Item">
              <input class="form-control form-control-sm fw-bold" type="text" data-conferencia-field="descricao" value="${escapeHtml(item.descricao || "")}" placeholder="Digite o material/produto conferido">
              <div class="text-secondary small mt-1">${escapeHtml(itemHint)}</div>
            </td>
            <td data-label="Grupo">${groupCell}</td>
            <td data-label="Un.">${isProduct ? `<span>${escapeHtml(item.unidade || "-")}</span><input type="hidden" data-conferencia-field="unidade" value="${escapeHtml(item.unidade || "")}">` : "-"}</td>
            ${reveal ? '<td data-label="Total" class="text-secondary">0</td><td data-label="Dif." class="text-secondary">-</td><td data-label="Valor" class="text-secondary">-</td>' : ""}
            <td data-label="Contagem">${renderConferenciaCountFields(item)}</td>
            <td data-label="Obs.">
              <div class="d-flex gap-1">
                <input class="form-control form-control-sm conference-note-input" type="text" data-conferencia-field="observacao" value="${escapeHtml(item.observacao || "")}" placeholder="Observação">
                <button class="btn btn-outline-danger btn-sm" type="button" data-conferencia-remove-manual="${escapeHtml(item.key)}"><i class="bi bi-x-lg"></i></button>
              </div>
            </td>
          </tr>
      `;
      }).join("");
      const emptyRows = (!rows && !manualHtml)
        ? `<tr><td colspan="${reveal ? 9 : 6}" class="text-center py-4 text-secondary">Este mapa esta aberto pelo relatório de rotas e ainda não recebeu os itens da 030302. Use o botão Adicionar item manual para fazer a contagem mesmo assim.</td></tr>`
        : "";
      const blindPersistedCards = items.map(item => {
        return `
          <div class="conference-simple-row" data-conferencia-item="${escapeHtml(item.id)}" data-conferencia-row-group="${escapeHtml(String(item.grupo_contagem || "").toUpperCase())}" data-conferencia-row-code="${escapeHtml(item.cod_item || "")}">
            <div>
              <div class="name">${escapeHtml(item.descricao || "-")}</div>
              <div class="meta">${escapeHtml(item.grupo_contagem || "-")}${item.cod_item ? ` | Cod. ${escapeHtml(item.cod_item)}` : ""}</div>
              <input type="hidden" data-conferencia-field="observacao" value="${escapeHtml(item.observacao || "")}">
            </div>
            ${renderConferenciaCountFields(item)}
            <span></span>
          </div>
        `;
      }).join("");
      const blindManualCards = manualRows.map(item => `
        <div class="conference-simple-row" data-conferencia-manual-item="${escapeHtml(item.key)}" data-conferencia-row-group="${escapeHtml(String(item.grupo_contagem || "").toUpperCase())}" data-conferencia-row-code="${escapeHtml(item.cod_item || "")}">
          <div>
            <input class="form-control form-control-sm fw-bold mb-1" type="text" data-conferencia-field="descricao" value="${escapeHtml(item.descricao || "")}" placeholder="Item conferido">
            <div class="meta">${escapeHtml(item.grupo_contagem || "-")}${item.observacao ? ` | ${escapeHtml(item.observacao)}` : ""}</div>
            <input type="hidden" data-conferencia-field="cod_item" value="${escapeHtml(item.cod_item || "")}">
            <input type="hidden" data-conferencia-field="grupo_contagem" value="${escapeHtml(item.grupo_contagem || "OUTROS MATERIAIS")}">
            <input type="hidden" data-conferencia-field="unidade" value="${escapeHtml(item.unidade || "")}">
            <input type="hidden" data-conferencia-field="observacao" value="${escapeHtml(item.observacao || "")}">
          </div>
          ${renderConferenciaCountFields(item)}
          <button class="btn btn-outline-danger btn-sm" type="button" data-conferencia-remove-manual="${escapeHtml(item.key)}"><i class="bi bi-x-lg"></i></button>
        </div>
      `).join("");
      const blindListHtml = !reveal
        ? `<div class="conference-simple-list mb-3">${blindPersistedCards}${blindManualCards}${(!blindPersistedCards && !blindManualCards) ? '<div class="empty-state py-3">Nenhum item lançado ainda. Use os botões acima para adicionar.</div>' : ""}</div>`
        : "";
      const tableHtml = reveal ? `
          <div class="conference-table-wrap">
            <table class="table table-sm align-middle mb-0">
              <thead>
                <tr>
                  <th>Cod.</th>
                  <th>Item</th>
                  <th>Grupo</th>
                  <th>Un.</th>
                  ${totalHeaders}
                  <th>Contagem real</th>
                  <th>Obs.</th>
                </tr>
              </thead>
              <tbody>${rows}${manualHtml}${emptyRows}</tbody>
            </table>
          </div>
        ` : "";
      els.editor.innerHTML = `
        <header class="px-3 pt-3 pb-2 border-bottom">
          <div class="d-flex flex-wrap gap-2 align-items-start justify-content-between">
            <div>
              <h3 class="h6 fw-bold mb-1">Mapa ${escapeHtml(mapa.mapa || "-")}</h3>
              <div class="form-text">${escapeHtml(mapa.filial_label || mapa.filial || "-")} | ${escapeHtml(mapa.placa || "sem placa")} | ${escapeHtml(mapa.motorista || "sem motorista")}</div>
            </div>
            <span class="pill">${escapeHtml(String(mapa.conferidos || 0))}/${escapeHtml(String(mapa.itens || 0))} conferidos</span>
          </div>
        </header>
        <div class="p-3">
          ${reveal ? "" : '<div class="conference-blind-note mb-3"><i class="bi bi-eye-slash me-1"></i>Contagem cega ativa: o parâmetro do sistema fica oculto para o conferente.</div>'}
          <div class="mb-3">
            <div class="d-flex flex-wrap gap-2 align-items-center justify-content-between mb-2">
              <div>
                <h4 class="h6 fw-bold mb-1">Itens da contagem</h4>
                <div class="text-secondary small fw-bold">Adicione o item e preencha a quantidade na lista abaixo.</div>
              </div>
              <button class="btn btn-outline-primary btn-sm" id="conferenciaAddManualBtn" type="button"><i class="bi bi-plus-lg me-1"></i>Adicionar item manual</button>
            </div>
            <div class="text-secondary small fw-bold mb-2">Adicionar item sem código</div>
            <div class="d-flex flex-wrap gap-2 mb-3">${materialQuick}</div>
            <div class="conference-product-picker">
              <label class="form-label small fw-semibold mb-0" for="conferenciaProductSearch">Produto
                <input class="form-control form-control-sm mt-1" id="conferenciaProductSearch" type="search" placeholder="Buscar por nome ou código">
              </label>
              <label class="form-label small fw-semibold mb-0" for="conferenciaProductSelect">Resultado
                <select class="form-select form-select-sm mt-1" id="conferenciaProductSelect">
                  <option value="">Busque e selecione</option>
                  ${productOptions}
                </select>
              </label>
              <button class="btn btn-outline-primary btn-sm" id="conferenciaAddProductBtn" type="button"><i class="bi bi-plus-lg me-1"></i>Adicionar produto</button>
            </div>
          </div>
          ${groupSummaryHtml}
          ${blindListHtml}
          ${tableHtml}
        </div>
      `;
      const addManual = document.getElementById("conferenciaAddManualBtn");
      if (addManual) addManual.addEventListener("click", () => addConferenciaManualRow());
      els.editor.querySelectorAll("[data-conferencia-add-group]").forEach(button => {
        button.addEventListener("click", () => {
          const group = String(button.dataset.conferenciaAddGroup || "OUTROS MATERIAIS");
          const description = CONFERENCIA_FAST_GROUPS.includes(group) ? `Garrafeira ${group}` : group;
          addConferenciaManualRow(group, description);
        });
      });
      const productSearch = document.getElementById("conferenciaProductSearch");
      if (productSearch) productSearch.addEventListener("input", scheduleConferenciaProductSearch);
      const addProduct = document.getElementById("conferenciaAddProductBtn");
      if (addProduct) addProduct.addEventListener("click", addConferenciaProductRow);
      els.editor.querySelectorAll("[data-conferencia-remove-manual]").forEach(button => {
        button.addEventListener("click", () => removeConferenciaManualRow(String(button.dataset.conferenciaRemoveManual || "")));
      });
    }

    function collectConferenciaCounts() {
      const els = conferenciaElements();
      if (!els.editor) return [];
      const persisted = Array.from(els.editor.querySelectorAll("[data-conferencia-item]")).map(row => {
        const count = row.querySelector("[data-conferencia-field='contagem_real']");
        const empty = row.querySelector("[data-conferencia-field='contagem_vazia']");
        const boxes = row.querySelector("[data-conferencia-field='contagem_caixas']");
        const units = row.querySelector("[data-conferencia-field='contagem_unidades']");
        const obs = row.querySelector("[data-conferencia-field='observacao']");
        return {
          item_id: Number(row.dataset.conferenciaItem || 0),
          contagem_real: count ? count.value : "",
          contagem_vazia: empty ? empty.value : "",
          contagem_caixas: boxes ? boxes.value : "",
          contagem_unidades: units ? units.value : "",
          observacao: obs ? obs.value : ""
        };
      }).filter(item => item.item_id > 0);
      const manual = Array.from(els.editor.querySelectorAll("[data-conferencia-manual-item]")).map(row => {
        const code = row.querySelector("[data-conferencia-field='cod_item']");
        const desc = row.querySelector("[data-conferencia-field='descricao']");
        const group = row.querySelector("[data-conferencia-field='grupo_contagem']");
        const count = row.querySelector("[data-conferencia-field='contagem_real']");
        const empty = row.querySelector("[data-conferencia-field='contagem_vazia']");
        const boxes = row.querySelector("[data-conferencia-field='contagem_caixas']");
        const units = row.querySelector("[data-conferencia-field='contagem_unidades']");
        const unidade = row.querySelector("[data-conferencia-field='unidade']");
        const obs = row.querySelector("[data-conferencia-field='observacao']");
        return {
          item_id: 0,
          cod_item: code ? code.value : "",
          descricao: desc ? desc.value : "",
          grupo_contagem: group ? group.value : "",
          unidade: unidade ? unidade.value : "",
          contagem_real: count ? count.value : "",
          contagem_vazia: empty ? empty.value : "",
          contagem_caixas: boxes ? boxes.value : "",
          contagem_unidades: units ? units.value : "",
          observacao: obs ? obs.value : ""
        };
      }).filter(item => String(item.descricao || item.cod_item || "").trim());
      return persisted.concat(manual);
    }

    async function saveConferenciaCounts() {
      const mapaId = state.conferencia && state.conferencia.selectedId ? state.conferencia.selectedId : "";
      if (!mapaId) return;
      const els = conferenciaElements();
      try {
        if (els.save) {
          els.save.disabled = true;
          els.save.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Salvando';
        }
        const result = await req(`${CONFIG.endpoints.conferencia.mapas}/${encodeURIComponent(mapaId)}/contagens`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ counts: collectConferenciaCounts() }),
          timeoutMs: 30000
        });
        addLog(`Conferência salva: ${result.saved || 0} item(ns).`, "ok");
        state.conferencia.manualRows = [];
        await loadConferenciaMapa(mapaId);
        await syncConferencia({ silent: true });
      } catch (err) {
        addLog(`Falha ao salvar conferência: ${err.message}`, "err");
      } finally {
        if (els.save) {
          els.save.innerHTML = '<i class="bi bi-check2-circle me-1"></i>Salvar contagem';
          els.save.disabled = false;
        }
      }
    }

    function isConferenciaOnlyPanelUser() {
      if (!state.panel || state.panel.isAdmin) return false;
      const featureFlags = [
        "canOperations",
        "canPayip",
        "canReports",
        "canManagePromax",
        "canEntrega",
        "canViewCritica",
        "canManageRecolhas",
        "canFinanceiro",
        "canProtestos",
        "canViewGiro",
        "canViewUsage",
        "canArmazem"
        ,"canPedidos", "canEstoque"
      ];
      return Boolean(state.panel.canConferencia) && featureFlags.every(flag => !state.panel[flag]);
    }
