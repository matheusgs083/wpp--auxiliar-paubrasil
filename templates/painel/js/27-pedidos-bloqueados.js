    // Gerencial de pedidos: clientes bloqueados pela 12.06.01 e liberação pelo administrador.
    const pedidoBloqueadosUi = { pagina: 1, paginas: 1, dias: [1, 3, 7], carregado: false };

    function pedidoBloqueadosDataBr(valor) {
      const partes = String(valor || "").split("-");
      return partes.length === 3 ? `${partes[2]}/${partes[1]}` : "-";
    }

    function pedidoBloqueadosDiasTexto(dias) {
      return dias === 1 ? "Só hoje" : `${dias} dias`;
    }

    // Valor da 12.06.01 vem como "1234,56".
    function pedidoBloqueadosValor(valor) {
      return formatPedidoMoney(Number(String(valor || "0").replace(/\./g, "").replace(",", ".")) || 0);
    }

    function pedidoBloqueadosStatus(texto, tipo = "") {
      const alvo = document.getElementById("pedidoBloqueadosStatus");
      if (!alvo) return;
      alvo.textContent = texto || "";
      alvo.classList.toggle("text-danger", tipo === "err");
      alvo.classList.toggle("text-success", tipo === "ok");
    }

    function renderPedidoLiberacoesAtivas(liberacoes) {
      const alvo = document.getElementById("pedidoLiberacoesAtivas");
      if (!alvo) return;
      if (!liberacoes.length) { alvo.innerHTML = ""; return; }
      alvo.innerHTML = `<div class="pedido-liberacoes-ativas"><strong class="small">Liberados agora (${liberacoes.length})</strong><ul>${liberacoes.map(item => `<li><span><strong>${escapeHtml(item.nome || `NB ${item.cliente}`)}</strong> · NB ${escapeHtml(item.cliente)} · filial ${escapeHtml(item.filial)}<br><span class="text-secondary small">Até ${escapeHtml(pedidoBloqueadosDataBr(item.valida_ate))} · por ${escapeHtml(item.liberado_por || "-")} · ${escapeHtml(item.motivo || "")}</span></span><button class="btn btn-sm btn-outline-danger" type="button" data-revogar-filial="${escapeHtml(item.filial)}" data-revogar-cliente="${escapeHtml(item.cliente)}" data-revogar-nome="${escapeHtml(item.nome || "")}">Remover liberação</button></li>`).join("")}</ul></div>`;
    }

    function pedidoBloqueadoAcao(item) {
      if (pedidosUi.config?.liberar_todos_inadimplentes) return '<span class="pedido-liberado-tag"><i class="bi bi-unlock" aria-hidden="true"></i>Liberação geral</span>';
      if (item.liberacao) {
        return `<span class="pedido-liberado-tag"><i class="bi bi-unlock" aria-hidden="true"></i>Liberado até ${escapeHtml(pedidoBloqueadosDataBr(item.liberacao.valida_ate))}</span>`;
      }
      return `<button class="btn btn-sm btn-outline-primary" type="button" data-liberar="${escapeHtml(JSON.stringify({ filial: item.filial, cliente: item.cliente, nome: item.nome }))}"><i class="bi bi-unlock me-1" aria-hidden="true"></i>Liberar</button>`;
    }

    function renderPedidoBloqueados(dados) {
      pedidoBloqueadosUi.dados = dados;
      const tabela = document.getElementById("pedidoBloqueadosTabela");
      const meta = document.getElementById("pedidoBloqueadosMeta");
      const clientes = Array.isArray(dados.clientes) ? dados.clientes : [];
      pedidoBloqueadosUi.pagina = Number(dados.pagina || 1);
      pedidoBloqueadosUi.paginas = Number(dados.paginas || 1);
      if (Array.isArray(dados.dias_permitidos) && dados.dias_permitidos.length) pedidoBloqueadosUi.dias = dados.dias_permitidos;
      if (meta) meta.textContent = `${formatStockNumber(dados.total || 0)} com títulos`;
      if (tabela) {
        tabela.innerHTML = clientes.length
          ? clientes.map(item => `<tr><td><strong>${escapeHtml(item.nome || "-")}</strong><span>NB ${escapeHtml(item.cliente)} · ${escapeHtml(item.filial_nome || `Filial ${item.filial}`)}</span></td><td class="text-end mono">${escapeHtml(String(item.titulos))}</td><td class="text-end mono">${escapeHtml(pedidoBloqueadosValor(item.total_pendente))}</td><td class="text-end">${pedidoBloqueadoAcao(item)}</td></tr>`).join("")
          : '<tr><td colspan="4" class="text-secondary text-center py-4">Nenhum cliente bloqueado neste filtro.</td></tr>';
      }
      const anterior = document.getElementById("pedidoBloqueadosAnterior");
      const proxima = document.getElementById("pedidoBloqueadosProxima");
      if (anterior) anterior.disabled = pedidoBloqueadosUi.pagina <= 1;
      if (proxima) proxima.disabled = pedidoBloqueadosUi.pagina >= pedidoBloqueadosUi.paginas;
      // Com uma página só, os botões de página nem aparecem.
      const paginas = anterior?.parentElement;
      if (paginas) paginas.hidden = pedidoBloqueadosUi.paginas <= 1;
      renderPedidoLiberacoesAtivas(Array.isArray(dados.liberacoes) ? dados.liberacoes : []);
      const filial = document.getElementById("pedidoBloqueadosFilial");
      if (filial && !pedidoBloqueadosUi.carregado && Array.isArray(dados.filiais)) {
        filial.innerHTML = '<option value="">Todas</option>' + dados.filiais.map(item => `<option value="${escapeHtml(item.codigo)}">${escapeHtml(item.nome)}</option>`).join("");
        pedidoBloqueadosUi.carregado = true;
      }
    }

    async function syncPedidoBloqueados({ silent = false, pagina = null } = {}) {
      if (!(state.panel && state.panel.isAdmin)) return false;
      const query = new URLSearchParams({ pagina: String(pagina || pedidoBloqueadosUi.pagina || 1) });
      const filial = document.getElementById("pedidoBloqueadosFilial")?.value || "";
      const busca = (document.getElementById("pedidoBloqueadosBusca")?.value || "").trim();
      if (filial) query.set("filial", filial);
      if (busca) query.set("busca", busca);
      if (!silent) pedidoBloqueadosStatus("Carregando...");
      try {
        renderPedidoBloqueados(await req(`/api/admin/pedidos/gerencial/bloqueados?${query}`, { timeoutMs: 30000 }));
        if (!silent) pedidoBloqueadosStatus("");
        return true;
      } catch (error) {
        pedidoBloqueadosStatus(error.message || "Não foi possível carregar os clientes bloqueados.", "err");
        return false;
      }
    }

    function abrirLiberacaoPedido(botao) {
      let cliente;
      try { cliente = JSON.parse(botao.dataset.liberar || "{}"); } catch (_err) { return; }
      const celula = botao.closest("td");
      if (!celula) return;
      const opcoes = pedidoBloqueadosUi.dias.map(dias => `<option value="${dias}">${pedidoBloqueadosDiasTexto(Number(dias))}</option>`).join("");
      celula.innerHTML = `<form class="pedido-liberar-form" data-cliente="${escapeHtml(JSON.stringify(cliente))}"><select class="form-select form-select-sm" name="dias" aria-label="Por quanto tempo">${opcoes}</select><input class="form-control form-control-sm" name="motivo" maxlength="200" required placeholder="Motivo (ex.: acordo de pagamento)" aria-label="Motivo da liberação"><button class="btn btn-sm btn-primary" type="submit">Confirmar</button><button class="btn btn-sm btn-outline-secondary" type="button" data-cancelar-liberacao>Cancelar</button></form>`;
      celula.querySelector('input[name="motivo"]')?.focus();
    }

    async function confirmarLiberacaoPedido(form) {
      let cliente;
      try { cliente = JSON.parse(form.dataset.cliente || "{}"); } catch (_err) { return; }
      const motivo = (form.elements.motivo.value || "").trim();
      if (motivo.length < 3) { form.elements.motivo.focus(); pedidoBloqueadosStatus("Escreva o motivo da liberação.", "err"); return; }
      form.querySelectorAll("button, input, select").forEach(item => { item.disabled = true; });
      try {
        const resposta = await req("/api/admin/pedidos/gerencial/liberacoes", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...cliente, motivo, dias: Number(form.elements.dias.value || 1) })
        });
        pedidoBloqueadosStatus(`${cliente.nome || `NB ${cliente.cliente}`} liberado até ${pedidoBloqueadosDataBr(resposta.liberacao?.valida_ate)}.`, "ok");
        addLog(`Cliente ${cliente.cliente} (filial ${cliente.filial}) liberado para pedido.`, "ok");
      } catch (error) {
        pedidoBloqueadosStatus(error.message || "Não foi possível liberar o cliente.", "err");
      }
      await syncPedidoBloqueados({ silent: true });
    }

    async function revogarLiberacaoPedido(botao) {
      const nome = botao.dataset.revogarNome || `NB ${botao.dataset.revogarCliente}`;
      if (!await askConfirmation(`Remover a liberação de ${nome}? Os vendedores voltam a não conseguir digitar pedido para este cliente enquanto houver título em aberto.`)) return;
      botao.disabled = true;
      try {
        await req(`/api/admin/pedidos/gerencial/liberacoes/${encodeURIComponent(botao.dataset.revogarFilial)}/${encodeURIComponent(botao.dataset.revogarCliente)}`, { method: "DELETE" });
        pedidoBloqueadosStatus(`Liberação de ${nome} removida.`, "ok");
      } catch (error) {
        pedidoBloqueadosStatus(error.message || "Não foi possível remover a liberação.", "err");
      }
      await syncPedidoBloqueados({ silent: true });
    }

    function setupPedidoBloqueados() {
      const card = document.getElementById("pedidoBloqueadosCard");
      if (!card) return;
      document.getElementById("pedidoBloqueadosForm")?.addEventListener("submit", event => { event.preventDefault(); syncPedidoBloqueados({ pagina: 1 }); });
      document.getElementById("pedidoBloqueadosFilial")?.addEventListener("change", () => syncPedidoBloqueados({ pagina: 1 }));
      document.getElementById("pedidoBloqueadosAnterior")?.addEventListener("click", () => syncPedidoBloqueados({ pagina: Math.max(1, pedidoBloqueadosUi.pagina - 1) }));
      document.getElementById("pedidoBloqueadosProxima")?.addEventListener("click", () => syncPedidoBloqueados({ pagina: pedidoBloqueadosUi.pagina + 1 }));
      card.addEventListener("click", event => {
        const liberar = event.target.closest("[data-liberar]");
        if (liberar) { abrirLiberacaoPedido(liberar); return; }
        if (event.target.closest("[data-cancelar-liberacao]")) { syncPedidoBloqueados({ silent: true }); return; }
        const revogar = event.target.closest("[data-revogar-cliente]");
        if (revogar) revogarLiberacaoPedido(revogar);
      });
      card.addEventListener("submit", event => {
        const form = event.target.closest(".pedido-liberar-form");
        if (!form) return;
        event.preventDefault();
        confirmarLiberacaoPedido(form);
      });
    }
