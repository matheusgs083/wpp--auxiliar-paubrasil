    function setArmazemRoutine(routine) {
      const selected = ["020304", "020105", "auditoria"].includes(String(routine)) ? String(routine) : "020304";
      state.promax.armazemRoutine = selected;
      document.querySelectorAll("[data-armazem-routine]").forEach(button => {
        const active = button.dataset.armazemRoutine === selected;
        button.classList.toggle("active", active);
        button.setAttribute("aria-selected", String(active));
        button.setAttribute("aria-current", active ? "page" : "false");
      });
      document.querySelectorAll("[data-armazem-section]").forEach(section => {
        section.hidden = section.dataset.armazemSection !== selected;
      });
    }

    function renderArmazemQueueSummary(jobs) {
      const armazemJobs = (Array.isArray(jobs) ? jobs : []).filter(job => ["lancamento_grade", "lancamento_grade_020304"].includes(String(job && job.job_type || "")));
      const total = armazemJobs.length;
      const done = armazemJobs.filter(job => ["completed", "success", "succeeded", "done"].includes(String(job && job.status || "").toLowerCase())).length;
      const pending = armazemJobs.filter(job => ["pending", "running", "cancel_requested"].includes(String(job && job.status || "").toLowerCase())).length;
      const failed = armazemJobs.filter(job => ["failed", "error", "cancelled"].includes(String(job && job.status || "").toLowerCase())).length;
      if (E.armazemQueueTotal) E.armazemQueueTotal.textContent = String(total);
      if (E.armazemQueueDone) E.armazemQueueDone.textContent = String(done);
      if (E.armazemQueuePending) E.armazemQueuePending.textContent = String(pending);
      if (E.armazemQueueFailed) E.armazemQueueFailed.textContent = String(failed);
    }

    async function syncArmazemGrade({ silent = true } = {}) {
      if (!(state.panel && state.panel.canArmazem)) return false;
      try {
        const payload = await req(CONFIG.endpoints.promax.gradeWorkers, { timeoutMs: 20000 });
        state.promax.worker = { workers: Array.isArray(payload.workers) ? payload.workers : [] };
        const workers = promaxWorkersFromPayload(state.promax.worker);
        renderPromaxTargetWorkerSelect(E.promaxGradeTargetWorker, workers);
        renderPromaxTargetWorkerSelect(E.promaxGrade020304Worker, workers);
        renderPromaxGradeResellerSelect(E.promaxGradeUnit);
        renderPromaxGradeResellerSelect(E.promaxGrade020304Unit);
      } catch (error) {
        if (!silent) addLog(`Não consegui carregar os bots para grade: ${error.message}`, "err");
        return false;
      }
      return syncArmazemGradeAudit({ silent });
    }

    async function previewArmazemCsv(file, statusElement, routine) {
      if (!file || !statusElement) return;
      if (file.size > 2 * 1024 * 1024) {
        statusElement.textContent = "Arquivo acima de 2 MB. Escolha um CSV menor.";
        return;
      }
      try {
        const lines = (await file.text()).split(/\r?\n/).map(line => line.trim()).filter(Boolean);
        const data = lines.slice(1);
        const codeIndex = routine === "020304" ? 1 : 3;
        const codes = data.map(line => line.split(/[;,]/)[codeIndex] || "").map(value => value.replace(/^\"|\"$/g, "").trim()).filter(Boolean);
        const duplicates = codes.length - new Set(codes).size;
        const duplicateHint = duplicates ? ` · ${duplicates} duplicidade(s) para revisar` : " · sem duplicidades aparentes";
        statusElement.textContent = `Prévia: ${data.length} linha(s), ${new Set(codes).size} código(s)${duplicateHint}. Selecione a revenda e envie para a fila.`;
      } catch (_error) {
        statusElement.textContent = "Não foi possível gerar a prévia. O arquivo ainda pode ser validado no envio.";
      }
    }

    function configureEstoqueFiliais() {
      const selects = [document.getElementById("estoqueFilial"), document.getElementById("estoqueImportFilial")].filter(Boolean);
      if (!selects.length || !state.panel) return;
      const allowed = state.panel.isAdmin ? null : (state.panel.filiais || []).map(value => String(value).replace(/^0+/, "") || "0");
      selects.forEach(select => {
        Array.from(select.options).forEach(option => {
          if (!option.value) return;
          const enabled = allowed === null || allowed.includes(option.value);
          option.hidden = !enabled;
          option.disabled = !enabled;
        });
        if (allowed && allowed.length === 1 && select.value !== allowed[0]) select.value = allowed[0];
      });
    }

    function estoqueSetStatus(message, kind = "") {
      const target = document.getElementById("estoqueStatus");
      if (!target) return;
      target.textContent = message;
      target.className = `pill ${kind}`;
    }

    function formatStockNumber(value) {
      const number = Number(value || 0);
      return Number.isFinite(number) ? new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 }).format(number) : "0";
    }

    function renderEstoque(payload) {
      const body = document.getElementById("estoqueTableBody");
      const summary = payload.summary || {};
      const batch = payload.batch || {};
      document.getElementById("estoqueProdutos").textContent = formatStockNumber(summary.produtos);
      document.getElementById("estoqueSaldo").textContent = formatStockNumber(summary.saldo_disponivel);
      document.getElementById("estoqueUltimaCarga").textContent = batch.imported_at ? formatDateTime(batch.imported_at) : "—";
      document.getElementById("estoqueFonte").textContent = batch.source_name ? `${batch.source_name} · ${summary.produtos || 0} produto(s)` : "";
      document.getElementById("estoqueAtualizadoEm").textContent = batch.imported_at ? `Atualizado em ${formatDateTime(batch.imported_at)}` : "";
      if (!body) return;
      if (!payload.ready) {
        body.innerHTML = '<tr class="estoque-empty-row"><td colspan="6" class="text-secondary text-center py-4">Ainda não há uma grade Stock_Product importada para esta filial.</td></tr>';
        estoqueSetStatus("Sem grade atual", "warn");
        return;
      }
      const rows = payload.items || [];
      body.innerHTML = rows.length ? rows.map(item => `<tr><td colspan="3" class="estoque-product"><span class="estoque-product-name">${escapeHtml(item.descricao_produto)}</span><span class="estoque-product-meta mono">Cód. ${escapeHtml(item.codigo_produto)} · ${escapeHtml(item.unidade_medida || "-")}</span></td><td data-label="Reserva" class="text-end mono estoque-number">${escapeHtml(formatStockNumber(item.reserva))}</td><td data-label="Saída" class="text-end mono estoque-number">${escapeHtml(formatStockNumber(item.saida))}</td><td data-label="Disponível" class="text-end mono fw-bold estoque-number estoque-available ${Number(item.saldo_disponivel) <= 0 ? "text-danger" : "text-success"}">${escapeHtml(formatStockNumber(item.saldo_disponivel))}</td></tr>`).join("") : '<tr class="estoque-empty-row"><td colspan="6" class="text-secondary text-center py-4">Nenhum produto encontrado nesta busca.</td></tr>';
      estoqueSetStatus("Grade atual", "ok");
    }

    async function syncEstoque({ silent = false } = {}) {
      const filial = document.getElementById("estoqueFilial")?.value || "";
      if (!filial) { if (!silent) estoqueSetStatus("Escolha uma filial"); return false; }
      const busca = document.getElementById("estoqueBusca")?.value.trim() || "";
      if (!silent) estoqueSetStatus("Consultando grade...");
      try {
        const payload = await req(`/api/admin/estoque?filial=${encodeURIComponent(filial)}&busca=${encodeURIComponent(busca)}`);
        renderEstoque(payload);
        return true;
      } catch (error) {
        estoqueSetStatus(error.message || "Falha ao consultar", "err");
        return false;
      }
    }

    async function importarEstoque() {
      const filial = document.getElementById("estoqueImportFilial")?.value || "";
      const file = document.getElementById("estoqueArquivo")?.files?.[0];
      const status = document.getElementById("estoqueImportStatus");
      if (!filial || !file) { if (status) status.textContent = "Selecione a filial e o CSV Stock_Product."; return; }
      if (!await askConfirmation(`Importar a nova grade para a filial ${filial}? Ela será usada na validação dos próximos pedidos.`)) return;
      const data = new FormData(); data.append("filial", filial); data.append("arquivo", file);
      if (status) status.textContent = "Importando grade e validando produtos...";
      try {
        const result = await req("/api/admin/estoque/importar", { method: "POST", body: data });
        if (status) status.textContent = `Grade importada: ${result.items} produto(s).`;
        document.getElementById("estoqueArquivo").value = "";
        const estoqueFilial = document.getElementById("estoqueFilial");
        if (estoqueFilial) estoqueFilial.value = filial;
        await syncEstoque();
      } catch (error) { if (status) status.textContent = error.message || "Não foi possível importar a grade."; }
    }

    function setupEstoquePanel() {
      document.getElementById("estoqueBuscarBtn")?.addEventListener("click", () => syncEstoque());
      document.getElementById("estoqueAtualizarBtn")?.addEventListener("click", () => syncEstoque());
      document.getElementById("estoqueImportarBtn")?.addEventListener("click", importarEstoque);
      document.getElementById("estoqueBusca")?.addEventListener("keydown", event => { if (event.key === "Enter") { event.preventDefault(); syncEstoque(); } });
      document.getElementById("estoqueFilial")?.addEventListener("change", () => syncEstoque());
    }
