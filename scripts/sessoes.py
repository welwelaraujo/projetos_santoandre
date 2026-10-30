"""Sessões plenárias da Câmara de Santo André: datas, pautas da Ordem do Dia, presença e vídeo.

Lê a primeira página de spl/sessoes.aspx (as ~10 sessões mais recentes, incluindo as já
agendadas), baixa os PDFs da Ordem do Dia (projetos e requerimentos), extrai os itens e os
classifica por tema, e grava docs/dados/sessoes.json. Chamado ao final de coletar.py.
"""
import html
import io
import json
import re
from datetime import datetime, timedelta

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
    t = t[t.find("Horário"):t.find("Consultas", t.find("Horário"))].strip()
    registros = []
    for m in re.finditer(r"(Ver\. .+?) (Presente|Falta Justificada|Falta|Ausente|Licen\w+)(?: Justificativa: (.+?))?(?= Ver\. |$)", t):
        registros.append({"nome": m.group(1).replace("Ver. ", ""), "situacao": m.group(2), "motivo": (m.group(3) or "").strip()})
    return {
        "presentes": sum(1 for r in registros if r["situacao"] == "Presente"),
        "total": len(registros),
        "ausentes": [r for r in registros if r["situacao"] != "Presente"],
        "nomes": [r["nome"] for r in registros],
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


def todas_as_sessoes(sessao, desde="01/01/2025", ate="31/12/2099"):
    """Todas as sessões a partir de `desde`, paginando a lista (10 por página, postback do ASP.NET)."""
    url = PORTAL + "sessoes.aspx"
    pagina = sessao.get(url, timeout=90).text
    campos = dict(re.findall(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"', pagina))
    base = {"ctl00$ContentPlaceHolder1$txt_data_inicio": desde, "ctl00$ContentPlaceHolder1$txt_data_final": ate,
            "ctl00$ContentPlaceHolder1$ddl_tipo_sessao": "", "ctl00$ContentPlaceHolder1$ddl_sessao_arquivo_tipo": ""}
    pagina = sessao.post(url, data={**campos, **base, "__EVENTTARGET": "", "__EVENTARGUMENT": "",
                                    "ctl00$ContentPlaceHolder1$btn_buscar": "Buscar"}, timeout=90).text
    todas, vistas = [], set()
    for _ in range(100):
        novas = [s for s in listar(pagina) if (s["numero"], s["tipo"], s["data"], s["hora"]) not in vistas]
        if not novas:
            break
        todas += novas
        vistas.update((s["numero"], s["tipo"], s["data"], s["hora"]) for s in novas)
        if "lvSessoes_lbNext&#39;" not in pagina:
            break
        campos = dict(re.findall(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"', pagina))
        pagina = sessao.post(url, data={**campos, **base, "__EVENTTARGET": "ctl00$ContentPlaceHolder1$lvSessoes_lbNext",
                                        "__EVENTARGUMENT": ""}, timeout=90).text
    return todas


def historico_presenca(sessao, destino, agora):
    """Grava docs/dados/presencas.json com a presença de cada sessão desde 2025.

    Sessões com mais de 15 dias não são relidas (a lista de presença não muda depois de fechada).
    """
    anterior = json.loads(destino.read_text(encoding="utf-8")) if destino.exists() else {"sessoes": []}
    guardadas = {s["id"]: s for s in anterior["sessoes"]}
    limite = (datetime.fromisoformat(agora[:10]) - timedelta(days=15)).date().isoformat()
    resultado = []
    for s in todas_as_sessoes(sessao):
        if not (s["tem_presenca"] and s["id"]):
            continue
        velha = guardadas.get(s["id"])
        if velha and velha["data"] < limite:
            resultado.append(velha)
            continue
        try:
            p = presenca(sessao, s["id"])
        except Exception as erro:
            print(f"presença {s['id']}: {erro}")
            if velha:
                resultado.append(velha)
            continue
        if not p["total"]:
            continue
        faltas = {a["nome"]: a for a in p["ausentes"]}
        resultado.append({
            "id": s["id"], "numero": s["numero"], "tipo": s["tipo"], "data": s["data"], "hora": s["hora"],
            "presentes": p["presentes"], "total": p["total"], "nomes": p["nomes"],
            "faltas": [[n, faltas[n]["situacao"], faltas[n]["motivo"]] for n in p["nomes"] if n in faltas],
        })
    resultado.sort(key=lambda s: (s["data"], s["hora"]))
    destino.write_text(json.dumps({"atualizado_em": agora, "sessoes": resultado}, ensure_ascii=False, separators=(",", ":")),
                       encoding="utf-8")
    print(f"presença: {len(resultado)} sessões")


def resultado_da_etapa(acao):
    a = acao.upper()
    for padrao, codigo in (("VETO MANTIDO", "veto_mantido"), ("VETO REJEITADO", "veto_derrubado"), ("REJEITAD", "rejeitado"),
                           ("RETIRAD", "retirado"), ("APROVAD", "aprovado"), ("ADIAD", "adiado")):
        if padrao in a:
            return codigo
    return None


def resultados(sessao, passadas, todas, indice, extra, apoio, hoje):
    """Marca cada item das sessões já realizadas como votado (com o resultado) ou adiado.

    A Câmara registra na tramitação a ação de votação ("Proposição Aprovada"...) com data entre o
    dia da sessão e a sessão seguinte; quando o item é adiado nada é registrado e ele segue na fase
    da Ordem do Dia. Itens antigos (fora da legislatura coletada) têm o id buscado na listagem do ano.
    """
    from concurrent.futures import ThreadPoolExecutor

    def ident(item):
        for t in item.get("tipo_ids", []):
            chave = (t, item["numero"], item["ano"])
            if chave in indice:
                return indice[chave], t
            if f"{t}|{item['ano']}|{item['numero']}" in extra:
                return tuple(extra[f"{t}|{item['ano']}|{item['numero']}"])
        return None

    faltam = {(t, i["ano"]) for s in passadas for i in s["pauta"]["itens"] if i["numero"] and not ident(i)
              for t in i.get("tipo_ids", [])[:1] if i["ano"] < 2025}
    for tipo, ano in sorted(faltam):
        try:
            for p in apoio["listar"](sessao, tipo, ano):
                extra[f"{tipo}|{ano}|{p['numero']}"] = [p["id"], tipo]
        except Exception as erro:
            print(f"listagem {tipo}/{ano}: {erro}")

    alvos = {}
    for s in passadas:
        for item in s["pauta"]["itens"]:
            achado = ident(item)
            item["_ref"] = list(achado) if achado else None
            if achado:
                alvos[tuple(achado)] = None

    def tramitar(chave):
        pid, tipo = chave
        ano = next(i["ano"] for s in passadas for i in s["pauta"]["itens"] if i.get("_ref") == [pid, tipo])
        url = f"{apoio['base']}processo.aspx?id={pid}&tipo={tipo}&ano_proposicao={ano}"
        try:
            alvos[chave] = apoio["tramitacao"](sessao.get(url, timeout=90).text)
        except Exception as erro:
            print(f"tramitação {pid}: {erro}")

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(tramitar, list(alvos)))

    def data_iso(texto):
        m = re.search(r"(\d{2})/(\d{2})/(\d{4})", texto or "")
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""

    ordem = sorted(passadas, key=lambda s: (s["data"], s["hora"]))
    for n, s in enumerate(ordem):
        fim = next((o["data"] for o in ordem[n + 1:] if o["data"] > s["data"]), "9999")
        # Item pautado de manhã e de novo à tarde no mesmo dia: de manhã ficou para depois.
        tarde = {(i["tipo"], i["numero"], i["ano"]) for o in ordem[n + 1:] if o["data"] == s["data"] for i in o["pauta"]["itens"]}
        # Pautas publicadas depois desta sessão (inclusive as já agendadas), para a pista de reserva.
        depois = [o for o in todas if (o["data"], o["hora"]) > (s["data"], s["hora"]) and o.get("pauta")]
        for item in s["pauta"]["itens"]:
            ref = item.pop("_ref", None)
            etapas = alvos.get(tuple(ref)) if ref else None
            if etapas is None:
                # Sem tramitação online (projetos anteriores a 2019): se o item volta numa pauta seguinte,
                # foi adiado; se volta já em 2ª votação, foi aprovado em 1ª.
                volta = [i["votacao"] for o in depois for i in o["pauta"]["itens"]
                         if (i["tipo"], i["numero"], i["ano"]) == (item["tipo"], item["numero"], item["ano"])]
                if not volta:
                    item["resultado"] = {"codigo": "sem_info"}
                elif item["votacao"] == "1ª votação" and "2ª votação" in volta:
                    item["resultado"] = {"codigo": "aprovado"}
                else:
                    item["resultado"] = {"codigo": "adiado"}
                continue
            if (item["tipo"], item["numero"], item["ano"]) in tarde:
                item["resultado"] = {"codigo": "adiado"}
                continue
            voto = None
            for e in etapas:
                quando = data_iso(e["envio"]) or data_iso(e["recebimento"])
                if s["data"] <= quando < fim and re.search(r"ORDEM DO DIA|LEITURA E VOTA|VOTAÇÃO", e["fase"].upper()):
                    voto = resultado_da_etapa(e["acao"])
                    if voto:
                        break
            if voto:
                item["resultado"] = {"codigo": voto}
            elif hoje > s["data"]:
                item["resultado"] = {"codigo": "adiado"}
            else:
                item["resultado"] = {"codigo": "aguardando"}
        placar = {}
        for item in s["pauta"]["itens"]:
            grupo = "requerimentos" if re.search(r"Requerimento|Moção", item["tipo"]) else "projetos"
            c = item["resultado"]["codigo"]
            placar.setdefault(grupo, {})
            placar[grupo][c] = placar[grupo].get(c, 0) + 1
        s["placar"] = placar


def atualizar(sessao, proposicoes, temas, destino, agora, apoio=None):
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

    # Resultado (votado ou adiado) das 4 sessões ordinárias já realizadas mais recentes.
    extra = anterior.get("indice_antigos", {})
    if apoio:
        hoje = agora[:10]
        passadas = sorted([s for s in sessoes if s["data"] < hoje or (s["data"] == hoje and s["hora"] < agora[11:16])],
                          key=lambda s: (s["data"], s["hora"]))[-4:]
        try:
            resultados(sessao, passadas, sessoes, indice, extra, apoio, hoje)
        except Exception as erro:
            print(f"resultados das sessões: {erro}")

    destino.write_text(json.dumps({
        "atualizado_em": agora, "portal": PORTAL + "sessoes.aspx",
        "ao_vivo": CANAL + "/live", "canal": CANAL + "/streams", "sessoes": sessoes,
        "indice_antigos": extra,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(sessoes)} sessões; próximas: {[s['data'] + ' ' + s['hora'] for s in sessoes if s['data'] >= agora[:10]]}")
