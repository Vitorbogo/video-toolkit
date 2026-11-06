"""face.py (neutral-face score) and the "auto" in thumb.py/publish.py.

    python3 -m unittest discover tests
"""
import contextlib, io, json, math, os, shutil, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from vtk import face, thumb, publish

WEIGHTS = face.DEFAULTS["weights"]


def quiet():
    return contextlib.redirect_stdout(io.StringIO())


class Score(unittest.TestCase):
    def test_neutral_scores_lower_than_blink_and_open_mouth(self):
        neutral = face.penalties({"eyeBlinkLeft": 0.1, "eyeBlinkRight": 0.1})
        blink = face.penalties({"eyeBlinkLeft": 0.9, "eyeBlinkRight": 0.8})
        talking = face.penalties({"jawOpen": 0.5})
        self.assertLess(face.score(neutral, WEIGHTS), face.score(blink, WEIGHTS))
        self.assertLess(face.score(neutral, WEIGHTS), face.score(talking, WEIGHTS))

    def test_pose_and_sharpness(self):
        self.assertAlmostEqual(face.penalties({}, yaw=15, pitch=0)["pose"], 0.5)
        self.assertEqual(face.penalties({}, yaw=90)["pose"], 1.0)
        self.assertEqual(face.penalties({}, sharpness=2.0)["sharpness"], 0.0)  # sharper than the median: no penalty
        self.assertAlmostEqual(face.penalties({}, sharpness=0.25)["sharpness"], 0.75)

    def test_baseline_subtracts_the_persons_normal(self):
        dets = [face.penalties({"browInnerUp": 0.4 + i / 100}) for i in range(20)] + [None]
        base = face.baseline(dets)
        self.assertAlmostEqual(base["brow"], 0.41, places=2)
        p = face.subtract_baseline(face.penalties({"browInnerUp": 0.45}, yaw=15), base)
        self.assertAlmostEqual(p["brow"], 0.04, places=2)
        self.assertAlmostEqual(p["pose"], 0.5)  # pose is not an expression: not subtracted
        self.assertEqual(face.subtract_baseline(face.penalties({}), base)["brow"], 0.0)  # never negative

    def test_smooth_uses_worst_neighbour_and_no_face_spreads(self):
        self.assertEqual(face.smooth([1, 0, 1, 0.1, 0.1, 0.1]), [1, 1, 1, 1, 0.1, 0.1])
        self.assertEqual(face.smooth([0.1, None, 0.1, 0.1]), [None, None, None, 0.1])

    def test_pick_respects_spacing_and_margins(self):
        ts = [i * 0.25 for i in range(40)]  # 10 s
        scores = [1.0] * 40
        scores[0] = 0.0; scores[8] = 0.1; scores[9] = 0.05; scores[30] = 0.2; scores[39] = 0.0
        idx = face.pick(ts, scores, 3, 1.5, start=0.5, end=9.5)
        self.assertEqual(idx[:2], [9, 30])  # 0 and 39 fall in the margin; 8 is too close to 9
        self.assertTrue(all(abs(ts[a] - ts[b]) >= 1.5 for a in idx for b in idx if a != b))

    def test_pose_from_matrix(self):
        a = math.radians(20)
        yaw = [[math.cos(a), 0, math.sin(a), 0], [0, 1, 0, 0], [-math.sin(a), 0, math.cos(a), 0], [0, 0, 0, 1]]
        y, p = face.pose(yaw)
        self.assertAlmostEqual(y, 20, places=3); self.assertAlmostEqual(p, 0, places=3)
        scaled = [[2 * v for v in row[:3]] + [0] for row in yaw[:3]] + [[0, 0, 0, 1]]
        self.assertAlmostEqual(face.pose(scaled)[0], 20, places=3)  # face scale does not change the angle


R = {"video": "final.mp4", "candidates": [{"t": 12.5, "score": 0.3, "face_x": 0.42},
                                          {"t": 30.0, "score": 0.4, "face_x": 0.55}],
     "all": [[10.0, 0.5, 0.40], [20.0, 0.6, 0.61], [30.0, 0.4, 0.55]]}


class ThumbAuto(unittest.TestCase):
    def test_auto_by_variant_position_and_auto_n(self):
        o = thumb.auto({"time_s": "auto", "face_x": "auto"}, R, 1)
        self.assertEqual((o["time_s"], o["face_x"]), (30.0, 0.55))
        o = thumb.auto({"time_s": "auto:1", "face_x": None}, R, 1)
        self.assertEqual((o["time_s"], o["face_x"]), (12.5, None))

    def test_face_x_auto_with_fixed_time_uses_nearest_frame(self):
        self.assertEqual(thumb.auto({"time_s": 19, "face_x": "auto"}, R, 0)["face_x"], 0.61)

    def test_missing_candidate_is_an_error(self):
        with self.assertRaises(SystemExit) as e:
            thumb.auto({"time_s": "auto:3", "face_x": None}, R, 0)
        self.assertIn("face.json has 2", str(e.exception))

    def test_validation_accepts_auto_and_rejects_junk(self):
        thumb.validate({"title": "x", "time_s": "auto", "face_x": "auto"})
        thumb.validate({"title": "x", "variants": [{"name": "A", "time_s": "auto:2"}]})
        for bad in ({"time_s": "automatic"}, {"time_s": "auto:0"}, {"time_s": 3, "face_x": "middle"}):
            with self.assertRaises(SystemExit):
                thumb.validate({"title": "x", **bad})
        self.assertTrue(thumb.uses_auto({"title": "x", "time_s": 3, "youtube": {"face_x": "auto"}}))
        self.assertFalse(thumb.uses_auto({"title": "x", "time_s": 3}))

    def test_missing_face_json_explains_what_to_run(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit) as e:
                thumb.read_face(os.path.join(d, "face.json"), "final.mp4")
            self.assertIn("face.py", str(e.exception))


class PublishUsesActualTime(unittest.TestCase):
    def test_covers_json_time_beats_thumb_auto(self):
        with open(os.path.join(ROOT, "presets", "publish.json"), encoding="utf-8") as f: P = json.load(f)
        M = {"titles": ["Title"], "description": "d", "tiktok_caption": "l", "hashtags_reason": "m",
             "hashtags": {"tiktok": ["#a"], "youtube": ["#a"]}, "cover": {"variant": "A", "reason": "neutral"}}
        T = {"variants": [{"name": "A", "vertical": {"time_s": "auto"}}]}
        md = publish.render("x", M, P, 40.0, T, [], {"A": {"vertical": {"time_s": 12.5, "face_x": None}}})
        self.assertIn("frame at ~12.5 s", md)
        self.assertNotIn("auto", publish.render("x", M, P, 40.0, T, []))  # without covers.json: does not write "~auto s"


MODEL = os.environ.get("VTK_FACE_MODEL", face.MODEL)


@unittest.skipUnless(shutil.which("ffmpeg") and os.path.isfile(MODEL), "needs ffmpeg and models/face_landmarker.task")
class Integration(unittest.TestCase):
    def test_video_without_face_gives_clear_error(self):
        try:
            import mediapipe  # noqa: F401
        except ImportError:
            self.skipTest("mediapipe not installed")
        import subprocess
        from vtk import preset
        with tempfile.TemporaryDirectory() as d:
            v = os.path.join(d, "v.mp4")
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=10:d=3",
                            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", v], check=True)
            with self.assertRaises(SystemExit) as e:
                face.analyze(v, preset.load("presets/thumbnail.json"), MODEL)
            self.assertIn("no face", str(e.exception))


if __name__ == "__main__":
    unittest.main()
