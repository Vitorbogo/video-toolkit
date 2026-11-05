#!/usr/bin/env python3
"""Transcricao com TEMPO POR PALAVRA, gratis e local (sherpa-onnx + NVIDIA Parakeet TDT v3, multilingue, inclui portugues).

  python3 src/vtk/transcribe_words.py --video GRAVACAO.mov --name <nome>      # -> videos/<nome>/transcript.json e .txt
  python3 src/vtk/transcribe_words.py --audio audio.wav --out work/ [--model-dir DIR]

Gera o formato que o src/vtk/engine.py lê: transcript.json com "words" ({w, start, end},
tempos absolutos em segundos) e "sentences", mais transcript.txt (uma linha por frase, com tempo). Resolucao de 80 ms.

O audio e decodificado pelo ffmpeg (mono 16 kHz, direto na memoria). Os silencios (abaixo de -35 dB por 0,4 s ou mais)
separam os trechos de fala; trechos vizinhos viram janelas de ate 25 s, com 0,2 s a mais nas bordas em silencio. Fala
continua com mais de 25 s e dividida no ponto mais silencioso (~80 ms) entre 15 e 25 s, nunca num tempo fixo; palavra
repetida na emenda das janelas sai. Fim da palavra = inicio + duracao do ultimo token (pontuacao nao mexe no fim), acertado
pelo inicio do silencio seguinte.

Modelo (487 MB) em models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8 (ignorado pelo git; como baixar: README).
Requer ffmpeg e `pip install sherpa-onnx numpy`.
"""
import argparse, difflib, json, os, shutil, subprocess, sys, time, unicodedata, wave
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODEL = os.path.join(ROOT, "models", "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8")
MODEL_FILES = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")
SR, FR, TOK = 16000, 0.02, 0.08      # taxa do modelo; quadro da deteccao de silencio; quadro do modelo (80 ms)
PUNCT = set(".,;:?!…")


# ---------- audio e silencios ----------

def decode(path):
    """Qualquer audio/video -> float32 mono 16 kHz. WAV mono 16 kHz 16 bits e lido direto; o resto passa pelo ffmpeg."""
    if path.lower().endswith(".wav"):
        try:
            with wave.open(path) as w:
                if (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (SR, 1, 2):
                    return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        except (wave.Error, EOFError):
            pass
    if not shutil.which("ffmpeg"):
        sys.exit(f"ERRO: {path} precisa do ffmpeg para virar mono 16 kHz (brew install ffmpeg), "
                 "ou passe um WAV mono 16 kHz 16 bits (ffmpeg -i X -vn -ac 1 -ar 16000 audio.wav).")
    p = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(SR),
                        "-f", "s16le", "-"], capture_output=True)
    if p.returncode or not p.stdout:
        sys.exit(f"ERRO: ffmpeg nao leu o audio de {path}: {p.stderr.decode('utf-8', 'replace').strip() or 'sem audio'}")
    return np.frombuffer(p.stdout, dtype=np.int16).astype(np.float32) / 32768


def frame_db(x, sr=SR, fr=FR):
    """Nivel RMS (dBFS) de cada quadro de fr segundos."""
    n = int(round(sr * fr)); m = len(x) // n
    rms = np.sqrt(np.mean(np.square(x[:m * n].reshape(m, n), dtype=np.float64), axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-10))


def speech_runs(db, dur, fr=FR, noise=-35.0, min_sil=0.4, min_speech=0.15):
    """Trechos de fala [[ini, fim]]: o que sobra entre silencios (abaixo de noise dB por min_sil s ou mais)."""
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
    """Centro dos ~80 ms mais silenciosos entre a e b segundos."""
    k = max(1, int(round(span / fr))); i0 = int(a / fr); i1 = min(len(db), int(b / fr))
    if i1 - i0 < k: return round((a + b) / 2, 3)
    p = np.convolve(10 ** (db[i0:i1] / 10), np.ones(k) / k, mode="valid")
    return round(float((i0 + int(np.argmin(p)) + k / 2) * fr), 3)


def windows(runs, db, win=25.0, lo=15.0, fr=FR):
    """Janelas de ate win s: trechos vizinhos se juntam; trecho maior que win e dividido no ponto mais silencioso
    entre lo e win s do seu inicio (nunca num tempo fixo)."""
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


# ---------- tokens -> palavras ----------

def words_of(tokens, timestamps, durations=None, offset=0.0):
    """Tokens do Parakeet -> [{w, start, end}]. Token com espaco inicia palavra; pontuacao gruda na palavra anterior
    sem mexer no fim. Fim = inicio do ultimo token + sua duracao (sem durations: + 0,16 s)."""
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
    """Emenda de duas janelas. Na zona [s0, e0] (borda da nova - 0,2 s, borda da anterior + 0,2 s) a mesma palavra pode
    vir das duas: ouvida duas vezes (borda com folga) ou cortada ao meio (divisao na fala). Palavra parecida, com tempo
    sobreposto, nessa zona: a emenda passa por ela e fica a versao mais longe da borda da propria janela (a outra
    costuma vir cortada); o que a outra janela ouviu dali em diante na zona sai junto."""
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
    """Acerta o fim pelo audio (a duracao do token vem em passos de 80 ms e erra uns 0,3 s para os dois lados):
    palavra que passa do fim do seu trecho de fala para nele; a ultima do trecho vai ate ele (no maximo ext s a mais).
    Fim nunca passa do inicio da palavra seguinte nem da duracao do audio."""
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
    """Uma linha por frase (ou pausa de mais de 0,8 s), como o transcribe.py da skill dev-video-editing."""
    out, cur = [], []
    for i, wd in enumerate(ws):
        cur.append(wd); nx = ws[i + 1] if i + 1 < len(ws) else None
        if nx is None or wd["w"][-1:] in ".?!" or nx["start"] - wd["end"] > max_gap or len(cur) >= max_len:
            out.append({"start": cur[0]["start"], "end": cur[-1]["end"], "text": " ".join(c["w"] for c in cur)}); cur = []
    return out


def stamp(t):
    return "%02d:%04.1f" % divmod(t, 60)


def write(out_dir, src, dur, words):
    """transcript.json + transcript.txt em out_dir. Retorna as frases."""
    os.makedirs(out_dir, exist_ok=True); sents = sentences(words)
    with open(os.path.join(out_dir, "transcript.json"), "w", encoding="utf-8") as fh:
        json.dump({"source": "sherpa-onnx parakeet-tdt-0.6b-v3 (local)", "audio": os.path.abspath(src), "duration": dur,
                   "words": words, "sentences": sents}, fh, ensure_ascii=False)
    with open(os.path.join(out_dir, "transcript.txt"), "w", encoding="utf-8") as fh:
        for s in sents: fh.write("[%s-%s] %s\n" % (stamp(s["start"]), stamp(s["end"]), s["text"]))
    return sents


# ---------- modelo ----------

def check_model(d):
    miss = [f for f in MODEL_FILES if not os.path.isfile(os.path.join(d, f))]
    if miss:
        sys.exit(f"ERRO: modelo incompleto em {d} (falta {', '.join(miss)}). Baixar do release asr-models de "
                 "github.com/k2-fsa/sherpa-onnx o arquivo sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2 e extrair "
                 "em models/ (ver README), ou passar --model-dir.")


def load_model(d, threads=4):
    try:
        import sherpa_onnx
    except ImportError:
        sys.exit("ERRO: falta o sherpa-onnx (pip install sherpa-onnx numpy).")
    j = lambda f: os.path.join(d, f)
    return sherpa_onnx.OfflineRecognizer.from_transducer(encoder=j(MODEL_FILES[0]), decoder=j(MODEL_FILES[1]),
            joiner=j(MODEL_FILES[2]), tokens=j(MODEL_FILES[3]), model_type="nemo_transducer", num_threads=threads)


def transcribe(rec, x, wins, runs=(), sr=SR, pad=0.2):
    """Decodifica cada janela e emenda as palavras em tempo absoluto. Borda em silencio ganha pad s a mais (fala fraca
    no comeco/fim); borda no meio da fala (ponto mais silencioso) fica exata, senao as duas janelas ouvem pedaco de palavra."""
    dur, words, e_prev = len(x) / sr, [], -1.0
    inside = lambda t: any(r0 < t < r1 for r0, r1 in runs)
    for s, e in wins:
        s0 = s if inside(s) else max(0.0, s - pad); e0 = e if inside(e) else min(dur, e + pad)
        st = rec.create_stream(); st.accept_waveform(sr, x[int(s0 * sr):int(e0 * sr)]); rec.decode_stream(st); r = st.result
        words = join(words, words_of(r.tokens, r.timestamps, getattr(r, "durations", None), s0), s - pad, e_prev + pad)
        e_prev = e
    return finish(words, dur, runs)


def main():
    ap = argparse.ArgumentParser(description="Transcricao local com tempo por palavra (Parakeet TDT v3).")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--video", help="gravacao original (.mov etc.); o audio sai pelo ffmpeg"); src.add_argument("--audio")
    dst = ap.add_mutually_exclusive_group(required=True)
    dst.add_argument("--name", help="escreve em videos/<nome>/"); dst.add_argument("--out", help="pasta de saida")
    ap.add_argument("--model-dir", default=MODEL); ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--win", type=float, default=25.0, help="duracao maxima de uma janela (s)")
    ap.add_argument("--noise", type=float, default=-35.0, help="nivel de silencio (dB)")
    ap.add_argument("--min-sil", type=float, default=0.4, help="silencio minimo entre trechos de fala (s)")
    a = ap.parse_args()
    path = a.video or a.audio
    if not os.path.isfile(path): sys.exit(f"ERRO: {path} nao existe.")
    check_model(a.model_dir)
    out = os.path.join(ROOT, "videos", a.name) if a.name else a.out
    t0 = time.time(); x = decode(path); dur = len(x) / SR
    db = frame_db(x); runs = speech_runs(db, dur, noise=a.noise, min_sil=a.min_sil)
    wins = windows(runs, db, win=a.win, lo=min(15.0, a.win * 0.6))
    print("audio %.1f s (lido em %.1f s); %d trechos de fala, %d janelas" % (dur, time.time() - t0, len(runs), len(wins)), flush=True)
    t1 = time.time(); words = transcribe(load_model(a.model_dir, a.threads), x, wins, runs)
    sents = write(out, path, dur, words)
    print("%d palavras, %d frases em %.1f s -> %s" % (len(words), len(sents), time.time() - t1, out))


if __name__ == "__main__":
    main()
