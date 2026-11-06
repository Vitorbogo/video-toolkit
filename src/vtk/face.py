#!/usr/bin/env python3
"""Finds the frames with the most neutral face in the final video, for the cover (local and free: MediaPipe, no network).

Looks at the camera strip (face_region in presets/thumbnail.json) a few frames per second and scores each one:
0 is ideal. Penalises closed eyes (blink), open mouth (mid-word), wide smile, frowning or raised brow, turned head
and blurry image, each expression measured against your own resting face in that video (its lowest level,
10th percentile). A frame's score is the worst of it and its neighbours, to prefer an expression that held (not
an instant between two grimaces). Weights in the preset ("neutral").

Output in videos/<name>/ (or --out):
  face.json             candidates in order (t, score, face_x and the detail) and the score of every frame
  face_candidates.jpg   contact sheet with the numbered candidates, to check by eye
In thumb.json: "time_s": "auto" uses the candidate at the variant's position (A = 1st, B = 2nd...), "auto:3" the 3rd;
"face_x": "auto" centres the 16:9 on the face in that frame. Same video + same weights = same result.

  python3 src/vtk/face.py --video videos/<name>/final.mp4 --name <name>
Requires: pip install mediapipe numpy Pillow, and the model at models/face_landmarker.task (see README).
"""
import argparse, json, math, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.path.join(ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "src"))
from vtk import preset

MODEL = os.path.join(ROOT, "models", "face_landmarker.task")
DOWNLOAD = ("download it (3.7 MB) from https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/"
            "float16/latest/face_landmarker.task and save it as models/face_landmarker.task")
DEFAULTS = {"fps": 4, "width": 540, "candidates": 6, "spacing_s": 1.5, "margin_s": 0.5,
            "weights": {"eyes": 3.0, "mouth": 4.0, "smile": 1.0, "brow": 0.5, "pose": 1.0, "sharpness": 1.0}}


# ---------- score (pure functions, tested without the model) ----------

def penalties(bs, yaw=0.0, pitch=0.0, sharpness=1.0):
    """blendshapes {name: 0..1} + pose (degrees) + relative sharpness (1 = video median) -> penalties 0..1."""
    g = lambda k: float(bs.get(k, 0.0))
    pair = lambda k: max(g(k + "Left"), g(k + "Right"))
    return {
        "eyes": max(pair("eyeBlink"), 0.5 * pair("eyeSquint")),
        "mouth": max(g("jawOpen"), g("mouthFunnel"), g("mouthPucker"), pair("mouthLowerDown"), pair("mouthUpperUp")),
        "smile": pair("mouthSmile"),
        "brow": max(g("browInnerUp"), pair("browDown")),
        "pose": min(1.0, (abs(yaw) + abs(pitch)) / 30.0),
        "sharpness": min(1.0, max(0.0, 1.0 - sharpness)),
    }


EXPRESSION = ("eyes", "mouth", "smile", "brow")


def baseline(dets, q=0.1):
    """Resting level of each expression in this video (percentile q): glasses, naturally high brows etc.
    Subtracted from each frame, the score measures how far the face left its own normal, not a generic face."""
    base = {}
    for k in EXPRESSION:
        vs = sorted(d[k] for d in dets if d)
        base[k] = vs[int(q * (len(vs) - 1))] if vs else 0.0
    return base


def subtract_baseline(p, base):
    return {k: max(0.0, v - base.get(k, 0.0)) if k in base else v for k, v in p.items()}


def score(p, weights):
    return sum(weights.get(k, 0.0) * v for k, v in p.items())


def smooth(scores):
    """Each frame's score = the worst of it and its neighbours (None = no face, counts as worst)."""
    out = []
    for i, n in enumerate(scores):
        nb = scores[max(0, i - 1):i + 2]
        out.append(None if n is None or any(v is None for v in nb) else max(nb))
    return out


def pick(ts, scores, k, spacing, start=0.0, end=float("inf")):
    """Up to k indices with the lowest scores, at least `spacing` s apart, within [start, end]."""
    order = sorted((n, i) for i, n in enumerate(scores) if n is not None and start <= ts[i] <= end)
    picked = []
    for n, i in order:
        if all(abs(ts[i] - ts[j]) >= spacing for j in picked):
            picked.append(i)
            if len(picked) == k: break
    return picked


def pose(m):
    """4x4 face transformation matrix -> (yaw, pitch) in degrees."""
    r = [[m[i][j] for j in range(3)] for i in range(3)]
    for j in range(3):  # remove the column scale
        s = math.sqrt(sum(r[i][j] ** 2 for i in range(3))) or 1.0
        for i in range(3): r[i][j] /= s
    yaw = math.degrees(math.asin(max(-1.0, min(1.0, -r[2][0]))))
    pitch = math.degrees(math.atan2(r[2][1], r[2][2]))
    return yaw, pitch


def candidate(ts, i, fx, det, sc):
    return {"t": round(ts[i], 3), "score": round(sc[i], 3), "face_x": round(fx[i], 3),
            **{k: round(v, 3) for k, v in det[i].items()}}


def resolve_ref(R, ref, var_idx=0):
    """Resolves "auto"/"auto:N" against the loaded face.json. var_idx = variant position (0 = A)."""
    c = R.get("candidates") or []
    n = var_idx + 1 if ref == "auto" else int(ref.split(":", 1)[1])
    if not 1 <= n <= len(c):
        raise ValueError("asked for candidate %d, but face.json has %d (run face.py with a larger --candidates)" % (n, len(c)))
    return c[n - 1]


# ---------- video ----------

def frames(video, R, fps, width):
    """Yields (t, RGB numpy image) of the camera strip, at `fps` frames per second."""
    import numpy as np
    h = int(round(R["h"] * width / R["w"] / 2)) * 2
    cmd = ["ffmpeg", "-v", "error", "-i", video, "-vf",
           "fps=%g,scale=1080:1920,crop=%d:%d:%d:%d,scale=%d:%d" % (fps, R["w"], R["h"], R["x"], R["y"], width, h),
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        sys.exit("ffmpeg not found in PATH")
    n, size = 0, width * h * 3
    with p:  # closes the pipes even if the consumer stops midway
        while True:
            b = p.stdout.read(size)
            if len(b) < size: break
            yield n / fps, np.frombuffer(b, np.uint8).reshape(h, width, 3)
            n += 1
        err = p.stderr.read().decode("utf-8", "replace").strip()
    if p.returncode or not n:
        sys.exit("face: could not read %s: %s" % (video, err[:300] or "no frames"))


def raw_sharpness(img, lms):
    """Laplacian variance in the face box (grayscale). Higher = sharper."""
    import numpy as np
    h, w = img.shape[:2]
    xs = [p.x for p in lms]; ys = [p.y for p in lms]
    x0, x1 = max(0, int(min(xs) * w)), min(w, int(max(xs) * w) + 1)
    y0, y1 = max(0, int(min(ys) * h)), min(h, int(max(ys) * h) + 1)
    g = img[y0:y1, x0:x1].astype(np.float32).mean(axis=2)
    if g.shape[0] < 3 or g.shape[1] < 3: return 0.0
    lap = g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:] - 4 * g[1:-1, 1:-1]
    return float(lap.var())


def analyze(video, P, model=MODEL):
    try:
        import mediapipe as mp
        from mediapipe.tasks import python as mpt
        from mediapipe.tasks.python import vision
    except ImportError:
        sys.exit("face: MediaPipe is missing (pip install mediapipe numpy Pillow)")
    if not os.path.isfile(model):
        sys.exit("face: model not found at %s: %s" % (model, DOWNLOAD))
    N = {**DEFAULTS, **P.get("neutral", {})}; N["weights"] = {**DEFAULTS["weights"], **N.get("weights", {})}
    opts = vision.FaceLandmarkerOptions(
        base_options=mpt.BaseOptions(model_asset_path=model), running_mode=vision.RunningMode.IMAGE, num_faces=1,
        output_face_blendshapes=True, output_facial_transformation_matrixes=True)
    ts, raw = [], []
    with vision.FaceLandmarker.create_from_options(opts) as lm:
        for t, img in frames(video, P["face_region"], N["fps"], N["width"]):
            ts.append(t)
            r = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=img))
            if not r.face_landmarks:
                raw.append(None); continue
            bs = {c.category_name: c.score for c in r.face_blendshapes[0]}
            yaw, pitch = pose(r.facial_transformation_matrixes[0])
            pts = r.face_landmarks[0]
            raw.append((bs, yaw, pitch, raw_sharpness(img, pts), sum(p.x for p in pts) / len(pts)))
    vals = sorted(b[3] for b in raw if b)
    if not vals:
        sys.exit("face: no face found in the camera strip (check face_region in the preset)")
    med = vals[len(vals) // 2] or 1.0
    det = [None if b is None else penalties(b[0], b[1], b[2], b[3] / med) for b in raw]
    base = baseline(det)
    scores, fx = [], []
    for b, p in zip(raw, det):
        if b is None:
            scores.append(None); fx.append(None); continue
        p.update(subtract_baseline(p, base)); p["yaw"], p["pitch"] = b[1], b[2]
        scores.append(score({k: v for k, v in p.items() if k in N["weights"]}, N["weights"])); fx.append(b[4])
    sm = smooth(scores)
    dur = ts[-1] + 1.0 / N["fps"]
    idx = pick(ts, sm, N["candidates"], N["spacing_s"], N["margin_s"], dur - N["margin_s"])
    return {
        "video": os.path.basename(video), "fps": N["fps"], "weights": N["weights"],
        "baseline": {k: round(v, 3) for k, v in base.items()},
        "frames": len(ts), "no_face": sum(b is None for b in raw),
        "candidates": [candidate(ts, i, fx, det, sm) for i in idx],
        "all": [[round(t, 3), None if n is None else round(n, 3), None if x is None else round(x, 3)]
                for t, n, x in zip(ts, sm, fx)],
    }


def contact_sheet(video, R, P, out):
    """Sheet with the candidates (whole camera frame), numbered in face.json order."""
    from PIL import Image, ImageDraw, ImageFont
    import numpy as np
    f = ImageFont.truetype(os.path.join(ROOT, P["fonts"]["text"]), 26)
    Rv = P["face_region"]; tiles = []
    for k, c in enumerate(R["candidates"], 1):
        img = next(frame_at(video, Rv, c["t"]))
        im = Image.fromarray(img).resize((360, int(360 * img.shape[0] / img.shape[1])))
        d = ImageDraw.Draw(im)
        d.rectangle((0, 0, 360, 36), fill=(0, 0, 0))
        d.text((8, 4), "#%d  %.2fs  score %.2f" % (k, c["t"], c["score"]), font=f, fill=(255, 220, 0))
        tiles.append(im)
    if not tiles: return None
    cols = 3; rows = (len(tiles) + cols - 1) // cols; th = tiles[0].height
    sh = Image.new("RGB", (cols * 366, rows * (th + 6)), (20, 27, 45))
    for i, t in enumerate(tiles): sh.paste(t, ((i % cols) * 366, (i // cols) * (th + 6)))
    p = os.path.join(out, "face_candidates.jpg"); sh.save(p, quality=90)
    return p


def frame_at(video, R, t):
    import numpy as np
    cmd = ["ffmpeg", "-v", "error", "-ss", str(t), "-i", video, "-frames:v", "1", "-vf",
           "scale=1080:1920,crop=%d:%d:%d:%d" % (R["w"], R["h"], R["x"], R["y"]), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    b = subprocess.run(cmd, capture_output=True).stdout
    if len(b) < R["w"] * R["h"] * 3: sys.exit("face: could not extract the frame at %gs" % t)
    yield np.frombuffer(b[:R["w"] * R["h"] * 3], np.uint8).reshape(R["h"], R["w"], 3)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--video", required=True, help="final video (the same one that goes to thumb.py)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--name", help="writes to videos/<name>/")
    g.add_argument("--out", help="output folder")
    ap.add_argument("--preset", default="presets/thumbnail.json")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--candidates", type=int, default=None, help="how many candidates (default: the preset's)")
    a = ap.parse_args(argv)
    if not os.path.isfile(a.video): sys.exit("face: video not found: %s" % a.video)
    P = preset.load(a.preset)
    if a.candidates: P.setdefault("neutral", {})["candidates"] = a.candidates
    out = a.out or os.path.join(ROOT, "videos", a.name)
    os.makedirs(out, exist_ok=True)
    R = analyze(a.video, P, a.model)
    p = os.path.join(out, "face.json")
    with open(p, "w", encoding="utf-8") as f: json.dump(R, f, ensure_ascii=False, indent=1)
    print("%d frames (%d without a face) -> %s" % (R["frames"], R["no_face"], p))
    for k, c in enumerate(R["candidates"], 1):
        print("  #%d  %6.2fs  score %.2f  eyes %.2f mouth %.2f smile %.2f brow %.2f pose %.2f sharpness %.2f"
              % (k, c["t"], c["score"], c["eyes"], c["mouth"], c["smile"], c["brow"], c["pose"], c["sharpness"]))
    s = contact_sheet(a.video, R, P, out)
    if s: print("sheet:", s)
    return R


if __name__ == "__main__":
    main()
