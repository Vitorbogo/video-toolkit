#!/usr/bin/env python3
"""Deterministic audio treatment, in 2 passes, over the assembled video.

Chain (fixed order, parameters in the preset): high-pass filter -> noise reduction (afftdn, OFF in the preset:
it made the voice robotic with the microphone used) -> gentle compressor -> pre-limiter -> loudnorm measured
(pass 1) and applied LINEAR (pass 2: fixed gain, no pumping) -> final limiter.
The video is copied without re-encoding; audio comes out as AAC 48 kHz. Accepts render.py's final.mov (h264 + PCM).

Pre-limiter: loudnorm only applies linear gain if measured peak + gain <= target peak. Real speech has short peaks
(plosives) far above the average level; without a pre-limiter loudnorm silently falls back to dynamic mode. With
"pre_limiter": "auto" pass 1 computes the limit that makes linear possible (with headroom) and measures again.
A number < 1 in the preset is a fixed limit (linear, 0-1) always applied; "auto" still lowers it further if needed.
Final peak: planned for TP - tp_margin_db (headroom for AAC, which raises the peak). The result is measured; if the
peak exceeds the target, it redoes it with more headroom. Off target (|I - target| > 0.5 LU or peak > TP):
exits with an error.

Sound effects (optional): --sfx videos/<name>/sfx.json mixes the effects from sfx/ (src/vtk/sfx.py, skill
sound-effects) into an intermediate PCM file before the chain; the final loudness stays on target. They go through
the compressor together with the voice (2:1, gentle: doesn't change their sound audibly).

Usage: python3 src/vtk/postaudio.py --preset presets/tiktok-vertical.json --in final.mov --out final.mp4 [--sfx sfx.json]
"""
import argparse, json, math, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.path.join(ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "src"))
from vtk import preset, sfx

TOL_I = 0.5           # LU tolerance on the integrated loudness of the result
LIMIT_MIN_DB = -24.0  # lowest alimiter limit (0.0625)
STEP_DB = 0.2         # extra headroom on each new pre-limit / new attempt


def db(x): return 20 * math.log10(x)
def lin(d): return 10 ** (d / 20)


def parse_loudnorm(stderr):
    """loudnorm JSON (print_format=json) in ffmpeg's stderr -> dict with floats ('-inf' becomes -inf)."""
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", stderr, re.S)
    if not m: return None
    out = {}
    for k, v in json.loads(m.group(0)).items():
        try: out[k] = float(v)
        except ValueError: out[k] = v
    return out


def check_preset(A):
    for k in ("highpass_hz", "compressor", "loudnorm", "bitrate"):
        if k not in A: sys.exit("preset: missing audio.%s" % k)
    for k in ("I", "TP", "LRA"):
        if k not in A["loudnorm"]: sys.exit("preset: missing audio.loudnorm.%s" % k)
    pl = A.get("pre_limiter", "auto")
    if pl != "auto" and not (isinstance(pl, (int, float)) and 0.0625 <= pl <= 1):
        sys.exit("preset: audio.pre_limiter must be \"auto\" or a number between 0.0625 and 1 (got %r)" % (pl,))
    tm = A.get("tp_margin_db", 1.0)
    if not isinstance(tm, (int, float)) or tm < 0: sys.exit("preset: audio.tp_margin_db must be a number >= 0 (got %r)" % (tm,))
    if "limiter" in A:
        print("warning: the preset's audio.limiter is no longer used (final limit = TP - tp_margin_db)")


def chain(A, pre_db=None):
    """Filters before loudnorm. pre_db = pre-limiter limit in dBFS (None = no pre-limiter).
    Everything at 192 kHz in both passes: pass 1's loudnorm forces 192 kHz and ffmpeg pulled the whole chain to
    that rate, but in pass 2 (linear) it ran at 48 kHz. A limiter at 48 kHz doesn't see inter-sample peaks,
    and the true peak came out ~2 dB above the measured one. At 192 kHz the limiter acts on the true peak."""
    f = ["aresample=192000", f"highpass=f={A['highpass_hz']}"]
    dn = A.get("denoise") or {}
    if dn.get("enabled"):
        f.append(f"afftdn=nr={dn['nr_db']}:nf={dn['noise_floor_db']}")
    c = A["compressor"]
    f.append(f"acompressor=threshold={c['threshold_linear']}:ratio={c['ratio']}:attack={c['attack_ms']}"
             f":release={c['release_ms']}:makeup={c['makeup']}")
    if pre_db is not None:
        # level=0: alimiter's auto-level would raise the gain back; latency=1: no ~5 ms audio delay
        f.append(f"alimiter=limit={lin(pre_db):.6f}:attack=5:release=50:level=0:latency=1")
    return ",".join(f)


def excess(m, I, tp_plan):
    """How much (dB) the peak would exceed tp_plan with linear gain up to I. <= 0: linear is possible."""
    return m["input_tp"] + (I - m["input_i"]) - tp_plan


def next_pre_db(m, I, tp_plan, cur_db):
    """Next pre-limiter limit: lowers the peak by the excess, plus headroom (the loudness drops a little too)."""
    base = m["input_tp"] if cur_db is None else min(cur_db, m["input_tp"])
    return base - excess(m, I, tp_plan) - STEP_DB


def ffmpeg_ln(args):
    try: r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats"] + args, capture_output=True, text=True)
    except FileNotFoundError: sys.exit("ffmpeg not found in PATH")
    return r, parse_loudnorm(r.stderr)


def measure(inp, af, base):
    r, m = ffmpeg_ln(["-i", inp, "-map", "0:a:0", "-af", f"{af},loudnorm={base}:print_format=json", "-f", "null", "-"])
    if m is None:
        if "matches no streams" in r.stderr: sys.exit("%s has no audio track" % inp)
        print(r.stderr[-800:]); sys.exit("could not measure the loudness of %s" % inp)
    if not math.isfinite(m["input_i"]) or m["input_i"] <= -70:
        sys.exit("silent audio (loudness %s LUFS) in %s: check the audio track" % (m["input_i"], inp))
    return m


def plan(inp, A, base, margin):
    """Pass 1 (+ re-measurements): finds the pre-limit that keeps linear gain within TP - margin."""
    I, tp_plan = A["loudnorm"]["I"], A["loudnorm"]["TP"] - margin
    pl = A.get("pre_limiter", "auto")
    pre = db(pl) if isinstance(pl, (int, float)) and pl < 1 else None
    for _ in range(6):
        m = measure(inp, chain(A, pre), base)
        print("measured%s: %.2f LUFS, peak %.2f dBTP, LRA %.2f -> gain %+.2f dB, predicted peak %.2f (plan %.2f)" % (
            "" if pre is None else " (pre-limit %.2f dBFS)" % pre, m["input_i"], m["input_tp"], m["input_lra"],
            I - m["input_i"], m["input_tp"] + I - m["input_i"], tp_plan))
        if excess(m, I, tp_plan) <= 0: return pre, m
        pre = next_pre_db(m, I, tp_plan, pre)
        if pre < LIMIT_MIN_DB:
            sys.exit("peaks too high to reach %s LUFS with peak %s: would need to limit to %.1f dBFS (minimum %.0f)"
                     % (I, A["loudnorm"]["TP"], pre, LIMIT_MIN_DB))
    sys.exit("could not find a pre-limit that allows linear loudnorm")


def encode(inp, out, A, base, pre, m, margin):
    """Pass 2: linear loudnorm with the measured values -> AAC. Returns normalization_type."""
    ln2 = (f"loudnorm={base}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
           f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true:print_format=json")
    final = lin(A["loudnorm"]["TP"] - margin)
    af = f"{chain(A, pre)},{ln2},alimiter=limit={final:.6f}:level=0:latency=1,aresample=48000"
    r, j = ffmpeg_ln(["-y", "-i", inp, "-map", "0:v?", "-map", "0:a:0", "-c:v", "copy", "-af", af,
                      "-c:a", "aac", "-b:a", A["bitrate"], "-ar", "48000", "-movflags", "+faststart", out])
    if r.returncode or j is None:
        print(r.stderr[-800:]); sys.exit("ffmpeg failed in pass 2")
    return j["normalization_type"]


def mix_sfx(inp, cues, tmp):
    """Mixes the effects into the audio track (PCM, video copied) and returns the path of the intermediate file."""
    errors = sfx.check(cues)
    if errors: sys.exit("sfx.json has problems:\n  " + "\n  ".join(errors))
    missing = sorted({c["sound"] for c in cues if not os.path.exists(sfx.path(c["sound"]))})
    if missing: sys.exit("missing files in sfx/: %s (run src/vtk/sfx.py generate)" % missing)
    ins = [x for c in cues for x in ("-i", sfx.path(c["sound"]))]
    try:
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", inp, *ins, "-filter_complex",
                            "[0:a:0]anull[voice];" + sfx.mix_filter(cues), "-map", "0:v?", "-map", "[mix]",
                            "-c:v", "copy", "-c:a", "pcm_s16le", "-ar", "48000", "-f", "mov", tmp],
                           capture_output=True, text=True)
    except FileNotFoundError: sys.exit("ffmpeg not found in PATH")
    if r.returncode: print(r.stderr[-800:]); sys.exit("ffmpeg failed to mix the effects")
    print("sound effects: %d mixed" % len(cues))
    return tmp


def run(inp, out, A, cues=()):
    check_preset(A)
    if cues:
        inp = mix_sfx(inp, list(cues), os.path.splitext(out)[0] + ".sfx.mov")
    ln = A["loudnorm"]; base = f"I={ln['I']}:TP={ln['TP']}:LRA={ln['LRA']}"
    root, ext = os.path.splitext(out); tmp = root + ".tmp" + ext
    margin = float(A.get("tp_margin_db", 1.0))
    for attempt in range(3):
        pre, m = plan(inp, A, base, margin)
        nt = encode(inp, tmp, A, base, pre, m, margin)
        print("pass 2: normalization_type=%s" % nt)
        if nt != "linear":
            print("warning: loudnorm fell back to dynamic mode (loudness varies over the video); check the pre-limiter")
        k = measure(tmp, "anull", base)
        print("result: %.2f LUFS, peak %.2f dBTP (target %s LUFS, peak <= %s)" % (k["input_i"], k["input_tp"], ln["I"], ln["TP"]))
        if k["input_tp"] > ln["TP"] and attempt < 2:
            margin += k["input_tp"] - ln["TP"] + STEP_DB
            print("peak above target after AAC: redoing with %.2f dB headroom" % margin); continue
        break
    if abs(k["input_i"] - ln["I"]) > TOL_I or k["input_tp"] > ln["TP"]:
        sys.exit("off target: %.2f LUFS (target %s +-%s), peak %.2f dBTP (max %s). File kept at %s for checking"
                 % (k["input_i"], ln["I"], TOL_I, k["input_tp"], ln["TP"], tmp))
    os.replace(tmp, out); print("ok:", out)
    if cues and os.path.exists(inp): os.remove(inp)  # the intermediate file with the effects
    return {"I": k["input_i"], "TP": k["input_tp"], "normalization_type": nt, "pre_limit_db": pre, "margin_db": margin}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--preset", required=True); ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True, help="output video (.mp4)")
    ap.add_argument("--sfx", help="videos/<name>/sfx.json (sound effects, skill sound-effects)")
    a = ap.parse_args(argv)
    if not os.path.exists(a.inp): sys.exit("%s not found" % a.inp)
    if os.path.abspath(a.inp) == os.path.abspath(a.out): sys.exit("--out must be different from --in")
    cues = []
    if a.sfx:
        with open(a.sfx, encoding="utf-8") as f: cues = json.load(f)
    return run(a.inp, a.out, preset.load(a.preset)["audio"], cues)


if __name__ == "__main__":
    main()
