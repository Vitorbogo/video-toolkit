"""thumb: option precedence, highlight, text wrapping/shrinking, spec validation and a real run.

    python3 -m unittest discover tests
"""
import contextlib, copy, hashlib, io, os, shutil, subprocess, sys, tempfile, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from vtk import preset, thumb

P = preset.load("presets/thumbnail.json")
F_T = os.path.join(thumb.ROOT, P["fonts"]["title"])
SPEC = {"time_s": 14, "kicker": "CHATGPT", "title": "O chat acha que você é homem?", "highlight": "homem?",
        "footer": "", "face_x": 0.5,
        "variants": [{"name": "A", "vertical": {"time_s": 14}, "youtube": {"time_s": 3}},
                     {"name": "B", "vertical": {"time_s": 3}}]}


def quiet():
    return contextlib.redirect_stdout(io.StringIO())


class Precedence(unittest.TestCase):
    S = {"time_s": 1, "face_x": 0.1, "title": "top", "kicker": "K",
         "youtube": {"time_s": 2, "title": "format"},
         "variants": [{"name": "A", "face_x": 0.3, "title": "variant", "youtube": {"time_s": 4}}]}

    def test_top_level_format_applies_without_variants(self):
        S = {k: v for k, v in self.S.items() if k != "variants"}
        o = thumb.resolve(S, {}, "youtube")
        self.assertEqual((o["time_s"], o["title"], o["face_x"]), (2, "format", 0.1))
        self.assertEqual(thumb.resolve(S, {}, "vertical")["title"], "top")

    def test_full_order(self):
        v = self.S["variants"][0]
        o = thumb.resolve(self.S, v, "youtube")
        self.assertEqual((o["time_s"], o["title"], o["face_x"], o["kicker"]), (4, "variant", 0.3, "K"))
        o = thumb.resolve(self.S, v, "vertical")
        self.assertEqual((o["time_s"], o["title"]), (1, "variant"))

    def test_cli_beats_everything(self):
        o = thumb.resolve(self.S, self.S["variants"][0], "youtube", time=9, face_x=0.9)
        self.assertEqual((o["time_s"], o["face_x"]), (9, 0.9))

    def test_missing_texts_become_empty(self):
        o = thumb.resolve({"time_s": 1, "title": "t"}, {}, "vertical")
        self.assertEqual((o["kicker"], o["footer"], o["highlight"], o["face_x"]), ("", "", "", None))


class Highlight(unittest.TestCase):
    def hl(self, title, d):
        with quiet() as out: r = thumb.highlight(title.split(), d)
        return r, out.getvalue()

    def test_punctuation_in_highlight_and_title(self):
        self.assertEqual(self.hl("O chat acha que você é homem?", "homem?")[0], {6})
        self.assertEqual(self.hl("O chat acha que você é homem?", "Homem")[0], {6})

    def test_several_words_in_sequence(self):
        self.assertEqual(self.hl("Isso não deixa a IA mais esperta", "mais  ESPERTA!")[0], {5, 6})
        self.assertEqual(self.hl("a IA, a ia e a IA", "a IA")[0], {0, 1, 2, 3, 5, 6})

    def test_not_found_warns(self):
        r, out = self.hl("A IA inventa a conta", "esperta")
        self.assertEqual(r, set()); self.assertIn("WARNING", out)
        r, out = self.hl("mais algo esperta", "mais esperta")  # scattered words do not count
        self.assertEqual(r, set())

    def test_empty_does_not_warn(self):
        self.assertEqual(self.hl("A IA", ""), (set(), ""))


class Text(unittest.TestCase):
    T = P["youtube_16x9"]["title"]

    def test_long_word_shrinks_until_it_fits(self):
        f, words, lines, lh = thumb.fit("Pare de dizer que a IA é especialista", F_T, self.T, 440)
        self.assertLess(f.size, self.T["size"])
        self.assertLessEqual(max(f.getlength(" ".join(words[i] for i in l)) for l in lines), 440)

    def test_line_limit(self):
        cfg = dict(self.T, max_lines=2)  # at the preset size (84) it would take 4 lines
        f, words, lines, lh = thumb.fit("A IA inventa a conta toda vez", F_T, cfg, 440)
        self.assertLessEqual(len(lines), 2); self.assertLess(f.size, 84)
        self.assertEqual(sum(len(l) for l in lines), len(words))

    def test_max_height(self):
        f, _, lines, lh = thumb.fit("A IA inventa a conta toda vez", F_T, self.T, 440, max_h=240)
        self.assertLessEqual(len(lines) * lh, 240); self.assertLess(f.size, 84)

    def test_does_not_fit_is_an_error(self):
        with self.assertRaises(SystemExit) as c:
            thumb.fit("Inconstitucionalissimamente", F_T, self.T, 440)
        self.assertIn("shorten", str(c.exception.code))

    def test_short_text_keeps_preset_size(self):
        self.assertEqual(thumb.fit("A IA inventa a conta", F_T, P["vertical_9x16"]["title"], 900)[0].size, 112)


class Validation(unittest.TestCase):
    def error(self, S):
        with self.assertRaises(SystemExit) as c: thumb.validate(S)
        return str(c.exception.code)

    def test_good_spec(self):
        thumb.validate(dict(SPEC, _note="comment"))
        thumb.validate({"time_s": 0, "title": "t"})

    def test_errors(self):
        cases = [({"title": "t"}, "missing time_s"),
                 ({"time_s": 1}, "missing title"),
                 ({"time_s": 1, "title": "  "}, "missing title"),
                 ({"time_s": 1, "title": "t", "titl": "x"}, "unknown key 'titl'"),
                 ({"time_s": -1, "title": "t"}, "time_s must be"),
                 ({"time_s": "3", "title": "t"}, "time_s must be"),
                 ({"time_s": True, "title": "t"}, "time_s must be"),
                 ({"time_s": 1, "title": "t", "face_x": 1.5}, "face_x must be"),
                 ({"time_s": 1, "title": 3}, "title must be text"),
                 ({"time_s": 1, "title": "t", "youtube": {"time": 2}}, "youtube: unknown key"),
                 ({"time_s": 1, "title": "t", "vertical": []}, "vertical must be an object"),
                 ({"time_s": 1, "title": "t", "variants": []}, "at least one variant"),
                 ({"time_s": 1, "title": "t", "variants": [{"time_s": 2}]}, "name is required"),
                 ({"time_s": 1, "title": "t", "variants": [{"name": "a b"}]}, "name is required"),
                 ({"time_s": 1, "title": "t", "variants": [{"name": "A", "youtube": {"face_x": -0.1}}]},
                  "variants[0].youtube.face_x"),
                 ({"title": "t", "variants": [{"name": "A", "vertical": {"time_s": 1}}]}, "missing time_s (variant A, youtube)")]
        for S, msg in cases:
            with self.subTest(S=S): self.assertIn(msg, self.error(S))

    def test_repeated_names(self):
        S = copy.deepcopy(SPEC); S["variants"][1]["name"] = "A"
        self.assertIn("name repeated", self.error(S))

    def test_collects_all_errors(self):
        m = self.error({"time_s": -1, "title": "t", "face_x": 2, "x": 1})
        for k in ("time_s", "face_x", "'x'"): self.assertIn(k, m)

    def test_sheet(self):
        self.assertEqual(thumb.parse_sheet("3, 20,48.5,"), [3.0, 20.0, 48.5])
        for s in ("3,x", "", "-1,2"):
            with self.subTest(s=s), self.assertRaises(SystemExit): thumb.parse_sheet(s)


FF = shutil.which("ffmpeg")


@unittest.skipUnless(FF, "ffmpeg not installed")
class Integration(unittest.TestCase):
    def test_deterministic_covers_and_cleanup(self):
        with tempfile.TemporaryDirectory() as d:
            video = os.path.join(d, "v.mp4")
            subprocess.run([FF, "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=10:d=16",
                            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", video], check=True)
            out1, out2 = os.path.join(d, "c1"), os.path.join(d, "c2")
            os.makedirs(out1)
            for old in ("cover_C_9x16_1080x1920.png", "cover_9x16_1080x1920.png", "other.png"):
                open(os.path.join(out1, old), "w").close()
            with quiet():
                r1 = thumb.run(video, SPEC, P, out1); r2 = thumb.run(video, SPEC, P, out2)
            names = ["cover_%s_%s.png" % (v, f) for v in "AB" for f in ("9x16_1080x1920", "16x9_1280x720")]
            self.assertEqual(sorted(r1), sorted(names))
            self.assertEqual(sorted(os.listdir(out1)), sorted(names + ["other.png", "covers.json"]))  # only old cover_*.png go away
            from PIL import Image
            def h(p):
                with open(p, "rb") as f: return hashlib.md5(f.read()).hexdigest()
            for n in names:
                with Image.open(r1[n]) as im: self.assertEqual(im.size, (1080, 1920) if "9x16" in n else (1280, 720))
                self.assertEqual(h(r1[n]), h(r2[n]), n)
            # --only: generates one format and does not delete the other
            with quiet(): r3 = thumb.run(video, SPEC, P, out1, only="youtube")
            self.assertEqual(sorted(r3), sorted(n for n in names if "16x9" in n))
            self.assertEqual(sorted(os.listdir(out1)), sorted(names + ["other.png", "covers.json"]))

    def test_time_past_the_end(self):
        with tempfile.TemporaryDirectory() as d:
            video = os.path.join(d, "v.mp4")
            subprocess.run([FF, "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=10:d=2",
                            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", video], check=True)
            with self.assertRaises(SystemExit) as c, quiet():
                thumb.run(video, {"time_s": 50, "title": "t"}, P, os.path.join(d, "c"))
            self.assertIn("t=50s", str(c.exception.code))
            self.assertFalse(os.path.exists(os.path.join(d, "c")))  # nothing written


if __name__ == "__main__":
    unittest.main()
