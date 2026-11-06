"""publish.py: validates meta.json (types, limits, hashtags, cover, duration) and generates a deterministic publish.md.

    python3 -m unittest discover tests
"""
import contextlib, copy, io, json, os, re, sys, tempfile, unicodedata, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from vtk import publish

with open(os.path.join(ROOT, "presets", "publish.json"), encoding="utf-8") as f:
    P = json.load(f)
YT, TT = P["limits"]["youtube"], P["limits"]["tiktok"]

META = {
    "titles": ["Os 4 elementos de um bom prompt", "Alternativa curta"],
    "description": "Gancho curto.\n\nO que voce leva do video.",
    "tiktok_caption": "Gancho curto da legenda.",
    "hashtags": {"tiktok": ["#InteligenciaArtificial", "#Prompt", "#Produtividade"],
                 "youtube": ["#InteligenciaArtificial", "#Prompt", "#Produtividade"]},
    "hashtags_reason": "PROPOSTA: publico geral.",
    "cover": {"variant": "A", "reason": "Rosto aberto e texto legivel."},
}
THUMB = {"variants": [{"name": "A", "vertical": {"time_s": 14}}, {"name": "B"}]}
COVERS = {f for v in "AB" for f in publish.cover_files(v).values()}


def meta(**over):
    M = copy.deepcopy(META)
    M.update(over)
    return M


def check(M, dur=45.0, thumb=THUMB, covers=COVERS):
    return publish.validate(publish.nfc(M), P, dur, thumb, covers)



class Fields(unittest.TestCase):
    def assertError(self, M, snippet, **kw):
        errors, _ = check(M, **kw)
        self.assertTrue(any(snippet in e for e in errors), f"expected '{snippet}' in {errors}")

    def test_valid_meta(self):
        self.assertEqual(check(META), ([], []))

    def test_each_required_missing_or_empty(self):
        for k in publish.FIELDS:
            for empty in (None, "", [], {}):
                M = meta(); M[k] = empty
                with self.subTest(k=k, v=empty): self.assertError(M, f"missing or empty: {k}")
            M = meta(); del M[k]
            with self.subTest(k=k, v="del"): self.assertError(M, f"missing or empty: {k}")

    def test_wrong_types(self):
        cases = [
            (dict(titles="a single title"), "titles must"),
            (dict(titles=["a", "b", "c", "d"]), "titles must"),
            (dict(titles=["a", ""]), "titles must"),
            (dict(titles=["a", 3]), "titles must"),
            (dict(description=5), "description must be text"),
            (dict(description=0), "description must be text"),
            (dict(tiktok_caption=["x"]), "tiktok_caption must be text"),
            (dict(hashtags_reason={"a": 1}), "hashtags_reason must be text"),
            (dict(hashtags=["#a"]), "hashtags must be"),
            (dict(hashtags={"tiktok": ["#a", "#b", "#c"]}), "hashtags.youtube missing"),
            (dict(hashtags={"tiktok": [], "youtube": [], "instagram": []}), "unknown platform 'instagram'"),
            (dict(hashtags={"tiktok": "#a #b", "youtube": []}), "hashtags.tiktok must be a list"),
            (dict(hashtags={"tiktok": [], "youtube": [1]}), "hashtags.youtube must be a list"),
            (dict(cover="A"), "cover must be"),
            (dict(cover={"variant": "A"}), "cover.reason"),
            (dict(cover={"reason": "x", "variant": 1}), "cover.variant"),
            (dict(youtube_tags="ia, prompt"), "youtube_tags must"),
            (dict(pinned_comment=3), "pinned_comment must be text"),
            (dict(notes=["x"]), "notes must be text"),
            (dict(lang="pt-BR"), "lang must be"),
            (dict(lang="PT"), "lang must be"),
            (dict(lang=1), "lang must be"),
        ]
        for over, snippet in cases:
            with self.subTest(over=over): self.assertError(meta(**over), snippet)

    def test_meta_not_object(self):
        self.assertError(["x"], "JSON object")

    def test_empty_hashtags_are_valid(self):
        errors, _ = check(meta(hashtags={"tiktok": [], "youtube": []}))
        self.assertEqual(errors, [])

    def test_unknown_field_warns(self):
        errors, warnings = check(meta(pinned_coment="x"))
        self.assertEqual(errors, [])
        self.assertTrue(any("pinned_coment" in a for a in warnings))

    def test_lang_is_optional_and_accepted(self):
        for lang in ("pt", "en"):
            with self.subTest(lang=lang): self.assertEqual(check(meta(lang=lang)), ([], []))


class Texts(unittest.TestCase):
    def test_title_over_max_is_error(self):
        errors, _ = check(meta(titles=["x" * (YT["title_max"] + 1)]))
        self.assertTrue(any("title 1" in e for e in errors))

    def test_title_only_over_visible_is_warning(self):
        errors, warnings = check(meta(titles=["x" * YT["title_max"]]))
        self.assertEqual(errors, [])
        self.assertTrue(any("title 1" in a and "feed" in a for a in warnings))
        errors, warnings = check(meta(titles=["x" * YT["title_visible_feed"]]))
        self.assertEqual((errors, warnings), ([], []))

    def test_nfc_before_counting(self):
        nfd = unicodedata.normalize("NFD", "é" * YT["title_max"])
        self.assertGreater(len(nfd), YT["title_max"])
        errors, _ = check(meta(titles=[nfd]))
        self.assertEqual(errors, [])

    def test_emoji_warns(self):
        errors, warnings = check(meta(tiktok_caption="Olha isso 🔥"))
        self.assertEqual(errors, [])
        self.assertTrue(any("emoji" in a and "tiktok_caption" in a for a in warnings))

    def test_hashtag_inside_text(self):
        for k, v in (("description", "Veja #IA aqui"), ("tiktok_caption", "#Prompt no comeco"), ("titles", ["Prompt #1 do ano"])):
            with self.subTest(k=k):
                errors, _ = check(meta(**{k: v}))
                self.assertTrue(any("hashtag in the text" in e for e in errors), errors)

    def test_hash_sign_that_is_not_a_hashtag(self):
        errors, _ = check(meta(description="Exemplo em C# e no site x.com/#secao; aspas &#39; ok"))
        self.assertEqual(errors, [])

    def test_less_greater_on_youtube(self):
        for k, v in (("titles", ["Prompt <bom>"]), ("description", "a > b")):
            with self.subTest(k=k):
                errors, _ = check(meta(**{k: v}))
                self.assertTrue(any("'<' or '>'" in e for e in errors), errors)
        errors, _ = check(meta(tiktok_caption="a > b"))
        self.assertEqual(errors, [])


class Hashtags(unittest.TestCase):
    def test_invalid(self):
        for h in ("IA", "#com espaco", "#a-b", "#", "#ponto."):
            with self.subTest(h=h):
                errors, _ = check(meta(hashtags={"tiktok": ["#Ok", h, "#Mais"], "youtube": []}))
                self.assertTrue(any("invalid hashtags in tiktok" in e for e in errors), errors)

    def test_accent_is_valid(self):
        errors, _ = check(meta(hashtags={"tiktok": ["#Inteligência", "#Prompt", "#Ação"], "youtube": []}))
        self.assertEqual(errors, [])

    def test_repeated_case_insensitive(self):
        errors, _ = check(meta(hashtags={"tiktok": [], "youtube": ["#IA", "#Prompt", "#ia"]}))
        self.assertTrue(any("repeated hashtags in youtube" in e and "#ia" in e for e in errors), errors)

    def test_outside_recommended_range_warns(self):
        errors, warnings = check(meta(hashtags={"tiktok": ["#A1"], "youtube": []}))
        self.assertEqual(errors, [])
        self.assertTrue(any(a.startswith("tiktok: 1 hashtags") for a in warnings))

    def test_youtube_60_ok_61_error(self):
        n = YT["hashtags_max"]
        errors, _ = check(meta(description="d", hashtags={"tiktok": [], "youtube": [f"#T{i}" for i in range(n)]}))
        self.assertEqual(errors, [])
        errors, _ = check(meta(description="d", hashtags={"tiktok": [], "youtube": [f"#T{i}" for i in range(n + 1)]}))
        self.assertTrue(any("hashtags on YouTube" in e for e in errors), errors)

    def test_caption_plus_hashtags_at_limit(self):
        hs = ["#Aa", "#Bb", "#Cc"]
        rest = TT["caption_max"] - len("\n\n" + " ".join(hs))
        errors, _ = check(meta(tiktok_caption="x" * rest, hashtags={"tiktok": hs, "youtube": []}))
        self.assertEqual(errors, [])
        errors, _ = check(meta(tiktok_caption="x" * (rest + 1), hashtags={"tiktok": hs, "youtube": []}))
        self.assertTrue(any("TikTok caption + hashtags" in e for e in errors), errors)

    def test_description_plus_hashtags_at_limit(self):
        hs = ["#Aa", "#Bb", "#Cc"]
        rest = YT["description_max"] - len("\n\n" + " ".join(hs))
        errors, _ = check(meta(description="x" * rest, hashtags={"tiktok": [], "youtube": hs}))
        self.assertEqual(errors, [])
        errors, _ = check(meta(description="x" * (rest + 1), hashtags={"tiktok": [], "youtube": hs}))
        self.assertTrue(any("description + hashtags" in e for e in errors), errors)

    def test_description_in_bytes_warns(self):
        errors, warnings = check(meta(description="ç" * 3000, hashtags={"tiktok": [], "youtube": []}))
        self.assertEqual(errors, [])
        self.assertTrue(any("bytes" in a for a in warnings))

    def test_youtube_tags_quotes_on_tag_with_space(self):
        self.assertEqual(publish.tags_total(["ia", "bom prompt"]), len("ia,bom prompt") + 2)
        full = ["x" * 99] * 5  # 5*99 + 4 commas = 499
        self.assertEqual(check(meta(youtube_tags=full))[0], [])
        with_space = full[:-1] + ["x" * 49 + " " + "x" * 49]  # 499 + 2 quotes = 501
        errors, _ = check(meta(youtube_tags=with_space))
        self.assertTrue(any("YouTube tags add up to 501" in e for e in errors), errors)


class CoverAndDuration(unittest.TestCase):
    def test_missing_variant(self):
        errors, _ = check(meta(cover={"variant": "Z", "reason": "x"}))
        self.assertTrue(any("cover variant 'Z'" in e for e in errors), errors)

    def test_no_thumb_json(self):
        errors, _ = check(META, thumb=None)
        self.assertTrue(any("thumb.json" in e for e in errors), errors)

    def test_provisional_cover(self):
        for reason in ("PROVISIONAL: pick after thumb.py", "PROVISÓRIA: escolher depois do thumb.py"):
            with self.subTest(reason=reason):
                errors, _ = check(meta(cover={"variant": "A", "reason": reason}))
                self.assertTrue(any("provisional" in e for e in errors), errors)

    def test_no_covers_folder(self):
        errors, _ = check(META, covers=None)
        self.assertTrue(any("covers folder" in e for e in errors), errors)

    def test_cover_file_missing(self):
        errors, _ = check(META, covers={publish.cover_files("A")["9x16"]})
        self.assertTrue(any("cover_A_16x9" in e for e in errors), errors)

    def test_zero_duration_is_error(self):
        errors, _ = check(META, dur=0.0)
        self.assertTrue(any("0.0 s" in e for e in errors), errors)

    def test_duration_over_short_warns_with_one_decimal(self):
        errors, warnings = check(META, dur=230.0)
        self.assertEqual(errors, [])
        self.assertTrue(any("230.0 s" in a for a in warnings), warnings)


def fake_ffprobe(bindir, output):
    p = os.path.join(bindir, "ffprobe")
    with open(p, "w") as f:
        f.write(f"#!/bin/sh\necho '{output}'\n")
    os.chmod(p, 0o755)


class Duration(unittest.TestCase):
    def test_missing_video(self):
        with self.assertRaisesRegex(ValueError, "video not found"):
            publish.duration("/does/not/exist.mp4")

    def test_no_ffprobe(self):
        with tempfile.TemporaryDirectory() as d:
            v = os.path.join(d, "f.mp4"); open(v, "w").close()
            with mock.patch.dict(os.environ, {"PATH": d}):
                with self.assertRaisesRegex(ValueError, "ffprobe not found"):
                    publish.duration(v)

    def test_rounds_and_unreadable_output(self):
        with tempfile.TemporaryDirectory() as d:
            v = os.path.join(d, "f.mp4"); open(v, "w").close()
            fake_ffprobe(d, "45.47")
            with mock.patch.dict(os.environ, {"PATH": d}):
                self.assertEqual(publish.duration(v), 45.5)
            fake_ffprobe(d, "N/A")
            with mock.patch.dict(os.environ, {"PATH": d}):
                with self.assertRaisesRegex(ValueError, "could not read the duration"):
                    publish.duration(v)


class Main(unittest.TestCase):
    """End to end: video folder in a temp dir (absolute --name) and a fake ffprobe in PATH."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.bin = os.path.join(d, "bin"); os.mkdir(self.bin)
        fake_ffprobe(self.bin, "62.34")
        self.vdir = os.path.join(d, "my-video")
        os.makedirs(os.path.join(self.vdir, "covers"))
        for f in COVERS: open(os.path.join(self.vdir, "covers", f), "w").close()
        self.video = os.path.join(self.vdir, "final.mp4"); open(self.video, "w").close()
        self.write("meta.json", META); self.write("thumb.json", THUMB)
        self.out = os.path.join(self.vdir, "publish.md")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, data):
        with open(os.path.join(self.vdir, name), "w", encoding="utf-8") as f:
            f.write(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False))

    def run_main(self, *extra, video=None):
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"PATH": self.bin}), contextlib.redirect_stdout(buf):
            rc = publish.main(["--name", self.vdir, "--video", video or self.video, *extra])
        return rc, buf.getvalue()

    def read(self):
        with open(self.out, "rb") as f: return f.read()

    def test_deterministic_without_date(self):
        rc, _ = self.run_main()
        self.assertEqual(rc, 0)
        a = self.read()
        rc, _ = self.run_main()
        self.assertEqual(a, self.read())
        txt = a.decode("utf-8")
        self.assertNotRegex(txt, r"\d{4}-\d{2}-\d{2}")
        self.assertIn("# Publish — my-video", txt)
        self.assertIn("duration 1:02", txt)
        self.assertNotIn("language", txt)  # no lang in meta.json: nothing shown
        self.assertIn("cover_A_9x16_1080x1920.png", txt)
        self.assertIn("~14 s", txt)
        self.assertIn(f"the first {YT['hashtags_above_title']} hashtags", txt)

    def test_lang_shown_and_content_kept_as_written(self):
        self.write("meta.json", meta(lang="en", titles=["The 4 parts of a good prompt"]))
        self.assertEqual(self.run_main()[0], 0)
        txt = self.read().decode("utf-8")
        self.assertIn("language en", txt)
        self.assertIn("The 4 parts of a good prompt", txt)

    def test_missing_video_without_traceback(self):
        rc, out = self.run_main(video=os.path.join(self.vdir, "no.mp4"))
        self.assertEqual(rc, 1)
        self.assertIn("ERROR: video not found", out)

    def test_broken_meta_json(self):
        self.write("meta.json", "{ not json")
        rc, out = self.run_main()
        self.assertEqual(rc, 1)
        self.assertIn("ERROR: meta.json unreadable", out)

    def test_missing_meta_json_lists_fields(self):
        os.remove(os.path.join(self.vdir, "meta.json"))
        rc, out = self.run_main()
        self.assertEqual(rc, 1)
        self.assertIn("hashtags_reason", out)

    def test_covers_in_another_folder(self):
        rc, out = self.run_main("--covers", os.path.join(self.vdir, "does-not-exist"))
        self.assertEqual(rc, 1)
        self.assertIn("covers folder", out)

    def test_error_does_not_leave_old_publish_md(self):
        self.assertEqual(self.run_main()[0], 0)
        old = self.read()
        self.write("meta.json", meta(cover={"variant": "Z", "reason": "x"}))
        rc, out = self.run_main()
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(self.out))
        self.assertIn("stale", out)
        with open(self.out + ".stale", "rb") as f: self.assertEqual(f.read(), old)
        self.write("meta.json", META)
        self.assertEqual(self.run_main()[0], 0)
        self.assertFalse(os.path.exists(self.out + ".stale"))

    def test_error_without_publish_md_creates_nothing(self):
        self.write("meta.json", meta(titles="x"))
        rc, _ = self.run_main()
        self.assertEqual(rc, 1)
        self.assertEqual(sorted(f for f in os.listdir(self.vdir) if f.startswith("publish")), [])


if __name__ == "__main__":
    unittest.main()
