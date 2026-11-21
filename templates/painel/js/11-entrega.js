    function setupRecolhasPane() {
      const pane = document.getElementById("recolhasPane");
      const panel = document.getElementById("recolhasPanel");
      if (pane && panel && panel.parentElement !== pane) {
        pane.appendChild(panel);
      }
    }

    function renderLigaEntregaReports() {
      const payload = state.ligaEntregaReports || {};
      const items = Array.isArray(payload.items) ? payload.items : [];
      const summary = payload.summary || {};
      if (E.entregaLigaReportsSummary) {
        const loaded = Number(summary.loaded || 0);
        const total = Number(summary.total || items.length || 0);
        E.entregaLigaReportsSummary.textContent = total
          ? `${loaded}/${total} relatório(s) com lote salvo no backend.`
          : "Nenhum status de relatório carregado.";
      }
      if (!E.entregaLigaReportsGrid) return;
      if (!items.length) {
        E.entregaLigaReportsGrid.innerHTML = '<div class="col-12 text-secondary">Nenhum relatório da Liga retornado pelo backend.</div>';
        return;
      }
      E.entregaLigaReportsGrid.innerHTML = items.map(item => {
        const manifest = item && item.manifest && typeof item.manifest === "object" ? item.manifest : null;
        const loaded = Boolean(item && item.loaded && manifest);
        const files = manifest && Array.isArray(manifest.files) ? manifest.files : [];
        const storedAt = manifest && manifest.stored_at ? formatDateTime(manifest.stored_at) : "-";
        const referenceDate = manifest && manifest.reference_date ? formatDate(manifest.reference_date) : "-";
        const badgeClass = loaded ? "text-bg-success" : "text-bg-secondary";
        const statusText = loaded ? "Carregado" : "Pendente";
        const fileText = loaded ? `${files.length || Number(manifest.file_count || 0)} arquivo(s)` : "sem lote";
        const filenames = files.slice(0, 3).map(file => escapeHtml(file.filename || "")).filter(Boolean).join(", ");
        const more = files.length > 3 ? ` +${files.length - 3}` : "";
        return `
          <div class="col-md-6">
            <div class="border rounded-3 p-2 h-100 ${loaded ? "" : "opacity-75"}">
              <div class="d-flex align-items-start justify-content-between gap-2">
                <div><span class="badge text-bg-light border me-1 mono">${escapeHtml(item.code || "-")}</span>${escapeHtml(item.label || item.routine || "-")}</div>
                <span class="badge ${badgeClass}">${statusText}</span>
              </div>
              <div class="text-secondary mt-2">${escapeHtml(fileText)} • ref. ${escapeHtml(referenceDate)}</div>
              <div class="text-secondary">Atualizado: ${escapeHtml(storedAt)}</div>
              ${filenames ? `<div class="mono small text-truncate mt-1" title="${filenames}${escapeHtml(more)}">${filenames}${escapeHtml(more)}</div>` : ""}
            </div>
          </div>`;
      }).join("");
      renderLigaEntregaDashboard(items, summary);
    }

    function renderLigaRulesEditor(rulesByOperation) {
      const operation = state.ligaEntregaRulesOperation === "SUME" ? "SUME" : "PATOS";
      const rule = rulesByOperation[operation] || {};
      const metas = rule.metas || {};
      const indicadores = rule.indicadores || {};
      const pesos = rule.pesos || {};
      const mot = pesos.motorista || {};
      const aju = pesos.ajudante || {};
      const indicatorFor = key => key.includes("devol") ? "devolucao" : (key.includes("saida") ? "tml" : (key.includes("km") ? "km" : ""));
      const disabled = key => { const indicator = indicatorFor(key); return indicator && !indicadores[indicator] ? "disabled" : ""; };
      const input = (key, value, label, step = "0.1", hint = "") => `<div class="col-md-6 col-xl-3"><label class="form-label small fw-semibold mb-1">${label}</label><input class="form-control form-control-sm liga-rule-input" data-liga-rule-operation="${operation}" data-liga-rule-key="${key}" type="number" min="0" step="${step}" value="${escapeHtml(String(value ?? ""))}" ${disabled(key)}>${hint ? `<div class="form-text small">${hint}</div>` : ""}</div>`;
      const weightInput = (role, key, value, label) => `<div class="col-sm-4"><label class="form-label small mb-1">${label}</label><div class="input-group input-group-sm"><input class="form-control liga-rule-input" data-liga-rule-operation="${operation}" data-liga-rule-key="pesos.${role}.${key}" type="number" min="0" step="1" value="${escapeHtml(String(value ?? ""))}" ${disabled(key)}><span class="input-group-text">pts</span></div></div>`;
      const toggle = (key, label, description) => `<div class="col-md-4"><label class="border rounded-3 p-3 d-flex gap-2 h-100 align-items-start"><input class="form-check-input mt-1 liga-rule-input liga-rule-toggle" data-liga-rule-operation="${operation}" data-liga-rule-key="indicadores.${key}" type="checkbox" ${indicadores[key] !== false ? "checked" : ""}><span><b class="d-block">${label}</b><small class="text-secondary">${description}</small></span></label></div>`;
      const name = operation === "PATOS" ? "Patos" : "Sumé";
      const competencia = String((state.ligaEntregaDashboard || {}).competencia || ensureLigaMesFilter() || "");
      return `<div class="p-3 p-md-4 liga-rules-editor">
        <div class="d-flex flex-wrap justify-content-between align-items-start gap-3 mb-4">
          <div><h3 class="h5 mb-1">Regras da Liga</h3><div class="text-secondary small">Regras válidas somente para a competência selecionada: <b>${escapeHtml(competencia || "não definida")}</b>.</div></div>
          <div class="btn-group" role="group" aria-label="Operação das regras"><button type="button" class="btn btn-sm ${operation === "PATOS" ? "btn-primary" : "btn-outline-primary"} liga-rules-operation" data-liga-rules-operation="PATOS">Patos</button><button type="button" class="btn btn-sm ${operation === "SUME" ? "btn-primary" : "btn-outline-primary"} liga-rules-operation" data-liga-rules-operation="SUME">Sumé</button></div>
        </div>
        <div class="alert alert-info small py-2 mb-3"><b>Operação em edição: ${name}.</b> As regras de ${operation === "PATOS" ? "Sumé" : "Patos"} e dos outros meses não serão alteradas.</div>
        <section class="border rounded-3 p-3 mb-3"><h4 class="h6 mb-1">Indicadores que valem neste mês</h4><p class="small text-secondary mb-3">Desative o que não deve compor a nota. É preciso manter ao menos um indicador ativo.</p><div class="row g-2">${toggle("devolucao", "Devolução", "Percentual de devoluções")}${toggle("tml", "TML / saída", "Saída dentro do horário configurado")}${toggle("km", "Desvio de KM", "KM realizado acima do previsto")}</div></section>
        <section class="border rounded-3 p-3 mb-3"><h4 class="h6 mb-3">Metas de ${name}</h4><div class="row g-3">
          <div class="col-md-6 col-xl-3"><label class="form-label small fw-semibold mb-1">Base da devolução</label><div class="form-control form-control-sm bg-body-secondary">Quantidade de devoluções ÷ entregas</div><div class="form-text small">Critério padrão da Liga. HL permanece apenas na análise operacional.</div></div>
          ${input("metas.devol", metas.devol, "Devolução máxima", "0.1", "Percentual")}
          ${input("metas.saida_pct", metas.saida_pct, "Saídas no horário", "0.1", "Percentual mínimo")}
          ${input("metas.km", metas.km, "Desvio de KM", "0.1", "Percentual máximo")}
          ${input("metas.min_rotas", metas.min_rotas, "Mínimo de rotas", "1", "Para entrar no ranking")}
          <div class="col-md-6 col-xl-3"><label class="form-label small fw-semibold mb-1">Hora limite de saída</label><input class="form-control form-control-sm liga-rule-input" data-liga-rule-operation="${operation}" data-liga-rule-key="metas.saida" type="time" value="${escapeHtml(metas.saida || "07:30")}" ${disabled("saida")}></div>
          ${input("metas.tempo", metas.tempo, "Tempo normal", "0.1", "% do tempo previsto")}
          ${input("metas.tempo_pern", metas.tempo_pern, "Tempo com pernoite", "0.1", "% do tempo previsto")}
        </div></section>
        <div class="row g-3"><section class="col-lg-6"><div class="border rounded-3 p-3 h-100"><h4 class="h6 mb-1">Pesos — motoristas</h4><p class="small text-secondary mb-3">Definem a importância de cada indicador na nota.</p><div class="row g-2">${weightInput("motorista", "devol", mot.devol, "Devolução")}${weightInput("motorista", "saida", mot.saida, "Saída")}${weightInput("motorista", "km", mot.km, "KM")}</div></div></section><section class="col-lg-6"><div class="border rounded-3 p-3 h-100"><h4 class="h6 mb-1">Pesos — ajudantes</h4><p class="small text-secondary mb-3">Definem a importância de cada indicador na nota.</p><div class="row g-2">${weightInput("ajudante", "devol", aju.devol, "Devolução")}${weightInput("ajudante", "saida", aju.saida, "Saída")}${weightInput("ajudante", "km", aju.km, "KM")}</div></div></section></div>
        <div class="d-flex justify-content-end mt-4"><button type="button" class="btn btn-primary liga-rules-save" data-liga-rules-operation="${operation}"><i class="bi bi-floppy me-1"></i>Salvar regras de ${name}</button></div>
      </div>`;
    }

    async function saveLigaRules(operation) {
      const container = E.entregaLigaDashboardDetails;
      const competencia = String((state.ligaEntregaDashboard || {}).competencia || ensureLigaMesFilter() || "");
      if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(competencia)) throw new Error("Selecione uma competência válida antes de salvar as regras.");
      const rules = { metas: {}, indicadores: {}, pesos: { motorista: {}, ajudante: {} } };
      container.querySelectorAll(`.liga-rule-input[data-liga-rule-operation="${operation}"]`).forEach(input => {
        const [group, role, key] = input.dataset.ligaRuleKey.split(".");
        const value = input.type === "checkbox" ? input.checked : ((input.type === "time" || input.tagName === "SELECT") ? input.value : Number(input.value));
        if (role && key) rules[group][role][key] = value;
        else rules[group][role] = value;
      });
      const result = await req(`${CONFIG.endpoints.ligaEntrega.rules}/${encodeURIComponent(operation)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ competencia, operation, rules }) });
      state.ligaEntregaRules = result.operations || {};
      state.ligaEntregaDashboard = null;
      await syncLigaEntregaReports({ silent: false, force: true });
      addLog(`Regras da Liga para ${operation} salvas para ${competencia}.`, "ok");
    }

    function updateLigaRuleInputs(operation) {
      const container = E.entregaLigaDashboardDetails;
      if (!container) return;
      const active = key => Boolean(container.querySelector(`.liga-rule-toggle[data-liga-rule-operation="${operation}"][data-liga-rule-key="indicadores.${key}"]`)?.checked);
      const indicatorFor = key => key.includes("devol") ? "devolucao" : (key.includes("saida") ? "tml" : (key.includes("km") ? "km" : ""));
      container.querySelectorAll(`.liga-rule-input[data-liga-rule-operation="${operation}"]:not(.liga-rule-toggle)`).forEach(input => {
        const indicator = indicatorFor(input.dataset.ligaRuleKey || "");
        if (indicator) input.disabled = !active(indicator);
      });
    }

    function renderLigaEntregaDashboard(items = [], summary = {}) {
      const dashboard = state.ligaEntregaDashboard || {};
      const dashSummary = dashboard.summary || {};
      const operacao = dashboard.operacao || {};
      const rankings = dashboard.rankings || {};
      const motoristas = Array.isArray(rankings.motoristas) ? rankings.motoristas : [];
      const ajudantes = Array.isArray(rankings.ajudantes) ? rankings.ajudantes : [];
      const rotas = Array.isArray(dashboard.rotas) ? dashboard.rotas : [];
      const missingItems = items.filter(item => !item || !item.loaded);
      const ready = Boolean(dashSummary.ready);
      const fmtPct = value => value === null || value === undefined || value === "" ? "-" : `${Number(value).toLocaleString("pt-BR", { maximumFractionDigits: 2 })}%`;
      const fmtNum = value => Number(value || 0).toLocaleString("pt-BR");
      if (E.entregaLigaDashboardBadge) {
        E.entregaLigaDashboardBadge.textContent = ready ? "Calculado" : "Pendente";
        E.entregaLigaDashboardBadge.className = `pill ${ready ? "ok" : ""}`;
      }
      if (E.entregaLigaDashboardStatus) {
        const comp = dashboard.competencia ? `Competência ${dashboard.competencia}. ` : "";
        E.entregaLigaDashboardStatus.textContent = ready
          ? `${comp}Ranking calculado com os lotes ativos e expurgos aplicados por indicador.`
          : `${comp}Aguardando dados suficientes para calcular ranking, rotas e operação.`;
      }
      if (E.entregaLigaDashboardCards) {
        const eligibleDrivers = Number(dashSummary.motoristas_elegiveis || 0);
        const activeDrivers = Number(dashSummary.motoristas_ativos || 0);
        const registeredDrivers = Number(dashSummary.motoristas || 0);
        E.entregaLigaDashboardCards.innerHTML = [
          ["Rotas", fmtNum(dashSummary.rotas), "mapas considerados"],
          ["Motoristas", fmtNum(eligibleDrivers), `${fmtNum(activeDrivers)} ativos • ${fmtNum(registeredDrivers)} cadastrados`],
          ["Entregas", fmtNum(operacao.entregas), "PDVs únicos/0805"],
          ["Devolução", fmtPct(operacao.devolucao_pct), `${fmtNum(dashSummary.devolucoes)} ativa(s)`],
          ["Saída", fmtPct(operacao.saida_pct), `meta até ${(dashboard.metas || {}).saida || "07:30"}`],
          ["Desvio KM", fmtPct(operacao.km_desv), `${fmtNum((dashboard.expurgos || {}).counts && (((dashboard.expurgos || {}).counts.km || 0) + ((dashboard.expurgos || {}).counts.dispersao || 0)))} expurgo(s) de KM`],
          ["Expurgos", fmtNum(dashSummary.expurgos), `${fmtNum(dashSummary.devolucoes_expurgadas)} devolução(ões)`]
        ].map(([label, value, sub]) => `
          <article class="recolha-dashboard-card">
            <span class="label">${escapeHtml(label)}</span>
            <span class="value">${escapeHtml(value)}</span>
            <span class="sub">${escapeHtml(sub)}</span>
          </article>`).join("");
      }
      const rankingRows = (rows, role) => rows.slice(0, 10).map(item => `
        <tr>
          <td>${item.pos ? `${item.pos}º` : "-"}</td>
          <td><b>${escapeHtml(item.nome || item.cod || "-")}</b><div class="text-secondary small">${escapeHtml(item.filial || "-")} • ${escapeHtml(item.cod || "-")}</div></td>
          <td class="text-end">${fmtNum(item.rotas)}</td>
          <td class="text-end">${fmtPct(item.pdev)}<div class="text-secondary small">${fmtNum(item.devol)}/${fmtNum(item.entregas)}</div></td>
          <td class="text-end">${fmtPct(item.psaida)}</td>
          <td class="text-end">${fmtPct(item.km_desv)}</td>
          <td class="text-end"><b>${fmtNum(item.total)}</b></td>
        </tr>`).join("") || `<tr><td colspan="7" class="text-center text-secondary py-3">Sem ${role} calculado.</td></tr>`;
      const rotasRows = rotas.slice(-12).reverse().map(rota => `
        <tr>
          <td>${escapeHtml(formatDate(rota.data) || "-")}</td>
          <td>${escapeHtml(rota.mapa || "-")}</td>
          <td>${escapeHtml(rota.filial || "-")}</td>
          <td>${escapeHtml(rota.cidade || "-")}</td>
          <td class="text-end">${fmtNum(rota.entregas)}</td>
          <td class="text-end">${escapeHtml(rota.hr_sai || "-")}</td>
          <td class="text-end">${fmtPct(rota.tempo_pct)}</td>
          <td class="text-end">${rota.expurgo_saida ? "TML" : ""}${rota.expurgo_km ? `${rota.expurgo_saida ? ", " : ""}KM` : ""}<div class="mt-1"><button class="btn btn-outline-secondary btn-sm py-0 liga-expurgo-route" type="button" data-expurgo-tipo="tml" data-expurgo-data="${escapeHtml(rota.data || "")}" data-expurgo-filial="${escapeHtml(rota.filial || "")}" data-expurgo-mapa="${escapeHtml(rota.mapa || "")}">TML</button> <button class="btn btn-outline-secondary btn-sm py-0 liga-expurgo-route" type="button" data-expurgo-tipo="km" data-expurgo-data="${escapeHtml(rota.data || "")}" data-expurgo-filial="${escapeHtml(rota.filial || "")}" data-expurgo-mapa="${escapeHtml(rota.mapa || "")}">KM</button></div></td>
        </tr>`).join("") || '<tr><td colspan="8" class="text-center text-secondary py-3">Sem rotas calculadas.</td></tr>';
      if (E.entregaLigaDashboardDetails) {
        const missingText = missingItems.length ? `Pendentes: ${missingItems.map(item => item.label || item.routine || "-").join(", ")}.` : "Todos os insumos homologados disponíveis ou já processados.";
        const warnings = Array.isArray(dashboard.warnings) ? dashboard.warnings : [];
        E.entregaLigaDashboardDetails.innerHTML = `
          <div class="d-flex flex-wrap gap-2 align-items-center justify-content-between mb-3">
            <div><div class="small text-secondary">Fonte</div><div class="source-path">${escapeHtml(missingText)} Expurgos aplicados: devolução só em devolução, TML só em saída, KM/dispersão só em KM.</div></div>
            ${dashboard.generated_at ? `<span class="badge text-bg-light border">Atualizado ${escapeHtml(formatDateTime(dashboard.generated_at))}</span>` : ""}
          </div>
          <div class="row g-3">
            <div class="col-xl-6">
              <h3 class="h6 fw-bold mb-2">Ranking motoristas</h3>
              <div class="table-scroll"><table class="table table-sm table-hover align-middle mb-0"><thead><tr><th>#</th><th>Motorista</th><th class="text-end">Rotas</th><th class="text-end">Dev.</th><th class="text-end">Saída</th><th class="text-end">KM</th><th class="text-end">Total</th></tr></thead><tbody>${rankingRows(motoristas, "motorista")}</tbody></table></div>
            </div>
            <div class="col-xl-6">
              <h3 class="h6 fw-bold mb-2">Ranking ajudantes</h3>
              <div class="table-scroll"><table class="table table-sm table-hover align-middle mb-0"><thead><tr><th>#</th><th>Ajudante</th><th class="text-end">Rotas</th><th class="text-end">Dev.</th><th class="text-end">Saída</th><th class="text-end">KM</th><th class="text-end">Total</th></tr></thead><tbody>${rankingRows(ajudantes, "ajudante")}</tbody></table></div>
            </div>
            <div class="col-12">
              <h3 class="h6 fw-bold mb-2">Últimas rotas calculadas</h3>
              <div class="table-scroll"><table class="table table-sm table-hover align-middle mb-0"><thead><tr><th>Data</th><th>Mapa</th><th>Filial</th><th>Cidade</th><th class="text-end">Entregas</th><th class="text-end">Saída</th><th class="text-end">Tempo</th><th class="text-end">Expurgo</th></tr></thead><tbody>${rotasRows}</tbody></table></div>
            </div>
          </div>
          ${warnings.length ? `<div class="alert alert-warning small mt-3 mb-0"><b>Avisos de leitura:</b><br>${warnings.slice(0, 5).map(w => escapeHtml(w)).join("<br>")}</div>` : ""}`;
        renderLigaEntregaOperationalViews(dashboard);
      }
    }

    async function downloadLigaDashboardPdf(view) {
      updateTokens();
      const normalizedView = view === "ajudantes" ? "ajudantes" : "motoristas";
      const dashboard = state.ligaEntregaDashboard || {};
      const query = new URLSearchParams({ view: normalizedView });
      if (dashboard.competencia) query.set("competencia", dashboard.competencia);
      const headers = {};
      if (state.tokens.api) headers["x-api-token"] = state.tokens.api;
      if (state.tokens.admin) headers["x-admin-token"] = state.tokens.admin;
      try {
        const response = await fetch(`${CONFIG.api}${CONFIG.endpoints.ligaEntrega.dashboardPdf}?${query.toString()}`, {
          method: "GET",
          credentials: "same-origin",
          headers,
        });
        if (!response.ok) {
          const payload = await response.json().catch(() => null);
          throw new Error(payload && payload.detail ? payload.detail : `HTTP ${response.status}`);
        }
        const blob = await response.blob();
        const disposition = response.headers.get("content-disposition") || "";
        const matchedName = disposition.match(/filename=\"?([^\";]+)\"?/i);
        const filename = matchedName && matchedName[1]
          ? matchedName[1]
          : `liga-entrega-${normalizedView}-${dashboard.competencia || "dados"}.pdf`;
        const blobUrl = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = blobUrl;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(blobUrl);
        addLog(`PDF da Liga (${normalizedView}) baixado.`, "ok");
      } catch (err) {
        addLog(`Falha ao baixar PDF da Liga: ${err.message}`, "err");
      }
    }

    function printLigaDashboard(view) {
      const previousView = state.ligaEntregaView || "motoristas";
      state.ligaEntregaView = view === "ajudantes" ? "ajudantes" : "motoristas";
      renderLigaEntregaDashboard((state.ligaEntregaReports || {}).items || [], (state.ligaEntregaReports || {}).summary || {});
      document.body.classList.add("liga-print-mode");
      const restore = () => {
        document.body.classList.remove("liga-print-mode");
        state.ligaEntregaView = previousView;
        renderLigaEntregaDashboard((state.ligaEntregaReports || {}).items || [], (state.ligaEntregaReports || {}).summary || {});
        window.removeEventListener("afterprint", restore);
      };
      window.addEventListener("afterprint", restore);
      window.print();
    }

    function printEntregaDevolucoes() {
      document.body.classList.add("entrega-devolucoes-print-mode");
      const restore = () => {
        document.body.classList.remove("entrega-devolucoes-print-mode");
        window.removeEventListener("afterprint", restore);
      };
      window.addEventListener("afterprint", restore);
      window.print();
    }

    function renderLigaEntregaOperationalViews(dashboard) {
      if (!E.entregaLigaDashboardDetails) return;
      const rankings = dashboard.rankings || {};
      const routes = Array.isArray(dashboard.rotas) ? dashboard.rotas : [];
      const devols = Array.isArray(dashboard.devolucoes_auxiliares) ? dashboard.devolucoes_auxiliares : (Array.isArray(dashboard.devolucoes) ? dashboard.devolucoes : []);
      const team = Array.isArray(dashboard.equipe) ? dashboard.equipe : [];
      const dashboardCompetencia = String(dashboard.competencia || "").trim();
      const coverage = (Array.isArray(dashboard.cobertura) ? dashboard.cobertura : [])
        .filter(row => !dashboardCompetencia || String(row.data || "").startsWith(`${dashboardCompetencia}-`));
      const view = state.ligaEntregaView || "motoristas";
      const filters = state.ligaEntregaFilters || {};
      const q = String(filters.q || "").trim().toLowerCase();
      const branch = String(filters.filial || "");
      const filter = rows => rows.filter(row => (!branch || String(row.filial || "") === branch) && (!q || JSON.stringify(row).toLowerCase().includes(q)));
      const fmt = value => Number(value || 0).toLocaleString("pt-BR", { maximumFractionDigits: 2 });
      const pct = value => value === null || value === undefined ? "-" : `${fmt(value)}%`;
      const table = (head, body) => `<div class="table-scroll"><table class="table table-sm table-hover align-middle mb-0"><thead><tr>${head}</tr></thead><tbody>${body || '<tr><td colspan="12" class="text-center text-secondary py-3">Nenhum registro para este filtro.</td></tr>'}</tbody></table></div>`;
      const personRows = (rows, role) => {
        const metric = (value, meta, higherIsBetter = false, detail = "", enabled = true) => {
          if (!enabled) return `<span class="text-secondary small">Não aplicado</span>`;
          const valid = value !== null && value !== undefined;
          const good = valid && (higherIsBetter ? Number(value) >= meta : Number(value) <= meta);
          return `<span class="liga-kpi ${valid ? (good ? "good" : "bad") : ""}"><b>${pct(value)}</b>${detail ? `<small>${escapeHtml(detail)}</small>` : ""}</span>`;
        };
        const prizes = role === "motoristas" ? [700, 600, 500, 450, 400, 350, 300, 300, 250, 250, 250, "BRINDE", "BRINDE", "BRINDE", "BRINDE", "BRINDE", "BRINDE"] : [500, 400, 350, 300, 250, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 150, 150, "BRINDE", "BRINDE", "BRINDE", "BRINDE", "BRINDE", "BRINDE", "BRINDE", "BRINDE", "BRINDE", "BRINDE", "BRINDE", "BRINDE"];
        const prize = pos => { const value = pos ? prizes[Number(pos) - 1] : null; return value === "BRINDE" ? '<span class="liga-prize gift"><i class="bi bi-gift-fill me-1"></i>Brinde</span>' : value ? `<span class="liga-prize">R$ ${fmt(value)}</span>` : '<span class="text-secondary">—</span>'; };
        return `<div class="table-scroll"><table class="table table-sm table-hover align-middle mb-0 liga-ranking-table"><thead><tr><th># <i class="bi bi-caret-up-fill text-warning"></i></th><th>Colaborador</th><th>Filial</th><th class="text-end">Rotas</th><th class="text-end">Devolução<span class="sub">≤${(dashboard.metas || {}).devol || 1.4}%</span></th><th class="text-end">Saída ≤${(dashboard.metas || {}).saida || "07:30"}<span class="sub">≥${(dashboard.metas || {}).saida_pct || 90}%</span></th><th class="text-end">Desvio KM<span class="sub">≤${(dashboard.metas || {}).km || 10}%</span></th><th class="text-end">Total</th><th class="text-end">Prêmio</th></tr></thead><tbody>${filter(rows.filter(row => String(row.status || "ativo") === "ativo")).map(row => { const pos = Number(row.pos || 0); const medal = pos ? `${pos}º` : "—"; const score = Math.max(0, Math.min(100, Number(row.total || 0))); const active = row.indicadores_ativos || {}; const devDetail = row.devolucao_base === "hl" ? `${fmt(row.devol_hl)} HL/${fmt(row.entregas_hl)} HL` : `${fmt(row.devol)}/${fmt(row.entregas)}`; return `<tr class="${pos ? `top-${pos}` : ""}"><td><span class="liga-rank ${pos && pos <= 3 ? "top" : ""}">${medal}</span></td><td><button type="button" class="btn btn-link p-0 liga-person-name liga-person-detail" data-liga-person="${escapeHtml(row.cod || "")}">${escapeHtml(row.nome || row.cod || "-")}</button></td><td>${escapeHtml(row.filial || "-")}</td><td class="text-end"><b>${fmt(row.rotas)}</b></td><td class="text-end">${metric(row.pdev, Number((dashboard.metas || {}).devol || 1.4), false, devDetail, active.devol !== false)}</td><td class="text-end">${metric(row.psaida, Number((dashboard.metas || {}).saida_pct || 90), true, "", active.saida !== false)}</td><td class="text-end">${metric(row.km_desv, Number((dashboard.metas || {}).km || 10), false, "", active.km !== false)}</td><td class="text-end"><span class="liga-score-wrap"><span class="liga-score-bar ${pos === 1 ? "gold" : ""}"><i style="width:${score}%"></i></span><span class="liga-score">${fmt(row.total)}</span></span></td><td class="text-end">${prize(row.pos)}</td></tr>`; }).join("") || '<tr><td colspan="9" class="text-center text-secondary py-4">Nenhum colaborador para este filtro.</td></tr>'}</tbody></table></div>`;
      };
      let content = "";
      if (view === "motoristas" || view === "ajudantes") content = personRows(Array.isArray(rankings[view]) ? rankings[view] : [], view);
      if (view === "devolucoes") content = renderLigaDevolucoesExpurgoCard(dashboard, filter);
      if (view === "rotas") content = table('<th>Data</th><th>Mapa</th><th>Filial</th><th>Motorista</th><th>Ajudantes</th><th>Cidade</th><th class="text-end">Entregas</th><th class="text-end">KM real/prev.</th><th class="text-end">Saída</th><th class="text-end">Tempo</th><th>Expurgos</th><th>Ações</th>', filter(routes).slice().reverse().map(row => { const suspect = Number(row.km_real || 0) > Number(row.km_prev || 0) + 50; const late = String(row.hr_sai || "") > "12:00"; const expurgos = [row.expurgo_saida ? '<span class="badge text-bg-warning me-1">TML</span>' : "", row.expurgo_km ? '<span class="badge text-bg-warning">KM</span>' : ""].filter(Boolean).join("") || '<span class="text-secondary">—</span>'; const helperNames = (row.aju || []).map(code => (team.find(p => p.cod === code) || {}).nome || code).join(", "); const pending030805 = row.pendente_030805 ? ' <span class="badge text-bg-warning">sem 03.08.05</span>' : ""; return `<tr><td>${escapeHtml(formatDate(row.data) || "-")}</td><td>${escapeHtml(row.mapa || "-")}${row.equipe_override ? ' <span class="badge text-bg-info">ajustada</span>' : ""}${pending030805}</td><td>${escapeHtml(row.filial || "-")}</td><td>${escapeHtml((team.find(p => p.cod === row.mot) || {}).nome || row.mot || "-")}</td><td>${escapeHtml(helperNames || "—")}</td><td>${escapeHtml(row.cidade || "-")}</td><td class="text-end">${row.pendente_030805 || row.entregas === null || row.entregas === undefined ? "—" : fmt(row.entregas)}</td><td class="text-end ${suspect ? "text-warning fw-bold" : ""}">${fmt(row.km_real)} / ${fmt(row.km_prev)}${suspect ? " ⚠" : ""}</td><td class="text-end ${late ? "text-warning fw-bold" : ""}">${escapeHtml(row.hr_sai || "-")}${late ? " ⚠" : ""}</td><td class="text-end">${pct(row.tempo_pct)}</td><td>${expurgos}</td><td><button class="btn btn-outline-primary btn-sm py-0 liga-route-team" type="button" data-route-data="${escapeHtml(row.data || "")}" data-route-filial="${escapeHtml(row.filial || "")}" data-route-mapa="${escapeHtml(row.mapa || "")}" data-route-mot="${escapeHtml(row.mot || "")}" data-route-aju="${escapeHtml((row.aju || []).join(","))}">Equipe</button> <button class="btn btn-outline-secondary btn-sm py-0 liga-expurgo-route" type="button" data-expurgo-tipo="tml" data-expurgo-data="${escapeHtml(row.data || "")}" data-expurgo-filial="${escapeHtml(row.filial || "")}" data-expurgo-mapa="${escapeHtml(row.mapa || "")}">TML</button> <button class="btn btn-outline-secondary btn-sm py-0 liga-expurgo-route" type="button" data-expurgo-tipo="km" data-expurgo-data="${escapeHtml(row.data || "")}" data-expurgo-filial="${escapeHtml(row.filial || "")}" data-expurgo-mapa="${escapeHtml(row.mapa || "")}">KM</button></td></tr>`; }).join(""));
      if (view === "equipe") {
        const pending = state.ligaEntregaTeamChanges || {};
        const pendingCount = Object.keys(pending).length;
        const rankingByCode = new Map([...(rankings.motoristas || []), ...(rankings.ajudantes || [])].map(row => [String(row.cod || ""), row]));
        const rows = filter(team).map(row => {
          const selected = pending[row.cod] || row.status || "ativo";
          const exp = (rankingByCode.get(String(row.cod || "")) || {}).expurgos || {};
          const expurgos = [["Dev", exp.devolucao], ["TML", exp.tml], ["KM", exp.km]].filter(([, count]) => Number(count || 0) > 0).map(([label, count]) => `<span class="badge text-bg-warning me-1">${label}: ${count}</span>`).join("") || '<span class="text-secondary">—</span>';
          return `<tr><td>${escapeHtml(row.funcao || "-")}</td><td>${escapeHtml(row.nome || "-")}</td><td>${escapeHtml(row.filial || "-")}</td><td><select class="form-select form-select-sm liga-team-status" data-liga-code="${escapeHtml(row.cod || "")}">${["ativo","ferias","afastado","desligado"].map(status => `<option value="${status}" ${selected === status ? "selected" : ""}>${status}</option>`).join("")}</select></td><td>${expurgos}</td><td>${escapeHtml(row.cod || "-")}</td></tr>`;
        }).join("");
        const candidates = Array.isArray(dashboard.equipe_candidatos) ? dashboard.equipe_candidatos : [];
        const candidateCard = candidates.length ? `<details class="liga-roster-candidates mb-3"><summary><i class="bi bi-person-plus me-1"></i>Encontrados nos relatórios, fora da Liga <span class="badge text-bg-info ms-1">${candidates.length}</span></summary><div class="row g-2 mt-1">${candidates.map(item => `<div class="col-xl-4 col-md-6"><div class="border rounded p-2 h-100 d-flex align-items-center justify-content-between gap-2"><div class="text-truncate"><div class="small fw-semibold text-uppercase">${escapeHtml(item.funcao || "-")} · ${escapeHtml(item.filial || "-")}</div><div class="text-truncate" title="${escapeHtml(item.nome || "-")}">${escapeHtml(item.nome || "-")}</div><small class="text-secondary">Código ${escapeHtml(item.cod || "-")}</small></div><button type="button" class="btn btn-sm btn-primary flex-shrink-0 liga-roster-add" data-roster-cod="${escapeHtml(item.cod || "")}" data-roster-nome="${escapeHtml(item.nome || "")}" data-roster-filial="${escapeHtml(item.filial || "")}" data-roster-funcao="${escapeHtml(item.funcao || "")}">Adicionar</button></div></div>`).join("")}</div></details>` : "";
        content = `${candidateCard}<div class="liga-team-pending"><small>${pendingCount ? `${pendingCount} alteração(ões) pendente(s). Revise a equipe antes de gravar.` : "Altere os status livremente; nada será sincronizado até você salvar."}</small><button type="button" class="btn btn-primary btn-sm liga-team-save" ${pendingCount ? "" : "disabled"}><i class="bi bi-floppy me-1"></i>Salvar alterações${pendingCount ? ` (${pendingCount})` : ""}</button></div>${table('<th>Função</th><th>Colaborador</th><th>Filial</th><th>Status</th><th>Expurgos</th><th>Código</th>', rows)}`;
      }
      if (view === "cobertura") content = `<div class="row g-2">${coverage.map(row => { const pending = Number(row.rotas_pendentes_030805 || 0); return `<div class="col-md-4"><div class="border rounded p-2"><b>${escapeHtml(formatDate(row.data) || "-")}</b><div>${fmt(row.rotas)} rota(s) • ${fmt(row.motoristas || row.mot || 0)} motorista(s)</div>${pending ? `<div class="small text-warning fw-semibold">${fmt(pending)} rota(s) pendente(s) da 03.08.05</div>` : ""}<div class="small ${pending ? "text-warning" : "text-secondary"}">${escapeHtml(row.status || "Cobertura calculada")}</div></div></div>`; }).join("") || '<div class="text-secondary">Sem cobertura diária calculada.</div>'}</div>`;
      if (view === "regras") content = renderLigaRulesEditor(dashboard.regras_operacao || state.ligaEntregaRules || {});
      const tabs = [["motoristas","Motoristas"],["ajudantes","Ajudantes"],["devolucoes","Devoluções"],["rotas","Rotas"],["equipe","Equipe"],["cobertura","Cobertura"],["regras","Regras"]].map(([key,label]) => `<button class="btn btn-sm ${view === key ? "btn-primary" : "btn-outline-secondary"} liga-view" data-liga-view="${key}" type="button">${label}</button>`).join(" ");
      const warnings = Array.isArray(dashboard.warnings) ? dashboard.warnings : [];
      E.entregaLigaDashboardDetails.innerHTML = `<section class="liga-dash-shell"><div class="liga-dash-controls"><div class="liga-dash-context"><b>${escapeHtml(dashboard.competencia || "Liga Entrega")}</b>${fmt(routes.length)} rotas processadas</div><div class="liga-dash-tools"><div class="liga-view-tabs" role="tablist">${tabs}</div><div class="liga-filters"><select class="form-select form-select-sm liga-filter-branch" aria-label="Filial"><option value="">Todas filiais</option><option value="PATOS" ${branch === "PATOS" ? "selected" : ""}>Patos</option><option value="SUME" ${branch === "SUME" ? "selected" : ""}>Sumé</option></select><div class="input-group input-group-sm"><span class="input-group-text"><i class="bi bi-search"></i></span><input class="form-control liga-filter-search" value="${escapeHtml(filters.q || "")}" placeholder="Buscar pessoa, mapa ou cliente"></div><div class="liga-pdf-actions"><button type="button" class="btn btn-sm btn-outline-primary liga-dashboard-pdf" data-liga-pdf="motoristas"><i class="bi bi-file-earmark-pdf me-1"></i>PDF motoristas</button><button type="button" class="btn btn-sm btn-outline-primary liga-dashboard-print" data-liga-print="motoristas"><i class="bi bi-printer me-1"></i>Imprimir motoristas</button><button type="button" class="btn btn-sm btn-outline-primary liga-dashboard-pdf" data-liga-pdf="ajudantes"><i class="bi bi-file-earmark-pdf me-1"></i>PDF ajudantes</button><button type="button" class="btn btn-sm btn-outline-primary liga-dashboard-print" data-liga-print="ajudantes"><i class="bi bi-printer me-1"></i>Imprimir ajudantes</button></div></div></div></div><div id="ligaOperationalView" class="liga-operational-view">${content}</div>${warnings.length ? `<div class="alert alert-warning small m-3"><b>Leitura parcial:</b> ${warnings.slice(0, 3).map(w => escapeHtml(w)).join(" · ")}</div>` : ""}</section>`;
    }

    function renderEntregaDevolucaoChart(title, rows, field, limit = 8, featured = false, metric = "volume_hl") {
      const fmt = value => Number(value || 0).toLocaleString("pt-BR", { maximumFractionDigits: 2 });
      const metricLabel = metric === "valor" ? "Valor" : metric === "registros" ? "Registros" : "Volume";
      const metricValue = item => metric === "valor" ? item.valor : metric === "registros" ? item.count : item.volume;
      const metricFmt = value => metric === "valor" ? `R$ ${fmt(value)}` : metric === "registros" ? fmt(value) : `${fmt(value)} HL`;
      const totals = new Map();
      rows.forEach(row => {
        const label = String(row[field] || "Sem informação").trim() || "Sem informação";
        if (["0", "9", "99"].includes(label)) return;
        const item = totals.get(label) || { label, volume: 0, valor: 0, count: 0 };
        item.volume += Number(row.volume_hl || 0);
        item.valor += Number(row.valor || 0);
        item.count += 1;
        totals.set(label, item);
      });
      const items = [...totals.values()].sort((a, b) => metricValue(b) - metricValue(a) || b.count - a.count).slice(0, limit);
      const max = Math.max(...items.map(metricValue), 1);
      const bars = items.map(item => `<div class="devolucao-bar-row" title="${escapeHtml(item.label)}: ${metricFmt(metricValue(item))} · ${item.count} registro(s)"><span class="devolucao-bar-label">${escapeHtml(item.label)}</span><span class="devolucao-bar-track"><span class="devolucao-bar-fill" style="width:${Math.max(2, (metricValue(item) / max) * 100)}%"></span></span><span class="devolucao-bar-value">${metricFmt(metricValue(item))}</span></div>`).join("");
      const dataTable = items.map(item => `<tr><td>${escapeHtml(item.label)}</td><td class="text-end">${fmt(item.volume)} HL</td><td class="text-end">R$ ${fmt(item.valor)}</td><td class="text-end">${item.count}</td></tr>`).join("");
      return `<article class="entrega-devolucao-chart ${featured ? "featured" : ""}"><h3>${escapeHtml(title)}</h3><div class="chart-caption">${metricLabel} por categoria · passe o mouse para o detalhe</div>${items.length ? `<div class="devolucao-bars" role="img" aria-label="${escapeHtml(title)} por ${escapeHtml(metricLabel.toLowerCase())}">${bars}</div><details><summary>Ver dados</summary><table><thead><tr><th>Categoria</th><th class="text-end">Volume</th><th class="text-end">Valor</th><th class="text-end">Registros</th></tr></thead><tbody>${dataTable}</tbody></table></details>` : '<div class="text-secondary small py-4">Sem dados para este gráfico.</div>'}</article>`;
    }

    function renderEntregaDevolucaoTrend(rows, metric = "volume_hl") {
      const fmt = value => Number(value || 0).toLocaleString("pt-BR", { maximumFractionDigits: 2 });
      const metricLabel = metric === "valor" ? "Valor devolvido" : metric === "registros" ? "Registros de devolução" : "Volume devolvido";
      const metricValue = item => metric === "valor" ? item.valor : metric === "registros" ? item.count : item.volume;
      const metricFmt = value => metric === "valor" ? `R$ ${fmt(value)}` : metric === "registros" ? fmt(value) : `${fmt(value)} HL`;
      const totals = new Map();
      rows.forEach(row => {
        const key = String(row.data_devolucao || row.data || "").slice(0, 10);
        if (!/^\d{4}-\d{2}-\d{2}$/.test(key)) return;
        const item = totals.get(key) || { date: key, volume: 0, valor: 0, count: 0 };
        item.volume += Number(row.volume_hl || 0);
        item.valor += Number(row.valor || 0);
        item.count += 1;
        totals.set(key, item);
      });
      const items = [...totals.values()].map(item => ({ ...item, value: metricValue(item) })).sort((a, b) => a.date.localeCompare(b.date));
      if (!items.length) return `<article class="entrega-devolucao-chart devolucao-trend-chart devolucao-chart-wide"><h3>Devolução por dia</h3><div class="chart-caption">${escapeHtml(metricLabel)} no período</div><div class="text-secondary small py-4">Sem datas válidas para este gráfico.</div></article>`;
      const width = 760; const height = 205; const pad = { left: 42, right: 14, top: 16, bottom: 30 };
      const max = Math.max(...items.map(item => item.value), 1); const innerW = width - pad.left - pad.right; const innerH = height - pad.top - pad.bottom;
      const yFor = value => pad.top + innerH - (value / max) * innerH;
      const point = (item, index) => `${(pad.left + (items.length === 1 ? innerW / 2 : index * innerW / (items.length - 1))).toFixed(1)},${yFor(item.value).toFixed(1)}`;
      const points = items.map(point).join(" ");
      const area = `${pad.left},${pad.top + innerH} ${points} ${pad.left + innerW},${pad.top + innerH}`;
      const grid = [0, .5, 1].map(ratio => { const y = pad.top + innerH - ratio * innerH; return `<line class="trend-grid" x1="${pad.left}" x2="${pad.left + innerW}" y1="${y}" y2="${y}"/><text x="2" y="${y + 4}">${escapeHtml(metricFmt(max * ratio))}</text>`; }).join("");
      const dots = items.map((item, index) => { const [x, y] = point(item, index).split(","); return `<circle class="trend-dot" cx="${x}" cy="${y}" r="3.5"><title>${escapeHtml(formatDate(item.date))}: ${escapeHtml(`${metricFmt(item.value)} (${item.count} registro(s))`)}</title></circle>`; }).join("");
      const labels = items.filter((_, index) => index === 0 || index === items.length - 1 || index === Math.floor((items.length - 1) / 2)).map(item => `<text x="${pad.left + items.indexOf(item) * innerW / Math.max(items.length - 1, 1)}" y="${height - 6}" text-anchor="middle">${escapeHtml(formatDate(item.date).slice(0, 5))}</text>`).join("");
      return `<article class="entrega-devolucao-chart devolucao-trend-chart devolucao-chart-wide"><h3>Devolução por dia</h3><div class="chart-caption">${escapeHtml(metricLabel)} no período filtrado</div><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(metricLabel)} por dia"><defs><linearGradient id="devolucaoTrendFill" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#7c5cff"/><stop offset="1" stop-color="#7c5cff" stop-opacity="0"/></linearGradient></defs>${grid}<polygon class="trend-area" points="${area}"/><polyline class="trend-line" points="${points}"/>${dots}${labels}</svg><details><summary>Ver dados</summary><table><thead><tr><th>Data</th><th class="text-end">${escapeHtml(metricLabel)}</th><th class="text-end">Registros</th></tr></thead><tbody>${items.map(item => `<tr><td>${escapeHtml(formatDate(item.date))}</td><td class="text-end">${escapeHtml(metricFmt(item.value))}</td><td class="text-end">${item.count}</td></tr>`).join("")}</tbody></table></details></article>`;
    }

    function renderEntregaDevolucoes(dashboard = {}) {
      ensureDevolucoesJustificativasTabs();
      if (state.devolucoesSubtab === 'justificativas') {
        renderDevolucoesJustificativas();
        return;
      }
      const persistedNames = dashboard.cadastros && typeof dashboard.cadastros === "object" ? dashboard.cadastros : {};
      const entriesFor = kind => [
        ...(Array.isArray(persistedNames[kind]) ? persistedNames[kind] : []),
        ...(Array.isArray(state.devolucoesCadastros?.[kind]) ? state.devolucoesCadastros[kind] : []),
      ];
      const operationLabels = new Map([
        ...(Array.isArray(persistedNames.operacoes) ? persistedNames.operacoes : []),
        ...(Array.isArray(state.devolucoesCadastros?.catalogo?.operacoes) ? state.devolucoesCadastros.catalogo.operacoes : []),
      ].map(item => [String(item.codigo || "").trim().toUpperCase(), String(item.nome || "").trim().toUpperCase()]));
      const makeNameMap = kind => new Map(entriesFor(kind).map(item => [`${String(item.filial || "").trim().toUpperCase()}|${String(item.codigo || "").trim()}`, String(item.nome || "").trim()]));
      const sectorNames = makeNameMap("setores");
      const managerNames = makeNameMap("gerentes");
      const allRows = (Array.isArray(dashboard.rows) ? dashboard.rows : []).map(row => {
        const filial = String(row.filial || "").trim().toUpperCase();
        const setor = String(row.setor || "").trim();
        const gv = String(row.gv || "").trim();
        return {
          ...row,
          setor_nome: sectorNames.get(`${filial}|${setor}`) || sectorNames.get(`|${setor}`) || entriesFor("setores").find(item => String(item.codigo || "").trim() === setor && String(item.nome || "").trim() && operationLabels.get(String(item.filial || "").trim().toUpperCase())?.includes(filial))?.nome || row.setor_nome || setor,
          gerente_nome: managerNames.get(`${filial}|${gv}`) || managerNames.get(`|${gv}`) || entriesFor("gerentes").find(item => String(item.codigo || "").trim() === gv && String(item.nome || "").trim() && operationLabels.get(String(item.filial || "").trim().toUpperCase())?.includes(filial))?.nome || row.gerente_nome || gv,
        };
      });
      const branch = String(state.entregaDevolucoesBranch || "").toUpperCase();
      const responsibility = String(state.entregaDevolucoesResponsibility || "").trim();
      const responsibilityOf = row => String(row.motivo_responsabilidade || row.resp || "Não informado").trim() || "Não informado";
      const branchRows = allRows.filter(row => !branch || String(row.filial || "").trim().toUpperCase() === branch);
      const responsibilityOptions = [...new Set(branchRows.map(responsibilityOf))].sort((a, b) => a.localeCompare(b, "pt-BR"));
      const rows = branchRows.filter(row => !responsibility || responsibilityOf(row) === responsibility);
      const fmt = value => Number(value || 0).toLocaleString("pt-BR", { maximumFractionDigits: 2 });
      const q = String(state.entregaDevolucoesFilter || "").trim().toLowerCase();
      const returnDate = String(state.entregaDevolucoesDate || "").slice(0, 10);
      const selectedRows = rows.filter(row =>
        (!q || JSON.stringify(row).toLowerCase().includes(q)) &&
        (!returnDate || String(row.data_devolucao || "").slice(0, 10) === returnDate)
      );
      const period = ["all", "7", "30"].includes(String(state.entregaDevolucoesPeriod)) ? String(state.entregaDevolucoesPeriod) : "all";
      const dateOf = row => String(row.data_devolucao || row.data || "").slice(0, 10);
      const stamps = selectedRows.map(row => Date.parse(`${dateOf(row)}T00:00:00Z`)).filter(Number.isFinite);
      const latestStamp = stamps.length ? Math.max(...stamps) : NaN;
      const activeRows = period === "all" || !Number.isFinite(latestStamp) ? selectedRows : selectedRows.filter(row => {
        const stamp = Date.parse(`${dateOf(row)}T00:00:00Z`);
        return Number.isFinite(stamp) && latestStamp - stamp <= Number(period) * 86400000;
      });
      const totalVolume = activeRows.reduce((sum, row) => sum + Number(row.volume_hl || 0), 0);
      const totalValue = activeRows.reduce((sum, row) => sum + Number(row.valor || 0), 0);
      const unique = field => new Set(activeRows.map(row => String(row[field] || "").trim()).filter(Boolean)).size;
      const bases = dashboard.bases_entrega && typeof dashboard.bases_entrega === "object" ? dashboard.bases_entrega : {};
      const base = branch && bases.filiais && bases.filiais[branch] ? bases.filiais[branch] : (bases.geral || {});
      const pct = (value, denominator) => Number(denominator || 0) > 0 ? value / Number(denominator) * 100 : null;
      const fmtPct = value => value === null || !Number.isFinite(value) ? "-" : `${fmt(value)}%`;
      const pdvs = unique("cliente_cod") || unique("cliente");
      const nfs = unique("nota");
      const hlPct = pct(totalVolume, base.entregas_hl);
      const pdvPct = pct(pdvs, base.entregas_pdvs);
      const nfPct = pct(nfs, base.entregas_nfs);
      const cards = [
        ["HL devolvido", fmtPct(hlPct), `${fmt(totalVolume)} HL`, false],
        ["PDVs devolvidos", fmtPct(pdvPct), `${fmt(pdvs)} PDVs`, false],
        ["NFs devolvidas", fmtPct(nfPct), `${fmt(nfs)} NFs`, false],
        ["Devolução total", fmtPct((hlPct || 0) + (pdvPct || 0)), "HL% + PDV%", true],
        ["Valor devolvido", `R$ ${fmt(totalValue)}`, "Total financeiro", false]
      ];
      if (E.entregaDevolucoesCards) E.entregaDevolucoesCards.innerHTML = cards.map(([label, value, sub, highlight]) => `<article class="devolucao-kpi-card ${highlight ? "is-highlight" : ""}"><span class="label">${escapeHtml(label)}</span><span class="value">${escapeHtml(value)}</span><span class="sub">${escapeHtml(sub)}</span></article>`).join("");
      const competencia = String(dashboard.competencia || ensureLigaMesFilter() || "");
      if (E.entregaDevolucoesStatus) E.entregaDevolucoesStatus.textContent = activeRows.length ? `${activeRows.length} registros operacionais do 03.02.24 Motorista · competência ${competencia}. Não utiliza metas, expurgos ou pontuação da Liga.` : `Nenhum registro de devoluções para os filtros da competência ${competencia}.`;
      if (!E.entregaDevolucoesDetails) return;
      const filtered = activeRows;
      const metric = ["volume_hl", "valor", "registros"].includes(state.entregaDevolucoesMetric) ? state.entregaDevolucoesMetric : "volume_hl";
      const topN = [5, 8, 10, 15].includes(Number(state.entregaDevolucoesTopN)) ? Number(state.entregaDevolucoesTopN) : 10;
      // A aba Devoluções é operacional e exibe todos os registros, inclusive
      // os expurgados. A exclusão do cálculo ocorre somente na Liga.
      const analysisRows = activeRows;
      const timestamps = analysisRows.map(row => Date.parse(`${dateOf(row)}T00:00:00Z`)).filter(Number.isFinite);
      const latest = timestamps.length ? Math.max(...timestamps) : NaN;
      const chartRows = analysisRows;
      const escape = value => escapeHtml(value === null || value === undefined || value === "" ? "-" : value);
      const body = filtered.map(row => `<tr><td>${escape(formatDate(row.data))}</td><td>${escape(formatDate(row.data_devolucao))}</td><td>${escape(row.filial)}</td><td>${escape(row.motorista || row.cod)}</td><td>${escape(row.nota)}</td><td>${escape(row.cliente_cod)}</td><td>${escape(row.cliente || row.cliente_cod)}</td><td>${escape(row.setor_nome || row.setor)}</td><td>${escape(row.gerente_nome || row.gv)}</td><td>${escape(row.motivo_operacional || row.motivo || row.resp)}</td><td>${escape(row.motivo_responsabilidade)}</td><td class="text-end">${fmt(row.volume_hl)}</td><td class="text-end">${fmt(row.valor)}</td></tr>`).join("");
      const charts = [
        renderEntregaDevolucaoTrend(chartRows, metric),
        renderEntregaDevolucaoChart("Devolução por GV", chartRows, "gerente_nome", topN, false, metric),
        renderEntregaDevolucaoChart("Devolução por motivo", chartRows, "motivo_operacional", topN, false, metric),
        renderEntregaDevolucaoChart("Devolução por setor", chartRows, "setor_nome", topN, false, metric),
        renderEntregaDevolucaoChart("Devolução por responsabilidade", chartRows, "motivo_responsabilidade", topN, false, metric)
      ].join("");
      E.entregaDevolucoesDetails.innerHTML = `<div class="devolucao-insight-head d-flex flex-wrap gap-3 align-items-center justify-content-between mb-3"><div><div class="small text-secondary">Análise operacional independente</div><div class="source-path">Todos os totais, gráficos e tabela seguem os filtros abaixo e usam somente os registros importados.</div></div><div class="input-group input-group-sm" style="max-width:320px"><span class="input-group-text"><i class="bi bi-search"></i></span><input class="form-control entrega-devolucoes-filter" value="${escapeHtml(state.entregaDevolucoesFilter || "")}" placeholder="Filtrar registros"></div></div><div class="devolucao-analysis-toolbar mb-3"><div><label class="form-label" for="entregaDevolucoesBranch">Filial</label><select id="entregaDevolucoesBranch" class="form-select form-select-sm entrega-devolucoes-control"><option value="" ${!branch ? "selected" : ""}>Todas as filiais</option><option value="PATOS" ${branch === "PATOS" ? "selected" : ""}>Patos</option><option value="SUME" ${branch === "SUME" ? "selected" : ""}>Sumé</option></select></div><div><label class="form-label" for="entregaDevolucoesDate">Dia da devolução</label><input type="date" id="entregaDevolucoesDate" class="form-control form-control-sm entrega-devolucoes-control" value="${escapeHtml(returnDate)}"></div><div><label class="form-label" for="entregaDevolucoesMetric">Métrica dos gráficos</label><select id="entregaDevolucoesMetric" class="form-select form-select-sm entrega-devolucoes-control"><option value="volume_hl" ${metric === "volume_hl" ? "selected" : ""}>Volume (HL)</option><option value="valor" ${metric === "valor" ? "selected" : ""}>Valor (R$)</option><option value="registros" ${metric === "registros" ? "selected" : ""}>Registros</option></select></div><div><label class="form-label" for="entregaDevolucoesPeriod">Período</label><select id="entregaDevolucoesPeriod" class="form-select form-select-sm entrega-devolucoes-control"><option value="all" ${period === "all" ? "selected" : ""}>Todo o período</option><option value="7" ${period === "7" ? "selected" : ""}>Últimos 7 dias</option><option value="30" ${period === "30" ? "selected" : ""}>Últimos 30 dias</option></select></div><div><label class="form-label" for="entregaDevolucoesTopN">Categorias exibidas</label><select id="entregaDevolucoesTopN" class="form-select form-select-sm entrega-devolucoes-control"><option value="5" ${topN === 5 ? "selected" : ""}>Top 5</option><option value="8" ${topN === 8 ? "selected" : ""}>Top 8</option><option value="10" ${topN === 10 ? "selected" : ""}>Top 10</option><option value="15" ${topN === 15 ? "selected" : ""}>Top 15</option></select></div><button type="button" class="btn btn-outline-primary btn-sm entrega-devolucoes-print"><i class="bi bi-file-earmark-pdf me-1"></i>Gerar PDF</button><div class="devolucao-analysis-note flex-grow-1">${chartRows.length} registro(s) no recorte visual.</div></div><div class="devolucao-dashboard-grid mb-3">${charts}</div><details class="devolucao-table-wrap"><summary><i class="bi bi-table me-2"></i>Ver registros detalhados (${filtered.length})</summary><div class="table-scroll"><table class="table table-sm table-hover align-middle mb-0"><thead><tr><th>Data</th><th>Data devolução</th><th>Revenda</th><th>Motorista</th><th>Nota</th><th>Código do cliente</th><th>Cliente</th><th>Setor</th><th>Gerente</th><th>Motivo</th><th>Responsabilidade</th><th class="text-end">Volume (HL)</th><th class="text-end">Valor</th></tr></thead><tbody>${body || '<tr><td colspan="13" class="text-center text-secondary py-4">Nenhum registro para este filtro.</td></tr>'}</tbody></table></div></details>`;
      const toolbar = E.entregaDevolucoesDetails.querySelector(".devolucao-analysis-toolbar");
      if (toolbar) {
        const control = document.createElement("div");
        control.innerHTML = `<label class="form-label" for="entregaDevolucoesResponsibility">Responsabilidade</label><select id="entregaDevolucoesResponsibility" class="form-select form-select-sm entrega-devolucoes-control"><option value="">Todas as responsabilidades</option>${responsibilityOptions.map(option => `<option value="${escapeHtml(option)}" ${option === responsibility ? "selected" : ""}>${escapeHtml(option)}</option>`).join("")}</select>`;
        toolbar.insertBefore(control, toolbar.children[1] || null);
      }
    }

    function renderIndicadores(payload = {}) {
      const allBranches = Array.isArray(payload.branches) ? payload.branches : [];
      const fmtNumber = value => Number(value || 0).toLocaleString("pt-BR", { maximumFractionDigits: 2 });
      const fmtPercent = value => `${Number(value || 0).toLocaleString("pt-BR", { maximumFractionDigits: 2 })}%`;
      // Metas da aba Metas, por operação. Sem meta cadastrada o card não compara.
      const targetsOf = item => {
        const meta = entregaMetaDaOperacao(item.filial || item.puxada);
        return { occupation: meta?.ocupacao_meta_pct ?? null, boxes: meta?.caixas_viagem_meta ?? null };
      };
      const selectedBranch = String(E.entregaIndicadoresFilial?.value || "").toUpperCase();
      const selectedSituation = String(E.entregaIndicadoresSituacao?.value || "");
      const matchesBranch = item => !selectedBranch || String(item.filial || "").toUpperCase().includes(selectedBranch);
      const withinGoal = item => {
        const target = targetsOf(item);
        return (target.occupation === null || Number(item.metrics?.ocupacao || 0) >= target.occupation)
          && (target.boxes === null || Number(item.metrics?.caixas_por_viagem || 0) >= target.boxes);
      };
      const branches = allBranches.filter(item => matchesBranch(item) && (!selectedSituation || (selectedSituation === "meta" ? withinGoal(item) : !withinGoal(item))));
      const filterNote = selectedBranch || selectedSituation ? ` · ${branches.length} no filtro` : "";
      if (E.entregaIndicadoresStatus) E.entregaIndicadoresStatus.textContent = allBranches.length ? `${payload.competencia || ""} · ${allBranches.length} operação(ões)${filterNote} · última importação ${payload.summary && payload.summary.stored_at || ""}` : ((payload.warnings || ["Nenhum lote importado."])[0]);
      const progress = (value, target, max = 100) => Math.max(0, Math.min(100, Number(value || 0) / Math.max(Number(target || 1), 1) * max));
      const goalBadge = (value, target, unit = "") => {
        if (target === null || target === undefined) return '<span class="badge rounded-pill text-bg-secondary" title="Cadastre na subaba Metas">Sem meta</span>';
        const ok = Number(value || 0) >= Number(target || 0);
        const delta = Number(value || 0) - Number(target || 0);
        return `<span class="badge rounded-pill ${ok ? "text-bg-success" : "text-bg-warning"}">${ok ? "Dentro da meta" : "Fora da meta"}</span><small class="text-${ok ? "success" : "warning"}">${delta >= 0 ? "+" : ""}${fmtNumber(delta)}${unit}</small>`;
      };
      if (E.entregaIndicadoresCards) E.entregaIndicadoresCards.innerHTML = branches.map(item => {
        const occupation = Number(item.metrics && item.metrics.ocupacao || 0);
        const boxes = Number(item.metrics && item.metrics.caixas_por_viagem || 0);
        const { occupation: targetOccupation, boxes: targetBoxes } = targetsOf(item);
        return `<article class="metric-card bi-efficiency-card" style="display:flex;flex-direction:column;align-items:stretch;gap:.75rem;padding:1rem"><div class="d-flex justify-content-between align-items-start gap-3"><strong>Eficiência do carregamento</strong><span class="text-secondary small text-end">${escapeHtml(item.filial || item.puxada)} · Acumulado do relatório</span></div><div class="bi-metric-grid" style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem"><div class="bi-metric"><div class="bi-metric-title d-flex justify-content-between align-items-start gap-2"><span>Ocupação da frota</span><span class="text-end">${goalBadge(occupation, targetOccupation, " p.p.")}</span></div><div class="fs-2 fw-bold bi-metric-value">${fmtNumber(occupation)}%</div><small>${targetOccupation === null ? "Sem meta cadastrada" : `Meta ≥ ${fmtNumber(targetOccupation)}%`}</small><div class="progress mt-2" style="height:8px"><div class="progress-bar ${targetOccupation === null ? "bg-secondary" : occupation >= targetOccupation ? "bg-success" : "bg-warning"}" style="width:${progress(occupation, 100)}%"></div></div><small class="text-secondary">Capacidade ocupada pela frota fixa</small></div><div class="bi-metric"><div class="bi-metric-title d-flex justify-content-between align-items-start gap-2"><span>Caixas por viagem FF</span><span class="text-end">${goalBadge(boxes, targetBoxes, " cx")}</span></div><div class="fs-2 fw-bold bi-metric-value">${fmtNumber(boxes)} <small class="fs-6">CX</small></div><small>${targetBoxes === null ? "Sem meta cadastrada" : `Meta ≥ ${fmtNumber(targetBoxes)} CX`}</small><div class="progress mt-2" style="height:8px"><div class="progress-bar ${targetBoxes === null ? "bg-secondary" : boxes >= targetBoxes ? "bg-success" : "bg-warning"}" style="width:${progress(boxes, targetBoxes ?? boxes)}%"></div></div><small class="text-secondary">Volume médio por viagem de frota fixa</small></div></div></article>`;
      }).join("") || '<article class="metric-card" style="display:flex;flex-direction:column;align-items:flex-start;gap:.25rem"><span>17.06 · Indicadores BI</span><b class="text-warning">Pendente</b><small>O lote SQL ainda não foi importado. Use Atualizar após a carga automática.</small></article><article class="metric-card" style="display:flex;flex-direction:column;align-items:flex-start;gap:.25rem"><span>Operações esperadas</span><b>Patos · Sumé</b><small>Aguardando caixas por viagem e ocupação.</small></article>';
      if (E.entregaIndicadoresBody) E.entregaIndicadoresBody.innerHTML = branches.map(item => `<tr><td>${escapeHtml(item.filial || "-")}</td><td>${escapeHtml(item.puxada || "-")}</td><td class="text-end">${fmtNumber(item.metrics && item.metrics.caixas_por_viagem)}</td><td class="text-end">${fmtPercent(item.metrics && item.metrics.ocupacao)}</td></tr>`).join("") || '<tr><td colspan="4" class="text-center text-secondary py-4">Nenhum lote 17.06 importado ainda.</td></tr>';
    }

    function opsDuration(minutes, { signed = false } = {}) {
      if (minutes === null || minutes === undefined || !Number.isFinite(Number(minutes))) return "—";
      const value = Math.round(Number(minutes));
      const abs = Math.abs(value);
      const text = `${String(Math.floor(abs / 60)).padStart(2, "0")}:${String(abs % 60).padStart(2, "0")}`;
      if (!signed || value === 0) return text;
      return `${value > 0 ? "+" : "−"}${text}`;
    }

    function opsChip(text, tone, label) {
      return `<span class="ops-chip ${tone}" title="${escapeHtml(label)}" aria-label="${escapeHtml(`${text} · ${label}`)}">${escapeHtml(text)}</span>`;
    }

    function opsJustificationCell(row, tipo) {
      const isOccupation = tipo === "ocupacao";
      const key = String((isOccupation ? row.ocupacao_justificativa_id : row.justificativa_id) || "");
      const current = (isOccupation ? row.ocupacao_justificativa : row.justificativa) || {};
      const status = current.updated_by
        ? `<small class="text-secondary">${escapeHtml(current.updated_by)} · ${escapeHtml(formatDateTime(current.updated_at) || current.updated_at || "")}</small>`
        : '<small class="text-warning fw-semibold">Pendente</small>';
      return `<td class="ops-just grp-start"><div class="input-group input-group-sm"><input type="text" class="form-control jornada-mapa-justificativa" maxlength="5000" data-version="${escapeHtml(current.version || "")}" value="${escapeHtml(current.text || "")}" placeholder="${isOccupation ? "Por que a ocupação ficou assim?" : "Justifique este mapa..."}" aria-label="Justificativa do mapa ${escapeHtml(row.mapa || "")}" title="${escapeHtml(current.text || "")}"><button type="button" class="btn btn-outline-primary jornada-mapa-salvar" data-key="${escapeHtml(key)}" data-tipo="${isOccupation ? "ocupacao" : "jornada"}" title="Salvar (Enter)"><i class="bi bi-check2"></i><span class="visually-hidden">Salvar</span></button></div>${status}</td>`;
    }

    function opsMetricCards(cards) {
      return cards.map(([label, value, note]) => `<article class="metric-card" style="display:flex;flex-direction:column;align-items:flex-start;gap:.25rem"><span>${escapeHtml(label)}</span><b>${escapeHtml(value)}</b><small>${escapeHtml(note)}</small></article>`).join("");
    }

    function opsDay(value) {
      const text = String(value || "");
      const match = text.match(/^(\d{4})-(\d{2})-(\d{2})/);
      return match ? `${match[3]}/${match[2]}` : (formatDate(text) || text || "-");
    }

    function opsBranch(value) {
      const text = String(value || "").toUpperCase();
      return text === "SUME" ? "Sumé" : text === "PATOS" ? "Patos" : (value || "-");
    }

    function opsNoPeriodo(row, de, ate) {
      // row.data vem como AAAA-MM-DD; os campos De/Até usam o mesmo formato.
      const day = String(row.data || "").slice(0, 10);
      return (!de || day >= de) && (!ate || day <= ate);
    }

    function renderJornadaMapas(payload = {}) {
      const allRows = Array.isArray(payload.rows) ? payload.rows : [];
      const branch = String(E.entregaJornadaMapasFilial?.value || "").toUpperCase();
      const justification = String(E.entregaJornadaMapasJustificativa?.value || "");
      const returns = String(E.entregaJornadaMapasDevolucao?.value || "");
      const order = String(E.entregaJornadaMapasOrdem?.value || "data");
      const de = String(E.entregaJornadaMapasDe?.value || "");
      const ate = String(E.entregaJornadaMapasAte?.value || "");
      const query = String(E.entregaJornadaMapasBusca?.value || "").trim().toLocaleLowerCase("pt-BR");
      const rows = allRows.filter(row => {
        const hasReturn = Number(row.devolucao_caixas || 0) > 0;
        const text = [row.data, row.filial, row.mapa, row.placa, row.rota, row.motorista].join(" ").toLocaleLowerCase("pt-BR");
        return (!branch || String(row.filial || "").toUpperCase() === branch)
          && opsNoPeriodo(row, de, ate)
          && (!justification || (justification === "justificada" ? Boolean(row.justificada) : !row.justificada))
          && (!returns || (returns === "com" ? hasReturn : !hasReturn))
          && (!query || text.includes(query));
      });
      const sortValue = { jornada: row => row.jornada_min, dif: row => row.dif_jornada_min, devolucao: row => row.devolucao_caixas }[order];
      if (sortValue) rows.sort((a, b) => (Number(sortValue(b)) || -Infinity) - (Number(sortValue(a)) || -Infinity));
      const fmtNumber = value => Number(value || 0).toLocaleString("pt-BR", { maximumFractionDigits: 2 });
      const withJourney = rows.filter(row => Number.isFinite(Number(row.jornada_min)) && row.jornada_min !== null);
      const averageJourney = withJourney.length ? withJourney.reduce((total, row) => total + Number(row.jornada_min), 0) / withJourney.length : null;
      const critical = withJourney.filter(row => Number(row.jornada_min) > OPS_JORNADA_CRITICA_MIN).length;
      const returned = rows.reduce((total, row) => total + Number(row.devolucao_caixas || 0), 0);
      const withReturn = rows.filter(row => Number(row.devolucao_caixas || 0) > 0).length;
      const pending = rows.filter(row => !row.justificada).length;
      if (E.entregaJornadaMapasStatus) E.entregaJornadaMapasStatus.textContent = rows.length
        ? `${payload.competencia || ""} · ${rows.length} mapa(s) no filtro · 03.11.49.02 + 03.08.05`
        : ((payload.warnings || ["Nenhum mapa para os filtros selecionados."])[0]);
      if (E.entregaJornadaMapasCards) E.entregaJornadaMapasCards.innerHTML = opsMetricCards([
        ["Mapas", fmtNumber(rows.length), `${fmtNumber(withJourney.length)} com horário da 03.08.05`],
        ["Jornada média", opsDuration(averageJourney), `${fmtNumber(critical)} mapa(s) acima de 15h`],
        ["Devolução", `${fmtNumber(returned)} CX`, `${fmtNumber(withReturn)} mapa(s) com caixas retornadas`],
        ["Justificativas pendentes", fmtNumber(pending), "preenchimento manual"],
      ]);
      if (!E.entregaJornadaMapasBody) return;
      E.entregaJornadaMapasBody.innerHTML = rows.map(row => {
        const journey = row.jornada_min;
        const hasJourney = journey !== null && journey !== undefined;
        const journeyTone = !hasJourney ? "neutral" : journey > OPS_JORNADA_CRITICA_MIN ? "bad" : journey > OPS_JORNADA_ATENCAO_MIN ? "warn" : "ok";
        const journeyLabel = { bad: "Jornada acima de 15h", warn: "Jornada entre 12h e 15h", ok: "Jornada até 12h", neutral: "Sem horário na 03.08.05" }[journeyTone];
        const diff = row.dif_jornada_min;
        const hasDiff = diff !== null && diff !== undefined;
        const diffTone = !hasDiff ? "neutral" : diff > OPS_DIF_CRITICA_MIN ? "bad" : diff > 0 ? "warn" : "ok";
        const diffLabel = !hasDiff ? "Sem tempo previsto" : diff > 0 ? "Acima do previsto" : "Dentro do previsto";
        const internal = row.tempo_interno_min;
        const hasInternal = internal !== null && internal !== undefined;
        const internalTone = !hasInternal ? "neutral" : internal > OPS_INTERNO_CRITICO_MIN ? "bad" : internal > OPS_INTERNO_ATENCAO_MIN ? "warn" : "ok";
        const internalLabel = { bad: "Tempo interno acima de 2h", warn: "Tempo interno entre 1h30 e 2h", ok: "Tempo interno até 1h30", neutral: "Sem tempo interno" }[internalTone];
        const boxes = Number(row.devolucao_caixas || 0);
        const returnCell = row.devolucao_caixas === null || row.devolucao_caixas === undefined
          ? '<span class="text-secondary">—</span>'
          : boxes > 0 ? opsChip(`${fmtNumber(boxes)} CX`, "warn", "Caixas retornadas") : '<span class="text-secondary">0</span>';
        const missing030805 = row.tem_030805 ? "" : ' <i class="bi bi-exclamation-triangle text-warning" title="Mapa sem a 03.08.05: sem horários e sem devolução"></i><span class="visually-hidden">sem 03.08.05</span>';
        const time = value => value ? escapeHtml(value) : '<span class="text-secondary">—</span>';
        return `<tr>
          <td class="fw-semibold">${escapeHtml(opsBranch(row.filial))}</td>
          <td>${escapeHtml(opsDay(row.data))}</td>
          <td class="mono">${escapeHtml(row.mapa || "-")}${missing030805}</td>
          <td class="mono fw-semibold">${escapeHtml(row.placa || "-")}</td>
          <td class="ops-wrap">${escapeHtml(row.rota || "-")}</td>
          <td class="text-end">${row.peso_kg === null || row.peso_kg === undefined ? "—" : escapeHtml(fmtNumber(row.peso_kg))}</td>
          <td class="text-end">${row.entregas === null || row.entregas === undefined ? "—" : escapeHtml(fmtNumber(row.entregas))}</td>
          <td class="text-center grp-start">${time(row.inicio_jornada)}</td>
          <td class="text-center">${time(row.hora_entrada)}</td>
          <td class="text-center">${time(row.hora_final)}</td>
          <td class="text-center grp-start">${hasJourney ? opsChip(opsDuration(journey), journeyTone, journeyLabel) : '<span class="text-secondary">—</span>'}</td>
          <td class="text-center">${escapeHtml(opsDuration(row.prevista_min))}</td>
          <td class="text-center">${hasDiff ? opsChip(opsDuration(diff, { signed: true }), diffTone, diffLabel) : '<span class="text-secondary">—</span>'}</td>
          <td class="text-center">${hasInternal ? opsChip(opsDuration(internal), internalTone, internalLabel) : '<span class="text-secondary">—</span>'}</td>
          <td class="text-end grp-start">${returnCell}</td>
          ${opsJustificationCell(row, "jornada")}
        </tr>`;
      }).join("") || '<tr><td colspan="16" class="text-center text-secondary py-4">Nenhum mapa para os filtros selecionados.</td></tr>';
      renderOcupacaoVeiculos(payload);
    }

    function renderOcupacaoVeiculos(payload = {}) {
      const branch = String(E.entregaOcupacaoVeiculosFilial?.value || "").toUpperCase();
      const comparison = String(E.entregaOcupacaoVeiculosComparacao?.value || "maior_igual");
      const threshold = Number(E.entregaOcupacaoVeiculosValor?.value || 0);
      const justification = String(E.entregaOcupacaoVeiculosJustificativa?.value || "");
      const de = String(E.entregaOcupacaoVeiculosDe?.value || "");
      const ate = String(E.entregaOcupacaoVeiculosAte?.value || "");
      const order = String(E.entregaOcupacaoVeiculosOrdem?.value || "data");
      const query = String(E.entregaOcupacaoVeiculosBusca?.value || "").trim().toLocaleLowerCase("pt-BR");
      const matches = value => ({ maior: value > threshold, maior_igual: value >= threshold, menor: value < threshold, menor_igual: value <= threshold, igual: Math.abs(value - threshold) < .005 }[comparison] ?? true);
      // Ocupação por pallets (03.02.37 com itens ÷ capacidade do caminhão); sem itens, o peso da 03.08.05.
      const occupationOf = row => row.ocupacao_pallets_pct !== null && row.ocupacao_pallets_pct !== undefined ? Number(row.ocupacao_pallets_pct) : (row.ocupacao_percentual !== null && row.ocupacao_percentual !== undefined ? Number(row.ocupacao_percentual) : null);
      const rows = (Array.isArray(payload.vehicles) ? payload.vehicles : []).filter(row => {
        const occupation = occupationOf(row);
        const text = [row.placa, row.mapa, row.rota, row.data, row.filial, row.caminhao_descricao].join(" ").toLocaleLowerCase("pt-BR");
        return (!branch || String(row.filial || "").toUpperCase() === branch)
          && opsNoPeriodo(row, de, ate)
          && (occupation === null || matches(occupation))
          && (!justification || (justification === "justificada" ? Boolean(row.ocupacao_justificada) : !row.ocupacao_justificada))
          && (!query || text.includes(query));
      });
      // Pior → melhor: menor ocupação primeiro; carros sem ocupação calculada vão para o fim.
      const ascending = { ocupacao: occupationOf, pallets: row => (row.pallets === null || row.pallets === undefined ? null : Number(row.pallets)) }[order];
      if (ascending) rows.sort((a, b) => (ascending(a) ?? Infinity) - (ascending(b) ?? Infinity));
      const fmt = value => Number(value || 0).toLocaleString("pt-BR", { maximumFractionDigits: 2 });
      const toneOf = row => {
        const occupation = row.ocupacao_pallets_pct;
        const meta = row.meta_ocupacao_pct;
        if (occupation === null || occupation === undefined || !meta) return "neutral";
        return occupation >= meta ? "ok" : occupation >= meta - 10 ? "warn" : "bad";
      };
      const withPallets = rows.filter(row => row.pallets !== null && row.pallets !== undefined && Number(row.pallets) > 0);
      const withOccupation = rows.filter(row => row.ocupacao_pallets_pct !== null && row.ocupacao_pallets_pct !== undefined);
      const below = withOccupation.filter(row => row.meta_ocupacao_pct && Number(row.ocupacao_pallets_pct) < Number(row.meta_ocupacao_pct));
      const averagePallets = withPallets.length ? withPallets.reduce((total, row) => total + Number(row.pallets), 0) / withPallets.length : null;
      const averageOccupation = withOccupation.length ? withOccupation.reduce((total, row) => total + Number(row.ocupacao_pallets_pct), 0) / withOccupation.length : null;
      const metas = [...new Map(rows.filter(row => row.meta_ocupacao_pct).map(row => [String(row.filial || "").toUpperCase(), row.meta_ocupacao_pct])).entries()];
      const avisos = Array.isArray(payload.ocupacao_avisos) ? payload.ocupacao_avisos : [];
      if (E.entregaOcupacaoVeiculosStatus) E.entregaOcupacaoVeiculosStatus.textContent = rows.length
        ? `${rows.length} mapa(s)/veículo(s) no filtro · pallets da 03.02.37 + 01.11${avisos.length ? ` · ${avisos.join(" ")}` : ""}`
        : (avisos[0] || "Nenhum veículo atende aos filtros de ocupação.");
      if (E.entregaOcupacaoVeiculosCards) E.entregaOcupacaoVeiculosCards.innerHTML = opsMetricCards([
        ["Pallets por carro", averagePallets === null ? "—" : fmt(averagePallets), withPallets.length ? `média de ${fmt(withPallets.length)} mapa(s) com itens` : "aguardando a 03.02.37 com itens"],
        ["Ocupação média", averageOccupation === null ? "—" : `${fmt(averageOccupation)}%`, metas.length ? `meta ${metas.map(([filial, meta]) => `${opsBranch(filial)} ${fmt(meta)}%`).join(" · ")}` : "cadastre a meta na aba Caminhões"],
        ["Abaixo da meta", fmt(below.length), withOccupation.length ? `de ${fmt(withOccupation.length)} carro(s) com ocupação em pallets` : "aguardando a 03.02.37 com itens"],
        ["Justificativas pendentes", fmt(below.filter(row => !row.ocupacao_justificada).length), "entre os abaixo da meta"],
      ]);
      if (E.entregaOcupacaoVeiculosLegenda) E.entregaOcupacaoVeiculosLegenda.innerHTML = `<span>Ocupação:</span><span class="ops-chip ok">na meta ou acima</span><span class="ops-chip warn">até 10 p.p. abaixo</span><span class="ops-chip bad">mais de 10 p.p. abaixo</span><span class="ops-chip neutral">sem capacidade ou sem itens</span>`;
      if (!E.entregaOcupacaoVeiculosBody) return;
      E.entregaOcupacaoVeiculosBody.innerHTML = rows.map(row => {
        const hasPallets = row.pallets !== null && row.pallets !== undefined;
        const hasCapacity = Boolean(row.capacidade_pallets);
        const tone = toneOf(row);
        const occupation = row.ocupacao_pallets_pct;
        const meta = row.meta_ocupacao_pct;
        const label = tone === "neutral"
          ? (!hasPallets ? "Mapa sem itens na 03.02.37" : !hasCapacity ? "Caminhão sem capacidade cadastrada" : "Operação sem meta cadastrada")
          : tone === "ok" ? `Na meta (${fmt(meta)}%)` : `Abaixo da meta (${fmt(meta)}%)`;
        let occupationCell;
        if (occupation !== null && occupation !== undefined) {
          const bar = Math.max(0, Math.min(Number(occupation), 100));
          const marker = meta ? `<span class="ops-occ-meta" style="left:${Math.min(Number(meta), 100)}%" title="Meta ${escapeHtml(fmt(meta))}%"></span>` : "";
          occupationCell = `<div class="ops-occ"><div class="ops-occ-bar" aria-hidden="true"><span class="${tone}" style="width:${bar}%"></span>${marker}</div>${opsChip(`${fmt(occupation)}%`, tone, label)}</div>`;
        } else if (hasPallets && !hasCapacity) {
          occupationCell = `<span class="text-warning small" title="Cadastre a placa na aba Caminhões"><i class="bi bi-exclamation-triangle me-1"></i>Caminhão sem cadastro</span>`;
        } else {
          const weight = row.ocupacao_percentual;
          occupationCell = weight === null || weight === undefined ? '<span class="text-secondary">—</span>' : `<span class="text-secondary small" title="Mapa sem itens na 03.02.37: ocupação por peso da 03.08.05">${escapeHtml(fmt(weight))}% <span class="ops-chip neutral">peso</span></span>`;
        }
        const truck = row.caminhao_descricao ? `<div class="text-secondary small">${escapeHtml(row.caminhao_descricao)}</div>` : "";
        return `<tr>
          <td class="fw-semibold">${escapeHtml(opsBranch(row.filial))}</td>
          <td>${escapeHtml(opsDay(row.data))}</td>
          <td class="mono fw-semibold">${escapeHtml(row.placa || "-")}${truck}</td>
          <td class="mono">${escapeHtml(row.mapa || "-")}</td>
          <td class="ops-wrap">${escapeHtml(row.rota || "-")}</td>
          <td class="text-end grp-start fw-semibold">${hasPallets ? escapeHtml(fmt(row.pallets)) : '<span class="text-secondary">—</span>'}</td>
          <td class="text-end">${hasCapacity ? escapeHtml(fmt(row.capacidade_pallets)) : '<span class="text-secondary">—</span>'}</td>
          <td class="grp-start">${occupationCell}</td>
          ${opsJustificationCell(row, "ocupacao")}
        </tr>`;
      }).join("") || '<tr><td colspan="9" class="text-center text-secondary py-4">Nenhum veículo atende aos filtros de ocupação.</td></tr>';
    }

    function entregaFrotaOperacoes() {
      const names = (Array.isArray(state.entregaFrota?.operacoes) ? state.entregaFrota.operacoes : []).map(name => String(name || "").trim().toUpperCase()).filter(Boolean);
      return names.length ? names : ["PATOS", "SUME"];
    }

    function entregaFrotaPlacasSemCadastro(operation) {
      const registered = new Set((state.entregaFrota?.caminhoes || []).filter(item => String(item.filial || "").toUpperCase() === operation).map(item => String(item.placa || "").toUpperCase()));
      const seen = new Map();
      (Array.isArray(state.ligaJornadaMapas?.vehicles) ? state.ligaJornadaMapas.vehicles : []).forEach(row => {
        const placa = String(row.placa || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
        if (String(row.filial || "").toUpperCase() !== operation || !placa || registered.has(placa)) return;
        seen.set(placa, (seen.get(placa) || 0) + 1);
      });
      return [...seen.entries()].sort((a, b) => b[1] - a[1]);
    }

    function renderEntregaFrota() {
      if (!E.entregaFrotaDetails) return;
      const operations = entregaFrotaOperacoes();
      if (!state.entregaFrotaOperation || !operations.includes(state.entregaFrotaOperation)) state.entregaFrotaOperation = operations[0];
      const operation = state.entregaFrotaOperation;
      const trucks = (state.entregaFrota?.caminhoes || []).filter(item => String(item.filial || "").toUpperCase() === operation);
      const missing = entregaFrotaPlacasSemCadastro(operation);
      const rows = trucks.map(item => `<tr>
          <td><input class="form-control form-control-sm mono frota-placa" value="${escapeHtml(item.placa || "")}" placeholder="ABC1D23" maxlength="8" aria-label="Placa"></td>
          <td><input class="form-control form-control-sm frota-descricao" value="${escapeHtml(item.descricao || "")}" placeholder="Toco, truck, carreta..." maxlength="80" aria-label="Descrição"></td>
          <td style="max-width:150px"><div class="input-group input-group-sm"><input class="form-control text-end frota-capacidade" type="number" min="0.5" max="100" step="0.5" value="${escapeHtml(item.capacidade_pallets ?? "")}" aria-label="Capacidade em pallets"><span class="input-group-text">pallets</span></div></td>
          <td class="text-center"><input class="form-check-input frota-ativo" type="checkbox" ${item.ativo === false ? "" : "checked"} aria-label="Caminhão ativo"></td>
          <td class="text-end"><button type="button" class="btn btn-outline-danger btn-sm frota-remover" title="Remover caminhão"><i class="bi bi-trash"></i><span class="visually-hidden">Remover</span></button></td>
        </tr>`).join("");
      const missingHtml = missing.length
        ? `<div class="ops-legend mt-2"><span>Placas da competência sem cadastro:</span>${missing.slice(0, 24).map(([placa, mapas]) => `<button type="button" class="btn btn-outline-secondary btn-sm py-0 frota-adicionar-placa" data-placa="${escapeHtml(placa)}" title="${mapas} mapa(s) na competência"><i class="bi bi-plus"></i> ${escapeHtml(placa)}</button>`).join("")}</div>`
        : "";
      const updated = state.entregaFrota?.updated_by ? `Última alteração: ${escapeHtml(state.entregaFrota.updated_by)} · ${escapeHtml(formatDateTime(state.entregaFrota.updated_at) || state.entregaFrota.updated_at || "")}` : "";
      E.entregaFrotaDetails.innerHTML = `
        <div class="d-flex flex-wrap gap-3 align-items-end mb-3">
          <div style="min-width:220px"><label class="form-label small mb-1" for="entregaFrotaOperation">Operação</label><select class="form-select form-select-sm" id="entregaFrotaOperation">${operations.map(name => `<option value="${escapeHtml(name)}" ${name === operation ? "selected" : ""}>${escapeHtml(opsBranch(name))}</option>`).join("")}</select></div>
          <div class="form-text mb-1">Ocupação do carro = pallets do mapa ÷ capacidade em pallets do caminhão. A meta fica na aba Metas.</div>
        </div>
        <div class="d-flex justify-content-between align-items-center mb-2"><h3 class="h6 mb-0">Caminhões de ${escapeHtml(opsBranch(operation))} <span class="text-secondary fw-normal">(${trucks.length})</span></h3><button type="button" class="btn btn-outline-primary btn-sm frota-adicionar"><i class="bi bi-plus-lg me-1"></i>Adicionar caminhão</button></div>
        <div class="table-scroll"><table class="table table-sm align-middle mb-0 ops-table"><thead><tr><th style="width:150px">Placa</th><th>Descrição</th><th style="width:170px">Capacidade</th><th class="text-center" style="width:70px">Ativo</th><th style="width:60px"></th></tr></thead><tbody id="entregaFrotaBody">${rows || '<tr><td colspan="5" class="text-secondary py-3">Nenhum caminhão cadastrado nesta operação.</td></tr>'}</tbody></table></div>
        ${missingHtml}
        <div class="form-text mt-2">${updated}</div>`;
    }

    function readEntregaFrotaOperacao() {
      // Lê o que está na tela para a operação aberta e mantém as demais como estão no estado.
      const operation = state.entregaFrotaOperation;
      if (!operation || !E.entregaFrotaDetails?.querySelector("#entregaFrotaBody")) return;
      const trucks = [...E.entregaFrotaDetails.querySelectorAll("#entregaFrotaBody tr")].filter(row => row.querySelector(".frota-placa")).map(row => ({
        filial: operation,
        placa: String(row.querySelector(".frota-placa")?.value || "").trim().toUpperCase(),
        descricao: String(row.querySelector(".frota-descricao")?.value || "").trim(),
        capacidade_pallets: String(row.querySelector(".frota-capacidade")?.value || "").trim(),
        ativo: Boolean(row.querySelector(".frota-ativo")?.checked),
      }));
      const others = list => (Array.isArray(list) ? list : []).filter(item => String(item.filial || "").toUpperCase() !== operation);
      state.entregaFrota = {
        ...(state.entregaFrota || {}),
        caminhoes: [...others(state.entregaFrota?.caminhoes), ...trucks],
      };
    }

    async function syncEntregaFrota() {
      state.entregaFrota = await req(CONFIG.endpoints.ligaEntrega.frota, { timeoutMs: 30000 }) || { caminhoes: [], metas: [], operacoes: [] };
      renderEntregaFrota();
    }

    async function saveEntregaFrota() {
      const button = E.entregaFrotaSaveBtn;
      readEntregaFrotaOperacao();
      if (button) button.disabled = true;
      try {
        const payload = {
          caminhoes: (state.entregaFrota?.caminhoes || []).filter(item => String(item.placa || "").trim() || String(item.capacidade_pallets || "").trim()),
          metas: state.entregaFrota?.metas || [],
        };
        state.entregaFrota = await req(CONFIG.endpoints.ligaEntrega.frota, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }) || state.entregaFrota;
        renderEntregaFrota();
        addLog("Caminhões da entrega salvos.", "ok");
        syncJornadaMapas({ silent: true });
      } catch (err) {
        addLog(`Falha ao salvar caminhões: ${err.message}`, "err");
      } finally {
        if (button) button.disabled = false;
      }
    }

    function entregaSemAcento(value) {
      return String(value || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase();
    }

    function entregaMetaDaOperacao(operacao) {
      // Aceita "PATOS", "3 - PATOS" ou "Sumé": a meta é cadastrada pelo nome da operação.
      const text = entregaSemAcento(operacao);
      return (state.entregaFrota?.metas || []).find(item => {
        const name = entregaSemAcento(item.filial);
        return name && (text === name || text.includes(name));
      }) || null;
    }

    function renderEntregaMetas() {
      if (!E.entregaMetasDetails) return;
      const metas = state.entregaFrota?.metas || [];
      const fmt = value => value === null || value === undefined || value === "" ? "" : escapeHtml(value);
      const rows = entregaFrotaOperacoes().map(operation => {
        const meta = metas.find(item => String(item.filial || "").toUpperCase() === operation) || {};
        return `<tr data-filial="${escapeHtml(operation)}">
          <td class="fw-semibold">${escapeHtml(opsBranch(operation))}</td>
          <td style="max-width:200px"><div class="input-group input-group-sm"><input class="form-control text-end meta-ocupacao" type="number" min="0.01" max="200" step="0.01" value="${fmt(meta.ocupacao_meta_pct)}" placeholder="Ex.: 65,76" aria-label="Meta de ocupação de ${escapeHtml(opsBranch(operation))}"><span class="input-group-text">%</span></div></td>
          <td style="max-width:220px"><div class="input-group input-group-sm"><input class="form-control text-end meta-caixas" type="number" min="0.01" step="0.01" value="${fmt(meta.caixas_viagem_meta)}" placeholder="Ex.: 285,69" aria-label="Meta de caixas por viagem de ${escapeHtml(opsBranch(operation))}"><span class="input-group-text">CX</span></div></td>
        </tr>`;
      }).join("");
      const updated = state.entregaFrota?.updated_by ? `Última alteração: ${escapeHtml(state.entregaFrota.updated_by)} · ${escapeHtml(formatDateTime(state.entregaFrota.updated_at) || state.entregaFrota.updated_at || "")}` : "";
      E.entregaMetasDetails.innerHTML = `
        <div class="table-scroll"><table class="table table-sm align-middle mb-0 ops-table"><thead><tr><th style="width:200px">Operação</th><th>Ocupação mínima</th><th>Caixas por viagem</th></tr></thead><tbody id="entregaMetasBody">${rows}</tbody></table></div>
        <div class="form-text mt-2">Ocupação: usada na Ocupação por veículo (pallets ÷ capacidade do caminhão) e no card de eficiência da 17.06. Caixas por viagem: card de eficiência da 17.06. Deixe em branco a meta que a operação não acompanha.</div>
        <div class="form-text">${updated}</div>`;
    }

    function readEntregaMetas() {
      const rows = [...(E.entregaMetasDetails?.querySelectorAll("#entregaMetasBody tr") || [])];
      return rows.map(row => ({
        filial: row.dataset.filial || "",
        ocupacao_meta_pct: String(row.querySelector(".meta-ocupacao")?.value || "").trim(),
        caixas_viagem_meta: String(row.querySelector(".meta-caixas")?.value || "").trim(),
      })).filter(item => item.ocupacao_meta_pct || item.caixas_viagem_meta);
    }

    async function saveEntregaMetas() {
      const button = E.entregaMetasSaveBtn;
      if (button) button.disabled = true;
      try {
        const payload = { caminhoes: state.entregaFrota?.caminhoes || [], metas: readEntregaMetas() };
        state.entregaFrota = await req(CONFIG.endpoints.ligaEntrega.frota, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }) || state.entregaFrota;
        renderEntregaMetas();
        addLog("Metas da entrega salvas.", "ok");
        renderIndicadores(state.ligaIndicadores || {});
        syncJornadaMapas({ silent: true });
      } catch (err) {
        addLog(`Falha ao salvar metas: ${err.message}`, "err");
      } finally {
        if (button) button.disabled = false;
      }
    }

    async function syncJornadaMapas({ silent = true } = {}) {
      if (!hasPanelAuth()) return;
      if (E.entregaJornadaMapasRefreshBtn) E.entregaJornadaMapasRefreshBtn.disabled = true;
      try {
        const competencia = ensureLigaMesFilter();
        const query = competencia ? `?competencia=${encodeURIComponent(competencia)}` : "";
        state.ligaJornadaMapas = await req(`${CONFIG.endpoints.ligaEntrega.jornadaMapas}${query}`, { timeoutMs: 30000 }) || {};
        renderJornadaMapas(state.ligaJornadaMapas);
        if (!silent) addLog("Jornada por mapa atualizada.", "ok");
      } catch (err) {
        if (E.entregaJornadaMapasStatus) E.entregaJornadaMapasStatus.textContent = `Falha ao carregar jornada por mapa: ${err.message}`;
        if (!silent) addLog(`Falha ao carregar jornada por mapa: ${err.message}`, "err");
      } finally {
        if (E.entregaJornadaMapasRefreshBtn) E.entregaJornadaMapasRefreshBtn.disabled = false;
      }
    }

    async function saveJornadaMapaJustificativa(button) {
      const key = String(button?.dataset?.key || "");
      const tipo = button?.dataset?.tipo === "ocupacao" ? "ocupacao" : "jornada";
      const input = button?.closest(".ops-just")?.querySelector(".jornada-mapa-justificativa");
      const texto = String(input?.value || "").trim();
      if (!key || !input || !texto) { addLog("Informe a justificativa antes de salvar.", "err"); return; }
      button.disabled = true;
      try {
        const competencia = ensureLigaMesFilter();
        await req(`${CONFIG.endpoints.ligaEntrega.jornadaMapas}/${encodeURIComponent(key)}/justificativa`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ competencia, texto, tipo, version: input.dataset.version || "" }) });
        addLog(tipo === "ocupacao" ? "Justificativa de ocupação salva." : "Justificativa de jornada salva.", "ok");
        await syncJornadaMapas({ silent: true });
      } catch (err) { addLog(err.message || "Não foi possível salvar a justificativa.", "err"); }
      finally { button.disabled = false; }
    }

    async function syncIndicadores({ silent = true } = {}) {
      if (!hasPanelAuth()) return;
      if (E.entregaIndicadoresRefreshBtn) E.entregaIndicadoresRefreshBtn.disabled = true;
      try {
        const competencia = ensureLigaMesFilter();
        const monthQuery = competencia ? `?competencia=${encodeURIComponent(competencia)}` : "";
        state.ligaIndicadores = await req(`${CONFIG.endpoints.ligaEntrega.indicadores}${monthQuery}`, { timeoutMs: 30000 }) || {};
        renderIndicadores(state.ligaIndicadores);
        if (!silent) addLog("Indicadores BI atualizados.", "ok");
      } catch (err) {
        if (E.entregaIndicadoresStatus) E.entregaIndicadoresStatus.textContent = `Falha ao carregar indicadores: ${err.message}`;
        if (!silent) addLog(`Falha ao carregar indicadores: ${err.message}`, "err");
      } finally {
        if (E.entregaIndicadoresRefreshBtn) E.entregaIndicadoresRefreshBtn.disabled = false;
      }
    }

    function renderMapasMensais(payload = {}) {
      const rows = Array.isArray(payload.rows) ? payload.rows : [];
      const summary = payload.summary || {};
      if (E.entregaMapasMensaisStatus) E.entregaMapasMensaisStatus.textContent = rows.length ? `${payload.competencia || ""} · ${summary.mapas || 0} mapa(s) · ${summary.cidades || 0} cidade(s)` : ((payload.warnings || ["Nenhum lote mensal importado."])[0]);
      if (E.entregaMapasMensaisCards) E.entregaMapasMensaisCards.innerHTML = `<article class="metric-card" style="display:flex;flex-direction:column;align-items:flex-start;gap:.25rem"><span>Mapas</span><b>${Number(summary.mapas || 0).toLocaleString("pt-BR")}</b><small>lote mensal 03.11.49.02</small></article><article class="metric-card" style="display:flex;flex-direction:column;align-items:flex-start;gap:.25rem"><span>Cidades</span><b>${Number(summary.cidades || 0).toLocaleString("pt-BR")}</b><small>cidades vinculadas aos mapas</small></article>${rows.length ? "" : '<article class="metric-card" style="display:flex;flex-direction:column;align-items:flex-start;gap:.25rem"><span>Atualização</span><b class="text-warning">Pendente</b><small>Aguardando o lote mensal no SQL.</small></article>'}`;
      if (E.entregaMapasMensaisBody) E.entregaMapasMensaisBody.innerHTML = rows.map(row => `<tr><td>${escapeHtml(row.filial || "-")}</td><td>${escapeHtml(row.mapa || "-")}</td><td>${escapeHtml(row.cidade || "-")}</td><td>${escapeHtml(formatDate(row.data) || row.data || "-")}</td></tr>`).join("") || '<tr><td colspan="4" class="text-center text-secondary py-4">Nenhum lote mensal importado ainda.</td></tr>';
    }

    async function syncMapasMensais({ silent = true } = {}) {
      if (!hasPanelAuth()) return;
      if (E.entregaMapasMensaisRefreshBtn) E.entregaMapasMensaisRefreshBtn.disabled = true;
      try {
        const competencia = ensureLigaMesFilter();
        const monthQuery = competencia ? `?competencia=${encodeURIComponent(competencia)}` : "";
        state.ligaMapasMensais = await req(`${CONFIG.endpoints.ligaEntrega.mapasMensais}${monthQuery}`, { timeoutMs: 30000 }) || {};
        renderMapasMensais(state.ligaMapasMensais);
        if (!silent) addLog("Cidades por mapa mensais atualizadas.", "ok");
      } catch (err) {
        if (E.entregaMapasMensaisStatus) E.entregaMapasMensaisStatus.textContent = `Falha ao carregar cidades por mapa: ${err.message}`;
        if (!silent) addLog(`Falha ao carregar cidades por mapa: ${err.message}`, "err");
      } finally {
        if (E.entregaMapasMensaisRefreshBtn) E.entregaMapasMensaisRefreshBtn.disabled = false;
      }
    }

    function renderMapasOperacionais(payload = {}) {
      const days = Array.isArray(payload.days) ? payload.days : [];
      const number = value => Number(value || 0).toLocaleString("pt-BR");
      const allDates = days.map(day => String(day.data || "")).filter(Boolean).sort();
      const minimumDate = allDates[0] || "";
      const maximumDate = allDates[allDates.length - 1] || "";
      const competencia = String(payload.competencia || "");
      if (state.ligaMapasOperacionaisSelectedCompetencia !== competencia) {
        state.ligaMapasOperacionaisSelectedCompetencia = competencia;
        state.ligaMapasOperacionaisSelectedDays = maximumDate ? [maximumDate] : [];
      }
      const selectedDays = new Set((Array.isArray(state.ligaMapasOperacionaisSelectedDays) ? state.ligaMapasOperacionaisSelectedDays : []).filter(day => allDates.includes(day)));
      state.ligaMapasOperacionaisSelectedDays = [...selectedDays];
      if (E.entregaMapasOperacionaisDias) E.entregaMapasOperacionaisDias.innerHTML = allDates.slice().reverse().map(day => `<button class="fechamento-day-option ${selectedDays.has(day) ? "is-selected" : ""}" type="button" data-fechamento-dia="${escapeHtml(day)}" aria-pressed="${selectedDays.has(day)}">${escapeHtml(formatDate(day) || day)}</button>`).join("") || '<span class="text-secondary small">Nenhum dia disponível.</span>';
      [E.entregaMapasOperacionaisDataInicio, E.entregaMapasOperacionaisDataFim].forEach(input => {
        if (!input) return;
        input.min = minimumDate;
        input.max = maximumDate;
        if (input.value && (input.value < minimumDate || input.value > maximumDate)) input.value = "";
      });
      let startDate = String(E.entregaMapasOperacionaisDataInicio?.value || "");
      let endDate = String(E.entregaMapasOperacionaisDataFim?.value || "");
      if (startDate && endDate && startDate > endDate) [startDate, endDate] = [endDate, startDate];
      const branch = String(E.entregaMapasOperacionaisFilial?.value || "").toUpperCase();
      const situation = String(E.entregaMapasOperacionaisSituacao?.value || "");
      const alertFilter = String(E.entregaMapasOperacionaisAlertas?.value || "");
      const search = String(E.entregaMapasOperacionaisBusca?.value || "").trim().toUpperCase();
      const matches = map => {
        const hasAlert = Array.isArray(map.alertas) && map.alertas.length > 0;
        if (branch && String(map.filial || "").toUpperCase() !== branch) return false;
        const financeiroFechado = map.fechamento_financeiro && map.fechamento_financeiro !== "-";
        if (situation === "aberto" && financeiroFechado) return false;
        if (situation === "pendente" && financeiroFechado) return false;
        if (situation === "fechado" && !financeiroFechado) return false;
        if (situation === "retornou" && map.status_operacional !== "Retornou") return false;
        if (alertFilter === "com_alerta" && !hasAlert) return false;
        if (alertFilter === "sem_alerta" && hasAlert) return false;
        if (alertFilter === "ti_total" && !map.ti_total_acima_30min) return false;
        if (alertFilter === "rota_48h" && !map.em_rota_acima_2dias) return false;
        if (alertFilter === "pulou_mpd" && !map.pulou_mpd) return false;
        return !search || `${map.mapa || ""} ${map.placa || ""}`.toUpperCase().includes(search);
      };
      const visibleDays = days
        .filter(day => selectedDays.has(day.data) && (!startDate || day.data >= startDate) && (!endDate || day.data <= endDate))
        .map(day => ({ ...day, maps: (Array.isArray(day.maps) ? day.maps : []).filter(matches) }))
        .filter(day => day.maps.length > 0);
      const maps = visibleDays.flatMap(day => Array.isArray(day.maps) ? day.maps : []);
      state.ligaMapasOperacionaisVisibleMaps = maps;
      const summary = {
        mapas: maps.length,
        dias: visibleDays.length,
        retornados: maps.filter(map => map.status_operacional === "Retornou").length,
        fisico_fechado: maps.filter(map => map.fechamento_fisico && map.fechamento_fisico !== "-").length,
        financeiro_fechado: maps.filter(map => map.fechamento_financeiro && map.fechamento_financeiro !== "-").length,
        pendentes: maps.filter(map => !map.fechamento_financeiro || map.fechamento_financeiro === "-").length,
        ti_total_acima_30min: maps.filter(map => map.ti_total_acima_30min).length,
        em_rota_acima_2dias: maps.filter(map => map.em_rota_acima_2dias).length,
        pulou_mpd: maps.filter(map => map.pulou_mpd).length,
      };
      const filterCount = [branch, situation, alertFilter, search].filter(Boolean).length;
      const range = startDate || endDate ? ` · ${startDate ? formatDate(startDate) : "início"} até ${endDate ? formatDate(endDate) : "fim"}` : "";
      if (E.entregaMapasOperacionaisStatus) E.entregaMapasOperacionaisStatus.textContent = days.length
        ? `${payload.competencia || ""} · ${summary.dias} dia(s) · ${summary.mapas} mapa(s)${range}${filterCount ? ` · ${filterCount} filtro(s) ativo(s)` : ""}`
        : ((payload.warnings || ["Nenhuma 03.11.20 importada para este mês."])[0]);
      if (E.entregaMapasOperacionaisCards) E.entregaMapasOperacionaisCards.innerHTML = [
        ["Mapas no recorte", summary.mapas, `${summary.dias || 0} dia(s) operacional(is)`, ""],
        ["Retornaram", summary.retornados, "com entrada registrada", ""],
        ["Fechamento físico", summary.fisico_fechado, "físico registrado", ""],
        ["Pendentes", summary.pendentes, "sem fechamento completo", summary.pendentes ? "is-warning" : ""],
        ["TI total > 30 min", summary.ti_total_acima_30min, "entrada até financeiro", summary.ti_total_acima_30min ? "is-warning" : ""],
        ["Rota > 48 h", summary.em_rota_acima_2dias, "saída sem retorno em até 48 h", summary.em_rota_acima_2dias ? "is-danger" : ""],
        ["Pulou MPD", summary.pulou_mpd, "fechado financeiramente sem MPD", summary.pulou_mpd ? "is-warning" : ""],
      ].map(([label, value, note, tone]) => `<article class="fechamento-kpi ${tone}"><span class="label">${label}</span><b class="value">${number(value)}</b><small class="note">${note}</small></article>`).join("");
      if (!E.entregaMapasOperacionaisDetails) return;
      const badge = map => map.status_tone === "ok" ? "text-bg-success" : map.status_tone === "warning" ? "text-bg-warning" : "text-bg-secondary";
      E.entregaMapasOperacionaisDetails.innerHTML = visibleDays.map((day, index) => {
        const dailyMaps = day.maps || [];
        const daily = {
          mapas: dailyMaps.length,
          retornados: dailyMaps.filter(map => map.status_operacional === "Retornou").length,
          financeiro_fechado: dailyMaps.filter(map => map.fechamento_financeiro && map.fechamento_financeiro !== "-").length,
          pendentes: dailyMaps.filter(map => !map.fechamento_financeiro || map.fechamento_financeiro === "-").length,
        };
        const compactCell = (items) => `<div class="fechamento-stack">${items.map(([label, value]) => {
          const shown = value || "-";
          return `<div class="fechamento-stack-line"><span class="fechamento-stack-label">${escapeHtml(label)}</span><span class="fechamento-stack-value ${shown === "-" ? "is-muted" : ""}">${escapeHtml(shown)}</span></div>`;
        }).join("")}</div>`;
        const rows = (day.maps || []).map(map => {
          const alerts = Array.isArray(map.alertas) ? map.alertas : [];
          const alertText = alerts.length ? `<div>${alerts.map(alert => `<span class="fechamento-alert">${escapeHtml(alert)}</span>`).join("")}</div>` : "";
          return `<tr class="${alerts.length ? "fechamento-row-alert" : ""}"><td>${escapeHtml(map.filial || "-")}</td><td><b>${escapeHtml(map.mapa || "-")}</b></td><td>${escapeHtml(map.placa || "-")}</td><td>${compactCell([["Carregado", map.carregado], ["Saída", map.saida]])}</td><td>${compactCell([["Entrada", map.entrada], ["Físico", map.fechamento_fisico], ["Financeiro", map.fechamento_financeiro]])}</td><td>${compactCell([["Rota", map.tempo_rota], ["TI total", map.tempo_interno_total]])}</td><td class="fechamento-status-cell"><span class="badge ${badge(map)}">${escapeHtml(map.status_operacional || "-")}</span><div class="small text-secondary mt-1">${escapeHtml(map.status_fechamento || "-")}</div>${alertText}</td></tr>`;
        }).join("");
        return `<details class="fechamento-day" ${index === 0 ? "open" : ""}><summary><span class="fechamento-day-date"><i class="bi bi-calendar3 me-2 text-primary"></i>${escapeHtml(formatDate(day.data) || day.data || "-")}</span><span class="fechamento-day-summary">${number(daily.mapas)} mapas · ${number(daily.retornados)} retornaram · ${number(daily.financeiro_fechado)} fechados · ${number(daily.pendentes)} pendentes <i class="bi bi-chevron-down ms-2"></i></span></summary><div class="table-scroll fechamento-table-scroll"><table class="table table-sm table-hover align-middle mb-0"><thead><tr><th>Filial</th><th>Mapa</th><th>Placa</th><th>Operação</th><th>Retorno e fechamento</th><th>Tempos</th><th>Status e alertas</th></tr></thead><tbody>${rows}</tbody></table></div></details>`;
      }).join("") || '<div class="text-center text-secondary py-4">Nenhum mapa no período selecionado.</div>';
    }

    async function syncMapasOperacionais({ silent = true } = {}) {
      if (!hasPanelAuth()) return;
      if (E.entregaMapasOperacionaisRefreshBtn) E.entregaMapasOperacionaisRefreshBtn.disabled = true;
      try {
        const competencia = ensureLigaMesFilter();
        const monthQuery = competencia ? `?competencia=${encodeURIComponent(competencia)}` : "";
        state.ligaMapasOperacionais = await req(`${CONFIG.endpoints.ligaEntrega.mapasOperacionais}${monthQuery}`, { timeoutMs: 30000 }) || {};
        renderMapasOperacionais(state.ligaMapasOperacionais);
        if (!silent) addLog("Acompanhamento da 03.11.20 atualizado.", "ok");
      } catch (err) {
        if (E.entregaMapasOperacionaisStatus) E.entregaMapasOperacionaisStatus.textContent = `Falha ao carregar acompanhamento dos mapas: ${err.message}`;
        if (!silent) addLog(`Falha ao carregar acompanhamento dos mapas: ${err.message}`, "err");
      } finally {
        if (E.entregaMapasOperacionaisRefreshBtn) E.entregaMapasOperacionaisRefreshBtn.disabled = false;
      }
    }

    async function downloadMapasOperacionaisPdf() {
      const maps = Array.isArray(state.ligaMapasOperacionaisVisibleMaps) ? state.ligaMapasOperacionaisVisibleMaps : [];
      if (!maps.length) {
        addLog("Selecione ao menos um dia com mapas para gerar o PDF.", "warn");
        return;
      }
      updateTokens();
      const button = E.entregaMapasOperacionaisPdfBtn;
      const original = button?.innerHTML || "";
      if (button) { button.disabled = true; button.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Gerando PDF'; }
      try {
        const headers = { "Content-Type": "application/json" };
        if (state.tokens.api) headers["x-api-token"] = state.tokens.api;
        if (state.tokens.admin) headers["x-admin-token"] = state.tokens.admin;
        const response = await fetch(`${CONFIG.api}${CONFIG.endpoints.ligaEntrega.mapasOperacionaisPdf}`, {
          method: "POST", credentials: "same-origin", headers,
          body: JSON.stringify({ competencia: state.ligaMapasOperacionais?.competencia || "", maps }),
        });
        if (!response.ok) {
          const payload = await response.json().catch(() => null);
          throw new Error(payload?.detail || `HTTP ${response.status}`);
        }
        const blob = await response.blob();
        const name = (response.headers.get("content-disposition") || "").match(/filename="?([^";]+)"?/i)?.[1] || "fechamento-mapas.pdf";
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a"); anchor.href = url; anchor.download = name; document.body.appendChild(anchor); anchor.click(); anchor.remove(); URL.revokeObjectURL(url);
        addLog(`PDF do fechamento baixado: ${maps.length} mapa(s).`, "ok");
      } catch (err) {
        addLog(`Falha ao gerar PDF do fechamento: ${err.message}`, "err");
      } finally {
        if (button) { button.disabled = false; button.innerHTML = original; }
      }
    }

    function setEntregaModule(module = "liga") {
      const indicadores = module === "indicadores";
      const fechamento = module === "fechamento";
      const devolucoes = module === "devolucoes";
      const devolucoesCadastros = module === "devolucoes-cadastros";
      const frota = module === "frota";
      const metas = module === "metas";
      if (E.entregaLigaModule) E.entregaLigaModule.classList.toggle("d-none", indicadores || fechamento || devolucoes || devolucoesCadastros || frota || metas);
      if (E.entregaFrotaModule) E.entregaFrotaModule.classList.toggle("d-none", !frota);
      if (E.entregaFrotaModuleTab) E.entregaFrotaModuleTab.className = `btn ${frota ? "btn-primary" : "btn-outline-primary"} entrega-module-tab`;
      if (E.entregaMetasModule) E.entregaMetasModule.classList.toggle("d-none", !metas);
      if (E.entregaMetasModuleTab) E.entregaMetasModuleTab.className = `btn ${metas ? "btn-primary" : "btn-outline-primary"} entrega-module-tab`;
      if (E.entregaIndicadoresModule) E.entregaIndicadoresModule.classList.toggle("d-none", !indicadores);
      if (E.entregaFechamentoModule) E.entregaFechamentoModule.classList.toggle("d-none", !fechamento);
      if (E.entregaDevolucoesModule) E.entregaDevolucoesModule.classList.toggle("d-none", !devolucoes);
      if (E.entregaDevolucoesCadastrosModule) E.entregaDevolucoesCadastrosModule.classList.toggle("d-none", !devolucoesCadastros);
      if (E.entregaLigaModuleTab) E.entregaLigaModuleTab.className = `btn ${!indicadores && !fechamento && !devolucoes && !devolucoesCadastros && !frota && !metas ? "btn-primary" : "btn-outline-primary"} entrega-module-tab`;
      if (E.entregaIndicadoresModuleTab) E.entregaIndicadoresModuleTab.className = `btn ${indicadores ? "btn-primary" : "btn-outline-primary"} entrega-module-tab`;
      if (E.entregaFechamentoModuleTab) E.entregaFechamentoModuleTab.className = `btn ${fechamento ? "btn-primary" : "btn-outline-primary"} entrega-module-tab`;
      if (E.entregaDevolucoesModuleTab) E.entregaDevolucoesModuleTab.className = `btn ${devolucoes ? "btn-primary" : "btn-outline-primary"} entrega-module-tab`;
      if (E.entregaDevolucoesCadastrosModuleTab) E.entregaDevolucoesCadastrosModuleTab.className = `btn ${devolucoesCadastros ? "btn-primary" : "btn-outline-primary"} entrega-module-tab`;
      if (indicadores) {
        syncIndicadores({ silent: true }); syncJornadaMapas({ silent: true }); syncMapasMensais({ silent: true });
        syncEntregaFrota().then(() => renderIndicadores(state.ligaIndicadores || {})).catch(() => {});
      }
      if (metas) syncEntregaFrota().then(() => renderEntregaMetas()).catch(err => { if (E.entregaMetasDetails) E.entregaMetasDetails.textContent = `Falha ao carregar metas: ${err.message}`; });
      if (fechamento) syncMapasOperacionais({ silent: true });
      if (devolucoes) syncDevolucoesOperacionais({ silent: true });
      if (frota) Promise.all([syncEntregaFrota(), syncJornadaMapas({ silent: true })]).then(() => renderEntregaFrota()).catch(err => { if (E.entregaFrotaDetails) E.entregaFrotaDetails.textContent = `Falha ao carregar caminhões: ${err.message}`; });
      if (devolucoesCadastros) Promise.all([syncDevolucoesOperacionais({ silent: true }), syncDevolucoesCadastros()]).then(() => renderDevolucoesCadastros()).catch(err => { if (E.entregaDevolucoesCadastrosDetails) E.entregaDevolucoesCadastrosDetails.textContent = `Falha ao carregar cadastros: ${err.message}`; });
    }

    function updateLigaEntregaExpurgoForm() {
      const tipo = String(E.entregaLigaExpurgoTipo && E.entregaLigaExpurgoTipo.value || "devolucao");
      const escopo = String(E.entregaLigaExpurgoEscopo && E.entregaLigaExpurgoEscopo.value || "individual");
      const isDevolucao = tipo === "devolucao";
      const equipeInteira = escopo === "equipe";
      if (E.entregaLigaExpurgoAlvoLabel) E.entregaLigaExpurgoAlvoLabel.textContent = isDevolucao ? "Cliente" : "Mapa";
      if (E.entregaLigaExpurgoAlvo) {
        E.entregaLigaExpurgoAlvo.placeholder = isDevolucao ? "Código do cliente" : "Número do mapa";
        E.entregaLigaExpurgoAlvo.required = isDevolucao || !equipeInteira;
        E.entregaLigaExpurgoAlvo.disabled = false;
      }
      if (E.entregaLigaExpurgoHint) E.entregaLigaExpurgoHint.textContent = isDevolucao
        ? (equipeInteira ? "Remove somente a devolução do cliente informado, para motorista e ajudantes vinculados a ela." : "Remove apenas devolução por cliente e data.")
        : (equipeInteira ? "Opcional: informe o mapa para remover o indicador de toda a equipe daquela rota; se vazio, remove todas as rotas da filial nesta data." : "Remove este indicador para motorista e ajudantes da rota; os demais continuam contando.");
    }

    function renderLigaDevolucoesExpurgoCard(dashboard = {}, filterRows = rows => rows) {
      const devolucoes = Array.isArray(dashboard.devolucoes_auxiliares)
        ? dashboard.devolucoes_auxiliares
        : (Array.isArray(dashboard.devolucoes) ? dashboard.devolucoes : []);
      const visible = filterRows(devolucoes);
      const pending = visible.filter(item => !item.excluida).length;
      if (!visible.length) return '<div class="liga-expurgo-pending-card"><b>Devoluções da Liga</b><span class="text-secondary">Nenhuma devolução encontrada para este filtro.</span></div>';
      return `<div class="liga-expurgo-pending-card"><div class="d-flex justify-content-between align-items-center gap-2 mb-2"><b>Devoluções da Liga (${visible.length})</b><span class="text-secondary small">${pending} pendente(s) · expurgadas permanecem visíveis</span></div><div class="liga-expurgo-pending-list">${visible.map(item => `<div class="d-flex justify-content-between align-items-center gap-2 border-top pt-2 mt-2 ${item.excluida ? "opacity-50" : ""}"><span><b>${escapeHtml(item.cliente || item.cliente_cod || "Cliente sem código")}</b> · ${escapeHtml(item.filial || "-")} · ${escapeHtml(formatDate(item.data) || item.data || "-")}<br><span class="text-secondary">NF ${escapeHtml(item.nota || "-")} · ${escapeHtml(item.motivo_operacional || item.motivo || "Motivo não informado")} · ${Number(item.volume_hl || 0).toLocaleString("pt-BR", { maximumFractionDigits: 2 })} HL</span></span>${item.excluida ? '<span class="badge text-bg-secondary">Expurgada</span>' : `<button type="button" class="btn btn-outline-warning btn-sm py-0 liga-expurgo-dev" data-expurgo-data="${escapeHtml(item.data || "")}" data-expurgo-filial="${escapeHtml(item.filial || "")}" data-expurgo-cliente="${escapeHtml(item.cliente_cod || "")}" title="Abrir formulário de expurgo">Expurgar</button>`}</div>`).join("")}</div></div>`;
    }

    function renderLigaEntregaExpurgos() {
      const pendingElement = E.entregaLigaDevolucoesExpurgoList;
      const dashboard = state.ligaEntregaDashboard || {};
      const devolucoes = Array.isArray(dashboard.devolucoes_auxiliares)
        ? dashboard.devolucoes_auxiliares
        : (Array.isArray(dashboard.devolucoes) ? dashboard.devolucoes : []);
      const pending = devolucoes;
      if (pendingElement) {
        const activeCount = pending.filter(item => !item.excluida).length;
        pendingElement.innerHTML = pending.length
          ? `<div class="small fw-bold mb-1">Devoluções da Liga (${pending.length}) · ${activeCount} pendente(s)</div><div class="liga-expurgo-pending-list">${pending.map(item => `<div class="d-flex justify-content-between align-items-center gap-2 border-top pt-2 mt-2 ${item.excluida ? "opacity-50" : ""}"><span><b>${escapeHtml(item.cliente || item.cliente_cod || "Cliente sem código")}</b> · ${escapeHtml(item.filial || "-")} · ${escapeHtml(formatDate(item.data) || item.data || "-")}<br><span class="text-secondary">NF ${escapeHtml(item.nota || "-")} · ${escapeHtml(item.motivo_operacional || item.motivo || "Motivo não informado")} · ${Number(item.volume_hl || 0).toLocaleString("pt-BR", { maximumFractionDigits: 2 })} HL</span></span>${item.excluida ? '<span class="badge text-bg-secondary">Expurgada</span>' : `<button type="button" class="btn btn-outline-warning btn-sm py-0 liga-expurgo-dev" data-expurgo-data="${escapeHtml(item.data || "")}" data-expurgo-filial="${escapeHtml(item.filial || "")}" data-expurgo-cliente="${escapeHtml(item.cliente_cod || "")}" title="Abrir formulário de expurgo">Expurgar</button>`}</div>`).join("")}</div>`
          : '<span class="text-secondary">Nenhuma devolução carregada na Liga.</span>';
      }
      if (!E.entregaLigaExpurgosList) return;
      const items = Array.isArray(state.ligaEntregaExpurgos) ? state.ligaEntregaExpurgos : [];
      if (!items.length) {
        E.entregaLigaExpurgosList.innerHTML = '<div class="small fw-bold mb-1">Expurgos ativos</div><span class="text-secondary">Nenhum expurgo ativo nesta competência.</span>';
        return;
      }
      E.entregaLigaExpurgosList.innerHTML = `<div class="small fw-bold mb-1">Expurgos ativos (${items.length})</div>${items.map(item => {
        const target = item.tipo === "devolucao"
          ? `cliente ${item.cliente || "-"}`
          : item.mapa ? (item.escopo === "equipe" ? `equipe do mapa ${item.mapa}` : `mapa ${item.mapa}`) : "equipe inteira";
        const applied = Number(item.aplicados || 0);
        return `<div class="d-flex justify-content-between gap-2 border-top pt-2 mt-2"><span><b>${escapeHtml(item.tipo || "-")}</b> · ${escapeHtml(item.filial || "-")} · ${escapeHtml(formatDate(item.data) || item.data || "-")} · ${escapeHtml(target)}<br><span class="text-secondary">${escapeHtml(item.motivo || "sem motivo")}</span><br><span class="badge ${applied ? "text-bg-success" : "text-bg-warning"}">${applied ? `${applied} registro(s) expurgado(s)` : "Ainda não encontrou registro"}</span></span><button class="btn btn-outline-danger btn-sm py-0 liga-expurgo-remove" type="button" data-expurgo-id="${escapeHtml(item.id || "")}" title="Remover expurgo"><i class="bi bi-x-lg"></i></button></div>`;
      }).join("")}`;
    }

    async function syncLigaEntregaExpurgos() {
      if (!hasPanelAuth()) return;
      const competencia = String((state.ligaEntregaDashboard || {}).competencia || "");
      if (!competencia) {
        state.ligaEntregaExpurgos = [];
        renderLigaEntregaExpurgos();
        return;
      }
      const query = `?competencia=${encodeURIComponent(competencia)}`;
      const payload = await req(`${CONFIG.endpoints.ligaEntrega.expurgos}${query}`, { timeoutMs: 15000 });
      const calculated = ((state.ligaEntregaDashboard || {}).expurgos || {}).items || [];
      const appliedById = new Map(calculated.map(item => [String(item.id || ""), Number(item.aplicados || 0)]));
      state.ligaEntregaExpurgos = (Array.isArray(payload && payload.items) ? payload.items : []).map(item => ({ ...item, aplicados: appliedById.get(String(item.id || "")) || 0 }));
      renderLigaEntregaExpurgos();
    }

    async function saveLigaEntregaExpurgo(event) {
      event.preventDefault();
      const tipo = String(E.entregaLigaExpurgoTipo && E.entregaLigaExpurgoTipo.value || "");
      const escopo = String(E.entregaLigaExpurgoEscopo && E.entregaLigaExpurgoEscopo.value || "individual");
      const data = String(E.entregaLigaExpurgoData && E.entregaLigaExpurgoData.value || "");
      const competencia = String((state.ligaEntregaDashboard || {}).competencia || data.slice(0, 7));
      const alvo = String(E.entregaLigaExpurgoAlvo && E.entregaLigaExpurgoAlvo.value || "").trim();
      if (!competencia || !data || (tipo === "devolucao" && !alvo) || (escopo === "individual" && !alvo)) throw new Error("Informe data e cliente para devolução, ou mapa para expurgo individual.");
      const payload = { tipo, escopo, competencia, filial: String(E.entregaLigaExpurgoFilial && E.entregaLigaExpurgoFilial.value || ""), data, motivo: String(E.entregaLigaExpurgoMotivo && E.entregaLigaExpurgoMotivo.value || "") };
      if (tipo === "devolucao") payload.cliente = alvo;
      else if (alvo) payload.mapa = alvo;
      await req(CONFIG.endpoints.ligaEntrega.expurgos, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload), timeoutMs: 20000 });
      E.entregaLigaExpurgoAlvo.value = "";
      if (E.entregaLigaExpurgoEscopo) E.entregaLigaExpurgoEscopo.value = "individual";
      E.entregaLigaExpurgoMotivo.value = "";
      updateLigaEntregaExpurgoForm();
      await syncLigaEntregaReports({ silent: false, force: true });
      addLog("Expurgo aplicado e dashboard recalculado.", "ok");
    }

    async function removeLigaEntregaExpurgo(expurgoId) {
      if (!expurgoId) return;
      await req(`${CONFIG.endpoints.ligaEntrega.expurgos}/${encodeURIComponent(expurgoId)}`, { method: "DELETE", timeoutMs: 20000 });
      await syncLigaEntregaReports({ silent: false, force: true });
      addLog("Expurgo removido e dashboard recalculado.", "ok");
    }

    async function saveLigaEntregaTeamChanges() {
      const pending = state.ligaEntregaTeamChanges || {};
      const changes = Object.entries(pending);
      const dashboard = state.ligaEntregaDashboard || {};
      if (!changes.length) return;
      if (!dashboard.competencia) throw new Error("Competência da Liga indisponível para salvar a equipe.");
      await Promise.all(changes.map(([cod, status]) => req(
        `${CONFIG.endpoints.ligaEntrega.equipe}/${encodeURIComponent(cod)}`,
        { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ competencia: dashboard.competencia, status }), timeoutMs: 20000 }
      )));
      state.ligaEntregaTeamChanges = {};
      await syncLigaEntregaReports({ silent: false, force: true });
      addLog(`${changes.length} status da equipe salvo(s).`, "ok");
    }

    async function editLigaEntregaRouteTeam(button) {
      const dashboard = state.ligaEntregaDashboard || {};
      if (!dashboard.competencia) throw new Error("Competência da Liga indisponível.");
      const team = Array.isArray(dashboard.equipe) ? dashboard.equipe : [];
      const drivers = team.filter(item => String(item.funcao || "").toUpperCase().includes("MOTOR"));
      const helpers = team.filter(item => String(item.funcao || "").toUpperCase().includes("AJUD"));
      const normalizeCode = value => { const digits = String(value || "").replace(/\D/g, ""); return digits.replace(/^0+(?=\d)/, ""); };
      const matchesPerson = (item, selected) => {
        const wanted = String(selected || "").trim().toUpperCase();
        return wanted && [item.cod, item.nome].some(value => String(value || "").trim().toUpperCase() === wanted || normalizeCode(value) === normalizeCode(wanted));
      };
      const option = (item, selected) => `<option value="${escapeHtml(normalizeCode(item.cod))}" ${matchesPerson(item, selected) ? "selected" : ""}>${escapeHtml(item.cod || "")} - ${escapeHtml(item.nome || "")}</option>`;
      const blank = `<option value="">— Não informado —</option>`;
      const driverSelect = document.getElementById("ligaRouteTeamDriver");
      const helper1Select = document.getElementById("ligaRouteTeamHelper1");
      const helper2Select = document.getElementById("ligaRouteTeamHelper2");
      const modalEl = document.getElementById("ligaRouteTeamModal");
      if (!driverSelect || !helper1Select || !helper2Select || !modalEl || !window.bootstrap) throw new Error("Modal de equipe da rota indisponível.");
      const atuais = (button.dataset.routeAju || "").split(",").map(value => value.trim()).filter(Boolean);
      driverSelect.innerHTML = blank + drivers.map(item => option(item, button.dataset.routeMot || "")).join("");
      helper1Select.innerHTML = blank + helpers.map(item => option(item, atuais[0])).join("");
      helper2Select.innerHTML = blank + helpers.map(item => option(item, atuais[1])).join("");
      document.getElementById("ligaRouteTeamModalSubtitle").textContent = `Mapa ${button.dataset.routeMapa || "-"} · ${button.dataset.routeData || "-"} · ${button.dataset.routeFilial || "-"}`;
      const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
      const save = document.getElementById("ligaRouteTeamSave");
      save.disabled = false;
      save.onclick = async () => {
        const ajudantes = [helper1Select.value, helper2Select.value].filter(Boolean);
        if (new Set(ajudantes).size !== ajudantes.length) { addLog("Selecione ajudantes diferentes.", "warn"); return; }
        if (!driverSelect.value) { addLog("Selecione o motorista da rota.", "warn"); return; }
        save.disabled = true;
        try {
          await req(CONFIG.endpoints.ligaEntrega.rotaEquipe, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ competencia: dashboard.competencia, data: button.dataset.routeData || "", filial: button.dataset.routeFilial || "", mapa: button.dataset.routeMapa || "", motorista: driverSelect.value, ajudantes }), timeoutMs: 30000 });
          modal.hide();
          await syncLigaEntregaReports({ silent: false, force: true });
          addLog(`Equipe da rota ${button.dataset.routeMapa} atualizada.`, "ok");
        } catch (error) {
          save.disabled = false;
          addLog(`Falha ao atualizar equipe: ${error.message || error}`, "error");
        }
      };
      modal.show();
    }

    async function addLigaRosterCandidate(button) {
      const dashboard = state.ligaEntregaDashboard || {};
      const payload = {
        competencia: dashboard.competencia || "",
        cod: button.dataset.rosterCod || "",
        nome: button.dataset.rosterNome || "",
        filial: button.dataset.rosterFilial || "",
        funcao: button.dataset.rosterFuncao || "",
      };
      if (!payload.competencia || !payload.cod) throw new Error("Colaborador ou competência inválida.");
      button.disabled = true;
      try {
        await req(CONFIG.endpoints.ligaEntrega.equipeCadastro, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload), timeoutMs: 30000 });
        state.ligaEntregaDashboard = null;
        await syncLigaEntregaReports({ silent: false, force: true });
        addLog(`${payload.nome} cadastrado na Liga.`, "ok");
      } catch (error) {
        button.disabled = false;
        throw error;
      }
    }

    async function syncLigaEntregaReports(options = {}) {
      const force = !!(options && options.force);
      if (state.ligaEntregaSyncPromise) {
        if (force) state.ligaEntregaSyncNeedsRefresh = true;
        const result = await state.ligaEntregaSyncPromise;
        if (force && state.ligaEntregaSyncNeedsRefresh) {
          state.ligaEntregaSyncNeedsRefresh = false;
          return syncLigaEntregaReports({ ...options, force: true });
        }
        return result;
      }
      const promise = syncLigaEntregaReportsInternal(options);
      state.ligaEntregaSyncPromise = promise;
      try {
        return await promise;
      } finally {
        if (state.ligaEntregaSyncPromise === promise) state.ligaEntregaSyncPromise = null;
        if (!state.ligaEntregaSyncPromise && !state.ligaEntregaSyncNeedsRefresh) {
          state.ligaEntregaSyncNeedsRefresh = false;
        }
      }
    }

    function ensureLigaMesFilter() {
      const select = E.entregaLigaMes;
      if (!select) return "";
      const now = new Date();
      const year = now.getFullYear();
      const options = LIGA_MESES.map((label, index) => {
        const month = String(index + 1).padStart(2, "0");
        return `<option value="${year}-${month}">${label} ${year}</option>`;
      }).join("");
      if (select.dataset.ligaYear !== String(year)) {
        const previous = select.value;
        select.innerHTML = options;
        select.dataset.ligaYear = String(year);
        const currentCompetencia = `${year}-${String(now.getMonth() + 1).padStart(2, "0")}`;
        // Ao inserir as opções, o navegador escolhe automaticamente a
        // primeira (janeiro). Definimos explicitamente a competência atual
        // quando não há uma escolha anterior válida do usuário.
        select.value = previous && select.querySelector(`option[value="${previous}"]`)
          ? previous
          : currentCompetencia;
      }
      if (!select.value) {
        const target = new Date(year, now.getMonth(), 1);
        select.value = `${target.getFullYear()}-${String(target.getMonth() + 1).padStart(2, "0")}`;
      }
      return String(select.value || "");
    }

    async function syncLigaEntregaReportsInternal({ silent = true, force = false } = {}) {
      if (!hasPanelAuth()) return false;
      if (!force && state.ligaEntregaReports && Array.isArray(state.ligaEntregaReports.items) && state.ligaEntregaDashboard) {
        renderLigaEntregaReports();
        return true;
      }
      if (E.entregaLigaReportsRefreshBtn) E.entregaLigaReportsRefreshBtn.disabled = true;
      try {
        const reportsPayload = await req(CONFIG.endpoints.ligaEntrega.reports, { timeoutMs: 30000 });
        state.ligaEntregaReports = reportsPayload || { items: [], summary: {} };
        renderLigaEntregaReports();
        if (!silent) addLog("Relatórios da Liga atualizados.", "ok");
      } catch (err) {
        if (E.entregaLigaReportsSummary) E.entregaLigaReportsSummary.textContent = `Falha ao carregar relatórios da Liga: ${err.message}`;
        if (!silent) addLog(`Falha ao carregar relatórios da Liga: ${err.message}`, "err");
        if (E.entregaLigaReportsRefreshBtn) E.entregaLigaReportsRefreshBtn.disabled = false;
        return false;
      }

      try {
        const competencia = ensureLigaMesFilter();
        // A leitura normal usa exclusivamente o snapshot SQL. O bootstrap
        // de arquivos fica reservado ao script administrativo de reconstrução.
        const bootstrap = "";
        const monthQuery = competencia ? `?competencia=${encodeURIComponent(competencia)}` : "";
        state.ligaEntregaDashboard = await req(`${CONFIG.endpoints.ligaEntrega.dashboard}${monthQuery}${bootstrap}`, { timeoutMs: force ? 180000 : 60000 }) || {};
      } catch (err) {
        state.ligaEntregaDashboard = {
          ok: false,
          summary: {},
          warnings: [err && err.message ? err.message : "Falha ao calcular dashboard."]
        };
        if (!silent) addLog(`Dashboard da Liga não calculou agora: ${err.message}`, "warn");
      } finally {
        renderLigaEntregaReports();
        try { await syncLigaEntregaExpurgos(); } catch (err) { if (!silent) addLog(`Falha ao listar expurgos: ${err.message}`, "warn"); }
        const latestRoute = Array.isArray((state.ligaEntregaDashboard || {}).rotas) ? state.ligaEntregaDashboard.rotas.slice(-1)[0] : null;
        if (E.entregaLigaExpurgoData && !E.entregaLigaExpurgoData.value && latestRoute && latestRoute.data) E.entregaLigaExpurgoData.value = String(latestRoute.data);
        if (E.entregaLigaReportsRefreshBtn) E.entregaLigaReportsRefreshBtn.disabled = false;
      }
      return true;
    }

    function ensureGiroRecolhaSection() {
      if (document.getElementById("giroRecolhaBody")) return;
      const recolhasSection = E.recolhasContainer ? E.recolhasContainer.closest("section") : null;
      if (!recolhasSection || !recolhasSection.parentElement) return;
      const section = document.createElement("section");
      section.className = "panel-card p-3 mb-3";
      section.innerHTML = `
        <div class="d-flex flex-wrap gap-2 align-items-center justify-content-between mb-2">
          <div>
            <h2 class="h6 fw-bold mb-1"><i class="bi bi-arrow-repeat me-2 text-primary"></i>Giro abaixo do esperado</h2>
            <div class="form-text">Clientes com vasilhame sem giro suficiente, priorizados por falta de caixas e faturamento médio para apoiar decisoes de recolha.</div>
          </div>
          <div class="d-flex flex-wrap gap-2 align-items-center">
            <span class="pill" id="giroRecolhaCount">Aguardando dados</span>
            <button class="btn btn-outline-primary btn-sm" id="giroRecolhaRefreshBtn"><i class="bi bi-arrow-repeat me-1"></i>Atualizar giro</button>
          </div>
        </div>
        <div class="row g-2 align-items-end mb-3">
          <div class="col-md-3">
            <label class="form-label small fw-semibold mb-1" for="giroRecolhaMinGap">Faltam mínimo de caixas</label>
            <input type="number" min="0" step="1" class="form-control form-control-sm" id="giroRecolhaMinGap" value="1">
          </div>
          <div class="col-md-3">
            <label class="form-label small fw-semibold mb-1" for="giroRecolhaLimit">Limite de clientes</label>
            <input type="number" min="1" max="1000" step="1" class="form-control form-control-sm" id="giroRecolhaLimit" value="200">
          </div>
          <div class="col-md-6">
            <div class="form-text">Use a lista como fila de análise: maior gap primeiro, com faturamento e média por pedido ao lado.</div>
          </div>
        </div>
        <div class="recolha-dashboard-grid mb-3" id="giroRecolhaCards"></div>
        <div class="table-scroll" style="max-height: 430px;">
          <table class="table table-sm table-hover align-middle mb-0">
            <thead>
              <tr class="text-uppercase small text-secondary">
                <th class="ps-3">Cliente</th>
                <th>Giro</th>
                <th>Faltam</th>
                <th>Fat. M-1</th>
                <th>Crédito</th>
                <th class="text-end pe-3">Ação</th>
              </tr>
            </thead>
            <tbody id="giroRecolhaBody">
              <tr><td colspan="6" class="text-center py-3 text-secondary">Carregando oportunidades...</td></tr>
            </tbody>
          </table>
        </div>
      `;
      recolhasSection.parentElement.insertBefore(section, recolhasSection);
      E.giroRecolhaCount = document.getElementById("giroRecolhaCount");
      E.giroRecolhaRefreshBtn = document.getElementById("giroRecolhaRefreshBtn");
      E.giroRecolhaMinGap = document.getElementById("giroRecolhaMinGap");
      E.giroRecolhaLimit = document.getElementById("giroRecolhaLimit");
      E.giroRecolhaCards = document.getElementById("giroRecolhaCards");
      E.giroRecolhaBody = document.getElementById("giroRecolhaBody");
    }

    function emptyGiroRecolhaOptions() {
      return { operations: [], sellers: [], managers: [], cities: [], districts: [], visit_days: [] };
    }

    function normalizeGiroRecolhaValues(values) {
      const rawValues = Array.isArray(values) ? values : String(values || "").split(",");
      const normalized = [];
      const seen = new Set();
      rawValues.forEach(value => {
        const item = String(value || "").trim();
        if (item && !seen.has(item)) {
          normalized.push(item);
          seen.add(item);
        }
      });
      return normalized;
    }

    function selectedGiroRecolhaValues(select) {
      if (!select) return [];
      return Array.from(select.selectedOptions || [])
        .map(option => String(option.value || "").trim())
        .filter(Boolean);
    }

    function currentGiroRecolhaParams() {
      const limit = Number(E.giroRecolhaLimit && E.giroRecolhaLimit.value ? E.giroRecolhaLimit.value : 200);
      const minGap = Number(E.giroRecolhaMinGap && E.giroRecolhaMinGap.value ? E.giroRecolhaMinGap.value : 1);
      const maxRouteSize = Number(E.giroRecolhaMaxRouteSize && E.giroRecolhaMaxRouteSize.value ? E.giroRecolhaMaxRouteSize.value : 12);
      return {
        limit: Number.isFinite(limit) ? Math.max(1, Math.min(1000, Math.trunc(limit))) : 200,
        minGap: Number.isFinite(minGap) ? Math.max(0, minGap) : 1,
        operation: selectedGiroRecolhaValues(E.giroRecolhaOperation),
        city: selectedGiroRecolhaValues(E.giroRecolhaCity),
        district: selectedGiroRecolhaValues(E.giroRecolhaDistrict),
        seller: selectedGiroRecolhaValues(E.giroRecolhaSeller),
        manager: selectedGiroRecolhaValues(E.giroRecolhaManager),
        visitDay: selectedGiroRecolhaValues(E.giroRecolhaVisitDay),
        zeroOnly: E.giroRecolhaZeroOnly ? E.giroRecolhaZeroOnly.checked : false,
        maxRouteSize: Number.isFinite(maxRouteSize) ? Math.max(1, Math.min(50, Math.trunc(maxRouteSize))) : 12
      };
    }

    function appendGiroRecolhaParamValues(query, name, values) {
      normalizeGiroRecolhaValues(values).forEach(value => query.append(name, value));
    }

    function appendGiroRecolhaFilters(query, params, { omit = "" } = {}) {
      if (omit !== "operation") appendGiroRecolhaParamValues(query, "operation", params.operation);
      if (omit !== "city") appendGiroRecolhaParamValues(query, "city", params.city);
      if (omit !== "district") appendGiroRecolhaParamValues(query, "district", params.district);
      if (omit !== "seller") appendGiroRecolhaParamValues(query, "seller", params.seller);
      if (omit !== "manager") appendGiroRecolhaParamValues(query, "manager", params.manager);
      if (omit !== "visitDay") appendGiroRecolhaParamValues(query, "visit_day", params.visitDay);
      if (params.zeroOnly) query.set("zero_only", "1");
    }

    function giroRecolhaQueryString(params) {
      const query = new URLSearchParams();
      query.set("limit", String(params.limit));
      query.set("min_gap", String(params.minGap));
      appendGiroRecolhaFilters(query, params);
      return query.toString();
    }

    function giroRecolhaOptionsQueryString(params, { omit = "" } = {}) {
      const query = new URLSearchParams();
      query.set("min_gap", String(params.minGap));
      appendGiroRecolhaFilters(query, params, { omit });
      return query.toString();
    }

    function giroRecolhaRoutesQueryString(params) {
      const query = new URLSearchParams(giroRecolhaQueryString(params));
      query.set("max_route_size", String(params.maxRouteSize || 12));
      return query.toString();
    }

    function normalizeGiroRecolhaOptionItems(options) {
      const mapped = [];
      const seen = new Set();
      (Array.isArray(options) ? options : []).forEach(item => {
        const value = String(item && item.value || "").trim();
        if (!value || seen.has(value)) return;
        mapped.push({ value, label: cleanDisplayText(item.label || item.value || "") });
        seen.add(value);
      });
      return mapped;
    }

    function giroRecolhaSlicerElements(def) {
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

    function giroRecolhaOptionsForSlicer(def) {
      const slicerOptions = state.giroRecolhaSlicerOptions || {};
      const fallbackOptions = state.giroRecolhaOptions || {};
      const source = Array.isArray(slicerOptions[def.optionKey])
        ? slicerOptions[def.optionKey]
        : fallbackOptions[def.optionKey];
      const mapped = normalizeGiroRecolhaOptionItems(source);
      const values = new Set(mapped.map(item => item.value));
      selectedGiroRecolhaValues(E[def.selectKey]).forEach(value => {
        if (value && !values.has(value)) {
          mapped.unshift({ value, label: cleanDisplayText(value) });
          values.add(value);
        }
      });
      return mapped;
    }

    function syncGiroRecolhaHiddenSelect(def, options, selectedValues) {
      const select = E[def.selectKey];
      if (!select) return [];
      const selected = normalizeGiroRecolhaValues(selectedValues);
      const selectedSet = new Set(selected);
      const optionValues = new Set((options || []).map(item => String(item.value || "")));
      const extra = selected.filter(value => value && !optionValues.has(value)).map(value => ({ value, label: value }));
      select.innerHTML = extra.concat(options || [])
        .map(item => `<option value="${escapeHtml(item.value || "")}">${escapeHtml(item.label || item.value || "")}</option>`)
        .join("");
      Array.from(select.options || []).forEach(option => {
        option.selected = selectedSet.has(String(option.value || ""));
      });
      return selectedGiroRecolhaValues(select);
    }

    function giroRecolhaSlicerSelectedSet(def) {
      return new Set(selectedGiroRecolhaValues(E[def.selectKey]));
    }

    function giroRecolhaSlicerButtonText(def, selectedValues, options) {
      const selected = Array.isArray(selectedValues) ? selectedValues : [];
      if (!selected.length) return def.allText;
      if (selected.length === 1) {
        const match = (options || []).find(item => item.value === selected[0]);
        return cleanDisplayText(match ? match.label : selected[0]);
      }
      return `${selected.length} ${def.selectedText}`;
    }

    function renderGiroRecolhaSlicer(def) {
      const els = giroRecolhaSlicerElements(def);
      const options = giroRecolhaOptionsForSlicer(def);
      const selectedSet = giroRecolhaSlicerSelectedSet(def);
      const search = normalizeTextForSearch(els.search ? els.search.value : "");
      const visibleOptions = options.filter(item => !search || normalizeTextForSearch(item.label || item.value).includes(search));
      if (els.button) {
        els.button.textContent = giroRecolhaSlicerButtonText(def, [...selectedSet], options);
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
            <input class="form-check-input m-0 giro-recolha-slicer-option" type="checkbox" value="${escapeHtml(item.value)}" ${checked ? "checked" : ""}>
            <span>${escapeHtml(item.label || item.value)}</span>
          </label>
        `;
      }).join("");
      els.list.querySelectorAll(".giro-recolha-slicer-option").forEach(input => {
        input.addEventListener("change", event => onGiroRecolhaSlicerCheckboxChange(def, event));
      });
    }

    function clearGiroRecolhaSlicerDependents(def) {
      (def.clears || []).forEach(key => {
        const childDef = GIRO_RECOLHA_SLICER_BY_KEY[key];
        if (childDef) setGiroRecolhaSlicerSelection(childDef, [], { sync: false, clearDependents: false });
      });
    }

    function setGiroRecolhaSlicerSelection(def, values, { sync = true, clearDependents = true } = {}) {
      const options = giroRecolhaOptionsForSlicer(def);
      const selected = syncGiroRecolhaHiddenSelect(def, options, values);
      renderGiroRecolhaSlicer(def);
      if (sync && clearDependents) clearGiroRecolhaSlicerDependents(def);
      if (sync) syncGiroRecolha({ silent: false });
      return selected;
    }

    function onGiroRecolhaSlicerCheckboxChange(def, event) {
      const selectedSet = giroRecolhaSlicerSelectedSet(def);
      const value = String(event.target && event.target.value || "").trim();
      if (!value) return;
      if (event.target.checked) selectedSet.add(value);
      else selectedSet.delete(value);
      setGiroRecolhaSlicerSelection(def, [...selectedSet]);
    }

    function toggleGiroRecolhaSlicerPanel(def, event) {
      if (event) event.stopPropagation();
      const els = giroRecolhaSlicerElements(def);
      if (!els.panel) return;
      const willOpen = els.panel.classList.contains("d-none");
      GIRO_RECOLHA_SLICERS.forEach(item => {
        if (item.key === def.key) return;
        const other = giroRecolhaSlicerElements(item);
        if (other.panel) other.panel.classList.add("d-none");
        if (other.button) other.button.setAttribute("aria-expanded", "false");
      });
      els.panel.classList.toggle("d-none", !willOpen);
      if (els.button) els.button.setAttribute("aria-expanded", willOpen ? "true" : "false");
      if (willOpen) {
        renderGiroRecolhaSlicer(def);
        if (els.search) els.search.focus();
      }
    }

    function closeGiroRecolhaSlicerPanelsOnOutsideClick(event) {
      GIRO_RECOLHA_SLICERS.forEach(def => {
        const els = giroRecolhaSlicerElements(def);
        if (!els.panel || els.panel.classList.contains("d-none")) return;
        if (els.root && els.root.contains(event.target)) return;
        els.panel.classList.add("d-none");
        if (els.button) els.button.setAttribute("aria-expanded", "false");
      });
    }

    function visibleGiroRecolhaSlicerValues(def) {
      const els = giroRecolhaSlicerElements(def);
      const options = giroRecolhaOptionsForSlicer(def);
      const search = normalizeTextForSearch(els.search ? els.search.value : "");
      return options
        .filter(item => !search || normalizeTextForSearch(item.label || item.value).includes(search))
        .map(item => item.value);
    }

    function selectVisibleGiroRecolhaSlicerValues(def, event) {
      if (event) event.stopPropagation();
      const selectedSet = giroRecolhaSlicerSelectedSet(def);
      visibleGiroRecolhaSlicerValues(def).forEach(value => selectedSet.add(value));
      setGiroRecolhaSlicerSelection(def, [...selectedSet]);
    }

    function clearGiroRecolhaSlicerSelection(def, event) {
      if (event) event.stopPropagation();
      setGiroRecolhaSlicerSelection(def, []);
    }

    function setupGiroRecolhaSlicerEvents() {
      GIRO_RECOLHA_SLICERS.forEach(def => {
        const els = giroRecolhaSlicerElements(def);
        if (els.select) {
          els.select.addEventListener("change", () => {
            clearGiroRecolhaSlicerDependents(def);
            syncGiroRecolha({ silent: false });
          });
        }
        if (els.button) els.button.addEventListener("click", event => toggleGiroRecolhaSlicerPanel(def, event));
        if (els.search) els.search.addEventListener("input", () => renderGiroRecolhaSlicer(def));
        if (els.selectAllBtn) els.selectAllBtn.addEventListener("click", event => selectVisibleGiroRecolhaSlicerValues(def, event));
        if (els.clearBtn) els.clearBtn.addEventListener("click", event => clearGiroRecolhaSlicerSelection(def, event));
      });
      document.addEventListener("click", closeGiroRecolhaSlicerPanelsOnOutsideClick);
    }

    function normalizeGiroRecolhaSlicerOptions(payloads, fallbackOptions) {
      const result = emptyGiroRecolhaOptions();
      GIRO_RECOLHA_SLICERS.forEach((def, index) => {
        const payloadOptions = payloads && payloads[index] && payloads[index].options ? payloads[index].options : {};
        const source = Array.isArray(payloadOptions[def.optionKey])
          ? payloadOptions[def.optionKey]
          : (fallbackOptions && fallbackOptions[def.optionKey]);
        result[def.optionKey] = normalizeGiroRecolhaOptionItems(source);
      });
      return result;
    }

    async function loadGiroRecolhaSlicerOptions(params) {
      return Promise.all(GIRO_RECOLHA_SLICERS.map(def => (
        req(`${CONFIG.endpoints.giroRecolha.options}?${giroRecolhaOptionsQueryString(params, { omit: def.key })}`, { timeoutMs: 45000 })
      )));
    }

    function renderGiroRecolhaFilterOptions(previousParams = currentGiroRecolhaParams()) {
      const selected = {};
      GIRO_RECOLHA_SLICERS.forEach(def => {
        selected[def.key] = setGiroRecolhaSlicerSelection(def, previousParams[def.key], { sync: false, clearDependents: false });
      });
      return selected;
    }

    function clearGiroRecolhaFilters() {
      GIRO_RECOLHA_SLICERS.forEach(def => {
        setGiroRecolhaSlicerSelection(def, [], { sync: false, clearDependents: false });
      });
      if (E.giroRecolhaMinGap) E.giroRecolhaMinGap.value = "1";
      if (E.giroRecolhaLimit) E.giroRecolhaLimit.value = "200";
      if (E.giroRecolhaMaxRouteSize) E.giroRecolhaMaxRouteSize.value = "12";
      if (E.giroRecolhaZeroOnly) E.giroRecolhaZeroOnly.checked = false;
      syncGiroRecolha({ silent: false });
    }

    function clearGiroRecolhaRoutes() {
      state.giroRecolhaRoutes = { generated: false, total: 0, summary: {}, routes: [] };
      state.giroRecolhaRouteFilter = { search: "", district: "", minGap: "" };
      state.giroRecolhaBuilder = { activeRouteId: "", search: "" };
      if (E.giroRecolhaRouteSearch) E.giroRecolhaRouteSearch.value = "";
      if (E.giroRecolhaRouteDistrict) E.giroRecolhaRouteDistrict.value = "";
      if (E.giroRecolhaRouteMinGap) E.giroRecolhaRouteMinGap.value = "";
      if (E.giroRecolhaActiveRoute) E.giroRecolhaActiveRoute.value = "";
      if (E.giroRecolhaBlockSearch) E.giroRecolhaBlockSearch.value = "";
      renderGiroRecolhaRoutes();
    }

    function updateGiroRecolhaRouteFilters() {
      state.giroRecolhaRouteFilter = {
        search: E.giroRecolhaRouteSearch ? E.giroRecolhaRouteSearch.value.trim() : "",
        district: E.giroRecolhaRouteDistrict ? E.giroRecolhaRouteDistrict.value.trim() : "",
        minGap: E.giroRecolhaRouteMinGap ? E.giroRecolhaRouteMinGap.value.trim() : ""
      };
      renderGiroRecolhaRoutes();
    }

    function clearGiroRecolhaRouteFilters() {
      state.giroRecolhaRouteFilter = { search: "", district: "", minGap: "" };
      if (E.giroRecolhaRouteSearch) E.giroRecolhaRouteSearch.value = "";
      if (E.giroRecolhaRouteDistrict) E.giroRecolhaRouteDistrict.value = "";
      if (E.giroRecolhaRouteMinGap) E.giroRecolhaRouteMinGap.value = "";
      renderGiroRecolhaRoutes();
    }

    function clampGiroRecolhaRouteHeight(value) {
      const height = Number(value);
      return Number.isFinite(height) ? Math.max(180, Math.min(1400, Math.trunc(height))) : 260;
    }

    function findGiroRecolhaRouteTable(routeId) {
      return Array.from(document.querySelectorAll(".route-table-scroll[data-route-id]"))
        .find(node => String(node.dataset.routeId || "") === String(routeId || ""));
    }

    function setGiroRecolhaRouteTableHeight(routeId, height) {
      const nextHeight = clampGiroRecolhaRouteHeight(height);
      state.giroRecolhaRouteHeights[routeId] = nextHeight;
      const tableWrap = findGiroRecolhaRouteTable(routeId);
      if (tableWrap) tableWrap.style.height = `${nextHeight}px`;
    }

    function renderGiroRecolha() {
      ensureGiroRecolhaSection();
      const payload = state.giroRecolha && typeof state.giroRecolha === "object" ? state.giroRecolha : { total: 0, summary: {}, records: [] };
      const records = Array.isArray(payload.records) ? payload.records : [];
      const summary = payload.summary || {};
      if (E.giroRecolhaCount) {
        E.giroRecolhaCount.textContent = `${formatNumber(records.length)} cliente(s)`;
        E.giroRecolhaCount.className = records.length ? "pill warn" : "pill";
      }
      if (E.giroRecolhaCards) {
        E.giroRecolhaCards.innerHTML = [
          ["Clientes", summary.clientes || records.length, "fora do giro"],
          ["Giro zero", summary.clientes_zero || 0, "com item zerado"],
          ["Faltam total", summary.gap_total || "0", "caixas em falta"],
          ["Maior falta", summary.maior_gap || "0", "cliente mais critico"]
        ].map(([label, value, sub]) => `
          <article class="recolha-dashboard-card">
            <span class="label">${escapeHtml(label)}</span>
            <span class="value">${escapeHtml(String(value))}</span>
            <span class="sub">${escapeHtml(sub)}</span>
          </article>
        `).join("");
      }
      if (!E.giroRecolhaBody) return;
      if (!records.length) {
        E.giroRecolhaBody.innerHTML = '<tr><td colspan="6" class="text-center py-3 text-secondary">Nenhum cliente fora do giro nos filtros atuais.</td></tr>';
        return;
      }
      E.giroRecolhaBody.innerHTML = records.map(record => {
        const command = `recolha ${record.filial || ""} ${record.cod_pdv || ""}`.trim();
        return `
          <tr>
            <td class="ps-3">
              <strong>${escapeHtml(cleanDisplayText(record.nome || "-"))}</strong>
              <div class="small text-secondary">Revenda ${escapeHtml(record.filial || "-")} | NB ${escapeHtml(record.cod_pdv || "-")} | Setor ${escapeHtml(record.setor || "-")}</div>
              <div class="small text-secondary">${escapeHtml(cleanDisplayText([record.cidade, record.bairro || record.status_pdv].filter(Boolean).join(" | ") || "-"))}</div>
            </td>
            <td>${giroStatusBadges(record)}</td>
            <td>
              <strong>${escapeHtml(record.gap_caixas || "0")} cx</strong>
              <div class="small text-secondary">Total ${escapeHtml(record.total_caixas || "0")} | Real ${escapeHtml(record.real_caixas || "0")}</div>
              <div class="small text-secondary">Tipos: ${escapeHtml(giroMissingTypesText(record))}</div>
            </td>
            <td>
              <strong>${escapeHtml(record.media_faturamento_pedido || "R$ 0,00")}</strong>
              <div class="small text-secondary">Fat. M-1 ${escapeHtml(record.faturamento_total || "R$ 0,00")} | Pedidos ${escapeHtml(record.pedidos_total || "0")}</div>
            </td>
            <td>
              <div>${escapeHtml(record.prazo_atual || "-")} | ${escapeHtml(record.cond_pag_atual || "-")}</div>
              <div class="small text-secondary">Atraso ${escapeHtml(record.percentual_pag_atraso || "-")}</div>
            </td>
            <td class="text-end pe-3">
              <button class="btn btn-outline-primary btn-sm" onclick="copyGiroRecolhaCommand('${escapeHtml(command)}')">
                <i class="bi bi-clipboard me-1"></i>Copiar
              </button>
            </td>
          </tr>
        `;
      }).join("");
    }

    function parseGiroRecolhaNumber(value) {
      const cleaned = String(value || "")
        .replace("R$", "")
        .replace(/\./g, "")
        .replace(",", ".")
        .replace(/[^\d.-]/g, "");
      const parsed = Number(cleaned);
      return Number.isFinite(parsed) ? parsed : 0;
    }

    function giroRecolhaPdvKey(item) {
      return `${String(item && item.filial || "").trim()}|${String(item && (item.cod_pdv || item.nb) || "").trim()}`;
    }

    function giroRecolhaRouteItemFromRecord(record, sequence = 1) {
      const filial = String(record && record.filial || "").trim();
      const codPdv = String(record && record.cod_pdv || "").trim();
      return {
        sequence,
        filial,
        cod_pdv: codPdv,
        nome: record && record.nome || "-",
        cidade: record && record.cidade || "",
        bairro: record && record.bairro || "",
        visit_day: record && record.visit_day || "",
        total_caixas: record && record.total_caixas || "0",
        real_caixas: record && record.real_caixas || "0",
        gap_caixas: record && record.gap_caixas || "0",
        gap_litrinho: record && record.gap_litrinho || "0",
        gap_inteira: record && record.gap_inteira || "0",
        gap_litrao: record && record.gap_litrao || "0",
        giro_litrinho: record && record.giro_litrinho || "-",
        giro_inteira: record && record.giro_inteira || "-",
        giro_litrao: record && record.giro_litrao || "-",
        media_faturamento_pedido: record && record.media_faturamento_pedido || "R$ 0,00",
        faturamento_total: record && record.faturamento_total || "R$ 0,00",
        seller: record && (record.seller_code || record.setor || record.seller) || "",
        manager: record && (record.manager_code || record.manager) || "",
        command: `recolha ${filial} ${codPdv}`.trim()
      };
    }

    function sortGiroRecolhaRouteItems(items) {
      return [...(items || [])].sort((a, b) => {
        const bairroCompare = String(a.bairro || "").localeCompare(String(b.bairro || ""), "pt-BR");
        if (bairroCompare) return bairroCompare;
        const gapCompare = parseGiroRecolhaNumber(b.gap_caixas) - parseGiroRecolhaNumber(a.gap_caixas);
        if (gapCompare) return gapCompare;
        const mediaCompare = parseGiroRecolhaNumber(b.media_faturamento_pedido) - parseGiroRecolhaNumber(a.media_faturamento_pedido);
        if (mediaCompare) return mediaCompare;
        return String(a.nome || "").localeCompare(String(b.nome || ""), "pt-BR");
      });
    }

    function recalcGiroRecolhaRoute(route) {
      const items = sortGiroRecolhaRouteItems(Array.isArray(route.items) ? route.items : [])
        .map((item, index) => ({ ...item, sequence: index + 1 }));
      const operations = [...new Set(items.map(item => String(item.filial || item.operation || "").trim()).filter(Boolean))].sort();
      const cities = [...new Set(items.map(item => String(item.cidade || item.city || "").trim()).filter(Boolean))].sort();
      const visitDays = [...new Set(items.map(item => String(item.visit_day || "").trim()).filter(Boolean))].sort();
      const neighborhoods = [...new Set(items.map(item => String(item.bairro || "").trim()).filter(Boolean))];
      const sellers = [...new Set(items.map(item => String(item.seller || "").trim()).filter(Boolean))].sort();
      const managers = [...new Set(items.map(item => String(item.manager || "").trim()).filter(Boolean))].sort();
      const totalGap = items.reduce((sum, item) => sum + parseGiroRecolhaNumber(item.gap_caixas), 0);
      const totalBoxes = items.reduce((sum, item) => sum + parseGiroRecolhaNumber(item.total_caixas), 0);
      return {
        ...route,
        operation: routeGroupLabel(operations, route.operation || "-"),
        operations,
        city: routeGroupLabel(cities, route.city || "-"),
        cities,
        visit_day: routeGroupLabel(visitDays, route.visit_day || "Sem dia"),
        visit_days: visitDays,
        items,
        neighborhoods,
        neighborhood_sequence: neighborhoods.join(" -> "),
        sellers,
        managers,
        seller: sellers.length === 1 ? sellers[0] : (sellers.length ? "Varios" : "-"),
        manager: managers.length === 1 ? managers[0] : (managers.length ? "Varios" : "-"),
        pdvs: items.length,
        total_caixas: String(Math.trunc(totalBoxes)),
        gap_total: String(Math.trunc(totalGap)),
        manual: Boolean(route.manual)
      };
    }

    function recalcGiroRecolhaRoutesState() {
      const payload = state.giroRecolhaRoutes && typeof state.giroRecolhaRoutes === "object" ? state.giroRecolhaRoutes : { generated: false, routes: [], summary: {} };
      const routes = (Array.isArray(payload.routes) ? payload.routes : [])
        .map(recalcGiroRecolhaRoute)
        .filter(route => route.manual || (Array.isArray(route.items) && route.items.length));
      const totalPdvs = routes.reduce((sum, route) => sum + route.items.length, 0);
      const totalGap = routes.reduce((sum, route) => sum + parseGiroRecolhaNumber(route.gap_total), 0);
      const totalBoxes = routes.reduce((sum, route) => sum + parseGiroRecolhaNumber(route.total_caixas), 0);
      state.giroRecolhaRoutes = {
        ...payload,
        total: routes.length,
        routes,
        summary: {
          ...(payload.summary || {}),
          rotas: routes.length,
          pdvs: totalPdvs,
          gap_total: String(Math.trunc(totalGap)),
          total_caixas: String(Math.trunc(totalBoxes))
        }
      };
      if (!routes.some(route => String(route.id || "") === String(state.giroRecolhaBuilder.activeRouteId || ""))) {
        state.giroRecolhaBuilder.activeRouteId = routes.length ? String(routes[0].id || "") : "";
      }
    }

    function allGiroRecolhaRouteCandidates() {
      const records = state.giroRecolha && Array.isArray(state.giroRecolha.records) ? state.giroRecolha.records : [];
      const routeItems = state.giroRecolhaRoutes && Array.isArray(state.giroRecolhaRoutes.routes)
        ? state.giroRecolhaRoutes.routes.flatMap(route => Array.isArray(route.items) ? route.items : [])
        : [];
      const map = new Map();
      records.forEach(record => {
        const item = giroRecolhaRouteItemFromRecord(record);
        const key = giroRecolhaPdvKey(item);
        if (key !== "|") map.set(key, item);
      });
      routeItems.forEach(item => {
        const key = giroRecolhaPdvKey(item);
        if (key !== "|" && !map.has(key)) map.set(key, item);
      });
      return [...map.values()];
    }

    function normalizeGiroRecolhaNb(value) {
      return String(value || "").replace(/\D/g, "").replace(/^0+(?=\d)/, "");
    }

    function findGiroRecolhaCandidateByNb(nb, targetRoute) {
      const rawNb = String(nb || "").trim().toUpperCase();
      const normalizedNb = normalizeGiroRecolhaNb(rawNb);
      if (!rawNb && !normalizedNb) return null;
      const matches = allGiroRecolhaRouteCandidates().filter(item => {
        const itemNb = String(item && (item.cod_pdv || item.nb) || "").trim();
        return itemNb.toUpperCase() === rawNb || (normalizedNb && normalizeGiroRecolhaNb(itemNb) === normalizedNb);
      });
      if (!matches.length) return null;
      const routeOperation = String(targetRoute && targetRoute.operation || "").trim();
      if (routeOperation && routeOperation !== "Varios") {
        const sameOperation = matches.find(item => String(item.filial || "").trim() === routeOperation);
        if (sameOperation) return sameOperation;
      }
      return matches[0];
    }

    function giroRecolhaRouteLabel(route) {
      if (!route) return "-";
      return `${route.id || "-"} | ${cleanDisplayText(route.city || "-")} | ${cleanDisplayText(route.visit_day || "Sem dia")} | ${route.pdvs || 0} PDV(s)`;
    }

    function giroRecolhaRouteMembershipMap(routes = null) {
      const sourceRoutes = Array.isArray(routes)
        ? routes
        : (state.giroRecolhaRoutes && Array.isArray(state.giroRecolhaRoutes.routes) ? state.giroRecolhaRoutes.routes : []);
      const map = new Map();
      sourceRoutes.forEach(route => {
        (Array.isArray(route.items) ? route.items : []).forEach(item => {
          map.set(giroRecolhaPdvKey(item), String(route.id || ""));
        });
      });
      return map;
    }

    function ensureGiroRecolhaActiveRoute(routes) {
      const items = Array.isArray(routes) ? routes : [];
      const current = String(state.giroRecolhaBuilder.activeRouteId || "");
      if (current && items.some(route => String(route.id || "") === current)) return current;
      const next = items.length ? String(items[0].id || "") : "";
      state.giroRecolhaBuilder.activeRouteId = next;
      return next;
    }

    function updateGiroRecolhaActiveRoute() {
      state.giroRecolhaBuilder.activeRouteId = E.giroRecolhaActiveRoute ? E.giroRecolhaActiveRoute.value : "";
      renderGiroRecolhaBuilder();
    }

    function updateGiroRecolhaBlockSearch() {
      state.giroRecolhaBuilder.search = E.giroRecolhaBlockSearch ? E.giroRecolhaBlockSearch.value.trim() : "";
      renderGiroRecolhaBuilder();
    }

    function moveGiroRecolhaPdvToRoute(pdvKey, routeId) {
      const payload = state.giroRecolhaRoutes && typeof state.giroRecolhaRoutes === "object" ? state.giroRecolhaRoutes : null;
      if (!payload || !Array.isArray(payload.routes)) return;
      const targetRoute = payload.routes.find(route => String(route.id || "") === String(routeId || ""));
      if (!targetRoute) {
        addLog("Selecione uma rota destino para mover o PDV.", "warn");
        return;
      }
      const candidate = allGiroRecolhaRouteCandidates().find(item => giroRecolhaPdvKey(item) === pdvKey);
      if (!candidate) {
        addLog("PDV não encontrado nas oportunidades carregadas.", "warn");
        return;
      }
      if ((Array.isArray(targetRoute.items) ? targetRoute.items : []).some(item => giroRecolhaPdvKey(item) === pdvKey)) {
        addLog(`NB ${candidate.cod_pdv || ""} já esta na rota ${routeId}.`, "warn");
        return;
      }
      payload.routes.forEach(route => {
        route.items = (Array.isArray(route.items) ? route.items : []).filter(item => giroRecolhaPdvKey(item) !== pdvKey);
      });
      targetRoute.items = [...(Array.isArray(targetRoute.items) ? targetRoute.items : []), candidate];
      state.giroRecolhaBuilder.activeRouteId = String(targetRoute.id || "");
      recalcGiroRecolhaRoutesState();
      renderGiroRecolhaRoutes();
      addLog(`NB ${candidate.cod_pdv || ""} movido para a rota ${targetRoute.id || ""}.`, "ok");
    }

    function createGiroRecolhaManualRoute() {
      const payload = state.giroRecolhaRoutes && typeof state.giroRecolhaRoutes === "object" ? state.giroRecolhaRoutes : null;
      if (!payload || !payload.generated || !Array.isArray(payload.routes)) {
        addLog("Gere as rotas antes de criar uma rota manual.", "warn");
        return;
      }
      const nextNumber = payload.routes.reduce((max, route) => {
        const match = String(route.id || "").match(/\d+/);
        return Math.max(max, match ? Number(match[0]) : 0);
      }, 0) + 1;
      const id = `R${String(nextNumber).padStart(3, "0")}`;
      payload.routes.push({
        id,
        operation: "Manual",
        seller: "-",
        sellers: [],
        manager: "-",
        managers: [],
        visit_day: "Manual",
        city: "Manual",
        neighborhoods: [],
        neighborhood_sequence: "",
        pdvs: 0,
        total_caixas: "0",
        gap_total: "0",
        faturamento_total: "R$ 0,00",
        items: [],
        manual: true
      });
      state.giroRecolhaBuilder.activeRouteId = id;
      recalcGiroRecolhaRoutesState();
      renderGiroRecolhaRoutes();
      addLog(`Rota ${id} criada para montagem manual.`, "ok");
    }

    function mergeGiroRecolhaRoute(targetRouteId) {
      const select = document.getElementById(`giroRouteMerge-${targetRouteId}`);
      const sourceRouteId = select ? String(select.value || "") : "";
      if (!sourceRouteId) {
        addLog("Selecione a rota que será mesclada.", "warn");
        return;
      }
      const payload = state.giroRecolhaRoutes && typeof state.giroRecolhaRoutes === "object" ? state.giroRecolhaRoutes : null;
      if (!payload || !Array.isArray(payload.routes)) return;
      if (String(sourceRouteId) === String(targetRouteId)) {
        addLog("Escolha rotas diferentes para mesclar.", "warn");
        return;
      }
      const targetRoute = payload.routes.find(route => String(route.id || "") === String(targetRouteId || ""));
      const sourceRoute = payload.routes.find(route => String(route.id || "") === String(sourceRouteId || ""));
      if (!targetRoute || !sourceRoute) {
        addLog("Rota de origem ou destino não encontrada.", "warn");
        return;
      }
      const existing = new Set((Array.isArray(targetRoute.items) ? targetRoute.items : []).map(giroRecolhaPdvKey));
      const movedItems = (Array.isArray(sourceRoute.items) ? sourceRoute.items : []).filter(item => !existing.has(giroRecolhaPdvKey(item)));
      targetRoute.items = [...(Array.isArray(targetRoute.items) ? targetRoute.items : []), ...movedItems];
      payload.routes = payload.routes.filter(route => String(route.id || "") !== String(sourceRouteId));
      delete state.giroRecolhaRouteHeights[sourceRouteId];
      state.giroRecolhaBuilder.activeRouteId = String(targetRoute.id || "");
      recalcGiroRecolhaRoutesState();
      renderGiroRecolhaRoutes();
      addLog(`Rota ${sourceRouteId} mesclada em ${targetRouteId}.`, "ok");
    }

    function renderGiroRecolhaBuilder(routes = null) {
      const payload = state.giroRecolhaRoutes && typeof state.giroRecolhaRoutes === "object" ? state.giroRecolhaRoutes : null;
      const sourceRoutes = Array.isArray(routes)
        ? routes
        : (payload && Array.isArray(payload.routes) ? payload.routes : []);
      if (!E.giroRecolhaBuilder) return;
      if (!payload || !payload.generated || !sourceRoutes.length) {
        E.giroRecolhaBuilder.classList.add("d-none");
        if (E.giroRecolhaBlockPool) E.giroRecolhaBlockPool.innerHTML = "";
        return;
      }
      E.giroRecolhaBuilder.classList.remove("d-none");
      const activeRouteId = ensureGiroRecolhaActiveRoute(sourceRoutes);
      if (E.giroRecolhaActiveRoute) {
        E.giroRecolhaActiveRoute.innerHTML = sourceRoutes
          .map(route => `<option value="${escapeHtml(route.id || "")}">${escapeHtml(giroRecolhaRouteLabel(route))}</option>`)
          .join("");
        E.giroRecolhaActiveRoute.value = activeRouteId;
      }
      if (E.giroRecolhaBlockSearch && E.giroRecolhaBlockSearch.value !== state.giroRecolhaBuilder.search) {
        E.giroRecolhaBlockSearch.value = state.giroRecolhaBuilder.search || "";
      }
      const membership = giroRecolhaRouteMembershipMap(sourceRoutes);
      const search = normalizeTextForSearch(state.giroRecolhaBuilder.search || "");
      const activeRoute = sourceRoutes.find(route => String(route.id || "") === activeRouteId);
      const candidates = allGiroRecolhaRouteCandidates()
        .filter(item => {
          if (!search) return true;
          return giroRecolhaRouteItemText(item).includes(search);
        })
        .sort((a, b) => {
          const currentA = membership.get(giroRecolhaPdvKey(a)) || "";
          const currentB = membership.get(giroRecolhaPdvKey(b)) || "";
          const activeA = currentA === activeRouteId ? 1 : 0;
          const activeB = currentB === activeRouteId ? 1 : 0;
          if (activeA !== activeB) return activeA - activeB;
          const cityCompare = String(a.cidade || "").localeCompare(String(b.cidade || ""), "pt-BR");
          if (cityCompare) return cityCompare;
          const bairroCompare = String(a.bairro || "").localeCompare(String(b.bairro || ""), "pt-BR");
          if (bairroCompare) return bairroCompare;
          return String(a.nome || "").localeCompare(String(b.nome || ""), "pt-BR");
        });
      const visibleCandidates = candidates.slice(0, 80);
      if (E.giroRecolhaBuilderHint) {
        E.giroRecolhaBuilderHint.textContent = `${formatNumber(candidates.length)} bloco(s) disponiveis${candidates.length > visibleCandidates.length ? " - mostrando 80" : ""}.`;
      }
      if (!E.giroRecolhaBlockPool) return;
      if (!visibleCandidates.length) {
        E.giroRecolhaBlockPool.innerHTML = '<div class="text-center py-3 text-secondary border rounded-3">Nenhum bloco encontrado na busca atual.</div>';
        return;
      }
      E.giroRecolhaBlockPool.innerHTML = visibleCandidates.map(item => {
        const key = giroRecolhaPdvKey(item);
        const currentRouteId = membership.get(key) || "";
        const isActive = currentRouteId === activeRouteId;
        return `
          <article class="route-pdv-block ${isActive ? "is-active" : ""}">
            <div class="d-flex justify-content-between gap-2 mb-1">
              <strong>${escapeHtml(cleanDisplayText(item.nome || "-"))}</strong>
              <span class="badge ${isActive ? "text-bg-success" : "text-bg-secondary"}">${escapeHtml(currentRouteId || "Fora")}</span>
            </div>
            <div class="small text-secondary">NB ${escapeHtml(item.cod_pdv || "-")} | Op. ${escapeHtml(item.filial || "-")} | ${escapeHtml(cleanDisplayText(item.cidade || "-"))}</div>
            <div class="small text-secondary">${escapeHtml(cleanDisplayText(item.bairro || "-"))} | Vend. ${escapeHtml(item.seller || "-")}</div>
            <div class="small mt-1">Caixas ${escapeHtml(item.total_caixas || "0")} cx | Faltam ${escapeHtml(item.gap_caixas || "0")} cx</div>
            <div class="small text-secondary">${escapeHtml(giroMissingTypesText(item))}</div>
            <button class="btn btn-outline-primary btn-sm mt-2 w-100" ${isActive ? "disabled" : ""} onclick="moveGiroRecolhaPdvToRoute('${escapeHtml(key)}', '${escapeHtml(activeRouteId)}')">
              <i class="bi bi-arrow-right-square me-1"></i>${isActive ? "Na rota destino" : `Mover para ${escapeHtml(activeRoute ? activeRoute.id || "" : "")}`}
            </button>
          </article>
        `;
      }).join("");
    }

    function giroRecolhaRouteSearchText(route, items) {
      const routeParts = [
        route.id,
        route.operation,
        route.seller,
        route.manager,
        route.visit_day,
        route.city,
        route.neighborhood_sequence,
        Array.isArray(route.neighborhoods) ? route.neighborhoods.join(" ") : ""
      ];
      const itemParts = (items || []).flatMap(item => [
        item.cod_pdv,
        item.nome,
        item.cidade,
        item.bairro,
        item.visit_day,
        item.seller,
        item.manager,
        item.total_caixas,
        item.gap_litrinho,
        item.gap_inteira,
        item.gap_litrao,
        item.giro_litrinho,
        item.giro_inteira,
        item.giro_litrao,
        giroMissingTypesText(item),
        item.command
      ]);
      return normalizeTextForSearch(routeParts.concat(itemParts).join(" "));
    }

    function giroRecolhaRouteMetaText(route) {
      return normalizeTextForSearch([
        route.id,
        route.operation,
        route.seller,
        route.manager,
        route.visit_day,
        route.city,
        route.neighborhood_sequence,
        Array.isArray(route.neighborhoods) ? route.neighborhoods.join(" ") : ""
      ].join(" "));
    }

    function giroRecolhaRouteItemText(item) {
      return normalizeTextForSearch([
        item.cod_pdv,
        item.nome,
        item.cidade,
        item.bairro,
        item.visit_day,
        item.seller,
        item.manager,
        item.total_caixas,
        item.gap_litrinho,
        item.gap_inteira,
        item.gap_litrao,
        item.giro_litrinho,
        item.giro_inteira,
        item.giro_litrao,
        giroMissingTypesText(item),
        item.command
      ].join(" "));
    }

    function filterGiroRecolhaRoutes(routes) {
      const filters = state.giroRecolhaRouteFilter || {};
      const search = normalizeTextForSearch(filters.search || "");
      const district = String(filters.district || "").trim();
      const minGap = parseGiroRecolhaNumber(filters.minGap || "");
      return (routes || []).map(route => {
        const originalItems = Array.isArray(route.items) ? route.items : [];
        let items = originalItems;
        if (district) {
          items = items.filter(item => String(item.bairro || "").trim() === district);
        }
        const routeMetaText = giroRecolhaRouteMetaText(route);
        if (search && !routeMetaText.includes(search)) {
          items = items.filter(item => giroRecolhaRouteItemText(item).includes(search));
          if (!items.length) return null;
        }
        if (!items.length) {
          if (route.manual && !district && !search && minGap <= 0) {
            return {
              ...route,
              items: [],
              pdvs: 0,
              total_caixas: "0",
              gap_total: "0",
              neighborhoods: [],
              neighborhood_sequence: ""
            };
          }
          return null;
        }
        const visibleGap = items.reduce((sum, item) => sum + parseGiroRecolhaNumber(item.gap_caixas), 0);
        const visibleBoxes = items.reduce((sum, item) => sum + parseGiroRecolhaNumber(item.total_caixas), 0);
        if (minGap > 0 && visibleGap < minGap) return null;
        const neighborhoods = [...new Set(items.map(item => String(item.bairro || "").trim()).filter(Boolean))];
        return {
          ...route,
          items,
          pdvs: items.length,
          total_caixas: String(Math.trunc(visibleBoxes)),
          gap_total: String(Math.trunc(visibleGap)),
          neighborhoods,
          neighborhood_sequence: neighborhoods.join(" -> ")
        };
      }).filter(Boolean);
    }

    function syncGiroRecolhaRouteDistrictOptions(routes) {
      if (!E.giroRecolhaRouteDistrict) return;
      const selected = String(state.giroRecolhaRouteFilter && state.giroRecolhaRouteFilter.district || "");
      const districts = [...new Set((routes || []).flatMap(route => Array.isArray(route.items) ? route.items : []).map(item => String(item.bairro || "").trim()).filter(Boolean))].sort();
      const hasSelected = selected && districts.includes(selected);
      E.giroRecolhaRouteDistrict.innerHTML = [
        '<option value="">Todos</option>',
        ...(selected && !hasSelected ? [`<option value="${escapeHtml(selected)}">${escapeHtml(cleanDisplayText(selected))}</option>`] : []),
        ...districts.map(item => `<option value="${escapeHtml(item)}">${escapeHtml(cleanDisplayText(item))}</option>`)
      ].join("");
      E.giroRecolhaRouteDistrict.value = selected && (hasSelected || selected) ? selected : "";
      state.giroRecolhaRouteFilter.district = E.giroRecolhaRouteDistrict.value;
    }

    function bindGiroRecolhaRouteResizers() {
      disconnectGiroRouteResizeObserver();
      if (typeof ResizeObserver === "undefined") return;
      const nodes = document.querySelectorAll(".route-table-scroll[data-route-id]");
      if (!nodes.length) return;
      giroRouteResizeObserver = new ResizeObserver(entries => {
        entries.forEach(entry => {
          const routeId = entry.target && entry.target.dataset ? entry.target.dataset.routeId : "";
          if (!routeId || !entry.contentRect || !entry.contentRect.height) return;
          state.giroRecolhaRouteHeights[routeId] = clampGiroRecolhaRouteHeight(entry.contentRect.height);
        });
      });
      nodes.forEach(node => giroRouteResizeObserver.observe(node));
    }

    function renderGiroRecolhaRoutes() {
      const payload = state.giroRecolhaRoutes && typeof state.giroRecolhaRoutes === "object" ? state.giroRecolhaRoutes : { generated: false, total: 0, summary: {}, routes: [] };
      const routes = Array.isArray(payload.routes) ? payload.routes : [];
      const summary = payload.summary || {};
      if (!payload.generated) {
        disconnectGiroRouteResizeObserver();
        renderGiroRecolhaBuilder([]);
        if (E.giroRecolhaRouteTools) E.giroRecolhaRouteTools.classList.add("d-none");
        if (E.giroRecolhaRouteCards) E.giroRecolhaRouteCards.innerHTML = "";
        if (E.giroRecolhaRoutesContainer) {
          E.giroRecolhaRoutesContainer.innerHTML = '<div class="text-center py-3 text-secondary border rounded-3">Ajuste os filtros e clique em Gerar rotas.</div>';
        }
        return;
      }
      if (E.giroRecolhaRouteTools) E.giroRecolhaRouteTools.classList.remove("d-none");
      syncGiroRecolhaRouteDistrictOptions(routes);
      const visibleRoutes = filterGiroRecolhaRoutes(routes);
      const visiblePdvs = visibleRoutes.reduce((sum, route) => sum + (Array.isArray(route.items) ? route.items.length : 0), 0);
      const visibleGap = visibleRoutes.reduce((sum, route) => sum + parseGiroRecolhaNumber(route.gap_total), 0);
      const visibleBoxes = visibleRoutes.reduce((sum, route) => sum + parseGiroRecolhaNumber(route.total_caixas), 0);
      if (E.giroRecolhaRouteCards) {
        E.giroRecolhaRouteCards.innerHTML = [
          ["Rotas", `${visibleRoutes.length}/${summary.rotas || routes.length || 0}`, "visiveis"],
          ["PDVs", `${visiblePdvs}/${summary.pdvs || 0}`, "visiveis"],
          ["Caixas", `${Math.trunc(visibleBoxes)}/${summary.total_caixas || "-"}`, "total visivel"],
          ["Faltam", String(Math.trunc(visibleGap)), "caixas visiveis"]
        ].map(([label, value, sub]) => `
          <article class="recolha-dashboard-card">
            <span class="label">${escapeHtml(label)}</span>
            <span class="value">${escapeHtml(String(value))}</span>
            <span class="sub">${escapeHtml(sub)}</span>
          </article>
        `).join("");
      }
      renderGiroRecolhaBuilder(routes);
      if (!E.giroRecolhaRoutesContainer) return;
      if (!routes.length) {
        disconnectGiroRouteResizeObserver();
        renderGiroRecolhaBuilder([]);
        E.giroRecolhaRoutesContainer.innerHTML = '<div class="text-center py-3 text-secondary border rounded-3">Nenhuma rota sugerida nos filtros atuais.</div>';
        return;
      }
      if (!visibleRoutes.length) {
        disconnectGiroRouteResizeObserver();
        E.giroRecolhaRoutesContainer.innerHTML = '<div class="text-center py-3 text-secondary border rounded-3">Nenhuma rota encontrada na pesquisa atual.</div>';
        return;
      }
      E.giroRecolhaRoutesContainer.innerHTML = visibleRoutes.map(route => {
        const items = Array.isArray(route.items) ? route.items : [];
        const bairros = route.neighborhood_sequence || (Array.isArray(route.neighborhoods) && route.neighborhoods.length ? route.neighborhoods.join(" -> ") : "-");
        const routeTypes = giroRouteMissingTypesText(items);
        const routeHeight = clampGiroRecolhaRouteHeight(state.giroRecolhaRouteHeights && state.giroRecolhaRouteHeights[route.id]);
        const mergeOptions = routes
          .filter(candidate => String(candidate.id || "") !== String(route.id || ""))
          .map(candidate => `<option value="${escapeHtml(candidate.id || "")}">${escapeHtml(giroRecolhaRouteLabel(candidate))}</option>`)
          .join("");
        const rows = items.map(item => `
          <tr>
            <td class="ps-3">${escapeHtml(item.sequence || "-")}</td>
            <td>
              <strong>${escapeHtml(cleanDisplayText(item.nome || "-"))}</strong>
              <div class="small text-secondary">Op. ${escapeHtml(item.filial || "-")} | NB ${escapeHtml(item.cod_pdv || "-")} | ${escapeHtml(cleanDisplayText(item.cidade || "-"))} | ${escapeHtml(cleanDisplayText(item.bairro || "-"))} | Vend. ${escapeHtml(item.seller || "-")}</div>
              <div class="small text-secondary">Tipos faltantes: ${escapeHtml(giroMissingTypesText(item))}</div>
            </td>
            <td>${escapeHtml(item.total_caixas || "0")} cx</td>
            <td>${escapeHtml(item.gap_caixas || "0")} cx</td>
            <td>${escapeHtml(item.faturamento_total || "R$ 0,00")}</td>
            <td>${escapeHtml(item.media_faturamento_pedido || "R$ 0,00")}</td>
            <td class="text-end pe-3">
              <div class="d-flex gap-1 justify-content-end">
                <button class="btn btn-outline-primary btn-sm" onclick="copyGiroRecolhaCommand('${escapeHtml(item.command || "")}')"><i class="bi bi-clipboard me-1"></i>Copiar</button>
                <button class="btn btn-outline-danger btn-sm" onclick="removeGiroRecolhaRouteItem('${escapeHtml(route.id || "")}', '${escapeHtml(giroRecolhaPdvKey(item))}')"><i class="bi bi-x-lg"></i></button>
              </div>
            </td>
          </tr>
        `).join("");
        return `
          <article class="panel-card p-3 mb-2">
            <div class="d-flex flex-wrap gap-2 align-items-start justify-content-between mb-2">
              <div>
                <h3 class="h6 fw-bold mb-1">${escapeHtml(route.id || "-")} | ${escapeHtml(cleanDisplayText(route.city || "-"))} | ${escapeHtml(cleanDisplayText(route.visit_day || "Sem dia"))}</h3>
                <div class="small text-secondary">Operação ${escapeHtml(route.operation || "-")} | Vendedores ${escapeHtml(route.seller || "-")} | GVs ${escapeHtml(route.manager || "-")}</div>
                <div class="small text-secondary">Sequência bairros: ${escapeHtml(cleanDisplayText(bairros))}</div>
                <div class="small text-secondary">Tipos faltantes: ${escapeHtml(routeTypes)}</div>
              </div>
              <div class="d-flex flex-wrap gap-2 align-items-center">
                <span class="pill warn">${escapeHtml(String(route.pdvs || items.length || 0))} PDV(s)</span>
                <span class="pill">Caixas ${escapeHtml(route.total_caixas || "0")} cx</span>
                <span class="pill">Faltam ${escapeHtml(route.gap_total || "0")} cx</span>
                <button class="btn btn-outline-success btn-sm" onclick="copyGiroRecolhaRoute('${escapeHtml(route.id || "")}')"><i class="bi bi-copy me-1"></i>Copiar rota</button>
              </div>
            </div>
            <div class="row g-2 align-items-end mb-2">
              <div class="col-md-9">
                <label class="form-label small fw-semibold mb-1" for="giroRouteAddNb-${escapeHtml(route.id || "")}">Adicionar NB nesta rota</label>
                <input type="text" inputmode="numeric" class="form-control form-control-sm" id="giroRouteAddNb-${escapeHtml(route.id || "")}" placeholder="Digite o NB do PDV">
              </div>
              <div class="col-md-3">
                <button class="btn btn-outline-primary btn-sm w-100" onclick="addGiroRecolhaRouteItem('${escapeHtml(route.id || "")}')"><i class="bi bi-plus-circle me-1"></i>Adicionar</button>
              </div>
            </div>
            <div class="table-scroll route-table-scroll" data-route-id="${escapeHtml(route.id || "")}" style="height: ${routeHeight}px;">
              <table class="table table-sm table-hover align-middle mb-0">
                <thead>
                  <tr class="text-uppercase small text-secondary">
                    <th class="ps-3">Seq.</th>
                    <th>PDV</th>
                    <th>Caixas</th>
                    <th>Faltam</th>
                    <th>Fat. M-1</th>
                    <th>Média pedido</th>
                    <th class="text-end pe-3">Ação</th>
                  </tr>
                </thead>
                <tbody>${rows || '<tr><td colspan="7" class="text-center py-3 text-secondary">Rota vazia. Use a montagem interativa ou digite um NB para adicionar.</td></tr>'}</tbody>
              </table>
            </div>
            <div class="route-resize-handle" onpointerdown="startGiroRouteResize(event, '${escapeHtml(route.id || "")}')">
              <i class="bi bi-grip-horizontal"></i>Arraste para ajustar altura
            </div>
            <div class="row g-2 align-items-end mt-2">
              <div class="col-md-9">
                <label class="form-label small fw-semibold mb-1" for="giroRouteMerge-${escapeHtml(route.id || "")}">Mesclar outra rota nesta</label>
                <select class="form-select form-select-sm" id="giroRouteMerge-${escapeHtml(route.id || "")}" ${mergeOptions ? "" : "disabled"}>
                  <option value="">${mergeOptions ? "Selecione a rota de origem" : "Nenhuma rota para mesclar"}</option>
                  ${mergeOptions}
                </select>
              </div>
              <div class="col-md-3">
                <button class="btn btn-outline-success btn-sm w-100" onclick="mergeGiroRecolhaRoute('${escapeHtml(route.id || "")}')" ${mergeOptions ? "" : "disabled"}>
                  <i class="bi bi-intersect me-1"></i>Mesclar
                </button>
              </div>
            </div>
          </article>
        `;
      }).join("");
      bindGiroRecolhaRouteResizers();
    }

    async function syncGiroRecolha({ silent = true } = {}) {
      updateTokens();
      if (!hasPanelAuth()) {
        if (!silent) addLog("Sessão do painel não validada.", "warn");
        return false;
      }
      try {
        if (!state.panel || !state.panel.mode) await syncPanelSession();
        const params = currentGiroRecolhaParams();
        const [optionsPayload, slicerOptionsPayloads, payload] = await Promise.all([
          req(`${CONFIG.endpoints.giroRecolha.options}?${giroRecolhaOptionsQueryString(params)}`, { timeoutMs: 45000 }),
          loadGiroRecolhaSlicerOptions(params),
          req(`${CONFIG.endpoints.giroRecolha.dashboard}?${giroRecolhaQueryString(params)}`, { timeoutMs: 45000 })
        ]);
        state.giroRecolhaOptions = optionsPayload && optionsPayload.options ? optionsPayload.options : emptyGiroRecolhaOptions();
        state.giroRecolhaSlicerOptions = normalizeGiroRecolhaSlicerOptions(slicerOptionsPayloads, state.giroRecolhaOptions);
        state.giroRecolha = payload && typeof payload === "object"
          ? { total: Number(payload.total || 0), summary: payload.summary || {}, records: Array.isArray(payload.records) ? payload.records : [] }
          : { total: 0, summary: {}, records: [] };
        state.giroRecolhaRoutes = { generated: false, total: 0, summary: {}, routes: [] };
        state.giroRecolhaBuilder = { activeRouteId: "", search: "" };
        renderGiroRecolhaFilterOptions(params);
        renderGiroRecolha();
        renderGiroRecolhaRoutes();
        if (!silent) addLog("Dashboard de giro para recolha atualizado.", "ok");
        return true;
      } catch (err) {
        if (!silent) addLog(`Falha ao carregar dashboard de giro: ${err.message}`, "err");
        renderGiroRecolha();
        renderGiroRecolhaRoutes();
        return false;
      }
    }

    async function syncGiroRecolhaRoutes({ silent = true } = {}) {
      updateTokens();
      if (!hasPanelAuth()) {
        if (!silent) addLog("Sessão do painel não validada.", "warn");
        return false;
      }
      try {
        if (!state.panel || !state.panel.mode) await syncPanelSession();
        const params = currentGiroRecolhaParams();
        const payload = await req(`${CONFIG.endpoints.giroRecolha.routes}?${giroRecolhaRoutesQueryString(params)}`, { timeoutMs: 45000 });
        state.giroRecolhaRoutes = payload && typeof payload === "object"
          ? { generated: true, total: Number(payload.total || 0), summary: payload.summary || {}, routes: Array.isArray(payload.routes) ? payload.routes : [] }
          : { generated: true, total: 0, summary: {}, routes: [] };
        state.giroRecolhaBuilder.activeRouteId = state.giroRecolhaRoutes.routes.length ? String(state.giroRecolhaRoutes.routes[0].id || "") : "";
        state.giroRecolhaBuilder.search = "";
        if (E.giroRecolhaBlockSearch) E.giroRecolhaBlockSearch.value = "";
        renderGiroRecolhaRoutes();
        if (!silent) addLog("Rotas de recolha geradas.", "ok");
        return true;
      } catch (err) {
        if (!silent) addLog(`Falha ao gerar rotas de recolha: ${err.message}`, "err");
        renderGiroRecolhaRoutes();
        return false;
      }
    }

    async function copyGiroRecolhaCommand(command) {
      const text = String(command || "").trim();
      if (!text) return;
      if (await writeTextToClipboard(text)) {
        addLog(`Comando copiado: ${text}`, "ok");
      } else {
        addLog(`Comando sugerido: ${text}`, "info");
      }
    }

    function buildGiroRecolhaRouteCopyText(route) {
      const items = Array.isArray(route && route.items) ? route.items : [];
      const operations = routeGroupLabel(items.map(item => item.filial || item.operation), route.operation || "-");
      const cities = routeGroupLabel(items.map(item => item.cidade || item.city), route.city || "-");
      const visitDays = routeGroupLabel(items.map(item => item.visit_day), route.visit_day || "Sem dia");
      const sellers = routeGroupLabel(items.map(item => item.seller), route.seller || "-");
      const managers = routeGroupLabel(items.map(item => item.manager), route.manager || "-");
      const bairros = [...new Set(items.map(item => String(item.bairro || "").trim()).filter(Boolean))].join(" -> ") || route.neighborhood_sequence || "-";
      const routeTypes = giroRouteMissingTypesText(items);
      const lines = [
        `*Rota de recolha ${route.id || ""}*`.trim(),
        `Cidade: ${cities} | Dia: ${visitDays}`,
        `Operação: ${operations} | Vendedor(es): ${sellers} | GV(s): ${managers}`,
        `PDVs: ${items.length} | Caixas cliente: ${route.total_caixas || "0"} cx | Faltam: ${route.gap_total || "0"} cx`,
        `Bairros: ${cleanDisplayText(bairros)}`,
        `Tipos faltantes: ${routeTypes}`,
        "",
        "*Sequência*"
      ];
      items.forEach(item => {
        lines.push(
          `${item.sequence || "-"}. ${cleanDisplayText(item.nome || "-")} | NB ${item.cod_pdv || "-"}`,
          `   Op. ${item.filial || "-"} | ${cleanDisplayText(item.cidade || "-")} | ${cleanDisplayText(item.bairro || "-")} | Vend. ${item.seller || "-"}`,
          `   Caixas cliente: ${item.total_caixas || "0"} cx | Faltam: ${item.gap_caixas || "0"} cx | Fat. M-1: ${item.faturamento_total || "R$ 0,00"}`,
          `   Tipos: ${giroMissingTypesText(item)}`,
          `   Comando: ${item.command || "-"}`
        );
      });
      return lines.join("\n");
    }

    async function copyGiroRecolhaRoute(routeId) {
      const visibleRoutes = currentVisibleGiroRecolhaRoutes();
      const allRoutes = state.giroRecolhaRoutes && Array.isArray(state.giroRecolhaRoutes.routes) ? state.giroRecolhaRoutes.routes : [];
      const route = visibleRoutes.find(item => String(item.id || "") === String(routeId || ""))
        || allRoutes.find(item => String(item.id || "") === String(routeId || ""));
      if (!route || !Array.isArray(route.items)) return;
      const text = buildGiroRecolhaRouteCopyText(route);
      if (await writeTextToClipboard(text)) {
        addLog(`Rota ${route.id || ""} copiada.`, "ok");
      } else {
        addLog(`Não foi possível copiar a rota ${route.id || ""} automaticamente.`, "warn");
      }
    }

    function removeGiroRecolhaRouteItem(routeId, pdvKey) {
      const payload = state.giroRecolhaRoutes && typeof state.giroRecolhaRoutes === "object" ? state.giroRecolhaRoutes : null;
      if (!payload || !Array.isArray(payload.routes)) return;
      let removed = null;
      payload.routes.forEach(route => {
        if (String(route.id || "") !== String(routeId || "")) return;
        const before = Array.isArray(route.items) ? route.items : [];
        removed = before.find(item => giroRecolhaPdvKey(item) === pdvKey) || removed;
        route.items = before.filter(item => giroRecolhaPdvKey(item) !== pdvKey);
      });
      recalcGiroRecolhaRoutesState();
      renderGiroRecolhaRoutes();
      if (removed) addLog(`PDV ${removed.cod_pdv || ""} removido da rota ${routeId}.`, "ok");
    }

    function addGiroRecolhaRouteItem(routeId) {
      const input = document.getElementById(`giroRouteAddNb-${routeId}`);
      const nb = input ? String(input.value || "").trim() : "";
      if (!nb) {
        addLog("Digite o NB do PDV para adicionar na rota.", "warn");
        return;
      }
      const payload = state.giroRecolhaRoutes && typeof state.giroRecolhaRoutes === "object" ? state.giroRecolhaRoutes : null;
      if (!payload || !Array.isArray(payload.routes)) return;
      const targetRoute = payload.routes.find(route => String(route.id || "") === String(routeId || ""));
      if (!targetRoute) return;
      const candidate = findGiroRecolhaCandidateByNb(nb, targetRoute);
      if (!candidate) {
        addLog(`NB ${nb} não encontrado nas oportunidades carregadas. Ajuste os filtros ou aumente o limite e atualize o giro.`, "warn");
        return;
      }
      const pdvKey = giroRecolhaPdvKey(candidate);
      if ((Array.isArray(targetRoute.items) ? targetRoute.items : []).some(item => giroRecolhaPdvKey(item) === pdvKey)) {
        addLog(`NB ${candidate.cod_pdv || nb} já esta na rota ${routeId}.`, "warn");
        if (input) input.value = "";
        return;
      }
      payload.routes.forEach(route => {
        route.items = (Array.isArray(route.items) ? route.items : []).filter(item => giroRecolhaPdvKey(item) !== pdvKey);
      });
      targetRoute.items = [...(Array.isArray(targetRoute.items) ? targetRoute.items : []), candidate];
      recalcGiroRecolhaRoutesState();
      renderGiroRecolhaRoutes();
      addLog(`NB ${candidate.cod_pdv || nb} adicionado na rota ${routeId}.`, "ok");
    }

    function currentVisibleGiroRecolhaRoutes() {
      const payload = state.giroRecolhaRoutes && typeof state.giroRecolhaRoutes === "object" ? state.giroRecolhaRoutes : { generated: false, routes: [] };
      if (!payload.generated || !Array.isArray(payload.routes)) return [];
      return filterGiroRecolhaRoutes(payload.routes);
    }

    function exportGiroRecolhaRoutesCsv() {
      const routes = currentVisibleGiroRecolhaRoutes();
      if (!routes.length) {
        addLog("Nenhuma rota visivel para exportar.", "warn");
        return;
      }
      const header = [
        "rota",
        "seq",
        "operacao",
        "cidade",
        "dia_visita",
        "bairro",
        "vendedor",
        "gv",
        "nb",
        "pdv",
        "total_caixas",
        "gap_caixas",
        "faltam_litrinho",
        "faltam_inteira",
        "faltam_litrao",
        "giro_litrinho",
        "giro_inteira",
        "giro_litrao",
        "tipos_faltantes",
        "media_pedido",
        "faturamento_ultimo_mes",
        "comando"
      ];
      const lines = [header.map(csvEscape).join(";")];
      routes.forEach(route => {
        (Array.isArray(route.items) ? route.items : []).forEach(item => {
          lines.push([
            route.id || "",
            item.sequence || "",
            item.filial || route.operation || "",
            route.city || item.cidade || "",
            route.visit_day || item.visit_day || "",
            item.bairro || "",
            item.seller || route.seller || "",
            item.manager || route.manager || "",
            item.cod_pdv || "",
            cleanDisplayText(item.nome || ""),
            item.total_caixas || "",
            item.gap_caixas || "",
            item.gap_litrinho || "",
            item.gap_inteira || "",
            item.gap_litrao || "",
            item.giro_litrinho || "",
            item.giro_inteira || "",
            item.giro_litrao || "",
            giroMissingTypesText(item),
            item.media_faturamento_pedido || "",
            item.faturamento_total || "",
            item.command || ""
          ].map(csvEscape).join(";"));
        });
      });
      const blob = new Blob(["\uFEFF" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
      const blobUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      const stamp = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, "");
      anchor.href = blobUrl;
      anchor.download = `rotas_recolha_${stamp}.csv`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(blobUrl);
      addLog(`CSV de rotas exportado: ${formatNumber(routes.length)} rota(s).`, "ok");
      void recordClientPanelAction({
        module: "giro",
        action: "exportar_rotas_recolha_csv",
        target_type: "rotas",
        target_id: String(routes.length),
        metadata: { routes: routes.length }
      });
    }

    function normalizeRecolhaStatus(value) {
      const normalized = normalizeTextForSearch(cleanDisplayText(value)).replace(/\s+/g, " ");
      if (normalized === "recolhido") return "Recolhido";
      if (normalized === "nao recolhido") return "Não Recolhido";
      if (normalized === "ok" || normalized === "lancado") return "Ok";
      if (normalized === "nok" || normalized === "nao" || normalized === "nao lancado") return "Nok";
      return cleanDisplayText(value || "");
    }

    function recolhaStatusBadge(status) {
      const normalized = normalizeRecolhaStatus(status);
      if (normalized === "Recolhido") return '<span class="badge text-bg-success">Recolhido</span>';
      if (normalized === "Ok") return '<span class="badge text-bg-primary">Lançado</span>';
      if (normalized === "Nok") return '<span class="badge text-bg-secondary">Aberta</span>';
      return '<span class="badge text-bg-warning">Não recolhido</span>';
    }

    function splitRecolhaPartialReason(value) {
      const text = cleanDisplayText(value || "").trim();
      const partialKey = normalizeTextForSearch(RECOLHA_PARTIAL_REASON).replace(/\s+/g, " ");
      const textKey = normalizeTextForSearch(text).replace(/\s+/g, " ");
      if (!textKey.startsWith(partialKey)) {
        return { isPartial: false, option: text, detail: "" };
      }
      const detail = text
        .replace(/^recolha\s+parcial\s*/i, "")
        .replace(/^[:|;\-]\s*/, "")
        .trim();
      return { isPartial: true, option: RECOLHA_PARTIAL_REASON, detail };
    }

    function syncRecolhaPartialDetail(container) {
      if (!container) return;
      const select = container.querySelector(".recolha-motivo, .recolha-bulk-motivo");
      const detail = container.querySelector(".recolha-partial-detail");
      if (!select || !detail) return;
      const parsed = splitRecolhaPartialReason(select.value);
      const visible = Boolean(parsed.isPartial);
      detail.classList.toggle("d-none", !visible);
      detail.required = visible;
      if (!visible) {
        detail.value = "";
        detail.classList.remove("recolha-partial-invalid");
      }
    }

    function buildRecolhaMotivoValue(container) {
      const select = container ? container.querySelector(".recolha-motivo, .recolha-bulk-motivo") : null;
      const detail = container ? container.querySelector(".recolha-partial-detail") : null;
      const selected = cleanDisplayText(select ? select.value : "").trim();
      const parsed = splitRecolhaPartialReason(selected);
      if (!parsed.isPartial) return selected;
      const detailValue = cleanDisplayText(detail ? detail.value : "").trim();
      if (!detailValue) {
        if (detail) {
          detail.classList.add("recolha-partial-invalid");
          detail.focus();
        }
        throw new Error("Informe o que foi recolhido na recolha parcial.");
      }
      if (detail) detail.classList.remove("recolha-partial-invalid");
      return `${RECOLHA_PARTIAL_REASON}: ${detailValue}`;
    }

    function recolhaBaixaBadge(record) {
      const validation = record && record.baixa_validacao ? record.baixa_validacao : {};
      const status = cleanDisplayText(validation.status || "");
      const label = cleanDisplayText(validation.label || "Não validado");
      if (status === "baixado") return `<span class="badge text-bg-success">${escapeHtml(label)}</span>`;
      if (status === "pendente") return `<span class="badge text-bg-danger">${escapeHtml(label)}</span>`;
      if (status === "erro") return `<span class="badge text-bg-warning">${escapeHtml(label)}</span>`;
      return `<span class="badge text-bg-secondary">${escapeHtml(label)}</span>`;
    }

    function recolhaBucket(record) {
      const status = normalizeRecolhaStatus(record.status_caixa_noturno || "");
      const lancado = normalizeRecolhaStatus(record.lancado_faturista || "");
      if (status === "Recolhido") return "recolhidas";
      if (status === "Não Recolhido") return "nao_recolhidas";
      if (lancado === "Ok") return "lancadas";
      return "abertas";
    }

    function flattenRecolhaOperations(operations) {
      const rows = [];
      for (const operation of Array.isArray(operations) ? operations : []) {
        const records = Array.isArray(operation.records) ? operation.records : [];
        for (const record of records) {
          rows.push({ ...record, _operation: cleanDisplayText(operation.revenda || record.revenda || "Sem operação") });
        }
      }
      return rows;
    }

    function parseRecolhaCreatedAt(record) {
      const iso = String(record.criado_em_iso || "").trim();
      if (iso) {
        const parsedIso = new Date(iso);
        if (!Number.isNaN(parsedIso.getTime())) return parsedIso;
      }
      const raw = String(record.criado_em || "").trim();
      const match = raw.match(/^(\d{2})\/(\d{2})\/(\d{4})(?:\s+(\d{2}):(\d{2}))?/);
      if (match) {
        const parsed = new Date(Number(match[3]), Number(match[2]) - 1, Number(match[1]), Number(match[4] || 0), Number(match[5] || 0));
        if (!Number.isNaN(parsed.getTime())) return parsed;
      }
      return null;
    }

    function recolhaRecordInPeriod(record) {
      const createdAt = parseRecolhaCreatedAt(record);
      const start = state.recolhasFilter.start ? new Date(`${state.recolhasFilter.start}T00:00:00`) : null;
      const end = state.recolhasFilter.end ? new Date(`${state.recolhasFilter.end}T23:59:59.999`) : null;
      if ((start || end) && !createdAt) return false;
      if (start && createdAt < start) return false;
      if (end && createdAt > end) return false;
      return true;
    }

    function filteredRecolhaRecords() {
      const payload = state.recolhas && typeof state.recolhas === "object" ? state.recolhas : { operations: [] };
      return flattenRecolhaOperations(payload.operations).filter(recolhaRecordInPeriod);
    }

    function groupRecolhasByOperation(records) {
      const grouped = new Map();
      for (const record of records) {
        const revenda = cleanDisplayText(record._operation || record.revenda || "Sem operação");
        if (!grouped.has(revenda)) {
          grouped.set(revenda, { revenda, total: 0, abertas: 0, lancadas: 0, recolhidas: 0, nao_recolhidas: 0, records: [] });
        }
        const bucket = grouped.get(revenda);
        bucket.total += 1;
        bucket[recolhaBucket(record)] += 1;
        bucket.records.push(record);
      }
      return Array.from(grouped.values()).sort((a, b) => String(a.revenda).localeCompare(String(b.revenda)));
    }

    function updateRecolhasPeriodFilter() {
      state.recolhasFilter.start = E.recolhasStartDate ? E.recolhasStartDate.value : "";
      state.recolhasFilter.end = E.recolhasEndDate ? E.recolhasEndDate.value : "";
      renderRecolhas();
    }

    function clearRecolhasPeriodFilter() {
      if (E.recolhasStartDate) E.recolhasStartDate.value = "";
      if (E.recolhasEndDate) E.recolhasEndDate.value = "";
      state.recolhasFilter = { start: "", end: "" };
      renderRecolhas();
    }

    function renderRecolhasDashboard(records, operations) {
      const totals = { total: records.length, abertas: 0, lancadas: 0, recolhidas: 0, nao_recolhidas: 0 };
      const reasons = new Map();
      for (const record of records) {
        const bucket = recolhaBucket(record);
        totals[bucket] += 1;
        if (bucket === "nao_recolhidas") {
          const reason = cleanDisplayText(record.motivo_caixa_noturno || "").trim() || "Sem motivo informado";
          reasons.set(reason, (reasons.get(reason) || 0) + 1);
        }
      }
      const pending = totals.total - totals.recolhidas;
      const recolhidasPct = totals.total ? Math.round((totals.recolhidas / totals.total) * 100) : 0;
      if (E.recolhasDashboardCards) {
        E.recolhasDashboardCards.innerHTML = [
          ["Total", totals.total, "solicitações no período"],
          ["Pendentes", pending, "não finalizadas"],
          ["Abertas", totals.abertas, "aguardando faturista"],
          ["Lançadas", totals.lancadas, "aguardando caixa"],
          ["Recolhidas", totals.recolhidas, `${recolhidasPct}% do período`],
          ["Não recolhidas", totals.nao_recolhidas, "com pendência no caixa"]
        ].map(([label, value, sub]) => `
          <article class="recolha-dashboard-card">
            <span class="label">${escapeHtml(label)}</span>
            <span class="value">${formatNumber(value)}</span>
            <span class="sub">${escapeHtml(sub)}</span>
          </article>
        `).join("");
      }
      if (E.recolhasReasonList) {
        const reasonRows = Array.from(reasons.entries()).sort((a, b) => b[1] - a[1]).slice(0, 6);
        E.recolhasReasonList.innerHTML = reasonRows.length
          ? reasonRows.map(([reason, total]) => `<div class="recolha-insight-row"><span>${escapeHtml(reason)}</span><strong>${formatNumber(total)}</strong></div>`).join("")
          : '<div class="text-secondary">Sem motivos registrados no período.</div>';
      }
      if (E.recolhasOperationSummary) {
        E.recolhasOperationSummary.innerHTML = operations.length
          ? operations.map(operation => `
            <div class="recolha-insight-row">
              <span>${escapeHtml(cleanDisplayText(operation.revenda || "-"))}</span>
              <strong>${formatNumber(operation.recolhidas || 0)}/${formatNumber(operation.total || 0)} recolhidas</strong>
            </div>
          `).join("")
          : '<div class="text-secondary">Sem operações no período.</div>';
      }
      if (E.recolhasPeriodLabel) {
        const start = state.recolhasFilter.start ? formatDate(state.recolhasFilter.start) : "inicio";
        const end = state.recolhasFilter.end ? formatDate(state.recolhasFilter.end) : "hoje";
        E.recolhasPeriodLabel.textContent = state.recolhasFilter.start || state.recolhasFilter.end
          ? `Dashboard filtrado de ${start} até ${end}.`
          : "Dashboard considerando todas as solicitações visíveis.";
      }
    }

    function renderRecolhas() {
      const payload = state.recolhas && typeof state.recolhas === "object" ? state.recolhas : { total: 0, operations: [] };
      const allRecords = flattenRecolhaOperations(payload.operations);
      const filteredRecords = allRecords.filter(recolhaRecordInPeriod);
      const operations = groupRecolhasByOperation(filteredRecords);
      if (E.recolhasCount) {
        E.recolhasCount.textContent = `${formatNumber(filteredRecords.length)} de ${formatNumber(allRecords.length)} solicitação(ões)`;
        E.recolhasCount.className = filteredRecords.length > 0 ? "pill ok" : "pill";
      }
      renderRecolhasDashboard(filteredRecords, operations);
      if (!E.recolhasContainer) return;
      if (!operations.length) {
        E.recolhasContainer.innerHTML = '<div class="text-center py-3 text-secondary">Nenhuma solicitação de recolha encontrada no período.</div>';
        return;
      }
      E.recolhasContainer.innerHTML = operations.map(operation => {
        const records = Array.isArray(operation.records) ? operation.records : [];
        const revenda = cleanDisplayText(operation.revenda || "Sem operação");
        const rows = records.length ? records.map(record => renderRecolhaRow(record)).join("") : '<tr><td colspan="13" class="text-center py-3 text-secondary">Sem solicitações nessa operação</td></tr>';
        return `
          <article class="recolha-operation">
            <header class="recolha-operation-head">
              <div>
                <h3 class="h6 fw-bold mb-1">Operação ${escapeHtml(revenda)}</h3>
                <div class="small text-secondary">Tabela própria da filial/revenda para acompanhamento financeiro.</div>
              </div>
              <div class="d-flex flex-wrap gap-2">
                <span class="pill">Total ${formatNumber(operation.total || records.length)}</span>
                <span class="pill">Abertas ${formatNumber(operation.abertas || 0)}</span>
                <span class="pill">Lançadas ${formatNumber(operation.lancadas || 0)}</span>
                <span class="pill ok">Recolhidas ${formatNumber(operation.recolhidas || 0)}</span>
                <span class="pill warn">Não recolhidas ${formatNumber(operation.nao_recolhidas || 0)}</span>
              </div>
              <div class="d-flex flex-wrap gap-2 align-items-center">
                <select class="form-select form-select-sm recolha-bulk-status" style="width: 150px;">
                  ${renderOptions(RECOLHA_STATUS_OPTIONS, "Recolhido")}
                </select>
                <select class="form-select form-select-sm recolha-bulk-motivo" style="width: 220px;">
                  ${renderOptions(RECOLHA_MOTIVO_OPTIONS, "", "Sem motivo")}
                </select>
                <input class="form-control form-control-sm recolha-partial-detail recolha-bulk-partial-detail d-none" style="width: 260px;" placeholder="O que foi recolhido?">
                <button class="btn btn-outline-primary btn-sm" onclick="bulkUpdateRecolhas(this)">
                  <i class="bi bi-check2-square me-1"></i>Fechar selecionadas
                </button>
              </div>
            </header>
            <div class="table-scroll" style="max-height: 380px;">
              <table class="table table-sm table-hover align-middle mb-0 recolha-table">
                <thead>
                  <tr class="text-uppercase small text-secondary">
                    <th class="ps-3"><input class="form-check-input recolha-select-all" type="checkbox" onchange="toggleRecolhaOperationSelection(this)"></th>
                    <th>Cliente</th>
                    <th>Solicitação</th>
                    <th>Pedido</th>
                    <th>Faturista</th>
                    <th>Motorista</th>
                    <th>Placa</th>
                    <th>Mapa</th>
                    <th>Caixa</th>
                    <th>Motivo</th>
                    <th>Status</th>
                    <th>Baixa base</th>
                    <th class="text-end pe-3">Ação</th>
                  </tr>
                </thead>
                <tbody>${rows}</tbody>
              </table>
            </div>
          </article>
        `;
      }).join("");
    }

    function renderRecolhaRow(record) {
      const id = String(record.id || "");
      const safeId = escapeHtml(id);
      const lancado = normalizeRecolhaStatus(record.lancado_faturista || "Nok") === "Ok" ? "Ok" : "Nok";
      const status = normalizeRecolhaStatus(record.status_caixa_noturno || "Nao Recolhido");
      const statusValue = status === "Recolhido" ? "Recolhido" : "Nao Recolhido";
      const requesterName = cleanDisplayText(record.solicitante_nome || record.solicitante || "-");
      const motivoInfo = splitRecolhaPartialReason(record.motivo_caixa_noturno || "");
      return `
        <tr data-recolha-id="${safeId}">
          <td class="ps-3"><input class="form-check-input recolha-select" type="checkbox" value="${safeId}"></td>
          <td>
            <strong>NB ${escapeHtml(record.nb || "-")}</strong>
            <div class="small text-secondary">Setor ${escapeHtml(record.setor || "-")} | RN ${escapeHtml(record.rn || "-")}</div>
            <div class="small text-secondary">${escapeHtml(cleanDisplayText(record.cidade || "-"))}</div>
          </td>
          <td>
            <div>${escapeHtml(record.criado_em || "-")}</div>
            <div class="small text-secondary">Solicitante: ${escapeHtml(requesterName)}</div>
          </td>
          <td>
            <div>${escapeHtml(cleanDisplayText(record.comodato || "-"))}</div>
            ${record.obs ? `<div class="small text-secondary">OBS.: ${escapeHtml(cleanDisplayText(record.obs))}</div>` : ""}
            <div class="small mono text-secondary">ID ${escapeHtml(id || "-")}</div>
          </td>
          <td>
            <select class="form-select form-select-sm recolha-lancado">
              <option value="Nok" ${lancado === "Nok" ? "selected" : ""}>Nok</option>
              <option value="Ok" ${lancado === "Ok" ? "selected" : ""}>Ok</option>
            </select>
          </td>
          <td><input class="form-control form-control-sm recolha-motorista" value="${escapeHtml(cleanDisplayText(record.motorista_faturista || ""))}" placeholder="Motorista"></td>
          <td><input class="form-control form-control-sm recolha-placa" value="${escapeHtml(cleanDisplayText(record.placa_faturista || ""))}" placeholder="Placa"></td>
          <td><input class="form-control form-control-sm recolha-mapa" value="${escapeHtml(cleanDisplayText(record.mapa_faturista || ""))}" placeholder="Mapa"></td>
          <td>
            <select class="form-select form-select-sm recolha-status">
              ${renderOptions(RECOLHA_STATUS_OPTIONS, statusValue)}
            </select>
          </td>
          <td>
            <select class="form-select form-select-sm recolha-motivo">
              ${renderOptions(RECOLHA_MOTIVO_OPTIONS, motivoInfo.option || "", "Sem motivo")}
            </select>
            <input class="form-control form-control-sm recolha-partial-detail ${motivoInfo.isPartial ? "" : "d-none"}" value="${escapeHtml(motivoInfo.detail || "")}" placeholder="O que foi recolhido?">
          </td>
          <td>${recolhaStatusBadge(statusValue === "Recolhido" ? "Recolhido" : lancado)}</td>
          <td>${recolhaBaixaBadge(record)}</td>
          <td class="text-end pe-3">
            <div class="d-flex gap-1 justify-content-end">
              <button class="btn btn-primary btn-sm recolha-save-btn" onclick="saveRecolhaRow('${safeId}')"><i class="bi bi-check2 me-1"></i>Salvar</button>
              <button class="btn btn-outline-danger btn-sm recolha-delete-btn" onclick="deleteRecolhaRow('${safeId}')"><i class="bi bi-trash3"></i></button>
            </div>
          </td>
        </tr>
      `;
    }

    function toggleRecolhaOperationSelection(source) {
      const article = source ? source.closest(".recolha-operation") : null;
      if (!article) return;
      for (const checkbox of article.querySelectorAll(".recolha-select")) {
        checkbox.checked = Boolean(source.checked);
      }
    }

    async function bulkUpdateRecolhas(source) {
      updateTokens();
      if (!hasPanelAuth()) { addLog("Sessão do painel não validada.", "warn"); return; }
      if (!state.panel || !state.panel.mode) {
        try { await syncPanelSession(); }
        catch (err) { addLog(`Falha ao validar token: ${err.message}`, "err"); return; }
      }
      const article = source ? source.closest(".recolha-operation") : null;
      if (!article) return;
      const ids = Array.from(article.querySelectorAll(".recolha-select:checked")).map(item => item.value).filter(Boolean);
      if (!ids.length) {
        addLog("Selecione pelo menos uma recolha para fechar em lote.", "warn");
        return;
      }
      let motivoCaixa;
      try {
        motivoCaixa = buildRecolhaMotivoValue(article);
      } catch (err) {
        addLog(err.message || "Informe o detalhe da recolha parcial.", "warn");
        return;
      }
      const payload = {
        ids,
        status_caixa_noturno: article.querySelector(".recolha-bulk-status")?.value || "Recolhido",
        motivo_caixa_noturno: motivoCaixa
      };
      const previousLabel = source ? source.innerHTML : "";
      if (source) {
        source.disabled = true;
        source.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Fechando';
      }
      try {
        const result = await req(CONFIG.endpoints.recolhas.bulk, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          timeoutMs: 60000
        });
        const errors = Array.isArray(result.errors) ? result.errors.length : 0;
        addLog(`Fechamento em lote: ${formatNumber(result.updated || 0)} atualizada(s), ${formatNumber(errors)} erro(s).`, errors ? "warn" : "ok");
        await syncRecolhas({ silent: true });
      } catch (err) {
        addLog(`Falha no fechamento em lote: ${err.message}`, "err");
      } finally {
        if (source) {
          source.disabled = false;
          source.innerHTML = previousLabel;
        }
      }
    }

    async function syncRecolhas({ silent = true } = {}) {
      updateTokens();
      if (!hasPanelAuth()) {
        if (!silent) addLog("Sessão do painel não validada.", "warn");
        return false;
      }
      try {
        if (!state.panel || !state.panel.mode) await syncPanelSession();
        const payload = await req(CONFIG.endpoints.recolhas.list, { timeoutMs: 30000 });
        state.recolhas = payload && typeof payload === "object"
          ? { total: Number(payload.total || 0), operations: Array.isArray(payload.operations) ? payload.operations : [] }
          : { total: 0, operations: [] };
        renderRecolhas();
        if (!silent) addLog("Recolhas atualizadas.", "ok");
        return true;
      } catch (err) {
        if (!silent) addLog(`Falha ao carregar recolhas: ${err.message}`, "err");
        renderRecolhas();
        return false;
      }
    }

    async function exportRecolhasCsv() {
      updateTokens();
      if (!hasPanelAuth()) { addLog("Sessão do painel não validada.", "warn"); return; }
      if (!state.panel || !state.panel.mode) {
        try { await syncPanelSession(); }
        catch (err) { addLog(`Falha ao validar token: ${err.message}`, "err"); return; }
      }
      const params = new URLSearchParams();
      if (E.recolhasStartDate && E.recolhasStartDate.value) params.set("start_date", E.recolhasStartDate.value);
      if (E.recolhasEndDate && E.recolhasEndDate.value) params.set("end_date", E.recolhasEndDate.value);
      const url = `${CONFIG.api}${CONFIG.endpoints.recolhas.exportCsv}${params.toString() ? `?${params.toString()}` : ""}`;
      const btn = E.recolhasExportBtn;
      const previousLabel = btn ? btn.innerHTML : "";
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Exportando';
      }
      try {
        const headers = {};
        if (state.tokens.api) headers["x-api-token"] = state.tokens.api;
        if (state.tokens.admin) headers["x-admin-token"] = state.tokens.admin;
        const response = await fetch(url, { credentials: "same-origin", headers });
        if (!response.ok) {
          const errPayload = await response.json().catch(() => null);
          throw new Error(errPayload && errPayload.detail ? errPayload.detail : `HTTP ${response.status}`);
        }
        const blob = await response.blob();
        const disposition = response.headers.get("content-disposition") || "";
        const matchedName = disposition.match(/filename=\"?([^\";]+)\"?/i);
        const filename = matchedName && matchedName[1] ? matchedName[1] : "relatorio_recolhas.csv";
        const blobUrl = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = blobUrl;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(blobUrl);
        addLog("Relatório de recolhas exportado.", "ok");
      } catch (err) {
        addLog(`Falha ao exportar relatório de recolhas: ${err.message}`, "err");
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = previousLabel;
        }
      }
    }

    async function importRecolhasCsv() {
      updateTokens();
      if (!hasPanelAuth()) { addLog("Sessão do painel não validada.", "warn"); return; }
      if (!state.panel || !state.panel.mode) {
        try { await syncPanelSession(); }
        catch (err) { addLog(`Falha ao validar token: ${err.message}`, "err"); return; }
      }
      const file = E.recolhasImportFile && E.recolhasImportFile.files ? E.recolhasImportFile.files[0] : null;
      if (!file) {
        addLog("Selecione um CSV de recolhas para importar.", "warn");
        return;
      }
      if (!String(file.name || "").toLowerCase().endsWith(".csv")) {
        addLog("O arquivo de recolhas deve ser CSV.", "warn");
        return;
      }
      const scopeText = state.panel && state.panel.isAdmin
        ? "todas as recolhas atuais"
        : "as recolhas das filiais liberadas para este token";
      const confirmed = await askConfirmation(`Importar ${file.name}? Isso vai substituir ${scopeText} pelo conteúdo do CSV.`);
      if (!confirmed) return;

      const btn = E.recolhasImportBtn;
      const previousLabel = btn ? btn.innerHTML : "";
      const formData = new FormData();
      formData.append("file", file);
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Importando';
      }
      try {
        const payload = await req(CONFIG.endpoints.recolhas.importCsv, {
          method: "POST",
          body: formData,
          timeoutMs: 120000
        });
        if (E.recolhasImportFile) E.recolhasImportFile.value = "";
        addLog(
          `CSV de recolhas importado: ${formatNumber(payload.imported || 0)} linha(s), ` +
          `${formatNumber(payload.skipped || 0)} fora do escopo, ${formatNumber(payload.preserved || 0)} preservada(s).`,
          "ok"
        );
        await syncRecolhas({ silent: true });
      } catch (err) {
        addLog(`Falha ao importar CSV de recolhas: ${err.message}`, "err");
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = previousLabel;
        }
      }
    }

    async function saveRecolhaRow(id) {
      updateTokens();
      if (!hasPanelAuth()) { addLog("Sessão do painel não validada.", "warn"); return; }
      if (!state.panel || !state.panel.mode) {
        try { await syncPanelSession(); }
        catch (err) { addLog(`Falha ao validar token: ${err.message}`, "err"); return; }
      }
      const row = document.querySelector(`tr[data-recolha-id="${CSS.escape(id)}"]`);
      if (!row) return;
      const btn = row.querySelector(".recolha-save-btn");
      const previousLabel = btn ? btn.innerHTML : "";
      let motivoCaixa;
      try {
        motivoCaixa = buildRecolhaMotivoValue(row);
      } catch (err) {
        addLog(err.message || "Informe o detalhe da recolha parcial.", "warn");
        return;
      }
      const payload = {
        lancado_faturista: row.querySelector(".recolha-lancado")?.value || "Nok",
        motorista_faturista: row.querySelector(".recolha-motorista")?.value || "",
        placa_faturista: row.querySelector(".recolha-placa")?.value || "",
        mapa_faturista: row.querySelector(".recolha-mapa")?.value || "",
        status_caixa_noturno: row.querySelector(".recolha-status")?.value || "Não Recolhido",
        motivo_caixa_noturno: motivoCaixa
      };
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Salvando';
      }
      try {
        await req(`${CONFIG.endpoints.recolhas.update}/${encodeURIComponent(id)}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          timeoutMs: 30000
        });
        addLog(`Recolha ${id.substring(0, 8)} atualizada.`, "ok");
        await syncRecolhas({ silent: true });
      } catch (err) {
        addLog(`Falha ao salvar recolha: ${err.message}`, "err");
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = previousLabel;
        }
      }
    }

    async function deleteRecolhaRow(id) {
      updateTokens();
      if (!hasPanelAuth()) { addLog("Sessão do painel não validada.", "warn"); return; }
      if (!state.panel || !state.panel.mode) {
        try { await syncPanelSession(); }
        catch (err) { addLog(`Falha ao validar token: ${err.message}`, "err"); return; }
      }
      const confirmed = await askConfirmation(`Apagar a solicitação de recolha ${id.substring(0, 8)}? Essa ação remove a linha do CSV.`);
      if (!confirmed) return;
      const row = document.querySelector(`tr[data-recolha-id="${CSS.escape(id)}"]`);
      const btn = row ? row.querySelector(".recolha-delete-btn") : null;
      const previousLabel = btn ? btn.innerHTML : "";
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
      }
      try {
        await req(`${CONFIG.endpoints.recolhas.delete}/${encodeURIComponent(id)}`, {
          method: "DELETE",
          timeoutMs: 30000
        });
        addLog(`Recolha ${id.substring(0, 8)} apagada.`, "ok");
        await syncRecolhas({ silent: true });
      } catch (err) {
        addLog(`Falha ao apagar recolha: ${err.message}`, "err");
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = previousLabel;
        }
      }
    }
