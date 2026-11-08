"""cuts.decide: Parakeet words -> render.py's plan.json, with engine.py deciding the cuts.

    python3 -m unittest discover tests
"""
import io, json, os, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from vtk import cuts


def words(spec):
    """[(word, start, end), ...] -> transcript.json format"""
    return [{"w": w, "start": s, "end": e} for w, s, e in spec]


def text_of(plan):
    return " ".join(cuts.caption_texts(plan))


def invariants(tc, plan, fps=30.0):
    """What render.py expects from any plan.json: increasing pieces, no overlap, on the frame, at least 0.4 s long,
    and captions/blurs inside the piece."""
    tc.assertTrue(plan, "empty plan")
    for k, c in enumerate(plan):
        d = c["e"] - c["s"]
        tc.assertGreaterEqual(c["s"], 0, c)
        tc.assertGreaterEqual(d, 0.4 - 1e-6, c)
        if k: tc.assertGreater(c["s"], plan[k - 1]["e"], (plan[k - 1], c))
        for t in (c["s"], c["e"]):
            tc.assertAlmostEqual(t * fps, round(t * fps), delta=1e-3, msg=f"{t} off the frame")
            tc.assertEqual(t, round(t, 6))
        for x0, x1, t in c["ev"]:
            tc.assertTrue(0 <= x0 < x1 <= d + 1e-6, (x0, x1, t, d))
        tc.assertLessEqual(c.get("z", 1), 1.2)
        for b in c.get("blur", []):
            tc.assertTrue(0 <= b[0] < b[1] <= d + 1e-6 and len(b) == 6, (b, d))


def decide(tc, ws, edit=None, lang="pt", **kw):
    plan, removed, maybe = cuts.decide(ws, edit or {}, lang=lang, **kw)
    invariants(tc, plan, kw.get("fps", 30.0))
    return plan, removed, maybe


def phrase(text, t0=0.0, dur=0.3, gap=0.1):
    """Words of dur seconds with gap between them, from t0."""
    out, t = [], t0
    for w in text.split():
        out.append((w, round(t, 3), round(t + dur, 3))); t += dur + gap
    return out


class Decide(unittest.TestCase):
    def test_article_stays_and_hesitation_leaves_video_and_captions(self):
        ws = words([("Estou", 0.0, 0.3), ("com", 0.4, 0.6), ("um", 0.7, 0.8), ("contrato.", 0.9, 1.4),
                    ("ééé", 1.6, 2.4), ("Quero", 2.6, 2.9), ("um", 3.0, 3.1), ("resumo.", 3.2, 3.8)])
        plan, removed, _ = decide(self, ws, total=4.5)
        self.assertEqual(text_of(plan), "Estou com um contrato. Quero um resumo.")
        # no bit of the "ééé" (1.6 to 2.4 s) may stay: the engine leaves the "breath" inside it
        for c in plan:
            self.assertFalse(c["s"] < 2.4 and c["e"] > 1.6, c)
        self.assertTrue(any("filler" in r[2] and "ééé" in r[3] for r in removed), removed)

    def test_fixed_caption_relative_to_the_piece_after_long_pause(self):
        ws = words([("Use", 0.0, 0.3), ("a", 0.4, 0.5), ("Ya.", 0.6, 1.0),
                    ("Ela", 5.0, 5.3), ("resume.", 5.4, 6.0)])
        plan, _, _ = decide(self, ws, {"replace": {"Ya": "IA"}}, total=6.5)
        self.assertEqual(len(plan), 2)  # the 4 s pause becomes a cut
        second = plan[1]
        self.assertEqual([t for _, _, t in plan[0]["ev"]], ["Use a IA."])
        x0, x1, t = second["ev"][0]
        self.assertEqual(t, "Ela resume.")
        self.assertAlmostEqual(second["s"] + x0, 5.0, delta=0.01)
        self.assertAlmostEqual(second["s"] + x1, 6.0, delta=0.01)

    def test_long_sentence_breaks_at_char_limit(self):
        text = "Quero um resumo executivo com objeto obrigações principais cláusulas de rescisão e riscos."
        plan, _, _ = decide(self, words(phrase(text)), total=6.0, max_chars=30)
        evs = [t for c in plan for _, _, t in c["ev"]]
        self.assertEqual(" ".join(evs), text)
        self.assertTrue(all(len(t) <= 30 for t in evs), evs)

    def test_balanced_break_without_orphan_word(self):
        # 69 characters with a 60 limit: it used to give "... tenho que arrumar" + "o texto." (0.7 s on screen)
        text = "O chat acha que eu sou homem e toda vez eu tenho que arrumar o texto."
        plan, _, _ = decide(self, words(phrase(text, dur=0.2, gap=0.05)), total=5.0)
        evs = plan[0]["ev"]
        self.assertEqual([t for _, _, t in evs], ["O chat acha que eu sou homem", "e toda vez eu tenho que arrumar o texto."])

    def test_sentence_crossing_a_cut_stays_whole_on_both_sides(self):
        # the "ééé" mid-sentence becomes a cut: "Hoje" alone in the 1st piece would be an orphan caption
        ws = words(phrase("Bom dia.", 0.0) + [("Hoje", 1.2, 1.5), ("ééé", 1.8, 2.6)] + phrase("o contrato tem três cláusulas.", 2.9))
        plan, _, _ = decide(self, ws, total=5.5)
        self.assertEqual(len(plan), 2)
        self.assertEqual(plan[0]["ev"][-1][2], "Hoje o contrato tem três cláusulas.")
        self.assertEqual(plan[1]["ev"][0][:1] + plan[1]["ev"][0][2:], [0.0, "Hoje o contrato tem três cláusulas."])
        self.assertAlmostEqual(plan[0]["ev"][-1][1], plan[0]["e"] - plan[0]["s"], places=5)
        self.assertEqual(text_of(plan), "Bom dia. Hoje o contrato tem três cláusulas.")

    def test_short_caption_joins_neighbour_and_stays_1_s(self):
        ws = words([("Sim.", 0.0, 0.3), ("Isso", 0.5, 0.8), ("mesmo.", 0.9, 1.3), ("Ok.", 1.5, 1.8)])
        plan, _, _ = decide(self, ws, total=2.5)
        evs = plan[0]["ev"]
        self.assertEqual([t for _, _, t in evs], ["Sim. Isso mesmo. Ok."])
        self.assertGreaterEqual(evs[0][1] - evs[0][0], 1.0)

    def test_edit_json_crutch_word_adds_to_the_pt_list(self):
        ws = words([("Isso", 0.0, 0.3), ("muda,", 0.4, 0.8), ("né,", 1.0, 1.3), ("sabe,", 1.5, 1.8), ("tudo.", 2.0, 2.4)])
        plan, _, _ = decide(self, ws, {"extra_fillers": ["sabe"]}, total=3.0)
        self.assertEqual(text_of(plan), "Isso muda, tudo.")

    def test_word_glued_to_filler_is_not_cut(self):
        # "Quero" starts 20 ms after the "ééé": less than a frame
        ws = words([("Contrato.", 0.0, 0.5), ("ééé", 0.6, 1.21), ("Quero", 1.23, 1.5), ("resumo.", 1.6, 2.0)])
        plan, removed, _ = decide(self, ws, total=2.5)
        self.assertEqual(text_of(plan), "Contrato. Quero resumo.")
        quero = next(c for c in plan if "Quero" in " ".join(t for _, _, t in c["ev"]))
        self.assertLessEqual(quero["s"], 1.23 - cuts.PRE_ROLL + 1e-6)  # the skill's pre-roll before the word

    def test_filler_glued_on_both_sides_comes_back_to_captions(self):
        # cutting the "hum" would leave a jump cut under 0.12 s: no cut, and the caption shows what is heard
        ws = words([("Isso", 0.0, 0.4), ("é", 0.45, 0.6), ("hum", 0.62, 0.74), ("bom.", 0.76, 1.2)])
        plan, _, _ = decide(self, ws, total=1.6)
        self.assertEqual(len(plan), 1)
        self.assertEqual(text_of(plan), "Isso é hum bom.")

    def test_capital_after_removed_opening(self):
        ws = words(phrase("Isso é bom.", 0.0) + phrase("Então, quando você fala isso.", 1.5))
        plan, removed, _ = decide(self, ws, total=4.5)
        self.assertEqual(text_of(plan), "Isso é bom. Quando você fala isso.")

    def test_capital_at_start_after_manual_cut(self):
        ws = words(phrase("Bom dia. vamos lá.", 0.0))
        plan, _, _ = decide(self, ws, {"cut": [[0.0, 0.75]]}, total=2.5)
        self.assertEqual(text_of(plan), "Vamos lá.")

    def test_keep_keeps_what_the_skill_would_remove(self):
        ws = words(phrase("Isso muda, né, tudo."))
        plan, _, _ = decide(self, ws, {"keep": [[0.8, 1.1]]}, total=2.5)
        self.assertEqual(text_of(plan), "Isso muda, né, tudo.")

    def test_manual_cut(self):
        ws = words(phrase("Primeiro isso.", 0.0) + phrase("Frase abandonada que.", 1.5) + phrase("Depois aquilo.", 3.5))
        plan, removed, _ = decide(self, ws, {"cut": [[1.5, 2.6, "abandonada"]]}, total=5.0)
        self.assertEqual(text_of(plan), "Primeiro isso. Depois aquilo.")
        self.assertTrue(any("cut by hand" in r[2] and r[3] == "Frase abandonada que." for r in removed), removed)

    def test_manual_cut_without_words_warns(self):
        warnings = []
        ws = words(phrase("Primeiro isso.", 0.0) + phrase("Depois aquilo.", 3.5))
        decide(self, ws, {"cut": [[1.5, 2.6]]}, total=5.0, warnings=warnings)
        self.assertTrue(any("cut 1.5-2.6" in a and "trim" in a for a in warnings), warnings)

    def test_stutter(self):
        ws = words([("Isso", 0.0, 0.3), ("é", 0.5, 0.65), ("é", 0.85, 1.0), ("importante.", 1.1, 1.7)])
        plan, removed, _ = decide(self, ws, total=2.2)
        self.assertEqual(text_of(plan), "Isso é importante.")
        self.assertTrue(any("stutter" in r[2] for r in removed), removed)

    def test_retake_and_possible_retake(self):
        # unfinished sentence restarted right after: the skill cuts it on its own
        ws = words(phrase("O contrato tem", 0.0) + phrase("O contrato tem três cláusulas.", 2.0))
        plan, removed, _ = decide(self, ws, total=4.5)
        self.assertEqual(text_of(plan), "O contrato tem três cláusulas.")
        self.assertTrue(any("retake" in r[2] for r in removed), removed)
        # complete sentence repeated: only suggested; leaves the report when a manual cut removes the first one
        ws = words(phrase("O contrato tem duas.", 0.0) + phrase("O contrato tem três cláusulas.", 2.0))
        _, _, maybe = decide(self, ws, total=4.5)
        self.assertEqual(len(maybe), 1)
        plan, removed, maybe = decide(self, ws, {"cut": [[0.0, 1.5]]}, total=4.5)
        self.assertEqual(maybe, [])
        self.assertNotIn("Possible retakes", cuts.report(plan, removed, maybe, 4.5))

    def test_replace_with_more_than_one_word(self):
        ws = words(phrase("Abra o chat GPT agora e peça um resumo do contrato inteiro."))
        plan, _, _ = decide(self, ws, {"replace": {"chat GPT": "ChatGPT"}}, total=6.0, max_chars=12)
        evs = [t for c in plan for _, _, t in c["ev"]]
        self.assertTrue(any("ChatGPT" in t for t in evs), evs)  # the line break doesn't separate "chat" from "GPT"
        ws = words(phrase("Apelido, ocupação, mais."))
        plan, _, _ = decide(self, ws, {"replace": {"ocupação": "ocupação,"}}, total=2.0)
        self.assertEqual(text_of(plan), "Apelido, ocupação, mais.")

    def test_trim_removes_range_without_words_and_warns_on_words(self):
        # 0.45 s pause inside the sentence: the skill keeps it; trim removes it
        ws = words([("Um", 0.0, 0.4), ("dois", 0.5, 0.9), ("três", 1.35, 1.8), ("quatro.", 1.9, 2.4)])
        plan, removed, _ = decide(self, ws, total=3.0)
        self.assertEqual(len(plan), 1)
        warnings = []
        plan, removed, _ = decide(self, ws, {"trim": [[0.95, 1.25, "breath"]]}, total=3.0, warnings=warnings)
        self.assertEqual(len(plan), 2)
        self.assertAlmostEqual(plan[0]["e"], 0.95, delta=1 / 30)
        self.assertAlmostEqual(plan[1]["s"], 1.25, delta=1 / 30)
        self.assertTrue(any("trim" in r[2] for r in removed), removed)
        self.assertEqual(text_of(plan), "Um dois três quatro.")
        self.assertEqual(warnings, [])
        decide(self, ws, {"trim": [[0.95, 1.5]]}, total=3.0, warnings=warnings)
        self.assertTrue(any("três" in a for a in warnings), warnings)

    def test_zoom_from_edit_json(self):
        ws = words(phrase("Primeira frase.", 0.0) + phrase("Segunda frase.", 4.0) + phrase("Terceira frase.", 8.0))
        plan, _, _ = decide(self, ws, {"zoom": [[4.3, 1.15], [8.2, 1.5]]}, total=10.0)
        self.assertEqual([c.get("z", 1) for c in plan], [1, 1.15, 1.2])
        plan, _, _ = decide(self, ws, {"zoom": [[4.3, 1]]}, total=10.0, zoom=1.1)
        self.assertEqual([c.get("z", 1) for c in plan], [1, 1, 1])

    def test_blur_becomes_relative_blur_on_each_piece(self):
        ws = words(phrase("Primeira frase.", 0.0) + phrase("Segunda frase.", 4.0) + phrase("Terceira frase.", 8.0))
        plan, _, _ = decide(self, ws, {"blur": [[0.5, 4.3, 10, 20, 300, 400, "sidebar"]]}, total=10.0)
        a, b, c = plan
        self.assertEqual(a["blur"], [[round(0.5 - a["s"], 3), round(a["e"] - a["s"], 6), 10, 20, 300, 400]])
        self.assertEqual(b["blur"], [[0.0, round(4.3 - b["s"], 3), 10, 20, 300, 400]])
        self.assertNotIn("blur", c)

    def test_report_adds_up_the_real_ranges(self):
        ws = words(phrase("Bom dia.", 1.0) + [("ééé", 2.0, 2.6)] + phrase("Hoje tem contrato.", 2.9)
                   + phrase("Agora outra coisa.", 7.0))
        plan, removed, maybe = decide(self, ws, total=10.0)
        gaps = [(0.0, plan[0]["s"])] + [(p["e"], q["s"]) for p, q in zip(plan, plan[1:])] + [(plan[-1]["e"], 10.0)]
        self.assertEqual([(a, b) for a, b, _, _ in removed], [(a, b) for a, b in gaps if b - a >= 0.01])
        self.assertAlmostEqual(sum(b - a for a, b, _, _ in removed) + sum(c["e"] - c["s"] for c in plan), 10.0, places=6)
        md = cuts.report(plan, removed, maybe, 10.0)
        self.assertEqual(md.count("\n| "), len(removed) + 1)

    def test_audio_energy_extends_the_edges(self):
        # the sound of "frase." lasts until 1.35 s, past Parakeet's end (1.2 s); "Outra" starts sounding 0.12 s earlier
        ws = words([("Uma", 0.3, 0.7), ("frase.", 0.8, 1.2), ("Outra", 4.0, 4.4), ("frase.", 4.5, 5.0)])
        voice = [(0.3, 1.35), (3.88, 5.0)]
        db = [-20.0 if any(a <= k * 0.01 < b for a, b in voice) else -70.0 for k in range(600)]
        without, _, _ = decide(self, ws, total=6.0)
        with_db, _, _ = decide(self, ws, total=6.0, db=db, floor=-70.0)
        self.assertGreater(with_db[0]["e"], 1.35 + 0.03)
        self.assertGreater(with_db[0]["e"], without[0]["e"])
        self.assertLess(with_db[1]["s"], without[1]["s"])
        self.assertLessEqual(with_db[1]["s"], 3.88 - 0.03)
        # high noise floor (everything below floor + 6 dB counts as silence): the edge goes back near Parakeet's
        high, _, _ = decide(self, ws, total=6.0, db=db, floor=-15.0)
        self.assertLess(high[0]["e"], with_db[0]["e"])


class English(unittest.TestCase):
    def test_um_is_a_filler_in_english_and_an_article_in_portuguese(self):
        en = words([("I", 0.0, 0.2), ("have", 0.3, 0.6), ("a", 0.7, 0.8), ("contract.", 0.9, 1.4),
                    ("Um", 1.6, 2.2), ("I", 2.4, 2.5), ("want", 2.6, 2.9), ("a", 3.0, 3.1), ("summary.", 3.2, 3.8)])
        plan, removed, _ = decide(self, en, total=4.5, lang="en")
        self.assertEqual(text_of(plan), "I have a contract. I want a summary.")
        self.assertTrue(any("filler" in r[2] and "Um" in r[3] for r in removed), removed)
        pt = words([("Estou", 0.0, 0.3), ("com", 0.4, 0.6), ("um", 0.7, 0.8), ("contrato.", 0.9, 1.4)])
        plan, _, _ = decide(self, pt, total=2.0, lang="pt")
        self.assertEqual(text_of(plan), "Estou com um contrato.")

    def test_portuguese_hesitation_is_not_cut_in_english(self):
        ws = words(phrase("This is, né, important."))
        self.assertEqual(text_of(decide(self, ws, total=2.5, lang="en")[0]), "This is, né, important.")
        self.assertEqual(text_of(decide(self, ws, total=2.5, lang="pt")[0]), "This is, important.")

    def test_edit_json_fillers_add_to_the_english_list(self):
        ws = words(phrase("It is, like, really, basically, done."))
        plan, _, _ = decide(self, ws, {"extra_fillers": ["like"]}, total=3.0, lang="en")
        self.assertEqual(text_of(plan), "It is, really, done.")

    def test_english_line_break_avoids_ending_on_a_short_word(self):
        text = "We send the report to the client every week of the year."
        ws = words(phrase(text, dur=0.2, gap=0.05))
        plan, _, _ = decide(self, ws, total=5.0, max_chars=40, lang="en")
        self.assertEqual([t for _, _, t in plan[0]["ev"]], ["We send the report to the client", "every week of the year."])
        plan, _, _ = decide(self, ws, total=5.0, max_chars=40, lang="pt")  # Portuguese short words: "the" is not one
        self.assertEqual([t for _, _, t in plan[0]["ev"]], ["We send the report to the", "client every week of the year."])


class Language(unittest.TestCase):
    T_PT = {"words": words(phrase("Hoje eu quero mostrar para vocês como isso é feito."))}
    T_EN = {"words": words(phrase("Today I want to show you how this is done and why it is free."))}

    def test_order_edit_transcript_detection(self):
        both = dict(self.T_PT, lang="en")
        self.assertEqual(cuts.resolve_lang({"lang": "pt"}, both), ("pt", "edit.json"))
        self.assertEqual(cuts.resolve_lang({}, both), ("en", "transcript.json"))
        code, why = cuts.resolve_lang({}, self.T_PT)
        self.assertEqual(code, "pt"); self.assertIn("detected", why)
        self.assertEqual(cuts.resolve_lang({}, dict(self.T_EN, lang=None))[0], "en")

    def test_unsupported_language_says_how_to_fix(self):
        for args in (({"lang": "es"}, self.T_PT), ({}, dict(self.T_PT, lang="es"))):
            with self.assertRaises(SystemExit) as e:
                cuts.resolve_lang(*args)
            self.assertIn("'es'", str(e.exception)); self.assertIn("\"lang\" in videos/<name>/edit.json", str(e.exception))

    def test_undetectable_language_says_how_to_fix(self):
        with self.assertRaises(SystemExit) as e:
            cuts.resolve_lang({}, {"words": words(phrase("Primeira frase. Segunda frase."))})
        self.assertIn("could not tell", str(e.exception)); self.assertIn("edit.json", str(e.exception))

    def test_report_shows_the_language(self):
        plan, removed, maybe = decide(self, self.T_EN["words"], total=6.0, lang="en")
        md = cuts.report(plan, removed, maybe, 6.0, lang=("en", "transcript.json"))
        self.assertIn("Language: en (transcript.json)", md)
        self.assertIn("presets/fillers-en.json", md)


class Cli(unittest.TestCase):
    def test_force_keeps_bak_and_uses_edit_and_transcript_from_folder(self):
        with tempfile.TemporaryDirectory() as d:
            v = os.path.join(d, "videos", "x"); os.makedirs(v)
            ws = words(phrase("Primeiro isso.", 0.0) + phrase("Frase abandonada.", 1.5) + phrase("Depois aquilo.", 3.5))
            for f, data in (("transcript.json", {"words": ws}), ("edit.json", {"cut": [[1.5, 2.6]]}), ("plan.json", ["revisado"])):
                with open(os.path.join(v, f), "w", encoding="utf-8") as fh: json.dump(data, fh)
            stubs = dict(check_tools=lambda: None, probe=lambda p: (100, 100, 5.0, 60.0),
                         audio_energy=lambda p: ([], -60.0), visual_events=lambda p: ([], []))
            argv = ["cuts.py", "--video", "v.mov", "--name", "x"]
            with open(os.devnull, "w") as nul, mock.patch.object(cuts, "ROOT", d), \
                    mock.patch.multiple(cuts.ev, **stubs), mock.patch("sys.stdout", new=nul):
                with mock.patch.object(sys, "argv", argv), self.assertRaises(SystemExit):
                    cuts.main()  # without --force it doesn't overwrite
                with mock.patch.object(sys, "argv", argv + ["--force"]):
                    cuts.main()
            def read(f):
                with open(os.path.join(v, f), encoding="utf-8") as fh: return fh.read()
            self.assertEqual(json.loads(read("plan.json.bak")), ["revisado"])
            plan = json.loads(read("plan.json"))
            invariants(self, plan)
            self.assertEqual(text_of(plan), "Primeiro isso. Depois aquilo.")
            self.assertIn("cut by hand", read("edit-plan.md"))
            self.assertIn("Language: pt (detected from the transcript", read("edit-plan.md"))

    def test_english_transcript_and_lang_in_edit_json(self):
        with tempfile.TemporaryDirectory() as d:
            v = os.path.join(d, "videos", "x"); os.makedirs(v)
            ws = words(phrase("Today I want, um, to show you how it works.", 0.0))
            with open(os.path.join(v, "transcript.json"), "w", encoding="utf-8") as fh:
                json.dump({"lang": "en", "words": ws}, fh)
            stubs = dict(check_tools=lambda: None, probe=lambda p: (100, 100, 5.0, 60.0),
                         audio_energy=lambda p: ([], -60.0), visual_events=lambda p: ([], []))
            argv = ["cuts.py", "--video", "v.mov", "--name", "x", "--no-scenes"]
            out = io.StringIO()
            with mock.patch.object(cuts, "ROOT", d), mock.patch.multiple(cuts.ev, **stubs), mock.patch("sys.stdout", new=out):
                with mock.patch.object(sys, "argv", argv):
                    cuts.main()
                self.assertIn("language: en (transcript.json)", out.getvalue())
                with open(os.path.join(v, "plan.json"), encoding="utf-8") as fh:
                    self.assertEqual(text_of(json.load(fh)), "Today I want, to show you how it works.")
                with open(os.path.join(v, "edit.json"), "w", encoding="utf-8") as fh:
                    json.dump({"lang": "pt"}, fh)
                with mock.patch.object(sys, "argv", argv + ["--force"]):
                    cuts.main()
                with open(os.path.join(v, "edit-plan.md"), encoding="utf-8") as fh:
                    self.assertIn("Language: pt (edit.json)", fh.read())


if __name__ == "__main__":
    unittest.main()
