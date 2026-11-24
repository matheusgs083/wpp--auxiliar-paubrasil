    // Aba Crítica, bloco "Buscar crítica no Cora": pede a Crítica ao worker e acompanha até importar.
    // (A aba "Gerar crítica" da área Vendedor é outra coisa: o PDF da carteira, em 26-critica-carteira.js.)
    const gerarCriticaUi = { timer: null, seq: 0, enviando: false, ultimoAtivo: "" };
    const GERAR_CRITICA_INTERVALO_MS = 10000;

    function gerarCriticaHora(valor) {
      return valor ? formatDateTime(valor) : "-";
    }

    function gerarCriticaDataBr(valor) {
      const partes = String(valor || "").split("-");
      return partes.length === 3 ? `${partes[2]}/${partes[1]}/${partes[0]}` : "-";
    }

    function gerarCriticaPill(item) {
      return `<span class="promax-status ${promaxStatusClass(item.status)}">${escapeHtml(item.situacao || "-")}</span>`;
    }

    function gerarCriticaResultado(item) {
      if (item.erro) return `<span class="text-danger small">${escapeHtml(item.erro)}</span>`;
      if (item.ativo) return '<span class="text-secondary small">Aguardando o worker…</span>';
      const partes = [];
      if (Array.isArray(item.filiais) && item.filiais.length) partes.push(`Operações ${item.filiais.join(", ")}`);
      if (item.linhas !== null && item.linhas !== undefined && item.linhas !== "") partes.push(`${Number(item.linhas).toLocaleString("pt-BR")} linhas`);
      if (item.aviso) partes.push(`Aviso: ${item.aviso}`);
      return `<span class="small">${escapeHtml(partes.join(" · ") || "-")}</span>`;
    }

    function renderGerarCriticaAtual(dados) {
      const alvo = document.getElementById("gerarCriticaAtual");
      if (!alvo) return;
      const ativo = dados.em_andamento;
      const ultimo = (dados.historico || [])[0];
      if (ativo) {
        const passo = ativo.status === "running"
          ? `Gerando desde ${gerarCriticaHora(ativo.iniciado_em)}.`
          : `Na fila desde ${gerarCriticaHora(ativo.criado_em)}. Começa assim que o worker pegar.`;
        alvo.innerHTML = `<div class="gerar-critica-cartao"><div class="d-flex flex-wrap align-items-center gap-2">${gerarCriticaPill(ativo)}<strong>Crítica de ${escapeHtml(gerarCriticaDataBr(ativo.data_referencia))}</strong></div><div class="small text-secondary mt-1"><span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>${escapeHtml(passo)} Esta tela se atualiza sozinha.</div></div>`;
        return;
      }
      if (!ultimo) {
        alvo.innerHTML = '<div class="small text-secondary">Nenhuma busca no Cora feita por aqui ainda.</div>';
        return;
      }
      const concluiu = ultimo.status === "success" || ultimo.status === "partial_success";
      const link = concluiu
        ? '<button class="btn btn-link btn-sm p-0 ms-1" type="button" data-gerar-critica-ver>Atualizar os totais</button>'
        : "";
      alvo.innerHTML = `<div class="gerar-critica-cartao"><div class="d-flex flex-wrap align-items-center gap-2">${gerarCriticaPill(ultimo)}<strong>Última: crítica de ${escapeHtml(gerarCriticaDataBr(ultimo.data_referencia))}</strong><span class="small text-secondary">terminou ${escapeHtml(gerarCriticaHora(ultimo.finalizado_em))}</span></div><div class="mt-1">${gerarCriticaResultado(ultimo)}${link}</div></div>`;
    }

    function renderGerarCriticaHistorico(historico) {
      const corpo = document.getElementById("gerarCriticaHistorico");
      if (!corpo) return;
      if (!historico.length) {
        corpo.innerHTML = '<tr><td colspan="5" class="text-secondary small py-3 text-center">Nenhuma busca ainda.</td></tr>';
        return;
      }
      corpo.innerHTML = historico.map(item => `<tr><td data-label="Pedido em" class="mono small">${escapeHtml(gerarCriticaHora(item.criado_em))}</td><td data-label="Data" class="mono small">${escapeHtml(gerarCriticaDataBr(item.data_referencia))}</td><td data-label="Situação">${gerarCriticaPill(item)}</td><td data-label="Resultado">${gerarCriticaResultado(item)}</td><td data-label="Quem pediu" class="small">${escapeHtml(item.criado_por || "-")}</td></tr>`).join("");
    }

    function agendarGerarCritica(ativo) {
      window.clearTimeout(gerarCriticaUi.timer);
      gerarCriticaUi.timer = null;
      if (!ativo) return;
      gerarCriticaUi.timer = window.setTimeout(() => {
        if (currentActiveTabId() === "criticaTab") syncGerarCritica({ silent: true });
        else agendarGerarCritica(true);
      }, GERAR_CRITICA_INTERVALO_MS);
    }

    async function syncGerarCritica({ silent = false } = {}) {
      if (!(state.panel && state.panel.canViewCritica)) return;
      const sequencia = ++gerarCriticaUi.seq;
      try {
        const dados = await req(CONFIG.endpoints.gerarCritica, { timeoutMs: 20000 });
        if (sequencia !== gerarCriticaUi.seq) return;
        const aviso = document.getElementById("gerarCriticaFilaPausada");
        if (aviso) {
          aviso.hidden = !dados.fila_pausada;
          aviso.textContent = dados.fila_pausada
            ? `A fila do worker está pausada${dados.motivo_pausa ? ` (${dados.motivo_pausa})` : ""}. O pedido fica aguardando até alguém retomar na aba Promax.`
            : "";
        }
        const campoData = document.getElementById("gerarCriticaData");
        if (campoData && dados.hoje) {
          campoData.max = dados.hoje;
          if (!campoData.value) campoData.value = dados.hoje;
        }
        const ativo = dados.em_andamento;
        const botao = document.getElementById("gerarCriticaBtn");
        if (botao) botao.disabled = Boolean(ativo) || gerarCriticaUi.enviando;
        if (gerarCriticaUi.ultimoAtivo && !ativo) {
          const fim = (dados.historico || []).find(item => item.id === gerarCriticaUi.ultimoAtivo);
          if (fim) addLog(`Crítica: ${fim.situacao}.`, fim.status === "success" ? "ok" : fim.status === "failed" ? "err" : "warn");
        }
        gerarCriticaUi.ultimoAtivo = ativo ? ativo.id : "";
        renderGerarCriticaAtual(dados);
        renderGerarCriticaHistorico(dados.historico || []);
        agendarGerarCritica(Boolean(ativo));
      } catch (err) {
        if (!silent) addLog(`Falha ao consultar a geração da crítica: ${err.message}`, "err");
        const alvo = document.getElementById("gerarCriticaAtual");
        if (alvo) alvo.innerHTML = `<div class="small text-danger">${escapeHtml(err.message || "Não consegui consultar a situação.")}</div>`;
        agendarGerarCritica(Boolean(gerarCriticaUi.ultimoAtivo));
      }
    }

    async function gerarCriticaAgora() {
      const data = document.getElementById("gerarCriticaData")?.value || "";
      const confirmado = await askConfirmation(`Buscar a crítica de ${gerarCriticaDataBr(data)} no Cora agora? Todas as operações serão reimportadas.`);
      if (!confirmado) return;
      const botao = document.getElementById("gerarCriticaBtn");
      gerarCriticaUi.enviando = true;
      if (botao) botao.disabled = true;
      try {
        const resposta = await req(CONFIG.endpoints.gerarCritica, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data ? { data } : {}),
          timeoutMs: 30000
        });
        addLog(resposta && resposta.ja_na_fila ? "Já existe uma busca da crítica em andamento; acompanhando a mesma." : "Busca da crítica no Cora pedida.", "ok");
      } catch (err) {
        addLog(`Falha ao pedir a crítica: ${err.message}`, "err");
      } finally {
        gerarCriticaUi.enviando = false;
        await syncGerarCritica({ silent: true });
      }
    }

    function setupGerarCriticaPanel() {
      document.getElementById("gerarCriticaBtn")?.addEventListener("click", gerarCriticaAgora);
      document.getElementById("gerarCriticaAtualizarBtn")?.addEventListener("click", () => syncGerarCritica());
      document.getElementById("gerarCriticaAtual")?.addEventListener("click", event => {
        if (event.target.closest("[data-gerar-critica-ver]")) syncCriticaDashboard({ silent: false });
      });
    }
