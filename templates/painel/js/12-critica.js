    function emptyCriticaDashboard() {
      return { total: 0, summary: {}, options: {}, rankings: {}, recommendations: [], orders: [] };
    }

    function selectedCriticaValues(select) {
      if (!select) return [];
      return Array.from(select.selectedOptions || [])
        .map(option => String(option.value || "").trim())
        .filter(Boolean);
    }

    function normalizeCriticaOptionItems(options) {
      const mapped = [];
      const seen = new Set();
      (Array.isArray(options) ? options : []).forEach(item => {
        const value = String(item && item.value || "").trim();
        if (!value || seen.has(value)) return;
        const count = Number(item && item.count || 0);
        const labelBase = cleanDisplayText(item && (item.label || item.value) || value);
        mapped.push({ value, label: count ? `${labelBase} (${formatNumber(count)})` : labelBase });
        seen.add(value);
      });
      return mapped;
    }

    function criticaSlicerElements(def) {
      return {
        select: E[def.selectKey],
        root: document.getElementById(`${def.idPrefix}Slicer`),
        button: document.getElementById(`${def.idPrefix}Button`),
        panel: document.getElementById(`${def.idPrefix}Panel`),
        search: document.getElementById(`${def.idPrefix}Search`),
        list: document.getElementById(`${def.idPrefix}List`),
        selectAllBtn: document.getElementById(`${def.idPrefix}SelectAllBtn`),
        clearBtn: document.getElementById(`${def.idPrefix}ClearBtn`)
      };
    }

    function criticaOptionsForSlicer(def) {
      const options = state.criticaDashboard && state.criticaDashboard.options ? state.criticaDashboard.options : {};
      const mapped = normalizeCriticaOptionItems(options[def.optionKey]);
      const values = new Set(mapped.map(item => item.value));
      selectedCriticaValues(E[def.selectKey]).forEach(value => {
        if (value && !values.has(value)) {
          mapped.unshift({ value, label: cleanDisplayText(value) });
          values.add(value);
        }
      });
      return mapped;
    }

    function syncCriticaHiddenSelect(def, options, selectedValues) {
      const select = E[def.selectKey];
      if (!select) return [];
      const selected = (Array.isArray(selectedValues) ? selectedValues : [])
        .map(value => String(value || "").trim())
        .filter(Boolean);
      const selectedSet = new Set(selected);
      const optionValues = new Set((options || []).map(item => String(item.value || "")));
      const extra = selected
        .filter(value => value && !optionValues.has(value))
        .map(value => ({ value, label: cleanDisplayText(value) }));
      select.innerHTML = extra.concat(options || [])
        .map(item => `<option value="${escapeHtml(item.value || "")}">${escapeHtml(item.label || item.value || "")}</option>`)
        .join("");
      Array.from(select.options || []).forEach(option => {
        option.selected = selectedSet.has(String(option.value || ""));
      });
      return selectedCriticaValues(select);
    }

    function criticaSlicerSelectedSet(def) {
      return new Set(selectedCriticaValues(E[def.selectKey]));
    }

    function criticaSlicerButtonText(def, selectedValues, options) {
      const selected = Array.isArray(selectedValues) ? selectedValues : [];
      if (!selected.length) return def.allText;
      if (selected.length === 1) {
        const match = (options || []).find(item => item.value === selected[0]);
        return cleanDisplayText(match ? match.label : selected[0]);
      }
      return `${selected.length} ${def.selectedText}`;
    }

    function renderCriticaSlicer(def) {
      const els = criticaSlicerElements(def);
      const options = criticaOptionsForSlicer(def);
      const selectedSet = criticaSlicerSelectedSet(def);
      const search = normalizeTextForSearch(els.search ? els.search.value : "");
      const visibleOptions = options.filter(item => !search || normalizeTextForSearch(item.label || item.value).includes(search));
      if (els.button) {
        els.button.textContent = criticaSlicerButtonText(def, [...selectedSet], options);
        els.button.title = selectedSet.size ? [...selectedSet].join(", ") : def.allText;
      }
      if (!els.list) return;
      if (!visibleOptions.length) {
        els.list.innerHTML = `<div class="small text-secondary px-1 py-2">${escapeHtml(def.emptyText)}</div>`;
        return;
      }
      els.list.innerHTML = visibleOptions.map(item => {
        const checked = selectedSet.has(item.value);
        return `
          <label class="power-slicer-item">
            <input class="form-check-input m-0 critica-slicer-option" type="checkbox" value="${escapeHtml(item.value)}" ${checked ? "checked" : ""}>
            <span>${escapeHtml(item.label || item.value)}</span>
          </label>
        `;
      }).join("");
      els.list.querySelectorAll(".critica-slicer-option").forEach(input => {
        input.addEventListener("change", event => onCriticaSlicerCheckboxChange(def, event));
      });
    }

    function clearCriticaSlicerDependents(def) {
      (def.clears || []).forEach(key => {
        const childDef = CRITICA_DASHBOARD_SLICER_BY_KEY[key];
        if (childDef) setCriticaSlicerSelection(childDef, [], { sync: false, clearDependents: false });
      });
    }

    function setCriticaSlicerSelection(def, values, { sync = true, clearDependents = true } = {}) {
      const options = criticaOptionsForSlicer(def);
      const selected = syncCriticaHiddenSelect(def, options, values);
      renderCriticaSlicer(def);
      if (sync && clearDependents) clearCriticaSlicerDependents(def);
      if (sync) syncCriticaDashboard({ silent: false });
      return selected;
    }

    function onCriticaSlicerCheckboxChange(def, event) {
      const selectedSet = criticaSlicerSelectedSet(def);
      const value = String(event.target && event.target.value || "").trim();
      if (!value) return;
      if (event.target.checked) selectedSet.add(value);
      else selectedSet.delete(value);
      setCriticaSlicerSelection(def, [...selectedSet]);
    }

    function toggleCriticaSlicerPanel(def, event) {
      if (event) event.stopPropagation();
      const els = criticaSlicerElements(def);
      if (!els.panel) return;
      const willOpen = els.panel.classList.contains("d-none");
      CRITICA_DASHBOARD_SLICERS.forEach(item => {
        if (item.key === def.key) return;
        const other = criticaSlicerElements(item);
        if (other.panel) other.panel.classList.add("d-none");
        if (other.button) other.button.setAttribute("aria-expanded", "false");
      });
      els.panel.classList.toggle("d-none", !willOpen);
      if (els.button) els.button.setAttribute("aria-expanded", willOpen ? "true" : "false");
      if (willOpen) {
        renderCriticaSlicer(def);
        if (els.search) els.search.focus();
      }
    }

    function closeCriticaSlicerPanelsOnOutsideClick(event) {
      CRITICA_DASHBOARD_SLICERS.forEach(def => {
        const els = criticaSlicerElements(def);
        if (!els.panel || els.panel.classList.contains("d-none")) return;
        if (els.root && els.root.contains(event.target)) return;
        els.panel.classList.add("d-none");
        if (els.button) els.button.setAttribute("aria-expanded", "false");
      });
    }

    function visibleCriticaSlicerValues(def) {
      const els = criticaSlicerElements(def);
      const options = criticaOptionsForSlicer(def);
      const search = normalizeTextForSearch(els.search ? els.search.value : "");
      return options
        .filter(item => !search || normalizeTextForSearch(item.label || item.value).includes(search))
        .map(item => item.value);
    }

    function selectVisibleCriticaSlicerValues(def, event) {
      if (event) event.stopPropagation();
      const selectedSet = criticaSlicerSelectedSet(def);
      visibleCriticaSlicerValues(def).forEach(value => selectedSet.add(value));
      setCriticaSlicerSelection(def, [...selectedSet]);
    }

    function clearCriticaSlicerSelection(def, event) {
      if (event) event.stopPropagation();
      setCriticaSlicerSelection(def, []);
    }

    function setupCriticaDashboardSlicerEvents() {
      CRITICA_DASHBOARD_SLICERS.forEach(def => {
        const els = criticaSlicerElements(def);
        if (els.select) {
          els.select.addEventListener("change", () => {
            clearCriticaSlicerDependents(def);
            syncCriticaDashboard({ silent: false });
          });
        }
        if (els.button) els.button.addEventListener("click", event => toggleCriticaSlicerPanel(def, event));
        if (els.search) els.search.addEventListener("input", () => renderCriticaSlicer(def));
        if (els.selectAllBtn) els.selectAllBtn.addEventListener("click", event => selectVisibleCriticaSlicerValues(def, event));
        if (els.clearBtn) els.clearBtn.addEventListener("click", event => clearCriticaSlicerSelection(def, event));
      });
      document.addEventListener("click", closeCriticaSlicerPanelsOnOutsideClick);
    }

    function currentCriticaDashboardParams() {
      const limit = Number(E.criticaLimit && E.criticaLimit.value ? E.criticaLimit.value : 1);
      const selectedOperation = E.criticaOperationSingle && E.criticaOperationSingle.value
        ? [E.criticaOperationSingle.value]
        : selectedCriticaValues(E.criticaOperation);
      return {
        date: E.criticaDate ? E.criticaDate.value : "",
        limit: Number.isFinite(limit) ? Math.max(1, Math.min(1000, Math.trunc(limit))) : 1,
        operation: selectedOperation,
        problem: selectedCriticaValues(E.criticaProblem),
        sector: selectedCriticaValues(E.criticaSector),
        manager: selectedCriticaValues(E.criticaManager),
        seller: selectedCriticaValues(E.criticaSeller),
        city: selectedCriticaValues(E.criticaCity),
        district: selectedCriticaValues(E.criticaDistrict),
        origin: selectedCriticaValues(E.criticaOrigin),
        search: E.criticaSearch ? E.criticaSearch.value.trim() : "",
        onlyProblems: E.criticaOnlyProblems ? E.criticaOnlyProblems.checked : false
      };
    }

    function appendCriticaValues(query, name, values) {
      (Array.isArray(values) ? values : []).forEach(value => {
        const text = String(value || "").trim();
        if (text) query.append(name, text);
      });
    }

    function criticaDashboardQueryString(params) {
      const query = new URLSearchParams();
      query.set("limit", String(params.limit || 200));
      if (params.date) query.set("date", params.date);
      if (params.search) query.set("search", params.search);
      if (params.onlyProblems) query.set("only_problems", "1");
      else query.set("only_problems", "0");
      appendCriticaValues(query, "operation", params.operation);
      appendCriticaValues(query, "problem", params.problem);
      appendCriticaValues(query, "sector", params.sector);
      appendCriticaValues(query, "manager", params.manager);
      appendCriticaValues(query, "seller", params.seller);
      appendCriticaValues(query, "city", params.city);
      appendCriticaValues(query, "district", params.district);
      appendCriticaValues(query, "origin", params.origin);
      return query.toString();
    }

    function resolveCriticaSectorExportScope() {
      const params = currentCriticaDashboardParams();
      const sectors = Array.isArray(params.sector) ? params.sector.filter(Boolean) : [];
      if (sectors.length !== 1) throw new Error("Selecione um único setor nos filtros da crítica.");
      const operations = Array.isArray(params.operation) ? params.operation.filter(Boolean) : [];
      if (operations.length === 1) {
        return { operation: operations[0], sector: sectors[0], date: params.date || "" };
      }
      const options = state.criticaDashboard && state.criticaDashboard.options ? state.criticaDashboard.options : {};
      const matchingOperations = Array.isArray(options.operations)
        ? options.operations
            .map(item => String(item && item.value || "").trim())
            .filter(Boolean)
        : [];
      if (matchingOperations.length === 1) {
        return { operation: matchingOperations[0], sector: sectors[0], date: params.date || "" };
      }
      throw new Error("Selecione uma única operação junto com o setor para gerar o PDF.");
    }

    function resolveCriticaOperationExportScope() {
      const params = currentCriticaDashboardParams();
      const operations = Array.isArray(params.operation) ? params.operation.filter(Boolean) : [];
      if (operations.length > 1) throw new Error("Selecione no máximo uma revenda para gerar o PDF.");
      return { operation: operations[0] || "", date: params.date || "" };
    }

    async function exportCriticaOperationPdf({ summaryOnly = false } = {}) {
      updateTokens();
      if (!hasPanelAuth()) {
        addLog("Sessão do painel não validada.", "warn");
        return;
      }

      let scope;
      try {
        scope = resolveCriticaOperationExportScope();
      } catch (err) {
        addLog(err.message, "warn");
        return;
      }

      const btn = summaryOnly ? E.criticaOperationSummaryPdfBtn : E.criticaOperationPdfBtn;
      const previousLabel = btn ? btn.innerHTML : "";
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = summaryOnly
          ? '<span class="spinner-border spinner-border-sm me-1"></span>Gerando resumo'
          : '<span class="spinner-border spinner-border-sm me-1"></span>Gerando PDF';
      }

      const headers = {};
      if (state.tokens.api) headers["x-api-token"] = state.tokens.api;
      if (state.tokens.admin) headers["x-admin-token"] = state.tokens.admin;

      try {
        const query = new URLSearchParams();
        if (scope.operation) query.set("operation", scope.operation);
        if (scope.date) query.set("date", scope.date);
        if (summaryOnly) query.set("summary_only", "1");
        const response = await fetch(`${CONFIG.api}${CONFIG.endpoints.critica.pdf}?${query.toString()}`, {
          method: "GET",
          headers,
          credentials: "same-origin"
        });
        if (!response.ok) {
          const errPayload = await response.json().catch(() => null);
          throw new Error(errPayload && errPayload.detail ? errPayload.detail : `HTTP ${response.status}`);
        }
        const blob = await response.blob();
        const disposition = response.headers.get("content-disposition") || "";
        const matchedName = disposition.match(/filename=\"([^\"]+)\"/i);
        const fallbackExtension = response.headers.get("content-type") && response.headers.get("content-type").includes("zip")
          ? "zip"
          : "pdf";
        const filename = matchedName && matchedName[1]
          ? matchedName[1]
          : scope.operation
            ? `critica-rn-operacao-${scope.operation}${summaryOnly ? "-resumo" : ""}.${fallbackExtension}`
            : `critica-rn-filiais${summaryOnly ? "-resumo" : ""}.${fallbackExtension}`;
        const blobUrl = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = blobUrl;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(blobUrl);
        addLog(
          scope.operation
            ? `${summaryOnly ? "Resumo" : "PDF"} da crítica exportado para revenda ${scope.operation}.`
            : `${summaryOnly ? "Resumo" : "PDF"} da crítica exportado para o escopo liberado do painel.`,
          "ok"
        );
      } catch (err) {
        addLog(`Falha ao exportar crítica da revenda: ${err.message}`, "err");
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = previousLabel;
        }
      }
    }

    async function exportCriticaSectorPdf({ summaryOnly = false } = {}) {
      updateTokens();
      if (!hasPanelAuth()) {
        addLog("Sessão do painel não validada.", "warn");
        return;
      }

      let scope;
      try {
        scope = resolveCriticaSectorExportScope();
      } catch (err) {
        addLog(err.message, "warn");
        return;
      }

      const btn = summaryOnly ? E.criticaSectorSummaryPdfBtn : E.criticaSectorPdfBtn;
      const previousLabel = btn ? btn.innerHTML : "";
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = summaryOnly
          ? '<span class="spinner-border spinner-border-sm me-1"></span>Gerando resumo'
          : '<span class="spinner-border spinner-border-sm me-1"></span>Gerando PDF';
      }

      const headers = {};
      if (state.tokens.api) headers["x-api-token"] = state.tokens.api;
      if (state.tokens.admin) headers["x-admin-token"] = state.tokens.admin;

      try {
        const query = new URLSearchParams();
        query.set("operation", scope.operation);
        query.set("sector", scope.sector);
        if (scope.date) query.set("date", scope.date);
        if (summaryOnly) query.set("summary_only", "1");
        const response = await fetch(`${CONFIG.api}${CONFIG.endpoints.critica.pdf}?${query.toString()}`, {
          method: "GET",
          headers,
          credentials: "same-origin"
        });
        if (!response.ok) {
          const errPayload = await response.json().catch(() => null);
          throw new Error(errPayload && errPayload.detail ? errPayload.detail : `HTTP ${response.status}`);
        }
        const blob = await response.blob();
        const disposition = response.headers.get("content-disposition") || "";
        const matchedName = disposition.match(/filename=\"([^\"]+)\"/i);
        const filename = matchedName && matchedName[1]
          ? matchedName[1]
          : `critica-rn-setor-${scope.operation}-${scope.sector}${summaryOnly ? "-resumo" : ""}.pdf`;
        const blobUrl = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = blobUrl;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(blobUrl);
        addLog(`${summaryOnly ? "Resumo" : "PDF"} da crítica exportado para operação ${scope.operation} setor ${scope.sector}.`, "ok");
      } catch (err) {
        addLog(`Falha ao exportar crítica do setor: ${err.message}`, "err");
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = previousLabel;
        }
      }
    }

    function renderCriticaFilterOptions(previousParams = currentCriticaDashboardParams()) {
      CRITICA_DASHBOARD_SLICERS.forEach(def => {
        setCriticaSlicerSelection(def, previousParams[def.key], { sync: false, clearDependents: false });
      });
      if (E.criticaOperationSingle) {
        const options = state.criticaDashboard && state.criticaDashboard.options ? state.criticaDashboard.options : {};
        const currentValue = E.criticaOperationSingle.value || (Array.isArray(previousParams.operation) ? previousParams.operation[0] : "");
        const operationOptions = Array.isArray(options.operations) ? options.operations : [];
        E.criticaOperationSingle.innerHTML = '<option value="">Todas as revendas</option>' + operationOptions.map(item => {
          const value = String(item && item.value != null ? item.value : "").trim();
          if (!value) return "";
          const label = cleanDisplayText(item.label || item.value || value);
          const selected = value === currentValue ? " selected" : "";
          return `<option value="${escapeHtml(value)}"${selected}>${escapeHtml(label)}</option>`;
        }).join("");
        if (currentValue && !E.criticaOperationSingle.value) E.criticaOperationSingle.value = currentValue;
      }
      const summaryDate = state.criticaDashboard && state.criticaDashboard.summary ? state.criticaDashboard.summary.data_pedido : "";
      if (E.criticaDate && !previousParams.date && summaryDate) E.criticaDate.value = summaryDate;
    }

    function criticaProblemBadges(order) {
      const keys = Array.isArray(order && order.problem_keys) ? order.problem_keys : [];
      const labels = Array.isArray(order && order.problem_labels) ? order.problem_labels : [];
      if (!keys.length && !labels.length) return '<span class="critica-problem-badge muted">Sem problema</span>';
      const source = labels.length ? labels.slice(0, 4) : keys.slice(0, 4);
      const html = source.map(label => `<span class="critica-problem-badge">${escapeHtml(cleanDisplayText(label))}</span>`).join("");
      const remaining = Math.max(0, (labels.length || keys.length) - source.length);
      return html + (remaining ? `<span class="critica-problem-badge muted">+${formatNumber(remaining)}</span>` : "");
    }

    function renderCriticaRankList(element, items, { valueKey = "orders", emptyText = "Sem dados nos filtros atuais." } = {}) {
      if (!element) return;
      const source = Array.isArray(items) ? items : [];
      if (!source.length) {
        element.innerHTML = `<li><span class="text-secondary small">${escapeHtml(emptyText)}</span></li>`;
        return;
      }
      element.innerHTML = source.slice(0, 8).map(item => {
        const label = cleanDisplayText(item.label || item.value || "-");
        const value = item[valueKey] != null ? item[valueKey] : item.orders;
        const sub = item.total ? `<div class="small text-secondary">${escapeHtml(item.total)}</div>` : "";
        return `
          <li>
            <span><strong>${escapeHtml(label)}</strong>${sub}</span>
            <span class="badge text-bg-light">${formatNumber(value || 0)}</span>
          </li>
        `;
      }).join("");
    }

    function renderCriticaRecommendations(items) {
      if (!E.criticaRecommendations) return;
      const source = Array.isArray(items) ? items : [];
      if (!source.length) {
        E.criticaRecommendations.innerHTML = '<div class="text-secondary small">Sem sugestoes para os filtros atuais.</div>';
        return;
      }
      E.criticaRecommendations.innerHTML = source.map(item => `
        <div class="critica-recommendation">
          <div class="fw-bold small">${escapeHtml(cleanDisplayText(item.title || "-"))}</div>
          <div class="small text-secondary">${escapeHtml(cleanDisplayText(item.detail || ""))}</div>
        </div>
      `).join("");
    }

      function renderCriticaDashboard() {
        const payload = state.criticaDashboard && typeof state.criticaDashboard === "object" ? state.criticaDashboard : emptyCriticaDashboard();
        const summary = payload.summary || {};
        const orders = Array.isArray(payload.orders) ? payload.orders : [];
        if (E.criticaDashboardCount) {
          E.criticaDashboardCount.textContent = summary.data_pedido
            ? `${formatNumber(summary.pedidos || orders.length)} pedido(s) | ${formatDate(summary.data_pedido)}`
            : `${formatNumber(summary.pedidos || orders.length)} pedido(s)`;
        E.criticaDashboardCount.className = Number(summary.pedidos_com_problema || 0) ? "pill warn" : "pill ok";
      }
      if (E.criticaDashboardCards) {
        E.criticaDashboardCards.innerHTML = [
          ["Pedidos analisados", summary.pedidos || orders.length, `${formatNumber(summary.pedidos_base || summary.pedidos || 0)} na base da data`],
          ["Com problema", summary.pedidos_com_problema || 0, `${summary.taxa_problema || "0,0%"} dos filtros`],
          ["Valor total", summary.valor_total || "R$ 0,00", `Ticket ${summary.ticket_medio || "R$ 0,00"}`],
          ["Peso total", summary.peso_total || "0,00", "soma dos pedidos"],
          ["Total HL", summary.total_hectolitros || "0,00", "fator hecto x quantidade"],
          ["NAB TT HL", summary.nab_tt_hectolitros || "0,00", "cesta de produtos"],
          ["High End HL", summary.high_end_hectolitros || "0,00", "cesta de produtos"],
          ["Cerveja TT HL", summary.cerveja_tt_hectolitros || "0,00", "cesta de produtos"],
          ["Refri Zero HL", summary.refri_zero_hectolitros || "0,00", "cesta de produtos"],
          ["Cerveja RGB/OW HL", `${summary.cerveja_rgb_hectolitros || "0,00"} / ${summary.cerveja_ow_hectolitros || "0,00"}`, "RGB / OW"],
          ["Marketplace TT R$", summary.marketplace_tt_faturamento || "R$ 0,00", "faturamento da cesta"]
        ].map(([label, value, sub]) => `
          <article class="recolha-dashboard-card">
            <span class="label">${escapeHtml(label)}</span>
            <span class="value">${escapeHtml(String(value))}</span>
            <span class="sub">${escapeHtml(String(sub))}</span>
          </article>
        `).join("");
      }
    }

    function clearCriticaDashboardFilters() {
      CRITICA_DASHBOARD_SLICERS.forEach(def => {
        setCriticaSlicerSelection(def, [], { sync: false, clearDependents: false });
      });
      if (E.criticaSearch) E.criticaSearch.value = "";
      if (E.criticaDate) E.criticaDate.value = "";
      if (E.criticaLimit) E.criticaLimit.value = "200";
      if (E.criticaOnlyProblems) E.criticaOnlyProblems.checked = true;
      syncCriticaDashboard({ silent: false });
    }

    async function syncCriticaDashboard({ silent = true } = {}) {
      updateTokens();
      if (!hasPanelAuth()) {
        if (!silent) addLog("Sessão do painel não validada.", "warn");
        return false;
      }
      try {
        if (!state.panel || !state.panel.mode) await syncPanelSession();
        const params = currentCriticaDashboardParams();
        const payload = await req(`${CONFIG.endpoints.critica.dashboard}?${criticaDashboardQueryString(params)}`, { timeoutMs: 45000 });
        state.criticaDashboard = payload && typeof payload === "object"
          ? {
              total: Number(payload.total || 0),
              summary: payload.summary || {},
              options: payload.options || {},
              rankings: payload.rankings || {},
              recommendations: Array.isArray(payload.recommendations) ? payload.recommendations : [],
              orders: Array.isArray(payload.orders) ? payload.orders : []
            }
          : emptyCriticaDashboard();
        renderCriticaFilterOptions(params);
        renderCriticaDashboard();
        if (!silent) addLog("Dashboard da crítica atualizado.", "ok");
        return true;
      } catch (err) {
        if (!silent) addLog(`Falha ao carregar dashboard da crítica: ${err.message}`, "err");
        renderCriticaDashboard();
        return false;
      }
    }

    async function copyCriticaCommand(command) {
      const text = String(command || "").trim();
      if (!text) return;
      if (await writeTextToClipboard(text)) {
        addLog(`Comando da crítica copiado: ${text}`, "ok");
      } else {
        addLog(`Comando sugerido: ${text}`, "info");
      }
    }

    async function importCriticaGeral() {
      updateTokens();
      if (!hasPanelAuth()) { addLog("Sessão do painel não validada.", "warn"); return; }
      const input = E.criticaGeralFile;
      const file = input && input.files && input.files[0] ? input.files[0] : null;
      if (!file) { addLog("Selecione o CSV completo da Crítica.", "warn"); return; }
      if (!String(file.name || "").toLowerCase().endsWith(".csv")) {
        addLog("O arquivo da Crítica deve ser CSV.", "warn");
        return;
      }
      const confirmed = await askConfirmation(`Importar ${file.name} para todas as operações da Crítica?`);
      if (!confirmed) return;
      const button = E.criticaGeralImportBtn;
      const previousLabel = button ? button.innerHTML : "";
      if (button) {
        button.disabled = true;
        button.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Importando todas';
      }
      if (E.criticaGeralStatus) E.criticaGeralStatus.textContent = "Enviando e atualizando as operações...";
      try {
        const formData = new FormData();
        formData.append("file", file);
        const payload = await req(CONFIG.endpoints.import.criticaGeral, {
          method: "POST",
          headers: {},
          body: formData,
          timeoutMs: 900000
        });
        const datasets = Array.isArray(payload && payload.datasets) ? payload.datasets.join(", ") : "todas as operações";
        if (E.criticaGeralStatus) E.criticaGeralStatus.textContent = `Concluído: ${datasets}.`;
        addLog("CSV geral da Crítica importado e atualizado.", "ok");
        if (input) input.value = "";
        await syncAll();
      } catch (err) {
        if (E.criticaGeralStatus) E.criticaGeralStatus.textContent = `Falha: ${err.message || "não foi possível importar"}.`;
        addLog(`Erro na importação geral da Crítica: ${err.message}`, "err");
      } finally {
        if (button) {
          button.disabled = false;
          button.innerHTML = previousLabel;
        }
      }
    }
