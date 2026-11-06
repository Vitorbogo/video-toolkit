---
name: edit-video
description: The agent's playbook for editing a video-toolkit video, from the recording (.mov) to publish.md, for videos spoken in Portuguese or English. Use when a new recording arrives or the user asks to cut, caption, render, preview, fix the audio, make a cover or resume an edit (PT: editar vídeo, gravação nova, cortar, legendar, renderizar, prévia, áudio, capa, retomar a edição).
---

# Edit a video (recording → publish.md)

The author runs nothing: you run everything and stop at the **review checkpoints** (marked 👀) for them to decide. Exact commands and flags: the "Flow" block of `README.md` (read it before starting). This skill gives the order, when a step is done and the gotchas the code doesn't tell.

`<name>` is a short nickname for the video (e.g. `instructions`). Every output goes to `videos/<name>/` (outside git). The original stays in the video's files folder given in `CLAUDE.local.md`; without it, ask where it is.

**Languages.** Talk to the author in the language the author writes in. Captions, cover texts (`thumb.json`) and metadata are in the video's spoken language (`pt` or `en`, `"lang"` in `transcript.json`).

## Steps

1. **Environment.** Python packages live in `.venv/` in the project, not in the system Python: in every command of this flow and of the other skills, use `.venv/bin/python` instead of `python3` (each shell call starts without the environment activated). Check `ffmpeg -version`, `ffprobe -version` and `.venv/bin/python -c "import PIL, numpy, sherpa_onnx, mediapipe"`, and the models `models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8/` and `models/face_landmarker.task` (how to download: README, "Transcription model"). Without `.venv/`: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` (on a Mac, ffmpeg with `brew install ffmpeg`) and say what you installed. **Done when** the four commands run without error.

2. **Video preset.** Extract frames from the recording (e.g. 5 s, 30 s, middle, end) and look at each one. Measure the camera window and the slide/screen panel (`width, height, x, y` in recording pixels) and the resolution. Write `videos/<name>/preset.json` with only what changes:
   `{"base": "presets/tiktok-vertical.json", "source": {"w": .., "h": .., "camera_crop": [..], "slide_crop": [..]}}`.
   An old preset copied whole (with `fontsdir` `/usr/share/...`) no longer runs: convert it to this format. **Done when** a 1-segment preview (step 5) shows face and screen whole, with no black border or crop.

3. **Transcribe** (`transcribe_words.py --video ... --name <name>`) and read the whole `transcript.txt`. Note wrong terms (Parakeet turns "IA" into "Ya", tool names). Check the detected language (printed as `language: ...` and in `"lang"` of `transcript.json`): if it is wrong or missing (`null`: short text, mixed speech), set `"lang"` in `edit.json`. **Done when** you read everything, the language is right, and you have the list of fixes and of words you didn't understand.

4. **Cuts.** Put the decisions in `videos/<name>/edit.json`, the single source of manual decisions: `replace` (caption fixes, works with several words), `cut`, `keep`, `trim`, `zoom`, `blur`, `lang` (keys and format: docstring of `src/vtk/cuts.py`). Run `cuts.py --video ... --name <name>`.
   - Check the `Language:` line at the top of `edit-plan.md` (language, why, filler list used). Wrong: set `"lang"` in `edit.json` and run again with `--force`.
   - **Portuguese retakes** ("deixa eu falar de novo", restarting a sentence) are not detected by the engine (only English retake cues are): find them in the transcript and remove them with `cut`.
   - **Sensitive data on screen** (chat titles, e-mails, client names, tabs): look at frames of the screen area throughout the video and cover it with `blur` (times and pixels of the original recording).
   - Zoom stays off; only if the author finds the jump cuts abrupt.
   - 👀 **Review 1:** show `edit-plan.md` (what was removed and why, warnings, possible retakes) and the caption text. A word you didn't understand: ask, never invent. Adjust `edit.json` and run again with `--force` until approved.
   - In the same review, propose the **sound effects** (skill `sound-effects`, `videos/<name>/sfx.json`) and, if the video lacks visual content or when asked, the **illustrations** (skill `illustrations`). Each item with the sentence where it goes.
   - Right after approval, write `meta.json` (skill `publish-video`).
   **Done when** cuts and captions are approved.

5. **Preview** (`render.py ... --out videos/<name>/render_prev --scale 0.5 --crf 30`, plus `--panel videos/<name>/illustration.mp4` if there is an illustration). It comes out at `render_prev/final.mov`. Look at a few frames (blur in place, caption whole inside the screen, face framed). 👀 **Review 2:** give the preview path so it can be watched with headphones. **Done when** the preview is approved; changes go back to `edit.json` (step 4).

6. **Final.** `render.py` without `--scale`, into `videos/<name>/render`. Then `postaudio.py --preset videos/<name>/preset.json --in videos/<name>/render/final.mov --out videos/<name>/final.mp4` (with `--sfx videos/<name>/sfx.json` if there are effects). **Done when** `postaudio.py` ends with `ok` (-14 LUFS, peak ≤ -1.5 dBTP, `normalization_type=linear`).

7. **Cover.** `face.py --video videos/<name>/final.mp4 --name <name>` and look at `face_candidates.jpg`. Write `thumb.json` (texts in the video's language, `"time_s": "auto"` and `"face_x": "auto"` in the variants) and run `thumb.py`. 👀 **Review 3:** show the covers in `videos/<name>/covers/` and wait for the variant choice: update `cover` in `meta.json` (without "PROVISIONAL"). **Done when** the cover is chosen.

8. **Publish.** Run `publish.py --name <name> --video videos/<name>/final.mp4` until it exits without `ERROR`. If `CLAUDE.local.md` gives a files folder for the video, copy `final.mp4`, the covers (`covers/`) and `publish.md` there, under the file names `CLAUDE.local.md` gives. **Done when** the files are copied (if there is a folder) and you delivered `publish.md`.

## Gotchas

- **A script error is to be read and its cause fixed**, not worked around. Crop outside the frame, resolution different from the preset's, missing font, audio off target, unsupported or undetected language: all stop the script on purpose.
- **Redoing is running the same command.** `render.py` resumes where it stopped and redoes only the clips whose segment, preset or option changed. If the shell kills long processes, run in stages with `--budget`.
- **The original `.mov` stays until the video is published** (the hook blocks deleting it or moving it to the trash). Your own test files: use `.mp4` or `.mkv`.
- **`plan.json` is generated.** Hand edits to it are lost on the next `--force` (the previous one goes to `plan.json.bak`). Every decision goes in `edit.json`.
- **The cover uses the final video at 1080×1920**, and so does `face.py`: run both on `final.mp4`, not on the preview.
- **The caption highlights the spoken word** using `"wt"` from `plan.json` (start of each word). It is generated by `cuts.py`; an old plan without `"wt"` or a `replace` that changes the word count still works, with the time estimated from word length (it can be slightly off: check it in the preview).
- **Changed a toolkit script?** Run `.venv/bin/python -m unittest discover tests` before going on.
