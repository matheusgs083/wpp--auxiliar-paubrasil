    // Aba Clientes: pesquisa na carteira autorizada; a ficha abre em blocos (24-ficha-cliente.js).
    // O servidor aplica o escopo; aqui só se mostra o que ele devolveu.

    const CLIENTES_SITUACAO = {
      vencido: { rotulo: "Vencido", tom: "err", icone: "bi-exclamation-octagon" },
      hoje: { rotulo: "Vence hoje", tom: "warn", icone: "bi-alarm" },
      amanha: { rotulo: "Vence amanhã", tom: "warn", icone: "bi-clock-history" },
      dois_dias: { rotulo: "Vence em 2 dias", tom: "info", icone: "bi-clock" },
      em_dia: { rotulo: "Em dia", tom: "ok", icone: "bi-check2-circle" },
      sem_data: { rotulo: "Sem vencimento", tom: "neutral", icone: "bi-dash-circle" }
    };

    function clientesChave(valor) {
      return String(valor || "").replace("_", "-");
    }

    function clientesSetStatus(message, kind = "") {
      const element = document.getElementById("clientesStatus");
      if (!element) return;
      element.textContent = message;
      element.className = `form-text mt-2 ${kind === "err" ? "text-danger" : kind === "ok" ? "text-success" : ""}`;
    }

    function clientesTag(texto, tom, icone = "") {
      return `<span class="cliente-tag" data-tom="${escapeHtml(tom)}">${icone ? `<i class="bi ${escapeHtml(icone)}" aria-hidden="true"></i>` : ""}${escapeHtml(texto)}</span>`;
    }

    function clientesFiltrosAtivos() {
      return Array.from(clientesUi.filtros);
    }

    function atualizarEscopoClientes(texto = "") {
      const alvo = document.getElementById("clientesEscopo");
      if (!alvo) return;
      if (texto) { alvo.textContent = texto; return; }
      const panel = state.panel || {};
      alvo.textContent = panel.isAdmin ? "Acesso administrativo" : (panel.sellerScopes || []).length ? `Carteira: ${(panel.sellerScopes || []).join(", ")}` : "Carteira não configurada";
    }

    async function buscarClientes({ automatico = false } = {}) {
      const busca = (document.getElementById("clientesBusca")?.value || "").trim();
      const filial = document.getElementById("clientesFilial")?.value || "";
      const botao = document.getElementById("clientesBuscarBtn");
      if (busca.length < 2) {
        if (!automatico) clientesSetStatus("Digite pelo menos 2 caracteres para pesquisar.", "err");
        return;
      }
      if (/^\d+$/.test(busca) && busca.length < 11 && !filial) {
        clientesSetStatus("Para buscar pelo NB, escolha a filial.", automatico ? "" : "err");
        return;
      }
      const sequencia = ++clientesUi.seq;
      if (botao) { botao.disabled = true; botao.innerHTML = '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>Buscando...'; }
      clientesSetStatus("Pesquisando na sua carteira...");
      const params = new URLSearchParams({ busca });
      if (filial) params.set("filial", filial);
      const filtros = clientesFiltrosAtivos();
      if (filtros.length) params.set("filtros", filtros.join(","));
      try {
        const response = await req(`${CONFIG.endpoints.clientes.busca}?${params.toString()}`);
        if (sequencia !== clientesUi.seq) return;
        clientesUi.rows = Array.isArray(response.clientes) ? response.clientes : [];
        if (response.escopo) atualizarEscopoClientes(response.escopo);
        renderClientesResultados(clientesUi.rows);
        const limite = Number(response.limite || 10);
        clientesSetStatus(clientesUi.rows.length
          ? `${clientesUi.rows.length} cliente(s) encontrado(s)${clientesUi.rows.length >= limite ? ` · mostrando os ${limite} primeiros, refine a busca` : ""}.`
          : "Nenhum cliente encontrado na sua carteira com esses critérios.");
      } catch (error) {
        if (sequencia !== clientesUi.seq) return;
        clientesUi.rows = [];
        renderClientesResultados([]);
        clientesSetStatus(error.message || "Não foi possível pesquisar agora.", "err");
      } finally {
        if (sequencia === clientesUi.seq && botao) { botao.disabled = false; botao.innerHTML = '<i class="bi bi-search me-1" aria-hidden="true"></i>Buscar'; }
      }
    }

    function clientesBadgesResultado(item) {
      const tags = [];
      if (item.tem_pendencia) tags.push(clientesTag(`Pendência ${formatMoneyText(item.total_pendente)}`, "warn", "bi-cash-coin"));
      const resumo = item.resumo || {};
      if (resumo.vencidos) tags.push(clientesTag(`${resumo.vencidos} vencido(s)`, "err", "bi-exclamation-octagon"));
      if (resumo.boletos) tags.push(clientesTag(`${resumo.boletos} boleto(s)`, "info", "bi-upc-scan"));
      if (item.tem_comodato) tags.push(clientesTag(`${item.comodatos_pendentes} comodato(s)`, "neutral", "bi-box-seam"));
      return tags.join("");
    }

    function renderClientesResultados(rows) {
      const alvo = document.getElementById("clientesResultados");
      if (!alvo) return;
      if (!rows.length) { alvo.innerHTML = ""; return; }
      alvo.innerHTML = rows.map((item, index) => `<div class="pedido-client-result cliente-resultado">
          <span class="nb mono" title="NB">${escapeHtml(item.cliente)}</span>
          <span class="cliente-resultado-main"><strong>${escapeHtml(item.nome || item.razao_social || "-")}</strong>
            <span class="meta">${escapeHtml(item.cidade || "Sem cidade")} · Filial ${escapeHtml(item.filial)} · Setor ${escapeHtml(clientesChave(item.setor) || "-")} · GV ${escapeHtml(clientesChave(item.gv) || "-")} · Visita ${escapeHtml(item.dia_visita || "-")}</span>
            <span class="meta">${escapeHtml(item.telefone || "Sem telefone")} · ${escapeHtml(item.status || "-")} · Cond. ${escapeHtml(item.cond_pagto || "-")} · Limite ${escapeHtml(item.limite_credito ? formatMoneyText(item.limite_credito) : "-")}</span>
            <span class="cliente-tags">${clientesBadgesResultado(item)}</span></span>
          <button class="btn btn-outline-primary btn-sm cliente-ver-ficha" type="button" data-index="${index}" aria-label="Ver ficha do cliente ${escapeHtml(item.nome || item.cliente)}"><i class="bi bi-person-lines-fill me-1" aria-hidden="true"></i>Ver ficha</button>
        </div>`).join("");
    }

    function abrirFichaCliente(filial, cliente) {
      clientesUi.atual = { filial, cliente };
      abrirFichaBlocos(filial, cliente);
    }

    function clientesUrlPdf(cliente, boleto) {
      return `${CONFIG.endpoints.clientes.ficha}/${encodeURIComponent(cliente.filial)}/${encodeURIComponent(cliente.cliente)}/boletos/${encodeURIComponent(boleto.nosso_numero)}/pdf`;
    }

    function clientesAcoesBoleto(cliente, boleto) {
      if (!boleto) return '<span class="cliente-tag" data-tom="neutral"><i class="bi bi-file-earmark-x" aria-hidden="true"></i>Boleto não importado</span>';
      const copiar = boleto.linha_digitavel
        ? `<button class="btn btn-outline-secondary btn-sm cliente-copiar" type="button" data-linha="${escapeHtml(boleto.linha_digitavel)}" aria-label="Copiar linha digitável do boleto ${escapeHtml(boleto.nosso_numero)}"><i class="bi bi-clipboard me-1" aria-hidden="true"></i>Copiar linha digitável</button>`
        : "";
      return `<div class="cliente-acoes">${copiar}<a class="btn btn-outline-primary btn-sm" href="${escapeHtml(clientesUrlPdf(cliente, boleto))}" target="_blank" rel="noopener" aria-label="Abrir PDF do boleto ${escapeHtml(boleto.nosso_numero)} em nova aba"><i class="bi bi-file-earmark-pdf me-1" aria-hidden="true"></i>Abrir boleto PDF</a></div>`;
    }

    function clientesFonteAviso(fonte) {
      if (!fonte || fonte.disponivel) return "";
      return `<div class="alert alert-warning py-2 mb-2" role="status"><i class="bi bi-database-exclamation me-1" aria-hidden="true"></i>${escapeHtml(fonte.mensagem || "Fonte indisponível.")}</div>`;
    }

    function clientesVazio(texto) {
      return `<div class="pedido-queue-empty"><i class="bi bi-inbox me-1" aria-hidden="true"></i>${escapeHtml(texto)}</div>`;
    }

    async function copiarLinhaDigitavel(botao) {
      const linha = botao.dataset.linha || "";
      const original = botao.innerHTML;
      try {
        if (navigator.clipboard && window.isSecureContext) {
          await navigator.clipboard.writeText(linha);
        } else {
          const area = document.createElement("textarea");
          area.value = linha;
          area.setAttribute("readonly", "");
          area.style.position = "fixed";
          area.style.opacity = "0";
          document.body.appendChild(area);
          area.select();
          const ok = document.execCommand("copy");
          area.remove();
          if (!ok) throw new Error("copy");
        }
        botao.innerHTML = '<i class="bi bi-clipboard-check me-1" aria-hidden="true"></i>Copiada!';
        clientesSetStatus("Linha digitável copiada.", "ok");
      } catch (_) {
        botao.innerHTML = '<i class="bi bi-x-circle me-1" aria-hidden="true"></i>Não copiou';
        clientesSetStatus(`Não consegui copiar automaticamente. Linha digitável: ${linha}`, "err");
      }
      setTimeout(() => { botao.innerHTML = original; }, 2500);
    }

    function setupClientesPanel() {
      const form = document.getElementById("clientesBuscaForm");
      if (!form) return;
      const buscarComAtraso = debounce(() => buscarClientes({ automatico: true }), 450);
      form.addEventListener("submit", event => { event.preventDefault(); buscarClientes(); });
      document.getElementById("clientesBusca")?.addEventListener("input", buscarComAtraso);
      document.getElementById("clientesFilial")?.addEventListener("change", () => buscarClientes({ automatico: true }));
      document.getElementById("clientesAtualizarBtn")?.addEventListener("click", () => buscarClientes({ automatico: true }));
      document.querySelectorAll(".clientes-filtro").forEach(botao => botao.addEventListener("click", () => {
        const filtro = botao.dataset.filtro;
        if (clientesUi.filtros.has(filtro)) clientesUi.filtros.delete(filtro); else clientesUi.filtros.add(filtro);
        botao.setAttribute("aria-pressed", String(clientesUi.filtros.has(filtro)));
        buscarClientes({ automatico: true });
      }));
      document.getElementById("clientesResultados")?.addEventListener("click", event => {
        const botao = event.target.closest(".cliente-ver-ficha");
        if (!botao) return;
        const item = clientesUi.rows[Number(botao.dataset.index)];
        if (item) abrirFichaCliente(item.filial, item.cliente);
      });
    }
