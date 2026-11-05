#!/usr/bin/env python3
"""Efeitos sonoros: biblioteca gerada por síntese (sfx/) e lista de efeitos por vídeo (videos/<nome>/sfx.json).

  python3 src/vtk/sfx.py gerar                                   # (re)gera sfx/*.wav, determinístico
  python3 src/vtk/sfx.py marcas --plan videos/<nome>/plan.json   # tempos no vídeo final: trechos e legendas
  python3 src/vtk/sfx.py checar --sfx videos/<nome>/sfx.json [--plan ...]

sfx.json: [{"t": 11.0, "som": "whoosh-curto"}, {"t": 7.5, "som": "pop-blip", "vol": 0.25}, ...]
  t   = momento no vídeo FINAL (depois dos cortes) em que o efeito "bate". O som começa um pouco antes
        (o "hit" de cada som está em CATALOGO), então o whoosh passa exatamente no corte.
  vol = opcional, padrão do CATALOGO. A mistura é feita pelo postaudio.py --sfx, antes do loudnorm.
Regras de uso (onde pôr cada som): .claude/skills/efeitos-sonoros/SKILL.md.
"""
import argparse, json, os, sys, wave

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SFX_DIR = os.path.join(ROOT, "sfx")
SR = 48000
MIN_GAP_S = 5.0  # menos que isso entre efeitos fica carregado (regra da skill)

# hit = segundos do início do arquivo até o ponto em que o som "bate"; vol = ganho padrão na mistura
CATALOGO = {
    "whoosh-curto": {"hit": 0.11, "vol": 0.28, "uso": "passagem: mudança de assunto ou de slide"},
    "pop-bolha":    {"hit": 0.02, "vol": 0.30, "uso": "destaque macio: texto ou ideia que aparece"},
    "pop-madeira":  {"hit": 0.0,  "vol": 0.30, "uso": "destaque seco: frase de impacto"},
    "pop-blip":     {"hit": 0.01, "vol": 0.25, "uso": "destaque leve: item de lista, número"},
    "clique":       {"hit": 0.0,  "vol": 0.35, "uso": "ação na tela: clique, botão, enviar prompt"},
}


# ---------- síntese (numpy só aqui, para o resto do módulo não depender dele) ----------

def _sintetizar():
    import numpy as np
    rng = np.random.default_rng(7)

    def norm(x, peak_db):
        x = x / (np.max(np.abs(x)) + 1e-9) * 10 ** (peak_db / 20)
        f = int(0.004 * SR); x[-f:] *= np.linspace(1, 0, f)
        return x

    def tone(dur, f, tau, att=0.002):
        n = int(dur * SR); t = np.arange(n) / SR
        ff = f(t) if callable(f) else np.full(n, float(f))
        return np.sin(2 * np.pi * np.cumsum(ff) / SR) * (1 - np.exp(-t / att)) * np.exp(-t / tau)

    def whoosh(dur, f0, f1, q=1.2, attack=0.5):
        n = int(dur * SR); t = np.linspace(0, 1, n)
        env = np.where(t < attack, (t / attack) ** 2, ((1 - t) / (1 - attack)) ** 1.5)
        x = rng.standard_normal(n); fc = np.geomspace(f0, f1, n)
        y = np.zeros(n); x1 = x2 = y1 = y2 = 0.0
        for i in range(n):  # passa-banda (biquad) com a frequência central varrendo f0 -> f1
            w0 = 2 * np.pi * fc[i] / SR; al = np.sin(w0) / (2 * q); a0 = 1 + al
            yi = (al * x[i] - al * x2 + 2 * np.cos(w0) * y1 - (1 - al) * y2) / a0
            x2, x1, y2, y1 = x1, x[i], y1, yi; y[i] = yi
        return y * env

    t08 = np.arange(int(0.08 * SR)) / SR
    t03 = np.arange(int(0.03 * SR)) / SR
    return {
        "whoosh-curto": norm(whoosh(0.22, 600, 5000), -3),
        "pop-bolha": norm(tone(0.12, lambda t: 380 + 520 * (1 - np.exp(-t / 0.02)), 0.03, 0.004), -6),
        "pop-madeira": norm(tone(0.08, 520, 0.018) + 0.5 * tone(0.08, 1320, 0.008)
                            + 0.15 * rng.standard_normal(len(t08)) * np.exp(-t08 / 0.0015), -6),
        "pop-blip": norm(tone(0.10, 700, 0.035, 0.006), -8),
        "clique": norm(np.sin(2 * np.pi * 3200 * t03) * np.exp(-t03 / 0.003)
                       + 0.6 * rng.standard_normal(len(t03)) * np.exp(-t03 / 0.0012), -6),
    }


def gerar(out=SFX_DIR):
    os.makedirs(out, exist_ok=True)
    for nome, x in _sintetizar().items():
        with wave.open(os.path.join(out, nome + ".wav"), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
            w.writeframes((x * 32767).astype("<i2").tobytes())
        print("ok", nome)


# ---------- lista por vídeo ----------

def timeline(plan):
    """plan.json -> [(inicio_no_final, fim_no_final, trecho)]: onde cada trecho cai no vídeo final."""
    out, t = [], 0.0
    for c in plan:
        d = c["e"] - c["s"]; out.append((round(t, 3), round(t + d, 3), c)); t += d
    return out


def checar(cues, duracao=None):
    """Lista de problemas (vazia = ok): som desconhecido, fora do vídeo, efeitos colados demais."""
    erros = []
    for i, c in enumerate(cues):
        if c.get("som") not in CATALOGO:
            erros.append(f"#{i}: som '{c.get('som')}' não existe (opções: {', '.join(CATALOGO)})")
        if not isinstance(c.get("t"), (int, float)) or c["t"] < 0 or (duracao and c["t"] > duracao):
            erros.append(f"#{i}: t={c.get('t')} fora do vídeo")
        v = c.get("vol")
        if v is not None and not (0 < v <= 1):
            erros.append(f"#{i}: vol={v} fora de (0, 1]")
    ts = sorted(c["t"] for c in cues if isinstance(c.get("t"), (int, float)))
    for a, b in zip(ts, ts[1:]):
        if b - a < MIN_GAP_S:
            erros.append(f"efeitos em {a:.1f}s e {b:.1f}s: menos de {MIN_GAP_S:g}s entre eles")
    return erros


def filtro_mistura(cues, voz="[voz]", primeiro_input=1, saida="[mix]"):
    """Trecho de -filter_complex: atrasa cada efeito até o seu t (descontando o hit) e mistura com a voz.
    Os efeitos entram como inputs primeiro_input, primeiro_input+1, ... na ordem de `cues`."""
    partes, rotulos = [], []
    for i, c in enumerate(cues):
        cat = CATALOGO[c["som"]]
        ms = max(0, int(round((c["t"] - cat["hit"]) * 1000)))
        partes.append(f"[{primeiro_input + i}:a]adelay={ms}:all=1,volume={c.get('vol', cat['vol'])}[s{i}]")
        rotulos.append(f"[s{i}]")
    partes.append(f"{voz}{''.join(rotulos)}amix=inputs={len(cues) + 1}:normalize=0:duration=first{saida}")
    return ";".join(partes)


def arquivo(som):
    return os.path.join(SFX_DIR, som + ".wav")


def main():
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gerar")
    m = sub.add_parser("marcas"); m.add_argument("--plan", required=True)
    c = sub.add_parser("checar"); c.add_argument("--sfx", required=True); c.add_argument("--plan")
    a = ap.parse_args()
    if a.cmd == "gerar":
        gerar(); return
    if a.cmd == "marcas":
        for n, (u, v, c) in enumerate(timeline(json.load(open(a.plan, encoding="utf-8")))):
            print(f"trecho {n:02d}  {u:7.2f}s - {v:7.2f}s")
            for (x0, _, txt) in c["ev"]:
                print(f"    {u + x0:7.2f}s  {txt}")
        return
    cues = json.load(open(a.sfx, encoding="utf-8"))
    dur = timeline(json.load(open(a.plan, encoding="utf-8")))[-1][1] if a.plan else None
    erros = checar(cues, dur)
    for e in erros: print("ERRO", e)
    if erros: sys.exit(1)
    print(f"ok: {len(cues)} efeitos")


if __name__ == "__main__":
    main()
