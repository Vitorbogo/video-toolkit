#!/usr/bin/env python3
"""Tratamento de audio deterministico, em 2 passadas, sobre o video ja montado.

Cadeia (ordem fixa, parametros no preset): filtro de graves -> reducao de ruido (afftdn, DESLIGADA no
preset: deixava a voz robotica com o microfone do Vitor) -> compressor suave -> loudnorm medido (passada 1) e aplicado linear (passada 2) -> limitador.
O video e copiado sem recodificar.

Uso: python3 postaudio.py --preset presets/tiktok-vertical.json --in final.mp4 --out final_audio.mp4
"""
import argparse, json, re, subprocess, sys

ap = argparse.ArgumentParser()
ap.add_argument("--preset", required=True); ap.add_argument("--in", dest="inp", required=True)
ap.add_argument("--out", required=True); ap.add_argument("--no-denoise", action="store_true")
a = ap.parse_args()
A = json.load(open(a.preset))["audio"]

def chain():
    f = [f"highpass=f={A['highpass_hz']}"]
    dn = A["denoise"]
    if dn["enabled"] and not a.no_denoise:
        f.append(f"afftdn=nr={dn['nr_db']}:nf={dn['noise_floor_db']}")
    c = A["compressor"]
    f.append(f"acompressor=threshold={c['threshold_linear']}:ratio={c['ratio']}:attack={c['attack_ms']}:release={c['release_ms']}:makeup={c['makeup']}")
    # limitador ANTES do loudnorm: fala tem picos altos em relacao ao volume medio; sem isso o loudnorm
    # nao consegue chegar ao alvo respeitando o pico maximo.
    f.append(f"alimiter=limit={A['pre_limiter']}:attack=5:release=50:level=0")
    return ",".join(f)

ln = A["loudnorm"]; base = f"I={ln['I']}:TP={ln['TP']}:LRA={ln['LRA']}"
# passada 1: medir
p1 = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", a.inp, "-vn", "-af",
                     f"{chain()},loudnorm={base}:print_format=json", "-f", "null", "-"],
                    capture_output=True, text=True)
m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p1.stderr, re.S)
if not m: print(p1.stderr[-600:]); sys.exit("nao consegui medir o volume")
j = json.loads(m.group(0))
print("medido:", {k: j[k] for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")})
# passada 2: aplicar com os valores medidos
ln2 = (f"loudnorm={base}:measured_I={j['input_i']}:measured_TP={j['input_tp']}:measured_LRA={j['input_lra']}"
       f":measured_thresh={j['input_thresh']}:offset={j['target_offset']}:linear=true")
af = f"{chain()},{ln2},aresample=48000,alimiter=limit={A['limiter']}:level=0"
r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.inp, "-map", "0:v", "-map", "0:a", "-c:v", "copy",
                    "-af", af, "-c:a", "aac", "-b:a", A["bitrate"], a.out], capture_output=True, text=True)
if r.returncode: print(r.stderr[-600:]); sys.exit(1)
chk = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", a.out, "-vn", "-af", f"loudnorm={base}:print_format=json", "-f", "null", "-"],
                     capture_output=True, text=True)
m2 = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", chk.stderr, re.S)
if m2:
    k = json.loads(m2.group(0)); print("resultado: %s LUFS, pico %s dBTP" % (k["input_i"], k["input_tp"]))
