"""Captions drawn with Pillow (the Mac's ffmpeg has no libass): the whole sentence, with the spoken word highlighted.

Each plan.json segment has "ev": [[x0, x1, text], ...] (times relative to the segment start) and, when it came from
cuts.py, "wt": [[start of each word], ...], parallel to "ev". If the text was edited in review and the number of
words changed (or the plan is old, without "wt"), each word's time is estimated from its length within the event.

render.py calls overlay(): one transparent PNG per state (sentence + active word) and an ffmpeg concat list
with each one's duration. The strip sits with the text baseline margin_v above the bottom of the frame.
"""
import os, textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_FONT = "assets/fonts/Poppins-ExtraBold.ttf"


def words(ev, wt=None):
    """One event [x0, x1, text] -> [(start, end, word)] relative to the segment."""
    x0, x1, text = ev[0], ev[1], ev[2]
    ws = text.split()
    if not ws:
        return []
    if wt and len(wt) == len(ws) and all(a <= b for a, b in zip(wt, wt[1:])):
        starts = [min(max(t, x0), x1) for t in wt]
    else:  # no per-word timing: split by length (plus 1 for the space)
        tot = sum(len(w) + 1 for w in ws); starts, t = [], x0
        for w in ws:
            starts.append(t); t += (x1 - x0) * (len(w) + 1) / tot
    ends = starts[1:] + [x1]
    return [(round(a, 3), round(b, 3), w) for a, b, w in zip(starts, ends, ws)]


def blocks(ws, max_chars):
    """Splits an event's words into blocks of up to max_chars (what fits on screen at once)."""
    out, cur = [], []
    for w in ws:
        if cur and len(" ".join(x[2] for x in cur + [w])) > max_chars:
            out.append(cur); cur = []
        cur.append(w)
    if cur: out.append(cur)
    return out


def states(seg, max_chars):
    """Plan segment -> [(start, end, block_words, active_index)], in order, without overlap."""
    wts = seg.get("wt") or []
    out = []
    for k, ev in enumerate(seg["ev"]):
        ws = words(ev, wts[k] if k < len(wts) else None)
        for b in blocks(ws, max_chars):
            for i, (a, z, _) in enumerate(b):
                out.append((a, z, [w[2] for w in b], i))
    clean, t = [], 0.0
    for a, z, b, i in sorted(out, key=lambda e: e[0]):
        a = max(a, t)
        if z - a > 0.001:
            clean.append((a, z, b, i)); t = z
    return clean


def font_path(sub):
    p = sub.get("font_file", DEFAULT_FONT)
    return p if os.path.isabs(p) else os.path.join(ROOT, p)


def check_font(sub):
    """Aborts with a clear message if the caption font doesn't exist (without it Pillow would fall back to an ugly font)."""
    if not os.path.exists(font_path(sub)):
        raise SystemExit(f"captions: font {font_path(sub)} not found (subtitles.font_file in the preset, relative to the root).")


def _rgb(h):
    h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def overlay(seg, folder, prefix, sub, width, k=1.0):
    """Writes the PNGs and the concat list in `folder`; returns (list_path, strip_height)."""
    from PIL import Image, ImageDraw, ImageFont
    size = max(8, int(round(sub["size"] * k)))
    f = ImageFont.truetype(font_path(sub), size)
    lh = int(size * 1.22); stroke = max(2, int(round(sub["outline"] * k)))
    height = (lh * 2 + stroke * 4 + 8) // 2 * 2
    color, hl, edge = _rgb(sub.get("color", "#FFFFFF")), _rgb(sub.get("highlight", "#F5A623")), _rgb(sub.get("outline_color", "#141B28"))
    sp = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textlength(" ", font=f)

    def draw(block, active, name):
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
        lines, i = [], 0
        for ln in textwrap.wrap(" ".join(block), sub["max_chars_per_line"], break_long_words=False) or [""]:
            n = len(ln.split()); lines.append(list(range(i, i + n))); i += n
        top = height - stroke * 2 - lh * len(lines)
        for li, idx in enumerate(lines):
            lw = sum(d.textlength(block[j], font=f) for j in idx) + sp * (len(idx) - 1)
            x, y = (width - lw) / 2, top + li * lh
            for j in idx:
                d.text((x, y), block[j], font=f, fill=hl if j == active else color, stroke_width=stroke, stroke_fill=edge)
                x += d.textlength(block[j], font=f) + sp
        img.save(os.path.join(folder, name))

    empty = f"{prefix}-empty.png"
    Image.new("RGBA", (width, height), (0, 0, 0, 0)).save(os.path.join(folder, empty))
    entries, t = [], 0.0
    for n, (a, z, block, active) in enumerate(states(seg, sub["max_chars_per_event"])):
        if a > t + 0.001: entries.append((empty, a - t))
        name = f"{prefix}-{n:03d}.png"; draw(block, active, name)
        entries.append((name, z - a)); t = z
    entries.append((empty, 1.0))  # covers the end of the clip; render cuts it with -t
    list_path = os.path.join(folder, f"{prefix}.txt")
    with open(list_path, "w", encoding="utf-8") as fh:
        fh.write("ffconcat version 1.0\n")
        for name, d in entries: fh.write(f"file '{name}'\nduration {d:.3f}\n")
        fh.write(f"file '{empty}'\n")
    return list_path, height
