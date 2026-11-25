    async function carregarGerentesVendas() {
      const status = document.getElementById("gerentesStatus");
      try {
        const dados = await req("/api/admin/gerentes-vendas");
        const lista = document.getElementById("gerentesLista");
        lista.innerHTML = (dados.gerentes || []).map(item => `<tr><td>${escapeHtml((dados.filiais_nomes || {})[item.filial] || `Filial ${item.filial}`)}</td><td>GV ${escapeHtml(item.gv)}</td><td>${escapeHtml(String(item.setores))}</td><td><input class="form-control form-control-sm" maxlength="60" list="gerentesSugestoes" data-gv-chave="${escapeHtml(item.chave)}" value="${escapeHtml(item.nome)}" aria-label="Nome do GV ${escapeHtml(item.gv)} da filial ${escapeHtml(item.filial)}"></td></tr>`).join("");
        const nomes = [...new Set((dados.gerentes || []).map(item => item.nome).filter(Boolean))];
        document.getElementById("gerentesSugestoes").innerHTML = nomes.map(nome => `<option value="${escapeHtml(nome)}"></option>`).join("");
        document.getElementById("gerentesSalvar").hidden = false;
        status.textContent = "";
      } catch (error) { status.textContent = error.message || "Não foi possível carregar os gerentes."; }
    }
    document.getElementById("gerentesCarregar")?.addEventListener("click", carregarGerentesVendas);
    document.getElementById("gerentesLista")?.addEventListener("change", () => {
      const nomes = [...new Set([...document.querySelectorAll("[data-gv-chave]")].map(input => input.value.trim()).filter(Boolean))];
      document.getElementById("gerentesSugestoes").innerHTML = nomes.map(nome => `<option value="${escapeHtml(nome)}"></option>`).join("");
    });
    document.getElementById("gerentesSalvar")?.addEventListener("click", async () => {
      const status = document.getElementById("gerentesStatus");
      const nomes = Object.fromEntries([...document.querySelectorAll("[data-gv-chave]")].map(input => [input.dataset.gvChave, input.value.trim()]));
      try {
        await req("/api/admin/gerentes-vendas", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ nomes }) });
        rotaUi.opcoes = null;
        status.textContent = "Nomes salvos.";
      } catch (error) { status.textContent = error.message || "Não foi possível salvar."; }
    });
