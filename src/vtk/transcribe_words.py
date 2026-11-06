#!/usr/bin/env python3
"""Transcription with PER-WORD TIMES, free and local (sherpa-onnx + NVIDIA Parakeet TDT v3, multilingual: Portuguese, English...).

  python3 src/vtk/transcribe_words.py --video RECORDING.mov --name <name>     # -> videos/<name>/transcript.json and .txt
  python3 src/vtk/transcribe_words.py --audio audio.wav --out work/ [--model-dir DIR]

Writes the format src/vtk/engine.py reads: transcript.json with "words" ({w, start, end}, absolute times in seconds),
"sentences" and "lang" (spoken language detected from the words, src/vtk/lang.py; null when it can't tell), plus
transcript.txt (one line per sentence, with times). 80 ms resolution.

The audio is decoded by ffmpeg (mono 16 kHz, straight into memory). Silences (below -35 dB for 0.4 s or more) separate
the speech runs; neighbouring runs become windows of up to 25 s, with 0.2 s extra at edges in silence. Continuous
speech longer than 25 s is split at the quietest point (~80 ms) between 15 and 25 s, never at a fixed time; a word
repeated at the join of two windows goes. Word end = start + duration of the last token (punctuation doesn't move the
end), snapped to the start of the next silence.

Model (487 MB) in models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8 (ignored by git; how to download: README).
Needs ffmpeg and `pip install sherpa-onnx numpy`.
"""
import argparse, difflib, json, os, shutil, subprocess, sys, time, unicodedata, wave
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))
from vtk import lang as lng
MODEL = os.path.join(ROOT, "models", "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8")
MODEL_FILES = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")
SR, FR, TOK = 16000, 0.02, 0.08      # model rate; silence detection frame; model frame (80 ms)
PUNCT = set(".,;:?!…")


# ---------- audio and silences ----------

def decode(path):
    """Any audio/video -> float32 mono 16 kHz. A 16-bit mono 16 kHz WAV is read directly; the rest goes through ffmpeg."""
    if path.lower().endswith(".wav"):
        try:
            with wave.open(path) as w:
                if (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (SR, 1, 2):
                    return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        except (wave.Error, EOFError):
            pass
    if not shutil.which("ffmpeg"):
        sys.exit(f"ERROR: {path} needs ffmpeg to become mono 16 kHz (brew install ffmpeg), "
                 "or pass a 16-bit mono 16 kHz WAV (ffmpeg -i X -vn -ac 1 -ar 16000 audio.wav).")
    p = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(SR),
                        "-f", "s16le", "-"], capture_output=True)
    if p.returncode or not p.stdout:
        sys.exit(f"ERROR: ffmpeg could not read the audio of {path}: {p.stderr.decode('utf-8', 'replace').strip() or 'no audio'}")
    return np.frombuffer(p.stdout, dtype=np.int16).astype(np.float32) / 32768


def frame_db(x, sr=SR, fr=FR):
    """RMS level (dBFS) of each frame of fr seconds."""
    n = int(round(sr * fr)); m = len(x) // n
    rms = np.sqrt(np.mean(np.square(x[:m * n].reshape(m, n), dtype=np.float64), axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-10))


def speech_runs(db, dur, fr=FR, noise=-35.0, min_sil=0.4, min_speech=0.15):
    """Speech runs [[start, end]]: what is left between silences (below noise dB for min_sil s or more)."""
    q = np.concatenate(([0], (db < noise).astype(np.int8), [0])); d = np.diff(q)
    sil = [(i * fr, dur if j >= len(db) else j * fr) for i, j in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1))
           if (j - i) * fr >= min_sil]
    out, cur = [], 0.0
    for s, e in sil:
        if s - cur > min_speech: out.append([round(float(cur), 3), round(float(s), 3)])
        cur = e
    if dur - cur > min_speech: out.append([round(float(cur), 3), round(float(dur), 3)])
    return out


def quiet_point(db, a, b, fr=FR, span=0.08):
    """Centre of the quietest ~80 ms between a and b seconds."""
    k = max(1, int(round(span / fr))); i0 = int(a / fr); i1 = min(len(db), int(b / fr))
    if i1 - i0 < k: return round((a + b) / 2, 3)
    p = np.convolve(10 ** (db[i0:i1] / 10), np.ones(k) / k, mode="valid")
    return round(float((i0 + int(np.argmin(p)) + k / 2) * fr), 3)


def windows(runs, db, win=25.0, lo=15.0, fr=FR):
    """Windows of up to win s: neighbouring runs merge; a run longer than win is split at the quietest point
    between lo and win s from its start (never at a fixed time)."""
    parts = []
    for x, y in runs:
        while y - x > win:
            c = quiet_point(db, x + lo, x + win, fr); parts.append([x, c]); x = c
        parts.append([x, y])
    out = []
    for s, e in parts:
        if out and e - out[-1][0] <= win: out[-1][1] = e
        else: out.append([s, e])
    return out


# ---------- tokens -> words ----------

def words_of(tokens, timestamps, durations=None, offset=0.0):
    """Parakeet tokens -> [{w, start, end}]. A token with a leading space starts a word; punctuation sticks to the
    previous word without moving its end. End = start of the last token + its duration (without durations: + 0.16 s)."""
    has_d = durations is not None and len(durations) == len(tokens)
    out = []
    for k, (tok, ts) in enumerate(zip(tokens, timestamps)):
        txt = tok.strip()
        if not txt: continue
        if all(c in PUNCT for c in txt):
            if out: out[-1]["w"] += txt
            continue
        t = offset + ts; end = round(t + (max(durations[k], TOK) if has_d else 0.16), 3)
        if tok.startswith(" ") or not out: out.append({"w": txt, "start": round(t, 3), "end": end})
        else: out[-1]["w"] += txt; out[-1]["end"] = end
    return out


def norm(w):
    w = unicodedata.normalize("NFD", w.lower())
    return "".join(c for c in w if c.isalnum())


def similar(a, b):
    a, b = norm(a), norm(b)
    if not a or not b: return False
    if a == b: return True
    if min(len(a), len(b)) >= 2 and (a.startswith(b) or b.startswith(a) or a.endswith(b) or b.endswith(a)): return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.75


def join(prev, new, s0, e0, tol=0.4):
    """Join of two windows. In the zone [s0, e0] (new window's edge - 0.2 s, previous window's edge + 0.2 s) the same
    word may come from both: heard twice (edge with padding) or cut in half (split inside speech). A similar word with
    overlapping time in that zone: the join goes through it and keeps the version farther from its own window's edge
    (the other one is usually clipped); what the other window heard from there on in the zone goes too."""
    if not prev or not new or s0 >= e0: return prev + new
    for j, b in enumerate(new):
        if b["start"] >= e0: break
        for i in range(len(prev) - 1, -1, -1):
            a = prev[i]
            if a["end"] <= s0: break
            if similar(a["w"], b["w"]) and a["start"] < b["end"] + tol and b["start"] < a["end"] + tol:
                return prev[:i] + new[j:] if b["start"] - s0 > e0 - a["end"] else prev[:i + 1] + new[j + 1:]
    return prev + new


def finish(words, dur, runs=(), ext=0.5):
    """Fixes the end from the audio (token duration comes in 80 ms steps and is off by ~0.3 s either way): a word that
    goes past the end of its speech run stops there; the last word of the run extends to it (at most ext s more).
    The end never goes past the next word's start nor the audio duration."""
    out = []
    for i, w in enumerate(words):
        nxt = words[i + 1]["start"] if i + 1 < len(words) else dur
        end = w["end"]
        run = next((r for r in runs if r[0] - 0.3 <= w["start"] < r[1]), None)
        if run:
            if end > run[1] or (nxt > run[1] - 0.02 and run[1] - end <= ext): end = run[1]
        out.append({"w": w["w"], "start": w["start"], "end": round(float(max(min(end, nxt, dur), w["start"])), 3)})
    return out


def sentences(ws, max_gap=0.8, max_len=45):
    """One line per sentence (or pause of more than 0.8 s), like the dev-video-editing skill's transcribe.py."""
    out, cur = [], []
    for i, wd in enumerate(ws):
        cur.append(wd); nx = ws[i + 1] if i + 1 < len(ws) else None
        if nx is None or wd["w"][-1:] in ".?!" or nx["start"] - wd["end"] > max_gap or len(cur) >= max_len:
            out.append({"start": cur[0]["start"], "end": cur[-1]["end"], "text": " ".join(c["w"] for c in cur)}); cur = []
    return out


def stamp(t):
    return "%02d:%04.1f" % divmod(t, 60)


def write(out_dir, src, dur, words):
    """transcript.json + transcript.txt in out_dir. Returns (sentences, language code or None)."""
    os.makedirs(out_dir, exist_ok=True); sents = sentences(words); lang = lng.detect(words)
    with open(os.path.join(out_dir, "transcript.json"), "w", encoding="utf-8") as fh:
        json.dump({"source": "sherpa-onnx parakeet-tdt-0.6b-v3 (local)", "audio": os.path.abspath(src), "duration": dur,
                   "lang": lang, "words": words, "sentences": sents}, fh, ensure_ascii=False)
    with open(os.path.join(out_dir, "transcript.txt"), "w", encoding="utf-8") as fh:
        for s in sents: fh.write("[%s-%s] %s\n" % (stamp(s["start"]), stamp(s["end"]), s["text"]))
    return sents, lang


# ---------- model ----------

def check_model(d):
    miss = [f for f in MODEL_FILES if not os.path.isfile(os.path.join(d, f))]
    if miss:
        sys.exit(f"ERROR: incomplete model in {d} (missing {', '.join(miss)}). Download "
                 "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2 from the asr-models release of "
                 "github.com/k2-fsa/sherpa-onnx and extract it into models/ (see README), or pass --model-dir.")


def load_model(d, threads=4):
    try:
        import sherpa_onnx
    except ImportError:
        sys.exit("ERROR: sherpa-onnx is missing (pip install sherpa-onnx numpy).")
    j = lambda f: os.path.join(d, f)
    return sherpa_onnx.OfflineRecognizer.from_transducer(encoder=j(MODEL_FILES[0]), decoder=j(MODEL_FILES[1]),
            joiner=j(MODEL_FILES[2]), tokens=j(MODEL_FILES[3]), model_type="nemo_transducer", num_threads=threads)


def transcribe(rec, x, wins, runs=(), sr=SR, pad=0.2):
    """Decodes each window and joins the words in absolute time. An edge in silence gets pad s extra (weak speech at the
    start/end); an edge inside speech (quietest point) stays exact, otherwise both windows hear part of a word."""
    dur, words, e_prev = len(x) / sr, [], -1.0
    inside = lambda t: any(r0 < t < r1 for r0, r1 in runs)
    for s, e in wins:
        s0 = s if inside(s) else max(0.0, s - pad); e0 = e if inside(e) else min(dur, e + pad)
        st = rec.create_stream(); st.accept_waveform(sr, x[int(s0 * sr):int(e0 * sr)]); rec.decode_stream(st); r = st.result
        words = join(words, words_of(r.tokens, r.timestamps, getattr(r, "durations", None), s0), s - pad, e_prev + pad)
        e_prev = e
    return finish(words, dur, runs)


def main():
    ap = argparse.ArgumentParser(description="Local transcription with per-word times (Parakeet TDT v3).")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--video", help="original recording (.mov etc.); audio extracted by ffmpeg"); src.add_argument("--audio")
    dst = ap.add_mutually_exclusive_group(required=True)
    dst.add_argument("--name", help="writes to videos/<name>/"); dst.add_argument("--out", help="output folder")
    ap.add_argument("--model-dir", default=MODEL); ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--win", type=float, default=25.0, help="maximum window length (s)")
    ap.add_argument("--noise", type=float, default=-35.0, help="silence level (dB)")
    ap.add_argument("--min-sil", type=float, default=0.4, help="minimum silence between speech runs (s)")
    a = ap.parse_args()
    path = a.video or a.audio
    if not os.path.isfile(path): sys.exit(f"ERROR: {path} does not exist.")
    check_model(a.model_dir)
    out = os.path.join(ROOT, "videos", a.name) if a.name else a.out
    t0 = time.time(); x = decode(path); dur = len(x) / SR
    db = frame_db(x); runs = speech_runs(db, dur, noise=a.noise, min_sil=a.min_sil)
    wins = windows(runs, db, win=a.win, lo=min(15.0, a.win * 0.6))
    print("audio %.1f s (read in %.1f s); %d speech runs, %d windows" % (dur, time.time() - t0, len(runs), len(wins)), flush=True)
    t1 = time.time(); words = transcribe(load_model(a.model_dir, a.threads), x, wins, runs)
    sents, lang = write(out, path, dur, words)
    print("%d words, %d sentences in %.1f s -> %s" % (len(words), len(sents), time.time() - t1, out))
    if lang: print(f"language: {lang} ({lng.describe(words)})")
    else: print(f"language: unknown ({lng.describe(words)}); set \"lang\" in videos/<name>/edit.json before cuts.py")


if __name__ == "__main__":
    main()
