/**
 * Recebe as assinaturas de docs/abaixo-assinado.html e grava cada uma como
 * uma linha desta planilha, numa aba por formulário.
 *
 * COMO CONECTAR:
 *  1. Crie uma Planilha Google nova (sheets.new), por exemplo "Abaixo-assinado transparência".
 *  2. Menu Extensões > Apps Script. Apague o conteúdo e cole este arquivo.
 *  3. Implantar > Nova implantação > Tipo "App da Web".
 *       - Executar como: Eu
 *       - Quem pode acessar: Qualquer pessoa
 *  4. Autorize quando o Google pedir e copie a URL (termina em /exec).
 *  5. Cole a URL em docs/cadastro.js, na variável CADASTRO_ENDPOINT.
 *
 * Teste: abra a URL /exec no navegador. Deve responder {"ok":true,"status":"ativo"}.
 *
 * Ao editar este arquivo depois: Implantar > Gerenciar implantações > lápis >
 * Versão "Nova versão" > Implantar. A URL continua a mesma.
 */

// Aba e colunas de cada formulário. O e-mail fica sempre na coluna 3.
var FORMULARIOS = {
  'abaixo-assinado': {
    aba: 'Abaixo-assinado',
    campos: ['nome', 'email', 'whatsapp', 'cep', 'rua', 'numero', 'complemento', 'bairro', 'cidade', 'uf'],
    titulos: ['Nome', 'E-mail', 'WhatsApp', 'CEP', 'Rua', 'Número', 'Complemento', 'Bairro', 'Cidade', 'UF'],
  },
};

// Precisa ser igual a CADASTRO_TOKEN em docs/cadastro.js. Não é segredo (fica
// visível no site); serve só para recusar envios que não vieram da página.
var SUBMIT_TOKEN = 'abaixo-assinado-sa-4b8e21';

// ?total=abaixo-assinado devolve o número de assinaturas (sem repetidas) para o contador do site.
function doGet(e) {
  var f = FORMULARIOS[e && e.parameter && e.parameter.total];
  if (!f) return json_({ ok: true, status: 'ativo' });
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(f.aba);
  if (!sheet || sheet.getLastRow() < 2) return json_({ ok: true, total: 0 });
  var repetido = sheet.getRange(2, sheet.getLastColumn(), sheet.getLastRow() - 1, 1).getValues();
  var total = repetido.filter(function (l) { return l[0] !== 'sim'; }).length;
  return json_({ ok: true, total: total });
}

function doPost(e) {
  var lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    var p = JSON.parse(e.postData.contents);

    if (p.token !== SUBMIT_TOKEN) return json_({ ok: false, error: 'token' });
    var f = FORMULARIOS[p.formulario];
    if (!f) return json_({ ok: false, error: 'formulario' });
    if (!p.nome || !p.email || !p.whatsapp) return json_({ ok: false, error: 'dados incompletos' });

    var planilha = SpreadsheetApp.getActiveSpreadsheet();
    var sheet = planilha.getSheetByName(f.aba) || planilha.insertSheet(f.aba);
    if (sheet.getLastRow() === 0) {
      var headers = ['Data/Hora'].concat(f.titulos, ['Origem', 'Cadastro repetido']);
      sheet.appendRow(headers);
      sheet.getRange(1, 1, 1, headers.length).setFontWeight('bold');
      sheet.setFrozenRows(1);
    }

    var email = limpar_(p.email).toLowerCase();
    var agora = Utilities.formatDate(new Date(), 'America/Sao_Paulo', 'dd/MM/yyyy HH:mm:ss');
    var valores = f.campos.map(function (c) { return c === 'email' ? email : limpar_(p[c]); });

    sheet.appendRow([agora].concat(valores, [limpar_(p.origem), jaCadastrado_(sheet, email) ? 'sim' : '']));
    return json_({ ok: true });

  } catch (err) {
    return json_({ ok: false, error: String(err) });
  } finally {
    lock.releaseLock();
  }
}

// Corta o tamanho e evita que um valor começando com = vire fórmula na planilha.
function limpar_(v) {
  var s = (v || '').toString().trim().slice(0, 200);
  return /^[=+\-@]/.test(s) ? "'" + s : s;
}

function jaCadastrado_(sheet, email) {
  var ultima = sheet.getLastRow();
  if (ultima < 2) return false;
  var emails = sheet.getRange(2, 3, ultima - 1, 1).getValues();
  for (var i = 0; i < emails.length; i++) {
    if (String(emails[i][0]).toLowerCase() === email) return true;
  }
  return false;
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
