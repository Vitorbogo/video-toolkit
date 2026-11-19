"""J-cut (split edit): at a join between two pieces, the next piece's voice starts before its picture (issue #8).

Sound never moves: the pieces in plan.json are the SOUND timeline, as always. A J-cut only moves the PICTURE edit
point later: piece A's picture runs on into the raw footage after its end (the silence the cut removed) and piece
B's picture starts `lead` seconds into B. In plan.json it is written on B, the piece the join leads into:

    {"s": .., "e": .., "ev": .., "j": [lead, "both"]}     lead in seconds, on the frame grid
                                                           area: "both" (camera and slide), "slide", "camera"

Here: the picture timeline render.py draws (pure), the craft rules that decide whether a join can take a J-cut
(cuts.py), and the mouth measurement those rules need (MediaPipe, local).

Craft rules (true for any author; why in .claude/skills/edit-video/SKILL.md):
  - the gap removed at the join must be silence: over a removed filler or retake the borrowed footage shows the
    mouth forming other words;
  - the borrowed footage must show the author NOT speaking: no audio (it ends before B's first word) and, when the
    camera moves, the mouth closed. Silence is not enough: on the first test 4 of 6 joins had the mouth opening in
    the silence before speaking;
  - lead is measured as V = voice-before-picture, from B's first word onset (not from the cut: the engine already
    keeps a beat of silence there). When the footage is too short, V shrinks; under MIN_V the join is skipped
    (no frozen frame);
  - B keeps at least MIN_PICTURE of its own picture.
  - length, picked per join when edit.json gives none: SHORT_V at a normal sentence-end join (continuity without
    calling attention); LONG_V only at a topic change (a speech gap of TOPIC_GAP or more, the engine's long_gap)
    and only if the mouth-closed footage covers it, else SHORT_V.

  - at most one J-cut every MIN_SPACING s of final video: more and the device shows (candidates keep that spacing,
    J-cuts asked for closer together get a warning);
  - one transition per join: a J-cut join takes no zoom punch-in (warned here) and no whoosh (sfx.py check).

Area, when edit.json gives none: "both" (the craft default; an author who prefers otherwise has it in profile/brand.md
and the edit-video skill writes that area in each edit.json item), except at a slide change
where the next piece opens pointing at the screen ("olha", "look": pointing_words in presets/fillers-<lang>.json):
there the screen must change with the voice, so only the camera waits ("camera").
"""
import math

AREAS = ("both", "slide", "camera")
SHORT_V = 0.25      # voice-before-picture (s) at a sentence-end join
LONG_V = 0.6        # at a topic change
TOPIC_GAP = 3.0     # speech gap (s, last word of A to first of B) that makes a topic change: engine.py's long_gap
POINT_WORDS = 3     # pointing words count among the next piece's first words only
SCENE_PAD = 0.5     # a slide change this close to the join (or B's first word) is "at the join"
MIN_V = 0.2         # a J-cut shorter than this is not noticed: skip the join instead
MIN_PICTURE = 1.5   # B's own picture after the shift
SPEECH_MARGIN = 0.05  # borrowed footage ends this long before B's first word
MOUTH_OPEN = 0.1    # face.py's raw "mouth" score above this = mouth moving (closed ~0-0.04, speech 0.1-0.7)
MOUTH_FPS = 15
MIN_SPACING = 10.0  # final-video seconds between two J-cuts (the issue's "at most one every ~10-15 s")
JOIN_WITHIN = 2.0   # an edit.json "jcut" time must be this close to a join
# removal reasons whose footage can be borrowed: a trim's footage is measured by the mouth check when the camera
# moves; a slide-only J-cut borrows no face, and the borrowed footage is never heard (the sound does not move)
SILENT = {"silence", "trim"}


def moves(area, which):
    """Does `area` move the camera ("camera") or the slide ("slide")?"""
    return area == "both" or area == which


def parse(item):
    """edit.json "jcut" item -> (t, V or None, area or None, note). [t], [t, V], [t, V, area], [t, "slide", "note"]..."""
    t, v, area, note = float(item[0]), None, None, ""
    for x in item[1:]:
        if isinstance(x, (int, float)) and not isinstance(x, bool): v = float(x)
        elif x in AREAS: area = x
        else: note = str(x)
    return t, v, area, note


def floor_frame(x, fps):
    """x seconds rounded down to the frame grid."""
    return math.floor(round(x * fps, 6)) / fps


def frame_starts(nframes):
    """First frame of each piece in the final video, plus the total: [0, n0, n0+n1, ...]."""
    F = [0]
    for q in nframes: F.append(F[-1] + q)
    return F


def join_time(plan, n):
    """Final-video time of the join plan[n] | plan[n+1] (the sound timeline)."""
    return sum(c["e"] - c["s"] for c in plan[:n + 1])


def nearest_join(plan, t, within=JOIN_WITHIN):
    """Index n of the join plan[n] | plan[n+1] closest to recording time t (inside the removed gap = 0), or None."""
    best = None
    for n in range(len(plan) - 1):
        a, b = plan[n]["e"], plan[n + 1]["s"]
        d = 0.0 if a - 0.001 <= t <= b + 0.001 else min(abs(t - a), abs(t - b))
        if d <= within and (best is None or d < best[0]): best = (d, n)
    return None if best is None else best[1]


def onset(seg):
    """Recording time of the piece's first word (from "wt", else the first caption), or None."""
    wt = [x for w in seg.get("wt") or [] for x in (w or [])]
    if wt: return seg["s"] + max(0.0, min(wt))
    ev = seg.get("ev") or []
    return seg["s"] + ev[0][0] if ev else None


def gap_reasons(removed, a, b):
    """Reasons of the removals between a and b (recording time), from cuts.removals()."""
    out = set()
    for x, y, why, _ in removed:
        if y > a + 0.005 and x < b - 0.005: out |= {w.strip() for w in why.split(",")}
    return out


def sentence_end(seg):
    ev = seg.get("ev") or []
    return bool(ev) and ev[-1][2].rstrip()[-1:] in ".?!"


def check(plan, n, removed, fps, area="both", mouth=None):
    """Can the join plan[n] | plan[n+1] take a J-cut? -> (max_V, why). max_V None = no (why says so).
    max_V = the longest voice-before-picture the borrowed footage allows (silence, and the mouth when the camera
    moves). mouth(t0, t1) -> recording time the mouth first opens in [t0, t1], or None if it stays closed;
    mouth=None means it could not be measured, and a camera J-cut is then refused."""
    A, B = plan[n], plan[n + 1]
    bad = gap_reasons(removed, A["e"], B["s"]) - SILENT
    if bad: return None, "the cut there removed " + ", ".join(sorted(bad)) + " (the mouth moves in that footage)"
    w = onset(B)
    if w is None: return None, "the next piece has no word"
    pre = w - B["s"]
    end = w - SPEECH_MARGIN  # borrowed footage stays before B's first word
    why = "silence"
    if moves(area, "camera"):
        if mouth is None: return None, "mouth not measured (MediaPipe or the face model missing)"
        m = mouth(A["e"], end)
        if m is not None and m < end: end, why = m, "mouth opens"
    lead = min(floor_frame(end - A["e"], fps), floor_frame(B["e"] - B["s"] - MIN_PICTURE, fps))
    v = round(lead - pre, 3)
    if v < MIN_V - 1e-6:
        return None, f"only {max(0.0, v):.2f} s of voice before picture fits ({why} {end - A['e']:.2f} s after the cut)"
    return v, why


def last_word_end(plan, n, kept):
    """End (recording time) of the last kept word inside piece n; kept = [(start, end)] of the kept words."""
    A = plan[n]
    ends = [e for st, e in kept if A["s"] - 0.02 <= st and e <= A["e"] + 0.02]
    return max(ends) if ends else A["e"]


def choose(plan, n, kept=(), scenes=(), pointing=()):
    """Area and length class for the join plan[n] | plan[n+1] when edit.json gives none -> (area, V wanted, why)."""
    A, B = plan[n], plan[n + 1]
    w = onset(B)
    first = [x.strip(".,;:!?\"'").lower() for e in (B.get("ev") or [])[:1] for x in e[2].split()[:POINT_WORDS]]
    area, why = "both", []
    if any(A["e"] - SCENE_PAD <= t <= w + SCENE_PAD for t in scenes) and set(first) & set(pointing):
        area = "camera"; why.append("slide changes and the next piece points at it: only the camera waits")
    gap = w - last_word_end(plan, n, kept)
    if gap >= TOPIC_GAP:
        why.insert(0, f"topic change ({gap:.1f} s without speech)"); return area, LONG_V, "; ".join(why)
    why.insert(0, "sentence end"); return area, SHORT_V, "; ".join(why)


def fallback(auto_v, vmax, limit, why):
    """choose()'s length against what the footage allows: LONG_V that doesn't fit falls back to SHORT_V."""
    if vmax >= auto_v - 1e-6 or auto_v <= SHORT_V: return auto_v, why
    return SHORT_V, why + f"; {limit} too soon for {LONG_V:g} s"


def apply(plan, items, removed, fps, mouth=None, warnings=None, kept=(), scenes=(), pointing=()):
    """edit.json "jcut" items -> "j": [lead, area] on the piece each join leads into.
    Returns [(n, V, area, why)]. Length and area the item leaves out are chosen by choose()."""
    warnings = [] if warnings is None else warnings
    done = []
    for it in items:
        t, v, area, note = parse(it)
        n = nearest_join(plan, t)
        if n is None:
            warnings.append(f"jcut at {t:.2f} s: no join within {JOIN_WITHIN:g} s"); continue
        if not sentence_end(plan[n]):
            warnings.append(f"jcut at {t:.2f} s skipped: the piece before it does not end a sentence "
                            "(a J-cut reads as a new thought)"); continue
        auto_area, auto_v, why = choose(plan, n, kept, scenes, pointing)
        area = area or auto_area
        vmax, limit = check(plan, n, removed, fps, area, mouth)
        if vmax is None:
            warnings.append(f"jcut at {t:.2f} s (join {plan[n]['e']:.2f}|{plan[n + 1]['s']:.2f}) skipped: {limit}"); continue
        if v is None: v, why = fallback(auto_v, vmax, limit, why)
        else: why = "set in edit.json"
        if v > vmax + 1e-6:
            warnings.append(f"jcut at {t:.2f} s: voice-before-picture {v:.2f} s shortened to {vmax:.2f} s ({limit})")
            v = vmax
        A, B = plan[n], plan[n + 1]; pre = onset(B) - B["s"]
        if A.get("z", 1) != B.get("z", 1):
            warnings.append(f"jcut at {t:.2f} s: the zoom also changes at this join (one transition per join): "
                            "drop the zoom or the J-cut")
        # next frame up (V never less than asked; 0.05 frame of slack for "wt" kept to 3 decimals), never past
        # what the footage allows
        lead = min(math.ceil(round((v + pre) * fps, 6) - 0.05) / fps, floor_frame(vmax + pre, fps))
        B["j"] = [round(lead, 6), area]
        done.append((n, round(lead - pre, 3), area, why + (f"; {note}" if note else "")))
    at = sorted(join_time(plan, n) for n, *_ in done)
    for a, b in zip(at, at[1:]):
        if b - a < MIN_SPACING:
            warnings.append(f"J-cuts at {a:.1f} s and {b:.1f} s of the final video: less than {MIN_SPACING:g} s apart "
                            "(the device starts to show)")
    return done


def candidates(plan, removed, fps, mouth=None, kept=(), scenes=(), pointing=()):
    """Joins that could take a J-cut, for edit-plan.md: [(n, recording time, V, area, why)] with the length and area
    choose() would pick, capped by the footage, at least MIN_SPACING s (final video) from any J-cut or other candidate."""
    out = []
    taken = [join_time(plan, n) for n in range(len(plan) - 1) if "j" in plan[n + 1]]
    for n in range(len(plan) - 1):
        if "j" in plan[n + 1] or not sentence_end(plan[n]): continue
        if any(abs(join_time(plan, n) - x) < MIN_SPACING for x in taken): continue
        area, v, why = choose(plan, n, kept, scenes, pointing)
        vmax, limit = check(plan, n, removed, fps, area, mouth)
        if vmax is None: continue
        v, why = fallback(v, vmax, limit, why)
        out.append((n, plan[n]["e"], round(min(v, vmax), 3), area, why))
        taken.append(join_time(plan, n))
    return out


def mouth_meter(video, crop, warnings=None):
    """-> mouth(t0, t1): recording time the mouth first opens (face.py's raw "mouth" > MOUTH_OPEN) in the camera
    crop between t0 and t1, or None if it stays closed. Returns None (not measurable) without MediaPipe or the model."""
    import os, subprocess
    try:
        import numpy as np, mediapipe as mp
        from mediapipe.tasks import python as mpt
        from mediapipe.tasks.python import vision
        from vtk import face
    except ImportError:
        if warnings is not None: warnings.append("J-cut: MediaPipe missing, the mouth can't be checked (camera J-cuts refused)")
        return None
    if not os.path.isfile(face.MODEL):
        if warnings is not None: warnings.append(f"J-cut: face model missing ({face.MODEL}), camera J-cuts refused")
        return None
    cw, ch, cx, cy = crop
    W = 480; H = int(ch * W / cw) // 2 * 2
    opts = vision.FaceLandmarkerOptions(base_options=mpt.BaseOptions(model_asset_path=face.MODEL),
                                        running_mode=vision.RunningMode.IMAGE, num_faces=1, output_face_blendshapes=True)

    def mouth(t0, t1):
        if t1 - t0 < 1.0 / MOUTH_FPS: return None
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}", "-i", video,
                              "-vf", f"crop={cw}:{ch}:{cx}:{cy},scale={W}:{H},fps={MOUTH_FPS}",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        size = W * H * 3
        with vision.FaceLandmarker.create_from_options(opts) as lm:
            for i in range(len(raw) // size):
                img = np.frombuffer(raw[i * size:(i + 1) * size], np.uint8).reshape(H, W, 3)
                r = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(img)))
                if not r.face_landmarks: continue  # no face (turned away): nothing to lip-read
                bs = {c.category_name: c.score for c in r.face_blendshapes[0]}
                if face.penalties(bs)["mouth"] > MOUTH_OPEN: return t0 + i / MOUTH_FPS
        return None
    return mouth


# ---------- picture timeline (render.py) ----------

def picture(plan, nframes, fps):
    """Pieces of the PICTURE timeline. nframes = frames of each plan piece (render.frames).
    -> [{"f0": first frame in the final video, "n": frames, "cam": piece the camera comes from, "sl": slide's}].
    Without "j" it is one clip per piece, like before. A J-cut on piece B moves the camera and/or slide switch
    from A to B `lead` frames later; a negative lead (L-cut) would move it earlier."""
    F = frame_starts(nframes)
    sw = {"cam": [0], "sl": [0]}
    for i in range(1, len(plan)):
        j = plan[i].get("j")
        k = round(float(j[0]) * fps) if j else 0
        area = j[1] if j and len(j) > 1 else "both"
        for key, which in (("cam", "camera"), ("sl", "slide")):
            p = F[i] + (k if j and moves(area, which) else 0)
            if not sw[key][-1] < p < F[i + 1]:
                raise SystemExit(f"render: piece {i}: J-cut lead {j} leaves no picture for it or the piece before.")
            sw[key].append(p)
    cuts = sorted(set(sw["cam"]) | set(sw["sl"]) | {F[-1]})
    owner = lambda key, p: max(i for i, x in enumerate(sw[key]) if x <= p)
    return [{"f0": p, "n": q - p, "cam": owner("cam", p), "sl": owner("sl", p)} for p, q in zip(cuts, cuts[1:])]


def source(plan, F, i, f0, fps):
    """Recording time shown at final frame f0 by piece i's picture (it runs on past the piece's own ends)."""
    return round(plan[i]["s"] + (f0 - F[i]) / fps, 6)


def caption_events(plan, nframes, fps):
    """Captions in FINAL time (they follow the sound): [(x0, x1, text, word starts or None)], each event kept inside
    its own piece's frames (an old plan's event may end past them by a fraction of a frame)."""
    out, t = [], 0.0
    for c, q in zip(plan, nframes):
        wts, d = c.get("wt") or [], q / fps
        for k, e in enumerate(c.get("ev", [])):
            x0, x1 = max(0.0, e[0]), min(d, e[1])
            if x1 - x0 < 1e-6: continue
            out.append((t + x0, t + x1, e[2], [t + x for x in wts[k]] if k < len(wts) and wts[k] else None))
        t += d
    return out


def slice_captions(events, t0, t1):
    """The events that fall in [t0, t1] (final time), relative to t0: (ev, wt) for a render clip."""
    ev, wt = [], []
    for a, b, text, w in events:
        if b <= t0 + 1e-6 or a >= t1 - 1e-6: continue
        ev.append([round(max(a, t0) - t0, 4), round(min(b, t1) - t0, 4), text])
        wt.append([round(x - t0, 4) for x in w] if w else None)
    return ev, wt
