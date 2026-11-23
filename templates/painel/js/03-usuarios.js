    function syncAllowedUsersCardSizing() {
      if (!E.accessEditorCard || !E.allowedUsersCard || !E.allowedUsersContainer) return;

      E.allowedUsersCard.style.height = "";
      E.allowedUsersContainer.style.maxHeight = "";

      const leftRect = E.accessEditorCard.getBoundingClientRect();
      const targetHeight = Math.max(0, Math.floor(leftRect.height));
      if (!targetHeight) return;

      E.allowedUsersCard.style.height = `${targetHeight}px`;

      const header = E.allowedUsersCard.querySelector("header");
      const headerHeight = header ? Math.ceil(header.getBoundingClientRect().height) : 0;
      const verticalPadding = 8;
      const maxTableHeight = Math.max(140, targetHeight - headerHeight - verticalPadding);
      E.allowedUsersContainer.style.maxHeight = `${maxTableHeight}px`;
    }

    function setupAllowedUsersCardSizing() {
      syncAllowedUsersCardSizing();
      requestAnimationFrame(() => syncAllowedUsersCardSizing());

      if (allowedUsersCardResizeObserver) {
        allowedUsersCardResizeObserver.disconnect();
        allowedUsersCardResizeObserver = null;
      }

      if (typeof ResizeObserver !== "undefined" && E.accessEditorCard) {
        allowedUsersCardResizeObserver = new ResizeObserver(() => syncAllowedUsersCardSizing());
        allowedUsersCardResizeObserver.observe(E.accessEditorCard);
      }

      window.addEventListener("resize", syncAllowedUsersCardSizing);
    }

    function roleToApi(roleUi) {
      const role = normalizeTextForSearch(roleUi).replace(/\s+/g, "_");
      if (role === "vendedor" || role === "rn") return "vendedor";
      if (role === "gerente_vendas" || role === "gerente_de_vendas" || role === "gv") return "gerente_vendas";
      if (role === "diretor_comercial" || role === "dc") return "diretor_comercial";
      if (role === "financeiro" || role === "fin") return "financeiro";
      if (role === "armazem" || role === "armazen" || role === "almoxarifado" || role === "estoque") return "armazem";
      return "admin";
    }

    function roleFromApi(user) {
      if (user.role) return String(user.role).toUpperCase();
      const roles = Array.isArray(user.roles) ? user.roles : [];
      const primary = String(roles[0] || "vendedor").toLowerCase();
      if (primary === "vendedor") return "VENDEDOR";
      if (primary === "gerente_vendas") return "GERENTE_VENDAS";
      if (primary === "diretor_comercial") return "DIRETOR_COMERCIAL";
      if (primary === "financeiro") return "FINANCEIRO";
      if (primary === "armazem") return "ARMAZEM";
      return "ADMIN";
    }

    function normalizeScopeTokenForApi(token) {
      return String(token || "").trim().replace(/-/g, "_");
    }

    function normalizeScopeTokenForUi(token) {
      return String(token || "").trim().replace(/_/g, "-");
    }

    function normalizePhoneDigits(value) {
      return String(value || "").replace(/\D/g, "");
    }

    function comparablePhoneDigits(value) {
      const digits = normalizePhoneDigits(value);
      if (digits.startsWith("55") && digits.length === 13 && digits.charAt(4) === "9") {
        return `${digits.slice(0, 4)}${digits.slice(5)}`;
      }
      return digits;
    }

    function formatPhoneForUi(value) {
      const digits = normalizePhoneDigits(value);
      if (!digits) return "-";
      if (digits.startsWith("55")) {
        const local = digits.slice(2);
        if (local.length === 11) return `+55 (${local.slice(0, 2)}) ${local.slice(2, 7)}-${local.slice(7)}`;
        if (local.length === 10) return `+55 (${local.slice(0, 2)}) ${local.slice(2, 6)}-${local.slice(6)}`;
      }
      if (digits.length === 11) return `(${digits.slice(0, 2)}) ${digits.slice(2, 7)}-${digits.slice(7)}`;
      if (digits.length === 10) return `(${digits.slice(0, 2)}) ${digits.slice(2, 6)}-${digits.slice(6)}`;
      return digits;
    }

    function normalizeUserForUi(user) {
      const role = roleFromApi(user);
      const sectors = Array.isArray(user.sectors) ? user.sectors : [];
      const gvVdes = Array.isArray(user.gv_vdes) ? user.gv_vdes : [];
      const fallbackScope = (role === "VENDEDOR" || role === "FINANCEIRO" || role === "ARMAZEM") ? sectors : gvVdes;
      const rawPhone = user.whatsapp_phone_number || user.phone_number || "";
      return {
        phone: rawPhone,
        phone_display: formatPhoneForUi(rawPhone),
        phone_comparable: comparablePhoneDigits(rawPhone),
        name: user.display_name || user.name || "",
        role,
        scope: Array.isArray(user.commercial_scope) && user.commercial_scope.length
          ? user.commercial_scope
          : fallbackScope.map(normalizeScopeTokenForUi),
        active: user.is_active !== false
      };
    }

    function buildRolesOption() {
      E.accessRole.innerHTML = Object.entries(CONFIG.roles).map(([k,v]) => `<option value="${escapeHtml(k)}">${escapeHtml(v)}</option>`).join("");
    }

    function updateScopeHint() {
      const role = E.accessRole.value;
      if (role === "VENDEDOR") E.accessScopeHint.innerHTML = 'Vendedor aceita uma ou mais chaves filial-setor. Ex.: <span class="mono">3-400, 3-401</span>.';
      else if (role === "GERENTE_VENDAS") E.accessScopeHint.innerHTML = 'Gerente de Vendas aceita uma ou mais chaves filial-GV. Ex.: <span class="mono">3-4, 4-5</span>.';
      else if (role === "DIRETOR_COMERCIAL") E.accessScopeHint.innerHTML = 'Diretor Comercial aceita uma ou mais chaves filial-DC. Ex.: <span class="mono">3-1, 4-2</span>.';
      else if (role === "FINANCEIRO") E.accessScopeHint.innerHTML = 'Financeiro aceita uma ou mais filiais. Ex.: <span class="mono">3, 4</span>.';
      else if (role === "ARMAZEM") E.accessScopeHint.innerHTML = 'Armazem aceita uma ou mais filiais. Ex.: <span class="mono">3, 4</span>.';
      else E.accessScopeHint.textContent = "Admin tem acesso total e não usa escopo.";
    }

    function renderPanelUserFeatureChecks(selected = []) {
      if (!E.panelUserFeatures) return;
      const adminMode = Boolean(E.panelUserAdmin && E.panelUserAdmin.checked);
      const selectedSet = new Set((selected || []).map(item => String(item || "").toLowerCase()));
      const disabled = adminMode ? "disabled" : "";
      const disabledClass = adminMode ? " is-disabled" : "";
      const cartao = feature => {
        const checked = (adminMode || selectedSet.has(feature.id)) ? "checked" : "";
        const icon = feature.icon || "bi-check2-square";
        return `<label class="panel-user-feature-card${disabledClass}"><input class="form-check-input panel-user-feature" type="checkbox" value="${escapeHtml(feature.id)}" data-grupo="${escapeHtml(feature.grupo || "")}" aria-label="${escapeHtml(feature.label)}" ${checked} ${disabled}><span class="panel-user-feature-icon"><i class="bi ${escapeHtml(icon)}"></i></span><span class="panel-user-feature-main"><span class="panel-user-feature-title">${escapeHtml(feature.label)}</span><span class="panel-user-feature-description">${escapeHtml(feature.description || "")}</span></span></label>`;
      };
      // Cada aba (grupo) tem uma caixa que marca ou desmarca todas as sub-abas dela.
      E.panelUserFeatures.innerHTML = PANEL_FEATURE_GROUPS.map(grupo => {
        const itens = PANEL_FEATURES.filter(feature => feature.grupo === grupo.id);
        if (!itens.length) return "";
        return `<fieldset class="panel-user-feature-grupo"><legend><label class="panel-user-feature-grupo-titulo${disabledClass}"><input class="form-check-input panel-user-feature-grupo-check" type="checkbox" data-grupo="${escapeHtml(grupo.id)}" ${disabled}><i class="bi ${escapeHtml(grupo.icon)}" aria-hidden="true"></i><span>Aba ${escapeHtml(grupo.label)}</span><small class="panel-user-feature-grupo-conta" data-grupo-conta="${escapeHtml(grupo.id)}"></small></label></legend><div class="panel-user-feature-grid">${itens.map(cartao).join("")}</div></fieldset>`;
      }).join("");
      E.panelUserFeatures.querySelectorAll(".panel-user-feature").forEach(input => {
        input.addEventListener("change", updatePanelUserFeatureCount);
      });
      E.panelUserFeatures.querySelectorAll(".panel-user-feature-grupo-check").forEach(input => {
        input.addEventListener("change", () => {
          E.panelUserFeatures.querySelectorAll(`.panel-user-feature[data-grupo="${CSS.escape(input.dataset.grupo)}"]`).forEach(item => { item.checked = input.checked; });
          updatePanelUserFeatureCount();
        });
      });
      updatePanelUserFeatureCount();
    }

    // Caixa da aba: marcada quando todas as sub-abas estão marcadas, "meio marcada" quando só algumas.
    function atualizarGruposDePermissao() {
      if (!E.panelUserFeatures) return;
      E.panelUserFeatures.querySelectorAll(".panel-user-feature-grupo-check").forEach(caixa => {
        const itens = Array.from(E.panelUserFeatures.querySelectorAll(`.panel-user-feature[data-grupo="${CSS.escape(caixa.dataset.grupo)}"]`));
        const marcados = itens.filter(item => item.checked).length;
        caixa.checked = itens.length > 0 && marcados === itens.length;
        caixa.indeterminate = marcados > 0 && marcados < itens.length;
        const conta = E.panelUserFeatures.querySelector(`[data-grupo-conta="${CSS.escape(caixa.dataset.grupo)}"]`);
        if (conta) conta.textContent = `${marcados} de ${itens.length}`;
      });
    }

    function selectedPanelUserFeatures() {
      if (!E.panelUserFeatures) return [];
      return Array.from(E.panelUserFeatures.querySelectorAll(".panel-user-feature:checked"))
        .map(input => String(input.value || "").trim())
        .filter(Boolean);
    }

    function updatePanelUserFeatureCount() {
      const total = PANEL_FEATURES.length;
      const adminMode = Boolean(E.panelUserAdmin && E.panelUserAdmin.checked);
      const selectedCount = adminMode ? total : selectedPanelUserFeatures().length;
      if (E.panelUserFeatureCount) {
        E.panelUserFeatureCount.textContent = adminMode ? `Todos (${total})` : `${selectedCount} de ${total}`;
      }
      atualizarGruposDePermissao();
      if (E.panelUserAdminHint) {
        E.panelUserAdminHint.textContent = adminMode
          ? "Administrador acessa todos os blocos. As permissões ficam travadas neste perfil."
          : "Marque apenas os blocos que o usuário realmente precisa acessar.";
      }
    }

    function panelUserPayload() {
      const isAdmin = Boolean(E.panelUserAdmin && E.panelUserAdmin.checked);
      return {
        username: E.panelUsername ? E.panelUsername.value.trim() : "",
        display_name: E.panelDisplayName ? E.panelDisplayName.value.trim() : "",
        is_admin: isAdmin,
        is_active: E.panelUserActive ? Boolean(E.panelUserActive.checked) : true,
        filiais: E.panelUserFiliais ? parsePanelFiliais(E.panelUserFiliais.value) : [],
        seller_scopes: E.panelUserSellerScopes ? parsePanelFiliais(E.panelUserSellerScopes.value) : [],
        features: isAdmin ? PANEL_FEATURES.map(feature => feature.id) : selectedPanelUserFeatures()
      };
    }

    function showPanelUserTemporaryCredentials(username, password, { openModal = true } = {}) {
      const cleanUsername = String(username || "").trim();
      const cleanPassword = String(password || "").trim();
      state.panelUserTemporaryCredentials = cleanUsername && cleanPassword
        ? { username: cleanUsername, password: cleanPassword }
        : null;
      if (!state.panelUserTemporaryCredentials) {
        if (E.panelUserPasswordBox) E.panelUserPasswordBox.classList.add("d-none");
        if (E.panelUserPasswordUsername) E.panelUserPasswordUsername.textContent = "";
        if (E.panelUserPasswordValue) E.panelUserPasswordValue.textContent = "";
        if (E.panelCredentialsUsername) E.panelCredentialsUsername.textContent = "";
        if (E.panelCredentialsPassword) E.panelCredentialsPassword.textContent = "";
        return;
      }
      if (E.panelUserPasswordUsername) E.panelUserPasswordUsername.textContent = cleanUsername;
      if (E.panelUserPasswordValue) E.panelUserPasswordValue.textContent = cleanPassword;
      if (E.panelUserPasswordBox) E.panelUserPasswordBox.classList.remove("d-none");
      if (E.panelCredentialsUsername) E.panelCredentialsUsername.textContent = cleanUsername;
      if (E.panelCredentialsPassword) E.panelCredentialsPassword.textContent = cleanPassword;
      if (openModal && panelCredentialsModalInstance) panelCredentialsModalInstance.show();
    }

    function resetPanelUserForm() {
      state.panelUserEditingId = "";
      if (E.panelUserId) E.panelUserId.value = "";
      if (E.panelUsername) {
        E.panelUsername.value = "";
        E.panelUsername.disabled = false;
      }
      if (E.panelDisplayName) E.panelDisplayName.value = "";
      if (E.panelUserFiliais) E.panelUserFiliais.value = "";
      if (E.panelUserSellerScopes) E.panelUserSellerScopes.value = "";
      if (E.panelUserActive) E.panelUserActive.checked = true;
      if (E.panelUserAdmin) E.panelUserAdmin.checked = false;
      showPanelUserTemporaryCredentials("", "");
      if (E.panelUserMode) E.panelUserMode.textContent = "Novo usuário";
      renderPanelUserFeatureChecks();
    }

    function fillPanelUserForm(userId) {
      const user = state.panelUsers.find(item => String(item.id) === String(userId));
      if (!user) return;
      state.panelUserEditingId = String(user.id);
      if (E.panelUserId) E.panelUserId.value = String(user.id);
      if (E.panelUsername) {
        E.panelUsername.value = user.username || "";
        E.panelUsername.disabled = true;
      }
      if (E.panelDisplayName) E.panelDisplayName.value = user.display_name || "";
      if (E.panelUserFiliais) E.panelUserFiliais.value = Array.isArray(user.filiais) ? user.filiais.join(", ") : "";
      if (E.panelUserSellerScopes) E.panelUserSellerScopes.value = Array.isArray(user.seller_scopes) ? user.seller_scopes.join(", ") : "";
      if (E.panelUserActive) E.panelUserActive.checked = user.is_active !== false;
      if (E.panelUserAdmin) E.panelUserAdmin.checked = Boolean(user.is_admin);
      renderPanelUserFeatureChecks(user.features || []);
      showPanelUserTemporaryCredentials("", "");
      if (E.panelUserMode) E.panelUserMode.textContent = `Editando #${user.id}`;
    }

    async function savePanelUser() {
      const payload = panelUserPayload();
      if (!payload.username && !state.panelUserEditingId) {
        addLog("Informe o usuário do painel.", "warn");
        return;
      }
      if (!payload.is_admin && !payload.features.length) {
        addLog("Escolha ao menos um bloco para o usuário.", "warn");
        return;
      }
      const editingId = state.panelUserEditingId || "";
      const path = editingId ? `${CONFIG.endpoints.panel.users}/${encodeURIComponent(editingId)}` : CONFIG.endpoints.panel.users;
      const method = editingId ? "PATCH" : "POST";
      const body = editingId ? { ...payload } : payload;
      if (editingId) delete body.username;
      try {
        const result = await req(path, {
          method,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
          timeoutMs: 30000
        });
        if (result.temporary_password) {
          showPanelUserTemporaryCredentials(
            result.user && result.user.username ? result.user.username : payload.username,
            result.temporary_password
          );
        } else {
          showPanelUserTemporaryCredentials("", "");
        }
        addLog(editingId ? "Usuário do painel atualizado." : "Usuário do painel criado.", "ok");
        await syncPanelUsers();
        if (editingId) resetPanelUserForm();
      } catch (err) {
        addLog(`Falha ao salvar usuário do painel: ${err.message}`, "err");
      }
    }

    async function resetPanelUserPassword(userId) {
      const user = state.panelUsers.find(item => String(item.id) === String(userId));
      if (!user) return;
      const confirmed = await askConfirmation(`Resetar a senha do usuário ${user.username}? A senha atual deixará de funcionar.`);
      if (!confirmed) return;
      try {
        const result = await req(`${CONFIG.endpoints.panel.users}/${encodeURIComponent(userId)}/reset-password`, {
          method: "POST",
          timeoutMs: 30000
        });
        if (result.temporary_password) {
          showPanelUserTemporaryCredentials(
            result.user && result.user.username ? result.user.username : user.username,
            result.temporary_password
          );
        }
        addLog(`Senha temporaria gerada para ${user.username}.`, "ok");
        await syncPanelUsers();
      } catch (err) {
        addLog(`Falha ao resetar senha: ${err.message}`, "err");
      }
    }

    async function deletePanelUser(userId) {
      const user = state.panelUsers.find(item => String(item.id) === String(userId));
      if (!user) return;
      if (state.panel && String(state.panel.userId || "") === String(user.id)) {
        addLog("Não apague o próprio usuário logado.", "warn");
        return;
      }
      const confirmed = await askConfirmation(`Apagar o usuário ${user.username}? Esta ação não pode ser desfeita.`);
      if (!confirmed) return;
      try {
        await req(`${CONFIG.endpoints.panel.users}/${encodeURIComponent(userId)}`, {
          method: "DELETE",
          timeoutMs: 30000
        });
        addLog(`Usuário ${user.username} apagado.`, "ok");
        await syncPanelUsers();
        if (String(state.panelUserEditingId || "") === String(userId)) resetPanelUserForm();
      } catch (err) {
        addLog(`Falha ao apagar usuário do painel: ${err.message}`, "err");
      }
    }

    async function copyPanelUserTemporaryPassword() {
      const credentials = state.panelUserTemporaryCredentials || {};
      const username = String(credentials.username || (E.panelUserPasswordUsername ? E.panelUserPasswordUsername.textContent : "") || "").trim();
      const password = String(credentials.password || (E.panelUserPasswordValue ? E.panelUserPasswordValue.textContent : "") || "").trim();
      if (!username || !password) {
        addLog("Nenhum acesso temporario para copiar.", "warn");
        return;
      }
      const value = [
        `Usuário: ${username}`,
        `Senha temporaria: ${password}`,
        "No primeiro acesso o painel vai pedir a troca da senha."
      ].join("\n");
      try {
        if (navigator.clipboard && window.isSecureContext) {
          await navigator.clipboard.writeText(value);
        } else {
          const textarea = document.createElement("textarea");
          textarea.value = value;
          textarea.setAttribute("readonly", "");
          textarea.style.position = "fixed";
          textarea.style.left = "-9999px";
          document.body.appendChild(textarea);
          textarea.select();
          document.execCommand("copy");
          textarea.remove();
        }
        addLog("Acesso temporario copiado.", "ok");
      } catch (err) {
        addLog(`Não consegui copiar o acesso automaticamente: ${err.message}`, "warn");
      }
    }

    async function syncPanelUsers() {
      if (!(state.panel && state.panel.isAdmin)) return false;
      const payload = await req(CONFIG.endpoints.panel.users, { timeoutMs: 30000 });
      state.panelUsers = payload && Array.isArray(payload.users) ? payload.users : [];
      renderPanelUsers();
      return true;
    }

    function renderPanelUserStats(users) {
      const list = Array.isArray(users) ? users : [];
      const active = list.filter(user => user.is_active !== false).length;
      const admins = list.filter(user => user.is_admin).length;
      const pending = list.filter(user => user.must_change_password && user.is_active !== false).length;
      const blocked = list.filter(user => user.is_active === false).length;
      if (E.panelUsersActiveCount) E.panelUsersActiveCount.textContent = String(active);
      if (E.panelUsersAdminCount) E.panelUsersAdminCount.textContent = String(admins);
      if (E.panelUsersPendingCount) E.panelUsersPendingCount.textContent = String(pending);
      if (E.panelUsersBlockedCount) E.panelUsersBlockedCount.textContent = String(blocked);
    }

    function panelUserSearchText(user) {
      const featureLabels = user.is_admin
        ? ["todos", "administrador"]
        : (user.features || []).map(panelFeatureLabel);
      const filiais = Array.isArray(user.filiais) ? user.filiais : [];
      const status = user.is_active === false
        ? "bloqueado"
        : user.must_change_password
          ? "trocar senha"
          : "ativo";
      return [
        user.username || "",
        user.display_name || "",
        user.is_admin ? "admin administrador" : "",
        status,
        ...featureLabels,
        ...filiais
      ].join(" ").toLowerCase();
    }

    function renderPanelUserFeaturePills(user) {
      if (user.is_admin) {
        return '<span class="panel-user-feature-pill all"><i class="bi bi-shield-check me-1"></i>Todos os blocos</span>';
      }
      const features = (user.features || []).map(panelFeatureLabel).filter(Boolean);
      if (!features.length) return '<span class="text-secondary small">-</span>';
      return features.map(label => `<span class="panel-user-feature-pill">${escapeHtml(label)}</span>`).join("");
    }

    function renderPanelUsers() {
      if (!E.panelUsersBody) return;
      const users = Array.isArray(state.panelUsers) ? state.panelUsers : [];
      const query = String(state.panelUserFilter || (E.panelUserSearch ? E.panelUserSearch.value : "") || "").trim().toLowerCase();
      const visibleUsers = query ? users.filter(user => panelUserSearchText(user).includes(query)) : users;
      renderPanelUserStats(users);
      if (E.panelUsersCount) {
        E.panelUsersCount.textContent = query ? `${visibleUsers.length}/${users.length} usuário(s)` : `${users.length} usuário(s)`;
      }
      if (E.panelUsersFilterInfo) {
        E.panelUsersFilterInfo.textContent = query ? `Filtro aplicado: ${visibleUsers.length} de ${users.length}` : "Mostrando todos";
      }
      if (!users.length) {
        E.panelUsersBody.innerHTML = '<tr><td colspan="5" class="text-center py-3 text-secondary">Nenhum usuário do painel cadastrado.</td></tr>';
        return;
      }
      if (!visibleUsers.length) {
        E.panelUsersBody.innerHTML = '<tr><td colspan="5" class="text-center py-3 text-secondary">Nenhum usuário encontrado com esse filtro.</td></tr>';
        return;
      }
      E.panelUsersBody.innerHTML = visibleUsers.map(user => {
        const filiais = Array.isArray(user.filiais) && user.filiais.length ? user.filiais.join(", ") : "-";
        const status = user.is_active === false
          ? '<span class="badge text-bg-danger">Bloqueado</span>'
          : user.must_change_password
            ? '<span class="badge text-bg-warning">Trocar senha</span>'
            : '<span class="badge text-bg-success">Ativo</span>';
        const role = user.is_admin ? '<span class="small fw-bold text-primary">Administrador</span>' : '<span class="small text-secondary">Usuário</span>';
        const deleteButton = state.panel && String(state.panel.userId || "") === String(user.id)
          ? ""
          : `<button class="btn btn-outline-danger btn-sm" title="Apagar usuário" onclick="deletePanelUser('${escapeHtml(String(user.id))}')"><i class="bi bi-trash me-1"></i>Apagar</button>`;
        return `<tr><td class="ps-3" data-label="Usuário"><span class="panel-user-name"><strong>${escapeHtml(user.username || "-")}</strong><span class="small text-secondary">${escapeHtml(user.display_name || "")}</span>${role}</span></td><td data-label="Blocos"><div class="panel-user-feature-pills">${renderPanelUserFeaturePills(user)}</div></td><td data-label="Filiais"><span class="mono small fw-bold">${escapeHtml(filiais)}</span></td><td data-label="Status">${status}</td><td class="text-end pe-3" data-label="Ações"><div class="panel-user-actions"><button class="btn btn-outline-primary btn-sm" title="Editar usuário" onclick="fillPanelUserForm('${escapeHtml(String(user.id))}')"><i class="bi bi-pencil-square me-1"></i>Editar</button><button class="btn btn-outline-warning btn-sm" title="Gerar nova senha temporaria" onclick="resetPanelUserPassword('${escapeHtml(String(user.id))}')"><i class="bi bi-key me-1"></i>Resetar</button>${deleteButton}</div></td></tr>`;
      }).join("");
    }

    function resetAccessForm() {
      state.accessEditing = null;
      document.getElementById("accessPhone").value = "";
      document.getElementById("accessName").value = "";
      document.getElementById("accessScope").value = "";
      document.getElementById("accessActive").checked = true;
      E.accessRole.selectedIndex = 0;
      updateScopeHint();
      E.accessModeHint.textContent = "Modo atual: novo cadastro.";
      E.accessUserCount.textContent = `${state.accessUsers.length} usuários`;
    }

    function editAccess(phone) {
      const u = state.accessUsers.find(x => (x.whatsapp_phone_number || x.phone_number) === phone);
      if (!u) return;
      const n = normalizeUserForUi(u);
      state.accessEditing = u;
      document.getElementById("accessPhone").value = n.phone_display === "-" ? "" : n.phone_display;
      document.getElementById("accessName").value = n.name;
      E.accessRole.value = n.role;
      document.getElementById("accessScope").value = n.scope.join(", ");
      document.getElementById("accessActive").checked = n.active;
      updateScopeHint();
      E.accessModeHint.innerHTML = `Editando <strong>${escapeHtml(n.phone_display)}</strong>.`;
    }

    async function deleteAccess(phone) {
      const u = state.accessUsers.find(x => (x.whatsapp_phone_number || x.phone_number) === phone);
      if (!u) return;
      const confirmed = await askConfirmation(`Deseja deletar o usuário ${u.name || phone}? Esta ação não pode ser desfeita.`);
      if (!confirmed) return;
      try {
        await req(`${CONFIG.endpoints.access.save}/${phone}`, {
          method: "DELETE",
          headers: { "Content-Type": "application/json" }
        });
        addLog(`Usuário ${formatPhoneForUi(phone)} deletado com sucesso.`, "ok");
        await syncAll();
      } catch (err) {
        addLog(`Falha ao deletar usuário: ${err.message}`, "err");
      }
    }

    async function saveAccess() {
      const phone = document.getElementById("accessPhone").value.trim().replace(/\D/g, "");
      const name = document.getElementById("accessName").value.trim();
      const role = E.accessRole.value;
      const scopeRaw = document.getElementById("accessScope").value.trim();
      const active = document.getElementById("accessActive").checked;
      if (!phone || phone.length < 10) { addLog("Número inválido.", "warn"); return; }
      const scopes = scopeRaw ? scopeRaw.split(/[,;\n]+/).map(s => normalizeScopeTokenForApi(s)).filter(Boolean) : [];
      const roleApi = roleToApi(role);
      const payload = {
        phone_number: phone,
        name: name || null,
        is_active: active,
        roles: [roleApi],
        sectors: (roleApi === "vendedor" || roleApi === "financeiro" || roleApi === "armazem") ? scopes : [],
        gv_vdes: (roleApi === "gerente_vendas" || roleApi === "diretor_comercial") ? scopes : []
      };
      try {
        await req(CONFIG.endpoints.access.save, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        addLog(`Acesso salvo: ${formatPhoneForUi(phone)}.`, "ok");
        resetAccessForm();
        await syncAll();
      } catch (err) {
        addLog(`Falha ao salvar acesso: ${err.message}`, "err");
      }
    }

    async function saveBulkAccess() {
      const txt = E.accessBulk.value.trim();
      if (!txt) { addLog("Use o formato: numero;nome;perfil;escopo;status", "warn"); return; }
      try {
        const users = txt.split(/\r?\n/).map(line => line.trim()).filter(Boolean).map((line, idx) => {
          const parts = line.split(";").map(x => x.trim());
          if (parts.length < 3) throw new Error(`Linha ${idx + 1} inválida. Use: numero;nome;perfil;escopo;status (Exemplo: 5583999999999;Nome;VENDEDOR;3-400;ativo)`);
          const phone = String(parts[0] || "").replace(/\D/g, "");
          if (!phone) throw new Error(`Linha ${idx + 1}: número inválido`);
          const name = parts[1] || null;
          if (!name) throw new Error(`Linha ${idx + 1}: nome e obrigatório`);
          const roleApi = roleToApi(parts[2]);
          const scopes = parts[3] ? parts[3].split(/[,]+/).map(s => normalizeScopeTokenForApi(s)).filter(Boolean) : [];
          const statusTxt = normalizeStatusText(parts[4] || "ativo");
          const isActive = !["0", "inativo", "nao", "false"].includes(statusTxt);
          return {
            phone_number: phone,
            name: name,
            is_active: isActive,
            roles: [roleApi],
            sectors: (roleApi === "vendedor" || roleApi === "financeiro" || roleApi === "armazem") ? scopes : [],
            gv_vdes: (roleApi === "gerente_vendas" || roleApi === "diretor_comercial") ? scopes : []
          };
        });

        await req(CONFIG.endpoints.access.importBulk, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ continue_on_error: true, users: users })
        });
        addLog("Lote RBAC importado.", "ok");
        E.accessBulk.value = "";
        await syncAll();
      } catch (err) {
        addLog(`Falha no lote: ${err.message}`, "err");
      }
    }

    function renderAccess() {
      const filter = normalizeTextForSearch(E.accessUsersFilter.value || "");
      const users = state.accessUsers.map(normalizeUserForUi).filter(u => {
        if (!filter) return true;
        const phone = normalizeTextForSearch(u.phone || "");
        const phoneDisplay = normalizeTextForSearch(u.phone_display || "");
        const phoneComparable = normalizeTextForSearch(u.phone_comparable || "");
        const name = normalizeTextForSearch(u.name || "");
        const role = normalizeTextForSearch(u.role || "");
        const scope = normalizeTextForSearch(Array.isArray(u.scope) ? u.scope.join(",") : "");
        return phone.includes(filter) || phoneDisplay.includes(filter) || phoneComparable.includes(filter) || name.includes(filter) || role.includes(filter) || scope.includes(filter);
      });
      E.accessUserCount.textContent = `${users.length} usuários`;
      if (!users.length) {
        E.accessUsersTable.innerHTML = '<tr><td colspan="6" class="text-center py-4 text-secondary">Nenhum usuário encontrado</td></tr>';
        syncAllowedUsersCardSizing();
        return;
      }
      E.accessUsersTable.innerHTML = users.map(u => {
        const rawPhone = u.phone || "-";
        const displayPhone = u.phone_display || "-";
        const rawPhoneAction = encodeURIComponent(rawPhone);
        const statusClass = u.active ? "badge text-bg-success" : "badge text-bg-danger";
        const statusText = u.active ? "Ativo" : "Bloqueado";
        const scope = Array.isArray(u.scope) && u.scope.length ? u.scope.join(", ") : "-";
        return `<tr><td class="ps-3"><strong class="mono">${escapeHtml(displayPhone)}</strong></td><td>${escapeHtml(u.name || "-")}</td><td><span class="badge text-bg-light border">${escapeHtml(u.role || "-")}</span></td><td><span class="mono small">${escapeHtml(scope)}</span></td><td><span class="${statusClass}">${escapeHtml(statusText)}</span></td><td class="text-end pe-3"><div class="d-flex gap-1 justify-content-end"><button class="btn btn-outline-primary btn-sm" onclick="editAccess(decodeURIComponent('${rawPhoneAction}'))"><i class="bi bi-pencil-square me-1"></i>Editar</button><button class="btn btn-outline-danger btn-sm" onclick="deleteAccess(decodeURIComponent('${rawPhoneAction}'))"><i class="bi bi-trash3 me-1"></i>Apagar</button></div></td></tr>`;
      }).join("");
      syncAllowedUsersCardSizing();
    }
