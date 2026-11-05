#!/usr/bin/env python3
"""Tratamento de audio deterministico, em 2 passadas, sobre o video ja montado.

Cadeia (ordem fixa, parametros no preset): filtro de graves -> reducao de ruido (afftdn, DESLIGADA no
preset: deixava a voz robotica com o microfone do Vitor) -> compressor suave -> pre-limitador -> loudnorm medido
(passada 1) e aplicado LINEAR (passada 2: ganho fixo, sem bombear) -> limitador final.
O video e copiado sem recodificar; o audio sai em AAC 48 kHz. Aceita o final.mov do render.py (h264 + PCM).

Pre-limitador: o loudnorm so aplica ganho linear se pico medido + ganho <= pico alvo. Fala real tem picos curtos
(plosivas) muito acima do volume medio; sem pre-limitador o loudnorm cai sozinho no modo dinamico. Com
"pre_limiter": "auto" a passada 1 calcula o limite que torna o linear possivel (com folga) e mede de novo.
Um numero < 1 no preset e um limite fixo (linear, 0-1) aplicado sempre; o "auto" ainda baixa mais se precisar.
Pico final: planejado para TP - tp_margin_db (folga para o AAC, que aumenta o pico). O resultado e medido; se o
pico passar do alvo, refaz com mais folga. Fora do alvo (|I - alvo| > 0,5 LU ou pico > TP): sai com erro.

Uso: python3 src/vtk/postaudio.py --preset presets/tiktok-vertical.json --in final.mov --out final.mp4
"""
import argparse, json, math, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.path.join(ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "src"))
from vtk import preset

TOL_I = 0.5           # LU de tolerancia no volume integrado do resultado
LIMIT_MIN_DB = -24.0  # menor limite do alimiter (0.0625)
STEP_DB = 0.2         # folga extra a cada novo pre-limite / nova tentativa


def db(x): return 20 * math.log10(x)
def lin(d): return 10 ** (d / 20)


def parse_loudnorm(stderr):
    """JSON do loudnorm (print_format=json) no stderr do ffmpeg -> dict com floats ('-inf' vira -inf)."""
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", stderr, re.S)
    if not m: return None
    out = {}
    for k, v in json.loads(m.group(0)).items():
        try: out[k] = float(v)
        except ValueError: out[k] = v
    return out


def check_preset(A):
    for k in ("highpass_hz", "compressor", "loudnorm", "bitrate"):
        if k not in A: sys.exit("preset: falta audio.%s" % k)
    for k in ("I", "TP", "LRA"):
        if k not in A["loudnorm"]: sys.exit("preset: falta audio.loudnorm.%s" % k)
    pl = A.get("pre_limiter", "auto")
    if pl != "auto" and not (isinstance(pl, (int, float)) and 0.0625 <= pl <= 1):
        sys.exit("preset: audio.pre_limiter deve ser \"auto\" ou um numero entre 0.0625 e 1 (veio %r)" % (pl,))
    tm = A.get("tp_margin_db", 1.0)
    if not isinstance(tm, (int, float)) or tm < 0: sys.exit("preset: audio.tp_margin_db deve ser um numero >= 0 (veio %r)" % (tm,))
    if "limiter" in A:
        print("aviso: audio.limiter do preset nao e mais usado (limite final = TP - tp_margin_db)")


def chain(A, pre_db=None):
    """Filtros antes do loudnorm. pre_db = limite do pre-limitador em dBFS (None = sem pre-limitador).
    Tudo a 192 kHz nas duas passadas: o loudnorm da passada 1 forca 192 kHz e o ffmpeg puxava a cadeia toda para
    essa taxa, mas na passada 2 (linear) ela rodava a 48 kHz. O limitador a 48 kHz nao ve os picos entre amostras,
    e o pico real saia ~2 dB acima do medido. A 192 kHz o limitador age no pico real (true peak)."""
    f = ["aresample=192000", f"highpass=f={A['highpass_hz']}"]
    dn = A.get("denoise") or {}
    if dn.get("enabled"):
        f.append(f"afftdn=nr={dn['nr_db']}:nf={dn['noise_floor_db']}")
    c = A["compressor"]
    f.append(f"acompressor=threshold={c['threshold_linear']}:ratio={c['ratio']}:attack={c['attack_ms']}"
             f":release={c['release_ms']}:makeup={c['makeup']}")
    if pre_db is not None:
        # level=0: o auto-level do alimiter sobe o ganho de volta; latency=1: sem atraso de ~5 ms no audio
        f.append(f"alimiter=limit={lin(pre_db):.6f}:attack=5:release=50:level=0:latency=1")
    return ",".join(f)


def excess(m, I, tp_plan):
    """Quanto (dB) o pico passaria de tp_plan com ganho linear ate I. <= 0: linear e possivel."""
    return m["input_tp"] + (I - m["input_i"]) - tp_plan


def next_pre_db(m, I, tp_plan, cur_db):
    """Proximo limite do pre-limitador: baixa o pico pelo excesso, mais uma folga (o volume cai um pouco junto)."""
    base = m["input_tp"] if cur_db is None else min(cur_db, m["input_tp"])
    return base - excess(m, I, tp_plan) - STEP_DB


def ffmpeg_ln(args):
    try: r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats"] + args, capture_output=True, text=True)
    except FileNotFoundError: sys.exit("ffmpeg nao encontrado no PATH")
    return r, parse_loudnorm(r.stderr)


def measure(inp, af, base):
    r, m = ffmpeg_ln(["-i", inp, "-map", "0:a:0", "-af", f"{af},loudnorm={base}:print_format=json", "-f", "null", "-"])
    if m is None:
        if "matches no streams" in r.stderr: sys.exit("%s nao tem faixa de audio" % inp)
        print(r.stderr[-800:]); sys.exit("nao consegui medir o volume de %s" % inp)
    if not math.isfinite(m["input_i"]) or m["input_i"] <= -70:
        sys.exit("audio em silencio (volume %s LUFS) em %s: confira a faixa de audio" % (m["input_i"], inp))
    return m


def plan(inp, A, base, margin):
    """Passada 1 (+ re-medidas): acha o pre-limite que deixa o ganho linear dentro de TP - margin."""
    I, tp_plan = A["loudnorm"]["I"], A["loudnorm"]["TP"] - margin
    pl = A.get("pre_limiter", "auto")
    pre = db(pl) if isinstance(pl, (int, float)) and pl < 1 else None
    for _ in range(6):
        m = measure(inp, chain(A, pre), base)
        print("medido%s: %.2f LUFS, pico %.2f dBTP, LRA %.2f -> ganho %+.2f dB, pico previsto %.2f (plano %.2f)" % (
            "" if pre is None else " (pre-limite %.2f dBFS)" % pre, m["input_i"], m["input_tp"], m["input_lra"],
            I - m["input_i"], m["input_tp"] + I - m["input_i"], tp_plan))
        if excess(m, I, tp_plan) <= 0: return pre, m
        pre = next_pre_db(m, I, tp_plan, pre)
        if pre < LIMIT_MIN_DB:
            sys.exit("picos altos demais para chegar a %s LUFS com pico %s: precisaria limitar a %.1f dBFS (minimo %.0f)"
                     % (I, A["loudnorm"]["TP"], pre, LIMIT_MIN_DB))
    sys.exit("nao consegui um pre-limite que permita loudnorm linear")


def encode(inp, out, A, base, pre, m, margin):
    """Passada 2: loudnorm linear com os valores medidos -> AAC. Devolve normalization_type."""
    ln2 = (f"loudnorm={base}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
           f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true:print_format=json")
    final = lin(A["loudnorm"]["TP"] - margin)
    af = f"{chain(A, pre)},{ln2},alimiter=limit={final:.6f}:level=0:latency=1,aresample=48000"
    r, j = ffmpeg_ln(["-y", "-i", inp, "-map", "0:v?", "-map", "0:a:0", "-c:v", "copy", "-af", af,
                      "-c:a", "aac", "-b:a", A["bitrate"], "-ar", "48000", "-movflags", "+faststart", out])
    if r.returncode or j is None:
        print(r.stderr[-800:]); sys.exit("ffmpeg falhou na passada 2")
    return j["normalization_type"]


def run(inp, out, A):
    check_preset(A)
    ln = A["loudnorm"]; base = f"I={ln['I']}:TP={ln['TP']}:LRA={ln['LRA']}"
    root, ext = os.path.splitext(out); tmp = root + ".tmp" + ext
    margin = float(A.get("tp_margin_db", 1.0))
    for tentativa in range(3):
        pre, m = plan(inp, A, base, margin)
        nt = encode(inp, tmp, A, base, pre, m, margin)
        print("passada 2: normalization_type=%s" % nt)
        if nt != "linear":
            print("aviso: loudnorm caiu no modo dinamico (volume varia ao longo do video); confira o pre-limitador")
        k = measure(tmp, "anull", base)
        print("resultado: %.2f LUFS, pico %.2f dBTP (alvo %s LUFS, pico <= %s)" % (k["input_i"], k["input_tp"], ln["I"], ln["TP"]))
        if k["input_tp"] > ln["TP"] and tentativa < 2:
            margin += k["input_tp"] - ln["TP"] + STEP_DB
            print("pico acima do alvo depois do AAC: refazendo com folga de %.2f dB" % margin); continue
        break
    if abs(k["input_i"] - ln["I"]) > TOL_I or k["input_tp"] > ln["TP"]:
        sys.exit("fora do alvo: %.2f LUFS (alvo %s +-%s), pico %.2f dBTP (max %s). Arquivo mantido em %s para conferir"
                 % (k["input_i"], ln["I"], TOL_I, k["input_tp"], ln["TP"], tmp))
    os.replace(tmp, out); print("ok:", out)
    return {"I": k["input_i"], "TP": k["input_tp"], "normalization_type": nt, "pre_limit_db": pre, "margin_db": margin}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--preset", required=True); ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True, help="video de saida (.mp4)")
    a = ap.parse_args(argv)
    if not os.path.exists(a.inp): sys.exit("nao achei %s" % a.inp)
    if os.path.abspath(a.inp) == os.path.abspath(a.out): sys.exit("--out precisa ser diferente de --in")
    return run(a.inp, a.out, preset.load(a.preset)["audio"])


if __name__ == "__main__":
    main()
