# Projetos Santo André

Acompanhamento diário das proposições da Câmara Municipal de Santo André (SP): projetos de lei, requerimentos, moções, emendas e vetos.

Site: https://welwelaraujo.github.io/projetos_santoandre/

## Como funciona

- `scripts/coletar.py` lê o portal [Câmara sem Papel](https://camarasempapel.cmsandre.sp.gov.br/) (consulta de produção por tipo e ano, 100 itens por página) e grava:
  - `docs/dados/proposicoes.json`: todas as proposições da legislatura, com temas atribuídos por palavras-chave;
  - `docs/dados/movimentacoes.json`: proposições novas e mudanças de situação/fase em relação à coleta anterior.
- `.github/workflows/coleta-diaria.yml` roda a coleta todo dia às 6h (Brasília), faz commit dos dados e publica `docs/` no GitHub Pages. Também dá para rodar à mão em *Actions → Coleta diária e publicação → Run workflow*.
- O site (`docs/`) é estático: `index.html` (hoje), `explorar.html` (busca), `vereadores.html` (ranking) e `sobre.html`.

## Rodar localmente

```
pip install requests
python scripts/coletar.py            # legislatura atual
python scripts/coletar.py --anos 2026
python -m http.server -d docs 8000
```

Os tipos coletados e as palavras-chave de cada tema ficam em `TIPOS` e `TEMAS`, no início de `scripts/coletar.py`.
