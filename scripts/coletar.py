"""Coleta as proposições da Câmara Municipal de Santo André (portal Câmara sem Papel / Ágape SPL).

Percorre a listagem "consulta-producao.aspx?tipo=X&ano_proposicao=Y" de cada tipo, 100 itens por
página (postback do ASP.NET), e grava docs/dados/proposicoes.json. Compara com a coleta anterior
para registrar proposições novas e mudanças de situação/fase em docs/dados/movimentacoes.json.

Uso: python scripts/coletar.py [--anos 2025 2026]
"""
import argparse
import html
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

BASE = "https://camarasempapel.cmsandre.sp.gov.br/spl/"
RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "docs" / "dados"
BRT = timezone(timedelta(hours=-3))
INICIO_LEGISLATURA = 2025

# id do tipo no portal -> (nome curto, categoria)
TIPOS = {
    161: ("Projeto de Lei", "Projetos de lei"),
    166: ("Projeto de Lei do Executivo", "Projetos de lei"),
    205: ("Projeto de Lei Complementar", "Projetos de lei"),
    164: ("Substitutivo", "Projetos de lei"),
    393: ("Substitutivo de Comissão", "Projetos de lei"),
    168: ("Emenda à Lei Orgânica", "Projetos de lei"),
    218: ("Emenda à Lei Orgânica do Executivo", "Projetos de lei"),
    167: ("Projeto de Decreto Legislativo", "Decretos e resoluções"),
    163: ("Projeto de Resolução", "Decretos e resoluções"),
    209: ("Emenda", "Emendas e vetos"),
    392: ("Emenda de Comissão", "Emendas e vetos"),
    162: ("Veto", "Emendas e vetos"),
    275: ("Razões do Veto", "Emendas e vetos"),
    156: ("Moção", "Moções"),
    151: ("Requerimento", "Requerimentos"),
    146: ("Requerimento de Informações", "Requerimentos"),
    159: ("Requerimento de Audiência Pública", "Requerimentos"),
    264: ("Audiência Pública LDO/LOA/PPA", "Requerimentos"),
    246: ("Requerimento de CPI", "Requerimentos"),
    158: ("Convocação de Secretário", "Requerimentos"),
    152: ("Abaixo-assinado", "Requerimentos"),
}

# Classificação automática por palavras-chave da ementa (uma proposição pode ter vários temas).
TEMAS = {
    "Homenagens e datas": r"DENOMINA|CALEND[AÁ]RIO|\bDIA (DO|DA|DE|MUNICIPAL)\b|SEMANA MUNICIPAL|T[IÍ]TULO DE CIDAD|CIDAD[AÃ]O ANDREENSE|APLAUSO|CONGRATULA|MEDALHA|HONRA|HOMENAG|PESAR|SESS[AÃ]O SOLENE|UTILIDADE P[UÚ]BLICA",
    "Saúde": r"SA[UÚ]DE|HOSPITA|\bUBS\b|M[EÉ]DIC|VACIN|\bSUS\b|DOEN[CÇ]A|C[AÂ]NCER|AUTIS|\bTEA\b|MEDICAMENT|ENFERM|FARM[AÁ]C|PSIC|DENGUE",
    "Educação": r"ESCOLA|EDUCA|ENSINO|ALUNO|CRECHE|ESTUDANT|PROFESSOR|BIBLIOTEC|DISLEXIA|AULAS?\b",
    "Mobilidade e trânsito": r"TR[AÂ]NSITO|[OÔ]NIBUS|TRANSPORTE|ESTACIONAMENTO|SEM[AÁ]FOR|CICLO|MOTO|VE[IÍ]CULO|MOBILIDADE|TAXI|T[AÁ]XI|SANTO ANDR[EÉ] TRANS|\bSA-?TRANS",
    "Segurança": r"GUARDA CIVIL|\bGCM\b|SEGURAN[CÇ]A|POL[IÍ]CI|VIOL[EÊ]NCIA|C[AÂ]MERAS?\b|MONITORAMENTO|CRIME|RONDAS?\b|PATRULH|BATALH[AÃ]O|\bBPM\b",
    "Meio ambiente e animais": r"AMBIENT|ANIMA|[AÁ]RVORE|\bPETS?\b|C[AÃ]ES|GATOS|RES[IÍ]DUO|LIXO|RECICL|ENCHENTE|CHUVA|SANEAMENTO|[AÁ]GUA|ESGOTO|SEMASA|[AÁ]REAS? VERDES?|ARBORIZA",
    "Assistência e direitos": r"DEFICI[EÊ]NCIA|\bPCD\b|IDOS|MULHER|CRIAN[CÇ]A|ADOLESCENT|VULNERAB|FAM[IÍ]LIA|SOCIAL|MORADOR(ES)? DE RUA|SITUA[CÇ][AÃ]O DE RUA|HABITA[CÇ]|MORADIA|NEGR|RACIAL|IDOSO|JUVENTUDE",
    "Economia e trabalho": r"EMPREG|TRABALH|EMPRES|COM[EÉ]RCIO|FEIRA|EMPREENDED|ENTREGADOR|AMBULANT|MEI\b|TURISMO",
    "Finanças e gestão pública": r"OR[CÇ]AMENT|TRIBUT|\bIPTU\b|\bISS\b|IMPOSTO|TAXA|CR[EÉ]DITO|\bLDO\b|\bLOA\b|\bPPA\b|SERVIDOR|CARGO|CONTRAT|LICITA|CONV[EÊ]NIO|FUABC|FUNDA[CÇ][AÃ]O DO ABC|REGIMENTO INTERNO|SAL[AÁ]RI|SUBS[IÍ]DIO|VENCIMENTO",
    "Urbanismo e zeladoria": r"OBRA|PAVIMENT|ILUMINA|PRA[CÇ]A|CAL[CÇ]ADA|ZONEAMENTO|URBAN|BURACO|TAPA|VIADUTO|PONTE|CONSTRU|IM[OÓ]VEL|LOTEAMENTO|ZELADORIA|LIMPEZA|POSTE|PLANO DIRETOR|ASFALT",
    "Cultura, esporte e lazer": r"CULTUR|ESPORT|LAZER|M[UÚ]SIC|TEATRO|FESTIVAL|EVENTO|ARTE|FUTEBOL|CARNAVAL",
    "Religião": r"IGREJA|EVANG|CAT[OÓ]LIC|RELIGI|GOSPEL|TEMPLO|CRIST|PAR[OÓ]QUIA",
}
TEMAS_RE = {nome: re.compile(r"\b(?:" + rx + ")") for nome, rx in TEMAS.items()}

PAGINACAO = "ctl00$ContentPlaceHolder1$ddl_ItensExibidos"
PROXIMA = "ctl00$ContentPlaceHolder1$lbNext"


def limpar(texto):
    texto = re.sub(r"<[^>]+>", " ", texto)
    return re.sub(r"\s+", " ", html.unescape(texto)).strip()


def campos_ocultos(pagina):
    return dict(re.findall(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"', pagina))


def nome_autor(nome):
    return re.sub(r"^VER\.", "Ver.", limpar(nome))


def temas(ementa):
    texto = ementa.upper()
    return [nome for nome, rx in TEMAS_RE.items() if rx.search(texto)]


def campo(bloco, rotulo):
    m = re.search(r"<span[^>]*>\s*" + re.escape(rotulo) + r"\s*</span>\s*<(?:a|span)[^>]*>(.*?)</(?:a|span)>", bloco, re.S)
    return limpar(m.group(1)) if m else ""


def ler_itens(pagina, tipo):
    itens = []
    for bloco in pagina.split('<div class="kt-widget5__item')[1:]:
        titulo = re.search(r'class="kt-widget5__title">(.*?)</a>', bloco, re.S)
        if not titulo:
            continue
        titulo = limpar(titulo.group(1))
        num = re.search(r"n[°º]\s*(\d+)/(\d{4})", titulo)
        ementa = re.search(r'class="kt-widget5__desc">(.*?)</a>', bloco, re.S)
        resumo = re.search(r'class="ai-summary-title">.*?</div>\s*<div>(.*?)</div>', bloco, re.S)
        autores = [
            {"id": int(a), "nome": nome_autor(n)}
            for a, n in re.findall(r"consulta-producao\.aspx\?autor=(\d+)'[^>]*>(.*?)</a>", bloco, re.S)
        ]
        data = campo(bloco, "Data:")
        try:
            data_iso = datetime.strptime(data, "%d/%m/%Y %H:%M:%S").strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            data_iso = ""
        itens.append({
            "id": int(campo(bloco, "ID:") or 0),
            "tipo_id": tipo,
            "tipo": TIPOS[tipo][0],
            "categoria": TIPOS[tipo][1],
            "numero": int(num.group(1)) if num else None,
            "ano": int(num.group(2)) if num else None,
            "titulo": titulo,
            "ementa": limpar(ementa.group(1)) if ementa else "",
            "resumo_ia": limpar(resumo.group(1)) if resumo else "",
            "processo": campo(bloco, "Processo N°:"),
            "protocolo": campo(bloco, "Protocolo N°:"),
            "data": data_iso,
            "situacao": campo(bloco, "Situação:"),
            "fase": campo(bloco, "Atividade Atual:"),
            "autores": autores,
        })
    return [i for i in itens if i["id"]]


def coletar_tipo_ano(sessao, tipo, ano):
    url = f"{BASE}consulta-producao.aspx?tipo={tipo}&ano_proposicao={ano}"
    pagina = sessao.get(url, timeout=90).text
    form = campos_ocultos(pagina)
    form.update({"__EVENTTARGET": PAGINACAO, "__EVENTARGUMENT": "", PAGINACAO: "100"})
    pagina = sessao.post(url, data=form, timeout=90).text
    itens, vistos = [], set()
    for _ in range(200):
        novos = [i for i in ler_itens(pagina, tipo) if i["id"] not in vistos]
        if not novos:
            break
        itens += novos
        vistos.update(i["id"] for i in novos)
        if f"__doPostBack(&#39;{PROXIMA}" not in pagina:
            break
        time.sleep(0.5)
        form = campos_ocultos(pagina)
        form.update({"__EVENTTARGET": PROXIMA, "__EVENTARGUMENT": "", PAGINACAO: "100"})
        pagina = sessao.post(url, data=form, timeout=90).text
    return itens


def carregar(nome, padrao):
    caminho = DADOS / nome
    return json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else padrao


def gravar(nome, conteudo):
    (DADOS / nome).write_text(json.dumps(conteudo, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main():
    hoje = datetime.now(BRT)
    ap = argparse.ArgumentParser()
    ap.add_argument("--anos", type=int, nargs="+", default=list(range(INICIO_LEGISLATURA, hoje.year + 1)))
    args = ap.parse_args()

    DADOS.mkdir(parents=True, exist_ok=True)
    anterior = {p["id"]: p for p in carregar("proposicoes.json", {"proposicoes": []})["proposicoes"]}
    movimentacoes = carregar("movimentacoes.json", [])
    primeira_coleta = not anterior

    sessao = requests.Session()
    sessao.headers["User-Agent"] = "Mozilla/5.0 (projetos_santoandre; coleta diaria de dados publicos)"

    atuais, falhas = {}, []
    for tipo in TIPOS:
        for ano in args.anos:
            try:
                itens = coletar_tipo_ano(sessao, tipo, ano)
            except requests.RequestException as erro:
                falhas.append((tipo, ano))
                print(f"falha tipo {tipo} ano {ano}: {erro}", file=sys.stderr)
                continue
            for item in itens:
                atuais[item["id"]] = item
            print(f"{TIPOS[tipo][0]} {ano}: {len(itens)}")

    # Se um tipo/ano falhou, mantém o que já se sabia dele em vez de apagar.
    for p in anterior.values():
        if p["id"] not in atuais and ((p["tipo_id"], p["ano"]) in falhas or p["ano"] not in args.anos):
            atuais[p["id"]] = p

    if not atuais:
        sys.exit("nenhuma proposição coletada; dados anteriores mantidos")

    agora = hoje.strftime("%Y-%m-%dT%H:%M:%S")
    for p in atuais.values():
        p["temas"] = temas(p["ementa"])
        for a in p["autores"]:
            a["nome"] = nome_autor(a["nome"])
        antigo = anterior.get(p["id"])
        p["visto_em"] = antigo.get("visto_em", agora) if antigo else (p["data"] or agora if primeira_coleta else agora)
        if antigo is None:
            if not primeira_coleta:
                movimentacoes.append({"quando": agora, "id": p["id"], "evento": "nova"})
        elif (antigo["situacao"], antigo["fase"]) != (p["situacao"], p["fase"]):
            movimentacoes.append({
                "quando": agora, "id": p["id"], "evento": "mudou",
                "de": {"situacao": antigo["situacao"], "fase": antigo["fase"]},
                "para": {"situacao": p["situacao"], "fase": p["fase"]},
            })

    proposicoes = sorted(atuais.values(), key=lambda p: (p["data"], p["id"]), reverse=True)
    gravar("proposicoes.json", {"atualizado_em": agora, "fonte": BASE, "proposicoes": proposicoes})
    gravar("movimentacoes.json", movimentacoes[-3000:])
    print(f"{len(proposicoes)} proposições; {len(falhas)} falhas")


if __name__ == "__main__":
    main()
