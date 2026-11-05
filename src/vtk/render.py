#!/usr/bin/env python3
"""Renderiza cada trecho do plano em 9:16 (rosto + slide + legenda), a partir de um preset, e junta tudo.

Uso:
  python3 src/vtk/render.py --preset presets/tiktok-vertical.json --video GRAVACAO.mov \
      --plan videos/<nome>/plan.json --out render_final --scale 1.0 --crf 20
  # prévia leve: --scale 0.5 --crf 30
Saídas em --out: c00.mov, c01.mov... (um clipe por trecho, áudio PCM 48 kHz), lista.txt e, quando todos os
clipes estão prontos, final.mov (junção sem recodificar). Depois: vtk/postaudio.py --in <out>/final.mov.

Grade de quadros: cada clipe tem exatamente round((e - s) * fps) quadros e áudio com a mesma duração, então as
emendas não acumulam atraso entre som e imagem (por isso PCM, e não AAC, nos clipes).

Retoma de onde parou: cada clipe tem um cNN.json com o hash de tudo que o afeta (trecho, blocos do preset, filtro
da câmera, --scale, --crf, arquivo da gravação). Se algo mudou, o clipe é refeito. --budget limita o tempo por
execução (s). Clipes de trechos que não existem mais no plano são apagados.

Zoom (opcional): um trecho do plan.json com "z": 1.1 aproxima só a janela da câmera (slide e legenda não mudam).
Sem "z", ou "z": 1, sai sem zoom. Máximo 1.2 (regra da skill).

Desfoque (opcional): "blur": [[t0, t1, x, y, w, h], ...] no trecho borra a caixa x/y/w/h (pixels da gravação
original) entre t0 e t1 (segundos a partir do início do trecho), antes de recortar câmera e slide.

Antes de renderizar, confere a gravação (ffprobe): resolução igual a source.w/h do preset (quando houver) e
recortes/caixas dentro do quadro. A fonte da legenda vem de assets/fonts (subtitles.fontsdir, relativo à raiz).
"""
import argparse, hashlib, json, math, os, re, subprocess, sys, textwrap, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.path.join(ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "src"))
from vtk import preset
from vtk._vendor import ev as skill

EYE_LINE = skill.EYE_LINE  # mesma linha dos olhos da skill de terceiros: o zoom cresce a partir dela
MAX_ZOOM = 1.2  # limite da skill (references/editing-rules.md)
AR = 48000  # áudio dos clipes: PCM 16 bits, 48 kHz
VERSAO = 2  # muda quando o jeito de renderizar muda: força refazer os clipes
CLIPE = re.compile(r"^c(\d+)\.(mov|mov\.part|json|ass|mp4|z)$")


def zoom_crop(crop, z, eye=EYE_LINE):
    """[w, h, x, y] da camera na gravacao -> recorte menor (zoom z), centrado na horizontal e com a
    linha dos olhos parada na mesma altura. z <= 1 devolve o recorte original."""
    w, h, x, y = crop
    if z <= 1.001:
        return [w, h, x, y]
    w2, h2 = int(w / z) // 2 * 2, int(h / z) // 2 * 2
    return [w2, h2, x + (w - w2) // 2, y + int(eye * (h - h2))]


def ts(t):
    """Tempo do ASS (h:mm:ss.cc), a partir do total de centésimos (59.996 -> 0:01:00.00)."""
    cs = max(0, int(round(t * 100)))
    h, cs = divmod(cs, 360000); m, cs = divmod(cs, 6000); s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def ass_text(t):
    """Texto puro para o ASS: { } viram ( ) (senão viram bloco de comando e somem) e a barra invertida
    ganha um WORD JOINER depois, para \\N, \\n e \\h não virarem quebra de linha/espaço."""
    t = " ".join(t.split())
    return t.replace("{", "(").replace("}", ")").replace("\\", "\\⁠")


def wrap(t, sub):
    return "\\N".join(ass_text(l) for l in textwrap.wrap(t, sub["max_chars_per_line"], break_long_words=False))


def chunks(x0, x1, t, sub):
    parts, cur = [], []
    for w in t.split():
        if len(" ".join(cur + [w])) > sub["max_chars_per_event"] and cur:
            parts.append(" ".join(cur)); cur = [w]
        else:
            cur.append(w)
    if cur: parts.append(" ".join(cur))
    tot = sum(len(p) for p in parts); out = []; x = x0
    for p in parts:
        d = (x1 - x0) * len(p) / tot; out.append((x, x + d, p)); x += d
    return out


def write_ass(path, c, cv, sub):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nWrapStyle: 2\n\n" % (cv["w"], cv["h"]))
        fh.write("[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n")
        fh.write(f"Style: Default,{sub['font']},{sub['size']},{sub['primary']},{sub['primary']},{sub['outline_color']},&H00000000,{-1 if sub['bold'] else 0},0,0,0,100,100,0,0,1,{sub['outline']},0,2,90,90,{sub['margin_v']},1\n\n")
        fh.write("[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
        for (x0, x1, t) in c["ev"]:
            for (u, v, p) in chunks(x0, x1, t, sub):
                fh.write(f"Dialogue: 0,{ts(u)},{ts(v)},Default,,0,0,0,,{wrap(p, sub)}\n")


def fpath(p):
    """Caminho dentro do filter_complex: escapa para a opção do filtro e depois para o grafo."""
    for ch in "\\':":
        p = p.replace(ch, "\\" + ch)
    for ch in "\\'[],;":
        p = p.replace(ch, "\\" + ch)
    return p


def zoom_of(c, n):
    z = float(c.get("z", 1.0))
    if z > MAX_ZOOM: print(f"aviso: trecho {n} com zoom {z:g}, limitado a {MAX_ZOOM:g}"); z = MAX_ZOOM
    return 1.0 if z <= 1.001 else z


def frames(c, fps, n=0):
    """Quadros do clipe: round((e - s) * fps). Erro claro se o trecho estiver invertido ou curto demais."""
    s, e = float(c["s"]), float(c["e"])
    if e <= s:
        raise SystemExit(f"render: trecho {n} com fim ({e:g}) <= início ({s:g}). Corrija o plan.json.")
    k = round((e - s) * fps)
    if k < 1:
        raise SystemExit(f"render: trecho {n} curto demais ({e - s:.3f} s, menos de 1 quadro a {fps} fps).")
    return k


def check_plan(plan, fps):
    """Valida o plano inteiro antes de renderizar; devolve [(quadros, zoom)] por trecho."""
    out = []
    for n, c in enumerate(plan):
        for b in c.get("blur", []):
            if len(b) != 6 or b[1] <= b[0] or b[4] <= 0 or b[5] <= 0:
                raise SystemExit(f"render: trecho {n}, blur {b}: esperado [t0, t1, x, y, w, h] com t1 > t0, w e h > 0.")
        out.append((frames(c, fps, n), zoom_of(c, n)))
    return out


def check_source(S, size, plan):
    """Lista de problemas: resolução diferente de source.w/h, recorte ou caixa de blur fora do quadro."""
    W, H = size; errs = []
    if "w" in S and "h" in S and (S["w"], S["h"]) != (W, H):
        errs.append(f"a gravação é {W}x{H}, mas o preset espera {S['w']}x{S['h']} (source.w/h). "
                    "Use/meça um preset para esta gravação (videos/<nome>/preset.json).")
    boxes = [("camera_crop", S["camera_crop"]), ("slide_crop", S["slide_crop"])]
    for n, c in enumerate(plan):
        boxes += [(f"trecho {n} blur {b}", [b[4], b[5], b[2], b[3]]) for b in c.get("blur", [])]
    for nome, (w, h, x, y) in boxes:
        if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > W or y + h > H:
            errs.append(f"{nome} = {w}x{h} em ({x}, {y}) sai do quadro {W}x{H}.")
    return errs


def probe(video):
    """(largura, altura) do 1º stream de vídeo, via ffprobe."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                            "-of", "csv=p=0:s=x", video], capture_output=True, text=True)
    except FileNotFoundError:
        raise SystemExit("render: ffprobe não encontrado (vem junto com o ffmpeg).")
    m = re.match(r"(\d+)x(\d+)", r.stdout.strip())
    if r.returncode or not m:
        raise SystemExit(f"render: não consegui ler a resolução de {video}: {r.stderr.strip()[-300:]}")
    return int(m.group(1)), int(m.group(2))


def font_dir(sub):
    """Pasta da fonte da legenda (relativa à raiz do repo). Aborta se a fonte não estiver lá: sem ela o libass
    troca de fonte calado (no macOS, Helvetica)."""
    d = sub["fontsdir"]
    d = d if os.path.isabs(d) else os.path.join(ROOT, d)
    alvo = sub["font"].replace(" ", "").lower()
    achou = os.path.isdir(d) and any(f.lower().startswith(alvo) and f.lower().endswith((".ttf", ".otf"))
                                     for f in os.listdir(d))
    if not achou:
        raise SystemExit(f"render: fonte '{sub['font']}' não encontrada em {d}. No preset, use "
                         '"subtitles": {"fontsdir": "assets/fonts"} (a fonte vai junto com o repositório).')
    return d


def blur_graph(boxes, size, src="v0"):
    """Desfoque das caixas [t0, t1, x, y, w, h] sobre a gravação, antes dos recortes.
    Devolve (trecho do filter_complex terminando em ';', rótulo de saída)."""
    W, H = size; g = []; cur = src
    for i, (t0, t1, x, y, w, h) in enumerate(boxes):
        # caixa par (yuv420) e só para fora: cobre pelo menos o pedido
        x0, y0 = int(x) // 2 * 2, int(y) // 2 * 2
        x1, y1 = min(W, math.ceil((x + w) / 2) * 2), min(H, math.ceil((y + h) / 2) * 2)
        bw, bh = x1 - x0, y1 - y0
        sigma = min(100, max(10, min(bw, bh) // 3))
        en = f"enable='between(t,{t0:g},{t1:g})'"
        nxt = f"bl{i + 1}"
        g.append(f"[{cur}]split=2[bm{i}][bc{i}];[bc{i}]crop={bw}:{bh}:{x0}:{y0},gblur=sigma={sigma}:steps=3[bk{i}];"
                 f"[bm{i}][bk{i}]overlay={x0}:{y0}:{en}[{nxt}];")
        cur = nxt
    return "".join(g), cur


def clip_hash(c, z, P, cam_extra, scale, crf, video, fontsdir):
    """Hash de tudo que muda o clipe: se mudar, o clipe é refeito."""
    limpo = lambda d: {k: v for k, v in d.items() if not k.startswith("_")}
    st = os.stat(video)
    dados = {"v": VERSAO, "s": c["s"], "e": c["e"], "ev": c["ev"], "z": z, "blur": c.get("blur", []),
             "canvas": limpo(P["canvas"]), "source": limpo(P["source"]), "layout": P["layout"],
             "subtitles": limpo(P["subtitles"]), "fontsdir": fontsdir,
             "fade": [P["cut"]["audio_fade_in_s"], P["cut"]["audio_fade_out_s"]],
             "cam": cam_extra, "scale": scale, "crf": str(crf),
             "video": [video, st.st_size, int(st.st_mtime)]}
    return hashlib.sha256(json.dumps(dados, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def clip_cmd(c, nq, z, P, size, cam_extra, scale, crf, video, ass, fontsdir, out):
    """Comando do ffmpeg para um clipe com exatamente nq quadros e nq/fps segundos de áudio."""
    even = lambda x: int(round(x * scale / 2)) * 2
    cv, L, S, cut = P["canvas"], P["layout"], P["source"], P["cut"]
    fps = cv["fps"]; W, H = even(cv["w"]), even(cv["h"])
    cam_h, cam_y = even(L["camera"]["h"]), even(L["camera"]["y"])
    sl_w, sl_h, sl_x, sl_y = (even(L["slide"][k]) for k in ("w", "h", "x", "y"))
    sw, sh, sx, sy = S["slide_crop"]
    cw, ch, cx, cy = zoom_crop(S["camera_crop"], z)
    bg, src = blur_graph(c.get("blur", []), size)
    D = nq / fps; ns = round(D * AR); fi, fo = cut["audio_fade_in_s"], cut["audio_fade_out_s"]
    fg = (f"color=c={cv['bg']}:s={W}x{H}:r={fps}[bg];"
          f"[0:v]setpts=PTS-STARTPTS,fps={fps},tpad=stop_mode=clone:stop_duration=1[v0];{bg}"
          f"[{src}]split=2[a][b];"
          f"[a]crop={cw}:{ch}:{cx}:{cy},scale={W}:{cam_h}{cam_extra}[cam];"
          f"[b]crop={sw}:{sh}:{sx}:{sy},scale={sl_w}:{sl_h}[sl];"
          f"[bg][cam]overlay=0:{cam_y}:shortest=1[t1];[t1][sl]overlay={sl_x}:{sl_y}[t2];"
          f"[t2]subtitles={fpath(os.path.basename(ass))}:fontsdir={fpath(fontsdir)}[v];"
          f"[0:a:0]aresample={AR},asetpts=PTS-STARTPTS,atrim=end_sample={ns},apad=whole_len={ns},"
          f"afade=t=in:d={fi},afade=t=out:st={max(0, D - fo):.4f}:d={fo}[a0]")
    return ["ffmpeg", "-v", "error", "-y", "-ss", str(c["s"]), "-t", f"{D + 0.5:.3f}", "-i", video,
            "-filter_complex", fg, "-map", "[v]", "-map", "[a0]", "-frames:v", str(nq),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p", "-r", str(fps),
            "-c:a", "pcm_s16le", "-ar", str(AR), "-f", "mov", out]


def clean(outdir, total):
    """Apaga clipes/sidecars de trechos que saíram do plano, sobras de render interrompido e os .mp4/.z antigos."""
    for f in os.listdir(outdir):
        m = CLIPE.match(f)
        if m and (int(m.group(1)) >= total or m.group(2) in ("mov.part", "mp4", "z")):
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
    """lista.txt com c00..c{total-1} e junção sem recodificar em final.mov."""
    lista = os.path.join(outdir, "lista.txt")
    with open(lista, "w", encoding="utf-8") as f:
        f.writelines(f"file 'c{n:02d}.mov'\n" for n in range(total))
    tmp = os.path.join(outdir, "final.mov.part")
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", "lista.txt",
                        "-map", "0", "-c", "copy", "-f", "mov", tmp], cwd=outdir, capture_output=True, text=True)
    if r.returncode:
        print("ERRO na junção", r.stderr[-400:]); sys.exit(1)
    os.replace(tmp, os.path.join(outdir, "final.mov"))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", required=True); ap.add_argument("--video", required=True)
    ap.add_argument("--plan", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--scale", type=float, default=1.0); ap.add_argument("--crf", default="20")
    ap.add_argument("--budget", type=float, default=1e9)
    ap.add_argument("--camera-filter", default=None, help="off|natural (padrao: o do preset)")
    a = ap.parse_args(argv)

    # o ffmpeg roda com cwd=a.out (por causa do .ass da legenda): caminhos relativos quebravam
    a.out, a.video = os.path.abspath(a.out), os.path.abspath(a.video)
    P = preset.load(a.preset)
    with open(a.plan, encoding="utf-8") as f:
        plan = json.load(f)
    info = check_plan(plan, P["canvas"]["fps"])
    size = probe(a.video)
    errs = check_source(P["source"], size, plan)
    if errs:
        raise SystemExit("render: a gravação não bate com o preset:\n  " + "\n  ".join(errs))
    fontsdir = font_dir(P["subtitles"])
    cf_mode = a.camera_filter or P["camera_filter"]["mode"]
    if cf_mode not in P["camera_filter"]:
        raise SystemExit(f"render: --camera-filter {cf_mode} não existe no preset (camera_filter).")
    cf = P["camera_filter"][cf_mode]
    cam_extra = ("," + cf) if cf else ""
    os.makedirs(a.out, exist_ok=True)
    clean(a.out, len(plan))

    t0 = time.time(); prontos = 0
    for n, c in enumerate(plan):
        nq, z = info[n]
        h = clip_hash(c, z, P, cam_extra, a.scale, a.crf, a.video, fontsdir)
        base = os.path.join(a.out, f"c{n:02d}")
        if ready(a.out, n, h):
            prontos += 1; continue
        if time.time() - t0 > a.budget: print("orcamento de tempo"); break
        write_ass(base + ".ass", c, P["canvas"], P["subtitles"])
        cmd = clip_cmd(c, nq, z, P, size, cam_extra, a.scale, a.crf, a.video, base + ".ass", fontsdir, base + ".mov.part")
        r = subprocess.run(cmd, cwd=a.out, capture_output=True, text=True)
        if r.returncode:
            if os.path.exists(base + ".mov.part"): os.remove(base + ".mov.part")
            print("ERRO", n, r.stderr[-400:]); sys.exit(1)
        os.replace(base + ".mov.part", base + ".mov")
        with open(base + ".json", "w", encoding="utf-8") as f:
            json.dump({"hash": h, "quadros": nq, "z": z}, f)
        prontos += 1
        print("ok", n, "%.1fs" % (time.time() - t0) + (f" zoom {z:g}x" if z > 1 else ""), flush=True)
    print(prontos, "/", len(plan), "clipes prontos;", f"camera_filter={cf_mode}")
    if prontos == len(plan):
        concat(a.out, len(plan))
        print("final:", os.path.join(a.out, "final.mov"))
    else:
        print("rode de novo para terminar; final.mov só sai com todos os clipes")


if __name__ == "__main__":
    main()
