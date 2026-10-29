/* Funções comuns às páginas: carga dos dados, formatação e cartão de proposição. */
(function () {
  var CATEGORIAS = [
    { nome: 'Projetos de lei', cor: 'var(--c-pl)' },
    { nome: 'Requerimentos', cor: 'var(--c-req)' },
    { nome: 'Emendas e vetos', cor: 'var(--c-emv)' },
    { nome: 'Decretos e resoluções', cor: 'var(--c-dr)' },
    { nome: 'Moções', cor: 'var(--c-mo)' }
  ];
  var COR = {};
  CATEGORIAS.forEach(function (c) { COR[c.nome] = c.cor; });
  var MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
  var SIGLAS = ['SUS', 'UBS', 'TEA', 'CM', 'PL', 'PLC', 'GCM', 'SEMASA', 'SABESP', 'LOM', 'PSOL', 'PT', 'PL', 'MDB', 'PSDB', 'PSD', 'LDO', 'LOA', 'PPA', 'CPI', 'ABC', 'FUABC', 'SPDM', 'CROSS', 'BPM', 'PMSA', 'SP', 'UFABC', 'ONG', 'PCD', 'CEU', 'EMEIEF', 'EMEI', 'CRAS', 'CREAS', 'UPA', 'AME', 'LGBTQIA+', 'ISS', 'IPTU', 'ITBI', 'II', 'III', 'IV', 'VI', 'XVII'];
  var SIGLA_RE = new RegExp('\\b(' + SIGLAS.map(function (s) { return s.replace('+', '\\+'); }).join('|') + ')\\b', 'gi');

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; });
  }
  function int(n) { return Number(n).toLocaleString('pt-BR'); }
  function data(iso) { return iso ? iso.slice(8, 10) + '/' + iso.slice(5, 7) + '/' + iso.slice(0, 4) : ''; }
  function dataHora(iso) { return iso ? data(iso) + ' às ' + iso.slice(11, 16) : ''; }
  function diaISO(d) { return d.toISOString().slice(0, 10); }
  function semAcento(s) { return String(s).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase(); }

  // As ementas chegam em caixa alta; passa para caixa de frase mantendo siglas e "Santo André".
  var NOMES_PROPRIOS = ['São Paulo', 'Santo André', 'Brasil', 'Grande ABC', 'Paço Municipal', 'Guarda Civil Municipal', 'Plano Diretor', 'Lei Orgânica', 'Bolsa Família', 'Câmara Municipal', 'Câmara dos Deputados', 'Polícia Militar', 'Prefeito Municipal'];
  function frase(s, nomes) {
    var letras = s.replace(/[^A-Za-zÀ-ÿ]/g, '');
    if (!letras || letras.replace(/[^A-ZÀ-Þ]/g, '').length / letras.length < 0.7) return s;
    var t = s.toLowerCase().replace(/(^|[.!?:]\s+|["“(]\s*)([a-zà-ÿ])/g, function (m, a, b) { return a + b.toUpperCase(); });
    NOMES_PROPRIOS.concat(nomes || []).forEach(function (n) {
      t = t.replace(new RegExp('(^|[^\\wÀ-ÿ])' + n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(?![\\wÀ-ÿ])', 'gi'), function (m, a) { return a + n; });
    });
    return t.replace(SIGLA_RE, function (m) { return m.toUpperCase(); });
  }

  function linkCamara(p) {
    return 'https://camarasempapel.cmsandre.sp.gov.br/spl/processo.aspx?id=' + p.id + '&tipo=' + p.tipo_id + '&ano_proposicao=' + p.ano;
  }
  function naPauta(p) { return /ordem do dia|leitura e vota/i.test(p.fase) && p.situacao === 'Tramitando'; }
  function coletiva(p) { return p.autores.length > 5; }

  function autores(p) {
    if (!p.autores.length) return '';
    if (coletiva(p)) return 'Proposição coletiva <small>(' + p.autores.length + ' autores)</small>';
    return p.autores.map(function (a) {
      return '<a href="explorar.html?autor=' + a.ids + '">' + esc(a.nome) + '</a>';
    }).join(', ');
  }

  function situacao(p) {
    if (naPauta(p)) return '<span class="sit sit--pauta" title="' + esc(p.fase) + '">Aguarda plenário</span>';
    var cls = p.situacao === 'Tramitando' ? ' sit--tramitando' : '';
    return '<span class="sit' + cls + '">' + esc(p.situacao) + '</span>';
  }

  function cartao(p, opc) {
    opc = opc || {};
    var temas = (p.temas || []).map(function (t) {
      return '<a class="tema" href="explorar.html?tema=' + encodeURIComponent(t) + '">' + esc(t) + '</a>';
    }).join('');
    return '<article class="prop" style="--cor:' + COR[p.categoria] + '">' +
      '<div class="prop__topo"><span class="prop__tipo"><i></i>' + esc(p.tipo) + '</span>' +
      '<span class="prop__num">nº ' + p.numero + '/' + p.ano + '</span>' +
      (opc.semData ? '' : '<span>' + data(p.data) + '</span>') + situacao(p) + '</div>' +
      '<p class="prop__ementa">' + esc(frase(p.ementa, p.nomes)) + '</p>' +
      (p.resumo_ia ? '<p class="prop__resumo">' + esc(p.resumo_ia) + '</p>' : '') +
      (temas ? '<div class="temas">' + temas + '</div>' : '') +
      '<div class="prop__pe"><span class="prop__autor">' + autores(p) + '</span>' +
      (p.fase ? '<span class="prop__fase">Fase: ' + esc(p.fase) + '</span>' : '') +
      '<a class="prop__link" href="' + linkCamara(p) + '" target="_blank" rel="noopener">Ver na Câmara ↗</a></div>' +
      '</article>';
  }

  function carregar() {
    return Promise.all([
      fetch('dados/proposicoes.json', { cache: 'no-cache' }).then(function (r) { return r.json(); }),
      fetch('dados/movimentacoes.json', { cache: 'no-cache' }).then(function (r) { return r.ok ? r.json() : []; }).catch(function () { return []; })
    ]).then(function (res) {
      var D = res[0];
      D.porId = {};
      // Um vereador pode ter mais de um cadastro (ids diferentes, mesmo nome): agrupa pelo nome.
      var ids = {};
      D.proposicoes.forEach(function (p) {
        D.porId[p.id] = p;
        p.autores.forEach(function (a) { var k = semAcento(a.nome); (ids[k] = ids[k] || {})[a.id] = 1; });
      });
      D.proposicoes.forEach(function (p) {
        p.autores.forEach(function (a) { a.ids = Object.keys(ids[semAcento(a.nome)]).join(','); });
        // Nomes dos autores, sem o prefixo, para recuperar a caixa na ementa ("Vereador Ricardo Alvarez").
        p.nomes = p.autores.map(function (a) { return a.nome.replace(/^Ver\.\s*/i, '').replace(/^(Dr\.|Dra\.)\s*/i, ''); }).filter(function (n) { return n.length > 3; });
      });
      D.movimentacoes = res[1];
      document.querySelectorAll('[data-atualizado]').forEach(function (el) { el.textContent = dataHora(D.atualizado_em); });
      return D;
    });
  }

  function legenda() {
    return '<div class="legenda">' + CATEGORIAS.map(function (c) {
      return '<span><i style="background:' + c.cor + '"></i>' + c.nome + '</span>';
    }).join('') + '</div>';
  }

  // Dica flutuante para elementos com data-dica.
  var dica = document.createElement('div');
  dica.className = 'dica'; dica.hidden = true; dica.setAttribute('role', 'tooltip');
  document.addEventListener('DOMContentLoaded', function () { document.body.appendChild(dica); });
  document.addEventListener('mousemove', function (e) {
    var alvo = e.target.closest && e.target.closest('[data-dica]');
    if (!alvo) { dica.hidden = true; return; }
    dica.innerHTML = alvo.getAttribute('data-dica');
    dica.hidden = false;
    var x = Math.min(e.clientX + 14, window.innerWidth - dica.offsetWidth - 8);
    var y = e.clientY + 16 + dica.offsetHeight > window.innerHeight ? e.clientY - dica.offsetHeight - 12 : e.clientY + 16;
    dica.style.left = x + 'px'; dica.style.top = y + 'px';
  });

  window.APP = {
    CATEGORIAS: CATEGORIAS, COR: COR, MESES: MESES,
    esc: esc, int: int, data: data, dataHora: dataHora, diaISO: diaISO, semAcento: semAcento, frase: frase,
    naPauta: naPauta, coletiva: coletiva, cartao: cartao, carregar: carregar, legenda: legenda, linkCamara: linkCamara
  };
})();
