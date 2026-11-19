#!/usr/bin/env python3
"""Renders each plan segment in 9:16 (face + slide + captions), from a preset, and joins them all.

Usage:
  python3 src/vtk/render.py --preset presets/tiktok-vertical.json --video RECORDING.mov \
      --plan videos/<name>/plan.json --out render_final --scale 1.0 --crf 20
  # light preview: --scale 0.5 --crf 30
Outputs in --out: c00.mov, c01.mov... (picture only, one clip per piece of the PICTURE timeline), sound.wav (the
whole sound track, PCM 48 kHz), list.txt and, when all clips are ready, final.mov (clips joined without re-encoding,
plus sound.wav). Then: vtk/postaudio.py --in <out>/final.mov.

Sound and picture are built apart. The plan's segments are the sound timeline: sound.wav is each segment's audio,
exactly round((e - s) * fps) frames long, with a short fade at each end, joined. The picture timeline has the same
total length; it is one clip per segment unless a segment has a J-cut ("j": [lead, area], src/vtk/jcut.py): then
the camera and/or slide switch to that segment `lead` seconds after its sound starts, and the clips are cut at those
picture edit points. Captions follow the sound (sliced from the sound timeline into each clip). Frame grid: every
clip and every sound piece is a whole number of frames, so nothing drifts at the joins.

Resumes where it stopped: each clip has a cNN.json with the hash of everything that affects it (segment, preset
blocks, camera filter, --scale, --crf, recording file). If anything changed, the clip is redone. --budget limits the
time per run (s). Clips of segments no longer in the plan are deleted.

Zoom (optional): a plan.json segment with "z": 1.1 zooms only the camera window (slide and captions don't change).
Without "z", or "z": 1, no zoom. Maximum 1.2 (skill rule).

Illustration (optional, skill illustrations): --panel videos/<name>/illustration.mp4 puts that video in place of the
cropped slide. It is in FINAL video time (after the cuts) and scaled to layout.slide; slide_crop is not used (but is
still checked). Panel shorter than the video: freezes on the last frame.

Blur (optional): "blur": [[t0, t1, x, y, w, h], ...] in the segment blurs the x/y/w/h box (pixels of the original
recording) between t0 and t1 (seconds from the segment start, may go past its end: footage a J-cut borrows), before
cropping camera and slide.

Before rendering, checks the recording (ffprobe): resolution equal to the preset's source.w/h (when present) and
crops/boxes inside the frame.

Captions: drawn with Pillow (src/vtk/captions.py), whole sentence with the spoken word highlighted
("highlight"). Homebrew's ffmpeg has no libass: no .ass/subtitles here. Font: subtitles.font_file.
"""
import argparse, hashlib, json, math, os, re, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.path.join(ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "src"))
from vtk import preset
from vtk import captions, engine, jcut

EYE_LINE = engine.EYE_LINE  # same eye line as engine.py: zoom grows from it
MAX_ZOOM = 1.2  # above this the zoom is too noticeable
AR = 48000  # clip audio: 16-bit PCM, 48 kHz
VERSION = 4  # changes when the way of rendering changes: forces the clips to be redone
CLIP_RE = re.compile(r"^c(\d+)\.(mov|mov\.part|json|ass|mp4|z)$")
CAPTION_RE = re.compile(r"^c(\d+)-cap[-.]")


def zoom_crop(crop, z, eye=EYE_LINE):
    """[w, h, x, y] of the camera in the recording -> smaller crop (zoom z), centered horizontally and with the
    eye line kept at the same height. z <= 1 returns the original crop."""
    w, h, x, y = crop
    if z <= 1.001:
        return [w, h, x, y]
    w2, h2 = int(w / z) // 2 * 2, int(h / z) // 2 * 2
    return [w2, h2, x + (w - w2) // 2, y + int(eye * (h - h2))]


def zoom_of(c, n):
    z = float(c.get("z", 1.0))
    if z > MAX_ZOOM: print(f"warning: segment {n} with zoom {z:g}, capped at {MAX_ZOOM:g}"); z = MAX_ZOOM
    return 1.0 if z <= 1.001 else z


def frames(c, fps, n=0):
    """Clip frames: round((e - s) * fps). Clear error if the segment is inverted or too short."""
    s, e = float(c["s"]), float(c["e"])
    if e <= s:
        raise SystemExit(f"render: segment {n} with end ({e:g}) <= start ({s:g}). Fix plan.json.")
    k = round((e - s) * fps)
    if k < 1:
        raise SystemExit(f"render: segment {n} too short ({e - s:.3f} s, less than 1 frame at {fps} fps).")
    return k


def check_plan(plan, fps):
    """Validates the whole plan before rendering; returns [(frames, zoom)] per segment."""
    out = []
    for n, c in enumerate(plan):
        for b in c.get("blur", []):
            if len(b) != 6 or b[1] <= b[0] or b[4] <= 0 or b[5] <= 0:
                raise SystemExit(f"render: segment {n}, blur {b}: expected [t0, t1, x, y, w, h] with t1 > t0, w and h > 0.")
        out.append((frames(c, fps, n), zoom_of(c, n)))
    return out


def check_source(S, size, plan):
    """List of problems: resolution different from source.w/h, crop or blur box outside the frame."""
    W, H = size; errs = []
    if "w" in S and "h" in S and (S["w"], S["h"]) != (W, H):
        errs.append(f"the recording is {W}x{H}, but the preset expects {S['w']}x{S['h']} (source.w/h). "
                    "Use/measure a preset for this recording (videos/<name>/preset.json).")
    boxes = [("camera_crop", S["camera_crop"]), ("slide_crop", S["slide_crop"])]
    for n, c in enumerate(plan):
        boxes += [(f"segment {n} blur {b}", [b[4], b[5], b[2], b[3]]) for b in c.get("blur", [])]
    for name, (w, h, x, y) in boxes:
        if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > W or y + h > H:
            errs.append(f"{name} = {w}x{h} at ({x}, {y}) goes outside the {W}x{H} frame.")
    return errs


def probe(video):
    """(width, height) of the 1st video stream, via ffprobe."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                            "-of", "csv=p=0:s=x", video], capture_output=True, text=True)
    except FileNotFoundError:
        raise SystemExit("render: ffprobe not found (it comes with ffmpeg).")
    m = re.match(r"(\d+)x(\d+)", r.stdout.strip())
    if r.returncode or not m:
        raise SystemExit(f"render: could not read the resolution of {video}: {r.stderr.strip()[-300:]}")
    return int(m.group(1)), int(m.group(2))


def blur_graph(boxes, size, src="v0", tag=""):
    """Blur of the [t0, t1, x, y, w, h] boxes over the recording, before the crops.
    Returns (filter_complex fragment ending in ';', output label). tag keeps two chains' labels apart."""
    W, H = size; g = []; cur = src
    for i, (t0, t1, x, y, w, h) in enumerate(boxes):
        # even box (yuv420), only growing outwards: covers at least what was asked
        x0, y0 = int(x) // 2 * 2, int(y) // 2 * 2
        x1, y1 = min(W, math.ceil((x + w) / 2) * 2), min(H, math.ceil((y + h) / 2) * 2)
        bw, bh = x1 - x0, y1 - y0
        sigma = min(100, max(10, min(bw, bh) // 3))
        en = f"enable='between(t,{t0:g},{t1:g})'"
        nxt = f"bl{tag}{i + 1}"
        g.append(f"[{cur}]split=2[bm{tag}{i}][bc{tag}{i}];[bc{tag}{i}]crop={bw}:{bh}:{x0}:{y0},gblur=sigma={sigma}:steps=3[bk{tag}{i}];"
                 f"[bm{tag}{i}][bk{tag}{i}]overlay={x0}:{y0}:{en}[{nxt}];")
        cur = nxt
    return "".join(g), cur


def clip_hash(c, z, P, cam_extra, scale, crf, video, panel=None):
    """Hash of everything that changes the clip: if it changes, the clip is redone."""
    clean = lambda d: {k: v for k, v in d.items() if not k.startswith("_")}
    st = os.stat(video)
    data = {"v": VERSION, "s": c["s"], "e": c["e"], "ev": c["ev"], "wt": c.get("wt"), "z": z, "blur": c.get("blur", []),
            "ss": c.get("ss"), "bs": c.get("bs", []),
            "canvas": clean(P["canvas"]), "source": clean(P["source"]), "layout": P["layout"],
            "subtitles": clean(P["subtitles"]),
            "cam": cam_extra, "scale": scale, "crf": str(crf),
            "video": [video, st.st_size, int(st.st_mtime)]}
    if panel:  # (file, start in the final video): the illustration changed or the segment moved in the timeline
        pt = os.stat(panel[0]); data["panel"] = [panel[0], pt.st_size, int(pt.st_mtime), round(panel[1], 4)]
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def clip_cmd(c, nq, z, P, size, cam_extra, scale, crf, video, caption, out, panel=None):
    """Picture-only clip of nq frames. c = {"s": camera source start, "ev", "wt", "blur"} plus, when the slide comes
    from another moment of the recording (J-cut on one area only), "ss" (slide source start) and "bs" (its blur).
    caption = (concat list with the caption PNGs, strip height), from captions.overlay.
    panel = (illustration video, start of this clip in the final video) or None: in place of the cropped slide."""
    even = lambda x: int(round(x * scale / 2)) * 2
    cv, L, S = P["canvas"], P["layout"], P["source"]
    fps = cv["fps"]; W, H = even(cv["w"]), even(cv["h"])
    cam_h, cam_y = even(L["camera"]["h"]), even(L["camera"]["y"])
    sl_w, sl_h, sl_x, sl_y = (even(L["slide"][k]) for k in ("w", "h", "x", "y"))
    sw, sh, sx, sy = S["slide_crop"]
    cw, ch, cx, cy = zoom_crop(S["camera_crop"], z)
    bg, src = blur_graph(c.get("blur", []), size)
    D = nq / fps
    apart = not panel and c.get("ss") is not None and abs(c["ss"] - c["s"]) > 1e-4
    grab = lambda: f"setpts=PTS-STARTPTS,fps={fps},tpad=stop_mode=clone:stop_duration=1"
    if panel:
        slide = f"[{src}]crop={cw}:{ch}:{cx}:{cy},scale={W}:{cam_h}{cam_extra}[cam];" \
                f"[2:v]{grab()},scale={sl_w}:{sl_h}[sl];"
    elif apart:  # slide from another moment of the recording: its own input and its own blur
        bs, ssrc = blur_graph(c.get("bs", []), size, "w0", "s")
        slide = f"[{src}]crop={cw}:{ch}:{cx}:{cy},scale={W}:{cam_h}{cam_extra}[cam];" \
                f"[2:v]{grab()}[w0];{bs}[{ssrc}]crop={sw}:{sh}:{sx}:{sy},scale={sl_w}:{sl_h}[sl];"
    else:
        slide = f"[{src}]split=2[a][b];" \
                f"[a]crop={cw}:{ch}:{cx}:{cy},scale={W}:{cam_h}{cam_extra}[cam];" \
                f"[b]crop={sw}:{sh}:{sx}:{sy},scale={sl_w}:{sl_h}[sl];"
    fg = (f"color=c={cv['bg']}:s={W}x{H}:r={fps}[bg];"
          f"[0:v]{grab()}[v0];{bg}" + slide +
          f"[bg][cam]overlay=0:{cam_y}:shortest=1[t1];[t1][sl]overlay={sl_x}:{sl_y}[t2];"
          f"[1:v]fps={fps},format=rgba[cap];[t2][cap]overlay=0:{H - even(P['subtitles']['margin_v']) - caption[1]}:eof_action=pass[v]")
    extra = (["-ss", f"{panel[1]:.4f}", "-t", f"{D + 0.5:.3f}", "-i", panel[0]] if panel else
             ["-ss", f"{c['ss']:.4f}", "-t", f"{D + 0.5:.3f}", "-i", video] if apart else [])
    return ["ffmpeg", "-v", "error", "-y", "-ss", f"{c['s']:.4f}", "-t", f"{D + 0.5:.3f}", "-i", video,
            "-f", "concat", "-safe", "0", "-i", caption[0], *extra,
            "-filter_complex", fg, "-map", "[v]", "-an", "-frames:v", str(nq),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p", "-r", str(fps), "-f", "mov", out]


def sound_cmd(plan, nframes, P, video, out):
    """The whole sound track: each segment's audio, exactly nq/fps long, faded in/out, joined (PCM 48 kHz)."""
    fps, cut = P["canvas"]["fps"], P["cut"]
    fi, fo = cut["audio_fade_in_s"], cut["audio_fade_out_s"]
    ins, fg = [], []
    for n, (c, nq) in enumerate(zip(plan, nframes)):
        D = nq / fps; ns = round(D * AR)
        ins += ["-ss", str(c["s"]), "-t", f"{D + 0.5:.3f}", "-i", video]
        fg.append(f"[{n}:a:0]aresample={AR},asetpts=PTS-STARTPTS,atrim=end_sample={ns},apad=whole_len={ns},"
                  f"afade=t=in:d={fi},afade=t=out:st={max(0, D - fo):.4f}:d={fo}[a{n}]")
    fg.append("".join(f"[a{n}]" for n in range(len(plan))) + f"concat=n={len(plan)}:v=0:a=1[a]")
    return ["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", ";".join(fg), "-map", "[a]",
            "-c:a", "pcm_s16le", "-ar", str(AR), "-f", "wav", out]


def blur_at(plan, t0, D):
    """Blur boxes of the recording window [t0, t0 + D], relative to t0 (from every segment's "blur", deduplicated)."""
    out = []
    for c in plan:
        for b in c.get("blur", []):
            a, z = c["s"] + b[0], c["s"] + b[1]
            box = [round(max(0.0, a - t0), 3), round(min(D, z - t0), 3)] + list(b[2:6])
            if min(z, t0 + D) - max(a, t0) > 0.001 and box not in out: out.append(box)
    return out


def clips(plan, info, fps):
    """plan + check_plan's info -> the picture clips: [(segment-like dict, frames, zoom, start in the final video)]."""
    nframes = [q for q, _ in info]
    F = [0]
    for q in nframes: F.append(F[-1] + q)
    events = jcut.caption_events(plan, nframes, fps)
    out = []
    for p in jcut.picture(plan, nframes, fps):
        t0, D = p["f0"] / fps, p["n"] / fps
        s, ss = jcut.source(plan, F, p["cam"], p["f0"], fps), jcut.source(plan, F, p["sl"], p["f0"], fps)
        ev, wt = jcut.slice_captions(events, t0, t0 + D)
        c = {"s": s, "e": round(s + D, 6), "ev": ev, "wt": wt, "blur": blur_at(plan, s, D)}
        if p["sl"] != p["cam"]: c["ss"], c["bs"] = ss, blur_at(plan, ss, D)
        out.append((c, p["n"], info[p["cam"]][1], t0))
    return out


def clean(outdir, total):
    """Deletes clips/sidecars of segments that left the plan, leftovers of an interrupted render and old .mp4/.z files."""
    for f in os.listdir(outdir):
        m = CLIP_RE.match(f)
        if m and (int(m.group(1)) >= total or m.group(2) in ("mov.part", "mp4", "z", "ass")):
            os.remove(os.path.join(outdir, f))
        m = CAPTION_RE.match(f)  # caption images (captions.overlay) of segments that left the plan
        if m and int(m.group(1)) >= total:
            os.remove(os.path.join(outdir, f))


def ready(outdir, n, h):
    base = os.path.join(outdir, f"c{n:02d}")
    if not os.path.exists(base + ".mov") or not os.path.exists(base + ".json"):
        return False
    try:
        with open(base + ".json", encoding="utf-8") as f:
            return json.load(f).get("hash") == h
    except (OSError, ValueError):
        return False


def concat(outdir, total):
    """list.txt with c00..c{total-1}, joined without re-encoding, plus sound.wav -> final.mov."""
    lst = os.path.join(outdir, "list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        f.writelines(f"file 'c{n:02d}.mov'\n" for n in range(total))
    tmp = os.path.join(outdir, "final.mov.part")
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt", "-i", "sound.wav",
                        "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "pcm_s16le", "-f", "mov", tmp],
                       cwd=outdir, capture_output=True, text=True)
    if r.returncode:
        print("ERROR joining", r.stderr[-400:]); sys.exit(1)
    os.replace(tmp, os.path.join(outdir, "final.mov"))


def sound(outdir, plan, info, P, video):
    """sound.wav, redone only when the segments, fades or recording change (sound.json keeps the hash)."""
    nframes = [q for q, _ in info]
    st = os.stat(video)
    h = hashlib.sha256(json.dumps({"v": VERSION, "seg": [[c["s"], q] for c, q in zip(plan, nframes)], "cut": P["cut"],
                                   "fps": P["canvas"]["fps"], "video": [video, st.st_size, int(st.st_mtime)]},
                                  sort_keys=True).encode()).hexdigest()
    wav, meta = os.path.join(outdir, "sound.wav"), os.path.join(outdir, "sound.json")
    try:
        with open(meta, encoding="utf-8") as f:
            if os.path.exists(wav) and json.load(f).get("hash") == h: return
    except (OSError, ValueError):
        pass
    r = subprocess.run(sound_cmd(plan, nframes, P, video, wav + ".part"), capture_output=True, text=True)
    if r.returncode:
        print("ERROR sound", r.stderr[-400:]); sys.exit(1)
    os.replace(wav + ".part", wav)
    with open(meta, "w", encoding="utf-8") as f: json.dump({"hash": h}, f)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", required=True); ap.add_argument("--video", required=True)
    ap.add_argument("--plan", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--scale", type=float, default=1.0); ap.add_argument("--crf", default="20")
    ap.add_argument("--budget", type=float, default=1e9)
    ap.add_argument("--camera-filter", default=None, help="off|natural (default: the preset's)")
    ap.add_argument("--panel", help="illustration video (skill illustrations), in final video time, in place of the slide")
    a = ap.parse_args(argv)
    if a.panel:
        a.panel = os.path.abspath(a.panel)
        if not os.path.exists(a.panel): raise SystemExit(f"render: --panel {a.panel} does not exist")

    # ffmpeg runs with cwd=a.out (the caption list points to the PNGs there): relative paths used to break
    a.out, a.video = os.path.abspath(a.out), os.path.abspath(a.video)
    P = preset.load(a.preset)
    with open(a.plan, encoding="utf-8") as f:
        plan = json.load(f)
    info = check_plan(plan, P["canvas"]["fps"])
    size = probe(a.video)
    errs = check_source(P["source"], size, plan)
    if errs:
        raise SystemExit("render: the recording doesn't match the preset:\n  " + "\n  ".join(errs))
    captions.check_font(P["subtitles"])
    cf_mode = a.camera_filter or P["camera_filter"]["mode"]
    if cf_mode not in P["camera_filter"]:
        raise SystemExit(f"render: --camera-filter {cf_mode} does not exist in the preset (camera_filter).")
    cf = P["camera_filter"][cf_mode]
    cam_extra = ("," + cf) if cf else ""
    os.makedirs(a.out, exist_ok=True)
    pics = clips(plan, info, P["canvas"]["fps"])
    clean(a.out, len(pics))
    sound(a.out, plan, info, P, a.video)

    t0 = time.time(); done = 0
    for n, (c, nq, z, start) in enumerate(pics):
        pn = (a.panel, start) if a.panel else None
        h = clip_hash(c, z, P, cam_extra, a.scale, a.crf, a.video, pn)
        base = os.path.join(a.out, f"c{n:02d}")
        if ready(a.out, n, h):
            done += 1; continue
        if time.time() - t0 > a.budget: print("time budget reached"); break
        even = lambda x: int(round(x * a.scale / 2)) * 2
        caption = captions.overlay(c, a.out, f"c{n:02d}-cap", P["subtitles"], even(P["canvas"]["w"]), a.scale)
        cmd = clip_cmd(c, nq, z, P, size, cam_extra, a.scale, a.crf, a.video, caption, base + ".mov.part", pn)
        r = subprocess.run(cmd, cwd=a.out, capture_output=True, text=True)
        if r.returncode:
            if os.path.exists(base + ".mov.part"): os.remove(base + ".mov.part")
            print("ERROR", n, r.stderr[-400:]); sys.exit(1)
        os.replace(base + ".mov.part", base + ".mov")
        with open(base + ".json", "w", encoding="utf-8") as f:
            json.dump({"hash": h, "frames": nq, "z": z}, f)
        done += 1
        print("ok", n, "%.1fs" % (time.time() - t0) + (f" zoom {z:g}x" if z > 1 else ""), flush=True)
    js = sum(1 for c in plan if c.get("j"))
    print(done, "/", len(pics), "clips ready;", f"camera_filter={cf_mode}" + (f"; {js} J-cuts" if js else ""))
    if done == len(pics):
        concat(a.out, len(pics))
        print("final:", os.path.join(a.out, "final.mov"))
    else:
        print("run again to finish; final.mov only comes out with all clips")


if __name__ == "__main__":
    main()
