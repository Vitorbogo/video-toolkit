#!/usr/bin/env python3
"""Decide os cortes com o motor (src/vtk/engine.py) e escreve o plan.json do render.py.

Uso:
  python3 src/vtk/cuts.py --video GRAVACAO.mov --transcript work/transcript.json --name <nome>
      [--edit videos/<nome>/edit.json] [--zoom [1.1]] [--sem-cenas] [--force]
Escreve videos/<nome>/plan.json (rascunho: legendas com o texto do Parakeet, REVISAR) e
videos/<nome>/edit-plan.md (cada remocao com o motivo). Nao sobrescreve um plan.json existente sem --force.
edit.json (opcional) usa as chaves do engine.py: style, pauses, cut, keep, replace, extra_fillers...
'cut' so tira palavras inteiras dentro do intervalo (trecho sem palavra nao some por ele). Rodar de novo com --force
refaz as legendas do zero: correcoes repetidas vao no 'replace' do edit.json para sobreviver.
Os enchimentos em portugues (presets/fillers-pt.json) entram sempre; os do edit.json somam com eles.
Zoom e opcional e fica DESLIGADO: so usar --zoom quando as emendas ficarem bruscas. Com ele, a regra do engine.py
(alterna zoom/sem zoom em emendas de 1 s ou mais, ou depois de 4 s no mesmo enquadramento) poe "z" nos trechos
do plan.json. Tambem da para por ou tirar "z" a mao em qualquer trecho.
"""
import argparse, json, math, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))
from vtk import engine
FILLERS_PT = {k: v for k, v in json.load(open(os.path.join(ROOT, "presets/fillers-pt.json"), encoding="utf-8")).items()
              if k in ("fillers", "extra_fillers")}


def captions(ws, s, max_chars):
    """Palavras mantidas de um trecho -> [[x0, x1, texto]] relativos ao inicio do trecho."""
    out, cur = [], []
    for i, w in enumerate(ws):
        cur.append(w)
        fim = i + 1 == len(ws) or w["w"][-1:] in ".?!" or len(" ".join(x["w"] for x in cur + [ws[i + 1]])) > max_chars
        if fim:
            out.append([round(max(0.0, cur[0]["start"] - s), 3), round(cur[-1]["end"] - s, 3), " ".join(x["w"] for x in cur)])
            cur = []
    return out


def exclude(words, reason, spans, fps):
    """Tira dos trechos o som das palavras removidas. O engine deixa parte da pausa ('respiracao') e, quando
    a palavra removida esta nessa pausa, uma ponta dela continua audivel. O corte vai ate o quadro mais
    proximo, sem nunca entrar numa palavra mantida; sobra sem palavra e com menos de 0,4 s sai junto."""
    kept = [w for w, r in zip(words, reason) if r is None]
    has_word = lambda s, e: any(s <= w["start"] < e for w in kept)
    for i, (w, r) in enumerate(zip(words, reason)):
        if r is None: continue
        prv = max((k["end"] for k in kept if k["end"] <= w["start"]), default=0.0)
        nxt = min((k["start"] for k in kept if k["start"] >= w["end"]), default=float("inf"))
        a, b = max(math.floor(w["start"] * fps) / fps, prv), min(math.ceil(w["end"] * fps) / fps, nxt)
        out = []
        for s, e in spans:
            if e <= a or s >= b: out.append((s, e)); continue
            out += [(x, y) for x, y in ((s, a), (b, e)) if y - x > 0 and (has_word(x, y) or y - x >= 0.4)]
        spans = out
    return spans


def decide(words, edit, total, fps=30.0, db=(), floor=-60.0, blacks=(), scenes=(), max_chars=60, zoom=0):
    """Retorna (plan, removidos, possiveis_retomadas). Tempos de 'removidos' e 'retomadas' na gravacao original.
    zoom > 1 liga a sugestao de zoom do engine (so na camera, no render.py); 0 deixa todos os trechos sem zoom.
    'fillers' e 'extra_fillers' do edit.json somam com a lista em portugues; o resto das chaves vai direto para o engine."""
    spec = {**edit, **{k: v + [x for x in edit.get(k, []) if x not in v] for k, v in FILLERS_PT.items()}}
    reason, maybe = engine.mark(words, spec)
    spans, removed = engine.plan_spans(words, reason, spec, total, fps, list(db), floor, list(blacks), list(scenes))
    spans = exclude(words, reason, spans, fps)
    for (_, a), (b, _) in zip(spans, spans[1:]):  # cortes novos do exclude tambem vao para o edit-plan.md
        if not any(rs < b and re_ > a for rs, re_, _, _ in removed):
            removed.append((a, b, "filler", " ".join(w["w"] for w, r in zip(words, reason) if r and a <= w["start"] < b)))
    removed.sort()
    rep = spec.get("replace", {})
    plan = []
    for s, e in spans:
        ws = [dict(w, w=engine.apply_replace(w["w"], rep), end=min(w["end"], e)) for w, r in zip(words, reason)
              if r is None and s <= w["start"] < e]
        plan.append({"s": s, "e": e, "ev": captions(ws, s, max_chars)})
    if zoom > 1:
        zs = engine.zoom_plan(spans, {"style": spec.get("style", "youtube"), "punch_in": zoom}, list(scenes), list(blacks))
        for c, z in zip(plan, zs):
            if z > 1: c["z"] = z
    return plan, removed, maybe


def report(plan, removed, maybe, total):
    dur = sum(c["e"] - c["s"] for c in plan)
    o = [f"# Plano de cortes\n\n{engine.stamp(total)} -> {engine.stamp(dur)} ({(total - dur) / total * 100:.0f}% menor), {len(plan) - 1} cortes.\n"]
    zoomed = [(i, c) for i, c in enumerate(plan) if c.get("z", 1) > 1]
    if zoomed:
        o.append("## Zoom na câmera (opcional: tirar o \"z\" do trecho no plan.json se não precisar)\n")
        o += [f"- trecho {i} ({engine.stamp(c['s'])}): {c['z']:g}x" for i, c in zoomed] + [""]
    if maybe:
        o.append("## Possíveis retomadas (não cortadas: decidir e pôr em \"cut\" no edit.json)\n")
        o += [f"- {engine.stamp(t)}: \"{a[:90]}\" depois \"{b[:90]}\"" for t, a, b in maybe] + [""]
    o += ["## Remoções\n", "| Original | Tirado | Motivo | Palavras |", "|---|---|---|---|"]
    o += [f"| {engine.stamp(s)} | {e - s:.1f} s | {why} | {txt[:80]} |" for s, e, why, txt in removed]
    return "\n".join(o) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True); ap.add_argument("--transcript", required=True)
    ap.add_argument("--name", required=True); ap.add_argument("--edit")
    ap.add_argument("--preset", default="presets/tiktok-vertical.json")
    ap.add_argument("--zoom", type=float, nargs="?", const=1.1, default=0,
                    help="sugere zoom na camera nas emendas (desligado por padrao; sem valor = 1.1, maximo 1.2)")
    ap.add_argument("--sem-cenas", action="store_true", help="ignora trocas de slide ao posicionar cortes")
    ap.add_argument("--force", action="store_true", help="sobrescreve plan.json existente (perde as legendas revisadas e os \"z\" postos a mao)")
    a = ap.parse_args()
    vdir = os.path.join(ROOT, "videos", a.name); os.makedirs(vdir, exist_ok=True)
    pp = os.path.join(vdir, "plan.json")
    if os.path.exists(pp) and not a.force: sys.exit(f"ERRO: {os.path.relpath(pp, ROOT)} ja existe (legendas revisadas?). Use --force para sobrescrever.")
    engine.check_tools()
    edit = json.load(open(a.edit, encoding="utf-8")) if a.edit else {}
    P = json.load(open(a.preset if os.path.isabs(a.preset) else os.path.join(ROOT, a.preset), encoding="utf-8"))
    words = json.load(open(a.transcript, encoding="utf-8"))["words"]
    _, _, total, fps = engine.probe(a.video)
    print("ouvindo e olhando...", flush=True)
    db, floor = engine.audio_energy(a.video)
    blacks, scenes = engine.visual_events(a.video)
    if a.sem_cenas: scenes = []
    plan, removed, maybe = decide(words, edit, total, fps, db, floor, blacks, scenes, P["subtitles"]["max_chars_per_event"], zoom=a.zoom)
    json.dump(plan, open(pp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    md = report(plan, removed, maybe, total)
    open(os.path.join(vdir, "edit-plan.md"), "w", encoding="utf-8").write(md)
    print(md.splitlines()[2])
    print(f"ok: {os.path.relpath(pp, ROOT)} e edit-plan.md. Revisar cortes e legendas antes do render;")
    print("depois escrever o meta.json (skill publicar-video).")
    for w in engine.WARNINGS: print("  aviso:", w)
