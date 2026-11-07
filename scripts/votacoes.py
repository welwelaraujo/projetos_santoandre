"""Votações nominais do plenário, lidas das atas taquigráficas das sessões ordinárias.

O Câmara sem Papel não publica voto por vereador (a página sessao-votacao.aspx vem sempre vazia).
Os votos estão nas atas taquigráficas, publicadas como PDF no portal de publicações da Câmara,
algumas semanas depois de cada sessão:

    [APROVADO POR VINTE E DOIS VOTOS FAVORÁVEIS: Nome Completo (Apelido), ...; UM VOTO CONTRÁRIO: ...;
     ausentes os vereadores ...; os vereadores ... não votaram]

Grava docs/dados/votacoes.json. Atas já lidas não são baixadas de novo.
"""
import json
import re
import sys

import fitz  # PyMuPDF
import requests

PORTAL = "http://www6.cmsandre.sp.gov.br:9002"
LISTA = PORTAL + "/atas-taquigraficas/?categoria=ORDINARIA&ano={ano}"
ATA = PORTAL + "/atas-taquigraficas/{id}"
ANO_INICIAL = 2025  # início da 19ª legislatura
LIDER = "Dr. Fabio Lopes"  # líder do governo na Câmara; o voto dele define a posição do governo

# Apelido usado nas atas -> nome usado no resto do site (presença, autores).
NOMES = {
    "Dr. Fábio Lopes": "Dr. Fabio Lopes", "Dr. Marcelo": "Dr. Marcelo Chehade",
    "Edilson Santos": "Edilson Santos do Torresmo", "Renatinho": "Renatinho Santiago",
    "Bahia do Parque": "Bahia", "Sargento Lôbo": "Sargento Lobo",
}

CABECALHO = re.compile(r"\d+ª Sessão (?:Ordinária|Extraordinária), da \dª Sessão Legislativa, da \d+ª Legislatura(?: \d{1,3}(?= ))?")
BLOCO = re.compile(r"\[([^\[\]]*?VOTOS? (?:FAVOR|CONTR)[^\[\]]*)\]")


def texto_da_ata(pdf):
    with fitz.open(stream=pdf, filetype="pdf") as doc:
        t = " ".join(pagina.get_text() for pagina in doc)
    t = re.sub(r"\s+", " ", t)
    return CABECALHO.sub(" ", t)


def apelidos(trecho):
    nomes = []
    for a in re.findall(r"\(([^()]{2,50})\)", trecho):
        if re.search(r"vereador|voto|painel|art\.|emenda|mapa", a, re.I):
            continue
        # quebra de página no meio do nome deixa espaços especiais e o número da página ("Dr. 13 Marcelo")
        a = re.sub(r"\b\d{1,3}\b", " ", a)
        a = " ".join(re.sub(r"[^\wÀ-ÿ.\-' ]", " ", a).split())
        nomes.append(NOMES.get(a, a))
    return nomes


def votos_da_ata(t):
    """Lista de votações nominais de uma ata (texto já normalizado)."""
    blocos = list(BLOCO.finditer(t))
    plenario = set()
    for m in blocos:
        plenario.update(apelidos(m.group(1)))
    resultado = []
    for m in blocos:
        corpo = m.group(1)
        cab = re.match(r"\s*(.*?)\s+POR\s", corpo)
        g = {"fav": [], "contra": [], "abst": [], "nao_votou": []}
        for parte in corpo.split(";"):
            p = parte.upper()
            if "NÃO VOTA" in p or "NÃO VOTOU" in p:
                chave = "nao_votou"
            elif "ABSTEN" in p:
                chave = "abst"
            elif re.search(r"VOTOS? FAVOR", p):
                chave = "fav"
            elif re.search(r"VOTOS? CONTR", p):
                chave = "contra"
            else:
                continue
            # "UM VOTO CONTRÁRIO: X; Y e Z não votaram" às vezes vem sem o ponto e vírgula
            trecho = re.split(r"(?i)(?=\b(?:e )?[^;:]*\bnão vot)", parte)[0] if chave != "nao_votou" else parte
            g[chave] += apelidos(trecho)
        completada = False
        # Unânime sem lista de nomes ("APROVADO POR VINTE E TRÊS VOTOS FAVORÁVEIS; ausentes ..."):
        # votaram a favor todos os que aparecem votando nesta sessão, menos os citados como ausentes.
        if not g["fav"] and not g["contra"] and re.search(r"VOTOS? FAVOR[ÁA]VE(?:IS|L)\s*(?:;|$)", corpo):
            g["fav"] = sorted(plenario - set(apelidos(corpo)))
            completada = True
        antes = t[max(0, m.start() - 6000):m.start()]
        partes = re.split(r"ITEM \d+º? ?-", antes)
        item = (partes[-1] if len(partes) > 1 else antes.split("]")[-1]).strip()
        proj = re.search(r"((?:Projeto|Veto|Emenda|Substitutivo|Requerimento|Moção)[^,]{0,90}?n[ºo°] ?[\d./]+)", item)
        autor = re.search(r"de autoria d[oa] (?:Vereador[a]? |Sr\.? )?([^,.;]{3,80})", item)
        ementa = re.search(r"\b(?:que|QUE) (.{10,260}?)(?:\. |$)", item)
        projeto = proj.group(1) if proj else ""
        autor_txt = autor.group(1).strip() if autor else ""
        resultado.append({
            "resultado": cab.group(1).strip() if cab else corpo[:40].strip(),
            "projeto": projeto,
            "autor": autor_txt,
            "ementa": ementa.group(1).strip() if ementa else item[:200],
            "prefeitura": autor_txt.upper().startswith("EXECUTIVO") or projeto.startswith("Veto"),
            "fav": g["fav"], "contra": g["contra"], "abst": g["abst"], "nao_votou": g["nao_votou"],
            "completada": completada,
        })
    for v in resultado:
        v["governo"] = "fav" if LIDER in v["fav"] else "contra" if LIDER in v["contra"] else None
    return resultado


def listar_atas(sessao, ano):
    h = sessao.get(LISTA.format(ano=ano), timeout=90).text
    achadas = re.findall(r"atas-taquigraficas/(\d+)'[^>]*>\s*([^<]+?)\s*</a>\s*</td>\s*<td data-order='(\d{8})'", h)
    return [{"id": int(i), "titulo": t, "data": f"{d[:4]}-{d[4:6]}-{d[6:]}",
             "sessao": int(re.match(r"(\d+)", t).group(1))} for i, t, d in achadas]


def atualizar(destino, agora):
    anterior = json.loads(destino.read_text(encoding="utf-8")) if destino.exists() else {"atas": []}
    lidas = {a["id"]: a for a in anterior["atas"]}
    sessao = requests.Session()
    atas = []
    for ano in range(ANO_INICIAL, int(agora[:4]) + 1):
        try:
            atas += listar_atas(sessao, ano)
        except requests.RequestException as erro:
            print(f"atas {ano}: {erro}", file=sys.stderr)
            atas += [a for a in anterior["atas"] if a["data"][:4] == str(ano)]
    resultado = []
    for a in sorted(atas, key=lambda a: (a["data"], a["sessao"])):
        if a["id"] in lidas:
            resultado.append(lidas[a["id"]])
            continue
        try:
            pdf = sessao.get(ATA.format(id=a["id"]), timeout=120).content
            a["votacoes"] = votos_da_ata(texto_da_ata(pdf))
        except Exception as erro:
            print(f"ata {a['id']}: {erro}", file=sys.stderr)
            continue
        resultado.append(a)
    destino.write_text(json.dumps({"atualizado_em": agora, "lider": LIDER, "fonte": LISTA.format(ano="").rstrip("="),
                                   "atas": resultado}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"votações: {len(resultado)} atas, {sum(len(a['votacoes']) for a in resultado)} votações nominais")


if __name__ == "__main__":
    from datetime import datetime
    from pathlib import Path
    atualizar(Path(__file__).resolve().parent.parent / "docs" / "dados" / "votacoes.json",
              datetime.now().isoformat(timespec="seconds"))
