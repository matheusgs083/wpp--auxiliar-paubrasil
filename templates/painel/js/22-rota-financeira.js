    // Aba Rota Financeira: fila do dia priorizada pelo risco. Ao tocar num cliente abre a
    // ficha em blocos (24-ficha-cliente.js); as tags vêm da aba Clientes.

    const ROTA_SITUACAO_ROTULO = { todos: "Todos", vencidos: "Vencidos", hoje: "Vence hoje", amanha: "Vence amanhã", dois_dias: "Vence em 2 dias", com_boleto: "Com boleto", sem_boleto: "Sem boleto", sem_giro_vasilhame: "Sem giro de vasilhame", sem_giro_equipamento: "Sem giro de equipamento" };

    function rotaSetStatus(message, kind = "") {
      const element = document.getElementById("rotaStatus");
      if (!element) return;
      element.textContent = message;
      element.className = `form-text mt-2 ${kind === "err" ? "text-danger" : kind === "ok" ? "text-success" : ""}`;
    }

    function rotaOpcoesSelect(select, valores, rotuloTodos, rotular = valor => valor) {
      if (!select) return;
      const atual = select.value;
      select.innerHTML = [`<option value="">${escapeHtml(rotuloTodos)}</option>`, ...valores.map(valor => `<option value="${escapeHtml(valor)}">${escapeHtml(rotular(valor))}</option>`)].join("");
      if (valores.includes(atual)) select.value = atual;
    }

    function rotaRotuloChave(chave) {
      return String(chave || "").replace("_", "-");
    }

    function rotaAtualizarSetores() {
      const opcoes = rotaUi.opcoes || {};
      const filial = document.getElementById("rotaFilial")?.value || "";
      const gv = document.getElementById("rotaGv")?.value || "";
      const setores = (opcoes.setores || []).filter(item => (!filial || item.filial === filial) && (!gv || item.gv === gv)).map(item => item.setor);
      rotaOpcoesSelect(document.getElementById("rotaSetor"), [...new Set(setores)], "Todos", rotaRotuloChave);
    }

    async function carregarOpcoesRota({ forcar = false } = {}) {
      if (rotaUi.opcoes && !forcar) return true;
      try {
        const opcoes = await req(CONFIG.endpoints.rotaFinanceira.opcoes);
        rotaUi.opcoes = opcoes;
        const escopo = document.getElementById("rotaEscopo");
        if (escopo) escopo.textContent = opcoes.escopo || "";
        const dia = document.getElementById("rotaDia");
        if (dia) {
          dia.innerHTML = (opcoes.dias || []).map(item => `<option value="${escapeHtml(item)}">${escapeHtml(diasVisitaTexto(item))}</option>`).join("") || '<option value="">Sem dias de visita</option>';
          if (opcoes.dia_sugerido) dia.value = opcoes.dia_sugerido;
        }
        rotaOpcoesSelect(document.getElementById("rotaFilial"), opcoes.filiais || [], "Todas", filial => (opcoes.filiais_nomes || {})[filial] || `Filial ${filial}`);
        const gvWrap = document.getElementById("rotaGvWrap");
        if (gvWrap) gvWrap.hidden = !opcoes.mostrar_gv;
        rotaOpcoesSelect(document.getElementById("rotaGv"), opcoes.gvs || [], "Todos", rotaRotuloChave);
        rotaAtualizarSetores();
        // Seleção com uma opção só não ajuda: some o campo e a coluna da tabela.
        const umaFilial = (opcoes.filiais || []).length <= 1;
        const umSetor = new Set((opcoes.setores || []).map(item => item.setor)).size <= 1 && (opcoes.gvs || []).length <= 1;
        const filialWrap = document.getElementById("rotaFilialWrap");
        if (filialWrap) filialWrap.hidden = umaFilial;
        const setorWrap = document.getElementById("rotaSetorWrap");
        if (setorWrap) setorWrap.hidden = umSetor;
        const tabela = document.querySelector("#rotaFinanceiraPane .rota-tabela");
        tabela?.classList.toggle("rota-uma-filial", umaFilial);
        tabela?.classList.toggle("rota-um-setor", umSetor);
        return true;
      } catch (error) {
        rotaUi.opcoes = null;
        rotaSetStatus(error.message || "Não foi possível carregar os filtros da rota.", "err");
        const escopo = document.getElementById("rotaEscopo");
        if (escopo) escopo.textContent = "Sem carteira";
        return false;
      }
    }

    async function syncRotaFinanceira({ pagina = 1 } = {}) {
      if (!(await carregarOpcoesRota())) return;
      const dia = document.getElementById("rotaDia")?.value || "";
      if (!dia) { rotaSetStatus("Escolha o dia de visita."); return; }
      const params = new URLSearchParams({ dia, situacao: rotaUi.situacao, pagina: String(pagina) });
      [["filial", "rotaFilial"], ["gv", "rotaGv"], ["setor", "rotaSetor"], ["busca", "rotaBusca"]].forEach(([nome, id]) => {
        const valor = (document.getElementById(id)?.value || "").trim();
        if (valor) params.set(nome, valor);
      });
      const sequencia = ++rotaUi.seq;
      const botao = document.getElementById("rotaAtualizarBtn");
      if (botao) botao.disabled = true;
      rotaSetStatus("Montando a rota...");
      document.getElementById("rotaLista")?.setAttribute("aria-busy", "true");
      try {
        const resposta = await req(`${CONFIG.endpoints.rotaFinanceira.lista}?${params.toString()}`);
        if (sequencia !== rotaUi.seq) return;
        rotaUi.dados = resposta;
        rotaUi.pagina = resposta.pagina || 1;
        renderRotaAvisos(resposta.fontes || {});
        renderRotaKpis(resposta.resumo || {});
        renderRotaContagens(resposta.resumo || {});
        renderRotaLista(resposta.clientes || []);
        renderRotaPaginacao(resposta);
        const filtro = rotaUi.situacao === "todos" ? "" : ` · ${ROTA_SITUACAO_ROTULO[rotaUi.situacao]}`;
        const diaTexto = diasVisitaTexto(dia).toLowerCase();
        const total = Number(resposta.total || 0);
        rotaSetStatus(total ? `${total} ${total === 1 ? "cliente" : "clientes"} na rota de ${diaTexto}${filtro}.` : `Nenhum cliente na rota de ${diaTexto}${filtro}.`);
      } catch (error) {
        if (sequencia !== rotaUi.seq) return;
        rotaUi.dados = null;
        renderRotaLista([]);
        renderRotaKpis({});
        rotaSetStatus(error.message || "Não foi possível montar a rota agora.", "err");
      } finally {
        if (sequencia === rotaUi.seq) {
          if (botao) botao.disabled = false;
          document.getElementById("rotaLista")?.removeAttribute("aria-busy");
        }
      }
    }

    function renderRotaAvisos(fontes) {
      const alvo = document.getElementById("rotaAvisos");
      if (!alvo) return;
      alvo.innerHTML = Object.values(fontes).filter(fonte => fonte && !fonte.disponivel).map(fonte => `<div class="alert alert-warning py-2 mt-2 mb-0" role="status"><i class="bi bi-database-exclamation me-1" aria-hidden="true"></i>${escapeHtml(fonte.mensagem)}</div>`).join("");
    }

    function renderRotaKpis(resumo) {
      const alvo = document.getElementById("rotaKpis");
      if (!alvo) return;
      const clientes = n => `${n} ${Number(n) === 1 ? "cliente" : "clientes"}`;
      // Os 4 primeiros são os de cobrança; os demais ficam só no computador.
      const cartoes = [
        ["Valor vencido", formatMoneyText(resumo.total_vencido || 0), clientes(resumo.clientes_vencidos ?? 0), "vencidos", false],
        ["Vence hoje", String(resumo.vence_hoje ?? 0), Number(resumo.vence_hoje) === 1 ? "cliente" : "clientes", "hoje", false],
        ["Clientes com pendência", String(resumo.clientes_pendencia ?? 0), resumo.clientes ? `de ${resumo.clientes} na rota` : "", "", false],
        ["Títulos sem boleto", String(resumo.titulos_sem_boleto ?? 0), "", "sem_boleto", false],
        ["Valor pendente", formatMoneyText(resumo.total_pendente || 0), "", "", true],
        ["Títulos em aberto", String(resumo.titulos ?? 0), "", "", true],
        ["Boletos disponíveis", String(resumo.boletos ?? 0), "", "com_boleto", true]
      ];
      alvo.innerHTML = cartoes.map(([rotulo, valor, nota, filtro, extra]) => {
        const conteudo = `<span>${escapeHtml(rotulo)}</span><strong>${escapeHtml(valor)}</strong>${nota ? `<small>${escapeHtml(nota)}</small>` : ""}`;
        const classe = `pedido-manager-kpi rota-kpi${extra ? " rota-kpi-extra" : ""}`;
        return filtro
          ? `<button class="${classe}" type="button" data-rota-situacao="${filtro}" aria-pressed="${rotaUi.situacao === filtro}" aria-label="${escapeHtml(`${rotulo}: ${valor}. Filtrar por ${ROTA_SITUACAO_ROTULO[filtro]}`)}">${conteudo}</button>`
          : `<div class="${classe}">${conteudo}</div>`;
      }).join("");
    }

    // Quantos clientes cada filtro traz (os do giro não têm contagem: a conta é pesada).
    const ROTA_CONTAGEM = { todos: "clientes", vencidos: "clientes_vencidos", hoje: "vence_hoje", amanha: "vence_amanha", dois_dias: "vence_dois_dias", com_boleto: "clientes_com_boleto", sem_boleto: "clientes_sem_boleto" };
    function renderRotaContagens(resumo) {
      document.querySelectorAll("#rotaFinanceiraPane .clientes-filtros [data-rota-situacao]").forEach(botao => {
        const campo = ROTA_CONTAGEM[botao.dataset.rotaSituacao];
        let contagem = botao.querySelector(".rota-contagem");
        if (!campo || resumo[campo] === undefined) { contagem?.remove(); botao.classList.remove("rota-filtro-vazio"); return; }
        if (!contagem) {
          contagem = document.createElement("span");
          contagem.className = "rota-contagem";
          botao.appendChild(contagem);
        }
        const valor = Number(resumo[campo] || 0);
        contagem.textContent = String(valor);
        botao.classList.toggle("rota-filtro-vazio", valor === 0 && botao.dataset.rotaSituacao !== "todos");
      });
    }

    function rotaVencimentoTexto(item) {
      return item.vencimento_proximo || "—";
    }

    function renderRotaLista(clientes) {
      const alvo = document.getElementById("rotaLista");
      if (!alvo) return;
      rotaUi.clientes = clientes;
      if (!clientes.length) { alvo.innerHTML = '<tr><td colspan="11" class="text-center text-secondary py-4">Nenhum cliente para mostrar.</td></tr>'; return; }
      alvo.innerHTML = clientes.map((item, index) => {
        const nome = item.nome || item.razao_social || "Cliente";
        const mensagem = encodeURIComponent(rotaMensagemWhatsapp(item, nome));
        const whats = item.telefone_whatsapp ? `<a class="btn btn-outline-success btn-sm" href="https://wa.me/${encodeURIComponent(item.telefone_whatsapp)}?text=${mensagem}" target="_blank" rel="noopener" title="Abrir o WhatsApp com a mensagem de cobrança" aria-label="WhatsApp de ${escapeHtml(nome)}"><i class="bi bi-whatsapp" aria-hidden="true"></i><span class="rota-acao-movel">WhatsApp</span></a>` : "";
        const ligar = item.telefone_discagem ? `<a class="btn btn-outline-secondary btn-sm" href="tel:${encodeURIComponent(item.telefone_discagem)}" title="Ligar para o cliente" aria-label="Ligar para ${escapeHtml(nome)}"><i class="bi bi-telephone" aria-hidden="true"></i><span class="rota-acao-movel">Ligar</span></a>` : "";
        const boleto = item.boletos ? `<button class="btn btn-outline-primary btn-sm rota-acao" type="button" data-acao="boleto" data-index="${index}" title="Ver os boletos" aria-label="Boletos de ${escapeHtml(nome)}"><i class="bi bi-upc-scan" aria-hidden="true"></i><span class="rota-acao-movel">Boleto</span></button>` : "";
        // Linha de resumo que só aparece no celular (no computador cada dado tem sua coluna).
        const resumoBoleto = !item.titulos ? "" : item.boletos ? "com boleto" : "sem boleto";
        const resumoTitulos = item.titulos
          ? `${item.titulos} ${item.titulos === 1 ? "título" : "títulos"}${item.titulos_vencidos ? `, ${item.titulos_vencidos} ${item.titulos_vencidos === 1 ? "vencido" : "vencidos"}` : ""}`
          : "";
        const venceu = item.menor_dias !== null && item.menor_dias < 0;
        const resumoVencimento = item.vencimento_proximo ? `${venceu ? "venceu" : "vence"} em ${item.vencimento_proximo.slice(0, 5)}` : "";
        const resumo = [`NB ${item.cliente}`, resumoTitulos, resumoVencimento, resumoBoleto].filter(Boolean).join(" · ");
        return `<tr class="rota-linha" data-index="${index}" data-faixa="${escapeHtml(String(item.prioridade))}">
          <td class="text-center rota-c-prior" data-label="Prioridade"><span class="rota-prioridade" title="Prioridade ${escapeHtml(String(item.prioridade))}">${escapeHtml(String(index + 1 + ((rotaUi.pagina || 1) - 1) * (rotaUi.dados?.por_pagina || 25)))}</span></td>
          <td class="rota-c-cliente"><button class="rota-cliente rota-acao" type="button" data-acao="detalhe" data-index="${index}"><strong>${escapeHtml(nome)}</strong><span class="mono">NB ${escapeHtml(item.cliente)}</span></button></td>
          <td class="rota-c-resumo">${escapeHtml(resumo)}</td>
          <td class="rota-c-filial" data-label="Filial">${escapeHtml(item.filial_nome || item.filial)}</td>
          <td class="small rota-c-setor" data-label="GV / Setor">${escapeHtml(rotaRotuloChave(item.gv) || "-")}<br>${escapeHtml(rotaRotuloChave(item.setor) || "-")}</td>
          <td class="small rota-c-telefone" data-label="Telefone">${escapeHtml(item.telefone || "—")}</td>
          <td class="text-end" data-label="Títulos">${escapeHtml(String(item.titulos))}${item.titulos_vencidos ? `<div class="small text-danger">${escapeHtml(String(item.titulos_vencidos))} ${item.titulos_vencidos === 1 ? "vencido" : "vencidos"}</div>` : ""}</td>
          <td class="text-end fw-semibold rota-c-pendente" data-label="Pendente">${item.titulos ? escapeHtml(formatMoneyText(item.total_pendente)) : "—"}</td>
          <td data-label="Vencimento">${escapeHtml(rotaVencimentoTexto(item))}</td>
          <td class="rota-c-situacao" data-label="Situação">${clientesTag(item.situacao.texto, item.situacao.tom)}</td>
          <td data-label="Boleto">${clientesTag(item.boleto.texto, item.boleto.tom)}</td>
          <td class="text-end rota-c-acoes"><div class="rota-acoes">${whats}${ligar}${boleto}</div></td>
        </tr>`;
      }).join("");
    }

    // Mensagem pronta do WhatsApp: cumprimento, valor em aberto e o próximo passo.
    function rotaMensagemWhatsapp(item, nome) {
      const partes = [`Olá, ${nome}! Tudo bem?`];
      if (item.titulos) {
        const venceu = item.menor_dias !== null && item.menor_dias < 0;
        const vencimento = item.vencimento_proximo ? (venceu ? `, vencido desde ${item.vencimento_proximo}` : `, com vencimento em ${item.vencimento_proximo}`) : "";
        partes.push(`Consta em aberto ${formatMoneyText(item.total_pendente)}${vencimento}.`);
        partes.push(item.boletos ? "Posso te enviar o boleto?" : "Como prefere fazer o pagamento?");
      }
      return partes.join(" ");
    }

    function renderRotaPaginacao(resposta) {
      const info = document.getElementById("rotaPaginaInfo");
      const anterior = document.getElementById("rotaAnteriorBtn");
      const proxima = document.getElementById("rotaProximaBtn");
      const pagina = resposta.pagina || 1;
      const paginas = resposta.paginas || 1;
      if (info) info.textContent = `Página ${pagina} de ${paginas}`;
      if (anterior) anterior.disabled = pagina <= 1;
      if (proxima) proxima.disabled = pagina >= paginas;
    }

    function rotaSelecionarSituacao(situacao) {
      rotaUi.situacao = ROTA_SITUACAO_ROTULO[situacao] ? situacao : "todos";
      document.querySelectorAll("[data-rota-situacao]").forEach(botao => botao.setAttribute("aria-pressed", String(botao.dataset.rotaSituacao === rotaUi.situacao)));
      rotaSetStatus(`Filtro ${ROTA_SITUACAO_ROTULO[rotaUi.situacao]} ativado. Atualizando...`);
      syncRotaFinanceira({ pagina: 1 });
    }

    function setupRotaFinanceiraPanel() {
      const form = document.getElementById("rotaFiltrosForm");
      if (!form) return;
      const recarregar = () => syncRotaFinanceira({ pagina: 1 });
      form.addEventListener("submit", event => { event.preventDefault(); recarregar(); });
      document.getElementById("rotaBusca")?.addEventListener("input", debounce(() => {
        const texto = (document.getElementById("rotaBusca")?.value || "").trim();
        if (!texto || texto.length >= 2) recarregar();
      }, 450));
      document.getElementById("rotaDia")?.addEventListener("change", recarregar);
      document.getElementById("rotaSetor")?.addEventListener("change", recarregar);
      ["rotaFilial", "rotaGv"].forEach(id => document.getElementById(id)?.addEventListener("change", () => { rotaAtualizarSetores(); recarregar(); }));
      document.getElementById("rotaAtualizarBtn")?.addEventListener("click", () => syncRotaFinanceira({ pagina: rotaUi.pagina || 1 }));
      document.getElementById("rotaAnteriorBtn")?.addEventListener("click", () => syncRotaFinanceira({ pagina: Math.max(1, (rotaUi.pagina || 1) - 1) }));
      document.getElementById("rotaProximaBtn")?.addEventListener("click", () => syncRotaFinanceira({ pagina: (rotaUi.pagina || 1) + 1 }));
      document.getElementById("rotaFinanceiraPane")?.addEventListener("click", event => {
        const filtro = event.target.closest("[data-rota-situacao]");
        if (filtro) { rotaSelecionarSituacao(filtro.dataset.rotaSituacao); return; }
        const acao = event.target.closest(".rota-acao");
        if (acao) {
          const item = rotaUi.clientes[Number(acao.dataset.index)];
          if (!item) return;
          abrirFichaBlocos(item.filial, item.cliente, { bloco: acao.dataset.acao === "boleto" ? "titulos" : "" });
          return;
        }
        // O cliente inteiro (linha no computador, cartão no celular) abre a ficha;
        // WhatsApp e Ligar continuam sendo links próprios.
        const linha = event.target.closest("tr.rota-linha");
        if (linha && !event.target.closest("a, button, input, select, label")) {
          const item = rotaUi.clientes[Number(linha.dataset.index)];
          if (item) abrirFichaBlocos(item.filial, item.cliente);
        }
      });
    }
