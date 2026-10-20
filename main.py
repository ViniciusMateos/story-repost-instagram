"""
story-repost — reposta peças DISPONÍVEIS do brechó no story das contas-vitrine (via instagrapi).

Uma run = uma conta (a ativa / a escolhida) OU um LOTE (várias contas, uma de cada vez — o
backend passa a lista em IG_LOTE_CONTAS, igual o like-repost). Em cada conta:
  1. LIMPA: apaga os stories que ESTE bot postou nessa conta (< 24h) cuja peça vendeu;
  2. ESCOLHE até QUANTOS_POSTS peças conforme a SELECAO do modo:
       "aleatorio" → entre todas as disponíveis; "drop_novo" → só as do último drop postado;
     sorteadas, sem repetir peça até a conta postar todas do ciclo (o ciclo é por conta e por
     seleção — drop novo entrando no meio só soma peças novas, nada quebra);
  3. POSTA com DELAY_POST entre um story e outro e marca no ciclo.
O brechó (peças + posts) é lido UMA vez por run, mesmo no lote.
"""
import argparse
import json
import os
import random
import sys
import time
import traceback

import config
import perfis
from safety import log, Guard, State, LimiteAtingido


def progresso(done, total, label=""):
    print(f"[progress] {done} {total} {label}".rstrip(), flush=True)


def _fatal(e):
    """Erro que NÃO dá pra pular peça a peça (sessão caiu/barrada, checkpoint, bloqueio de ação).
    A lib às vezes embrulha (ex: PhotoNotUpload com 'login_required' no texto) → olha a mensagem."""
    n = type(e).__name__.lower()
    m = str(e).lower()
    return (any(t in n for t in ("loginrequired", "challenge", "feedback", "pleasewait", "ratelimit"))
            or any(t in m for t in ("login_required", "challenge_required", "checkpoint", "feedback_required")))


class ContaBarrada(Exception):
    """A conta não consegue postar story pela API (sessão barrada/caída) — pula pra próxima."""


# ───────────────────────────── brechó (1x por run) ─────────────────────────────
_CTX = {}


def _contexto_brecho(ig):
    """Peças disponíveis já ligadas ao post (foto/descrição) + o último drop. Cacheado na run."""
    if _CTX:
        return _CTX
    import brecho
    todas = brecho.todas_pecas()
    disp = brecho.ligar_posts(brecho.pecas_disponiveis(todas), ig)
    drop_chave, drop_data = brecho.ultimo_drop(todas)
    _CTX.update({"disp": disp, "drop_chave": drop_chave, "drop_data": drop_data,
                 "codes": {p["code"] for p in disp}})
    log.info("Último drop postado: %s (%s) — %d disponíveis nele", drop_chave, drop_data,
             sum(1 for p in disp if p.get("drop_chave") == drop_chave))
    return _CTX


def _selecionar(ctx, st, quantos):
    """Devolve (ciclo, peças a postar). Sorteia entre as do pool que a conta ainda não postou
    neste ciclo; se faltar pra completar `quantos`, fecha o ciclo e completa com o resto."""
    if config.SELECAO == "drop_novo":
        ciclo = f"drop:{ctx['drop_chave']}"
        pool = [p for p in ctx["disp"] if p.get("drop_chave") == ctx["drop_chave"]]
    else:
        ciclo = "aleatorio"
        pool = list(ctx["disp"])
    random.shuffle(pool)
    novas = [p for p in pool if not st.ja_fez(p["code"], ciclo)]
    alvos = novas[:quantos]
    if len(alvos) < quantos and len(pool) > len(alvos):
        log.info("Ciclo '%s' completo nesta conta (postou todas as %d) — recomeçando.", ciclo, len(pool))
        st.zerar(ciclo)
        ja = {p["code"] for p in alvos}
        alvos += [p for p in pool if p["code"] not in ja][:quantos - len(alvos)]
    return ciclo, alvos


def _limpar_vendidas(ig, st, ctx, dry):
    """Apaga os stories (< 24h) que este bot postou nesta conta cuja peça não está mais
    disponível (vendeu, ou o post virou VENDIDO). Devolve quantos apagou."""
    apagados = 0
    for s in st.stories_no_ar(24):
        if s["code"] in ctx["codes"]:
            continue
        if dry:
            log.info("  [dry] apagaria o story %s (peça %s vendeu)", s["pk"], s["code"])
            continue
        try:
            ig.cl.story_delete(int(s["pk"]))
            apagados += 1
            log.info("  ✂ apaguei o story da peça %s (vendeu)", s["code"])
        except Exception as e:
            log.warning("  ~ não apaguei o story %s (%s)", s["pk"], str(e)[:60])
        st.esquecer_story(s["pk"])
    return apagados


def run_conta(dry, rotulo="", ignorar_janela=False):
    """Roda UMA conta (a do config.SESSION_FILE atual). Devolve o saldo dela."""
    from ig import IG
    import brecho
    import etiqueta
    guard = Guard(dry_run=dry)
    guard.checar_janela(ignorar=ignorar_janela)
    st = State(config.state_file(config.conta_da_sessao()))
    st.podar()
    quantos = max(1, int(config.QUANTOS_POSTS))
    saldo = {"postados": 0, "apagados": 0, "falhas": 0}
    pre = (rotulo + " · ") if rotulo else ""

    with IG(dry_run=dry) as ig:
        if config.FONTE != "brecho":
            return _run_proprios(ig, guard, st, quantos, dry, saldo)
        ctx = _contexto_brecho(ig)
        saldo["apagados"] = _limpar_vendidas(ig, st, ctx, dry)
        ciclo, alvos = _selecionar(ctx, st, quantos)
        if not alvos:
            log.info("Nenhuma peça pra postar (%s).", "drop novo" if config.SELECAO == "drop_novo" else "aleatório")
            progresso(0, 0, pre + "sem peças")
            return saldo
        total = len(alvos)
        progresso(0, total, pre + "começando")
        intro = bool(config.VIDEO_INTRO) and os.path.exists(config.INTRO_PATH)
        if config.VIDEO_INTRO and not intro:
            log.warning("  ~ vídeo de abertura ligado, mas %s não existe — sigo sem ele", config.INTRO_PATH)
        if intro:   # abre com o vídeo "confiram as peças disponíveis no destaque" (não entra na limpeza)
            log.info("Abertura: vídeo \"confiram as peças disponíveis\"")
            try:
                log.info("  → vídeo de abertura publicado (%s)", ig.postar_video(config.INTRO_PATH))
                saldo["abertura"] = 1
            except Exception as e:
                if "login_required" in str(e).lower() or _fatal(e):
                    raise ContaBarrada(f"o IG barrou a conta ({str(e)[:80]})") from e
                log.warning("  ! não consegui postar o vídeo de abertura (%s) — sigo com as peças", str(e)[:90])
        for i, p in enumerate(alvos):
            if i > 0 or intro:
                guard.dormir(config.DELAY_POST, "entre stories")
            nome = brecho.rotulo(p)
            log.info("Story %d/%d: %s (post %s · drop %s)", i + 1, total, nome, p["code"], p.get("drop_chave"))
            try:
                sid = ig.postar_code(p["code"], config.REPOST_CARD, config.TEXTO, config.LINK,
                                     img_url=[p.get("imagem_url"), p.get("imagem_reserva")],
                                     foto_local=p.get("foto_local"),
                                     legenda=p.get("nome") or "",
                                     etiqueta=etiqueta.linhas(p, p.get("descricao")))
            except Exception as e:
                if "login_required" in str(e).lower():
                    raise ContaBarrada("sem permissão de postar story pela API (login_required) — "
                                       "sessão barrada; reconecta a conta") from e
                if _fatal(e):
                    raise ContaBarrada(f"o IG barrou a conta ({str(e)[:80]})") from e
                saldo["falhas"] += 1
                log.warning("  ! não consegui repostar %s (%s) — pulo essa peça", p["code"], str(e)[:90])
                continue
            if not dry:
                st.marcar(p["code"], ciclo, sid)
            saldo["postados"] += 1
            log.info("  → story publicado (%s)", sid)
            progresso(saldo["postados"], total, f"{pre}@{ig.username} · {nome}")
    return saldo


def _run_proprios(ig, guard, st, quantos, dry, saldo):
    """Fonte = últimos posts da própria conta logada (modo antigo)."""
    posts = ig.ultimos_posts(quantos + 4)
    alvos = [p for p in posts if not st.ja_fez(p.code, "proprios")][:quantos]
    progresso(0, len(alvos), "começando")
    for i, media in enumerate(alvos):
        if i > 0:
            guard.dormir(config.DELAY_POST, "entre stories")
        sid = ig.postar(media, config.REPOST_CARD, config.TEXTO, config.LINK)
        if not dry:
            st.marcar(media.code, "proprios", sid)
        saldo["postados"] += 1
        progresso(saldo["postados"], len(alvos), f"@{ig.username}")
    return saldo


# ───────────────────────────── lote ─────────────────────────────
def _carregar_contas_lote():
    """Contas do lote via env IG_LOTE_CONTAS (JSON): [{id,label,session,profile}]."""
    raw = (os.environ.get("IG_LOTE_CONTAS") or "").strip()
    if not raw:
        return []
    try:
        d = json.loads(raw)
        return [c for c in d if isinstance(c, dict)] if isinstance(d, list) else []
    except Exception:
        log.warning("IG_LOTE_CONTAS inválido — ignorando lote.")
        return []


def _somar(agg, s):
    for k, v in s.items():
        agg[k] = agg.get(k, 0) + v


def rodar_lote(contas, dry, ignorar_janela):
    """UMA run, todas as contas em sequência. Conta barrada é pulada (aparece no fim)."""
    total = len(contas)
    agg = {"postados": 0, "apagados": 0, "falhas": 0}
    barradas = []
    log.info("═══ LOTE: %d conta%s, uma de cada vez ═══", total, "s" if total != 1 else "")
    for i, c in enumerate(contas, 1):
        if c.get("session"):
            config.SESSION_FILE = c["session"]
        rot = c.get("label") or c.get("id") or "?"
        log.info(" ")
        log.info("━━━━━ Conta %d/%d: @%s ━━━━━", i, total, rot)
        try:
            _somar(agg, run_conta(dry, f"conta {i}/{total} · @{rot}", ignorar_janela))
        except KeyboardInterrupt:
            log.info("Lote parado na conta @%s.", rot)
            break
        except ContaBarrada as e:
            barradas.append(rot)
            log.warning("@%s: %s — sigo pra próxima", rot, e)
        except LimiteAtingido as e:
            log.info("Parando: %s", e)
            break
        except Exception as e:
            barradas.append(rot)
            log.error("@%s deu erro (%s) — sigo pra próxima", rot, str(e)[:120])
            _dump_erro(e)
    if barradas:
        log.warning("Contas que não postaram: %s", ", ".join("@" + b for b in barradas))
    agg["contas_com_erro"] = len(barradas)
    return agg


def _dump_erro(e):
    try:
        _logs = os.path.join(config.OUTPUT_DIR, "logs")
        os.makedirs(_logs, exist_ok=True)
        p = os.path.join(_logs, "erro_" + time.strftime("%Y%m%d_%H%M%S") + ".log")
        with open(p, "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        log.error("   detalhes completos em: %s", p)
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modo", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limite", type=int, default=None)         # backend pode mandar; = QUANTOS_POSTS
    ap.add_argument("--ignore-window", action="store_true")
    ap.add_argument("--listar-modos", action="store_true")
    ap.add_argument("--import-cookies", default=None)           # tolerado; este worker não conecta
    a, _ = ap.parse_known_args()

    if a.listar_modos:
        print(json.dumps(perfis.carregar_perfis(), ensure_ascii=False))
        return
    if a.import_cookies:
        log.info("story-repost não conecta conta — ignorando --import-cookies.")
        return

    modo = a.modo or "aleatório"
    perfil = perfis.get_perfil(modo)
    if perfil is None:
        log.error("Modo '%s' não existe. Modos: %s", modo, ", ".join(perfis.carregar_perfis().keys()))
        sys.exit(2)
    perfis.aplicar(config, perfil)
    if a.limite is not None:
        config.QUANTOS_POSTS = a.limite
    log.info("Modo: %s  |  seleção=%s  |  %s stories/run  |  intervalo %s-%ss  |  estilo=%s",
             modo, config.SELECAO, config.QUANTOS_POSTS, config.DELAY_POST[0], config.DELAY_POST[1],
             config.ESTILO if config.REPOST_CARD else "imagem cheia")

    contas = _carregar_contas_lote()
    try:
        if contas:
            saldo = rodar_lote(contas, a.dry_run, a.ignore_window)
        else:
            saldo = run_conta(a.dry_run, ignorar_janela=a.ignore_window)
    except LimiteAtingido as e:
        log.info("Parando: %s", e)
        saldo = {"postados": 0, "apagados": 0, "falhas": 0}
    except ContaBarrada as e:
        log.error("%s", e)
        sys.exit(1)
    except KeyboardInterrupt:
        log.info("Interrompido.")
        saldo = {"postados": 0, "apagados": 0, "falhas": 0}
    except Exception as e:
        log.error("erro inesperado — parando o run: %s", e)
        _dump_erro(e)
        sys.exit(1)

    log.info("──────────────── SALDO DA EXECUÇÃO ────────────────")
    log.info("   stories postados ... %d", saldo.get("postados", 0))
    log.info("   apagados (vendeu) .. %d", saldo.get("apagados", 0))
    log.info("   falhas ............. %d", saldo.get("falhas", 0))
    if "contas_com_erro" in saldo:
        log.info("   contas com erro .... %d", saldo["contas_com_erro"])
    log.info("────────────────────────────────────────────────────")
    log.info("[saldo] " + " ".join(f"{k}={v}" for k, v in saldo.items()))


if __name__ == "__main__":
    main()
