"""Loads a JSON preset, with optional inheritance.

A per-video preset (videos/<name>/preset.json) keeps only what changes, for example the crops of that recording:

    {"base": "presets/tiktok-vertical.json",
     "source": {"w": 2940, "h": 1612, "camera_crop": [1440, 810, 15, 290], "slide_crop": [1466, 1612, 1474, 0]}}

The rest comes from the base preset. Dicts are merged key by key; lists and plain values are replaced whole.
"base" is relative to the repository root (or absolute). Old presets, with everything copied, still work.
"""
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def merge(base, over):
    out = dict(base)
    for k, v in over.items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def resolve(path):
    """Absolute path: as given, if it exists from the current folder; otherwise, relative to the repository root."""
    if os.path.isabs(path) or os.path.exists(path):
        return os.path.abspath(path)
    return os.path.join(ROOT, path)


def load(path, _seen=None):
    path = resolve(path)
    seen = _seen or set()
    if path in seen:
        raise SystemExit("preset: circular inheritance in %s" % path)
    seen.add(path)
    with open(path, encoding="utf-8") as f:
        P = json.load(f)
    base = P.pop("base", None)
    return merge(load(base, seen), P) if base else P
