#!/usr/bin/env python3
"""Transcricao com TEMPO POR PALAVRA, gratis e local (sherpa-onnx + NVIDIA Parakeet TDT v3, multilingue, inclui portugues).

Gera o formato que o src/vtk/engine.py le: transcript.json com "words" e "sentences",
mais transcript.txt (uma linha por frase, com tempo). A resolucao e de 80 ms (um quadro do modelo).

  python3 src/vtk/transcribe_words.py --audio audio.wav --model-dir models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8 \
      --out work/ [--segs segs.json]

Modelo (487 MB, GitHub releases do k2-fsa/sherpa-onnx, asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2),
guardado em models/ (ignorado pelo git). O audio deve ser mono, 16 kHz (ffmpeg -ac 1 -ar 16000).
Com --segs (trechos de fala do seg.py) as janelas comecam e terminam em silencio; sem, usa janelas fixas de 20 s.
"""
import argparse, json, os, wave
import numpy as np, sherpa_onnx

ap = argparse.ArgumentParser()
ap.add_argument("--audio", required=True); ap.add_argument("--model-dir", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--segs", default=None); ap.add_argument("--win", type=float, default=25.0, help="duracao maxima de uma janela (s)")
ap.add_argument("--threads", type=int, default=4)
a = ap.parse_args(); M = a.model_dir.rstrip("/") + "/"; os.makedirs(a.out, exist_ok=True)

rec = sherpa_onnx.OfflineRecognizer.from_transducer(encoder=M + "encoder.int8.onnx", decoder=M + "decoder.int8.onnx",
        joiner=M + "joiner.int8.onnx", tokens=M + "tokens.txt", model_type="nemo_transducer", num_threads=a.threads)
w = wave.open(a.audio); sr = w.getframerate()
assert sr == 16000 and w.getnchannels() == 1, "audio deve ser mono 16 kHz"
x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768; dur = len(x) / sr

# janelas: junta trechos de fala vizinhos ate a.win segundos (bordas em silencio)
if a.segs:
    segs = json.load(open(a.segs)); wins = []
    for s, e in segs:
        if wins and e - wins[-1][0] <= a.win: wins[-1][1] = e
        else: wins.append([s, e])
else:
    wins = [[t, min(t + a.win, dur)] for t in np.arange(0, dur, a.win)]

words = []
for s, e in wins:
    s0 = max(0.0, s - 0.2); e0 = min(dur, e + 0.2)
    st = rec.create_stream(); st.accept_waveform(sr, x[int(s0 * sr):int(e0 * sr)]); rec.decode_stream(st); r = st.result
    cur = None
    for tok, ts in zip(r.tokens, r.timestamps):
        t = round(s0 + ts, 3)
        if tok.startswith(" ") or cur is None:                       # token com espaco inicia palavra
            if cur: words.append(cur)
            cur = {"w": tok.strip(), "start": t, "last": t}
        else:
            cur["w"] += tok; cur["last"] = t
    if cur: words.append(cur)

# pontuacao solta gruda na palavra anterior; fim da palavra = ultimo token + ~0.16 s, limitado pelo inicio da seguinte
clean = []
for wd in words:
    if clean and wd["w"] and all(c in ".,;:?!…" for c in wd["w"]): clean[-1]["w"] += wd["w"]; clean[-1]["last"] = wd["last"]
    elif wd["w"]: clean.append(wd)
for i, wd in enumerate(clean):
    nxt = clean[i + 1]["start"] if i + 1 < len(clean) else dur
    wd["end"] = round(min(wd["last"] + 0.16, nxt), 3); del wd["last"]

def sentences(ws, max_gap=0.8, max_len=45):
    out, cur = [], []
    for i, wd in enumerate(ws):
        cur.append(wd); nx = ws[i + 1] if i + 1 < len(ws) else None
        if nx is None or wd["w"][-1:] in ".?!" or nx["start"] - wd["end"] > max_gap or len(cur) >= max_len:
            out.append({"start": cur[0]["start"], "end": cur[-1]["end"], "text": " ".join(c["w"] for c in cur)}); cur = []
    return out
sents = sentences(clean)
stamp = lambda t: "%02d:%04.1f" % divmod(t, 60)
json.dump({"source": "sherpa-onnx parakeet-tdt-0.6b-v3 (local)", "audio": os.path.abspath(a.audio), "duration": dur,
           "words": clean, "sentences": sents}, open(os.path.join(a.out, "transcript.json"), "w"), ensure_ascii=False)
with open(os.path.join(a.out, "transcript.txt"), "w") as fh:
    for s in sents: fh.write("[%s-%s] %s\n" % (stamp(s["start"]), stamp(s["end"]), s["text"]))
print(len(clean), "palavras,", len(sents), "frases ->", a.out)
