#!/usr/bin/env python3
"""Decide the cuts with the engine (src/vtk/engine.py, derived from the dev-video-editing skill, MIT) and write render.py's plan.json.

Usage:
  python3 src/vtk/cuts.py --video RECORDING.mov --name <name>
      [--transcript T] [--edit E] [--preset P] [--lang pt|en] [--zoom [1.1]] [--no-scenes] [--force]
Defaults: --transcript videos/<name>/transcript.json; --edit videos/<name>/edit.json (if it exists);
--preset videos/<name>/preset.json (if it exists) or presets/tiktok-vertical.json (canvas fps, default 30).
Writes videos/<name>/plan.json (draft: captions with Parakeet's text, REVIEW with the author) and
videos/<name>/edit-plan.md (every removal, rebuilt from the final pieces, with its reasons). Does not overwrite
an existing plan.json without --force; with --force the previous one is kept in plan.json.bak.

Spoken language (pt, en): --lang > "lang" in edit.json > "lang" in transcript.json > detected from the transcript
words (src/vtk/lang.py). It picks presets/fillers-<lang>.json: fillers, crutch words and caption line breaks.

edit.json (optional; times in seconds in the original recording). The skill's keys (style, pauses, cut, keep,
replace, extra_fillers...) and ours (trim, zoom, blur, lang):
  "cut":  [[a, b, "note"]]  removes the whole words inside the range (warning if it catches none)
  "keep": [[a, b]]          keeps the words in the range (wins over the automatic cuts)
  "replace": {"chat GPT": "ChatGPT"}  applied to each caption's text (keys may have more than one word)
  "trim": [[a, b, "note"]]  removes the raw range, with or without words (warning if it cuts part of a kept word)
  "zoom": [[t, z]]          "z" on the piece that contains time t (max 1.2; z <= 1 removes the zoom)
  "blur": [[t0, t1, x, y, w, h, "note"]]  blur box; x/y/w/h in pixels of the original recording
  "lang": "en"              spoken language, when detection gets it wrong or can't tell
Every manual decision goes in edit.json: --force rebuilds plan.json without losing anything (a repeated caption
fix goes in "replace"). The language's fillers (presets/fillers-<lang>.json) always apply; edit.json's add to them.
Automatic zoom is optional and OFF: use --zoom only when the jump cuts feel abrupt. With it, the skill's rule
(alternate zoom/no zoom at cuts of 1 s or more, or after 4 s on the same framing) sets "z" on the pieces; edit.json's
"zoom" goes on top.

plan.json: [{"s", "e", "ev": [[x0, x1, "text"]], "wt": [[start of each word]], "z"?, "blur"?: [[t0, t1, x, y, w, h]]}];
s/e on the frame, ev and blur relative to s.
"""
import argparse, json, math, os, re, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))
from vtk import engine as ev
from vtk import lang as lng
from vtk import preset

PRE_ROLL = 0.10   # same as the skill's PRE_ROLL: a piece never opens less than this before a word
TAIL = 0.03       # slack after a word (the skill's, when there is no audio measurement)
MIN_GAP = 0.12    # a cut shorter than this is a pointless jump cut (same limit as the skill)
MIN_PIECE = 0.4   # a piece shorter than this flickers (same limit as the skill)
MIN_CAP = 1.0     # a caption stays at least this long on screen, if there is room
MAX_ZOOM = 1.2
REASONS = {"cut": "cut by hand", "short": "short piece"}  # engine reason -> edit-plan.md (others as they are)


def fr(t, fps, how=round):
    """Time on the frame (round, math.floor or math.ceil), without floating point noise."""
    return how(round(t * fps, 6)) / fps


def inside(w, a, b):
    """Same rule as the skill's 'cut'/'keep': whole word inside the range, with 20 ms of slack."""
    return w["start"] >= a - 0.02 and w["end"] <= b + 0.02


def overlap(x, y, w):
    """How much of word w falls in [x, y] (negative if none)."""
    return min(y, w["end"]) - max(x, w["start"])


def kept_words(words, reason):
    return [w for w, r in zip(words, reason) if r is None]


def exclude(words, reason, spans, fps):
    """Remove the sound of the removed words from the pieces. The skill leaves part of the pause (a 'breath') and,
    when the removed word sits in that pause, a bit of it stays audible. The cut goes from the frame before the word
    to the frame after (a short word takes some of the pause with it, up to 0.12 s), without entering the previous
    kept word's tail nor the next one's pre-roll; leftover without speech shorter than 0.4 s goes too. If the cut
    would leave a jump cut < 0.12 s or a piece with speech < 0.4 s, it doesn't cut and the word comes back
    (reason None), so captions and audio match."""
    for i, w in enumerate(words):
        if reason[i] is None or not any(overlap(s, e, w) > 0 for s, e in spans): continue
        kept = kept_words(words, reason)
        has_speech = lambda x, y: any(overlap(x, y, k) > 0.01 for k in kept)
        prv = [k["end"] for k in kept if k["end"] <= w["start"]]
        nxt = [k["start"] for k in kept if k["start"] >= w["end"]]
        lo = fr(max(prv) + TAIL, fps, math.ceil) if prv else 0.0
        hi = fr(min(nxt) - PRE_ROLL, fps, math.floor) if nxt else math.inf
        a, b = max(lo, fr(w["start"], fps, math.floor)), min(hi, fr(w["end"], fps, math.ceil))
        if b - a < MIN_GAP: b = min(hi, fr(a + MIN_GAP, fps, math.ceil))  # short word: takes the pause with it
        if b - a < MIN_GAP: a = max(lo, fr(b - MIN_GAP, fps, math.floor))
        out, ok = [], b - a >= MIN_GAP
        for s, e in (spans if ok else ()):
            if e <= a or s >= b: out.append((s, e)); continue
            for x, y in ((s, a), (b, e)):
                if y <= x or (y - x < MIN_PIECE and not has_speech(x, y)): continue
                ok = ok and y - x >= MIN_PIECE
                out.append((x, y))
        holes = set(zip([e for _, e in spans], [s for s, _ in spans[1:]]))
        if ok and all(q - p >= MIN_GAP or (p, q) in holes for (_, p), (q, _) in zip(out, out[1:])):
            spans = out
        elif sum(max(0, overlap(s, e, w)) for s, e in spans) > (w["end"] - w["start"]) / 2:
            reason[i] = None
    return spans


def trim(words, reason, spans, ranges, fps, warnings):
    """edit.json's 'trim': removes the raw range from the pieces (on the nearest frame)."""
    for it in ranges:
        a, b = fr(float(it[0]), fps), fr(float(it[1]), fps)
        for w, r in zip(words, reason):
            if r is None and overlap(a, b, w) > 0:
                warnings.append(f"trim {a:.2f}-{b:.2f} cuts part of \"{w['w']}\" ({w['start']:.2f}-{w['end']:.2f}), a kept word")
        spans = [(x, y) for s, e in spans for x, y in (((s, e),) if e <= a or s >= b else ((s, a), (b, e))) if y > x]
    return spans


def finish(words, reason, spans, fps, total, warnings):
    """Edges on the frame: the start moves up to after the previous kept word, the end down to before the next one;
    touching pieces become one; a piece < 0.4 s goes (with a warning, if it had speech)."""
    kept = kept_words(words, reason)
    out = []
    for s, e in sorted(spans):
        s2, e2 = max(0.0, fr(s, fps)), min(fr(e, fps), fr(total, fps, math.floor))
        if s2 < s and any(s2 < k["end"] <= s for k in kept): s2 = fr(s, fps, math.ceil)
        if e2 > e and any(e <= k["start"] < e2 for k in kept): e2 = fr(e, fps, math.floor)
        if out and s2 <= out[-1][1] + 1e-6: out[-1] = (out[-1][0], max(out[-1][1], e2))
        elif e2 > s2: out.append((s2, e2))
    final = []
    for s, e in out:
        if e - s >= MIN_PIECE - 1e-6: final.append((round(s, 6), round(e, 6))); continue
        ws = [k for k in kept if overlap(s, e, k) > 0.01]
        if ws:
            warnings.append(f"piece {s:.2f}-{e:.2f} shorter than {MIN_PIECE} s removed, and with it \"{' '.join(k['w'] for k in ws)}\"")
            for k in ws: reason[words.index(k)] = "short"
    return final


def removals(words, reason, spans, total, trims=()):
    """Removals from the final pieces (opening, gaps, end): (start, end, reasons, words).
    Reasons = those of the removed words inside, "trim" if an edit.json trim covers the gap, and "silence" when most
    of it has no word."""
    b = [0.0] + [t for s, e in spans for t in (s, e)] + [total]
    out = []
    for x, y in zip(b[::2], b[1::2]):
        if y - x < 0.01: continue
        ins = [(w, r) for w, r in zip(words, reason) if x <= (w["start"] + w["end"]) / 2 < y]
        why = {REASONS.get(r.split(":")[0], r.split(":")[0]) for _, r in ins if r}
        if any(min(y, float(t[1])) - max(x, float(t[0])) > 0.01 for t in trims): why.add("trim")
        why = sorted(why)
        if sum(max(0, overlap(x, y, w)) for w, _ in ins) < (y - x) / 2 or not why: why.append("silence")
        out.append((x, y, ", ".join(why), " ".join(w["w"] for w, r in ins if r)))
    return out


def caption_text(ws, rep):
    t = ev.apply_replace(" ".join(w[2] for w in ws), rep)
    return re.sub(r"([,;:])\1+", r"\1", t)  # "ocupação" -> "ocupação," when Parakeet already added the comma


def split_lines(ws, max_chars, rep, lp):
    """Sentence -> pieces of up to max_chars: as few as possible, balanced (no orphan word). Avoids breaking after a
    short word (lp["short_words"]), prefers after a comma or before "and", "but"... (lp["break_before"]); never
    breaks inside a replace key ("chat GPT")."""
    raw, pos = "", []
    for w in ws:
        pos.append(len(raw) + bool(raw)); raw += " " * bool(raw) + w[2]
    glued = set()
    for a in rep:
        for m in re.finditer(r"\b" + re.escape(a) + r"\b", raw, flags=re.I):
            glued |= set([k for k, p in enumerate(pos) if p < m.end() and p + len(ws[k][2]) > m.start()][:-1])
    penalty = max_chars ** 2 / 12
    best = [(0, 0, 0.0, None)] + [None] * len(ws)  # (pieces too long, pieces, cost, start)
    for j in range(1, len(ws) + 1):
        if j < len(ws) and j - 1 in glued: continue
        for i in range(j):
            if best[i] is None: continue
            n = len(caption_text(ws[i:j], rep))
            c = n * n
            if j < len(ws):
                last = ws[j - 1][2]
                c += (penalty * (ev.clean(last) in lp["short_words"]) - penalty * (last[-1:] in ",;:")
                      - penalty / 2 * (ev.clean(ws[j][2]) in lp["break_before"]))
            cand = (best[i][0] + (n > max_chars and j - i > 1), best[i][1] + 1, best[i][2] + c, i)
            if best[j] is None or cand[:3] < best[j][:3]: best[j] = cand
    out, j = [], len(ws)
    while j: out.insert(0, ws[best[j][3]:j]); j = best[j][3]
    return out


def captions(ws, d, max_chars, rep, lp):
    """Kept words [(t0, t1, word)] in the time of the cut video (d = duration) -> [[t0, t1, text, starts]],
    with starts = start of each word of the caption (plan.json's "wt", to highlight the spoken word).
    Breaks at sentences, in balanced pieces; each caption stays at least 1 s on screen, stretching up to the next;
    if even that doesn't reach 1 s, it joins a neighbour when that fits in max_chars."""
    groups, cur = [], []
    for w in ws:
        cur.append(w)
        if w[2][-1:] in ".?!": groups += split_lines(cur, max_chars, rep, lp); cur = []
    if cur: groups += split_lines(cur, max_chars, rep, lp)
    k = 0
    while k < len(groups):
        g = groups[k]
        if (groups[k + 1][0][0] if k + 1 < len(groups) else d) - g[0][0] < MIN_CAP:  # not 1 s even stretched
            if k and g[0][0] - groups[k - 1][-1][1] < 1.0 and len(caption_text(groups[k - 1] + g, rep)) <= max_chars:
                groups[k - 1:k + 1] = [groups[k - 1] + g]; k -= 1; continue
            if k + 1 < len(groups) and groups[k + 1][0][0] - g[-1][1] < 1.0 and len(caption_text(g + groups[k + 1], rep)) <= max_chars:
                groups[k:k + 2] = [g + groups[k + 1]]; continue
        k += 1
    return [[g[0][0], max(g[-1][1], min(g[0][0] + MIN_CAP, groups[k + 1][0][0] if k + 1 < len(groups) else d)),
             caption_text(g, rep), [w[0] for w in g]] for k, g in enumerate(groups)]


def decide(words, edit, total, fps=30.0, db=(), floor=-60.0, blacks=(), scenes=(), max_chars=60, zoom=0,
           warnings=None, lang="pt"):
    """Returns (plan, removed, possible_retakes). Times of 'removed' and 'possible_retakes' in the original recording.
    zoom > 1 turns on the skill's zoom suggestion (camera only, in render.py); 0 leaves every piece unzoomed.
    lang = spoken language (main() resolves it): its preset's 'fillers' and 'extra_fillers' are merged with edit.json's;
    the skill's other keys go straight to it. 'warnings' (list) gets what needs review."""
    warnings = [] if warnings is None else warnings
    lp = lng.load(lang)
    spec = {**edit, **{k: lp[k] + [x for x in edit.get(k, []) if x not in lp[k]] for k in ("fillers", "extra_fillers")}}
    for it in spec.get("cut", []):
        if not any(inside(w, float(it[0]), float(it[1])) for w in words):
            warnings.append(f"cut {it[0]}-{it[1]} catches no whole word (range without words: use \"trim\")")
    reason, maybe = ev.mark(words, spec)
    for it in spec.get("trim", []):
        for i, w in enumerate(words):
            if inside(w, float(it[0]), float(it[1])): reason[i] = reason[i] or "trim: " + (it[2] if len(it) > 2 else "by hand")
    spans, _ = ev.plan_spans(words, reason, spec, total, fps, list(db), floor, list(blacks), list(scenes))
    spans = exclude(words, reason, spans, fps)
    spans = trim(words, reason, spans, spec.get("trim", []), fps, warnings)
    spans = finish(words, reason, spans, fps, total, warnings)
    if not spans: sys.exit("cuts: no piece left; check 'cut' and 'trim' in edit.json")
    removed = removals(words, reason, spans, total, spec.get("trim", []))
    first = {w["start"]: i for i, w in reversed(list(enumerate(words)))}
    maybe = [m for m in maybe if not all(reason[first[m[0]]:first[m[0]] + len(m[1].split())])]
    # captions in the time of the cut video (a sentence may cross a cut), then split across the pieces;
    # capital letter at the start and after a sentence end (kept or removed), like the skill's caption_events
    rep, prv, out, off = spec.get("replace", {}), None, [], [0.0]
    for s, e in spans: off.append(off[-1] + e - s)
    for i, (w, r) in enumerate(zip(words, reason)):
        if r is not None: continue
        t = w["w"]
        if (prv is None or prv[-1:] in ".?!" or (reason[i - 1] and words[i - 1]["w"][-1:] in ".?!")) and t[:1].islower():
            t = t[:1].upper() + t[1:]
        prv = t
        ov = [overlap(s, e, dict(w, end=max(w["end"], w["start"] + 0.02))) for s, e in spans]
        j = max(range(len(spans)), key=ov.__getitem__)
        if ov[j] <= 0.01:
            warnings.append(f"\"{w['w']}\" ({w['start']:.2f} s) fell outside the pieces and the captions"); continue
        s, e = spans[j]
        out.append((off[j] + max(0.0, w["start"] - s), off[j] + min(w["end"], e) - s, t))
    plan = [{"s": s, "e": e, "ev": [], "wt": []} for s, e in spans]
    for t0, t1, t, starts in captions(out, off[-1], max_chars, rep, lp):
        for c, o in zip(plan, off):
            d = round(c["e"] - c["s"], 6)
            a, b = round(max(0.0, t0 - o), 3), min(round(t1 - o, 3), d)
            if b - a >= 0.01:
                # "wt": start of each word, relative to the piece (may fall outside it when the caption crosses
                # a cut; render clamps it to the event). If replace changed the word count, render estimates.
                c["ev"].append([a, b, t]); c["wt"].append([round(x - o, 3) for x in starts])
    if zoom > 1:
        zs = ev.zoom_plan(spans, {"style": spec.get("style", "youtube"), "punch_in": zoom}, list(scenes), list(blacks))
        for c, z in zip(plan, zs):
            if z > 1: c["z"] = z
    for it in spec.get("zoom", []):
        t, z = float(it[0]), float(it[1])
        c = next((c for c in plan if c["s"] <= t < c["e"]), None)
        if c is None: warnings.append(f"zoom at {t} s: outside the kept pieces"); continue
        c.pop("z", None)
        if z > 1: c["z"] = round(min(MAX_ZOOM, z), 3)
    for it in spec.get("blur", []):
        t0, t1, box = float(it[0]), float(it[1]), list(it[2:6])
        hit = [c for c in plan if min(t1, c["e"]) - max(t0, c["s"]) > 0.001]
        if not hit: warnings.append(f"blur {t0}-{t1}: outside the kept pieces")
        for c in hit:
            d = round(c["e"] - c["s"], 6)
            c.setdefault("blur", []).append([round(max(0.0, t0 - c["s"]), 3), min(round(t1 - c["s"], 3), d)] + box)
    return plan, removed, maybe


def resolve_lang(flag, edit, transcript):
    """Spoken language and why: --lang > edit.json "lang" > transcript.json "lang" > detected from the words.
    Exits with a clear error when it is unsupported or can't be told."""
    fix = "Set \"lang\" in videos/<name>/edit.json (or pass --lang) to one of: " + ", ".join(lng.supported()) + "."
    for code, why in ((flag, "--lang"), (edit.get("lang"), "edit.json"), (transcript.get("lang"), "transcript.json")):
        if code:
            if code not in lng.supported():
                sys.exit(f"cuts: language '{code}' (from {why}) is not supported: no presets/fillers-{code}.json. {fix}")
            return code, why
    words = transcript.get("words", [])
    code = lng.detect(words)
    if code is None:
        sys.exit(f"cuts: could not tell the spoken language from the transcript ({lng.describe(words)}). {fix}")
    return code, f"detected from the transcript: {lng.describe(words)}"


def read_json(p):
    with open(p, encoding="utf-8") as f: return json.load(f)


def write_text(p, txt):
    with open(p, "w", encoding="utf-8") as f: f.write(txt)


def caption_texts(plan):
    """Caption texts in order; one that crosses a cut (continues at the start of the next piece) counts once."""
    out, last = [], None
    for c in plan:
        out += [t for n, (x0, _, t) in enumerate(c["ev"]) if n or x0 > 0 or t != last]
        last = c["ev"][-1][2] if c["ev"] else None
    return out


def mmss(t):
    return f"{int(t // 60)}:{t % 60:04.1f}"


def report(plan, removed, maybe, total, warnings=(), lang=None):
    """edit-plan.md. lang = (code, why) shown at the top, so the reviewer sees which filler list was used."""
    dur = sum(c["e"] - c["s"] for c in plan)
    wpm = sum(len(t.split()) for t in caption_texts(plan)) / max(1.0, dur) * 60
    o = [f"# Cut plan\n\n{ev.stamp(total)} -> {ev.stamp(dur)} ({(total - dur) / total * 100:.0f}% shorter), "
         f"{len(plan) - 1} cuts, {wpm:.0f} words per minute.\n"]
    if lang:
        o.append(f"Language: {lang[0]} ({lang[1]}); fillers from presets/fillers-{lang[0]}.json. "
                 "Wrong? Set \"lang\" in edit.json and run again with --force.\n")
    av = list(warnings)  # the skill's: pace and how much was removed
    if wpm > 190: av.append(f"pace of {wpm:.0f} words per minute: above 190 feels rushed")
    if (total - dur) / total > 0.45: av.append(f"{(total - dur) / total * 100:.0f}% removed: above 45% is usually a wrong cut")
    if av: o += ["## Warnings\n"] + [f"- {a}" for a in av] + [""]
    zoomed = [(i, c) for i, c in enumerate(plan) if c.get("z", 1) > 1]
    if zoomed:
        o.append("## Camera zoom (optional: to remove it, \"zoom\": [[t, 1]] in edit.json, which survives --force)\n")
        o += [f"- piece {i} ({ev.stamp(c['s'])}): {c['z']:g}x" for i, c in zoomed] + [""]
    if maybe:
        o.append("## Possible retakes (not cut: decide and put them in \"cut\" in edit.json)\n")
        o += [f"- {ev.stamp(t)}: \"{a[:90]}\" then \"{b[:90]}\"" for t, a, b in maybe] + [""]
    o += ["## Removals\n", "| Original | Removed | Reason | Words |", "|---|---|---|---|"]
    o += [f"| {mmss(s)} | {e - s:.1f} s | {why} | {txt[:80]} |" for s, e, why, txt in removed]
    return "\n".join(o) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True); ap.add_argument("--name", required=True)
    ap.add_argument("--transcript", help="default: videos/<name>/transcript.json")
    ap.add_argument("--edit", help="default: videos/<name>/edit.json, if it exists")
    ap.add_argument("--preset", help="default: videos/<name>/preset.json, if it exists, or presets/tiktok-vertical.json")
    ap.add_argument("--lang", help="spoken language (pt, en); default: edit.json, then transcript.json, then detected")
    ap.add_argument("--zoom", type=float, nargs="?", const=1.1, default=0,
                    help="suggest camera zoom at the cuts (off by default; no value = 1.1, max 1.2)")
    ap.add_argument("--no-scenes", action="store_true", help="ignore slide changes when placing cuts")
    ap.add_argument("--force", action="store_true", help="rebuild an existing plan.json (the previous one goes to plan.json.bak)")
    a = ap.parse_args()
    vdir = os.path.join(ROOT, "videos", a.name); os.makedirs(vdir, exist_ok=True)
    pp = os.path.join(vdir, "plan.json")
    if os.path.exists(pp) and not a.force: sys.exit(f"ERROR: {os.path.relpath(pp, ROOT)} already exists (reviewed captions?). Use --force to overwrite.")
    ep = a.edit or os.path.join(vdir, "edit.json")
    edit = read_json(ep) if a.edit or os.path.exists(ep) else {}
    pv = os.path.join(vdir, "preset.json")
    P = preset.load(a.preset or (pv if os.path.exists(pv) else "presets/tiktok-vertical.json"))
    fps = float(P.get("canvas", {}).get("fps", 30))
    transcript = read_json(a.transcript or os.path.join(vdir, "transcript.json"))
    words = transcript["words"]
    lang, why = resolve_lang(a.lang, edit, transcript)
    print(f"language: {lang} ({why})", flush=True)
    ev.check_tools()
    _, _, total, _ = ev.probe(a.video)
    print("listening and looking...", flush=True)
    db, floor = ev.audio_energy(a.video)
    blacks, scenes = ev.visual_events(a.video)
    if a.no_scenes: scenes = []
    warnings = []
    plan, removed, maybe = decide(words, edit, total, fps, db, floor, blacks, scenes, P["subtitles"]["max_chars_per_event"],
                                  zoom=a.zoom, warnings=warnings, lang=lang)
    bak = os.path.exists(pp)
    if bak: shutil.copyfile(pp, pp + ".bak")
    write_text(pp, json.dumps(plan, ensure_ascii=False, indent=1))
    md = report(plan, removed, maybe, total, warnings, (lang, why))
    write_text(os.path.join(vdir, "edit-plan.md"), md)
    print(md.splitlines()[2])
    print(f"ok: {os.path.relpath(pp, ROOT)} and edit-plan.md" + (" (the previous one is in plan.json.bak)" if bak else "")
          + (f", with {os.path.relpath(ep, ROOT)}" if edit else ", without edit.json") + ".")
    print("Review cuts and captions with the author before rendering; then write meta.json (publish-video skill).")
    for w in warnings + ev.WARNINGS: print("  warning:", w)


if __name__ == "__main__":
    main()
