#!/usr/bin/env python3
"""Gera capas (9:16 e 16:9) de forma deterministica a partir do video final.

Mesmo video + mesmo tempo + mesmos textos + mesmo preset = mesma imagem (nada aleatorio).
O rosto e centralizado em "rosto_x" (fracao 0-1 da largura, no spec); sem isso tenta OpenCV (Haar), e por fim usa o centro.

Cada formato pode usar um quadro proprio. No spec:
  "tempo_s"/"rosto_x": padrao para os dois formatos
  "vertical": {"tempo_s":..,"rosto_x":..}  e  "youtube": {...}  sobrescrevem por formato
  "variantes": [{"nome":"A","vertical":{...},"youtube":{...}}, ...]  gera um par de capas por variante
    (arquivos capa_<nome>_9x16_1080x1920.png / capa_<nome>_16x9_1280x720.png)

  python3 src/vtk/thumb.py --video final.mp4 --spec videos/<nome>/thumb.json --out capas/
  # --sheet gera uma folha de candidatos (tempos) para escolher o quadro
"""
import argparse, json, os, subprocess, sys, tempfile
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

ap = argparse.ArgumentParser()
ap.add_argument("--video", required=True); ap.add_argument("--spec", required=True)
ap.add_argument("--out", required=True); ap.add_argument("--preset", default="presets/thumbnail.json")
ap.add_argument("--time", type=float, default=None, help="sobrescreve o tempo do spec")
ap.add_argument("--rosto-x", type=float, default=None, help="sobrescreve rosto_x do spec (fracao 0-1)")
ap.add_argument("--sheet", default=None, help="lista de tempos (ex.: 3,20,48,75) para folha de candidatos")
a = ap.parse_args()
root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
P = json.load(open(a.preset if os.path.isabs(a.preset) else os.path.join(root, a.preset)))
S = json.load(open(a.spec)); os.makedirs(a.out, exist_ok=True)
if a.rosto_x is not None: S["rosto_x"] = a.rosto_x
CUR = {}
C = P["cores"]; R = P["rosto_no_video"]
hexrgb = lambda h: tuple(int(h[i:i+2], 16) for i in (1, 3, 5))
F_T = os.path.join(root, P["fontes"]["titulo"]); F_X = os.path.join(root, P["fontes"]["texto"])

def frame(t):
    tmp = tempfile.mktemp(suffix=".png")
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", a.video, "-frames:v", "1",
                        "-vf", f"crop={R['w']}:{R['h']}:{R['x']}:{R['y']}", tmp], capture_output=True, text=True)
    if r.returncode or not os.path.exists(tmp): sys.exit("nao consegui extrair o quadro em t=%s: %s" % (t, r.stderr[-200:]))
    im = Image.open(tmp).convert("RGB"); os.remove(tmp); return im

def tune(im):
    I = P["imagem"]
    im = ImageEnhance.Contrast(im).enhance(I["contraste"]); im = ImageEnhance.Color(im).enhance(I["cor"])
    return ImageEnhance.Brightness(im).enhance(I["brilho"])

def face_cx(im):
    if CUR.get("rosto_x") is not None: return float(CUR["rosto_x"]) * im.width
    try:
        import cv2, numpy as np
        g = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2GRAY)
        if not hasattr(cv2, "CascadeClassifier"): raise RuntimeError("esta versao do OpenCV nao tem CascadeClassifier")
        cas = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        f = cas.detectMultiScale(g, 1.1, 5, minSize=(80, 80))
        if len(f):
            x, y, w, h = max(f, key=lambda r: r[2] * r[3]); return x + w / 2
    except Exception as e:
        print("aviso: deteccao de rosto indisponivel:", e)
    return im.width / 2

def square(im):
    s = min(im.width, im.height); cx = face_cx(im)
    x0 = int(min(max(cx - s / 2, 0), im.width - s)); return im.crop((x0, 0, x0 + s, s))

def rounded(im, r):
    m = Image.new("L", im.size, 0); ImageDraw.Draw(m).rounded_rectangle((0, 0) + im.size, r, fill=255)
    o = Image.new("RGBA", im.size); o.paste(im, (0, 0), m); return o

def wrap(draw, text, font, maxw):
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= maxw or not cur: cur = t
        else: lines.append(cur); cur = w
    if cur: lines.append(cur)
    return lines

def title_block(draw, x, y, text, destaque, size, maxw, lh=1.12):
    font = ImageFont.truetype(F_T, size)
    for line in wrap(draw, text, font, maxw):
        cx = x
        for w in line.split():
            col = hexrgb(C["destaque"]) if w.lower().strip(".,!?") == destaque.lower() else hexrgb(C["texto"])
            draw.text((cx, y), w, font=font, fill=col); cx += draw.textlength(w + " ", font=font)
        y += int(size * lh)
    return y

def vertical(face):
    W, H = P["vertical_9x16"]["w"], P["vertical_9x16"]["h"]
    im = Image.new("RGB", (W, H), hexrgb(C["fundo"])); d = ImageDraw.Draw(im)
    d.text((90, 300), S["kicker"], font=ImageFont.truetype(F_X, 38), fill=hexrgb(C["destaque"]))
    d.rectangle((90, 360, 90 + 110, 368), fill=hexrgb(C["destaque"]))
    y = title_block(d, 90, 410, S["titulo"], S["destaque"], 112, W - 180)
    f = rounded(face.resize((W - 120, int((W - 120) * face.height / face.width))), 36)
    im.paste(f, (60, max(y + 60, 940)), f)
    d.text((90, 1590), S["rodape"], font=ImageFont.truetype(F_X, 36), fill=hexrgb(C["suave"]))
    return im

def horizontal(face):
    W, H = P["youtube_16x9"]["w"], P["youtube_16x9"]["h"]
    im = Image.new("RGB", (W, H), hexrgb(C["fundo"])); d = ImageDraw.Draw(im)
    sq = rounded(square(face).resize((H, H)), 0); im.paste(sq, (W - H, 0), sq)
    d.rectangle((W - H - 10, 0, W - H, H), fill=hexrgb(C["destaque"]))
    d.text((70, 90), S["kicker"], font=ImageFont.truetype(F_X, 34), fill=hexrgb(C["destaque"]))
    title_block(d, 70, 150, S["titulo"], S["destaque"], 84, W - H - 120, 1.1)
    d.text((70, H - 90), S["rodape"], font=ImageFont.truetype(F_X, 30), fill=hexrgb(C["suave"]))
    return im

if a.sheet:
    ts = [float(x) for x in a.sheet.split(",")]; tiles = []
    for t in ts:
        im = frame(t).resize((360, 203)); ImageDraw.Draw(im).text((8, 8), "%gs" % t, font=ImageFont.truetype(F_X, 28), fill=(255, 255, 0)); tiles.append(im)
    cols = 4; rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 366, rows * 209), hexrgb(C["fundo"]))
    for i, t in enumerate(tiles): sheet.paste(t, ((i % cols) * 366, (i // cols) * 209))
    sheet.save(os.path.join(a.out, "candidatos.jpg"), quality=90); print("folha:", os.path.join(a.out, "candidatos.jpg")); sys.exit()

def opts(base, fmt):
    o = {"tempo_s": base.get("tempo_s", S.get("tempo_s")), "rosto_x": base.get("rosto_x", S.get("rosto_x"))}
    o.update(base.get(fmt, {}))
    if a.time is not None: o["tempo_s"] = a.time
    return o

def make(base, nome):
    suf = ("_" + nome) if nome else ""
    for fmt, fn, nm in (("vertical", vertical, "capa%s_9x16_1080x1920.png"), ("youtube", horizontal, "capa%s_16x9_1280x720.png")):
        o = opts(base, fmt); CUR.clear(); CUR.update(o)
        if o["tempo_s"] is None: sys.exit("falta tempo_s no spec")
        out = os.path.join(a.out, nm % suf); fn(tune(frame(o["tempo_s"]))).save(out)
        print("%s: quadro %gs rosto_x %s -> %s" % (fmt, o["tempo_s"], o["rosto_x"], out))

for v in (S.get("variantes") or [{}]):
    make(v, v.get("nome", ""))
