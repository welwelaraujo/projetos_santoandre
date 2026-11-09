// Formulário do abaixo-assinado (abaixo-assinado.html).
// Os envios vão para o Apps Script em apps-script/Code.gs, que grava cada
// formulário numa aba da planilha.

// URL do Apps Script (termina em /exec). Vazia = cadastro ainda não ativo.
var CADASTRO_ENDPOINT = 'https://script.google.com/macros/s/AKfycbxf61KpJf5faS8nPvdL_BqXoF3sM-JZwrawALcmyIdhhs5O9fidldGE3wUWKC45_Csb/exec';
// Precisa ser igual ao SUBMIT_TOKEN de apps-script/Code.gs.
var CADASTRO_TOKEN = 'abaixo-assinado-sa-4b8e21';

var RE_EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
var RE_FONE = /^\(?\d{2}\)?[\s-]?9?\d{4}[\s-]?\d{4}$/;
var REGRAS = {
  nome:     { ok: function (v) { return v.trim().length >= 3; }, erro: 'Informe seu nome completo.' },
  email:    { ok: function (v) { return RE_EMAIL.test(v.trim()); }, erro: 'Informe um e-mail válido.' },
  whatsapp: { ok: function (v) { return RE_FONE.test(v.trim()); }, erro: 'Informe um WhatsApp válido. Ex: (11) 99999-9999' },
  cep:      { ok: function (v) { return /^\d{5}-?\d{3}$/.test(v.trim()); }, erro: 'Informe um CEP válido. Ex: 09000-000' },
  rua:      { ok: function (v) { return v.trim().length >= 3; }, erro: 'Informe a rua.' },
  numero:   { ok: function (v) { return v.trim().length >= 1; }, erro: 'Informe o número (ou s/n).' },
  bairro:   { ok: function (v) { return v.trim().length >= 2; }, erro: 'Informe o bairro.' },
  cidade:   { ok: function (v) { return v.trim().length >= 2; }, erro: 'Informe a cidade.' },
  uf:       { ok: function (v) { return /^[A-Za-z]{2}$/.test(v.trim()); }, erro: 'UF com 2 letras.' },
};

// opcoes: { form, formulario (chave de FORMULARIOS no Code.gs), obrigatorios: [campos], extras: [campos opcionais], concluir() }
function iniciarCadastro(opcoes) {
  var form = opcoes.form;
  var msg = form.querySelector('.form__msg');
  var el = form.elements;

  function validar(input) {
    var ok = REGRAS[input.name].ok(input.value);
    input.closest('.form__group').querySelector('.form__erro').textContent = ok ? '' : REGRAS[input.name].erro;
    input.classList.toggle('is-erro', !ok);
    return ok;
  }

  opcoes.obrigatorios.forEach(function (nome) {
    el[nome].addEventListener('blur', function () { if (el[nome].value) validar(el[nome]); });
  });

  el.whatsapp.addEventListener('input', function (e) {
    var v = e.target.value.replace(/\D/g, '').slice(0, 11);
    if (v.length > 6) v = '(' + v.slice(0, 2) + ') ' + v.slice(2, 7) + '-' + v.slice(7);
    else if (v.length > 2) v = '(' + v.slice(0, 2) + ') ' + v.slice(2);
    else if (v.length > 0) v = '(' + v;
    e.target.value = v;
  });

  if (el.uf) el.uf.addEventListener('input', function (e) { e.target.value = e.target.value.replace(/[^A-Za-z]/g, '').toUpperCase(); });

  // Ao completar o CEP, preenche rua, bairro, cidade e UF pelo ViaCEP.
  if (el.cep) {
    var avisoCep = form.querySelector('.endereco__aviso');
    el.cep.addEventListener('input', function (e) {
      var v = e.target.value.replace(/\D/g, '').slice(0, 8);
      e.target.value = v.length > 5 ? v.slice(0, 5) + '-' + v.slice(5) : v;
      avisoCep.textContent = '';
      if (v.length !== 8) return;
      avisoCep.textContent = 'Buscando endereço…';
      fetch('https://viacep.com.br/ws/' + v + '/json/')
        .then(function (res) { return res.json(); })
        .then(function (r) {
          if (r.erro) { avisoCep.textContent = 'CEP não encontrado. Preencha o endereço abaixo.'; return; }
          avisoCep.textContent = '';
          [['rua', r.logradouro], ['bairro', r.bairro], ['cidade', r.localidade], ['uf', r.uf]].forEach(function (p) {
            if (p[1]) { el[p[0]].value = p[1]; validar(el[p[0]]); }
          });
          (el.rua.value ? el.numero : el.rua).focus();
        })
        .catch(function () { avisoCep.textContent = 'Não foi possível buscar o CEP. Preencha o endereço abaixo.'; });
    });
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var ok = true;
    opcoes.obrigatorios.forEach(function (nome) { if (!validar(el[nome])) ok = false; });
    var lgpd = el.lgpd.checked;
    form.querySelector('.lgpd + .form__erro').textContent = lgpd ? '' : 'Marque a autorização para continuar.';
    if (!ok || !lgpd) return;

    // Honeypot: só robôs preenchem o campo escondido.
    if (el.site.value) { opcoes.concluir(); return; }
    if (!CADASTRO_ENDPOINT) { msg.textContent = 'O cadastro ainda não está ativo. Tente de novo mais tarde.'; return; }

    var dados = { token: CADASTRO_TOKEN, formulario: opcoes.formulario, origem: document.referrer || 'direto' };
    opcoes.obrigatorios.concat(opcoes.extras || []).forEach(function (nome) { dados[nome] = el[nome].value.trim(); });

    var botao = form.querySelector('button[type="submit"]');
    botao.disabled = true;
    msg.textContent = 'Enviando…';

    // Sem Content-Type: vai como text/plain e o navegador não faz preflight (o Apps Script não responde a OPTIONS).
    fetch(CADASTRO_ENDPOINT, { method: 'POST', body: JSON.stringify(dados) })
      .then(function (res) { return res.json(); })
      .then(function (r) {
        if (r.ok) { opcoes.concluir(); return; }
        msg.textContent = 'Não foi possível enviar agora. Tente de novo em instantes.';
        botao.disabled = false;
      })
      .catch(function () {
        msg.textContent = 'Sem conexão com o servidor. Verifique sua internet e tente de novo.';
        botao.disabled = false;
      });
  });
}

