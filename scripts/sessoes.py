"""Sessões plenárias da Câmara de Santo André: datas, pautas da Ordem do Dia, presença e vídeo.

Lê a primeira página de spl/sessoes.aspx (as ~10 sessões mais recentes, incluindo as já
agendadas), baixa os PDFs da Ordem do Dia (projetos e requerimentos), extrai os itens e os
classifica por tema, e grava docs/dados/sessoes.json. Chamado ao final de coletar.py.
"""
import html
import io
import json
import re

import fitz  # PyMuPDF

PORTAL = "https://camarasempapel.cmsandre.sp.gov.br/spl/"
CANAL = "https://www.youtube.com/@tvcamarasantoandre6841"
VERSAO = 3  # mude ao alterar a leitura das pautas, para reprocessar os PDFs já lidos

# Tipo citado na pauta -> ids de tipo no portal (para cruzar com proposicoes.json).
TIPOS_PAUTA = [
    (r"PROPOSTA DE EMENDA À LEI ORGÂNICA(?: DO MUNICÍPIO)?", "Emenda à Lei Orgânica", (168, 218)),
    (r"PROJETO DE LEI COMPLEMENTAR", "Projeto de Lei Complementar", (205,)),
    (r"PROJETO DE DECRETO LEGISLATIVO", "Projeto de Decreto Legislativo", (167,)),
    (r"PROJETO DE RESOLUÇÃO", "Projeto de Resolução", (163,)),
    (r"PROJETO DE LEI(?: CM| ORDINÁRIA)?", "Projeto de Lei", (161, 166)),
]
TIPOS_REQ = {
    "Requerimento": (151,), "Requerimento de Informações (art. 58)": (146,),
    "Requerimento - Abaixo Assinado": (152,), "Moção": (156,),
}


def limpar(texto):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", texto))).strip()


def listar(pagina):
    sessoes = []
    for bloco in pagina.split("<tr>")[1:]:
        cab = re.search(r"<strong>\s*([^<\d]+?)\s+N°\s*(\d+)\s*</strong>", bloco)
        quando = re.search(r"Data:\s*</strong>\s*(\d{2})/(\d{2})/(\d{4}).*?Horário\s*</strong>\s*(\d{2}:\d{2})", bloco, re.S)
        if not (cab and quando):
            continue
        d, m, a, hora = quando.groups()
        docs = [{"titulo": limpar(t), "url": u} for u, t in re.findall(r"<a target='_blank' href='([^']+)'[^>]*>(.*?)</a>", bloco, re.S)]
        ses_id = re.search(r"/SES/(\d+)/", bloco) or re.search(r"sessao-parlamentares\.aspx\?id=(\d+)", bloco)
        sessoes.append({
            "id": int(ses_id.group(1)) if ses_id else None,
            "tipo": limpar(cab.group(1)),
            "numero": int(cab.group(2)),
            "data": f"{a}-{m}-{d}",
            "hora": hora,
            "docs": docs,
            "tem_presenca": "sessao-parlamentares.aspx" in bloco,
        })
    return sessoes


def texto_pdf(conteudo):
    doc = fitz.open(stream=io.BytesIO(conteudo), filetype="pdf")
    linhas = []
    for pagina in doc:
        for linha in pagina.get_text().split("\n"):
            tokens = linha.split()
            # O cabeçalho das páginas sai com letras duplicadas ("O   R", "SE", "6666 ªªª"): descarta.
            # Linhas só com o número do item ("70.") ficam.
            if (tokens and all(len(t) <= 4 for t in tokens) and not re.search(r"[a-zà-ú]|\d+/\d+", linha)
                    and not re.fullmatch(r"\s*\d{1,3}\.\s*", linha)):
                continue
            linhas.append(linha)
    return "\n".join(linhas)


def itens_projetos(texto):
    """Itens numerados da Ordem do Dia de projetos ("1. PRIMEIRA discussão e votação do PROJETO...")."""
    itens = []
    # O item começa com "N. PRIMEIRA/SEGUNDA discussão..." ou "N. Discussão (ADIADA) e votação do VETO...".
    partes = re.split(r"\n\s*(\d{1,3})\.\s+(?=(?:PRIMEIRA|SEGUNDA|ÚNICA|Discuss|DISCUSS)[^\n]{0,40}(?:discuss|votaç|DISCUSS|VOTAÇ))", "\n" + texto)
    for i in range(1, len(partes) - 1, 2):
        corpo = re.sub(r"\s+", " ", partes[i + 1]).strip()
        corpo = corpo.split("PROCESSO N")[0]
        votacao = next((v for k, v in (("PRIMEIRA", "1ª votação"), ("SEGUNDA", "2ª votação"), ("ÚNICA", "votação única")) if k in corpo[:60].upper()), "votação")
        veto = re.search(r"VETO (TOTAL|PARCIAL)", corpo.upper())
        tipo, ids, numero, ano = "Proposição", (), None, None
        for rx, nome, tids in TIPOS_PAUTA:
            m = re.search(rx + r"\s*(?:N[º°.]*\s*)?(\d+)\s*/\s*(\d{2,4})", corpo.upper())
            if m:
                tipo, ids, numero, ano = nome, tids, int(m.group(1)), int(m.group(2))
                ano += 2000 if ano < 100 else 0
                break
        autor = re.search(r"de autoria d[oa] (?:Vereador[a]?|Ver\.)\s+([^,]+)|de autoria d[oa] (Prefeito Municipal|Executivo|Mesa)", corpo, re.I)
        resto = re.search(r"de autoria d[oa] [^,]+,\s*(?:que\s+)?(.*)", corpo, re.S)
        ementa = resto.group(1) if resto else corpo
        ementa = re.split(r"\s(?:As Comiss|A Comiss|PENDENTE|Apresentad[ao])", ementa)[0].strip(" .")
        itens.append({
            "ordem": int(partes[i]),
            "tipo": ("Veto " + veto.group(1).lower() + " ao " if veto else "") + tipo,
            "tipo_ids": list(ids), "numero": numero, "ano": ano,
            "votacao": votacao, "adiada": "ADIADA" in corpo[:60].upper(),
            "autor": (autor.group(1) or autor.group(2)).strip().title() if autor else "",
            "ementa": ementa[:400],
        })
    return itens


def itens_requerimentos(texto):
    itens = []
    for m in re.finditer(r"Ordem:\s*(\d+)\s*\n(.+?):\s*(\d+)/(\d{4}).*?\nAutoria:\s*(.+?)\nEmenta:\s*(.+?)\nFase:", texto, re.S):
        tipo = m.group(2).strip()
        itens.append({
            "ordem": int(m.group(1)), "tipo": tipo, "tipo_ids": list(TIPOS_REQ.get(tipo, ())),
            "numero": int(m.group(3)), "ano": int(m.group(4)), "votacao": "leitura e votação", "adiada": False,
            "autor": re.sub(r"^Ver\.\s*", "", m.group(5)).strip(), "ementa": re.sub(r"\s+", " ", m.group(6)).strip()[:400],
        })
    return itens


def presenca(sessao, ses_id):
    pagina = sessao.get(f"{PORTAL}sessao-parlamentares.aspx?id={ses_id}", timeout=90).text
    t = limpar(re.sub(r"<script.*?</script>|<style.*?</style>", "", pagina, flags=re.S))
    t = t[t.find("Horário"):t.find("Consultas", t.find("Horário"))]
    registros = []
    for m in re.finditer(r"(Ver\. .+?) (Presente|Falta Justificada|Falta|Ausente|Licen\w+)(?: Justificativa: (.+?))?(?= Ver\. |$)", t):
        registros.append({"nome": m.group(1).replace("Ver. ", ""), "situacao": m.group(2), "motivo": (m.group(3) or "").strip()})
    return {
        "presentes": sum(1 for r in registros if r["situacao"] == "Presente"),
        "total": len(registros),
        "ausentes": [r for r in registros if r["situacao"] != "Presente"],
    }


def videos(sessao):
    """{(número da sessão, 'AAAA-MM-DD'): id do vídeo} a partir da aba de transmissões do canal."""
    pagina = sessao.get(CANAL + "/streams", timeout=60, headers={"Accept-Language": "pt-BR"}).text
    meses = {m: i + 1 for i, m in enumerate(["JANEIRO", "FEVEREIRO", "MARÇO", "ABRIL", "MAIO", "JUNHO", "JULHO",
                                             "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO"])}
    achados = {}
    for bloco in pagina.split('"lockupViewModel":{')[1:]:
        vid = re.search(r'"contentId":"([\w-]{11})"', bloco)
        titulo = re.search(r'"title":\{"content":"(.*?)"', bloco)
        if not (vid and titulo):
            continue
        m = re.search(r"(\d+)ª SESSÃO (ORDINÁRIA|EXTRAORDINÁRIA).*?(\d{1,2}) DE ([A-ZÇ]+) DE (\d{4})", titulo.group(1).upper())
        if m and m.group(4) in meses:
            chave = f"{m.group(1)}|{m.group(5)}-{meses[m.group(4)]:02d}-{int(m.group(3)):02d}"
            achados[chave] = vid.group(1)
    return achados


def atualizar(sessao, proposicoes, temas, destino, agora):
    anterior = json.loads(destino.read_text(encoding="utf-8")) if destino.exists() else {"sessoes": []}
    antigas = {s["id"]: s for s in anterior.get("sessoes", [])}
    indice = {}
    for p in proposicoes:
        indice[(p["tipo_id"], p["numero"], p["ano"])] = p["id"]

    sessoes = listar(sessao.get(PORTAL + "sessoes.aspx", timeout=90).text)[:10]
    try:
        vids = videos(sessao)
    except Exception as erro:  # YouTube pode bloquear; mantém os vídeos já conhecidos.
        print(f"vídeos indisponíveis: {erro}")
        vids = {}

    for s in sessoes:
        velha = antigas.get(s["id"], {})
        assinatura = [VERSAO] + [d["url"] for d in s["docs"]]
        if velha.get("assinatura") == assinatura and velha.get("pauta"):
            s["pauta"] = velha["pauta"]
        else:
            itens = []
            for d in s["docs"]:
                titulo = d["titulo"].upper()
                if "ORDEM DO DIA" not in titulo:
                    continue
                try:
                    texto = texto_pdf(sessao.get(d["url"], timeout=120).content)
                except Exception as erro:
                    print(f"pauta {d['titulo']}: {erro}")
                    continue
                itens += itens_projetos(texto) if "PROJETO" in titulo else itens_requerimentos(texto)
            contagem = {}
            for item in itens:
                item["temas"] = temas(item["ementa"])
                for t in item["temas"]:
                    contagem[t] = contagem.get(t, 0) + 1
            s["pauta"] = {"itens": itens, "temas": dict(sorted(contagem.items(), key=lambda kv: -kv[1]))}
        s["assinatura"] = assinatura
        for item in s["pauta"]["itens"]:
            item["proposicao_id"] = next((indice[(t, item["numero"], item["ano"])] for t in item.get("tipo_ids", [])
                                          if (t, item["numero"], item["ano"]) in indice), None)
        s["video"] = vids.get(f"{s['numero']}|{s['data']}") or velha.get("video")
        if s["tem_presenca"] and s["id"]:
            try:
                s["presenca"] = presenca(sessao, s["id"])
            except Exception as erro:
                print(f"presença {s['id']}: {erro}")
                s["presenca"] = velha.get("presenca")

    destino.write_text(json.dumps({
        "atualizado_em": agora, "portal": PORTAL + "sessoes.aspx",
        "ao_vivo": CANAL + "/live", "canal": CANAL + "/streams", "sessoes": sessoes,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(sessoes)} sessões; próximas: {[s['data'] + ' ' + s['hora'] for s in sessoes if s['data'] >= agora[:10]]}")
