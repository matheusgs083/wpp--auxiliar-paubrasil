    // Celular: a barra inferior usa as mesmas abas e permissões do painel.
    // O menu é montado das próprias abas de #adminTabs, então segue as mesmas permissões.
    function renderNavCelular() {
      const lista = document.getElementById("navCelularLista");
      if (!lista) return;
      const rotulos = {};
      document.querySelectorAll("#panelGroups [data-grupo]").forEach(botao => { rotulos[botao.dataset.grupo] = botao.textContent.trim(); });
      const porGrupo = new Map();
      document.querySelectorAll("#adminTabs > .nav-item").forEach(item => {
        if (!abaLiberada(item)) return;
        const grupo = String(item.dataset.grupo || "");
        if (!porGrupo.has(grupo)) porGrupo.set(grupo, []);
        porGrupo.get(grupo).push(item.querySelector(".nav-link"));
      });
      const comTitulo = porGrupo.size > 1;
      const ativa = document.querySelector("#adminTabs .nav-link.active");
      lista.replaceChildren();
      porGrupo.forEach((abas, grupo) => {
        const secao = document.createElement("div");
        secao.className = "nav-celular-grupo";
        if (comTitulo) {
          const titulo = document.createElement("div");
          titulo.className = "nav-celular-titulo";
          titulo.textContent = rotulos[grupo] || grupo;
          secao.appendChild(titulo);
        }
        abas.forEach(aba => {
          const link = document.createElement("a");
          link.className = "nav-celular-link";
          link.href = aba.getAttribute("href") || "#";
          link.dataset.aba = aba.id;
          const icone = aba.querySelector("i.bi");
          if (icone) {
            const copia = icone.cloneNode(true);
            copia.classList.remove("me-1");
            copia.setAttribute("aria-hidden", "true");
            link.appendChild(copia);
          }
          link.appendChild(document.createTextNode(aba.textContent.trim()));
          if (aba === ativa) link.setAttribute("aria-current", "page");
          secao.appendChild(link);
        });
        lista.appendChild(secao);
      });
      const atual = document.getElementById("navCelularAtual");
      if (atual) atual.textContent = ativa ? ativa.textContent.trim() : "Menu";
    }

    function setupNavCelular() {
      const lista = document.getElementById("navCelularLista");
      if (!lista) return;
      lista.addEventListener("click", event => {
        const link = event.target.closest(".nav-celular-link");
        if (!link || !isPlainLeftClick(event)) return;
        event.preventDefault();
        navigatePanelPage(link.dataset.aba);
      });
      renderNavCelular();
    }
