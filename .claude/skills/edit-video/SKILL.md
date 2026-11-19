---
name: edit-video
description: The agent's playbook for editing a video-toolkit video, from the recording (.mov) to publish.md, for videos spoken in Portuguese or English. Use when a new recording arrives or the user asks to cut, caption, render, preview, fix the audio, make a cover or resume an edit (PT: editar vídeo, gravação nova, cortar, legendar, renderizar, prévia, áudio, capa, retomar a edição).
---

# Edit a video (recording → publish.md)

The author runs nothing: you run everything and stop at the **review checkpoints** (marked 👀) for them to decide. Exact commands and flags: the "Flow" block of `README.md` (read it before starting). This skill gives the order, when a step is done and the gotchas the code doesn't tell.

`<name>` is a short nickname for the video (e.g. `instructions`). Every output goes to `videos/<name>/` (outside git). The original stays in the video's files folder given in `profile/recording.md`; with no folder there, ask where it is.

**Author profile.** Before step 2, read `profile/recording.md` (setup, habits on camera, files), `profile/voice.md` (voice treatment) and `profile/brand.md` ("Look" for the preset, "Covers" for step 7). Their entries override this skill's defaults. No `profile/` yet: create it first (`profile.example/README.md`).

**Languages.** Talk to the author in the language the author writes in. Captions, cover texts (`thumb.json`) and metadata are in the video's spoken language (`pt` or `en`, `"lang"` in `transcript.json`).

## Steps

1. **Environment.** Python packages live in `.venv/` in the project, not in the system Python: in every command of this flow and of the other skills, use `.venv/bin/python` instead of `python3` (each shell call starts without the environment activated). Check `ffmpeg -version`, `ffprobe -version` and `.venv/bin/python -c "import PIL, numpy, sherpa_onnx, mediapipe"`, and the models `models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8/` and `models/face_landmarker.task` (how to download: README, "Transcription model"). Without `.venv/`: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` (ffmpeg: `brew install ffmpeg` on a Mac, `sudo apt install ffmpeg python3-venv` on Debian/Ubuntu) and say what you installed. **Done when** the four commands run without error.

2. **Video preset.** Extract frames from the recording (e.g. 5 s, 30 s, middle, end) and look at each one. Measure the camera window and the slide/screen panel (`width, height, x, y` in recording pixels) and the resolution. Write `videos/<name>/preset.json` with only what changes:
   `{"base": "presets/tiktok-vertical.json", "source": {"w": .., "h": .., "camera_crop": [..], "slide_crop": [..]}}`.
   An old preset copied whole (with `fontsdir` `/usr/share/...`) no longer runs: convert it to this format. **Done when** a 1-segment preview (step 5) shows face and screen whole, with no black border or crop.

3. **Transcribe** (`transcribe_words.py --video ... --name <name>`) and read the whole `transcript.txt`. Note wrong terms (Parakeet turns "IA" into "Ya", tool names). Check the detected language (printed as `language: ...` and in `"lang"` of `transcript.json`): if it is wrong or missing (`null`: short text, mixed speech), set `"lang"` in `edit.json`. **Done when** you read everything, the language is right, and you have the list of fixes and of words you didn't understand.

4. **Cuts.** Put the decisions in `videos/<name>/edit.json`, the single source of manual decisions: `replace` (caption fixes, works with several words), `cut`, `keep`, `trim`, `zoom`, `blur`, `lang`, `jcut` (keys and format: docstring of `src/vtk/cuts.py`). Run `cuts.py --video ... --name <name>`.
   - Check the `Language:` line at the top of `edit-plan.md` (language, why, filler list used). Wrong: set `"lang"` in `edit.json` and run again with `--force`.
   - **Portuguese retakes** (a spoken cue to start over, or a restarted sentence) are not detected by the engine (only English retake cues are): find them in the transcript, using the author's own cues in `profile/recording.md`, and remove them with `cut`.
   - **Sensitive data on screen** (chat titles, e-mails, client names, tabs): look at frames of the screen area throughout the video and cover it with `blur` (times and pixels of the original recording).
   - Zoom stays off; only if the author finds the jump cuts abrupt.
   - 👀 **Review 1:** show `edit-plan.md` (what was removed and why, warnings, possible retakes) and the caption text. A word you didn't understand: ask, never invent. Adjust `edit.json` and run again with `--force` until approved.
   - In the same review, propose the **sound effects** (skill `sound-effects`, `videos/<name>/sfx.json`) and, if the video lacks visual content or when asked, the **illustrations** (skill `illustrations`). Each item with the sentence where it goes.
   - Right after approval, write `meta.json` (skill `publish-video`).
   - **J-cuts** (the next piece's voice starts before its picture; see the gotcha), if `profile/brand.md` uses them:
     pick joins from "J-cut candidates" in `edit-plan.md`, put them in `"jcut"` in `edit.json` (just `[t]`: length and
     area are chosen per join; if `profile/brand.md` says only the camera or only the slide waits, write that area
     in each item: `[t, "camera"]`) and run again with `--force`. They are judged on the preview, not in this table.
   **Done when** cuts and captions are approved.

5. **Preview** (`render.py ... --out videos/<name>/render_prev --scale 0.5 --crf 30`, plus `--panel videos/<name>/illustration.mp4` if there is an illustration). It comes out at `render_prev/final.mov`. Look at a few frames (blur in place, caption whole inside the screen, face framed; inside each J-cut lead, a closed mouth). 👀 **Review 2:** give the preview path so it can be watched with headphones, with the time of each J-cut (`sfx.py marks` prints them) so the author judges each one. **Done when** the preview is approved; changes go back to `edit.json` (step 4).

6. **Final.** `render.py` without `--scale`, into `videos/<name>/render`. Then `postaudio.py --preset videos/<name>/preset.json --in videos/<name>/render/final.mov --out videos/<name>/final.mp4` (with `--sfx videos/<name>/sfx.json` if there are effects). **Done when** `postaudio.py` ends with `ok` (-14 LUFS, peak ≤ -1.5 dBTP, `normalization_type=linear`).

7. **Cover.** `face.py --video videos/<name>/final.mp4 --name <name>` and look at `face_candidates.jpg`. Write `thumb.json` (following `profile/brand.md` "Covers", texts in the video's language, `"time_s": "auto"` and `"face_x": "auto"` in the variants) and run `thumb.py`. 👀 **Review 3:** show the covers in `videos/<name>/covers/` and wait for the variant choice: update `cover` in `meta.json` (without "PROVISIONAL"). **Done when** the cover is chosen.

8. **Publish.** Run `publish.py --name <name> --video videos/<name>/final.mp4` until it exits without `ERROR`. If `profile/recording.md` gives a files folder for the video, copy `final.mp4`, the covers (`covers/`) and `publish.md` there, under the file names it gives. **Done when** the files are copied (if there is a folder) and you delivered `publish.md`.

## Gotchas

- **A script error is to be read and its cause fixed**, not worked around. Crop outside the frame, resolution different from the preset's, missing font, audio off target, unsupported or undetected language: all stop the script on purpose.
- **Redoing is running the same command.** `render.py` resumes where it stopped and redoes only the clips whose segment, preset or option changed. If the shell kills long processes, run in stages with `--budget`.
- **The original `.mov` stays until the video is published** (the hook blocks deleting it or moving it to the trash). Your own test files: use `.mp4` or `.mkv`.
- **`plan.json` is generated.** Hand edits to it are lost on the next `--force` (the previous one goes to `plan.json.bak`). Every decision goes in `edit.json`.
- **The cover uses the final video at 1080×1920**, and so does `face.py`: run both on `final.mp4`, not on the preview.
- **The caption highlights the spoken word** using `"wt"` from `plan.json` (start of each word). It is generated by `cuts.py`; an old plan without `"wt"` or a `replace` that changes the word count still works, with the time estimated from word length (it can be slightly off: check it in the preview).
- **A piece that starts right after a hand `cut` can keep the tail of the cut word** (Parakeet's word end comes before the sound fades: a "-o" was audible on the "fluxo-de-trabalho" video). When the author hears a leftover syllable, measure the level around the join (RMS in 20 ms windows) and add a `trim` up to the silence before the next kept word, leaving ~0.05 s before its onset.
- **Opening without speech (an entrance before the first word):** the engine drops everything before the first
  word. If `profile/recording.md` lists an entrance, look for it on every video. `"intro": t` in `edit.json` opens the video raw at `t`; leave ~0.3–0.4 s of empty frame before the
  author shows up *inside the camera crop* (with a tight crop they appear later than in the full frame).
- **Last words missing from the transcript:** Parakeet can drop the final words (on "grilling" it turned "eles ficam
  melhores" into "é que você ficou", ending 0.7 s early) and the last piece then cuts the speech. Measure the RMS
  after the last word; if there is speech, `"outro": t` ends the video there and `replace` fixes the caption.
- **Camera-only recording:** the face moves as the author leans in and back. Measure `camera_crop` on frames from
  the whole video, not only the first ones, or the crop cuts the chin.
- **Voice treatment:** `audio.eq` (`[[lowshelf|highshelf|peak, Hz, dB, q], ...]`) and `audio.exciter` (synthetic
  air) in the video preset. Default: the voice untouched. The author's treatment is in `profile/voice.md`: copy its
  values into the video's `preset.json`, and when its status is *testing*, offer the comparison again. Craft rules,
  true for any voice:
  - Compare variants as *full previews*: in 13 s samples the variants sound the same.
  - Keep pitch natural: pitch shifting (asetrate + atempo) sounds awful.
  - One low-end move is enough: adding density (a low-mid boost) on top of an EQ that already warms the voice
    muddies it.
- **J-cut (split edit):** at a join, the next piece's voice starts before its picture; the picture of the piece
  before runs on into footage the cut removed. Sound never moves; only the picture edit point does
  (`src/vtk/jcut.py`, `"j"` in `plan.json`). Craft rules, true for any author:
  - Only over a removed **silence** at a sentence end. Over a removed filler or retake the borrowed footage shows the
    mouth forming other words, which reads as a dubbing error. `cuts.py` refuses those joins.
  - **Silence in the audio is not a closed mouth.** On the first test, 4 of 6 "silent" joins had the mouth opening
    before the next word (getting ready to speak). `cuts.py` measures the mouth (MediaPipe) and caps the lead there;
    without MediaPipe a camera J-cut is refused.
  - **Length is measured as voice-before-picture, from the next piece's first word**, not from the cut: the engine
    already leaves a beat of silence there, so a lead measured from the cut is mostly silence and looks like a hard
    cut. Pick it per join: ~0.25 s at a normal sentence end (continuity without calling attention), ~0.6 s only at a
    topic change (`cuts.py` uses a 3 s speech gap, like the engine's long_gap) and only when the mouth stays closed
    for all of it; otherwise fall back to 0.25 s; under 0.2 s skip the join (no frozen frame). `cuts.py` makes this
    choice when `"jcut"` gives only `[t]`; a length in `edit.json` overrides it.
  - **When the slide changes at the join and the next words point at the screen** ("olha", "look"), the screen must
    change with the voice: only the camera waits (`"camera"`). `cuts.py` picks that from `pointing_words` in
    `presets/fillers-<lang>.json`.
  - **Not too often:** at most one J-cut every ~10 s of final video, or the device shows. Candidates keep that
    spacing; J-cuts asked for closer together get a warning.
  - One transition per join: a J-cut takes no whoosh or zoom punch-in on the same join (`cuts.py` warns about the
    zoom, `sfx.py check --plan` refuses the whoosh). A join that doesn't end a sentence is skipped.
  - Approve J-cuts on the preview, never from `edit-plan.md`: nobody can judge one from a table.
- **A new cut technique (L-cut, a new transition...) gets a variant render watched by the author before it gets
  code:** `variants.py` renders one join N ways (hard cut, punch-in, J/L-cut lengths) and checks they have the same
  length. A join is judged on its ~6 s excerpt; a voice treatment still needs full previews (above).
- **Temporary files of yours:** `.mkv`/`.mp4`, never `.mov` (the guard blocks `rm` on any `.mov`).
- **Changed a toolkit script?** Run `.venv/bin/python -m unittest discover tests` before going on.
