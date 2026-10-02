"""
Modos (perfis) do story-repost. Persiste em perfis.json; DEFAULTS aqui (clone novo já
funciona). O backend semeia na 1ª leitura (bots.ler_modos), então aparecem no app.
"""
import copy
import json
import os

_BASE = os.path.dirname(os.path.abspath(__file__))
PERFIS_FILE = os.path.join(_BASE, "perfis.json")

PERFIL_PADRAO = {
    "fonte": "brecho",       # "brecho" = peças disponíveis c/ drop do app do brechó; "proprios" = posts da conta
    "selecao": "aleatorio",  # "aleatorio" = todas as disponíveis; "drop_novo" = só as do último drop postado
    "video_intro": False,    # posta o vídeo "confiram as peças no destaque" ANTES das peças
    "repost_card": True,     # True = reposta o post como card; False = posta a imagem em tela cheia
    "estilo": "vitrine",     # card: "vitrine" = fundo laranja + etiqueta de preço; "original" = igual o do Insta
    "mostrar_preco": True,   # vitrine: etiqueta com o valor (e tamanho) da peça
    "quantos_posts": 10,     # stories por run (por conta, no lote)
    "texto": "",             # chamada embaixo do card ("" = "comente “fila” para garantir a sua!")
    "link": "",              # link opcional (sticker de link)
    "delay_post": [1, 7],    # segundos entre um story e o próximo
    "active_hours": [9, 23], # janela de horário (ini==fim = sem janela)
}

_MODOS_BUILTIN = {
    "aleatório": {           # ⭐ padrão: sorteia entre TODAS as disponíveis, sem repetir até postar todas
        "selecao": "aleatorio",
        "video_intro": True,     # abre com o vídeo "confiram as peças disponíveis no destaque"
    },
    "drop novo": {           # só as disponíveis do último drop postado
        "selecao": "drop_novo",
    },
}

_MAP_CONFIG = {
    "fonte": "FONTE", "selecao": "SELECAO", "video_intro": "VIDEO_INTRO", "repost_card": "REPOST_CARD", "estilo": "ESTILO",
    "mostrar_preco": "MOSTRAR_PRECO", "quantos_posts": "QUANTOS_POSTS", "texto": "TEXTO",
    "link": "LINK", "delay_post": "DELAY_POST", "active_hours": "ACTIVE_HOURS",
}


def _default_perfis():
    out = {}
    for nome, override in _MODOS_BUILTIN.items():
        p = copy.deepcopy(PERFIL_PADRAO)
        p.update(override)
        out[nome] = p
    return out


def carregar_perfis():
    if os.path.exists(PERFIS_FILE):
        try:
            with open(PERFIS_FILE, encoding="utf-8") as f:
                d = json.load(f)
            for nome, p in list(d.items()):
                base = copy.deepcopy(PERFIL_PADRAO)
                base.update(p)
                d[nome] = base
            return d
        except Exception:
            pass
    d = _default_perfis()
    salvar_perfis(d)
    return d


def salvar_perfis(d):
    with open(PERFIS_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def get_perfil(nome):
    return carregar_perfis().get(nome)


def salvar_perfil(nome, valores):
    perfis = carregar_perfis()
    base = copy.deepcopy(PERFIL_PADRAO)
    base.update(valores or {})
    perfis[nome] = base
    salvar_perfis(perfis)
    return base


def aplicar(config, perfil):
    for campo, attr in _MAP_CONFIG.items():
        if campo in perfil:
            v = perfil[campo]
            if isinstance(v, list) and len(v) == 2:
                v = tuple(v)
            setattr(config, attr, v)
