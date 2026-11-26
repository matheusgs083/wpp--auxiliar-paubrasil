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

    async function importar030237Compactar(arquivo) {
      // CSV comprime ~10x: menos tempo subindo o arquivo. Sem suporte no navegador, vai como está.
      if (typeof CompressionStream === "undefined") return arquivo;
      try {
        const compactado = await new Response(arquivo.stream().pipeThrough(new CompressionStream("gzip"))).blob();
        return new File([compactado], `${arquivo.name}.gz`, { type: "application/gzip" });
      } catch (_error) {
        return arquivo;
      }
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
          const item = importar030237Item(`${arquivo.name}: compactando...`, "text-secondary");
          const inicio = performance.now();
          try {
            const envio = await importar030237Compactar(arquivo);
            item.textContent = `${arquivo.name}: enviando e processando...`;
            const data = new FormData();
            data.append("arquivo", envio);
            const resposta = await req("/api/admin/promax/030237/importar", { method: "POST", body: data, timeoutMs: 600000 });
            const segundos = Math.max(1, Math.round((performance.now() - inicio) / 1000));
            item.textContent = `${arquivo.name}: ${importar030237Resumo(resposta.result)} (${segundos}s)`;
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
      document.getElementById("importar012012Btn")?.addEventListener("click", importar012012);
    }

    async function importar012012() {
      const input = document.getElementById("importar012012Arquivos");
      const botao = document.getElementById("importar012012Btn");
      const status = document.getElementById("importar012012Status");
      const lista = document.getElementById("importar012012Lista");
      const arquivos = [...(input?.files || [])];
      if (!arquivos.length) { if (status) status.textContent = "Selecione pelo menos um CSV da 01.20.12."; return; }
      if (botao?.disabled) return;
      if (botao) botao.disabled = true;
      lista?.replaceChildren();
      let importados = 0;
      try {
        for (const [indice, arquivo] of arquivos.entries()) {
          if (status) status.textContent = `Importando ${indice + 1} de ${arquivos.length}: ${arquivo.name}...`;
          const item = document.createElement("li");
          item.textContent = `${arquivo.name}: importando...`;
          lista?.appendChild(item);
          try {
            const data = new FormData();
            data.append("arquivo", arquivo);
            const resposta = await req("/api/admin/promax/012012/importar", { method: "POST", body: data, timeoutMs: 600000 });
            const resultado = resposta.result || {};
            item.textContent = `${arquivo.name}: ${Number(resultado.rows || 0).toLocaleString("pt-BR")} clientes, ${Number(resultado.com_coordenadas || 0).toLocaleString("pt-BR")} com coordenadas.`;
            item.className = "text-success";
            importados++;
          } catch (erro) {
            item.textContent = `${arquivo.name}: ${erro.message || "falha ao importar"}`;
            item.className = "text-danger";
          }
        }
      } finally {
        if (botao) botao.disabled = false;
      }
      if (status) status.textContent = importados === arquivos.length ? `Importação concluída: ${importados} arquivo(s).` : `Importados ${importados} de ${arquivos.length} arquivos. Confira os erros abaixo.`;
      if (importados === arquivos.length && input) input.value = "";
    }
