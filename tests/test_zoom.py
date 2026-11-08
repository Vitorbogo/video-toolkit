"""Optional zoom: only the camera zooms in, and only when asked (--zoom or "z" in plan.json).

    python3 -m unittest discover tests
"""
import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from vtk import cuts
from vtk.render import EYE_LINE, zoom_crop
from test_cuts import invariants

CAM = [1231, 692, 1287, 461]  # camera_crop of presets/tiktok-vertical.json


def words(spec):
    return [{"w": w, "start": s, "end": e} for w, s, e in spec]


# three sentences separated by long pauses: two cuts of more than 1 s
WS = words([("Primeira", 0.0, 0.5), ("frase.", 0.6, 1.2),
            ("Segunda", 4.0, 4.5), ("frase.", 4.6, 5.2),
            ("Terceira", 8.0, 8.5), ("frase.", 8.6, 9.2)])


class ZoomCrop(unittest.TestCase):
    def test_no_zoom_returns_the_preset_crop(self):
        self.assertEqual(zoom_crop(CAM, 1.0), CAM)

    def test_zoom_shrinks_the_crop_keeping_aspect_and_inside(self):
        w, h, x, y = zoom_crop(CAM, 1.1)
        self.assertEqual((w % 2, h % 2), (0, 0))
        self.assertAlmostEqual(w / h, CAM[0] / CAM[1], places=2)
        self.assertLess(w, CAM[0])
        self.assertTrue(CAM[2] <= x and x + w <= CAM[2] + CAM[0])
        self.assertTrue(CAM[3] <= y and y + h <= CAM[3] + CAM[1])

    def test_eye_line_stays_at_the_same_height(self):
        w, h, x, y = zoom_crop(CAM, 1.2)
        eyes = CAM[3] + EYE_LINE * CAM[1]
        self.assertAlmostEqual((eyes - y) / h, EYE_LINE, places=2)


class ZoomInPlan(unittest.TestCase):
    def test_off_by_default(self):
        plan, _, _ = cuts.decide(WS, {}, total=10.0, lang="pt")
        invariants(self, plan)
        self.assertGreater(len(plan), 1)
        self.assertFalse(any("z" in c for c in plan))

    def test_zoom_alternates_at_large_cuts(self):
        plan, removed, maybe = cuts.decide(WS, {}, total=10.0, zoom=1.1, lang="pt")
        invariants(self, plan)
        self.assertEqual([c.get("z", 1) for c in plan], [1, 1.1, 1])
        self.assertIn("Camera zoom", cuts.report(plan, removed, maybe, 10.0))


if __name__ == "__main__":
    unittest.main()
