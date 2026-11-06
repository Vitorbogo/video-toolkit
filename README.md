# video-toolkit

A local, free toolkit (ffmpeg + Python) that turns a screen + camera recording into a captioned vertical short
(TikTok, YouTube Shorts): cuts fillers and pauses, draws word-by-word captions, levels the audio, makes covers and
writes the publishing metadata. A Claude Code agent runs the whole flow and stops at review checkpoints with the
author. Works for videos spoken in Portuguese or English. Nothing leaves the machine and no paid API is used. Each
author's context (folders, audience, content decisions) lives in a `CLAUDE.local.md` outside git.

## Layout

| Folder | What it holds |
|--------|---------------|
| `src/vtk/` | Our scripts: `engine.py` (cut engine: per-word timing, fillers, repeats, punch-ins; started as a copy of the dev-video-editing skill, MIT, see `THIRD_PARTY_LICENSES.md`), `transcribe_words.py` (per-word timing, free), `cuts.py` (cuts through `engine.py` → `plan.json`), `lang.py` (spoken language: presets and detection), `render.py` (captions drawn by `captions.py`), `postaudio.py` (sound effects with `--sfx`), `sfx.py` (sound effect library and per-video list), `face.py` (frames with a neutral face for the cover), `thumb.py`, `publish.py` (publishing metadata), `preset.py` (loads a preset with inheritance). |
| `models/` | Transcription (487 MB) and face (3.7 MB) models, **outside git**. See below. |
| `presets/` | Per-format parameters (layout, cuts, captions, audio, image), covers (`thumbnail.json`), fillers per language (`fillers-pt.json`, `fillers-en.json`), platform limits (`publish.json`) and the illustration example (`illustration/`). |
| `assets/fonts/` | Poppins (captions and covers, SIL OFL 1.1, `OFL-Poppins.txt`). |
| `sfx/` | Short sound effects (whoosh, pops, click), **generated** by `src/vtk/sfx.py generate`. The only `.wav` files in git. |
| `tests/` | Tests (`python3 -m unittest discover tests`; the ones that need ffmpeg or the model are skipped without them). |
| `.claude/` | `skills/edit-video` (the agent's playbook: recording → `publish.md`, with the review checkpoints), `skills/publish-video` (how to write the metadata), `skills/sound-effects` (where each effect goes), `skills/illustrations` (animations in place of the slide, with HyperFrames) and `hooks/guard.py` (blocks media in git, deleting/moving a `.mov`, sending media out, paid APIs, paid or cloud HyperFrames commands, the third-party skill's `transcribe.py` without `--engine local`, `upload_parts.py`). |
| `videos/<name>/` | **Everything for each video**: transcript, `edit.json`, `plan.json`, `preset.json`, clips (`render/`), final video, covers (`covers/`), `meta.json`, `publish.md`. **Outside git** (the repo is public and the content must not leak before the video is out). |

Requirements: `ffmpeg` (with `ffprobe`), Python 3 with `Pillow`, `numpy`, `sherpa-onnx` and `mediapipe` (only for `face.py`).
The Python packages live in a project environment, `.venv/` (outside git):
`python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`. In the commands below, `python3` is that
environment's: run `source .venv/bin/activate` first, or replace `python3` with `.venv/bin/python`.

## Flow

```bash
# 0. per-video preset: only what changes (crops measured on a frame of the recording); the rest comes from the base
#    videos/<name>/preset.json = {"base": "presets/tiktok-vertical.json",
#                                 "source": {"w": 2940, "h": 1612, "camera_crop": [...], "slide_crop": [...]}}
#    render.py stops with an error if the recording has another resolution or a crop falls outside the frame
# 1. transcribe with per-word timing (free, local): audio, silences and windows are handled inside the script
python3 src/vtk/transcribe_words.py --video RECORDING.mov --name <name>   # videos/<name>/transcript.json + .txt
#    (--audio x.wav instead of --video; --out DIR instead of --name; --model-dir if the model is not in models/)
#    transcript.json gets "lang" (spoken language detected from the words; null when it can't tell)
# 2. cuts decided by engine.py (the language's fillers, shortened pauses, edges from the audio) -> draft
#    plan.json + edit-plan.md. Review cuts and captions with the author.
python3 src/vtk/cuts.py --video RECORDING.mov --name <name> [--lang pt|en] [--zoom] [--no-scenes] [--force]
#    reads videos/<name>/transcript.json, edit.json and preset.json by default (if they exist)
#    adjustments in videos/<name>/edit.json, with times of the original recording (they survive --force):
#      cut [[a, b, "note"]]          removes the words in the range (warns if it catches none)
#      keep [[a, b]]                 protects the range
#      trim [[a, b, "note"]]         removes the raw range, even without words (long pause, noise)
#      replace {"chat GPT": "ChatGPT"} fixes the caption (works with more than one word)
#      zoom [[t, 1.1]]               zoom on the camera only, in the piece that contains t (max 1.2; 1 removes it)
#      blur [[t0, t1, x, y, w, h, "note"]] blurs the box (recording pixels) between t0 and t1
#      lang "en"                     spoken language, when detection gets it wrong or can't tell
#      style, pauses, extra_fillers  engine.py keys
#    zoom is optional and off: only if the jump cuts feel abrupt (--zoom suggests, edit.json decides)
#    --no-scenes ignores slide changes when placing cuts
#    --force rebuilds plan.json (the previous one goes to plan.json.bak); captions edited directly in plan.json are lost
#    plan.json keeps in "wt" the start of each word: the caption highlights the spoken word (text changed by
#    a replace with a different word count falls back to an estimate from word length)
# 2b. sound effects (skill sound-effects): videos/<name>/sfx.json, reviewed together with the cuts
python3 src/vtk/sfx.py marks --plan videos/<name>/plan.json     # times in the final video, to pick the moments
python3 src/vtk/sfx.py check --sfx videos/<name>/sfx.json --plan videos/<name>/plan.json
# 2c. illustrations (skill illustrations), only when the video lacks visual content or when asked
# 3. preview and final: resumes where it stopped and redoes only the clips whose segment, preset or options changed
#    output: render/c00.mov... (PCM audio, no drift at the joins), render/list.txt and, when all are ready, render/final.mov
python3 src/vtk/render.py --preset videos/<name>/preset.json --video RECORDING.mov \
  --plan videos/<name>/plan.json --out videos/<name>/render_prev --scale 0.5 --crf 30
python3 src/vtk/render.py --preset videos/<name>/preset.json --video RECORDING.mov \
  --plan videos/<name>/plan.json --out videos/<name>/render
#    (+ --panel videos/<name>/illustration.mp4 with an illustration; --budget S limits the time per run)
# 4. audio: fixed filters + automatic pre-limiter + LINEAR loudnorm in 2 passes (-14 LUFS, peak <= -1.5 dBTP
#    measured on the result; off target it exits with an error). Noise reduction off in the preset (robotic voice)
python3 src/vtk/postaudio.py --preset videos/<name>/preset.json --in videos/<name>/render/final.mov --out videos/<name>/final.mp4 \
  [--sfx videos/<name>/sfx.json]
# 5. covers. First the frames with a neutral face (eyes open, mouth closed, head straight, sharp image), in ~3 s:
python3 src/vtk/face.py --video videos/<name>/final.mp4 --name <name>   # face.json + face_candidates.jpg (check it)
#    in thumb.json: "time_s": "auto" (variant A = 1st candidate, B = 2nd...) or "auto:3"; "face_x": "auto" centres
#    the 16:9 on the face. Score weights in presets/thumbnail.json ("neutral"). A fixed number in time_s still works.
#    covers -> videos/<name>/covers/ (default). Each format and variant can have its own frame and texts:
#    "youtube": {"title": .., "highlight": ..} in thumb.json; --only vertical|youtube generates one format only
python3 src/vtk/thumb.py --video videos/<name>/final.mp4 --spec videos/<name>/thumb.json
python3 src/vtk/thumb.py --video videos/<name>/final.mp4 --spec videos/<name>/thumb.json --sheet 5,20,40,62,95  # candidate sheet
# 6. publishing: checks platform limits and generates videos/<name>/publish.md (titles, description, caption, hashtags, cover)
#    meta.json is written by Claude (skill publish-video) right after the plan.json review, with the cover
#    PROVISIONAL; after thumb.py, pick the cover and update it. On ERROR nothing is generated (the old one becomes .stale)
python3 src/vtk/publish.py --name <name> --video videos/<name>/final.mp4   # covers read from videos/<name>/covers
```

Camera image: `--camera-filter off|natural` in `render.py` (default from the preset).

## Languages

Supported spoken languages: Portuguese (`pt`) and English (`en`). The language picks the filler preset
(`presets/fillers-<lang>.json`): hesitations always cut, crutch words cut next to a comma, words a caption line
should not end on, and where a caption line breaks naturally.

- `transcribe_words.py` detects the language from the transcript words and writes it as `"lang"` in
  `transcript.json` (`null` when it can't tell). The transcription model (Parakeet TDT v3) is multilingual but
  does not report the language: detection is `src/vtk/lang.py`, local and deterministic (it counts each
  language's function words).
- `cuts.py` uses, in this order: `--lang` > `"lang"` in `edit.json` > `"lang"` in `transcript.json` > detection.
  Unsupported or undetectable language: it stops with an error asking for `"lang"` in `edit.json`. The choice and
  why are on the `Language:` line at the top of `edit-plan.md`.
- `meta.json` takes an optional `"lang"` (shown in the `publish.md` header). Captions, cover texts and metadata
  follow the video's spoken language.

Limits:
- Short text (few function words) is not detected: set `"lang"` in `edit.json`.
- Detection only chooses among the supported languages: a video in another language may come out as the closest one.
- Mixed speech (both languages in one video) is not detected as either: set `"lang"` to the main one.
- Retake cues ("let me start over"...) are detected by the engine only in English. Portuguese retakes ("deixa eu
  falar de novo") go in `cut` by hand during review.

Adding a language: create `presets/fillers-<code>.json` (two-letter code) with `fillers`, `extra_fillers`,
`short_words`, `break_before` and `function_words` (see the `_note` in `fillers-en.json` for what each one means
and what to leave out), and add cases to `tests/test_fillers.py`. Nothing else changes: `lang.py` finds the
presets by file name. The language must be one Parakeet TDT v3 transcribes.

## Status (v0.2)

- [x] 9:16 layout (face, slide, captions) from a preset; per-video preset inherits from the base (`"base"`)
- [x] Deterministic 2-pass audio, -14 LUFS (1st video, old chain: -14.05 LUFS, -1.36 dBTP)
- [x] New audio chain as default: no noise reduction (`afftdn` made the voice robotic), 2:1 compressor, automatic pre-limiter (loudnorm always linear) and peak headroom for AAC. Measured on synthetic speech with plosives: -14.1 LUFS, -2.2 dBTP, linear. Accepted without a measurement on a real video (2026-11-06)
- [x] Light camera image treatment (optional)
- [x] Deterministic 9:16 and 16:9 covers (`thumb.py`), with their own frame and texts per format; text shrinks to fit
- [x] Cover with a neutral expression: `face.py` scores each frame (MediaPipe, local) against the resting face of the video itself; `thumb.json` uses `"auto"`
- [x] Cut engine as our own code (`engine.py`, derived from the dev-video-editing skill)
- [x] `engine.py` wired to `render.py` through `cuts.py` (used on the "especialista" and "instrucoes" videos)
  - Our decision on top of the original engine: it leaves a "breath" in place of the removed filler, and a bit of its sound stayed audible. `cuts.py` removes that bit too, but doesn't cut if the join would be shorter than 0.12 s or leave a piece with less than 0.4 s of speech (the word goes back to the caption). `edit-plan.md` is rebuilt from the final pieces
- [x] Portuguese filler list (`presets/fillers-pt.json`, applied by `cuts.py`)
- [x] English support: `presets/fillers-en.json`, language detection (`lang.py`) and `"lang"` override. Covered by tests; not yet used on a real English video
- [x] Short pauses instead of deleted ones (the engine shortens them to a breath)
- [x] Joins without audio drift: clips with PCM audio and an exact frame duration, joined by `render.py` itself
- [x] Blur a region over a time range (`blur` in `edit.json`), to hide data on screen
- [x] Light zoom on the camera only, **optional** (`cuts.py --zoom` suggests, `zoom` in `edit.json` decides; `render.py` applies it). Accepted without running on a real video (2026-11-06)
- [ ] Join check image (the `engine.py` `cut_sheet` could be used on our final)
- [x] Captions drawn with Pillow (Homebrew's ffmpeg has no libass): whole sentence, spoken word in orange (style chosen on 2026-11-05)
- [x] Generated sound effects (`sfx/`), per-video list (`sfx.json`), mixed in `postaudio.py --sfx`. Tested on segments; accepted without a full video (2026-11-06)
- [ ] Illustrations with HyperFrames (skill `illustrations`). Tested on the "teste ilustração" video (2026-11-05); already goes in through `render.py --panel`. Not yet used on a full video
- [x] Transcription with per-word timing, free and local (`transcribe_words.py`, Parakeet TDT v3; gets terms wrong, e.g. "IA" → "Ya": review the text). Long windows split at the quietest point, no duplicated word; word end aligned to the silence
- [x] Model kept in `models/` (ignored by git)

## Transcription model

`models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8/` (487 MB, not in git). To download again: release `asr-models` of
`github.com/k2-fsa/sherpa-onnx`, file `sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2`, extracted into `models/`.
Needs `sherpa-onnx` and `numpy` (in `.venv/`, from `requirements.txt`). No API key, no audio sent out.

Face (for `face.py`): `models/face_landmarker.task` (3.7 MB, Apache 2.0, not in git), from
`https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task`.
Needs `mediapipe` (in `.venv/`, from `requirements.txt`). Runs locally; the video never leaves the machine.

## Licenses

See `THIRD_PARTY_LICENSES.md`.
