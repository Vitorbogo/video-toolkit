#!/usr/bin/env python3
"""Renderiza cada trecho do plano em 9:16 (rosto + slide + legenda), a partir de um preset.

Uso:
  python3 render.py --preset presets/tiktok-vertical.json --video GRAVACAO.mov \
      --plan videos/<nome>/plan.json --out render_final --scale 1.0 --crf 20
  # previa leve: --scale 0.5 --crf 30
Retoma de onde parou (pula clipes ja prontos). --budget limita o tempo por execucao (s).
Depois: ffmpeg -f concat ... -c copy final.mp4 e vtk/postaudio.py para o audio.

Legenda: desenhada com Pillow (src/vtk/captions.py), a frase inteira com a palavra falada em destaque
("highlight" no preset). O ffmpeg do Mac nao tem libass, entao nada de .ass/subtitles aqui.

Zoom (opcional): um trecho do plan.json com "z": 1.1 aproxima so a janela da camera (slide e legenda
nao mudam). Sem "z", ou "z": 1, o trecho sai sem zoom. Maximo 1.2 (regra da skill). O zoom de cada clipe
fica em cNN.z: se o "z" do trecho mudar, o clipe e refeito sozinho.
"""
import argparse, importlib.util, json, os, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from vtk import captions

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_m = importlib.util.spec_from_file_location("edit_video", os.path.join(ROOT, "vendor/dev-video-editing/scripts/edit_video.py"))
_vendor = importlib.util.module_from_spec(_m); _m.loader.exec_module(_vendor)
EYE_LINE = _vendor.EYE_LINE  # mesma linha dos olhos da skill de terceiros: o zoom cresce a partir dela
MAX_ZOOM = 1.2  # limite da skill (references/editing-rules.md)


def zoom_crop(crop, z, eye=EYE_LINE):
    """[w, h, x, y] da camera na gravacao -> recorte menor (zoom z), centrado na horizontal e com a
    linha dos olhos parada na mesma altura. z <= 1 devolve o recorte original."""
    w, h, x, y = crop
    if z <= 1.001:
        return [w, h, x, y]
    w2, h2 = int(w / z) // 2 * 2, int(h / z) // 2 * 2
    return [w2, h2, x + (w - w2) // 2, y + int(eye * (h - h2))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", required=True); ap.add_argument("--video", required=True)
    ap.add_argument("--plan", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--scale", type=float, default=1.0); ap.add_argument("--crf", default="20")
    ap.add_argument("--budget", type=float, default=1e9)
    ap.add_argument("--camera-filter", default=None, help="off|natural (padrao: o do preset)")
    a = ap.parse_args()

    # o ffmpeg roda com cwd=a.out: caminhos relativos quebravam
    a.out, a.video = os.path.abspath(a.out), os.path.abspath(a.video)
    P = json.load(open(a.preset)); plan = json.load(open(a.plan)); os.makedirs(a.out, exist_ok=True)
    K = a.scale
    ev = lambda x: int(round(x * K / 2)) * 2
    cv, L, S, SUB = P["canvas"], P["layout"], P["source"], P["subtitles"]
    W, H = ev(cv["w"]), ev(cv["h"])
    cam_h, cam_y = ev(L["camera"]["h"]), ev(L["camera"]["y"])
    sl_w, sl_h, sl_x, sl_y = (ev(L["slide"][k]) for k in ("w", "h", "x", "y"))
    sw, sh, sx, sy = S["slide_crop"]
    cf_mode = a.camera_filter or P["camera_filter"]["mode"]
    cf = P["camera_filter"].get(cf_mode, "")
    cam_extra = ("," + cf) if cf else ""

    t0 = time.time(); cf_info = f"camera_filter={cf_mode}"
    for n, c in enumerate(plan):
        f, zf = f"{a.out}/c{n:02d}.mp4", f"{a.out}/c{n:02d}.z"
        z = float(c.get("z", 1.0))
        if z > MAX_ZOOM: print(f"aviso: trecho {n} com zoom {z:g}, limitado a {MAX_ZOOM:g}"); z = MAX_ZOOM
        if z <= 1.001: z = 1.0
        feito = float(open(zf).read()) if os.path.exists(zf) else 1.0  # clipe sem cNN.z = sem zoom
        if os.path.exists(f) and feito == z: continue
        if time.time() - t0 > a.budget: print("orcamento de tempo"); break
        lista, alt = captions.overlay(c, a.out, f"c{n:02d}-leg", SUB, W, K)
        leg_y = H - ev(SUB["margin_v"]) - alt
        d = c["e"] - c["s"]
        cw, ch, cx, cy = zoom_crop(S["camera_crop"], z)
        fg = (f"color=c={cv['bg']}:s={W}x{H}:r={cv['fps']}[bg];"
              f"[0:v]fps={cv['fps']},split=2[a][b];"
              f"[a]crop={cw}:{ch}:{cx}:{cy},scale={W}:{cam_h}{cam_extra}[cam];"
              f"[b]crop={sw}:{sh}:{sx}:{sy},scale={sl_w}:{sl_h}[sl];"
              f"[bg][cam]overlay=0:{cam_y}[t1];[t1][sl]overlay={sl_x}:{sl_y}[t2];"
              f"[1:v]fps={cv['fps']},format=rgba[leg];[t2][leg]overlay=0:{leg_y}:eof_action=pass[v]")
        cut = P["cut"]
        cmd = ["ffmpeg", "-v", "error", "-y", "-ss", str(c["s"]), "-t", str(d), "-i", a.video,
               "-f", "concat", "-safe", "0", "-i", lista, "-filter_complex", fg, "-map", "[v]", "-map", "0:a",
               "-af", f"afade=t=in:d={cut['audio_fade_in_s']},afade=t=out:st={d-cut['audio_fade_out_s']:.3f}:d={cut['audio_fade_out_s']}",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", str(a.crf), "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "192k", "-t", str(d), f]
        r = subprocess.run(cmd, cwd=a.out, capture_output=True, text=True)
        if r.returncode: print("ERRO", n, r.stderr[-400:]); sys.exit(1)
        open(zf, "w").write(f"{z:g}")
        print("ok", n, "%.1fs" % (time.time() - t0) + (f" zoom {z:g}x" if z > 1 else ""), flush=True)
    print(len([x for x in os.listdir(a.out) if x.endswith(".mp4") and x.startswith("c")]), "/", len(plan), "clipes prontos;", cf_info)


if __name__ == "__main__":
    main()
