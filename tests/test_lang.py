"""Spoken language: presets per language and detection from the transcript (src/vtk/lang.py).

    python3 -m unittest discover tests
"""
import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from vtk import lang

PT = ("Hoje eu quero mostrar para vocês como eu edito os meus vídeos curtos usando só ferramentas locais, sem "
      "mandar nada para a internet. O processo começa com a gravação da tela junto com a câmera.")
EN = ("Today I want to show you how I edit my short videos using only local tools, without sending anything to "
      "the internet. The process starts with the screen recording together with the camera.")


class Presets(unittest.TestCase):
    def test_supported(self):
        self.assertEqual(lang.supported(), ["en", "pt"])

    def test_every_preset_has_the_lists(self):
        for code in lang.supported():
            p = lang.load(code)
            for k in ("fillers", "extra_fillers", "short_words", "break_before", "function_words"):
                self.assertTrue(p[k] or k == "extra_fillers", (code, k))
            self.assertTrue(all(w == w.lower() for w in p["fillers"]), code)

    def test_unknown_language(self):
        with self.assertRaises(ValueError):
            lang.load("es")


class Detect(unittest.TestCase):
    def test_portuguese(self):
        self.assertEqual(lang.detect(PT), "pt")

    def test_english(self):
        self.assertEqual(lang.detect(EN), "en")
        self.assertEqual(lang.detect("It’s what we’re going to do, and it’s free."), "en")

    def test_word_list_from_transcript(self):
        self.assertEqual(lang.detect([{"w": w, "start": 0, "end": 0} for w in EN.split()]), "en")

    def test_too_short_or_no_function_words(self):
        for t in ("", "Ok.", "Primeira frase. Segunda frase.", "ChatGPT Claude Gemini.", "Estou com um contrato."):
            self.assertIsNone(lang.detect(t), t)

    def test_words_shared_by_both_languages_dont_count(self):
        # "a", "no", "do", "as", "me" are function words in both
        self.assertIsNone(lang.detect("a no do as me a no do as me a no do as me"))

    def test_portuguese_heavy_on_the_article_a(self):
        # "a" is the most common Portuguese word; it must not tip PT speech towards English
        self.assertNotEqual(lang.detect("A IA vai ajudar a equipe a fazer a tarefa toda."), "en")
        for t in ("Então, a primeira coisa que você precisa entender é que a IA não sabe a resposta. Ela calcula a "
                  "palavra mais provável, e a chance de acertar sobe muito quando a pergunta traz o contexto todo.",
                  "Quando eu comecei a usar a IA no trabalho, a primeira coisa que eu percebi foi que a resposta mudava."):
            self.assertEqual(lang.detect(t), "pt", t)

    def test_mixed_without_a_clear_winner(self):
        self.assertIsNone(lang.detect("isso é de você and the it is"))

    def test_english_terms_in_portuguese_speech(self):
        self.assertEqual(lang.detect("Eu abro o ChatGPT, colo o prompt e peço um resumo do contract review que "
                                     "fiz para o meu cliente, porque isso é o que mais tempo leva."), "pt")

    def test_english_filler_um_does_not_count_as_portuguese(self):
        self.assertEqual(lang.detect("Um, so, um, the thing is, uh, I think it works and um, that is it."), "en")


if __name__ == "__main__":
    unittest.main()
