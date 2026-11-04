"""Zoom opcional: so a camera aproxima, e so quando pedido (--zoom ou "z" no plan.json).

    python3 -m unittest discover tests
"""
import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from vtk import cuts
from vtk.render import EYE_LINE, zoom_crop

CAM = [1231, 692, 1287, 461]  # camera_crop do presets/tiktok-vertical.json


def words(spec):
    return [{"w": w, "start": s, "end": e} for w, s, e in spec]


# tres frases separadas por pausas longas: dois cortes de mais de 1 s
WS = words([("Primeira", 0.0, 0.5), ("frase.", 0.6, 1.2),
            ("Segunda", 4.0, 4.5), ("frase.", 4.6, 5.2),
            ("Terceira", 8.0, 8.5), ("frase.", 8.6, 9.2)])


class ZoomCrop(unittest.TestCase):
    def test_sem_zoom_devolve_o_recorte_do_preset(self):
        self.assertEqual(zoom_crop(CAM, 1.0), CAM)

    def test_zoom_diminui_o_recorte_mantendo_proporcao_e_ficando_dentro(self):
        w, h, x, y = zoom_crop(CAM, 1.1)
        self.assertEqual((w % 2, h % 2), (0, 0))
        self.assertAlmostEqual(w / h, CAM[0] / CAM[1], places=2)
        self.assertLess(w, CAM[0])
        self.assertTrue(CAM[2] <= x and x + w <= CAM[2] + CAM[0])
        self.assertTrue(CAM[3] <= y and y + h <= CAM[3] + CAM[1])

    def test_linha_dos_olhos_fica_na_mesma_altura(self):
        w, h, x, y = zoom_crop(CAM, 1.2)
        olhos = CAM[3] + EYE_LINE * CAM[1]
        self.assertAlmostEqual((olhos - y) / h, EYE_LINE, places=2)


class ZoomNoPlano(unittest.TestCase):
    def test_desligado_por_padrao(self):
        plan, _, _ = cuts.decide(WS, {}, total=10.0)
        self.assertGreater(len(plan), 1)
        self.assertFalse(any("z" in c for c in plan))

    def test_com_zoom_alterna_nas_emendas_grandes(self):
        plan, removed, maybe = cuts.decide(WS, {}, total=10.0, zoom=1.1)
        self.assertEqual([c.get("z", 1) for c in plan], [1, 1.1, 1])
        self.assertIn("Zoom na câmera", cuts.report(plan, removed, maybe, 10.0))


if __name__ == "__main__":
    unittest.main()
