"""
Segurança/infra do story-repost: logger (arquivo + stdout que o backend captura), delays
humanos com contagem regressiva ([espera]), janela de horário e estado (dedup de posts já
postados no story). Espelha o padrão dos outros workers.
"""
import json
import os
import sys
import time
import random
import logging


def setup_logger():
    import config
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    logger = logging.getLogger("storyrepost")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    fmt = logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(config.LOG_FILE, encoding="utf-8"); fh.setFormatter(fmt)
    ch = logging.StreamHandler(sys.stdout); ch.setFormatter(fmt)
    _logs = os.path.join(config.OUTPUT_DIR, "logs"); os.makedirs(_logs, exist_ok=True)
    _sess = logging.FileHandler(os.path.join(_logs, "run_" + time.strftime("%Y%m%d_%H%M%S") + ".log"), encoding="utf-8")
    _sess.setFormatter(fmt)
    try:
        antigos = sorted(f for f in os.listdir(_logs) if f.startswith("run_") and f.endswith(".log"))
        for f in antigos[:-30]:
            os.remove(os.path.join(_logs, f))
    except Exception:
        pass
    for h in (fh, _sess, ch):
        logger.addHandler(h)
    return logger


log = setup_logger()


def fmt_tempo(segundos):
    seg = int(round(segundos))
    if seg < 60:
        return f"{seg}s"
    m, s = divmod(seg, 60)
    return f"{m}m {s}s" if s else f"{m}m"


def _dormir_contando(t, motivo=""):
    """Dorme `t`s. Pausas longas (>15s) emitem [espera] a cada ~12s → contagem no app/LA."""
    if t <= 15:
        time.sleep(t)
        return
    fim = time.monotonic() + t
    while True:
        restam = fim - time.monotonic()
        if restam <= 0.5:
            break
        print(f"[espera] {int(round(restam))} {motivo}".rstrip(), flush=True)
        time.sleep(min(restam, 12))


class BloqueioDetectado(Exception):
    """IG barrou a ação (checkpoint/spam/limite)."""


class LimiteAtingido(Exception):
    """Cap/janela — parar com elegância."""


class ErroTransitorio(Exception):
    """Falha pontual — pula e segue."""


class State:
    """Estado POR conta (config.state_file):
      - `ciclos`: {nome_do_ciclo: [codes já postados]} — um ciclo por seleção ("aleatorio",
        "drop:<id>"…). Peça só repete quando a conta já postou todas as do ciclo;
      - `stories`: os stories que ESTE bot postou (pk, code, ts), últimas 48h — pra apagar o
        story de peça que vendeu enquanto ele estava no ar.
    O `done_codes` antigo (antes dos ciclos) vira o ciclo "aleatorio"."""
    def __init__(self, path):
        self.path = path
        self.data = {"ciclos": {}, "stories": []}
        if os.path.exists(path):
            try:
                self.data.update(json.load(open(path, encoding="utf-8")))
            except Exception as e:
                log.warning("state ilegível (%s); começando limpo.", e)
        antigos = self.data.pop("done_codes", None)
        if antigos and "aleatorio" not in self.data["ciclos"]:
            self.data["ciclos"]["aleatorio"] = antigos

    def _ciclo(self, ciclo):
        return self.data["ciclos"].setdefault(ciclo, [])

    def ja_fez(self, code, ciclo="aleatorio"):
        return str(code) in self._ciclo(ciclo)

    def zerar(self, ciclo):
        self.data["ciclos"][ciclo] = []
        self.save()

    def marcar(self, code, ciclo="aleatorio", story_pk=None):
        code = str(code)
        c = self._ciclo(ciclo)
        if code not in c:
            c.append(code)
        self.data["ciclos"][ciclo] = c[-1000:]
        if story_pk and str(story_pk) not in ("dry", "ok"):
            self.data["stories"].append({"pk": str(story_pk), "code": code, "ts": int(time.time())})
        self.save()

    def stories_no_ar(self, horas=24):
        """Stories postados por este bot que ainda estão no ar (< `horas`)."""
        lim = time.time() - horas * 3600
        return [s for s in self.data["stories"] if s.get("ts", 0) >= lim]

    def esquecer_story(self, pk):
        self.data["stories"] = [s for s in self.data["stories"] if s.get("pk") != str(pk)]
        self.save()

    def podar(self):
        lim = time.time() - 48 * 3600
        self.data["stories"] = [s for s in self.data["stories"] if s.get("ts", 0) >= lim]

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)


class Guard:
    def __init__(self, dry_run=False):
        import config
        self.cfg = config
        self.dry_run = dry_run

    def checar_janela(self, ignorar=False):
        from datetime import datetime
        if ignorar or not getattr(self.cfg, "ACTIVE_HOURS", None):
            return
        h = datetime.now().hour
        ini, fim = self.cfg.ACTIVE_HOURS
        if ini == fim:
            return
        if not (ini <= h < fim):
            raise LimiteAtingido(f"Fora da janela ({ini}h–{fim}h). Agora: {h}h.")

    def dormir(self, faixa, motivo=""):
        a, b = faixa
        if b <= 0:
            return
        t = random.uniform(a, b)
        log.info("dormindo %s (%s)", fmt_tempo(t), motivo)
        _dormir_contando(t, motivo)
