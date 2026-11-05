#!/usr/bin/env python3
"""Acha os quadros com o rosto mais neutro do vídeo final, para a capa (local e grátis: MediaPipe, sem rede).

Olha a faixa da câmera (rosto_no_video do presets/thumbnail.json) em alguns quadros por segundo e dá uma nota a
cada um: 0 é o ideal. Pesa olhos fechados (piscada), boca aberta (no meio de uma palavra), sorriso largo, testa
franzida ou levantada, cabeça virada e imagem tremida, cada expressão medida a partir do seu rosto em repouso
naquele vídeo (o nível mais baixo dela, percentil 10). A nota de um quadro é a pior entre ele e os vizinhos,
para preferir uma expressão que se manteve (e não um instante entre duas caretas). Pesos no preset ("neutro").

Saída em videos/<nome>/ (ou --out):
  rosto.json            candidatos em ordem (t, nota, rosto_x e o detalhe) e a nota de todos os quadros
  rosto_candidatos.jpg  folha com os candidatos, numerados, para conferir com o olho
No thumb.json: "tempo_s": "auto" usa o candidato da posição da variante (A = 1º, B = 2º...), "auto:3" o 3º;
"rosto_x": "auto" centraliza o 16:9 no rosto daquele quadro. Mesmo vídeo + mesmos pesos = mesmo resultado.

  python3 src/vtk/rosto.py --video videos/<nome>/final.mp4 --name <nome>
Requer: pip install mediapipe numpy Pillow, e o modelo em models/face_landmarker.task (ver README).
"""
import argparse, json, math, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.path.join(ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "src"))
from vtk import preset

MODELO = os.path.join(ROOT, "models", "face_landmarker.task")
BAIXAR = ("baixe (3,7 MB) de https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/"
          "float16/latest/face_landmarker.task e salve em models/face_landmarker.task")
PADRAO = {"fps": 4, "largura": 540, "candidatos": 6, "distancia_s": 1.5, "margem_s": 0.5,
          "pesos": {"olhos": 3.0, "boca": 4.0, "sorriso": 1.0, "testa": 0.5, "pose": 1.0, "nitidez": 1.0}}


# ---------- nota (funções puras, testadas sem modelo) ----------

def partes(bs, yaw=0.0, pitch=0.0, nitidez=1.0):
    """blendshapes {nome: 0..1} + pose (graus) + nitidez relativa (1 = mediana do vídeo) -> penalidades 0..1."""
    g = lambda k: float(bs.get(k, 0.0))
    par = lambda k: max(g(k + "Left"), g(k + "Right"))
    return {
        "olhos": max(par("eyeBlink"), 0.5 * par("eyeSquint")),
        "boca": max(g("jawOpen"), g("mouthFunnel"), g("mouthPucker"), par("mouthLowerDown"), par("mouthUpperUp")),
        "sorriso": par("mouthSmile"),
        "testa": max(g("browInnerUp"), par("browDown")),
        "pose": min(1.0, (abs(yaw) + abs(pitch)) / 30.0),
        "nitidez": min(1.0, max(0.0, 1.0 - nitidez)),
    }


EXPRESSAO = ("olhos", "boca", "sorriso", "testa")


def repouso(dets, q=0.1):
    """Nível de repouso de cada expressão neste vídeo (percentil q): óculos, sobrancelha alta de nascença etc.
    Descontado de cada quadro, a nota mede o quanto o rosto saiu do seu normal, não de um rosto genérico."""
    base = {}
    for k in EXPRESSAO:
        vs = sorted(d[k] for d in dets if d)
        base[k] = vs[int(q * (len(vs) - 1))] if vs else 0.0
    return base


def desconta(p, base):
    return {k: max(0.0, v - base.get(k, 0.0)) if k in base else v for k, v in p.items()}


def nota(p, pesos):
    return sum(pesos.get(k, 0.0) * v for k, v in p.items())


def suaviza(notas):
    """Nota de cada quadro = a pior entre ele e os vizinhos (None = sem rosto, conta como pior)."""
    out = []
    for i, n in enumerate(notas):
        viz = notas[max(0, i - 1):i + 2]
        out.append(None if n is None or any(v is None for v in viz) else max(viz))
    return out


def escolhe(ts, notas, k, distancia, inicio=0.0, fim=float("inf")):
    """Até k índices com as menores notas, separados por pelo menos `distancia` s, dentro de [inicio, fim]."""
    ordem = sorted((n, i) for i, n in enumerate(notas) if n is not None and inicio <= ts[i] <= fim)
    pegos = []
    for n, i in ordem:
        if all(abs(ts[i] - ts[j]) >= distancia for j in pegos):
            pegos.append(i)
            if len(pegos) == k: break
    return pegos


def pose(m):
    """Matriz 4x4 de transformação do rosto -> (yaw, pitch) em graus."""
    r = [[m[i][j] for j in range(3)] for i in range(3)]
    for j in range(3):  # tira a escala das colunas
        s = math.sqrt(sum(r[i][j] ** 2 for i in range(3))) or 1.0
        for i in range(3): r[i][j] /= s
    yaw = math.degrees(math.asin(max(-1.0, min(1.0, -r[2][0]))))
    pitch = math.degrees(math.atan2(r[2][1], r[2][2]))
    return yaw, pitch


def candidato(ts, i, rx, det, nt):
    return {"t": round(ts[i], 3), "nota": round(nt[i], 3), "rosto_x": round(rx[i], 3),
            **{k: round(v, 3) for k, v in det[i].items()}}


def pega(R, ref, var_idx=0):
    """Resolve "auto"/"auto:N" contra o rosto.json carregado. var_idx = posição da variante (0 = A)."""
    c = R.get("candidatos") or []
    n = var_idx + 1 if ref == "auto" else int(ref.split(":", 1)[1])
    if not 1 <= n <= len(c):
        raise ValueError("pedi o candidato %d, mas o rosto.json tem %d (rode rosto.py com --candidatos maior)" % (n, len(c)))
    return c[n - 1]


# ---------- vídeo ----------

def quadros(video, R, fps, largura):
    """Gera (t, imagem RGB numpy) da faixa da câmera, a `fps` quadros por segundo."""
    import numpy as np
    h = int(round(R["h"] * largura / R["w"] / 2)) * 2
    cmd = ["ffmpeg", "-v", "error", "-i", video, "-vf",
           "fps=%g,scale=1080:1920,crop=%d:%d:%d:%d,scale=%d:%d" % (fps, R["w"], R["h"], R["x"], R["y"], largura, h),
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        sys.exit("ffmpeg não encontrado no PATH")
    n, tam = 0, largura * h * 3
    with p:  # fecha os pipes mesmo se quem consome parar no meio
        while True:
            b = p.stdout.read(tam)
            if len(b) < tam: break
            yield n / fps, np.frombuffer(b, np.uint8).reshape(h, largura, 3)
            n += 1
        err = p.stderr.read().decode("utf-8", "replace").strip()
    if p.returncode or not n:
        sys.exit("rosto: não consegui ler %s: %s" % (video, err[:300] or "sem quadros"))


def nitidez_bruta(img, lms):
    """Variância do laplaciano na caixa do rosto (cinza). Maior = mais nítido."""
    import numpy as np
    h, w = img.shape[:2]
    xs = [p.x for p in lms]; ys = [p.y for p in lms]
    x0, x1 = max(0, int(min(xs) * w)), min(w, int(max(xs) * w) + 1)
    y0, y1 = max(0, int(min(ys) * h)), min(h, int(max(ys) * h) + 1)
    g = img[y0:y1, x0:x1].astype(np.float32).mean(axis=2)
    if g.shape[0] < 3 or g.shape[1] < 3: return 0.0
    lap = g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:] - 4 * g[1:-1, 1:-1]
    return float(lap.var())


def analisa(video, P, modelo=MODELO):
    try:
        import mediapipe as mp
        from mediapipe.tasks import python as mpt
        from mediapipe.tasks.python import vision
    except ImportError:
        sys.exit("rosto: falta o MediaPipe (pip install mediapipe numpy Pillow)")
    if not os.path.isfile(modelo):
        sys.exit("rosto: modelo não encontrado em %s: %s" % (modelo, BAIXAR))
    N = {**PADRAO, **P.get("neutro", {})}; N["pesos"] = {**PADRAO["pesos"], **N.get("pesos", {})}
    opts = vision.FaceLandmarkerOptions(
        base_options=mpt.BaseOptions(model_asset_path=modelo), running_mode=vision.RunningMode.IMAGE, num_faces=1,
        output_face_blendshapes=True, output_facial_transformation_matrixes=True)
    ts, brutos = [], []
    with vision.FaceLandmarker.create_from_options(opts) as lm:
        for t, img in quadros(video, P["rosto_no_video"], N["fps"], N["largura"]):
            ts.append(t)
            r = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=img))
            if not r.face_landmarks:
                brutos.append(None); continue
            bs = {c.category_name: c.score for c in r.face_blendshapes[0]}
            yaw, pitch = pose(r.facial_transformation_matrixes[0])
            pts = r.face_landmarks[0]
            brutos.append((bs, yaw, pitch, nitidez_bruta(img, pts), sum(p.x for p in pts) / len(pts)))
    vals = sorted(b[3] for b in brutos if b)
    if not vals:
        sys.exit("rosto: nenhum rosto encontrado na faixa da câmera (confira rosto_no_video no preset)")
    med = vals[len(vals) // 2] or 1.0
    det = [None if b is None else partes(b[0], b[1], b[2], b[3] / med) for b in brutos]
    base = repouso(det)
    notas, rx = [], []
    for b, p in zip(brutos, det):
        if b is None:
            notas.append(None); rx.append(None); continue
        p.update(desconta(p, base)); p["yaw"], p["pitch"] = b[1], b[2]
        notas.append(nota({k: v for k, v in p.items() if k in N["pesos"]}, N["pesos"])); rx.append(b[4])
    sv = suaviza(notas)
    dur = ts[-1] + 1.0 / N["fps"]
    idx = escolhe(ts, sv, N["candidatos"], N["distancia_s"], N["margem_s"], dur - N["margem_s"])
    return {
        "video": os.path.basename(video), "fps": N["fps"], "pesos": N["pesos"],
        "repouso": {k: round(v, 3) for k, v in base.items()},
        "quadros": len(ts), "sem_rosto": sum(b is None for b in brutos),
        "candidatos": [candidato(ts, i, rx, det, sv) for i in idx],
        "todos": [[round(t, 3), None if n is None else round(n, 3), None if x is None else round(x, 3)]
                  for t, n, x in zip(ts, sv, rx)],
    }


def folha(video, R, P, out):
    """Folha com os candidatos (quadro inteiro da câmera), numerados na ordem do rosto.json."""
    from PIL import Image, ImageDraw, ImageFont
    import numpy as np
    f = ImageFont.truetype(os.path.join(ROOT, P["fontes"]["texto"]), 26)
    Rv = P["rosto_no_video"]; tiles = []
    for k, c in enumerate(R["candidatos"], 1):
        img = next(quadros_em(video, Rv, c["t"]))
        im = Image.fromarray(img).resize((360, int(360 * img.shape[0] / img.shape[1])))
        d = ImageDraw.Draw(im)
        d.rectangle((0, 0, 360, 36), fill=(0, 0, 0))
        d.text((8, 4), "#%d  %.2fs  nota %.2f" % (k, c["t"], c["nota"]), font=f, fill=(255, 220, 0))
        tiles.append(im)
    if not tiles: return None
    cols = 3; rows = (len(tiles) + cols - 1) // cols; th = tiles[0].height
    sh = Image.new("RGB", (cols * 366, rows * (th + 6)), (20, 27, 45))
    for i, t in enumerate(tiles): sh.paste(t, ((i % cols) * 366, (i // cols) * (th + 6)))
    p = os.path.join(out, "rosto_candidatos.jpg"); sh.save(p, quality=90)
    return p


def quadros_em(video, R, t):
    import numpy as np
    cmd = ["ffmpeg", "-v", "error", "-ss", str(t), "-i", video, "-frames:v", "1", "-vf",
           "scale=1080:1920,crop=%d:%d:%d:%d" % (R["w"], R["h"], R["x"], R["y"]), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    b = subprocess.run(cmd, capture_output=True).stdout
    if len(b) < R["w"] * R["h"] * 3: sys.exit("rosto: não consegui extrair o quadro em %gs" % t)
    yield np.frombuffer(b[:R["w"] * R["h"] * 3], np.uint8).reshape(R["h"], R["w"], 3)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--video", required=True, help="vídeo final (o mesmo que vai para o thumb.py)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--name", help="grava em videos/<nome>/")
    g.add_argument("--out", help="pasta de saída")
    ap.add_argument("--preset", default="presets/thumbnail.json")
    ap.add_argument("--modelo", default=MODELO)
    ap.add_argument("--candidatos", type=int, default=None, help="quantos candidatos (padrão: o do preset)")
    a = ap.parse_args(argv)
    if not os.path.isfile(a.video): sys.exit("rosto: não achei o vídeo %s" % a.video)
    P = preset.load(a.preset)
    if a.candidatos: P.setdefault("neutro", {})["candidatos"] = a.candidatos
    out = a.out or os.path.join(ROOT, "videos", a.name)
    os.makedirs(out, exist_ok=True)
    R = analisa(a.video, P, a.modelo)
    p = os.path.join(out, "rosto.json")
    with open(p, "w", encoding="utf-8") as f: json.dump(R, f, ensure_ascii=False, indent=1)
    print("%d quadros (%d sem rosto) -> %s" % (R["quadros"], R["sem_rosto"], p))
    for k, c in enumerate(R["candidatos"], 1):
        print("  #%d  %6.2fs  nota %.2f  olhos %.2f boca %.2f sorriso %.2f testa %.2f pose %.2f nitidez %.2f"
              % (k, c["t"], c["nota"], c["olhos"], c["boca"], c["sorriso"], c["testa"], c["pose"], c["nitidez"]))
    s = folha(a.video, R, P, out)
    if s: print("folha:", s)
    return R


if __name__ == "__main__":
    main()
