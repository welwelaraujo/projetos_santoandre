"""Coleta as indicações da Câmara (pedidos do vereador ao prefeito) e o que a Prefeitura respondeu.

Gera docs/dados/indicacoes.json, separado de proposicoes.json: as indicações não entram no Explorar.
A indicação não é votada: a Câmara manda um ofício ao prefeito e espera a resposta. A Prefeitura
responde em ofícios que juntam várias indicações; cada uma é citada pelo número do processo
("Proc. 9343/2025") e seguida do que foi feito. Este script lê esses PDFs e classifica o trecho.

Uso: python scripts/indicacoes.py [--anos 2025 2026]
"""
import argparse, io, json, re, sys, time, unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import requests
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coletar  # noqa: E402

TIPO = 153
coletar.TIPOS.setdefault(TIPO, ("Indicação", "Indicações"))
PORTAL = "https://camarasempapel.cmsandre.sp.gov.br"
CACHE = Path(__file__).resolve().parent / "cache_indicacoes.json"
SEM_RESPOSTA_AINDA = {"Protocolar Proposição", "Leitura e Encaminhamento", "Elaboração de Ofício", "Aguardar Resposta"}

# Abertura padrão das ementas: some da tela para sobrar o pedido em si.
ABERTURA = re.compile(
    r"^INDICA[ÇC][ÃA]O\s+AO\s+(EXCELENT[ÍI]SSIMO\s+)?(SENHOR\s+)?PREFEITO(\s+MUNICIPAL)?(\s+DE\s+SANTO\s+ANDR[ÉE])?[\s,]*"
    r"((PARA\s+QUE|SOLICITANDO|QUE)\s+)?((SOLICITE|DETERMINE|DETERMINAR|SEJAM?)\s+)?"
    r"((AO|À|A)\s+(DEPARTAMENTO|SECRETARIA|[ÓO]RG[ÃA]O)\s+(COMPETENTE|RESPONS[ÁA]VEL)[\s,]*)?", re.I)

# Classificação do trecho da resposta (texto sem acento, minúsculo, sem espaços: o PDF quebra palavras).
CLASSES = [
    ("atendida", r"(?<!nao)(foi|foram|jafoi|jaforam|estao|esta|encontrase|encontramse)(devidamente|prontamente|parcialmente)?(atendid|realizad|executad|concluid|efetuad|instalad|regularizad|removid|recolhid|implantad|reparad|substituid|sanad|podad|rocad|capinad|tapad|sinalizad|recapead|consertad|desobstruid|retirad|limp|pintad|trocad|vistoriadoseatendid)"),
    ("negada", r"naohaprevisao|naoexisteprevisao|inviav|naoserapossivel|naoepossivel|naohapossibilidade|naohaviabilidade|indeferid|naocompete|naoeatribuicao|naosejustific|naojustific|inexist\w{0,6}justificativa|naohamotivo|semmotivo|naoforamconstatad|naoforamencontrad|naoforamidentificad|naofoiconstatad|naofoiidentificad|responsabilidadesexclusiva|responsabilidadeexclusiva|deveraformalizar|deveraabrir|devendooproprio|naofoipossivel|naoconsta|naoatende|naopodeseratendid|naoseraatendid|naosendo|naoincluindo|demandaria|naoprevist|naoestaprevist|semprevisao|naohacomo|naoserealiza|naohanecessidade|naonecessita|desnecessari"),
    ("andamento", r"incluid|inserid|integrad|programac|cronograma|emandamento|sera(o)?(executad|realizad|atendid|providenciad|implantad|instalad|feit|encaminhad)|passara|emanalise|emestudo|analisad|agendad|previst|oportunamente|embreve|encaminhad|tramit|aguarda|priorizac"),
]
CLASSES_RE = [(c, re.compile(rx)) for c, rx in CLASSES]


def compacto(texto):
    t = unicodedata.normalize("NFKD", texto.lower())
    return re.sub(r"[^a-z0-9]", "", "".join(ch for ch in t if not unicodedata.combining(ch)))


def classificar(trecho):
    c = compacto(trecho)
    # "atendida" só vale quando não é negada ("não foi atendida")
    ach = {nome for nome, rx in CLASSES_RE if rx.search(c)}
    if "negada" in ach and not re.search(r"(foi|foram)(atendid|realizad|executad)", c):
        return "negada"
    for nome, _ in CLASSES:
        if nome in ach:
            return nome
    return "respondida"


def ler_pdf(conteudo):
    """{processo: trecho} de um ofício-resposta da Prefeitura."""
    texto = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(conteudo)).pages)
    texto = re.sub(r"Prefeitura Municipal de Santo Andr[ée]\s*Gabinete do Prefeito\s*(PCLEG n[º°] ?[\d.]+\s*)?(\d+\s*\n)?", " ", texto)
    texto = re.sub(r"\s+", " ", texto)
    partes = re.split(r"(?=Of[ií]cio n[º°o]\.? ?\d+ ?/ ?\d{4})", texto)
    saida, pendentes = {}, []
    for parte in partes[1:]:
        procs = re.findall(r"Proc(?:esso)?\.? ?n?[º°]? ?(\d+) ?/ ?(\d{4})", parte[:400])
        pendentes += [f"{n}/{a}" for n, a in procs[:1]]
        m = re.search(r"informa(mos|-se)?\s*:?", parte, re.I)
        if not m:
            continue
        trecho = parte[m.end():]
        trecho = re.split(r"Atenciosamente|Por fim,", trecho)[0].strip(" :;.-")
        for proc in pendentes:
            saida[proc] = trecho[:700]
        pendentes = []
    return saida


def chave(url):
    """O mesmo ofício aparece com ?identificador= diferentes: a chave é só o caminho."""
    return url.split("?", 1)[0]


def respostas_da_pagina(pagina):
    """[(data, url, nome)] dos documentos anexados nas etapas 'Resposta Recebida'."""
    corpo = pagina.split('id="ContentPlaceHolder1_tb_tramitacao"', 1)[-1].split("</tbody>", 1)[0]
    achados = []
    for bloco in re.split(r"<tr>\s*<td>\s*<table>", corpo)[1:]:
        if "Resposta Recebida" not in bloco:
            continue
        envio = re.search(r"<strong>\s*Envio:?\s*</strong>:?(.*?)</td>", bloco, re.S)
        receb = re.search(r"<strong>\s*Recebimento:?\s*</strong>:?(.*?)</td>", bloco, re.S)
        dt = re.search(r"(\d{2})/(\d{2})/(\d{4})", coletar.limpar((envio or receb).group(1)) if (envio or receb) else "")
        for href, nome in re.findall(r"<a [^>]*href='(/Arquivo/[^']*)'[^>]*>(.*?)</a>", bloco, re.S):
            achados.append((f"{dt.group(3)}-{dt.group(2)}-{dt.group(1)}" if dt else "", PORTAL + href, coletar.limpar(nome)))
    return achados


def main():
    hoje = datetime.now(coletar.BRT)
    ap = argparse.ArgumentParser()
    ap.add_argument("--anos", type=int, nargs="+", default=list(range(coletar.INICIO_LEGISLATURA, hoje.year + 1)))
    ap.add_argument("--sem-lista", action="store_true", help="reaproveita a lista do cache (retomar uma rodada interrompida)")
    args = ap.parse_args()

    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    for k in ("lista", "det", "pdf"):
        cache.setdefault(k, {})
    sessao = requests.Session()
    sessao.headers["User-Agent"] = "Mozilla/5.0 (projetos_santoandre; coleta diaria de dados publicos)"

    itens, falhas = {}, []
    if args.sem_lista and cache["lista"]:
        itens = {int(k): v for k, v in cache["lista"].items()}
        print(f"lista do cache: {len(itens)} indicações", flush=True)
    for ano in ([] if itens else args.anos):
        try:
            lista = coletar.coletar_tipo_ano(sessao, TIPO, ano)
        except requests.RequestException as erro:
            falhas.append(ano)
            print(f"falha indicações {ano}: {erro}", file=sys.stderr)
            continue
        print(f"Indicação {ano}: {len(lista)}", flush=True)
        for i in lista:
            itens[i["id"]] = i
    for p in cache["lista"].values():  # ano que falhou: mantém o que já se sabia
        if p["id"] not in itens and (p["ano"] in falhas or p["ano"] not in args.anos):
            itens[p["id"]] = p
    cache["lista"] = {str(k): v for k, v in itens.items()}
    if not itens:
        sys.exit("nenhuma indicação coletada; dados anteriores mantidos")

    # Página de detalhe só para quem já passou da espera, e só quando a fase mudou.
    detalhar = [i for i in itens.values() if i["fase"] not in SEM_RESPOSTA_AINDA
                and cache["det"].get(str(i["id"]), {}).get("fase") != i["fase"]]
    print(f"detalhes a buscar: {len(detalhar)}", flush=True)
    feitos, seguidas = [0], [0]

    def detalhe(i):
        if seguidas[0] >= 20:  # internet ou portal fora: para e deixa o resto para a próxima rodada
            return
        url = f"{coletar.BASE}processo.aspx?id={i['id']}&tipo={TIPO}&ano_proposicao={i['ano']}"
        try:
            resp = respostas_da_pagina(sessao.get(url, timeout=90).text)
        except requests.RequestException as erro:
            seguidas[0] += 1
            print(f"falha no detalhe {i['id']}: {erro}", file=sys.stderr)
            return
        seguidas[0] = 0
        cache["det"][str(i["id"])] = {"fase": i["fase"], "resp": resp}
        feitos[0] += 1
        if feitos[0] % 500 == 0:
            print(f"  {feitos[0]} detalhes", flush=True)
            CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(detalhe, detalhar))
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    if seguidas[0] >= 20:
        sys.exit("portal inacessível (20 falhas seguidas); o que já veio está no cache, rode de novo depois")

    # Ofícios-resposta: cada PDF é lido uma vez (um ofício cobre várias indicações).
    por_caminho = {}
    for d in cache["det"].values():
        for _, u, nome in d["resp"]:
            if "Resposta" in nome:
                por_caminho.setdefault(chave(u), u)
    urls = [u for k, u in sorted(por_caminho.items()) if k not in cache["pdf"]]
    print(f"ofícios a ler: {len(urls)}", flush=True)
    seguidas[0] = 0

    def pdf(u):
        if seguidas[0] >= 20:
            return
        try:
            r = sessao.get(u, timeout=120)
            cache["pdf"][chave(u)] = ler_pdf(r.content) if r.content[:4] == b"%PDF" else {}
            seguidas[0] = 0
        except requests.RequestException as erro:
            seguidas[0] += 1
            print(f"falha no ofício {u}: {erro}", file=sys.stderr)
        except Exception as erro:  # PDF ilegível: marca vazio para não insistir
            cache["pdf"][chave(u)] = {}
            print(f"ofício ilegível {u}: {erro}", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(pdf, urls))
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    if seguidas[0] >= 20:
        sys.exit("portal inacessível ao baixar os ofícios; o que já veio está no cache, rode de novo depois")

    hoje_d = hoje.date()
    saida, autores = [], {}
    for i in sorted(itens.values(), key=lambda i: (i["data"], i["id"]), reverse=True):
        for a in i["autores"]:
            autores[a["id"]] = coletar.nome_autor(a["nome"])
        det = cache["det"].get(str(i["id"]), {"resp": []})
        resp = [r for r in det["resp"] if "Resposta" in r[2]]
        trecho, oficio, data_resp = "", "", ""
        for dt, u, nome in resp:
            data_resp = data_resp or dt
            t = cache["pdf"].get(chave(u), {}).get(i["processo"])
            if t:
                trecho, oficio, data_resp = t, u, dt
        if trecho:
            status = classificar(trecho)
        elif resp:
            status, oficio = "respondida", resp[0][1]
        elif i["situacao"] == "Arquivado":
            status = "arquivada"
        else:
            status = "aguardando"
        ementa = ABERTURA.sub("", i["ementa"]).strip(" ,.;")
        dias = (hoje_d - datetime.fromisoformat(i["data"]).date()).days if i["data"] else None
        saida.append({
            "id": i["id"], "n": i["numero"], "a": i["ano"], "d": i["data"][:10], "e": ementa[:1].upper() + ementa[1:].lower(),
            "au": [a["id"] for a in i["autores"]], "pr": i["processo"], "s": status,
            "r": data_resp, "t": trecho, "o": oficio, "dias": dias,
        })
    coletar.gravar("indicacoes.json", {"atualizado_em": hoje.strftime("%Y-%m-%dT%H:%M:%S"), "autores": autores, "indicacoes": saida})
    from collections import Counter
    print(len(saida), "indicações", Counter(s["s"] for s in saida))


if __name__ == "__main__":
    main()
