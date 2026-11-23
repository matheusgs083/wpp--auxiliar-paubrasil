    // Relatórios > "Importar 03.02.37 com itens": envia um CSV por vez para não estourar o tempo da requisição.
    const importar030237Ui = { enviando: false };

    function importar030237Item(texto, classe) {
      const item = document.createElement("li");
      item.textContent = texto;
      if (classe) item.className = classe;
      document.getElementById("importar030237Lista")?.appendChild(item);
      return item;
    }

    function importar030237Resumo(result) {
      const r = result || {};
      if (!r.arquivos) return "já estava importado (ignorado)";
      const meses = (r.meses || []).join(", ") || "sem mês de emissão";
      return `${Number(r.rows || 0).toLocaleString("pt-BR")} linha(s), meses ${meses}`;
    }

    async function importar030237() {
      if (importar030237Ui.enviando) return;
      const input = document.getElementById("importar030237Arquivos");
      const status = document.getElementById("importar030237Status");
      const botao = document.getElementById("importar030237Btn");
      const arquivos = [...(input?.files || [])];
      if (!arquivos.length) { if (status) status.textContent = "Selecione pelo menos um CSV da 03.02.37 com itens."; return; }
      if (!await askConfirmation(`Importar ${arquivos.length} arquivo(s) da 03.02.37? Os resumos de compras dos meses desses arquivos serão refeitos.`)) return;
      importar030237Ui.enviando = true;
      if (botao) botao.disabled = true;
      const lista = document.getElementById("importar030237Lista");
      if (lista) lista.replaceChildren();
      let ok = 0;
      try {
        for (const [indice, arquivo] of arquivos.entries()) {
          if (status) status.textContent = `Importando ${indice + 1} de ${arquivos.length}: ${arquivo.name}...`;
          const item = importar030237Item(`${arquivo.name}: enviando...`, "text-secondary");
          const data = new FormData();
          data.append("arquivo", arquivo);
          try {
            const resposta = await req("/api/admin/promax/030237/importar", { method: "POST", body: data, timeoutMs: 600000 });
            item.textContent = `${arquivo.name}: ${importar030237Resumo(resposta.result)}`;
            item.className = "text-success";
            ok += 1;
          } catch (error) {
            const motivo = error.message || "falha ao importar";
            item.textContent = motivo.startsWith(arquivo.name) ? motivo : `${arquivo.name}: ${motivo}`;
            item.className = "text-danger";
          }
        }
      } finally {
        importar030237Ui.enviando = false;
        if (botao) botao.disabled = false;
      }
      if (status) status.textContent = ok === arquivos.length
        ? `Importação concluída: ${ok} arquivo(s).`
        : `Importação terminou com erro em ${arquivos.length - ok} de ${arquivos.length} arquivo(s). Veja a lista abaixo.`;
      if (ok === arquivos.length && input) input.value = "";
    }

    function setupImportar030237() {
      document.getElementById("importar030237Btn")?.addEventListener("click", importar030237);
    }
