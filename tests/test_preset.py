import json, os, sys, tempfile, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from vtk import preset


class Load(unittest.TestCase):
    def write(self, d, name, data):
        p = os.path.join(d, name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return p

    def test_override_merges_onto_base(self):
        with tempfile.TemporaryDirectory() as d:
            self.write(d, "base.json", {"source": {"camera_crop": [1, 2, 3, 4], "slide_crop": [5, 6, 7, 8]},
                                        "audio": {"loudnorm": {"I": -14, "TP": -1.5}}})
            v = self.write(d, "v.json", {"base": os.path.join(d, "base.json"),
                                         "source": {"camera_crop": [9, 9, 9, 9]}})
            P = preset.load(v)
            self.assertEqual(P["source"]["camera_crop"], [9, 9, 9, 9])
            self.assertEqual(P["source"]["slide_crop"], [5, 6, 7, 8])
            self.assertEqual(P["audio"]["loudnorm"]["I"], -14)
            self.assertNotIn("base", P)

    def test_full_copy_still_loads(self):
        P = preset.load("presets/tiktok-vertical.json")
        self.assertIn("subtitles", P)

    def test_circular_base_fails(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = os.path.join(d, "a.json"), os.path.join(d, "b.json")
            self.write(d, "a.json", {"base": b})
            self.write(d, "b.json", {"base": a})
            with self.assertRaises(SystemExit):
                preset.load(a)


if __name__ == "__main__":
    unittest.main()
