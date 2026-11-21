    function armazemGradeAuditDate() {
      return String(E.armazemGradeAuditDate && E.armazemGradeAuditDate.value || formatDateInputValue(new Date()));
    }

    function armazemGradeJobAudit(job) {
      const result = job && job.result && typeof job.result === "object" ? job.result : {};
      const metadata = result.metadata || (result.details && result.details.metadata) || {};
      return Array.isArray(metadata.item_audit) ? metadata.item_audit : [];
    }

    function armazemGradeAuditProductCode(value) {
      const text = String(value ?? "").trim();
      return /^\d+$/.test(text) ? (text.replace(/^0+/, "") || "0") : text;
    }

    function armazemGradeAuditProductName(value) {
      return String(state.promax.grade020304ProductNames[armazemGradeAuditProductCode(value)] || "");
    }

    async function loadArmazemGradeAuditProductNames(items) {
      const names = state.promax.grade020304ProductNames;
      const attempted = state.promax.grade020304ProductLookupAttempted;
      const codes = [...new Set((Array.isArray(items) ? items : [])
        .map(item => armazemGradeAuditProductCode(item && (item.produto || item.item || item.codigo)))
        .filter(code => code && !Object.prototype.hasOwnProperty.call(names, code) && !attempted[code]))];
      if (!codes.length) return;
      codes.forEach(code => { attempted[code] = true; });
      try {
        const params = new URLSearchParams({ codes: codes.join(","), limit: String(Math.min(codes.length, 200)) });
        const payload = await req(`${CONFIG.endpoints.conferencia.produtos}?${params.toString()}`, { timeoutMs: 20000 });
        (Array.isArray(payload && payload.products) ? payload.products : []).forEach(product => {
          const code = armazemGradeAuditProductCode(product && product.codigo);
          const name = String(product && (product.descricao || product.descricao_completa) || "").trim();
          if (code && name) names[code] = name;
        });
      } catch (_error) {
        // A auditoria continua útil pelo código mesmo se a base 01.11 estiver indisponível.
      }
      renderArmazemGradeAudit();
    }

    function selectArmazemGradeAuditJob(jobId) {
      state.promax.selectedGrade020304AuditJobId = String(jobId || "");
      renderArmazemGradeAudit();
    }

    function renderArmazemGradeAudit() {
      if (!E.armazemGradeAudit) return;
      const gradeJobs = (Array.isArray(state.promax.grade020304AuditJobs) ? state.promax.grade020304AuditJobs : [])
        .filter(job => ["lancamento_grade", "lancamento_grade_020304"].includes(String(job && job.job_type || "")))
        .sort((left, right) => String(right.created_at || "").localeCompare(String(left.created_at || "")));
      if (!gradeJobs.length) {
        if (E.armazemGradeAuditCount) E.armazemGradeAuditCount.textContent = "Nenhum job no dia";
        E.armazemGradeAudit.innerHTML = '<div class="text-secondary small py-3">Nenhum lançamento de grade foi encontrado neste dia.</div>';
        return;
      }
      const selectedId = gradeJobs.some(job => String(job.id) === state.promax.selectedGrade020304AuditJobId)
        ? state.promax.selectedGrade020304AuditJobId
        : String(gradeJobs[0].id || "");
      state.promax.selectedGrade020304AuditJobId = selectedId;
      const selectedJob = gradeJobs.find(job => String(job.id) === selectedId) || gradeJobs[0];
      const audit = armazemGradeJobAudit(selectedJob);
      const query = normalizeTextForSearch(E.armazemGradeAuditSearch && E.armazemGradeAuditSearch.value || "");
      const onlyErrors = Boolean(E.armazemGradeAuditErrorsOnly && E.armazemGradeAuditErrorsOnly.checked);
      const visibleAudit = audit.filter(item => {
        const code = String(item && (item.produto || item.item || item.codigo) || "");
        const name = armazemGradeAuditProductName(code);
        const searchText = normalizeTextForSearch(`${code} ${name}`);
        const status = String(item && item.status || "NAO_EXECUTADO");
        return (!query || searchText.includes(query)) && (!onlyErrors || status !== "LANCADO");
      });
      loadArmazemGradeAuditProductNames(audit);
      const totals = audit.reduce((summary, item) => {
        const status = String(item && item.status || "NAO_EXECUTADO");
        summary[status] = (summary[status] || 0) + 1;
        return summary;
      }, {});
      if (E.armazemGradeAuditCount) E.armazemGradeAuditCount.textContent = `${gradeJobs.length} job(ns) em ${formatDate(armazemGradeAuditDate())}`;
      const jobCards = gradeJobs.map(job => {
        const jobAudit = armazemGradeJobAudit(job);
        const isSelected = String(job.id) === selectedId;
        const jobStatus = String(job.status || "pending");
        const jobTotals = jobAudit.reduce((summary, item) => { const status = String(item && item.status || "NAO_EXECUTADO"); summary[status] = (summary[status] || 0) + 1; return summary; }, {});
        const jobSummary = jobAudit.length ? `${jobTotals.LANCADO || 0} lançado(s) · ${(jobTotals.FALHOU || 0) + (jobTotals.NAO_EXECUTADO || 0)} pendência(s)` : "sem retorno por item";
        const routineLabel = String(job.job_type || "") === "lancamento_grade_020304" ? "02.03.04" : "02.01.05";
        return `<button type="button" class="list-group-item list-group-item-action armazem-grade-job-card ${isSelected ? "active" : ""}" data-grade-audit-job="${escapeHtml(String(job.id || ""))}" aria-pressed="${isSelected ? "true" : "false"}"><div class="d-flex justify-content-between gap-2"><strong class="mono small">${escapeHtml(String(job.id || "").slice(0, 8))}</strong><span class="promax-status ${promaxStatusClass(jobStatus)}">${escapeHtml(promaxStatusLabel(jobStatus))}</span></div><div class="small text-secondary mt-1">${escapeHtml(routineLabel)} · ${escapeHtml(formatDateTime(job.created_at))}</div><div class="small text-secondary">${escapeHtml(jobSummary)}</div></button>`;
      }).join("");
      const auditRows = audit.length
        ? visibleAudit.length
          ? `<div class="table-scroll"><table class="table table-sm table-hover align-middle mb-0"><thead><tr><th>Linha</th><th>Produto/item</th><th class="text-end">Quantidade</th><th>Status</th><th>Detalhe</th></tr></thead><tbody>${visibleAudit.map(item => { const status = String(item.status || "NAO_EXECUTADO"); const tone = status === "LANCADO" ? "ok" : status === "FALHOU" ? "danger" : "warn"; const code = String(item.produto || item.item || item.codigo || "-"); const name = armazemGradeAuditProductName(code); const quantity = item.quantidade ?? item.unidade ?? item.pallet ?? "-"; const isPending = status !== "LANCADO"; return `<tr class="${isPending ? "armazem-grade-error-row" : ""}"><td class="mono small">${escapeHtml(String(item.source_row ?? item.line ?? "-"))}</td><td><div class="mono">${escapeHtml(code)}</div><span class="armazem-grade-product-name">${escapeHtml(name || "Código enviado ao Promax")}</span></td><td class="text-end">${escapeHtml(String(quantity))}</td><td><span class="pill ${tone}">${escapeHtml(status.replaceAll("_", " "))}</span></td><td class="small text-secondary">${escapeHtml(item.detail || "-")}</td></tr>`; }).join("")}</tbody></table></div>`
          : '<div class="text-secondary small py-3">Nenhum item deste job atende aos filtros informados.</div>'
        : '<div class="text-secondary small py-3">Este job ainda não retornou a auditoria por item. Atualize após a execução.</div>';
      E.armazemGradeAudit.innerHTML = `<div class="armazem-grade-audit-kpis"><div class="armazem-grade-audit-kpi"><span class="label">Jobs no dia</span><strong>${gradeJobs.length}</strong></div><div class="armazem-grade-audit-kpi ok"><span class="label">Lançados</span><strong>${totals.LANCADO || 0}</strong></div><div class="armazem-grade-audit-kpi danger"><span class="label">Falhos</span><strong>${totals.FALHOU || 0}</strong></div><div class="armazem-grade-audit-kpi warn"><span class="label">Não executados</span><strong>${totals.NAO_EXECUTADO || 0}</strong></div></div><div class="row g-3"><div class="col-lg-4"><div class="d-flex justify-content-between align-items-center mb-2"><span class="small fw-bold">JOBS DO DIA</span><span class="small text-secondary">${gradeJobs.length}</span></div><div class="list-group armazem-grade-job-list">${jobCards}</div></div><div class="col-lg-8"><div class="armazem-grade-detail"><div class="d-flex flex-wrap gap-2 justify-content-between align-items-start mb-3"><div><div class="small text-secondary text-uppercase fw-bold">Job selecionado</div><strong class="mono">${escapeHtml(String(selectedJob.id || "").slice(0, 8))}</strong><span class="small text-secondary ms-2">${escapeHtml(formatDateTime(selectedJob.created_at))}</span><div class="small text-secondary mt-1">${visibleAudit.length}/${audit.length} item(ns) exibidos</div></div><div class="d-flex flex-wrap gap-1"><span class="pill ok">${totals.LANCADO || 0} lançado(s)</span><span class="pill danger">${totals.FALHOU || 0} falhou</span><span class="pill warn">${totals.NAO_EXECUTADO || 0} não executado(s)</span></div></div>${auditRows}</div></div></div>`;
      E.armazemGradeAudit.querySelectorAll("[data-grade-audit-job]").forEach(button => button.addEventListener("click", () => selectArmazemGradeAuditJob(button.dataset.gradeAuditJob)));
    }

    async function syncArmazemGradeAudit({ silent = true } = {}) {
      if (!(state.panel && state.panel.canArmazem)) return false;
      const selectedDate = armazemGradeAuditDate();
      const baseParams = { limit: "200", created_from: selectedDate, created_to: selectedDate };
      try {
        const categories = ["lancamento_grade", "lancamento_grade_020304"];
        const payloads = await Promise.all(categories.map(category => {
          const params = new URLSearchParams({ ...baseParams, category });
          return req(`${CONFIG.endpoints.promax.jobs}?${params.toString()}`, { timeoutMs: 30000 });
        }));
        state.promax.grade020304AuditJobs = payloads.flatMap(payload => Array.isArray(payload && payload.jobs) ? payload.jobs : []);
        renderArmazemQueueSummary(state.promax.grade020304AuditJobs);
        renderArmazemGradeAudit();
        return true;
      } catch (error) {
        if (!silent) addLog(`Não consegui carregar a auditoria da grade: ${error.message}`, "err");
        return false;
      }
    }

    function getUsageWindowDays() {
      const raw = Number(E.usageWindow && E.usageWindow.value ? E.usageWindow.value : 7);
      if (!Number.isFinite(raw)) return 7;
      return Math.max(1, Math.min(30, Math.trunc(raw)));
    }

    function getUsageFunctionWindowDays() {
      const raw = Number(E.usageFunctionWindow && E.usageFunctionWindow.value ? E.usageFunctionWindow.value : getUsageWindowDays());
      if (!Number.isFinite(raw)) return getUsageWindowDays();
      return Math.max(1, Math.min(30, Math.trunc(raw)));
    }

    function ensureUsageFunctionDateRange() {
      if (E.usageFunctionWindow && E.usageFunctionWindow.parentElement) {
        E.usageFunctionWindow.parentElement.style.display = "none";
      }
      const today = new Date();
      const defaultFrom = new Date(today);
      defaultFrom.setDate(today.getDate() - 6);
      if (E.usageFunctionDateFrom && !E.usageFunctionDateFrom.value) {
        E.usageFunctionDateFrom.value = formatDateInputValue(defaultFrom);
      }
      if (E.usageFunctionDateTo && !E.usageFunctionDateTo.value) {
        E.usageFunctionDateTo.value = formatDateInputValue(today);
      }
    }

    function getUsageFunctionDateParams() {
      ensureUsageFunctionDateRange();
      const dateFrom = E.usageFunctionDateFrom ? String(E.usageFunctionDateFrom.value || "").trim() : "";
      const dateTo = E.usageFunctionDateTo ? String(E.usageFunctionDateTo.value || "").trim() : "";
      if (!dateFrom || !dateTo) throw new Error("Informe data inicial e final.");
      if (dateFrom > dateTo) throw new Error("Data inicial não pode ser maior que a final.");
      return { dateFrom, dateTo };
    }

    function setUsageMetric(element, value) {
      if (!element) return;
      element.textContent = value;
    }

    function renderEvolutionUsageLoading() {
      setUsageMetric(E.usageMetricMessages, "--");
      setUsageMetric(E.usageMetricUnique, "--");
      setUsageMetric(E.usageMetricProcessed, "--");
      setUsageMetric(E.usageMetricBlocked, "--");
      setUsageMetric(E.usageMetricErrors, "--");
      setUsageMetric(E.usageMetricDeniedSent, "--");
      setUsageMetric(E.usageMetricDeniedSuppressed, "--");
      setUsageMetric(E.usageMetricEvents, "--");
      setUsageMetric(E.usageMetricFeatureInteractions, "--");
      setUsageMetric(E.usageMetricFeatureUsers, "--");
      setUsageMetric(E.usageMetricFeatureCount, "--");
      setUsageMetric(E.usageMetricFeatureTop, "--");
      if (E.usageDailyBars) {
        E.usageDailyBars.innerHTML = '<div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line"></div>';
      }
      if (E.usageTopNumbersBody) {
        E.usageTopNumbersBody.innerHTML = '<tr><td colspan="4" class="py-3"><div class="skeleton skeleton-line"></div></td></tr>';
      }
      if (E.usageFunctionSummaryBody) {
        E.usageFunctionSummaryBody.innerHTML = '<tr><td colspan="3" class="py-3"><div class="skeleton skeleton-line"></div></td></tr>';
      }
      if (E.usageFunctionUsersBody) {
        E.usageFunctionUsersBody.innerHTML = '<tr><td colspan="4" class="py-3"><div class="skeleton skeleton-line"></div></td></tr>';
      }
      if (E.usageBreakdownBody) {
        E.usageBreakdownBody.innerHTML = '<tr><td colspan="3" class="py-3"><div class="skeleton skeleton-line"></div></td></tr>';
      }
      if (E.usageRecentBody) {
        E.usageRecentBody.innerHTML = '<tr><td colspan="5" class="py-3"><div class="skeleton skeleton-line"></div></td></tr>';
      }
    }

    function renderEvolutionUsage() {
      const payload = state.evolutionUsage && typeof state.evolutionUsage === "object" ? state.evolutionUsage : null;
      const summary = payload && payload.summary && typeof payload.summary === "object" ? payload.summary : null;

      if (!summary) {
        setUsageMetric(E.usageMetricMessages, "--");
        setUsageMetric(E.usageMetricUnique, "--");
        setUsageMetric(E.usageMetricProcessed, "--");
        setUsageMetric(E.usageMetricBlocked, "--");
        setUsageMetric(E.usageMetricErrors, "--");
        setUsageMetric(E.usageMetricDeniedSent, "--");
        setUsageMetric(E.usageMetricDeniedSuppressed, "--");
        setUsageMetric(E.usageMetricEvents, "--");
        setUsageMetric(E.usageMetricFeatureInteractions, "--");
        setUsageMetric(E.usageMetricFeatureUsers, "--");
        setUsageMetric(E.usageMetricFeatureCount, "--");
        setUsageMetric(E.usageMetricFeatureTop, "--");
        if (E.usageDailyBars) E.usageDailyBars.innerHTML = '<div class="small text-secondary">Sem dados de uso disponíveis para o Evolution.</div>';
        if (E.usageTopNumbersBody) E.usageTopNumbersBody.innerHTML = '<tr><td colspan="4" class="text-center py-3 text-secondary">Sem dados</td></tr>';
        if (E.usageFunctionSummaryBody) E.usageFunctionSummaryBody.innerHTML = '<tr><td colspan="3" class="text-center py-3 text-secondary">Sem dados</td></tr>';
        if (E.usageFunctionUsersBody) E.usageFunctionUsersBody.innerHTML = '<tr><td colspan="4" class="text-center py-3 text-secondary">Sem dados</td></tr>';
        if (E.usageBreakdownBody) E.usageBreakdownBody.innerHTML = '<tr><td colspan="3" class="text-center py-3 text-secondary">Sem dados</td></tr>';
        if (E.usageRecentBody) E.usageRecentBody.innerHTML = '<tr><td colspan="5" class="text-center py-3 text-secondary">Sem dados</td></tr>';
        return;
      }

      setUsageMetric(E.usageMetricMessages, formatNumber(summary.total_messages));
      setUsageMetric(E.usageMetricUnique, formatNumber(summary.unique_numbers));
      setUsageMetric(E.usageMetricProcessed, formatNumber(summary.processed_ok));
      setUsageMetric(E.usageMetricBlocked, formatNumber(summary.blocked_rbac));
      setUsageMetric(E.usageMetricErrors, formatNumber(summary.total_errors));
      setUsageMetric(E.usageMetricDeniedSent, formatNumber(summary.denied_reply_sent));
      setUsageMetric(E.usageMetricDeniedSuppressed, formatNumber(summary.denied_reply_suppressed));
      setUsageMetric(E.usageMetricEvents, formatNumber(summary.total_events));
      const functionUsageSummary = payload && payload.function_usage_summary && typeof payload.function_usage_summary === "object"
        ? payload.function_usage_summary
        : null;
      setUsageMetric(
        E.usageMetricFeatureInteractions,
        formatNumber(functionUsageSummary && functionUsageSummary.tracked_interactions)
      );
      setUsageMetric(
        E.usageMetricFeatureUsers,
        formatNumber(functionUsageSummary && functionUsageSummary.tracked_users)
      );
      setUsageMetric(
        E.usageMetricFeatureCount,
        formatNumber(functionUsageSummary && functionUsageSummary.functions_used)
      );
      setUsageMetric(
        E.usageMetricFeatureTop,
        functionUsageSummary && functionUsageSummary.top_function_label
          ? functionUsageSummary.top_function_label
          : "--"
      );

      const daily = Array.isArray(payload.daily_messages) ? payload.daily_messages : [];
      const maxMessages = daily.reduce((maxValue, item) => {
        const current = Number(item && item.messages ? item.messages : 0);
        return current > maxValue ? current : maxValue;
      }, 0);

      if (E.usageDailyBars) {
        if (!daily.length) {
          E.usageDailyBars.innerHTML = '<div class="small text-secondary">Sem volume registrado no período selecionado.</div>';
        } else {
          E.usageDailyBars.innerHTML = daily.map(item => {
            const messages = Number(item && item.messages ? item.messages : 0);
            const blocked = Number(item && item.blocked_rbac ? item.blocked_rbac : 0);
            const uniqueNumbers = Number(item && item.unique_numbers ? item.unique_numbers : 0);
            const ratio = maxMessages > 0 ? Math.round((messages / maxMessages) * 100) : 0;
            const width = messages > 0 ? Math.max(2, ratio) : 0;
            return `
              <div class="usage-bar-row">
                <span class="usage-bar-label">${escapeHtml(formatDate(item.date))}</span>
                <div>
                  <div class="usage-bar-track">
                    <div class="usage-bar-fill" style="width:${width}%;"></div>
                  </div>
                  <div class="usage-kpi-line">
                    <span>Únicos: ${formatNumber(uniqueNumbers)}</span>
                    <span>Bloq: ${formatNumber(blocked)}</span>
                  </div>
                </div>
                <span class="usage-bar-value">${formatNumber(messages)}</span>
              </div>
            `;
          }).join("");
        }
      }

      const topNumbers = Array.isArray(payload.top_numbers) ? payload.top_numbers : [];
      if (E.usageTopNumbersBody) {
        if (!topNumbers.length) {
          E.usageTopNumbersBody.innerHTML = '<tr><td colspan="4" class="text-center py-3 text-secondary">Sem números no período</td></tr>';
        } else {
          E.usageTopNumbersBody.innerHTML = topNumbers.map(item => {
            const rawPhone = String(item.phone_number || "");
            const phone = formatPhoneForUi(rawPhone);
            const displayName = String(item.display_name || phone || "-");
            const showPhone = phone && displayName !== phone;
            return `
              <tr>
                <td>
                  <strong>${escapeHtml(displayName)}</strong>
                  ${showPhone ? `<div class="small mono text-secondary">${escapeHtml(phone)}</div>` : ""}
                </td>
                <td class="text-end">${formatNumber(item.messages)}</td>
                <td class="text-end">${formatNumber(item.processed_ok)}</td>
                <td class="text-end">${formatNumber(item.blocked_rbac)}</td>
              </tr>
            `;
          }).join("");
        }
      }

      renderEvolutionFunctionUsage(payload);

      const breakdown = Array.isArray(payload.event_breakdown) ? payload.event_breakdown : [];
      if (E.usageBreakdownBody) {
        if (!breakdown.length) {
          E.usageBreakdownBody.innerHTML = '<tr><td colspan="3" class="text-center py-3 text-secondary">Sem eventos no período</td></tr>';
        } else {
          E.usageBreakdownBody.innerHTML = breakdown.map(item => `
            <tr>
              <td><span class="mono">${escapeHtml(item.event_type || "-")}</span></td>
              <td>${escapeHtml(item.decision || "-")}</td>
              <td class="text-end">${formatNumber(item.total)}</td>
            </tr>
          `).join("");
        }
      }

      const recent = Array.isArray(payload.recent_events) ? payload.recent_events : [];
      if (E.usageRecentBody) {
        if (!recent.length) {
          E.usageRecentBody.innerHTML = '<tr><td colspan="5" class="text-center py-3 text-secondary">Sem eventos recentes</td></tr>';
        } else {
          E.usageRecentBody.innerHTML = recent.map(item => `
            <tr>
              <td>${escapeHtml(formatDateTime(item.created_at))}</td>
              <td><span class="mono">${escapeHtml(item.event_type || "-")}</span></td>
              <td>${escapeHtml(item.decision || "-")}</td>
              <td><span class="mono">${escapeHtml(formatPhoneForUi(item.phone_number || "-"))}</span></td>
              <td>${escapeHtml(item.reason || "-")}</td>
            </tr>
          `).join("");
        }
      }
    }

    function renderEvolutionFunctionUsage(payload) {
      const source = payload && typeof payload === "object" ? payload : {};
      const functionSummary = Array.isArray(source.function_summary) ? source.function_summary : [];
      const previousFunction = E.usageFunctionFilter ? String(E.usageFunctionFilter.value || "") : "";
      const availableFunctions = new Set(functionSummary.map(item => String(item.feature_code || "").trim()).filter(Boolean));
      const selectedFunction = availableFunctions.has(previousFunction) ? previousFunction : "";
      if (E.usageFunctionFilter) {
        const options = [
          '<option value="">Todas</option>',
          ...functionSummary.map(item => {
            const code = String(item.feature_code || "").trim();
            const label = String(item.label || code || "-").trim();
            return `<option value="${escapeHtml(code)}"${code === selectedFunction ? " selected" : ""}>${escapeHtml(label)}</option>`;
          })
        ];
        E.usageFunctionFilter.innerHTML = options.join("");
      }
      const rawNumberFunctionUsage = Array.isArray(source.number_function_usage) ? source.number_function_usage : [];
      const numberFunctionUsage = selectedFunction
        ? rawNumberFunctionUsage.map(item => {
            if (!item || typeof item !== "object") return null;
            const features = Array.isArray(item.features)
              ? item.features.filter(feature => feature && String(feature.feature_code || "").trim() === selectedFunction)
              : [];
            if (!features.length) return null;
            const selectedTotal = features.reduce((sum, feature) => sum + Number(feature.total || 0), 0);
            return {
              ...item,
              total: selectedTotal,
              unique_functions: features.length,
              features
            };
          }).filter(Boolean)
        : rawNumberFunctionUsage;
      const selectedSummary = selectedFunction
        ? functionSummary.find(item => String(item.feature_code || "").trim() === selectedFunction)
        : null;
      const functionUsageSummary = source.function_usage_summary && typeof source.function_usage_summary === "object"
        ? source.function_usage_summary
        : null;
      const metricInteractions = selectedFunction
        ? (selectedSummary ? selectedSummary.total : 0)
        : (functionUsageSummary && functionUsageSummary.tracked_interactions);
      const metricUsers = selectedFunction
        ? numberFunctionUsage.length
        : (functionUsageSummary && functionUsageSummary.tracked_users);
      const metricFunctions = selectedFunction
        ? (selectedSummary ? 1 : 0)
        : (functionUsageSummary && functionUsageSummary.functions_used);
      const metricTop = selectedFunction
        ? (selectedSummary ? (selectedSummary.label || selectedSummary.feature_code || "--") : "--")
        : (functionUsageSummary && functionUsageSummary.top_function_label ? functionUsageSummary.top_function_label : "--");
      setUsageMetric(
        E.usageMetricFeatureInteractions,
        formatNumber(metricInteractions)
      );
      setUsageMetric(
        E.usageMetricFeatureUsers,
        formatNumber(metricUsers)
      );
      setUsageMetric(
        E.usageMetricFeatureCount,
        formatNumber(metricFunctions)
      );
      setUsageMetric(
        E.usageMetricFeatureTop,
        metricTop
      );

      if (E.usageFunctionSummaryBody) {
        if (!functionSummary.length) {
          E.usageFunctionSummaryBody.innerHTML = '<tr><td colspan="3" class="text-center py-3 text-secondary">Sem funções rastreadas</td></tr>';
        } else {
          E.usageFunctionSummaryBody.innerHTML = functionSummary.map(item => `
            <tr${String(item.feature_code || "").trim() === selectedFunction ? ' class="table-primary"' : ""}>
              <td><strong>${escapeHtml(item.label || item.feature_code || "-")}</strong></td>
              <td class="text-end">${formatNumber(item.total)}</td>
              <td class="text-end">${formatNumber(item.unique_numbers)}</td>
            </tr>
          `).join("");
        }
      }

      if (E.usageFunctionUsersBody) {
        if (!numberFunctionUsage.length) {
          E.usageFunctionUsersBody.innerHTML = '<tr><td colspan="4" class="text-center py-3 text-secondary">Sem rastreio por função no período</td></tr>';
        } else {
          E.usageFunctionUsersBody.innerHTML = numberFunctionUsage.map(item => {
            const rawPhone = String(item.phone_number || "");
            const phone = formatPhoneForUi(rawPhone);
            const displayName = String(item.display_name || phone || "-");
            const showPhone = phone && displayName !== phone;
            const features = Array.isArray(item.features) ? item.features : [];
            const badges = features.length
              ? features.map(feature => `<span class="badge rounded-pill text-bg-light border me-1 mb-1">${escapeHtml(feature.label || feature.feature_code || "-")}: ${formatNumber(feature.total)}</span>`).join("")
              : '<span class="text-secondary small">Sem detalhe</span>';
            return `
              <tr>
                <td>
                  <strong>${escapeHtml(displayName)}</strong>
                  ${showPhone ? `<div class="small mono text-secondary">${escapeHtml(phone)}</div>` : ""}
                </td>
                <td class="text-end">${formatNumber(item.total)}</td>
                <td class="text-end">${formatNumber(item.unique_functions)}</td>
                <td>${badges}</td>
              </tr>
            `;
          }).join("");
        }
      }
    }

    async function syncEvolutionUsage({ silent = true } = {}) {
      if (state.panel && state.panel.mode === "financeiro" && !state.panel.isAdmin) {
        state.evolutionUsage = null;
        renderEvolutionUsage();
        return false;
      }
      if (!hasPanelAuth()) {
        if (!silent) addLog("Sessão do painel não validada.", "warn");
        return false;
      }

      const days = getUsageWindowDays();
      try {
        const payload = await req(`${CONFIG.endpoints.usage.evolution}?days=${days}`, { timeoutMs: 30000 });
        state.evolutionUsage = payload && typeof payload === "object" ? payload : null;
        renderEvolutionUsage();
        if (!silent) addLog(`Dashboard de uso do Evolution atualizado (${days} dia(s)).`, "ok");
        return true;
      } catch (err) {
        if (state.evolutionUsage === null) renderEvolutionUsage();
        if (!silent) addLog(`Falha ao consultar uso do Evolution: ${err.message}`, "warn");
        return false;
      }
    }

    async function syncEvolutionFunctionUsage({ silent = false } = {}) {
      if (state.panel && state.panel.mode === "financeiro" && !state.panel.isAdmin) {
        renderEvolutionFunctionUsage(null);
        return false;
      }
      if (!hasPanelAuth()) {
        if (!silent) addLog("Sessão do painel não validada.", "warn");
        return false;
      }

      let dateParams;
      try {
        dateParams = getUsageFunctionDateParams();
      } catch (err) {
        if (!silent) addLog(err.message, "warn");
        return false;
      }
      const days = getUsageWindowDays();
      const btn = E.usageFunctionRefreshBtn;
      const previousLabel = btn ? btn.innerHTML : "";
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Atualizando';
      }
      try {
        const query = `days=${days}&date_from=${encodeURIComponent(dateParams.dateFrom)}&date_to=${encodeURIComponent(dateParams.dateTo)}`;
        const payload = await req(`${CONFIG.endpoints.usage.evolution}?${query}`, { timeoutMs: 30000 });
        state.evolutionUsage = {
          ...(state.evolutionUsage && typeof state.evolutionUsage === "object" ? state.evolutionUsage : {}),
          function_usage_summary: payload.function_usage_summary,
          function_summary: payload.function_summary,
          number_function_usage: payload.number_function_usage
        };
        renderEvolutionFunctionUsage(payload);
        if (!silent) addLog(`Uso por função atualizado (${dateParams.dateFrom} até ${dateParams.dateTo}).`, "ok");
        return true;
      } catch (err) {
        if (!silent) addLog(`Falha ao consultar uso por função: ${err.message}`, "warn");
        return false;
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = previousLabel;
        }
      }
    }

    async function exportEvolutionAverageReport() {
      updateTokens();
      if (state.panel && state.panel.mode === "financeiro" && !state.panel.isAdmin) {
        addLog("Uso Evolution fica disponível apenas para admin.", "warn");
        return;
      }
      if (!hasPanelAuth()) {
        addLog("Sessão do painel não validada.", "warn");
        return;
      }

      const btn = E.usageExportReportBtn;
      const previousLabel = btn ? btn.innerHTML : "";
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Exportando';
      }

      const days = getUsageWindowDays();
      const limit = 5000;
      const headers = {};
      if (state.tokens.api) headers["x-api-token"] = state.tokens.api;
      if (state.tokens.admin) headers["x-admin-token"] = state.tokens.admin;

      try {
        const response = await fetch(
          `${CONFIG.api}${CONFIG.endpoints.usage.evolutionReport}?days=${days}&limit=${limit}`,
          { method: "GET", headers, credentials: "same-origin" }
        );

        if (!response.ok) {
          const errPayload = await response.json().catch(() => null);
          throw new Error(errPayload && errPayload.detail ? errPayload.detail : `HTTP ${response.status}`);
        }

        const blob = await response.blob();
        const disposition = response.headers.get("content-disposition") || "";
        const matchedName = disposition.match(/filename=\"([^\"]+)\"/i);
        const filename = matchedName && matchedName[1]
          ? matchedName[1]
          : `relatorio_media_msg_por_dia_${days}d.csv`;

        const blobUrl = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = blobUrl;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(blobUrl);
        addLog(`Relatório exportado com sucesso (${days} dia(s)).`, "ok");
      } catch (err) {
        addLog(`Falha ao exportar relatório: ${err.message}`, "err");
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = previousLabel;
        }
      }
    }

    async function exportEvolutionFunctionUsageReport() {
      updateTokens();
      if (state.panel && state.panel.mode === "financeiro" && !state.panel.isAdmin) {
        addLog("Uso Evolution fica disponível apenas para admin.", "warn");
        return;
      }
      if (!hasPanelAuth()) {
        addLog("Sessão do painel não validada.", "warn");
        return;
      }

      const btn = E.usageFunctionExportBtn;
      const previousLabel = btn ? btn.innerHTML : "";
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Exportando';
      }

      let dateParams;
      try {
        dateParams = getUsageFunctionDateParams();
      } catch (err) {
        addLog(err.message, "warn");
        return;
      }
      const days = getUsageWindowDays();
      const limit = 5000;
      const featureCode = E.usageFunctionFilter ? String(E.usageFunctionFilter.value || "").trim() : "";
      const headers = {};
      if (state.tokens.api) headers["x-api-token"] = state.tokens.api;
      if (state.tokens.admin) headers["x-admin-token"] = state.tokens.admin;

      try {
        const featureParam = featureCode ? `&feature=${encodeURIComponent(featureCode)}` : "";
        const response = await fetch(
          `${CONFIG.api}${CONFIG.endpoints.usage.evolutionFunctionsReport}?days=${days}&date_from=${encodeURIComponent(dateParams.dateFrom)}&date_to=${encodeURIComponent(dateParams.dateTo)}&limit=${limit}${featureParam}`,
          { method: "GET", headers, credentials: "same-origin" }
        );

        if (!response.ok) {
          const errPayload = await response.json().catch(() => null);
          throw new Error(errPayload && errPayload.detail ? errPayload.detail : `HTTP ${response.status}`);
        }

        const blob = await response.blob();
        const disposition = response.headers.get("content-disposition") || "";
        const matchedName = disposition.match(/filename=\"([^\"]+)\"/i);
        const filename = matchedName && matchedName[1]
          ? matchedName[1]
          : `numero_x_funcao_evolution_${dateParams.dateFrom}_a_${dateParams.dateTo}.csv`;

        const blobUrl = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = blobUrl;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(blobUrl);
        addLog(`Número x função exportado com sucesso (${dateParams.dateFrom} até ${dateParams.dateTo}).`, "ok");
      } catch (err) {
        addLog(`Falha ao exportar número x função: ${err.message}`, "err");
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = previousLabel;
        }
      }
    }

    function ensurePanelAuditDateRange() {
      const today = new Date();
      const defaultFrom = new Date(today);
      defaultFrom.setDate(today.getDate() - 6);
      if (E.panelAuditDateFrom && !E.panelAuditDateFrom.value) {
        E.panelAuditDateFrom.value = formatDateInputValue(defaultFrom);
      }
      if (E.panelAuditDateTo && !E.panelAuditDateTo.value) {
        E.panelAuditDateTo.value = formatDateInputValue(today);
      }
    }

    function getPanelAuditParams() {
      ensurePanelAuditDateRange();
      const params = new URLSearchParams();
      const dateFrom = E.panelAuditDateFrom ? String(E.panelAuditDateFrom.value || "").trim() : "";
      const dateTo = E.panelAuditDateTo ? String(E.panelAuditDateTo.value || "").trim() : "";
      if (!dateFrom || !dateTo) throw new Error("Informe data inicial e final das ações do painel.");
      if (dateFrom > dateTo) throw new Error("Data inicial não pode ser maior que a final.");
      params.set("date_from", dateFrom);
      params.set("date_to", dateTo);
      params.set("limit", "500");
      const username = E.panelAuditUser ? String(E.panelAuditUser.value || "").trim() : "";
      const moduleName = E.panelAuditModule ? String(E.panelAuditModule.value || "").trim() : "";
      const action = E.panelAuditAction ? String(E.panelAuditAction.value || "").trim() : "";
      if (username) params.set("username", username);
      if (moduleName) params.set("module", moduleName);
      if (action) params.set("action", action);
      return params;
    }

    function renderPanelAuditLoading() {
      if (E.panelAuditCount) E.panelAuditCount.textContent = "Carregando ações";
      if (E.panelAuditBody) {
        E.panelAuditBody.innerHTML = '<tr><td colspan="7" class="py-3"><div class="skeleton skeleton-line"></div></td></tr>';
      }
    }

    function renderPanelAuditActions() {
      const payload = state.panelAudit && typeof state.panelAudit === "object" ? state.panelAudit : null;
      const actions = payload && Array.isArray(payload.actions) ? payload.actions : [];
      if (E.panelAuditCount) {
        E.panelAuditCount.textContent = payload ? `${formatNumber(payload.total)} ação(ões)` : "Sem dados";
      }
      if (!E.panelAuditBody) return;
      if (!actions.length) {
        E.panelAuditBody.innerHTML = '<tr><td colspan="7" class="text-center py-3 text-secondary">Sem ações no período selecionado</td></tr>';
        return;
      }
      E.panelAuditBody.innerHTML = actions.map(item => {
        const target = [item.target_type, item.target_id].filter(Boolean).join(" ");
        const statusClass = String(item.status || "") === "success" ? "text-success" : "text-warning";
        return `
          <tr>
            <td>${escapeHtml(item.created_at_local || formatDateTime(item.created_at))}</td>
            <td>
              <strong>${escapeHtml(item.username || "-")}</strong>
              ${item.display_name ? `<div class="small text-secondary">${escapeHtml(item.display_name)}</div>` : ""}
            </td>
            <td><span class="mono">${escapeHtml(item.module || "-")}</span></td>
            <td>${escapeHtml(item.action || "-")}</td>
            <td>${escapeHtml(target || "-")}</td>
            <td><strong class="${statusClass}">${escapeHtml(item.status || "-")}</strong></td>
            <td><span class="mono">${escapeHtml(item.ip_address || "-")}</span></td>
          </tr>
        `;
      }).join("");
    }

    async function syncPanelAuditActions({ silent = true } = {}) {
      if (!hasPanelAuth()) {
        if (!silent) addLog("Sessão do painel não validada.", "warn");
        return false;
      }
      let params;
      try {
        params = getPanelAuditParams();
      } catch (err) {
        if (!silent) addLog(err.message, "warn");
        return false;
      }
      const btn = E.panelAuditRefreshBtn;
      const previousLabel = btn ? btn.innerHTML : "";
      if (btn && !silent) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Atualizando';
      }
      try {
        const payload = await req(`${CONFIG.endpoints.usage.panelActions}?${params.toString()}`, { timeoutMs: 30000 });
        state.panelAudit = payload && typeof payload === "object" ? payload : null;
        renderPanelAuditActions();
        if (!silent) addLog("Ações do painel atualizadas.", "ok");
        return true;
      } catch (err) {
        if (state.panelAudit === null) renderPanelAuditActions();
        if (!silent) addLog(`Falha ao consultar ações do painel: ${err.message}`, "warn");
        return false;
      } finally {
        if (btn && !silent) {
          btn.disabled = false;
          btn.innerHTML = previousLabel;
        }
      }
    }

    async function exportPanelAuditActionsReport() {
      updateTokens();
      if (!hasPanelAuth()) {
        addLog("Sessão do painel não validada.", "warn");
        return;
      }
      let params;
      try {
        params = getPanelAuditParams();
      } catch (err) {
        addLog(err.message, "warn");
        return;
      }
      params.set("limit", "5000");
      const headers = {};
      if (state.tokens.api) headers["x-api-token"] = state.tokens.api;
      if (state.tokens.admin) headers["x-admin-token"] = state.tokens.admin;
      const btn = E.panelAuditExportBtn;
      const previousLabel = btn ? btn.innerHTML : "";
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Exportando';
      }
      try {
        const response = await fetch(
          `${CONFIG.api}${CONFIG.endpoints.usage.panelActionsReport}?${params.toString()}`,
          { method: "GET", headers, credentials: "same-origin" }
        );
        if (!response.ok) {
          const errPayload = await response.json().catch(() => null);
          throw new Error(errPayload && errPayload.detail ? errPayload.detail : `HTTP ${response.status}`);
        }
        const blob = await response.blob();
        const disposition = response.headers.get("content-disposition") || "";
        const matchedName = disposition.match(/filename=\"?([^\";]+)\"?/i);
        const filename = matchedName && matchedName[1] ? matchedName[1] : "acoes_painel.csv";
        const blobUrl = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = blobUrl;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(blobUrl);
        addLog("Ações do painel exportadas com sucesso.", "ok");
      } catch (err) {
        addLog(`Falha ao exportar ações do painel: ${err.message}`, "err");
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = previousLabel;
        }
      }
    }

    function resetBroadcastPreview() {
      state.broadcast.preview = null;
      if (E.broadcastRunBtn) E.broadcastRunBtn.disabled = true;
      if (E.broadcastSummary) E.broadcastSummary.textContent = "Clique em Prévia para carregar os destinatários.";
      if (E.broadcastRecipientsBody) {
        E.broadcastRecipientsBody.innerHTML = '<tr><td colspan="4" class="text-center py-3 text-secondary">Sem prévia carregada</td></tr>';
      }
      if (E.broadcastSelectAll) {
        E.broadcastSelectAll.checked = false;
        E.broadcastSelectAll.indeterminate = false;
        E.broadcastSelectAll.disabled = true;
      }
    }

    function broadcastRecipientChecks() {
      return E.broadcastRecipientsBody
        ? Array.from(E.broadcastRecipientsBody.querySelectorAll(".broadcast-recipient-check"))
        : [];
    }

    function selectedBroadcastNumbers() {
      return broadcastRecipientChecks()
        .filter(item => item.checked)
        .map(item => item.value)
        .filter(Boolean);
    }

    function updateBroadcastSummaryFromSelection() {
      const preview = state.broadcast.preview;
      const recipients = preview && Array.isArray(preview.recipients) ? preview.recipients : [];
      const selectedCount = selectedBroadcastNumbers().length;
      const total = recipients.length;

      if (E.broadcastSelectAll) {
        E.broadcastSelectAll.disabled = total === 0;
        E.broadcastSelectAll.checked = total > 0 && selectedCount === total;
        E.broadcastSelectAll.indeterminate = selectedCount > 0 && selectedCount < total;
      }
      if (E.broadcastRunBtn) E.broadcastRunBtn.disabled = selectedCount === 0;

      if (!E.broadcastSummary || !preview) return;
      const dayText = preview.supports_day ? ` Dia: ${preview.day_label || "-"}.` : "";
      const audienceLabel = preview.target_audience_label || "Vendedores (RN)";
      const targetText = preview.target_mode === "specific"
        ? ` Destino: número específico ${formatPhoneForUi(preview.target_number || "")}.`
        : ` Destino: ${audienceLabel} da filial ${preview.filial || "-"}.`;
      E.broadcastSummary.textContent = `${formatNumber(selectedCount)} de ${formatNumber(total)} destinatário(s) selecionado(s) para ${preview.action_label || "-"}.${dayText}${targetText} Atalho: ${preview.shortcut || "-"}.`;
    }

    function toggleBroadcastSelectAll() {
      const checked = Boolean(E.broadcastSelectAll && E.broadcastSelectAll.checked);
      for (const item of broadcastRecipientChecks()) item.checked = checked;
      updateBroadcastSummaryFromSelection();
    }

    function selectedBroadcastAction() {
      const actionId = E.broadcastAction ? E.broadcastAction.value : "";
      const actions = Array.isArray(state.broadcast.actions) ? state.broadcast.actions : [];
      return actions.find(item => item.id === actionId) || null;
    }

    function syncBroadcastDayState() {
      const action = selectedBroadcastAction();
      const supportsDay = !action || Boolean(action.supports_day);
      if (E.broadcastDay) {
        E.broadcastDay.disabled = !supportsDay;
        if (!supportsDay) E.broadcastDay.value = "hoje";
      }
    }

    function syncBroadcastTargetModeState() {
      const mode = E.broadcastTargetMode ? E.broadcastTargetMode.value : "filial";
      const isSpecific = mode === "specific";
      if (E.broadcastTargetNumberWrap) E.broadcastTargetNumberWrap.classList.toggle("d-none", !isSpecific);
      if (E.broadcastTargetNumber) E.broadcastTargetNumber.disabled = !isSpecific;
    }

    function renderBroadcastStatus(status) {
      const payload = status && typeof status === "object" ? status : {};
      if (!E.broadcastStatus) return;
      if (payload.running) {
        const sent = Number(payload.sent || 0);
        const total = Number(payload.total || 0);
        const failed = Number(payload.failed || 0);
        const skipped = Number(payload.skipped || 0);
        E.broadcastStatus.textContent = `Disparo em andamento: ${sent}/${total} enviados, ${failed} erro(s), ${skipped} ignorado(s)`;
        E.broadcastStatus.className = "pill warn";
        return;
      }
      const lastJob = payload.last_job && typeof payload.last_job === "object" ? payload.last_job : null;
      if (lastJob && lastJob.job_id) {
        E.broadcastStatus.textContent = `Último disparo: ${lastJob.sent || 0}/${lastJob.total || 0} enviados`;
        E.broadcastStatus.className = Number(lastJob.failed || 0) > 0 ? "pill warn" : "pill ok";
        return;
      }
      E.broadcastStatus.textContent = "Nenhum disparo em andamento";
      E.broadcastStatus.className = "pill";
    }

    function renderBroadcastOptions() {
      if (E.broadcastAction) {
        const selectedAction = E.broadcastAction.value;
        const selectedAudience = E.broadcastAudience ? E.broadcastAudience.value || "vendedor" : "vendedor";
        const actions = (Array.isArray(state.broadcast.actions) ? state.broadcast.actions : [])
          .filter(item => {
            const audiences = Array.isArray(item.target_audiences) ? item.target_audiences : [];
            return !audiences.length || audiences.includes(selectedAudience);
          });
        E.broadcastAction.innerHTML = actions.length
          ? actions.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.label)}</option>`).join("")
          : '<option value="">Sem mensagens disponíveis</option>';
        if (selectedAction && actions.some(item => item.id === selectedAction)) E.broadcastAction.value = selectedAction;
      }

      if (E.broadcastDay) {
        const selectedDay = E.broadcastDay.value || "hoje";
        const days = Array.isArray(state.broadcast.days) && state.broadcast.days.length
          ? state.broadcast.days
          : [{ id: "hoje", label: "Hoje" }];
        E.broadcastDay.innerHTML = days.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.label)}</option>`).join("");
        if (selectedDay && days.some(item => item.id === selectedDay)) E.broadcastDay.value = selectedDay;
      }

      if (E.broadcastTargetMode) {
        const selectedMode = E.broadcastTargetMode.value || "filial";
        const modes = Array.isArray(state.broadcast.targetModes) && state.broadcast.targetModes.length
          ? state.broadcast.targetModes
          : [{ id: "filial", label: "Todos da filial" }, { id: "specific", label: "Número específico" }];
        E.broadcastTargetMode.innerHTML = modes.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.label)}</option>`).join("");
        if (selectedMode && modes.some(item => item.id === selectedMode)) E.broadcastTargetMode.value = selectedMode;
      }

      if (E.broadcastAudience) {
        const selectedAudience = E.broadcastAudience.value || "vendedor";
        const audiences = Array.isArray(state.broadcast.targetAudiences) && state.broadcast.targetAudiences.length
          ? state.broadcast.targetAudiences
          : [{ id: "vendedor", label: "Vendedores (RN)" }, { id: "gerente_vendas", label: "GVs" }];
        E.broadcastAudience.innerHTML = audiences.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.label)}</option>`).join("");
        if (selectedAudience && audiences.some(item => item.id === selectedAudience)) E.broadcastAudience.value = selectedAudience;
      }

      if (E.broadcastFilial) {
        const selectedFilial = E.broadcastFilial.value;
        const selectedAudience = E.broadcastAudience ? E.broadcastAudience.value || "vendedor" : "vendedor";
        const filiais = (Array.isArray(state.broadcast.filiais) ? state.broadcast.filiais : [])
          .map(item => ({ ...item, audience_total: Number(item[selectedAudience] || 0) }))
          .filter(item => item.audience_total > 0);
        E.broadcastFilial.innerHTML = filiais.length
          ? filiais.map(item => `<option value="${escapeHtml(item.filial)}">Operação ${escapeHtml(item.filial)} (${formatNumber(item.audience_total)})</option>`).join("")
          : '<option value="">Sem operações cadastradas</option>';
        if (selectedFilial && filiais.some(item => String(item.filial) === selectedFilial)) E.broadcastFilial.value = selectedFilial;
      }

      syncBroadcastDayState();
      syncBroadcastTargetModeState();
      renderBroadcastStatus(state.broadcast.status);
      if (!state.broadcast.preview) resetBroadcastPreview();
    }

    async function syncBroadcastOptions({ silent = true } = {}) {
      if (!hasPanelAuth()) return false;
      try {
        const payload = await req(CONFIG.endpoints.broadcast.options, { timeoutMs: 30000 });
        state.broadcast.actions = Array.isArray(payload.actions) ? payload.actions : [];
        state.broadcast.days = Array.isArray(payload.days) ? payload.days : [];
        state.broadcast.targetModes = Array.isArray(payload.target_modes) ? payload.target_modes : [];
        state.broadcast.targetAudiences = Array.isArray(payload.target_audiences) ? payload.target_audiences : [];
        state.broadcast.filiais = Array.isArray(payload.filiais) ? payload.filiais : [];
        state.broadcast.status = payload.status || null;
        renderBroadcastOptions();
        return true;
      } catch (err) {
        if (!silent) addLog(`Falha ao carregar opções de disparo: ${err.message}`, "warn");
        renderBroadcastOptions();
        return false;
      }
    }

    async function syncBroadcastStatus({ silent = true } = {}) {
      if (!hasPanelAuth()) return false;
      try {
        const payload = await req(CONFIG.endpoints.broadcast.status, { timeoutMs: 30000 });
        state.broadcast.status = payload || null;
        renderBroadcastStatus(state.broadcast.status);
        if (!silent) addLog("Status do disparo atualizado.", "ok");
        return Boolean(payload && payload.running);
      } catch (err) {
        if (!silent) addLog(`Falha ao consultar status do disparo: ${err.message}`, "warn");
        return false;
      }
    }

    function currentBroadcastRequest() {
      return {
        filial: E.broadcastFilial ? E.broadcastFilial.value : "",
        action: E.broadcastAction ? E.broadcastAction.value : "",
        day: E.broadcastDay ? E.broadcastDay.value : "hoje",
        target_mode: E.broadcastTargetMode ? E.broadcastTargetMode.value : "filial",
        target_audience: E.broadcastAudience ? E.broadcastAudience.value : "vendedor",
        target_number: E.broadcastTargetNumber ? E.broadcastTargetNumber.value : ""
      };
    }

    function renderBroadcastPreview(payload) {
      state.broadcast.preview = payload && typeof payload === "object" ? payload : null;
      const recipients = state.broadcast.preview && Array.isArray(state.broadcast.preview.recipients)
        ? state.broadcast.preview.recipients
        : [];
      if (!E.broadcastRecipientsBody) return;
      if (!recipients.length) {
        E.broadcastRecipientsBody.innerHTML = '<tr><td colspan="4" class="text-center py-3 text-secondary">Nenhum destinatário encontrado</td></tr>';
        updateBroadcastSummaryFromSelection();
        return;
      }
      E.broadcastRecipientsBody.innerHTML = recipients.map(item => `
        <tr>
          <td class="ps-3 broadcast-select-cell">
            <input class="form-check-input broadcast-recipient-check" type="checkbox" value="${escapeHtml(item.phone_number || "")}" checked aria-label="Selecionar ${escapeHtml(item.name || item.phone_number || "destinatario")}">
          </td>
          <td><strong>${escapeHtml(item.name || "-")}</strong></td>
          <td>
            <span class="badge text-bg-light border">${escapeHtml(item.role || "-")}</span>
            ${item.shortcut ? `<div class="small mono text-secondary mt-1">${escapeHtml(item.shortcut)}</div>` : ""}
          </td>
          <td><span class="mono">${escapeHtml(formatPhoneForUi(item.phone_number || ""))}</span></td>
        </tr>
      `).join("");
      for (const item of broadcastRecipientChecks()) {
        item.addEventListener("change", updateBroadcastSummaryFromSelection);
      }
      updateBroadcastSummaryFromSelection();
    }

    async function previewBroadcast() {
      updateTokens();
      if (!hasPanelAuth()) { addLog("Sessão do painel não validada.", "warn"); return; }
      const payload = currentBroadcastRequest();
      if (!payload.filial || !payload.action) { addLog("Escolha a operação e a mensagem do disparo.", "warn"); return; }
      if (payload.target_mode === "specific" && !payload.target_number.trim()) {
        addLog("Informe o número específico para teste.", "warn");
        return;
      }
      const btn = E.broadcastPreviewBtn;
      const previousLabel = btn ? btn.innerHTML : "";
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Carregando';
      }
      try {
        const result = await req(CONFIG.endpoints.broadcast.preview, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          timeoutMs: 30000
        });
        renderBroadcastPreview(result);
        addLog(`Prévia carregada: ${result.total || 0} destinatário(s).`, "ok");
      } catch (err) {
        resetBroadcastPreview();
        addLog(`Falha ao carregar prévia do disparo: ${err.message}`, "err");
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = previousLabel;
        }
      }
    }

    async function runBroadcast() {
      updateTokens();
      if (!hasPanelAuth()) { addLog("Sessão do painel não validada.", "warn"); return; }
      const payload = currentBroadcastRequest();
      const preview = state.broadcast.preview;
      const checkedNumbers = selectedBroadcastNumbers();
      const targetChanged = preview && preview.target_mode === "specific"
        ? comparablePhoneDigits(preview.target_number || "") !== comparablePhoneDigits(payload.target_number || "")
        : false;
      if (
        !preview
        || preview.filial !== payload.filial
        || preview.action !== payload.action
        || preview.day !== payload.day
        || preview.target_mode !== payload.target_mode
        || preview.target_audience !== payload.target_audience
        || targetChanged
      ) {
        addLog("Carregue a prévia antes de disparar.", "warn");
        return;
      }
      const total = checkedNumbers.length;
      if (total <= 0) { addLog("Selecione ao menos um destinatário para disparar.", "warn"); return; }
      payload.selected_numbers = checkedNumbers;
      const targetLabel = preview.target_mode === "specific"
        ? `o número ${formatPhoneForUi(preview.target_number || "")}`
        : `${total} destinatário(s) selecionado(s) da operação ${preview.filial}`;
      const dayLabel = preview.supports_day ? ` (${preview.day_label})` : "";
      const confirmed = await askConfirmation(`Disparar "${preview.action_label}${dayLabel}" para ${targetLabel}?`);
      if (!confirmed) return;

      const btn = E.broadcastRunBtn;
      const previousLabel = btn ? btn.innerHTML : "";
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Enfileirando';
      }
      try {
        const result = await req(CONFIG.endpoints.broadcast.run, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          timeoutMs: 60000
        });
        state.broadcast.status = {
          running: true,
          current_job_id: result.job_id,
          current_filial: result.filial,
          current_action: result.action,
          total: result.total,
          sent: 0,
          failed: 0,
          skipped: 0
        };
        renderBroadcastStatus(state.broadcast.status);
        addLog(`Disparo iniciado: ${result.total || 0} destinatário(s).`, "ok");
        pollBroadcastStatus();
      } catch (err) {
        addLog(`Falha ao iniciar disparo: ${err.message}`, "err");
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = previousLabel;
        }
      }
    }

    async function pollBroadcastStatus() {
      if (state.broadcast.polling) return;
      state.broadcast.polling = true;
      try {
        let keepPolling = true;
        while (keepPolling) {
          await new Promise(resolve => setTimeout(resolve, 2500));
          keepPolling = await syncBroadcastStatus({ silent: true });
        }
        await syncBroadcastOptions({ silent: true });
        await syncPayipBatchStatus({ silent: true });
      } finally {
        state.broadcast.polling = false;
      }
    }
