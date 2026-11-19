# video-toolkit

Local tools (ffmpeg + Python) for short vertical videos, spoken in Portuguese or English. The author runs nothing by hand: the agent runs the whole flow and stops at the review checkpoints with them.

- **Edit a video** (new recording, cuts, captions, preview, audio, cover, resuming an edit): skill `edit-video`. It has the order, the review checkpoints and the gotchas.
- **Publishing metadata** (title, description, hashtags, cover): skill `publish-video`.
- **Sound effects** (whoosh, pops, click): skill `sound-effects`. **Animated illustrations** in place of the slide (HyperFrames): skill `illustrations`, when the video lacks visual content or when asked.
- Commands and tool status: `README.md`. Terms (preference, craft rule, author profile): `GLOSSARY.md`.
- **Author profile** (this author's preferences, setup and where their files live): `profile/`, outside git. Each skill names the file it reads. No `profile/` yet: create it with `profile.example/README.md` before the first video.

## Fixed rules
- Everything local and free. No paid API, no sending audio/video out, without an explicit request. (The `.claude/hooks/guard.py` hook blocks the obvious.)
- Media, models and `videos/` (transcripts, cuts, metadata, clips, covers) never go into git: the repo is public. Every output of a video goes to `videos/<name>/`, never to the root. Keep the original recording (`.mov`) until the video is published.
- Manual cut decisions (replace, cut, keep, trim, zoom, blur, lang) go in `videos/<name>/edit.json`, not in `plan.json`: `cuts.py --force` rebuilds the plan.
- Cuts and captions are reviewed with the author. A word you didn't understand: ask, never invent.
- Sort every lesson: a **preference** goes in `profile/` the moment the author decides it, a **craft rule** in the skill's gotchas. The test and the entry format: `profile.example/README.md`.
- Reply to the author in the language they write in. Video outputs (captions, cover texts, metadata) follow the video's spoken language.
- Every video ends with `videos/<name>/publish.md` delivered to the author. Platform limits live in `presets/publish.json`, not in the conversation.
