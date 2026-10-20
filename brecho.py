"""
Fonte das peças = o app do BRECHÓ. O backend dele (server1) já guarda, em cada peça, o `code`
do post do IG. Então em vez de raspar o destaque "Disponíveis" do Instagram (que briga com o IG:
login_required na API mobile, flaky no web), a gente pergunta pro próprio brechó quais peças
estão DISPONÍVEIS (não vendidas) e têm DROP.

URL/token vêm do .env do server2 (BRECHO_API_URL / BRECHO_API_TOKEN). Não passa pelo proxy do
IG — é a nossa própria API.

Os posts do brechó (legendas) também são lidos — 1x a cada 12h, com cache — pra duas coisas:
  - ligar ao post a peça que não tem `code` (peça manual, ex: conjunto) pela tag `#p<num>`;
  - dar a DESCRIÇÃO de cada peça (a etiqueta de preço lê preços/tamanhos dela — ver etiqueta.py);
  - dar a FOTO do story = 1ª imagem do post (a do app pode ser a foto crua, na peça manual);
  - pular peça cujo post já diz "| ❌VENDIDO❌" na legenda (o app às vezes atrasa).
"""
import json
import os
import re
import time
import urllib.request

import config
import etiqueta
from safety import log

_POSTS_CACHE = os.path.join(config.OUTPUT_DIR, "posts_brecho.json")   # {"codes": {num: code}, "legendas": {code: texto}}
_POSTS_TTL = 12 * 3600


def todas_pecas(timeout=60):
    """Todas as peças do brechó (vendidas inclusive) — cru, como a API devolve."""
    if not config.BRECHO_API_URL or not config.BRECHO_API_TOKEN:
        raise RuntimeError("BRECHO_API_URL / BRECHO_API_TOKEN não configurados no .env do server")
    req = urllib.request.Request(config.BRECHO_API_URL.rstrip("/") + "/brecho/pecas",
                                 headers={"Authorization": f"Bearer {config.BRECHO_API_TOKEN}"})
    # opener sem proxy: é a nossa API, não o IG (não pode cair no socks do túnel)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8"))
    return (d.get("pecas") if isinstance(d, dict) else d) or []


def drop_da_peca(p):
    """(chave, data) do drop de uma peça, do MESMO jeito que o app do brechó monta os drops:
      - drop MANUAL (tabela drops): chave "m<id>", data = data do drop;
      - drop do HISTÓRICO: peça do scraper SEM drop manual, agrupada pela DATA DO POST →
        chave "h<postado_em>", data = postado_em.
    Peça manual sem drop (nunca postada) → (None, None)."""
    if p.get("drop_id"):
        return f"m{p['drop_id']}", str(p.get("drop_data") or "")
    if p.get("origem") == "scraper" and p.get("postado_em"):
        return f"h{p['postado_em']}", str(p["postado_em"])
    return None, None


def ultimo_drop(pz):
    """O último drop POSTADO (manual ou do histórico): entre os drops com peça já postada no IG
    (`postado_em`), o de data mais recente. Drop montado mas ainda não postado não conta.
    Devolve (chave, data) ou (None, None)."""
    melhor = None
    for p in pz:
        chave, data = drop_da_peca(p)
        if chave and p.get("postado_em"):
            k = (data, 1 if chave.startswith("m") else 0, chave)   # empate de data → manual ganha
            if melhor is None or k > melhor:
                melhor = k
    return (melhor[2], melhor[0]) if melhor else (None, None)


def pecas_disponiveis(pz=None, timeout=60):
    """Peças DISPONÍVEIS (não vendidas) que estão em algum drop — manual OU do histórico (as do
    scraper, agrupadas pela data do post; antes elas ficavam de fora e a conta dava ~37 em vez de
    ~78). Cada peça ganha `drop_chave`/`drop_data` e `imagem_url` absoluta (peça manual vem como
    "/uploads/…"). Peça SEM `code` continua — ligar_posts completa pela tag #p<num>."""
    if pz is None:
        pz = todas_pecas(timeout)
    base = config.BRECHO_API_URL.rstrip("/")
    out = []
    for p in pz:
        if p.get("vendida"):
            continue
        chave, data = drop_da_peca(p)
        if not chave:
            continue
        p = dict(p)
        p["drop_chave"], p["drop_data"] = chave, data
        u = p.get("imagem_url") or ""
        if u.startswith("/"):
            p["imagem_url"] = base + u
        out.append(p)
    log.info("Brechó: %d peças disponíveis em drops (%d de drop manual, %d do histórico; %d sem post ligado)",
             len(out), sum(1 for p in out if p["drop_chave"].startswith("m")),
             sum(1 for p in out if p["drop_chave"].startswith("h")), sum(1 for p in out if not p.get("code")))
    return out


_COMPLETO_MIN = 6 * 3600          # leitura COMPLETA só quando falta peça — no máx 1x a cada 6h
FOTOS_DIR = os.path.join(config.OUTPUT_DIR, "fotos")   # foto de cada post, salva 1x (o link do IG expira)
_RECENTES_QTD = 60                # leitura CURTA (a cada 12h): só os posts mais novos


def _posts_brecho(ig, codes_precisa=(), nums_precisa=()):
    """{codes, legendas, fotos} dos posts do brechó, com cache em output/posts_brecho.json.
    Leitura INCREMENTAL (o brechó tem centenas de posts e as peças do histórico são antigas):
      - COMPLETA (todos os posts, ~3 min): só sem cache ou quando falta alguma peça que a gente
        precisa (no máx 1x/6h). Não precisa renovar por causa do link de foto expirar: a foto de
        cada peça é salva no server na 1ª vez que posta (output/fotos/<code>.jpg);
      - CURTA (60 mais novos): a cada 12h — pega post novo e legenda editada ("VENDIDO")."""
    cache = {"codes": {}, "legendas": {}, "fotos": {}, "completo_em": 0, "lido_em": 0}
    try:
        c = json.load(open(_POSTS_CACHE, encoding="utf-8"))
        if isinstance(c, dict) and "fotos" in c:
            cache.update(c)
    except Exception:
        pass
    agora = time.time()
    faltam = ([c for c in codes_precisa if c and c not in cache["legendas"]]
              + [n for n in nums_precisa if str(n) not in cache["codes"]])
    if not cache["completo_em"] or (faltam and agora - cache["completo_em"] > _COMPLETO_MIN):
        qtd, completo = 0, True                         # 0 = todos os posts
    elif agora - cache["lido_em"] > _POSTS_TTL:
        qtd, completo = _RECENTES_QTD, False
    else:
        return cache
    try:
        if completo:
            log.info("Lendo TODOS os posts do brechó (%s peça(s) sem post no cache) — demora uns minutos…",
                     len(faltam) if cache["completo_em"] else "1ª leitura,")
        else:
            log.info("Lendo os %d posts mais novos do brechó (posts novos / legenda VENDIDO)…", qtd)
        lidos = 0
        for m in ig.cl.user_medias(config.BRECHO_UID, amount=qtd):
            lidos += 1
            texto = m.caption_text or ""
            cache["legendas"][m.code] = texto
            foto = ""                                   # 1ª imagem do post (carrossel → 1ª mídia), igual o feed
            if getattr(m, "resources", None):
                foto = str(m.resources[0].thumbnail_url or "")
            cache["fotos"][m.code] = foto or str(m.thumbnail_url or "")
            for n in re.findall(r"#p(\d+)\b", texto):
                cache["codes"].setdefault(n, m.code)
        cache["lido_em"] = agora
        log.info("  %d posts lidos.", lidos)
        if completo:
            cache["completo_em"] = agora
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)
        json.dump(cache, open(_POSTS_CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception as e:
        log.warning("  ~ não li os posts do brechó (%s) — sigo com o cache que tiver", str(e)[:60])
    return cache


def ligar_posts(pecas, ig):
    """Completa cada peça com o post (`code`, pela tag #p<num> quando falta) e a `descricao`
    (o texto manual do brechó, senão a legenda do post). Devolve só as peças que têm post."""
    posts = _posts_brecho(ig, [p.get("code") for p in pecas],
                          [p["num"] for p in pecas if not p.get("code") and p.get("num") is not None])
    out = []
    for p in pecas:
        if not p.get("code") and p.get("num") is not None:
            p["code"] = posts["codes"].get(str(p["num"]))
            if not p["code"]:
                log.info("  ~ %s (#p%s) sem post achado — fica de fora", rotulo(p), p["num"])
                continue
        if p.get("code"):
            legenda = posts["legendas"].get(p["code"]) or ""
            if etiqueta.post_vendido(legenda):         # a legenda já diz VENDIDO (o app tá atrasado)
                log.info("  ~ %s: o post já tá marcado VENDIDO na legenda — fica de fora", rotulo(p))
                continue
            p["descricao"] = p.get("template") or legenda
            # foto SEMPRE do post (a do app pode ser a crua, ex: peça manual); a do app é reserva
            p["imagem_reserva"] = p.get("imagem_url")
            p["imagem_url"] = posts["fotos"].get(p["code"]) or p.get("imagem_url")
            p["foto_local"] = os.path.join(FOTOS_DIR, f"{p['code']}.jpg")   # usada se já existir
            out.append(p)
    return out


def rotulo(p):
    """Nome curtinho da peça pro log/progresso."""
    for k in ("nome", "titulo", "descricao"):
        v = (p.get(k) or "").strip() if isinstance(p.get(k), str) else ""
        if v:
            return v[:40]
    return p.get("code") or "?"
