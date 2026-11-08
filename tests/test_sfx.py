"""Sound effects: times in the final video, sfx.json validation and the mix in postaudio.

    python3 -m unittest discover tests
"""
import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from vtk import sfx


class Timeline(unittest.TestCase):
    def test_segments_add_up_in_the_final_video(self):
        plan = [{"s": 10.0, "e": 14.0, "ev": []}, {"s": 30.0, "e": 32.5, "ev": []}]
        self.assertEqual([(u, v) for u, v, _ in sfx.timeline(plan)], [(0.0, 4.0), (4.0, 6.5)])


class Check(unittest.TestCase):
    def test_valid_list(self):
        self.assertEqual(sfx.check([{"t": 1.0, "sound": "whoosh-short"}, {"t": 7.0, "sound": "pop-blip", "vol": 0.2}], 10), [])

    def test_unknown_sound_and_outside_the_video(self):
        errors = sfx.check([{"t": 1.0, "sound": "pop"}, {"t": 99.0, "sound": "click"}], 10)
        self.assertTrue(any("'pop'" in e for e in errors))
        self.assertTrue(any("outside the video" in e for e in errors))

    def test_old_portuguese_names_say_the_new_one(self):
        errors = sfx.check([{"t": 1.0, "som": "clique"}, {"t": 5.0, "sound": "whoosh-curto"}], 10)
        self.assertTrue(any("'som'" in e and "'sound'" in e for e in errors), errors)
        self.assertTrue(any("'whoosh-short'" in e for e in errors), errors)

    def test_effects_too_close(self):
        errors = sfx.check([{"t": 1.0, "sound": "click"}, {"t": 3.0, "sound": "pop-blip"}])
        self.assertTrue(any("less than" in e for e in errors))


class Mix(unittest.TestCase):
    def test_whoosh_starts_early_to_hit_on_time(self):
        f = sfx.mix_filter([{"t": 11.0, "sound": "whoosh-short"}])
        hit = sfx.CATALOG["whoosh-short"]["hit"]
        self.assertIn(f"[1:a]adelay={int(round((11.0 - hit) * 1000))}:all=1", f)
        self.assertIn("amix=inputs=2:normalize=0:duration=first[mix]", f)

    def test_list_vol_overrides_the_default(self):
        self.assertIn("volume=0.1[s0]", sfx.mix_filter([{"t": 2.0, "sound": "click", "vol": 0.1}]))

    def test_catalog_has_a_file_for_each_sound(self):
        for sound in sfx.CATALOG:
            self.assertTrue(os.path.exists(sfx.path(sound)), sound)


if __name__ == "__main__":
    unittest.main()
