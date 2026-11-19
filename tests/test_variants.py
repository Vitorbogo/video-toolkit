"""variants.py: an excerpt of the plan rendered N ways (hard cut, punch-in, J-cut...) to watch side by side.

    python3 -m unittest discover tests
"""
import contextlib, io, json, os, shutil, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vtk import render, variants

PLAN = [{"s": 0.0, "e": 5.0, "ev": [[0.5, 2.0, "Primeira."], [3.0, 4.8, "Segunda ideia."]],
         "wt": [[0.5, 1.0], [3.0, 3.6]], "blur": [[1.0, 4.5, 0, 0, 10, 10]]},
        {"s": 6.0, "e": 12.0, "ev": [[0.4, 2.0, "Agora outra."], [4.0, 5.9, "Fim."]],
         "wt": [[0.4, 1.1], [4.0]], "z": 1.1, "j": [0.6, "both"]}]


class Excerpt(unittest.TestCase):
    def test_join_range_takes_ctx_on_each_side(self):
        self.assertEqual(variants.join_range(PLAN, 0, 3.0), (2.0, 9.0))

    def test_clips_the_pieces_and_rebases_captions_and_blur(self):
        ex = variants.excerpt(PLAN, 2.0, 9.0)
        A, B = ex
        self.assertEqual((A["s"], A["e"], A["_i"]), (2.0, 5.0, 0))
        self.assertEqual(A["ev"], [[1.0, 2.8, "Segunda ideia."]])  # "Primeira." ends where the range starts
        self.assertEqual(A["wt"], [[1.0, 1.6]])
        self.assertEqual(A["blur"], [[0.0, 2.5, 0, 0, 10, 10]])
        self.assertEqual((B["s"], B["e"], B["_i"]), (6.0, 9.0, 1))
        self.assertEqual(B["ev"], [[0.4, 2.0, "Agora outra."]])
        self.assertEqual(B["j"], [0.6, "both"])  # the plan as it is: the variant decides

    def test_a_sentence_cut_in_the_middle_keeps_its_visible_part(self):
        A = variants.excerpt(PLAN, 1.5, 5.0)[0]
        self.assertEqual(A["ev"][0], [0.0, 0.5, "Primeira."])
        self.assertEqual(A["wt"][0], [-1.0, -0.5])

    def test_first_piece_loses_its_jcut(self):
        B = variants.excerpt(PLAN, 7.0, 12.0)[0]
        self.assertNotIn("j", B)
        self.assertEqual(B["ev"], [[0.0, 1.0, "Agora outra."], [3.0, 4.9, "Fim."]])

    def test_nothing_in_the_range_is_an_error(self):
        with self.assertRaises(SystemExit):
            variants.excerpt(PLAN, 5.2, 5.8)


class Apply(unittest.TestCase):
    def ex(self):
        return variants.excerpt(PLAN, 2.0, 9.0)

    def test_hard_cut_removes_keys_set_to_null(self):
        plan, info = variants.apply(self.ex(), {"name": "hard", "j": None, "z": None}, 1, 30)
        self.assertNotIn("j", plan[1]); self.assertNotIn("z", plan[1])
        self.assertFalse(any(k.startswith("_") for c in plan for k in c))
        self.assertIsNone(info.get("skipped"))

    def test_other_keys_are_set_on_the_target(self):
        plan, _ = variants.apply(self.ex(), {"name": "punch", "z": 1.15}, 1, 30)
        self.assertEqual(plan[1]["z"], 1.15)
        self.assertEqual(plan[0].get("z"), None)

    def test_V_is_voice_before_picture_from_the_first_word(self):
        # B's first word at 6.4: lead = 0.4 (silence) + 0.25 = 0.65, next frame up at 30 fps
        plan, info = variants.apply(self.ex(), {"name": "J", "V": 0.25}, 1, 30)
        self.assertEqual(plan[1]["j"], [0.666667, "both"])
        self.assertEqual(info["picture_lead_s"], 0.667)
        self.assertEqual(info["lead_silence_s"], 0.4)
        plan, _ = variants.apply(self.ex(), {"name": "J", "V": 0.2, "area": "camera"}, 1, 30)
        self.assertEqual(plan[1]["j"][1], "camera")

    def test_V_longer_than_the_silent_footage_is_skipped(self):
        # A ends at 5.0, B's voice at 6.4: borrowed footage must end by 6.35 -> lead at most 1.35
        _, info = variants.apply(self.ex(), {"name": "J", "V": 1.0}, 1, 30)
        self.assertIn("silent footage", info["skipped"])

    def test_V_over_the_limit_by_under_a_frame_is_shortened_like_jcut(self):
        # limit 1.35 s; V 0.95 -> 1.35 rounds up to 1.367: floored to 1.333 (V 0.933, < 1 frame short)
        plan, info = variants.apply(self.ex(), {"name": "J", "V": 0.95}, 1, 30)
        self.assertEqual(plan[1]["j"], [1.333333, "both"])
        self.assertIsNone(info.get("skipped"))
        _, info = variants.apply(self.ex(), {"name": "J", "V": 0.97}, 1, 30)  # 1.4 frames short
        self.assertIn("silent footage", info["skipped"])

    def test_lead_that_leaves_no_picture_is_skipped(self):
        _, info = variants.apply(self.ex(), {"name": "J", "j": [3.5, "both"]}, 1, 30)  # B has 3 s here
        self.assertIn("picture", info["skipped"])

    def test_l_cut_longer_than_the_removed_gap_is_skipped(self):
        # gap 5.0 -> 6.0: B's picture 1.2 s early would show A still speaking
        _, info = variants.apply(self.ex(), {"name": "L", "j": [-1.2, "both"]}, 1, 30)
        self.assertIn("speaking", info["skipped"])

    def test_raw_negative_j_is_an_l_cut(self):
        plan, info = variants.apply(self.ex(), {"name": "L", "j": [-0.3, "both"]}, 1, 30)
        self.assertEqual(plan[1]["j"], [-0.3, "both"])
        self.assertIsNone(info.get("skipped"))

    def test_bad_variants_are_clear_errors(self):
        for v in ({"V": 0.2}, {"name": "a/b"}, {"name": "x", "V": 0.2, "area": "face"}, {"name": "x", "area": "camera"}):
            with self.assertRaises(SystemExit):
                variants.apply(self.ex(), v, 1, 30)
        with self.assertRaises(SystemExit):  # V needs a piece before the target
            variants.apply(self.ex(), {"name": "x", "V": 0.2}, 0, 30)
        with self.assertRaises(SystemExit):
            variants.check_names([{"name": "a"}, {"name": "a"}])


class Compare(unittest.TestCase):
    def test_same_length_or_an_error(self):
        self.assertEqual(variants.mismatches({"a": (90, 144000), "b": (90, 144000)}), [])
        errs = variants.mismatches({"a": (90, 144000), "b": (91, 144000), "c": (90, 140000)})
        self.assertEqual(len(errs), 2)
        self.assertIn("b", errs[0]); self.assertIn("c", errs[1])


def frame(path, i):
    """Frame i, 45x80 gray bytes."""
    import subprocess
    return subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", f"select=eq(n\\,{i}),scale=45:80,format=gray",
                           "-frames:v", "1", "-f", "rawvideo", "-"], capture_output=True, check=True).stdout


def mean_diff(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


@unittest.skipIf(shutil.which("ffmpeg") is None, "no ffmpeg")
class RealRender(unittest.TestCase):
    PLAN = [{"s": 0.2, "e": 1.0, "ev": [[0.1, 0.7, "Um."]], "wt": [[0.1]]},
            {"s": 1.6, "e": 2.6, "ev": [[0.3, 0.9, "Dois três."]], "wt": [[0.3, 0.6]]}]

    def setUp(self):
        import subprocess
        from test_render import dump
        self.d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.d)
        self.video = os.path.join(self.d, "g.mkv")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=30:d=3",
                        "-f", "lavfi", "-i", "sine=f=440:sample_rate=48000:d=3", "-c:v", "libx264", "-preset", "ultrafast",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", self.video], check=True)
        self.preset = os.path.join(self.d, "preset.json")
        dump({"base": os.path.join(ROOT, "presets/tiktok-vertical.json"), "canvas": {"w": 180, "h": 320},
              "source": {"w": 320, "h": 240, "camera_crop": [160, 120, 160, 0], "slide_crop": [160, 240, 0, 0]},
              "layout": {"camera": {"y": 10, "h": 90}, "slide": {"x": 10, "y": 110, "w": 160, "h": 150}}}, self.preset)
        self.plan = os.path.join(self.d, "plan.json"); dump(self.PLAN, self.plan)
        self.vs = os.path.join(self.d, "v.json")
        dump([{"name": "hard"}, {"name": "punch-in", "z": 1.1}, {"name": "J0.2", "V": 0.2},
              {"name": "J1", "V": 1.0}], self.vs)
        self.out = os.path.join(self.d, "out")
        probe = render.probe
        render.probe = lambda v: (320, 240)  # no ffprobe in the tests
        self.addCleanup(setattr, render, "probe", probe)

    def test_every_variant_same_length_and_a_report(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            variants.main(["--preset", self.preset, "--video", self.video, "--plan", self.plan, "--join", "0",
                           "--ctx", "1.0", "--variants", self.vs, "--out", self.out, "--tag", "t"])
        files = sorted(f for f in os.listdir(self.out) if f.endswith(".mkv"))
        self.assertEqual(files, ["t_0-hard.mkv", "t_1-punch-in.mkv", "t_2-J0.2.mkv"])
        with open(os.path.join(self.out, "t_report.json"), encoding="utf-8") as f:
            rep = json.load(f)
        ok = [v for v in rep["variants"] if "skipped" not in v]
        self.assertEqual({(v["frames"], v["samples"]) for v in ok}, {(54, 54 * 1600)})  # A clipped to its 0.8 s + B's 1.0 s, 30 fps
        self.assertIn("skipped", rep["variants"][3])
        self.assertEqual(rep["join"]["removed_gap_s"], 0.6)
        # the J-cut moves the picture: its frames differ from the hard cut's after the join
        diff = lambda i: mean_diff(*(frame(os.path.join(self.out, f), i) for f in ("t_0-hard.mkv", "t_2-J0.2.mkv")))
        self.assertLess(diff(12), 1)    # same picture before the sound join (frame 24)
        self.assertGreater(diff(30), 3)  # after it A's picture runs on 0.5 s in the J-cut


    def test_every_variant_skipped_is_an_error(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(io.StringIO()):
            variants.main(["--preset", self.preset, "--video", self.video, "--plan", self.plan, "--join", "0",
                           "--variants", '[{"name": "J1", "V": 1.0}]', "--out", self.out])


if __name__ == "__main__":
    unittest.main()
