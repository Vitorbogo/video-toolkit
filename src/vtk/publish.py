#!/usr/bin/env python3
"""Validates a video's publishing metadata and generates videos/<name>/publish.md (ready to copy and paste).

The creative part (titles, description, hashtags, cover recommendation) is written by Claude in
videos/<name>/meta.json, following .claude/skills/publish-video/SKILL.md, in the language spoken in the video.
This script is the DETERMINISTIC part: checks types and platform limits (presets/publish.json), hashtag format,
the chosen cover (thumb.json + files in covers/) and the duration, and builds the final file.
Same inputs (meta.json, thumb.json, preset, video duration) = same publish.md, byte for byte (no date).
Exits with code 1 on any ERROR: nothing is generated and an old publish.md becomes publish.md.stale.
WARNINGS go at the top of publish.md.

  python3 src/vtk/publish.py --name <name> --video <final mp4>   # covers: videos/<name>/covers (or --covers)
"""
import argparse, json, os, re, shutil, subprocess, sys, unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FIELDS = {
    "titles": "list of 1 to 3 titles (the first is the recommended one)",
    "description": "YouTube description, without hashtags (hook in the first 100 characters)",
    "tiktok_caption": "TikTok caption, without hashtags",
    "hashtags": '{"tiktok": [...], "youtube": [...]}, each with "#"',
    "hashtags_reason": "1 sentence: why these hashtags (or why none)",
    "cover": '{"variant": "A|B|C" (from thumb.json), "reason": "..."}',
}
OPTIONAL = ("youtube_tags", "pinned_comment", "notes", "lang")
PLATFORMS = ("tiktok", "youtube")

RX_HASHTAG = re.compile(r"^#\w+$")
RX_HASH_IN_TEXT = re.compile(r"(?<![\w&/])#\w+")
RX_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍]")
RX_LANG = re.compile(r"^[a-z]{2}$")


def nfc(x):
    """Normalizes (NFC) every string: "ã" counts as 1 character, wherever it came from."""
    if isinstance(x, str): return unicodedata.normalize("NFC", x)
    if isinstance(x, list): return [nfc(v) for v in x]
    if isinstance(x, dict): return {k: nfc(v) for k, v in x.items()}
    return x


def text(v):
    return isinstance(v, str) and v.strip() != ""


def text_list(v):
    return isinstance(v, list) and all(text(x) for x in v)


def cover_files(var):
    return {"9x16": f"cover_{var}_9x16_1080x1920.png", "16x9": f"cover_{var}_16x9_1280x720.png"}


def tiktok_caption(M):
    hs = M["hashtags"]["tiktok"]
    return M["tiktok_caption"] + ("\n\n" + " ".join(hs) if hs else "")


def youtube_description(M):
    hs = M["hashtags"]["youtube"]
    return M["description"] + ("\n\n" + " ".join(hs) if hs else "")


def tags_total(tags):
    """How YouTube counts the tags field: commas between them + 2 quotes on each tag with a space."""
    return len(",".join(tags)) + 2 * sum(1 for t in tags if " " in t)


def duration(video):
    """Duration in seconds (1 decimal) via ffprobe. Raises ValueError with a readable message."""
    if not os.path.isfile(video):
        raise ValueError(f"video not found: {video}")
    if not shutil.which("ffprobe"):
        raise ValueError("ffprobe not found in PATH (it comes with ffmpeg); without it the duration cannot be checked")
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video],
                       capture_output=True, text=True)
    try:
        return round(float(r.stdout.strip()), 1)
    except ValueError:
        raise ValueError(f"could not read the duration of {video} (ffprobe: {r.stderr.strip()[:200] or 'no output'})")


def validate(M, P, dur=None, thumb=None, covers=None):
    """Checks meta.json (already NFC) against the preset. Returns (errors, warnings).
    dur: seconds or None (not checked); thumb: thumb.json or None (missing); covers: file names in covers/ or None."""
    errors, warnings = [], []
    if not isinstance(M, dict):
        return ["meta.json must be a JSON object {...}"], []
    has = lambda k: k in M and M[k] not in ("", [], {}, None)
    for k in FIELDS:
        if not has(k): errors.append(f"required field missing or empty: {k} ({FIELDS[k]})")
    for k in ("description", "tiktok_caption", "hashtags_reason"):
        if has(k) and not text(M[k]): errors.append(f"{k} must be text")
    t = M.get("titles")
    if has("titles") and not (isinstance(t, list) and 1 <= len(t) <= 3 and text_list(t)):
        errors.append("titles must be a list of 1 to 3 non-empty texts")
    h = M.get("hashtags")
    if has("hashtags"):
        if not isinstance(h, dict): errors.append('hashtags must be {"tiktok": [...], "youtube": [...]}')
        else:
            for p in sorted(set(h) - set(PLATFORMS)): errors.append(f"hashtags: unknown platform '{p}' (use {', '.join(PLATFORMS)})")
            for p in PLATFORMS:
                if p not in h: errors.append(f"hashtags.{p} missing (empty list [] if there are none)")
                elif not (isinstance(h[p], list) and all(isinstance(x, str) for x in h[p])): errors.append(f"hashtags.{p} must be a list of texts")
    c = M.get("cover")
    if has("cover"):
        if not isinstance(c, dict): errors.append('cover must be {"variant": "...", "reason": "..."}')
        else:
            for k in ("variant", "reason"):
                if not text(c.get(k)): errors.append(f"cover.{k} missing or empty")
    if "youtube_tags" in M and not text_list(M["youtube_tags"]):
        errors.append("youtube_tags must be a list of non-empty texts")
    for k in ("pinned_comment", "notes"):
        if k in M and not isinstance(M[k], str): errors.append(f"{k} must be text")
    if "lang" in M and not (isinstance(M["lang"], str) and RX_LANG.match(M["lang"])):
        errors.append(f"lang must be a two-letter lowercase language code, e.g. \"pt\" or \"en\" (got {M['lang']!r})")
    for k in sorted(set(M) - set(FIELDS) - set(OPTIONAL)): warnings.append(f"unknown field in meta.json (ignored): {k}")
    if errors:
        return errors, warnings

    L, H = P["limits"], P["hashtags"]
    yt, tt = L["youtube"], L["tiktok"]
    for i, t in enumerate(M["titles"], 1):
        if len(t) > yt["title_max"]: errors.append(f"title {i} has {len(t)} characters (max {yt['title_max']})")
        elif len(t) > yt["title_visible_feed"]:
            warnings.append(f"title {i} has {len(t)} characters; the feed only shows ~{yt['title_visible_feed']}. Put the key point first.")

    texts = [(f"title {i}", t) for i, t in enumerate(M["titles"], 1)] + [("description", M["description"]), ("tiktok_caption", M["tiktok_caption"])]
    for name, s in texts:
        found = RX_HASH_IN_TEXT.findall(s)
        if found: errors.append(f"{name} has a hashtag in the text {found}: hashtags go only in the hashtag lists")
        if name != "tiktok_caption" and re.search("[<>]", s): errors.append(f"{name} has '<' or '>' (YouTube does not accept them)")
    with_emoji = [n for n, s in texts if RX_EMOJI.search(s)]
    if with_emoji: warnings.append(f"emoji in {', '.join(with_emoji)}: the platform may count differently (check the limit when pasting)")

    for p in PLATFORMS:
        hs = M["hashtags"][p]
        bad = [x for x in hs if not RX_HASHTAG.match(x)]
        if bad: errors.append(f"invalid hashtags in {p} (need '#' and no space/punctuation): {bad}")
        seen, rep = set(), []
        for x in hs:
            if x.casefold() in seen: rep.append(x)
            seen.add(x.casefold())
        if rep: errors.append(f"repeated hashtags in {p} (case-insensitive): {rep}")
        if hs and not (H["recommended_min"] <= len(hs) <= H["recommended_max"]):
            warnings.append(f"{p}: {len(hs)} hashtags (recommended {H['recommended_min']} to {H['recommended_max']}). If on purpose, explain it in hashtags_reason.")
    if len(M["hashtags"]["youtube"]) > yt["hashtags_max"]:
        errors.append(f"{len(M['hashtags']['youtube'])} hashtags on YouTube (max {yt['hashtags_max']}): above that all of them are ignored")

    n = len(tiktok_caption(M))
    if n > tt["caption_max"]: errors.append(f"TikTok caption + hashtags has {n} characters (max {tt['caption_max']})")
    d = youtube_description(M)
    if len(d) > yt["description_max"]: errors.append(f"description + hashtags has {len(d)} characters (max {yt['description_max']})")
    elif len(d.encode("utf-8")) > yt["description_max"]:
        warnings.append(f"description + hashtags has {len(d.encode('utf-8'))} bytes in UTF-8 (> {yt['description_max']}); if the limit is in bytes, YouTube truncates it")
    tg = M.get("youtube_tags", [])
    if tags_total(tg) > yt["tags_total_max"]:
        errors.append(f"YouTube tags add up to {tags_total(tg)} characters, counting commas and quotes on tags with a space (max {yt['tags_total_max']})")

    if dur is not None:
        if dur <= 0: errors.append(f"video duration is {dur:.1f} s: empty or corrupted file")
        elif dur > yt["short_max_duration_s"]:
            warnings.append(f"video is {dur:.1f} s long: above {yt['short_max_duration_s']} s, YouTube does not treat it as a Short (it becomes a regular vertical video).")

    var, reason = M["cover"]["variant"], M["cover"]["reason"]
    if reason.strip().upper().startswith("PROVIS"):
        errors.append("cover still provisional: look at the thumb.py covers and update cover.variant and cover.reason")
    if thumb is None:
        errors.append("the video's thumb.json is missing: the cover is chosen among its variants")
    else:
        names = [v.get("name") for v in thumb.get("variants") or [] if isinstance(v, dict)]
        if var not in names:
            opts = names or 'none; add "variants" to thumb.json'
            errors.append(f"cover variant '{var}' does not exist in thumb.json (variants: {opts})")
    if covers is None:
        errors.append("covers folder not found (run thumb.py)")
    else:
        for f in cover_files(var).values():
            if f not in covers: errors.append(f"cover not found: {f} (run thumb.py)")
    return errors, warnings


def render(name, M, P, dur, thumb, warnings, used=None):
    """Builds publish.md. Depends only on the inputs (no date, no absolute path).
    used: covers/covers.json from thumb.py (actual times, including the neutral-face "auto" ones)."""
    yt, tt = P["limits"]["youtube"], P["limits"]["tiktok"]
    var = M["cover"]["variant"]
    files = cover_files(var)
    vinfo = next((v for v in (thumb or {}).get("variants") or [] if isinstance(v, dict) and v.get("name") == var), None)
    clip = lambda s, n: " ".join(s[:n].split()) + ("…" if len(s) > n else "")  # on a single line
    mmss = lambda s: f"{int(round(s)) // 60}:{int(round(s)) % 60:02d}"
    o = [f"# Publish — {name}\n"]
    o.append("_Generated by `publish.py`" + (f" · language {M['lang']}" if M.get("lang") else "")
             + (f" · duration {mmss(dur)}" if dur else "") + "_\n")
    if warnings:
        o.append("> [!warning] Warnings\n" + "\n".join(f"> - {x}" for x in warnings) + "\n")
    o.append("## Cover\n")
    o.append(f"**Recommended: variant {var}.** {M['cover']['reason']}\n")
    o.append(f"- Files: `{files['9x16']}` (vertical) and `{files['16x9']}` (YouTube)")
    t = ((used or {}).get(var) or {}).get("vertical", {}).get("time_s")
    if t is None and vinfo and isinstance(vinfo.get("vertical"), dict):
        t = vinfo["vertical"].get("time_s")
    if isinstance(t, (int, float)) and not isinstance(t, bool):
        o.append(f"- TikTok: in the cover editor, pick the frame at ~{t:g} s (the frame used in variant {var}).")
    o.append("- YouTube: upload the 16:9 cover as a custom thumbnail. _For Shorts, check whether Studio accepts a custom thumbnail in your case (not verified)._\n")
    o.append("## TikTok\n")
    o.append("Caption (paste all of it):\n\n```text\n" + tiktok_caption(M) + "\n```\n")
    o.append(f"Before \"more\" (~{tt['caption_visible']} characters): {clip(M['tiktok_caption'], tt['caption_visible'])}\n")
    o.append("## YouTube\n")
    o.append("**Recommended title:**\n\n```text\n" + M["titles"][0] + "\n```\n")
    if len(M["titles"]) > 1:
        o.append("Alternatives:\n" + "\n".join(f"- {t}" for t in M["titles"][1:]) + "\n")
    o.append(f"Description (paste all of it; the first {yt['hashtags_above_title']} hashtags may appear above the title, "
             "not verified for Shorts):\n\n```text\n" + youtube_description(M) + "\n```\n")
    o.append(f"Before \"more\" (~{yt['description_visible']} characters): {clip(M['description'], yt['description_visible'])}\n")
    if M.get("youtube_tags"): o.append("Tags (hidden Studio field):\n\n```text\n" + ", ".join(M["youtube_tags"]) + "\n```\n")
    if M.get("pinned_comment"): o.append("Pinned comment:\n\n```text\n" + M["pinned_comment"] + "\n```\n")
    o.append("## Hashtags: why\n\n" + M["hashtags_reason"] + "\n")
    if M.get("notes"): o.append("## Notes\n\n" + M["notes"] + "\n")
    o.append("## Before posting\n\n" + "\n".join(f"- [ ] {c}" for c in P["checklist"]) + "\n")
    return "\n".join(o)


def read_json(path, label, errors):
    try:
        with open(path, encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError) as e:
        errors.append(f"{label} unreadable ({path}): {e}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validates videos/<name>/meta.json and generates publish.md")
    ap.add_argument("--name", required=True, help="folder videos/<name>/ (or absolute path of the folder)")
    ap.add_argument("--video", required=True, help="final mp4 (checks the duration)")
    ap.add_argument("--covers", help="folder with the thumb.py covers (default: videos/<name>/covers)")
    ap.add_argument("--preset", default="presets/publish.json")
    ap.add_argument("--out", help="default: videos/<name>/publish.md")
    a = ap.parse_args(argv)

    vdir = a.name if os.path.isabs(a.name) else os.path.join(ROOT, "videos", a.name)
    name = os.path.basename(os.path.normpath(vdir))
    out = os.path.abspath(a.out) if a.out else os.path.join(vdir, "publish.md")
    covers = a.covers or os.path.join(vdir, "covers")
    mp, tp = os.path.join(vdir, "meta.json"), os.path.join(vdir, "thumb.json")
    errors, warnings = [], []

    P = read_json(a.preset if os.path.isabs(a.preset) else os.path.join(ROOT, a.preset), "preset", errors)
    M = None
    if not os.path.exists(mp):
        errors.append(f"{mp} is missing. Required fields:\n" + "\n".join(f"  - {k}: {v}" for k, v in FIELDS.items())
                      + f"\nOptional: {', '.join(OPTIONAL)}. Rules: .claude/skills/publish-video/SKILL.md")
    else:
        M = read_json(mp, "meta.json", errors)
    thumb = read_json(tp, "thumb.json", errors) if os.path.exists(tp) else None
    dur = None
    try: dur = duration(a.video)
    except ValueError as e: errors.append(str(e))
    if M is not None and P is not None:
        M = nfc(M)
        e2, warnings = validate(M, P, dur, thumb, set(os.listdir(covers)) if os.path.isdir(covers) else None)
        errors += e2

    stale = out + ".stale"
    if errors:
        print("\n".join("ERROR: " + e for e in errors))
        if os.path.exists(out):
            os.replace(out, stale)
            print(f"old {os.path.basename(out)} renamed to {os.path.basename(stale)} (do not use it: it does not match the current meta.json)")
        return 1
    tmp = out + ".tmp"
    used = None
    try:
        with open(os.path.join(covers, "covers.json"), encoding="utf-8") as f: used = json.load(f)
    except (OSError, ValueError): pass
    with open(tmp, "w", encoding="utf-8", newline="\n") as f: f.write(render(name, M, P, dur, thumb, warnings, used))
    os.replace(tmp, out)
    if os.path.exists(stale): os.remove(stale)
    print(f"ok: {out}  ({len(warnings)} warning(s))")
    for x in warnings: print("  WARNING:", x)
    return 0


if __name__ == "__main__":
    sys.exit(main())
