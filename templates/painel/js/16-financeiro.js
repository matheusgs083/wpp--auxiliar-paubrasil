    function financeiroElements() {
      return {
        data: document.getElementById("financeiroData"),
        filial: document.getElementById("financeiroFilial"),
        filialMapas: document.getElementById("financeiroFilialMapas"),
        status: document.getElementById("financeiroStatus"),
        refresh: document.getElementById("financeiroRefreshBtn"),
        exportPdf: document.getElementById("financeiroExportPdfBtn"),
        novo: document.getElementById("financeiroNewMapBtn"),
        compra: document.getElementById("financeiroCompraBtn"),
        despesa: document.getElementById("financeiroDespesaBtn"),
        vale: document.getElementById("financeiroValeBtn"),
        fechamentoMapa: document.getElementById("financeiroFechamentoMapa"),
        fechamentoModo: document.getElementById("financeiroFechamentoModo"),
        fechamentoKm: document.getElementById("financeiroFechamentoKm"),
        fechamentoData: document.getElementById("financeiroFechamentoData"),
        fechamentoRefresh: document.getElementById("financeiroFechamentoRefreshBtn"),
        fechamentoWorkerStatus: document.getElementById("financeiroFechamentoWorkerStatus"),
        fechamentoStatus: document.getElementById("financeiroFechamentoStatus"),
        fechamentoLogBox: document.getElementById("financeiroFechamentoLogBox"),
        fechamentoLogJob: document.getElementById("financeiroFechamentoLogJob"),
        fechamentoLogToggle: document.getElementById("financeiroFechamentoLogToggleBtn"),
        fechamentoLogList: document.getElementById("financeiroFechamentoLogList"),
        fechamentoJobsBody: document.getElementById("financeiroFechamentoJobsBody"),
        fechamentoJobStatusFilter: document.getElementById("financeiroFechamentoJobStatusFilter"),
        fechamentoJobFromDate: document.getElementById("financeiroFechamentoJobFromDate"),
        fechamentoJobToDate: document.getElementById("financeiroFechamentoJobToDate"),
        fechamentoJobShowHidden: document.getElementById("financeiroFechamentoJobShowHiddenBtn"),
        fechamentoJobClearFilters: document.getElementById("financeiroFechamentoJobClearFiltersBtn"),
        fechamentoBtn: document.getElementById("financeiroFechamentoBtn"),
        fechamentoRefresh: document.getElementById("financeiroFechamentoRefreshBtn"),
        fechamentoSheet: document.getElementById("financeiroFechamentoSheet"),
        rel031120Hint: document.getElementById("financeiro031120Hint"),
        rel031120Status: document.getElementById("financeiro031120Status"),
        rel031120Target: document.getElementById("financeiro031120Target"),
        rel031120File: document.getElementById("financeiro031120File"),
        rel031120Download: document.getElementById("financeiro031120DownloadBtn"),
        rel031120Upload: document.getElementById("financeiro031120UploadBtn"),
        summary: document.getElementById("financeiroSummaryCards"),
        list: document.getElementById("financeiroMapList"),
        count: document.getElementById("financeiroMapCount"),
        editor: document.getElementById("financeiroEditor")
      };
    }

    function financeiroBlankMap(overrides = {}) {
      const els = financeiroElements();
      const data = els.data && els.data.value ? els.data.value : formatDateInputValue(new Date());
      const filial = financeiroSelectedFilial();
      const map = {
        id: "",
        data,
        filial,
        tipo_bloco: "mapa",
        mapa: "",
        mapa_ref: "",
        motorista: "",
        placa: "",
        ajudante1: "",
        ajudante2: "",
        boletos_rota: 0,
        boletos_recebido_qtd: 0,
        total_promax: 0,
        credito_conta: 0,
        dinheiro_promax: 0,
        dinheiro: FINANCEIRO_DENOMS.reduce((acc, denom) => { acc[denom] = 0; return acc; }, {}),
        moedas: 0,
        diarista: 0,
        diarista_recibo_recebido: true,
        diaristas: [],
        pernoite: 0,
        hospedagem: 0,
        janta: 0,
        almoco: 0,
        cafe: 0,
        transferencias: [],
        despesas: [],
        vales: [],
        observacao: "",
        dirty_fields: []
      };
      return Object.assign(map, overrides || {});
    }

    function financeiroNormalizeDirtyFields(fields) {
      const supported = new Set(FINANCEIRO_DIRTY_SUPPORTED_FIELDS);
      return Array.from(new Set((Array.isArray(fields) ? fields : [])
        .map(item => String(item || "").trim())
        .filter(item => supported.has(item))));
    }

    function financeiroMarkDraftDirty(field) {
      const cleanField = String(field || "").trim();
      if (!cleanField || !FINANCEIRO_DIRTY_SUPPORTED_FIELDS.includes(cleanField)) return;
      const draft = state.financeiro.draft || financeiroBlankMap();
      const dirty = new Set(financeiroNormalizeDirtyFields(draft.dirty_fields));
      dirty.add(cleanField);
      draft.dirty_fields = Array.from(dirty);
      state.financeiro.draft = draft;
    }

    function financeiroNormalizeHospedagemDraft(map, { markDirty = false } = {}) {
      if (!map || typeof map !== "object") return map;
      const pernoite = financeiroNumber(map.pernoite);
      const hospedagem = financeiroNumber(map.hospedagem);
      if (pernoite <= 0) return map;
      map.hospedagem = hospedagem + pernoite;
      map.pernoite = 0;
      if (markDirty) {
        const dirty = new Set(financeiroNormalizeDirtyFields(map.dirty_fields));
        dirty.add("hospedagem");
        dirty.add("pernoite");
        map.dirty_fields = Array.from(dirty);
      }
      return map;
    }

    function financeiroNumber(value) {
      if (typeof value === "number" && Number.isFinite(value)) return value;
      let cleaned = String(value ?? "").replace("R$", "").replace(/\s/g, "");
      if (cleaned.includes(",") && cleaned.includes(".")) {
        cleaned = cleaned.replace(/\./g, "").replace(",", ".");
      } else if (cleaned.includes(",")) {
        cleaned = cleaned.replace(",", ".");
      }
      const parsed = Number(cleaned);
      return Number.isFinite(parsed) ? parsed : 0;
    }

    function financeiroTextKey(value) {
      return String(value || "").trim().toLowerCase();
    }

    function financeiroDifferenceClass(value) {
      return financeiroNumber(value) < -0.009 ? "text-danger" : "text-success";
    }

    function financeiroTotals(map) {
      const dinheiroTotal = FINANCEIRO_DENOMS.reduce((total, denom) => {
        return total + financeiroNumber(denom) * Math.max(0, Math.trunc(financeiroNumber(map.dinheiro && map.dinheiro[denom])));
      }, 0);
      const sumRows = rows => (Array.isArray(rows) ? rows : []).reduce((total, row) => total + financeiroNumber(row.valor), 0);
      const valesCalculados = Array.isArray(map.vales) ? map.vales : [];
      const valesExistentes = Array.isArray(map.vales) ? map.vales : [];
      const hasValeMesmoNomeValor = (nome, valor) => valesExistentes.some(row => (
        financeiroTextKey(row.nome) === financeiroTextKey(nome)
        && Math.abs(financeiroNumber(row.valor) - financeiroNumber(valor)) < 0.01
      ));
      const diaristaAvulso = financeiroNumber(map.diarista);
      const diaristaAvulsoComRecibo = map.diarista_recibo_recebido !== false;
      const diaristasComRecibo = (Array.isArray(map.diaristas) ? map.diaristas : []).filter(row => row.recibo_recebido !== false);
      const diaristasSemRecibo = (Array.isArray(map.diaristas) ? map.diaristas : []).filter(row => row.recibo_recebido === false);
      const valeAvulsoDiarista = (!diaristaAvulsoComRecibo && !hasValeMesmoNomeValor(map.motorista || "Diarista", diaristaAvulso)) ? diaristaAvulso : 0;
      const valesDiaristas = valeAvulsoDiarista + diaristasSemRecibo.reduce((total, row) => {
        return total + (hasValeMesmoNomeValor(row.nome || map.motorista || "Diarista", row.valor) ? 0 : financeiroNumber(row.valor));
      }, 0);
      const valesTotal = sumRows(valesCalculados) + valesDiaristas;
      const diaristasTotal = (diaristaAvulsoComRecibo ? diaristaAvulso : 0) + sumRows(diaristasComRecibo);
      const alimentacao = financeiroNumber(map.pernoite) + financeiroNumber(map.hospedagem) + financeiroNumber(map.janta) + financeiroNumber(map.almoco) + financeiroNumber(map.cafe);
      const totalApurado = dinheiroTotal + financeiroNumber(map.moedas) + sumRows(map.transferencias) + sumRows(map.despesas) + valesTotal + diaristasTotal + alimentacao;
      const dinheiroPromax = financeiroNumber(map.dinheiro_promax);
      const diferenca = totalApurado - dinheiroPromax;
      const boletosDiferencaQtd = financeiroNumber(map.boletos_rota) - financeiroNumber(map.boletos_recebido_qtd);
      return { dinheiroTotal, dinheiroPromax, diaristasTotal, valesTotal, alimentacao, totalApurado, diferenca, boletosDiferencaQtd };
    }

    function financeiroMapaEntraNoCaixa(map) {
      const tipo = String(map && map.tipo_bloco || "mapa");
      return !["despesa", "vale", "vale_conferencia", "despesa_conferencia"].includes(tipo);
    }

    function financeiroMapaContaDiferenca(map) {
      return String(map && map.tipo_bloco || "mapa") === "mapa";
    }

    function financeiroDiferencaMapas(maps, fallback) {
      const onlyMaps = (Array.isArray(maps) ? maps : []).filter(financeiroMapaContaDiferenca);
      if (!onlyMaps.length) return financeiroNumber(fallback || 0);
      return onlyMaps.reduce((total, map) => total + financeiroNumber(map && map.diferenca), 0);
    }

    function financeiroRowsFromMaps(maps, key) {
      const rows = [];
      (Array.isArray(maps) ? maps : []).forEach(map => {
        (Array.isArray(map[key]) ? map[key] : []).forEach(row => {
          rows.push({ map, row });
        });
      });
      return rows;
    }

    function financeiroRenderFechamentoSheet(payload) {
      const els = financeiroElements();
      const el = els.fechamentoSheet;
      if (!el) return;
      const maps = Array.isArray(payload && payload.maps) ? payload.maps : [];
      const summary = payload && payload.summary ? payload.summary : {};
      const caixaMaps = maps.filter(financeiroMapaEntraNoCaixa);
      const denomTotals = FINANCEIRO_DENOMS.reduce((acc, denom) => {
        acc[denom] = caixaMaps.reduce((total, map) => total + Math.max(0, Math.trunc(financeiroNumber(map.dinheiro && map.dinheiro[denom]))), 0);
        return acc;
      }, {});
      const numerarioMalote = financeiroNumber(summary.numerario_total || (financeiroNumber(summary.dinheiro_total) + financeiroNumber(summary.moedas)));
      const depositos = financeiroNumber(summary.depositos_total || (financeiroNumber(summary.credito_conta) + financeiroNumber(summary.transferencias_total)));
      const baseDinheiroDeposito = numerarioMalote + depositos;
      const diferenca = financeiroDiferencaMapas(maps, summary.diferenca);
      const dinheiroPct = financeiroNumber(summary.dinheiro_percent || (baseDinheiroDeposito ? (numerarioMalote / baseDinheiroDeposito) * 100 : 0));
      const depositoPct = financeiroNumber(summary.deposito_percent || (baseDinheiroDeposito ? (depositos / baseDinheiroDeposito) * 100 : 0));
      const transfers = financeiroRowsFromMaps(caixaMaps, "transferencias");
      const vales = financeiroRowsFromMaps(maps, "vales_consolidados");
      const despesas = financeiroRowsFromMaps(maps, "despesas");
      const despesasBody = despesas.length ? despesas.slice(0, 12).map(({ map, row }) => `
        <tr>
          <td>${escapeHtml(map.mapa || "-")}</td>
          <td>${escapeHtml(row.nome || row.observacao || "-")}</td>
          <td class="finance-sheet-value">${escapeHtml(formatMoneyText(row.valor || 0))}</td>
        </tr>
      `).join("") : '<tr><td colspan="3" class="text-center finance-sheet-muted">Sem despesas lançadas.</td></tr>';
      const transferBody = transfers.length ? transfers.slice(0, 16).map(({ row }) => `
        <tr>
          <td>${escapeHtml(row.data || "-")}</td>
          <td>${escapeHtml(row.banco || "-")}</td>
          <td>${escapeHtml(row.nb || "-")}</td>
          <td>${escapeHtml(row.nf || "-")}</td>
          <td class="finance-sheet-value">${escapeHtml(formatMoneyText(row.valor || 0))}</td>
        </tr>
      `).join("") : '<tr><td colspan="5" class="text-center finance-sheet-muted">Sem comprovantes lançados.</td></tr>';
      const valeBody = vales.length ? vales.slice(0, 16).map(({ map, row }) => `
        <tr>
          <td>${escapeHtml(row.nome || map.motorista || "-")}</td>
          <td class="finance-sheet-value">${escapeHtml(formatMoneyText(row.valor || 0))}</td>
          <td>${escapeHtml(row.observacao || "-")}</td>
          <td class="text-center finance-sheet-ass ${row.assinado ? "ok" : "nok"}">${row.assinado ? "OK" : "NOK"}</td>
        </tr>
      `).join("") : '<tr><td colspan="4" class="text-center finance-sheet-muted">Sem vales lançados.</td></tr>';
      const rotasDia = Array.isArray(payload && payload.rotas_dia) ? payload.rotas_dia : [];
      const rotasDiaMeta = payload && payload.rotas_dia_meta && typeof payload.rotas_dia_meta === "object" ? payload.rotas_dia_meta : {};
      const rotasDiaFechados = rotasDia.filter(row => row && row.fechamento_ok).length;
      const rotasDiaPendentes = rotasDia.filter(row => row && row.fechamento_ok === false).length;
      const rotasDiaMetaStatus = String(rotasDiaMeta.status || "").toLowerCase();
      const rotasDiaMetaText = rotasDiaMeta.message
        ? `${rotasDiaMeta.message}${rotasDiaMeta.imported_at ? ` Importado em ${formatDateTime(rotasDiaMeta.imported_at)}.` : ""}`
        : "";
      const rotasDiaNotice = rotasDiaMetaText
        ? `<div class="finance-route-notice ${rotasDiaMetaStatus === "ok" ? "ok" : ""}">${escapeHtml(rotasDiaMetaText)}</div>`
        : "";
      const rotasDiaBody = rotasDia.length ? rotasDia.map(row => `
        <tr>
          <td>${escapeHtml(row.mapa || "-")}</td>
          <td>${escapeHtml(row.placa || "-")}</td>
          <td class="finance-sheet-value">${escapeHtml(row.km_percorrido || "-")}</td>
          <td class="finance-sheet-value">${escapeHtml(row.km_prev || "-")}</td>
          <td>${escapeHtml(row.saida || "-")}</td>
          <td>${escapeHtml(row.entrada || "-")}</td>
          <td>${escapeHtml(row.tempo_rota || "-")}</td>
          <td>${escapeHtml(row.ti_fisico || "-")}</td>
          <td>${escapeHtml(row.ti_financeiro || "-")}</td>
          <td>${escapeHtml(row.ti_total || "-")}</td>
          <td class="finance-route-status ${row.operacional_ok === false ? "pending" : "ok"}">${escapeHtml(row.status_operacional || "-")}</td>
          <td class="finance-route-status ${row.fechamento_ok === false ? "pending" : "ok"}">${escapeHtml(row.fechamento_status || "-")}</td>
        </tr>
      `).join("") : '<tr><td colspan="12" class="text-center finance-sheet-muted">Sem relatório 031120 importado para esta data.</td></tr>';
      el.innerHTML = `
        <div class="finance-sheet-title">
          <h3>Caixa Noturno ${escapeHtml((payload.filiais || []).find(item => String(item.code) === String(payload.filial))?.name || payload.filial || "")}</h3>
          <span class="finance-sheet-muted">${escapeHtml(formatDate(payload.data || ""))} | ${caixaMaps.length} mapa(s)</span>
        </div>
        <div class="finance-sheet-body">
          <div class="finance-sheet-side">
            <div class="finance-sheet-box">
              <div class="finance-sheet-box-title"><span>Resumo</span><strong>${escapeHtml(summary.status || "-")}</strong></div>
              <table class="finance-sheet-table">
                <tbody>
                  <tr><td>Dinheiro Promax</td><td class="finance-sheet-value">${escapeHtml(formatMoneyText(summary.dinheiro_promax || summary.total_promax || 0))}</td></tr>
                  <tr><td>Numerario do Malote</td><td class="finance-sheet-value">${escapeHtml(formatMoneyText(numerarioMalote))}</td></tr>
                  <tr><td>Boletos rota</td><td class="finance-sheet-value">${escapeHtml(String(financeiroNumber(summary.boletos_recebido_qtd || 0)))} / ${escapeHtml(String(financeiroNumber(summary.boletos_rota || 0)))}</td></tr>
                  <tr><td>Despesas</td><td class="finance-sheet-value">${escapeHtml(formatMoneyText(summary.despesas_total || 0))}</td></tr>
                  <tr><td>Diaristas</td><td class="finance-sheet-value">${escapeHtml(formatMoneyText(summary.diaristas_total || 0))}</td></tr>
                  <tr><td>Alimentacao</td><td class="finance-sheet-value">${escapeHtml(formatMoneyText(summary.alimentacao_total || 0))}</td></tr>
                  <tr><td class="finance-sheet-muted ps-3">Hospedagem</td><td class="finance-sheet-value">${escapeHtml(formatMoneyText(summary.alimentacao_hospedagem_total || 0))}</td></tr>
                  <tr><td class="finance-sheet-muted ps-3">Janta</td><td class="finance-sheet-value">${escapeHtml(formatMoneyText(summary.alimentacao_janta_total || 0))}</td></tr>
                  <tr><td class="finance-sheet-muted ps-3">Almoco</td><td class="finance-sheet-value">${escapeHtml(formatMoneyText(summary.alimentacao_almoco_total || 0))}</td></tr>
                  <tr><td class="finance-sheet-muted ps-3">Cafe</td><td class="finance-sheet-value">${escapeHtml(formatMoneyText(summary.alimentacao_cafe_total || 0))}</td></tr>
                  <tr><td>Depositos</td><td class="finance-sheet-value">${escapeHtml(formatMoneyText(depositos))}</td></tr>
                  <tr><td>Vales</td><td class="finance-sheet-value">${escapeHtml(formatMoneyText(summary.vales_total || 0))}</td></tr>
                  <tr><td>Moedas</td><td class="finance-sheet-value">${escapeHtml(formatMoneyText(summary.moedas || 0))}</td></tr>
                  <tr><td><strong>Diferenca</strong></td><td class="finance-sheet-value ${financeiroDifferenceClass(diferenca)}">${escapeHtml(formatMoneyText(diferenca))}</td></tr>
                </tbody>
              </table>
            </div>
            <div class="finance-sheet-box">
              <div class="finance-sheet-box-title"><span>Numerario do Malote</span><strong>${escapeHtml(formatMoneyText(numerarioMalote))}</strong></div>
              <table class="finance-sheet-table">
                <tbody>
                  ${FINANCEIRO_DENOMS.slice().reverse().map(denom => `
                    <tr><td>R$ ${escapeHtml(denom)}</td><td class="finance-sheet-value">${escapeHtml(String(denomTotals[denom] || 0))}</td><td class="finance-sheet-value">${escapeHtml(formatMoneyText(financeiroNumber(denom) * (denomTotals[denom] || 0)))}</td></tr>
                  `).join("")}
                </tbody>
              </table>
            </div>
            <div class="finance-sheet-mini-grid">
              <div class="finance-sheet-mini"><span>% Dinheiro</span><strong>${escapeHtml(dinheiroPct.toFixed(2).replace(".", ","))}%</strong></div>
              <div class="finance-sheet-mini"><span>% Deposito</span><strong>${escapeHtml(depositoPct.toFixed(2).replace(".", ","))}%</strong></div>
            </div>
          </div>
          <div class="finance-sheet-side">
            <div class="finance-sheet-quick">
              <span class="finance-sheet-quick-title">Lançamentos do caixa</span>
              <div class="finance-sheet-quick-grid">
                <div class="finance-sheet-quick-item"><span>Compras</span><strong>${escapeHtml(String(maps.filter(map => (map.tipo_bloco || "") === "compra").length))}</strong></div>
                <div class="finance-sheet-quick-item"><span>Despesas</span><strong>${escapeHtml(String(despesas.length))}</strong></div>
                <div class="finance-sheet-quick-item"><span>Vales</span><strong>${escapeHtml(String(vales.length))}</strong></div>
                <div class="finance-sheet-quick-item"><span>Transferências</span><strong>${escapeHtml(String(transfers.length))}</strong></div>
              </div>
            </div>
            <div class="finance-sheet-mini-grid">
              <div class="finance-sheet-mini"><span>Crédito em conta</span><strong>${escapeHtml(formatMoneyText(summary.credito_conta || 0))}</strong></div>
              <div class="finance-sheet-mini"><span>Transferências</span><strong>${escapeHtml(formatMoneyText(summary.transferencias_total || 0))}</strong></div>
            </div>
            <div class="finance-sheet-box">
              <div class="finance-sheet-box-title"><span>Comprovantes</span><strong>${escapeHtml(formatMoneyText(summary.transferencias_total || 0))}</strong></div>
              <div class="finance-sheet-scroll">
                <table class="finance-sheet-table">
                  <thead><tr><th>Data</th><th>Banco</th><th>NB</th><th>NF</th><th>Valor</th></tr></thead>
                  <tbody>${transferBody}</tbody>
                </table>
              </div>
            </div>
          </div>
          <div class="finance-sheet-side">
            <div class="finance-sheet-box">
              <div class="finance-sheet-box-title"><span>Vales</span><strong>${escapeHtml(formatMoneyText(summary.vales_total || 0))}</strong></div>
              <div class="finance-sheet-scroll">
                <table class="finance-sheet-table">
                  <thead><tr><th>Nome</th><th>Valor</th><th>Obs.</th><th>Ass.</th></tr></thead>
                  <tbody>${valeBody}</tbody>
                </table>
              </div>
            </div>
            <div class="finance-sheet-box">
              <div class="finance-sheet-box-title"><span>Despesas</span><strong>${escapeHtml(formatMoneyText(summary.despesas_total || 0))}</strong></div>
              <div class="finance-sheet-scroll">
                <table class="finance-sheet-table">
                  <thead><tr><th>Mapa</th><th>Descrição</th><th>Valor</th></tr></thead>
                  <tbody>${despesasBody}</tbody>
                </table>
              </div>
            </div>
          </div>
          <div class="finance-sheet-wide">
            <div class="finance-sheet-box">
              <div class="finance-sheet-box-title"><span>Relatório de rotas do dia</span><strong>${escapeHtml(String(rotasDiaFechados))} fech. | ${escapeHtml(String(rotasDiaPendentes))} pend.</strong></div>
              ${rotasDiaNotice}
              <div class="finance-sheet-scroll">
                <table class="finance-sheet-table">
                  <thead>
                    <tr>
                      <th>Mapa</th>
                      <th>Placa</th>
                      <th>Km percorrido</th>
                      <th>Km Prev.</th>
                      <th>Saída</th>
                      <th>Entrada</th>
                      <th>Tempo rota</th>
                      <th>TI - Fisico</th>
                      <th>TI - Financeiro</th>
                      <th>TI total</th>
                      <th>Operacional</th>
                      <th>Fechamento</th>
                    </tr>
                  </thead>
                  <tbody>${rotasDiaBody}</tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      `;
    }

    function financeiroCollectDraft() {
      const root = document.getElementById("financeiroEditor");
      if (!root) return state.financeiro.draft || financeiroBlankMap();
      const map = state.financeiro.draft || financeiroBlankMap();
      financeiroNormalizeHospedagemDraft(map);
      const get = selector => root.querySelector(selector);
      const dataEl = document.getElementById("financeiroData");
      const filialEl = document.getElementById("financeiroFilialMapas") || document.getElementById("financeiroFilial");
      map.data = dataEl && dataEl.value ? dataEl.value : map.data;
      map.filial = filialEl && filialEl.value ? filialEl.value : map.filial;
      ["tipo_bloco", "mapa", "mapa_ref", "motorista", "placa", "ajudante1", "ajudante2", "boletos_rota", "boletos_recebido_qtd", "total_promax", "credito_conta", "dinheiro_promax", "moedas", "diarista", "diarista_recibo_recebido", "pernoite", "hospedagem", "janta", "almoco", "cafe", "observacao"].forEach(key => {
        const el = get(`[data-financeiro-field="${key}"]`);
        if (el) map[key] = el.type === "checkbox" ? el.checked : el.value;
      });
      FINANCEIRO_DENOMS.forEach(denom => {
        const el = get(`[data-financeiro-denom="${denom}"]`);
        map.dinheiro[denom] = el ? el.value : 0;
      });
      map.transferencias = financeiroCollectRows(root, "transferencias");
      map.despesas = financeiroCollectRows(root, "despesas");
      map.vales = financeiroCollectRows(root, "vales");
      map.diaristas = financeiroCollectRows(root, "diaristas");
      map.detail_fields = ["transferencias", "despesas", "vales", "diaristas"];
      map.total_promax = map.dinheiro_promax;
      map.dirty_fields = financeiroNormalizeDirtyFields(map.dirty_fields);
      return map;
    }

    function financeiroCollectRows(root, type) {
      return Array.from(root.querySelectorAll(`[data-financeiro-row="${type}"]`)).map(row => {
        const item = {};
        row.querySelectorAll("[data-financeiro-cell]").forEach(input => {
          item[input.dataset.financeiroCell] = input.type === "checkbox" ? input.checked : input.value;
        });
        return item;
      }).filter(item => {
        if (type === "diaristas" || type === "vales") {
          return ["nome", "valor", "observacao"].some(key => String(item[key] || "").trim());
        }
        return Object.values(item).some(value => typeof value === "boolean" ? value : String(value || "").trim());
      });
    }

    function financeiroRefreshEditorComputedValues(map) {
      const root = document.getElementById("financeiroEditor");
      if (!root || !map) return;
      const totals = financeiroTotals(map);
      const dinheiroEl = root.querySelector('[data-financeiro-summary="dinheiro_contado"]');
      if (dinheiroEl) dinheiroEl.textContent = formatMoneyText(totals.dinheiroTotal);
      const totalEl = root.querySelector('[data-financeiro-summary="total_apurado"]');
      if (totalEl) totalEl.textContent = formatMoneyText(totals.totalApurado);
      const boletosEl = root.querySelector('[data-financeiro-summary="boletos"]');
      if (boletosEl) {
        boletosEl.textContent = `${financeiroNumber(map.boletos_recebido_qtd)} / ${financeiroNumber(map.boletos_rota)}`;
        boletosEl.classList.toggle("text-success", Math.abs(totals.boletosDiferencaQtd) < 0.01);
        boletosEl.classList.toggle("text-danger", Math.abs(totals.boletosDiferencaQtd) >= 0.01);
      }
      const diferencaEl = root.querySelector('[data-financeiro-summary="diferenca"]');
      if (diferencaEl) {
        diferencaEl.textContent = formatMoneyText(totals.diferenca);
        diferencaEl.classList.toggle("text-success", financeiroDifferenceClass(totals.diferenca) === "text-success");
        diferencaEl.classList.toggle("text-danger", financeiroDifferenceClass(totals.diferenca) === "text-danger");
      }
    }

    function financeiroTrackEditorInput(event) {
      state.financeiro.draft = financeiroCollectDraft();
      const target = event.currentTarget;
      if (target && target.dataset) {
        if (target.dataset.financeiroField) {
          financeiroMarkDraftDirty(target.dataset.financeiroField);
        } else if (target.dataset.financeiroDenom) {
          financeiroMarkDraftDirty("dinheiro");
        }
      }
      financeiroRefreshEditorComputedValues(state.financeiro.draft);
    }

    function financeiroHasPendingEditorChanges() {
      const draft = state.financeiro.draft;
      return Boolean(draft && financeiroNormalizeDirtyFields(draft.dirty_fields).length);
    }

    function financeiroRender({ preserveEditor = false } = {}) {
      const els = financeiroElements();
      if (!els.editor) return;
      const payload = state.financeiro.payload || { maps: [], summary: {}, filiais: [] };
      if (els.count) els.count.textContent = `${payload.summary && payload.summary.mapas || 0}/${payload.summary && payload.summary.compras || 0}`;
      if (els.status) {
        const extras = [];
        if (payload.summary && payload.summary.compras) extras.push(`${payload.summary.compras} compra`);
        if (payload.summary && payload.summary.despesas_blocos) extras.push(`${payload.summary.despesas_blocos} desp.`);
        if (payload.summary && payload.summary.vales_blocos) extras.push(`${payload.summary.vales_blocos} vale`);
        els.status.textContent = state.financeiro.loading ? "Carregando caixa" : `${payload.summary && payload.summary.mapas || 0} mapa(s)${extras.length ? " + " + extras.join(" + ") : ""}`;
        els.status.className = `pill ${payload.summary && payload.summary.status === "OK" ? "ok" : ""}`;
      }
      financeiroRenderFiliais(payload.filiais || []);
      renderFinanceiroFechamentoWorker(state.financeiro.worker);
      financeiroUpdate031120Panel();
      financeiroRenderFechamentoSheet(payload);
      financeiroRenderSummary(payload.summary || {});
      financeiroRenderMapList(payload.maps || []);
      if (!state.financeiro.draft) {
        const selected = (payload.maps || []).find(item => String(item.id) === String(state.financeiro.selectedId));
        state.financeiro.draft = selected ? JSON.parse(JSON.stringify(selected)) : financeiroBlankMap();
      }
      if (!preserveEditor || !financeiroHasPendingEditorChanges()) {
        financeiroRenderEditor(state.financeiro.draft);
      }
    }

    function financeiroRenderFiliais(filiais) {
      const selects = [document.getElementById("financeiroFilial"), document.getElementById("financeiroFilialMapas")].filter(Boolean);
      if (!selects.length) return;
      const current = selects.find(el => el.value)?.value || "";
      const items = filiais || [];
      const options = ['<option value="">Escolha a revenda</option>'].concat(items.map(item => {
        return `<option value="${escapeHtml(item.code)}">${escapeHtml(item.code)} - ${escapeHtml(item.name || item.code)}</option>`;
      }));
      const nextValue = current && items.some(item => String(item.code) === String(current)) ? current : (!current && items.length === 1 ? items[0].code : "");
      selects.forEach(el => {
        el.innerHTML = options.join("");
        el.value = nextValue;
      });
      financeiroUpdate031120Panel();
      if (!current && nextValue) {
        setTimeout(() => syncFinanceiro({ silent: true }), 0);
      }
    }

    function financeiroSyncFilialSelects(source) {
      const els = financeiroElements();
      const value = source && typeof source.value !== "undefined" ? source.value : (els.filial && els.filial.value) || (els.filialMapas && els.filialMapas.value) || "";
      [els.filial, els.filialMapas].forEach(element => {
        if (element && element.value !== value) element.value = value;
      });
      return value;
    }

    function financeiroSelectedFilial() {
      const els = financeiroElements();
      return String((els.filialMapas && els.filialMapas.value) || (els.filial && els.filial.value) || "").trim();
    }

    function financeiroFilialLabel(filial) {
      const payloadFiliais = state.financeiro.payload && Array.isArray(state.financeiro.payload.filiais) ? state.financeiro.payload.filiais : [];
      const found = payloadFiliais.find(item => String(item.code) === String(filial));
      return found ? `${found.code} - ${found.name || found.code}` : (filial ? `Revenda ${filial}` : "");
    }

    function financeiro031120Dataset(filial) {
      const clean = String(filial || "").trim();
      return clean ? `relatorio_031120_op_${clean}` : "";
    }

    function financeiro031120Unit(filial) {
      return PROMAX_UNIT_BY_FILIAL[String(filial || "").trim()] || "";
    }

    function financeiroUpdate031120Panel() {
      const els = financeiroElements();
      const filial = financeiroSelectedFilial();
      const unit = financeiro031120Unit(filial);
      const dataset = financeiro031120Dataset(filial);
      if (els.rel031120Target) {
        els.rel031120Target.textContent = filial && unit
          ? `${financeiroFilialLabel(filial)} | Unidade ${unit} | ${dataset}`
          : "Escolha uma revenda no filtro acima";
      }
      if (els.rel031120Hint) {
        els.rel031120Hint.textContent = filial && unit
          ? "O download e o upload serao aplicados somente nesta revenda selecionada."
          : "Escolha uma revenda para solicitar o download ou importar o CSV da operação correta.";
      }
      if (els.rel031120Status && !els.rel031120Status.dataset.busy) {
        els.rel031120Status.textContent = filial && unit ? "Pronto para a revenda" : "Aguardando revenda";
        els.rel031120Status.className = `pill ${filial && unit ? "ok" : ""}`;
      }
      if (els.rel031120Download) els.rel031120Download.disabled = !filial || !unit;
      if (els.rel031120Upload) els.rel031120Upload.disabled = !filial || !unit;
    }

    async function financeiroSolicitar031120Download() {
      const els = financeiroElements();
      const filial = financeiroSyncFilialSelects(els.filial);
      const unit = financeiro031120Unit(filial);
      if (!filial || !unit) {
        addLog("Escolha uma revenda antes de solicitar a 031120.", "warn");
        return;
      }
      const confirmed = await askConfirmation(`Solicitar download da 031120 para ${financeiroFilialLabel(filial)}?`);
      if (!confirmed) return;
      if (els.rel031120Status) {
        els.rel031120Status.dataset.busy = "1";
        els.rel031120Status.textContent = "Enfileirando download";
        els.rel031120Status.className = "pill";
      }
      if (els.rel031120Download) els.rel031120Download.disabled = true;
      try {
        const payload = {
          filial,
          data: els.data && els.data.value ? els.data.value : formatDateInputValue(new Date())
        };
        const response = await req(CONFIG.endpoints.financeiro.relatorio031120Download, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          timeoutMs: 20000
        });
        const jobId = response && response.job && response.job.id ? String(response.job.id).slice(0, 8) : "";
        if (els.rel031120Status) {
          els.rel031120Status.textContent = jobId ? `Job ${jobId} enfileirado` : "Download enfileirado";
          els.rel031120Status.className = "pill ok";
        }
        addLog(`Download 031120 solicitado para ${financeiroFilialLabel(filial)}.`, "ok");
      } catch (err) {
        if (els.rel031120Status) {
          els.rel031120Status.textContent = "Falha no download";
          els.rel031120Status.className = "pill danger";
        }
        addLog(`Falha ao solicitar 031120: ${err.message}`, "err");
      } finally {
        if (els.rel031120Status) delete els.rel031120Status.dataset.busy;
        financeiroUpdate031120Panel();
      }
    }

    async function financeiroImportar031120Upload() {
      const els = financeiroElements();
      const filial = financeiroSyncFilialSelects(els.filial);
      const file = els.rel031120File && els.rel031120File.files && els.rel031120File.files[0] ? els.rel031120File.files[0] : null;
      if (!filial || !financeiro031120Unit(filial)) {
        addLog("Escolha uma revenda antes de importar a 031120.", "warn");
        return;
      }
      if (!file) {
        addLog("Selecione o CSV 031120 antes de importar.", "warn");
        if (els.rel031120File) els.rel031120File.focus();
        return;
      }
      const confirmed = await askConfirmation(`Importar o CSV 031120 em ${financeiroFilialLabel(filial)}?`);
      if (!confirmed) return;
      const formData = new FormData();
      formData.append("filial", filial);
      formData.append("file", file);
      if (els.rel031120Status) {
        els.rel031120Status.dataset.busy = "1";
        els.rel031120Status.textContent = "Importando CSV";
        els.rel031120Status.className = "pill";
      }
      if (els.rel031120Upload) els.rel031120Upload.disabled = true;
      try {
        const response = await req(CONFIG.endpoints.financeiro.relatorio031120Upload, {
          method: "POST",
          headers: {},
          body: formData,
          timeoutMs: 300000
        });
        const rows = response && response.result ? response.result.rows : "";
        if (els.rel031120File) els.rel031120File.value = "";
        if (els.rel031120Status) {
          els.rel031120Status.textContent = rows ? `${rows} linha(s) importadas` : "CSV importado";
          els.rel031120Status.className = "pill ok";
        }
        addLog(`031120 importada para ${financeiroFilialLabel(filial)}.`, "ok");
        await syncFinanceiro({ silent: true });
      } catch (err) {
        if (els.rel031120Status) {
          els.rel031120Status.textContent = "Falha no upload";
          els.rel031120Status.className = "pill danger";
        }
        addLog(`Falha ao importar 031120: ${err.message}`, "err");
      } finally {
        if (els.rel031120Status) delete els.rel031120Status.dataset.busy;
        financeiroUpdate031120Panel();
      }
    }

    function financeiroRenderSummary(summary) {
      const el = document.getElementById("financeiroSummaryCards");
      if (!el) return;
      const maps = Array.isArray(state.financeiro.payload && state.financeiro.payload.maps) ? state.financeiro.payload.maps : [];
      const diferenca = financeiroDiferencaMapas(maps, summary && summary.diferenca);
      const items = [
        ["Mapas", summary.mapas || 0],
        ["Compra", summary.compras || 0],
        ["Desp./Vales", `${summary.despesas_blocos || 0} / ${summary.vales_blocos || 0}`],
        ["Total Promax", formatMoneyText(summary.total_promax || 0)],
        ["Total Apurado", formatMoneyText(summary.total_apurado || 0)],
        ["Crédito em conta", formatMoneyText(summary.credito_conta || 0)],
        ["Boletos rota", `${financeiroNumber(summary.boletos_recebido_qtd || 0)} / ${financeiroNumber(summary.boletos_rota || 0)}`],
        ["Transferências", formatMoneyText(summary.transferencias_total || 0)],
        ["Diaristas", formatMoneyText(summary.diaristas_total || 0)],
        ["Diferença", formatMoneyText(diferenca)]
      ];
      el.innerHTML = items.map(([label, value]) => {
        const valueClass = label === "Diferença" ? ` class="${financeiroDifferenceClass(diferenca)}"` : "";
        return `<div class="finance-summary-item"><span>${escapeHtml(label)}</span><strong${valueClass}>${escapeHtml(String(value))}</strong></div>`;
      }).join("");
    }

    function financeiroRenderMapList(maps) {
      const el = document.getElementById("financeiroMapList");
      if (!el) return;
      if (!maps.length) {
        el.innerHTML = '<div class="empty-state py-3">Nenhum mapa criado para este caixa.</div>';
        return;
      }
      el.innerHTML = maps.map(map => {
        const active = String(map.id) === String(state.financeiro.selectedId) ? " is-active" : "";
        const diferencaClass = financeiroDifferenceClass(map.diferenca || 0);
        return `<button type="button" class="finance-map-btn${active}" data-financeiro-select="${escapeHtml(map.id)}">
          <strong>${escapeHtml(financeiroTipoLabel(map.tipo_bloco))} ${escapeHtml(map.mapa || "-")}</strong>
          <span class="meta">${escapeHtml(map.motorista || "Sem motorista")}${map.placa ? ` | ${escapeHtml(map.placa)}` : ""} | ${escapeHtml(map.filial_nome || map.filial || "-")}</span>
          <span class="status-line ${diferencaClass}">${escapeHtml(map.status || "-")} | Dif. ${escapeHtml(formatMoneyText(map.diferenca || 0))}</span>
        </button>`;
      }).join("");
      el.querySelectorAll("[data-financeiro-select]").forEach(button => {
        button.addEventListener("click", () => {
          const id = button.dataset.financeiroSelect;
          const selected = (state.financeiro.payload.maps || []).find(item => String(item.id) === String(id));
          state.financeiro.selectedId = id;
          state.financeiro.draft = selected
            ? financeiroNormalizeHospedagemDraft(Object.assign(JSON.parse(JSON.stringify(selected)), { dirty_fields: [] }), { markDirty: true })
            : financeiroBlankMap();
          const fechamentoMapa = document.getElementById("financeiroFechamentoMapa");
          if (fechamentoMapa && selected && selected.tipo_bloco === "mapa") fechamentoMapa.value = selected.mapa || selected.mapa_key || "";
          financeiroRender();
        });
      });
    }

    function financeiroTipoLabel(tipo) {
      if (tipo === "compra") return "Compra";
      if (tipo === "despesa") return "Despesa";
      if (tipo === "vale") return "Vale";
      if (tipo === "vale_conferencia") return "Vales";
      if (tipo === "despesa_conferencia") return "Despesas";
      return "Mapa";
    }

    function financeiroIsValeChapa(row) {
      return String(row && row.observacao || "").trim().toLowerCase() === "vale de chapa";
    }

    function financeiroRenderEditor(map) {
      const el = document.getElementById("financeiroEditor");
      if (!el) return;
      const totals = financeiroTotals(map || {});
      const tipo = map && map.tipo_bloco ? map.tipo_bloco : "mapa";
      if (tipo === "vale_conferencia") {
        financeiroRenderValeReview(map || {});
        return;
      }
      if (tipo === "despesa_conferencia") {
        financeiroRenderDespesaReview(map || {});
        return;
      }
      const isCompra = tipo === "compra";
      const isDespesa = tipo === "despesa";
      const isVale = tipo === "vale";
      const isLancamento = isDespesa || isVale;
      const prestacao = map && map.prestacao_contas ? map.prestacao_contas : {};
      const prestacaoButton = !isLancamento && !isCompra && map && map.id
        ? `<button type="button" class="btn btn-outline-primary btn-sm" id="financeiroPrestacaoBtn"><i class="bi bi-table me-1"></i>${prestacao.available ? "Validar 030322" : "Sem 030322"}</button>`
        : "";
      const visibleBlocks = [];
      if (!isLancamento) {
        visibleBlocks.push(financeiroRowsBlock("transferencias", "Transferências parciais", map.transferencias || []));
        visibleBlocks.push(financeiroRowsBlock("diaristas", "Diaristas", map.diaristas || []));
        visibleBlocks.push(financeiroRowsBlock("despesas", "Despesas do mapa", map.despesas || []));
        visibleBlocks.push(financeiroRowsBlock("vales", "Vales do mapa", map.vales || []));
      }
      if (isDespesa) visibleBlocks.push(financeiroRowsBlock("despesas", "Despesas", map.despesas || []));
      if (isVale) visibleBlocks.push(financeiroRowsBlock("vales", "Vales", map.vales || []));
      el.classList.add("finance-editor-card");
      el.innerHTML = `
        <div class="finance-editor-head">
          <div>
            <h3 class="h6 fw-bold mb-1">${map && map.id ? "Editar" : "Novo"} ${escapeHtml(financeiroTipoLabel(tipo))}</h3>
            <div class="form-text">${isLancamento ? "Lançamento separado do caixa, vinculado ao mapa e motorista informados." : (isCompra ? "Bloco especial que pertence ao caixa do dia e entra no consolidado." : "Preencha o mapa e detalhe transferencias parciais.")}</div>
          </div>
          <div class="d-flex flex-wrap gap-2">
            ${prestacaoButton}
            ${map && map.id ? '<button type="button" class="btn btn-outline-danger btn-sm" id="financeiroDeleteMapBtn"><i class="bi bi-trash me-1"></i>Excluir</button>' : ""}
            <button type="button" class="btn btn-primary btn-sm" id="financeiroSaveMapBtn"><i class="bi bi-check2-circle me-1"></i>Salvar mapa</button>
          </div>
        </div>
        <div class="finance-editor-body">
          <input type="hidden" data-financeiro-field="tipo_bloco" value="${escapeHtml(tipo)}">
              ${isLancamento ? `<input type="hidden" data-financeiro-field="mapa" value="${escapeHtml(map.mapa_key || map.mapa || `${tipo.toUpperCase()}-${Date.now()}`)}">` : ""}
          <section>
            <h4 class="h6 fw-bold mb-2">Identificação</h4>
            <div class="finance-editor-grid">
              ${isLancamento ? financeiroInput("mapa_ref", "Mapa vinculado", map.mapa_ref || map.mapa) : financeiroInput("mapa", isCompra ? "Identificação do bloco" : "Número do mapa", map.mapa)}
              ${financeiroInput("motorista", isCompra ? "Responsável" : "Motorista", map.motorista)}
              ${isLancamento || isCompra ? "" : financeiroInput("placa", "Placa", map.placa)}
              ${isLancamento || isCompra ? "" : financeiroInput("ajudante1", "Ajudante 1", map.ajudante1)}
              ${isLancamento || isCompra ? "" : financeiroInput("ajudante2", "Ajudante 2", map.ajudante2)}
              ${isLancamento ? "" : financeiroInput("boletos_rota", "Boletos rota (qtd.)", map.boletos_rota, "number", "1")}
              ${isLancamento ? "" : financeiroInput("boletos_recebido_qtd", "Boletos que voltaram (qtd.)", map.boletos_recebido_qtd, "number", "1")}
              ${isLancamento ? "" : financeiroInput("credito_conta", "Crédito em conta", map.credito_conta, "number")}
              ${isLancamento ? "" : financeiroInput("dinheiro_promax", "Dinheiro Promax", map.dinheiro_promax, "number")}
            </div>
          </section>
          ${isLancamento ? "" : `
            <section>
              <h4 class="h6 fw-bold mb-2">Dinheiro e alimentacao</h4>
              <div class="finance-money-grid mb-2">
                ${FINANCEIRO_DENOMS.map(denom => `<label class="form-label small fw-semibold">R$ ${denom}<input class="form-control form-control-sm mt-1" type="number" min="0" step="1" data-financeiro-denom="${denom}" value="${escapeHtml(String(map.dinheiro && map.dinheiro[denom] || 0))}"></label>`).join("")}
              </div>
              <div class="finance-editor-grid">
                ${financeiroInput("moedas", "Moedas", map.moedas, "number")}
                ${financeiroInput("hospedagem", "Hospedagem", map.hospedagem, "number")}
                ${financeiroInput("janta", "Janta", map.janta, "number")}
                ${financeiroInput("almoco", "Almoco", map.almoco, "number")}
                ${financeiroInput("cafe", "Cafe", map.cafe, "number")}
                <div class="finance-summary-item"><span>Dinheiro contado</span><strong data-financeiro-summary="dinheiro_contado">${formatMoneyText(totals.dinheiroTotal)}</strong></div>
              </div>
            </section>
          `}
          <section class="finance-detail-grid">${visibleBlocks.join("")}</section>
          <label class="form-label small fw-semibold w-100">Observação<textarea class="form-control mt-1" rows="2" data-financeiro-field="observacao">${escapeHtml(map.observacao || "")}</textarea></label>
          <div class="finance-summary-strip">
            <div class="finance-summary-item"><span>Total apurado</span><strong data-financeiro-summary="total_apurado">${formatMoneyText(totals.totalApurado)}</strong></div>
            ${isLancamento ? "" : `<div class="finance-summary-item"><span>Conferência boletos</span><strong data-financeiro-summary="boletos" class="${Math.abs(totals.boletosDiferencaQtd) < 0.01 ? "text-success" : "text-danger"}">${financeiroNumber(map.boletos_recebido_qtd)} / ${financeiroNumber(map.boletos_rota)}</strong></div>`}
            ${isLancamento ? "" : `<div class="finance-summary-item"><span>Diferenca</span><strong data-financeiro-summary="diferenca" class="${financeiroDifferenceClass(totals.diferenca)}">${formatMoneyText(totals.diferenca)}</strong></div>`}
          </div>
          <div class="finance-editor-footer">
            <button type="button" class="btn btn-primary btn-sm" id="financeiroSaveMapBottomBtn"><i class="bi bi-check2-circle me-1"></i>Salvar mapa</button>
          </div>
        </div>
      `;
      el.querySelectorAll("input, textarea, select").forEach(input => {
        input.addEventListener("input", financeiroTrackEditorInput);
        input.addEventListener("change", financeiroTrackEditorInput);
      });
      el.querySelectorAll("[data-financeiro-add]").forEach(button => button.addEventListener("click", () => financeiroAddRow(button.dataset.financeiroAdd)));
      el.querySelectorAll("[data-financeiro-remove]").forEach(button => button.addEventListener("click", () => financeiroRemoveRow(button.dataset.financeiroRemove, Number(button.dataset.index))));
      const gerarValesDiarista = document.getElementById("financeiroGerarValesDiaristaBtn");
      if (gerarValesDiarista) gerarValesDiarista.addEventListener("click", financeiroGerarValesDiaristas);
      const prestacaoBtn = document.getElementById("financeiroPrestacaoBtn");
      if (prestacaoBtn) prestacaoBtn.addEventListener("click", () => financeiroOpenPrestacaoModal(map.id));
      const save = document.getElementById("financeiroSaveMapBtn");
      const saveBottom = document.getElementById("financeiroSaveMapBottomBtn");
      const del = document.getElementById("financeiroDeleteMapBtn");
      if (save) save.addEventListener("click", financeiroSaveMap);
      if (saveBottom) saveBottom.addEventListener("click", financeiroSaveMap);
      if (del) del.addEventListener("click", financeiroDeleteMap);
    }

    async function financeiroOpenPrestacaoModal(mapaId) {
      const modalEl = document.getElementById("financeiroPrestacaoModal");
      if (!modalEl || !mapaId) return;
      financeiroRenderPrestacaoModalLoading();
      if (window.bootstrap) bootstrap.Modal.getOrCreateInstance(modalEl).show();
      try {
        const payload = await req(`${CONFIG.endpoints.financeiro.prestacaoContas}/${encodeURIComponent(mapaId)}/prestacao-contas`, {
          timeoutMs: 45000
        });
        financeiroRenderPrestacaoModal(payload || {});
      } catch (err) {
        financeiroRenderPrestacaoModalError(err.message);
      }
    }

    function financeiroRenderPrestacaoModalLoading() {
      const title = document.getElementById("financeiroPrestacaoModalTitle");
      const subtitle = document.getElementById("financeiroPrestacaoModalSubtitle");
      const summary = document.getElementById("financeiroPrestacaoSummary");
      const notas = document.getElementById("financeiroPrestacaoNotasBody");
      const vasilhames = document.getElementById("financeiroPrestacaoVasilhamesBody");
      const resumo = document.getElementById("financeiroPrestacaoResumoRaw");
      state.financeiro.prestacaoNotas = [];
      [
        "financeiroPrestacaoFiltroCliente",
        "financeiroPrestacaoFiltroCondicao",
        "financeiroPrestacaoFiltroValorMin",
        "financeiroPrestacaoFiltroValorMax"
      ].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = "";
      });
      const count = document.getElementById("financeiroPrestacaoNotasCount");
      if (count) count.textContent = "0 nota(s)";
      if (title) title.textContent = "Prestação de contas do mapa";
      if (subtitle) subtitle.textContent = "Carregando dados da 030322...";
      if (summary) summary.innerHTML = '<div class="finance-summary-item"><span>Status</span><strong>Carregando</strong></div>';
      if (notas) notas.innerHTML = '<tr><td colspan="10" class="text-center py-3 text-secondary">Carregando notas...</td></tr>';
      if (vasilhames) vasilhames.innerHTML = '<tr><td colspan="7" class="text-center py-3 text-secondary">Carregando vasilhames...</td></tr>';
      if (resumo) resumo.textContent = "Carregando...";
    }

    function financeiroRenderPrestacaoModalError(message) {
      const subtitle = document.getElementById("financeiroPrestacaoModalSubtitle");
      const summary = document.getElementById("financeiroPrestacaoSummary");
      const notas = document.getElementById("financeiroPrestacaoNotasBody");
      const vasilhames = document.getElementById("financeiroPrestacaoVasilhamesBody");
      const resumo = document.getElementById("financeiroPrestacaoResumoRaw");
      if (subtitle) subtitle.textContent = "Não foi possível carregar a prestação.";
      if (summary) summary.innerHTML = `<div class="finance-summary-item"><span>Erro</span><strong class="text-danger">${escapeHtml(message || "Falha ao carregar")}</strong></div>`;
      if (notas) notas.innerHTML = '<tr><td colspan="10" class="text-center py-3 text-secondary">Sem dados.</td></tr>';
      if (vasilhames) vasilhames.innerHTML = '<tr><td colspan="7" class="text-center py-3 text-secondary">Sem dados.</td></tr>';
      if (resumo) resumo.textContent = message || "Falha ao carregar.";
    }

    function financeiroRenderPrestacaoModal(payload) {
      const mapa = payload.mapa || {};
      const prestacao = payload.prestacao_contas || {};
      const summary = payload.summary || prestacao.resumo || {};
      const title = document.getElementById("financeiroPrestacaoModalTitle");
      const subtitle = document.getElementById("financeiroPrestacaoModalSubtitle");
      if (title) title.textContent = `Prestação 030322 - Mapa ${mapa.mapa || "-"}`;
      if (subtitle) {
        subtitle.textContent = `${mapa.filial_nome || mapa.filial || "-"} | ${mapa.placa || "sem placa"} | ${mapa.motorista || "sem motorista"}`;
      }
      const summaryEl = document.getElementById("financeiroPrestacaoSummary");
      if (summaryEl) {
        const items = [
          ["Notas", summary.notas_count ?? summary.notas ?? 0],
          ["Devolucoes", summary.devolucoes_count ?? summary.devolucoes ?? 0],
          ["Vasilhames", summary.vasilhames_count ?? summary.vasilhames ?? 0],
          ["Valor notas", formatMoneyText(summary.valor_notas || 0)],
          ["Devolucao", formatMoneyText(summary.valor_devolucao || 0)],
          ["Liquido", formatMoneyText(summary.valor_liquido || 0)],
          ["Atualizado", summary.updated_at ? formatDateTime(summary.updated_at) : "-"]
        ];
        summaryEl.innerHTML = items.map(([label, value]) => `<div class="finance-summary-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong></div>`).join("");
      }
      state.financeiro.prestacaoNotas = Array.isArray(prestacao.notas) ? prestacao.notas : [];
      financeiroBindPrestacaoNotaFilters();
      financeiroRenderPrestacaoNotas();
      financeiroRenderPrestacaoVasilhames(prestacao.vasilhames || []);
      const resumo = document.getElementById("financeiroPrestacaoResumoRaw");
      const linhasResumo = prestacao.resumo_financeiro && Array.isArray(prestacao.resumo_financeiro.linhas)
        ? prestacao.resumo_financeiro.linhas
        : [];
      if (resumo) resumo.textContent = linhasResumo.length ? linhasResumo.join("\n") : "Sem resumo financeiro capturado.";
    }

    function financeiroBindPrestacaoNotaFilters() {
      [
        "financeiroPrestacaoFiltroCliente",
        "financeiroPrestacaoFiltroCondicao",
        "financeiroPrestacaoFiltroValorMin",
        "financeiroPrestacaoFiltroValorMax"
      ].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.oninput = () => financeiroRenderPrestacaoNotas();
      });
      const clear = document.getElementById("financeiroPrestacaoFiltroClear");
      if (clear) {
        clear.onclick = () => {
          [
            "financeiroPrestacaoFiltroCliente",
            "financeiroPrestacaoFiltroCondicao",
            "financeiroPrestacaoFiltroValorMin",
            "financeiroPrestacaoFiltroValorMax"
          ].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.value = "";
          });
          financeiroRenderPrestacaoNotas();
        };
      }
    }

    function financeiroPrestacaoFiltroTexto(value) {
      return String(value || "").trim().toLowerCase();
    }

    function financeiroFiltrarPrestacaoNotas(rows) {
      const clienteFiltro = financeiroPrestacaoFiltroTexto(document.getElementById("financeiroPrestacaoFiltroCliente")?.value);
      const condicaoFiltro = financeiroPrestacaoFiltroTexto(document.getElementById("financeiroPrestacaoFiltroCondicao")?.value);
      const valorMinRaw = document.getElementById("financeiroPrestacaoFiltroValorMin")?.value;
      const valorMaxRaw = document.getElementById("financeiroPrestacaoFiltroValorMax")?.value;
      const valorMin = valorMinRaw !== "" && valorMinRaw != null ? financeiroNumber(valorMinRaw) : null;
      const valorMax = valorMaxRaw !== "" && valorMaxRaw != null ? financeiroNumber(valorMaxRaw) : null;
      return rows.filter(row => {
        const clienteTexto = financeiroPrestacaoFiltroTexto([
          row.nb,
          row.filial_nb,
          row.cliente,
          row.cliente_original,
          row.cliente_dclientes,
          row.nome_fantasia,
          row.razao_social
        ].join(" "));
        const condicaoTexto = financeiroPrestacaoFiltroTexto(row.condicao_pagamento);
        const valor = Math.abs(financeiroNumber(row.valor_liquido || row.valor_nota || 0));
        if (clienteFiltro && !clienteTexto.includes(clienteFiltro)) return false;
        if (condicaoFiltro && !condicaoTexto.includes(condicaoFiltro)) return false;
        if (valorMin !== null && valor < valorMin) return false;
        if (valorMax !== null && valor > valorMax) return false;
        return true;
      });
    }

    function financeiroRenderPrestacaoNotas(rows = null) {
      const body = document.getElementById("financeiroPrestacaoNotasBody");
      if (!body) return;
      const allRows = Array.isArray(rows) ? rows : (Array.isArray(state.financeiro.prestacaoNotas) ? state.financeiro.prestacaoNotas : []);
      const filteredRows = financeiroFiltrarPrestacaoNotas(allRows);
      const count = document.getElementById("financeiroPrestacaoNotasCount");
      if (count) count.textContent = `${filteredRows.length}/${allRows.length} nota(s)`;
      if (!filteredRows.length) {
        const message = allRows.length
          ? "Nenhuma nota encontrada para os filtros aplicados."
          : "Nenhuma nota capturada pela 030322.";
        body.innerHTML = `<tr><td colspan="10" class="text-center py-3 text-secondary">${escapeHtml(message)}</td></tr>`;
        return;
      }
      body.innerHTML = filteredRows.map(row => {
        const devolucao = financeiroNumber(row.valor_devolucao || 0);
        const statusClass = String(row.situacao || "").toUpperCase() === "DEV" || Math.abs(devolucao) > 0.001 ? "text-danger fw-bold" : "";
        const nomePrincipal = row.nome_fantasia || row.cliente_dclientes || row.cliente || "-";
        const nomeSecundario = row.cliente_original || row.razao_social || "";
        const mostrarSecundario = nomeSecundario && financeiroPrestacaoFiltroTexto(nomeSecundario) !== financeiroPrestacaoFiltroTexto(nomePrincipal);
        return `<tr>
          <td class="mono fw-bold">${escapeHtml(row.nb || "-")}</td>
          <td>
            <div class="fw-semibold">${escapeHtml(nomePrincipal)}</div>
            ${mostrarSecundario ? `<div class="small text-secondary">${escapeHtml(nomeSecundario)}</div>` : ""}
          </td>
          <td class="mono">${escapeHtml(row.nota || "-")}</td>
          <td>${escapeHtml(row.serie || "-")}</td>
          <td class="${statusClass}">${escapeHtml(row.situacao || "-")}</td>
          <td>${escapeHtml(row.operacao || "-")}</td>
          <td>${escapeHtml(row.condicao_pagamento || "-")}</td>
          <td class="text-end">${escapeHtml(formatMoneyText(row.valor_nota || 0))}</td>
          <td class="text-end ${statusClass}">${escapeHtml(formatMoneyText(row.valor_devolucao || 0))}</td>
          <td class="text-end fw-bold">${escapeHtml(formatMoneyText(row.valor_liquido || 0))}</td>
        </tr>`;
      }).join("");
    }

    function financeiroRenderPrestacaoVasilhames(rows) {
      const body = document.getElementById("financeiroPrestacaoVasilhamesBody");
      if (!body) return;
      if (!rows.length) {
        body.innerHTML = '<tr><td colspan="7" class="text-center py-3 text-secondary">Nenhum vasilhame capturado pela 030322.</td></tr>';
        return;
      }
      body.innerHTML = rows.map(row => {
        const diff = financeiroNumber(row.diferenca_valor || 0);
        const diffClass = Math.abs(diff) > 0.001 ? "text-danger fw-bold" : "";
        return `<tr>
          <td class="mono fw-bold">${escapeHtml(row.codigo || "-")}</td>
          <td>${escapeHtml(row.unidade || "-")}</td>
          <td>${escapeHtml(row.denominacao || "-")}</td>
          <td class="text-end">${escapeHtml(formatMoneyText(row.preco || 0))}</td>
          <td class="text-end">${escapeHtml(`${row.saida_qtd || "-"} | ${formatMoneyText(row.saida_valor || 0)}`)}</td>
          <td class="text-end">${escapeHtml(`${row.retorno_qtd || "-"} | ${formatMoneyText(row.retorno_valor || 0)}`)}</td>
          <td class="text-end ${diffClass}">${escapeHtml(`${row.diferenca_qtd || "-"} | ${formatMoneyText(row.diferenca_valor || 0)}`)}</td>
        </tr>`;
      }).join("");
    }

    function financeiroValeRows() {
      const maps = state.financeiro.payload && Array.isArray(state.financeiro.payload.maps) ? state.financeiro.payload.maps : [];
      const rows = [];
      maps.forEach(map => {
        (map.vales || []).forEach((vale, index) => {
          rows.push({ map, vale, index, persisted: true });
        });
        (map.vales_consolidados || [])
          .filter(vale => vale && vale.origem === "diarista_sem_recibo")
          .forEach(vale => {
            rows.push({ map, vale, index: -1, persisted: false });
          });
      });
      return rows;
    }

    function financeiroDespesaRows() {
      const maps = state.financeiro.payload && Array.isArray(state.financeiro.payload.maps) ? state.financeiro.payload.maps : [];
      const rows = [];
      maps.forEach(map => {
        (map.despesas || []).forEach((despesa, index) => {
          rows.push({ map, despesa, index });
        });
      });
      return rows;
    }

    function financeiroRenderValeReview(map) {
      const el = document.getElementById("financeiroEditor");
      if (!el) return;
      const rows = financeiroValeRows();
      state.financeiro.valeReviewChangedMapIds = new Set();
      const total = rows.reduce((sum, row) => sum + financeiroNumber(row.vale.valor), 0);
      const body = rows.length ? rows.map(({ map: itemMap, vale }, rowIndex) => `
        <tr>
          <td><strong>${escapeHtml(itemMap.mapa || "-")}</strong></td>
          <td>${escapeHtml(itemMap.motorista || "-")}</td>
          <td>${escapeHtml(vale.nome || vale.observacao || "-")}</td>
          <td class="text-end fw-bold">${escapeHtml(formatMoneyText(vale.valor || 0))}</td>
          <td class="text-center">
            <label class="finance-review-check">
              <input class="form-check-input" type="checkbox" data-financeiro-vale-row-index="${rowIndex}" data-financeiro-vale-field="assinado" ${vale.assinado ? "checked" : ""}>
            </label>
          </td>
        </tr>
      `).join("") : '<tr><td colspan="5" class="text-center text-secondary py-4">Nenhum vale lançado nos mapas deste caixa.</td></tr>';
      el.innerHTML = `
        <div class="d-flex flex-wrap gap-2 justify-content-between align-items-start mb-3">
          <div>
            <h3 class="h6 fw-bold mb-1">Conferência de vales</h3>
            <div class="form-text">Vales lançados nos mapas do dia. Ajuste apenas se o vale esta assinado.</div>
          </div>
          <button type="button" class="btn btn-primary btn-sm" id="financeiroSaveValeReviewBtn" ${rows.length ? "" : "disabled"}><i class="bi bi-check2-circle me-1"></i>Salvar conferência</button>
        </div>
        <div class="table-scroll border rounded">
          <table class="finance-review-table">
            <thead>
              <tr>
                <th>Mapa</th>
                <th>Motorista</th>
                <th>Vale</th>
                <th class="text-end">Valor</th>
                <th class="text-center">Assinado</th>
              </tr>
            </thead>
            <tbody>${body}</tbody>
          </table>
        </div>
        <div class="finance-summary-strip mt-3">
          <div class="finance-summary-item"><span>Vales</span><strong>${rows.length}</strong></div>
          <div class="finance-summary-item"><span>Total em vales</span><strong>${formatMoneyText(total)}</strong></div>
          <div class="finance-summary-item"><span>Assinados</span><strong>${rows.filter(row => row.vale.assinado).length}</strong></div>
        </div>
      `;
      el.querySelectorAll("[data-financeiro-vale-field]").forEach(input => {
        input.addEventListener("change", () => {
          const reviewRow = rows[Number(input.dataset.financeiroValeRowIndex)];
          if (!reviewRow || !reviewRow.map || !reviewRow.vale) return;
          const targetMap = reviewRow.map;
          targetMap.vales = Array.isArray(targetMap.vales) ? targetMap.vales : [];
          let vale = reviewRow.persisted ? targetMap.vales[reviewRow.index] : null;
          if (!vale) {
            vale = {
              nome: reviewRow.vale.nome || targetMap.motorista || "Diarista",
              valor: financeiroNumber(reviewRow.vale.valor),
              observacao: reviewRow.vale.observacao || "vale de chapa",
              assinado: false
            };
            targetMap.vales.push(vale);
            reviewRow.persisted = true;
            reviewRow.index = targetMap.vales.length - 1;
          }
          vale.assinado = input.checked;
          reviewRow.vale.assinado = input.checked;
          state.financeiro.valeReviewChangedMapIds.add(String(targetMap.id));
          state.financeiro.draft = Object.assign({}, map, { tipo_bloco: "vale_conferencia" });
        });
      });
      const save = document.getElementById("financeiroSaveValeReviewBtn");
      if (save) save.addEventListener("click", financeiroSaveValeReview);
    }

    function financeiroRenderDespesaReview(map) {
      const el = document.getElementById("financeiroEditor");
      if (!el) return;
      const rows = financeiroDespesaRows();
      const total = rows.reduce((sum, row) => sum + financeiroNumber(row.despesa.valor), 0);
      const body = rows.length ? rows.map(({ map: itemMap, despesa, index }) => `
        <tr>
          <td><strong>${escapeHtml(itemMap.mapa || "-")}</strong></td>
          <td>${escapeHtml(itemMap.motorista || "-")}</td>
          <td><input class="form-control form-control-sm" data-financeiro-despesa-map="${escapeHtml(itemMap.id)}" data-financeiro-despesa-index="${index}" data-financeiro-despesa-field="nome" value="${escapeHtml(despesa.nome || "")}"></td>
          <td><input class="form-control form-control-sm" data-financeiro-despesa-map="${escapeHtml(itemMap.id)}" data-financeiro-despesa-index="${index}" data-financeiro-despesa-field="observacao" value="${escapeHtml(despesa.observacao || "")}"></td>
          <td class="text-end"><input class="form-control form-control-sm text-end" type="number" step="0.01" data-financeiro-despesa-map="${escapeHtml(itemMap.id)}" data-financeiro-despesa-index="${index}" data-financeiro-despesa-field="valor" value="${escapeHtml(String(despesa.valor || ""))}"></td>
        </tr>
      `).join("") : '<tr><td colspan="5" class="text-center text-secondary py-4">Nenhuma despesa lançada nos mapas deste caixa.</td></tr>';
      el.innerHTML = `
        <div class="d-flex flex-wrap gap-2 justify-content-between align-items-start mb-3">
          <div>
            <h3 class="h6 fw-bold mb-1">Conferência de despesas</h3>
            <div class="form-text">Despesas lançadas nos mapas do dia. Ajuste descrição, observação ou valor quando necessário.</div>
          </div>
          <button type="button" class="btn btn-primary btn-sm" id="financeiroSaveDespesaReviewBtn" ${rows.length ? "" : "disabled"}><i class="bi bi-check2-circle me-1"></i>Salvar conferência</button>
        </div>
        <div class="table-scroll border rounded">
          <table class="finance-review-table">
            <thead>
              <tr>
                <th>Mapa</th>
                <th>Motorista</th>
                <th>Despesa</th>
                <th>Observação</th>
                <th class="text-end">Valor</th>
              </tr>
            </thead>
            <tbody>${body}</tbody>
          </table>
        </div>
        <div class="finance-summary-strip mt-3">
          <div class="finance-summary-item"><span>Despesas</span><strong>${rows.length}</strong></div>
          <div class="finance-summary-item"><span>Total em despesas</span><strong>${formatMoneyText(total)}</strong></div>
        </div>
      `;
      const save = document.getElementById("financeiroSaveDespesaReviewBtn");
      if (save) save.addEventListener("click", financeiroSaveDespesaReview);
    }

    async function financeiroSaveDespesaReview() {
      if (!financeiroRequireFilial()) return;
      const maps = state.financeiro.payload && Array.isArray(state.financeiro.payload.maps) ? state.financeiro.payload.maps : [];
      const changedMapIds = new Set();
      document.querySelectorAll("[data-financeiro-despesa-field]").forEach(input => {
        const targetMap = maps.find(item => String(item.id) === String(input.dataset.financeiroDespesaMap));
        if (!targetMap || !Array.isArray(targetMap.despesas)) return;
        const despesa = targetMap.despesas[Number(input.dataset.financeiroDespesaIndex)];
        if (!despesa) return;
        const field = input.dataset.financeiroDespesaField;
        despesa[field] = field === "valor" ? financeiroNumber(input.value) : input.value;
        changedMapIds.add(String(targetMap.id));
      });
      const changedMaps = maps.filter(map => changedMapIds.has(String(map.id)));
      if (!changedMaps.length) {
        addLog("Nenhuma despesa para conferir neste caixa.", "warn");
        return;
      }
      try {
        for (const map of changedMaps) {
          const payload = Object.assign({}, map, {
            mapa: map.mapa_key || map.mapa,
            detail_fields: ["despesas"]
          });
          await req(CONFIG.endpoints.financeiro.mapas, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
            timeoutMs: 20000
          });
        }
        state.financeiro.selectedId = null;
        state.financeiro.draft = { tipo_bloco: "despesa_conferencia" };
        addLog("Conferência de despesas salva.", "ok");
        await syncFinanceiro({ silent: true });
        state.financeiro.draft = { tipo_bloco: "despesa_conferencia" };
        financeiroRender();
      } catch (err) {
        addLog(`Falha ao salvar conferência de despesas: ${err.message}`, "err");
      }
    }

    async function financeiroSaveValeReview() {
      if (!financeiroRequireFilial()) return;
      const maps = state.financeiro.payload && Array.isArray(state.financeiro.payload.maps) ? state.financeiro.payload.maps : [];
      const changedIds = state.financeiro.valeReviewChangedMapIds instanceof Set
        ? state.financeiro.valeReviewChangedMapIds
        : new Set();
      const changedMaps = maps.filter(map => changedIds.has(String(map.id)));
      if (!changedMaps.length) {
        addLog("Nenhuma alteração de vale para salvar.", "warn");
        return;
      }
      try {
        for (const map of changedMaps) {
          const payload = Object.assign({}, map, {
            mapa: map.mapa_key || map.mapa,
            detail_fields: ["vales"]
          });
          await req(CONFIG.endpoints.financeiro.mapas, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
            timeoutMs: 20000
          });
        }
        state.financeiro.selectedId = null;
        state.financeiro.draft = { tipo_bloco: "vale_conferencia" };
        addLog("Conferência de vales salva.", "ok");
        await syncFinanceiro({ silent: true });
        state.financeiro.draft = { tipo_bloco: "vale_conferencia" };
        financeiroRender();
      } catch (err) {
        addLog(`Falha ao salvar conferência de vales: ${err.message}`, "err");
      }
    }

    function financeiroInput(key, label, value, type = "text", numberStep = "0.01") {
      const step = type === "number" ? ` step="${numberStep}"` : "";
      return `<label class="form-label small fw-semibold">${escapeHtml(label)}<input class="form-control form-control-sm mt-1" type="${type}"${step} data-financeiro-field="${key}" value="${escapeHtml(String(value ?? ""))}"></label>`;
    }

    function financeiroCheckbox(key, label, checked) {
      return `<label class="finance-summary-item d-flex align-items-center gap-2 mb-0">
        <input class="form-check-input m-0" type="checkbox" data-financeiro-field="${escapeHtml(key)}" ${checked ? "checked" : ""}>
        <span class="text-uppercase">${escapeHtml(label)}</span>
      </label>`;
    }

    function financeiroRowsBlock(type, title, rows) {
      const body = (rows && rows.length ? rows : [{}]).map((row, index) => financeiroRow(type, row, index)).join("");
      return `<section class="finance-entry-block">
        <div class="finance-entry-head">
          <h4 class="mb-0">${escapeHtml(title)}</h4>
          <div class="d-flex gap-2">
            ${type === "diaristas" ? '<button type="button" class="btn btn-outline-success btn-sm" id="financeiroGerarValesDiaristaBtn"><i class="bi bi-journal-plus me-1"></i>Gerar vales</button>' : ""}
            <button type="button" class="btn btn-outline-primary btn-sm" data-financeiro-add="${type}"><i class="bi bi-plus"></i></button>
          </div>
        </div>
        <div class="finance-entry-list">${body}</div>
      </section>`;
    }

    function financeiroRow(type, row, index) {
      if (type === "transferencias") {
        return `<div class="finance-transfer-row" data-financeiro-row="${type}">
          <input class="form-control form-control-sm" data-financeiro-cell="data" placeholder="Data" value="${escapeHtml(row.data || "")}">
          <input class="form-control form-control-sm" data-financeiro-cell="banco" placeholder="Banco" value="${escapeHtml(row.banco || "")}">
          <input class="form-control form-control-sm" data-financeiro-cell="nb" placeholder="NB" value="${escapeHtml(row.nb || "")}">
          <input class="form-control form-control-sm" data-financeiro-cell="nf" placeholder="NF" value="${escapeHtml(row.nf || "")}">
          <input class="form-control form-control-sm" type="number" step="0.01" data-financeiro-cell="valor" placeholder="Valor" value="${escapeHtml(String(row.valor || ""))}">
          <button type="button" class="btn btn-outline-danger btn-sm finance-row-remove" data-financeiro-remove="${type}" data-index="${index}"><i class="bi bi-x"></i></button>
        </div>`;
      }
      if (type === "diaristas") {
        return `<div class="finance-diarista-row" data-financeiro-row="${type}">
          <input class="form-control form-control-sm" data-financeiro-cell="nome" placeholder="Nome" value="${escapeHtml(row.nome || "")}">
          <input class="form-control form-control-sm" type="number" min="0.01" step="0.01" data-financeiro-cell="valor" placeholder="Valor" value="${escapeHtml(String(row.valor || ""))}">
          <label class="form-check small fw-semibold d-flex align-items-center gap-2 mb-0">
            <input class="form-check-input m-0" type="checkbox" data-financeiro-cell="recibo_recebido" ${row.recibo_recebido === false ? "" : "checked"}>
            Recibo recebido
          </label>
          <button type="button" class="btn btn-outline-danger btn-sm finance-row-remove" data-financeiro-remove="${type}" data-index="${index}"><i class="bi bi-x"></i></button>
        </div>`;
      }
      const assinadoField = type === "vales"
        ? `<input type="hidden" data-financeiro-cell="assinado" value="${row.assinado ? "true" : "false"}">`
        : "";
      const positiveValue = type === "vales" ? ' min="0.01"' : "";
      return `<div class="finance-detail-row" data-financeiro-row="${type}">
        <input class="form-control form-control-sm" data-financeiro-cell="nome" placeholder="${type === "despesas" ? "Ex: almoco, janta, chapa" : "Nome"}" value="${escapeHtml(row.nome || "")}">
        <input class="form-control form-control-sm" type="number"${positiveValue} step="0.01" data-financeiro-cell="valor" placeholder="Valor" value="${escapeHtml(String(row.valor || ""))}">
        <button type="button" class="btn btn-outline-danger btn-sm finance-row-remove" data-financeiro-remove="${type}" data-index="${index}"><i class="bi bi-x"></i></button>
        <input class="form-control form-control-sm grid-column-full" data-financeiro-cell="observacao" placeholder="Observação" value="${escapeHtml(row.observacao || "")}">
        ${assinadoField}
      </div>`;
    }

    function financeiroAddRow(type) {
      state.financeiro.draft = financeiroCollectDraft();
      state.financeiro.draft[type] = state.financeiro.draft[type] || [];
      state.financeiro.draft[type].push({});
      financeiroRenderEditor(state.financeiro.draft);
    }

    function financeiroRemoveRow(type, index) {
      state.financeiro.draft = financeiroCollectDraft();
      state.financeiro.draft[type] = (state.financeiro.draft[type] || []).filter((_, idx) => idx !== index);
      financeiroRenderEditor(state.financeiro.draft);
    }

    function financeiroGerarValesDiaristas() {
      state.financeiro.draft = financeiroCollectDraft();
      const map = state.financeiro.draft || financeiroBlankMap();
      const diaristas = Array.isArray(map.diaristas) ? map.diaristas : [];
      const valesBase = (Array.isArray(map.vales) ? map.vales : []).filter(row => !financeiroIsValeChapa(row));
      const valesChapaExistentes = (Array.isArray(map.vales) ? map.vales : []).filter(financeiroIsValeChapa);
      const novosVales = [];
      diaristas
        .filter(row => financeiroNumber(row.valor) > 0 && row.recibo_recebido === false)
        .forEach(row => {
          const nome = String(row.nome || map.motorista || "").trim();
          const valor = financeiroNumber(row.valor);
          const valeManual = valesBase.some(vale => (
            financeiroTextKey(vale.nome) === financeiroTextKey(nome)
            && Math.abs(financeiroNumber(vale.valor) - valor) < 0.01
          ));
          const valeNovo = novosVales.some(vale => (
            financeiroTextKey(vale.nome) === financeiroTextKey(nome)
            && Math.abs(financeiroNumber(vale.valor) - valor) < 0.01
          ));
          if (valeManual || valeNovo) return;
          const existente = valesChapaExistentes.find(vale => (
            financeiroTextKey(vale.nome) === financeiroTextKey(nome)
            && Math.abs(financeiroNumber(vale.valor) - valor) < 0.01
          ));
          novosVales.push({
            nome,
            valor,
            observacao: "vale de chapa",
            assinado: Boolean(existente && existente.assinado)
          });
        });
      map.vales = valesBase.concat(novosVales);
      state.financeiro.draft = map;
      addLog(`${novosVales.length} vale(s) de chapa gerado(s).`, novosVales.length ? "ok" : "warn");
      financeiroRenderEditor(state.financeiro.draft);
    }

    function financeiroRequireFilial() {
      const filial = document.getElementById("financeiroFilialMapas") || document.getElementById("financeiroFilial");
      if (filial && String(filial.value || "").trim()) return true;
      addLog("Escolha uma revenda antes de lancar o caixa.", "warn");
      if (filial) filial.focus();
      return false;
    }

    function financeiroSetFechamentoLogHidden(hidden) {
      const els = financeiroElements();
      state.financeiro.fechamentoLogHidden = !!hidden;
      if (els.fechamentoLogBox) {
        els.fechamentoLogBox.classList.toggle("is-collapsed", state.financeiro.fechamentoLogHidden);
      }
      if (els.fechamentoLogToggle) {
        els.fechamentoLogToggle.setAttribute("aria-expanded", state.financeiro.fechamentoLogHidden ? "false" : "true");
        els.fechamentoLogToggle.innerHTML = state.financeiro.fechamentoLogHidden
          ? '<i class="bi bi-eye me-1"></i>Mostrar log'
          : '<i class="bi bi-eye-slash me-1"></i>Esconder log';
      }
    }

    function financeiroToggleFechamentoLog() {
      financeiroSetFechamentoLogHidden(!state.financeiro.fechamentoLogHidden);
    }

    function financeiroResetFechamentoLog(message = "Aguardando solicitação.") {
      const els = financeiroElements();
      if (state.financeiro.fechamentoLogTimer) {
        window.clearTimeout(state.financeiro.fechamentoLogTimer);
        state.financeiro.fechamentoLogTimer = null;
      }
      state.financeiro.fechamentoJobId = "";
      state.financeiro.fechamentoLogDone = false;
      if (els.fechamentoLogJob) els.fechamentoLogJob.textContent = "Sem job ativo";
      if (els.fechamentoLogList) {
        els.fechamentoLogList.innerHTML = `<li><span class="time">--:--</span><span>${escapeHtml(message)}</span></li>`;
      }
    }

    function financeiroRenderFechamentoLog(payload) {
      const els = financeiroElements();
      if (!els.fechamentoLogList) return;
      const job = payload && payload.job ? payload.job : {};
      const logs = Array.isArray(payload && payload.logs) ? payload.logs : [];
      const phases = Array.isArray(payload && payload.phases) ? payload.phases : [];
      const items = phases.length ? phases : logs.slice(-8).map(item => ({
        created_at: item.created_at,
        level: item.level || "info",
        label: item.message || ""
      })).filter(item => item.label);
      if (els.fechamentoLogJob) {
        const shortId = String(job.id || state.financeiro.fechamentoJobId || "").slice(0, 8);
        const status = String(job.status || job.result_status || "").trim();
        els.fechamentoLogJob.textContent = shortId ? `Job ${shortId}${status ? ` | ${status}` : ""}` : "Job ativo";
      }
      els.fechamentoLogList.innerHTML = items.length ? items.map(item => {
        const level = String(item.level || "info").toLowerCase();
        const marker = level === "error" ? "text-danger" : level === "warning" || level === "warn" ? "text-warning" : "";
        return `<li><span class="time">${escapeHtml(formatDateTime(item.created_at) || "--:--")}</span><span class="${marker}">${escapeHtml(item.label || item.message || "")}</span></li>`;
      }).join("") : '<li><span class="time">--:--</span><span>Job enfileirado. Aguardando worker iniciar.</span></li>';
    }

    function financeiroFechamentoJobParams() {
      const els = financeiroElements();
      const params = new URLSearchParams({ limit: "100" });
      const status = String(els.fechamentoJobStatusFilter && els.fechamentoJobStatusFilter.value || "").trim();
      const createdFrom = String(els.fechamentoJobFromDate && els.fechamentoJobFromDate.value || "").trim();
      const createdTo = String(els.fechamentoJobToDate && els.fechamentoJobToDate.value || "").trim();
      if (createdFrom && createdTo && createdTo < createdFrom) {
        throw new Error("A data final do filtro não pode ser anterior a inicial.");
      }
      if (status) params.set("status", status);
      if (createdFrom) params.set("created_from", createdFrom);
      if (createdTo) params.set("created_to", createdTo);
      return params;
    }

    function financeiroRenderFechamentoJobs() {
      const els = financeiroElements();
      if (!els.fechamentoJobsBody) return;
      const allJobs = Array.isArray(state.financeiro.fechamentoJobs) ? state.financeiro.fechamentoJobs : [];
      const hiddenIds = new Set(Array.isArray(state.financeiro.fechamentoHiddenJobIds) ? state.financeiro.fechamentoHiddenJobIds.map(String) : []);
      const jobs = allJobs.filter(job => !hiddenIds.has(String(job && job.id || "")));
      const hiddenCount = Math.max(allJobs.length - jobs.length, 0);
      if (els.fechamentoJobShowHidden) {
        els.fechamentoJobShowHidden.hidden = hiddenCount < 1;
        els.fechamentoJobShowHidden.innerHTML = `<i class="bi bi-eye me-1"></i>Mostrar ${hiddenCount} oculto(s)`;
      }
      els.fechamentoJobsBody.innerHTML = jobs.length ? jobs.map(job => {
        const payload = job && job.payload && typeof job.payload === "object" ? job.payload : {};
        const result = job && job.result && typeof job.result === "object" ? job.result : {};
        const status = String(job.status || "");
        const running = status === "running" || status === "cancel_requested";
        const pending = status === "pending";
        const message = String(result.message || job.error || "").trim();
        const visibleMessage = message.length > 110 ? `${message.slice(0, 107)}...` : message;
        const mapa = String(payload.mapa || "-");
        const filial = String(payload.filial || "-");
        const modo = String(payload.modo || "-");
        const data = String(payload.data || "-");
        const kmFallback = String(payload.km_fallback_atual || "").trim();
        const kmInfo = kmFallback
          ? `<div class="small text-secondary">KM fallback: ${escapeHtml(kmFallback)}</div>`
          : "";
        const stopAction = (running || pending)
          ? `<button class="btn btn-outline-danger btn-sm" onclick="financeiroStopFechamentoJob('${escapeHtml(job.id)}')"><i class="bi bi-stop-circle me-1"></i>${running ? "Parar" : "Cancelar"}</button>`
          : "";
        const hideAction = `<button class="btn btn-outline-secondary btn-sm" onclick="financeiroHideFechamentoJob('${escapeHtml(job.id)}')"><i class="bi bi-eye-slash me-1"></i>Esconder</button>`;
        return `<tr>
          <td><span class="small">${escapeHtml(formatDateTime(job.created_at))}</span><div class="mono small text-secondary">${escapeHtml(String(job.id || "").slice(0, 8))}</div></td>
          <td><strong>${escapeHtml(mapa)}</strong><div class="small text-secondary">Revenda ${escapeHtml(filial)} | ${escapeHtml(data)}</div></td>
          <td>${escapeHtml(modo)}${kmInfo}</td>
          <td><span class="promax-status ${promaxStatusClass(status)}">${escapeHtml(promaxStatusLabel(status))}</span>${visibleMessage ? `<div class="small text-secondary mt-1" title="${escapeHtml(message)}">${escapeHtml(visibleMessage)}</div>` : ""}</td>
          <td>${escapeHtml(job.leased_by || "-")}</td>
          <td class="text-end"><div class="d-flex gap-1 justify-content-end">${stopAction}${hideAction}<button class="btn btn-outline-primary btn-sm" onclick="financeiroOpenFechamentoJob('${escapeHtml(job.id)}')"><i class="bi bi-terminal me-1"></i>Logs</button></div></td>
        </tr>`;
      }).join("") : `<tr><td colspan="6" class="text-center py-3 text-secondary">${hiddenCount ? "Todas as execuções carregadas estão escondidas." : "Nenhuma execução de fechamento encontrada."}</td></tr>`;
    }

    async function financeiroSyncFechamentoJobs({ silent = true } = {}) {
      const els = financeiroElements();
      if (!els.fechamentoJobsBody || !(state.panel && state.panel.canFinanceiro)) return false;
      let params;
      try {
        params = financeiroFechamentoJobParams();
      } catch (err) {
        if (!silent) addLog(err.message, "warn");
        return false;
      }
      try {
        const payload = await req(`${CONFIG.endpoints.financeiro.fechamentoPromaxJobs}?${params.toString()}`, { timeoutMs: 20000 });
        state.financeiro.fechamentoJobs = Array.isArray(payload.jobs) ? payload.jobs : [];
        financeiroRenderFechamentoJobs();
        financeiroScheduleFechamentoJobsRefresh();
        return true;
      } catch (err) {
        if (!silent) addLog(`Falha ao carregar execuções de fechamento: ${err.message}`, "err");
        return false;
      }
    }

    function financeiroOpenFechamentoJob(jobId) {
      const cleanJobId = String(jobId || "").trim();
      if (!cleanJobId) return;
      state.financeiro.fechamentoJobId = cleanJobId;
      state.financeiro.fechamentoLogDone = false;
      financeiroSetFechamentoLogHidden(false);
      const els = financeiroElements();
      if (els.fechamentoLogJob) els.fechamentoLogJob.textContent = `Job ${cleanJobId.slice(0, 8)}`;
      if (els.fechamentoLogList) {
        els.fechamentoLogList.innerHTML = '<li><span class="time">--:--</span><span>Carregando logs do fechamento.</span></li>';
      }
      financeiroPollFechamentoLog(cleanJobId);
    }

    function financeiroHideFechamentoJob(jobId) {
      const cleanJobId = String(jobId || "").trim();
      if (!cleanJobId) return;
      if (!Array.isArray(state.financeiro.fechamentoHiddenJobIds)) {
        state.financeiro.fechamentoHiddenJobIds = [];
      }
      if (!state.financeiro.fechamentoHiddenJobIds.map(String).includes(cleanJobId)) {
        state.financeiro.fechamentoHiddenJobIds.push(cleanJobId);
      }
      financeiroRenderFechamentoJobs();
    }

    function financeiroShowHiddenFechamentoJobs() {
      state.financeiro.fechamentoHiddenJobIds = [];
      financeiroRenderFechamentoJobs();
    }

    async function financeiroStopFechamentoJob(jobId) {
      const cleanJobId = String(jobId || "").trim();
      if (!cleanJobId) return;
      const confirmed = await askConfirmation("Interromper esta execução de fechamento?");
      if (!confirmed) return;
      try {
        await req(`${CONFIG.endpoints.financeiro.fechamentoPromaxLogs}/${encodeURIComponent(cleanJobId)}/stop`, {
          method: "POST",
          timeoutMs: 15000
        });
        addLog("Solicitação de parada enviada para o fechamento.", "ok");
        await financeiroSyncFechamentoJobs({ silent: true });
        financeiroOpenFechamentoJob(cleanJobId);
      } catch (err) {
        addLog(`Falha ao parar fechamento: ${err.message}`, "err");
      }
    }

    function financeiroApplyFechamentoJobFilters() {
      financeiroSyncFechamentoJobs({ silent: false });
    }

    function financeiroClearFechamentoJobFilters() {
      const els = financeiroElements();
      if (els.fechamentoJobStatusFilter) els.fechamentoJobStatusFilter.value = "";
      if (els.fechamentoJobFromDate) els.fechamentoJobFromDate.value = "";
      if (els.fechamentoJobToDate) els.fechamentoJobToDate.value = "";
      financeiroSyncFechamentoJobs({ silent: false });
    }

    async function financeiroPollFechamentoLog(jobId, attempt = 0) {
      const cleanJobId = String(jobId || "").trim();
      if (!cleanJobId || state.financeiro.fechamentoJobId !== cleanJobId) return;
      try {
        const payload = await req(`${CONFIG.endpoints.financeiro.fechamentoPromaxLogs}/${encodeURIComponent(cleanJobId)}/logs?limit=120`, { timeoutMs: 15000 });
        financeiroRenderFechamentoLog(payload);
        const status = String(payload && payload.job && payload.job.status || "").toLowerCase();
        if (["success", "partial_success", "error", "failed", "cancelled", "canceled"].includes(status)) {
          state.financeiro.fechamentoLogDone = true;
          return;
        }
      } catch (err) {
        const els = financeiroElements();
        if (els.fechamentoLogList) {
          els.fechamentoLogList.innerHTML = `<li><span class="time">--:--</span><span class="text-danger">Falha ao carregar log: ${escapeHtml(err.message)}</span></li>`;
        }
      }
      if (attempt < 80 && state.financeiro.fechamentoJobId === cleanJobId) {
        state.financeiro.fechamentoLogTimer = window.setTimeout(() => financeiroPollFechamentoLog(cleanJobId, attempt + 1), 5000);
      }
    }

    async function syncFinanceiro({ silent = true, refreshDraft = false } = {}) {
      const els = financeiroElements();
      if (!els.editor || !(state.panel && state.panel.canFinanceiro)) return;
      if (!els.data.value) els.data.value = formatDateInputValue(new Date());
      if (els.fechamentoData && !els.fechamentoData.value) els.fechamentoData.value = els.data.value;
      const params = new URLSearchParams({ data: els.data.value });
      if (els.filial && els.filial.value) params.set("filial", els.filial.value);
      if (refreshDraft) state.financeiro.draft = null;
      state.financeiro.loading = true;
      financeiroRender({ preserveEditor: true });
      try {
        const [caixaResult, workerResult] = await Promise.allSettled([
          req(`${CONFIG.endpoints.financeiro.caixas}?${params.toString()}`, { timeoutMs: 20000 }),
          req(CONFIG.endpoints.financeiro.worker, { timeoutMs: 12000 }),
          financeiroSyncFechamentoJobs({ silent: true })
        ]);
        if (workerResult.status === "fulfilled") {
          state.financeiro.worker = workerResult.value || null;
        }
        if (caixaResult.status === "rejected") throw caixaResult.reason;
        const payload = caixaResult.value;
        state.financeiro.payload = payload;
        if (payload.maps && payload.maps.length && !payload.maps.some(item => String(item.id) === String(state.financeiro.selectedId))) {
          state.financeiro.selectedId = payload.maps[0].id;
          state.financeiro.draft = null;
        }
        if (refreshDraft && payload.maps && payload.maps.length) {
          const refreshed = payload.maps.find(item => String(item.id) === String(state.financeiro.selectedId));
          state.financeiro.draft = refreshed
            ? financeiroNormalizeHospedagemDraft(Object.assign(JSON.parse(JSON.stringify(refreshed)), { dirty_fields: [] }))
            : null;
        }
        if (!payload.maps || !payload.maps.length) {
          state.financeiro.selectedId = null;
          state.financeiro.draft = financeiroBlankMap();
        }
        if (workerResult.status === "rejected" && !silent) {
          addLog(`Financeiro: não foi possível consultar o worker de fechamento: ${workerResult.reason.message}`, "warn");
        }
        if (!silent) addLog("Fechamento financeiro atualizado.", "ok");
      } catch (err) {
        if (!silent) addLog(`Falha ao carregar fechamento financeiro: ${err.message}`, "err");
      } finally {
        state.financeiro.loading = false;
        financeiroRender({ preserveEditor: !refreshDraft });
      }
    }

    async function downloadFinanceiroCaixaPdf() {
      updateTokens();
      const els = financeiroElements();
      if (!els.data || !els.data.value) {
        addLog("Informe a data do caixa antes de exportar.", "warn");
        return;
      }
      financeiroSyncFilialSelects((els.filial && els.filial.value) ? els.filial : els.filialMapas);
      const filial = els.filial && els.filial.value ? els.filial.value : "";
      if (!filial) {
        addLog("Escolha uma revenda antes de exportar o PDF do caixa.", "warn");
        return;
      }
      const headers = {};
      if (state.tokens.api) headers["x-api-token"] = state.tokens.api;
      if (state.tokens.admin) headers["x-admin-token"] = state.tokens.admin;
      const params = new URLSearchParams({ data: els.data.value, filial });
      const originalHtml = els.exportPdf ? els.exportPdf.innerHTML : "";
      if (els.exportPdf) {
        els.exportPdf.disabled = true;
        els.exportPdf.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Gerando';
      }
      try {
        const response = await fetch(`${CONFIG.api}${CONFIG.endpoints.financeiro.caixaPdf}?${params.toString()}`, {
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
        const filename = matchedName && matchedName[1] ? matchedName[1] : `caixa-financeiro-${filial}-${els.data.value}.pdf`;
        const blobUrl = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = blobUrl;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(blobUrl);
        addLog("PDF do caixa exportado.", "ok");
      } catch (err) {
        addLog(`Falha ao exportar PDF do caixa: ${err.message}`, "err");
      } finally {
        if (els.exportPdf) {
          els.exportPdf.disabled = false;
          els.exportPdf.innerHTML = originalHtml || '<i class="bi bi-file-earmark-pdf me-1"></i>Exportar PDF';
        }
      }
    }

    async function financeiroSaveMap() {
      const els = financeiroElements();
      financeiroSyncFilialSelects(els.filialMapas || els.filial);
      state.financeiro.draft = financeiroCollectDraft();
      if (!financeiroRequireFilial()) return;
      if (!String(state.financeiro.draft.mapa || "").trim()) {
        addLog("Informe o número do mapa antes de salvar.", "warn");
        return;
      }
      if (["despesa", "vale"].includes(state.financeiro.draft.tipo_bloco || "")) {
        if (!String(state.financeiro.draft.mapa_ref || "").trim()) {
          addLog("Informe o mapa vinculado antes de salvar o lançamento.", "warn");
          return;
        }
        if (!String(state.financeiro.draft.motorista || "").trim()) {
          addLog("Informe o motorista antes de salvar o lançamento.", "warn");
          return;
        }
      }
      try {
        const result = await req(CONFIG.endpoints.financeiro.mapas, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(state.financeiro.draft),
          timeoutMs: 20000
        });
        state.financeiro.selectedId = result.map && result.map.id;
        state.financeiro.draft = null;
        addLog("Mapa financeiro salvo.", "ok");
        await syncFinanceiro({ silent: true, refreshDraft: true });
      } catch (err) {
        addLog(`Falha ao salvar mapa financeiro: ${err.message}`, "err");
      }
    }

    async function financeiroDeleteMap() {
      const draft = state.financeiro.draft || {};
      if (!draft.id || !await askConfirmation("Excluir este mapa do fechamento?")) return;
      try {
        await req(`${CONFIG.endpoints.financeiro.mapas}/${encodeURIComponent(draft.id)}`, { method: "DELETE", timeoutMs: 20000 });
        state.financeiro.selectedId = null;
        state.financeiro.draft = null;
        addLog("Mapa financeiro excluido.", "ok");
        await syncFinanceiro({ silent: true });
      } catch (err) {
        addLog(`Falha ao excluir mapa financeiro: ${err.message}`, "err");
      }
    }

    function financeiroSetSubtab(tab) {
      const activeTab = tab || "fechamento";
      document.querySelectorAll("[data-financeiro-subtab]").forEach(button => {
        const isActive = button.dataset.financeiroSubtab === activeTab;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-selected", isActive ? "true" : "false");
      });
      document.querySelectorAll("[data-financeiro-subpanel]").forEach(panel => {
        panel.hidden = panel.dataset.financeiroSubpanel !== activeTab;
      });
    }

    function setupFinanceiroEvents() {
      const els = financeiroElements();
      if (!els.editor) return;
      if (!els.data.value) els.data.value = formatDateInputValue(new Date());
      if (els.fechamentoData && !els.fechamentoData.value) els.fechamentoData.value = els.data.value;
      if (els.fechamentoData) {
        els.fechamentoData.addEventListener("input", () => {
          state.financeiro.fechamentoDataManual = true;
        });
        els.fechamentoData.addEventListener("change", () => {
          state.financeiro.fechamentoDataManual = Boolean(els.fechamentoData.value);
        });
      }
      document.querySelectorAll("[data-financeiro-subtab]").forEach(button => {
        button.addEventListener("click", () => financeiroSetSubtab(button.dataset.financeiroSubtab));
      });
      financeiroSetSubtab("fechamento");
      if (els.refresh) els.refresh.addEventListener("click", () => syncFinanceiro({ silent: false }));
      if (els.exportPdf) els.exportPdf.addEventListener("click", downloadFinanceiroCaixaPdf);
      if (els.fechamentoBtn) els.fechamentoBtn.addEventListener("click", financeiroSolicitarFechamentoPromax);
      if (els.fechamentoRefresh) els.fechamentoRefresh.addEventListener("click", () => syncFinanceiro({ silent: false }));
      if (els.fechamentoLogToggle) els.fechamentoLogToggle.addEventListener("click", financeiroToggleFechamentoLog);
      if (els.fechamentoJobStatusFilter) els.fechamentoJobStatusFilter.addEventListener("change", financeiroApplyFechamentoJobFilters);
      if (els.fechamentoJobFromDate) els.fechamentoJobFromDate.addEventListener("change", financeiroApplyFechamentoJobFilters);
      if (els.fechamentoJobToDate) els.fechamentoJobToDate.addEventListener("change", financeiroApplyFechamentoJobFilters);
      if (els.fechamentoJobShowHidden) els.fechamentoJobShowHidden.addEventListener("click", financeiroShowHiddenFechamentoJobs);
      if (els.fechamentoJobClearFilters) els.fechamentoJobClearFilters.addEventListener("click", financeiroClearFechamentoJobFilters);
      if (els.rel031120Download) els.rel031120Download.addEventListener("click", financeiroSolicitar031120Download);
      if (els.rel031120Upload) els.rel031120Upload.addEventListener("click", financeiroImportar031120Upload);
      if (els.novo) els.novo.addEventListener("click", () => {
        if (!financeiroRequireFilial()) return;
        state.financeiro.selectedId = null;
        state.financeiro.draft = financeiroBlankMap();
        if (els.fechamentoMapa) els.fechamentoMapa.value = "";
        if (els.fechamentoKm) els.fechamentoKm.value = "";
        financeiroRender();
        financeiroSetSubtab("mapas");
      });
      if (els.compra) els.compra.addEventListener("click", () => {
        if (!financeiroRequireFilial()) return;
        state.financeiro.selectedId = null;
        state.financeiro.draft = financeiroBlankMap({ tipo_bloco: "compra", mapa: "COMPRA", motorista: "Compra" });
        financeiroRender();
        financeiroSetSubtab("mapas");
      });
      if (els.despesa) els.despesa.addEventListener("click", () => {
        if (!financeiroRequireFilial()) return;
        state.financeiro.selectedId = null;
        state.financeiro.draft = { tipo_bloco: "despesa_conferencia" };
        financeiroRender();
        financeiroSetSubtab("mapas");
      });
      if (els.vale) els.vale.addEventListener("click", () => {
        if (!financeiroRequireFilial()) return;
        state.financeiro.selectedId = null;
        state.financeiro.draft = { tipo_bloco: "vale_conferencia" };
        financeiroRender();
        financeiroSetSubtab("mapas");
      });
      if (els.data) els.data.addEventListener("change", () => {
        if (els.fechamentoData && (!state.financeiro.fechamentoDataManual || !els.fechamentoData.value)) {
          els.fechamentoData.value = els.data.value || formatDateInputValue(new Date());
          state.financeiro.fechamentoDataManual = false;
        }
        state.financeiro.selectedId = null;
        state.financeiro.draft = null;
        syncFinanceiro({ silent: false });
      });
      [els.filial, els.filialMapas].forEach(element => {
        if (element) element.addEventListener("change", () => {
          financeiroSyncFilialSelects(element);
          financeiroUpdate031120Panel();
          state.financeiro.selectedId = null;
          state.financeiro.draft = null;
          syncFinanceiro({ silent: false });
        });
      });
      if (els.fechamentoMapa) {
        els.fechamentoMapa.addEventListener("keydown", event => {
          if (event.key === "Enter") financeiroSolicitarFechamentoPromax();
        });
      }
    }
