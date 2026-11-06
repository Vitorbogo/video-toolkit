#!/usr/bin/env python3
"""Generates covers (9:16 and 16:9) deterministically from the final video.

Same video + same time + same texts + same preset = same image (nothing random).

Spec (videos/<name>/thumb.json). Option keys: time_s, face_x, title, highlight, kicker, footer.
  - Valid at the top level, in a format block ("vertical": {...}, "youtube": {...}), in a variant and in the
    variant's format block. Precedence: top < format < variant < variant format < --time/--face-x.
    So a different title on the 16:9 goes in "youtube": {"title": .., "highlight": ..} (no second spec needed).
  - "variants": [{"name": "A", ...}, ...] generates one pair of covers per variant
    (cover_<name>_9x16_1080x1920.png / cover_<name>_16x9_1280x720.png); without variants: cover_9x16_... and cover_16x9_...
  - highlight: word(s) of the title painted in the highlight colour. Compared without punctuation and case
    ("homem" finds "homem?"); several words = a sequence in the title. Not found: warning.
  - face_x (fraction 0-1 of the width) only affects the 16:9: centres the square face crop. The 9:16 uses the
    whole camera strip. Without face_x it tries OpenCV (Haar) and, last, the centre.
  - Automatic neutral face (run src/vtk/face.py first; it writes face.json next to the spec):
    "time_s": "auto" uses the candidate at the variant's position (A = 1st, B = 2nd...); "auto:3" uses the 3rd.
    "face_x": "auto" centres the 16:9 on the face in that frame (or in the nearest analysed frame).
    The times used go to covers/covers.json (publish.py reads the TikTok frame from there).
  - Keys starting with "_" are comments. Unknown key, wrong type or text that does not fit: error.
Long texts: the font shrinks until it fits (limits in the preset); if it still does not fit, error asking for shorter text.
Before writing, deletes from the output folder the cover_*.png this spec no longer generates (renamed/removed variant).

  python3 src/vtk/thumb.py --video final.mp4 --spec videos/<name>/thumb.json          # -> videos/<name>/covers/
  python3 src/vtk/thumb.py --video final.mp4 --spec videos/<name>/thumb.json --only youtube
  python3 src/vtk/thumb.py --video final.mp4 --spec videos/<name>/thumb.json --sheet 3,20,48,75  # candidate sheet
  --face <face.json> (default: the one next to the spec) for the "auto" values.
"""
import argparse, functools, glob, json, os, re, subprocess, sys, unicodedata
from io import BytesIO
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.path.join(ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "src"))
from vtk import preset

TEXTS = ("title", "highlight", "kicker", "footer")
OPTIONS = ("time_s", "face_x") + TEXTS
FORMATS = ("vertical", "youtube")
FILES = {"vertical": "cover%s_9x16_1080x1920.png", "youtube": "cover%s_16x9_1280x720.png"}  # names used by publish.py

AUTO_T = re.compile(r"auto(:[1-9][0-9]*)?$")
hexrgb = lambda h: tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))
num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)


# ---------- spec ----------

def _check(d, where, valid, errors):
    if not isinstance(d, dict):
        errors.append("%s must be an object {...}" % where); return False
    for k, v in d.items():
        if k.startswith("_"): continue
        if k not in valid:
            errors.append("%s: unknown key '%s' (valid: %s)" % (where, k, ", ".join(valid)))
        elif k == "time_s" and not (isinstance(v, str) and AUTO_T.match(v)) and (not num(v) or v < 0):
            errors.append("%s.time_s must be a number >= 0, \"auto\" or \"auto:N\" (got %r)" % (where, v))
        elif k == "face_x" and v is not None and v != "auto" and (not num(v) or not 0 <= v <= 1):
            errors.append("%s.face_x must be a number between 0 and 1 or \"auto\" (got %r)" % (where, v))
        elif k in TEXTS and not isinstance(v, str):
            errors.append("%s.%s must be text (got %r)" % (where, k, v))
    return True


def variants(S):
    return S.get("variants") or [{}]


def resolve(S, v, fmt, time=None, face_x=None):
    """Options of one cover: top < format < variant < variant format < CLI."""
    o = {"face_x": None, **{k: "" for k in TEXTS}}
    for layer in (S, S.get(fmt) or {}, v, v.get(fmt) or {}):
        o.update({k: layer[k] for k in OPTIONS if k in layer})
    if time is not None: o["time_s"] = time
    if face_x is not None: o["face_x"] = face_x
    return o


def validate(S):
    if not isinstance(S, dict): sys.exit("spec: thumb.json must be an object {...}")
    errors = []
    _check(S, "spec", OPTIONS + FORMATS + ("variants",), errors)
    for f in FORMATS:
        if f in S: _check(S[f], f, OPTIONS, errors)
    if "variants" in S:
        vs = S["variants"]
        if not isinstance(vs, list) or not vs:
            errors.append("variants must be a list with at least one variant (or remove the key)")
        else:
            names = set()
            for i, v in enumerate(vs):
                where = "variants[%d]" % i
                if not _check(v, where, OPTIONS + FORMATS + ("name",), errors): continue
                n = v.get("name")
                if not isinstance(n, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", n):
                    errors.append("%s.name is required: letters, digits, - or _ (goes in the file name; got %r)" % (where, n))
                elif n in names:
                    errors.append("%s.name repeated: %r" % (where, n))
                else:
                    names.add(n)
                for f in FORMATS:
                    if f in v: _check(v[f], "%s.%s" % (where, f), OPTIONS, errors)
    if not errors:
        for v in variants(S):
            for f in FORMATS:
                o, where = resolve(S, v, f), "%s%s" % ("variant %s, " % v["name"] if v else "", f)
                if not o["title"].strip(): errors.append("missing title (%s)" % where)
                if o.get("time_s") is None: errors.append("missing time_s (%s)" % where)
    if errors: sys.exit("invalid spec:\n  - " + "\n  - ".join(errors))


def uses_auto(S):
    """Does the (already validated) spec have any "auto" in time_s or face_x?"""
    return any(isinstance(o.get("time_s"), str) or o.get("face_x") == "auto"
               for o in (resolve(S, v, f) for v in variants(S) for f in FORMATS))


def read_face(path, video):
    """face.json from face.py. Warns if it was made from another video (stale analysis)."""
    try:
        with open(path, encoding="utf-8") as f: R = json.load(f)
    except OSError:
        sys.exit("thumb.json uses \"auto\", but %s was not found: run first\n  python3 src/vtk/face.py --video %s --out %s"
                 % (path, video, os.path.dirname(path) or "."))
    except ValueError as e:
        sys.exit("invalid face.json (%s): %s" % (path, e))
    if R.get("video") and R["video"] != os.path.basename(video):
        print("WARNING: %s was made from %s, not %s: run face.py again if the video changed"
              % (path, R["video"], os.path.basename(video)))
    return R


def auto(o, R, var_idx):
    """Replaces "auto" in time_s / face_x with the values from face.json."""
    t, c = o["time_s"], None
    if isinstance(t, str):
        n = var_idx + 1 if t == "auto" else int(t.split(":", 1)[1])
        cs = (R or {}).get("candidates") or []
        if not 1 <= n <= len(cs):
            sys.exit("time_s %r asks for candidate %d, but face.json has %d (face.py --candidates N)" % (t, n, len(cs)))
        c = cs[n - 1]; o["time_s"] = c["t"]
    if o.get("face_x") == "auto":
        if c is None:  # fixed time: face of the nearest analysed frame
            vs = [x for x in (R or {}).get("all") or [] if x[2] is not None]
            if not vs: sys.exit("face_x \"auto\" but face.json has no frames with a face")
            c = {"face_x": min(vs, key=lambda x: abs(x[0] - float(o["time_s"])))[2]}
        o["face_x"] = c["face_x"]
    return o


def parse_sheet(s):
    try: ts = [float(x) for x in s.split(",") if x.strip()]
    except ValueError: sys.exit("--sheet: use comma-separated times in seconds, e.g. 3,20,48.5 (got %r)" % s)
    if not ts or any(t < 0 for t in ts): sys.exit("--sheet: needs at least one time, all >= 0 (got %r)" % s)
    return ts


# ---------- highlight ----------

def norm(w):
    w = unicodedata.normalize("NFC", w).casefold()
    return "".join(c for c in w if not unicodedata.category(c).startswith("P"))


def highlight(words, hl_text):
    """Indices of the title words that form the highlight (a sequence, no punctuation, no case)."""
    d = [t for t in (norm(x) for x in hl_text.split()) if t]
    if not d: return set()
    toks, n, hl = [norm(w) for w in words], len(d), set()
    for i in range(len(toks) - n + 1):
        if toks[i:i + n] == d: hl.update(range(i, i + n))
    if not hl: print("WARNING: highlight %r does not appear in the title %r" % (hl_text, " ".join(words)))
    return hl


# ---------- text ----------

@functools.lru_cache(None)
def font(path, size):
    return ImageFont.truetype(path, size)


def wrap(words, f, maxw):
    """Breaks into lines (lists of indices) that fit in maxw. A word wider than maxw stays alone (fit avoids it)."""
    lines, cur = [], []
    for i in range(len(words)):
        if not cur or f.getlength(" ".join(words[j] for j in cur + [i])) <= maxw: cur.append(i)
        else: lines.append(cur); cur = [i]
    if cur: lines.append(cur)
    return lines


def fit(text, fpath, cfg, maxw, max_h=None, name="text"):
    """Largest font (from cfg.size down to cfg.size_min, 2 at a time) where the longest word fits in maxw, the text
    fits in cfg.max_lines lines and the block (lines x line_height) in max_h. -> (font, words, lines, line height)."""
    words = text.split()
    for size in range(cfg["size"], cfg["size_min"] - 1, -2):
        f, lh = font(fpath, size), int(size * cfg["line_height"])
        if max(f.getlength(w) for w in words) > maxw: continue
        lines = wrap(words, f, maxw)
        if len(lines) > cfg["max_lines"] or (max_h is not None and len(lines) * lh > max_h): continue
        return f, words, lines, lh
    sys.exit("%s does not fit on the cover even at font size %d (width %d px, up to %d lines%s): shorten the text: %r"
             % (name, cfg["size_min"], maxw, cfg["max_lines"], "" if max_h is None else ", height %d px" % max_h, text))


def block_h(t):
    f, words, lines, lh = t
    return (len(lines) - 1) * lh + f.getbbox(" ".join(words[i] for i in lines[-1]))[3]


def draw_lines(d, x, y, t, color, boxes, name, hl=(), color_hl=None):
    f, words, lines, lh = t
    for line in lines:
        cx = x
        for i in line:
            d.text((cx, y), words[i], font=f, fill=color_hl if i in hl else color); cx += f.getlength(words[i] + " ")
        boxes.append((name, d.textbbox((x, y), " ".join(words[i] for i in line), font=f)))
        y += lh
    return y


def inside(boxes, W, top, bot, fmt):
    for name, (x0, y0, x1, y1) in boxes:
        if x0 < 0 or x1 > W or y0 < top or y1 > bot:
            sys.exit("cover %s: %s leaves the safe area (y %d-%d): box %s. Shorten the texts or adjust the preset"
                     % (fmt, name, top, bot, (x0, y0, x1, y1)))


# ---------- image ----------

def frame(video, t, R):
    try:
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", video, "-frames:v", "1",
                            # the face crop is in pixels of the 1080x1920 final: a smaller preview (--scale 0.5) is upscaled first
                            "-vf", "scale=1080:1920:flags=lanczos,crop=%d:%d:%d:%d" % (R["w"], R["h"], R["x"], R["y"]),
                            "-f", "image2pipe", "-c:v", "png", "-"], capture_output=True)
    except FileNotFoundError: sys.exit("ffmpeg not found in PATH")
    if r.returncode or not r.stdout:
        err = r.stderr.decode("utf-8", "replace").strip()[:300]
        sys.exit("could not extract the frame at t=%gs from %s: %s" % (t, video, err or "time past the end of the video?"))
    return Image.open(BytesIO(r.stdout)).convert("RGB")


def tune(im, I):
    im = ImageEnhance.Contrast(im).enhance(I["contrast"]); im = ImageEnhance.Color(im).enhance(I["saturation"])
    return ImageEnhance.Brightness(im).enhance(I["brightness"])


def face_cx(im, face_x):
    if face_x is not None: return float(face_x) * im.width
    try:
        import cv2, numpy as np
        g = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2GRAY)
        if not hasattr(cv2, "CascadeClassifier"): raise RuntimeError("this OpenCV build has no CascadeClassifier")
        cas = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        f = cas.detectMultiScale(g, 1.1, 5, minSize=(80, 80))
        if len(f):
            x, y, w, h = max(f, key=lambda r: r[2] * r[3]); return x + w / 2
    except Exception as e:
        print("WARNING: face detection unavailable:", e)
    return im.width / 2


def square(im, face_x):
    s = min(im.width, im.height); cx = face_cx(im, face_x)
    x0 = int(min(max(cx - s / 2, 0), im.width - s)); return im.crop((x0, 0, x0 + s, s))


def rounded(im, r):
    m = Image.new("L", im.size, 0); ImageDraw.Draw(m).rounded_rectangle((0, 0) + im.size, r, fill=255)
    o = Image.new("RGBA", im.size); o.paste(im, (0, 0), m); return o


class Cover:
    def __init__(self, P):
        self.P, self.C = P, {k: hexrgb(v) for k, v in P["colors"].items() if not k.startswith("_")}
        self.F_T = os.path.join(ROOT, P["fonts"]["title"]); self.F_X = os.path.join(ROOT, P["fonts"]["text"])

    def kicker(self, d, o, x, K, tw, boxes, fmt):
        """Draws the kicker (if any) and returns how much it grew beyond 1 line."""
        if not o["kicker"].strip(): return 0
        t = fit(o["kicker"], self.F_X, K, tw, name="kicker (%s)" % fmt)
        draw_lines(d, x, K["y"], t, self.C["highlight"], boxes, "kicker")
        return (len(t[2]) - 1) * t[3]

    def vertical(self, face, o):
        L, C = self.P["vertical_9x16"], self.C
        W, H, (top, bot), mx = L["w"], L["h"], L["safe"], L["margin_x"]
        K, B, T, Fc, Ft, tw = L["kicker"], L["bar"], L["title"], L["face"], L["footer"], W - 2 * L["margin_x"]
        im = Image.new("RGB", (W, H), C["background"]); d = ImageDraw.Draw(im); boxes = []
        extra = self.kicker(d, o, mx, K, tw, boxes, "9:16")
        by = K["y"] + B["dy"] + extra
        d.rectangle((mx, by, mx + B["w"], by + B["h"]), fill=C["highlight"])
        ty = T["y"] + extra
        fw = W - 2 * Fc["margin_x"]; fh = int(fw * face.height / face.width)
        lim, r = bot, None
        if o["footer"].strip():
            r = fit(o["footer"], self.F_X, Ft, tw, name="footer (9:16)")
            ry = min(Ft["y"], bot - block_h(r)); lim = ry - Fc["footer_gap"]
        t = fit(o["title"], self.F_T, T, tw, lim - fh - Fc["dy"] - ty, name="title (9:16)")
        y = draw_lines(d, mx, ty, t, C["text"], boxes, "title", highlight(t[1], o["highlight"]), C["highlight"])
        fy = max(y + Fc["dy"], Fc["y_min"])
        if fy + fh > lim: sys.exit("cover 9:16: the face does not fit between the title and the footer; shorten the texts")
        f = rounded(face.resize((fw, fh)), Fc["radius"]); im.paste(f, (Fc["margin_x"], fy), f)
        boxes.append(("face", (Fc["margin_x"], fy, Fc["margin_x"] + fw, fy + fh)))
        if r: draw_lines(d, mx, ry, r, C["muted"], boxes, "footer")
        inside(boxes, W, top, bot, "9:16")
        return im

    def youtube(self, face, o):
        L, C = self.P["youtube_16x9"], self.C
        W, H, (top, bot), mx = L["w"], L["h"], L["safe"], L["margin_x"]
        K, T, Ft, tw = L["kicker"], L["title"], L["footer"], W - H - L["margin_x"] - L["margin_right"]
        im = Image.new("RGB", (W, H), C["background"]); d = ImageDraw.Draw(im); boxes = []
        im.paste(square(face, o["face_x"]).resize((H, H)), (W - H, 0))
        d.rectangle((W - H - 10, 0, W - H, H), fill=C["highlight"])
        ty = T["y"] + self.kicker(d, o, mx, K, tw, boxes, "16:9")
        lim, r = bot, None
        if o["footer"].strip():
            r = fit(o["footer"], self.F_X, Ft, tw, name="footer (16:9)")
            ry = min(Ft["y"], bot - block_h(r)); lim = ry - Ft["gap"]
        t = fit(o["title"], self.F_T, T, tw, lim - ty, name="title (16:9)")
        draw_lines(d, mx, ty, t, C["text"], boxes, "title", highlight(t[1], o["highlight"]), C["highlight"])
        if r: draw_lines(d, mx, ry, r, C["muted"], boxes, "footer")
        inside(boxes, W - H, top, bot, "16:9")
        return im


def sheet(video, ts, P, out):
    R, f = P["face_region"], font(os.path.join(ROOT, P["fonts"]["text"]), 28); tiles = []
    for t in ts:
        im = frame(video, t, R).resize((360, 203)); ImageDraw.Draw(im).text((8, 8), "%gs" % t, font=f, fill=(255, 255, 0))
        tiles.append(im)
    cols = 4; rows = (len(tiles) + cols - 1) // cols
    sh = Image.new("RGB", (cols * 366, rows * 209), hexrgb(P["colors"]["background"]))
    for i, t in enumerate(tiles): sh.paste(t, ((i % cols) * 366, (i // cols) * 209))
    p = os.path.join(out, "candidates.jpg"); sh.save(p, quality=90); print("sheet:", p)
    return p


def run(video, S, P, out, only=None, time=None, face_x=None, face=None):
    """Generates the covers. Returns {file: path}. Validates everything and builds the images before writing/deleting.
    face: dict from face.json (needed if the spec uses "auto")."""
    validate(S)
    fmts = (only,) if only else FORMATS
    cover, frames, imgs, used = Cover(P), {}, [], {}
    for vi, v in enumerate(variants(S)):
        suf = "_" + v["name"] if v else ""
        for fmt in fmts:
            o = auto(resolve(S, v, fmt, time, face_x), face, vi); t = float(o["time_s"])
            used.setdefault(v.get("name", ""), {})[fmt] = {"time_s": t, "face_x": o["face_x"]}
            if t not in frames: frames[t] = tune(frame(video, t, P["face_region"]), P["image"])
            imgs.append((FILES[fmt] % suf, getattr(cover, fmt)(frames[t], o)))
            print("%s%s: frame %gs%s" % (fmt, " " + v["name"] if v else "", t,
                                         " face_x %s" % o["face_x"] if fmt == "youtube" else ""))
    valid = {FILES[f] % ("_" + v["name"] if v else "") for v in variants(S) for f in FORMATS}
    os.makedirs(out, exist_ok=True)
    for p in sorted(glob.glob(os.path.join(out, "cover_*.png"))):
        if os.path.basename(p) not in valid: os.remove(p); print("removed (the spec no longer generates it):", p)
    made = {}
    for nm, im in imgs:
        p = os.path.join(out, nm); im.save(p); made[nm] = p; print("  ->", p)
    mp = os.path.join(out, "covers.json")  # frames used (publish.py reads the TikTok time from here)
    try:
        with open(mp, encoding="utf-8") as f: prev = json.load(f)
    except (OSError, ValueError): prev = {}
    if only:  # --only: keep the other format from the previous record
        for name, fs in prev.items():
            for f, val in fs.items(): used.setdefault(name, {}).setdefault(f, val)
    with open(mp, "w", encoding="utf-8") as f: json.dump(used, f, ensure_ascii=False, indent=1, sort_keys=True)
    return made


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--video", required=True); ap.add_argument("--spec", required=True)
    ap.add_argument("--out", default=None, help="covers folder (default: <spec folder>/covers)")
    ap.add_argument("--preset", default="presets/thumbnail.json")
    ap.add_argument("--only", choices=FORMATS, default=None, help="generate only one format")
    ap.add_argument("--time", type=float, default=None, help="overrides time_s of every cover")
    ap.add_argument("--face-x", type=float, default=None, help="overrides face_x (fraction 0-1; only changes the 16:9)")
    ap.add_argument("--face", default=None, help="face.json from face.py (default: the one in the spec folder)")
    ap.add_argument("--sheet", default=None, help="list of times (e.g. 3,20,48,75) for a candidate sheet")
    a = ap.parse_args(argv)
    if a.time is not None and a.time < 0: sys.exit("--time must be >= 0")
    if a.face_x is not None and not 0 <= a.face_x <= 1: sys.exit("--face-x must be between 0 and 1")
    if not os.path.exists(a.video): sys.exit("video not found: %s" % a.video)
    try:
        with open(a.spec, encoding="utf-8") as f: S = json.load(f)
    except (OSError, ValueError) as e: sys.exit("spec: could not read %s: %s" % (a.spec, e))
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.spec)), "covers")
    P = preset.load(a.preset)
    if a.sheet:
        ts = parse_sheet(a.sheet); os.makedirs(out, exist_ok=True); return sheet(a.video, ts, P, out)
    validate(S)
    R = None
    if uses_auto(S) or a.face:
        R = read_face(a.face or os.path.join(os.path.dirname(os.path.abspath(a.spec)), "face.json"), a.video)
    return run(a.video, S, P, out, a.only, a.time, a.face_x, R)


if __name__ == "__main__":
    main()
