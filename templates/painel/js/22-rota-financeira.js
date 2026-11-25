    // Aba Rota Financeira: fila do dia priorizada pelo risco. Ao tocar num cliente abre a
    // ficha em blocos (24-ficha-cliente.js); as tags vêm da aba Clientes.

    const ROTA_SITUACAO_ROTULO = { todos: "Todos", vencidos: "Vencidos", ate_dois_dias: "Até 2 dias", hoje: "Vence hoje", amanha: "Vence amanhã", dois_dias: "Vence em 2 dias", com_boleto: "Com boleto", sem_boleto: "Sem boleto", sem_giro_vasilhame: "Sem giro de vasilhame", sem_giro_equipamento: "Sem giro de equipamento" };

    function rotaSetStatus(message, kind = "") {
      const element = document.getElementById("rotaStatus");
      if (!element) return;
      element.textContent = message;
      element.className = kind === "err" ? "form-text mt-2 text-danger" : "form-text mt-2";
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
      const gv = (document.getElementById("rotaGv")?.value || "").split(",").filter(Boolean);
      const setores = (opcoes.setores || []).filter(item => (!filial || item.filial === filial) && (!gv.length || gv.includes(item.gv)));
      const select = document.getElementById("rotaSetor");
      const atual = select.value;
      const filiais = [...new Set(setores.map(item => item.filial))];
      const opcoesSetores = itens => itens.map(item => `<option value="${escapeHtml(item.setor)}">Setor ${escapeHtml(item.setor.split("_").pop())}</option>`).join("");
      select.innerHTML = '<option value="">Todos</option>' + (filial
        ? opcoesSetores(setores)
        : filiais.map(codigo => `<optgroup label="${escapeHtml((opcoes.filiais_nomes || {})[codigo] || `Filial ${codigo}`)}">${opcoesSetores(setores.filter(item => item.filial === codigo))}</optgroup>`).join(""));
      if (setores.some(item => item.setor === atual)) select.value = atual;
    }

    function rotaAtualizarGerentes() {
      const opcoes = rotaUi.opcoes || {};
      const filial = document.getElementById("rotaFilial")?.value || "";
      const select = document.getElementById("rotaGv");
      const atual = select.value;
      const grupos = (opcoes.gerentes || [])
        .filter(item => (!filial || item.filiais.includes(filial)) && (!item.tratamento || Boolean(filial)))
        .map(item => ({ ...item, chaves: item.tratamento ? item.chaves.filter(chave => chave.split("_")[0] === filial) : item.chaves }));
      select.innerHTML = '<option value="">Todos</option>' + grupos.map(item => `<option value="${escapeHtml(item.chaves.join(","))}">${escapeHtml(item.nome)}</option>`).join("");
      if (grupos.some(item => item.chaves.join(",") === atual)) select.value = atual;
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
        if ((opcoes.filiais || []).length === 1) document.getElementById("rotaFilial").value = opcoes.filiais[0];
        const gvWrap = document.getElementById("rotaGvWrap");
        if (gvWrap) gvWrap.hidden = !opcoes.mostrar_gv;
        rotaAtualizarGerentes();
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
      rotaUi.clientes = [];
      document.getElementById("rotaLista").innerHTML = '<tr><td colspan="9" class="text-center text-secondary py-4">Atualizando a rota…</td></tr>';
      document.getElementById("rotaKpis").innerHTML = "";
      renderRotaAvisos({});
      renderRotaContagens({});
      renderRotaDestaque(null);
      document.getElementById("rotaPaginacao").hidden = true;
      try {
        const resposta = await req(`${CONFIG.endpoints.rotaFinanceira.lista}?${params.toString()}`);
        if (sequencia !== rotaUi.seq) return;
        rotaUi.dados = resposta;
        rotaUi.pagina = resposta.pagina || 1;
        renderRotaAvisos(resposta.fontes || {});
        renderRotaKpis(resposta.resumo || {});
        renderRotaDestaque(resposta.resumo || {});
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
        rotaUi.clientes = [];
        document.getElementById("rotaLista").innerHTML = '<tr><td colspan="9" class="text-center py-4">Não foi possível carregar a rota. <button type="button" class="btn btn-link btn-sm rota-tentar-novamente">Tentar novamente</button></td></tr>';
        document.getElementById("rotaKpis").innerHTML = "";
        renderRotaDestaque(null);
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
      alvo.innerHTML = Object.values(fontes).filter(fonte => fonte && typeof fonte === "object" && !fonte.disponivel && fonte.mensagem).map(fonte => `<div class="alert alert-warning py-2 mt-2 mb-0" role="status"><i class="bi bi-database-exclamation me-1" aria-hidden="true"></i>${escapeHtml(fonte.mensagem)}</div>`).join("");
    }

    function renderRotaKpis(resumo) {
      const alvo = document.getElementById("rotaKpis");
      if (!alvo) return;
      const clientes = n => `${n} ${Number(n) === 1 ? "cliente" : "clientes"}`;
      // Só no computador e só informação: quem filtra são os botões acima, que já têm as contagens.
      const cartoes = [
        ["Valor vencido", formatMoneyText(resumo.total_vencido || 0), clientes(resumo.clientes_vencidos ?? 0)],
        ["Valor em aberto", formatMoneyText(resumo.total_pendente || 0), `${resumo.titulos ?? 0} ${Number(resumo.titulos) === 1 ? "título" : "títulos"}`],
        ["Clientes com pendência", String(resumo.clientes_pendencia ?? 0), resumo.clientes ? `de ${resumo.clientes} na rota` : ""]
      ];
      alvo.innerHTML = cartoes.map(([rotulo, valor, nota]) => `<div class="pedido-manager-kpi rota-kpi"><span>${escapeHtml(rotulo)}</span><strong>${escapeHtml(valor)}</strong>${nota ? `<small>${escapeHtml(nota)}</small>` : ""}</div>`).join("");
    }

    // No celular, uma linha no lugar dos cartões: quanto está vencido e quantos devem.
    function renderRotaDestaque(resumo) {
      const alvo = document.getElementById("rotaDestaque");
      if (!alvo) return;
      if (!resumo || resumo.clientes === undefined) { alvo.hidden = true; return; }
      const devem = Number(resumo.clientes_pendencia || 0);
      const vencido = Number(resumo.total_vencido || 0);
      alvo.innerHTML = devem
        ? `${vencido ? `<strong>${escapeHtml(formatMoneyText(vencido))} vencido</strong> · ` : ""}${devem} de ${escapeHtml(String(resumo.clientes))} ${Number(resumo.clientes) === 1 ? "cliente" : "clientes"} com pendência`
        : `Nenhum cliente com pendência na rota (${escapeHtml(String(resumo.clientes))} ${Number(resumo.clientes) === 1 ? "cliente" : "clientes"}).`;
      alvo.hidden = false;
    }

    // Quantos clientes cada filtro traz (os do giro não têm contagem: a conta é pesada).
    const ROTA_CONTAGEM = { todos: "clientes", vencidos: "clientes_vencidos", ate_dois_dias: "vence_ate_dois_dias", hoje: "vence_hoje", amanha: "vence_amanha", dois_dias: "vence_dois_dias", com_boleto: "clientes_com_boleto", sem_boleto: "clientes_sem_boleto" };
    function renderRotaContagens(resumoServidor) {
      const resumo = { ...resumoServidor };
      if (resumo.vence_hoje !== undefined) resumo.vence_ate_dois_dias = Number(resumo.vence_hoje || 0) + Number(resumo.vence_amanha || 0) + Number(resumo.vence_dois_dias || 0);
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
      rotaMarcarMaisFiltros();
    }

    function rotaVencimentoTexto(item) {
      return item.vencimento_proximo || "—";
    }

    function renderRotaLista(clientes) {
      const alvo = document.getElementById("rotaLista");
      if (!alvo) return;
      rotaUi.clientes = clientes;
      if (!clientes.length) { alvo.innerHTML = '<tr><td colspan="9" class="text-center text-secondary py-4">Nenhum cliente para mostrar.</td></tr>'; return; }
      alvo.innerHTML = clientes.map((item, index) => {
        const nome = item.nome || item.razao_social || "Cliente";
        const mensagem = encodeURIComponent(rotaMensagemWhatsapp(item, nome));
        // Os três botões aparecem sempre, no mesmo lugar; o que não se aplica fica desabilitado.
        const whats = item.telefone_whatsapp ? `<a class="btn btn-sm rota-btn-whats" href="https://wa.me/${encodeURIComponent(item.telefone_whatsapp)}?text=${mensagem}" target="_blank" rel="noopener" title="Abrir o WhatsApp com a mensagem de cobrança" aria-label="WhatsApp de ${escapeHtml(nome)}"><i class="bi bi-whatsapp" aria-hidden="true"></i><span class="rota-acao-movel">WhatsApp</span></a>` : `<button class="btn btn-sm rota-btn-neutro" type="button" disabled aria-label="Sem WhatsApp cadastrado"><i class="bi bi-whatsapp" aria-hidden="true"></i><span class="rota-acao-movel">WhatsApp</span></button>`;
        const ligar = item.telefone_discagem ? `<a class="btn btn-sm rota-btn-neutro" href="tel:${encodeURIComponent(item.telefone_discagem)}" title="Ligar para o cliente" aria-label="Ligar para ${escapeHtml(nome)}"><i class="bi bi-telephone" aria-hidden="true"></i><span class="rota-acao-movel">Ligar</span></a>` : `<button class="btn btn-sm rota-btn-neutro" type="button" disabled aria-label="Sem telefone cadastrado"><i class="bi bi-telephone" aria-hidden="true"></i><span class="rota-acao-movel">Ligar</span></button>`;
        const boleto = item.boletos ? `<button class="btn btn-sm rota-btn-boleto rota-acao" type="button" data-acao="boleto" data-index="${index}" title="Ver os boletos" aria-label="Boletos de ${escapeHtml(nome)}"><i class="bi bi-upc-scan" aria-hidden="true"></i><span class="rota-acao-movel">Boleto</span></button>` : `<button class="btn btn-sm rota-btn-neutro" type="button" disabled aria-label="Sem boleto"><i class="bi bi-upc-scan" aria-hidden="true"></i><span class="rota-acao-movel">Sem boleto</span></button>`;
        // Linha de resumo que só aparece no celular (no computador cada dado tem sua coluna).
        const resumoTitulos = item.titulos
          ? `${item.titulos} ${item.titulos === 1 ? "título" : "títulos"}${item.titulos_vencidos ? `, ${item.titulos_vencidos} ${item.titulos_vencidos === 1 ? "vencido" : "vencidos"}` : ""}`
          : "";
        // O vencimento está na etiqueta e o boleto no botão; aqui fica só o que eles não dizem.
        const resumo = [`NB ${item.cliente}`, resumoTitulos].filter(Boolean).join(" · ");
        return `<tr class="rota-linha" data-index="${index}" data-faixa="${escapeHtml(String(item.prioridade))}">
          <td class="rota-c-cliente"><button class="rota-cliente rota-acao" type="button" data-acao="detalhe" data-index="${index}"><strong>${escapeHtml(nome)}</strong><span class="mono">NB ${escapeHtml(item.cliente)}</span></button></td>
          <td class="rota-c-resumo">${escapeHtml(resumo)}</td>
          <td class="rota-c-filial" data-label="Filial">${escapeHtml(item.filial_nome || item.filial)}</td>
          <td class="small rota-c-setor" data-label="GV / Setor">${escapeHtml(item.gerente_nome || "GV")} (${escapeHtml(rotaRotuloChave(item.gv) || "-")})<br>Setor ${escapeHtml(String(item.setor || "-").split("_").pop())}</td>
          <td class="small rota-c-telefone" data-label="Telefone">${escapeHtml(item.telefone || "—")}</td>
          <td class="text-end" data-label="Títulos">${escapeHtml(String(item.titulos))}${item.titulos_vencidos ? `<div class="small text-danger">${escapeHtml(String(item.titulos_vencidos))} ${item.titulos_vencidos === 1 ? "vencido" : "vencidos"}</div>` : ""}</td>
          <td class="text-end fw-semibold rota-c-pendente" data-label="Pendente">${item.titulos ? escapeHtml(formatMoneyText(item.total_pendente)) : "—"}</td>
          <td data-label="Vencimento">${escapeHtml(rotaVencimentoTexto(item))}</td>
          <td class="rota-c-situacao" data-label="Situação">${clientesTag(item.situacao.texto, item.situacao.tom)}</td>
          <td class="text-end rota-c-acoes"><div class="rota-acoes">${whats}${ligar}${boleto}</div></td>
        </tr>`;
      }).join("");
    }

    // Mensagem pronta do WhatsApp: cumprimento, valor em aberto e o próximo passo.
    function rotaMensagemWhatsapp(item, nome) {
      const saudacao = nome && nome !== "Cliente" ? `Olá, ${nome}! Tudo bem?` : "Olá! Tudo bem?";
      const partes = [saudacao, "Aqui é da Pau Brasil Bebidas."];
      if (item.titulos) {
        const venceu = item.menor_dias !== null && item.menor_dias < 0;
        partes.push(`Estou entrando em contato sobre um saldo em aberto de ${formatMoneyText(item.total_pendente)}.`);
        if (item.vencimento_proximo) partes.push(venceu ? `O vencimento mais antigo foi em ${item.vencimento_proximo}.` : `O próximo vencimento é em ${item.vencimento_proximo}.`);
        partes.push(item.boletos ? "Posso te enviar o boleto para conferência?" : "Podemos conferir essa pendência?");
        partes.push("Se o pagamento já foi feito, por favor, desconsidere e me avise. Obrigado!");
      }
      else partes.push("Estou entrando em contato para conversarmos. Fico à disposição!");
      return partes.join("\n\n");
    }

    function renderRotaPaginacao(resposta) {
      const info = document.getElementById("rotaPaginaInfo");
      const anterior = document.getElementById("rotaAnteriorBtn");
      const proxima = document.getElementById("rotaProximaBtn");
      const pagina = resposta.pagina || 1;
      const paginas = resposta.paginas || 1;
      if (info) info.textContent = `Página ${pagina} de ${paginas}`;
      // Com uma página só, a navegação de páginas não aparece.
      const nav = document.getElementById("rotaPaginacao");
      if (nav) nav.hidden = paginas <= 1;
      if (anterior) anterior.disabled = pagina <= 1;
      if (proxima) proxima.disabled = pagina >= paginas;
    }

    function rotaSelecionarSituacao(situacao) {
      rotaUi.situacao = ROTA_SITUACAO_ROTULO[situacao] ? situacao : "todos";
      document.querySelectorAll("[data-rota-situacao]").forEach(botao => botao.setAttribute("aria-pressed", String(botao.dataset.rotaSituacao === rotaUi.situacao)));
      rotaMarcarMaisFiltros();
      rotaSetStatus(`Filtro ${ROTA_SITUACAO_ROTULO[rotaUi.situacao]} ativado. Atualizando...`);
      syncRotaFinanceira({ pagina: 1 });
    }

    // "Mais filtros" mostra quando o filtro ativo está escondido lá dentro.
    function rotaMarcarMaisFiltros() {
      const ativoDentro = Boolean(document.querySelector(`#rotaMaisFiltros [data-rota-situacao="${rotaUi.situacao}"]`));
      const marca = document.getElementById("rotaMaisFiltrosAtivo");
      if (marca) marca.hidden = !ativoDentro;
    }

    function rotaAlternarMaisFiltros(abrir) {
      const painel = document.getElementById("rotaMaisFiltros");
      const botao = document.getElementById("rotaMaisFiltrosBtn");
      if (!painel || !botao) return;
      const aberto = abrir ?? painel.hidden;
      painel.hidden = !aberto;
      botao.setAttribute("aria-expanded", String(aberto));
    }

    function setupRotaFinanceiraPanel() {
      const form = document.getElementById("rotaFiltrosForm");
      if (!form) return;
      const recarregar = () => syncRotaFinanceira({ pagina: 1 });
      form.addEventListener("submit", event => { event.preventDefault(); recarregar(); });
      let buscaTimer;
      document.getElementById("rotaBusca")?.addEventListener("input", () => {
        clearTimeout(buscaTimer);
        buscaTimer = setTimeout(() => {
          const texto = (document.getElementById("rotaBusca")?.value || "").trim();
          if (!texto || texto.length >= 2) recarregar();
        }, 450);
      });
      document.getElementById("rotaDia")?.addEventListener("change", recarregar);
      document.getElementById("rotaSetor")?.addEventListener("change", recarregar);
      document.getElementById("rotaFilial")?.addEventListener("change", () => { rotaAtualizarGerentes(); rotaAtualizarSetores(); recarregar(); });
      document.getElementById("rotaGv")?.addEventListener("change", () => { rotaAtualizarSetores(); recarregar(); });
      document.getElementById("rotaAtualizarBtn")?.addEventListener("click", () => syncRotaFinanceira({ pagina: rotaUi.pagina || 1 }));
      document.getElementById("rotaAnteriorBtn")?.addEventListener("click", () => syncRotaFinanceira({ pagina: Math.max(1, (rotaUi.pagina || 1) - 1) }));
      document.getElementById("rotaProximaBtn")?.addEventListener("click", () => syncRotaFinanceira({ pagina: (rotaUi.pagina || 1) + 1 }));
      document.getElementById("rotaMaisFiltrosBtn")?.addEventListener("click", () => rotaAlternarMaisFiltros());
      document.getElementById("rotaLimparFiltros")?.addEventListener("click", () => {
        clearTimeout(buscaTimer);
        const filialUnica = (rotaUi.opcoes?.filiais || []).length === 1 ? rotaUi.opcoes.filiais[0] : "";
        const alterado = ["rotaGv", "rotaSetor", "rotaBusca"].some(id => Boolean(document.getElementById(id)?.value)) || (document.getElementById("rotaFilial")?.value || "") !== filialUnica || rotaUi.situacao !== "todos";
        ["rotaGv", "rotaSetor", "rotaBusca"].forEach(id => { const campo = document.getElementById(id); if (campo) campo.value = ""; });
        document.getElementById("rotaFilial").value = filialUnica;
        rotaAtualizarGerentes();
        rotaAtualizarSetores();
        rotaAlternarMaisFiltros(false);
        if (alterado) rotaSelecionarSituacao("todos");
      });
      document.getElementById("rotaFinanceiraPane")?.addEventListener("click", event => {
        if (event.target.closest(".rota-tentar-novamente")) { recarregar(); return; }
        const filtro = event.target.closest("[data-rota-situacao]");
        if (filtro) { rotaSelecionarSituacao(filtro.dataset.rotaSituacao); return; }
        const acao = event.target.closest(".rota-acao");
        if (acao) {
          const item = rotaUi.clientes[Number(acao.dataset.index)];
          if (!item) return;
          abrirFichaBlocos(item.filial, item.cliente);
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
