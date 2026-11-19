"""J-cut (src/vtk/jcut.py): picture timeline, captions following the sound, the craft rules that accept or refuse a
join, cuts.py's "jcut" key, and a real render (if ffmpeg is available).

    python3 -m unittest discover tests
"""
import contextlib, io, json, os, shutil, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vtk import cuts, jcut, render
from test_cuts import words, phrase, invariants
from test_render import dump, frames_and_samples

CLOSED = lambda t0, t1: None              # mouth stays closed
OPENS_AT = lambda d: (lambda t0, t1: t0 + d)  # mouth opens d s after the cut


def two(j=None, A_ev="Primeira ideia.", wt0=0.3):
    """A = 0-2 s, B = 3-6 s (removed gap 1 s of silence); B's first word 0.3 s into it."""
    B = {"s": 3.0, "e": 6.0, "ev": [[wt0, 1.5, "Agora a segunda."]], "wt": [[wt0, 0.8, 1.1]]}
    if j: B["j"] = j
    return [{"s": 0.0, "e": 2.0, "ev": [[0.1, 1.8, A_ev]], "wt": [[0.1, 0.6]]}, B]


SILENT = [(2.0, 3.0, "silence", "")]


class Picture(unittest.TestCase):
    def test_no_jcut_is_one_clip_per_piece(self):
        self.assertEqual(jcut.picture(two(), [60, 60], 30),
                         [{"f0": 0, "n": 60, "cam": 0, "sl": 0}, {"f0": 60, "n": 60, "cam": 1, "sl": 1}])

    def test_both_moves_the_picture_edit_later(self):
        p = jcut.picture(two([0.5, "both"]), [60, 60], 30)
        self.assertEqual(p, [{"f0": 0, "n": 75, "cam": 0, "sl": 0}, {"f0": 75, "n": 45, "cam": 1, "sl": 1}])
        F = [0, 60, 120]
        self.assertEqual(jcut.source(two(), F, 0, 70, 30), round(70 / 30, 6))  # A runs on past its end (2.0)
        self.assertEqual(jcut.source(two(), F, 1, 75, 30), 3.5)                 # B's picture starts 0.5 s in

    def test_one_area_splits_the_join_in_three(self):
        p = jcut.picture(two([0.5, "slide"]), [60, 60], 30)
        self.assertEqual(p, [{"f0": 0, "n": 60, "cam": 0, "sl": 0}, {"f0": 60, "n": 15, "cam": 1, "sl": 0},
                             {"f0": 75, "n": 45, "cam": 1, "sl": 1}])
        p = jcut.picture(two([0.5, "camera"]), [60, 60], 30)
        self.assertEqual(p[1], {"f0": 60, "n": 15, "cam": 0, "sl": 1})

    def test_negative_lead_is_an_l_cut(self):
        p = jcut.picture(two([-0.5, "both"]), [60, 60], 30)
        self.assertEqual([(x["f0"], x["n"]) for x in p], [(0, 45), (45, 75)])

    def test_lead_past_the_piece_is_an_error(self):
        with self.assertRaises(SystemExit):
            jcut.picture(two([2.0, "both"]), [60, 60], 30)

    def test_captions_follow_the_sound(self):
        plan = two([0.5, "both"])
        ev = jcut.caption_events(plan, [60, 60], 30)
        self.assertEqual(ev[1][:3], (2.3, 3.5, "Agora a segunda."))
        # clip 0 runs to 2.5 s: B's sentence already shows in its last 0.2 s, its first word highlighted
        e0, w0 = jcut.slice_captions(ev, 0.0, 2.5)
        self.assertEqual([x[2] for x in e0], ["Primeira ideia.", "Agora a segunda."])
        self.assertEqual(e0[1][:2], [2.3, 2.5]); self.assertEqual(w0[1][0], 2.3)
        e1, w1 = jcut.slice_captions(ev, 2.5, 4.0)
        self.assertEqual(e1, [[0.0, 1.0, "Agora a segunda."]])
        self.assertEqual(w1[0], [-0.2, 0.3, 0.6])  # captions.words clamps the started word to 0

    def test_old_plan_event_past_the_frames_does_not_leak(self):
        plan = [{"s": 0.0, "e": 1.01, "ev": [[0, 1.01, "Um."]]}, {"s": 2.0, "e": 3.0, "ev": [[0, 1.0, "Dois."]]}]
        ev = jcut.caption_events(plan, [30, 30], 30)
        self.assertEqual(jcut.slice_captions(ev, 1.0, 2.0)[0], [[0.0, 1.0, "Dois."]])


class Rules(unittest.TestCase):
    def test_silent_gap_with_closed_mouth_passes(self):
        v, why = jcut.check(two(), 0, SILENT, 30, "both", CLOSED)
        self.assertEqual(why, "silence")
        self.assertAlmostEqual(v, 0.95, delta=1 / 30)  # footage up to 0.05 s before B's word (1.25 s) - 0.3 s pre

    def test_filler_or_retake_gap_is_refused(self):
        for why in ("filler", "cut by hand", "retake", "repeat"):
            v, msg = jcut.check(two(), 0, [(2.0, 3.0, why, "x")], 30, "both", CLOSED)
            self.assertIsNone(v, why); self.assertIn(why, msg)

    def test_mouth_opening_caps_the_lead_and_too_little_skips(self):
        v, why = jcut.check(two(), 0, SILENT, 30, "both", OPENS_AT(0.8))
        self.assertEqual(why, "mouth opens"); self.assertAlmostEqual(v, 0.5, delta=0.04)
        v, why = jcut.check(two(), 0, SILENT, 30, "both", OPENS_AT(0.4))
        self.assertIsNone(v); self.assertIn("mouth opens", why)

    def test_unmeasured_mouth_refuses_the_camera_not_the_slide(self):
        self.assertIsNone(jcut.check(two(), 0, SILENT, 30, "both", None)[0])
        self.assertIsNone(jcut.check(two(), 0, SILENT, 30, "camera", None)[0])
        self.assertIsNotNone(jcut.check(two(), 0, SILENT, 30, "slide", None)[0])

    def test_next_piece_keeps_its_own_picture(self):
        plan = two(); plan[1]["e"] = 4.7  # 1.7 s long: only 0.2 s of lead, less than B's 0.3 s pre
        self.assertIsNone(jcut.check(plan, 0, SILENT, 30, "both", CLOSED)[0])

    def test_length_short_at_sentence_end_long_at_topic_change(self):
        self.assertEqual(jcut.choose(two(), 0, [(0.1, 0.5), (0.6, 1.8), (3.3, 3.7)])[:2], ("both", jcut.SHORT_V))
        area, v, why = jcut.choose(two(), 0, [(0.1, 0.2), (3.3, 3.7)])  # A's last word ends at 0.2: 3.1 s silent
        self.assertEqual(v, jcut.LONG_V); self.assertIn("topic change", why)

    def test_pointing_at_a_new_slide_delays_only_the_camera(self):
        plan = two(); plan[1]["ev"][0][2] = "Olha aqui o resultado."
        self.assertEqual(jcut.choose(plan, 0, (), [2.6], {"olha", "aqui"})[0], "camera")
        self.assertEqual(jcut.choose(plan, 0, (), [], {"olha", "aqui"})[0], "both")  # no slide change
        self.assertEqual(jcut.choose(plan, 0, (), [10.0], {"olha"})[0], "both")      # change elsewhere

    def test_parse_and_nearest_join(self):
        self.assertEqual(jcut.parse([4.2]), (4.2, None, None, ""))
        self.assertEqual(jcut.parse([4.2, 0.6, "slide", "topic"]), (4.2, 0.6, "slide", "topic"))
        self.assertEqual(jcut.parse([4.2, "nota"]), (4.2, None, None, "nota"))
        plan = two() + [{"s": 7.0, "e": 9.0, "ev": [[0.3, 1, "x."]]}]
        self.assertEqual(jcut.nearest_join(plan, 2.5), 0)
        self.assertEqual(jcut.nearest_join(plan, 5.9), 1)
        self.assertIsNone(jcut.nearest_join(plan, 20))


class Apply(unittest.TestCase):
    def test_writes_the_lead_on_the_next_piece(self):
        plan, w = two(), []
        done = jcut.apply(plan, [[2.5]], SILENT, 30, CLOSED, w)
        lead, area = plan[1]["j"]  # 0.25 s voice + 0.3 s pre, on the frame grid
        self.assertEqual(area, "both"); self.assertLessEqual(abs(lead - 0.55), 1 / 60 + 1e-6)
        self.assertAlmostEqual(lead * 30, round(lead * 30), delta=1e-4)
        self.assertAlmostEqual(done[0][1], 0.25, delta=1 / 60 + 1e-3); self.assertEqual(w, [])

    def test_too_long_is_shortened_with_a_warning(self):
        plan, w = two(), []
        jcut.apply(plan, [[2.5, 2.0]], SILENT, 30, OPENS_AT(0.8), w)
        self.assertAlmostEqual(plan[1]["j"][0], 0.8, delta=0.001)
        self.assertIn("shortened", w[0])

    def test_long_wanted_but_mouth_opens_falls_back_to_short(self):
        plan, w = two(), []
        done = jcut.apply(plan, [[2.5]], SILENT, 30, OPENS_AT(0.8), w, kept=[(0.1, 0.2), (3.3, 3.7)])
        self.assertAlmostEqual(done[0][1], jcut.SHORT_V, delta=1 / 60 + 1e-3); self.assertIn("too soon", done[0][3])

    def test_refused_join_and_not_a_sentence_end_warn(self):
        plan, w = two(A_ev="Primeira ideia e"), []
        jcut.apply(plan, [[2.5], [30]], [(2.0, 3.0, "filler", "ééé")], 30, CLOSED, w)
        self.assertNotIn("j", plan[1])
        self.assertTrue(any("skipped" in x for x in w) and any("no join" in x for x in w), w)
        plan, w = two(A_ev="Primeira ideia e"), []
        jcut.apply(plan, [[2.5]], SILENT, 30, CLOSED, w)
        self.assertIn("j", plan[1]); self.assertIn("does not end a sentence", w[0])


class Decide(unittest.TestCase):
    WS = words(phrase("Isso é a primeira ideia.", 0.0) + phrase("Agora vem a segunda ideia completa.", 3.5))

    def test_jcut_key_and_candidates(self):
        jc, w = {}, []
        plan, _, _ = cuts.decide(self.WS, {"jcut": [[2.5]]}, 6.5, lang="pt", warnings=w, mouth=CLOSED, jcuts=jc)
        invariants(self, plan)
        self.assertEqual(plan[1]["j"][1], "both")
        self.assertAlmostEqual(jc["applied"][0][1], 0.25, delta=1 / 60 + 1e-3)  # on the frame grid
        jc = {}
        plan, _, _ = cuts.decide(self.WS, {}, 6.5, lang="pt", mouth=CLOSED, jcuts=jc)
        self.assertNotIn("j", plan[1])
        self.assertEqual([c[0] for c in jc["candidates"]], [0])
        md = cuts.report(plan, [], [], 6.5, jcuts=jc)
        self.assertIn("## J-cut candidates", md); self.assertIn("sentence end", md)

    def test_filler_join_is_not_a_candidate(self):
        ws = words(phrase("Isso é a primeira ideia.", 0.0) + [("ééé", 2.2, 3.0)] + phrase("Agora vem a segunda ideia.", 3.5))
        jc, w = {}, []
        plan, _, _ = cuts.decide(ws, {"jcut": [[2.5]]}, 6.5, lang="pt", warnings=w, mouth=CLOSED, jcuts=jc)
        self.assertNotIn("j", plan[-1]); self.assertEqual(jc["candidates"], [])
        self.assertTrue(any("filler" in x for x in w), w)

    def test_blur_reaches_the_borrowed_footage(self):
        plan, _, _ = cuts.decide(self.WS, {"jcut": [[2.5]], "blur": [[2.3, 2.6, 0, 0, 10, 10]]}, 6.5, lang="pt",
                                 mouth=CLOSED)
        invariants(self, plan)
        self.assertTrue(plan[0].get("blur"), plan[0])  # 2.3-2.6 is after piece 0's end, inside its borrowed footage


@unittest.skipIf(shutil.which("ffmpeg") is None, "no ffmpeg")
class RealRender(unittest.TestCase):
    """2 pieces with a J-cut: frames and samples exact, the picture edit point where the plan puts it."""

    def setUp(self):
        self.d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.d)
        self.video = os.path.join(self.d, "g.mov")
        # red for 1.5 s, then blue: the picture shows which moment of the recording it comes from
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=320x240:r=30:d=1.5",
                        "-f", "lavfi", "-i", "color=c=blue:s=320x240:r=30:d=1.5",
                        "-f", "lavfi", "-i", "sine=f=440:sample_rate=48000:d=3",
                        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-map", "2:a",
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", self.video],
                       check=True)
        self.preset = os.path.join(self.d, "preset.json")
        dump({"base": os.path.join(ROOT, "presets/tiktok-vertical.json"), "canvas": {"w": 180, "h": 320},
              "source": {"w": 320, "h": 240, "camera_crop": [160, 120, 160, 0], "slide_crop": [160, 240, 0, 0]},
              "layout": {"camera": {"y": 10, "h": 90}, "slide": {"x": 10, "y": 110, "w": 160, "h": 150}}}, self.preset)
        self.out = os.path.join(self.d, "out")
        probe = render.probe
        render.probe = lambda v: (320, 240)
        self.addCleanup(setattr, render, "probe", probe)

    def render(self, plan):
        p = os.path.join(self.d, "plan.json"); dump(plan, p)
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            render.main(["--preset", self.preset, "--video", self.video, "--plan", p, "--out", self.out])
        return buf.getvalue()

    def pixel(self, t, x, y):
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t}", "-i", os.path.join(self.out, "final.mov"),
                            "-frames:v", "1", "-vf", f"crop=2:2:{x}:{y}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           capture_output=True, check=True).stdout
        return "red" if r[0] > r[2] else "blue"

    def test_slide_only_jcut(self):
        # A = 0.3-1.0 s (red), B = 2.0-2.7 s (blue); slide waits 0.4 s: from 0.7 to 1.1 s of the final video the
        # camera is already B (blue) and the slide still shows A's footage from 1.0-1.4 s (red)
        plan = [{"s": 0.3, "e": 1.0, "ev": [[0, 0.6, "Um."]]},
                {"s": 2.0, "e": 2.7, "ev": [[0.1, 0.6, "Dois."]], "j": [0.4, "slide"]}]
        log = self.render(plan)
        self.assertIn("3 / 3 clips ready", log); self.assertIn("1 J-cuts", log)
        q, a, steps = frames_and_samples(os.path.join(self.out, "final.mov"))
        self.assertEqual((q, a, len(steps)), (42, 42 * 1600, 1))  # 21 + 21 frames; sound = picture
        cam, sl = (90, 50), (90, 180)
        self.assertEqual((self.pixel(0.9, *cam), self.pixel(0.9, *sl)), ("blue", "red"))
        self.assertEqual((self.pixel(1.2, *cam), self.pixel(1.2, *sl)), ("blue", "blue"))
        self.assertEqual(json.load(open(os.path.join(self.out, "c01.json")))["frames"], 12)

    def test_hard_cut_plan_renders_like_before(self):
        plan = [{"s": 0.3, "e": 1.0, "ev": [[0, 0.6, "Um."]]}, {"s": 2.0, "e": 2.7, "ev": [[0.1, 0.6, "Dois."]]}]
        self.assertIn("2 / 2 clips ready", self.render(plan))
        self.assertEqual((self.pixel(0.6, 90, 50), self.pixel(0.75, 90, 50)), ("red", "blue"))


if __name__ == "__main__":
    unittest.main()
