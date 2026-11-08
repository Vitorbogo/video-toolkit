"""Spoken language of a video: language presets and detection from the transcript.

Each supported language has presets/fillers-<lang>.json (two-letter code) with:
  "fillers"         pure hesitations, always cut by src/vtk/engine.py
  "extra_fillers"   crutch words, cut only next to a comma (single words: the engine cuts phrases anywhere)
  "short_words"     a caption line should not end on these (articles, prepositions...)
  "break_before"    conjunctions: breaking a caption line before them reads naturally
  "function_words"  common words of the language, for detect()
Adding a language = adding that file. The transcription model (Parakeet TDT v3) does not report the language.

detect() is local and deterministic: it counts the transcript words that are function words of each language
(words listed by more than one language don't count) and picks the clear winner, or None when the text is too
short or mixed. It only chooses among the supported languages: a video in another language is not recognised as
such (it may come out as the closest one).
"""
import functools, glob, json, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PRESETS = os.path.join(ROOT, "presets")
MIN_HITS = 3        # fewer function words than this: too little text to tell
MIN_SHARE = 0.20    # the winner's function words must be at least this share of all words (speech: ~35-45%)
MARGIN = 2.0        # and at least this many times the runner-up's


def path(code):
    return os.path.join(PRESETS, f"fillers-{code}.json")


def supported():
    """Language codes that have a presets/fillers-<lang>.json, sorted."""
    names = (os.path.basename(p) for p in glob.glob(path("*")))
    return sorted(m.group(1) for m in map(re.compile(r"fillers-(\w+)\.json").fullmatch, names) if m)


@functools.lru_cache(maxsize=None)
def load(code):
    """The language preset as a dict, word lists as lowercase lists/sets. ValueError if unsupported."""
    if code not in supported():
        raise ValueError(f"unsupported language '{code}' (supported: {', '.join(supported())})")
    with open(path(code), encoding="utf-8") as f:
        p = json.load(f)
    lower = lambda k: [w.lower() for w in p.get(k, [])]
    return {"lang": code, "fillers": lower("fillers"), "extra_fillers": lower("extra_fillers"),
            "short_words": frozenset(lower("short_words")), "break_before": frozenset(lower("break_before")),
            "function_words": frozenset(lower("function_words"))}


def clean(word):
    """Lowercase word without punctuation, curly apostrophe as straight. Same as engine.clean."""
    return re.sub(r"[^\w']", "", word.lower().replace("’", "'"))


def tokens(text):
    """Cleaned words of text (str, or the transcript's word list)."""
    if not isinstance(text, str):
        text = " ".join(w["w"] for w in text)
    return [t for t in map(clean, text.split()) if t]


def scores(text):
    """{lang: number of words in text (str or word list) that are function words of only that language}, and the word count."""
    sets = {c: load(c)["function_words"] for c in supported()}
    shared = {w for c, s in sets.items() for d, t in sets.items() if c < d for w in s & t}
    toks = tokens(text)
    return {c: sum(t in s and t not in shared for t in toks) for c, s in sets.items()}, len(toks)


def detect(text):
    """Language code of text (str, or the transcript's word list), or None when it can't tell."""
    sc, n = scores(text)
    ranked = sorted(sc.items(), key=lambda kv: -kv[1])
    if not ranked: return None
    best, hits = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0
    if hits >= MIN_HITS and hits >= MIN_SHARE * n and hits >= MARGIN * second:
        return best
    return None


def describe(text):
    """'pt 41, en 3 function words out of 120' for messages."""
    sc, n = scores(text)
    return ", ".join(f"{c} {k}" for c, k in sorted(sc.items(), key=lambda kv: -kv[1])) + f" function words out of {n}"
