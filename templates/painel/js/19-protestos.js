    function formatProtestoDate(value) {
      const text = String(value || "").trim();
      if (!text) return "-";
      if (/^\d{2}\/\d{2}\/\d{4}$/.test(text)) return text;
      if (/^\d{4}-\d{2}-\d{2}/.test(text)) {
        const [year, month, day] = text.slice(0, 10).split("-");
        return `${day}/${month}/${year}`;
      }
      const dt = new Date(text);
      if (Number.isNaN(dt.getTime())) return text;
      return dt.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric" });
    }

    function formatProtestoMoney(value) {
      let text = String(value || "").trim();
      if (!text) return "-";
      const negative = /-/.test(text);
      text = text.replace(/[^\d,.-]/g, "");
      if (!text) return "-";
      let normalized;
      if (text.includes(",")) {
        normalized = text.replace(/\./g, "").replace(",", ".");
      } else {
        normalized = text;
      }
      const amount = Number(normalized);
      if (!Number.isFinite(amount)) return String(value || "-");
      return `${negative ? "- " : ""}${Math.abs(amount).toLocaleString("pt-BR", { style: "currency", currency: "BRL" })}`;
    }

    function protestoStatusLabel(status) {
      const labels = {
        em_aberto: "Aberto na 120601",
        em_acompanhamento: "Em acompanhamento",
        protestado: "Protestado",
        pago_retirar_spc: "Pago / retirar SPC",
        baixado: "Baixado",
        cancelado: "Cancelado"
      };
      return labels[String(status || "").trim()] || "Aberto na 120601";
    }

    function protestoStatusClass(status) {
      if (status === "pago_retirar_spc") return "text-danger";
      if (status === "protestado") return "text-warning";
      if (status === "baixado") return "text-success";
      if (status === "cancelado") return "text-secondary";
      return "";
    }

    function formatProtestoTitulo(value) {
      const text = String(value || "").trim();
      if (!text) return "-";
      const numeric = text.replace(/\D/g, "");
      if (numeric) return String(Number.parseInt(numeric, 10));
      return text;
    }

    function renderProtestos() {
      const payload = state.protestos && state.protestos.payload ? state.protestos.payload : null;
      const loading = Boolean(state.protestos && state.protestos.loading);
      const error = state.protestos && state.protestos.error ? String(state.protestos.error) : "";
      if (E.protestosStatus) {
        if (loading) {
          E.protestosStatus.textContent = "Carregando...";
          E.protestosStatus.className = "pill warn";
        } else if (error) {
          E.protestosStatus.textContent = "Falha";
          E.protestosStatus.className = "pill warn";
        } else if (payload) {
          E.protestosStatus.textContent = `${formatNumber((payload.titles || []).length)} título(s)`;
          E.protestosStatus.className = "pill ok";
        } else {
          E.protestosStatus.textContent = "Aguardando dados";
          E.protestosStatus.className = "pill";
        }
      }
      if (E.protestosRefreshBtn) E.protestosRefreshBtn.disabled = loading;
      if (E.protestosApplyBtn) E.protestosApplyBtn.disabled = loading;
      renderProtestosFiliais(payload);
      renderProtestosSummary(payload ? payload.summary : null);
      renderProtestosPaidAlert(payload ? payload.paid_alerts : []);
      renderProtestosRows(payload, error, loading);
    }

    function renderProtestosFiliais(payload) {
      if (!E.protestosFilial || !payload || !Array.isArray(payload.filiais)) return;
      const selected = E.protestosFilial.value;
      const options = ['<option value="">Todas liberadas</option>']
        .concat(payload.filiais.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.id)} - ${escapeHtml(item.name || item.id)}</option>`));
      E.protestosFilial.innerHTML = options.join("");
      if ([...E.protestosFilial.options].some(option => option.value === selected)) E.protestosFilial.value = selected;
    }

    function renderProtestosSummary(summary) {
      if (!E.protestosSummary) return;
      const data = summary || {};
      const cards = [
        ["Títulos abertos", data.titulos_abertos || 0, ""],
        ["Clientes abertos", data.clientes_abertos || 0, ""],
        ["Acompanhados", data.acompanhados || 0, ""],
        ["Protestados", data.protestados || 0, ""],
        ["Retirar SPC", data.retirar_spc || 0, "text-danger"],
        ["Atualização 120601", data.updated_at ? formatDateTime(data.updated_at) : "-", ""]
      ];
      E.protestosSummary.innerHTML = cards.map(([label, value, cls]) => `
        <div class="col-md-2 col-sm-4">
          <div class="metric-card h-100">
            <span>${escapeHtml(label)}</span>
            <strong class="${escapeHtml(cls)}">${escapeHtml(String(value))}</strong>
          </div>
        </div>
      `).join("");
    }

    function renderProtestosPaidAlert(alerts) {
      if (!E.protestosPaidAlert) return;
      const rows = Array.isArray(alerts) ? alerts : [];
      if (!rows.length) {
        E.protestosPaidAlert.classList.add("d-none");
        E.protestosPaidAlert.innerHTML = "";
        return;
      }
      E.protestosPaidAlert.classList.remove("d-none");
      E.protestosPaidAlert.innerHTML = `
        <strong>Alerta para retirada do SPC:</strong>
        ${rows.slice(0, 8).map(item => `${escapeHtml(item.filial || "")}/${escapeHtml(item.nb || "")} - NF ${escapeHtml(item.nota_fiscal || "-")}`).join("; ")}
        ${rows.length > 8 ? ` e mais ${formatNumber(rows.length - 8)}.` : ""}
      `;
    }

    function renderProtestosRows(payload, error, loading) {
      if (!E.protestosBody) return;
      if (loading && !payload) {
        E.protestosBody.innerHTML = '<tr><td colspan="6" class="text-center py-4 text-secondary"><span class="spinner-border spinner-border-sm me-1"></span>Carregando títulos...</td></tr>';
        return;
      }
      if (error) {
        E.protestosBody.innerHTML = `<tr><td colspan="6" class="text-danger"><strong>Falha:</strong> ${escapeHtml(error)}</td></tr>`;
        return;
      }
      const rows = payload && Array.isArray(payload.titles) ? payload.titles : [];
      if (!rows.length) {
        E.protestosBody.innerHTML = '<tr><td colspan="6" class="text-center py-4 text-secondary">Nenhum título encontrado nos filtros atuais.</td></tr>';
        return;
      }
      E.protestosBody.innerHTML = rows.map(item => {
        const key = item.titulo_key || "";
        const status = item.status || "em_aberto";
        const boletoDownload = item.boleto_assinado_name
          ? `<button class="btn btn-outline-success btn-sm protesto-download-btn" type="button" data-kind="boleto_assinado"><i class="bi bi-download me-1"></i>Baixar</button>`
          : "";
        const comprovanteDownload = item.comprovante_protesto_name
          ? `<button class="btn btn-outline-success btn-sm protesto-download-btn" type="button" data-kind="comprovante_protesto"><i class="bi bi-download me-1"></i>Baixar</button>`
          : "";
        return `
          <tr data-protesto-key="${escapeHtml(key)}">
            <td>
              <strong>Título ${escapeHtml(formatProtestoTitulo(item.titulo_numero))}</strong>
              <div class="small text-secondary">Revenda ${escapeHtml(item.filial || "")} - ${escapeHtml(item.filial_nome || "")}</div>
              <div class="small text-secondary">NB ${escapeHtml(item.nb || "-")}</div>
              <div class="small mono">NF ${escapeHtml(item.nota_fiscal || "-")}</div>
            </td>
            <td class="min-w-220">
              <strong>${escapeHtml(item.cliente_nome || "-")}</strong>
            </td>
            <td>
              <div class="protesto-date-value">
                <div class="protesto-date-line"><span class="label">Venc.</span><span class="value">${escapeHtml(formatProtestoDate(item.data_vencimento))}</span></div>
                <div class="protesto-date-line"><span class="label">Emissão</span><span class="value">${escapeHtml(formatProtestoDate(item.data_emissao))}</span></div>
                <div class="protesto-money">${escapeHtml(formatProtestoMoney(item.valor_pendente))}</div>
              </div>
            </td>
            <td class="min-w-180">
              <select class="form-select form-select-sm protesto-status-select ${escapeHtml(protestoStatusClass(status))}">
                ${["em_acompanhamento", "protestado", "pago_retirar_spc", "baixado", "cancelado"].map(value => `<option value="${value}" ${status === value ? "selected" : ""}>${escapeHtml(protestoStatusLabel(value))}</option>`).join("")}
              </select>
              <div class="small text-secondary mt-1">Atualizado: ${escapeHtml(item.updated_at ? formatDateTime(item.updated_at) : "-")}</div>
            </td>
            <td class="min-w-220">
              <div class="d-flex flex-column gap-1 small">
                <div class="d-flex gap-1 align-items-center justify-content-between">
                  <span class="${item.boleto_assinado_name ? "text-success" : "text-secondary"}">Boleto: ${escapeHtml(item.boleto_assinado_name || "não enviado")}</span>
                  ${boletoDownload}
                </div>
                <label class="btn btn-outline-secondary btn-sm mb-1"><i class="bi bi-upload me-1"></i>Enviar boleto<input class="d-none protesto-upload" type="file" accept="application/pdf,.pdf" data-kind="boleto_assinado"></label>
                <div class="d-flex gap-1 align-items-center justify-content-between">
                  <span class="${item.comprovante_protesto_name ? "text-success" : "text-secondary"}">Comprovante: ${escapeHtml(item.comprovante_protesto_name || "não enviado")}</span>
                  ${comprovanteDownload}
                </div>
                <label class="btn btn-outline-secondary btn-sm mb-0"><i class="bi bi-upload me-1"></i>Enviar comprovante<input class="d-none protesto-upload" type="file" accept="application/pdf,.pdf" data-kind="comprovante_protesto"></label>
              </div>
            </td>
            <td class="min-w-240">
              <textarea class="form-control form-control-sm protesto-obs mb-2" rows="2" placeholder="Observação">${escapeHtml(item.observacao || "")}</textarea>
              <button class="btn btn-primary btn-sm w-100 protesto-save-btn" type="button"><i class="bi bi-check2-circle me-1"></i>Salvar acompanhamento</button>
            </td>
          </tr>
        `;
      }).join("");
      E.protestosBody.querySelectorAll(".protesto-save-btn").forEach(button => {
        button.addEventListener("click", () => saveProtestoRow(button.closest("tr")));
      });
      E.protestosBody.querySelectorAll(".protesto-upload").forEach(input => {
        input.addEventListener("change", () => uploadProtestoDocument(input.closest("tr"), input));
      });
      E.protestosBody.querySelectorAll(".protesto-download-btn").forEach(button => {
        button.addEventListener("click", () => downloadProtestoDocument(button.closest("tr"), button.getAttribute("data-kind") || ""));
      });
    }

    function protestosQueryString() {
      const params = new URLSearchParams();
      const filial = E.protestosFilial ? String(E.protestosFilial.value || "").trim() : "";
      const status = E.protestosStatusFilter ? String(E.protestosStatusFilter.value || "").trim() : "";
      const search = E.protestosSearch ? String(E.protestosSearch.value || "").trim() : "";
      const titleFrom = E.protestosTitleDateFrom ? String(E.protestosTitleDateFrom.value || "").trim() : "";
      const titleTo = E.protestosTitleDateTo ? String(E.protestosTitleDateTo.value || "").trim() : "";
      const protestFrom = E.protestosActionDateFrom ? String(E.protestosActionDateFrom.value || "").trim() : "";
      const protestTo = E.protestosActionDateTo ? String(E.protestosActionDateTo.value || "").trim() : "";
      if (filial) params.set("filial", filial);
      if (status) params.set("status", status);
      if (search) params.set("search", search);
      if (titleFrom) params.set("title_date_from", titleFrom);
      if (titleTo) params.set("title_date_to", titleTo);
      if (protestFrom) params.set("protest_date_from", protestFrom);
      if (protestTo) params.set("protest_date_to", protestTo);
      params.set("limit", "300");
      return `?${params.toString()}`;
    }

    async function syncProtestos({ silent = true } = {}) {
      if (!hasPanelAuth()) return false;
      state.protestos.loading = true;
      state.protestos.error = "";
      renderProtestos();
      try {
        const payload = await req(`${CONFIG.endpoints.protestos.list}${protestosQueryString()}`, { timeoutMs: 45000 });
        state.protestos.payload = payload;
        state.protestos.error = "";
        if (!silent) addLog(`Protestos atualizados: ${formatNumber((payload.titles || []).length)} título(s).`, "ok");
        return true;
      } catch (err) {
        state.protestos.error = err.message || "Falha ao carregar protestos.";
        if (!silent) addLog(`Falha ao carregar protestos: ${err.message}`, "err");
        return false;
      } finally {
        state.protestos.loading = false;
        renderProtestos();
      }
    }

    async function saveProtestoRow(row) {
      if (!row) return;
      const key = row.getAttribute("data-protesto-key") || "";
      const status = row.querySelector(".protesto-status-select")?.value || "em_acompanhamento";
      const observacao = row.querySelector(".protesto-obs")?.value || "";
      const btn = row.querySelector(".protesto-save-btn");
      const previous = btn ? btn.innerHTML : "";
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Salvando';
      }
      try {
        await req(`${CONFIG.endpoints.protestos.update}/${encodeURIComponent(key)}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status, observacao }),
          timeoutMs: 30000
        });
        addLog("Título de protesto atualizado.", "ok");
        await syncProtestos({ silent: true });
      } catch (err) {
        addLog(`Falha ao salvar protesto: ${err.message}`, "err");
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = previous;
        }
      }
    }

    async function uploadProtestoDocument(row, input) {
      if (!row || !input || !input.files || !input.files[0]) return;
      const key = row.getAttribute("data-protesto-key") || "";
      const kind = input.getAttribute("data-kind") || "";
      const formData = new FormData();
      formData.append("file", input.files[0]);
      input.disabled = true;
      try {
        await req(`${CONFIG.endpoints.protestos.upload}/${encodeURIComponent(key)}/documentos/${encodeURIComponent(kind)}`, {
          method: "POST",
          body: formData,
          timeoutMs: 90000
        });
        addLog("Documento do protesto enviado.", "ok");
        await syncProtestos({ silent: true });
      } catch (err) {
        addLog(`Falha ao enviar documento: ${err.message}`, "err");
      } finally {
        input.disabled = false;
        input.value = "";
      }
    }

    async function downloadProtestoDocument(row, kind) {
      updateTokens();
      if (!row || !kind || !hasPanelAuth()) return;
      const key = row.getAttribute("data-protesto-key") || "";
      const button = row.querySelector(`.protesto-download-btn[data-kind="${CSS.escape(kind)}"]`);
      const previous = button ? button.innerHTML : "";
      if (button) {
        button.disabled = true;
        button.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Baixando';
      }
      try {
        const headers = {};
        if (state.tokens.api) headers["x-api-token"] = state.tokens.api;
        if (state.tokens.admin) headers["x-admin-token"] = state.tokens.admin;
        const response = await fetch(`${CONFIG.api}${CONFIG.endpoints.protestos.upload}/${encodeURIComponent(key)}/documentos/${encodeURIComponent(kind)}`, {
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
        const filename = matchedName && matchedName[1] ? matchedName[1] : `${kind}.pdf`;
        const blobUrl = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = blobUrl;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(blobUrl);
        addLog("Documento do protesto baixado.", "ok");
      } catch (err) {
        addLog(`Falha ao baixar documento: ${err.message}`, "err");
      } finally {
        if (button) {
          button.disabled = false;
          button.innerHTML = previous;
        }
      }
    }
