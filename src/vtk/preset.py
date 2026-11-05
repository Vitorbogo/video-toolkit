"""Carrega um preset JSON, com herança opcional.

Um preset de vídeo (videos/<nome>/preset.json) guarda só o que muda, por exemplo os recortes daquela gravação:

    {"base": "presets/tiktok-vertical.json",
     "source": {"w": 2940, "h": 1612, "camera_crop": [1440, 810, 15, 290], "slide_crop": [1466, 1612, 1474, 0]}}

O resto vem do preset base. Dicionários são mesclados chave a chave; listas e valores simples são trocados inteiros.
"base" é relativo à raiz do repositório (ou absoluto). Presets antigos, com tudo copiado, continuam valendo.
"""
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def merge(base, over):
    out = dict(base)
    for k, v in over.items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def resolve(path):
    """Caminho absoluto: como dado, se existir a partir da pasta atual; senão, relativo à raiz do repositório."""
    if os.path.isabs(path) or os.path.exists(path):
        return os.path.abspath(path)
    return os.path.join(ROOT, path)


def load(path, _seen=None):
    path = resolve(path)
    seen = _seen or set()
    if path in seen:
        raise SystemExit("preset: herança circular em %s" % path)
    seen.add(path)
    with open(path, encoding="utf-8") as f:
        P = json.load(f)
    base = P.pop("base", None)
    return merge(load(base, seen), P) if base else P
