    function datasetUiId(apiName) {
      const name = String(apiName || "").toLowerCase();
      const boletoMatch = name.match(/^boletos_bradesco_op_(\d+)$/);
      if (boletoMatch) return `BoletosOp${boletoMatch[1]}`;
      const estoqueMatch = name.match(/^estoque_020304_op_(\d+)$/);
      if (estoqueMatch) return `Estoque020304Op${estoqueMatch[1]}`;
      const rel031120Match = name.match(/^relatorio_031120_op_(\d+)$/);
      if (rel031120Match) return `Relatorio031120Op${rel031120Match[1]}`;
      if (name === "relatorio_03114902_geo") return "Relatorio03114902Csv";
      const criticaMatch = name.match(/^critica_op_(\d+)$/);
      if (criticaMatch) return `CriticaOp${criticaMatch[1]}`;
      if (DATASET_UI_OVERRIDES[name] && DATASET_UI_OVERRIDES[name].id) return DATASET_UI_OVERRIDES[name].id;
      if (name.startsWith("liga_")) return name.replace(/(^|_)([a-z0-9])/g, (_, __, chr) => chr.toUpperCase());
      return name.replace(/(^|_)([a-z0-9])/g, (_, __, chr) => chr.toUpperCase());
    }

    function datasetArea(apiName) {
      const name = String(apiName || "").toLowerCase();
      if (DATASET_UI_OVERRIDES[name] && DATASET_UI_OVERRIDES[name].area) return DATASET_UI_OVERRIDES[name].area;
      if (name.startsWith("critica_op_")) return "critica";
      if (name.startsWith("boletos_bradesco_op_")) return "promax";
      if (name.startsWith("estoque_020304_op_")) return "promax";
      if (name.startsWith("relatorio_031120_op_")) return "promax";
      if (name === "relatorio_03114902_geo") return "promax";
      if (name.startsWith("liga_")) return "promax";
      if (["prazo_limite", "giro"].includes(name)) return "powerbi";
      if (["dsetores", "dprecos", "doperacoes", "drevendas", "dcondicoes", "dprodutos", "dgarrafeiras", "dmateriais", "produto_cestas"].includes(name)) return "operational";
      return "promax";
    }

    function datasetIcon(apiName) {
      const name = String(apiName || "").toLowerCase();
      if (DATASET_UI_OVERRIDES[name] && DATASET_UI_OVERRIDES[name].icon) return DATASET_UI_OVERRIDES[name].icon;
      if (name.startsWith("critica_op_")) return "bi-clipboard-data";
      if (name.startsWith("boletos_bradesco_op_")) return "bi-upc-scan";
      if (name.startsWith("estoque_020304_op_")) return "bi-boxes";
      if (name.startsWith("relatorio_031120_op_")) return "bi-map";
      if (name === "relatorio_03114902_geo") return "bi-filetype-csv";
      if (name.startsWith("liga_")) return "bi-trophy";
      return "bi-table";
    }

    function datasetGroup(apiName) {
      const name = String(apiName || "").toLowerCase();
      if (DATASET_UI_OVERRIDES[name] && DATASET_UI_OVERRIDES[name].group) return DATASET_UI_OVERRIDES[name].group;
      if (name.startsWith("critica_op_")) return "Promax 030111 - Crítica por operação";
      if (name.startsWith("estoque_020304_op_")) return "Promax 020304 - Estoque por operação";
      if (name.startsWith("relatorio_031120_op_")) return "Promax 031120 - Mapa por operação";
      if (name === "relatorio_03114902_geo") return "Promax 03114902 - CSV";
      if (name.startsWith("liga_")) return "Liga Entrega";
      if (datasetArea(name) === "operational") return "Operacional";
      if (datasetArea(name) === "powerbi") return "Power BI";
      return "Promax";
    }

    function datasetGroupNote(apiName) {
      const name = String(apiName || "").toLowerCase();
      if (DATASET_UI_OVERRIDES[name] && DATASET_UI_OVERRIDES[name].groupNote) return DATASET_UI_OVERRIDES[name].groupNote;
      if (name.startsWith("critica_op_")) return "Use o card de Importação geral para um CSV completo ou envie um arquivo separado nesta operação.";
      if (name.startsWith("estoque_020304_op_")) return "Upload separado por filial. O bot envia o PDF ativo pelo comando estoque filial.";
      if (name.startsWith("relatorio_031120_op_")) return "Upload separado por filial. Rotina 031120 com classificacao Mapa e armazem central.";
      if (name === "relatorio_03114902_geo") return "Relatório único para todas as operações. Rotina 03114902 gerada pelo botão Gerar CSV.";
      if (name.startsWith("liga_")) return "Arquivos usados para montar o painel da Liga. A 03.08.05 fica diaria; os demais usam o último lote importado.";
      return "";
    }

    function datasetUploadMetaForItem(item, ds) {
      const apiName = String(item.dataset || ds.apiName || "").toLowerCase();
      const accept = String(item.accept_extensions || ".csv");
      const mode = String(item.upload_mode || "single");
      if (apiName.startsWith("boletos_bradesco_op_")) {
        return { accept, mode, label: "PDF da Operação", emptyHint: `Selecione o PDF de boletos da operação ${apiName.replace("boletos_bradesco_op_", "")}.` };
      }
      if (apiName.startsWith("estoque_020304_op_")) {
        return { accept, mode, label: "CSV da Operação", emptyHint: `Selecione o CSV 020304 da operação ${apiName.replace("estoque_020304_op_", "")}.` };
      }
      if (apiName.startsWith("relatorio_031120_op_")) {
        return { accept, mode, label: "CSV da Operação", emptyHint: `Selecione o CSV 031120 da operação ${apiName.replace("relatorio_031120_op_", "")}.` };
      }
      if (apiName === "relatorio_03114902_geo") {
        return { accept, mode, label: "CSV", emptyHint: "Selecione o CSV 03114902 consolidado." };
      }
      if (apiName.startsWith("liga_")) {
        const isDaily = apiName === "liga_030805";
        const label = apiName === "liga_checklist_frota" ? "Checklist Frota" : (apiName === "liga_espelho_ponto" ? "Espelho de ponto" : "Arquivo(s) da Liga");
        return {
          accept,
          mode,
          label,
          emptyHint: isDaily
            ? "Selecione os arquivos da 03.08.05 do dia, normalmente PATOS_DD_MM e SUME_DD_MM."
            : "Selecione o(s) arquivo(s) mais recente(s) deste relatório da Liga."
        };
      }
      if (apiName.startsWith("critica_op_")) {
        return { accept, mode, label: "CSV da Operação", emptyHint: `Selecione o CSV da operação ${apiName.replace("critica_op_", "")}.` };
      }
      if (accept.includes(".xls") && accept.includes(".csv")) {
        return { accept, mode, label: "Planilha do Dataset", emptyHint: "Selecione um arquivo Excel ou CSV." };
      }
      if (accept.includes(".xls")) {
        return { accept, mode, label: "Planilha do Dataset", emptyHint: "Selecione um arquivo Excel." };
      }
      return {
        accept,
        mode,
        label: mode === "multiple" ? "CSV do Dataset(s)" : "CSV do Dataset",
        emptyHint: mode === "multiple" ? "Selecione um ou mais arquivos CSV." : "Selecione um arquivo CSV."
      };
    }

    function normalizeImportDatasetItem(item) {
      const apiName = String(item && item.dataset ? item.dataset : "").toLowerCase();
      if (!apiName) return null;
      const override = DATASET_UI_OVERRIDES[apiName] || {};
      const ds = {
        id: datasetUiId(apiName),
        apiName,
        name: override.name || item.label || apiName,
        icon: datasetIcon(apiName),
        area: datasetArea(apiName),
        group: datasetGroup(apiName),
        groupNote: datasetGroupNote(apiName),
        disabled: Boolean(override.disabled),
        badge: override.badge || "",
        description: override.description || "",
        sourcePath: override.sourcePath || item.default_path || ""
      };
      return ds;
    }

    function buildFallbackImportDatasets() {
      return DATASET_FALLBACK_ORDER
        .map(dataset => normalizeImportDatasetItem({ dataset, label: (DATASET_UI_OVERRIDES[dataset] || {}).name || dataset }))
        .filter(Boolean);
    }

    function rebuildDatasetIndexes() {
      DATASET_MAP = {};
      DATASET_UPLOAD_META = {};
      CONFIG.datasets.forEach(ds => {
        const apiName = String(ds.apiName || ds.id || "").toLowerCase();
        DATASET_MAP[ds.id] = apiName;
        DATASET_UPLOAD_META[ds.id] = datasetUploadMetaForItem({
          dataset: apiName,
          accept_extensions: ds.acceptExtensions || ".csv",
          upload_mode: ds.uploadMode || "single"
        }, ds);
      });
    }

    function syncDatasetsFromImportStatus(statusPayload) {
      const items = statusPayload && Array.isArray(statusPayload.items) ? statusPayload.items : [];
      if (!items.length) return;
      CONFIG.datasets = items
        .map(item => {
          const ds = normalizeImportDatasetItem(item);
          if (!ds) return null;
          ds.acceptExtensions = item.accept_extensions || ".csv";
          ds.uploadMode = item.upload_mode || "single";
          return ds;
        })
        .filter(Boolean);
      rebuildDatasetIndexes();
    }

    function gradeCsvCell(value) {
      return `"${String(value ?? "").replaceAll('"', '""')}"`;
    }

    function gradeCsvBase64(text) {
      const bytes = new TextEncoder().encode(text);
      let binary = "";
      for (let offset = 0; offset < bytes.length; offset += 8192) binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
      return btoa(binary);
    }

    function downloadGradeTemplate(filename, content) {
      const blobUrl = URL.createObjectURL(new Blob([content], { type: "text/csv;charset=utf-8" }));
      const anchor = document.createElement("a");
      anchor.href = blobUrl;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(blobUrl);
    }

    function manualGradeField(row, name) {
      const field = row.querySelector(`[data-field="${name}"]`);
      return String(field && field.value || "").trim();
    }

    function toApiDataset(dsId) {
      return DATASET_MAP[dsId] || String(dsId || "").toLowerCase();
    }

    function isBoletoDataset(dsId) {
      return String(toApiDataset(dsId) || "").toLowerCase().startsWith("boletos_bradesco_op_");
    }

    function fromApiDataset(dsName) {
      const name = String(dsName || "").toLowerCase();
      const found = Object.entries(DATASET_MAP).find(([, apiName]) => apiName === name);
      return found ? found[0] : dsName;
    }

    function datasetTimeouts(dsId) {
      const apiName = toApiDataset(dsId);
      if (String(apiName || "").startsWith("boletos_bradesco_op_")) {
        return { validateMs: 600000, importMs: 1800000 };
      }
      return DATASET_TIMEOUTS[dsId] || DATASET_TIMEOUTS.default;
    }

    function getDatasetStatus(dsId) {
      const apiDs = toApiDataset(dsId);
      const statusItems = state.status && Array.isArray(state.status.items) ? state.status.items : [];
      const statusItem = statusItems.find(item => item.dataset === apiDs);
      const activeJobs = state.status && Array.isArray(state.status.current_jobs) ? state.status.current_jobs : [];
      const datasetRunning = activeJobs.some(job => String(job.dataset || "") === apiDs);
      return {
        import: statusItem && statusItem.last_import ? {
          batch_id: statusItem.last_import.batch_id,
          total_processed_rows: statusItem.last_import.total_rows,
          reference_date: statusItem.last_import.reference_date,
          status: datasetRunning ? "in_progress" : "completed"
        } : null,
        statusItem: statusItem || null,
        activeJob: activeJobs.find(job => String(job.dataset || "") === apiDs) || null
      };
    }

    function groupedDatasets(datasets) {
      const groups = [];
      (Array.isArray(datasets) ? datasets : CONFIG.datasets).forEach(ds => {
        const name = ds.group || "Relatórios";
        let group = groups.find(item => item.name === name);
        if (!group) {
          group = { name, note: ds.groupNote || "", items: [] };
          groups.push(group);
        }
        if (!group.note && ds.groupNote) group.note = ds.groupNote;
        group.items.push(ds);
      });
      return groups;
    }

    function datasetCardHtml(ds) {
      const referenceDateBlock = isBoletoDataset(ds.id) ? `
            <div id="datewrapper-${ds.id}">
              <div class="form-label small fw-semibold mb-1">Referência dos boletos</div>
              <div class="form-text">Sempre será gravada a data em que o PDF foi enviado pelo painel.</div>
            </div>
      ` : `
            <div id="datewrapper-${ds.id}">
              <label class="form-label small fw-semibold mb-1">Data de Referência
                <input type="date" class="form-control form-control-sm" id="date-${ds.id}">
              </label>
              <div class="form-text">Opcional. Se informar, essa data será gravada no lote importado.</div>
            </div>
      `;
      const disabledBody = ds.disabled ? `
            <div class="small text-secondary d-grid gap-1" id="meta-${ds.id}">${escapeHtml(ds.description || "Tabela operacional sem importação ativa.")}</div>
            <div id="val-${ds.id}">
              <div class="source-box">
                <div class="small text-secondary">Fonte local</div>
                <div class="source-path">${escapeHtml(ds.sourcePath || "-")}</div>
              </div>
            </div>
            <div class="d-grid gap-2" id="btns-${ds.id}"></div>
      ` : `
            <div class="small text-secondary d-grid gap-1" id="meta-${ds.id}">Sem dados ainda.</div>
            <label class="form-label small fw-semibold mb-1">${(DATASET_UPLOAD_META[ds.id] || {}).label || "Arquivo(s) do Dataset"}
              <input
                type="file"
                class="form-control form-control-sm"
                id="file-${ds.id}"
                accept="${(DATASET_UPLOAD_META[ds.id] || {}).accept || ".csv"}"
                ${(DATASET_UPLOAD_META[ds.id] || {}).mode === "multiple" ? "multiple" : ""}
              >
            </label>
            <div class="form-text" id="filehint-${ds.id}">${(DATASET_UPLOAD_META[ds.id] || {}).emptyHint || "Selecione o arquivo do dataset."}</div>
            <div class="file-list" id="filelist-${ds.id}"></div>
            ${referenceDateBlock}
            <div id="val-${ds.id}"></div>
            <div class="d-grid gap-2" id="btns-${ds.id}"></div>
      `;
      return `
        <article class="dataset-card ${ds.disabled ? "is-disabled" : ""}" id="card-${ds.id}">
          <header class="dataset-head d-flex justify-content-between align-items-center">
            <h3 class="h6 mb-0 fw-bold"><i class="bi ${ds.icon} text-primary me-2"></i>${ds.name}</h3>
            <div id="stat-${ds.id}"></div>
          </header>
          <div class="dataset-body">${disabledBody}</div>
        </article>
      `;
    }

    function renderDatasetGrid(container, datasets) {
      if (!container) return;
      container.innerHTML = groupedDatasets(datasets).map(group => `
        <section class="dataset-group">
          <div class="dataset-group-head">
            <div>
              <h3 class="dataset-group-title">${escapeHtml(group.name)}</h3>
              ${group.note ? `<p class="dataset-group-note">${escapeHtml(group.note)}</p>` : ""}
            </div>
            <span class="badge text-bg-light border">${group.items.length} item(ns)</span>
          </div>
          <div class="dataset-grid">
            ${group.items.map(datasetCardHtml).join("")}
          </div>
        </section>
      `).join("");
    }

    function buildGrid() {
      renderDatasetGrid(E.operationalGrid, CONFIG.datasets.filter(ds => ds.area === "operational"));
      renderDatasetGrid(E.criticaGrid, CONFIG.datasets.filter(ds => ds.area === "critica"));
      renderDatasetGrid(E.reportGrid, CONFIG.datasets.filter(ds => ds.area === "promax"));
      renderDatasetGrid(E.powerBiGrid, CONFIG.datasets.filter(ds => ds.area === "powerbi"));
      CONFIG.datasets.filter(ds => !ds.disabled).forEach(ds => {
        const inp = document.getElementById(`file-${ds.id}`);
        const hint = document.getElementById(`filehint-${ds.id}`);
        const list = document.getElementById(`filelist-${ds.id}`);
        const meta = DATASET_UPLOAD_META[ds.id] || {};
        if (!inp || !hint) return;
        inp.addEventListener("change", () => {
          const total = inp.files ? inp.files.length : 0;
          hint.textContent = total > 0
            ? `${total} arquivo(s) selecionado(s).`
            : (meta.emptyHint || "Selecione o arquivo do dataset.");
          if (!list) return;
          if (!total) {
            list.innerHTML = "";
            return;
          }
          const names = Array.from(inp.files).slice(0, 3).map(f => `<span>• ${escapeHtml(f.name)}</span>`);
          if (total > 3) names.push(`<span>• +${total - 3} arquivo(s)</span>`);
          list.innerHTML = names.join("");
        });
      });

      CONFIG.datasets.filter(ds => !ds.disabled).forEach(ds => {
        const fileInput = document.getElementById(`file-${ds.id}`);
        if (!fileInput) return;
        fileInput.addEventListener("change", (e) => {
          const file = e.target.files && e.target.files[0] ? e.target.files[0] : null;
          if (!file) return;
          if (isBoletoDataset(ds.id)) return;
          const m = file.name.match(/(\d{2})[-_](\d{2})[-_](\d{4})/);
          if (m) {
            const dateInput = document.getElementById(`date-${ds.id}`);
            if (dateInput && !dateInput.value) {
              dateInput.value = `${m[3]}-${m[2]}-${m[1]}`;
            }
          }
        });
      });
    }

    function renderGridPanels() {
      CONFIG.datasets.forEach(ds => {
        const s = getDatasetStatus(ds.id);
        const st = document.getElementById(`stat-${ds.id}`);
        const meta = document.getElementById(`meta-${ds.id}`);
        const valBox = document.getElementById(`val-${ds.id}`);
        const btns = document.getElementById(`btns-${ds.id}`);
        const card = document.getElementById(`card-${ds.id}`);
        if (card) card.classList.remove("is-loading");

        if (ds.disabled) {
          if (st) st.innerHTML = `<span class="badge text-bg-secondary">${escapeHtml(ds.badge || "Inativo")}</span>`;
          if (meta) {
            meta.innerHTML = `<div class="dataset-meta"><div><span class="label">Estado:</span><span class="value">Importação não habilitada</span></div><div><span class="label">Uso:</span><span class="value">${escapeHtml(ds.description || "Tabela operacional de apoio.")}</span></div></div>`;
          }
          if (valBox) {
            valBox.innerHTML = `<div class="source-box"><div class="small text-secondary">Fonte local</div><div class="source-path">${escapeHtml(ds.sourcePath || "-")}</div></div>`;
          }
          if (btns) {
            btns.innerHTML = '<button class="btn btn-outline-secondary btn-sm" disabled><i class="bi bi-lock me-1"></i>Sem importação no painel</button>';
          }
          return;
        }

        let statusUi = "<span class='badge text-bg-secondary'>Sem historico</span>";
        let metaHtml = "<div class='dataset-meta'><div><span class='label'>Estado:</span><span class='value'>Aguardando primeira importação</span></div></div>";
        let valHtml = "";
        const isBusy = state.datasetBusy[ds.id] === true;
        let buttonsHtml = `<button class="btn btn-outline-primary btn-sm" ${isBusy ? "disabled" : ""} onclick="validateCSV('${ds.id}')"><i class="bi bi-check2-circle me-1"></i>${isBusy ? "Processando" : "Validar"}</button><button class="btn btn-primary btn-sm" ${isBusy ? "disabled" : ""} onclick="startImport('${ds.id}')"><i class="bi bi-cloud-arrow-up me-1"></i>${isBusy ? "Aguarde" : "Importar"}</button>`;

        if (s.activeJob) {
          statusUi = `<span class="badge text-bg-warning">Em processamento</span>`;
          metaHtml = `<div class="dataset-meta"><div><span class="label">Job:</span><span class="value">${escapeHtml(String(s.activeJob.job_id || "").substring(0, 12))}</span></div><div><span class="label">Estado:</span><span class="value">Processando no servidor</span></div></div>`;
        }

        if (s.import) {
          const l = s.import;
          const map = { completed:["text-bg-success","Importado"], failed:["text-bg-danger","Falhou"], in_progress:["text-bg-warning","Importando"] };
          const x = map[l.status] || ["text-bg-secondary", l.status || "Status"];
          statusUi = `<span class="badge ${escapeHtml(x[0])}">${escapeHtml(x[1])}</span>`;
          metaHtml = `<div class="dataset-meta"><div><span class="label">Lote:</span><span class="value">${escapeHtml(String(l.batch_id || "").split("-")[0])}...</span></div><div><span class="label">Linhas:</span><span class="value">${escapeHtml(l.total_processed_rows || 0)}</span></div><div><span class="label">Referência:</span><span class="value">${escapeHtml(l.reference_date || "N/A")}</span></div></div>`;
        }

        if (s.statusItem) {
          const source = s.statusItem.using_uploaded_source
            ? (s.statusItem.versioned_upload ? "Upload versionado ativo" : "Upload ativo")
            : (s.statusItem.requires_upload ? "Upload obrigatório" : "Arquivo padrão");
          valHtml += `<div class="source-box"><div class="small text-secondary">Fonte: <strong>${escapeHtml(source)}</strong></div><div class="source-path">${escapeHtml(s.statusItem.active_source_path || "-")}</div></div>`;
        }

        const v = state.datasetValidation[ds.id];
        if (v) {
          const validationKind = v.kind === "ok" || v.kind === "err" || v.kind === "warn" ? v.kind : "warn";
          valHtml = `<div class="validation-panel ${validationKind}"><div class="validation-title">${escapeHtml(v.title)}</div><div>${escapeHtml(v.message)}</div></div>${valHtml}`;
        }

        st.innerHTML = statusUi;
        meta.innerHTML = metaHtml;
        valBox.innerHTML = valHtml;
        btns.innerHTML = buttonsHtml;
      });
    }

    function renderHistory() {
      if (!state.history.length) {
        E.historyTable.innerHTML = '<tr><td colspan="5" class="text-center py-4 text-secondary">Sem histórico de importação</td></tr>';
        return;
      }
      E.historyTable.innerHTML = state.history.map(h => {
        const importedAt = new Date(h.imported_at || h.created_at);
        const importedText = Number.isNaN(importedAt.getTime()) ? "-" : importedAt.toLocaleString();
        return `<tr><td class="ps-3"><strong>${escapeHtml(fromApiDataset(h.dataset || h.dataset_type || "-"))}</strong></td><td><span class="mono">${escapeHtml(String(h.batch_id || "").substring(0,8))}</span></td><td>${escapeHtml(h.total_rows || h.total_processed_rows || 0)}</td><td>${escapeHtml(h.reference_date || "--")}</td><td>${escapeHtml(importedText)}</td></tr>`;
      }).join("");
    }

    function jobStatusBadge(status) {
      const normalized = String(status || "").toLowerCase();
      const map = {
        queued: ["text-bg-secondary", "Em fila"],
        running: ["text-bg-warning", "Rodando"],
        completed: ["text-bg-success", "Concluido"],
        failed: ["text-bg-danger", "Falhou"],
        blocked: ["text-bg-danger", "Bloqueado"],
        stale: ["text-bg-dark", "Antigo"]
      };
      const item = map[normalized] || ["text-bg-secondary", status || "-"];
      return `<span class="badge ${escapeHtml(item[0])}">${escapeHtml(item[1])}</span>`;
    }

    function renderJobs() {
      if (!E.jobsTable) return;
      const jobs = Array.isArray(state.jobs) ? state.jobs : [];
      if (!jobs.length) {
        E.jobsTable.innerHTML = '<tr><td colspan="4" class="text-center py-4 text-secondary">Sem jobs recentes</td></tr>';
        return;
      }
      E.jobsTable.innerHTML = jobs.slice(0, 12).map(job => {
        const updatedAt = new Date(job.updated_at || job.finished_at || job.started_at || job.created_at);
        const updatedText = Number.isNaN(updatedAt.getTime()) ? "-" : updatedAt.toLocaleString();
        const action = String(job.action || "") === "upload" ? "Upload" : "Import";
        const error = String(job.error || "").trim();
        return `<tr title="${escapeHtml(error)}"><td class="ps-3"><strong>${escapeHtml(action)}</strong><div class="small text-secondary mono">${escapeHtml(String(job.job_id || "").substring(0, 14))}</div></td><td>${escapeHtml(fromApiDataset(job.dataset || job.dataset_name || "-"))}</td><td>${jobStatusBadge(job.status)}</td><td>${escapeHtml(updatedText)}</td></tr>`;
      }).join("");
    }

    async function validateCSV(dsId) {
      const input = document.getElementById(`file-${dsId}`);
      const apiDataset = toApiDataset(dsId);
      const di = document.getElementById(`date-${dsId}`);
      const refDate = isBoletoDataset(dsId) ? null : (di ? di.value : null);
      const timeouts = datasetTimeouts(dsId);

      try {
        state.datasetBusy[dsId] = true;
        renderGridPanels();
        if (input && input.files.length) {
          const formData = new FormData();
          formData.append("dataset", apiDataset);
          const totalFiles = input.files.length;
          for (const f of Array.from(input.files)) {
            formData.append("files", f);
          }
          const payload = await req(CONFIG.endpoints.import.upload, {
            method: "POST",
            headers: {},
            body: formData,
            timeoutMs: timeouts.validateMs
          });
          input.value = "";
          const hint = document.getElementById(`filehint-${dsId}`);
          const list = document.getElementById(`filelist-${dsId}`);
          const meta = DATASET_UPLOAD_META[dsId] || {};
          if (hint) hint.textContent = meta.emptyHint || "Selecione o arquivo do dataset.";
          if (list) list.innerHTML = "";
          state.datasetValidation[dsId] = buildValidationMessage(dsId, payload, `Validação concluída com ${totalFiles} arquivo(s).`);
          addLog(`Upload e validação do dataset ${dsId} concluído com ${totalFiles} arquivo(s).`, "ok");
        } else {
          const payload = await req(CONFIG.endpoints.import.validate, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ dataset: apiDataset, reference_date: refDate || null }),
            timeoutMs: timeouts.validateMs
          });
          state.datasetValidation[dsId] = buildValidationMessage(dsId, payload, "Validação concluída sem envio de arquivo.");
          addLog(`Validação executada para ${dsId}.`, "ok");
        }
        setTimeout(syncAll, 1200);
      } catch (err) {
        state.datasetValidation[dsId] = {
          kind: "err",
          title: "Falha na validação",
          message: err.message || "Não foi possível validar o dataset."
        };
        addLog(`Erro ao validar ${dsId}: ${err.message}`, "err");
      } finally {
        state.datasetBusy[dsId] = false;
        renderGridPanels();
      }
    }

    async function startImport(dsId) {
      const apiDataset = toApiDataset(dsId);
      const confirmed = await askConfirmation(`Efetivar importação do dataset ${dsId}?`);
      if (!confirmed) return;
      const di = document.getElementById(`date-${dsId}`);
      const refDate = isBoletoDataset(dsId) ? null : (di ? di.value : null);
      try {
        state.datasetBusy[dsId] = true;
        renderGridPanels();
        const runPayload = await req(CONFIG.endpoints.import.run, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ dataset: apiDataset, reference_date: refDate || null }),
          timeoutMs: 60000
        });

        const jobId = String(runPayload && runPayload.job_id ? runPayload.job_id : "");
        state.datasetValidation[dsId] = {
          kind: "warn",
          title: "Importação iniciada",
          message: "Processo disparado com sucesso. Aguardando conclusão..."
        };
        addLog("Importação disparada.", "ok");

        const jobResult = await waitForImportCompletion({ dsId, apiDataset, jobId });
        if (jobResult.status === "completed") {
          state.datasetValidation[dsId] = {
            kind: "ok",
            title: "Importação concluída",
            message: "Processo finalizado com sucesso."
          };
          addLog(`Importação concluída para ${dsId}.`, "ok");
        } else if (jobResult.status === "failed") {
          state.datasetValidation[dsId] = {
            kind: "err",
            title: "Importação falhou",
            message: jobResult.error || "A execução terminou com falha."
          };
          addLog(`Falha na importação de ${dsId}: ${jobResult.error || "erro não informado"}`, "err");
        } else {
          state.datasetValidation[dsId] = {
            kind: "warn",
            title: "Importação em processamento",
            message: "Ainda executando no servidor. Clique em Atualizar para acompanhar."
          };
          addLog(`Importação de ${dsId} ainda em processamento.`, "warn");
        }

        await syncAll();
      } catch (err) {
        state.datasetValidation[dsId] = {
          kind: "err",
          title: "Falha na importação",
          message: err.message || "Não foi possível iniciar a importação."
        };
        addLog(`Erro na importação: ${err.message}`, "err");
      } finally {
        state.datasetBusy[dsId] = false;
        renderGridPanels();
      }
    }

    async function waitForImportCompletion({ dsId, apiDataset, jobId }) {
      const timeoutAt = Date.now() + datasetTimeouts(dsId).importMs;
      while (Date.now() < timeoutAt) {
        const status = await req(CONFIG.endpoints.import.status, { timeoutMs: 30000 });
        state.status = status || {};
        state.jobs = Array.isArray(state.status.jobs) ? state.status.jobs : state.jobs;
        renderJobs();
        const running = Boolean(status && status.running);
        const currentDataset = String(status && status.current_dataset ? status.current_dataset : "");
        const lastJob = status && status.last_job ? status.last_job : null;
        const jobs = status && Array.isArray(status.jobs) ? status.jobs : [];
        const currentJob = jobId ? jobs.find(job => String(job.job_id || "") === jobId) : null;

        if (running && currentDataset === apiDataset) {
          state.datasetValidation[dsId] = {
            kind: "warn",
            title: "Importação em andamento",
            message: "Processando dados..."
          };
          renderGridPanels();
        }

        if (currentJob) {
          const currentStatus = String(currentJob.status || "").toLowerCase();
          if (currentStatus === "completed") {
            return { status: "completed" };
          }
          if (["failed", "blocked", "stale"].includes(currentStatus)) {
            return { status: "failed", error: String(currentJob.error || currentStatus) };
          }
        }

        if (lastJob) {
          const sameJob = jobId ? String(lastJob.job_id || "") === jobId : String(lastJob.dataset || "") === apiDataset;
          if (sameJob && String(lastJob.status || "") === "completed") {
            return { status: "completed" };
          }
          if (sameJob && ["failed", "blocked", "stale"].includes(String(lastJob.status || "").toLowerCase())) {
            return { status: "failed", error: String(lastJob.error || "") };
          }
        }

        await new Promise(resolve => setTimeout(resolve, 2000));
      }
      return { status: "timeout" };
    }

    function buildValidationMessage(dsId, payload, fallbackMessage) {
      const data = payload && typeof payload === "object" ? payload : {};
      const errors = Number(data.errors || data.error_count || data.invalid_rows || 0);
      const warnings = Number(data.warnings || data.warning_count || 0);
      const checked = Number(data.total_rows || data.checked_rows || data.validated_rows || 0);

      let kind = "ok";
      let title = "Validação aprovada";
      if (errors > 0) {
        kind = "err";
        title = "Validação com erros";
      } else if (warnings > 0) {
        kind = "warn";
        title = "Validação com alertas";
      }

      const parts = [];
      if (checked > 0) parts.push(`${checked} linhas verificadas`);
      if (warnings > 0) parts.push(`${warnings} alerta(s)`);
      if (errors > 0) parts.push(`${errors} erro(s)`);
      if (!parts.length) parts.push(fallbackMessage);

      return { kind, title, message: parts.join(" • ") };
    }
