# Author profile (template)

`profile/` holds one author's **preferences**: choices that are right for them and could be wrong for another
author. It lives outside git, one per clone. This folder is its template: the same four files, each saying what
goes in it.

| File | Part |
|------|------|
| `voice.md` | voice treatment, and the mic and room facts behind it |
| `brand.md` | how the videos look and sound |
| `channel.md` | audience, tone, hashtags, calls to action |
| `recording.md` | setup and habits on camera, where files live |

The spoken language is not a preference: the toolkit supports Portuguese and English and detects it per video.

## Creating it (no `profile/` yet)

1. Copy this folder to `profile/` and drop this README from the copy.
2. Ask the author only what the first video needs: where the recording is and where the finished files go, and who
   the channel is for. Write the answers in `recording.md` and `channel.md`.
3. Leave every other section empty. An empty section means the toolkit's **default** applies.

**Done when** `profile/` exists with those answers, before step 2 of the `edit-video` skill.

## Filling it over time

Sort every lesson with one test: would it still be true with a different author, voice, room and mic? Then it is a
**craft rule** and goes in the skill's gotchas. Otherwise it is a preference and goes here, in the file and section
it belongs to, the moment the author decides it (usually at a review checkpoint):

```md
- **<what>**: <the choice, with the values to reuse>. <decided | testing | rejected>, <YYYY-MM-DD>, video "<name>".
  <the author's reason, in their words when they gave one>
```

- **decided**: apply it on every video.
- **testing**: apply it and offer the comparison again until the author decides.
- **rejected**: the author heard it and turned it down. Keep it, so it is never proposed again.

A **setup fact** (measured or observed, not chosen: levels, framing, where a window sits) has no status, only when
it was seen: `seen <YYYY-MM-DD>, video "<name>"`.
