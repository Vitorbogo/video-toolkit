"""A lista de enchimentos em portugues (presets/fillers-pt.json) aplicada pelo engine.py.

    python3 -m unittest discover tests
"""
import json, os, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from vtk import engine as ev
PT = json.load(open(os.path.join(ROOT, "presets/fillers-pt.json"), encoding="utf-8"))


def words(text, gap=0.1):
    """Palavras com 0,3 s cada e uma pausa entre elas (suficiente para o engine aceitar o corte)."""
    out, t = [], 0.0
    for w in text.split():
        out.append({"w": w, "start": round(t, 3), "end": round(t + 0.3, 3)}); t += 0.3 + gap
    return out


def cut(text, edit):
    ws = words(text)
    reason, _ = ev.mark(ws, edit)
    return [w["w"] for w, r in zip(ws, reason) if r]


class FillersPT(unittest.TestCase):
    def test_padrao_do_engine_corta_o_artigo_um(self):
        # o motivo do preset: sem ele, "um" (artigo) vira enchimento
        self.assertEqual(cut("Estou com um contrato.", {}), ["um"])

    def test_preset_mantem_artigo_um_e_verbo_e(self):
        self.assertEqual(cut("Estou com um contrato e é um bom exemplo.", PT), [])

    def test_hesitacoes_sao_cortadas(self):
        self.assertEqual(cut("O contexto ééé é importante, hum, sempre.", PT), ["ééé", "hum,"])

    def test_concordancia_fica(self):
        self.assertEqual(cut("Uhum, aham, exatamente.", PT), [])

    def test_muleta_so_ao_lado_de_virgula(self):
        self.assertEqual(cut("Isso é importante, né, porque muda tudo.", PT), ["né,"])
        self.assertEqual(cut("Então, quando você fala isso.", PT), ["Então,"])
        self.assertEqual(cut("Esse tipo de contrato é comum.", PT), [])
        self.assertEqual(cut("E então ela responde.", PT), [])

    def test_palavras_com_sentido_ficam(self):
        for frase in ("Ele não sabe, mas tenta.", "Enfim, chegamos ao ponto.", "Ele é desse tipo assim calado.", "Hã? Como assim?"):
            self.assertEqual(cut(frase, PT), [], frase)

    def test_limite_conhecido_entao_de_conclusao(self):
        # o engine corta muleta com virgula antes OU depois; conferir no edit-plan.md
        self.assertEqual(cut("Se chover, então fica em casa.", PT), ["então"])


if __name__ == "__main__":
    unittest.main()
