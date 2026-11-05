#!/usr/bin/env python3
"""Decide os cortes com o engine (src/vtk/engine.py, derivado da skill dev-video-editing, MIT) e escreve o plan.json do render.py.

Uso:
  python3 src/vtk/cuts.py --video GRAVACAO.mov --name <nome>
      [--transcript T] [--edit E] [--preset P] [--zoom [1.1]] [--sem-cenas] [--force]
Padrões: --transcript videos/<nome>/transcript.json; --edit videos/<nome>/edit.json (se existir);
--preset videos/<nome>/preset.json (se existir) ou presets/tiktok-vertical.json (fps do canvas, padrão 30).
Escreve videos/<nome>/plan.json (rascunho: legendas com o texto do Parakeet, REVISAR com o autor) e
videos/<nome>/edit-plan.md (cada remoção, refeita a partir dos trechos finais, com os motivos). Não sobrescreve
um plan.json existente sem --force; com --force guarda o anterior em plan.json.bak.

edit.json (opcional; tempos em segundos na gravação original). Chaves da skill (style, pauses, cut, keep,
replace, extra_fillers...) e as nossas (trim, zoom, blur):
  "cut":  [[a, b, "nota"]]  tira as palavras inteiras dentro do intervalo (aviso se não pegar nenhuma)
  "keep": [[a, b]]          mantém as palavras do intervalo (ganha do corte automático)
  "replace": {"chat GPT": "ChatGPT"}  aplicado no texto de cada legenda (vale chave com mais de uma palavra)
  "trim": [[a, b, "nota"]]  tira o intervalo bruto, com ou sem palavra (aviso se cortar parte de palavra mantida)
  "zoom": [[t, z]]          "z" no trecho que contém o tempo t (máx. 1.2; z <= 1 tira o zoom)
  "blur": [[t0, t1, x, y, w, h, "nota"]]  borrão; x/y/w/h em pixels da gravação original
Toda decisão à mão fica no edit.json: --force refaz o plan.json sem perder nada (correção de legenda repetida
vai no "replace"). Os enchimentos em português (presets/fillers-pt.json) entram sempre; os do edit.json somam.
Zoom automático é opcional e fica DESLIGADO: só usar --zoom quando as emendas ficarem bruscas. Com ele, a regra
da skill (alterna zoom/sem zoom em emendas de 1 s ou mais, ou depois de 4 s no mesmo enquadramento) põe "z" nos
trechos; o "zoom" do edit.json vem por cima.

plan.json: [{"s", "e", "ev": [[x0, x1, "texto"]], "wt": [[início de cada palavra]], "z"?, "blur"?: [[t0, t1, x, y, w, h]]}]; s/e no quadro,
ev e blur relativos a s.
"""
import argparse, json, math, os, re, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))
from vtk import engine as ev
from vtk import preset

with open(os.path.join(ROOT, "presets/fillers-pt.json"), encoding="utf-8") as _f:
    FILLERS_PT = {k: v for k, v in json.load(_f).items() if k in ("fillers", "extra_fillers")}
PRE_ROLL = 0.10   # igual ao PRE_ROLL da skill: trecho nunca abre a menos disso antes de uma palavra
TAIL = 0.03       # folga depois de uma palavra (a da skill quando não há medição de áudio)
MIN_GAP = 0.12    # corte menor que isso é emenda à toa (mesmo limite da skill)
MIN_PIECE = 0.4   # trecho menor que isso pisca (mesmo limite da skill)
MIN_CAP = 1.0     # legenda fica pelo menos isso na tela, se houver espaço
MAX_ZOOM = 1.2
MOTIVOS = {"filler": "enchimento", "stutter": "gagueira", "retake": "retomada", "cut": "corte à mão",
           "trim": "trim", "curto": "trecho curto"}
PEQUENAS = {"a", "o", "as", "os", "um", "uma", "de", "do", "da", "dos", "das", "em", "no", "na", "nos", "nas", "e",
            "que", "com", "para", "pra", "por", "pelo", "pela", "ao", "à", "se", "eu", "me", "te", "seu", "sua"}
LIGA = {"e", "mas", "porque", "pois", "quando", "ou", "então", "onde"}  # quebrar antes delas é natural


def fr(t, fps, how=round):
    """Tempo no quadro (round, math.floor ou math.ceil), sem ruído de ponto flutuante."""
    return how(round(t * fps, 6)) / fps


def dentro(w, a, b):
    """Mesmo critério de 'cut'/'keep' da skill: palavra inteira no intervalo, com 20 ms de folga."""
    return w["start"] >= a - 0.02 and w["end"] <= b + 0.02


def sobra(x, y, w):
    """Quanto da palavra w cai em [x, y] (negativo se não cai)."""
    return min(y, w["end"]) - max(x, w["start"])


def mantidas(words, reason):
    return [w for w, r in zip(words, reason) if r is None]


def exclude(words, reason, spans, fps):
    """Tira dos trechos o som das palavras removidas. A skill deixa parte da pausa ('respiração') e, quando a
    palavra removida está nessa pausa, uma ponta dela continua audível. O corte vai do quadro antes da palavra
    ao quadro depois (palavra curta leva junto um pouco da pausa, até 0,12 s), sem entrar na folga da palavra
    mantida anterior nem no pre-roll da seguinte; sobra sem fala com menos de 0,4 s sai junto. Se o corte
    deixar emenda < 0,12 s ou trecho com fala < 0,4 s, não corta e a palavra volta (reason None), para
    legenda e áudio baterem."""
    for i, w in enumerate(words):
        if reason[i] is None or not any(sobra(s, e, w) > 0 for s, e in spans): continue
        kept = mantidas(words, reason)
        fala = lambda x, y: any(sobra(x, y, k) > 0.01 for k in kept)
        prv = [k["end"] for k in kept if k["end"] <= w["start"]]
        nxt = [k["start"] for k in kept if k["start"] >= w["end"]]
        lo = fr(max(prv) + TAIL, fps, math.ceil) if prv else 0.0
        hi = fr(min(nxt) - PRE_ROLL, fps, math.floor) if nxt else math.inf
        a, b = max(lo, fr(w["start"], fps, math.floor)), min(hi, fr(w["end"], fps, math.ceil))
        if b - a < MIN_GAP: b = min(hi, fr(a + MIN_GAP, fps, math.ceil))  # palavra curta: leva junto a pausa
        if b - a < MIN_GAP: a = max(lo, fr(b - MIN_GAP, fps, math.floor))
        out, ok = [], b - a >= MIN_GAP
        for s, e in (spans if ok else ()):
            if e <= a or s >= b: out.append((s, e)); continue
            for x, y in ((s, a), (b, e)):
                if y <= x or (y - x < MIN_PIECE and not fala(x, y)): continue
                ok = ok and y - x >= MIN_PIECE
                out.append((x, y))
        holes = set(zip([e for _, e in spans], [s for s, _ in spans[1:]]))
        if ok and all(q - p >= MIN_GAP or (p, q) in holes for (_, p), (q, _) in zip(out, out[1:])):
            spans = out
        elif sum(max(0, sobra(s, e, w)) for s, e in spans) > (w["end"] - w["start"]) / 2:
            reason[i] = None
    return spans


def trim(words, reason, spans, cortes, fps, avisos):
    """'trim' do edit.json: tira o intervalo bruto dos trechos (no quadro mais próximo)."""
    for it in cortes:
        a, b = fr(float(it[0]), fps), fr(float(it[1]), fps)
        for w, r in zip(words, reason):
            if r is None and sobra(a, b, w) > 0:
                avisos.append(f"trim {a:.2f}-{b:.2f} corta parte de \"{w['w']}\" ({w['start']:.2f}-{w['end']:.2f}), palavra mantida")
        spans = [(x, y) for s, e in spans for x, y in (((s, e),) if e <= a or s >= b else ((s, a), (b, e))) if y > x]
    return spans


def finish(words, reason, spans, fps, total, avisos):
    """Bordas no quadro: o início sobe para depois da palavra mantida anterior, o fim desce para antes da
    seguinte; trechos encostados viram um; trecho < 0,4 s sai (com aviso, se tinha fala)."""
    kept = mantidas(words, reason)
    out = []
    for s, e in sorted(spans):
        s2, e2 = max(0.0, fr(s, fps)), min(fr(e, fps), fr(total, fps, math.floor))
        if s2 < s and any(s2 < k["end"] <= s for k in kept): s2 = fr(s, fps, math.ceil)
        if e2 > e and any(e <= k["start"] < e2 for k in kept): e2 = fr(e, fps, math.floor)
        if out and s2 <= out[-1][1] + 1e-6: out[-1] = (out[-1][0], max(out[-1][1], e2))
        elif e2 > s2: out.append((s2, e2))
    final = []
    for s, e in out:
        if e - s >= MIN_PIECE - 1e-6: final.append((round(s, 6), round(e, 6))); continue
        ws = [k for k in kept if sobra(s, e, k) > 0.01]
        if ws:
            avisos.append(f"trecho {s:.2f}-{e:.2f} com menos de {MIN_PIECE} s saiu, e com ele \"{' '.join(k['w'] for k in ws)}\"")
            for k in ws: reason[words.index(k)] = "curto"
    return final


def removals(words, reason, spans, total, trims=()):
    """Remoções a partir dos trechos finais (abertura, intervalos, fim): (início, fim, motivos, palavras).
    Motivos = os das palavras removidas ali dentro, "trim" se um trim do edit.json pega o intervalo, e
    "silêncio" quando a maior parte dele não tem palavra."""
    b = [0.0] + [t for s, e in spans for t in (s, e)] + [total]
    out = []
    for x, y in zip(b[::2], b[1::2]):
        if y - x < 0.01: continue
        ins = [(w, r) for w, r in zip(words, reason) if x <= (w["start"] + w["end"]) / 2 < y]
        why = {MOTIVOS.get(r.split(":")[0], r.split(":")[0]) for _, r in ins if r}
        if any(min(y, float(t[1])) - max(x, float(t[0])) > 0.01 for t in trims): why.add("trim")
        why = sorted(why)
        if sum(max(0, sobra(x, y, w)) for w, _ in ins) < (y - x) / 2 or not why: why.append("silêncio")
        out.append((x, y, ", ".join(why), " ".join(w["w"] for w, r in ins if r)))
    return out


def limpa(t):
    return re.sub(r"[^\w']", "", t.lower())


def texto(ws, rep):
    t = ev.apply_replace(" ".join(w[2] for w in ws), rep)
    return re.sub(r"([,;:])\1+", r"\1", t)  # "ocupação" -> "ocupação," quando o Parakeet já pôs a vírgula


def quebra(ws, max_chars, rep):
    """Frase -> pedaços de até max_chars: o menor número deles, equilibrados (sem palavra órfã). Evita quebrar
    depois de palavra pequena, prefere depois de vírgula ou antes de "e", "mas"...; nunca quebra dentro de uma
    chave do replace ("chat GPT")."""
    raw, pos = "", []
    for w in ws:
        pos.append(len(raw) + bool(raw)); raw += " " * bool(raw) + w[2]
    cola = set()
    for a in rep:
        for m in re.finditer(r"\b" + re.escape(a) + r"\b", raw, flags=re.I):
            cola |= set([k for k, p in enumerate(pos) if p < m.end() and p + len(ws[k][2]) > m.start()][:-1])
    pena = max_chars ** 2 / 12
    best = [(0, 0, 0.0, None)] + [None] * len(ws)  # (pedaços longos demais, pedaços, custo, início)
    for j in range(1, len(ws) + 1):
        if j < len(ws) and j - 1 in cola: continue
        for i in range(j):
            if best[i] is None: continue
            n = len(texto(ws[i:j], rep))
            c = n * n
            if j < len(ws):
                fim = ws[j - 1][2]
                c += pena * (limpa(fim) in PEQUENAS) - pena * (fim[-1:] in ",;:") - pena / 2 * (limpa(ws[j][2]) in LIGA)
            cand = (best[i][0] + (n > max_chars and j - i > 1), best[i][1] + 1, best[i][2] + c, i)
            if best[j] is None or cand[:3] < best[j][:3]: best[j] = cand
    out, j = [], len(ws)
    while j: out.insert(0, ws[best[j][3]:j]); j = best[j][3]
    return out


def captions(ws, d, max_chars, rep):
    """Palavras mantidas [(t0, t1, palavra)] no tempo do vídeo já cortado (d = duração) -> [[t0, t1, texto, inícios]],
    com inícios = começo de cada palavra da legenda (o "wt" do plan.json, para o destaque da palavra falada).
    Quebra nas frases, em pedaços equilibrados; cada legenda fica pelo menos 1 s na tela, esticando até a
    próxima; se nem assim chega a 1 s, junta com a vizinha quando cabe em max_chars."""
    grupos, cur = [], []
    for w in ws:
        cur.append(w)
        if w[2][-1:] in ".?!": grupos += quebra(cur, max_chars, rep); cur = []
    if cur: grupos += quebra(cur, max_chars, rep)
    k = 0
    while k < len(grupos):
        g = grupos[k]
        if (grupos[k + 1][0][0] if k + 1 < len(grupos) else d) - g[0][0] < MIN_CAP:  # nem esticando chega a 1 s
            if k and g[0][0] - grupos[k - 1][-1][1] < 1.0 and len(texto(grupos[k - 1] + g, rep)) <= max_chars:
                grupos[k - 1:k + 1] = [grupos[k - 1] + g]; k -= 1; continue
            if k + 1 < len(grupos) and grupos[k + 1][0][0] - g[-1][1] < 1.0 and len(texto(g + grupos[k + 1], rep)) <= max_chars:
                grupos[k:k + 2] = [g + grupos[k + 1]]; continue
        k += 1
    return [[g[0][0], max(g[-1][1], min(g[0][0] + MIN_CAP, grupos[k + 1][0][0] if k + 1 < len(grupos) else d)), texto(g, rep),
             [w[0] for w in g]] for k, g in enumerate(grupos)]


def decide(words, edit, total, fps=30.0, db=(), floor=-60.0, blacks=(), scenes=(), max_chars=60, zoom=0, avisos=None):
    """Retorna (plan, removidos, possiveis_retomadas). Tempos de 'removidos' e 'retomadas' na gravação original.
    zoom > 1 liga a sugestão de zoom da skill (só na câmera, no render.py); 0 deixa todos os trechos sem zoom.
    'fillers' e 'extra_fillers' do edit.json somam com a lista em português; as outras chaves da skill vão direto
    para ela. 'avisos' (lista) recebe o que precisa de revisão."""
    avisos = [] if avisos is None else avisos
    spec = {**edit, **{k: v + [x for x in edit.get(k, []) if x not in v] for k, v in FILLERS_PT.items()}}
    for it in spec.get("cut", []):
        if not any(dentro(w, float(it[0]), float(it[1])) for w in words):
            avisos.append(f"cut {it[0]}-{it[1]} não pega nenhuma palavra inteira (trecho sem palavra: usar \"trim\")")
    reason, maybe = ev.mark(words, spec)
    for it in spec.get("trim", []):
        for i, w in enumerate(words):
            if dentro(w, float(it[0]), float(it[1])): reason[i] = reason[i] or "trim: " + (it[2] if len(it) > 2 else "à mão")
    spans, _ = ev.plan_spans(words, reason, spec, total, fps, list(db), floor, list(blacks), list(scenes))
    spans = exclude(words, reason, spans, fps)
    spans = trim(words, reason, spans, spec.get("trim", []), fps, avisos)
    spans = finish(words, reason, spans, fps, total, avisos)
    if not spans: sys.exit("cuts: não sobrou nenhum trecho; conferir 'cut' e 'trim' do edit.json")
    removed = removals(words, reason, spans, total, spec.get("trim", []))
    first = {w["start"]: i for i, w in reversed(list(enumerate(words)))}
    maybe = [m for m in maybe if not all(reason[first[m[0]]:first[m[0]] + len(m[1].split())])]
    # legenda no tempo do vídeo cortado (uma frase pode atravessar uma emenda), depois repartida pelos trechos;
    # maiúscula no começo e depois de fim de frase (mantida ou removida), como a caption_events da skill
    rep, prv, out, off = spec.get("replace", {}), None, [], [0.0]
    for s, e in spans: off.append(off[-1] + e - s)
    for i, (w, r) in enumerate(zip(words, reason)):
        if r is not None: continue
        t = w["w"]
        if (prv is None or prv[-1:] in ".?!" or (reason[i - 1] and words[i - 1]["w"][-1:] in ".?!")) and t[:1].islower():
            t = t[:1].upper() + t[1:]
        prv = t
        ov = [sobra(s, e, dict(w, end=max(w["end"], w["start"] + 0.02))) for s, e in spans]
        j = max(range(len(spans)), key=ov.__getitem__)
        if ov[j] <= 0.01:
            avisos.append(f"\"{w['w']}\" ({w['start']:.2f} s) ficou fora dos trechos e da legenda"); continue
        s, e = spans[j]
        out.append((off[j] + max(0.0, w["start"] - s), off[j] + min(w["end"], e) - s, t))
    plan = [{"s": s, "e": e, "ev": [], "wt": []} for s, e in spans]
    for t0, t1, t, ini in captions(out, off[-1], max_chars, rep):
        for c, o in zip(plan, off):
            d = round(c["e"] - c["s"], 6)
            a, b = round(max(0.0, t0 - o), 3), min(round(t1 - o, 3), d)
            if b - a >= 0.01:
                # "wt": início de cada palavra, relativo ao trecho (pode cair fora dele quando a legenda atravessa
                # uma emenda; o render prende no evento). Se o replace mudou o número de palavras, o render estima.
                c["ev"].append([a, b, t]); c["wt"].append([round(x - o, 3) for x in ini])
    if zoom > 1:
        zs = ev.zoom_plan(spans, {"style": spec.get("style", "youtube"), "punch_in": zoom}, list(scenes), list(blacks))
        for c, z in zip(plan, zs):
            if z > 1: c["z"] = z
    for it in spec.get("zoom", []):
        t, z = float(it[0]), float(it[1])
        c = next((c for c in plan if c["s"] <= t < c["e"]), None)
        if c is None: avisos.append(f"zoom em {t} s: fora dos trechos mantidos"); continue
        c.pop("z", None)
        if z > 1: c["z"] = round(min(MAX_ZOOM, z), 3)
    for it in spec.get("blur", []):
        t0, t1, box = float(it[0]), float(it[1]), list(it[2:6])
        hit = [c for c in plan if min(t1, c["e"]) - max(t0, c["s"]) > 0.001]
        if not hit: avisos.append(f"blur {t0}-{t1}: fora dos trechos mantidos")
        for c in hit:
            d = round(c["e"] - c["s"], 6)
            c.setdefault("blur", []).append([round(max(0.0, t0 - c["s"]), 3), min(round(t1 - c["s"], 3), d)] + box)
    return plan, removed, maybe


def ler(p):
    with open(p, encoding="utf-8") as f: return json.load(f)


def escrever(p, txt):
    with open(p, "w", encoding="utf-8") as f: f.write(txt)


def legendas(plan):
    """Textos das legendas em ordem; a que atravessa uma emenda (continua no começo do trecho seguinte) conta uma vez."""
    out, ult = [], None
    for c in plan:
        out += [t for n, (x0, _, t) in enumerate(c["ev"]) if n or x0 > 0 or t != ult]
        ult = c["ev"][-1][2] if c["ev"] else None
    return out


def marca(t):
    return f"{int(t // 60)}:{t % 60:04.1f}"


def report(plan, removed, maybe, total, avisos=()):
    dur = sum(c["e"] - c["s"] for c in plan)
    wpm = sum(len(t.split()) for t in legendas(plan)) / max(1.0, dur) * 60
    o = [f"# Plano de cortes\n\n{ev.stamp(total)} -> {ev.stamp(dur)} ({(total - dur) / total * 100:.0f}% menor), "
         f"{len(plan) - 1} cortes, {wpm:.0f} palavras por minuto.\n"]
    av = list(avisos)  # os da skill: ritmo e quanto saiu
    if wpm > 190: av.append(f"ritmo de {wpm:.0f} palavras por minuto: acima de 190 parece corrido")
    if (total - dur) / total > 0.45: av.append(f"{(total - dur) / total * 100:.0f}% removido: acima de 45% costuma ser corte indevido")
    if av: o += ["## Avisos\n"] + [f"- {a}" for a in av] + [""]
    zoomed = [(i, c) for i, c in enumerate(plan) if c.get("z", 1) > 1]
    if zoomed:
        o.append("## Zoom na câmera (opcional: para tirar, \"zoom\": [[t, 1]] no edit.json, que sobrevive ao --force)\n")
        o += [f"- trecho {i} ({ev.stamp(c['s'])}): {c['z']:g}x" for i, c in zoomed] + [""]
    if maybe:
        o.append("## Possíveis retomadas (não cortadas: decidir e pôr em \"cut\" no edit.json)\n")
        o += [f"- {ev.stamp(t)}: \"{a[:90]}\" depois \"{b[:90]}\"" for t, a, b in maybe] + [""]
    o += ["## Remoções\n", "| Original | Tirado | Motivo | Palavras |", "|---|---|---|---|"]
    o += [f"| {marca(s)} | {e - s:.1f} s | {why} | {txt[:80]} |" for s, e, why, txt in removed]
    return "\n".join(o) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True); ap.add_argument("--name", required=True)
    ap.add_argument("--transcript", help="padrão: videos/<nome>/transcript.json")
    ap.add_argument("--edit", help="padrão: videos/<nome>/edit.json, se existir")
    ap.add_argument("--preset", help="padrão: videos/<nome>/preset.json, se existir, ou presets/tiktok-vertical.json")
    ap.add_argument("--zoom", type=float, nargs="?", const=1.1, default=0,
                    help="sugere zoom na camera nas emendas (desligado por padrao; sem valor = 1.1, maximo 1.2)")
    ap.add_argument("--sem-cenas", action="store_true", help="ignora trocas de slide ao posicionar cortes")
    ap.add_argument("--force", action="store_true", help="refaz o plan.json existente (o anterior vai para plan.json.bak)")
    a = ap.parse_args()
    vdir = os.path.join(ROOT, "videos", a.name); os.makedirs(vdir, exist_ok=True)
    pp = os.path.join(vdir, "plan.json")
    if os.path.exists(pp) and not a.force: sys.exit(f"ERRO: {os.path.relpath(pp, ROOT)} ja existe (legendas revisadas?). Use --force para sobrescrever.")
    ep = a.edit or os.path.join(vdir, "edit.json")
    edit = ler(ep) if a.edit or os.path.exists(ep) else {}
    pv = os.path.join(vdir, "preset.json")
    P = preset.load(a.preset or (pv if os.path.exists(pv) else "presets/tiktok-vertical.json"))
    fps = float(P.get("canvas", {}).get("fps", 30))
    words = ler(a.transcript or os.path.join(vdir, "transcript.json"))["words"]
    ev.check_tools()
    _, _, total, _ = ev.probe(a.video)
    print("ouvindo e olhando...", flush=True)
    db, floor = ev.audio_energy(a.video)
    blacks, scenes = ev.visual_events(a.video)
    if a.sem_cenas: scenes = []
    avisos = []
    plan, removed, maybe = decide(words, edit, total, fps, db, floor, blacks, scenes, P["subtitles"]["max_chars_per_event"],
                                  zoom=a.zoom, avisos=avisos)
    bak = os.path.exists(pp)
    if bak: shutil.copyfile(pp, pp + ".bak")
    escrever(pp, json.dumps(plan, ensure_ascii=False, indent=1))
    md = report(plan, removed, maybe, total, avisos)
    escrever(os.path.join(vdir, "edit-plan.md"), md)
    print(md.splitlines()[2])
    print(f"ok: {os.path.relpath(pp, ROOT)} e edit-plan.md" + (" (o anterior ficou em plan.json.bak)" if bak else "")
          + (f", com {os.path.relpath(ep, ROOT)}" if edit else ", sem edit.json") + ".")
    print("Revisar cortes e legendas com o autor antes do render; depois escrever o meta.json (skill publicar-video).")
    for w in avisos + ev.WARNINGS: print("  aviso:", w)


if __name__ == "__main__":
    main()
