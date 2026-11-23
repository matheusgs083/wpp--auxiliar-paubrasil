    // Ficha do cliente em blocos empilhados (Rota Financeira e Clientes).
    // Fluxo: cabeçalho com contato → blocos com resumo → detalhe dentro do bloco.
    // O servidor confere o escopo em cada chamada; aqui só se mostra o que ele devolveu.

    const FICHA_BLOCOS = [
      { id: "titulos", titulo: "Títulos em aberto", icone: "bi-receipt" },
      { id: "credito", titulo: "Análise de crédito", icone: "bi-speedometer2" },
      { id: "compras", titulo: "Compras", icone: "bi-bag-check" },
      { id: "vasilhames", titulo: "Vasilhames", icone: "bi-recycle" },
      { id: "equipamentos", titulo: "Equipamentos", icone: "bi-plug" },
      { id: "comodatos", titulo: "Comodatos", icone: "bi-box-seam" },
      { id: "devolucoes", titulo: "Devoluções", icone: "bi-arrow-return-left" },
      { id: "cadastro", titulo: "Cadastro e documentos", icone: "bi-person-vcard" }
    ];
    const FICHA_DOC_TOM = { OK: "ok", PENDENTE: "warn" };

    function fichaUrl(filial, cliente, sufixo) {
      return `${CONFIG.endpoints.clientes.ficha}/${encodeURIComponent(filial)}/${encodeURIComponent(cliente)}/${sufixo}`;
    }

    function fichaMaxAbertos() {
      return window.matchMedia("(max-width: 767.98px)").matches ? 1 : 2;
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

    async function abrirFichaBlocos(filial, cliente, { bloco = "" } = {}) {
      const painel = document.getElementById("fichaCliente");
      const corpo = document.getElementById("fichaClienteCorpo");
      if (!painel || !corpo) return;
      const sequencia = ++fichaUi.seq;
      fichaUi.atual = { filial: String(filial), cliente: String(cliente) };
      fichaUi.blocos = {};
      fichaUi.abertos = [];
      fichaUi.pedido = bloco;
      corpo.innerHTML = '<div class="text-secondary py-3" role="status"><span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>Abrindo o cliente...</div>';
      bootstrap.Offcanvas.getOrCreateInstance(painel).show();
      try {
        const resposta = await req(fichaUrl(filial, cliente, "cabecalho"));
        if (sequencia !== fichaUi.seq) return;
        fichaUi.cliente = resposta.cliente || {};
        corpo.innerHTML = renderFichaCabecalho(fichaUi.cliente) + `<div class="ficha-blocos">${FICHA_BLOCOS.map(renderFichaBlocoCasca).join("")}</div>`;
        FICHA_BLOCOS.forEach(item => carregarFichaBloco(item.id, sequencia));
      } catch (error) {
        if (sequencia !== fichaUi.seq) return;
        corpo.innerHTML = `<div class="alert alert-danger mb-0" role="alert"><i class="bi bi-shield-exclamation me-2" aria-hidden="true"></i>${escapeHtml(error.message || "Não foi possível abrir o cliente.")}</div>`;
      }
    }

    function renderFichaCabecalho(c) {
      const nome = c.nome || c.razao_social || "Cliente";
      const titulo = document.getElementById("fichaClienteTitulo");
      if (titulo) titulo.textContent = nome;
      const acoes = [
        c.telefone_whatsapp ? `<a class="btn btn-success btn-sm" href="https://wa.me/${encodeURIComponent(c.telefone_whatsapp)}" target="_blank" rel="noopener" aria-label="WhatsApp de ${escapeHtml(nome)}"><i class="bi bi-whatsapp me-1" aria-hidden="true"></i>WhatsApp</a>` : "",
        c.telefone_discagem ? `<a class="btn btn-outline-secondary btn-sm" href="tel:${encodeURIComponent(c.telefone_discagem)}" aria-label="Ligar para ${escapeHtml(nome)}"><i class="bi bi-telephone me-1" aria-hidden="true"></i>Ligar</a>` : "",
        c.mapa_url ? `<a class="btn btn-outline-secondary btn-sm" href="${escapeHtml(c.mapa_url)}" target="_blank" rel="noopener" aria-label="Abrir endereço de ${escapeHtml(nome)} no mapa"><i class="bi bi-geo-alt me-1" aria-hidden="true"></i>Mapa</a>` : ""
      ].join("");
      const fatos = [["Filial", c.filial], ["Setor / RN", clientesChave(c.setor)], ["GV", clientesChave(c.gv)], ["Cidade", c.cidade], ["Visita", c.dia_visita], ["Status", c.status], ["Telefone", c.telefone]];
      return `<header class="ficha-cabecalho">
          <div class="ficha-cabecalho-nome"><span class="mono">NB ${escapeHtml(c.cliente || "")}</span><h2 class="h5 fw-bold mb-0">${escapeHtml(nome)}</h2>${c.razao_social && c.razao_social !== nome ? `<div class="small text-secondary">${escapeHtml(c.razao_social)}</div>` : ""}</div>
          ${fichaFatos(fatos)}
          ${acoes ? `<div class="ficha-acoes">${acoes}</div>` : ""}
        </header>`;
    }

    function renderFichaBlocoCasca(item) {
      return `<section class="ficha-bloco" data-bloco="${item.id}" data-estado="carregando">
          <h3 class="ficha-bloco-h"><button class="ficha-bloco-cab" type="button" aria-expanded="false" aria-controls="fichaBloco-${item.id}" data-ficha-bloco="${item.id}">
            <span class="ficha-bloco-icone"><i class="bi ${item.icone}" aria-hidden="true"></i></span>
            <span class="ficha-bloco-texto"><span class="ficha-bloco-titulo">${escapeHtml(item.titulo)}</span><span class="ficha-bloco-resumo"><span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>Carregando...</span></span>
            <i class="bi bi-chevron-down ficha-bloco-chevron" aria-hidden="true"></i>
          </button></h3>
          <div class="ficha-bloco-corpo" id="fichaBloco-${item.id}" role="region" aria-label="${escapeHtml(item.titulo)}" hidden></div>
        </section>`;
    }

    async function carregarFichaBloco(id, sequencia) {
      const { filial, cliente } = fichaUi.atual || {};
      const secao = document.querySelector(`.ficha-bloco[data-bloco="${id}"]`);
      if (!secao) return;
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
      fichaAbrirInicial();
    }

    // Abre um bloco quando a ficha fica pronta: o pedido (ex.: botão Boleto da rota), senão
    // Títulos se houver pendência, senão Compras, senão Cadastro.
    function fichaAbrirInicial() {
      if (fichaUi.abertos.length || fichaUi.inicialFeito === fichaUi.seq) return;
      const b = fichaUi.blocos;
      let alvo = "";
      if (fichaUi.pedido && b[fichaUi.pedido]) alvo = fichaUi.pedido;
      else if (!fichaUi.pedido && b.titulos) {
        if (b.titulos.estado === "ok") alvo = "titulos";
        else if (b.compras) alvo = b.compras.estado === "ok" ? "compras" : (b.cadastro ? "cadastro" : "");
      }
      if (!alvo) return;
      fichaUi.inicialFeito = fichaUi.seq;
      alternarFichaBloco(alvo, true);
    }

    function alternarFichaBloco(id, abrir) {
      const botao = document.querySelector(`[data-ficha-bloco="${id}"]`);
      const corpo = document.getElementById(`fichaBloco-${id}`);
      if (!botao || !corpo) return;
      const vaiAbrir = abrir === undefined ? corpo.hidden : abrir;
      fichaUi.abertos = fichaUi.abertos.filter(item => item !== id);
      if (vaiAbrir) {
        fichaUi.abertos.push(id);
        while (fichaUi.abertos.length > fichaMaxAbertos()) alternarFichaBloco(fichaUi.abertos[0], false);
        corpo.innerHTML = renderFichaBlocoCorpo(id);
      }
      corpo.hidden = !vaiAbrir;
      botao.setAttribute("aria-expanded", String(vaiAbrir));
      botao.closest(".ficha-bloco")?.classList.toggle("is-open", vaiAbrir);
    }

    function renderFichaBlocoCorpo(id) {
      const bloco = fichaUi.blocos[id];
      if (!bloco) return '<div class="text-secondary small py-2" role="status"><span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>Carregando...</div>';
      if (bloco.erro) return `<div class="alert alert-danger py-2 mb-0" role="alert">${escapeHtml(bloco.resumo)}</div>`;
      if (bloco.estado === "indisponivel") return `<div class="alert alert-warning py-2 mb-0" role="status"><i class="bi bi-database-exclamation me-1" aria-hidden="true"></i>${escapeHtml(bloco.fonte?.mensagem || bloco.resumo || "Fonte indisponível.")}</div>${fichaRodape(bloco)}`;
      const render = FICHA_RENDER[id];
      return `${render ? render(bloco.dados || {}, bloco) : ""}${fichaRodape(bloco)}`;
    }

    function fichaRodape(bloco) {
      const fonte = bloco.fonte || {};
      const quando = fonte.atualizado_em ? ` · atualizado em ${fonte.atualizado_em}` : "";
      return `<div class="ficha-rodape"><i class="bi bi-database me-1" aria-hidden="true"></i>Fonte: ${escapeHtml(fonte.nome || "-")}${escapeHtml(quando)}</div>`;
    }

    const FICHA_RENDER = {
      titulos(d, bloco) {
        const titulos = d.titulos || [];
        if (!titulos.length) return clientesVazio("Nenhum título em aberto na 12.06.01.");
        const c = fichaUi.cliente || {};
        return `<div class="ficha-lista">${titulos.map(t => {
          const s = CLIENTES_SITUACAO[t.situacao] || CLIENTES_SITUACAO.sem_data;
          const acoes = t.boleto ? clientesAcoesBoleto(c, t.boleto) : clientesTag(t.situacao_boleto || "Boleto não importado", "neutral", "bi-file-earmark-x");
          return `<article class="ficha-item" data-situacao="${escapeHtml(t.situacao)}">
              <div class="ficha-item-topo"><strong class="mono">NF ${escapeHtml(t.nota_fiscal || "-")}</strong>${clientesTag(s.rotulo, s.tom, s.icone)}</div>
              ${fichaFatos([["Emissão", t.emissao], ["Vencimento", t.vencimento], ["Dias", t.dias === null || t.dias === undefined ? "-" : t.dias < 0 ? `${-t.dias} de atraso` : t.dias], ["Original", formatMoneyText(t.valor_original)], ["Pendente", formatMoneyText(t.valor_pendente)], ["Corrigido", formatMoneyText(t.valor_corrigido)]])}
              <div class="ficha-item-acoes">${acoes}</div>
            </article>`;
        }).join("")}</div>${bloco.dados && bloco.dados.boletos_disponivel === false ? '<div class="small text-warning-emphasis mt-2">Base de boletos (03.02.06) indisponível agora.</div>' : ""}`;
      },
      credito(d) {
        const disponivel = d.limite_disponivel ? `${formatMoneyText(d.limite_disponivel)}${d.limite_disponivel_calculado ? " (calculado)" : ""}` : "-";
        const fatos = fichaFatos([["Limite total", d.limite_total ? formatMoneyText(d.limite_total) : "-"], ["Limite utilizado", d.limite_utilizado ? `${formatMoneyText(d.limite_utilizado)} (12.06.01)` : "-"], ["Limite disponível", disponivel], ["Condição de pagamento", d.condicao_pagamento], ["Prazo atual", d.prazo_atual], ["Pag. em atraso", d.percentual_pag_atraso]]);
        const fat = (d.faturamento || []).length
          ? `<h4 class="ficha-sub">Faturamento entregue (03.02.37)</h4><ul class="ficha-linhas">${d.faturamento.map(f => `<li><span>${escapeHtml(f.kpi || "-")}</span><strong>${escapeHtml(f.faturamento_com_pdv || "-")}</strong><small>${escapeHtml(f.pedidos === "" ? "" : `${f.pedidos} nota(s)`)}</small></li>`).join("")}</ul>`
          : `<h4 class="ficha-sub">Faturamento entregue (03.02.37)</h4><div class="small text-secondary">${d.faturamento_fonte === "indisponivel" ? "Base da 03.02.37 indisponível agora." : "Sem compras importadas."}</div>`;
        return `${fatos}${fat}<div class="small text-secondary mt-2">Disponível = limite total − pendente da 12.06.01. Faturamento e notas da 03.02.37. Sem score: só os indicadores das bases.</div>`;
      },
      compras(d, bloco) {
        if (bloco.estado === "vazio") return clientesVazio("Nenhuma compra deste cliente na 03.02.37 importada.");
        const atual = d.mes_atual || {};
        const media = d.media_3_meses === null || d.media_3_meses === undefined
          ? `<span class="text-secondary">Base desde ${escapeHtml(fichaMesBr(d.base_desde))}</span>`
          : escapeHtml(formatMoneyText(d.media_3_meses));
        const kpis = `<div class="ficha-kpis">
            <div><span>Mês atual (parcial)</span><strong>${escapeHtml(formatMoneyText(atual.total || 0))}</strong></div>
            <div><span>Média mensal entregue</span><strong>${media}</strong><small>3 meses fechados</small></div>
            <div><span>Notas (3 meses)</span><strong>${escapeHtml(fichaNumero(d.notas_3_meses))}</strong></div>
            <div><span>Qtde entregue (3 meses)</span><strong>${escapeHtml(fichaNumero(d.qtde_3_meses))}</strong></div>
            <div><span>Última entrega</span><strong>${escapeHtml(fichaDataBr(d.ultima_entrega))}</strong></div>
          </div>`;
        const aviso = d.historico_suficiente ? "" : `<div class="small text-secondary mb-2">A média aparece quando a base tiver os 3 meses fechados. Base desde ${escapeHtml(fichaMesBr(d.base_desde))}.</div>`;
        const tops = [["Maior faturamento", d.top_faturamento || [], p => formatMoneyText(p.total)], ["Maior quantidade", d.top_quantidade || [], p => `${fichaNumero(p.qtde)} ${p.unidade || ""}`]]
          .map(([rotulo, itens, valor]) => `<div><h4 class="ficha-sub">${rotulo}</h4>${itens.length ? `<ol class="ficha-top">${itens.map(p => `<li><span>${escapeHtml(p.descricao || `Produto ${p.produto}`)}</span><strong>${escapeHtml(valor(p))}</strong></li>`).join("")}</ol>` : '<div class="small text-secondary">Sem produtos no período.</div>'}</div>`).join("");
        return `${kpis}${aviso}<h4 class="ficha-sub">Faturamento entregue por mês</h4>${fichaGraficoCompras(d.serie || [])}<div class="ficha-tops">${tops}</div>`;
      },
      vasilhames(d, bloco) {
        if (bloco.estado === "vazio") return clientesVazio("O cliente não tem garrafeiras em comodato na 02.02.20.");
        const cartoes = (d.tipos || []).filter(t => Number(String(t.caixas).replace(",", ".")) > 0).map(t => {
          const situacao = t.em_risco ? clientesTag(`Faltam ${t.falta} cx`, "warn", "bi-exclamation-triangle") : clientesTag("Giro batido", "ok", "bi-check2");
          const barra = t.percentual === null ? "" : `<div class="ficha-progresso" role="progressbar" aria-label="Giro de ${escapeHtml(t.rotulo)}: ${t.percentual}%" aria-valuenow="${t.percentual}" aria-valuemin="0" aria-valuemax="100"><span style="width:${t.percentual}%"></span></div>`;
          return `<article class="ficha-item"><div class="ficha-item-topo"><strong>${escapeHtml(t.rotulo)}</strong>${situacao}</div>${barra}
              ${fichaFatos([["Caixas em comodato", t.caixas], [`Meta (${d.multiplicador || 2}×)`, t.meta], ["Compradas no mês", t.compradas], ["Falta", t.falta]])}</article>`;
        }).join("");
        return `<div class="ficha-lista">${cartoes}</div><div class="small text-secondary mt-2">${escapeHtml(d.explicacao || "")}</div>`;
      },
      equipamentos() {
        return clientesVazio("Ainda não há base de equipamentos instalados importada. Quando houver, eles aparecem aqui.");
      },
      comodatos(d, bloco) {
        if (bloco.estado === "vazio") return clientesVazio("Nenhum comodato em aberto na 02.02.20.");
        return `<div class="ficha-lista">${(d.itens || []).map(i => `<article class="ficha-item">
            <div class="ficha-item-topo"><strong>${escapeHtml(i.material || "-")}</strong>${i.vencido ? clientesTag("Contrato vencido", "err", "bi-calendar-x") : (i.vencimento ? clientesTag("Em dia", "ok", "bi-calendar-check") : "")}</div>
            ${fichaFatos([["Subtipo", i.sub_tipo], ["Comodato", i.nro_comodato], ["Saldo", i.saldo], ["Vencimento", i.vencimento || "não informado"]])}
          </article>`).join("")}</div><div class="small text-secondary mt-2">Saldo total: ${escapeHtml(d.saldo_total || "0")}</div>`;
      },
      devolucoes(d, bloco) {
        if (!(d.itens || []).length) return clientesVazio(`Nenhuma devolução nos últimos ${d.dias || 60} dias.`);
        return `<div class="ficha-lista">${d.itens.map(i => `<article class="ficha-item">
            <div class="ficha-item-topo"><strong class="mono">NF ${escapeHtml(i.nota || "-")}</strong><span class="small text-secondary">${escapeHtml(fichaDataBr(i.data))}</span></div>
            ${fichaFatos([["Motivo", i.motivo], ["Responsabilidade", i.responsabilidade || "-"], ["NF de origem", i.nf_referencia || "-"], ["Volume", fichaNumero(i.qtde)], ["Valor", formatMoneyText(i.total)]])}
            ${i.justificativa ? `<p class="ficha-justificativa"><i class="bi bi-chat-left-text me-1" aria-hidden="true"></i>${escapeHtml(i.justificativa)}</p>` : ""}
          </article>`).join("")}</div>`;
      },
      cadastro(d) {
        const fatos = fichaFatos([["Razão social", d.razao_social], ["Nome fantasia", d.nome_fantasia], ["CPF/CNPJ", d.documento], ["Endereço", [d.endereco, d.complemento].filter(Boolean).join(" - ")], ["CEP", d.cep], ["Bairro", d.bairro], ["Cidade", d.cidade_uf || d.cidade], ["Telefone", d.telefone], ["E-mail", d.email], ["Setor / RN", clientesChave(d.setor)], ["GV", clientesChave(d.gv)], ["Dia de visita", d.dia_visita], ["Status cadastral", d.status]]);
        const docs = !d.documentos_disponivel
          ? '<div class="small text-warning-emphasis">Base de documentação pendente indisponível agora.</div>'
          : (d.documentos || []).length
            ? `<ul class="ficha-docs">${d.documentos.map(doc => `<li><span>${escapeHtml(doc.rotulo)}</span>${clientesTag(doc.status || "-", FICHA_DOC_TOM[String(doc.status || "").toUpperCase()] || "neutral")}</li>`).join("")}</ul>`
            : '<div class="small text-secondary">Cliente fora da base de documentação pendente.</div>';
        return `${fatos}<h4 class="ficha-sub">Documentos</h4>${docs}<div class="small text-secondary mt-2">Só o status de cada documento; os arquivos não ficam aqui.</div>`;
      }
    };

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
        const cab = event.target.closest("[data-ficha-bloco]");
        if (cab) { alternarFichaBloco(cab.dataset.fichaBloco); return; }
        const copiar = event.target.closest(".cliente-copiar");
        if (copiar) copiarLinhaDigitavel(copiar);
      });
    }
