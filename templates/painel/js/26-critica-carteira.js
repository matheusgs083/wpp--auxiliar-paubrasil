    // Aba "Gerar crítica" (área Vendedor): PDFs da crítica no recorte da carteira.
    // A lista mostra só o que o usuário pode baixar (GV, carteira inteira, cada setor);
    // o servidor confere a carteira de novo em cada download.
    const criticaCarteiraUi = { seq: 0, baixando: false, filial: "", ultimaData: "" };
    const CRITICA_CARTEIRA_BUSCA_A_PARTIR = 10;

    function criticaCarteiraDataBr(valor) {
      const partes = String(valor || "").split("-");
      return partes.length === 3 ? `${partes[2]}/${partes[1]}/${partes[0]}` : "";
    }

    // Diz antes do download de que dia sai a crítica: a escolhida ou a mais recente.
    function renderCriticaCarteiraData() {
      const alvo = document.getElementById("criticaCarteiraDataInfo");
      if (!alvo) return;
      const escolhida = document.getElementById("criticaCarteiraData")?.value || "";
      if (escolhida) alvo.textContent = `Crítica de ${criticaCarteiraDataBr(escolhida)}`;
      else if (criticaCarteiraUi.ultimaData) alvo.textContent = `Crítica de ${criticaCarteiraDataBr(criticaCarteiraUi.ultimaData)} (a mais recente)`;
      else alvo.textContent = criticaCarteiraUi.filial ? "Ainda não há crítica importada para a sua carteira." : "";
    }

    function filtrarCriticaCarteira() {
      const termo = (document.getElementById("criticaCarteiraBusca")?.value || "").trim().toLowerCase();
      document.querySelectorAll("#criticaCarteiraLista .crit-item").forEach(item => {
        item.hidden = Boolean(termo) && !item.dataset.busca.includes(termo);
      });
    }

    function criticaCarteiraStatus(texto, tipo = "") {
      const alvo = document.getElementById("criticaCarteiraStatus");
      if (!alvo) return;
      alvo.textContent = texto || "";
      alvo.classList.toggle("text-danger", tipo === "err");
      alvo.classList.toggle("text-success", tipo === "ok");
    }

    // Só o relatório principal do perfil leva o azul cheio; os demais ficam em contorno.
    function criticaCarteiraItem({ icone, titulo, detalhe, params, resumo = true, principal = false }) {
      const dados = escapeHtml(JSON.stringify(params));
      const botaoResumo = resumo
        ? `<button class="btn btn-sm ${principal ? "btn-outline-primary" : "btn-outline-secondary"}" type="button" data-critica-pdf="${dados}" data-resumo="1" aria-label="Baixar resumo: ${escapeHtml(titulo)}"><i class="bi bi-list-check me-1" aria-hidden="true"></i>Resumo</button>`
        : "";
      const busca = escapeHtml(`${titulo} ${detalhe || ""}`.toLowerCase());
      return `<li class="crit-item" data-busca="${busca}"><span class="crit-icone" aria-hidden="true"><i class="bi ${icone}"></i></span><div class="crit-texto"><strong>${escapeHtml(titulo)}</strong>${detalhe ? `<span>${escapeHtml(detalhe)}</span>` : ""}</div><div class="crit-acoes"><button class="btn btn-sm ${principal ? "btn-primary" : "btn-outline-primary"}" type="button" data-critica-pdf="${dados}" aria-label="Baixar PDF: ${escapeHtml(titulo)}"><i class="bi bi-file-earmark-pdf me-1" aria-hidden="true"></i>Baixar PDF</button>${botaoResumo}</div></li>`;
    }

    function renderCriticaCarteiraLista(dados) {
      const lista = document.getElementById("criticaCarteiraLista");
      if (!lista) return;
      const filial = dados.filial || "";
      if (!filial) {
        lista.innerHTML = `<li class="crit-vazio">${(dados.filiais || []).length ? "Escolha a filial para ver os relatórios." : "Sua carteira ainda não tem filial liberada."}</li>`;
        return;
      }
      const setores = Array.isArray(dados.setores) ? dados.setores : [];
      const gvs = Array.isArray(dados.gvs) ? dados.gvs : [];
      const nomeFilial = ((dados.filiais || []).find(item => item.codigo === filial) || {}).nome || `Filial ${filial}`;
      const partes = [];
      // Vendedor com um setor só: uma linha direta, sem título de grupo nem GV.
      if (setores.length === 1 && !gvs.length) {
        partes.push(criticaCarteiraItem({ icone: "bi-person-badge", titulo: `Setor ${setores[0].codigo}`, detalhe: nomeFilial, params: { filial, setor: setores[0].codigo }, principal: true }));
      } else {
        // O principal é o mais amplo que o perfil tem: o GV do gerente, senão a carteira.
        if (gvs.length) {
          partes.push('<li class="crit-grupo">Gerente de vendas</li>');
          gvs.forEach((item, indice) => partes.push(criticaCarteiraItem({
            icone: "bi-people", titulo: `Crítica do GV ${item.gv}`,
            detalhe: item.setores ? `Resumo por setor · ${item.setores} ${item.setores === 1 ? "setor" : "setores"}` : "Resumo por setor do gerente",
            params: { filial, gv: item.gv }, resumo: false, principal: gvs.length === 1 && indice === 0
          })));
        }
        if (setores.length > 1) {
          partes.push('<li class="crit-grupo">Carteira</li>');
          partes.push(criticaCarteiraItem({
            icone: "bi-buildings",
            titulo: dados.pode_filial_inteira ? `${nomeFilial}: todos os setores` : "Toda a minha carteira",
            detalhe: `${setores.length} setores juntos em um PDF`,
            params: { filial }, principal: gvs.length !== 1
          }));
        }
        if (setores.length) {
          partes.push(`<li class="crit-grupo">${setores.length === 1 ? "Setor" : "Por setor"}</li>`);
          setores.forEach(item => partes.push(criticaCarteiraItem({
            icone: "bi-person-badge", titulo: `Setor ${item.codigo}`,
            detalhe: item.gv ? `GV ${item.gv}` : nomeFilial,
            params: { filial, setor: item.codigo }
          })));
        }
      }
      lista.innerHTML = partes.join("") || '<li class="crit-vazio">Nenhum setor desta filial na sua carteira.</li>';
      const busca = document.getElementById("criticaCarteiraBusca");
      if (busca) {
        busca.hidden = setores.length <= CRITICA_CARTEIRA_BUSCA_A_PARTIR;
        busca.value = "";
      }
    }

    async function syncCriticaCarteira({ silent = false, filial = null } = {}) {
      if (!(state.panel && state.panel.canGerarCritica)) return;
      const sequencia = ++criticaCarteiraUi.seq;
      const query = filial ? `?${new URLSearchParams({ filial })}` : "";
      try {
        const dados = await req(`${CONFIG.endpoints.criticaCarteira.opcoes}${query}`, { timeoutMs: 20000 });
        if (sequencia !== criticaCarteiraUi.seq) return;
        const filiais = Array.isArray(dados.filiais) ? dados.filiais : [];
        const select = document.getElementById("criticaCarteiraFilial");
        if (select && filial === null) {
          select.innerHTML = (filiais.length === 1 ? "" : '<option value="">Escolha a filial</option>')
            + filiais.map(item => `<option value="${escapeHtml(item.codigo)}">${escapeHtml(item.nome)}</option>`).join("");
        }
        if (select) select.value = dados.filial || "";
        // Com uma filial só, o campo nem aparece.
        const wrap = document.getElementById("criticaCarteiraFilialWrap");
        if (wrap) wrap.hidden = filiais.length === 1;
        criticaCarteiraUi.filial = dados.filial || "";
        criticaCarteiraUi.ultimaData = dados.ultima_data || "";
        renderCriticaCarteiraLista(dados);
        renderCriticaCarteiraData();
        if (!silent) criticaCarteiraStatus("");
      } catch (err) {
        if (sequencia !== criticaCarteiraUi.seq) return;
        const lista = document.getElementById("criticaCarteiraLista");
        if (lista) lista.innerHTML = `<li class="crit-vazio text-danger">${escapeHtml(err.message || "Não consegui carregar a sua carteira.")}</li>`;
      }
    }

    async function baixarCriticaCarteira(botao) {
      if (criticaCarteiraUi.baixando) return;
      let params;
      try { params = JSON.parse(botao.dataset.criticaPdf || "{}"); } catch (_err) { return; }
      const resumo = botao.dataset.resumo === "1";
      const data = document.getElementById("criticaCarteiraData")?.value || "";
      const query = new URLSearchParams(params);
      if (data) query.set("date", data);
      if (resumo) query.set("summary_only", "1");
      const rotulo = botao.innerHTML;
      const linha = botao.closest(".crit-item");
      linha?.querySelector(".crit-erro")?.remove();
      criticaCarteiraUi.baixando = true;
      document.querySelectorAll("#criticaCarteiraLista [data-critica-pdf]").forEach(item => { item.disabled = true; });
      botao.innerHTML = '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>Gerando';
      criticaCarteiraStatus("Gerando o PDF. Pode levar alguns segundos.");
      const headers = {};
      if (state.tokens.api) headers["x-api-token"] = state.tokens.api;
      if (state.tokens.admin) headers["x-admin-token"] = state.tokens.admin;
      try {
        const resposta = await fetch(`${CONFIG.api}${CONFIG.endpoints.criticaCarteira.pdf}?${query}`, { headers, credentials: "same-origin" });
        if (!resposta.ok) {
          const erro = await resposta.json().catch(() => null);
          throw new Error(erro && erro.detail ? erro.detail : `Não consegui gerar o PDF (erro ${resposta.status}).`);
        }
        const blob = await resposta.blob();
        const nome = (resposta.headers.get("content-disposition") || "").match(/filename="([^"]+)"/i);
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = nome ? nome[1] : "critica.pdf";
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(link.href);
        // O retorno aparece no próprio botão, que é onde a pessoa está olhando.
        criticaCarteiraStatus(resumo ? "Resumo baixado." : "Crítica baixada.", "ok");
        botao.innerHTML = '<i class="bi bi-check2 me-1" aria-hidden="true"></i>Baixado';
        window.setTimeout(() => { if (!botao.disabled) botao.innerHTML = rotulo; }, 2500);
      } catch (err) {
        botao.innerHTML = rotulo;
        const mensagem = err.message || "Não consegui gerar o PDF.";
        criticaCarteiraStatus(mensagem, "err");
        linha?.insertAdjacentHTML("beforeend", `<p class="crit-erro" role="alert">${escapeHtml(mensagem)}</p>`);
      } finally {
        criticaCarteiraUi.baixando = false;
        document.querySelectorAll("#criticaCarteiraLista [data-critica-pdf]").forEach(item => { item.disabled = false; });
      }
    }

    function setupCriticaCarteira() {
      document.getElementById("criticaCarteiraFilial")?.addEventListener("change", event => {
        criticaCarteiraStatus("");
        const lista = document.getElementById("criticaCarteiraLista");
        if (!event.target.value) { if (lista) lista.innerHTML = '<li class="crit-vazio">Escolha a filial para ver os relatórios.</li>'; return; }
        if (lista) lista.innerHTML = '<li class="crit-vazio">Carregando...</li>';
        syncCriticaCarteira({ silent: true, filial: event.target.value });
      });
      document.getElementById("criticaCarteiraLista")?.addEventListener("click", event => {
        const botao = event.target.closest("[data-critica-pdf]");
        if (botao) baixarCriticaCarteira(botao);
      });
      document.getElementById("criticaCarteiraForm")?.addEventListener("submit", event => event.preventDefault());
      document.getElementById("criticaCarteiraData")?.addEventListener("change", renderCriticaCarteiraData);
      document.getElementById("criticaCarteiraBusca")?.addEventListener("input", filtrarCriticaCarteira);
    }
