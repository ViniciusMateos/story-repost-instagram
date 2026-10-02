"""
Config do story-repost. Diferente dos outros workers, este NÃO usa Playwright — usa a
`instagrapi` (API privada, HTTP puro), então é leve (sem Chromium). Lê a sessão do
IG_SESSION_FILE (a conta LOGADA, ex: o brechó), reaproveitando o cookie `sessionid`, e
roteia pelo MESMO proxy residencial (:1080) que os outros workers.
"""
import json
import os

_BASE = os.path.dirname(os.path.abspath(__file__))

# sessão da conta LOGADA (quem posta o story). O backend injeta IG_SESSION_FILE apontando pra
# sessions/<uid>.json da conta escolhida; fallback = session_cookies.json central (conta ativa).
SESSION_FILE = os.environ.get("IG_SESSION_FILE") or os.path.join(
    os.path.dirname(os.path.dirname(_BASE)), "session_cookies.json")


def _carregar_proxy():
    """Lê proxy.json do dir do worker (mesmo formato dos outros). Só o `server` importa aqui
    (instagrapi.set_proxy recebe a URL socks5). username/password embutidos na URL se houver."""
    f = os.path.join(_BASE, "proxy.json")
    try:
        if os.path.exists(f):
            d = json.load(open(f, encoding="utf-8"))
            if d.get("enabled") and d.get("server"):
                return {k: d[k] for k in ("server", "username", "password") if d.get(k)}
    except Exception:
        pass
    return None


PROXY = _carregar_proxy()

# ───────────────────── fonte das peças ─────────────
# "brecho"   = peças DISPONÍVEIS com DROP do app do brechó (o code do post IG fica salvo em cada
#              peça) — sorteia entre elas. É o padrão: as contas-vitrine repostam o estoque.
# "proprios" = os últimos posts da própria conta logada (modo antigo).
FONTE = "brecho"
BRECHO_API_URL = os.environ.get("BRECHO_API_URL", "")
BRECHO_API_TOKEN = os.environ.get("BRECHO_API_TOKEN", "")
BRECHO_IG = os.environ.get("BRECHO_IG", "brechoquasenadaa")   # @ do brechó (cabeçalho do card)
BRECHO_UID = os.environ.get("BRECHO_UID", "72013221906")      # user_id do brechó (dono dos posts + foto de perfil)
FONTS_DIR = os.path.join(_BASE, "assets", "fonts")

# ───────────────────── comportamento (sobrescrito pelo MODO via perfis.aplicar) ─────────────
# REPOST_CARD True  = reposta o post embutido como card (o "adicionar ao story" clássico, com as
#                     bordas em cima/embaixo);
#             False = posta a IMAGEM do post em tela cheia (9:16).
REPOST_CARD = True
# estilo do card: "vitrine"  = fundo laranja do brechó + etiqueta de preço/tamanho na letra da logo
#                              + chamada pra ação (TEXTO, se tiver, substitui a chamada padrão);
#                 "original" = cópia do card do Insta (fundo = foto desfocada, sem preço).
ESTILO = "vitrine"
MOSTRAR_PRECO = True
COR_BRECHO = (255, 130, 52)        # #FF8234
CTA_PADRAO = "comente “fila” para garantir a sua!"
# SELECAO (fonte brecho): "aleatorio" = sorteia entre TODAS as disponíveis (o último drop
#                          incluso), sem repetir até a conta postar todas (ciclo por conta);
#                          "drop_novo" = só as disponíveis do ÚLTIMO DROP POSTADO (ciclo próprio).
SELECAO = "aleatorio"
# vídeo de ABERTURA ("confiram as peças disponíveis no destaque") postado ANTES das peças.
# Ligado no modo aleatório; desligado no drop novo. Arquivo: assets/intro.mp4 (H.264 1080x1920).
VIDEO_INTRO = False
INTRO_PATH = os.path.join(_BASE, "assets", "intro.mp4")
QUANTOS_POSTS = 10         # stories por run (por conta, no lote)
TEXTO = ""                 # texto opcional sobreposto (ex: "NOVO DROP  -20%"); "" = sem texto
LINK = ""                  # link opcional (sticker de link); "" = sem link
DELAY_POST = (1, 7)        # segundos entre um story e o próximo
ACTIVE_HOURS = (9, 23)     # janela de horário (h). ini==fim = sem janela

# ───────────────────── paths de saída/estado ─────────────
OUTPUT_DIR = os.path.join(_BASE, "output")
LOG_FILE = os.path.join(OUTPUT_DIR, "run.log")
TMP_DIR = os.path.join(OUTPUT_DIR, "tmp")


def _ds_user_id_do_arquivo(path):
    try:
        with open(path, encoding="utf-8") as f:
            for c in json.load(f):
                if c.get("name") == "ds_user_id" and c.get("value"):
                    return str(c["value"])
    except Exception:
        pass
    return None


def conta_da_sessao():
    return _ds_user_id_do_arquivo(SESSION_FILE) or "conta"


def label_da_conta(uid):
    """@ da conta pelo índice local (sessions/accounts.json, ao lado do SESSION_FILE) — sem
    chamar o IG (o account_info dá login_required via sessionid)."""
    try:
        idx = os.path.join(os.path.dirname(SESSION_FILE), "accounts.json")
        for c in json.load(open(idx, encoding="utf-8")).get("contas", []):
            if str(c.get("id")) == str(uid) and c.get("label"):
                return c["label"]
    except Exception:
        pass
    return str(uid)


def state_file(conta):
    return os.path.join(OUTPUT_DIR, f"state-{conta}.json")
