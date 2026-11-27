    // Ficha do cliente em blocos empilhados (Rota Financeira e Clientes).
    // Fluxo: cabeçalho com contato → blocos com resumo → detalhe dentro do bloco.
    // O servidor confere o escopo em cada chamada; aqui só se mostra o que ele devolveu.

    const FICHA_BLOCOS = [
      { id: "titulos", titulo: "Títulos em aberto", icone: "bi-receipt" },
      { id: "credito", titulo: "Análise de crédito", icone: "bi-speedometer2" },
      { id: "compras", titulo: "Compras", icone: "bi-bag-check" },
      { id: "notas", titulo: "Notas fiscais", icone: "bi-receipt-cutoff" },
      { id: "vasilhames", titulo: "Vasilhames", icone: "bi-recycle" },
      { id: "equipamentos", titulo: "Equipamentos", icone: "bi-plug" },
      { id: "comodatos", titulo: "Comodatos", icone: "bi-box-seam" },
      { id: "devolucoes", titulo: "Devoluções", icone: "bi-arrow-return-left" },
      { id: "cadastro", titulo: "Cadastro e documentos", icone: "bi-person-vcard" }
    ];

    function fichaUrl(filial, cliente, sufixo) {
      return `${CONFIG.endpoints.clientes.ficha}/${encodeURIComponent(filial)}/${encodeURIComponent(cliente)}/${sufixo}`;
    }

    function fichaMesBr(competencia) {
      const [ano, mes] = String(competencia || "").split("-");
      return ano && mes ? `${mes}/${ano}` : "-";
    }

    function fichaDataBr(valor) {
      const texto = String(valor || "");
      const iso = texto.match(/^(\d{4})-(\d{2})-(\d{2})/);
      return iso ? `${iso[3]}/${iso[2]}/${iso[1]}` : (texto || "-");
    }

    function fichaNumero(valor, casas = 0) {
      const n = Number(valor || 0);
      return Number.isFinite(n) ? n.toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas }) : String(valor || "0");
    }

    function fichaFatos(pares) {
      return `<dl class="ficha-fatos">${pares.filter(([, valor]) => valor !== undefined).map(([rotulo, valor]) => `<div><dt>${escapeHtml(rotulo)}</dt><dd>${escapeHtml(String(valor === "" || valor === null ? "-" : valor))}</dd></div>`).join("")}</dl>`;
    }

    async function abrirFichaBlocos(filial, cliente) {
      const painel = document.getElementById("fichaCliente");
      const corpo = document.getElementById("fichaClienteCorpo");
      if (!painel || !corpo) return;
      const sequencia = ++fichaUi.seq;
      fichaUi.atual = { filial: String(filial), cliente: String(cliente) };
      fichaUi.blocos = {};
      fichaUi.abertos = [];
      corpo.innerHTML = '<div class="text-secondary py-3" role="status"><span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>Abrindo o cliente...</div>';
      bootstrap.Offcanvas.getOrCreateInstance(painel).show();
      try {
        const resposta = await req(fichaUrl(filial, cliente, "cabecalho"));
        if (sequencia !== fichaUi.seq) return;
        fichaUi.cliente = resposta.cliente || {};
        corpo.innerHTML = renderFichaCabecalho(fichaUi.cliente) + `<section class="ficha-resumo" aria-label="Resumo do cliente"><h3 class="h6 fw-bold">Resumo do cliente</h3><div id="fichaResumoDados" aria-live="polite">Carregando resumo...</div><nav class="ficha-atalhos" aria-label="Acessos rápidos"><button type="button" data-ficha-ir="titulos">Títulos</button><button type="button" data-ficha-ir="compras">Compras</button><button type="button" data-ficha-ir="notas">Notas</button><button type="button" data-ficha-ir="devolucoes">Devoluções</button></nav></section><div class="ficha-blocos">${FICHA_BLOCOS.map(renderFichaBlocoCasca).join("")}</div>`;
        FICHA_BLOCOS.filter(item => item.id !== "notas").forEach(item => carregarFichaBloco(item.id, sequencia));
      } catch (error) {
        if (sequencia !== fichaUi.seq) return;
        corpo.innerHTML = `<div class="alert alert-danger mb-0" role="alert"><i class="bi bi-shield-exclamation me-2" aria-hidden="true"></i>${escapeHtml(error.message || "Não foi possível abrir o cliente.")} <button class="btn btn-outline-danger btn-sm ms-2" type="button" data-ficha-repetir="cabecalho">Tentar novamente</button></div>`;
      }
    }

    function renderFichaCabecalho(c) {
      const nome = c.nome || c.razao_social || "Cliente";
      const saudacao = nome !== "Cliente" ? `Olá, ${nome}! Tudo bem?` : "Olá! Tudo bem?";
      const mensagem = `${saudacao}\n\nAqui é da Pau Brasil Bebidas. Estou entrando em contato para conversarmos. Fico à disposição!`;
      const titulo = document.getElementById("fichaClienteTitulo");
      if (titulo) titulo.textContent = nome;
      const acoes = [
        c.telefone_whatsapp ? `<a class="btn btn-success btn-sm" href="https://wa.me/${encodeURIComponent(c.telefone_whatsapp)}?text=${encodeURIComponent(mensagem)}" target="_blank" rel="noopener" aria-label="WhatsApp de ${escapeHtml(nome)}"><i class="bi bi-whatsapp me-1" aria-hidden="true"></i>WhatsApp</a>` : "",
        c.telefone_discagem ? `<a class="btn btn-outline-secondary btn-sm" href="tel:${encodeURIComponent(c.telefone_discagem)}" aria-label="Ligar para ${escapeHtml(nome)}"><i class="bi bi-telephone me-1" aria-hidden="true"></i>Ligar</a>` : "",
        c.mapa_url ? `<a class="btn btn-outline-secondary btn-sm" href="${escapeHtml(c.mapa_url)}" target="_blank" rel="noopener" aria-label="Abrir endereço de ${escapeHtml(nome)} no mapa"><i class="bi bi-geo-alt me-1" aria-hidden="true"></i>Mapa</a>` : ""
      ].join("");
      const fatos = [["Filial", c.filial], ["Setor / RN", clientesChave(c.setor)], ["GV", clientesChave(c.gv)], ["Cidade", c.cidade], ["Visita", diasVisitaTexto(c.dia_visita)], ["Status", c.status], ["Telefone", c.telefone]];
      return `<header class="ficha-cabecalho">
          <div class="ficha-cabecalho-nome"><span class="mono">NB ${escapeHtml(c.cliente || "")}</span><h2 class="h5 fw-bold mb-0">${escapeHtml(nome)}</h2>${c.razao_social && c.razao_social !== nome ? `<div class="small text-secondary">${escapeHtml(c.razao_social)}</div>` : ""}</div>
          ${fichaFatos(fatos)}
          ${acoes ? `<div class="ficha-acoes">${acoes}</div>` : ""}
        </header>`;
    }

    function renderFichaBlocoCasca(item) {
      return `<section class="ficha-bloco" data-bloco="${item.id}" data-estado="${item.id === "notas" ? "nao-carregado" : "carregando"}">
          <h3 class="ficha-bloco-h"><button class="ficha-bloco-cab" type="button" aria-expanded="false" aria-controls="fichaBloco-${item.id}" data-ficha-bloco="${item.id}">
            <span class="ficha-bloco-icone"><i class="bi ${item.icone}" aria-hidden="true"></i></span>
            <span class="ficha-bloco-texto"><span class="ficha-bloco-titulo">${escapeHtml(item.titulo)}</span><span class="ficha-bloco-resumo">${item.id === "notas" ? "Emissão no mês atual e nos dois anteriores" : '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>Carregando...'}</span></span>
            <i class="bi bi-chevron-down ficha-bloco-chevron" aria-hidden="true"></i>
          </button></h3>
          <div class="ficha-bloco-corpo" id="fichaBloco-${item.id}" role="region" aria-label="${escapeHtml(item.titulo)}" hidden></div>
        </section>`;
    }

    async function carregarFichaBloco(id, sequencia) {
      const { filial, cliente } = fichaUi.atual || {};
      const secao = document.querySelector(`.ficha-bloco[data-bloco="${id}"]`);
      if (!secao) return;
      delete fichaUi.blocos[id];
      secao.dataset.estado = "carregando";
      secao.querySelector(".ficha-bloco-resumo").textContent = "Carregando...";
      const painelBloco = document.getElementById(`fichaBloco-${id}`);
      if (painelBloco && !painelBloco.hidden) painelBloco.innerHTML = renderFichaBlocoCorpo(id);
      try {
        const dados = await req(fichaUrl(filial, cliente, `blocos/${id}`));
        if (sequencia !== fichaUi.seq) return;
        fichaUi.blocos[id] = dados;
        secao.dataset.estado = dados.estado || "ok";
        secao.querySelector(".ficha-bloco-resumo").textContent = dados.resumo || "-";
      } catch (error) {
        if (sequencia !== fichaUi.seq) return;
        fichaUi.blocos[id] = { estado: "indisponivel", resumo: error.message || "Não foi possível carregar.", erro: true };
        secao.dataset.estado = "indisponivel";
        secao.querySelector(".ficha-bloco-resumo").textContent = fichaUi.blocos[id].resumo;
      }
      const corpo = document.getElementById(`fichaBloco-${id}`);
      if (corpo && !corpo.hidden) corpo.innerHTML = renderFichaBlocoCorpo(id);
      atualizarFichaResumo();
    }

    function atualizarFichaResumo() {
      const alvo = document.getElementById("fichaResumoDados");
      if (!alvo) return;
      const resumo = id => {
        const bloco = fichaUi.blocos[id];
        if (!bloco) return "Carregando...";
        if (bloco.erro || bloco.estado === "indisponivel") return "Indisponível";
        return bloco.resumo || "Sem dados";
      };
      const compras = fichaUi.blocos.compras;
      const ultima = compras && compras.estado === "ok" ? fichaDataBr(compras.dados?.ultima_entrega) : resumo("compras");
      const titulos = fichaUi.blocos.titulos;
      const vencidos = Number(titulos?.dados?.vencidos || 0);
      const alertas = [];
      if (titulos?.estado === "ok" && vencidos > 0) alertas.push(`${vencidos} título${vencidos === 1 ? " vencido" : "s vencidos"}. Abra Títulos para conferir.`);
      const dataEntrega = compras?.estado === "ok" ? String(compras.dados?.ultima_entrega || "") : "";
      if (/^\d{4}-\d{2}-\d{2}$/.test(dataEntrega)) {
        const dias = Math.floor((Date.now() - new Date(`${dataEntrega}T12:00:00`).getTime()) / 86400000);
        if (dias >= 30) alertas.push(`Última entrega há ${dias} dias, conforme a base importada.`);
      }
      const alerta = alertas.length ? `<div class="ficha-alerta" role="status">${alertas.map(texto => `<div>${escapeHtml(texto)}</div>`).join("")}</div>` : "";
      alvo.innerHTML = alerta + fichaFatos([["Títulos", resumo("titulos")], ["Crédito", resumo("credito")], ["Última entrega", ultima], ["Devoluções", resumo("devolucoes")]]);
    }

    function alternarFichaBloco(id, abrir) {
      const botao = document.querySelector(`[data-ficha-bloco="${id}"]`);
      const corpo = document.getElementById(`fichaBloco-${id}`);
      if (!botao || !corpo) return;
      const vaiAbrir = abrir === undefined ? corpo.hidden : abrir;
      fichaUi.abertos = fichaUi.abertos.filter(item => item !== id);
      if (vaiAbrir) {
        fichaUi.abertos.push(id);
        corpo.innerHTML = renderFichaBlocoCorpo(id);
        const secao = botao.closest(".ficha-bloco");
        if (id === "notas" && secao?.dataset.estado === "nao-carregado") carregarFichaBloco(id, fichaUi.seq);
      }
      corpo.hidden = !vaiAbrir;
      botao.setAttribute("aria-expanded", String(vaiAbrir));
      botao.closest(".ficha-bloco")?.classList.toggle("is-open", vaiAbrir);
    }

    function renderFichaBlocoCorpo(id) {
      const bloco = fichaUi.blocos[id];
      if (!bloco) return '<div class="text-secondary small py-2" role="status"><span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>Carregando...</div>';
      if (bloco.erro) return `<div class="alert alert-danger py-2 mb-0" role="alert">${escapeHtml(bloco.resumo)} <button class="btn btn-outline-danger btn-sm ms-2" type="button" data-ficha-repetir="${escapeHtml(id)}">Tentar novamente</button></div>`;
      if (bloco.estado === "indisponivel") return `<div class="alert alert-warning py-2 mb-0" role="status"><i class="bi bi-database-exclamation me-1" aria-hidden="true"></i>${escapeHtml(bloco.fonte?.mensagem || bloco.resumo || "Não foi possível carregar agora.")} <button class="btn btn-outline-secondary btn-sm ms-2" type="button" data-ficha-repetir="${escapeHtml(id)}">Tentar novamente</button></div>${fichaRodape(bloco)}`;
      const render = FICHA_RENDER[id];
      return `${render ? render(bloco.dados || {}, bloco) : ""}${fichaRodape(bloco)}`;
    }

    function fichaRodape(bloco) {
      const fonte = bloco.fonte || {};
      // Só a data da atualização; o nome do relatório de origem não interessa a quem usa a ficha.
      return fonte.atualizado_em ? `<div class="ficha-rodape"><i class="bi bi-clock-history me-1" aria-hidden="true"></i>Atualizado em ${escapeHtml(fonte.atualizado_em)}</div>` : "";
    }

    function fichaFiltrosNotas(prefixo) {
      return `<div class="ficha-filtros-notas"><label>Número da NF<input class="form-control form-control-sm" type="search" inputmode="numeric" data-ficha-filtro="nota" placeholder="Buscar nota"></label><label>De<input class="form-control form-control-sm" type="date" data-ficha-filtro="inicio"></label><label>Até<input class="form-control form-control-sm" type="date" data-ficha-filtro="fim"></label></div><div class="small text-secondary" data-ficha-filtro-status aria-live="polite"></div>`;
    }

    const FICHA_RENDER = {
      titulos(d, bloco) {
        const titulos = d.titulos || [];
        if (!titulos.length) return clientesVazio("Nenhum título em aberto.");
        const c = fichaUi.cliente || {};
        return `<div class="ficha-lista">${titulos.map(t => {
          const s = CLIENTES_SITUACAO[t.situacao] || CLIENTES_SITUACAO.sem_data;
          const acoes = t.boleto ? clientesAcoesBoleto(c, t.boleto) : clientesTag(t.situacao_boleto || "Sem boleto", "neutral", "bi-file-earmark-x");
          return `<article class="ficha-item" data-situacao="${escapeHtml(t.situacao)}">
              <div class="ficha-item-topo"><strong class="mono">NF ${escapeHtml(t.nota_fiscal || "-")}</strong>${clientesTag(s.rotulo, s.tom, s.icone)}</div>
              ${fichaFatos([["Emissão", t.emissao], ["Vencimento", t.vencimento], ["Dias", t.dias === null || t.dias === undefined ? "-" : t.dias < 0 ? `${-t.dias} de atraso` : t.dias], ["Original", formatMoneyText(t.valor_original)], ["Pendente", formatMoneyText(t.valor_pendente)], ["Corrigido", formatMoneyText(t.valor_corrigido)]])}
              <div class="ficha-item-acoes">${acoes}</div>
            </article>`;
        }).join("")}</div>${bloco.dados && bloco.dados.boletos_disponivel === false ? '<div class="small text-warning-emphasis mt-2">Os boletos não puderam ser carregados agora.</div>' : ""}`;
      },
      credito(d) {
        const disponivel = d.limite_disponivel ? `${formatMoneyText(d.limite_disponivel)}${d.limite_disponivel_calculado ? " (calculado)" : ""}` : "-";
        const fatos = fichaFatos([["Limite total", d.limite_total ? formatMoneyText(d.limite_total) : "-"], ["Limite utilizado", d.limite_utilizado ? formatMoneyText(d.limite_utilizado) : "-"], ["Limite disponível", disponivel], ["Condição de pagamento", d.condicao_pagamento_nome || d.condicao_pagamento], ["ADF da condição", d.adf_condicao || "Não informado"], ["Prazo atual", d.prazo_atual], ["Pagamentos em atraso", d.percentual_pag_atraso]]);
        const fat = (d.faturamento || []).length
          ? `<h4 class="ficha-sub">Faturamento entregue</h4><ul class="ficha-linhas">${d.faturamento.map(f => `<li><span>${escapeHtml(f.kpi || "-")}</span><strong>${escapeHtml(f.faturamento_com_pdv || "-")}</strong><small>${escapeHtml(f.pedidos === "" ? "" : `${f.pedidos} nota(s)`)}</small></li>`).join("")}</ul>`
          : `<h4 class="ficha-sub">Faturamento entregue</h4><div class="small text-secondary">${d.faturamento_fonte === "indisponivel" ? "O faturamento não pôde ser carregado agora." : "Nenhuma compra registrada."}</div>`;
        return `${fatos}${fat}`;
      },
      compras(d, bloco) {
        if (bloco.estado === "vazio") return clientesVazio("Nenhuma compra registrada para este cliente.");
        const atual = d.mes_atual || {};
        const media = d.media_3_meses === null || d.media_3_meses === undefined
          ? `<span class="text-secondary">Histórico desde ${escapeHtml(fichaMesBr(d.base_desde))}</span>`
          : escapeHtml(formatMoneyText(d.media_3_meses));
        const kpis = `<div class="ficha-kpis">
            <div><span>Mês atual (parcial)</span><strong>${escapeHtml(formatMoneyText(atual.total || 0))}</strong></div>
            <div><span>Média mensal entregue</span><strong>${media}</strong><small>3 meses fechados</small></div>
            <div><span>Notas (3 meses)</span><strong>${escapeHtml(fichaNumero(d.notas_3_meses))}</strong></div>
            <div><span>Média semanal entregue</span><strong>${d.media_semanal === null || d.media_semanal === undefined ? "—" : escapeHtml(formatMoneyText(d.media_semanal))}</strong><small>3 meses fechados</small></div>
            <div><span>Última entrega</span><strong>${escapeHtml(fichaDataBr(d.ultima_entrega))}</strong></div>
          </div>`;
        const aviso = d.historico_suficiente ? "" : `<div class="small text-secondary mb-2">A média aparece quando houver 3 meses fechados de histórico. Histórico desde ${escapeHtml(fichaMesBr(d.base_desde))}.</div>`;
        const tops = [["Maior faturamento", d.top_faturamento || [], p => formatMoneyText(p.total)], ["Maior quantidade", d.top_quantidade || [], p => `${fichaNumero(p.qtde)} ${p.unidade || ""}`]]
          .map(([rotulo, itens, valor]) => `<div><h4 class="ficha-sub">${rotulo}</h4>${itens.length ? `<ol class="ficha-top">${itens.map(p => `<li><span>${escapeHtml(p.descricao || `Produto ${p.produto}`)}</span><strong>${escapeHtml(valor(p))}</strong></li>`).join("")}</ol>` : '<div class="small text-secondary">Sem produtos no período.</div>'}</div>`).join("");
        return `${kpis}${aviso}<h4 class="ficha-sub">Faturamento entregue por mês</h4>${fichaGraficoCompras(d.serie || [])}<div class="ficha-tops">${tops}</div>`;
      },
      notas(d) {
        const notas = d.notas_fiscais || [];
        if (!notas.length) return clientesVazio("Nenhuma nota encontrada na base importada.");
        return `<div data-ficha-filtros>${fichaFiltrosNotas("notas")}<div class="ficha-lista">${notas.map(n => `<details class="ficha-item ficha-nota" data-ficha-nota="${escapeHtml(String(n.nota || ""))}" data-data="${escapeHtml(String(n.data || ""))}"><summary class="ficha-nota-resumo"><span><strong>NF ${escapeHtml(n.nota)}${n.serie ? ` · Série ${escapeHtml(n.serie)}` : ""}</strong><small>${escapeHtml(fichaDataBr(n.data))} · ${escapeHtml(fichaNumero(n.itens))} itens · ${((n.operacoes || []).length ? n.operacoes.map(op => escapeHtml(op.nome || `Operação ${op.codigo}`)).join(" / ") : "Operação não informada")}</small></span><strong>${escapeHtml(formatMoneyText(n.total))}</strong></summary>${(n.produtos || []).length ? `<ul class="ficha-linhas">${n.produtos.map(p => `<li><span>${escapeHtml(p.descricao || `Produto ${p.produto}`)}<small class="d-block text-secondary">Quantidade: ${escapeHtml(fichaNumero(p.qtde, 2))} ${escapeHtml(p.unidade || "")}</small></span><strong aria-label="Valor total do item">${escapeHtml(formatMoneyText(p.total))}</strong></li>`).join("")}</ul>` : '<div class="small text-secondary">Produtos indisponíveis.</div>'}</details>`).join("")}</div><p class="small text-secondary mt-2">Notas filtradas pela data de emissão. Valores dos produtos conforme a coluna Total da importação. PDF e XML não estão disponíveis nesta base.</p></div>`;
      },
      vasilhames(d, bloco) {
        if (bloco.estado === "vazio") return clientesVazio("O cliente não tem garrafeiras em comodato.");
        const cartoes = (d.tipos || []).filter(t => Number(String(t.caixas).replace(",", ".")) > 0).map(t => {
          const tag = FICHA_CAIXAS_TAG[t.situacao] || FICHA_CAIXAS_TAG.em_risco;
          const barra = t.percentual === null ? "" : `<div class="ficha-progresso" role="progressbar" aria-label="Giro de ${escapeHtml(t.rotulo)}: ${t.percentual}%" aria-valuenow="${t.percentual}" aria-valuemin="0" aria-valuemax="100"><span style="width:${t.percentual}%"></span></div>`;
          const pendente = t.situacao !== "batido";
          const fatos = [["Comprou no mês", `${t.compradas} de ${t.meta} cx`]];
          if (pendente) fatos.push(["Faltam", `${t.falta} cx`], ["Previsão do mês", `${t.previsao} cx`]);
          fatos.push(["Em comodato", `${t.caixas} cx, giro ${d.multiplicador || 2}`]);
          if (t.visitas_restantes !== null && t.visitas_restantes !== undefined) fatos.push(["Visitas que faltam no mês", String(t.visitas_restantes)]);
          const media = pendente ? `<div class="small text-secondary mt-1">Costuma comprar ${escapeHtml(t.media_mensal)} cx por mês (média dos 3 meses anteriores).</div>` : "";
          return `<article class="ficha-item"><div class="ficha-item-topo"><strong>${escapeHtml(t.rotulo)}</strong>${clientesTag(tag[0], tag[1], tag[2])}</div>${barra}${fichaFatos(fatos)}${media}</article>`;
        }).join("");
        const ate = d.compras_ate ? `<div class="small text-secondary mt-2">Compras até ${escapeHtml(d.compras_ate)}</div>` : "";
        return `<div class="ficha-lista">${cartoes}</div>${ate}<div class="small text-secondary mt-2">${escapeHtml(d.explicacao || "")}</div>`;
      },
      equipamentos(d, bloco) {
        if (bloco.estado === "vazio") return clientesVazio("O cliente não tem SOPI nem Visa em comodato.");
        const cartoes = (d.tipos || []).filter(t => Number(t.equipamentos) > 0).map(t => {
          const tag = FICHA_GIRO_TAG[t.situacao] || FICHA_GIRO_TAG.em_risco;
          const barra = t.percentual === null ? "" : `<div class="ficha-progresso" role="progressbar" aria-label="Giro de ${escapeHtml(t.rotulo)}: ${t.percentual}%" aria-valuenow="${t.percentual}" aria-valuemin="0" aria-valuemax="100"><span style="width:${t.percentual}%"></span></div>`;
          const nome = t.rotulo.split(" ")[0];
          return `<article class="ficha-item"><div class="ficha-item-topo"><strong>${escapeHtml(nome)} · ${t.equipamentos} equipamento${t.equipamentos > 1 ? "s" : ""}</strong>${clientesTag(tag[0], tag[1], tag[2])}</div>${barra}
              ${fichaFatos([[`Faturado de ${t.cesta} no mês`, `R$ ${t.comprado} de R$ ${t.meta}`], ["Faltam", `R$ ${t.falta}`], ["Previsão do mês", `R$ ${t.previsao}`], ["Valor dos equipamentos", `R$ ${t.valor_equipamentos}`]])}</article>`;
        }).join("");
        return `<div class="ficha-lista">${cartoes}${d.mix ? fichaMixCerveja(d.mix) : ""}</div><div class="small text-secondary mt-2">${escapeHtml(d.explicacao || "")}</div>`;
      },
      comodatos(d, bloco) {
        if (bloco.estado === "vazio") return clientesVazio("Nenhum comodato em aberto.");
        return `<div class="ficha-lista">${(d.itens || []).map(i => `<article class="ficha-item">
            <div class="ficha-item-topo"><strong>${escapeHtml(i.material || "-")}</strong>${i.vencido ? clientesTag("Contrato vencido", "err", "bi-calendar-x") : (i.vencimento ? clientesTag("Em dia", "ok", "bi-calendar-check") : "")}</div>
            ${fichaFatos([["Subtipo", i.sub_tipo], ["Comodato", i.nro_comodato], ["Saldo", i.saldo], ["Vencimento", i.vencimento || "não informado"]])}
          </article>`).join("")}</div><div class="small text-secondary mt-2">Saldo total: ${escapeHtml(d.saldo_total || "0")}</div>`;
      },
      devolucoes(d, bloco) {
        if (!(d.itens || []).length) return clientesVazio("Nenhuma devolução na base importada.");
        return `<div data-ficha-filtros>${fichaFiltrosNotas("devolucoes")}<div class="ficha-lista">${d.itens.map(i => `<article class="ficha-item" data-ficha-nota="${escapeHtml(String(i.nota || ""))}" data-data="${escapeHtml(String(i.data || ""))}">
            <div class="ficha-item-topo"><strong class="mono">NF ${escapeHtml(i.nota || "-")}</strong><span class="small text-secondary">${escapeHtml(fichaDataBr(i.data))}</span></div>
            ${fichaFatos([["Motivo", i.motivo], ["Responsabilidade", i.responsabilidade || "-"], ["NF de origem", i.nf_referencia || "-"], ["Volume", fichaNumero(i.qtde)], ["Valor", formatMoneyText(i.total)]])}
            ${i.justificativa ? `<p class="ficha-justificativa"><i class="bi bi-chat-left-text me-1" aria-hidden="true"></i>${escapeHtml(i.justificativa)}</p>` : ""}
          </article>`).join("")}</div></div>`;
      },
      cadastro(d) {
        return `${fichaDocumentacao(d.documentacao || {})}
          ${fichaFatos([["Endereço", d.endereco], ["Bairro e cidade", d.bairro_cidade], ["CEP", d.cep], ["Telefones", (d.telefones || []).join(" · ")]])}
          ${fichaFatos([["Setor", clientesChave(d.setor)], ["Gerente (GV)", clientesChave(d.gv)], ["Visita do vendedor", d.visita_vendedor], ["Próxima visita", d.proxima_visita], ["Contato do BEES", d.contato_bees], ["Próximo contato BEES", d.proximo_contato_bees]])}
          ${fichaFatos([["Categoria", d.categoria], ["Segmento", d.segmento], ...(d.rede ? [["Rede", d.rede]] : []), ["Cliente desde", d.cliente_desde]])}
          ${fichaFatos([["Razão social", d.razao_social], ["Nome fantasia", d.nome_fantasia], ["CPF/CNPJ", d.documento], ["Tipo de pessoa", d.tipo_pessoa], ["Situação na Receita", d.situacao_rf], ["Status do cliente", d.status]])}`;
      }
    };

    const FICHA_CAIXAS_TAG = {
      batido: ["Já bateu", "ok", "bi-check2"],
      deve_bater: ["Deve bater", "ok", "bi-graph-up-arrow"],
      em_risco: ["Em risco", "warn", "bi-exclamation-triangle"]
    };
    const FICHA_GIRO_TAG = {
      batido: ["Giro batido", "ok", "bi-check2"],
      deve_atingir: ["Deve atingir", "ok", "bi-graph-up-arrow"],
      em_risco: ["Em risco", "warn", "bi-exclamation-triangle"]
    };

    // Mix de cerveja do SOPI: SKUs no mês, nos 3 meses anteriores e o que falta comprar.
    function fichaMixCerveja(mix) {
      const tag = mix.faltam ? clientesTag(`Faltam ${mix.faltam} cerveja${mix.faltam > 1 ? "s" : ""}`, "warn", "bi-exclamation-triangle") : clientesTag("Mix completo", "ok", "bi-check2");
      const meses = (mix.meses_anteriores || []).map(m => m.sem_base
        ? clientesTag(`${fichaMesBr(m.competencia)}: sem dados`, "neutral")
        : clientesTag(`${fichaMesBr(m.competencia)}: ${m.skus}`, m.bateu ? "ok" : "err", m.bateu ? "bi-check2" : "bi-x-lg")).join(" ");
      const comprados = (mix.comprados || []).map(p => `<li>${escapeHtml(p.descricao || p.produto)}</li>`).join("");
      const completar = (mix.completar || []).map(p => {
        const frequencia = p.meses === p.de_meses ? `Comprou nos ${p.de_meses} meses` : `Comprou em ${p.meses} de ${p.de_meses} meses`;
        const ultima = p.ultima ? `a última em ${p.ultima}` : `a última em ${fichaMesBr(p.ultima_competencia)}`;
        return `<li><span>${escapeHtml(p.descricao || p.produto)}<small class="d-block text-secondary">${escapeHtml(`${frequencia}, ${ultima}`)}</small></span></li>`;
      }).join("");
      return `<article class="ficha-item"><div class="ficha-item-topo"><strong>Mix de cerveja</strong>${tag}</div>
          ${fichaFatos([["Cervejas diferentes no mês", `${mix.skus_mes} de ${mix.meta}`]])}
          <div class="small text-secondary mt-2 mb-1">Cervejas diferentes nos meses anteriores</div><div class="d-flex flex-wrap gap-1">${meses}</div>
          <details class="ficha-detalhe mt-2"><summary>Comprados no mês (${(mix.comprados || []).length})</summary>${comprados ? `<ul class="ficha-linhas">${comprados}</ul>` : '<div class="small text-secondary">Nenhuma cerveja no mês ainda.</div>'}</details>
          <details class="ficha-detalhe mt-1"${completar ? " open" : ""}><summary>Para completar o mix (${(mix.completar || []).length})</summary>
            <div class="small text-secondary mb-1">Cervejas que o cliente comprou nos 3 meses anteriores e ainda não comprou neste. Primeiro as que ele compra com mais frequência.</div>
            ${completar ? `<ul class="ficha-linhas">${completar}</ul>` : '<div class="small text-secondary">Nada a sugerir: ele já comprou neste mês tudo o que comprava antes.</div>'}</details></article>`;
    }

    // Documentação: completa ou quantos faltam, e o status de cada documento.
    function fichaDocumentacao(doc) {
      const titulo = doc.completa === true
        ? '<div class="ficha-doc-titulo text-success-emphasis fw-semibold">Documentação completa</div>'
        : doc.completa === false
          ? `<div class="ficha-doc-titulo text-warning-emphasis fw-semibold">${doc.pendentes ? `${doc.pendentes} documento${doc.pendentes > 1 ? "s" : ""} pendente${doc.pendentes > 1 ? "s" : ""}` : "Documentação pendente"}</div>`
          : '<div class="ficha-doc-titulo text-secondary">Documentação sem informação</div>';
      if (doc.disponivel === false) return `${titulo}<div class="small text-warning-emphasis mb-2">Os documentos não puderam ser carregados agora.</div>`;
      const itens = (doc.itens || []).map(item => `<li><span>${escapeHtml(item.rotulo)}${item.observacao ? `<small class="d-block text-secondary">${escapeHtml(item.observacao)}</small>` : ""}</span>${item.ok ? clientesTag("OK", "ok", "bi-check2") : clientesTag("Pendente", "warn", "bi-exclamation-triangle")}</li>`).join("");
      return `${titulo}${itens ? `<ul class="ficha-docs mb-2">${itens}</ul>` : ""}`;
    }

    // Barras simples do faturamento mensal (3 meses fechados + mês atual parcial).
    function fichaGraficoCompras(serie) {
      if (!serie.length) return "";
      const max = Math.max(...serie.map(m => Number(m.total) || 0), 1);
      const largura = 320, altura = 120, base = 96, coluna = largura / serie.length;
      const barras = serie.map((m, i) => {
        const valor = Number(m.total) || 0;
        const h = Math.round((valor / max) * 76);
        const x = Math.round(i * coluna + coluna * 0.2);
        const w = Math.round(coluna * 0.6);
        const rotulo = valor >= 1000 ? `${fichaNumero(valor / 1000, 1)} mil` : fichaNumero(valor);
        const semBase = m.com_base === false;
        return `<g><title>${escapeHtml(fichaMesBr(m.competencia))}: ${escapeHtml(formatMoneyText(valor))}${semBase ? " (fora da base)" : ""}</title>
            <rect x="${x}" y="${base - h}" width="${w}" height="${Math.max(h, 1)}" rx="3" class="ficha-barra${m.atual ? " is-atual" : ""}${semBase ? " is-sem-base" : ""}"></rect>
            <text x="${x + w / 2}" y="${base - h - 5}" text-anchor="middle" class="ficha-barra-valor">${semBase ? "—" : escapeHtml(rotulo)}</text>
            <text x="${x + w / 2}" y="${base + 16}" text-anchor="middle" class="ficha-barra-mes">${escapeHtml(fichaMesBr(m.competencia).slice(0, 2))}${m.atual ? "*" : ""}</text></g>`;
      }).join("");
      return `<svg class="ficha-grafico" viewBox="0 0 ${largura} ${altura}" role="img" aria-label="Faturamento entregue nos últimos meses">${barras}<line x1="0" x2="${largura}" y1="${base}" y2="${base}" class="ficha-grafico-eixo"></line></svg><div class="small text-secondary">* mês atual, parcial.</div>`;
    }

    function setupFichaCliente() {
      const corpo = document.getElementById("fichaClienteCorpo");
      if (!corpo) return;
      corpo.addEventListener("click", event => {
        const atalho = event.target.closest("[data-ficha-ir]");
        if (atalho) { const id = atalho.dataset.fichaIr; alternarFichaBloco(id, true); document.querySelector(`.ficha-bloco[data-bloco="${id}"]`)?.scrollIntoView({ behavior: "smooth", block: "start" }); return; }
        const repetir = event.target.closest("[data-ficha-repetir]");
        if (repetir) {
          const id = repetir.dataset.fichaRepetir;
          if (id === "cabecalho" && fichaUi.atual) abrirFichaBlocos(fichaUi.atual.filial, fichaUi.atual.cliente);
          else if (FICHA_BLOCOS.some(item => item.id === id)) carregarFichaBloco(id, fichaUi.seq);
          return;
        }
        const cab = event.target.closest("[data-ficha-bloco]");
        if (cab) { alternarFichaBloco(cab.dataset.fichaBloco); return; }
        const copiar = event.target.closest(".cliente-copiar");
        if (copiar) copiarLinhaDigitavel(copiar);
      });
      corpo.addEventListener("input", event => {
        if (!event.target.matches("[data-ficha-filtro]")) return;
        const area = event.target.closest("[data-ficha-filtros]");
        if (!area) return;
        const busca = (area.querySelector('[data-ficha-filtro="nota"]')?.value || "").trim().toLowerCase();
        const inicio = area.querySelector('[data-ficha-filtro="inicio"]')?.value || "";
        const fim = area.querySelector('[data-ficha-filtro="fim"]')?.value || "";
        let visiveis = 0;
        area.querySelectorAll("[data-ficha-nota]").forEach(item => {
          const data = item.dataset.data || "";
          item.hidden = Boolean((busca && !item.dataset.fichaNota.toLowerCase().includes(busca)) || (inicio && (!data || data < inicio)) || (fim && (!data || data > fim)));
          if (!item.hidden) visiveis++;
        });
        const status = area.querySelector("[data-ficha-filtro-status]");
        if (status) status.textContent = `${visiveis} resultado${visiveis === 1 ? "" : "s"}`;
      });
    }
