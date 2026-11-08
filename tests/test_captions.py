"""Captions with the spoken word highlighted: each word's timing, blocks and the drawn strip.

    python3 -m unittest discover tests
"""
import json, os, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from vtk import captions, cuts

SUB = json.load(open(os.path.join(ROOT, "presets/tiktok-vertical.json"), encoding="utf-8"))["subtitles"]


class Words(unittest.TestCase):
    def test_uses_each_word_timing(self):
        ws = captions.words([1.0, 3.0, "uma frase curta"], [1.0, 1.4, 2.2])
        self.assertEqual(ws, [(1.0, 1.4, "uma"), (1.4, 2.2, "frase"), (2.2, 3.0, "curta")])

    def test_text_edited_in_review_falls_back_to_estimate(self):
        # the author changed "Ya" to "a IA": 3 words, 2 times -> split by length, without breaking
        ws = captions.words([0.0, 2.0, "Use a IA"], [0.0, 1.0])
        self.assertEqual([w[2] for w in ws], ["Use", "a", "IA"])
        self.assertEqual((ws[0][0], ws[-1][1]), (0.0, 2.0))
        self.assertTrue(all(a < b for a, b, _ in ws))

    def test_old_plan_without_wt(self):
        st = captions.states({"ev": [[0.0, 1.0, "oi tudo"], [1.5, 2.0, "bem"]]}, 60)
        self.assertEqual([(b, i) for _, _, b, i in st], [(["oi", "tudo"], 0), (["oi", "tudo"], 1), (["bem"], 0)])


class States(unittest.TestCase):
    def test_long_event_becomes_blocks_and_nothing_overlaps(self):
        text = "uma frase bem comprida que nao cabe inteira na tela de uma vez so e precisa dividir"
        n = len(text.split())
        st = captions.states({"ev": [[0.0, 6.0, text]], "wt": [[i * 0.25 for i in range(n)]]}, 30)
        self.assertGreater(len({tuple(b) for _, _, b, _ in st}), 1)
        self.assertTrue(all(len(" ".join(b)) <= 30 for _, _, b, _ in st))
        self.assertTrue(all(a1 <= a2 and z1 <= a2 + 1e-9 for (a1, z1, _, _), (a2, _, _, _) in zip(st, st[1:])))


class FromCuts(unittest.TestCase):
    def test_cuts_writes_wt_parallel_to_ev(self):
        ws = [{"w": w, "start": s, "end": e} for w, s, e in
              [("Primeira", 0.0, 0.5), ("frase.", 0.6, 1.2), ("Segunda", 1.4, 1.9), ("frase.", 2.0, 2.5)]]
        plan, _, _ = cuts.decide(ws, {}, total=3.0, lang="pt")
        for c in plan:
            self.assertEqual([len(t.split()) for _, _, t in c["ev"]], [len(x) for x in c["wt"]])


class Overlay(unittest.TestCase):
    def test_writes_png_and_concat_list(self):
        with tempfile.TemporaryDirectory() as d:
            lst, height = captions.overlay({"ev": [[0.5, 1.5, "Teste da legenda."]], "wt": [[0.5, 0.9, 1.1]]},
                                          d, "c00-cap", SUB, 540, 0.5)
            txt = open(lst, encoding="utf-8").read()
            self.assertTrue(txt.startswith("ffconcat version 1.0"))
            self.assertEqual(txt.count(".png'"), 6)  # leading empty + 3 words + trailing empty + required repeat
            self.assertEqual(height % 2, 0)


if __name__ == "__main__":
    unittest.main()
