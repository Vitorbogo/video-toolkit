"""Legenda com a palavra falada em destaque: tempo de cada palavra, blocos e a faixa desenhada.

    python3 -m unittest discover tests
"""
import json, os, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from vtk import captions, cuts

SUB = json.load(open(os.path.join(ROOT, "presets/tiktok-vertical.json"), encoding="utf-8"))["subtitles"]


class Palavras(unittest.TestCase):
    def test_usa_o_tempo_de_cada_palavra(self):
        ws = captions.palavras([1.0, 3.0, "uma frase curta"], [1.0, 1.4, 2.2])
        self.assertEqual(ws, [(1.0, 1.4, "uma"), (1.4, 2.2, "frase"), (2.2, 3.0, "curta")])

    def test_texto_editado_na_revisao_cai_na_estimativa(self):
        # o autor trocou "Ya" por "a IA": 3 palavras, 2 tempos -> reparte pelo tamanho, sem quebrar
        ws = captions.palavras([0.0, 2.0, "Use a IA"], [0.0, 1.0])
        self.assertEqual([w[2] for w in ws], ["Use", "a", "IA"])
        self.assertEqual((ws[0][0], ws[-1][1]), (0.0, 2.0))
        self.assertTrue(all(a < b for a, b, _ in ws))

    def test_plano_antigo_sem_wt(self):
        st = captions.estados({"ev": [[0.0, 1.0, "oi tudo"], [1.5, 2.0, "bem"]]}, 60)
        self.assertEqual([(b, i) for _, _, b, i in st], [(["oi", "tudo"], 0), (["oi", "tudo"], 1), (["bem"], 0)])


class Estados(unittest.TestCase):
    def test_evento_longo_vira_blocos_e_nada_se_sobrepoe(self):
        texto = "uma frase bem comprida que nao cabe inteira na tela de uma vez so e precisa dividir"
        n = len(texto.split())
        st = captions.estados({"ev": [[0.0, 6.0, texto]], "wt": [[i * 0.25 for i in range(n)]]}, 30)
        self.assertGreater(len({tuple(b) for _, _, b, _ in st}), 1)
        self.assertTrue(all(len(" ".join(b)) <= 30 for _, _, b, _ in st))
        self.assertTrue(all(a1 <= a2 and z1 <= a2 + 1e-9 for (a1, z1, _, _), (a2, _, _, _) in zip(st, st[1:])))


class DoCuts(unittest.TestCase):
    def test_cuts_grava_wt_paralelo_ao_ev(self):
        ws = [{"w": w, "start": s, "end": e} for w, s, e in
              [("Primeira", 0.0, 0.5), ("frase.", 0.6, 1.2), ("Segunda", 1.4, 1.9), ("frase.", 2.0, 2.5)]]
        plan, _, _ = cuts.decide(ws, {}, total=3.0)
        for c in plan:
            self.assertEqual([len(t.split()) for _, _, t in c["ev"]], [len(x) for x in c["wt"]])


class Overlay(unittest.TestCase):
    def test_gera_png_e_lista_do_concat(self):
        with tempfile.TemporaryDirectory() as d:
            lista, alt = captions.overlay({"ev": [[0.5, 1.5, "Teste da legenda."]], "wt": [[0.5, 0.9, 1.1]]},
                                          d, "c00-leg", SUB, 540, 0.5)
            txt = open(lista, encoding="utf-8").read()
            self.assertTrue(txt.startswith("ffconcat version 1.0"))
            self.assertEqual(txt.count(".png'"), 6)  # vazio inicial + 3 palavras + vazio final + repetição exigida
            self.assertEqual(alt % 2, 0)


if __name__ == "__main__":
    unittest.main()
