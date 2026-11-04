#!/usr/bin/env python3
"""Transcricao por trecho com Whisper (sherpa-onnx). Retoma de onde parou.
Modelo: https://github.com/k2-fsa/sherpa-onnx/releases (asr-models/sherpa-onnx-whisper-small.tar.bz2).
  python3 transcribe_sherpa.py --audio audio.wav --segs segs.json --model-dir MODELO/ --out tr.json
Sem tempo por palavra (so por trecho). Para tempo por palavra, usar transcribe_words.py.
"""
import argparse, json, os, time, wave
import numpy as np, sherpa_onnx
ap = argparse.ArgumentParser()
for k in ("--audio", "--segs", "--model-dir", "--out"): ap.add_argument(k, required=True)
ap.add_argument("--lang", default="pt"); ap.add_argument("--budget", type=float, default=140); ap.add_argument("--model", default="small")
a = ap.parse_args(); M = a.model_dir.rstrip("/") + "/"
rec = sherpa_onnx.OfflineRecognizer.from_whisper(encoder=M + f"{a.model}-encoder.int8.onnx", decoder=M + f"{a.model}-decoder.int8.onnx",
                                                 tokens=M + f"{a.model}-tokens.txt", language=a.lang, task="transcribe", num_threads=4)
w = wave.open(a.audio); sr = w.getframerate(); x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
segs = json.load(open(a.segs)); res = json.load(open(a.out)) if os.path.exists(a.out) else {}
t0 = time.time()
for i, (s, e) in enumerate(segs):
    if str(i) in res: continue
    if time.time() - t0 > a.budget: break
    st = rec.create_stream(); st.accept_waveform(sr, x[int(s * sr):int(e * sr)]); rec.decode_stream(st)
    res[str(i)] = {"a": s, "b": e, "t": st.result.text.strip()}; json.dump(res, open(a.out, "w"), ensure_ascii=False)
print(len(res), "/", len(segs), "feitos")
