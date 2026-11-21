    function setupPayipPane() {
      const pane = document.getElementById("payipPane");
      if (!pane) return;
      [
        document.getElementById("payipImportPanel"),
        document.getElementById("payipBatchPanel")
      ].forEach(panel => {
        if (panel && panel.parentElement !== pane) pane.appendChild(panel);
      });
    }

    function payipGeneratedFilialValue() {
      const explicitValue = E.payipGeneratedFilial ? String(E.payipGeneratedFilial.value || "").trim() : "";
      if (explicitValue) return explicitValue;
      const importValue = E.payipImportFilial ? String(E.payipImportFilial.value || "").trim() : "";
      if (importValue) return importValue;
      const filiais = state.panel && Array.isArray(state.panel.filiais) ? state.panel.filiais : [];
      return filiais.length === 1 ? String(filiais[0] || "").trim() : "";
    }

    function payipGeneratedStatusText(statusCounts) {
      if (!statusCounts || typeof statusCounts !== "object") return "-";
      return Object.entries(statusCounts)
        .filter(([, value]) => Number(value || 0) > 0)
        .sort((a, b) => Number(b[1] || 0) - Number(a[1] || 0))
        .slice(0, 4)
        .map(([key, value]) => `${escapeHtml(key || "-")}: ${formatNumber(value)}`)
        .join(" | ") || "-";
    }

    function payipGeneratedActions(batch) {
      const batchId = batch && batch.batch_id ? String(batch.batch_id) : "";
      if (!batchId) return '<span class="text-secondary small">Sem batchId</span>';
      const encodedBatch = escapeHtml(batchId);
      const actionButton = (kind, label, variant) => {
        const isGenerating = state.payipGenerated.generating === `${batchId}:${kind}`;
        const disabled = state.payipGenerated.generating ? "disabled" : "";
        const icon = isGenerating ? '<span class="spinner-border spinner-border-sm me-1"></span>' : "";
        return `<button type="button" class="btn ${variant} btn-sm" ${disabled} onclick="downloadPayipGeneratedBatchFile('${encodedBatch}', '${kind}')">${icon}${label}</button>`;
      };
      const progress = state.payipGenerated.generating && String(state.payipGenerated.generating).startsWith(`${batchId}:`)
        ? '<div class="small text-warning mt-1"><span class="spinner-border spinner-border-sm me-1"></span>Gerando arquivo...</div>'
        : "";
      return `
        <div class="d-flex flex-wrap gap-1">
          ${actionButton("pix", "PIX", "btn-outline-primary")}
          ${actionButton("pix_a_prazo", "PIX a prazo", "btn-outline-primary")}
          ${actionButton("boleto", "Boleto", "btn-outline-secondary")}
        </div>
        ${progress}
      `;
    }

    function renderPayipGeneratedBatches() {
      const payload = state.payipGenerated && state.payipGenerated.payload ? state.payipGenerated.payload : null;
      const loading = Boolean(state.payipGenerated && state.payipGenerated.loading);
      const error = state.payipGenerated && state.payipGenerated.error ? String(state.payipGenerated.error) : "";
      const batches = payload && Array.isArray(payload.batches) ? payload.batches : [];
      if (E.payipGeneratedStatus) {
        if (loading) {
          E.payipGeneratedStatus.textContent = "Atualizando...";
          E.payipGeneratedStatus.className = "pill warn";
        } else if (error) {
          E.payipGeneratedStatus.textContent = "Falha na consulta";
          E.payipGeneratedStatus.className = "pill warn";
        } else if (payload) {
          E.payipGeneratedStatus.textContent = `${formatNumber(payload.items_count || 0)} lote(s) recentes`;
          E.payipGeneratedStatus.className = batches.length ? "pill ok" : "pill";
        } else {
          E.payipGeneratedStatus.textContent = "Aguardando consulta";
          E.payipGeneratedStatus.className = "pill";
        }
      }
      if (E.payipGeneratedRefreshBtn) E.payipGeneratedRefreshBtn.disabled = loading;
      if (E.payipGeneratedHint) {
        const checkedAt = payload && payload.last_checked_at ? `Última consulta: ${formatDateTime(payload.last_checked_at)}.` : "Atualiza automaticamente a cada 60 segundos enquanto a aba PayIP estiver aberta.";
        E.payipGeneratedHint.textContent = checkedAt;
      }
      if (!E.payipGeneratedBody) return;
      if (loading && !payload) {
        E.payipGeneratedBody.innerHTML = '<tr><td colspan="4" class="text-center py-3 text-secondary"><span class="spinner-border spinner-border-sm me-1"></span>Consultando histórico PayIP...</td></tr>';
        return;
      }
      if (error) {
        E.payipGeneratedBody.innerHTML = `<tr><td colspan="4" class="text-danger"><strong>Falha na consulta:</strong> ${escapeHtml(error)}</td></tr>`;
        return;
      }
      if (!payload) {
        E.payipGeneratedBody.innerHTML = '<tr><td colspan="4" class="text-center py-3 text-secondary">Consulte uma revenda para acompanhar os lotes gerados.</td></tr>';
        return;
      }
      if (!batches.length) {
        E.payipGeneratedBody.innerHTML = '<tr><td colspan="4" class="text-center py-3 text-secondary">Nenhuma cobrança recente encontrada para essa revenda.</td></tr>';
        return;
      }
      E.payipGeneratedBody.innerHTML = batches.slice(0, 12).map(batch => `
        <tr>
          <td class="ps-2"><strong>${escapeHtml(batch.created_label || batch.key || "-")}</strong></td>
          <td>${formatNumber(batch.count || 0)}</td>
          <td><span class="small">${payipGeneratedStatusText(batch.status_counts)}</span></td>
          <td>${payipGeneratedActions(batch)}</td>
        </tr>
      `).join("");
    }

    async function syncPayipGeneratedBatches({ silent = true } = {}) {
      if (!hasPanelAuth()) return false;
      const filial = payipGeneratedFilialValue();
      if (!filial) {
        renderPayipGeneratedBatches();
        if (!silent) addLog("Informe a revenda para consultar os lotes gerados PayIP.", "warn");
        return false;
      }
      if (E.payipGeneratedFilial && !E.payipGeneratedFilial.value) E.payipGeneratedFilial.value = filial;
      const mfaCode = E.payipGeneratedMfaCode ? String(E.payipGeneratedMfaCode.value || "").trim() : "";
      state.payipGenerated.loading = true;
      state.payipGenerated.error = "";
      renderPayipGeneratedBatches();
      try {
        const queryParams = new URLSearchParams();
        queryParams.set("filial", filial);
        queryParams.set("page_size", "50");
        const query = `?${queryParams.toString()}`;
        const extraHeaders = {};
        if (mfaCode) extraHeaders["x-payip-mfa-code"] = mfaCode;
        const payload = await req(`${CONFIG.endpoints.payipImport.generatedBatches}${query}`, { headers: extraHeaders, timeoutMs: 45000 });
        state.payipGenerated.payload = payload;
        state.payipGenerated.lastFilial = filial;
        state.payipGenerated.error = "";
        if (mfaCode && E.payipGeneratedMfaCode) E.payipGeneratedMfaCode.value = "";
        renderPayipGeneratedBatches();
        if (!silent) addLog(`Log de lotes PayIP atualizado: ${formatNumber(payload.items_count || 0)} lote(s).`, "ok");
        startPayipGeneratedPolling();
        return true;
      } catch (err) {
        state.payipGenerated.error = err.message || "Falha ao consultar histórico PayIP.";
        renderPayipGeneratedBatches();
        if (!silent) addLog(`Falha ao consultar lotes PayIP: ${err.message}`, "warn");
        return false;
      } finally {
        state.payipGenerated.loading = false;
        renderPayipGeneratedBatches();
      }
    }

    async function startPayipGeneratedPolling() {
      if (state.payipGenerated.polling) return;
      state.payipGenerated.polling = true;
      try {
        while (currentActiveTabId() === "payipTab") {
          await new Promise(resolve => setTimeout(resolve, 60000));
          if (currentActiveTabId() !== "payipTab") break;
          await syncPayipGeneratedBatches({ silent: true });
        }
      } finally {
        state.payipGenerated.polling = false;
      }
    }

    function currentPayipImportPayload() {
      return {
        filial: E.payipImportFilial ? String(E.payipImportFilial.value || "").trim() : "",
        start_date: E.payipImportStartDate ? String(E.payipImportStartDate.value || "").trim() : "",
        end_date: E.payipImportEndDate ? String(E.payipImportEndDate.value || "").trim() : "",
        auto_create_clients: false,
        mfa_code: E.payipImportMfaCode ? String(E.payipImportMfaCode.value || "").trim() : ""
      };
    }

    function payipImportSignature(payload) {
      return JSON.stringify({
        filial: String(payload && payload.filial || ""),
        start_date: String(payload && payload.start_date || ""),
        end_date: String(payload && payload.end_date || "")
      });
    }

    function resetPayipImportValidation() {
      if (!state.payipImport) return;
      state.payipImport.validation = null;
      state.payipImport.validationPayload = null;
      state.payipImport.loading = false;
      state.payipImport.error = "";
      renderPayipImport();
    }

    function payipImportItemAmount(item) {
      if (!item || typeof item !== "object") return "0";
      return item.total || item.value || item.amount || item.valor || "0";
    }

    function payipImportItemDueDate(item) {
      if (!item || typeof item !== "object") return "";
      return item.dueDate || item.due_date || item.vencimento || "";
    }

    function renderPayipImport() {
      const validation = state.payipImport && state.payipImport.validation ? state.payipImport.validation : null;
      const items = validation && Array.isArray(validation.items) ? validation.items : [];
      const missing = validation && Array.isArray(validation.missing_client_codes) ? validation.missing_client_codes : [];
      const creation = validation && validation.client_creation ? validation.client_creation : { created: [], not_found: [], failed: [] };
      const created = Array.isArray(creation.created) ? creation.created : [];
      const notFound = Array.isArray(creation.not_found) ? creation.not_found : [];
      const failed = Array.isArray(creation.failed) ? creation.failed : [];
      const loading = Boolean(state.payipImport && state.payipImport.loading);
      const error = state.payipImport && state.payipImport.error ? String(state.payipImport.error) : "";
      const canRun = Boolean(validation && state.payipImport.validationPayload === payipImportSignature(currentPayipImportPayload()) && !missing.length);
      if (E.payipImportStatus) {
        if (loading) {
          E.payipImportStatus.textContent = "Validando...";
          E.payipImportStatus.className = "pill warn";
        } else if (error) {
          E.payipImportStatus.textContent = "Falha na validação";
          E.payipImportStatus.className = "pill warn";
        } else if (validation) {
          E.payipImportStatus.textContent = missing.length
            ? `Clientes faltantes: ${missing.length}`
            : `Validado: ${items.length} cobrança(s)`;
          E.payipImportStatus.className = missing.length ? "pill warn" : "pill ok";
        } else {
          E.payipImportStatus.textContent = "Aguardando validação";
          E.payipImportStatus.className = "pill";
        }
      }
      if (E.payipImportValidateBtn) E.payipImportValidateBtn.disabled = loading;
      if (E.payipImportRunBtn) E.payipImportRunBtn.disabled = loading || !canRun;
      if (!E.payipImportBody) return;
      if (loading) {
        E.payipImportBody.innerHTML = '<tr><td colspan="5" class="text-center py-3 text-secondary"><span class="spinner-border spinner-border-sm me-1"></span>Validando importação PayIP...</td></tr>';
        return;
      }
      if (error) {
        E.payipImportBody.innerHTML = `<tr><td colspan="5" class="text-danger"><strong>Falha na validação:</strong> ${escapeHtml(error)}</td></tr>`;
        return;
      }
      if (!validation) {
        E.payipImportBody.innerHTML = '<tr><td colspan="5" class="text-center py-3 text-secondary">Valide a importação automatizada para começar.</td></tr>';
        return;
      }
      const helperRows = [];
      if (missing.length) {
        helperRows.push(`
          <tr>
            <td colspan="5" class="text-danger">
              <div class="d-flex flex-wrap align-items-center justify-content-between gap-2">
                <div><strong>Clientes não encontrados na PayIP:</strong> ${escapeHtml(missing.slice(0, 40).join(", "))}${missing.length > 40 ? "..." : ""}</div>
                <button type="button" class="btn btn-outline-warning btn-sm" onclick="createPayipImportClients()"><i class="bi bi-person-plus me-1"></i>Criar cadastros</button>
              </div>
            </td>
          </tr>
        `);
      }
      if (created.length) helperRows.push(`<tr><td colspan="5" class="text-success"><strong>Criados pela dClientes:</strong> ${escapeHtml(created.join(", "))}</td></tr>`);
      if (notFound.length) helperRows.push(`<tr><td colspan="5" class="text-danger"><strong>Não encontrados na dClientes:</strong> ${escapeHtml(notFound.join(", "))}</td></tr>`);
      if (failed.length) helperRows.push(`<tr><td colspan="5" class="text-danger"><strong>Falhas ao criar:</strong> ${escapeHtml(failed.join(" | "))}</td></tr>`);
      const itemRows = items.slice(0, 80).map(item => `
        <tr>
          <td class="ps-2"><strong>${escapeHtml(item.clientCode || item.client_code || item.nb || "-")}</strong></td>
          <td>${escapeHtml(item.invoice || item.notaFiscal || item.nf || "-")}</td>
          <td>${escapeHtml(formatMoneyText(payipImportItemAmount(item)))}</td>
          <td>${escapeHtml(formatDate(payipImportItemDueDate(item)))}</td>
          <td><span class="badge text-bg-light">${validation.imported ? "importado" : "validado"}</span></td>
        </tr>
      `);
      if (items.length > 80) itemRows.push(`<tr><td colspan="5" class="text-center text-secondary small">Mostrando 80 de ${formatNumber(items.length)} cobrança(s).</td></tr>`);
      if (!helperRows.length && !itemRows.length) {
        E.payipImportBody.innerHTML = '<tr><td colspan="5" class="text-center py-3 text-secondary">Nenhuma cobrança retornada pela PayIP.</td></tr>';
        return;
      }
      E.payipImportBody.innerHTML = helperRows.concat(itemRows).join("");
    }

    async function validatePayipImport() {
      updateTokens();
      if (!hasPanelAuth()) { addLog("Sessão do painel não validada.", "warn"); return; }
      const payload = currentPayipImportPayload();
      if (!payload.filial || !payload.start_date || !payload.end_date) {
        addLog("Informe revenda, data inicial e data final da importação PayIP.", "warn");
        return;
      }
      const btn = E.payipImportValidateBtn;
      const previousLabel = btn ? btn.innerHTML : "";
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Validando';
      }
      state.payipImport.loading = true;
      state.payipImport.error = "";
      renderPayipImport();
      try {
        const result = await req(CONFIG.endpoints.payipImport.validate, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          timeoutMs: 90000
        });
        state.payipImport.validation = result;
        state.payipImport.validationPayload = payipImportSignature(payload);
        state.payipImport.error = "";
        renderPayipImport();
        const missing = Array.isArray(result.missing_client_codes) ? result.missing_client_codes.length : 0;
        addLog(missing ? `PayIP validou com ${missing} cliente(s) faltando.` : `Importação PayIP validada: ${result.items_count || 0} cobrança(s).`, missing ? "warn" : "ok");
      } catch (err) {
        state.payipImport.validation = null;
        state.payipImport.validationPayload = null;
        state.payipImport.error = err.message || "Falha ao validar importação PayIP.";
        renderPayipImport();
        addLog(`Falha ao validar importação PayIP: ${err.message}`, "err");
      } finally {
        state.payipImport.loading = false;
        renderPayipImport();
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = previousLabel;
        }
      }
    }

    async function createPayipImportClients() {
      updateTokens();
      if (!hasPanelAuth()) { addLog("Sessão do painel não validada.", "warn"); return; }
      const validation = state.payipImport && state.payipImport.validation ? state.payipImport.validation : null;
      const missing = validation && Array.isArray(validation.missing_client_codes) ? validation.missing_client_codes : [];
      if (!missing.length) {
        addLog("Não ha clientes faltantes para criar.", "warn");
        return;
      }
      const payload = currentPayipImportPayload();
      if (!payload.filial || !payload.start_date || !payload.end_date) {
        addLog("Informe revenda, data inicial e data final antes de criar clientes PayIP.", "warn");
        return;
      }
      const confirmed = await askConfirmation(`Criar ${missing.length} cadastro(s) na PayIP usando a dClientes?`);
      if (!confirmed) return;
      payload.missing_client_codes = missing;
      state.payipImport.loading = true;
      state.payipImport.error = "";
      renderPayipImport();
      try {
        const result = await req(CONFIG.endpoints.payipImport.createClients, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          timeoutMs: 120000
        });
        state.payipImport.validation = result;
        state.payipImport.validationPayload = payipImportSignature(payload);
        state.payipImport.error = "";
        renderPayipImport();
        const creation = result.client_creation || {};
        const created = Array.isArray(creation.created) ? creation.created.length : 0;
        const failed = Array.isArray(creation.failed) ? creation.failed.length : 0;
        const notFound = Array.isArray(creation.not_found) ? creation.not_found.length : 0;
        const stillMissing = Array.isArray(result.missing_client_codes) ? result.missing_client_codes.length : 0;
        addLog(`Criação PayIP finalizada: ${created} criado(s), ${notFound} não encontrado(s) na dClientes, ${failed} falha(s), ${stillMissing} ainda faltante(s).`, stillMissing || failed || notFound ? "warn" : "ok");
      } catch (err) {
        state.payipImport.error = err.message || "Falha ao criar clientes PayIP.";
        renderPayipImport();
        addLog(`Falha ao criar clientes PayIP: ${err.message}`, "err");
      } finally {
        state.payipImport.loading = false;
        renderPayipImport();
      }
    }

    async function runPayipImport() {
      updateTokens();
      if (!hasPanelAuth()) { addLog("Sessão do painel não validada.", "warn"); return; }
      const payload = currentPayipImportPayload();
      if (!state.payipImport.validation || state.payipImport.validationPayload !== payipImportSignature(payload)) {
        addLog("Valide a importação PayIP antes de confirmar.", "warn");
        return;
      }
      const missing = Array.isArray(state.payipImport.validation.missing_client_codes) ? state.payipImport.validation.missing_client_codes : [];
      if (missing.length) {
        addLog("Crie os cadastros faltantes antes de importar.", "warn");
        return;
      }
      if (!payload.mfa_code) {
        addLog("Informe o token MFA PayIP para confirmar a importação.", "warn");
        return;
      }
      const total = state.payipImport.validation.items_count || (Array.isArray(state.payipImport.validation.items) ? state.payipImport.validation.items.length : 0);
      const confirmed = await askConfirmation(`Confirmar importação PayIP da revenda ${payload.filial} com ${total} cobrança(s)?`);
      if (!confirmed) return;
      const btn = E.payipImportRunBtn;
      const previousLabel = btn ? btn.innerHTML : "";
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Importando';
      }
      try {
        const result = await req(CONFIG.endpoints.payipImport.run, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          timeoutMs: 120000
        });
        state.payipImport.validation = result;
        state.payipImport.validationPayload = payipImportSignature(payload);
        if (E.payipImportMfaCode) E.payipImportMfaCode.value = "";
        renderPayipImport();
        addLog(`Importação PayIP confirmada: ${result.items_count || 0} cobrança(s).`, "ok");
      } catch (err) {
        addLog(`Falha ao confirmar importação PayIP: ${err.message}`, "err");
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = previousLabel;
        }
      }
    }

    function currentPayipBatchPayload() {
      return {
        raw_text: E.payipBatchText ? E.payipBatchText.value : "",
        use_default_rate: Boolean(E.payipBatchDefaultRate && E.payipBatchDefaultRate.checked),
        use_default_interest: Boolean(E.payipBatchDefaultInterest && E.payipBatchDefaultInterest.checked),
        include_nb: Boolean(E.payipBatchIncludeNb && E.payipBatchIncludeNb.checked),
        include_nf: Boolean(E.payipBatchIncludeNf && E.payipBatchIncludeNf.checked),
        auto_create_clients: Boolean(E.payipBatchAutoCreate && E.payipBatchAutoCreate.checked),
        mfa_code: E.payipBatchMfaCode ? String(E.payipBatchMfaCode.value || "").trim() : ""
      };
    }

    function payipBatchPreviewSignature(payload) {
      return JSON.stringify({
        raw_text: String(payload && payload.raw_text || ""),
        use_default_rate: Boolean(payload && payload.use_default_rate),
        use_default_interest: Boolean(payload && payload.use_default_interest),
        include_nb: Boolean(payload && payload.include_nb),
        include_nf: Boolean(payload && payload.include_nf),
        auto_create_clients: Boolean(payload && payload.auto_create_clients)
      });
    }

    function resetPayipBatchPreview() {
      if (!state.payipBatch) return;
      state.payipBatch.preview = null;
      state.payipBatch.previewPayload = null;
      renderPayipBatch();
    }

    function renderPayipBatch() {
      const job = state.payipBatch && state.payipBatch.job ? state.payipBatch.job : null;
      const preview = state.payipBatch && state.payipBatch.preview ? state.payipBatch.preview : null;
      const status = job && job.status ? String(job.status) : "";
      const running = status === "queued" || status === "running" || Boolean(state.payipBatch && state.payipBatch.state && state.payipBatch.state.running);
      if (E.payipBatchStatus) {
        if (job && job.job_id) {
          const processed = Number(job.processed || 0);
          const total = Number(job.total || 0);
          const success = Number(job.success || 0);
          const failed = Number(job.failed || 0);
          E.payipBatchStatus.textContent = running ? `Lote em andamento: ${processed}/${total}` : `Último lote: ${success} ok, ${failed} erro(s)`;
          E.payipBatchStatus.className = running ? "pill warn" : failed > 0 ? "pill warn" : "pill ok";
        } else if (preview && Array.isArray(preview.items)) {
          E.payipBatchStatus.textContent = `Lote validado: ${preview.items.length} cobrança(s)`;
          E.payipBatchStatus.className = "pill ok";
        } else {
          E.payipBatchStatus.textContent = "Aguardando lote";
          E.payipBatchStatus.className = "pill";
        }
      }
      if (E.payipBatchRunBtn) E.payipBatchRunBtn.disabled = running || !(preview && Array.isArray(preview.items) && preview.items.length);
      if (E.payipBatchPreviewBtn) E.payipBatchPreviewBtn.disabled = running;

      const results = job && Array.isArray(job.results) ? job.results : [];
      const rows = results.length ? results : preview && Array.isArray(preview.items) ? preview.items : [];
      if (!E.payipBatchBody) return;
      if (!rows.length) {
        E.payipBatchBody.innerHTML = '<tr><td colspan="6" class="text-center py-3 text-secondary">Valide um lote para começar.</td></tr>';
        return;
      }
      E.payipBatchBody.innerHTML = rows.map(item => {
        const itemId = item.item_id || "";
        const pix = item.pix_code || "";
        const canTryPdf = Boolean(item.pdf_available || item.payment_id);
        const statusText = item.status || (results.length ? "pendente" : "validado");
        const statusClass = statusText === "success" ? "text-bg-success" : statusText === "failed" ? "text-bg-danger" : "text-bg-light";
        const creation = item.client_creation && typeof item.client_creation === "object" ? item.client_creation : null;
        const creationText = creation && Array.isArray(creation.created) && creation.created.length ? '<div class="small text-success">Cliente criado pela dClientes</div>' : "";
        return `
          <tr>
            <td class="ps-2">${escapeHtml(String(item.line_number || ""))}</td>
            <td><strong>${escapeHtml(item.filial || "-")}</strong> / NB ${escapeHtml(item.nb || "-")}<div class="small text-secondary">${escapeHtml(item.client_name || item.description || "")}</div>${creationText}</td>
            <td>${escapeHtml(formatMoneyText(item.amount || "0"))}<div class="small text-secondary">Venc. ${escapeHtml(formatDate(item.due_date || ""))}</div></td>
            <td><span class="badge ${statusClass}">${escapeHtml(statusText)}</span>${item.error ? `<div class="small text-danger mt-1">${escapeHtml(item.error)}</div>` : ""}</td>
            <td>${pix ? `<button class="btn btn-outline-primary btn-sm" onclick="copyPayipBatchPix('${escapeHtml(itemId)}')"><i class="bi bi-clipboard me-1"></i>Copiar</button>` : '<span class="text-secondary small">-</span>'}</td>
            <td>${canTryPdf ? `<button class="btn btn-outline-success btn-sm" onclick="downloadPayipBatchPdf('${escapeHtml(itemId)}')"><i class="bi bi-file-earmark-pdf me-1"></i>${item.pdf_available ? "PDF" : "Gerar PDF"}</button>` : '<span class="text-secondary small">-</span>'}</td>
          </tr>
        `;
      }).join("");
    }

    async function previewPayipBatch() {
      updateTokens();
      if (!hasPanelAuth()) { addLog("Sessão do painel não validada.", "warn"); return; }
      const payload = currentPayipBatchPayload();
      payload.mfa_code = "";
      if (!String(payload.raw_text || "").trim()) { addLog("Cole o lote PayIP antes de validar.", "warn"); return; }
      const btn = E.payipBatchPreviewBtn;
      const previousLabel = btn ? btn.innerHTML : "";
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Validando';
      }
      try {
        const result = await req(CONFIG.endpoints.payipBatch.preview, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          timeoutMs: 60000
        });
        state.payipBatch.preview = result;
        state.payipBatch.previewPayload = payipBatchPreviewSignature(payload);
        state.payipBatch.job = null;
        renderPayipBatch();
        addLog(`Lote PayIP validado: ${result.total || 0} cobrança(s).`, "ok");
      } catch (err) {
        state.payipBatch.preview = null;
        state.payipBatch.previewPayload = null;
        renderPayipBatch();
        addLog(`Falha ao validar lote PayIP: ${err.message}`, "err");
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = previousLabel;
        }
      }
    }

    async function runPayipBatch() {
      updateTokens();
      if (!hasPanelAuth()) { addLog("Sessão do painel não validada.", "warn"); return; }
      const payload = currentPayipBatchPayload();
      const preview = state.payipBatch.preview;
      const total = preview && Array.isArray(preview.items) ? preview.items.length : 0;
      if (!total) { addLog("Valide o lote PayIP antes de gerar.", "warn"); return; }
      if (state.payipBatch.previewPayload !== payipBatchPreviewSignature(payload)) {
        state.payipBatch.preview = null;
        state.payipBatch.previewPayload = null;
        renderPayipBatch();
        addLog("O lote PayIP mudou depois da validação. Valide novamente antes de gerar.", "warn");
        return;
      }
      const confirmed = await askConfirmation(`Gerar ${total} cobrança(s) PayIP em fila?`);
      if (!confirmed) return;
      const btn = E.payipBatchRunBtn;
      const previousLabel = btn ? btn.innerHTML : "";
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Enfileirando';
      }
      try {
        const result = await req(CONFIG.endpoints.payipBatch.run, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          timeoutMs: 60000
        });
        state.payipBatch.state = result.state || null;
        state.payipBatch.job = result.job || null;
        if (E.payipBatchMfaCode) E.payipBatchMfaCode.value = "";
        renderPayipBatch();
        addLog(`Lote PayIP iniciado: ${total} cobrança(s).`, "ok");
        pollPayipBatchStatus();
      } catch (err) {
        addLog(`Falha ao iniciar lote PayIP: ${err.message}`, "err");
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = previousLabel;
        }
      }
    }

    async function syncPayipBatchStatus({ silent = true } = {}) {
      if (!hasPanelAuth()) return false;
      try {
        const jobId = state.payipBatch && state.payipBatch.job && state.payipBatch.job.job_id ? state.payipBatch.job.job_id : "";
        const query = jobId ? `?job_id=${encodeURIComponent(jobId)}` : "";
        const payload = await req(`${CONFIG.endpoints.payipBatch.status}${query}`, { timeoutMs: 30000 });
        state.payipBatch.state = payload.state || null;
        state.payipBatch.job = payload.job && payload.job.job_id ? payload.job : state.payipBatch.job;
        renderPayipBatch();
        if (!silent) addLog("Status do lote PayIP atualizado.", "ok");
        return Boolean(payload.state && payload.state.running);
      } catch (err) {
        if (!silent) addLog(`Falha ao consultar lote PayIP: ${err.message}`, "warn");
        return false;
      }
    }

    async function pollPayipBatchStatus() {
      if (state.payipBatch.polling) return;
      state.payipBatch.polling = true;
      try {
        let keepPolling = true;
        while (keepPolling) {
          await new Promise(resolve => setTimeout(resolve, 2500));
          keepPolling = await syncPayipBatchStatus({ silent: true });
        }
        await syncPayipBatchStatus({ silent: true });
      } finally {
        state.payipBatch.polling = false;
      }
    }

    function payipBatchResultById(itemId) {
      const job = state.payipBatch && state.payipBatch.job ? state.payipBatch.job : null;
      const results = job && Array.isArray(job.results) ? job.results : [];
      return results.find(item => String(item.item_id || "") === String(itemId || "")) || null;
    }

    async function copyPayipBatchPix(itemId) {
      const item = payipBatchResultById(itemId);
      const pix = item ? String(item.pix_code || "") : "";
      if (!pix) { addLog("PIX copia e cola ainda não disponível para este item.", "warn"); return; }
      try {
        const copied = await writeTextToClipboard(pix);
        if (!copied) throw new Error("clipboard indisponível");
        addLog("PIX PayIP copiado.", "ok");
      } catch (err) {
        addLog(`Não foi possível copiar o PIX: ${err.message}`, "warn");
      }
    }

    async function downloadPayipBatchPdf(itemId) {
      updateTokens();
      const jobId = state.payipBatch && state.payipBatch.job && state.payipBatch.job.job_id ? state.payipBatch.job.job_id : "";
      const headers = {};
      if (state.tokens.api) headers["x-api-token"] = state.tokens.api;
      if (state.tokens.admin) headers["x-admin-token"] = state.tokens.admin;
      const query = jobId ? `?job_id=${encodeURIComponent(jobId)}` : "";
      try {
        const response = await fetch(`${CONFIG.api}${CONFIG.endpoints.payipBatch.pdf}/${encodeURIComponent(itemId)}${query}`, {
          method: "GET",
          credentials: "same-origin",
          headers
        });
        if (!response.ok) {
          const errPayload = await response.json().catch(() => null);
          throw new Error(errPayload && errPayload.detail ? errPayload.detail : `HTTP ${response.status}`);
        }
        const blob = await response.blob();
        const disposition = response.headers.get("content-disposition") || "";
        const matchedName = disposition.match(/filename=\"?([^\";]+)\"?/i);
        const filename = matchedName && matchedName[1] ? matchedName[1] : `payip-${itemId}.pdf`;
        const blobUrl = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = blobUrl;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(blobUrl);
        addLog("PDF PayIP baixado.", "ok");
        await syncPayipBatchStatus({ silent: true });
      } catch (err) {
        addLog(`Falha ao baixar PDF PayIP: ${err.message}`, "err");
      }
    }

    async function downloadPayipGeneratedBatchFile(batchId, kind) {
      updateTokens();
      if (!hasPanelAuth()) { addLog("Sessão do painel não validada.", "warn"); return; }
      const filial = payipGeneratedFilialValue();
      if (!filial) { addLog("Informe a revenda para gerar o arquivo do lote PayIP.", "warn"); return; }
      const mfaCode = E.payipGeneratedMfaCode ? String(E.payipGeneratedMfaCode.value || "").trim() : "";
      const headers = {};
      if (state.tokens.api) headers["x-api-token"] = state.tokens.api;
      if (state.tokens.admin) headers["x-admin-token"] = state.tokens.admin;
      if (mfaCode) headers["x-payip-mfa-code"] = mfaCode;
      const queryParams = new URLSearchParams();
      queryParams.set("filial", filial);
      queryParams.set("kind", kind || "");
      const query = `?${queryParams.toString()}`;
      try {
        state.payipGenerated.generating = `${batchId}:${kind || ""}`;
        renderPayipGeneratedBatches();
        addLog("Solicitando geração do arquivo na PayIP...", "info");
        const processResponse = await fetch(`${CONFIG.api}${CONFIG.endpoints.payipImport.generatedBatchProcess}/${encodeURIComponent(batchId)}/process${query}`, {
          method: "POST",
          credentials: "same-origin",
          headers
        });
        if (!processResponse.ok) {
          const errPayload = await processResponse.json().catch(() => null);
          throw new Error(errPayload && errPayload.detail ? errPayload.detail : `HTTP ${processResponse.status}`);
        }
        if (E.payipGeneratedMfaCode) E.payipGeneratedMfaCode.value = "";
        delete headers["x-payip-mfa-code"];
        await new Promise(resolve => setTimeout(resolve, 9000));
        addLog("Baixando arquivo gerado pela PayIP...", "info");
        const response = await fetch(`${CONFIG.api}${CONFIG.endpoints.payipImport.generatedBatchFile}/${encodeURIComponent(batchId)}/pdf${query}`, {
          method: "GET",
          credentials: "same-origin",
          headers
        });
        if (!response.ok) {
          const errPayload = await response.json().catch(() => null);
          throw new Error(errPayload && errPayload.detail ? errPayload.detail : `HTTP ${response.status}`);
        }
        const blob = await response.blob();
        const disposition = response.headers.get("content-disposition") || "";
        const matchedName = disposition.match(/filename=\"?([^\";]+)\"?/i);
        const filename = matchedName && matchedName[1] ? matchedName[1] : `payip-lote-${batchId}.zip`;
        const blobUrl = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = blobUrl;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(blobUrl);
        addLog("Arquivo do lote PayIP baixado.", "ok");
      } catch (err) {
        addLog(`Falha ao baixar arquivo do lote PayIP: ${err.message}`, "err");
      } finally {
        state.payipGenerated.generating = "";
        renderPayipGeneratedBatches();
      }
    }

    async function exportPayipBatchCsv() {
      updateTokens();
      if (!hasPanelAuth()) { addLog("Sessão do painel não validada.", "warn"); return; }
      const jobId = state.payipBatch && state.payipBatch.job && state.payipBatch.job.job_id ? state.payipBatch.job.job_id : "";
      const headers = {};
      if (state.tokens.api) headers["x-api-token"] = state.tokens.api;
      if (state.tokens.admin) headers["x-admin-token"] = state.tokens.admin;
      const query = jobId ? `?job_id=${encodeURIComponent(jobId)}` : "";
      try {
        const response = await fetch(`${CONFIG.api}${CONFIG.endpoints.payipBatch.exportCsv}${query}`, {
          method: "GET",
          credentials: "same-origin",
          headers
        });
        if (!response.ok) {
          const errPayload = await response.json().catch(() => null);
          throw new Error(errPayload && errPayload.detail ? errPayload.detail : `HTTP ${response.status}`);
        }
        const blob = await response.blob();
        const disposition = response.headers.get("content-disposition") || "";
        const matchedName = disposition.match(/filename=\"?([^\";]+)\"?/i);
        const filename = matchedName && matchedName[1] ? matchedName[1] : "payip-lote.csv";
        const blobUrl = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = blobUrl;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(blobUrl);
        addLog("Resultado PayIP exportado.", "ok");
      } catch (err) {
        addLog(`Falha ao exportar lote PayIP: ${err.message}`, "err");
      }
    }
