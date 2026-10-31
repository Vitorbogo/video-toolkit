#!/usr/bin/env python3
"""Trechos de fala a partir da saida do silencedetect.
  ffmpeg -i audio.wav -af silencedetect=noise=-35dB:d=0.4 -f null - 2>&1 | grep -E "silence_(start|end)" \
     | sed -E 's/.*silence_(start|end): ([0-9.]+).*/\1 \2/' > sil.txt
  python3 seg.py --sil sil.txt --dur 355.95 --out segs.json
"""
import argparse, json
ap = argparse.ArgumentParser(); ap.add_argument("--sil", required=True); ap.add_argument("--dur", type=float, required=True)
ap.add_argument("--out", required=True); ap.add_argument("--max", type=float, default=25.0); a = ap.parse_args()
sil = [l.split() for l in open(a.sil)]
starts = [float(v) for k, v in sil if k == "start"]; ends = [float(v) for k, v in sil if k == "end"]
sp, cur = [], 0.0
for s, e in zip(starts, ends):
    if s - cur > 0.15: sp.append([cur, s])
    cur = e
if a.dur - cur > 0.15: sp.append([cur, a.dur])
out = []
for x, y in sp:
    while y - x > a.max: out.append([x, x + a.max]); x += a.max
    out.append([x, y])
json.dump(out, open(a.out, "w")); print(len(out), "segmentos; fala total %.1fs" % sum(y - x for x, y in out))
