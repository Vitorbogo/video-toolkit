#!/usr/bin/env python3
"""Gera capas (9:16 e 16:9) de forma deterministica a partir do video final.

Mesmo video + mesmo tempo + mesmos textos + mesmo preset = mesma imagem (nada aleatorio).

Spec (videos/<nome>/thumb.json). Chaves de opcao: tempo_s, rosto_x, titulo, destaque, kicker, rodape.
  - Valem no topo, num bloco de formato ("vertical": {...}, "youtube": {...}), numa variante e no bloco de formato
    da variante. Precedencia: topo < formato < variante < formato da variante < --time/--rosto-x.
    Assim um titulo diferente no 16:9 vai em "youtube": {"titulo": .., "destaque": ..} (nao precisa de outro spec).
  - "variantes": [{"nome": "A", ...}, ...] gera um par de capas por variante
    (capa_<nome>_9x16_1080x1920.png / capa_<nome>_16x9_1280x720.png); sem variantes: capa_9x16_... e capa_16x9_...
  - destaque: palavra(s) do titulo pintadas na cor de destaque. Compara sem pontuacao e sem caixa
    ("homem" acha "homem?"); varias palavras = sequencia no titulo. Nao achou: aviso.
  - rosto_x (fracao 0-1 da largura) so serve ao 16:9: centraliza o recorte quadrado do rosto. O 9:16 usa a faixa
    inteira da camera. Sem rosto_x tenta OpenCV (Haar) e, por fim, o centro.
  - Rosto neutro automatico (rode antes src/vtk/rosto.py, que grava rosto.json ao lado do spec):
    "tempo_s": "auto" usa o candidato da posicao da variante (A = 1o, B = 2o...); "auto:3" usa o 3o.
    "rosto_x": "auto" centraliza o 16:9 no rosto daquele quadro (ou do quadro analisado mais perto).
    Os tempos usados ficam em capas/capas.json (o publish.py le de la o quadro do TikTok).
  - Chaves comecando com "_" sao comentarios. Chave desconhecida, tipo errado ou texto que nao cabe: erro.
Textos grandes: a fonte diminui ate caber (limites no preset); nao cabendo, erro pedindo texto mais curto.
Antes de gravar, apaga da pasta de saida as capa_*.png que este spec nao gera mais (variante renomeada/removida).

  python3 src/vtk/thumb.py --video final.mp4 --spec videos/<nome>/thumb.json          # -> videos/<nome>/capas/
  python3 src/vtk/thumb.py --video final.mp4 --spec videos/<nome>/thumb.json --only youtube
  python3 src/vtk/thumb.py --video final.mp4 --spec videos/<nome>/thumb.json --sheet 3,20,48,75  # folha de candidatos
  --rosto <rosto.json> (padrao: o do lado do spec) para os "auto".
"""
import argparse, functools, glob, json, os, re, subprocess, sys, unicodedata
from io import BytesIO
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.path.join(ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "src"))
from vtk import preset

TEXTOS = ("titulo", "destaque", "kicker", "rodape")
OPCOES = ("tempo_s", "rosto_x") + TEXTOS
FORMATOS = ("vertical", "youtube")
ARQ = {"vertical": "capa%s_9x16_1080x1920.png", "youtube": "capa%s_16x9_1280x720.png"}  # nomes usados pelo publish.py

AUTO_T = re.compile(r"auto(:[1-9][0-9]*)?$")
hexrgb = lambda h: tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))
num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)


# ---------- spec ----------

def _check(d, onde, validas, erros):
    if not isinstance(d, dict):
        erros.append("%s precisa ser um objeto {...}" % onde); return False
    for k, v in d.items():
        if k.startswith("_"): continue
        if k not in validas:
            erros.append("%s: chave desconhecida '%s' (validas: %s)" % (onde, k, ", ".join(validas)))
        elif k == "tempo_s" and not (isinstance(v, str) and AUTO_T.match(v)) and (not num(v) or v < 0):
            erros.append("%s.tempo_s deve ser um numero >= 0, \"auto\" ou \"auto:N\" (veio %r)" % (onde, v))
        elif k == "rosto_x" and v is not None and v != "auto" and (not num(v) or not 0 <= v <= 1):
            erros.append("%s.rosto_x deve ser um numero entre 0 e 1 ou \"auto\" (veio %r)" % (onde, v))
        elif k in TEXTOS and not isinstance(v, str):
            erros.append("%s.%s deve ser texto (veio %r)" % (onde, k, v))
    return True


def variantes(S):
    return S.get("variantes") or [{}]


def resolve(S, v, fmt, time=None, rosto_x=None):
    """Opcoes de uma capa: topo < formato < variante < formato da variante < CLI."""
    o = {"rosto_x": None, **{k: "" for k in TEXTOS}}
    for camada in (S, S.get(fmt) or {}, v, v.get(fmt) or {}):
        o.update({k: camada[k] for k in OPCOES if k in camada})
    if time is not None: o["tempo_s"] = time
    if rosto_x is not None: o["rosto_x"] = rosto_x
    return o


def validate(S):
    if not isinstance(S, dict): sys.exit("spec: o thumb.json precisa ser um objeto {...}")
    erros = []
    _check(S, "spec", OPCOES + FORMATOS + ("variantes",), erros)
    for f in FORMATOS:
        if f in S: _check(S[f], f, OPCOES, erros)
    if "variantes" in S:
        vs = S["variantes"]
        if not isinstance(vs, list) or not vs:
            erros.append("variantes precisa ser uma lista com pelo menos uma variante (ou tire a chave)")
        else:
            nomes = set()
            for i, v in enumerate(vs):
                onde = "variantes[%d]" % i
                if not _check(v, onde, OPCOES + FORMATOS + ("nome",), erros): continue
                n = v.get("nome")
                if not isinstance(n, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", n):
                    erros.append("%s.nome e obrigatorio: letras, numeros, - ou _ (vai no nome do arquivo; veio %r)" % (onde, n))
                elif n in nomes:
                    erros.append("%s.nome repetido: %r" % (onde, n))
                else:
                    nomes.add(n)
                for f in FORMATOS:
                    if f in v: _check(v[f], "%s.%s" % (onde, f), OPCOES, erros)
    if not erros:
        for v in variantes(S):
            for f in FORMATOS:
                o, onde = resolve(S, v, f), "%s%s" % ("variante %s, " % v["nome"] if v else "", f)
                if not o["titulo"].strip(): erros.append("falta titulo (%s)" % onde)
                if o.get("tempo_s") is None: erros.append("falta tempo_s (%s)" % onde)
    if erros: sys.exit("spec invalido:\n  - " + "\n  - ".join(erros))


def usa_auto(S):
    """O spec (ja validado) tem algum "auto" em tempo_s ou rosto_x?"""
    return any(isinstance(o.get("tempo_s"), str) or o.get("rosto_x") == "auto"
               for o in (resolve(S, v, f) for v in variantes(S) for f in FORMATOS))


def ler_rosto(path, video):
    """rosto.json do rosto.py. Avisa se foi feito com outro video (analise velha)."""
    try:
        with open(path, encoding="utf-8") as f: R = json.load(f)
    except OSError:
        sys.exit("o thumb.json usa \"auto\", mas nao achei %s: rode antes\n  python3 src/vtk/rosto.py --video %s --out %s"
                 % (path, video, os.path.dirname(path) or "."))
    except ValueError as e:
        sys.exit("rosto.json invalido (%s): %s" % (path, e))
    if R.get("video") and R["video"] != os.path.basename(video):
        print("aviso: %s foi feito com %s, nao com %s: rode o rosto.py de novo se o video mudou"
              % (path, R["video"], os.path.basename(video)))
    return R


def auto(o, R, var_idx):
    """Troca "auto" de tempo_s / rosto_x pelos valores do rosto.json."""
    t, c = o["tempo_s"], None
    if isinstance(t, str):
        n = var_idx + 1 if t == "auto" else int(t.split(":", 1)[1])
        cs = (R or {}).get("candidatos") or []
        if not 1 <= n <= len(cs):
            sys.exit("tempo_s %r pede o candidato %d, mas o rosto.json tem %d (rosto.py --candidatos N)" % (t, n, len(cs)))
        c = cs[n - 1]; o["tempo_s"] = c["t"]
    if o.get("rosto_x") == "auto":
        if c is None:  # tempo fixo: rosto do quadro analisado mais perto
            vs = [x for x in (R or {}).get("todos") or [] if x[2] is not None]
            if not vs: sys.exit("rosto_x \"auto\" sem quadros com rosto no rosto.json")
            c = {"rosto_x": min(vs, key=lambda x: abs(x[0] - float(o["tempo_s"])))[2]}
        o["rosto_x"] = c["rosto_x"]
    return o


def parse_sheet(s):
    try: ts = [float(x) for x in s.split(",") if x.strip()]
    except ValueError: sys.exit("--sheet: use tempos em segundos separados por virgula, ex.: 3,20,48.5 (veio %r)" % s)
    if not ts or any(t < 0 for t in ts): sys.exit("--sheet: precisa de pelo menos um tempo, todos >= 0 (veio %r)" % s)
    return ts


# ---------- destaque ----------

def norm(w):
    w = unicodedata.normalize("NFC", w).casefold()
    return "".join(c for c in w if not unicodedata.category(c).startswith("P"))


def highlight(words, destaque):
    """Indices das palavras do titulo que formam o destaque (sequencia, sem pontuacao, sem caixa)."""
    d = [t for t in (norm(x) for x in destaque.split()) if t]
    if not d: return set()
    toks, n, hl = [norm(w) for w in words], len(d), set()
    for i in range(len(toks) - n + 1):
        if toks[i:i + n] == d: hl.update(range(i, i + n))
    if not hl: print("aviso: destaque %r nao aparece no titulo %r" % (destaque, " ".join(words)))
    return hl


# ---------- texto ----------

@functools.lru_cache(None)
def font(path, size):
    return ImageFont.truetype(path, size)


def wrap(words, f, maxw):
    """Quebra em linhas (listas de indices) que cabem em maxw. Palavra maior que maxw fica sozinha (fit evita)."""
    lines, cur = [], []
    for i in range(len(words)):
        if not cur or f.getlength(" ".join(words[j] for j in cur + [i])) <= maxw: cur.append(i)
        else: lines.append(cur); cur = [i]
    if cur: lines.append(cur)
    return lines


def fit(text, fpath, cfg, maxw, max_h=None, nome="texto"):
    """Maior fonte (de cfg.tam ate cfg.tam_min, de 2 em 2) em que a palavra mais longa cabe em maxw, o texto
    cabe em cfg.linhas_max linhas e o bloco (linhas x entrelinha) em max_h. -> (fonte, palavras, linhas, entrelinha)."""
    words = text.split()
    for size in range(cfg["tam"], cfg["tam_min"] - 1, -2):
        f, lh = font(fpath, size), int(size * cfg["entrelinha"])
        if max(f.getlength(w) for w in words) > maxw: continue
        lines = wrap(words, f, maxw)
        if len(lines) > cfg["linhas_max"] or (max_h is not None and len(lines) * lh > max_h): continue
        return f, words, lines, lh
    sys.exit("%s nao cabe na capa nem com fonte %d (largura %d px, ate %d linhas%s): encurte o texto: %r"
             % (nome, cfg["tam_min"], maxw, cfg["linhas_max"], "" if max_h is None else ", altura %d px" % max_h, text))


def block_h(t):
    f, words, lines, lh = t
    return (len(lines) - 1) * lh + f.getbbox(" ".join(words[i] for i in lines[-1]))[3]


def draw_lines(d, x, y, t, cor, boxes, nome, hl=(), cor_hl=None):
    f, words, lines, lh = t
    for line in lines:
        cx = x
        for i in line:
            d.text((cx, y), words[i], font=f, fill=cor_hl if i in hl else cor); cx += f.getlength(words[i] + " ")
        boxes.append((nome, d.textbbox((x, y), " ".join(words[i] for i in line), font=f)))
        y += lh
    return y


def inside(boxes, W, top, bot, fmt):
    for nome, (x0, y0, x1, y1) in boxes:
        if x0 < 0 or x1 > W or y0 < top or y1 > bot:
            sys.exit("capa %s: %s sai da area segura (y %d-%d): caixa %s. Encurte os textos ou ajuste o preset"
                     % (fmt, nome, top, bot, (x0, y0, x1, y1)))


# ---------- imagem ----------

def frame(video, t, R):
    try:
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", video, "-frames:v", "1",
                            # o recorte do rosto e em pixels do final 1080x1920: uma previa menor (--scale 0.5) e ampliada antes
                            "-vf", "scale=1080:1920:flags=lanczos,crop=%d:%d:%d:%d" % (R["w"], R["h"], R["x"], R["y"]),
                            "-f", "image2pipe", "-c:v", "png", "-"], capture_output=True)
    except FileNotFoundError: sys.exit("ffmpeg nao encontrado no PATH")
    if r.returncode or not r.stdout:
        err = r.stderr.decode("utf-8", "replace").strip()[:300]
        sys.exit("nao consegui extrair o quadro em t=%gs de %s: %s" % (t, video, err or "tempo depois do fim do video?"))
    return Image.open(BytesIO(r.stdout)).convert("RGB")


def tune(im, I):
    im = ImageEnhance.Contrast(im).enhance(I["contraste"]); im = ImageEnhance.Color(im).enhance(I["cor"])
    return ImageEnhance.Brightness(im).enhance(I["brilho"])


def face_cx(im, rosto_x):
    if rosto_x is not None: return float(rosto_x) * im.width
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


def square(im, rosto_x):
    s = min(im.width, im.height); cx = face_cx(im, rosto_x)
    x0 = int(min(max(cx - s / 2, 0), im.width - s)); return im.crop((x0, 0, x0 + s, s))


def rounded(im, r):
    m = Image.new("L", im.size, 0); ImageDraw.Draw(m).rounded_rectangle((0, 0) + im.size, r, fill=255)
    o = Image.new("RGBA", im.size); o.paste(im, (0, 0), m); return o


class Capa:
    def __init__(self, P):
        self.P, self.C = P, {k: hexrgb(v) for k, v in P["cores"].items() if not k.startswith("_")}
        self.F_T = os.path.join(ROOT, P["fontes"]["titulo"]); self.F_X = os.path.join(ROOT, P["fontes"]["texto"])

    def kicker(self, d, o, x, K, tw, boxes, fmt):
        """Desenha o kicker (se houver) e devolve quanto ele cresceu alem de 1 linha."""
        if not o["kicker"].strip(): return 0
        t = fit(o["kicker"], self.F_X, K, tw, nome="kicker (%s)" % fmt)
        draw_lines(d, x, K["y"], t, self.C["destaque"], boxes, "kicker")
        return (len(t[2]) - 1) * t[3]

    def vertical(self, face, o):
        L, C = self.P["vertical_9x16"], self.C
        W, H, (top, bot), mx = L["w"], L["h"], L["seguro"], L["margem_x"]
        K, B, T, Ro, Rd, tw = L["kicker"], L["barra"], L["titulo"], L["rosto"], L["rodape"], W - 2 * L["margem_x"]
        im = Image.new("RGB", (W, H), C["fundo"]); d = ImageDraw.Draw(im); boxes = []
        extra = self.kicker(d, o, mx, K, tw, boxes, "9:16")
        by = K["y"] + B["dy"] + extra
        d.rectangle((mx, by, mx + B["w"], by + B["h"]), fill=C["destaque"])
        ty = T["y"] + extra
        fw = W - 2 * Ro["margem_x"]; fh = int(fw * face.height / face.width)
        lim, r = bot, None
        if o["rodape"].strip():
            r = fit(o["rodape"], self.F_X, Rd, tw, nome="rodape (9:16)")
            ry = min(Rd["y"], bot - block_h(r)); lim = ry - Ro["folga_rodape"]
        t = fit(o["titulo"], self.F_T, T, tw, lim - fh - Ro["dy"] - ty, nome="titulo (9:16)")
        y = draw_lines(d, mx, ty, t, C["texto"], boxes, "titulo", highlight(t[1], o["destaque"]), C["destaque"])
        fy = max(y + Ro["dy"], Ro["y_min"])
        if fy + fh > lim: sys.exit("capa 9:16: o rosto nao cabe entre o titulo e o rodape; encurte os textos")
        f = rounded(face.resize((fw, fh)), Ro["raio"]); im.paste(f, (Ro["margem_x"], fy), f)
        boxes.append(("rosto", (Ro["margem_x"], fy, Ro["margem_x"] + fw, fy + fh)))
        if r: draw_lines(d, mx, ry, r, C["suave"], boxes, "rodape")
        inside(boxes, W, top, bot, "9:16")
        return im

    def youtube(self, face, o):
        L, C = self.P["youtube_16x9"], self.C
        W, H, (top, bot), mx = L["w"], L["h"], L["seguro"], L["margem_x"]
        K, T, Rd, tw = L["kicker"], L["titulo"], L["rodape"], W - H - L["margem_x"] - L["margem_dir"]
        im = Image.new("RGB", (W, H), C["fundo"]); d = ImageDraw.Draw(im); boxes = []
        im.paste(square(face, o["rosto_x"]).resize((H, H)), (W - H, 0))
        d.rectangle((W - H - 10, 0, W - H, H), fill=C["destaque"])
        ty = T["y"] + self.kicker(d, o, mx, K, tw, boxes, "16:9")
        lim, r = bot, None
        if o["rodape"].strip():
            r = fit(o["rodape"], self.F_X, Rd, tw, nome="rodape (16:9)")
            ry = min(Rd["y"], bot - block_h(r)); lim = ry - Rd["folga"]
        t = fit(o["titulo"], self.F_T, T, tw, lim - ty, nome="titulo (16:9)")
        draw_lines(d, mx, ty, t, C["texto"], boxes, "titulo", highlight(t[1], o["destaque"]), C["destaque"])
        if r: draw_lines(d, mx, ry, r, C["suave"], boxes, "rodape")
        inside(boxes, W - H, top, bot, "16:9")
        return im


def sheet(video, ts, P, out):
    R, f = P["rosto_no_video"], font(os.path.join(ROOT, P["fontes"]["texto"]), 28); tiles = []
    for t in ts:
        im = frame(video, t, R).resize((360, 203)); ImageDraw.Draw(im).text((8, 8), "%gs" % t, font=f, fill=(255, 255, 0))
        tiles.append(im)
    cols = 4; rows = (len(tiles) + cols - 1) // cols
    sh = Image.new("RGB", (cols * 366, rows * 209), hexrgb(P["cores"]["fundo"]))
    for i, t in enumerate(tiles): sh.paste(t, ((i % cols) * 366, (i // cols) * 209))
    p = os.path.join(out, "candidatos.jpg"); sh.save(p, quality=90); print("folha:", p)
    return p


def run(video, S, P, out, only=None, time=None, rosto_x=None, rosto=None):
    """Gera as capas. Devolve {arquivo: caminho}. Valida tudo e monta as imagens antes de gravar/apagar algo.
    rosto: dict do rosto.json (necessario se o spec usa "auto")."""
    validate(S)
    fmts = (only,) if only else FORMATOS
    capa, frames, imgs, usados = Capa(P), {}, [], {}
    for vi, v in enumerate(variantes(S)):
        suf = "_" + v["nome"] if v else ""
        for fmt in fmts:
            o = auto(resolve(S, v, fmt, time, rosto_x), rosto, vi); t = float(o["tempo_s"])
            usados.setdefault(v.get("nome", ""), {})[fmt] = {"tempo_s": t, "rosto_x": o["rosto_x"]}
            if t not in frames: frames[t] = tune(frame(video, t, P["rosto_no_video"]), P["imagem"])
            imgs.append((ARQ[fmt] % suf, getattr(capa, fmt)(frames[t], o)))
            print("%s%s: quadro %gs%s" % (fmt, " " + v["nome"] if v else "", t,
                                          " rosto_x %s" % o["rosto_x"] if fmt == "youtube" else ""))
    validos = {ARQ[f] % ("_" + v["nome"] if v else "") for v in variantes(S) for f in FORMATOS}
    os.makedirs(out, exist_ok=True)
    for p in sorted(glob.glob(os.path.join(out, "capa_*.png"))):
        if os.path.basename(p) not in validos: os.remove(p); print("removida (o spec nao gera mais):", p)
    feitos = {}
    for nm, im in imgs:
        p = os.path.join(out, nm); im.save(p); feitos[nm] = p; print("  ->", p)
    mp = os.path.join(out, "capas.json")  # quadros usados (o publish.py le o tempo do TikTok daqui)
    try:
        with open(mp, encoding="utf-8") as f: ant = json.load(f)
    except (OSError, ValueError): ant = {}
    if only:  # --only: mantem o outro formato do registro anterior
        for nome, fs in ant.items():
            for f, val in fs.items(): usados.setdefault(nome, {}).setdefault(f, val)
    with open(mp, "w", encoding="utf-8") as f: json.dump(usados, f, ensure_ascii=False, indent=1, sort_keys=True)
    return feitos


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--video", required=True); ap.add_argument("--spec", required=True)
    ap.add_argument("--out", default=None, help="pasta das capas (padrao: <pasta do spec>/capas)")
    ap.add_argument("--preset", default="presets/thumbnail.json")
    ap.add_argument("--only", choices=FORMATOS, default=None, help="gera so um formato")
    ap.add_argument("--time", type=float, default=None, help="sobrescreve tempo_s de todas as capas")
    ap.add_argument("--rosto-x", type=float, default=None, help="sobrescreve rosto_x (fracao 0-1; so muda o 16:9)")
    ap.add_argument("--rosto", default=None, help="rosto.json do rosto.py (padrao: o da pasta do spec)")
    ap.add_argument("--sheet", default=None, help="lista de tempos (ex.: 3,20,48,75) para folha de candidatos")
    a = ap.parse_args(argv)
    if a.time is not None and a.time < 0: sys.exit("--time deve ser >= 0")
    if a.rosto_x is not None and not 0 <= a.rosto_x <= 1: sys.exit("--rosto-x deve estar entre 0 e 1")
    if not os.path.exists(a.video): sys.exit("nao achei o video %s" % a.video)
    try:
        with open(a.spec, encoding="utf-8") as f: S = json.load(f)
    except (OSError, ValueError) as e: sys.exit("spec: nao consegui ler %s: %s" % (a.spec, e))
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.spec)), "capas")
    P = preset.load(a.preset)
    if a.sheet:
        ts = parse_sheet(a.sheet); os.makedirs(out, exist_ok=True); return sheet(a.video, ts, P, out)
    validate(S)
    R = None
    if usa_auto(S) or a.rosto:
        R = ler_rosto(a.rosto or os.path.join(os.path.dirname(os.path.abspath(a.spec)), "rosto.json"), a.video)
    return run(a.video, S, P, out, a.only, a.time, a.rosto_x, R)


if __name__ == "__main__":
    main()
