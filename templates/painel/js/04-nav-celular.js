    // Categorias no menu lateral; a barra inferior mostra as telas da categoria ativa.
    function renderNavCelular() {
      const lista = document.getElementById("navCelularLista");
      const categorias = document.getElementById("navCategoriasLista");
      const grupos = document.getElementById("panelGroups");
      if (!lista || !categorias || !grupos) return;
      const ativa = document.querySelector("#adminTabs .nav-link.active");
      const grupoAtual = grupos.dataset.selecionado || (ativa && grupoDaAba(ativa.id)) || "";
      lista.replaceChildren();
      categorias.replaceChildren();
      const menu = document.createElement("button");
      menu.type = "button"; menu.className = "nav-celular-link nav-categorias-abrir";
      menu.setAttribute("data-bs-toggle", "offcanvas"); menu.setAttribute("data-bs-target", "#navCategorias");
      menu.setAttribute("aria-controls", "navCategorias");
      menu.innerHTML = '<i class="bi bi-grid" aria-hidden="true"></i><span>Categorias</span>';
      lista.appendChild(menu);
      grupos.querySelectorAll("[data-grupo]").forEach(botao => {
        const grupo = botao.dataset.grupo;
        const itens = Array.from(document.querySelectorAll("#adminTabs > .nav-item")).filter(item => item.dataset.grupo === grupo && abaLiberada(item));
        if (!itens.length) return;
        const categoria = document.createElement("button");
        categoria.type = "button"; categoria.className = "nav-categoria-link"; categoria.dataset.grupo = grupo;
        categoria.innerHTML = botao.innerHTML; categoria.setAttribute("aria-pressed", String(grupo === grupoAtual));
        categorias.appendChild(categoria);
        if (grupo !== grupoAtual) return;
        itens.forEach(item => {
          const aba = item.querySelector(".nav-link"); if (!aba) return;
          const link = document.createElement("a"); link.className = "nav-celular-link";
          link.href = aba.getAttribute("href") || "#"; link.dataset.aba = aba.id;
          const icone = aba.querySelector("i.bi");
          if (icone) { const copia = icone.cloneNode(true); copia.classList.remove("me-1"); copia.setAttribute("aria-hidden", "true"); link.appendChild(copia); }
          const rotulo = document.createElement("span"); rotulo.textContent = aba.textContent.trim(); link.appendChild(rotulo);
          if (aba === ativa) link.setAttribute("aria-current", "page");
          lista.appendChild(link);
        });
      });
    }

    function setupNavCelular() {
      const lista = document.getElementById("navCelularLista");
      const categorias = document.getElementById("navCategoriasLista");
      if (!lista || !categorias) return;
      lista.addEventListener("click", event => {
        const link = event.target.closest("a[data-aba]");
        if (!link || !isPlainLeftClick(event)) return;
        event.preventDefault(); navigatePanelPage(link.dataset.aba);
      });
      categorias.addEventListener("click", event => {
        const botao = event.target.closest("button[data-grupo]"); if (!botao) return;
        const original = Array.from(document.querySelectorAll("#panelGroups [data-grupo]")).find(item => item.dataset.grupo === botao.dataset.grupo);
        if (original) original.click();
        if (window.bootstrap) bootstrap.Offcanvas.getOrCreateInstance(document.getElementById("navCategorias")).hide();
      });
      renderNavCelular();
    }
