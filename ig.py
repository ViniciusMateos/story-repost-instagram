"""
Wrapper da instagrapi pro story-repost. Login por `sessionid` (reaproveita a sessão da conta
que o backend injetou em IG_SESSION_FILE — nada de senha), roteia pelo mesmo proxy socks5
(:1080) dos outros workers, pega os últimos posts da conta e posta no story:
  - REPOST_CARD=True  → post embutido como card (sticker de mídia) sobre fundo desfocado;
  - REPOST_CARD=False → a imagem do post em tela cheia (9:16).
Texto/link são stickers opcionais.
"""
import json
import logging
import os
import time
import urllib.request

import config
from safety import log

from instagrapi import Client
from instagrapi.types import StoryMedia, StoryLink

# a lib loga o traceback de erro que A GENTE já trata (ex: login_required num endpoint opcional)
# — vira lixo no log da run. Só os nossos logs importam.
logging.getLogger("instagrapi").setLevel(logging.CRITICAL)
logging.getLogger("public_request").setLevel(logging.CRITICAL)
logging.getLogger("private_request").setLevel(logging.CRITICAL)


_ALFA = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def _code_to_pk(code):
    """shortcode do IG → pk (base64 do IG). Fallback se a lib não resolver."""
    pk = 0
    for ch in str(code)[:11]:
        pk = pk * 64 + _ALFA.index(ch)
    return pk


def _sessionid(path):
    with open(path, encoding="utf-8") as f:
        for c in json.load(f):
            if c.get("name") == "sessionid" and c.get("value"):
                return c["value"]
    return None


class IG:
    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.cl = Client()
        self.cl.delay_range = [2, 5]        # respiro humano entre requests internos da lib
        self.uid = None
        self.username = None

    def __enter__(self):
        self.abrir()
        return self

    def __exit__(self, *a):
        return False

    def abrir(self):
        if config.PROXY and config.PROXY.get("server"):
            self.cl.set_proxy(config.PROXY["server"])
            log.info("Proxy ativo: %s", config.PROXY["server"])
        if not os.path.exists(config.SESSION_FILE):
            raise RuntimeError(f"SESSION_FILE não existe: {config.SESSION_FILE}")
        sid = _sessionid(config.SESSION_FILE)
        if not sid:
            raise RuntimeError("sem cookie sessionid no SESSION_FILE — a conta não está conectada")
        log.info("Abrindo sessão (login por sessionid, sem senha)…")
        self.cl.login_by_sessionid(sid)
        self.uid = str(self.cl.user_id)
        self.username = config.label_da_conta(self.uid)
        # "Conta: @x" é o que o backend lê pra marcar a conta da run no histórico
        log.info("Conta: @%s (id %s)", self.username, self.uid)

    def ultimos_posts(self, n):
        """Últimos posts da conta logada (mais recentes primeiro)."""
        return self.cl.user_medias(self.uid, amount=max(1, int(n)))

    # ─────────────────────── montagem do canvas 9:16 (Pillow) ───────────────────────
    def _baixar(self, media):
        url = ""
        if getattr(media, "resources", None):          # carrossel → 1ª mídia
            url = str(media.resources[0].thumbnail_url or "")
        if not url:
            url = str(media.thumbnail_url or "")
        os.makedirs(config.TMP_DIR, exist_ok=True)
        return str(self.cl.photo_download_by_url(url, folder=config.TMP_DIR))

    @staticmethod
    def _fonte(tam, peso=700):
        """Inter (assets/fonts, OFL) — a livre mais parecida com a fonte do app. Fallback DejaVu."""
        from PIL import ImageFont
        for f in (os.path.join(config.FONTS_DIR, f"Inter-{peso}.ttf"),
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
            try:
                return ImageFont.truetype(f, tam)
            except Exception:
                pass
        return ImageFont.load_default()

    @staticmethod
    def _linha_mao(d, cx, cy, texto, f, cor=(255, 255, 255)):
        """Uma linha de texto à mão centrada em (cx, cy), traço grosso igual a logo. As aspas da
        Walter Turncoat ficam baixas (quase no meio da letra), então são desenhadas à parte e
        SUBIDAS pra altura do topo das maiúsculas."""
        aspas = "“”\"'‘’"
        kw = {"fill": cor, "font": f, "stroke_width": 2, "stroke_fill": cor}
        x = cx - d.textlength(texto, font=f) / 2
        sobe = f.size * 0.22
        for ch in texto:
            d.text((x, cy - (sobe if ch in aspas else 0)), ch, anchor="lm", **kw)
            x += d.textlength(ch, font=f)

    @staticmethod
    def _fonte_mao(tam):
        """Walter Turncoat (assets/fonts, Apache 2.0) — letra à mão parecida com a da logo do brechó."""
        from PIL import ImageFont
        try:
            return ImageFont.truetype(os.path.join(config.FONTS_DIR, "WalterTurncoat.ttf"), tam)
        except Exception:
            return IG._fonte(tam)

    def _etiqueta(self, linhas):
        """Desenha o adesivo branco com as linhas que o etiqueta.py decidiu — (texto, tamanho da
        fonte, "destaque"|"neutra") — na letra da logo, já inclinado (RGBA)."""
        from PIL import Image, ImageDraw, ImageFilter
        cores = {"destaque": config.COR_BRECHO, "neutra": (60, 60, 60)}
        tmp = ImageDraw.Draw(Image.new("L", (1, 1)))
        itens = []
        for txt, tam, cor in linhas:
            f = self._fonte_mao(tam)
            itens.append((txt, f, cores.get(cor, cores["neutra"]), tmp.textbbox((0, 0), txt, font=f)))
        PX, PY, GAP = 38, 28, 14
        w = max(b[2] - b[0] for *_, b in itens) + 2 * PX
        h = sum(b[3] - b[1] for *_, b in itens) + GAP * (len(itens) - 1) + 2 * PY
        M = 40                                          # margem pra sombra + rotação
        im = Image.new("RGBA", (w + 2 * M, h + 2 * M), (0, 0, 0, 0))
        sh = Image.new("L", im.size, 0)
        ImageDraw.Draw(sh).rounded_rectangle([M, M + 8, M + w, M + h + 8], radius=30, fill=90)
        im.putalpha(sh.filter(ImageFilter.GaussianBlur(12)))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([M, M, M + w, M + h], radius=30, fill=(255, 255, 255, 255))
        y = M + PY
        for i, (txt, f, cor, b) in enumerate(itens):
            # posiciona pela "tinta" (bbox) — mesmo anchor do textbbox, senão o texto vaza do adesivo
            grosso = {"stroke_width": 1, "stroke_fill": cor + (255,)} if f.size >= 80 else {}   # o preço grande
            d.text((M + (w - (b[2] - b[0])) / 2 - b[0], y - b[1]), txt, fill=cor + (255,), font=f, **grosso)
            y += b[3] - b[1] + GAP
        return im.rotate(7, resample=Image.BICUBIC, expand=True)

    def _avatar(self, uid):
        """Foto de perfil REAL do autor do post (user_info_v1 passa via sessionid). Cache de 1 dia
        em output/avatar-<uid>.jpg pra não bater no IG todo story. None se não der."""
        if not uid:
            return None
        out = os.path.join(config.OUTPUT_DIR, f"avatar-{uid}.jpg")
        try:
            if os.path.exists(out) and time.time() - os.path.getmtime(out) < 86400:
                return out
            u = self.cl.user_info_v1(str(uid))
            url = str(u.profile_pic_url_hd or u.profile_pic_url or "")
            if url:
                tmp = os.path.join(config.TMP_DIR, "avatar.part")
                os.replace(self._baixar_url(url, tmp), out)
                return out
        except Exception as e:
            log.warning("  ~ sem foto de perfil de %s (%s)", uid, str(e)[:60])
        return out if os.path.exists(out) else None   # cache velho ainda serve

    def _montar(self, img_path, card, texto, autor, avatar=None, legenda="", etiqueta=None):
        """Monta o story 1080x1920 e devolve (caminho, geometria do card).

        IMPORTANTE: o card nativo do "compartilhar no story" é desenhado pelo APP do celular de quem
        compartilha — pela API, o IG só guarda o post anexado (área tocável), não desenha nada
        (testado 01/10: com dono + media_simple certinhos, o story sai só com o fundo). Então o card
        é desenhado aqui, copiando o do app (medido num print do original, 01/10): fundo = a própria
        foto bem desfocada; card branco quase reto (~74% da largura), cabeçalho com a foto de perfil
        real + @autor, a foto do post em largura total (no máx 4:5) e rodapé "**@autor** | legenda".
        A geometria volta relativa (x, y, w, h) pro post anexado casar em cima do card.
        ESTILO "vitrine" (padrão, pra captar cliente): o mesmo card de post (é ele que convida a
        tocar), mas sobre o laranja do brechó, com etiqueta de preço/tamanho na letra da logo e uma
        chamada pra ação embaixo (TEXTO substitui a padrão).
        card=False → a foto em tela cheia (sem sticker)."""
        from PIL import Image, ImageFilter, ImageDraw
        W, H = 1080, 1920
        src = Image.open(img_path).convert("RGB")

        def cover(im):
            r = max(W / im.width, H / im.height)
            nw, nh = int(im.width * r), int(im.height * r)
            im2 = im.resize((nw, nh))
            return im2.crop(((nw - W) // 2, (nh - H) // 2, (nw - W) // 2 + W, (nh - H) // 2 + H))

        geo = None
        vitrine = card and config.ESTILO == "vitrine"
        if vitrine:                                   # laranja do brechó com um brilho suave no meio
            base = Image.new("RGB", (W, H), config.COR_BRECHO)
            luz = Image.new("L", (W, H), 0)
            ImageDraw.Draw(luz).ellipse([-200, 300, W + 200, H - 300], fill=110)
            base = Image.composite(Image.new("RGB", (W, H), (255, 168, 110)), base,
                                   luz.filter(ImageFilter.GaussianBlur(220)))
        elif card:
            base = cover(src).filter(ImageFilter.GaussianBlur(60))
            base = Image.blend(base, Image.new("RGB", (W, H), (0, 0, 0)), 0.12)
        if card:
            CW = int(W * 0.74)                        # largura do card (as "bordas" ficam em volta)
            HEAD = 100                                # cabeçalho: foto de perfil + @
            FOOT = 96 if legenda else 0               # rodapé: "@autor | legenda"
            nat = int(src.height * CW / src.width)
            cap = int(CW * 4 / 3)                     # até 3:4 (o IG aceita 3:4; o brechó tem fotos 1800x2400)
            if nat > cap:                             # foto mais alta que 3:4: corta o excesso no meio
                keep = int(src.width * cap / CW)
                top = (src.height - keep) // 2
                src = src.crop((0, top, src.width, top + keep))
                nat = cap
            foto = src.resize((CW, nat), Image.LANCZOS)
            ch = HEAD + nat + FOOT
            x0, y0 = (W - CW) // 2, (H - ch) // 2
            if vitrine:                               # sobe um pouco: embaixo vai a chamada pra ação
                y0 = max(170, int(H * 0.45 - ch / 2))
            R = 12
            cartao = Image.new("RGB", (CW, ch), (255, 255, 255))
            cartao.paste(foto, (0, HEAD))
            d = ImageDraw.Draw(cartao)
            if legenda:                                # rodapé: @ em negrito + " | legenda" (corta com …)
                fb, fr = self._fonte(29, 600), self._fonte(29, 400)
                yb = HEAD + nat + FOOT / 2
                xt = 20
                d.text((xt, yb), autor or "", fill=(38, 38, 38), font=fb, anchor="lm")
                xt += d.textlength(autor or "", font=fb)
                resto, maxw = f" | {legenda}", CW - 20 - xt
                if d.textlength(resto, font=fr) > maxw:
                    while resto and d.textlength(resto + "…", font=fr) > maxw:
                        resto = resto[:-1]
                    resto = resto.rstrip() + "…"
                d.text((xt, yb), resto, fill=(38, 38, 38), font=fr, anchor="lm")
            AV, ax, ay = 64, 18, (HEAD - 64) // 2
            fav = None
            if avatar:
                try:
                    fav = Image.open(avatar).convert("RGB").resize((AV * 4, AV * 4), Image.LANCZOS)
                except Exception:
                    fav = None
            if fav:                                    # foto de perfil redonda (supersample = borda lisa)
                m = Image.new("L", (AV * 4, AV * 4), 0)
                ImageDraw.Draw(m).ellipse([0, 0, AV * 4 - 1, AV * 4 - 1], fill=255)
                cartao.paste(fav.resize((AV, AV), Image.LANCZOS), (ax, ay), m.resize((AV, AV), Image.LANCZOS))
            else:
                d.ellipse([ax, ay, ax + AV, ay + AV], fill=(219, 219, 219))
            d.text((ax + AV + 20, HEAD / 2), autor or "", fill=(38, 38, 38), font=self._fonte(30, 600), anchor="lm")
            S = 4                                      # máscara arredondada em supersample
            mask = Image.new("L", (CW * S, ch * S), 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, CW * S - 1, ch * S - 1], radius=R * S, fill=255)
            base.paste(cartao, (x0, y0), mask.resize((CW, ch), Image.LANCZOS))
            geo = (0.5, (y0 + ch / 2) / H, CW / W, ch / H)
            y_txt = min(H - 190, y0 + ch + 60)
            if vitrine:
                linhas = (etiqueta or []) if config.MOSTRAR_PRECO else []
                if linhas:                            # etiqueta "colada" no canto de cima à direita do card
                    tag = self._etiqueta(linhas)
                    cx, cy = x0 + CW - 60, y0 + 20
                    px = min(int(cx - tag.width / 2), W - tag.width + 10)   # nunca sai da tela
                    py = max(int(cy - tag.height / 2), 200)                # fora da barra de cima do story (progresso + @)
                    base.paste(tag, (px, py), tag)
                cta = (texto or config.CTA_PADRAO).upper()
                if cta:                               # chamada pra ação à mão, branca, no espaço de baixo
                    d = ImageDraw.Draw(base)
                    f = self._fonte_mao(68)
                    linhas, atual = [], ""            # quebra em linhas que caibam (letra grande > letra miúda)
                    for pal in cta.split():
                        tenta = f"{atual} {pal}".strip()
                        if atual and d.textlength(tenta, font=f) > W - 140:
                            linhas.append(atual)
                            atual = pal
                        else:
                            atual = tenta
                    linhas.append(atual)
                    yc = y0 + ch + (H - (y0 + ch)) * 0.42
                    alt = f.size + 18                 # altura de cada linha (fonte + espaçamento)
                    y_lin = yc - alt * (len(linhas) - 1) / 2
                    for lin in linhas:
                        self._linha_mao(d, W / 2, y_lin, lin, f)
                        y_lin += alt
                texto = ""                            # já usado como chamada; sem a caixa preta
        else:
            base = cover(src)
            y_txt = int(H * 0.80)
        if texto:
            d = ImageDraw.Draw(base)
            fonte = self._fonte(80)
            tw = d.textlength(texto, font=fonte)
            x = max(24, int((W - tw) // 2))
            d.rounded_rectangle([x - 30, y_txt - 22, x + tw + 30, y_txt + 112], radius=24, fill=(0, 0, 0))
            d.text((x, y_txt), texto, fill=(255, 255, 255), font=fonte)
        os.makedirs(config.TMP_DIR, exist_ok=True)
        out = os.path.join(config.TMP_DIR, "canvas.jpg")
        base.save(out, "JPEG", quality=92)
        return out, geo

    def postar_video(self, path):
        """Posta um VÍDEO pronto no story (o de abertura). Precisa do moviepy 2.x no venv (a
        instagrapi analisa duração/tamanho e gera a capa com ele)."""
        from pathlib import Path
        if self.dry_run:
            log.info("[dry] postaria o vídeo de abertura %s", os.path.basename(path))
            return "dry"
        st = self.cl.video_upload_to_story(Path(path))
        return str(getattr(st, "pk", "") or getattr(st, "id", "") or "ok")

    def postar(self, media, repost_card, texto, link):
        """Posta UM post (objeto Media da própria conta) no story. Devolve o id do story (ou 'dry')."""
        img = self._baixar(media)
        return self._publicar(int(media.pk), media.code, img, repost_card, texto, link,
                              self.username, self.uid, (media.caption_text or "").split("\n")[0])

    def media_pk(self, code):
        try:
            return int(self.cl.media_pk_from_code(code))
        except Exception:
            return _code_to_pk(code)

    def _baixar_url(self, url, out=None):
        """Baixa uma imagem direto da URL (CDN). Sem proxy — é arquivo público do CDN."""
        os.makedirs(config.TMP_DIR, exist_ok=True)
        out = out or os.path.join(config.TMP_DIR, "peca.jpg")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=30) as r, open(out, "wb") as f:
            f.write(r.read())
        return out

    def postar_code(self, code, repost_card, texto, link, img_url=None, autor=None, legenda="",
                    etiqueta=None):
        """Posta no story o post de QUALQUER conta pública pelo `code` (ex: peça do brechó, repostada
        por uma conta-vitrine). A foto é OBRIGATÓRIA (é ela que vira o card desenhado): tenta a que
        o brechó já tem da peça (`img_url`), depois a API do IG. Sem foto, não posta (story preto)."""
        pk = self.media_pk(code)
        img = None
        for u in ([img_url] if isinstance(img_url, str) else (img_url or [])):   # em ordem: post, depois a do app
            if not u or img:
                continue
            try:
                img = self._baixar_url(u)
            except Exception as e:
                log.warning("  ~ foto não baixou (%s) — tento a próxima", str(e)[:50])
        if not img:
            try:
                img = self._baixar(self.cl.media_info(pk))
            except Exception as e:
                log.warning("  ~ não peguei a imagem do post %s (%s)", code, str(e)[:60])
        if not img:
            raise RuntimeError("sem a foto da peça — não posto story vazio")
        return self._publicar(pk, code, img, repost_card, texto, link,
                              autor or config.BRECHO_IG, config.BRECHO_UID, legenda, etiqueta)

    def _publicar(self, pk, code, img, repost_card, texto, link, autor, autor_uid, legenda="",
                  etiqueta=None):
        avatar = self._avatar(autor_uid) if repost_card else None
        legenda = " ".join(str(legenda or "").split())    # 1ª linha só, igual o app
        canvas, geo = self._montar(img, bool(repost_card), texto, autor, avatar, legenda, etiqueta)
        if self.dry_run:
            log.info("[dry] postaria story (card=%s, texto=%r) do post %s → %s", repost_card, texto or "", code, canvas)
            return "dry"
        kwargs = {}
        if repost_card and geo:                        # post anexado (tocável) exatamente em cima do card desenhado
            x, y, w, h = geo                           # user_id = dono do post (sem ele o IG grava o anexo incompleto)
            kwargs["medias"] = [StoryMedia(media_pk=int(pk), user_id=str(autor_uid or ""),
                                           x=x, y=y, width=w, height=h)]
        if link:
            kwargs["links"] = [StoryLink(webUri=link)]
        try:
            st = self.cl.photo_upload_to_story(canvas, **kwargs)
        except Exception as e:
            if link:                                   # link exige elegibilidade — tenta sem
                log.warning("falhou com link (%s) — reenvio sem o link", str(e)[:80])
                kwargs.pop("links", None)
                st = self.cl.photo_upload_to_story(canvas, **kwargs)
            else:
                raise
        return str(getattr(st, "pk", "") or getattr(st, "id", "") or "ok")
