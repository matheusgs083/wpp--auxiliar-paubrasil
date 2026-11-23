    const CONFIG = {
      api: "",
      endpoints: {
        clientes: {
          busca: "/api/admin/clientes",
          ficha: "/api/admin/clientes"
        },
        gerarCritica: "/api/admin/critica/geracao",
        rotaFinanceira: {
          opcoes: "/api/admin/rota-financeira/opcoes",
          lista: "/api/admin/rota-financeira"
        },
        panel: {
          session: "/api/admin/panel/session",
          logout: "/api/admin/panel/logout",
          users: "/api/admin/panel/users",
          actions: "/api/admin/panel/actions"
        },
        access: {
          list: "/api/admin/access/users",
          save: "/api/admin/access/users",
          importBulk: "/api/admin/access/users/bulk",
          roles: "/api/admin/access/roles"
        },
        import: {
          status: "/api/admin/imports/status",
          history: "/api/admin/imports/history",
          validate: "/api/admin/imports/validate",
          run: "/api/admin/imports/run",
          upload: "/api/admin/imports/upload",
          criticaGeral: "/api/admin/imports/critica-geral"
        },
        ligaEntrega: {
          expurgos: "/api/admin/liga-entrega/expurgos",
          equipe: "/api/admin/liga-entrega/equipe",
          equipeCadastro: "/api/admin/liga-entrega/equipe/cadastro",
          rotaEquipe: "/api/admin/liga-entrega/rotas/equipe",
          rules: "/api/admin/liga-entrega/regras",
          reports: "/api/admin/liga-entrega/relatorios",
          dashboard: "/api/admin/liga-entrega/dashboard",
          indicadores: "/api/admin/liga-entrega/indicadores",
          jornadaMapas: "/api/admin/liga-entrega/indicadores/jornada-mapas",
          mapasMensais: "/api/admin/liga-entrega/mapas-mensais",
          mapasOperacionais: "/api/admin/liga-entrega/mapas-operacionais",
          mapasOperacionaisPdf: "/api/admin/liga-entrega/mapas-operacionais/pdf",
          devolucoes: "/api/admin/liga-entrega/devolucoes",
          devolucoesCadastros: "/api/admin/liga-entrega/devolucoes/cadastros",
          frota: "/api/admin/liga-entrega/frota",
          dashboardPdf: "/api/admin/liga-entrega/dashboard/pdf"
        },
        usage: {
          evolution: "/api/admin/usage/evolution",
          evolutionReport: "/api/admin/usage/evolution/report",
          evolutionFunctionsReport: "/api/admin/usage/evolution/functions/report",
          panelActions: "/api/admin/usage/panel-actions",
          panelActionsReport: "/api/admin/usage/panel-actions/report"
        },
        broadcast: {
          options: "/api/admin/broadcast/options",
          preview: "/api/admin/broadcast/preview",
          run: "/api/admin/broadcast/run",
          status: "/api/admin/broadcast/status"
        },
        payipBatch: {
          preview: "/api/admin/payip/batch/preview",
          run: "/api/admin/payip/batch/run",
          status: "/api/admin/payip/batch/status",
          result: "/api/admin/payip/batch/result",
          pdf: "/api/admin/payip/batch/pdf",
          exportCsv: "/api/admin/payip/batch/export.csv"
        },
        payipImport: {
          validate: "/api/admin/payip/import/validate",
          createClients: "/api/admin/payip/import/create-clients",
          run: "/api/admin/payip/import/run",
          generatedBatches: "/api/admin/payip/generated-batches",
          generatedBatchProcess: "/api/admin/payip/generated-batches",
          generatedBatchFile: "/api/admin/payip/generated-batches"
        },
        recolhas: {
          list: "/api/admin/recolhas",
          update: "/api/admin/recolhas",
          bulk: "/api/admin/recolhas/bulk",
          importCsv: "/api/admin/recolhas/import",
          exportCsv: "/api/admin/recolhas/export",
          delete: "/api/admin/recolhas"
        },
        financeiro: {
          caixas: "/api/admin/financeiro/caixas",
          caixaPdf: "/api/admin/financeiro/caixa/pdf",
          mapas: "/api/admin/financeiro/mapas",
          prestacaoContas: "/api/admin/financeiro/mapas",
          fechamentoPromax: "/api/admin/financeiro/fechamento-promax",
          fechamentoPromaxLogs: "/api/admin/financeiro/fechamento-promax",
          fechamentoPromaxJobs: "/api/admin/financeiro/fechamento-promax/jobs",
          relatorio031120Download: "/api/admin/financeiro/031120/download",
          relatorio031120Upload: "/api/admin/financeiro/031120/upload",
          worker: "/api/admin/financeiro/worker/status"
        },
        conferencia: {
          mapas: "/api/admin/conferencia/mapas",
          garrafeiras: "/api/admin/conferencia/garrafeiras",
          produtos: "/api/admin/conferencia/produtos"
        },
        protestos: {
          list: "/api/admin/protestos",
          update: "/api/admin/protestos",
          upload: "/api/admin/protestos"
        },
        giroRecolha: {
          dashboard: "/api/admin/giro/recolha-dashboard",
          options: "/api/admin/giro/recolha-filter-options",
          routes: "/api/admin/giro/recolha-routes"
        },
        critica: {
          dashboard: "/api/admin/critica/dashboard",
          pdf: "/api/admin/critica/pdf"
        },
        promax: {
          catalog: "/api/admin/promax/catalog",
          jobs: "/api/admin/promax/jobs",
          coraCriticaJobs: "/api/admin/promax/cora/critica/jobs",
          jobsBatch: "/api/admin/promax/jobs/batch",
          gradeJobs: "/api/admin/promax/grade/jobs",
          grade020304Jobs: "/api/admin/promax/grade-020304/jobs",
          gradeWorkers: "/api/admin/promax/grade/workers",
          worker: "/api/admin/promax/worker/status",
          workerAssignments: "/api/admin/promax/worker-assignments",
          workerCredentials: "/api/admin/promax/worker-credentials",
          pause: "/api/admin/promax/queue/pause",
          resume: "/api/admin/promax/queue/resume",
          pending: "/api/admin/promax/queue/pending",
          reprocessPublications: "/api/admin/promax/publications/reprocess",
          schedules: "/api/admin/promax/schedules",
          scheduleChains: "/api/admin/promax/schedule-chains"
        }
      },
      roles: {
        VENDEDOR: "Vendedor",
        GERENTE_VENDAS: "Gerente de Vendas (GV)",
        DIRETOR_COMERCIAL: "Diretor Comercial (DC)",
        FINANCEIRO: "Financeiro",
        ARMAZEM: "Armazem",
        ADMIN: "Administrador / TI"
      },
      datasets: []
    };

    // Abas do painel (grupos) e as sub-abas que cada permissão libera.
    // Na criação de usuário dá para marcar a aba inteira ou só algumas sub-abas.
    const PANEL_FEATURE_GROUPS = [
      { id: "vendedor", label: "Vendedor", icon: "bi-person-badge" },
      { id: "operacao", label: "Operação", icon: "bi-truck" },
      { id: "financeiro", label: "Financeiro", icon: "bi-cash-stack" },
      { id: "dados", label: "Dados", icon: "bi-database" },
      { id: "admin", label: "Gestão", icon: "bi-gear" }
    ];

    const PANEL_FEATURES = [
      { id: "pedidos", grupo: "vendedor", label: "Pedidos", icon: "bi-cart-plus", description: "Digitação de pedidos para a carteira do vendedor." },
      { id: "cliente", grupo: "vendedor", label: "Clientes", icon: "bi-person-vcard", description: "Ficha do cliente: pendências, boletos e comodatos da carteira." },
      { id: "rota_financeira", grupo: "vendedor", label: "Rota Financeira", icon: "bi-signpost-2", description: "Fila do dia por atraso, vencimento e boleto." },
      { id: "estoque", grupo: "operacao", label: "Estoque", icon: "bi-boxes", description: "Grade Stock_Product do Cora e saldo disponível." },
      { id: "armazem", grupo: "operacao", label: "Armazem", icon: "bi-box-seam", description: "Consultas basicas de cliente e estoque." },
      { id: "entrega", grupo: "operacao", label: "Entrega", icon: "bi-truck", description: "Liga Entrega, rotas e indicadores." },
      { id: "recolhas", grupo: "operacao", label: "Recolhas", icon: "bi-box-arrow-in-down", description: "Solicitações e acompanhamento." },
      { id: "giro", grupo: "operacao", label: "Giro", icon: "bi-arrow-repeat", description: "Giro e oportunidades da carteira." },
      { id: "conferencia", grupo: "operacao", label: "Conferência", icon: "bi-clipboard-check", description: "Contagem cega de materiais e produtos por mapa." },
      { id: "financeiro", grupo: "financeiro", label: "Financeiro", icon: "bi-cash-coin", description: "Fechamento de caixa por dia e mapa." },
      { id: "payip", grupo: "financeiro", label: "PayIP", icon: "bi-credit-card-2-front", description: "Cobranças, validações e clientes." },
      { id: "protestos", grupo: "financeiro", label: "Protestos", icon: "bi-shield-exclamation", description: "Títulos da inadimplência, provas em PDF e retirada de SPC." },
      { id: "reports", grupo: "dados", label: "Relatórios", icon: "bi-folder2-open", description: "Uploads e histórico de relatórios." },
      { id: "critica", grupo: "dados", label: "Crítica", icon: "bi-clipboard-data", description: "Importação, dashboard e PDFs." },
      { id: "gerar_critica", grupo: "dados", label: "Gerar crítica", icon: "bi-cloud-download", description: "Baixa a crítica no Cora e importa agora." },
      { id: "promax", grupo: "dados", label: "Promax", icon: "bi-cloud-arrow-down", description: "Execuções, agendas e workers." },
      { id: "operations", grupo: "admin", label: "Acessos e disparos", icon: "bi-sliders", description: "Acessos, disparos e rotinas operacionais." },
      { id: "usage", grupo: "admin", label: "Uso Evolution", icon: "bi-activity", description: "Número x função e auditoria." }
    ];

    const PROMAX_RESELLERS = [
      { id: "0640001", name: "Sousa" },
      { id: "0640002", name: "Itaporanga" },
      { id: "2210003", name: "Patos" },
      { id: "2210004", name: "Sume" },
      { id: "3480005", name: "Guarabira" },
      { id: "3610006", name: "Brumado" },
      { id: "3610007", name: "Barra da Estiva" },
      { id: "3610008", name: "Cacule" }
    ];

    const PROMAX_UNIT_BY_FILIAL = {
      "1": "0640001",
      "2": "0640002",
      "3": "2210003",
      "4": "2210004",
      "5": "3480005",
      "6": "3610006",
      "7": "3610007",
      "8": "3610008"
    };

    const PROMAX_WEEKDAYS = [
      { value: 0, short: "Seg", name: "Segunda" },
      { value: 1, short: "Ter", name: "Terca" },
      { value: 2, short: "Qua", name: "Quarta" },
      { value: 3, short: "Qui", name: "Quinta" },
      { value: 4, short: "Sex", name: "Sexta" },
      { value: 5, short: "Sab", name: "Sabado" },
      { value: 6, short: "Dom", name: "Domingo" }
    ];

    const PROMAX_SCHEDULE_SLICERS = {
      reseller: {
        prefix: "promaxScheduleReseller",
        listId: "promaxScheduleResellers",
        allText: "Todas as revendas",
        emptyText: "Nenhuma revenda",
        selectedText: "revendas"
      },
      category: {
        prefix: "promaxScheduleCategory",
        listId: "promaxScheduleCategories",
        allText: "Todos os grupos",
        emptyText: "Nenhum grupo",
        selectedText: "grupos"
      },
      routine: {
        prefix: "promaxScheduleRoutine",
        listId: "promaxScheduleRoutines",
        allText: "Todas as rotinas",
        emptyText: "Nenhuma rotina",
        selectedText: "rotinas"
      }
    };

    const PROMAX_RUN_SLICERS = {
      reseller: { ...PROMAX_SCHEDULE_SLICERS.reseller, prefix: "promaxRunReseller", listId: "promaxRunResellers" },
      category: { ...PROMAX_SCHEDULE_SLICERS.category, prefix: "promaxRunCategory", listId: "promaxRunCategories" },
      routine: { ...PROMAX_SCHEDULE_SLICERS.routine, prefix: "promaxRunRoutine", listId: "promaxRunRoutines" }
    };

    const state = {
      logs: [], history: [], jobs: [], status: null,
      tokens: { api: "", admin: "" },
      panel: {
        mode: "",
        isAdmin: false,
        filiais: [],
        canBroadcast: true,
        canImport: true,
        canImportCritica: true,
        canManageRecolhas: true,
        canFinanceiro: true,
        canConferencia: true,
        canProtestos: true,
        canArmazem: true,
        canPayip: true,
        canOperations: true,
        canReports: true,
        canViewGiro: true,
        canViewCritica: true,
        canViewUsage: true,
        canManagePromax: false,
        canEntrega: true
      },
      accessUsers: [], accessEditing: null, panelUsers: [], panelUserEditingId: "", panelUserFilter: "", panelUserTemporaryCredentials: null, lastSyncAt: null,
      evolutionUsage: null,
      panelAudit: null,
      broadcast: { actions: [], days: [], targetModes: [], targetAudiences: [], filiais: [], preview: null, status: null, polling: false },
      payipBatch: { preview: null, previewPayload: null, job: null, state: null, polling: false },
      payipImport: { validation: null, validationPayload: null, loading: false, error: "" },
      payipGenerated: { payload: null, loading: false, error: "", polling: false, lastFilial: "", generating: "" },
      financeiro: { payload: null, selectedId: null, draft: null, loading: false, worker: null, fechamentoJobs: [], fechamentoHiddenJobIds: [], fechamentoJobId: "", fechamentoLogTimer: null, fechamentoJobsTimer: null, fechamentoLogDone: false, fechamentoLogHidden: false, fechamentoDataManual: false, prestacaoNotas: [] },
      conferencia: { payload: null, selectedId: null, detail: null, loading: false, manualRows: [], productResults: [], view: "mapas", garrafeiras: null },
      protestos: { payload: null, loading: false, error: "" },
      promax: {
        catalog: null,
        jobs: [],
        armazemRoutine: "020304",
        grade020304AuditJobs: [],
        selectedGrade020304AuditJobId: "",
        grade020304ProductNames: {},
        grade020304ProductLookupAttempted: {},
        worker: null,
        workerAssignments: [],
        workerCredentials: [],
        credentialUserDrafts: {},
        schedules: [],
        scheduleGroups: [],
        activeScheduleGroupKey: "",
        selectedJobId: "",
        editingScheduleId: "",
        editingScheduleGroupKey: "",
        runSelectedCategories: null,
        runSelectedRoutines: {},
        runSelectedUnits: PROMAX_RESELLERS.map(reseller => reseller.id),
        scheduleSelectedCategories: null,
        scheduleSelectedRoutines: {},
        scheduleSelectedUnits: PROMAX_RESELLERS.map(reseller => reseller.id)
      },
      recolhas: { total: 0, operations: [] },
      giroRecolha: { total: 0, summary: {}, records: [] },
      giroRecolhaOptions: { operations: [], sellers: [], managers: [], cities: [], districts: [], visit_days: [] },
      giroRecolhaSlicerOptions: { operations: [], sellers: [], managers: [], cities: [], districts: [], visit_days: [] },
      giroRecolhaRoutes: { generated: false, total: 0, summary: {}, routes: [] },
      giroRecolhaRouteFilter: { search: "", district: "", minGap: "" },
      giroRecolhaBuilder: { activeRouteId: "", search: "" },
      giroRecolhaRouteHeights: {},
      criticaDashboard: { total: 0, summary: {}, options: {}, rankings: {}, recommendations: [], orders: [] },
      recolhasFilter: { start: "", end: "" },
      datasetValidation: {},
      datasetBusy: {},
      lazyTabs: {},
      ligaEntregaSyncPromise: null,
      ligaEntregaSyncNeedsRefresh: false,
      devolucoesOperacionais: null,
      entregaFrota: { caminhoes: [], metas: [], operacoes: [] },
      devolucoesCadastros: { setores: [], gerentes: [] }
    };

    let DATASET_MAP = {};
    let DATASET_UPLOAD_META = {};
    const DATASET_TIMEOUTS = {
      dClientes: { validateMs: 600000, importMs: 900000 },
      default: { validateMs: 180000, importMs: 300000 }
    };

    const DATASET_UI_OVERRIDES = {
      dsetores: { id: "dSetores", name: "Setores e Vendedores", icon: "bi-diagram-2", area: "operational", group: "Operacional", groupNote: "Tabelas operacionais de apoio: setores, preços, operações, condições, produtos, materiais e cesta." },
      dprecos: { id: "DPrecos", name: "Tabela de Preços", icon: "bi-tags", area: "operational", group: "Operacional" },
      doperacoes: { id: "dOperacoes", name: "Tabela de Operações", icon: "bi-list-columns", area: "operational", group: "Operacional" },
      drevendas: { id: "dRevendas", name: "Tabela de Revendas", icon: "bi-building", area: "operational", group: "Operacional" },
      dcondicoes: { id: "dCondicoes", name: "Tabela de Condições", icon: "bi-receipt", area: "operational", group: "Operacional" },
      dprodutos: { id: "dProdutos", name: "Cadastro de Produtos", icon: "bi-boxes", area: "operational", group: "Operacional" },
      dgarrafeiras: { id: "dGarrafeiras", name: "Tabela de Garrafeiras", icon: "bi-grid-3x3-gap", area: "operational", group: "Operacional" },
      dmateriais: { id: "dMateriais", name: "Tabela de Materiais", icon: "bi-box-seam", area: "operational", group: "Operacional" },
      produto_cestas: { id: "ProdutoCestas", name: "Cesta de Produtos", icon: "bi-collection", area: "operational", group: "Operacional" },
      dclientes: { id: "dClientes", name: "dClientes - 0105070402", icon: "bi-person-badge", area: "promax", group: "Promax", groupNote: "Relatórios oriundos do Promax: dClientes, inadimplência, comodatos, documentação pendente e boletos." },
      inadimplencia: { id: "Inadimplência", name: "Inadimplência - 120601", icon: "bi-graph-down-arrow", area: "promax", group: "Promax" },
      comodatos: { id: "Comodatos", name: "Comodatos - 020220", icon: "bi-box-seam", area: "promax", group: "Promax" },
      documentacao_pendente: { id: "DocumentacaoPendente", name: "Documentação Pendente - 031701", icon: "bi-file-earmark-check", area: "promax", group: "Promax" },
      prazo_limite: { id: "PrazoLimite", name: "Prazo e Limite", icon: "bi-cash-stack", area: "powerbi", group: "Power BI", groupNote: "Relatórios oriundos do Power BI: prazo e limite e giro de vasilhame." },
      giro: { id: "Giro", name: "Giro de Vasilhame", icon: "bi-arrow-repeat", area: "powerbi", group: "Power BI" },

      liga_030805: { id: "Liga030805", name: "03.08.05 - Rotas do dia", icon: "bi-calendar-day", area: "promax", group: "Liga Entrega", groupNote: "Relatórios que alimentam o painel da Liga. 03.08.05 e diário por data; os demais substituem o lote ativo e preservam histórico no armazenamento da Liga." },
      liga_031120: { id: "Liga031120", name: "03.11.20 - Portaria", icon: "bi-map", area: "promax", group: "Liga Entrega" },
      liga_030224_motorista: { id: "Liga030224Motorista", name: "03.02.24 - Devolucoes Motorista", icon: "bi-person-vcard", area: "promax", group: "Liga Entrega" },
      liga_030224_resumo: { id: "Liga030224Resumo", name: "03.02.24 - Devolucoes Resumo", icon: "bi-bar-chart-line", area: "promax", group: "Liga Entrega" },
      liga_030224_ajudante: { id: "Liga030224Ajudante", name: "03.02.24 - Devolucoes Ajudante", icon: "bi-people", area: "promax", group: "Liga Entrega" },
      liga_030237: { id: "Liga030237", name: "03.02.37 - Entregas", icon: "bi-truck", area: "promax", group: "Liga Entrega" },
      liga_03114902: { id: "Liga03114902", name: "03.11.49.02 - Cidades por mapa", icon: "bi-geo-alt", area: "promax", group: "Liga Entrega" },
      liga_03114902_mensal: { id: "Liga03114902Mensal", name: "03.11.49.02 - Cidades por mapa mensal", icon: "bi-calendar3", area: "promax", group: "Liga Entrega" },
      liga_1706_indicadores: { id: "Liga1706Indicadores", name: "17.06 - Indicadores BI", icon: "bi-speedometer2", area: "promax", group: "Liga Entrega" },
      liga_031129: { id: "Liga031129", name: "03.11.29 - Equipes do dia", icon: "bi-person-lines-fill", area: "promax", group: "Liga Entrega" },
      liga_espelho_ponto: { id: "LigaEspelhoPonto", name: "Espelho de ponto", icon: "bi-clock-history", area: "promax", group: "Liga Entrega" },
      liga_checklist_frota: { id: "LigaChecklistFrota", name: "Checklist Frota", icon: "bi-clipboard-check", area: "promax", group: "Liga Entrega" },
      critica_rn: { id: "CriticaRNLegacy", name: "Crítica RN (legado)", icon: "bi-archive", area: "critica", group: "Rotina anterior", groupNote: "Mantida apenas para compatibilidade. O fluxo atual deve usar os uploads por operação.", disabled: true, badge: "Legado", description: "Importação antiga preservada no código, sem uso no fluxo atual do bot.", sourcePath: "data/CriticaRN/critica_rn.xlsx" }
    };

    const DATASET_FALLBACK_ORDER = [
      "dsetores", "dprecos", "doperacoes", "drevendas", "dcondicoes", "dprodutos", "dgarrafeiras", "dmateriais", "produto_cestas",
      "dclientes", "inadimplencia", "comodatos", "documentacao_pendente",
      "liga_1706_indicadores", "liga_03114902_mensal",
      "prazo_limite", "giro", "critica_rn"
    ];

    CONFIG.datasets = buildFallbackImportDatasets();
    rebuildDatasetIndexes();

    const E = {
      main: document.getElementById("mainContent"),
      log: document.getElementById("logPanel"),
      apiToken: document.getElementById("apiToken"),
      apiTokenField: document.getElementById("apiTokenField"),
      adminToken: document.getElementById("adminToken"),
      accessUsersFilter: document.getElementById("accessUsersFilter"),
      themeToggle: document.getElementById("themeToggle"),
      logoutBtn: document.getElementById("logoutBtn"),
      runningState: document.getElementById("runningState"),
      lastJobState: document.getElementById("lastJobState"),
      authState: document.getElementById("authState"),
      operationalGrid: document.getElementById("operationalDatasetGrid"),
      criticaGrid: document.getElementById("criticaDatasetGrid"),
      criticaGeralFile: document.getElementById("criticaGeralFile"),
      criticaGeralImportBtn: document.getElementById("criticaGeralImportBtn"),
      criticaGeralStatus: document.getElementById("criticaGeralStatus"),
      reportGrid: document.getElementById("reportDatasetGrid"),
      powerBiGrid: document.getElementById("powerBiDatasetGrid"),
      historyTable: document.getElementById("historyBody"),
      jobsTable: document.getElementById("jobsBody"),
      promaxTab: document.getElementById("promaxTab"),
      entregaOpenLigaPromaxBtn: document.getElementById("entregaOpenLigaPromaxBtn"),
      entregaLigaExpurgoForm: document.getElementById("entregaLigaExpurgoForm"),
      entregaLigaExpurgoTipo: document.getElementById("entregaLigaExpurgoTipo"),
      entregaLigaExpurgoEscopo: document.getElementById("entregaLigaExpurgoEscopo"),
      entregaLigaExpurgoFilial: document.getElementById("entregaLigaExpurgoFilial"),
      entregaLigaExpurgoData: document.getElementById("entregaLigaExpurgoData"),
      entregaLigaExpurgoAlvo: document.getElementById("entregaLigaExpurgoAlvo"),
      entregaLigaExpurgoAlvoLabel: document.getElementById("entregaLigaExpurgoAlvoLabel"),
      entregaLigaExpurgoMotivo: document.getElementById("entregaLigaExpurgoMotivo"),
      entregaLigaExpurgoHint: document.getElementById("entregaLigaExpurgoHint"),
      entregaLigaDevolucoesExpurgoList: document.getElementById("entregaLigaDevolucoesExpurgoList"),
      entregaLigaExpurgosList: document.getElementById("entregaLigaExpurgosList"),
      entregaLigaReportsGrid: document.getElementById("entregaLigaReportsGrid"),
      entregaLigaReportsSummary: document.getElementById("entregaLigaReportsSummary"),
      entregaLigaReportsRefreshBtn: document.getElementById("entregaLigaReportsRefreshBtn"),
      entregaLigaDashboardStatus: document.getElementById("entregaLigaDashboardStatus"),
      entregaLigaDashboardBadge: document.getElementById("entregaLigaDashboardBadge"),
      entregaLigaDashboardCards: document.getElementById("entregaLigaDashboardCards"),
      entregaLigaDashboardDetails: document.getElementById("entregaLigaDashboardDetails"),
      entregaLigaMes: document.getElementById("entregaLigaMes"),
      entregaIndicadoresModule: document.getElementById("entregaIndicadoresModule"),
      entregaIndicadoresModuleTab: document.getElementById("entregaIndicadoresModuleTab"),
      entregaFechamentoModule: document.getElementById("entregaFechamentoModule"),
      entregaFechamentoModuleTab: document.getElementById("entregaFechamentoModuleTab"),
      entregaIndicadoresRefreshBtn: document.getElementById("entregaIndicadoresRefreshBtn"),
      entregaIndicadoresStatus: document.getElementById("entregaIndicadoresStatus"),
      entregaIndicadoresCards: document.getElementById("entregaIndicadoresCards"),
      entregaIndicadoresBody: document.getElementById("entregaIndicadoresBody"),
      entregaIndicadoresFilial: document.getElementById("entregaIndicadoresFilial"),
      entregaIndicadoresSituacao: document.getElementById("entregaIndicadoresSituacao"),
      entregaIndicadoresLimparFiltrosBtn: document.getElementById("entregaIndicadoresLimparFiltrosBtn"),
      entregaJornadaMapasRefreshBtn: document.getElementById("entregaJornadaMapasRefreshBtn"),
      entregaJornadaMapasStatus: document.getElementById("entregaJornadaMapasStatus"),
      entregaJornadaMapasCards: document.getElementById("entregaJornadaMapasCards"),
      entregaJornadaMapasBody: document.getElementById("entregaJornadaMapasBody"),
      entregaJornadaMapasFilial: document.getElementById("entregaJornadaMapasFilial"),
      entregaJornadaMapasJustificativa: document.getElementById("entregaJornadaMapasJustificativa"),
      entregaJornadaMapasDevolucao: document.getElementById("entregaJornadaMapasDevolucao"),
      entregaJornadaMapasBusca: document.getElementById("entregaJornadaMapasBusca"),
      entregaJornadaMapasOrdem: document.getElementById("entregaJornadaMapasOrdem"),
      entregaJornadaMapasDe: document.getElementById("entregaJornadaMapasDe"),
      entregaJornadaMapasAte: document.getElementById("entregaJornadaMapasAte"),
      entregaJornadaMapasLimparFiltrosBtn: document.getElementById("entregaJornadaMapasLimparFiltrosBtn"),
      entregaOcupacaoVeiculosStatus: document.getElementById("entregaOcupacaoVeiculosStatus"),
      entregaOcupacaoVeiculosCards: document.getElementById("entregaOcupacaoVeiculosCards"),
      entregaOcupacaoVeiculosBody: document.getElementById("entregaOcupacaoVeiculosBody"),
      entregaOcupacaoVeiculosFilial: document.getElementById("entregaOcupacaoVeiculosFilial"),
      entregaOcupacaoVeiculosComparacao: document.getElementById("entregaOcupacaoVeiculosComparacao"),
      entregaOcupacaoVeiculosValor: document.getElementById("entregaOcupacaoVeiculosValor"),
      entregaOcupacaoVeiculosBusca: document.getElementById("entregaOcupacaoVeiculosBusca"),
      entregaOcupacaoVeiculosJustificativa: document.getElementById("entregaOcupacaoVeiculosJustificativa"),
      entregaOcupacaoVeiculosDe: document.getElementById("entregaOcupacaoVeiculosDe"),
      entregaOcupacaoVeiculosAte: document.getElementById("entregaOcupacaoVeiculosAte"),
      entregaOcupacaoVeiculosOrdem: document.getElementById("entregaOcupacaoVeiculosOrdem"),
      entregaOcupacaoVeiculosLimparFiltrosBtn: document.getElementById("entregaOcupacaoVeiculosLimparFiltrosBtn"),
      entregaMapasMensaisRefreshBtn: document.getElementById("entregaMapasMensaisRefreshBtn"),
      entregaMapasMensaisStatus: document.getElementById("entregaMapasMensaisStatus"),
      entregaMapasMensaisCards: document.getElementById("entregaMapasMensaisCards"),
      entregaMapasMensaisBody: document.getElementById("entregaMapasMensaisBody"),
      entregaMapasOperacionaisRefreshBtn: document.getElementById("entregaMapasOperacionaisRefreshBtn"),
      entregaMapasOperacionaisStatus: document.getElementById("entregaMapasOperacionaisStatus"),
      entregaMapasOperacionaisCards: document.getElementById("entregaMapasOperacionaisCards"),
      entregaMapasOperacionaisDetails: document.getElementById("entregaMapasOperacionaisDetails"),
      entregaMapasOperacionaisDataInicio: document.getElementById("entregaMapasOperacionaisDataInicio"),
      entregaMapasOperacionaisDataFim: document.getElementById("entregaMapasOperacionaisDataFim"),
      entregaMapasOperacionaisTodasDatasBtn: document.getElementById("entregaMapasOperacionaisTodasDatasBtn"),
      entregaMapasOperacionaisFilial: document.getElementById("entregaMapasOperacionaisFilial"),
      entregaMapasOperacionaisSituacao: document.getElementById("entregaMapasOperacionaisSituacao"),
      entregaMapasOperacionaisAlertas: document.getElementById("entregaMapasOperacionaisAlertas"),
      entregaMapasOperacionaisBusca: document.getElementById("entregaMapasOperacionaisBusca"),
      entregaMapasOperacionaisLimparFiltrosBtn: document.getElementById("entregaMapasOperacionaisLimparFiltrosBtn"),
      entregaMapasOperacionaisDias: document.getElementById("entregaMapasOperacionaisDias"),
      entregaMapasOperacionaisSelecionarTodosBtn: document.getElementById("entregaMapasOperacionaisSelecionarTodosBtn"),
      entregaMapasOperacionaisLimparDiasBtn: document.getElementById("entregaMapasOperacionaisLimparDiasBtn"),
      entregaMapasOperacionaisPdfBtn: document.getElementById("entregaMapasOperacionaisPdfBtn"),
      entregaDevolucoesModule: document.getElementById("entregaDevolucoesModule"),
      entregaDevolucoesCadastrosModule: document.getElementById("entregaDevolucoesCadastrosModule"),
      entregaDevolucoesStatus: document.getElementById("entregaDevolucoesStatus"),
      entregaDevolucoesCards: document.getElementById("entregaDevolucoesCards"),
      entregaDevolucoesDetails: document.getElementById("entregaDevolucoesDetails"),
      entregaDevolucoesRefreshBtn: document.getElementById("entregaDevolucoesRefreshBtn"),
      entregaDevolucoesCadastrosDetails: document.getElementById("entregaDevolucoesCadastrosDetails"),
      entregaDevolucoesCadastrosSaveBtn: document.getElementById("entregaDevolucoesCadastrosSaveBtn"),
      entregaLigaModule: document.getElementById("entregaLigaModule"),
      entregaLigaCollapseBtn: document.getElementById("entregaLigaCollapseBtn"),
      entregaLigaModuleTab: document.getElementById("entregaLigaModuleTab"),
      entregaDevolucoesModuleTab: document.getElementById("entregaDevolucoesModuleTab"),
      entregaDevolucoesCadastrosModuleTab: document.getElementById("entregaDevolucoesCadastrosModuleTab"),
      entregaFrotaModuleTab: document.getElementById("entregaFrotaModuleTab"),
      entregaFrotaModule: document.getElementById("entregaFrotaModule"),
      entregaFrotaDetails: document.getElementById("entregaFrotaDetails"),
      entregaFrotaSaveBtn: document.getElementById("entregaFrotaSaveBtn"),
      entregaMetasModuleTab: document.getElementById("entregaMetasModuleTab"),
      entregaMetasModule: document.getElementById("entregaMetasModule"),
      entregaMetasDetails: document.getElementById("entregaMetasDetails"),
      entregaMetasSaveBtn: document.getElementById("entregaMetasSaveBtn"),
      entregaOcupacaoVeiculosLegenda: document.getElementById("entregaOcupacaoVeiculosLegenda"),
      promaxWorkerState: document.getElementById("promaxWorkerState"),
      promaxWorkerGrid: document.getElementById("promaxWorkerGrid"),
      promaxWorkerAssignmentsBody: document.getElementById("promaxWorkerAssignmentsBody"),
      promaxSaveWorkerAssignmentsBtn: document.getElementById("promaxSaveWorkerAssignmentsBtn"),
      promaxCredentialsBody: document.getElementById("promaxCredentialsBody"),
      promaxCredentialsStatus: document.getElementById("promaxCredentialsStatus"),
      promaxQueueState: document.getElementById("promaxQueueState"),
      promaxRefreshBtn: document.getElementById("promaxRefreshBtn"),
      promaxPauseBtn: document.getElementById("promaxPauseBtn"),
      promaxResumeBtn: document.getElementById("promaxResumeBtn"),
      promaxClearBtn: document.getElementById("promaxClearBtn"),
      promaxReprocessPublicationsBtn: document.getElementById("promaxReprocessPublicationsBtn"),
      promaxImpactPeriod: document.getElementById("promaxImpactPeriod"),
      promaxImpactSaved: document.getElementById("promaxImpactSaved"),
      promaxImpactManual: document.getElementById("promaxImpactManual"),
      promaxImpactDone: document.getElementById("promaxImpactDone"),
      promaxImpactSuccessRate: document.getElementById("promaxImpactSuccessRate"),
      promaxImpactAvgRuntime: document.getElementById("promaxImpactAvgRuntime"),
      promaxImpactRuns: document.getElementById("promaxImpactRuns"),
      promaxImpactWorkUnits: document.getElementById("promaxImpactWorkUnits"),
      promaxImpactChart: document.getElementById("promaxImpactChart"),
      promaxStartDate: document.getElementById("promaxStartDate"),
      promaxEndDate: document.getElementById("promaxEndDate"),
      promaxSendDates: document.getElementById("promaxSendDates"),
      promaxPublish: document.getElementById("promaxPublish"),
      promaxRunTargetWorker: document.getElementById("promaxRunTargetWorker"),
      promaxRunBtn: document.getElementById("promaxRunBtn"),
      promaxGradeFile: document.getElementById("promaxGradeFile"),
      promaxGradeUnit: document.getElementById("promaxGradeUnit"),
      promaxGradeTargetWorker: document.getElementById("promaxGradeTargetWorker"),
      promaxGradeQueueBtn: document.getElementById("promaxGradeQueueBtn"),
      promaxGradeStatus: document.getElementById("promaxGradeStatus"),
      promaxGradeTemplateBtn: document.getElementById("promaxGradeTemplateBtn"),
      promaxGradeManualArmazem: document.getElementById("promaxGradeManualArmazem"),
      promaxGradeManualDeposito: document.getElementById("promaxGradeManualDeposito"),
      promaxGradeManualDate: document.getElementById("promaxGradeManualDate"),
      promaxGradeManualRows: document.getElementById("promaxGradeManualRows"),
      promaxGradeAddRowBtn: document.getElementById("promaxGradeAddRowBtn"),
      promaxGradeManualQueueBtn: document.getElementById("promaxGradeManualQueueBtn"),
      promaxGradeManualStatus: document.getElementById("promaxGradeManualStatus"),
      promaxGrade020304File: document.getElementById("promaxGrade020304File"),
      promaxGrade020304Unit: document.getElementById("promaxGrade020304Unit"),
      promaxGrade020304Worker: document.getElementById("promaxGrade020304Worker"),
      promaxGrade020304QueueBtn: document.getElementById("promaxGrade020304QueueBtn"),
      promaxGrade020304Status: document.getElementById("promaxGrade020304Status"),
      promaxGrade020304TemplateBtn: document.getElementById("promaxGrade020304TemplateBtn"),
      promaxGrade020304ManualGrade: document.getElementById("promaxGrade020304ManualGrade"),
      promaxGrade020304ManualRows: document.getElementById("promaxGrade020304ManualRows"),
      promaxGrade020304AddRowBtn: document.getElementById("promaxGrade020304AddRowBtn"),
      promaxGrade020304ManualQueueBtn: document.getElementById("promaxGrade020304ManualQueueBtn"),
      promaxGrade020304ManualStatus: document.getElementById("promaxGrade020304ManualStatus"),
      armazemRoutine020304Tab: document.getElementById("armazemRoutine020304Tab"),
      armazemRoutine020105Tab: document.getElementById("armazemRoutine020105Tab"),
      armazemRoutineAuditTab: document.getElementById("armazemRoutineAuditTab"),
      armazemQueueTotal: document.getElementById("armazemQueueTotal"),
      armazemQueueDone: document.getElementById("armazemQueueDone"),
      armazemQueuePending: document.getElementById("armazemQueuePending"),
      armazemQueueFailed: document.getElementById("armazemQueueFailed"),
      armazemGradeTab: document.getElementById("armazemGradeTab"),
      armazem020304Tab: document.getElementById("armazem020304Tab"),
      armazemGradePane: document.getElementById("armazemGradePane"),
      armazem020304Pane: document.getElementById("armazem020304Pane"),
      armazemGradeAudit: document.getElementById("armazemGradeAudit"),
      armazemGradeAuditCount: document.getElementById("armazemGradeAuditCount"),
      armazemGradeAuditDate: document.getElementById("armazemGradeAuditDate"),
      armazemGradeAuditTodayBtn: document.getElementById("armazemGradeAuditTodayBtn"),
      armazemGradeAuditSearch: document.getElementById("armazemGradeAuditSearch"),
      armazemGradeAuditErrorsOnly: document.getElementById("armazemGradeAuditErrorsOnly"),
      promaxJobStatusFilter: document.getElementById("promaxJobStatusFilter"),
      promaxJobFromDate: document.getElementById("promaxJobFromDate"),
      promaxJobToDate: document.getElementById("promaxJobToDate"),
      promaxJobClearFiltersBtn: document.getElementById("promaxJobClearFiltersBtn"),
      promaxJobsBody: document.getElementById("promaxJobsBody"),
      promaxScheduleName: document.getElementById("promaxScheduleName"),
      promaxScheduleType: document.getElementById("promaxScheduleType"),
      promaxScheduleTime: document.getElementById("promaxScheduleTime"),
      promaxScheduleWeekdayWrap: document.getElementById("promaxScheduleWeekdayWrap"),
      promaxScheduleWeekday: document.getElementById("promaxScheduleWeekday"),
      promaxScheduleMonthDayWrap: document.getElementById("promaxScheduleMonthDayWrap"),
      promaxScheduleMonthDay: document.getElementById("promaxScheduleMonthDay"),
      promaxScheduleDailyDaysWrap: document.getElementById("promaxScheduleDailyDaysWrap"),
      promaxScheduleDailyDays: document.getElementById("promaxScheduleDailyDays"),
      promaxScheduleSpecificWrap: document.getElementById("promaxScheduleSpecificWrap"),
      promaxScheduleSpecificHours: document.getElementById("promaxScheduleSpecificHours"),
      promaxScheduleSpecificStart: document.getElementById("promaxScheduleSpecificStart"),
      promaxScheduleSpecificEnd: document.getElementById("promaxScheduleSpecificEnd"),
      promaxScheduleSpecificStep: document.getElementById("promaxScheduleSpecificStep"),
      promaxScheduleSpecificPreview: document.getElementById("promaxScheduleSpecificPreview"),
      promaxScheduleHourlyWrap: document.getElementById("promaxScheduleHourlyWrap"),
      promaxScheduleHourlyStart: document.getElementById("promaxScheduleHourlyStart"),
      promaxScheduleHourlyEnd: document.getElementById("promaxScheduleHourlyEnd"),
      promaxScheduleHourlyStep: document.getElementById("promaxScheduleHourlyStep"),
      promaxScheduleHourlyPreview: document.getElementById("promaxScheduleHourlyPreview"),
      promaxScheduleCreateBtn: document.getElementById("promaxScheduleCreateBtn"),
      promaxScheduleCancelBtn: document.getElementById("promaxScheduleCancelBtn"),
      promaxSchedulesBody: document.getElementById("promaxSchedulesBody"),
      promaxScheduleCategories: document.getElementById("promaxScheduleCategories"),
      promaxScheduleStartDate: document.getElementById("promaxScheduleStartDate"),
      promaxScheduleEndDate: document.getElementById("promaxScheduleEndDate"),
      promaxScheduleSendDates: document.getElementById("promaxScheduleSendDates"),
      promaxScheduleResellers: document.getElementById("promaxScheduleResellers"),
      promaxScheduleRoutines: document.getElementById("promaxScheduleRoutines"),
      promaxSchedulePublish: document.getElementById("promaxSchedulePublish"),
      promaxScheduleTargetWorker: document.getElementById("promaxScheduleTargetWorker"),
      promaxScheduleTriggerType: document.getElementById("promaxScheduleTriggerType"),
      promaxScheduleTriggerScheduleWrap: document.getElementById("promaxScheduleTriggerScheduleWrap"),
      promaxScheduleTriggerSchedule: document.getElementById("promaxScheduleTriggerSchedule"),
      promaxScheduleTypeWrap: document.getElementById("promaxScheduleTypeWrap"),
      promaxScheduleTimeWrap: document.getElementById("promaxScheduleTimeWrap"),
      promaxLogJob: document.getElementById("promaxLogJob"),
      promaxLogOutput: document.getElementById("promaxLogOutput"),
      promaxUnitsModalTitle: document.getElementById("promaxUnitsModalTitle"),
      promaxUnitsModalSubtitle: document.getElementById("promaxUnitsModalSubtitle"),
      promaxUnitsModalBody: document.getElementById("promaxUnitsModalBody"),
      promaxScheduleGroupModalTitle: document.getElementById("promaxScheduleGroupModalTitle"),
      promaxScheduleGroupModalSubtitle: document.getElementById("promaxScheduleGroupModalSubtitle"),
      promaxScheduleGroupModalDays: document.getElementById("promaxScheduleGroupModalDays"),
      promaxScheduleGroupModalBody: document.getElementById("promaxScheduleGroupModalBody"),
      promaxScheduleGroupRunBtn: document.getElementById("promaxScheduleGroupRunBtn"),
      accessRole: document.getElementById("accessRole"),
      accessScopeHint: document.getElementById("accessScopeHint"),
      accessModeHint: document.getElementById("accessModeHint"),
      accessUsersTable: document.getElementById("accessUsersBody"),
      accessUserCount: document.getElementById("accessUserCount"),
      accessBulk: document.getElementById("accessBulk"),
      metricDatasets: document.getElementById("metricDatasets"),
      metricUsers: document.getElementById("metricUsers"),
      metricRunning: document.getElementById("metricRunning"),
      metricLastSync: document.getElementById("metricLastSync"),
      usageWindow: document.getElementById("usageWindow"),
      usageFunctionWindow: document.getElementById("usageFunctionWindow"),
      usageFunctionDateFrom: document.getElementById("usageFunctionDateFrom"),
      usageFunctionDateTo: document.getElementById("usageFunctionDateTo"),
      usageFunctionFilter: document.getElementById("usageFunctionFilter"),
      usageExportReportBtn: document.getElementById("usageExportReportBtn"),
      usageFunctionRefreshBtn: document.getElementById("usageFunctionRefreshBtn"),
      usageFunctionExportBtn: document.getElementById("usageFunctionExportBtn"),
      usageDailyBars: document.getElementById("usageDailyBars"),
      usageTopNumbersBody: document.getElementById("usageTopNumbersBody"),
      usageFunctionSummaryBody: document.getElementById("usageFunctionSummaryBody"),
      usageFunctionUsersBody: document.getElementById("usageFunctionUsersBody"),
      usageBreakdownBody: document.getElementById("usageBreakdownBody"),
      usageRecentBody: document.getElementById("usageRecentBody"),
      usageMetricMessages: document.getElementById("usageMetricMessages"),
      usageMetricUnique: document.getElementById("usageMetricUnique"),
      usageMetricProcessed: document.getElementById("usageMetricProcessed"),
      usageMetricBlocked: document.getElementById("usageMetricBlocked"),
      usageMetricErrors: document.getElementById("usageMetricErrors"),
      usageMetricDeniedSent: document.getElementById("usageMetricDeniedSent"),
      usageMetricDeniedSuppressed: document.getElementById("usageMetricDeniedSuppressed"),
      usageMetricEvents: document.getElementById("usageMetricEvents"),
      usageMetricFeatureInteractions: document.getElementById("usageMetricFeatureInteractions"),
      usageMetricFeatureUsers: document.getElementById("usageMetricFeatureUsers"),
      usageMetricFeatureCount: document.getElementById("usageMetricFeatureCount"),
      usageMetricFeatureTop: document.getElementById("usageMetricFeatureTop"),
      panelAuditDateFrom: document.getElementById("panelAuditDateFrom"),
      panelAuditDateTo: document.getElementById("panelAuditDateTo"),
      panelAuditUser: document.getElementById("panelAuditUser"),
      panelAuditModule: document.getElementById("panelAuditModule"),
      panelAuditAction: document.getElementById("panelAuditAction"),
      panelAuditRefreshBtn: document.getElementById("panelAuditRefreshBtn"),
      panelAuditExportBtn: document.getElementById("panelAuditExportBtn"),
      panelAuditCount: document.getElementById("panelAuditCount"),
      panelAuditBody: document.getElementById("panelAuditBody"),
      accessEditorCard: document.getElementById("accessEditorCard"),
      allowedUsersCard: document.getElementById("allowedUsersCard"),
      allowedUsersContainer: document.getElementById("allowedUsersContainer"),
      panelUsersPanel: document.getElementById("panelUsersPanel"),
      panelUsersCount: document.getElementById("panelUsersCount"),
      panelUsersActiveCount: document.getElementById("panelUsersActiveCount"),
      panelUsersAdminCount: document.getElementById("panelUsersAdminCount"),
      panelUsersPendingCount: document.getElementById("panelUsersPendingCount"),
      panelUsersBlockedCount: document.getElementById("panelUsersBlockedCount"),
      panelUserMode: document.getElementById("panelUserMode"),
      panelUsersFilterInfo: document.getElementById("panelUsersFilterInfo"),
      panelUserSearch: document.getElementById("panelUserSearch"),
      panelUserId: document.getElementById("panelUserId"),
      panelUsername: document.getElementById("panelUsername"),
      panelDisplayName: document.getElementById("panelDisplayName"),
      panelUserFiliais: document.getElementById("panelUserFiliais"),
      panelUserSellerScopes: document.getElementById("panelUserSellerScopes"),
      panelUserGvScopes: document.getElementById("panelUserGvScopes"),
      panelUserActive: document.getElementById("panelUserActive"),
      panelUserAdmin: document.getElementById("panelUserAdmin"),
      panelUserAdminHint: document.getElementById("panelUserAdminHint"),
      panelUserFeatures: document.getElementById("panelUserFeatures"),
      panelUserFeatureCount: document.getElementById("panelUserFeatureCount"),
      panelUserSaveBtn: document.getElementById("panelUserSaveBtn"),
      panelUserResetFormBtn: document.getElementById("panelUserResetFormBtn"),
      panelUserPasswordBox: document.getElementById("panelUserPasswordBox"),
      panelUserPasswordUsername: document.getElementById("panelUserPasswordUsername"),
      panelUserPasswordValue: document.getElementById("panelUserPasswordValue"),
      panelUserCopyPasswordBtn: document.getElementById("panelUserCopyPasswordBtn"),
      panelUsersBody: document.getElementById("panelUsersBody"),
      usageEvolutionTab: document.getElementById("usageEvolutionTab"),
      payipTab: document.getElementById("payipTab"),
      broadcastPanel: document.getElementById("broadcastPanel"),
      broadcastFilial: document.getElementById("broadcastFilial"),
      broadcastAudience: document.getElementById("broadcastAudience"),
      broadcastAction: document.getElementById("broadcastAction"),
      broadcastDay: document.getElementById("broadcastDay"),
      broadcastTargetMode: document.getElementById("broadcastTargetMode"),
      broadcastTargetNumber: document.getElementById("broadcastTargetNumber"),
      broadcastTargetNumberWrap: document.getElementById("broadcastTargetNumberWrap"),
      broadcastPreviewBtn: document.getElementById("broadcastPreviewBtn"),
      broadcastRunBtn: document.getElementById("broadcastRunBtn"),
      broadcastRefreshBtn: document.getElementById("broadcastRefreshBtn"),
      broadcastStatus: document.getElementById("broadcastStatus"),
      broadcastSummary: document.getElementById("broadcastSummary"),
      broadcastRecipientsBody: document.getElementById("broadcastRecipientsBody"),
      broadcastSelectAll: document.getElementById("broadcastSelectAll"),
      payipGeneratedBatchesPanel: document.getElementById("payipGeneratedBatchesPanel"),
      payipGeneratedStatus: document.getElementById("payipGeneratedStatus"),
      payipGeneratedFilial: document.getElementById("payipGeneratedFilial"),
      payipGeneratedMfaCode: document.getElementById("payipGeneratedMfaCode"),
      payipGeneratedRefreshBtn: document.getElementById("payipGeneratedRefreshBtn"),
      payipGeneratedHint: document.getElementById("payipGeneratedHint"),
      payipGeneratedBody: document.getElementById("payipGeneratedBody"),
      payipImportPanel: document.getElementById("payipImportPanel"),
      payipImportStatus: document.getElementById("payipImportStatus"),
      payipImportFilial: document.getElementById("payipImportFilial"),
      payipImportStartDate: document.getElementById("payipImportStartDate"),
      payipImportEndDate: document.getElementById("payipImportEndDate"),
      payipImportMfaCode: document.getElementById("payipImportMfaCode"),
      payipImportValidateBtn: document.getElementById("payipImportValidateBtn"),
      payipImportRunBtn: document.getElementById("payipImportRunBtn"),
      payipImportBody: document.getElementById("payipImportBody"),
      payipBatchPanel: document.getElementById("payipBatchPanel"),
      payipBatchStatus: document.getElementById("payipBatchStatus"),
      payipBatchText: document.getElementById("payipBatchText"),
      payipBatchMfaCode: document.getElementById("payipBatchMfaCode"),
      payipBatchDefaultRate: document.getElementById("payipBatchDefaultRate"),
      payipBatchDefaultInterest: document.getElementById("payipBatchDefaultInterest"),
      payipBatchIncludeNb: document.getElementById("payipBatchIncludeNb"),
      payipBatchIncludeNf: document.getElementById("payipBatchIncludeNf"),
      payipBatchAutoCreate: document.getElementById("payipBatchAutoCreate"),
      payipBatchPreviewBtn: document.getElementById("payipBatchPreviewBtn"),
      payipBatchRunBtn: document.getElementById("payipBatchRunBtn"),
      payipBatchStatusBtn: document.getElementById("payipBatchStatusBtn"),
      payipBatchExportBtn: document.getElementById("payipBatchExportBtn"),
      payipBatchBody: document.getElementById("payipBatchBody"),
      protestosTab: document.getElementById("protestosTab"),
      protestosStatus: document.getElementById("protestosStatus"),
      protestosRefreshBtn: document.getElementById("protestosRefreshBtn"),
      protestosFilial: document.getElementById("protestosFilial"),
      protestosStatusFilter: document.getElementById("protestosStatusFilter"),
      protestosSearch: document.getElementById("protestosSearch"),
      protestosTitleDateFrom: document.getElementById("protestosTitleDateFrom"),
      protestosTitleDateTo: document.getElementById("protestosTitleDateTo"),
      protestosActionDateFrom: document.getElementById("protestosActionDateFrom"),
      protestosActionDateTo: document.getElementById("protestosActionDateTo"),
      protestosApplyBtn: document.getElementById("protestosApplyBtn"),
      protestosSummary: document.getElementById("protestosSummary"),
      protestosPaidAlert: document.getElementById("protestosPaidAlert"),
      protestosBody: document.getElementById("protestosBody"),
      recolhasContainer: document.getElementById("recolhasContainer"),
      recolhasCount: document.getElementById("recolhasCount"),
      recolhasExportBtn: document.getElementById("recolhasExportBtn"),
      recolhasRefreshBtn: document.getElementById("recolhasRefreshBtn"),
      recolhasStartDate: document.getElementById("recolhasStartDate"),
      recolhasEndDate: document.getElementById("recolhasEndDate"),
      recolhasPeriodClearBtn: document.getElementById("recolhasPeriodClearBtn"),
      recolhasPeriodLabel: document.getElementById("recolhasPeriodLabel"),
      recolhasImportFile: document.getElementById("recolhasImportFile"),
      recolhasImportBtn: document.getElementById("recolhasImportBtn"),
      recolhasDashboardCards: document.getElementById("recolhasDashboardCards"),
      recolhasReasonList: document.getElementById("recolhasReasonList"),
      recolhasOperationSummary: document.getElementById("recolhasOperationSummary"),
      giroRecolhaCount: document.getElementById("giroRecolhaCount"),
      giroRecolhaRefreshBtn: document.getElementById("giroRecolhaRefreshBtn"),
      giroRecolhaRoutesBtn: document.getElementById("giroRecolhaRoutesBtn"),
      giroRecolhaOperation: document.getElementById("giroRecolhaOperation"),
      giroRecolhaCity: document.getElementById("giroRecolhaCity"),
      giroRecolhaCitySlicer: document.getElementById("giroRecolhaCitySlicer"),
      giroRecolhaCityButton: document.getElementById("giroRecolhaCityButton"),
      giroRecolhaCityPanel: document.getElementById("giroRecolhaCityPanel"),
      giroRecolhaCitySearch: document.getElementById("giroRecolhaCitySearch"),
      giroRecolhaCityList: document.getElementById("giroRecolhaCityList"),
      giroRecolhaCitySelectAllBtn: document.getElementById("giroRecolhaCitySelectAllBtn"),
      giroRecolhaCityClearBtn: document.getElementById("giroRecolhaCityClearBtn"),
      giroRecolhaDistrict: document.getElementById("giroRecolhaDistrict"),
      giroRecolhaSeller: document.getElementById("giroRecolhaSeller"),
      giroRecolhaManager: document.getElementById("giroRecolhaManager"),
      giroRecolhaVisitDay: document.getElementById("giroRecolhaVisitDay"),
      giroRecolhaMinGap: document.getElementById("giroRecolhaMinGap"),
      giroRecolhaLimit: document.getElementById("giroRecolhaLimit"),
      giroRecolhaMaxRouteSize: document.getElementById("giroRecolhaMaxRouteSize"),
      giroRecolhaZeroOnly: document.getElementById("giroRecolhaZeroOnly"),
      giroRecolhaClearBtn: document.getElementById("giroRecolhaClearBtn"),
      giroRecolhaCards: document.getElementById("giroRecolhaCards"),
      giroRecolhaRouteCards: document.getElementById("giroRecolhaRouteCards"),
      giroRecolhaRouteTools: document.getElementById("giroRecolhaRouteTools"),
      giroRecolhaRouteSearch: document.getElementById("giroRecolhaRouteSearch"),
      giroRecolhaRouteDistrict: document.getElementById("giroRecolhaRouteDistrict"),
      giroRecolhaRouteMinGap: document.getElementById("giroRecolhaRouteMinGap"),
      giroRecolhaRouteClearBtn: document.getElementById("giroRecolhaRouteClearBtn"),
      giroRecolhaRouteExportBtn: document.getElementById("giroRecolhaRouteExportBtn"),
      giroRecolhaBuilder: document.getElementById("giroRecolhaBuilder"),
      giroRecolhaActiveRoute: document.getElementById("giroRecolhaActiveRoute"),
      giroRecolhaBlockSearch: document.getElementById("giroRecolhaBlockSearch"),
      giroRecolhaBuilderHint: document.getElementById("giroRecolhaBuilderHint"),
      giroRecolhaBlockPool: document.getElementById("giroRecolhaBlockPool"),
      giroRecolhaNewRouteBtn: document.getElementById("giroRecolhaNewRouteBtn"),
      giroRecolhaRoutesContainer: document.getElementById("giroRecolhaRoutesContainer"),
      giroRecolhaBody: document.getElementById("giroRecolhaBody"),
      criticaDashboardCount: document.getElementById("criticaDashboardCount"),
      criticaDashboardRefreshBtn: document.getElementById("criticaDashboardRefreshBtn"),
      criticaOperationSingle: document.getElementById("criticaOperationSingle"),
      criticaOperationPdfBtn: document.getElementById("criticaOperationPdfBtn"),
      criticaOperationSummaryPdfBtn: document.getElementById("criticaOperationSummaryPdfBtn"),
      criticaSectorPdfBtn: document.getElementById("criticaSectorPdfBtn"),
      criticaSectorSummaryPdfBtn: document.getElementById("criticaSectorSummaryPdfBtn"),
      criticaDashboardClearBtn: document.getElementById("criticaDashboardClearBtn"),
      criticaDate: document.getElementById("criticaDate"),
      criticaOperation: document.getElementById("criticaOperation"),
      criticaProblem: document.getElementById("criticaProblem"),
      criticaSector: document.getElementById("criticaSector"),
      criticaManager: document.getElementById("criticaManager"),
      criticaSeller: document.getElementById("criticaSeller"),
      criticaCity: document.getElementById("criticaCity"),
      criticaDistrict: document.getElementById("criticaDistrict"),
      criticaOrigin: document.getElementById("criticaOrigin"),
      criticaSearch: document.getElementById("criticaSearch"),
      criticaLimit: document.getElementById("criticaLimit"),
      criticaOnlyProblems: document.getElementById("criticaOnlyProblems"),
      criticaDashboardCards: document.getElementById("criticaDashboardCards"),
      criticaProblemRank: document.getElementById("criticaProblemRank"),
      criticaConcentrationRank: document.getElementById("criticaConcentrationRank"),
      criticaRecommendations: document.getElementById("criticaRecommendations"),
      criticaDashboardBody: document.getElementById("criticaDashboardBody"),
      confirmModalText: document.getElementById("confirmModalText"),
      confirmModalOk: document.getElementById("confirmModalOk"),
      confirmModalCancel: document.getElementById("confirmModalCancel"),
      panelCredentialsUsername: document.getElementById("panelCredentialsUsername"),
      panelCredentialsPassword: document.getElementById("panelCredentialsPassword"),
      panelCredentialsCopyBtn: document.getElementById("panelCredentialsCopyBtn")
    };

    const GIRO_RECOLHA_SLICERS = [
      {
        key: "operation",
        selectKey: "giroRecolhaOperation",
        optionKey: "operations",
        idPrefix: "giroRecolhaOperation",
        allText: "Todas",
        selectedText: "operações selecionadas",
        emptyText: "Nenhuma operação encontrada.",
        clears: ["city", "district", "seller", "manager", "visitDay"]
      },
      {
        key: "city",
        selectKey: "giroRecolhaCity",
        optionKey: "cities",
        idPrefix: "giroRecolhaCity",
        allText: "Todas",
        selectedText: "cidades selecionadas",
        emptyText: "Nenhuma cidade encontrada.",
        clears: ["district"]
      },
      {
        key: "district",
        selectKey: "giroRecolhaDistrict",
        optionKey: "districts",
        idPrefix: "giroRecolhaDistrict",
        allText: "Todos",
        selectedText: "bairros selecionados",
        emptyText: "Nenhum bairro encontrado."
      },
      {
        key: "seller",
        selectKey: "giroRecolhaSeller",
        optionKey: "sellers",
        idPrefix: "giroRecolhaSeller",
        allText: "Todos",
        selectedText: "vendedores selecionados",
        emptyText: "Nenhum vendedor encontrado."
      },
      {
        key: "manager",
        selectKey: "giroRecolhaManager",
        optionKey: "managers",
        idPrefix: "giroRecolhaManager",
        allText: "Todos",
        selectedText: "GVs selecionados",
        emptyText: "Nenhum GV encontrado."
      },
      {
        key: "visitDay",
        selectKey: "giroRecolhaVisitDay",
        optionKey: "visit_days",
        idPrefix: "giroRecolhaVisitDay",
        allText: "Todos",
        selectedText: "dias selecionados",
        emptyText: "Nenhum dia encontrado."
      }
    ];
    const GIRO_RECOLHA_SLICER_BY_KEY = GIRO_RECOLHA_SLICERS.reduce((acc, item) => {
      acc[item.key] = item;
      return acc;
    }, {});

    const CRITICA_DASHBOARD_SLICERS = [
      {
        key: "operation",
        selectKey: "criticaOperation",
        optionKey: "operations",
        idPrefix: "criticaOperation",
        allText: "Todas",
        selectedText: "operações selecionadas",
        emptyText: "Nenhuma operação encontrada.",
        clears: ["sector", "manager", "seller", "city", "district", "origin"]
      },
      {
        key: "problem",
        selectKey: "criticaProblem",
        optionKey: "problems",
        idPrefix: "criticaProblem",
        allText: "Todos",
        selectedText: "problemas selecionados",
        emptyText: "Nenhum problema encontrado."
      },
      {
        key: "sector",
        selectKey: "criticaSector",
        optionKey: "sectors",
        idPrefix: "criticaSector",
        allText: "Todos",
        selectedText: "setores selecionados",
        emptyText: "Nenhum setor encontrado."
      },
      {
        key: "manager",
        selectKey: "criticaManager",
        optionKey: "managers",
        idPrefix: "criticaManager",
        allText: "Todos",
        selectedText: "GVs selecionados",
        emptyText: "Nenhum GV encontrado."
      },
      {
        key: "seller",
        selectKey: "criticaSeller",
        optionKey: "sellers",
        idPrefix: "criticaSeller",
        allText: "Todos",
        selectedText: "vendedores selecionados",
        emptyText: "Nenhum vendedor encontrado."
      },
      {
        key: "city",
        selectKey: "criticaCity",
        optionKey: "cities",
        idPrefix: "criticaCity",
        allText: "Todas",
        selectedText: "cidades selecionadas",
        emptyText: "Nenhuma cidade encontrada.",
        clears: ["district"]
      },
      {
        key: "district",
        selectKey: "criticaDistrict",
        optionKey: "districts",
        idPrefix: "criticaDistrict",
        allText: "Todos",
        selectedText: "bairros selecionados",
        emptyText: "Nenhum bairro encontrado."
      },
      {
        key: "origin",
        selectKey: "criticaOrigin",
        optionKey: "origins",
        idPrefix: "criticaOrigin",
        allText: "Todas",
        selectedText: "origens selecionadas",
        emptyText: "Nenhuma origem encontrada."
      }
    ];
    const CRITICA_DASHBOARD_SLICER_BY_KEY = CRITICA_DASHBOARD_SLICERS.reduce((acc, item) => {
      acc[item.key] = item;
      return acc;
    }, {});

    const confirmModalInstance = document.getElementById("confirmModal")
      ? new bootstrap.Modal(document.getElementById("confirmModal"), { backdrop: "static", keyboard: true })
      : null;
    const panelCredentialsModalInstance = document.getElementById("panelCredentialsModal")
      ? new bootstrap.Modal(document.getElementById("panelCredentialsModal"), { backdrop: "static", keyboard: true })
      : null;
    const promaxUnitsModalInstance = document.getElementById("promaxUnitsModal")
      ? new bootstrap.Modal(document.getElementById("promaxUnitsModal"), { keyboard: true })
      : null;
    const promaxScheduleGroupModalInstance = document.getElementById("promaxScheduleGroupModal")
      ? new bootstrap.Modal(document.getElementById("promaxScheduleGroupModal"), { keyboard: true })
      : null;
    let allowedUsersCardResizeObserver = null;
    let giroRouteResizeObserver = null;
    const PANEL_TAB_BY_PATH = {
      "/": "operationsTab",
      "/acessos": "operationsTab",
      "/payip": "payipTab",
      "/relatorios": "reportsTab",
      "/promax": "promaxTab",
      "/pedidos": "pedidosTab",
      "/clientes": "clientesTab",
      "/rota-financeira": "rotaFinanceiraTab",
      "/estoque": "estoqueTab",
      "/armazem": "armazemTab",
      "/entrega": "entregaTab",
      "/critica": "criticaTab",
      "/gerar-critica": "gerarCriticaTab",
      "/recolhas": "recolhasTab",
      "/protestos": "protestosTab",
      "/financeiro": "financeiroTab",
      "/conferencia": "conferenciaTab",
      "/giro": "giroRecolhaTab",
      "/uso": "usageEvolutionTab"
    };

    const PANEL_PATH_BY_TAB = {
      operationsTab: "/acessos",
      payipTab: "/payip",
      reportsTab: "/relatorios",
      promaxTab: "/promax",
      pedidosTab: "/pedidos",
      clientesTab: "/clientes",
      rotaFinanceiraTab: "/rota-financeira",
      estoqueTab: "/estoque",
      armazemTab: "/armazem",
      entregaTab: "/entrega",
      criticaTab: "/critica",
      gerarCriticaTab: "/gerar-critica",
      recolhasTab: "/recolhas",
      protestosTab: "/protestos",
      financeiroTab: "/financeiro",
      conferenciaTab: "/conferencia",
      giroRecolhaTab: "/giro",
      usageEvolutionTab: "/uso"
    };

    // Faixas das tabelas de jornada e ocupação (minutos e percentuais).
    const OPS_JORNADA_ATENCAO_MIN = 12 * 60;
    const OPS_JORNADA_CRITICA_MIN = 15 * 60;
    const OPS_INTERNO_ATENCAO_MIN = 90;
    const OPS_INTERNO_CRITICO_MIN = 120;
    const OPS_DIF_CRITICA_MIN = 60;
    const OPS_OCUPACAO_BOA = 70;
    const OPS_OCUPACAO_BAIXA = 50;

    const LIGA_MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"];

    const CONFERENCIA_GRUPOS = ["300", "600", "1L", "51", "FREEZER", "CADEIRA", "MESA", "BARRIL", "BARRACA", "OUTRAS GARRAFEIRAS", "OUTROS MATERIAIS", "PRODUTO"];
    const CONFERENCIA_FAST_GROUPS = ["300", "600", "1L", "51"];
    const CONFERENCIA_MANUAL_GROUPS = ["300", "600", "1L", "51", "FREEZER", "CADEIRA", "MESA", "BARRIL", "BARRACA", "OUTRAS GARRAFEIRAS", "OUTROS MATERIAIS"];
    const CONFERENCIA_MATERIAL_QUICK_GROUPS = ["300", "600", "1L", "51", "FREEZER", "CADEIRA", "MESA", "BARRIL", "BARRACA"];
    const CONFERENCIA_INTEGER_GROUPS = ["300", "600", "1L", "51", "FREEZER", "CADEIRA", "MESA", "BARRIL", "BARRACA", "OUTRAS GARRAFEIRAS", "OUTROS MATERIAIS", "PRODUTO"];
    const CONFERENCIA_GARRAFEIRA_GROUPS = ["300", "600", "1L", "51"];
    const scheduleConferenciaSearch = debounce(() => {
      if (state.panel && state.panel.canConferencia) syncConferencia({ silent: true });
    }, 240);
    const scheduleConferenciaItemSearch = debounce(() => {
      if (state.conferencia && state.conferencia.selectedId) loadConferenciaMapa(state.conferencia.selectedId);
    }, 220);
    const scheduleConferenciaProductSearch = debounce(() => searchConferenciaProducts(), 260);

    const FINANCEIRO_DENOMS = ["200", "100", "50", "20", "10", "5", "2"];
    const FINANCEIRO_DIRTY_SUPPORTED_FIELDS = [
      "tipo_bloco", "mapa", "mapa_ref", "motorista", "placa", "ajudante1", "ajudante2",
      "boletos_rota", "boletos_recebido_qtd", "total_promax", "credito_conta", "dinheiro_promax",
      "dinheiro", "moedas", "diarista", "diarista_recibo_recebido", "pernoite", "hospedagem",
      "janta", "almoco", "cafe", "observacao"
    ];

    const scheduleAccessRender = debounce(() => renderAccess(), 120);
    const scheduleGiroRouteFilterUpdate = debounce(() => updateGiroRecolhaRouteFilters(), 120);
    const scheduleGiroBlockSearchUpdate = debounce(() => updateGiroRecolhaBlockSearch(), 120);

    let criticaDashboardSearchTimer = null;

    const RECOLHA_STATUS_OPTIONS = ["Nao Recolhido", "Recolhido"];
    const RECOLHA_PARTIAL_REASON = "Recolha parcial";
    const RECOLHA_MOTIVO_OPTIONS = [
      "",
      "Recolhido no prazo",
      "Baixa confirmada no sistema",
      RECOLHA_PARTIAL_REASON,
      "Cliente fechado",
      "Cliente ausente",
      "Cliente recusou",
      "Endereco nao localizado",
      "Material nao localizado",
      "Sem motorista",
      "Sem rota",
      "Nao quis",
      "Outro"
    ];

    const rotaUi = { opcoes: null, dados: null, clientes: [], situacao: "todos", pagina: 1, seq: 0 };
    const clientesUi = { rows: [], filtros: new Set(), seq: 0, atual: null };
    const fichaUi = { seq: 0, atual: null, cliente: null, blocos: {}, abertos: [], pedido: "", inicialFeito: 0 };
    const pedidosUi = { client: null, items: [], loadingClient: false, stockTimers: {}, conditions: [], queue: [], config: null, audit: [], productLimits: [], selectedLimitProduct: null, managerProductTimer: null };
