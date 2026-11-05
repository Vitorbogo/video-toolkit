"""Legenda desenhada com Pillow (o ffmpeg do Mac não tem libass): a frase inteira, com a palavra falada destacada.

Cada trecho do plan.json tem "ev": [[x0, x1, texto], ...] (tempos relativos ao início do trecho) e, quando veio do
cuts.py, "wt": [[início de cada palavra], ...], paralelo ao "ev". Se o texto foi editado na revisão e o número de
palavras mudou (ou o plano é antigo, sem "wt"), o tempo de cada palavra é estimado pelo tamanho dela dentro do evento.

O render.py chama overlay(): uma imagem PNG transparente por estado (frase + palavra ativa) e uma lista do
concat do ffmpeg com a duração de cada uma. A faixa fica com a base do texto a margin_v do fim do quadro.
"""
import os, textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FONTE_PADRAO = "assets/fonts/Poppins-ExtraBold.ttf"


def palavras(ev, wt=None):
    """Um evento [x0, x1, texto] -> [(inicio, fim, palavra)] relativos ao trecho."""
    x0, x1, texto = ev[0], ev[1], ev[2]
    ws = texto.split()
    if not ws:
        return []
    if wt and len(wt) == len(ws) and all(a <= b for a, b in zip(wt, wt[1:])):
        ini = [min(max(t, x0), x1) for t in wt]
    else:  # sem tempo por palavra: reparte pelo tamanho (mais 1 pelo espaço)
        tot = sum(len(w) + 1 for w in ws); ini, t = [], x0
        for w in ws:
            ini.append(t); t += (x1 - x0) * (len(w) + 1) / tot
    fins = ini[1:] + [x1]
    return [(round(a, 3), round(b, 3), w) for a, b, w in zip(ini, fins, ws)]


def blocos(ws, max_chars):
    """Divide as palavras de um evento em blocos de até max_chars (o que cabe na tela de uma vez)."""
    out, cur = [], []
    for w in ws:
        if cur and len(" ".join(x[2] for x in cur + [w])) > max_chars:
            out.append(cur); cur = []
        cur.append(w)
    if cur: out.append(cur)
    return out


def estados(trecho, max_chars):
    """Trecho do plano -> [(inicio, fim, palavras_do_bloco, indice_ativo)], em ordem, sem sobreposição."""
    wts = trecho.get("wt") or []
    out = []
    for k, ev in enumerate(trecho["ev"]):
        ws = palavras(ev, wts[k] if k < len(wts) else None)
        for b in blocos(ws, max_chars):
            for i, (a, z, _) in enumerate(b):
                out.append((a, z, [w[2] for w in b], i))
    limpo, t = [], 0.0
    for a, z, b, i in sorted(out, key=lambda e: e[0]):
        a = max(a, t)
        if z - a > 0.001:
            limpo.append((a, z, b, i)); t = z
    return limpo


def fonte(sub):
    p = sub.get("font_file", FONTE_PADRAO)
    return p if os.path.isabs(p) else os.path.join(ROOT, p)


def check_font(sub):
    """Aborta com mensagem clara se a fonte da legenda não existir (sem ela o Pillow cairia numa fonte feia)."""
    if not os.path.exists(fonte(sub)):
        raise SystemExit(f"legenda: fonte {fonte(sub)} não encontrada (subtitles.font_file no preset, relativo à raiz).")


def _rgb(h):
    h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def overlay(trecho, pasta, prefixo, sub, largura, k=1.0):
    """Escreve os PNG e a lista do concat em `pasta`; devolve (caminho_da_lista, altura_da_faixa)."""
    from PIL import Image, ImageDraw, ImageFont
    size = max(8, int(round(sub["size"] * k)))
    f = ImageFont.truetype(fonte(sub), size)
    lh = int(size * 1.22); stroke = max(2, int(round(sub["outline"] * k)))
    alt = (lh * 2 + stroke * 4 + 8) // 2 * 2
    cor, dest, borda = _rgb(sub.get("color", "#FFFFFF")), _rgb(sub.get("highlight", "#F5A623")), _rgb(sub.get("outline_color", "#141B28"))
    sp = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textlength(" ", font=f)

    def desenhar(bloco, ativo, nome):
        img = Image.new("RGBA", (largura, alt), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
        linhas, i = [], 0
        for ln in textwrap.wrap(" ".join(bloco), sub["max_chars_per_line"], break_long_words=False) or [""]:
            n = len(ln.split()); linhas.append(list(range(i, i + n))); i += n
        top = alt - stroke * 2 - lh * len(linhas)
        for li, idx in enumerate(linhas):
            larg = sum(d.textlength(bloco[j], font=f) for j in idx) + sp * (len(idx) - 1)
            x, y = (largura - larg) / 2, top + li * lh
            for j in idx:
                d.text((x, y), bloco[j], font=f, fill=dest if j == ativo else cor, stroke_width=stroke, stroke_fill=borda)
                x += d.textlength(bloco[j], font=f) + sp
        img.save(os.path.join(pasta, nome))

    vazio = f"{prefixo}-vazio.png"
    Image.new("RGBA", (largura, alt), (0, 0, 0, 0)).save(os.path.join(pasta, vazio))
    lista, t = [], 0.0
    for n, (a, z, bloco, ativo) in enumerate(estados(trecho, sub["max_chars_per_event"])):
        if a > t + 0.001: lista.append((vazio, a - t))
        nome = f"{prefixo}-{n:03d}.png"; desenhar(bloco, ativo, nome)
        lista.append((nome, z - a)); t = z
    lista.append((vazio, 1.0))  # cobre o fim do clipe; o render corta no -t
    caminho = os.path.join(pasta, f"{prefixo}.txt")
    with open(caminho, "w", encoding="utf-8") as fh:
        fh.write("ffconcat version 1.0\n")
        for nome, d in lista: fh.write(f"file '{nome}'\nduration {d:.3f}\n")
        fh.write(f"file '{vazio}'\n")
    return caminho, alt
