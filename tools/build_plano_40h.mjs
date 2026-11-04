import fs from "node:fs/promises";
import { execFileSync } from "node:child_process";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "C:/Users/cadcom.patos/Documents/bot_api/outputs/plano_40h_gestao_jornada";
const outputPath = `${outputDir}/Plano_40h_Gestao_Jornada_atualizado.xlsx`;
const sourcePath = "M:/REVENDA/ARQUIVOS TEMPORÁRIOS/CADASTRO DE FUNCIONÁRIOS - PATOS E SUMÉ/CADASTRO DE FUNCIONÁRIOS PATOS CORRETO ATUALIZADO.xlsx";
const routesDirectory = "M:/REVENDA/SDPO 2026/DPO/PILAR ENTREGA/RELATORIOS/03.08.05";
const closingDirectory = "M:/REVENDA/SDPO 2026/DPO/PILAR ENTREGA/RELATORIOS/03.11.20";
const navy = "#102A43";
const blue = "#2F80ED";
const paleBlue = "#EAF3FF";
const paleYellow = "#FFF4CC";
const paleRed = "#FDE2E4";
const paleGreen = "#DDF6E9";
const grey = "#5B7083";
const white = "#FFFFFF";

// O cadastro atualizado possui o título na primeira linha e os cabeçalhos na segunda.
// A leitura é restrita aos quatro campos operacionais, pois o arquivo contém abas
// históricas que não participam do plano de jornada.
const sourceExtractor = String.raw`
import sys, json, openpyxl, unicodedata
book = openpyxl.load_workbook(sys.argv[1], read_only=True, data_only=True)
sheet = book.worksheets[0]
rows = list(sheet.iter_rows(values_only=True))
def key(v): return unicodedata.normalize('NFKD', str(v or '')).encode('ascii', 'ignore').decode().strip().upper()
headers = [key(v) for v in rows[1]]
idx = {v:i for i,v in enumerate(headers)}
fields = ['MATRICULA', 'SETOR', 'NOME', 'CARGO ATUAL']
out = []
for row in rows[2:]:
    out.append({field: row[idx[field]] if idx.get(field) is not None else None for field in fields})
print(json.dumps(out, ensure_ascii=False, default=str))
`;
const sourceValues = JSON.parse(execFileSync("C:/Users/cadcom.patos/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe", ["-c", sourceExtractor, sourcePath], { encoding: "utf8" }));
const isPuxador = name => {
  const value = nameText(name).normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  return value.startsWith("RONALDO DINIZ") || value.startsWith("VINICIUS MENDES");
};
const sourceHeaders = ["FUNCAO", "COD", "NOME", "OPERACAO"];
const idxFuncao = 0;
const idxCod = 1;
const idxNome = 2;
const idxOperacao = 3;
const sourceRows = sourceValues
  .filter(row => nameText(row.SETOR) === "ENTREGA")
  .map(row => {
    const cargo = nameText(row["CARGO ATUAL"]);
    const nome = row.NOME;
    const funcao = cargo.includes("MOTORISTA") ? (isPuxador(nome) ? "PUXADOR" : "MOTORISTA") : cargo.includes("AJUDANTE") ? "AJUDANTE" : "";
    return [funcao, row.MATRICULA, nome, "PATOS"];
  })
  .filter(row => row[idxFuncao] && normalizeCode(row[idxCod]) !== "0");

const helperCodes = new Set(sourceRows
  .filter(row => nameText(row[idxFuncao]) === "AJUDANTE")
  .map(row => normalizeCode(row[idxCod])));
const driverCodes = new Set(sourceRows
  .filter(row => nameText(row[idxFuncao]) === "MOTORISTA")
  .map(row => normalizeCode(row[idxCod])));
const patosDrivers = sourceRows.filter(row => nameText(row[idxFuncao]) === "MOTORISTA").length;
const patosHelpers = sourceRows.filter(row => nameText(row[idxFuncao]) === "AJUDANTE").length;
const patosPullers = sourceRows.filter(row => nameText(row[idxFuncao]) === "PUXADOR").length;
const providerHelperCodes = new Set(["10", "20", "29", "66", "7224", "7489", "9054"]);
providerHelperCodes.forEach(code => helperCodes.add(code));

const routeFiles = (await fs.readdir(routesDirectory)).filter(file => file.toLowerCase().endsWith(".csv"));
const closingFiles = (await fs.readdir(closingDirectory)).filter(file => file.toLowerCase().endsWith(".csv"));
const phasesByMap = new Map();
for (const file of closingFiles) {
  const operation = operationFromFile(file);
  const rows = parseCsv(await fs.readFile(`${closingDirectory}/${file}`, "latin1"));
  for (const row of rows) {
    const map = normalizeMap(row.Mapa);
    if (!map || map === "0") continue;
    const key = `${operation}|${map}`;
    const entry = { phase: String(row.Fase || "").trim(), when: phaseDateTime(row), row };
    if (!phasesByMap.has(key)) phasesByMap.set(key, []);
    phasesByMap.get(key).push(entry);
  }
}
function phaseFor(operation, map, phase) {
  return (phasesByMap.get(`${operation}|${map}`) || []).find(item => nameText(item.phase) === nameText(phase))?.when || "";
}
const fechamentoRows = [...phasesByMap.entries()].map(([key, phases]) => {
  const [operation, map] = key.split("|");
  const base = phases.find(item => item.row.Placa || item.row.Motorista || item.row.KmPrev) || phases[0];
  const raw = base.row;
  return [
    operation, map, phaseFor(operation, map, "Entrada Cdd/Fab"), phaseFor(operation, map, "PC_Fisica"), phaseFor(operation, map, "PC_Financeira"), phaseFor(operation, map, "Saida Cdd/Fab"),
    raw.Placa || "", raw.Motorista || "", toNumber(raw.KmPrev), toNumber(raw.KmAtual), raw.Liberacao || "", toNumber(raw["Cx Carregadas"]), `${phases.length} fase(s) consolidadas`,
  ];
});
const historicalRows = [];
const scaleImportedRows = [];
for (const file of routeFiles) {
  const operation = operationFromFile(file);
  const rows = parseCsv(await fs.readFile(`${routesDirectory}/${file}`, "latin1"));
  for (const row of rows) {
    const date = dateFromEight(row.Data);
    const map = normalizeMap(row.Mapa);
    if (!date || !map || map === "0") continue;
    const driverCode = normalizeCode(row.CdMot);
    const driverType = helperCodes.has(driverCode) || !driverCodes.has(driverCode) ? "Diarista" : "Interno";
    const minutes = (() => { const match = String(row.TempoPrev || "").match(/^(\d{1,3}):(\d{2})/); return match ? Number(match[1]) * 60 + Number(match[2]) : 0; })();
    const overnight = minutes > 840 ? "SIM" : "NÃO";
    const entryReal = phaseFor(operation, map, "Entrada Cdd/Fab");
    const physical = phaseFor(operation, map, "PC_Fisica");
    const financial = phaseFor(operation, map, "PC_Financeira");
    historicalRows.push([
      date, operation, map, toNumber(row.PesoCargaKG), toNumber(row.Entregas), row.TempoPrev || "", row.HrSai || "", row.HrEntr || "",
      entryReal, physical, financial, driverCode, normalizeCode(row.CdAju1), normalizeCode(row.CdAju2), "03.08.05 + 03.11.20",
    ]);
    scaleImportedRows.push([
      date, operation, map, toNumber(row.PesoCargaKG), toNumber(row.Entregas), driverType, driverCode,
      normalizeCode(row.CdAju1), normalizeCode(row.CdAju2), overnight, entryReal,
      overnight === "SIM" && !entryReal ? "SIM" : "NÃO", "Importado", `03.08.05 · CdMot ${driverCode}${driverType === "Diarista" ? " = motorista diarista a identificar" : ""}`,
    ]);
  }
}

function nameText(value) { return String(value ?? "").trim().toUpperCase(); }
function roleFromSource(value) {
  if (nameText(value) === "PUXADOR") return "Puxador de madrugada";
  return nameText(value) === "MOTORISTA" ? "Motorista entrega" : "Ajudante de entrega";
}
function typeFromName(name) { return isPuxador(name) ? "Puxador madrugada" : "Próprio"; }
function deliveryFlag(name) { return isPuxador(name) ? "NÃO" : "SIM"; }
function normalizeCode(value) {
  const digits = String(value ?? "").replace(/\D/g, "");
  return digits.replace(/^0+/, "") || "0";
}
function normalizeMap(value) { return normalizeCode(value); }
function toNumber(value) {
  const text = String(value ?? "").trim().replace(/\./g, "").replace(",", ".").replace(/[^0-9.-]/g, "");
  return Number(text) || 0;
}
function dateFromEight(value) {
  const digits = String(value ?? "").replace(/\D/g, "");
  return digits.length === 8 ? `${digits.slice(4)}-${digits.slice(2, 4)}-${digits.slice(0, 2)}` : "";
}
function dateFromDmy(value) {
  const digits = String(value ?? "").replace(/\D/g, "");
  return digits.length === 8 ? `${digits.slice(4)}-${digits.slice(2, 4)}-${digits.slice(0, 2)}` : "";
}
function operationFromFile(fileName) {
  const file = String(fileName).toUpperCase();
  return file.includes("PATOS") ? "PATOS" : file.includes("SUME") ? "SUMÉ" : "";
}
function parseCsv(text) {
  const rows = []; let row = []; let field = ""; let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index]; const next = text[index + 1];
    if (char === '"' && quoted && next === '"') { field += '"'; index += 1; }
    else if (char === '"') quoted = !quoted;
    else if (char === ";" && !quoted) { row.push(field); field = ""; }
    else if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && next === "\n") index += 1;
      row.push(field); field = "";
      if (row.some(value => String(value).trim() !== "")) rows.push(row);
      row = [];
    } else field += char;
  }
  if (field || row.length) { row.push(field); if (row.some(value => String(value).trim() !== "")) rows.push(row); }
  const [headers = [], ...body] = rows;
  return body.map(values => Object.fromEntries(headers.map((header, index) => [String(header).replace(/^\uFEFF/, "").trim(), String(values[index] ?? "").trim()])));
}
function phaseDateTime(row) {
  const date = dateFromDmy(row.DtOper || ""); const time = String(row.HrOper || "").trim();
  return date ? `${date}${time ? ` ${time}` : ""}` : "";
}
function styleTitle(sheet, range, title, subtitle) {
  sheet.getRange(range).merge();
  const cell = sheet.getRange(range.split(":")[0]);
  cell.values = [[title]];
  cell.format = { fill: navy, font: { name: "Arial", size: 16, bold: true, color: white }, verticalAlignment: "center" };
  const subtitleRow = Number(range.match(/\d+/)[0]) + 1;
  const endingColumn = range.split(":")[1].replace(/\d+/g, "");
  sheet.getRange(`A${subtitleRow}:${endingColumn}${subtitleRow}`).merge();
  sheet.getRange(`A${subtitleRow}`).values = [[subtitle]];
  sheet.getRange(`A${subtitleRow}`).format = { font: { name: "Arial", size: 10, italic: true, color: grey }, verticalAlignment: "center" };
}
function styleHeader(sheet, range) {
  const r = sheet.getRange(range);
  r.format = { fill: navy, font: { name: "Arial", size: 10, bold: true, color: white }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true, borders: { preset: "all", style: "thin", color: white } };
}
function styleTable(sheet, range) {
  const r = sheet.getRange(range);
  r.format.font = { name: "Arial", size: 10, color: "#243B53" };
  r.format.verticalAlignment = "center";
  r.format.borders = { preset: "inside", style: "thin", color: "#D9E2EC" };
}
function setWidths(sheet, widths) {
  widths.forEach(([column, width]) => { sheet.getRange(`${column}:${column}`).format.columnWidth = width; });
}

const wb = Workbook.create();
const summary = wb.worksheets.add("Resumo executivo");
const cadastro = wb.worksheets.add("Cadastro operacional");
const escala = wb.worksheets.add("Escala diária");
const ausencias = wb.worksheets.add("Ausências");
const diaristas = wb.worksheets.add("Diárias e custos");
const historico = wb.worksheets.add("Histórico 03.08.05");
const fechamento = wb.worksheets.add("Fechamento 03.11.20");
const listas = wb.worksheets.add("Listas");

[summary, cadastro, escala, ausencias, diaristas, historico, fechamento, listas].forEach(sheet => { sheet.showGridLines = false; });
summary.tabColor = navy;
cadastro.tabColor = blue;

styleTitle(summary, "A2:H2", "Plano de gestão de jornada · 40 horas", "Base atualizada em 29/10/2026: cobertura, pernoite, diaristas e controle de horas. Atualize somente os campos amarelos quando houver mudança de quadro.");
summary.getRange("A5:D5").values = [["Quadro informado", "Motoristas", "Ajudantes", "Observação"]];
styleHeader(summary, "A5:D5");
summary.getRange("A6:D8").values = [
  ["Patos", patosDrivers, patosHelpers, `${patosPullers} puxadores identificados no cadastro; não entram como motorista de entrega.`],
  ["Sumé", 5, 8, "Quadro próprio informado."],
  ["Total", patosDrivers + 5, patosHelpers + 8, "Não inclui motorista diarista como quadro próprio."],
];
styleTable(summary, "A6:D8");
summary.getRange("B6:C8").format.numberFormat = "0";
summary.getRange("A6:D8").format.wrapText = true;

summary.getRange("F5:H5").values = [["Cenário 40h protegido", "Necessário", "Diferença"]];
styleHeader(summary, "F5:H5");
summary.getRange("F6:H11").values = [
  ["Patos · motoristas", 17, patosDrivers - 17],
  ["Patos · ajudantes", 30, 1],
  ["Sumé · motoristas", 6, -1],
  ["Sumé · ajudantes", 9, -1],
  ["Total · motoristas", 23, patosDrivers + 5 - 23],
  ["Total · ajudantes", 39, 0],
];
styleTable(summary, "F6:H11");
summary.getRange("G6:H11").format.numberFormat = "0";
summary.getRange("H6:H11").conditionalFormats.add("cellIs", { operator: "lessThan", formula: 0, format: { fill: paleRed, font: { bold: true, color: "#9B1C31" } } });
summary.getRange("H6:H11").conditionalFormats.add("cellIs", { operator: "greaterThanOrEqual", formula: 0, format: { fill: paleGreen, font: { bold: true, color: "#166534" } } });

summary.getRange("A13:H13").values = [["Decisão e regras operacionais"]];
summary.getRange("A13:H13").merge();
summary.getRange("A13").format = { fill: paleBlue, font: { name: "Arial", size: 11, bold: true, color: navy }, verticalAlignment: "center" };
summary.getRange("A14:H19").values = [
  ["1", "Função fixa", "Motorista é sempre motorista; ajudante é sempre ajudante. O código de ajudante no CdMot indica motorista diarista."],
  ["2", "Puxadores", "Ronaldo e Vinicius são puxadores de madrugada e não contam na capacidade de motorista de entrega."],
  ["3", "Pernoite", "Cada pernoite aberto bloqueia 1 motorista e até 2 ajudantes na programação seguinte."],
  ["4", "Diarista", "Cobre o mapa, mas não consome a jornada de 40h do quadro interno. Registrar em cada rota."],
  ["5", "Ausências", "Férias, afastamentos, faltas e treinamento reduzem a capacidade antes de calcular a escala."],
  ["6", "Histórico", "Importar 8 a 12 semanas da 03.08.05 e 03.11.20 para dimensionar pico, não média. O cadastro atual contém 19 motoristas de entrega em Patos, após excluir 2 puxadores."],
];
for (let row = 14; row <= 19; row += 1) summary.mergeCells(`C${row}:H${row}`);
summary.getRange("A14:A19").format = { fill: blue, font: { bold: true, color: white }, horizontalAlignment: "center" };
summary.getRange("B14:B19").format.font = { bold: true, color: navy };
summary.getRange("A14:H19").format.wrapText = true;
styleTable(summary, "A14:H19");
summary.getRange("A14:H19").format.rowHeight = 34;

summary.getRange("A22:H22").values = [["Plano de 30 dias"]];
summary.getRange("A22:H22").merge();
summary.getRange("A22").format = { fill: paleBlue, font: { name: "Arial", size: 11, bold: true, color: navy } };
summary.getRange("A23:H27").values = [
  ["Semana", "Objetivo", "", "Entregável", "", "", "Responsável", ""],
  ["1", "Saneamento", "", "Cadastro operacional e classificação de prestador/puxador/diarista.", "", "", "Operação + RH", ""],
  ["2", "Medição", "", "Mapa diário com equipe, pernoite, ponto e diarista.", "", "", "Entrega", ""],
  ["3", "Piloto", "", "Cenário de 40h em Sumé e bloqueio de pernoite.", "", "", "Gestão Entrega", ""],
  ["4", "Decisão", "", "Comparativo de custo: diária, hora extra, reforço e rota.", "", "", "Diretoria", ""],
];
for (let row = 23; row <= 27; row += 1) { summary.mergeCells(`B${row}:C${row}`); summary.mergeCells(`D${row}:F${row}`); summary.mergeCells(`G${row}:H${row}`); }
styleHeader(summary, "A23:H23");
styleTable(summary, "A24:H27");
summary.getRange("A23:H27").format.wrapText = true;
summary.getRange("A24:H27").format.rowHeight = 30;
setWidths(summary, [["A", 15], ["B", 18], ["C", 18], ["D", 48], ["E", 3], ["F", 28], ["G", 16], ["H", 14]]);
summary.getRange("A2:H27").format.rowHeight = 22;
summary.getRange("A2:H2").format.rowHeight = 28;
summary.getRange("A3:H3").format.rowHeight = 28;
summary.getRange("A6:D8").format.rowHeight = 36;

styleTitle(cadastro, "A2:L2", "Cadastro operacional de colaboradores", "Fonte inicial: Base colaborador.xlsx. Campos amarelos precisam refletir o cenário atual antes da primeira simulação.");
cadastro.getRange("A4:L4").values = [["Função base", "Matrícula", "Nome", "Operação", "Função para planejamento", "Tipo de vínculo", "Status", "Início vigência", "Fim vigência", "Pode entrega?", "Pode pernoite?", "Observação operacional"]];
styleHeader(cadastro, "A4:L4");
const cadastroRows = sourceRows.map(row => {
  const funcao = row[idxFuncao];
  const codigo = row[idxCod];
  const nome = row[idxNome];
  const operacao = row[idxOperacao];
  return [funcao, codigo, nome, operacao, roleFromSource(funcao), typeFromName(nome), "ATIVO - VALIDAR", "", "", deliveryFlag(nome), "VALIDAR", "Conferir vínculo e vigência do cadastro."];
});
const specialRows = [
  ["", 66, "", "SUMÉ", "Ajudante prestador", "Prestador", "ATIVO - VALIDAR", "", "", "SIM", "VALIDAR", "Código informado pela operação; confirmar nome."],
  ["", 9054, "", "SUMÉ", "Ajudante prestador", "Prestador", "ATIVO - VALIDAR", "", "", "SIM", "VALIDAR", "Código sem base atual; confirmar nome."],
  ["", 10, "", "PATOS", "Ajudante prestador", "Prestador", "ATIVO - VALIDAR", "", "", "SIM", "VALIDAR", "Se aparecer em CdMot, marcar rota como motorista diarista."],
  ["", 20, "", "PATOS", "Ajudante prestador", "Prestador", "ATIVO - VALIDAR", "", "", "SIM", "VALIDAR", "Se aparecer em CdMot, marcar rota como motorista diarista."],
  ["", 7224, "", "PATOS", "Ajudante prestador", "Prestador", "ATIVO - VALIDAR", "", "", "SIM", "VALIDAR", "Se aparecer em CdMot, marcar rota como motorista diarista."],
  ["", 29, "", "PATOS", "Ajudante prestador", "Prestador", "ATIVO - VALIDAR", "", "", "SIM", "VALIDAR", "Se aparecer em CdMot, marcar rota como motorista diarista."],
  ["", 7489, "", "PATOS", "Ajudante prestador", "Prestador", "ATIVO - VALIDAR", "", "", "SIM", "VALIDAR", "Se aparecer em CdMot, marcar rota como motorista diarista."],
];
cadastro.getRange(`A5:L${4 + cadastroRows.length + specialRows.length}`).values = [...cadastroRows, ...specialRows];
styleTable(cadastro, `A5:L${4 + cadastroRows.length + specialRows.length}`);
cadastro.getRange(`E5:L${4 + cadastroRows.length + specialRows.length}`).format.fill = paleYellow;
cadastro.getRange(`H5:I${4 + cadastroRows.length + specialRows.length}`).format.numberFormat = "yyyy-mm-dd";
cadastro.getRange(`A4:L${4 + cadastroRows.length + specialRows.length}`).format.wrapText = true;
cadastro.freezePanes.freezeRows(4);
cadastro.getRange(`F5:F${4 + cadastroRows.length + specialRows.length}`).dataValidation = { rule: { type: "list", values: ["Próprio", "Prestador", "Diarista", "Puxador madrugada"] } };
cadastro.getRange(`G5:G${4 + cadastroRows.length + specialRows.length}`).dataValidation = { rule: { type: "list", values: ["ATIVO", "ATIVO - VALIDAR", "FÉRIAS", "AFASTADO", "DESLIGADO"] } };
cadastro.getRange(`J5:K${4 + cadastroRows.length + specialRows.length}`).dataValidation = { rule: { type: "list", values: ["SIM", "NÃO", "VALIDAR"] } };
cadastro.tables.add(`A4:L${4 + cadastroRows.length + specialRows.length}`, true, "CadastroOperacional");
setWidths(cadastro, [["A", 18], ["B", 12], ["C", 34], ["D", 14], ["E", 27], ["F", 18], ["G", 18], ["H", 14], ["I", 14], ["J", 14], ["K", 15], ["L", 48]]);

styleTitle(escala, "A2:N2", "Escala diária e disponibilidade", "Uma linha por mapa. Registre a equipe real e classifique o motorista como interno ou diarista. Pernoite aberto bloqueia a equipe para o dia seguinte.");
escala.getRange("A4:N4").values = [["Data", "Operação", "Mapa", "Peso kg", "Entregas", "Motorista tipo", "Motorista matrícula", "Ajudante 1", "Ajudante 2", "Pernoite?", "Retorno real", "Bloqueia dia seguinte?", "Situação", "Observação"]];
styleHeader(escala, "A4:N4");
const scaleLastRow = 4 + scaleImportedRows.length;
escala.getRange(`A5:N${scaleLastRow}`).values = scaleImportedRows;
escala.getRange(`A5:N${scaleLastRow}`).format.wrapText = true;
escala.getRange(`L5:L${scaleLastRow}`).conditionalFormats.add("containsText", { text: "SIM", format: { fill: paleRed, font: { bold: true, color: "#9B1C31" } } });
escala.getRange(`F5:F${scaleLastRow}`).conditionalFormats.add("containsText", { text: "Diarista", format: { fill: paleYellow, font: { bold: true, color: "#7C4A03" } } });
escala.getRange(`A5:A${scaleLastRow}`).format.numberFormat = "yyyy-mm-dd";
escala.getRange(`D5:D${scaleLastRow}`).format.numberFormat = "#,##0.00";
escala.freezePanes.freezeRows(4);
escala.tables.add(`A4:N${scaleLastRow}`, true, "EscalaDiaria");
setWidths(escala, [["A", 13], ["B", 14], ["C", 12], ["D", 13], ["E", 11], ["F", 18], ["G", 17], ["H", 15], ["I", 15], ["J", 12], ["K", 19], ["L", 20], ["M", 14], ["N", 38]]);

styleTitle(ausencias, "A2:H2", "Ausências e indisponibilidades", "Preencha antes de gerar a escala. Todo registro reduz a disponibilidade do colaborador na data informada.");
ausencias.getRange("A4:H4").values = [["Data início", "Data fim", "Matrícula", "Nome", "Operação", "Motivo", "Impacta escala?", "Observação"]];
styleHeader(ausencias, "A4:H4");
ausencias.getRange("A5:H104").values = Array.from({ length: 100 }, () => ["", "", "", "", "", "", "SIM", ""]);
styleTable(ausencias, "A5:H104");
ausencias.getRange("A5:H104").format.fill = paleYellow;
ausencias.getRange("A5:B104").format.numberFormat = "yyyy-mm-dd";
ausencias.getRange("F5:F104").dataValidation = { rule: { type: "list", values: ["Férias", "Atestado", "Afastamento", "Falta", "Treinamento", "Outro"] } };
ausencias.getRange("G5:G104").dataValidation = { rule: { type: "list", values: ["SIM", "NÃO"] } };
ausencias.freezePanes.freezeRows(4);
ausencias.tables.add("A4:H104", true, "Ausencias");
setWidths(ausencias, [["A", 14], ["B", 14], ["C", 14], ["D", 34], ["E", 15], ["F", 18], ["G", 16], ["H", 42]]);

styleTitle(diaristas, "A2:J2", "Diárias e custo de cobertura", "Registre toda cobertura externa. A diária resolve o mapa no dia, mas deve ser analisada como custo e sinal de necessidade estrutural.");
diaristas.getRange("A4:J4").values = [["Data", "Operação", "Mapa", "Tipo", "Identificador diarista", "Motivo", "Valor diária", "Horas estimadas", "Horas reais", "Observação"]];
styleHeader(diaristas, "A4:J4");
diaristas.getRange("A5:J104").values = Array.from({ length: 100 }, () => ["", "", "", "Motorista diarista", "", "Cobertura de escala", "", "", "", ""]);
styleTable(diaristas, "A5:J104");
diaristas.getRange("A5:J104").format.fill = paleYellow;
diaristas.getRange("A5:A104").format.numberFormat = "yyyy-mm-dd";
diaristas.getRange("G5:G104").format.numberFormat = 'R$ #,##0.00';
diaristas.getRange("H5:I104").format.numberFormat = "0.00";
diaristas.getRange("D5:D104").dataValidation = { rule: { type: "list", values: ["Motorista diarista", "Ajudante prestador"] } };
diaristas.getRange("F5:F104").dataValidation = { rule: { type: "list", values: ["Cobertura de escala", "Pernoite", "Ausência", "Rota adicional", "Outro"] } };
diaristas.freezePanes.freezeRows(4);
diaristas.tables.add("A4:J104", true, "DiariasCustos");
setWidths(diaristas, [["A", 13], ["B", 14], ["C", 12], ["D", 20], ["E", 24], ["F", 21], ["G", 15], ["H", 16], ["I", 14], ["J", 40]]);

styleTitle(historico, "A2:N2", "Histórico operacional · importação 03.08.05 e 03.11.20", "Importe 8 a 12 semanas. Uma linha por mapa permite identificar pico diário, pernoite, retorno e necessidade de cobertura.");
historico.getRange("A4:N4").values = [["Data", "Operação", "Mapa", "Peso kg", "Entregas", "Tempo previsto", "Saída prevista", "Entrada real", "Fechamento físico", "Fechamento financeiro", "Motorista CdMot", "Ajudante 1", "Ajudante 2", "Fonte"]];
styleHeader(historico, "A4:N4");
const historicalLastRow = 4 + historicalRows.length;
historico.getRange(`A5:N${historicalLastRow}`).values = historicalRows;
historico.getRange(`A5:A${historicalLastRow}`).format.numberFormat = "yyyy-mm-dd";
historico.getRange(`D5:D${historicalLastRow}`).format.numberFormat = "#,##0.00";
historico.freezePanes.freezeRows(4);
historico.tables.add(`A4:N${historicalLastRow}`, true, "HistoricoOperacional");
setWidths(historico, [["A", 13], ["B", 14], ["C", 12], ["D", 13], ["E", 11], ["F", 16], ["G", 17], ["H", 17], ["I", 18], ["J", 20], ["K", 16], ["L", 15], ["M", 15], ["N", 13]]);

styleTitle(fechamento, "A2:M2", "Fechamento de mapas · 03.11.20", "Uma linha por mapa, com as fases consolidadas: entrada, PC físico, PC financeiro e saída.");
fechamento.getRange("A4:M4").values = [["Operação", "Mapa", "Entrada Cdd/Fab", "PC físico", "PC financeiro", "Saída Cdd/Fab", "Placa", "Motorista código", "KM previsto", "KM atual", "Liberação", "Cx carregadas", "Consolidação"]];
styleHeader(fechamento, "A4:M4");
const closingLastRow = 4 + fechamentoRows.length;
fechamento.getRange(`A5:M${closingLastRow}`).values = fechamentoRows;
fechamento.getRange(`I5:J${closingLastRow}`).format.numberFormat = "#,##0.00";
fechamento.getRange(`L5:L${closingLastRow}`).format.numberFormat = "#,##0.00";
fechamento.freezePanes.freezeRows(4);
setWidths(fechamento, [["A", 14], ["B", 12], ["C", 19], ["D", 19], ["E", 19], ["F", 19], ["G", 14], ["H", 16], ["I", 14], ["J", 14], ["K", 14], ["L", 15], ["M", 25]]);

styleTitle(listas, "A2:F2", "Listas de apoio", "Listas usadas nas validações. Mantenha os valores operacionais atualizados.");
listas.getRange("A4:F4").values = [["Função planejamento", "Vínculo", "Status", "Operação", "Motorista tipo", "Motivo ausência"]];
styleHeader(listas, "A4:F4");
listas.getRange("A5:F10").values = [
  ["Motorista entrega", "Próprio", "ATIVO", "PATOS", "Interno", "Férias"],
  ["Ajudante", "Prestador", "ATIVO - VALIDAR", "SUMÉ", "Diarista", "Atestado"],
  ["Puxador madrugada", "Diarista", "FÉRIAS", "", "Puxador - não entrega", "Afastamento"],
  ["Ajudante prestador", "Puxador madrugada", "AFASTADO", "", "", "Falta"],
  ["", "", "DESLIGADO", "", "", "Treinamento"],
  ["", "", "", "", "", "Outro"],
];
styleTable(listas, "A5:F10");
setWidths(listas, [["A", 26], ["B", 20], ["C", 18], ["D", 15], ["E", 22], ["F", 20]]);

wb.recalculate();
const check = await wb.inspect({ kind: "table", range: "Resumo executivo!A2:H27", include: "values,formulas", tableMaxRows: 27, tableMaxCols: 8 });
console.log(check.ndjson);
const errors = await wb.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 100 }, summary: "final formula error scan" });
console.log(errors.ndjson);
const preview = await wb.render({ sheetName: "Resumo executivo", range: "A2:H27", scale: 1.2, format: "png" });
await fs.mkdir(outputDir, { recursive: true });
await fs.writeFile(`${outputDir}/preview_resumo.png`, new Uint8Array(await preview.arrayBuffer()));
const output = await SpreadsheetFile.exportXlsx(wb);
await output.save(outputPath);
console.log(JSON.stringify({ outputPath, previewPath: `${outputDir}/preview_resumo.png`, sourceRows: sourceRows.length, routesImported: historicalRows.length, closingPhasesImported: fechamentoRows.length }));
