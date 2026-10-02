"""
O que vai escrito na etiqueta de preço do story — separado do desenho (ig.py só renderiza).

Tudo passa por REGRAS, em ordem; a primeira que se aplica decide a etiqueta:
  1. várias ofertas na descrição  → preço do pacote (conjunto/kit/os dois…) em destaque + o avulso;
                                    parte marcada "VENDIDO" sai (e o pacote some, porque quebrou)
  2. peça simples                 → preço (+ "TAM X" se tiver tamanho)
  3. sem preço                    → sem etiqueta
Caso novo = uma regra nova na lista REGRAS, sem mexer no resto.

A descrição é lida de forma GENÉRICA (não depende da ordem nem do separador): linha a linha,
cada preço achado vira uma "oferta" com o nome e o tamanho mais próximos acima dele (ou o texto
na mesma linha, ex: "conjunto: R$ 50"). Oferta cujo nome tem palavra de pacote vira o total.
"""
import re

# ───────────────────────────── leitura da descrição ─────────────────────────────
_PRECO = re.compile(r"(?:R\$\s*:?\s*(\d+(?:[.,]\d{1,2})?))|(?:\b(\d+(?:[.,]\d{1,2})?)\s*reais\b)", re.I)
_TAM = re.compile(r"^\s*tam(?:anho)?\.?\s*:?\s*([^\s(,;]+)", re.I)
_TAM_INLINE = re.compile(r"\btam(?:anho)?\.?\s*:?\s*([^\s(,;]+)", re.I)
_SEPARADOR = re.compile(r"^\s*[—–\-_=*•.]{3,}\s*$")
_META = re.compile(r"^\s*(condi[çc][ãa]o|medidas?|largura|comprimento|cintura|busto|quadril|obs|"
                   r"comente|#|\.$|@)", re.I)
PACOTE = re.compile(r"\b(conjunto|kit|combo|pacote|look|tudo|todos|todas|juntos?|juntas?|"
                    r"(?:os|as)\s+(?:dois|duas|tr[êe]s|\d+))\b", re.I)


def _num(s):
    return float(s.replace(",", "."))


_VENDIDO = re.compile(r"vendid[oa]s?", re.I)


def post_vendido(texto):
    """O brechó marca o post inteiro como vendido no título da legenda: "| ❌VENDIDO❌"."""
    return any(l.strip().startswith("|") and _VENDIDO.search(l) for l in (texto or "").splitlines())


def ler_ofertas(texto):
    """Lista de ofertas achadas no texto: [{"rotulo", "tam", "preco", "pacote", "vendida"}, …].
    "vendida" = o bloco da oferta (entre separadores) tem "VENDIDO" escrito."""
    ofertas, rotulo, tam = [], None, None
    ini_bloco, bloco_vendido = 0, False
    for linha in (texto or "").splitlines():
        l = linha.strip()
        if not l or l.startswith("|"):                 # vazia / título "| nome da peça"
            continue
        if _SEPARADOR.match(l):                        # "—————" fecha o bloco
            rotulo, tam = None, None
            ini_bloco, bloco_vendido = len(ofertas), False
            continue
        if _VENDIDO.search(l):                         # "top ❌VENDIDO❌": marca o bloco todo
            bloco_vendido = True
            for o in ofertas[ini_bloco:]:
                o["vendida"] = True
            l = _VENDIDO.sub("", l).strip(" ❌✖️x-–—|:")
            if not l:
                continue
        mt = _TAM.match(l)
        if mt:
            tam = mt.group(1).strip(".:")
            continue
        mp = _PRECO.search(l)
        if mp:
            antes = l[:mp.start()].strip(" :-–—|·").strip()
            antes = re.sub(r"\b(por|a|de|só|apenas)$", "", antes, flags=re.I).strip(" :-–—")
            mi = _TAM_INLINE.search(antes)               # "body tam: p R$ 40" → nome "body", tam "p"
            if mi:
                tam = mi.group(1).strip(".:")
                antes = (antes[:mi.start()] + antes[mi.end():]).strip(" :-–—,")
            nome = antes if antes else rotulo
            ofertas.append({"rotulo": (nome or "").strip(), "tam": tam,
                            "preco": _num(mp.group(1) or mp.group(2)),
                            "pacote": bool(PACOTE.search(nome or "")), "vendida": bloco_vendido})
            rotulo, tam = None, None
            continue
        if _META.match(l):
            continue
        if PACOTE.search(l) or rotulo is None:         # 1ª linha "de nome" do bloco (ou palavra de pacote)
            rotulo = l
    return ofertas


# ───────────────────────────── formatação ─────────────────────────────
def preco_txt(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return ""
    if v <= 0:
        return ""
    return f"R$ {int(v)}" if v == int(v) else f"R$ {v:.2f}".replace(".", ",")


# cada linha da etiqueta = (texto, tamanho da fonte, cor) — cor "destaque" (laranja) ou "neutra" (cinza)
def _l(txt, tam, cor):
    return (txt, tam, cor)


# ───────────────────────────── regras ─────────────────────────────
def _nome_tam(o):
    return " ".join(x for x in (o["rotulo"].upper(), (o["tam"] or "").upper()) if x)


def _regra_varias_ofertas(peca, texto):
    ofertas = [o for o in ler_ofertas(texto) if o["preco"] > 0]
    if len(ofertas) < 2:
        return None
    pacotes = [o for o in ofertas if o["pacote"] and not o["vendida"]]
    avulsas = [o for o in ofertas if not o["pacote"] and not o["vendida"]]
    if any(o["vendida"] for o in ofertas if not o["pacote"]):
        pacotes = []                                    # vendeu uma parte → o pacote não existe mais
    if not pacotes and len(avulsas) == 1:               # sobrou uma peça só (ex: "SAIA M")
        o = avulsas[0]
        return [_l(preco_txt(o["preco"]), 92, "destaque")] + ([_l(_nome_tam(o), 40, "neutra")] if _nome_tam(o) else [])
    if not pacotes and not avulsas:
        return None
    linhas = []
    if pacotes:
        tot = pacotes[0]
        nome_pacote = PACOTE.search(tot["rotulo"]).group(0).upper()
        linhas += [_l(preco_txt(tot["preco"]), 92, "destaque"), _l(nome_pacote, 34, "neutra")]
        if not avulsas:
            return linhas
        if len({o["preco"] for o in avulsas}) == 1:     # todas iguais: compacto
            linhas.append(_l(f"OU {preco_txt(avulsas[0]['preco'])} CADA", 38, "destaque"))
            tams = [f"{o['rotulo'].upper()} {o['tam'].upper()}" for o in avulsas if o["tam"] and o["rotulo"]]
            if tams:
                linhas.append(_l(" · ".join(tams), 32, "neutra"))
            return linhas
        linhas.append(_l("OU AVULSO", 32, "neutra"))
    else:                                               # várias peças, sem pacote: "a partir de"
        linhas += [_l("A PARTIR DE", 32, "neutra"),
                   _l(preco_txt(min(o["preco"] for o in avulsas)), 92, "destaque")]
    for o in avulsas:                                   # preços diferentes: uma linha por peça
        nome = _nome_tam(o)
        linhas.append(_l(f"{nome} · {preco_txt(o['preco'])}" if nome else preco_txt(o["preco"]), 36, "destaque"))
    return linhas


def _regra_peca_simples(peca, texto):
    pt = preco_txt(peca.get("venda"))
    if not pt:                                          # sem preço no cadastro: tenta a descrição
        ofertas = ler_ofertas(texto)
        pt = preco_txt(ofertas[0]["preco"]) if len(ofertas) == 1 else ""
    if not pt:
        return None
    tam = peca.get("tamanho")
    return [_l(pt, 92, "destaque")] + ([_l(f"TAM {str(tam).upper()}", 40, "neutra")] if tam else [])


REGRAS = [_regra_varias_ofertas, _regra_peca_simples]


def linhas(peca, texto=""):
    """Linhas da etiqueta pra esta peça ([] = sem etiqueta). `texto` = descrição da peça
    (template manual do brechó ou a legenda do post)."""
    for regra in REGRAS:
        r = regra(peca, texto or "")
        if r:
            return r
    return []
