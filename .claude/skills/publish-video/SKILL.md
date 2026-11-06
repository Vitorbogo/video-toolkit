---
name: publish-video
description: Writes the titles, description, TikTok caption, hashtags and cover recommendation of a video-toolkit video (videos/<name>/meta.json), in the video's spoken language, and generates publish.md. Use when a video's plan.json has been reviewed, when the final video/covers are generated, or when the user asks for a title, description, hashtags or "everything to post" (PT: título, descrição, legenda, hashtags, publicar, "tudo para postar").
---

# Publishing metadata

Goal: the author reaches the end of the edit and only copies and pastes. No researching platform rules again.

## When
- **Write `meta.json` right after reviewing `plan.json` with the author** (the `cuts.py` draft doesn't have the fixed captions yet; after the review the content is fresh). Don't wait for the render.
  The cover doesn't exist yet at that point (`thumb.json` depends on the final video): write `"cover": {"variant": "A", "reason": "PROVISIONAL: ..."}`.
- **After `thumb.py`**, look at the covers in `videos/<name>/covers/`, pick the `thumb.json` variant and rewrite `cover` (without "PROVISIONAL").
- **Run `publish.py` after `postaudio.py` and `thumb.py`**, with the final mp4. Covers are read from `videos/<name>/covers/` (or `--covers`).

```bash
python3 src/vtk/publish.py --name <name> --video <final mp4, after postaudio.py>
```
It gives `ERROR` (and nothing is generated; an old `publish.md` becomes `publish.md.stale`) if: a field is missing or has the wrong type, a platform limit is exceeded, there is a `#hashtag` in the title/description/caption, the cover is `PROVISIONAL`, the variant doesn't exist in `thumb.json` or its files are not in `covers/`, `lang` is not a two-letter lowercase code, the video doesn't exist or has no readable duration. Fix `meta.json` and run again. Don't edit `publish.md` by hand (it is regenerated). The limits live in `presets/publish.json`, not here.

## Format of `videos/<name>/meta.json`
```json
{
  "titles": ["recommended", "alternative 1", "alternative 2"],
  "description": "text without hashtags",
  "tiktok_caption": "text without hashtags",
  "hashtags": { "tiktok": ["#Broad", "#OnTopic"], "youtube": ["#Broad", "#OnTopic"] },
  "hashtags_reason": "1 sentence",
  "cover": { "variant": "A", "reason": "1 sentence" },
  "lang": "en",
  "youtube_tags": ["optional"],
  "pinned_comment": "optional",
  "notes": "optional"
}
```

## Content rules
- **Language:** the video's spoken language (`"lang"` in `videos/<name>/transcript.json`, or the one set in `edit.json`), whatever language the author talks to you in. Put it in the optional `"lang"` (`"pt"`, `"en"`); `publish.md` shows it in the header.
- **Source of truth:** what the video actually says (`plan.json`/captions) and the source material, if the author points to one (`CLAUDE.local.md`). Don't promise what the video doesn't deliver.
- **Audience:** follow the video's content. The default is the broadest audience the topic serves; the channel's default audience, if any, is in `CLAUDE.local.md`. A **niche** video (a specific audience or field) only when the content only serves that audience or the author says so. Niche source material doesn't make the video niche: an example from one field in a video on a general topic is an example, not the audience. Say in `hashtags_reason` which audience you assumed.
- **Tone:** an experienced colleague talking to a colleague. No condescension, no shouted CAPITALS, no promise of results (financial, professional or other).
- **Title:** the concrete promise in the **first 50 characters** (the feed cuts it there). Give 3 options, the recommended one first. No bait the video doesn't deliver. No `<` or `>` (YouTube rejects them).
- **Description and caption:** the hook fits in ~100 characters (what shows before "more"). Then: 1 to 2 sentences on what the viewer takes from the video and a call to the next step (next video, related material). No made-up links: if there is no real link, don't add one.
- **Hashtags:** default 3 to 5 per platform, one broad on the topic + the rest specific to the video's content, in the video's language. An audience hashtag (e.g. `#<Topic>For<Profession>`) only on a niche video. Which hashtags to use for the general audience is still the author's decision: propose them, mark them as a proposal in `hashtags_reason` and don't treat earlier choices as the default. CamelCase (`#VideoEditing`, `#EdicaoDeVideo`). YouTube's first ones may show above the title (not confirmed on Shorts): the most important go first. No generic "reach" hashtag by default. Going outside the 3 to 5 range only with a justification in `hashtags_reason` (`publish.py` warns).
- **Cover:** choose among the `thumb.json` variants (its `name` goes in `cover.variant`) and justify it in one sentence (open face, text readable on a phone, a frame that represents the video).
- **Platform facts** (limits, cover rules) don't go here: if you need a new number, update `presets/publish.json` after checking the official source.
- **No paid API and no sending audio/video out.**
