"""cuts.decide: palavras do Parakeet -> plan.json do render.py, com o engine.py decidindo os cortes.

    python3 -m unittest discover tests
"""
import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from vtk import cuts


def words(spec):
    """[(palavra, inicio, fim), ...] -> formato do transcript.json"""
    return [{"w": w, "start": s, "end": e} for w, s, e in spec]


def text_of(plan):
    return " ".join(t for c in plan for _, _, t in c["ev"])


class Decide(unittest.TestCase):
    def test_artigo_fica_e_hesitacao_sai_do_video_e_da_legenda(self):
        ws = words([("Estou", 0.0, 0.3), ("com", 0.4, 0.6), ("um", 0.7, 0.8), ("contrato.", 0.9, 1.4),
                    ("ééé", 1.6, 2.4), ("Quero", 2.6, 2.9), ("um", 3.0, 3.1), ("resumo.", 3.2, 3.8)])
        plan, removed, _ = cuts.decide(ws, {}, total=4.5)
        self.assertEqual(text_of(plan), "Estou com um contrato. Quero um resumo.")
        # nenhum pedaco do "ééé" (1,6 a 2,4 s) pode ficar: o engine deixa a "respiracao" dentro dele
        for c in plan:
            self.assertFalse(c["s"] < 2.4 and c["e"] > 1.6, c)
        self.assertTrue(any("filler" in r[2] for r in removed))

    def test_legenda_corrigida_e_relativa_ao_trecho_depois_de_pausa_longa(self):
        ws = words([("Use", 0.0, 0.3), ("a", 0.4, 0.5), ("Ya.", 0.6, 1.0),
                    ("Ela", 5.0, 5.3), ("resume.", 5.4, 6.0)])
        plan, _, _ = cuts.decide(ws, {"replace": {"Ya": "IA"}}, total=6.5)
        self.assertEqual(len(plan), 2)  # a pausa de 4 s vira um corte
        segundo = plan[1]
        self.assertEqual([t for _, _, t in plan[0]["ev"]], ["Use a IA."])
        x0, x1, t = segundo["ev"][0]
        self.assertEqual(t, "Ela resume.")
        self.assertAlmostEqual(segundo["s"] + x0, 5.0, delta=0.01)
        self.assertAlmostEqual(segundo["s"] + x1, 6.0, delta=0.01)

    def test_frase_longa_quebra_no_limite_de_caracteres(self):
        frase = "Quero um resumo executivo com objeto obrigações principais cláusulas de rescisão e riscos."
        ws = words([(w, i * 0.4, i * 0.4 + 0.3) for i, w in enumerate(frase.split())])
        plan, _, _ = cuts.decide(ws, {}, total=6.0, max_chars=30)
        evs = [t for c in plan for _, _, t in c["ev"]]
        self.assertEqual(" ".join(evs), frase)
        self.assertTrue(all(len(t) <= 30 for t in evs), evs)

    def test_muleta_do_edit_json_soma_com_a_lista_pt(self):
        ws = words([("Isso", 0.0, 0.3), ("muda,", 0.4, 0.8), ("né,", 1.0, 1.3), ("sabe,", 1.5, 1.8), ("tudo.", 2.0, 2.4)])
        plan, _, _ = cuts.decide(ws, {"extra_fillers": ["sabe"]}, total=3.0)
        self.assertEqual(text_of(plan), "Isso muda, tudo.")

    def test_palavra_colada_no_enchimento_nao_e_cortada(self):
        # "Quero" comeca 20 ms depois do "ééé": menos de um quadro
        ws = words([("Contrato.", 0.0, 0.5), ("ééé", 0.6, 1.21), ("Quero", 1.23, 1.5), ("resumo.", 1.6, 2.0)])
        plan, removed, _ = cuts.decide(ws, {}, total=2.5)
        self.assertEqual(text_of(plan), "Contrato. Quero resumo.")
        quero = next(c for c in plan if "Quero" in " ".join(t for _, _, t in c["ev"]))
        self.assertLessEqual(quero["s"], 1.23)
        for c in plan:
            self.assertTrue(all(0 <= x0 < x1 <= c["e"] - c["s"] + 1e-6 for x0, x1, _ in c["ev"]), c)
            self.assertGreaterEqual(c["e"] - c["s"], 0.1, c)
        # todo corte aparece no edit-plan.md
        self.assertEqual(len(removed), len(plan) - 1 + sum(1 for r in removed if r[2] in ("opening", "ending")))


if __name__ == "__main__":
    unittest.main()
