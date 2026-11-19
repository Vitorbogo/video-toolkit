#!/usr/bin/env python3
"""Renders one excerpt of a plan N ways (hard cut, punch-in, J-cut at two lengths, an L-cut...) so the author can
watch them side by side BEFORE a new cut technique gets code (issue #10). This step decided the J-cut (#8) and
caught two design bugs before any code.

Usage:
  python3 src/vtk/variants.py --preset videos/<name>/preset.json --video REC.mov \
      --plan videos/<name>/plan.json --join 2 --variants variants.json --out videos/<name>/variants
  # --join N: the join plan[N] | plan[N+1], --ctx seconds of each piece around it (default 3)
  # --range T0,T1: any range of the RECORDING instead (the plan's pieces clipped to it)

Variants (a JSON file or inline JSON): a list of {"name": .., key: value, ...}. Each variant changes ONE piece of
the excerpt, the target: in --join mode the piece the join leads into (plan[N+1]), else "piece" (index in the full
plan). Every other key is set on the target as it is ("z": 1.1, "j": [-0.3, "both"] = an L-cut); null removes it.
Shortcuts: "V" = voice-before-picture in seconds, measured from the target's first word (jcut.py's convention),
written as "j": [lead, "area"] with "area" (default "both"). A V whose borrowed footage would reach the target's
first word is skipped, and so is an L-cut longer than the removed gap or a lead that leaves a piece no picture.
Unlike cuts.py, WHY the gap was removed is not checked (filler, retake): the author is watching. A variant with only
a name renders the excerpt as the plan has it; in --range mode the plan's own J-cuts stay on the other pieces.
Default in --join mode: hard cut, punch-in 1.1, J-cut V 0.25 and 0.6 (add {"V": .., "area": "camera"} or "slide"
for one area only).

The excerpt is rendered by render.py, as the real video will be. Out: <tag>_<k>-<name>.mkv per variant (picture
and PCM sound copied from render.py's final.mov; its work/ is deleted) and <tag>_report.json (join measurements,
picture lead, frames, audio samples). The sound is the same in every variant; every output must have the same frame
count and audio length, or this exits with an error. Loudness (postaudio.py) is not applied: same for all,
irrelevant to the comparison.
"""
import argparse, copy, json, os, re, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.path.join(ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "src"))
from vtk import jcut, preset, render

CTX = 3.0  # seconds of each piece around a join
DEFAULT = [{"name": "hard", "j": None, "z": None}, {"name": "punch-in", "j": None, "z": 1.1},
           {"name": "J0.25", "V": 0.25, "z": None}, {"name": "J0.6", "V": 0.6, "z": None}]
NAME_RE = re.compile(r"^[\w.+-]+$")
RESERVED = ("name", "piece", "V", "area")  # variant keys that are not plan.json keys


def join_range(plan, n, ctx=CTX):
    """Recording range around the join plan[n] | plan[n+1]: ctx s before A's end, ctx s after B's start."""
    if not 0 <= n < len(plan) - 1:
        raise SystemExit(f"variants: no join {n} (the plan has {len(plan)} pieces, joins 0..{len(plan) - 2})")
    return plan[n]["e"] - ctx, plan[n + 1]["s"] + ctx


def _events(c, sh, d):
    """c's captions and word starts shifted by -sh and kept inside [0, d]."""
    ev, wt = [], []
    wts = c.get("wt") or []
    for k, (x0, x1, text) in enumerate(c.get("ev") or []):
        a, b = max(0.0, x0 - sh), min(d, x1 - sh)
        if b - a < 1e-6: continue
        ev.append([round(a, 4), round(b, 4), text])
        w = wts[k] if k < len(wts) else None
        wt.append([round(x - sh, 4) for x in w] if w else None)
    return ev, wt


def excerpt(plan, t0, t1):
    """The plan's pieces clipped to the recording range [t0, t1]: captions, word starts and blur rebased on each
    piece's new start. Each piece keeps "_i" = its index in the full plan. The first piece loses its "j" (the join
    before it is not in the excerpt)."""
    out = []
    for i, c in enumerate(plan):
        s, e = max(c["s"], t0), min(c["e"], t1)
        if e - s < 1e-6: continue
        sh, d = s - c["s"], e - s
        x = {k: copy.deepcopy(v) for k, v in c.items() if k not in ("ev", "wt", "blur")}
        x.update(s=round(s, 6), e=round(e, 6), _i=i)
        x["ev"], wt = _events(c, sh, d)
        if c.get("wt") is not None: x["wt"] = wt
        if c.get("blur"):
            blur = [[round(max(0.0, b[0] - sh), 4), round(b[1] - sh, 4)] + list(b[2:]) for b in c["blur"]
                    if b[1] - sh > 1e-6 and b[0] - sh < d - 1e-6]
            if blur: x["blur"] = blur
        out.append(x)
    if not out:
        raise SystemExit(f"variants: no piece of the plan in {t0:g}-{t1:g} s of the recording")
    out[0].pop("j", None)
    return out


def check_names(vs):
    names = [v.get("name") for v in vs]
    for n in names:
        if not isinstance(n, str) or not NAME_RE.match(n):
            raise SystemExit(f"variants: every variant needs a \"name\" usable in a file name (got {n!r})")
    if len(set(names)) != len(names):
        raise SystemExit("variants: two variants with the same name")


def _lead_problem(plan, k, lead, fps):
    """Why the picture lead on piece k can't be rendered, or None. The picture timeline is render.py's own
    (jcut.picture), so the other pieces' J-cuts count too. An L-cut (negative lead) longer than the removed gap
    would show the piece before still speaking under the next voice."""
    if k == 0: return "a J/L-cut needs a piece before the target in the excerpt"
    A, B = plan[k - 1], plan[k]
    try:
        jcut.picture(plan, [render.frames(c, fps) for c in plan], fps)
    except SystemExit:
        return f"a {lead:g} s lead leaves a piece with no picture (excerpt too short: --ctx, or a J-cut next to it)"
    if lead < 0 and -lead > B["s"] - A["e"] + 1e-6:
        return f"an L-cut of {-lead:g} s reaches past the removed gap ({B['s'] - A['e']:.2f} s): A still speaking"
    return None


def apply(ex, variant, k, fps):
    """Excerpt + one variant on its piece k -> (plan for render.py, report entry). The entry has "skipped" when
    the variant can't be rendered (a V longer than the silent footage). k None: a variant that changes nothing
    (the excerpt as the plan has it)."""
    check_names([variant])
    plan = copy.deepcopy(ex)
    if k is None:
        if any(key != "name" for key in variant):
            raise SystemExit(f"variants: {variant['name']}: say which piece it changes (\"piece\": index in plan.json)")
        for c in plan: c.pop("_i", None)
        return plan, {"name": variant["name"]}
    T = plan[k]
    info = {"name": variant["name"], "piece": T["_i"]}
    for key, val in variant.items():
        if key in RESERVED: continue
        if val is None: T.pop(key, None)
        else: T[key] = copy.deepcopy(val)
    if "area" in variant and "V" not in variant:
        raise SystemExit(f"variants: {variant['name']}: \"area\" goes with \"V\" (or write \"j\": [lead, area])")
    if "V" in variant:
        area = variant.get("area", "both")
        if area not in jcut.AREAS:
            raise SystemExit(f"variants: {variant['name']}: area {area!r}, expected one of {', '.join(jcut.AREAS)}")
        if k == 0:
            raise SystemExit(f"variants: {variant['name']}: V needs a piece before the target in the excerpt")
        w = jcut.onset(T)
        if w is None:
            raise SystemExit(f"variants: {variant['name']}: the target piece has no word to measure V from")
        V = variant["V"]
        if isinstance(V, bool) or not isinstance(V, (int, float)) or V <= 0:
            raise SystemExit(f"variants: {variant['name']}: V must be seconds > 0 (an L-cut is \"j\": [-lead, area])")
        V, pre = float(V), w - T["s"]
        avail = silent_footage(plan[k - 1], T)
        lead = jcut.snap_lead(V, pre, avail - pre, fps)
        T["j"] = [round(lead, 6), area]
        info.update(V=V, picture_lead_s=round(lead, 3), lead_silence_s=round(min(lead, pre), 3),
                    lead_speech_s=round(max(0.0, lead - pre), 3))
        if lead < V + pre - 1.0 / fps:
            info["skipped"] = f"needs {V + pre:.2f} s of silent footage after the cut, only {max(0.0, avail):.2f} s"
    if T.get("j") and not info.get("skipped"):
        info["skipped"] = _lead_problem(plan, k, float(T["j"][0]), fps)
        info.setdefault("picture_lead_s", round(float(T["j"][0]), 3))
    if not info.get("skipped"): info.pop("skipped", None)
    for c in plan: c.pop("_i", None)
    return plan, info


def silent_footage(A, B):
    """Seconds of footage after A's end that are still before B's first word (minus jcut's margin)."""
    return jcut.onset(B) - jcut.SPEECH_MARGIN - A["e"]


def frame_crc(path):
    """Per-frame CRC of the video stream (ffmpeg framecrc): compares pictures without ffprobe."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-map", "0:v", "-f", "framecrc", "-"],
                       capture_output=True, text=True)
    if r.returncode: raise SystemExit(f"variants: could not read {path}: {r.stderr[-300:]}")
    return [l.split(",")[-1].strip() for l in r.stdout.splitlines() if l and not l.startswith("#")]


def measure(path):
    """(video frames, audio samples at 48 kHz) of an output, by decoding it."""
    a = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-map", "0:a", "-f", "s16le", "-ac", "1",
                        "-ar", str(render.AR), "-"], capture_output=True)
    if a.returncode: raise SystemExit(f"variants: could not read the audio of {path}")
    return len(frame_crc(path)), len(a.stdout) // 2


def mismatches(measured):
    """{name: (frames, samples)} -> one error per variant whose length differs from the first one's."""
    items = list(measured.items())
    if not items: return []
    ref, (q0, a0) = items[0]
    return [f"{n}: {q} frames / {a} audio samples, {ref} has {q0} / {a0}" for n, (q, a) in items[1:]
            if (q, a) != (q0, a0)]


def load_variants(arg):
    if arg is None: return None
    if os.path.exists(arg):
        with open(arg, encoding="utf-8") as f: return json.load(f)
    return json.loads(arg)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Render one excerpt of a plan N ways, to compare side by side.")
    for k in ("--preset", "--video", "--plan", "--out"): ap.add_argument(k, required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--join", type=int, help="the join plan[N] | plan[N+1]")
    g.add_argument("--range", help="T0,T1 in recording seconds")
    ap.add_argument("--ctx", type=float, default=CTX, help="--join: seconds of each piece around the join")
    ap.add_argument("--variants", help="JSON file or inline JSON list (default in --join mode: hard, punch-in, J-cuts)")
    ap.add_argument("--tag", help="file name prefix (default j<N> or r<T0>-<T1>)")
    ap.add_argument("--scale", default="1.0"); ap.add_argument("--crf", default="20")
    a = ap.parse_args(argv)

    P = preset.load(a.preset); fps = P["canvas"]["fps"]
    with open(a.plan, encoding="utf-8") as f: plan = json.load(f)
    vs = load_variants(a.variants)
    if a.join is not None:
        t0, t1 = join_range(plan, a.join, a.ctx); target = a.join + 1
        tag = a.tag or f"j{a.join}"
        vs = DEFAULT if vs is None else vs
    else:
        try: t0, t1 = (float(x) for x in a.range.split(","))
        except ValueError: raise SystemExit("variants: --range T0,T1 (recording seconds)")
        target = None
        tag = a.tag or f"r{t0:g}-{t1:g}"
        if vs is None: raise SystemExit("variants: --range needs --variants")
    check_names(vs)
    ex = excerpt(plan, t0, t1)
    out = os.path.abspath(a.out); os.makedirs(out, exist_ok=True)

    report = {"tag": tag, "range": [round(t0, 3), round(t1, 3)], "variants": []}
    if a.join is not None:
        A, B = plan[a.join], plan[a.join + 1]; w = jcut.onset(B)
        report["join"] = {"n": a.join, "A_end": A["e"], "B_start": B["s"], "removed_gap_s": round(B["s"] - A["e"], 3)}
        if w is not None:
            report["join"].update(pre_silence_before_B_voice_s=round(w - B["s"], 3),
                                  silent_footage_after_A_s=round(silent_footage(A, B), 3))
    measured = {}
    for n, v in enumerate(vs):
        i = v.get("piece", target)
        k = next((k for k, c in enumerate(ex) if c["_i"] == i), None)
        if k is None and i is not None:
            raise SystemExit(f"variants: {v.get('name')}: piece {i} is not in the excerpt "
                             f"(pieces {[c['_i'] for c in ex]}; set \"piece\")")
        vplan, info = apply(ex, v, k, fps)
        report["variants"].append(info)
        if info.get("skipped"):
            print(f"skipped {v['name']}: {info['skipped']}"); continue
        work = os.path.join(out, "work", v["name"]); os.makedirs(work, exist_ok=True)
        pf = os.path.join(work, "plan.json")
        with open(pf, "w", encoding="utf-8") as f: json.dump(vplan, f, ensure_ascii=False, indent=1)
        render.main(["--preset", a.preset, "--video", a.video, "--plan", pf, "--out", work,
                     "--scale", a.scale, "--crf", a.crf])
        name = f"{tag}_{n}-{v['name']}.mkv"  # not .mov: the guard treats every .mov as an original recording
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", os.path.join(work, "final.mov"), "-c", "copy",
                            os.path.join(out, name)], capture_output=True, text=True)
        if r.returncode: raise SystemExit(f"variants: could not write {name}: {r.stderr[-300:]}")
        info["file"] = name
        info["frames"], info["samples"] = measured[v["name"]] = measure(os.path.join(out, name))
    with open(os.path.join(out, f"{tag}_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    shutil.rmtree(os.path.join(out, "work"), ignore_errors=True)  # render.py's .mov clips: the guard keeps .mov
    if not measured:
        raise SystemExit("variants: every variant was skipped (see the report): nothing to compare")
    if len(measured) == 1: print("only one variant rendered: nothing to compare it with")
    errs = mismatches(measured)
    if errs:
        raise SystemExit("variants: the outputs differ in length (they must not):\n  " + "\n  ".join(errs))
    print(f"{len(measured)} variants in {out} ({tag}_report.json), all {next(iter(measured.values()), (0, 0))[0]} frames")


if __name__ == "__main__":
    main()
