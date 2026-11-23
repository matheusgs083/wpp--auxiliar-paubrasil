    // Aba Clientes: pesquisa na carteira autorizada e ficha com 12.06.01, 03.02.06 e 02.02.20.
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

    async function abrirFichaCliente(filial, cliente) {
      const wrap = document.getElementById("clientesFichaWrap");
      const alvo = document.getElementById("clientesFicha");
      if (!wrap || !alvo) return;
      const sequencia = ++clientesUi.fichaSeq;
      clientesUi.atual = { filial, cliente };
      wrap.hidden = false;
      alvo.innerHTML = '<div class="text-secondary py-3" role="status"><span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>Carregando a ficha do cliente...</div>';
      wrap.scrollIntoView({ behavior: "smooth", block: "start" });
      try {
        const ficha = await req(`${CONFIG.endpoints.clientes.ficha}/${encodeURIComponent(filial)}/${encodeURIComponent(cliente)}`);
        if (sequencia !== clientesUi.fichaSeq) return;
        clientesUi.ficha = ficha;
        renderFichaCliente(ficha);
      } catch (error) {
        if (sequencia !== clientesUi.fichaSeq) return;
        clientesUi.ficha = null;
        alvo.innerHTML = `<div class="alert alert-danger mb-0" role="alert"><i class="bi bi-shield-exclamation me-2" aria-hidden="true"></i>${escapeHtml(error.message || "Não foi possível abrir a ficha.")}</div>`;
      }
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

    function renderFichaCliente(ficha) {
      const alvo = document.getElementById("clientesFicha");
      if (!alvo) return;
      const c = ficha.cliente || {};
      const k = ficha.kpis || {};
      const contato = [
        c.telefone_whatsapp ? `<a class="btn btn-success btn-sm" href="https://wa.me/${encodeURIComponent(c.telefone_whatsapp)}" target="_blank" rel="noopener" aria-label="Abrir conversa no WhatsApp com ${escapeHtml(c.nome || "o cliente")}"><i class="bi bi-whatsapp me-1" aria-hidden="true"></i>WhatsApp</a>` : "",
        c.telefone_discagem ? `<a class="btn btn-outline-secondary btn-sm" href="tel:${encodeURIComponent(c.telefone_discagem)}" aria-label="Ligar para ${escapeHtml(c.nome || "o cliente")}"><i class="bi bi-telephone me-1" aria-hidden="true"></i>Ligar</a>` : ""
      ].join("");
      const fatos = [["NB", c.cliente], ["Filial", c.filial], ["Setor / RN", clientesChave(c.setor) || "-"], ["GV", clientesChave(c.gv) || "-"], ["Telefone", c.telefone || "-"], ["Dia de visita", c.dia_visita || "-"], ["Cidade", c.cidade || "-"], ["Status", c.status || "-"]];
      const kpis = [
        ["Total pendente", formatMoneyText(k.total_pendente || "0"), k.titulos ? `${k.titulos} título(s)` : "Sem títulos"],
        ["Títulos vencidos", String(k.titulos_vencidos || 0), k.titulos_vencidos ? formatMoneyText(k.total_vencido || "0") : (k.proximo_vencimento ? `Próximo: ${k.proximo_vencimento}` : "—")],
        ["Boletos disponíveis", String(k.boletos_disponiveis || 0), "03.02.06"],
        ["Comodatos", String(k.comodatos || 0), "02.02.20"],
        ["Saldo de material", String(k.saldo_material || "0"), "unidades"]
      ];
      const aba = clientesUi.aba || "financeiro";
      const abas = [["financeiro", "Financeiro", "bi-cash-stack"], ["boletos", "Boletos", "bi-upc-scan"], ["comodatos", "Comodatos", "bi-box-seam"], ["cadastro", "Cadastro", "bi-person-vcard"]];
      alvo.innerHTML = `<div class="pedido-client-card">
          <div class="pedido-client-head"><div class="pedido-client-title"><h3>${escapeHtml(c.nome || "Cliente")}</h3><p>${escapeHtml(c.razao_social || "")}</p></div><div class="cliente-acoes">${contato}</div></div>
          <div class="pedido-client-facts">${fatos.map(([label, value]) => `<div class="pedido-client-fact"><span class="label">${escapeHtml(label)}</span><span class="value">${escapeHtml(String(value))}</span></div>`).join("")}</div>
        </div>
        <div class="pedido-manager-grid clientes-kpis mt-3">${kpis.map(([label, value, nota]) => `<div class="pedido-manager-kpi"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small class="text-secondary">${escapeHtml(nota)}</small></div>`).join("")}</div>
        <nav class="pedido-subtabs mt-3" role="tablist" aria-label="Ficha do cliente">${abas.map(([id, rotulo, icone]) => `<button class="pedido-subtab${id === aba ? " is-active" : ""}" type="button" role="tab" id="clienteAba-${id}" aria-controls="clientePainel-${id}" aria-selected="${id === aba}" data-cliente-aba="${id}"><i class="bi ${icone} me-1" aria-hidden="true"></i>${rotulo}</button>`).join("")}</nav>
        ${abas.map(([id]) => `<div class="mt-3" role="tabpanel" id="clientePainel-${id}" aria-labelledby="clienteAba-${id}" ${id === aba ? "" : "hidden"}>${clientesPainel(id, ficha)}</div>`).join("")}`;
    }

    function clientesPainel(id, ficha) {
      const c = ficha.cliente || {};
      if (id === "financeiro") {
        const fin = ficha.financeiro || {};
        const titulos = fin.titulos || [];
        const tabela = titulos.length ? `<div class="table-responsive"><table class="table table-sm align-middle mb-0 cliente-tabela"><thead><tr><th>NF</th><th>Emissão</th><th>Vencimento</th><th class="text-end">Dias</th><th>Situação</th><th class="text-end">Original</th><th class="text-end">Pendente</th><th class="text-end">Corrigido</th><th>Boleto</th></tr></thead><tbody>${titulos.map(t => {
          const s = CLIENTES_SITUACAO[t.situacao] || CLIENTES_SITUACAO.sem_data;
          return `<tr data-situacao="${escapeHtml(t.situacao)}"><td class="mono">${escapeHtml(t.nota_fiscal || "-")}</td><td>${escapeHtml(t.emissao || "-")}</td><td>${escapeHtml(t.vencimento || "-")}</td><td class="text-end">${t.dias === null || t.dias === undefined ? "—" : escapeHtml(String(t.dias))}</td><td>${clientesTag(s.rotulo, s.tom, s.icone)}</td><td class="text-end">${escapeHtml(formatMoneyText(t.valor_original))}</td><td class="text-end fw-semibold">${escapeHtml(formatMoneyText(t.valor_pendente))}</td><td class="text-end">${escapeHtml(formatMoneyText(t.valor_corrigido))}</td><td>${clientesAcoesBoleto(c, t.boleto)}</td></tr>`;
        }).join("")}</tbody></table></div>` : (fin.fonte && !fin.fonte.disponivel ? "" : clientesVazio("Nenhum título pendente na 12.06.01 para este cliente."));
        return `${clientesFonteAviso(fin.fonte)}${clientesFonteAviso((ficha.boletos || {}).fonte)}${tabela}
          <div class="cliente-acoes-financeiras mt-3"><strong><i class="bi bi-wallet2 me-1" aria-hidden="true"></i>Ações financeiras</strong><span>Copie a linha digitável ou abra o PDF em cada título acima. Pagamento por PIX ainda não está disponível nesta tela.</span></div>`;
      }
      if (id === "boletos") {
        const bol = ficha.boletos || {};
        const itens = bol.itens || [];
        if (!itens.length) return clientesFonteAviso(bol.fonte) || clientesVazio("Nenhum boleto importado da 03.02.06 para este cliente.");
        return `<div class="table-responsive"><table class="table table-sm align-middle mb-0 cliente-tabela"><thead><tr><th>Nosso número</th><th>NF / documento</th><th>Vencimento</th><th class="text-end">Valor</th><th>Linha digitável</th><th>Ações</th></tr></thead><tbody>${itens.map(b => `<tr><td class="mono">${escapeHtml(b.nosso_numero)}</td><td class="mono">${escapeHtml(b.nota_fiscal || b.num_documento || "-")}</td><td>${escapeHtml(b.vencimento || "-")}</td><td class="text-end">${escapeHtml(formatMoneyText(b.valor))}</td><td class="mono cliente-linha">${escapeHtml(b.linha_digitavel || "-")}</td><td>${clientesAcoesBoleto(c, b)}</td></tr>`).join("")}</tbody></table></div>`;
      }
      if (id === "comodatos") {
        const com = ficha.comodatos || {};
        const itens = com.itens || [];
        if (!itens.length) return clientesFonteAviso(com.fonte) || clientesVazio("Este cliente não tem comodatos na 02.02.20.");
        return `<div class="table-responsive"><table class="table table-sm align-middle mb-0 cliente-tabela"><thead><tr><th>Comodato</th><th>Material</th><th>Subtipo</th><th class="text-end">Saldo</th></tr></thead><tbody>${itens.map(i => `<tr><td class="mono">${escapeHtml(i.nro_comodato || "-")}</td><td>${escapeHtml(i.material || "-")}</td><td>${escapeHtml(i.sub_tipo || "-")}</td><td class="text-end">${escapeHtml(i.saldo || "0")}</td></tr>`).join("")}</tbody><tfoot><tr><th colspan="3">${itens.length} comodato(s)</th><th class="text-end">${escapeHtml(com.saldo_total || "0")}</th></tr></tfoot></table></div>`;
      }
      const cad = c.cadastro || {};
      const fatos = [["Razão social", c.razao_social], ["Nome fantasia", c.nome], ["CPF/CNPJ", cad.documento], ["Condição de pagamento", c.cond_pagto], ["Limite de crédito", c.limite_credito ? formatMoneyText(c.limite_credito) : ""], ["Status", c.status], ["Endereço", cad.endereco], ["Bairro", cad.bairro], ["Cidade / UF", cad.cidade_uf || c.cidade], ["CEP", cad.cep], ["E-mail", cad.email], ["Base atualizada", c.atualizado_em]];
      return `<div class="pedido-client-card"><div class="pedido-client-facts">${fatos.map(([label, value]) => `<div class="pedido-client-fact"><span class="label">${escapeHtml(label)}</span><span class="value">${escapeHtml(String(value || "-"))}</span></div>`).join("")}</div></div>`;
    }

    function selecionarAbaCliente(id) {
      clientesUi.aba = id;
      document.querySelectorAll("[data-cliente-aba]").forEach(botao => {
        const ativa = botao.dataset.clienteAba === id;
        botao.classList.toggle("is-active", ativa);
        botao.setAttribute("aria-selected", String(ativa));
      });
      document.querySelectorAll('[id^="clientePainel-"]').forEach(painel => { painel.hidden = painel.id !== `clientePainel-${id}`; });
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
      document.getElementById("clientesAtualizarBtn")?.addEventListener("click", () => {
        buscarClientes({ automatico: true });
        if (clientesUi.atual) abrirFichaCliente(clientesUi.atual.filial, clientesUi.atual.cliente);
      });
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
      document.getElementById("clientesFicha")?.addEventListener("click", event => {
        const aba = event.target.closest("[data-cliente-aba]");
        if (aba) { selecionarAbaCliente(aba.dataset.clienteAba); return; }
        const copiar = event.target.closest(".cliente-copiar");
        if (copiar) copiarLinhaDigitavel(copiar);
      });
    }
