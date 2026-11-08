"""The language filler lists (presets/fillers-pt.json, presets/fillers-en.json) applied by the third-party engine.

    python3 -m unittest discover tests
"""
import json, os, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from vtk import engine as ev


def preset(code):
    with open(os.path.join(ROOT, f"presets/fillers-{code}.json"), encoding="utf-8") as f:
        return json.load(f)


PT, EN = preset("pt"), preset("en")


def words(text, gap=0.1):
    """Words of 0.3 s each with a pause between them (enough for the engine to accept the cut)."""
    out, t = [], 0.0
    for w in text.split():
        out.append({"w": w, "start": round(t, 3), "end": round(t + 0.3, 3)}); t += 0.3 + gap
    return out


def cut(text, edit):
    ws = words(text)
    reason, _ = ev.mark(ws, edit)
    return [w["w"] for w, r in zip(ws, reason) if r]


class FillersPT(unittest.TestCase):
    def test_engine_default_cuts_the_article_um(self):
        # why the preset exists: without it, "um" (Portuguese article) becomes a filler
        self.assertEqual(cut("Estou com um contrato.", {}), ["um"])

    def test_preset_keeps_article_um_and_verb_e(self):
        self.assertEqual(cut("Estou com um contrato e é um bom exemplo.", PT), [])

    def test_hesitations_are_cut(self):
        self.assertEqual(cut("O contexto ééé é importante, hum, sempre.", PT), ["ééé", "hum,"])

    def test_agreement_stays(self):
        self.assertEqual(cut("Uhum, aham, exatamente.", PT), [])

    def test_crutch_word_only_next_to_comma(self):
        self.assertEqual(cut("Isso é importante, né, porque muda tudo.", PT), ["né,"])
        self.assertEqual(cut("Então, quando você fala isso.", PT), ["Então,"])
        self.assertEqual(cut("Esse tipo de contrato é comum.", PT), [])
        self.assertEqual(cut("E então ela responde.", PT), [])

    def test_meaningful_words_stay(self):
        for s in ("Ele não sabe, mas tenta.", "Enfim, chegamos ao ponto.", "Ele é desse tipo assim calado.", "Hã? Como assim?"):
            self.assertEqual(cut(s, PT), [], s)

    def test_known_limit_concluding_entao(self):
        # the engine cuts a crutch word with a comma before OR after; check edit-plan.md
        self.assertEqual(cut("Se chover, então fica em casa.", PT), ["então"])


class FillersEN(unittest.TestCase):
    def test_hesitations_are_cut(self):
        self.assertEqual(cut("So, um, the contract is, uh, ready.", EN), ["um,", "uh,"])
        self.assertEqual(cut("Hmm, let me erm check the umm numbers.", EN), ["Hmm,", "erm", "umm"])

    def test_interjections_and_agreement_stay(self):
        for s in ("Ah, I see.", "Oh, right.", "Mm-hmm, yeah.", "Uh-huh, exactly."):
            self.assertEqual(cut(s, EN), [], s)

    def test_words_that_look_like_fillers_stay(self):
        for s in ("She went to the ER, then home.", "Leave a 5 mm gap.", "To err is human."):
            self.assertEqual(cut(s, EN), [], s)

    def test_basically_only_next_to_comma(self):
        self.assertEqual(cut("Basically, it is a list.", EN), ["Basically,"])
        self.assertEqual(cut("It is, basically, a list.", EN), ["basically,"])
        self.assertEqual(cut("It is free, basically the same.", EN), ["basically"])  # comma before is enough
        self.assertEqual(cut("It is basically a list.", EN), [])

    def test_crutch_words_with_meaning_stay(self):
        for s in ("Things, like emails, pile up.", "I think so, but not now.", "No, actually, it is free.",
                  "It works well, and fast.", "It is free, right?", "Do you know what I mean?", "It is kind of slow.",
                  "Okay, let us start.", "Honestly, I like it."):
            self.assertEqual(cut(s, EN), [], s)

    def test_no_multi_word_crutch_phrases(self):
        # the engine cuts multi-word extra_fillers anywhere, comma or not ("do you know" would lose "you know")
        self.assertTrue(all(len(f.split()) == 1 for f in EN["extra_fillers"]), EN["extra_fillers"])


if __name__ == "__main__":
    unittest.main()
