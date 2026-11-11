import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outDir = "C:/Users/cadcom.patos/Documents/bot_api/outputs/escala_motoristas_5x2_20261110";
const outFile = `${outDir}/Escala_5x2_Patos.xlsx`;

const drivers = [
  "Adriano Diniz Paulo", "Carlos Alexandre Leite Silva", "Cicero Delfino da Costa",
  "Cosmo Jackson Monteiro Santana", "Diogo de Medeiros Lima", "Emanuel da Silva Guedes",
  "Motorista A", "Jofle Luilles Carvalho Leite", "Jose Francileudo Rodrigues",
  "Jose Vanderlan da Silva Gomes", "Josivaldo Gomes de Oliveira", "Laires Mendes de Sousa",
  "Leonardo Vieira da Silva", "Pedro Aprigio dos Santos Filho", "Roberto Jorge Almeida dos Santos Junior",
  "Tulio Belo de Lima", "Willyan de Lima Satorno", "Expedito Acassio de Araujo Roque", "Motorista B",
];

const helpers = [
  "Alexsandro Costa de Araujo", "Antonio de Medeiros Batista",
  "Antonio Marcio da Silva Filho", "Avany Nobrega Alves", "Carlos Alberto Nascimento de Araujo",
  "Fabio Junho Mendes Farias", "Francisco Samuel Soares da Silva Rocha",
  "Gabriel Morais Bezerra", "Gilmar Soares Ferreira", "Irlandir Ferreira de Lira",
  "Jeferson Gomes Martins Lima", "Jose Anderson Oliveira dos Santos", "Jose Aluizio Paulo de Souza",
  "Jose Antonio de Maria Neto", "Jose Henrique Dourado da Silva", "Jose Marcelo Galdino Pereira",
  "Jucielson de Souza Costa", "Luan Victor de Sousa Dantas", "Marcelo Barbosa Lucena",
  "Marcio Nunes Alves", "Matheus da Silva Almeida", "Mauricio Apolinario Nobrega Filho",
  "Michell Rodrigo Macedo Dantas", "Nicollas da Silva Lucena", "Pedro Lourenco Medeiros",
  "Romario da Silva Ferreira", "Ruan Victor Leite Batista", "Uelson Nunes Alves", "Anderson", "Alysson", "Joao Vitor",
];

const satDrivers = new Set(["Jose Vanderlan da Silva Gomes", "Willyan de Lima Satorno", "Expedito Acassio de Araujo Roque"]);
const satHelpers = new Set(["Anderson", "Michell Rodrigo Macedo Dantas", "Mauricio Apolinario Nobrega Filho", "Matheus da Silva Almeida", "Alysson", "Joao Vitor", "Jeferson Gomes Martins Lima", "Jose Marcelo Galdino Pereira", "Gilmar Soares Ferreira"]);
const weekdays = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado"];

const teams = [
  ["Equipe 01", "Adriano Diniz Paulo", "Alexsandro Costa de Araujo", "Antonio de Medeiros Batista"],
  ["Equipe 02", "Carlos Alexandre Leite Silva", "Antonio Marcio da Silva Filho", "Avany Nobrega Alves"],
  ["Equipe 03", "Cicero Delfino da Costa", "Carlos Alberto Nascimento de Araujo", "Fabio Junho Mendes Farias"],
  ["Equipe 04", "Cosmo Jackson Monteiro Santana", "Francisco Samuel Soares da Silva Rocha", "Gabriel Morais Bezerra"],
  ["Equipe 05", "Diogo de Medeiros Lima", "Gilmar Soares Ferreira", "Irlandir Ferreira de Lira"],
  ["Equipe 06", "Emanuel da Silva Guedes", "Jeferson Gomes Martins Lima", "Jose Anderson Oliveira dos Santos"],
  ["Equipe 07", "Motorista A", "Jose Aluizio Paulo de Souza", "Jose Antonio de Maria Neto"],
  ["Equipe 08", "Jofle Luilles Carvalho Leite", "Jose Henrique Dourado da Silva", "Jose Marcelo Galdino Pereira"],
  ["Equipe 09", "Jose Francileudo Rodrigues", "Jucielson de Souza Costa", "Luan Victor de Sousa Dantas"],
  ["Equipe 10", "Jose Vanderlan da Silva Gomes", "Marcelo Barbosa Lucena", "Marcio Nunes Alves"],
  ["Equipe 11", "Josivaldo Gomes de Oliveira", "Matheus da Silva Almeida", "Mauricio Apolinario Nobrega Filho"],
  ["Equipe 12", "Laires Mendes de Sousa", "Michell Rodrigo Macedo Dantas", "Nicollas da Silva Lucena"],
  ["Equipe 13", "Leonardo Vieira da Silva", "Pedro Lourenco Medeiros", "Romario da Silva Ferreira"],
  ["Equipe 14", "Pedro Aprigio dos Santos Filho", "Ruan Victor Leite Batista", "Uelson Nunes Alves"],
  ["Equipe 15", "Roberto Jorge Almeida dos Santos Junior", "Anderson", "Alysson"],
];

const mondayTeams = [
  ["Equipe 01", "Adriano Diniz Paulo", "Alexsandro Costa de Araujo", "Antonio de Medeiros Batista"],
  ["Equipe 02", "Carlos Alexandre Leite Silva", "Antonio Marcio da Silva Filho", "Avany Nobrega Alves"],
  ["Equipe 03", "Cicero Delfino da Costa", "Carlos Alberto Nascimento de Araujo", "Fabio Junho Mendes Farias"],
  ["Equipe 04", "Cosmo Jackson Monteiro Santana", "Francisco Samuel Soares da Silva Rocha", "Gabriel Morais Bezerra"],
  ["Equipe 05", "Diogo de Medeiros Lima", "Irlandir Ferreira de Lira", "Jose Anderson Oliveira dos Santos"],
  ["Equipe 06", "Emanuel da Silva Guedes", "Jose Aluizio Paulo de Souza", "Jose Antonio de Maria Neto"],
  ["Equipe 07", "Motorista A", "Jose Henrique Dourado da Silva", "Jucielson de Souza Costa"],
  ["Equipe 08", "Jofle Luilles Carvalho Leite", "Luan Victor de Sousa Dantas", ""],
  ["Equipe 09", "Jose Francileudo Rodrigues", "Marcelo Barbosa Lucena", ""],
  ["Equipe 10", "Tulio Belo de Lima", "Marcio Nunes Alves", ""],
  ["Equipe 11", "Josivaldo Gomes de Oliveira", "Nicollas da Silva Lucena", ""],
  ["Equipe 12", "Laires Mendes de Sousa", "Pedro Lourenco Medeiros", ""],
  ["Equipe 13", "Leonardo Vieira da Silva", "Romario da Silva Ferreira", ""],
  ["Equipe 14", "Pedro Aprigio dos Santos Filho", "Ruan Victor Leite Batista", ""],
  ["Equipe 15", "Roberto Jorge Almeida dos Santos Junior", "Uelson Nunes Alves", ""],
];

const wb = Workbook.create();
const escala = wb.worksheets.add("Escala");
const equipes = wb.worksheets.add("Equipes");
const controle = wb.worksheets.add("Controle");
const sume = wb.worksheets.add("Sumé");
for (const sh of [escala, equipes, controle, sume]) { sh.showGridLines = false; }

const navy = "#17365D";
const blue = "#D9EAF7";
const green = "#E2F0D9";
const yellow = "#FFF2CC";
const red = "#FCE4D6";
const gray = "#F2F2F2";
const header = { fill: navy, font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center" };
const thin = { preset: "all", style: "thin", color: "#D9E2F3" };

escala.getRange("A2:H2").merge();
escala.getRange("A2").values = [["Escala semanal 5x2 - Patos"]];
escala.getRange("A2").format = { font: { name: "Arial", size: 15, bold: true, color: navy } };
escala.getRange("A3:H3").merge();
escala.getRange("A3").values = [["Regra obrigatória: quem trabalha no sábado fica de folga na segunda. Domingo é folga de todos."]];
escala.getRange("A3").format = { font: { name: "Arial", size: 10, italic: true, color: "#666666" } };
escala.getRange("A5:H7").values = [
  ["Configuração", "Valor", "", "", "", "", "", ""],
  ["Equipes em rota de segunda a sexta", 15, "", "Equipes em rota no sábado", 3, "", "", ""],
  ["Motoristas", 19, "", "Ajudantes cadastrados nesta escala", 31, "", "", ""],
];
escala.getRange("A5:H5").format = header;
escala.getRange("A5:H7").format.borders = thin;
escala.getRange("A6:B7").format.fill = blue;
escala.getRange("D6:E7").format.fill = blue;
escala.getRange("A10:H10").values = [["Motoristas", "Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Observação"]];
escala.getRange("A10:H10").format = header;
const driverRows = drivers.map((name) => {
  const sat = satDrivers.has(name);
  return [name, sat ? "Folga" : "Rota/Apoio", sat ? "Rota/Apoio" : "Rota/Apoio", sat ? "Rota/Apoio" : "Rota/Apoio", sat ? "Rota/Apoio" : "Rota/Apoio", sat ? "Rota/Apoio" : "Rota/Apoio", sat ? "Rota" : "Folga", sat ? "Trabalha sábado; folga segunda" : "Folga no sábado"];
});
escala.getRange(`A11:H${10 + driverRows.length}`).values = driverRows;
escala.getRange(`A11:H${10 + driverRows.length}`).format.borders = thin;
escala.getRange(`A11:A${10 + driverRows.length}`).format.font = { name: "Arial", size: 10, bold: true };
escala.getRange("A17").format.fill = yellow;
escala.getRange("A29").format.fill = yellow;

const helperStart = 33;
escala.getRange(`A${helperStart}:H${helperStart}`).values = [["Ajudantes", "Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Observação"]];
escala.getRange(`A${helperStart}:H${helperStart}`).format = header;
const helperRows = helpers.map((name) => {
  const sat = satHelpers.has(name);
  return [name, sat ? "Folga" : "Rota/Apoio", sat ? "Rota/Apoio" : "Rota/Apoio", sat ? "Rota/Apoio" : "Rota/Apoio", sat ? "Rota/Apoio" : "Rota/Apoio", sat ? "Rota/Apoio" : "Rota/Apoio", sat ? "Rota" : "Folga", sat ? "Trabalha sábado; folga segunda" : "Folga no sábado"];
});
escala.getRange(`A${helperStart + 1}:H${helperStart + helperRows.length}`).values = helperRows;
escala.getRange(`A${helperStart + 1}:H${helperStart + helperRows.length}`).format.borders = thin;
escala.getRange(`A${helperStart + 1}:A${helperStart + helperRows.length}`).format.font = { name: "Arial", size: 10, bold: true };
escala.getRange(`A${helperStart + helperRows.length + 3}:H${helperStart + helperRows.length + 4}`).merge();
escala.getRange(`A${helperStart + helperRows.length + 3}`).values = [["Fonte: plano de produtividade 5x2 e espelho de jornada de Patos, ambos fornecidos pelo usuário. Os campos amarelos representam as duas vagas de motorista A e B."]];
escala.getRange(`A${helperStart + helperRows.length + 3}`).format = { fill: gray, font: { name: "Arial", size: 9, italic: true, color: "#666666" }, wrapText: true };
escala.getRange("B11:G64").conditionalFormats.add("containsText", { text: "Folga", format: { fill: red, font: { color: "#9C0006" } } });
escala.getRange("B11:G64").conditionalFormats.add("containsText", { text: "Rota", format: { fill: green, font: { color: "#375623" } } });
escala.freezePanes.freezeRows(10);
escala.getRange("A:A").format.columnWidth = 35;
escala.getRange("B:G").format.columnWidth = 15;
escala.getRange("H:H").format.columnWidth = 31;
escala.getRange("A2:H68").format.font = { name: "Arial", size: 10 };

equipes.getRange("A2:F2").merge();
equipes.getRange("A2").values = [["Equipes de rota"]];
equipes.getRange("A2").format = { font: { name: "Arial", size: 15, bold: true, color: navy } };
equipes.getRange("A3:F3").merge();
equipes.getRange("A3").values = [["Na segunda, as equipes de sábado são substituídas. De terça a sexta, a formação-base se mantém."]];
equipes.getRange("A3").format = { font: { name: "Arial", size: 10, italic: true, color: "#666666" } };
equipes.getRange("A5:F5").values = [["Dia", "Equipe", "Motorista", "Ajudante 1", "Ajudante 2", "Ajudante 3"]];
equipes.getRange("A5:F5").format = header;
const teamRows = [];
for (const t of mondayTeams) teamRows.push(["Segunda", ...t, ""]);
for (const day of ["Terça", "Quarta", "Quinta", "Sexta"]) for (const t of teams) teamRows.push([day, ...t, ""]);
teamRows.push(["Sábado", "Equipe 10", "Jose Vanderlan da Silva Gomes", "Anderson", "Michell Rodrigo Macedo Dantas", "Jeferson Gomes Martins Lima"]);
teamRows.push(["Sábado", "Equipe 16", "Willyan de Lima Satorno", "Mauricio Apolinario Nobrega Filho", "Matheus da Silva Almeida", "Jose Marcelo Galdino Pereira"]);
teamRows.push(["Sábado", "Equipe 17", "Expedito Acassio de Araujo Roque", "Alysson", "Joao Vitor", "Gilmar Soares Ferreira"]);
equipes.getRange(`A6:F${5 + teamRows.length}`).values = teamRows;
equipes.getRange(`A6:F${5 + teamRows.length}`).format.borders = thin;
equipes.getRange(`A6:A${5 + teamRows.length}`).format.fill = blue;
equipes.getRange(`A${5 + teamRows.length + 2}:F${5 + teamRows.length + 3}`).merge();
equipes.getRange(`A${5 + teamRows.length + 2}`).values = [["Túlio substitui Vanderlan na segunda. Willyan e Expedito trabalham no sábado e ficam de folga na segunda. Ajuste a equipe antes da saída caso haja falta, férias ou volume acima do previsto."]];
equipes.getRange(`A${5 + teamRows.length + 2}`).format = { fill: yellow, font: { name: "Arial", size: 9, italic: true }, wrapText: true };
equipes.freezePanes.freezeRows(5);
equipes.getRange("A:A").format.columnWidth = 13;
equipes.getRange("B:B").format.columnWidth = 13;
equipes.getRange("C:C").format.columnWidth = 34;
equipes.getRange("D:F").format.columnWidth = 33;
equipes.getRange(`A2:F${5 + teamRows.length + 3}`).format.font = { name: "Arial", size: 10 };

controle.getRange("A2:G2").merge();
controle.getRange("A2").values = [["Controle da escala"]];
controle.getRange("A2").format = { font: { name: "Arial", size: 15, bold: true, color: navy } };
controle.getRange("A5:G5").values = [["Dia", "Equipes previstas", "Equipes escaladas", "Status", "Motoristas de sábado", "Folga na segunda", "Regra"]];
controle.getRange("A5:G5").format = header;
const controlRows = weekdays.map((day, i) => [day, i === 5 ? 3 : 15, null, null, null, null, null]);
controle.getRange("A6:G11").values = controlRows;
controle.getRange("C6").formulas = [["=COUNTIF(Equipes!$A$6:$A$83,A6)"]];
controle.getRange("C6:C11").fillDown();
controle.getRange("D6").formulas = [["=IF(B6=C6,\"OK\",\"REVISAR\")"]];
controle.getRange("D6:D11").fillDown();
controle.getRange("E6").formulas = [["=IF(A6=\"Sábado\",COUNTIF(Escala!$G$11:$G$29,\"Rota\"),\"\")"]];
controle.getRange("E6:E11").fillDown();
controle.getRange("F6").formulas = [["=IF(A6=\"Segunda\",COUNTIF(Escala!$B$11:$B$29,\"Folga\"),\"\")"]];
controle.getRange("F6:F11").fillDown();
controle.getRange("G6").formulas = [["=IF(AND(A6=\"Segunda\",F6>=E11),\"OK\",IF(A6=\"Segunda\",\"REVISAR\",\"\"))"]];
controle.getRange("G6:G11").fillDown();
controle.getRange("A13:G15").merge();
controle.getRange("A13").values = [["Validação-chave: 3 motoristas trabalham no sábado e os mesmos 3 ficam de folga na segunda. A programação opera em 5x2, com domingo livre para todos."]];
controle.getRange("A13").format = { fill: gray, font: { name: "Arial", size: 10, italic: true }, wrapText: true };
controle.getRange("A5:G11").format.borders = thin;
controle.getRange("D6:D11").conditionalFormats.add("containsText", { text: "REVISAR", format: { fill: red, font: { bold: true, color: "#9C0006" } } });
controle.getRange("D6:D11").conditionalFormats.add("containsText", { text: "OK", format: { fill: green, font: { bold: true, color: "#375623" } } });
controle.getRange("G6:G11").conditionalFormats.add("containsText", { text: "REVISAR", format: { fill: red, font: { bold: true, color: "#9C0006" } } });
controle.getRange("G6:G11").conditionalFormats.add("containsText", { text: "OK", format: { fill: green, font: { bold: true, color: "#375623" } } });
controle.getRange("A:A").format.columnWidth = 15;
controle.getRange("B:G").format.columnWidth = 19;
controle.getRange("A2:G15").format.font = { name: "Arial", size: 10 };

// ---------------- SUMÉ: 5x2 sem pernoite ----------------
const sumeTeams = [
  ["Equipe A", "Yan Oliveira Pereira", "Luiz Carlos Ferreira da Silva", "Ajudante A"],
  ["Equipe B", "Jose Robson Ribeiro do Nascimento", "Jackson de Lima Silva", "Ajudante B"],
  ["Equipe C", "Jose Marcio Cordeiro de Souza", "Genilson Jose de Sousa", "Ajudante C"],
  ["Equipe D", "Valdeci Soares de Lima", "Jeferson Barros de Melo", ""],
  ["Equipe E", "Jose Lucas de Oliveira Duarte", "Francisco Florencio da Silva Junior", ""],
];
const sumeSupport = ["Leonaldo Nunes da Silva", "Irismark Clemente de Lira", "Cassio Caue Silva Oliveira"];
sume.getRange("A2:I2").merge();
sume.getRange("A2").values = [["Escala semanal 5x2 - Sumé"]];
sume.getRange("A2").format = { font: { name: "Arial", size: 15, bold: true, color: navy } };
sume.getRange("A3:I3").merge();
sume.getRange("A3").values = [["Sem pernoite: todas as equipes trabalham de segunda a sexta e folgam sábado e domingo."]];
sume.getRange("A3").format = { font: { name: "Arial", size: 10, italic: true, color: "#666666" } };
sume.getRange("A5:I7").values = [
  ["Configuração", "Valor", "", "", "", "", "", "", ""],
  ["Equipes em rota", 5, "", "Motoristas", 5, "", "Ajudantes", 8, ""],
  ["Pernoite", "Não", "", "Modelo", "5x2", "", "Sábado", "Folga geral", ""],
];
sume.getRange("A5:I5").format = header;
sume.getRange("A5:I7").format.borders = thin;
sume.getRange("A6:B7").format.fill = blue;
sume.getRange("D6:E7").format.fill = blue;
sume.getRange("G6:H7").format.fill = blue;
sume.getRange("A10:I10").values = [["Equipe", "Motorista", "Ajudante principal", "Referência", "Segunda", "Terça", "Quarta", "Quinta", "Sexta"]];
sume.getRange("A10:I10").format = header;
const sumeRows = sumeTeams.map(t => [...t, "Rota", "Rota", "Rota", "Rota", "Rota"]);
sume.getRange("A11:I15").values = sumeRows;
sume.getRange("A11:I15").format.borders = thin;
sume.getRange("E11:I15").format.fill = green;
sume.getRange("A18:F18").values = [["Ajudantes de apoio / cobertura", "Segunda", "Terça", "Quarta", "Quinta", "Sexta"]];
sume.getRange("A18:F18").format = header;
sume.getRange("A19:F21").values = sumeSupport.map(n => [n, "Apoio", "Apoio", "Apoio", "Apoio", "Apoio"]);
sume.getRange("A19:F21").format.borders = thin;
sume.getRange("B19:F21").format.fill = green;
sume.getRange("A23:I24").merge();
sume.getRange("A23").values = [["Sábado e domingo: folga geral. Não há pernoite em Sumé. Os ajudantes de apoio cobrem faltas, férias e picos de volume durante a semana."]];
sume.getRange("A23").format = { fill: yellow, font: { name: "Arial", size: 10, italic: true }, wrapText: true };
sume.freezePanes.freezeRows(10);
sume.getRange("A:A").format.columnWidth = 27;
sume.getRange("B:C").format.columnWidth = 33;
sume.getRange("D:D").format.columnWidth = 16;
sume.getRange("E:I").format.columnWidth = 14;
sume.getRange("A2:I24").format.font = { name: "Arial", size: 10 };

wb.recalculate();
const verification = await wb.inspect({ kind: "table", range: "Controle!A5:G11", include: "values,formulas", tableMaxRows: 10, tableMaxCols: 7 });
console.log(verification.ndjson);
const errors = await wb.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 100 }, summary: "formula errors" });
console.log(errors.ndjson);
const preview = await wb.render({ sheetName: "Escala", range: "A2:H68", scale: 1.2, format: "png" });
await fs.writeFile(`${outDir}/escala_preview.png`, new Uint8Array(await preview.arrayBuffer()));
const teamsPreview = await wb.render({ sheetName: "Equipes", range: "A2:F88", scale: 1.1, format: "png" });
await fs.writeFile(`${outDir}/equipes_preview.png`, new Uint8Array(await teamsPreview.arrayBuffer()));
const sumePreview = await wb.render({ sheetName: "Sumé", range: "A2:I24", scale: 1.2, format: "png" });
await fs.writeFile(`${outDir}/sume_preview.png`, new Uint8Array(await sumePreview.arrayBuffer()));
await fs.mkdir(outDir, { recursive: true });
const xlsx = await SpreadsheetFile.exportXlsx(wb);
await xlsx.save(outFile);
console.log(outFile);
