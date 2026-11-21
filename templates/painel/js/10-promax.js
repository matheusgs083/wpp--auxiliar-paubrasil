    function normalizePromaxCatalogItems(items) {
      if (!Array.isArray(items)) return [];
      const seen = new Set();
      return items.map(item => {
        const isObject = item && typeof item === "object";
        const id = String(isObject ? (item.id || item.name || "") : (item || "")).trim();
        const name = String(isObject ? (item.name || item.label || id) : id).trim();
        return { id, name: name || id };
      }).filter(item => {
        if (!item.id || seen.has(item.id)) return false;
        seen.add(item.id);
        return true;
      });
    }

    function promaxCatalogCategories() {
      const catalog = state.promax.catalog;
      const categories = catalog && typeof catalog === "object" ? catalog.categories : null;
      const result = categories && typeof categories === "object" && !Array.isArray(categories)
        ? Object.entries(categories).map(([categoryId, value]) => {
        if (!value || typeof value !== "object" || Array.isArray(value)) return null;
        const id = String(categoryId || "").trim();
        if (!id) return null;
        return {
          id,
          name: String(value.name || value.label || id).trim() || id,
          section: String(value.section || value.group || "Geral").trim() || "Geral",
          description: String(value.description || "").trim(),
          routines: normalizePromaxCatalogItems(value.routines),
          units: normalizePromaxCatalogItems(value.units)
        };
          }).filter(Boolean)
        : [];
      if (!result.some(category => category.id === "cora_critica")) {
        result.push({
          id: "cora_critica",
          name: "Cora — Crítica",
          section: "Cora",
          description: "Baixa e importa o CSV completo da Crítica pelo portal Cora.",
          routines: [{ id: "critica", name: "Crítica Cora" }],
          units: []
        });
      }
      return result;
    }

    function promaxCatalogCategory(categoryId) {
      const id = String(categoryId || "");
      return promaxCatalogCategories().find(category => category.id === id) || null;
    }

    function promaxSelectionStateKeys(scope) {
      return scope === "run"
        ? {
          categories: "runSelectedCategories",
          routines: "runSelectedRoutines",
          units: "runSelectedUnits"
        }
        : {
          categories: "scheduleSelectedCategories",
          routines: "scheduleSelectedRoutines",
          units: "scheduleSelectedUnits"
        };
    }

    function promaxSelectionSelectedCategories(scope) {
      const keys = promaxSelectionStateKeys(scope);
      const values = Array.isArray(state.promax[keys.categories])
        ? state.promax[keys.categories]
        : [];
      return values
        .map(value => String(value || "").trim())
        .filter((value, index, items) => value && items.indexOf(value) === index);
    }

    function promaxSelectionSelectedRoutines(scope) {
      const keys = promaxSelectionStateKeys(scope);
      const selections = {};
      const configured = state.promax[keys.routines] || {};
      Object.entries(configured).forEach(([categoryId, routines]) => {
        const normalizedCategory = String(categoryId || "").trim();
        if (!normalizedCategory || !Array.isArray(routines)) return;
        selections[normalizedCategory] = routines
          .map(value => String(value || "").trim())
          .filter((value, index, items) => value && items.indexOf(value) === index);
      });
      return selections;
    }

    function promaxSelectionSelectedUnits(scope) {
      const keys = promaxSelectionStateKeys(scope);
      const values = Array.isArray(state.promax[keys.units])
        ? state.promax[keys.units]
        : [];
      return values
        .map(value => String(value || "").trim())
        .filter((value, index, items) => value && items.indexOf(value) === index);
    }

    function promaxRunSelectedCategories() {
      return promaxSelectionSelectedCategories("run");
    }

    function promaxRunSelectedRoutines() {
      return promaxSelectionSelectedRoutines("run");
    }

    function promaxRunSelectedUnits() {
      return promaxSelectionSelectedUnits("run");
    }

    function promaxScheduleSelectedCategories() {
      return promaxSelectionSelectedCategories("schedule");
    }

    function promaxScheduleSelectedRoutines() {
      return promaxSelectionSelectedRoutines("schedule");
    }

    function promaxScheduleRoutinesForEdit(schedule, payload, categoryId) {
      const payloadRoutines = Array.isArray(payload && payload.routines)
        ? payload.routines.map(String).filter(Boolean)
        : [];
      if (payloadRoutines.length) return payloadRoutines;
      const groups = Array.isArray(payload && payload.groups) ? payload.groups : [];
      const group = groups.find(item => String(item && item.category || "") === String(categoryId));
      const groupRoutines = Array.isArray(group && group.routines)
        ? group.routines.map(String).filter(Boolean)
        : [];
      if (groupRoutines.length) return groupRoutines;
      const catalogCategory = promaxCatalogCategory(categoryId || (schedule && schedule.job_type));
      const catalogRoutines = Array.isArray(catalogCategory && catalogCategory.routines)
        ? catalogCategory.routines.map(item => String(item && item.id || item || "")).filter(Boolean)
        : [];
      return catalogRoutines;
    }

    function promaxNormalizeScheduleScopeValues(values) {
      return (Array.isArray(values) ? values : [])
        .map(value => String(value || "").trim())
        .filter((value, index, items) => value && items.indexOf(value) === index);
    }

    function promaxScheduleCatalogRoutineIds(categoryId) {
      const catalogCategory = promaxCatalogCategory(categoryId);
      return Array.isArray(catalogCategory && catalogCategory.routines)
        ? catalogCategory.routines.map(item => String(item && item.id || item || "").trim()).filter(Boolean)
        : [];
    }

    function promaxEmptyScheduleScope() {
      return { units: [], categories: [], routines: {} };
    }

    function promaxAddScheduleScopeGroup(scope, categoryId, routines) {
      const normalizedCategory = String(categoryId || "").trim();
      if (!normalizedCategory) return;
      if (!scope.categories.includes(normalizedCategory)) scope.categories.push(normalizedCategory);
      const current = Array.isArray(scope.routines[normalizedCategory])
        ? scope.routines[normalizedCategory]
        : [];
      scope.routines[normalizedCategory] = promaxNormalizeScheduleScopeValues([
        ...current,
        ...promaxNormalizeScheduleScopeValues(routines)
      ]);
    }

    function promaxMergeScheduleScope(target, source) {
      target.units = promaxNormalizeScheduleScopeValues([
        ...target.units,
        ...promaxNormalizeScheduleScopeValues(source && source.units)
      ]);
      promaxNormalizeScheduleScopeValues(source && source.categories).forEach(categoryId => {
        promaxAddScheduleScopeGroup(
          target,
          categoryId,
          source && source.routines ? source.routines[categoryId] : []
        );
      });
      return target;
    }

    function promaxScheduleScopeFromSchedule(schedule) {
      const payload = schedule && schedule.payload && typeof schedule.payload === "object"
        ? schedule.payload
        : {};
      const scope = promaxEmptyScheduleScope();
      scope.units = promaxNormalizeScheduleScopeValues(payload.units);
      const groups = Array.isArray(payload.groups) ? payload.groups : [];
      groups.forEach(group => {
        promaxAddScheduleScopeGroup(
          scope,
          group && group.category,
          Array.isArray(group && group.routines) ? group.routines : []
        );
      });
      const categoryId = String(payload.category || schedule && schedule.job_type || "").trim();
      if (categoryId) {
        promaxAddScheduleScopeGroup(
          scope,
          categoryId,
          promaxScheduleRoutinesForEdit(schedule, payload, categoryId)
        );
      }
      return scope;
    }

    function promaxScheduleScopeForEdit(target) {
      const schedules = Array.isArray(target && target.schedules)
        ? target.schedules
        : [target].filter(Boolean);
      const scope = promaxEmptyScheduleScope();
      schedules.forEach(schedule => promaxMergeScheduleScope(scope, promaxScheduleScopeFromSchedule(schedule)));
      if (!scope.units.length) {
        scope.units = PROMAX_RESELLERS.map(reseller => reseller.id);
      }
      scope.categories.forEach(categoryId => {
        if (scope.routines[categoryId] && scope.routines[categoryId].length) return;
        scope.routines[categoryId] = promaxScheduleCatalogRoutineIds(categoryId);
      });
      return scope;
    }

    function promaxResetScheduleSlicerSearches() {
      Object.keys(PROMAX_SCHEDULE_SLICERS).forEach(kind => {
        const els = promaxScheduleSlicerElements(kind, "schedule");
        if (els.search) els.search.value = "";
        if (els.panel) els.panel.classList.add("d-none");
        if (els.button) els.button.setAttribute("aria-expanded", "false");
      });
    }

    function promaxApplyScheduleScopeForEdit(scope) {
      const normalizedScope = scope && typeof scope === "object" ? scope : promaxEmptyScheduleScope();
      state.promax.scheduleSelectedUnits = promaxNormalizeScheduleScopeValues(normalizedScope.units);
      if (!state.promax.scheduleSelectedUnits.length) {
        state.promax.scheduleSelectedUnits = PROMAX_RESELLERS.map(reseller => reseller.id);
      }
      state.promax.scheduleSelectedCategories = promaxNormalizeScheduleScopeValues(normalizedScope.categories);
      state.promax.scheduleSelectedRoutines = {};
      state.promax.scheduleSelectedCategories.forEach(categoryId => {
        const selected = promaxNormalizeScheduleScopeValues(
          normalizedScope.routines && normalizedScope.routines[categoryId]
        );
        state.promax.scheduleSelectedRoutines[categoryId] = selected.length
          ? selected
          : promaxScheduleCatalogRoutineIds(categoryId);
      });
      promaxResetScheduleSlicerSearches();
      renderPromaxScheduleResellers(state.promax.scheduleSelectedUnits);
      renderPromaxScheduleCatalog({
        categoryIds: state.promax.scheduleSelectedCategories,
        routines: state.promax.scheduleSelectedRoutines
      });
      updatePromaxActionState();
    }

    function updatePromaxActionState() {
      const runCategories = promaxRunSelectedCategories();
      const runRoutines = promaxRunSelectedRoutines();
      const runEnabled = Boolean(
        runCategories.length
        && (runCategories.every(categoryId => categoryId === "cora_critica") || promaxRunSelectedUnits().length)
        && runCategories.every(categoryId => (runRoutines[categoryId] || []).length)
      );
      const scheduleCategories = promaxScheduleSelectedCategories();
      const scheduleRoutines = promaxScheduleSelectedRoutines();
      const scheduleEnabled = Boolean(
        scheduleCategories.length
        && promaxScheduleSelectedUnits().length
        && scheduleCategories.every(categoryId => (scheduleRoutines[categoryId] || []).length)
      );
      if (E.promaxRunBtn) E.promaxRunBtn.disabled = !runEnabled;
      if (E.promaxScheduleCreateBtn) E.promaxScheduleCreateBtn.disabled = !scheduleEnabled;
    }

    function promaxScheduleSlicerElements(kind, scope = "schedule") {
      const slicers = scope === "run" ? PROMAX_RUN_SLICERS : PROMAX_SCHEDULE_SLICERS;
      const def = slicers[kind];
      if (!def) return {};
      return {
        def,
        root: document.getElementById(`${def.prefix}Slicer`),
        button: document.getElementById(`${def.prefix}Button`),
        panel: document.getElementById(`${def.prefix}Panel`),
        search: document.getElementById(`${def.prefix}Search`),
        list: document.getElementById(def.listId),
        selectAllBtn: document.getElementById(`${def.prefix}SelectAllBtn`),
        clearBtn: document.getElementById(`${def.prefix}ClearBtn`)
      };
    }

    function promaxScheduleRoutineKey(categoryId, routineId) {
      return `${String(categoryId || "")}::${String(routineId || "")}`;
    }

    function promaxScheduleSlicerOptions(kind, scope = "schedule") {
      if (kind === "reseller") {
        return PROMAX_RESELLERS.map(reseller => ({
          value: reseller.id,
          label: `${reseller.name} (${reseller.id})`
        }));
      }
      if (kind === "category") {
        const options = promaxCatalogCategories().map(category => ({
          value: category.id,
          label: category.name,
          section: category.section || "Geral"
        }));
        const values = new Set(options.map(item => item.value));
        promaxSelectionSelectedCategories(scope).forEach(categoryId => {
          if (!values.has(categoryId)) {
            options.unshift({ value: categoryId, label: `${categoryId} (indisponível)`, section: "Indisponível" });
            values.add(categoryId);
          }
        });
        return options;
      }
      if (kind === "routine") {
        return promaxSelectionSelectedCategories(scope).flatMap(categoryId => {
          const category = promaxCatalogCategory(categoryId);
          if (!category) return [];
          return category.routines.map(routine => ({
            value: promaxScheduleRoutineKey(categoryId, routine.id),
            categoryId,
            categoryName: category.name,
            routineId: routine.id,
            label: routine.name === routine.id
              ? routine.id
              : `${routine.id} - ${routine.name}`
          }));
        });
      }
      return [];
    }

    function promaxScheduleSlicerSelectedKeys(kind, scope = "schedule") {
      if (kind === "reseller") return promaxSelectionSelectedUnits(scope);
      if (kind === "category") return promaxSelectionSelectedCategories(scope);
      if (kind === "routine") {
        const routines = promaxSelectionSelectedRoutines(scope);
        return promaxSelectionSelectedCategories(scope).flatMap(categoryId => (
          (routines[categoryId] || []).map(routineId => promaxScheduleRoutineKey(categoryId, routineId))
        ));
      }
      return [];
    }

    function promaxScheduleSlicerVisibleOptions(kind, scope = "schedule") {
      const els = promaxScheduleSlicerElements(kind, scope);
      const search = normalizeTextForSearch(els.search ? els.search.value : "");
      return promaxScheduleSlicerOptions(kind, scope).filter(item => (
        !search || normalizeTextForSearch(
          `${item.label || item.value} ${item.categoryName || ""} ${item.section || ""}`
        ).includes(search)
      ));
    }

    function updatePromaxScheduleSlicerButton(kind, scope = "schedule") {
      const els = promaxScheduleSlicerElements(kind, scope);
      if (!els.button || !els.def) return;
      const options = promaxScheduleSlicerOptions(kind, scope);
      const selectedKeys = promaxScheduleSlicerSelectedKeys(kind, scope);
      const selected = new Set(selectedKeys);
      const selectedOptions = options.filter(item => selected.has(item.value));
      const allSelected = Boolean(options.length)
        && options.every(item => selected.has(item.value));
      if (!selectedOptions.length) {
        els.button.textContent = els.def.emptyText;
      } else if (allSelected) {
        els.button.textContent = els.def.allText;
      } else if (selectedOptions.length === 1) {
        els.button.textContent = selectedOptions[0].label;
      } else {
        els.button.textContent = `${selectedOptions.length} ${els.def.selectedText}`;
      }
      els.button.title = selectedOptions.length
        ? selectedOptions.map(item => item.label).join(", ")
        : els.def.emptyText;
    }

    function createPromaxScheduleSlicerItem(kind, item, selected, scope = "schedule") {
      const label = document.createElement("label");
      label.className = "power-slicer-item";
      const input = document.createElement("input");
      input.className = `form-check-input m-0 promax-schedule-${kind}`;
      input.type = "checkbox";
      input.value = item.value;
      input.checked = selected.has(item.value);
      if (item.categoryId) input.dataset.category = item.categoryId;
      if (item.routineId) input.dataset.routine = item.routineId;
      input.addEventListener("change", event => onPromaxScheduleSlicerOptionChange(kind, event, scope));
      const text = document.createElement("span");
      text.className = kind === "routine" ? "mono" : "";
      text.textContent = item.label;
      label.append(input, text);
      return label;
    }

    function renderPromaxScheduleSlicer(kind, scope = "schedule") {
      const els = promaxScheduleSlicerElements(kind, scope);
      if (!els.list) return;
      const options = promaxScheduleSlicerVisibleOptions(kind, scope);
      const selected = new Set(promaxScheduleSlicerSelectedKeys(kind, scope));
      els.list.replaceChildren();
      if (!options.length) {
        const empty = document.createElement("div");
        empty.className = "small text-secondary px-1 py-2";
        empty.textContent = kind === "routine" && !promaxSelectionSelectedCategories(scope).length
          ? "Selecione pelo menos um grupo."
          : "Nenhum item corresponde a pesquisa.";
        els.list.appendChild(empty);
        updatePromaxScheduleSlicerButton(kind, scope);
        return;
      }

      if (kind === "routine") {
        const grouped = new Map();
        options.forEach(item => {
          if (!grouped.has(item.categoryId)) {
            grouped.set(item.categoryId, { name: item.categoryName, items: [] });
          }
          grouped.get(item.categoryId).items.push(item);
        });
        grouped.forEach(group => {
          const wrapper = document.createElement("div");
          wrapper.className = "promax-slicer-group";
          const title = document.createElement("div");
          title.className = "promax-slicer-group-title";
          title.textContent = group.name;
          wrapper.appendChild(title);
          group.items.forEach(item => {
            wrapper.appendChild(createPromaxScheduleSlicerItem(kind, item, selected, scope));
          });
          els.list.appendChild(wrapper);
        });
      } else if (kind === "category") {
        const grouped = new Map();
        options.forEach(item => {
          const section = String(item.section || "Geral");
          if (!grouped.has(section)) grouped.set(section, []);
          grouped.get(section).push(item);
        });
        grouped.forEach((items, section) => {
          const wrapper = document.createElement("div");
          wrapper.className = "promax-slicer-group";
          const title = document.createElement("div");
          title.className = "promax-slicer-group-title";
          title.textContent = section;
          wrapper.appendChild(title);
          items.forEach(item => {
            wrapper.appendChild(createPromaxScheduleSlicerItem(kind, item, selected, scope));
          });
          els.list.appendChild(wrapper);
        });
      } else {
        const fragment = document.createDocumentFragment();
        options.forEach(item => {
          fragment.appendChild(createPromaxScheduleSlicerItem(kind, item, selected, scope));
        });
        els.list.appendChild(fragment);
      }
      updatePromaxScheduleSlicerButton(kind, scope);
    }

    function setPromaxScheduleSlicerSelection(kind, values, scope = "schedule") {
      const stateKeys = promaxSelectionStateKeys(scope);
      const requested = new Set(
        (Array.isArray(values) ? values : [])
          .map(value => String(value || "").trim())
          .filter(Boolean)
      );
      if (kind === "reseller") {
        state.promax[stateKeys.units] = PROMAX_RESELLERS
          .map(reseller => reseller.id)
          .filter(value => requested.has(value));
      } else if (kind === "category") {
        const available = promaxCatalogCategories().map(category => category.id);
        const ordered = available.filter(value => requested.has(value));
        requested.forEach(value => {
          if (!available.includes(value)) ordered.push(value);
        });
        state.promax[stateKeys.categories] = ordered;
        const selectedRoutines = { ...(state.promax[stateKeys.routines] || {}) };
        ordered.forEach(categoryId => {
          if (Array.isArray(selectedRoutines[categoryId])) return;
          const category = promaxCatalogCategory(categoryId);
          selectedRoutines[categoryId] = category
            ? category.routines.map(routine => routine.id)
            : [];
        });
        state.promax[stateKeys.routines] = selectedRoutines;
      } else if (kind === "routine") {
        const selectedRoutines = { ...(state.promax[stateKeys.routines] || {}) };
        promaxSelectionSelectedCategories(scope).forEach(categoryId => {
          selectedRoutines[categoryId] = [];
        });
        promaxScheduleSlicerOptions("routine", scope).forEach(item => {
          if (requested.has(item.value)) {
            selectedRoutines[item.categoryId].push(item.routineId);
          }
        });
        state.promax[stateKeys.routines] = selectedRoutines;
      }
      renderPromaxScheduleSlicer(kind, scope);
      if (kind === "category") renderPromaxScheduleSlicer("routine", scope);
      updatePromaxActionState();
    }

    function onPromaxScheduleSlicerOptionChange(kind, event, scope = "schedule") {
      const value = String(event.target && event.target.value || "").trim();
      if (!value) return;
      const selected = new Set(promaxScheduleSlicerSelectedKeys(kind, scope));
      if (event.target.checked) selected.add(value);
      else selected.delete(value);
      setPromaxScheduleSlicerSelection(kind, [...selected], scope);
    }

    function selectVisiblePromaxScheduleSlicerOptions(kind, event, scope = "schedule") {
      if (event) event.stopPropagation();
      const selected = new Set(promaxScheduleSlicerSelectedKeys(kind, scope));
      promaxScheduleSlicerVisibleOptions(kind, scope).forEach(item => selected.add(item.value));
      setPromaxScheduleSlicerSelection(kind, [...selected], scope);
    }

    function clearPromaxScheduleSlicerSelection(kind, event, scope = "schedule") {
      if (event) event.stopPropagation();
      setPromaxScheduleSlicerSelection(kind, [], scope);
    }

    function togglePromaxScheduleSlicerPanel(kind, event, scope = "schedule") {
      if (event) event.stopPropagation();
      const slicers = scope === "run" ? PROMAX_RUN_SLICERS : PROMAX_SCHEDULE_SLICERS;
      const els = promaxScheduleSlicerElements(kind, scope);
      if (!els.panel) return;
      const willOpen = els.panel.classList.contains("d-none");
      Object.keys(slicers).forEach(otherKind => {
        const other = promaxScheduleSlicerElements(otherKind, scope);
        if (otherKind === kind) return;
        if (other.panel) other.panel.classList.add("d-none");
        if (other.button) other.button.setAttribute("aria-expanded", "false");
      });
      els.panel.classList.toggle("d-none", !willOpen);
      if (els.button) els.button.setAttribute("aria-expanded", willOpen ? "true" : "false");
      if (willOpen) {
        renderPromaxScheduleSlicer(kind, scope);
        if (els.search) els.search.focus();
      }
    }

    function closePromaxScheduleSlicerPanels(event) {
      ["run", "schedule"].forEach(scope => {
        const slicers = scope === "run" ? PROMAX_RUN_SLICERS : PROMAX_SCHEDULE_SLICERS;
        Object.keys(slicers).forEach(kind => {
          const els = promaxScheduleSlicerElements(kind, scope);
          if (!els.panel || els.panel.classList.contains("d-none")) return;
          if (event && els.root && els.root.contains(event.target)) return;
          els.panel.classList.add("d-none");
          if (els.button) els.button.setAttribute("aria-expanded", "false");
        });
      });
    }

    function setupPromaxScheduleSlicerEvents(scope = "schedule") {
      const slicers = scope === "run" ? PROMAX_RUN_SLICERS : PROMAX_SCHEDULE_SLICERS;
      Object.keys(slicers).forEach(kind => {
        const els = promaxScheduleSlicerElements(kind, scope);
        if (els.button) {
          els.button.addEventListener("click", event => togglePromaxScheduleSlicerPanel(kind, event, scope));
        }
        if (els.search) {
          els.search.addEventListener("input", () => renderPromaxScheduleSlicer(kind, scope));
          els.search.addEventListener("keydown", event => {
            if (event.key !== "Escape") return;
            closePromaxScheduleSlicerPanels();
            if (els.button) els.button.focus();
          });
        }
        if (els.selectAllBtn) {
          els.selectAllBtn.addEventListener("click", event => selectVisiblePromaxScheduleSlicerOptions(kind, event, scope));
        }
        if (els.clearBtn) {
          els.clearBtn.addEventListener("click", event => clearPromaxScheduleSlicerSelection(kind, event, scope));
        }
      });
      if (scope === "schedule") document.addEventListener("click", closePromaxScheduleSlicerPanels);
    }

    function renderPromaxSelectionResellers(scope, selectedUnits = null) {
      const stateKeys = promaxSelectionStateKeys(scope);
      if (Array.isArray(selectedUnits)) {
        state.promax[stateKeys.units] = selectedUnits.map(String);
      } else if (!Array.isArray(state.promax[stateKeys.units])) {
        state.promax[stateKeys.units] = PROMAX_RESELLERS.map(reseller => reseller.id);
      }
      renderPromaxScheduleSlicer("reseller", scope);
    }

    function renderPromaxSelectionRoutineGroups(scope) {
      renderPromaxScheduleSlicer("routine", scope);
      updatePromaxActionState();
    }

    function renderPromaxSelectionCatalog(scope, { categoryIds = null, routines = null } = {}) {
      const stateKeys = promaxSelectionStateKeys(scope);
      const categories = promaxCatalogCategories();
      if (Array.isArray(categoryIds)) {
        state.promax[stateKeys.categories] = categoryIds.map(String);
      } else if (!Array.isArray(state.promax[stateKeys.categories])) {
        if (categories.length) state.promax[stateKeys.categories] = [categories[0].id];
      }
      if (routines && typeof routines === "object") {
        state.promax[stateKeys.routines] = Object.fromEntries(
          Object.entries(routines).map(([categoryId, values]) => [
            String(categoryId),
            Array.isArray(values) ? values.map(String) : []
          ])
        );
      }
      const selectedRoutines = { ...(state.promax[stateKeys.routines] || {}) };
      promaxSelectionSelectedCategories(scope).forEach(categoryId => {
        if (Array.isArray(selectedRoutines[categoryId])) return;
        const category = promaxCatalogCategory(categoryId);
        selectedRoutines[categoryId] = category
          ? category.routines.map(routine => routine.id)
          : [];
      });
      state.promax[stateKeys.routines] = selectedRoutines;
      renderPromaxScheduleSlicer("category", scope);
      renderPromaxSelectionRoutineGroups(scope);
    }

    function renderPromaxRunResellers(selectedUnits = null) {
      renderPromaxSelectionResellers("run", selectedUnits);
    }

    function renderPromaxRunCatalog(options = {}) {
      renderPromaxSelectionCatalog("run", options);
    }

    function renderPromaxScheduleResellers(selectedUnits = null) {
      renderPromaxSelectionResellers("schedule", selectedUnits);
    }

    function renderPromaxScheduleRoutineGroups() {
      renderPromaxSelectionRoutineGroups("schedule");
    }

    function renderPromaxScheduleCatalog(options = {}) {
      renderPromaxSelectionCatalog("schedule", options);
    }

    async function openLigaEntregaPromax() {
      if (!state.panel || !state.panel.canManagePromax) {
        addLog("Sem permissão para acessar a Liga no Promax.", "warn");
        return;
      }
      showPanelTab("promaxTab");
      updateFlowNavigation("promaxTab");
      if (!state.promax.catalog) {
        await syncPromax({ silent: true });
      }
      const category = promaxCatalogCategory("liga_entrega");
      if (!category) {
        addLog("Grupo Liga Entrega ainda não apareceu no catálogo Promax.", "warn");
        return;
      }
      const routines = category.routines.map(routine => routine.id);
      setPromaxScheduleSlicerSelection("category", ["liga_entrega"], "run");
      setPromaxScheduleSlicerSelection(
        "routine",
        routines.map(routineId => promaxScheduleRoutineKey("liga_entrega", routineId)),
        "run"
      );
      if (E.promaxSendDates) E.promaxSendDates.checked = true;
      if (E.promaxPublish) E.promaxPublish.checked = true;
      syncPromaxDateFields();
      addLog("Liga Entrega selecionada no Promax Admin.", "ok");
    }

    function promaxRunBatchPayload() {
      const categoryIds = promaxRunSelectedCategories();
      if (!categoryIds.length) throw new Error("Selecione pelo menos um grupo para executar.");
      const routinesByCategory = promaxRunSelectedRoutines();
      const groups = categoryIds.map(categoryId => {
        const routines = routinesByCategory[categoryId] || [];
        if (!routines.length) {
          const category = promaxCatalogCategory(categoryId);
          throw new Error(`Selecione pelo menos uma rotina para ${category ? category.name : categoryId}.`);
        }
        return { category: categoryId, routines };
      });
      if (groups.some(group => group.category === "cora_critica")) {
        if (groups.length > 1) throw new Error("Execute a Crítica Cora separadamente dos grupos Promax.");
        return {
          cora_critica: true,
          target_worker_id: String(E.promaxRunTargetWorker && E.promaxRunTargetWorker.value || "") || null
        };
      }
      const units = promaxRunSelectedUnits();
      if (!units.length) throw new Error("Selecione pelo menos uma revenda.");
      const startDate = String(E.promaxStartDate && E.promaxStartDate.value || "");
      const endDate = String(E.promaxEndDate && E.promaxEndDate.value || "");
      if (!startDate || !endDate) throw new Error("Informe o período da execução.");
      if (endDate < startDate) throw new Error("A data final não pode ser anterior a inicial.");
      return {
        groups,
        units,
        start_date: startDate,
        end_date: endDate,
        send_dates: Boolean(E.promaxSendDates && E.promaxSendDates.checked),
        publish: Boolean(E.promaxPublish && E.promaxPublish.checked),
        target_worker_id: String(E.promaxRunTargetWorker && E.promaxRunTargetWorker.value || "") || null
      };
    }

    function promaxScheduleSelectedUnits() {
      return promaxSelectionSelectedUnits("schedule");
    }

    function promaxSelectedScheduleDays() {
      const inputs = E.promaxScheduleDailyDays
        ? Array.from(E.promaxScheduleDailyDays.querySelectorAll(".promax-schedule-day"))
        : [];
      return inputs
        .filter(input => input.checked)
        .map(input => Number(input.value))
        .filter(value => Number.isInteger(value) && value >= 0 && value <= 6);
    }

    function setPromaxSelectedScheduleDays(days) {
      const selected = new Set((Array.isArray(days) ? days : []).map(Number));
      if (!E.promaxScheduleDailyDays) return;
      E.promaxScheduleDailyDays.querySelectorAll(".promax-schedule-day").forEach(input => {
        input.checked = selected.has(Number(input.value));
      });
    }

    function promaxFormatWeekday(value) {
      const day = PROMAX_WEEKDAYS.find(item => item.value === Number(value));
      return day ? day.short : String(value);
    }

    function promaxTimeToMinutes(value) {
      const text = String(value || "").trim();
      const match = text.match(/^(\d{1,2})(?::(\d{2}))?$/);
      if (!match) return null;
      const hours = Number(match[1]);
      const minutes = Number(match[2] || 0);
      if (!Number.isInteger(hours) || !Number.isInteger(minutes) || hours < 0 || hours > 23 || minutes < 0 || minutes > 59) return null;
      return hours * 60 + minutes;
    }

    function promaxMinutesToTime(minutes) {
      const normalized = Number(minutes);
      const hours = Math.floor(normalized / 60);
      const mins = normalized % 60;
      return `${String(hours).padStart(2, "0")}:${String(mins).padStart(2, "0")}`;
    }

    function promaxSpecificScheduleTimes() {
      const times = new Set();
      const rawHours = String(E.promaxScheduleSpecificHours && E.promaxScheduleSpecificHours.value || "");
      rawHours.split(/[,\s;]+/).forEach(part => {
        const text = String(part || "").trim();
        if (!text) return;
        const minutes = promaxTimeToMinutes(text.includes(":") ? text : `${text}:00`);
        if (minutes != null) times.add(promaxMinutesToTime(minutes));
      });
      const start = promaxTimeToMinutes(E.promaxScheduleSpecificStart && E.promaxScheduleSpecificStart.value);
      const end = promaxTimeToMinutes(E.promaxScheduleSpecificEnd && E.promaxScheduleSpecificEnd.value);
      const step = Number(E.promaxScheduleSpecificStep && E.promaxScheduleSpecificStep.value || 0);
      if (start != null || end != null || step) {
        if (start == null || end == null || start > end) throw new Error("Confira o intervalo de horários da agenda específica.");
        if (!Number.isInteger(step) || step < 1 || step > 120) throw new Error("O intervalo em minutos deve ficar entre 1 e 120.");
        for (let current = start; current <= end; current += step) {
          times.add(promaxMinutesToTime(current));
        }
      }
      return Array.from(times).sort();
    }

    function updatePromaxSpecificSchedulePreview() {
      if (!E.promaxScheduleSpecificPreview) return;
      try {
        const times = promaxSpecificScheduleTimes();
        E.promaxScheduleSpecificPreview.textContent = times.length
          ? `${times.length} horario(s): ${times.slice(0, 8).join(", ")}${times.length > 8 ? "..." : ""}`
          : "Informe os horários.";
      } catch (_err) {
        E.promaxScheduleSpecificPreview.textContent = "Intervalo inválido.";
      }
    }

    function promaxHourlyScheduleTimes() {
      const start = promaxTimeToMinutes(E.promaxScheduleHourlyStart && E.promaxScheduleHourlyStart.value);
      const end = promaxTimeToMinutes(E.promaxScheduleHourlyEnd && E.promaxScheduleHourlyEnd.value);
      const step = Number(E.promaxScheduleHourlyStep && E.promaxScheduleHourlyStep.value || 60);
      if (start == null || end == null || start > end) {
        throw new Error("Confira o intervalo de horários da agenda recorrente.");
      }
      if (![5, 30, 60].includes(step)) {
        throw new Error("Escolha um intervalo válido para a agenda recorrente.");
      }
      const times = [];
      for (let current = start; current <= end; current += step) {
        times.push(promaxMinutesToTime(current));
      }
      return times;
    }

    function updatePromaxHourlySchedulePreview() {
      if (!E.promaxScheduleHourlyPreview) return;
      try {
        const times = promaxHourlyScheduleTimes();
        E.promaxScheduleHourlyPreview.textContent = times.length
          ? `${times.length} horario(s): ${times.slice(0, 10).join(", ")}${times.length > 10 ? "..." : ""}`
          : "Informe os horários.";
      } catch (_err) {
        E.promaxScheduleHourlyPreview.textContent = "Intervalo inválido.";
      }
    }

    function promaxInferRecurringStep(times) {
      const minutes = (Array.isArray(times) ? times : [])
        .map(promaxTimeToMinutes)
        .filter(value => value != null)
        .sort((left, right) => left - right);
      if (minutes.length < 2) return null;
      const step = minutes[1] - minutes[0];
      if (![5, 30, 60].includes(step)) return null;
      for (let index = 2; index < minutes.length; index += 1) {
        if (minutes[index] - minutes[index - 1] !== step) return null;
      }
      return step;
    }

    function promaxApplyScheduleGroupTimes(times) {
      const cleanTimes = (Array.isArray(times) ? times : []).map(String).filter(Boolean).sort();
      if (cleanTimes.length > 1) {
        const step = promaxInferRecurringStep(cleanTimes);
        if (step) {
          E.promaxScheduleType.value = "daily_hourly";
          E.promaxScheduleHourlyStart.value = cleanTimes[0];
          E.promaxScheduleHourlyEnd.value = cleanTimes[cleanTimes.length - 1];
          E.promaxScheduleHourlyStep.value = String(step);
          return;
        }
        E.promaxScheduleType.value = "daily_specific";
        E.promaxScheduleSpecificHours.value = cleanTimes.join(", ");
        return;
      }
      E.promaxScheduleType.value = "daily";
      E.promaxScheduleTime.value = String(cleanTimes[0] || "06:00").slice(0, 5);
    }

    function promaxScheduleTimingPayloads(name) {
      const triggerType = String(E.promaxScheduleTriggerType && E.promaxScheduleTriggerType.value || "time");
      const type = String(E.promaxScheduleType && E.promaxScheduleType.value || "daily");
      if (triggerType === "after") {
        return [{
          name,
          schedule_type: "daily",
          time_of_day: "00:00",
          timezone: "America/Fortaleza",
          weekday: null,
          day_of_month: null
        }];
      }
      if (type === "monthly") {
        return [{
          name,
          schedule_type: "monthly",
          time_of_day: E.promaxScheduleTime.value || "06:00",
          timezone: "America/Fortaleza",
          weekday: null,
          day_of_month: Number(E.promaxScheduleMonthDay.value || 1)
        }];
      }
      if (type === "weekly") {
        return [{
          name,
          schedule_type: "weekly",
          time_of_day: E.promaxScheduleTime.value || "06:00",
          timezone: "America/Fortaleza",
          weekday: Number(E.promaxScheduleWeekday.value || 0),
          day_of_month: null
        }];
      }
      const selectedDays = promaxSelectedScheduleDays();
      if (!selectedDays.length) throw new Error("Selecione pelo menos um dia para a agenda diária.");
      const allDays = selectedDays.length === 7;
      const times = type === "daily_specific"
        ? promaxSpecificScheduleTimes()
        : type === "daily_hourly"
          ? promaxHourlyScheduleTimes()
          : [E.promaxScheduleTime.value || "06:00"];
      if (!times.length) throw new Error("Informe pelo menos um horário para a agenda diária.");
      const payloads = [];
      times.forEach(timeValue => {
        if (allDays) {
          payloads.push({
            name: times.length > 1 ? `${name} ${timeValue}` : name,
            schedule_type: "daily",
            time_of_day: timeValue,
            timezone: "America/Fortaleza",
            weekday: null,
            day_of_month: null
          });
          return;
        }
        selectedDays.forEach(day => {
          payloads.push({
            name: `${name} ${promaxFormatWeekday(day)} ${timeValue}`,
            schedule_type: "weekly",
            time_of_day: timeValue,
            timezone: "America/Fortaleza",
            weekday: day,
            day_of_month: null
          });
        });
      });
      return payloads.map(item => ({
        ...item,
        name: String(item.name || name).slice(0, 120)
      }));
    }

    function promaxScheduleChainPayload() {
      const categoryIds = promaxScheduleSelectedCategories();
      if (!categoryIds.length) throw new Error("Selecione pelo menos um grupo para a agenda.");
      const routinesByCategory = promaxScheduleSelectedRoutines();
      const groups = categoryIds.map(categoryId => {
        const routines = routinesByCategory[categoryId] || [];
        if (!routines.length) {
          const category = promaxCatalogCategory(categoryId);
          throw new Error(`Selecione pelo menos uma rotina para ${category ? category.name : categoryId}.`);
        }
        return { category: categoryId, routines };
      });
      const units = promaxScheduleSelectedUnits();
      if (!units.length) throw new Error("Selecione pelo menos uma revenda.");
      const startDate = String(E.promaxScheduleStartDate && E.promaxScheduleStartDate.value || "");
      const endDate = String(E.promaxScheduleEndDate && E.promaxScheduleEndDate.value || "");
      if (!startDate || !endDate) throw new Error("Informe o período da agenda.");
      if (endDate < startDate) throw new Error("A data final da agenda não pode ser anterior a inicial.");
      const triggerType = String(E.promaxScheduleTriggerType && E.promaxScheduleTriggerType.value || "time");
      const triggerAfterScheduleId = triggerType === "after"
        ? String(E.promaxScheduleTriggerSchedule && E.promaxScheduleTriggerSchedule.value || "")
        : "";
      if (triggerType === "after" && !triggerAfterScheduleId) {
        throw new Error("Selecione a agenda que deve terminar antes desta cadeia.");
      }
      return {
        groups,
        units,
        start_date: startDate,
        end_date: endDate,
        send_dates: Boolean(E.promaxScheduleSendDates && E.promaxScheduleSendDates.checked),
        publish: Boolean(E.promaxSchedulePublish && E.promaxSchedulePublish.checked),
        target_worker_id: String(E.promaxScheduleTargetWorker && E.promaxScheduleTargetWorker.value || "") || null,
        trigger_after_schedule_id: triggerAfterScheduleId || null
      };
    }

    function renderPromaxScheduleTriggerOptions(selectedId = null) {
      if (!E.promaxScheduleTriggerSchedule) return;
      const currentValue = selectedId == null
        ? String(E.promaxScheduleTriggerSchedule.value || "")
        : String(selectedId || "");
      const editingId = String(state.promax.editingScheduleId || "");
      E.promaxScheduleTriggerSchedule.replaceChildren();
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = "Selecione uma agenda";
      E.promaxScheduleTriggerSchedule.appendChild(placeholder);
      (state.promax.schedules || []).forEach(schedule => {
        const scheduleId = String(schedule.id || "");
        if (!scheduleId || scheduleId === editingId) return;
        const groupId = String(schedule.job_type || (schedule.payload || {}).category || "");
        const group = promaxCatalogCategory(groupId);
        const option = document.createElement("option");
        option.value = scheduleId;
        option.textContent = `${schedule.name || "Agenda"} - ${group ? group.name : groupId}`;
        option.selected = scheduleId === currentValue;
        E.promaxScheduleTriggerSchedule.appendChild(option);
      });
      E.promaxScheduleTriggerSchedule.value = currentValue;
    }

    function promaxStatusLabel(status) {
      return {
        pending: "Pendente",
        running: "Executando",
        success: "Concluido",
        partial_success: "Parcial",
        failed: "Falhou",
        cancel_requested: "Cancelando",
        cancelled: "Cancelado"
      }[String(status || "")] || String(status || "-");
    }

    function promaxStatusClass(status) {
      const value = String(status || "");
      if (value === "success") return "promax-status--success";
      if (value === "running") return "promax-status--running";
      if (value === "pending" || value === "partial_success") return "promax-status--warning";
      if (value === "failed" || value === "cancel_requested") return "promax-status--danger";
      return "";
    }

    function promaxScheduleTimingLabel(schedule) {
      const type = String(schedule && schedule.schedule_type || "");
      const timeValue = String(schedule && schedule.time_of_day || "").slice(0, 5);
      if (type === "weekly") return `${promaxFormatWeekday(schedule.weekday)} ${timeValue}`;
      if (type === "monthly") return `Dia ${schedule.day_of_month || "-"} ${timeValue}`;
      if (type === "daily") return `Diária ${timeValue}`;
      return `${type || "-"} ${timeValue}`;
    }

    function promaxScheduleBaseName(schedule) {
      const rawName = String(schedule && schedule.name || "").trim();
      let name = rawName || "Agenda";
      name = name.replace(/\s+(Seg|Ter|Qua|Qui|Sex|Sab|Dom)\s+\d{1,2}:\d{2}$/i, "");
      name = name.replace(/\s+\d{1,2}:\d{2}$/i, "");
      return name.trim() || rawName || "Agenda";
    }

    function promaxSchedulePayloadGroupKey(schedule) {
      const payload = schedule && schedule.payload && typeof schedule.payload === "object"
        ? schedule.payload
        : {};
      const routines = Array.isArray(payload.routines)
        ? payload.routines.map(String).sort()
        : [];
      const units = Array.isArray(payload.units)
        ? payload.units.map(String).sort()
        : [];
      const groups = Array.isArray(payload.groups)
        ? payload.groups.map(group => ({
          category: String(group && group.category || ""),
          routines: Array.isArray(group && group.routines) ? group.routines.map(String).sort() : []
        })).sort((left, right) => left.category.localeCompare(right.category))
        : [];
      return JSON.stringify({
        category: String(payload.category || schedule && schedule.job_type || ""),
        groups,
        routines,
        units,
        start_date: String(payload.start_date || ""),
        end_date: String(payload.end_date || ""),
        send_dates: Boolean(payload.send_dates),
        publish: Boolean(payload.publish),
      });
    }

    function promaxScheduleCreatedGroupKey(schedule) {
      const createdAt = Date.parse(schedule && schedule.created_at);
      if (!Number.isFinite(createdAt)) return "";
      const bucketMs = 5 * 60 * 1000;
      return String(Math.floor(createdAt / bucketMs));
    }

    function promaxScheduleSortValue(schedule) {
      const type = String(schedule && schedule.schedule_type || "");
      const weekday = schedule && schedule.weekday != null ? Number(schedule.weekday) : 99;
      const dayOfMonth = schedule && schedule.day_of_month != null ? Number(schedule.day_of_month) : 99;
      const timeValue = String(schedule && schedule.time_of_day || "").slice(0, 5);
      return `${type}|${String(weekday).padStart(2, "0")}|${String(dayOfMonth).padStart(2, "0")}|${timeValue}|${String(schedule && schedule.id || "")}`;
    }

    function promaxBuildScheduleGroups(schedules) {
      const buckets = new Map();
      (Array.isArray(schedules) ? schedules : []).forEach(schedule => {
        if (!schedule || typeof schedule !== "object") return;
        const payload = schedule.payload && typeof schedule.payload === "object" ? schedule.payload : {};
        const baseName = promaxScheduleBaseName(schedule);
        const jobType = String(schedule.job_type || payload.category || "-");
        const triggerScheduleId = String(schedule.trigger_after_schedule_id || "");
        const groupKey = [
          baseName,
          jobType,
          String(schedule.schedule_type || ""),
          triggerScheduleId,
          promaxScheduleCreatedGroupKey(schedule),
          promaxSchedulePayloadGroupKey(schedule)
        ].join("||");
        if (!buckets.has(groupKey)) {
          buckets.set(groupKey, {
            key: "",
            baseName,
            jobType,
            triggerScheduleId,
            payload,
            schedules: []
          });
        }
        buckets.get(groupKey).schedules.push(schedule);
      });

      return Array.from(buckets.values()).map((group, index) => {
        group.key = `schedule-group-${index}`;
        group.schedules.sort((left, right) => promaxScheduleSortValue(left).localeCompare(promaxScheduleSortValue(right)));
        group.primary = group.schedules.find(schedule => Boolean(schedule.enabled)) || group.schedules[0] || {};
        group.enabledCount = group.schedules.filter(schedule => Boolean(schedule.enabled)).length;
        group.days = Array.from(new Set(
          group.schedules
            .map(schedule => schedule.weekday)
            .filter(value => value != null)
            .map(Number)
            .filter(value => Number.isInteger(value) && value >= 0 && value <= 6)
        )).sort((left, right) => left - right);
        group.monthDays = Array.from(new Set(
          group.schedules
            .map(schedule => schedule.day_of_month)
            .filter(value => value != null)
            .map(Number)
            .filter(value => Number.isInteger(value) && value >= 1 && value <= 31)
        )).sort((left, right) => left - right);
        group.times = Array.from(new Set(
          group.schedules
            .map(schedule => String(schedule.time_of_day || "").slice(0, 5))
            .filter(Boolean)
        )).sort();
        const nextRuns = group.schedules
          .map(schedule => ({ raw: schedule.next_run_at, time: Date.parse(schedule.next_run_at) }))
          .filter(item => Number.isFinite(item.time))
          .sort((left, right) => left.time - right.time);
        group.nextRunAt = nextRuns.length ? nextRuns[0].raw : "";
        return group;
      }).sort((left, right) => {
        const nextLeft = Date.parse(left.nextRunAt);
        const nextRight = Date.parse(right.nextRunAt);
        if (Number.isFinite(nextLeft) && Number.isFinite(nextRight) && nextLeft !== nextRight) return nextLeft - nextRight;
        return String(left.baseName || "").localeCompare(String(right.baseName || ""));
      });
    }

    function promaxFindScheduleGroup(groupKey) {
      return (state.promax.scheduleGroups || []).find(group => String(group.key) === String(groupKey));
    }

    function promaxScheduleGroupTimeLabel(group) {
      const times = Array.isArray(group && group.times) ? group.times : [];
      if (times.length === 1) return times[0];
      return times.length ? `${times.length} horários` : "-";
    }

    function promaxScheduleGroupRepetitionLabel(group) {
      if (!group) return "-";
      if (group.triggerScheduleId) {
        const schedules = Array.isArray(state.promax.schedules) ? state.promax.schedules : [];
        const triggerSchedule = schedules.find(item => String(item.id || "") === String(group.triggerScheduleId));
        return `Após ${triggerSchedule ? triggerSchedule.name : String(group.triggerScheduleId).slice(0, 8)}`;
      }
      const primary = group.primary || {};
      const type = String(primary.schedule_type || "");
      const timeLabel = promaxScheduleGroupTimeLabel(group);
      if (type === "weekly") {
        const days = Array.isArray(group.days) && group.days.length
          ? group.days.map(promaxFormatWeekday).join(", ")
          : "Sem dia";
        return `${days} | ${timeLabel}`;
      }
      if (type === "monthly") {
        const days = Array.isArray(group.monthDays) && group.monthDays.length
          ? group.monthDays.join(", ")
          : "-";
        return `Dia ${days} | ${timeLabel}`;
      }
      if (type === "daily") return `Diária | ${timeLabel}`;
      return promaxScheduleTimingLabel(primary);
    }

    function promaxScheduleGroupStatus(group) {
      const total = Array.isArray(group && group.schedules) ? group.schedules.length : 0;
      const enabled = Number(group && group.enabledCount || 0);
      if (!total || !enabled) return { label: "Pausada", badge: "text-bg-secondary" };
      if (enabled === total) return { label: "Ativa", badge: "text-bg-success" };
      return { label: "Parcial", badge: "text-bg-warning" };
    }

    function promaxScheduleGroupSubtitle(group) {
      const total = Array.isArray(group && group.schedules) ? group.schedules.length : 0;
      const enabled = Number(group && group.enabledCount || 0);
      const suffix = total === 1 ? "repeticao" : "repeticoes";
      return `${total} ${suffix} | ${enabled} ativa(s)`;
    }

    function promaxUnitLabel(unitId) {
      const id = String(unitId || "").trim();
      const reseller = PROMAX_RESELLERS.find(item => item.id === id);
      return reseller ? `${reseller.name} (${id})` : id || "-";
    }

    function promaxJobResultText(job) {
      const result = job && job.result && typeof job.result === "object" ? job.result : {};
      return String(result.message || job.error || job.failure_reason || "").trim();
    }

    function promaxJobFailedUnitMap(job) {
      const result = job && job.result && typeof job.result === "object" ? job.result : {};
      const failedMap = new Map();
      const addFailed = (unitId, detail) => {
        const cleanUnit = String(unitId || "").trim();
        if (!cleanUnit) return;
        failedMap.set(cleanUnit, detail && typeof detail === "object" ? detail : {});
      };
      if (Array.isArray(result.failed_units)) {
        result.failed_units.forEach(unitId => addFailed(unitId, {}));
      }
      if (Array.isArray(result.failed_unit_details)) {
        result.failed_unit_details.forEach(detail => {
          if (!detail || typeof detail !== "object") return;
          const unitId = detail.unit || detail.unidade || detail.unit_id || detail.code || detail.id;
          addFailed(unitId, detail);
        });
      }
      return failedMap;
    }

    function promaxJobUnitRows(job) {
      const payload = job && job.payload && typeof job.payload === "object" ? job.payload : {};
      const selectedUnits = Array.isArray(payload.units) && payload.units.length
        ? payload.units.map(String)
        : PROMAX_RESELLERS.map(item => item.id);
      const status = String(job && job.status || "");
      const resultText = promaxJobResultText(job);
      const normalizedResult = normalizeSearchText(resultText);
      const failedMap = promaxJobFailedUnitMap(job);
      return selectedUnits.map(unitId => {
        const reseller = PROMAX_RESELLERS.find(item => item.id === String(unitId));
        const unitName = reseller ? reseller.name : String(unitId);
        const mentioned = normalizedResult.includes(normalizeSearchText(unitId))
          || (unitName && normalizedResult.includes(normalizeSearchText(unitName)));
        const failedDetail = failedMap.get(String(unitId));
        let label = "Não executado";
        let tone = "warn";
        if (status === "success") {
          label = "Concluido";
          tone = "ok";
        } else if (status === "partial_success") {
          label = failedDetail || mentioned ? "Falhou" : "Concluido";
          tone = failedDetail || mentioned ? "err" : "ok";
        } else if (status === "failed") {
          label = "Falhou";
          tone = "err";
        } else if (status === "running" || status === "cancel_requested") {
          label = status === "cancel_requested" ? "Parando" : "Executando";
          tone = "warn";
        } else if (status === "pending") {
          label = "Aguardando";
          tone = "warn";
        } else if (status === "cancelled") {
          label = "Cancelado";
          tone = "err";
        }
        const detailText = failedDetail && typeof failedDetail === "object"
          ? String(failedDetail.detail || failedDetail.detalhe || failedDetail.message || failedDetail.status || "").trim()
          : "";
        return { unitId: String(unitId), unitName, label, tone, detailText };
      });
    }

    function promaxJobUnitSummary(job) {
      const rows = promaxJobUnitRows(job);
      const failed = rows.filter(row => row.tone === "err").length;
      const ok = rows.filter(row => row.tone === "ok").length;
      if (!rows.length) return "Sem unidades";
      if (failed) return `${failed}/${rows.length} com problema`;
      if (ok === rows.length) return `${rows.length}/${rows.length} concluídas`;
      return `${rows.length} unidade(s)`;
    }

    function promaxImpactMetrics(jobs) {
      const manualMinutesPerWorkUnit = 12;
      const sourceJobs = Array.isArray(jobs) ? jobs : [];
      const relevantJobs = sourceJobs.filter(job => {
        const status = String(job && job.status || "");
        return String(job && job.job_type || "") !== "reprocess_publication"
          && ["success", "partial_success", "failed", "cancelled"].includes(status);
      });
      const analyzedJobs = relevantJobs.filter(job => promaxJobRuntimeMinutes(job) > 0 || promaxJobWorkUnits(job) > 0);
      const totals = analyzedJobs.reduce((acc, job) => {
        const status = String(job && job.status || "");
        const workUnits = promaxJobWorkUnits(job);
        const runtimeMinutes = promaxJobRuntimeMinutes(job);
        const manualMinutes = workUnits * manualMinutesPerWorkUnit;
        const savedMinutes = Math.max(0, manualMinutes - runtimeMinutes);
        acc.workUnits += workUnits;
        acc.runtimeMinutes += runtimeMinutes;
        acc.manualMinutes += manualMinutes;
        acc.savedMinutes += savedMinutes;
        acc.done += ["success", "partial_success"].includes(status) ? 1 : 0;
        acc.success += status === "success" ? 1 : 0;
        acc.partial += status === "partial_success" ? 1 : 0;
        acc.failed += ["failed", "cancelled"].includes(status) ? 1 : 0;
        const dayKey = promaxJobFinishedDay(job);
        if (dayKey) {
          if (!acc.days[dayKey]) acc.days[dayKey] = { day: dayKey, savedMinutes: 0, partial: 0, jobs: 0 };
          acc.days[dayKey].savedMinutes += savedMinutes;
          acc.days[dayKey].partial += status === "partial_success" ? 1 : 0;
          acc.days[dayKey].jobs += 1;
        }
        return acc;
      }, {
        analyzed: analyzedJobs.length,
        done: 0,
        success: 0,
        partial: 0,
        failed: 0,
        workUnits: 0,
        runtimeMinutes: 0,
        manualMinutes: 0,
        savedMinutes: 0,
        days: {}
      });
      const daySeries = Object.values(totals.days)
        .sort((a, b) => String(a.day).localeCompare(String(b.day)))
        .slice(-7);
      return { ...totals, daySeries, manualMinutesPerWorkUnit };
    }

    function promaxJobWorkUnits(job) {
      const payload = job && job.payload && typeof job.payload === "object" ? job.payload : {};
      const units = Array.isArray(payload.units) && payload.units.length ? payload.units : [];
      let routineCount = 0;
      if (Array.isArray(payload.groups)) {
        routineCount = payload.groups.reduce((total, group) => {
          const routines = group && Array.isArray(group.routines) ? group.routines : [];
          return total + routines.length;
        }, 0);
      } else if (Array.isArray(payload.routines)) {
        routineCount = payload.routines.length;
      }
      return Math.max(0, units.length * routineCount);
    }

    function promaxJobRuntimeMinutes(job) {
      const started = new Date(job && job.started_at || "");
      const finished = new Date(job && job.finished_at || "");
      if (Number.isNaN(started.getTime()) || Number.isNaN(finished.getTime()) || finished <= started) return 0;
      return Math.round((finished.getTime() - started.getTime()) / 60000);
    }

    function promaxJobFinishedDay(job) {
      const dt = new Date(job && (job.finished_at || job.updated_at || job.created_at) || "");
      if (Number.isNaN(dt.getTime())) return "";
      const year = dt.getFullYear();
      const month = String(dt.getMonth() + 1).padStart(2, "0");
      const day = String(dt.getDate()).padStart(2, "0");
      return `${year}-${month}-${day}`;
    }

    function formatPromaxDuration(minutes) {
      const safeMinutes = Math.max(0, Math.round(Number(minutes || 0)));
      if (!safeMinutes) return "0min";
      const hours = Math.floor(safeMinutes / 60);
      const mins = safeMinutes % 60;
      if (!hours) return `${mins}min`;
      return mins ? `${hours}h ${mins}min` : `${hours}h`;
    }

    function renderPromaxImpact(jobs) {
      const metrics = promaxImpactMetrics(jobs);
      if (E.promaxImpactSaved) E.promaxImpactSaved.textContent = formatPromaxDuration(metrics.savedMinutes);
      if (E.promaxImpactManual) E.promaxImpactManual.textContent = `Manual estimado: ${formatPromaxDuration(metrics.manualMinutes)}`;
      if (E.promaxImpactDone) E.promaxImpactDone.textContent = formatNumber(metrics.done);
      if (E.promaxImpactSuccessRate) {
        const denominator = metrics.success + metrics.partial + metrics.failed;
        const rate = denominator ? Math.round((metrics.success / denominator) * 100) : 0;
        E.promaxImpactSuccessRate.textContent = `Taxa de sucesso: ${rate}%`;
      }
      if (E.promaxImpactAvgRuntime) {
        const avg = metrics.analyzed ? metrics.runtimeMinutes / metrics.analyzed : 0;
        E.promaxImpactAvgRuntime.textContent = formatPromaxDuration(avg);
      }
      if (E.promaxImpactRuns) E.promaxImpactRuns.textContent = `Automacoes analisadas: ${formatNumber(metrics.analyzed)}`;
      if (E.promaxImpactWorkUnits) E.promaxImpactWorkUnits.textContent = formatNumber(metrics.workUnits);
      if (E.promaxImpactPeriod) {
        E.promaxImpactPeriod.textContent = metrics.daySeries.length
          ? `${formatDate(metrics.daySeries[0].day)} a ${formatDate(metrics.daySeries[metrics.daySeries.length - 1].day)}`
          : "Sem histórico";
        E.promaxImpactPeriod.className = `pill ${metrics.daySeries.length ? "ok" : "warn"}`;
      }
      renderPromaxImpactChart(metrics.daySeries);
    }

    function renderPromaxImpactChart(daySeries) {
      if (!E.promaxImpactChart) return;
      const series = Array.isArray(daySeries) ? daySeries : [];
      if (!series.length) {
        E.promaxImpactChart.innerHTML = '<div class="promax-impact-empty">Sem execuções finalizadas para montar o gráfico.</div>';
        return;
      }
      const width = 720;
      const height = 180;
      const top = 16;
      const bottom = 30;
      const left = 34;
      const right = 12;
      const plotHeight = height - top - bottom;
      const plotWidth = width - left - right;
      const maxValue = Math.max(...series.map(item => Number(item.savedMinutes || 0)), 1);
      const gap = 12;
      const barWidth = Math.max(28, (plotWidth - gap * (series.length - 1)) / series.length);
      const bars = series.map((item, index) => {
        const value = Number(item.savedMinutes || 0);
        const barHeight = Math.max(2, (value / maxValue) * plotHeight);
        const x = left + index * (barWidth + gap);
        const y = top + plotHeight - barHeight;
        const label = formatDate(item.day);
        const valueLabel = formatPromaxDuration(value);
        const partialClass = Number(item.partial || 0) > 0 ? " partial" : "";
        return `
          <rect class="promax-impact-bar${partialClass}" x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barWidth.toFixed(1)}" height="${barHeight.toFixed(1)}" rx="5">
            <title>${escapeHtml(label)}: ${escapeHtml(valueLabel)}</title>
          </rect>
          <text x="${(x + barWidth / 2).toFixed(1)}" y="${(y - 5).toFixed(1)}" text-anchor="middle">${escapeHtml(valueLabel)}</text>
          <text x="${(x + barWidth / 2).toFixed(1)}" y="${height - 8}" text-anchor="middle">${escapeHtml(label)}</text>
        `;
      }).join("");
      E.promaxImpactChart.innerHTML = `
        <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Ganho estimado por dia">
          <line class="promax-impact-gridline" x1="${left}" y1="${top}" x2="${width - right}" y2="${top}"></line>
          <line class="promax-impact-axis" x1="${left}" y1="${top + plotHeight}" x2="${width - right}" y2="${top + plotHeight}"></line>
          <line class="promax-impact-axis" x1="${left}" y1="${top}" x2="${left}" y2="${top + plotHeight}"></line>
          ${bars}
        </svg>
      `;
    }

    function promaxOpenUnitsModal(jobId) {
      const job = (Array.isArray(state.promax.jobs) ? state.promax.jobs : []).find(item => String(item && item.id || "") === String(jobId));
      if (!job) {
        addLog("Execução Promax não encontrada para resumo.", "warn");
        return;
      }
      const rows = promaxJobUnitRows(job);
      const payload = job && job.payload && typeof job.payload === "object" ? job.payload : {};
      const routines = Array.isArray(payload.routines) ? payload.routines.join(", ") : String(job.job_type || "-");
      if (E.promaxUnitsModalTitle) E.promaxUnitsModalTitle.textContent = `Resumo ${String(job.id || "").slice(0, 8)}`;
      if (E.promaxUnitsModalSubtitle) E.promaxUnitsModalSubtitle.textContent = `${routines || "-"} | ${promaxStatusLabel(job.status)}`;
      if (E.promaxUnitsModalBody) {
        E.promaxUnitsModalBody.innerHTML = rows.length
          ? rows.map(row => `<tr><td><strong>${escapeHtml(row.unitName)}</strong><div class="mono small text-secondary">${escapeHtml(row.unitId)}</div>${row.detailText ? `<div class="small text-secondary mt-1">${escapeHtml(row.detailText)}</div>` : ""}</td><td><span class="promax-unit-status ${escapeHtml(row.tone)}">${escapeHtml(row.label)}</span></td></tr>`).join("")
          : '<tr><td colspan="2" class="text-center py-3 text-secondary">Esta execução não possui unidades no payload.</td></tr>';
      }
      if (promaxUnitsModalInstance) promaxUnitsModalInstance.show();
    }

    function promaxWorkersFromPayload(payload) {
      const workers = Array.isArray(payload && payload.workers) ? payload.workers : [];
      return workers.slice().sort((a, b) => {
        const onlineDelta = Number(Boolean(b && b.online)) - Number(Boolean(a && a.online));
        if (onlineDelta) return onlineDelta;
        return new Date(b && b.heartbeat_at || 0) - new Date(a && a.heartbeat_at || 0);
      });
    }

    function promaxWorkerDisplayName(worker) {
      const id = String(worker && worker.worker_id || "").trim();
      return id || "worker-sem-id";
    }

    function promaxFechamentoWorker(workers) {
      return (workers || []).find(worker => /fechamento/i.test(promaxWorkerDisplayName(worker)))
        || (workers || []).find(worker => worker && worker.online)
        || null;
    }

    function renderPromaxWorkers(workers) {
      if (!E.promaxWorkerGrid) return;
      if (!workers.length) {
        E.promaxWorkerGrid.innerHTML = '<div class="empty-state py-2">Nenhum worker registrado ainda.</div>';
        return;
      }
      E.promaxWorkerGrid.innerHTML = workers.map(worker => {
        const online = Boolean(worker && worker.online);
        const metadata = worker && worker.metadata && typeof worker.metadata === "object" ? worker.metadata : {};
        const currentJob = worker && worker.current_job_id ? String(worker.current_job_id).slice(0, 8) : "";
        const subtitle = currentJob
          ? `Job ${currentJob}`
          : (metadata.status ? `Status ${metadata.status}` : "Sem job ativo");
        return `<div class="promax-worker-card ${online ? "is-online" : "is-offline"}">
          <div class="d-flex align-items-center justify-content-between gap-2">
            <strong>${escapeHtml(promaxWorkerDisplayName(worker))}</strong>
            <span class="pill ${online ? "ok" : "warn"}">${online ? "Online" : "Offline"}</span>
          </div>
          <small>${escapeHtml(subtitle)}</small>
          <small>Último sinal: ${escapeHtml(formatDateTime(worker && worker.heartbeat_at))}</small>
        </div>`;
      }).join("");
    }

    function promaxAssignableCategories() {
      const categories = promaxCatalogCategories().map(category => ({
        id: category.id,
        name: category.name,
        routines: Array.isArray(category.routines) ? category.routines.map(routine => routine.id).filter(Boolean) : []
      }));
      if (!categories.some(category => category.id === "fechamento-mapa")) {
        categories.push({
          id: "fechamento-mapa",
          name: "Fechamento financeiro",
          routines: ["030302", "03030702"]
        });
      }
      // Pedidos do painel viram jobs "digitacao_030104"; a API procura a regra por esse tipo.
      if (!categories.some(category => category.id === "digitacao_030104")) {
        categories.push({
          id: "digitacao_030104",
          name: "Digitação de pedidos",
          routines: ["030104"]
        });
      }
      return categories;
    }

    function promaxAssignmentForCategory(categoryId) {
      return (state.promax.workerAssignments || []).find(assignment =>
        String(assignment && assignment.scope_type || "category") === "category"
        && String(assignment && assignment.category || "") === String(categoryId || "")
      ) || null;
    }

    function renderPromaxWorkerAssignmentOptions(workers, selectedWorkerId) {
      const options = ['<option value="">Automatico</option>'];
      workers.forEach(worker => {
        const workerId = String(worker && worker.worker_id || "").trim();
        if (!workerId) return;
        const status = worker && worker.online ? "online" : "offline";
        const busy = worker && worker.current_job_id ? " - ocupado" : "";
        options.push(`<option value="${escapeHtml(workerId)}"${workerId === selectedWorkerId ? " selected" : ""}>${escapeHtml(promaxWorkerDisplayName(worker))} (${status}${busy})</option>`);
      });
      return options.join("");
    }

    function renderPromaxTargetWorkerSelect(select, workers, selectedWorkerId = null) {
      if (!select) return;
      const currentWorkerId = selectedWorkerId == null
        ? String(select.value || "")
        : String(selectedWorkerId || "");
      select.innerHTML = renderPromaxWorkerAssignmentOptions(workers, currentWorkerId);
      select.value = currentWorkerId;
    }

    function renderPromaxGradeResellerSelect(select) {
      if (!select) return;
      const selected = String(select.value || "");
      select.innerHTML = `<option value="">Selecione a revenda</option>${PROMAX_RESELLERS.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)} (${escapeHtml(item.id)})</option>`).join("")}`;
      select.value = selected;
    }

    function renderPromaxWorkerAssignments(workers) {
      if (!E.promaxWorkerAssignmentsBody) return;
      const categories = promaxAssignableCategories();
      if (!categories.length) {
        E.promaxWorkerAssignmentsBody.innerHTML = '<tr><td colspan="4" class="text-secondary">Nenhum grupo disponível.</td></tr>';
        return;
      }
      E.promaxWorkerAssignmentsBody.innerHTML = categories.map(category => {
        const assignment = promaxAssignmentForCategory(category.id);
        const selectedWorkerId = String(assignment && assignment.target_worker_id || "");
        const worker = workers.find(item => String(item && item.worker_id || "") === selectedWorkerId);
        const status = !selectedWorkerId
          ? '<span class="pill">Automático</span>'
          : worker
            ? `<span class="pill ${worker.online ? "ok" : "warn"}">${worker.online ? "Online" : "Offline"}</span>`
            : '<span class="pill warn">Não registrado</span>';
        const routineText = category.routines.length ? category.routines.join(", ") : "-";
        return `<tr>
          <td><strong>${escapeHtml(category.name)}</strong><div class="text-secondary small">${escapeHtml(category.id)}</div></td>
          <td class="small">${escapeHtml(routineText)}</td>
          <td>
            <select class="form-select form-select-sm promax-worker-assignment" data-category="${escapeHtml(category.id)}">
              ${renderPromaxWorkerAssignmentOptions(workers, selectedWorkerId)}
            </select>
          </td>
          <td>${status}</td>
        </tr>`;
      }).join("");
    }

    async function savePromaxWorkerAssignments() {
      if (!E.promaxWorkerAssignmentsBody) return;
      const assignments = Array.from(E.promaxWorkerAssignmentsBody.querySelectorAll(".promax-worker-assignment"))
        .map(select => ({
          scope_type: "category",
          category: String(select.dataset.category || ""),
          target_worker_id: String(select.value || "")
        }))
        .filter(item => item.category && item.target_worker_id);
      if (E.promaxSaveWorkerAssignmentsBtn) E.promaxSaveWorkerAssignmentsBtn.disabled = true;
      try {
        const result = await req(CONFIG.endpoints.promax.workerAssignments, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ assignments }),
          timeoutMs: 20000
        });
        state.promax.workerAssignments = Array.isArray(result.assignments) ? result.assignments : [];
        renderPromax();
        addLog("Configuração dos workers salva.", "ok");
      } catch (err) {
        addLog(`Falha ao salvar configuração dos workers: ${err.message}`, "err");
      } finally {
        if (E.promaxSaveWorkerAssignmentsBtn) E.promaxSaveWorkerAssignmentsBtn.disabled = false;
      }
    }

    function renderPromaxCredentials(workers) {
      if (E.promaxCredentialsBody) {
        E.promaxCredentialsBody.querySelectorAll("tr[data-worker-id]").forEach(row => {
          const usernameInput = row.querySelector(".promax-credential-username");
          const workerId = String(row.dataset.workerId || "").trim();
          if (!workerId || !usernameInput) return;
          // A credencial salva e devolvida pela API e a fonte de verdade. Nao
          // deixe um campo vazio de uma renderizacao anterior esconder o
          // usuario persistido quando o painel atualiza automaticamente.
          const draftUsername = String(usernameInput.value || "").trim();
          if (draftUsername) state.promax.credentialUserDrafts[workerId] = draftUsername;
          else delete state.promax.credentialUserDrafts[workerId];
        });
      }
      const credentials = Array.isArray(state.promax.workerCredentials) ? state.promax.workerCredentials : [];
      const byWorkerId = new Map(credentials.map(item => [String(item && item.worker_id || ""), item]));
      const allWorkers = new Map();
      (workers || []).forEach(worker => {
        const workerId = String(worker && worker.worker_id || "").trim();
        if (workerId) allWorkers.set(workerId, worker);
      });
      credentials.forEach(item => {
        const workerId = String(item && item.worker_id || "").trim();
        if (workerId && !allWorkers.has(workerId)) allWorkers.set(workerId, { worker_id: workerId, online: false });
      });
      if (!E.promaxCredentialsBody) return;
      if (!allWorkers.size) {
        E.promaxCredentialsBody.innerHTML = '<tr><td colspan="5" class="text-secondary">Nenhum worker registrado ainda. Inicie o worker para ele aparecer aqui.</td></tr>';
        return;
      }
      E.promaxCredentialsBody.innerHTML = [...allWorkers.values()].map(worker => {
        const workerId = String(worker.worker_id || "");
        const credential = byWorkerId.get(workerId) || {};
        const draftUsername = state.promax.credentialUserDrafts[workerId];
        const username = draftUsername === undefined ? String(credential.username || "") : draftUsername;
        const online = Boolean(worker.online);
        return `<tr data-worker-id="${escapeHtml(workerId)}">
          <td><strong>${escapeHtml(workerId)}</strong></td>
          <td><span class="pill ${online ? "ok" : "warn"}">${online ? "Online" : "Offline"}</span></td>
          <td><input class="form-control form-control-sm promax-credential-username" value="${escapeHtml(username)}" autocomplete="username"></td>
          <td><input class="form-control form-control-sm promax-credential-password" type="password" placeholder="${credential.password_configured ? "Senha configurada" : "Informe a senha"}" autocomplete="new-password"></td>
          <td class="text-end"><button class="btn btn-primary btn-sm promax-save-credential" type="button"><i class="bi bi-lock-fill me-1"></i>Salvar</button></td>
        </tr>`;
      }).join("");
      if (E.promaxCredentialsStatus) E.promaxCredentialsStatus.textContent = `${allWorkers.size} worker(s) disponível(is) para configurar.`;
    }

    function mergePromaxWorkerCredentials(credentials) {
      const merged = new Map(
        (Array.isArray(state.promax.workerCredentials) ? state.promax.workerCredentials : [])
          .map(item => [String(item && item.worker_id || ""), item])
      );
      (Array.isArray(credentials) ? credentials : []).forEach(item => {
        const workerId = String(item && item.worker_id || "").trim();
        if (workerId) merged.set(workerId, item);
      });
      state.promax.workerCredentials = [...merged.values()];
    }

    async function savePromaxCredentials(row) {
      const worker_id = String(row && row.dataset.workerId || "").trim();
      const username = String(row && row.querySelector(".promax-credential-username")?.value || "").trim();
      const passwordInput = row && row.querySelector(".promax-credential-password");
      const password = String(passwordInput && passwordInput.value || "");
      if (!worker_id || !username || !password) { addLog("Informe worker, usuário e senha do Promax.", "warn"); return; }
      const saveButton = row.querySelector(".promax-save-credential");
      if (saveButton) saveButton.disabled = true;
      try {
        const result = await req(CONFIG.endpoints.promax.workerCredentials, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ worker_id, username, password }), timeoutMs: 20000 });
        const saved = result.credentials || {};
        mergePromaxWorkerCredentials([saved]);
        state.promax.credentialUserDrafts[worker_id] = String(saved.username || username);
        if (passwordInput) passwordInput.value = "";
        renderPromaxCredentials(promaxWorkersFromPayload(state.promax.worker || {}));
        addLog(`Credenciais Promax salvas para ${worker_id}.`, "ok");
      } catch (err) { addLog(`Falha ao salvar credenciais Promax: ${err.message}`, "err"); }
      finally { if (saveButton) saveButton.disabled = false; }
    }

    function renderFinanceiroFechamentoWorker(payload) {
      const els = financeiroElements();
      const workers = promaxWorkersFromPayload(payload || state.financeiro.worker || state.promax.worker || {});
      renderFinanceiroFechamentoWorkerSelect(workers);
      if (!els.fechamentoWorkerStatus) return;
      const worker = promaxFechamentoWorker(workers);
      if (!worker) {
        els.fechamentoWorkerStatus.textContent = "Worker fechamento offline";
        els.fechamentoWorkerStatus.className = "pill warn";
        return;
      }
      const online = Boolean(worker.online);
      els.fechamentoWorkerStatus.textContent = online
        ? `Fechamento online: ${promaxWorkerDisplayName(worker)}`
        : `Fechamento offline: ${promaxWorkerDisplayName(worker)}`;
      els.fechamentoWorkerStatus.className = `pill ${online ? "ok" : "warn"}`;
    }

    function renderFinanceiroFechamentoWorkerSelect(workers) {
      const els = financeiroElements();
      const select = els.fechamentoWorker;
      if (!select) return;
      const current = String(select.value || "");
      const options = ['<option value="">Automatico</option>'];
      (Array.isArray(workers) ? workers : [])
        .slice()
        .sort((a, b) => {
          const onlineDiff = (b && b.online ? 1 : 0) - (a && a.online ? 1 : 0);
          if (onlineDiff) return onlineDiff;
          return String(a && a.worker_id || "").localeCompare(String(b && b.worker_id || ""));
        })
        .forEach(worker => {
          const workerId = String(worker && worker.worker_id || "").trim();
          if (!workerId) return;
          const status = worker && worker.online ? "online" : "offline";
          const busy = worker && worker.current_job_id ? " - ocupado" : "";
          options.push(`<option value="${escapeHtml(workerId)}">${escapeHtml(promaxWorkerDisplayName(worker))} (${status}${busy})</option>`);
        });
      select.innerHTML = options.join("");
      if (Array.from(select.options).some(option => option.value === current)) {
        select.value = current;
      }
    }

    function renderPromax() {
      renderPromaxRunCatalog({
        categoryIds: state.promax.runSelectedCategories,
        routines: state.promax.runSelectedRoutines
      });
      renderPromaxRunResellers(state.promax.runSelectedUnits);
      renderPromaxScheduleCatalog({
        categoryIds: state.promax.scheduleSelectedCategories,
        routines: state.promax.scheduleSelectedRoutines
      });
      renderPromaxScheduleResellers(state.promax.scheduleSelectedUnits);
      renderPromaxScheduleTriggerOptions();

      const workerPayload = state.promax.worker || {};
      const queue = workerPayload.queue || {};
      const workers = promaxWorkersFromPayload(workerPayload);
      const jobs = Array.isArray(state.promax.jobs) ? state.promax.jobs : [];
      renderArmazemQueueSummary([...(Array.isArray(jobs) ? jobs : []), ...(Array.isArray(state.promax.grade020304AuditJobs) ? state.promax.grade020304AuditJobs : [])]);
      const pendingJobs = jobs.filter(job => String(job && job.status || "") === "pending").length;
      const activeJobs = jobs.filter(job => ["running", "cancel_requested"].includes(String(job && job.status || ""))).length;
      const onlineWorkers = workers.filter(worker => worker && worker.online);
      if (E.promaxWorkerState) {
        E.promaxWorkerState.textContent = onlineWorkers.length
          ? `${onlineWorkers.length}/${workers.length} robô(s) ligado(s)`
          : "Robôs desligados";
        E.promaxWorkerState.className = `pill ${onlineWorkers.length ? "ok" : "warn"}`;
      }
      renderPromaxWorkers(workers);
      renderPromaxWorkerAssignments(workers);
      renderPromaxTargetWorkerSelect(E.promaxRunTargetWorker, workers);
      renderPromaxTargetWorkerSelect(E.promaxGradeTargetWorker, workers);
      renderPromaxTargetWorkerSelect(E.promaxGrade020304Worker, workers);
      renderPromaxGradeResellerSelect(E.promaxGradeUnit);
      renderPromaxGradeResellerSelect(E.promaxGrade020304Unit);
      renderPromaxTargetWorkerSelect(E.promaxScheduleTargetWorker, workers);
      renderPromaxCredentials(workers);
      renderFinanceiroFechamentoWorker(workerPayload);
      if (E.promaxQueueState) {
        const queueLabel = queue.paused ? "Fila pausada" : "Fila liberada";
        E.promaxQueueState.textContent = `${queueLabel}: ${activeJobs} executando, ${pendingJobs} aguardando`;
        E.promaxQueueState.className = `pill ${queue.paused ? "warn" : "ok"}`;
      }
      if (E.promaxPauseBtn) E.promaxPauseBtn.disabled = Boolean(queue.paused);
      if (E.promaxResumeBtn) E.promaxResumeBtn.disabled = !queue.paused;
      if (E.promaxReprocessPublicationsBtn) {
        E.promaxReprocessPublicationsBtn.disabled = !onlineWorkers.length || Boolean(queue.paused);
      }
      renderPromaxImpact(jobs);
      renderArmazemGradeAudit();
      setArmazemRoutine(state.promax.armazemRoutine);

      if (E.promaxJobsBody) {
        E.promaxJobsBody.innerHTML = jobs.length ? jobs.map(job => {
          const payload = job && job.payload && typeof job.payload === "object" ? job.payload : {};
          const result = job && job.result && typeof job.result === "object" ? job.result : {};
          const isPublicationRetry = String(job.job_type || "") === "reprocess_publication";
          const routines = isPublicationRetry
            ? "Reprocessar publicacoes"
            : (Array.isArray(payload.routines) ? payload.routines.join(", ") : "-");
          const unitSummary = isPublicationRetry ? "Manutenção" : promaxJobUnitSummary(job);
          const periodStart = isPublicationRetry ? "Manutenção" : (payload.start_date || "-");
          const periodEnd = isPublicationRetry ? "Pendências salvas" : (payload.end_date || "-");
          const resultMessage = String(result.message || job.error || job.failure_reason || "").trim();
          const visibleResult = resultMessage.length > 180
            ? `${resultMessage.slice(0, 177)}...`
            : resultMessage;
          const status = String(job.status || "");
          const action = status === "pending"
            ? `<button class="btn btn-outline-danger btn-sm" onclick="promaxCancelJob('${escapeHtml(job.id)}', false)"><i class="bi bi-x-circle me-1"></i>Cancelar</button>`
            : (status === "running" || status === "cancel_requested")
              ? `<button class="btn btn-outline-danger btn-sm" onclick="promaxCancelJob('${escapeHtml(job.id)}', true)"><i class="bi bi-stop-circle me-1"></i>Parar</button>`
              : "";
          const failedUnitsCount = promaxJobUnitRows(job).filter(row => row.tone === "err").length;
          const retryButtonText = status === "partial_success" && failedUnitsCount
            ? "Retry pendentes"
            : "Retry completo";
          const retryAction = ["failed", "partial_success", "cancelled"].includes(status) && !isPublicationRetry
            ? `<button class="btn btn-outline-warning btn-sm" title="Reenfileirar ${escapeHtml(failedUnitsCount ? "somente as unidades com falha" : "a execução completa")}" onclick="promaxRetryJob('${escapeHtml(job.id)}')"><i class="bi bi-arrow-clockwise me-1"></i>${escapeHtml(retryButtonText)}</button>`
            : "";
          const unitAction = isPublicationRetry
            ? `<span class="small text-secondary">-</span>`
            : `<button class="btn btn-outline-primary btn-sm promax-unit-summary" onclick="promaxOpenUnitsModal('${escapeHtml(job.id)}')"><i class="bi bi-list-check"></i>${escapeHtml(unitSummary)}</button>`;
          return `<tr>
            <td class="ps-3"><span class="small">${escapeHtml(formatDateTime(job.created_at))}</span><div class="mono small text-secondary">${escapeHtml(String(job.id || "").slice(0, 8))}</div></td>
            <td>${escapeHtml(periodStart)}<br><span class="text-secondary">${escapeHtml(periodEnd)}</span></td>
            <td class="mono">${escapeHtml(routines)}</td>
            <td>${unitAction}</td>
            <td><span class="promax-status ${promaxStatusClass(status)}">${escapeHtml(promaxStatusLabel(status))}</span>${visibleResult ? `<div class="small text-secondary mt-1 text-wrap" title="${escapeHtml(resultMessage)}">${escapeHtml(visibleResult)}</div>` : ""}</td>
            <td>${escapeHtml(job.leased_by || "-")}</td>
            <td class="text-end pe-3"><div class="d-flex gap-1 justify-content-end">${action}${retryAction}<button class="btn btn-outline-primary btn-sm" onclick="promaxLoadLogs('${escapeHtml(job.id)}')"><i class="bi bi-terminal me-1"></i>Logs</button></div></td>
          </tr>`;
        }).join("") : '<tr><td colspan="7" class="text-center py-4 text-secondary">Nenhuma execução encontrada.</td></tr>';
      }

      const schedules = Array.isArray(state.promax.schedules) ? state.promax.schedules : [];
      if (E.promaxSchedulesBody) {
        state.promax.scheduleGroups = promaxBuildScheduleGroups(schedules);
        const scheduleGroups = state.promax.scheduleGroups;
        E.promaxSchedulesBody.innerHTML = scheduleGroups.length ? scheduleGroups.map(scheduleGroup => {
          const schedulePayload = scheduleGroup.payload || {};
          const groupId = String(scheduleGroup.jobType || schedulePayload.category || "-");
          const catalogGroup = promaxCatalogCategory(groupId);
          const units = Array.isArray(schedulePayload.units) ? schedulePayload.units : [];
          const unitNames = units.map(unitId => {
            const reseller = PROMAX_RESELLERS.find(item => item.id === String(unitId));
            return reseller ? reseller.name : String(unitId);
          });
          const status = promaxScheduleGroupStatus(scheduleGroup);
          const allEnabled = Number(scheduleGroup.enabledCount || 0) === scheduleGroup.schedules.length;
          return `<tr>
            <td><strong>${escapeHtml(scheduleGroup.baseName || "-")}</strong><div class="small text-secondary">${escapeHtml(promaxScheduleGroupSubtitle(scheduleGroup))}</div></td>
            <td><span class="mono">${escapeHtml(catalogGroup ? catalogGroup.name : groupId)}</span></td>
            <td>${escapeHtml(unitNames.length ? unitNames.join(", ") : "Todas")}</td>
            <td><button class="btn btn-outline-primary btn-sm promax-schedule-repeat" onclick="promaxOpenScheduleGroupModal('${escapeHtml(scheduleGroup.key)}')" title="Ver repeticoes da agenda"><i class="bi bi-calendar-week"></i><span class="promax-schedule-repeat-label">${escapeHtml(promaxScheduleGroupRepetitionLabel(scheduleGroup))}</span></button></td>
            <td>${scheduleGroup.triggerScheduleId ? '<span class="text-secondary">Aguardando conclusão</span>' : escapeHtml(formatDateTime(scheduleGroup.nextRunAt))}</td>
            <td><span class="badge ${status.badge}">${escapeHtml(status.label)}</span></td>
            <td class="text-end"><div class="d-flex gap-1 justify-content-end"><button class="btn btn-outline-success btn-sm" title="Executar agora" onclick="promaxRunScheduleGroup('${escapeHtml(scheduleGroup.key)}')"><i class="bi bi-play-fill"></i></button><button class="btn btn-outline-primary btn-sm" title="Editar agenda" onclick="promaxEditScheduleGroup('${escapeHtml(scheduleGroup.key)}')"><i class="bi bi-pencil-square"></i></button><button class="btn btn-outline-primary btn-sm" title="${allEnabled ? "Pausar repeticoes" : "Ativar repeticoes"}" onclick="promaxToggleScheduleGroup('${escapeHtml(scheduleGroup.key)}', ${allEnabled ? "false" : "true"})"><i class="bi ${allEnabled ? "bi-pause-circle" : "bi-play-circle"}"></i></button><button class="btn btn-outline-danger btn-sm" title="Excluir repeticoes" onclick="promaxDeleteScheduleGroup('${escapeHtml(scheduleGroup.key)}')"><i class="bi bi-trash3"></i></button></div></td>
          </tr>`;
        }).join("") : '<tr><td colspan="7" class="text-center py-3 text-secondary">Nenhuma agenda cadastrada.</td></tr>';
      }
    }

    async function syncPromax({ silent = true } = {}) {
      if (!state.panel || !state.panel.canManagePromax) return false;
      const params = new URLSearchParams({ limit: "100" });
      const status = String(E.promaxJobStatusFilter && E.promaxJobStatusFilter.value || "");
      const createdFrom = String(E.promaxJobFromDate && E.promaxJobFromDate.value || "");
      const createdTo = String(E.promaxJobToDate && E.promaxJobToDate.value || "");
      if (createdFrom && createdTo && createdTo < createdFrom) {
        if (!silent) addLog("A data final do filtro não pode ser anterior a inicial.", "warn");
        return false;
      }
      if (status) params.set("status", status);
      if (createdFrom) params.set("created_from", createdFrom);
      if (createdTo) params.set("created_to", createdTo);
      const requests = [
        req(CONFIG.endpoints.promax.catalog, { timeoutMs: 20000 }),
        req(`${CONFIG.endpoints.promax.jobs}?${params.toString()}`, { timeoutMs: 30000 }),
        req(CONFIG.endpoints.promax.worker, { timeoutMs: 20000 }),
        req(`${CONFIG.endpoints.promax.schedules}?limit=1000`, { timeoutMs: 20000 }),
        req(CONFIG.endpoints.promax.workerAssignments, { timeoutMs: 20000 }),
        req(CONFIG.endpoints.promax.workerCredentials, { timeoutMs: 20000 })
      ];
      const results = await Promise.allSettled(requests);
      state.promax.catalog = results[0].status === "fulfilled"
        ? (results[0].value.catalog || null)
        : null;
      if (results[1].status === "fulfilled") state.promax.jobs = Array.isArray(results[1].value.jobs) ? results[1].value.jobs : [];
      if (results[2].status === "fulfilled") state.promax.worker = results[2].value || null;
      if (results[3].status === "fulfilled") state.promax.schedules = Array.isArray(results[3].value.schedules) ? results[3].value.schedules : [];
      if (results[4].status === "fulfilled") state.promax.workerAssignments = Array.isArray(results[4].value.assignments) ? results[4].value.assignments : [];
      if (results[5].status === "fulfilled") mergePromaxWorkerCredentials(results[5].value.credentials);
      renderPromax();
      const failed = results.filter(result => result.status === "rejected");
      if (failed.length && !silent) addLog(`Promax: ${failed.length} consulta(s) falharam.`, "err");
      const auditLoaded = await syncArmazemGradeAudit({ silent });
      if (!failed.length && auditLoaded && !silent) addLog("Promax Admin atualizado.", "ok");
      return failed.length === 0 && auditLoaded;
    }

    function addPromaxGrade020304ManualRow(values = {}) {
      if (!E.promaxGrade020304ManualRows) return;
      E.promaxGrade020304ManualRows.insertAdjacentHTML("beforeend", `<tr data-grade-020304-manual-row><td><input class="form-control form-control-sm mono" data-field="produto" inputmode="numeric" value="${escapeHtml(values.produto || "")}" placeholder="Código"></td><td><input class="form-control form-control-sm" data-field="quantidade" inputmode="numeric" value="${escapeHtml(values.quantidade ?? "")}" placeholder="0"></td><td class="text-end"><button class="btn btn-outline-danger btn-sm" type="button" data-remove-grade-020304-row aria-label="Remover item"><i class="bi bi-trash3"></i></button></td></tr>`);
    }

    function addPromaxGradeManualRow(values = {}) {
      if (!E.promaxGradeManualRows) return;
      E.promaxGradeManualRows.insertAdjacentHTML("beforeend", `<tr data-grade-manual-row><td><input class="form-control form-control-sm mono" data-field="item" inputmode="numeric" value="${escapeHtml(values.item || "")}" placeholder="Código"></td><td><input class="form-control form-control-sm" data-field="pallet" inputmode="numeric" value="${escapeHtml(values.pallet ?? "0")}"></td><td><input class="form-control form-control-sm" data-field="lastro" inputmode="numeric" value="${escapeHtml(values.lastro ?? "0")}"></td><td><input class="form-control form-control-sm" data-field="sku" inputmode="numeric" value="${escapeHtml(values.sku ?? "0")}"></td><td><input class="form-control form-control-sm" data-field="unidade" inputmode="numeric" value="${escapeHtml(values.unidade ?? "0")}"></td><td><input class="form-control form-control-sm" data-field="garrafa" inputmode="numeric" value="${escapeHtml(values.garrafa || "")}"></td><td class="text-end"><button class="btn btn-outline-danger btn-sm" type="button" data-remove-grade-row aria-label="Remover item"><i class="bi bi-trash3"></i></button></td></tr>`);
    }

    async function queuePromaxGrade020304Manual() {
      const grade = String(E.promaxGrade020304ManualGrade && E.promaxGrade020304ManualGrade.value || "").trim();
      const unidade = String(E.promaxGrade020304Unit && E.promaxGrade020304Unit.value || "").trim();
      const rows = [...(E.promaxGrade020304ManualRows ? E.promaxGrade020304ManualRows.querySelectorAll("[data-grade-020304-manual-row]") : [])];
      if (!grade || !/^\d+$/.test(grade)) { E.promaxGrade020304ManualStatus.textContent = "Informe uma grade numérica."; return; }
      if (!unidade) { E.promaxGrade020304ManualStatus.textContent = "Selecione a revenda que executará o lançamento."; return; }
      const items = rows.map((row, index) => ({ produto: manualGradeField(row, "produto"), quantidade: manualGradeField(row, "quantidade"), line: index + 1 })).filter(item => item.produto || item.quantidade);
      if (!items.length) { E.promaxGrade020304ManualStatus.textContent = "Informe ao menos um produto."; return; }
      const invalid = items.find(item => !/^\d+$/.test(item.produto) || !/^\d+$/.test(item.quantidade));
      if (invalid) { E.promaxGrade020304ManualStatus.textContent = `Linha ${invalid.line}: produto e quantidade devem ser números inteiros não negativos.`; return; }
      const csv = ["grade;produto;quantidade", ...items.map(item => [grade, item.produto, item.quantidade].map(gradeCsvCell).join(";"))].join("\n");
      E.promaxGrade020304ManualQueueBtn.disabled = true;
      E.promaxGrade020304ManualStatus.textContent = "Validando e adicionando o lançamento manual à fila...";
      try {
        const response = await req(CONFIG.endpoints.promax.grade020304Jobs, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ filename: "lancamento_manual_020304.csv", file_base64: gradeCsvBase64(csv), unidade, target_worker_id: String(E.promaxGrade020304Worker.value || "").trim() || null }) });
        E.promaxGrade020304ManualStatus.textContent = `${response.items || 0} item(ns) manual(is) em ${response.launches || 0} grade(s) adicionados à fila.`;
        E.promaxGrade020304ManualRows.innerHTML = "";
        addPromaxGrade020304ManualRow();
        syncArmazemGrade({ silent: true });
      } catch (error) { E.promaxGrade020304ManualStatus.textContent = error && error.message ? error.message : "Falha ao lançar os itens manualmente."; }
      finally { E.promaxGrade020304ManualQueueBtn.disabled = false; }
    }

    async function queuePromaxGradeManual() {
      const armazem = String(E.promaxGradeManualArmazem && E.promaxGradeManualArmazem.value || "").trim();
      const deposito = String(E.promaxGradeManualDeposito && E.promaxGradeManualDeposito.value || "").trim();
      const dateValue = String(E.promaxGradeManualDate && E.promaxGradeManualDate.value || "").trim();
      const unidade = String(E.promaxGradeUnit && E.promaxGradeUnit.value || "").trim();
      const rows = [...(E.promaxGradeManualRows ? E.promaxGradeManualRows.querySelectorAll("[data-grade-manual-row]") : [])];
      if (!/^\d+$/.test(armazem) || !/^\d+$/.test(deposito) || !dateValue) { E.promaxGradeManualStatus.textContent = "Informe armazém, depósito e data do movimento."; return; }
      if (!unidade) { E.promaxGradeManualStatus.textContent = "Selecione a revenda que executará o lançamento."; return; }
      const items = rows.map((row, index) => ({ item: manualGradeField(row, "item"), pallet: manualGradeField(row, "pallet") || "0", lastro: manualGradeField(row, "lastro") || "0", sku: manualGradeField(row, "sku") || "0", unidade: manualGradeField(row, "unidade") || "0", garrafa: manualGradeField(row, "garrafa"), line: index + 1 })).filter(item => item.item || Number(item.pallet) || Number(item.lastro) || Number(item.sku) || Number(item.unidade) || item.garrafa);
      if (!items.length) { E.promaxGradeManualStatus.textContent = "Informe ao menos um item."; return; }
      const invalid = items.find(item => !/^\d+$/.test(item.item) || ![item.pallet, item.lastro, item.sku, item.unidade].every(value => /^\d+$/.test(value)) || (item.garrafa && !/^\d+$/.test(item.garrafa)) || ![item.pallet, item.lastro, item.sku, item.unidade].some(value => Number(value) > 0));
      if (invalid) { E.promaxGradeManualStatus.textContent = `Linha ${invalid.line}: informe código numérico e ao menos uma quantidade maior que zero.`; return; }
      const movementDate = dateValue.split("-").reverse().join("/");
      const csv = ["armazem;deposito;data_movimento;item;pallet;lastro;sku;unidade;garrafa", ...items.map(item => [armazem, deposito, movementDate, item.item, item.pallet, item.lastro, item.sku, item.unidade, item.garrafa].map(gradeCsvCell).join(";"))].join("\n");
      E.promaxGradeManualQueueBtn.disabled = true;
      E.promaxGradeManualStatus.textContent = "Validando e adicionando o lançamento manual à fila...";
      try {
        const response = await req(CONFIG.endpoints.promax.gradeJobs, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ filename: "lancamento_manual_020105.csv", file_base64: gradeCsvBase64(csv), unidade, target_worker_id: String(E.promaxGradeTargetWorker.value || "").trim() || null }) });
        E.promaxGradeManualStatus.textContent = `${response.items || 0} item(ns) manual(is) em ${response.launches || 0} lançamento(s) adicionados à fila.`;
        E.promaxGradeManualRows.innerHTML = "";
        addPromaxGradeManualRow();
        syncArmazemGrade({ silent: true });
      } catch (error) { E.promaxGradeManualStatus.textContent = error && error.message ? error.message : "Falha ao lançar os itens manualmente."; }
      finally { E.promaxGradeManualQueueBtn.disabled = false; }
    }

    async function promaxQueueGradeCsv() {
      const file = E.promaxGradeFile && E.promaxGradeFile.files && E.promaxGradeFile.files[0];
      if (!file) {
        E.promaxGradeStatus.textContent = "Selecione o CSV da grade.";
        return;
      }
      if (!String(E.promaxGradeUnit.value || "").trim()) {
        E.promaxGradeStatus.textContent = "Selecione a revenda que executará o lançamento.";
        return;
      }
      if (file.size > 2 * 1024 * 1024) {
        E.promaxGradeStatus.textContent = "O CSV da grade não pode passar de 2 MB.";
        return;
      }
      E.promaxGradeQueueBtn.disabled = true;
      E.promaxGradeStatus.textContent = "Validando o CSV e criando os lançamentos...";
      try {
        const encoded = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result || "").split(",", 2)[1] || "");
          reader.onerror = () => reject(new Error("Não foi possível ler o arquivo."));
          reader.readAsDataURL(file);
        });
        const response = await req(CONFIG.endpoints.promax.gradeJobs, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            filename: file.name,
            file_base64: encoded,
            unidade: String(E.promaxGradeUnit.value || "").trim() || null,
            target_worker_id: String(E.promaxGradeTargetWorker.value || "").trim() || null
          })
        });
        E.promaxGradeStatus.textContent = `${response.items || 0} item(ns) em ${response.launches || 0} lançamento(s) adicionados à fila.`;
        syncArmazemGrade({ silent: true });
      } catch (error) {
        E.promaxGradeStatus.textContent = error && error.message ? error.message : "Falha ao validar o CSV.";
      } finally {
        E.promaxGradeQueueBtn.disabled = false;
      }
    }

    async function promaxQueueGrade020304Csv() {
      const file = E.promaxGrade020304File && E.promaxGrade020304File.files[0];
      if (!file) { E.promaxGrade020304Status.textContent = "Selecione o CSV da entrada para 02.03.04."; return; }
      if (!String(E.promaxGrade020304Unit.value || "").trim()) { E.promaxGrade020304Status.textContent = "Selecione a revenda que executará o lançamento."; return; }
      E.promaxGrade020304QueueBtn.disabled = true;
      try {
        const encoded = await new Promise((resolve, reject) => { const r = new FileReader(); r.onload = () => resolve(String(r.result || "").split(",", 2)[1] || ""); r.onerror = () => reject(new Error("Não foi possível ler o arquivo.")); r.readAsDataURL(file); });
        const response = await req(CONFIG.endpoints.promax.grade020304Jobs, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ filename: file.name, file_base64: encoded, unidade: String(E.promaxGrade020304Unit.value || "").trim() || null, target_worker_id: String(E.promaxGrade020304Worker.value || "").trim() || null }) });
        E.promaxGrade020304Status.textContent = `${response.items || 0} item(ns) em ${response.launches || 0} grade(s) adicionados à fila.`;
        syncArmazemGrade({ silent: true });
      } catch (error) { E.promaxGrade020304Status.textContent = error && error.message ? error.message : "Falha ao validar o CSV."; }
      finally { E.promaxGrade020304QueueBtn.disabled = false; }
    }

    async function promaxRunNow() {
      let payload;
      try {
        payload = promaxRunBatchPayload();
      } catch (err) {
        addLog(err.message, "warn");
        return;
      }
      if (payload.cora_critica) {
        const confirmedCora = await askConfirmation("Adicionar a Crítica Cora à fila para baixar e importar automaticamente?");
        if (!confirmedCora) return;
        E.promaxRunBtn.disabled = true;
        try {
          const response = await req(CONFIG.endpoints.promax.coraCriticaJobs, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ target_worker_id: payload.target_worker_id }),
            timeoutMs: 30000
          });
          const job = response && response.job ? response.job : {};
          addLog(`Crítica Cora adicionada à fila: ${String(job.id || "").slice(0, 8) || "ok"}.`, "ok");
          await syncPromax({ silent: true });
        } catch (err) {
          addLog(`Falha ao adicionar Crítica Cora: ${err.message}`, "err");
        } finally {
          updatePromaxActionState();
        }
        return;
      }
      const groupNames = payload.groups.map(item => {
        const category = promaxCatalogCategory(item.category);
        return category ? category.name : item.category;
      });
      const confirmed = await askConfirmation(
        `Adicionar ${payload.groups.length} grupo(s) a fila Promax: ${groupNames.join(", ")}?`
      );
      if (!confirmed) return;
      E.promaxRunBtn.disabled = true;
      try {
        const response = await req(CONFIG.endpoints.promax.jobsBatch, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          timeoutMs: 30000
        });
        const jobs = response && Array.isArray(response.jobs) ? response.jobs : [];
        addLog(
          `${jobs.length || payload.groups.length} execução(ões) Promax adicionada(s) a fila.`,
          "ok"
        );
        await syncPromax({ silent: true });
      } catch (err) {
        addLog(`Falha ao adicionar execução Promax: ${err.message}`, "err");
      } finally {
        updatePromaxActionState();
      }
    }

    async function promaxReprocessPublications() {
      if (!await askConfirmation("Tentar novamente a transferencia de todas as publicacoes pendentes no worker Promax?")) return;
      E.promaxReprocessPublicationsBtn.disabled = true;
      try {
        const response = await req(CONFIG.endpoints.promax.reprocessPublications, {
          method: "POST",
          timeoutMs: 30000
        });
        const job = response && response.job ? response.job : {};
        addLog(`Reprocessamento de publicacoes adicionado a fila: ${String(job.id || "").slice(0, 8) || "job existente"}.`, "ok");
        await syncPromax({ silent: true });
      } catch (err) {
        addLog(`Falha ao solicitar reprocessamento das publicacoes: ${err.message}`, "err");
      } finally {
        const workerPayload = state.promax.worker || {};
        const queue = workerPayload.queue || {};
        const workers = Array.isArray(workerPayload.workers) ? workerPayload.workers : [];
        E.promaxReprocessPublicationsBtn.disabled = !workers.some(worker => worker && worker.online) || Boolean(queue.paused);
      }
    }

    async function promaxRetryJob(jobId) {
      const job = (Array.isArray(state.promax.jobs) ? state.promax.jobs : []).find(item => String(item && item.id || "") === String(jobId));
      const shortId = String(jobId || "").slice(0, 8);
      const label = job ? `${promaxStatusLabel(job.status)} ${shortId}` : shortId;
      if (!await askConfirmation(`Adicionar retry desta execução Promax (${label}) a fila?`)) return;
      try {
        const response = await req(`${CONFIG.endpoints.promax.jobs}/${encodeURIComponent(jobId)}/retry`, {
          method: "POST",
          timeoutMs: 30000
        });
        const newJob = response && response.job ? response.job : {};
        const retryUnits = response && Array.isArray(response.retry_units) ? response.retry_units : [];
        const retryLabel = retryUnits.length ? `somente ${retryUnits.join(", ")}` : "job completo";
        addLog(`Retry Promax adicionado a fila (${retryLabel}): ${String(newJob.id || "").slice(0, 8) || "novo job"}.`, "ok");
        await syncPromax({ silent: true });
      } catch (err) {
        addLog(`Falha ao adicionar retry Promax: ${err.message}`, "err");
      }
    }

    async function promaxQueueAction(action) {
      const messages = {
        pause: "Pausar novas execuções da fila Promax?",
        resume: "Retomar a fila Promax?",
        pending: "Cancelar todos os jobs pendentes da fila Promax?"
      };
      if (!await askConfirmation(messages[action] || "Confirmar ação?")) return;
      const endpoint = CONFIG.endpoints.promax[action];
      const method = action === "pending" ? "DELETE" : "POST";
      try {
        await req(endpoint, { method, timeoutMs: 20000 });
        addLog(`Fila Promax atualizada: ${action}.`, "ok");
        await syncPromax({ silent: true });
      } catch (err) {
        addLog(`Falha no controle da fila Promax: ${err.message}`, "err");
      }
    }

    async function promaxCancelJob(jobId, running) {
      if (!await askConfirmation(running ? "Parar esta execução Promax?" : "Cancelar este job pendente?")) return;
      try {
        await req(`${CONFIG.endpoints.promax.jobs}/${encodeURIComponent(jobId)}/${running ? "stop" : "cancel"}`, {
          method: "POST",
          timeoutMs: 20000
        });
        addLog(running ? "Parada solicitada ao worker." : "Job pendente cancelado.", "ok");
        await syncPromax({ silent: true });
      } catch (err) {
        addLog(`Falha ao cancelar job Promax: ${err.message}`, "err");
      }
    }

    async function promaxLoadLogs(jobId) {
      state.promax.selectedJobId = jobId;
      if (E.promaxLogJob) E.promaxLogJob.textContent = `Job ${String(jobId).slice(0, 8)}`;
      if (E.promaxLogOutput) E.promaxLogOutput.textContent = "Carregando logs...";
      try {
        const payload = await req(`${CONFIG.endpoints.promax.jobs}/${encodeURIComponent(jobId)}/logs?limit=1000`, { timeoutMs: 30000 });
        const logs = Array.isArray(payload.logs) ? payload.logs : [];
        E.promaxLogOutput.textContent = logs.length
          ? logs.map(item => `[${formatDateTime(item.created_at)}] ${String(item.level || "info").toUpperCase()} ${item.message || ""}`).join("\n")
          : "Este job ainda não possui logs.";
        E.promaxLogOutput.scrollTop = E.promaxLogOutput.scrollHeight;
      } catch (err) {
        E.promaxLogOutput.textContent = `Falha ao carregar logs: ${err.message}`;
      }
    }

    function syncPromaxJobDateBounds() {
      const createdFrom = String(E.promaxJobFromDate && E.promaxJobFromDate.value || "");
      const createdTo = String(E.promaxJobToDate && E.promaxJobToDate.value || "");
      if (E.promaxJobFromDate) {
        if (createdTo) E.promaxJobFromDate.max = createdTo;
        else E.promaxJobFromDate.removeAttribute("max");
      }
      if (E.promaxJobToDate) {
        if (createdFrom) E.promaxJobToDate.min = createdFrom;
        else E.promaxJobToDate.removeAttribute("min");
      }
    }

    function applyPromaxJobFilters() {
      syncPromaxJobDateBounds();
      return syncPromax({ silent: false });
    }

    function clearPromaxJobFilters() {
      if (E.promaxJobStatusFilter) E.promaxJobStatusFilter.value = "";
      if (E.promaxJobFromDate) E.promaxJobFromDate.value = "";
      if (E.promaxJobToDate) E.promaxJobToDate.value = "";
      syncPromaxJobDateBounds();
      return syncPromax({ silent: true });
    }

    function syncPromaxDateFields() {
      const runEnabled = Boolean(E.promaxSendDates && E.promaxSendDates.checked);
      const scheduleEnabled = Boolean(
        E.promaxScheduleSendDates && E.promaxScheduleSendDates.checked
      );
      if (E.promaxStartDate) E.promaxStartDate.disabled = !runEnabled;
      if (E.promaxEndDate) E.promaxEndDate.disabled = !runEnabled;
      if (E.promaxScheduleStartDate) E.promaxScheduleStartDate.disabled = !scheduleEnabled;
      if (E.promaxScheduleEndDate) E.promaxScheduleEndDate.disabled = !scheduleEnabled;
    }

    function syncPromaxScheduleFields() {
      const triggerType = String(E.promaxScheduleTriggerType && E.promaxScheduleTriggerType.value || "time");
      const type = String(E.promaxScheduleType && E.promaxScheduleType.value || "daily");
      const triggered = triggerType === "after";
      if (E.promaxScheduleTypeWrap) E.promaxScheduleTypeWrap.classList.toggle("d-none", triggered);
      if (E.promaxScheduleTimeWrap) E.promaxScheduleTimeWrap.classList.toggle("d-none", triggered || ["daily_hourly", "daily_specific"].includes(type));
      if (E.promaxScheduleTriggerScheduleWrap) E.promaxScheduleTriggerScheduleWrap.classList.toggle("d-none", !triggered);
      if (E.promaxScheduleWeekdayWrap) {
        E.promaxScheduleWeekdayWrap.classList.toggle("d-none", triggered || type !== "weekly");
      }
      if (E.promaxScheduleMonthDayWrap) {
        E.promaxScheduleMonthDayWrap.classList.toggle("d-none", triggered || type !== "monthly");
      }
      if (E.promaxScheduleDailyDaysWrap) {
        E.promaxScheduleDailyDaysWrap.classList.toggle("d-none", triggered || !["daily", "daily_hourly", "daily_specific"].includes(type));
      }
      if (E.promaxScheduleSpecificWrap) {
        E.promaxScheduleSpecificWrap.classList.toggle("d-none", triggered || type !== "daily_specific");
      }
      if (E.promaxScheduleHourlyWrap) {
        E.promaxScheduleHourlyWrap.classList.toggle("d-none", triggered || type !== "daily_hourly");
      }
      updatePromaxSpecificSchedulePreview();
      updatePromaxHourlySchedulePreview();
    }

    function resetPromaxScheduleForm() {
      state.promax.editingScheduleId = "";
      state.promax.editingScheduleGroupKey = "";
      state.promax.scheduleSelectedCategories = null;
      state.promax.scheduleSelectedRoutines = {};
      state.promax.scheduleSelectedUnits = PROMAX_RESELLERS.map(reseller => reseller.id);
      if (E.promaxScheduleName) E.promaxScheduleName.value = "";
      if (E.promaxScheduleTriggerType) E.promaxScheduleTriggerType.value = "time";
      if (E.promaxScheduleType) E.promaxScheduleType.value = "daily";
      if (E.promaxScheduleTime) E.promaxScheduleTime.value = "06:00";
      if (E.promaxScheduleSpecificHours) E.promaxScheduleSpecificHours.value = "";
      if (E.promaxScheduleSpecificStart) E.promaxScheduleSpecificStart.value = "17:05";
      if (E.promaxScheduleSpecificEnd) E.promaxScheduleSpecificEnd.value = "18:00";
      if (E.promaxScheduleSpecificStep) E.promaxScheduleSpecificStep.value = "5";
      if (E.promaxScheduleHourlyStart) E.promaxScheduleHourlyStart.value = "06:00";
      if (E.promaxScheduleHourlyEnd) E.promaxScheduleHourlyEnd.value = "18:00";
      if (E.promaxScheduleHourlyStep) E.promaxScheduleHourlyStep.value = "60";
      setPromaxSelectedScheduleDays([0, 1, 2, 3, 4]);
      if (E.promaxScheduleSendDates) E.promaxScheduleSendDates.checked = false;
      if (E.promaxScheduleTargetWorker) E.promaxScheduleTargetWorker.value = "";
      renderPromaxScheduleCatalog();
      renderPromaxScheduleResellers(state.promax.scheduleSelectedUnits);
      renderPromaxScheduleTriggerOptions("");
      if (E.promaxScheduleCreateBtn) E.promaxScheduleCreateBtn.innerHTML = '<i class="bi bi-calendar-plus me-1"></i>Criar agenda';
      if (E.promaxScheduleCancelBtn) E.promaxScheduleCancelBtn.classList.add("d-none");
      syncPromaxDateFields();
      syncPromaxScheduleFields();
      updatePromaxActionState();
    }

    function promaxEditSchedule(scheduleId) {
      const schedule = (state.promax.schedules || []).find(item => String(item.id) === String(scheduleId));
      if (!schedule) {
        addLog("Agenda Promax não encontrada para edição.", "warn");
        return;
      }
      const payload = schedule.payload || {};
      state.promax.editingScheduleId = String(schedule.id);
      state.promax.editingScheduleGroupKey = "";
      E.promaxScheduleName.value = String(schedule.name || "");
      E.promaxScheduleType.value = String(schedule.schedule_type || "daily");
      E.promaxScheduleTime.value = String(schedule.time_of_day || "06:00").slice(0, 5);
      E.promaxScheduleWeekday.value = String(schedule.weekday == null ? 0 : schedule.weekday);
      setPromaxSelectedScheduleDays(schedule.weekday == null ? [0, 1, 2, 3, 4, 5, 6] : [Number(schedule.weekday)]);
      E.promaxScheduleMonthDay.value = String(schedule.day_of_month == null ? 1 : schedule.day_of_month);
      E.promaxScheduleStartDate.value = String(payload.start_date || "");
      E.promaxScheduleEndDate.value = String(payload.end_date || "");
      E.promaxScheduleSendDates.checked = Boolean(payload.send_dates);
      E.promaxSchedulePublish.checked = Boolean(payload.publish);
      renderPromaxTargetWorkerSelect(
        E.promaxScheduleTargetWorker,
        promaxWorkersFromPayload(state.promax.worker || {}),
        payload.target_worker_id
      );
      promaxApplyScheduleScopeForEdit(promaxScheduleScopeForEdit(schedule));
      const triggerScheduleId = String(schedule.trigger_after_schedule_id || "");
      E.promaxScheduleTriggerType.value = triggerScheduleId ? "after" : "time";
      renderPromaxScheduleTriggerOptions(triggerScheduleId);
      E.promaxScheduleCreateBtn.innerHTML = '<i class="bi bi-check2-circle me-1"></i>Salvar agenda';
      E.promaxScheduleCancelBtn.classList.remove("d-none");
      syncPromaxDateFields();
      syncPromaxScheduleFields();
      E.promaxScheduleName.focus();
    }

    function promaxEditScheduleGroup(groupKey) {
      const group = promaxFindScheduleGroup(groupKey);
      const schedules = Array.isArray(group && group.schedules) ? group.schedules : [];
      const primary = group && group.primary ? group.primary : schedules[0];
      if (!group || !primary) {
        addLog("Grupo de agenda Promax não encontrado para edição.", "warn");
        return;
      }
      const payload = primary.payload || {};
      const times = Array.isArray(group.times) ? group.times : [];
      const days = Array.isArray(group.days) && group.days.length
        ? group.days
        : (primary.weekday == null ? [0, 1, 2, 3, 4, 5, 6] : [Number(primary.weekday)]);
      state.promax.editingScheduleId = "";
      state.promax.editingScheduleGroupKey = String(group.key || "");
      E.promaxScheduleName.value = String(group.baseName || primary.name || "");
      E.promaxScheduleTime.value = String(times[0] || primary.time_of_day || "06:00").slice(0, 5);
      if (String(primary.schedule_type || "") === "monthly") {
        E.promaxScheduleType.value = "monthly";
      } else {
        promaxApplyScheduleGroupTimes(times);
      }
      E.promaxScheduleWeekday.value = String(days[0] == null ? 0 : days[0]);
      setPromaxSelectedScheduleDays(days);
      E.promaxScheduleMonthDay.value = String(primary.day_of_month == null ? 1 : primary.day_of_month);
      E.promaxScheduleStartDate.value = String(payload.start_date || "");
      E.promaxScheduleEndDate.value = String(payload.end_date || "");
      E.promaxScheduleSendDates.checked = Boolean(payload.send_dates);
      E.promaxSchedulePublish.checked = Boolean(payload.publish);
      renderPromaxTargetWorkerSelect(
        E.promaxScheduleTargetWorker,
        promaxWorkersFromPayload(state.promax.worker || {}),
        payload.target_worker_id
      );
      promaxApplyScheduleScopeForEdit(promaxScheduleScopeForEdit(group));
      const triggerScheduleId = String(group.triggerScheduleId || primary.trigger_after_schedule_id || "");
      E.promaxScheduleTriggerType.value = triggerScheduleId ? "after" : "time";
      renderPromaxScheduleTriggerOptions(triggerScheduleId);
      E.promaxScheduleCreateBtn.innerHTML = '<i class="bi bi-check2-circle me-1"></i>Salvar agenda';
      E.promaxScheduleCancelBtn.classList.remove("d-none");
      syncPromaxDateFields();
      syncPromaxScheduleFields();
      E.promaxScheduleName.focus();
    }

    async function promaxCreateSchedule() {
      const name = String(E.promaxScheduleName && E.promaxScheduleName.value || "").trim();
      if (!name) {
        addLog("Informe um nome para a agenda Promax.", "warn");
        return;
      }
      const editingScheduleId = String(state.promax.editingScheduleId || "");
      const editingScheduleGroupKey = String(state.promax.editingScheduleGroupKey || "");
      const editingSchedule = (state.promax.schedules || []).find(
        item => String(item.id) === editingScheduleId
      );
      const editingScheduleGroup = editingScheduleGroupKey ? promaxFindScheduleGroup(editingScheduleGroupKey) : null;
      let chainPayload;
      try {
        chainPayload = promaxScheduleChainPayload();
      } catch (err) {
        addLog(err.message, "warn");
        return;
      }
      if ((editingScheduleId || editingScheduleGroupKey) && chainPayload.groups.length !== 1) {
        addLog("Na edição, mantenha somente o grupo desta agenda. Para vários grupos, crie uma nova cadeia.", "warn");
        return;
      }
      if (editingScheduleGroupKey && (!editingScheduleGroup || !Array.isArray(editingScheduleGroup.schedules) || !editingScheduleGroup.schedules.length)) {
        addLog("Grupo de agenda Promax não encontrado para salvar.", "warn");
        return;
      }
      let timingPayloads;
      try {
        timingPayloads = promaxScheduleTimingPayloads(name);
      } catch (err) {
        addLog(err.message, "warn");
        return;
      }
      if (editingScheduleId && timingPayloads.length !== 1) {
        addLog("Na edição, mantenha somente um dia e um horário. Para vários horários, crie uma nova agenda.", "warn");
        return;
      }
      const payload = editingScheduleId
        ? {
          name: timingPayloads[0].name,
          category: chainPayload.groups[0].category,
          routines: chainPayload.groups[0].routines,
          units: chainPayload.units,
          start_date: chainPayload.start_date,
          end_date: chainPayload.end_date,
          send_dates: chainPayload.send_dates,
          publish: chainPayload.publish,
          target_worker_id: chainPayload.target_worker_id,
          trigger_after_schedule_id: chainPayload.trigger_after_schedule_id,
          ...timingPayloads[0],
          enabled: editingSchedule ? Boolean(editingSchedule.enabled) : true
        }
        : {
          ...chainPayload,
          name,
          ...timingPayloads[0],
          enabled: true
        };
      const totalCreations = editingScheduleId ? 1 : timingPayloads.length;
      const actionLabel = editingScheduleId || editingScheduleGroupKey ? "Salvar as alterações da agenda" : `Criar ${totalCreations} agenda(s)`;
      if (!await askConfirmation(`${actionLabel} "${name}"?`)) return;
      E.promaxScheduleCreateBtn.disabled = true;
      try {
        let createdSchedules = 0;
        if (editingScheduleId) {
          await req(`${CONFIG.endpoints.promax.schedules}/${encodeURIComponent(editingScheduleId)}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
            timeoutMs: 30000
          });
        } else if (editingScheduleGroupKey) {
          const oldSchedules = Array.isArray(editingScheduleGroup && editingScheduleGroup.schedules)
            ? [...editingScheduleGroup.schedules]
            : [];
          const sortedOldSchedules = oldSchedules.sort((left, right) => promaxScheduleSortValue(left).localeCompare(promaxScheduleSortValue(right)));
          if (sortedOldSchedules.length === timingPayloads.length) {
            for (let index = 0; index < sortedOldSchedules.length; index += 1) {
              const schedule = sortedOldSchedules[index];
              const timingPayload = timingPayloads[index];
              await req(`${CONFIG.endpoints.promax.schedules}/${encodeURIComponent(schedule.id)}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  name: timingPayload.name,
                  category: chainPayload.groups[0].category,
                  routines: chainPayload.groups[0].routines,
                  units: chainPayload.units,
                  start_date: chainPayload.start_date,
                  end_date: chainPayload.end_date,
                  send_dates: chainPayload.send_dates,
                  publish: chainPayload.publish,
                  target_worker_id: chainPayload.target_worker_id,
                  trigger_after_schedule_id: chainPayload.trigger_after_schedule_id,
                  ...timingPayload,
                  enabled: Boolean(schedule.enabled)
                }),
                timeoutMs: 30000
              });
              createdSchedules += 1;
            }
          } else {
            for (const schedule of sortedOldSchedules.reverse()) {
              await req(`${CONFIG.endpoints.promax.schedules}/${encodeURIComponent(schedule.id)}`, {
                method: "DELETE",
                timeoutMs: 20000
              });
            }
            for (const timingPayload of timingPayloads) {
              const response = await req(CONFIG.endpoints.promax.scheduleChains, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  ...chainPayload,
                  name: timingPayload.name,
                  ...timingPayload,
                  enabled: true
                }),
                timeoutMs: 30000
              });
              createdSchedules += Array.isArray(response && response.schedules)
                ? response.schedules.length
                : chainPayload.groups.length;
            }
          }
        } else {
          for (const timingPayload of timingPayloads) {
            const response = await req(CONFIG.endpoints.promax.scheduleChains, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                ...chainPayload,
                name: timingPayload.name,
                ...timingPayload,
                enabled: true
              }),
              timeoutMs: 30000
            });
            createdSchedules += Array.isArray(response && response.schedules)
              ? response.schedules.length
              : chainPayload.groups.length;
          }
        }
        addLog(
          editingScheduleId || editingScheduleGroupKey
            ? `Agenda Promax atualizada com ${createdSchedules || timingPayloads.length} repeticao(oes).`
            : `Agenda Promax criada com ${createdSchedules || (chainPayload.groups.length * totalCreations)} item(ns).`,
          "ok"
        );
        resetPromaxScheduleForm();
        await syncPromax({ silent: true });
      } catch (err) {
        addLog(`Falha ao salvar agenda Promax: ${err.message}`, "err");
      } finally {
        updatePromaxActionState();
      }
    }

    function promaxOpenScheduleGroupModal(groupKey) {
      const group = promaxFindScheduleGroup(groupKey);
      if (!group) {
        addLog("Grupo de agenda Promax não encontrado.", "warn");
        return;
      }
      state.promax.activeScheduleGroupKey = String(group.key || "");
      const schedulePayload = group.payload || {};
      const catalogGroup = promaxCatalogCategory(group.jobType || schedulePayload.category || "");
      const groupName = catalogGroup ? catalogGroup.name : String(group.jobType || "-");
      if (E.promaxScheduleGroupModalTitle) E.promaxScheduleGroupModalTitle.textContent = group.baseName || "Repeticoes da agenda";
      if (E.promaxScheduleGroupModalSubtitle) {
        E.promaxScheduleGroupModalSubtitle.textContent = `${groupName} | ${promaxScheduleGroupSubtitle(group)}`;
      }
      if (E.promaxScheduleGroupModalDays) {
        const dayPills = group.triggerScheduleId
          ? [`<span class="promax-schedule-day-pill">${escapeHtml(promaxScheduleGroupRepetitionLabel(group))}</span>`]
          : [
            ...((group.days || []).map(day => `<span class="promax-schedule-day-pill">${escapeHtml(promaxFormatWeekday(day))}</span>`)),
            ...((group.monthDays || []).map(day => `<span class="promax-schedule-day-pill">Dia ${escapeHtml(day)}</span>`)),
            ...((group.times || []).map(timeValue => `<span class="promax-schedule-day-pill">${escapeHtml(timeValue)}</span>`))
          ];
        E.promaxScheduleGroupModalDays.innerHTML = dayPills.length
          ? dayPills.join("")
          : '<span class="text-secondary small">Sem repeticoes detalhadas.</span>';
      }
      if (E.promaxScheduleGroupModalBody) {
        E.promaxScheduleGroupModalBody.innerHTML = group.schedules.length ? group.schedules.map(schedule => {
          const enabled = Boolean(schedule.enabled);
          const scheduleId = String(schedule.id || "");
          const nextRun = schedule.trigger_after_schedule_id
            ? '<span class="text-secondary">Aguardando conclusão</span>'
            : escapeHtml(formatDateTime(schedule.next_run_at));
          return `<tr>
            <td><strong>${escapeHtml(promaxScheduleTimingLabel(schedule))}</strong><div class="small text-secondary">${escapeHtml(schedule.name || "-")}</div></td>
            <td>${nextRun}</td>
            <td><span class="badge ${enabled ? "text-bg-success" : "text-bg-secondary"}">${enabled ? "Ativa" : "Pausada"}</span></td>
            <td class="text-end"><div class="d-flex gap-1 justify-content-end"><button class="btn btn-outline-success btn-sm" title="Executar esta repeticao agora" onclick="promaxRunScheduleNow('${escapeHtml(scheduleId)}')"><i class="bi bi-play-fill"></i></button><button class="btn btn-outline-primary btn-sm" title="Editar repeticao" onclick="promaxEditSchedule('${escapeHtml(scheduleId)}')"><i class="bi bi-pencil-square"></i></button><button class="btn btn-outline-primary btn-sm" title="${enabled ? "Pausar repeticao" : "Ativar repeticao"}" onclick="promaxToggleSchedule('${escapeHtml(scheduleId)}', ${enabled ? "false" : "true"})"><i class="bi ${enabled ? "bi-pause-circle" : "bi-play-circle"}"></i></button><button class="btn btn-outline-danger btn-sm" title="Excluir repeticao" onclick="promaxDeleteSchedule('${escapeHtml(scheduleId)}')"><i class="bi bi-trash3"></i></button></div></td>
          </tr>`;
        }).join("") : '<tr><td colspan="4" class="text-center py-3 text-secondary">Nenhuma repeticao cadastrada.</td></tr>';
      }
      if (promaxScheduleGroupModalInstance) promaxScheduleGroupModalInstance.show();
    }

    async function promaxRunScheduleNow(scheduleId) {
      const schedule = (state.promax.schedules || []).find(item => String(item.id || "") === String(scheduleId));
      const label = schedule ? String(schedule.name || "agenda") : String(scheduleId || "").slice(0, 8);
      if (!await askConfirmation(`Executar agora a agenda Promax "${label}"?`)) return;
      try {
        const response = await req(`${CONFIG.endpoints.promax.schedules}/${encodeURIComponent(scheduleId)}/run-now`, {
          method: "POST",
          timeoutMs: 30000
        });
        const job = response && response.job ? response.job : {};
        addLog(`Agenda Promax enviada para fila: ${String(job.id || "").slice(0, 8) || "novo job"}.`, "ok");
        await syncPromax({ silent: true });
      } catch (err) {
        addLog(`Falha ao executar agenda Promax: ${err.message}`, "err");
      }
    }

    function promaxRunScheduleGroup(groupKey) {
      const group = promaxFindScheduleGroup(groupKey);
      const scheduleId = String(group && group.primary && group.primary.id || "");
      if (!scheduleId) {
        addLog("Grupo de agenda Promax sem repeticao executavel.", "warn");
        return;
      }
      return promaxRunScheduleNow(scheduleId);
    }

    async function promaxToggleScheduleGroup(groupKey, enabled) {
      const group = promaxFindScheduleGroup(groupKey);
      if (!group || !group.schedules.length) {
        addLog("Grupo de agenda Promax não encontrado.", "warn");
        return;
      }
      const action = enabled ? "Ativar" : "Pausar";
      if (!await askConfirmation(`${action} ${group.schedules.length} repeticao(oes) da agenda "${group.baseName}"?`)) return;
      try {
        for (const schedule of group.schedules) {
          await req(`${CONFIG.endpoints.promax.schedules}/${encodeURIComponent(schedule.id)}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ enabled }),
            timeoutMs: 20000
          });
        }
        addLog(`Agenda Promax atualizada: ${group.schedules.length} repeticao(oes).`, "ok");
        if (promaxScheduleGroupModalInstance) promaxScheduleGroupModalInstance.hide();
        await syncPromax({ silent: true });
      } catch (err) {
        addLog(`Falha ao atualizar repeticoes da agenda: ${err.message}`, "err");
      }
    }

    async function promaxDeleteScheduleGroup(groupKey) {
      const group = promaxFindScheduleGroup(groupKey);
      if (!group || !group.schedules.length) {
        addLog("Grupo de agenda Promax não encontrado.", "warn");
        return;
      }
      if (!await askConfirmation(`Excluir ${group.schedules.length} repeticao(oes) da agenda "${group.baseName}"?`)) return;
      try {
        for (const schedule of [...group.schedules].reverse()) {
          await req(`${CONFIG.endpoints.promax.schedules}/${encodeURIComponent(schedule.id)}`, {
            method: "DELETE",
            timeoutMs: 20000
          });
        }
        addLog("Repeticoes da agenda Promax excluidas.", "ok");
        if (promaxScheduleGroupModalInstance) promaxScheduleGroupModalInstance.hide();
        await syncPromax({ silent: true });
      } catch (err) {
        addLog(`Falha ao excluir repeticoes da agenda: ${err.message}`, "err");
      }
    }

    async function promaxToggleSchedule(scheduleId, enabled) {
      try {
        await req(`${CONFIG.endpoints.promax.schedules}/${encodeURIComponent(scheduleId)}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ enabled }),
          timeoutMs: 20000
        });
        await syncPromax({ silent: true });
      } catch (err) {
        addLog(`Falha ao atualizar agenda Promax: ${err.message}`, "err");
      }
    }

    async function promaxDeleteSchedule(scheduleId) {
      if (!await askConfirmation("Excluir esta agenda Promax?")) return;
      try {
        await req(`${CONFIG.endpoints.promax.schedules}/${encodeURIComponent(scheduleId)}`, {
          method: "DELETE",
          timeoutMs: 20000
        });
        addLog("Agenda Promax excluida.", "ok");
        await syncPromax({ silent: true });
      } catch (err) {
        addLog(`Falha ao excluir agenda Promax: ${err.message}`, "err");
      }
    }

    function promaxFilialFromUnit(unit) {
      const clean = String(unit || "").replace(/\D/g, "");
      if (!clean) return "";
      if (clean.length >= 7) return String(Number(clean.slice(-4)));
      return String(Number(clean));
    }

    function financeiroScheduleFechamentoJobsRefresh() {
      if (state.financeiro.fechamentoJobsTimer) {
        window.clearTimeout(state.financeiro.fechamentoJobsTimer);
        state.financeiro.fechamentoJobsTimer = null;
      }
      const jobs = Array.isArray(state.financeiro.fechamentoJobs) ? state.financeiro.fechamentoJobs : [];
      const hasActive = jobs.some(job => ["pending", "running", "cancel_requested"].includes(String(job && job.status || "").toLowerCase()));
      if (!hasActive) return;
      state.financeiro.fechamentoJobsTimer = window.setTimeout(() => {
        state.financeiro.fechamentoJobsTimer = null;
        financeiroSyncFechamentoJobs({ silent: true });
      }, 5000);
    }

    async function financeiroSolicitarFechamentoPromax() {
      const els = financeiroElements();
      if (!financeiroRequireFilial()) return;
      const mapa = els.fechamentoMapa ? String(els.fechamentoMapa.value || "").trim() : "";
      if (!mapa) {
        addLog("Informe o número do mapa para solicitar o fechamento Promax.", "warn");
        if (els.fechamentoMapa) els.fechamentoMapa.focus();
        return;
      }
      const dataRotina = els.fechamentoData && els.fechamentoData.value
        ? els.fechamentoData.value
        : (els.data && els.data.value ? els.data.value : formatDateInputValue(new Date()));
      const caixaData = els.data && els.data.value ? els.data.value : formatDateInputValue(new Date());
      const rotasDia = Array.isArray(state.financeiro.payload && state.financeiro.payload.rotas_dia)
        ? state.financeiro.payload.rotas_dia
        : [];
      const rotaMapa = rotasDia.find(row => String(row && row.mapa || "").trim() === mapa);
      const payload = {
        data: caixaData,
        data_rotina: dataRotina,
        filial: els.filial && els.filial.value ? els.filial.value : "",
        mapa,
        modo: els.fechamentoModo && els.fechamentoModo.value ? els.fechamentoModo.value : "completo",
        km_atual: els.fechamentoKm && els.fechamentoKm.value ? els.fechamentoKm.value : "",
        km_inicial: rotaMapa && (rotaMapa.km_carregado || rotaMapa.km_atual) ? (rotaMapa.km_carregado || rotaMapa.km_atual) : "",
        km_prev: rotaMapa && rotaMapa.km_prev ? rotaMapa.km_prev : ""
      };
      if (els.fechamentoBtn) els.fechamentoBtn.disabled = true;
      if (els.fechamentoStatus) {
        els.fechamentoStatus.textContent = "Enfileirando fechamento";
        els.fechamentoStatus.className = "pill";
      }
      financeiroSetFechamentoLogHidden(false);
      financeiroResetFechamentoLog("Enfileirando fechamento Promax.");
      try {
        const result = await req(CONFIG.endpoints.financeiro.fechamentoPromax, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          timeoutMs: 20000
        });
        const job = result && result.job ? result.job : {};
        const shortId = String(job.id || "").slice(0, 8);
        if (job.id) {
          state.financeiro.fechamentoJobId = String(job.id);
          state.financeiro.fechamentoLogDone = false;
        }
        if (els.fechamentoStatus) {
          els.fechamentoStatus.textContent = shortId ? `Job ${shortId} enfileirado` : "Fechamento enfileirado";
          els.fechamentoStatus.className = "pill ok";
        }
        if (els.fechamentoLogJob) els.fechamentoLogJob.textContent = shortId ? `Job ${shortId}` : "Job enfileirado";
        if (els.fechamentoLogList) {
          els.fechamentoLogList.innerHTML = '<li><span class="time">--:--</span><span>Job enfileirado. Aguardando worker iniciar.</span></li>';
        }
        await financeiroSyncFechamentoJobs({ silent: true });
        if (job.id) financeiroPollFechamentoLog(String(job.id));
        addLog(`Fechamento Promax solicitado para o mapa ${mapa}.`, "ok");
      } catch (err) {
        if (els.fechamentoStatus) {
          els.fechamentoStatus.textContent = "Falha ao enfileirar";
          els.fechamentoStatus.className = "pill danger";
        }
        addLog(`Falha ao solicitar fechamento Promax: ${err.message}`, "err");
      } finally {
        if (els.fechamentoBtn) els.fechamentoBtn.disabled = false;
      }
    }

    function scheduleCriticaDashboardSync() {
      clearTimeout(criticaDashboardSearchTimer);
      criticaDashboardSearchTimer = setTimeout(() => syncCriticaDashboard({ silent: true }), 350);
    }
