---
name: illustrations
description: Creates animated illustrations (HTML + GSAP, rendered with HyperFrames) that go in place of the slide in a video-toolkit video. Use when the video lacks visual content (camera only, slide static for too long, a concept hard to picture), when the user asks for an illustration, animation, drawing or "something on screen", or when resuming a video that has videos/<name>/illustration/ (PT: ilustração, animação, desenho, "algo na tela").
---

# Animated illustrations

The illustration is a video the size of the slide panel (882×850, the preset's `layout.slide`) that `render.py --panel`
puts in place of the cropped slide. It follows the speech: each thing appears on the word that names it.

## When to use

- The video lacks visual content: camera only, or a slide static for a long time.
- It was asked for.
- Don't use it just to decorate a video that already has a screen recording with content. When in doubt, propose it and let the author decide.

## Tool

HyperFrames (Apache 2.0, by HeyGen), via `npx hyperframes@0.9.16`, pinned to that version. It runs locally (Node 22+,
ffmpeg, a headless Chrome it downloads itself) and doesn't send the video out. The first time on a machine, run
`npx hyperframes@0.9.16 telemetry disable`. Offline docs: `npx hyperframes@0.9.16 docs <topic>`
(data-attributes, gsap, compositions, rendering).

**Free and unlimited is only the local part:** `init`, `lint`, `snapshot`, `render`, `preview`, `docs`. HeyGen's
account, credits and cloud are paid or send things out, and `guard.py` blocks them: `auth`, `billing`, `cloud`,
`lambda`, `cloudrun`, `publish`, `templates`, `reverse`, `--engine heygen`, and the Pro skills `reverse-any-video`
and `style-sampling`. The HyperFrames Studio app (Free plan with 5 cloud exports a month, paid Pro) is not part of
the flow either. Keep the pinned version: the Apache 2.0 license of 0.9.16 can't be withdrawn.

## Steps

1. **Proposal** (together with the cuts review, step 4 of `edit-video`). Run
   `python3 src/vtk/sfx.py marks --plan videos/<name>/plan.json` to get the times in the final video. Write
   a list: spoken sentence (with its time), what appears, how it comes in. Text, numbers and values on screen are
   content: they are approved like the captions, and written in the video's spoken language. No made-up data
   presented as real.
   👀 Wait for confirmation: approve, cut or change. **Done when** the list is approved.
2. **Project.** In `videos/<name>/illustration/` (outside git):
   `npx hyperframes@0.9.16 init illustration --example blank --non-interactive --skip-skills --resolution square`.
   Then replace `index.html` starting from `presets/illustration/example-spreadsheet.html`, and copy the Poppins
   fonts from `assets/fonts/` to `illustration/assets/`.
3. **Write the animation.** HyperFrames rules: `#root` with `data-composition-id`, `data-start`,
   `data-duration` (= duration of the final video) and `data-width="882" data-height="850"`. Every timed element has
   `class="clip"`, `data-start` and `data-duration`. One paused GSAP timeline in `window.__timelines["main"]`.
   No `Math.random()`, `Date.now()` or fetch. Absolute times, taken from `marks` (the word, not the sentence).
4. **Check.** `npx hyperframes@0.9.16 lint`, then `npx hyperframes@0.9.16 snapshot --at <times>` and **look at
   `contact-sheet.jpg`** before going on. A passing lint doesn't tell how it looks.
5. **Render.** `npx hyperframes@0.9.16 render -o ../illustration.mp4` (~10 s for 20 s of video).
6. **Assemble.** `render.py ... --panel videos/<name>/illustration.mp4` (preview and final). Camera-only video: the
   video preset measures `camera_crop` around the face. `slide_crop` is not used with `--panel`, but must fit in
   the frame. 👀 The preview goes to review as always.

## Style (approved on 2026-11-05, "teste ilustração" video)

- Background `#141B2D` (the same as the video), cards `#1E2740` with border `#2C3757` and 22 px corners.
- Poppins Bold and ExtraBold. Highlight in orange `#F5A623` (the same as the captions and the slide badge). Green
  `#3DDC84` for "it worked", red `#FF5A4F` for error or anger.
- Characters and reactions: Microsoft's Fluent Emoji 3D (MIT), downloaded from
  `https://raw.githubusercontent.com/microsoft/fluentui-emoji/main/assets/<Name>/3D/<name>_3d.png` (with skin tone:
  `<Name>/Default/3D/<name>_3d_default.png`). Don't draw faces in SVG by hand: it looked ugly and was rejected.
- Short entrances (0.3–0.5 s, `back.out`), one element at a time, nothing moving while the author explains something
  else. Shaking only for anger or error.

## Gotchas

- **Appearing too early.** The element comes in on the word that names it, not at the start of the sentence. In
  the test, the spreadsheet came in on "work" and the review caught it: it should have been on "spreadsheet".
- **Sound effect with it.** If the illustration has a strong moment (something appears, someone shouts), pair it
  with the `sound-effects` skill at the same time. Minimum 3.5 s between effects.
- **The illustration follows the final video.** If the cuts change later (`cuts.py --force`), the times change: run
  `marks` again and adjust the timeline before rendering.
- GSAP comes from a CDN at render time (the example HTML uses jsDelivr). Without internet, download `gsap.min.js` to
  `illustration/assets/` and point to it.
