"""Efeitos sonoros: tempos no vídeo final, validação do sfx.json e a mistura no postaudio.

    python3 -m unittest discover tests
"""
import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from vtk import sfx


class Timeline(unittest.TestCase):
    def test_trechos_somam_no_video_final(self):
        plan = [{"s": 10.0, "e": 14.0, "ev": []}, {"s": 30.0, "e": 32.5, "ev": []}]
        self.assertEqual([(u, v) for u, v, _ in sfx.timeline(plan)], [(0.0, 4.0), (4.0, 6.5)])


class Checar(unittest.TestCase):
    def test_lista_valida(self):
        self.assertEqual(sfx.checar([{"t": 1.0, "som": "whoosh-curto"}, {"t": 7.0, "som": "pop-blip", "vol": 0.2}], 10), [])

    def test_som_desconhecido_e_fora_do_video(self):
        erros = sfx.checar([{"t": 1.0, "som": "pop"}, {"t": 99.0, "som": "clique"}], 10)
        self.assertTrue(any("'pop'" in e for e in erros))
        self.assertTrue(any("fora do vídeo" in e for e in erros))

    def test_efeitos_colados_demais(self):
        erros = sfx.checar([{"t": 1.0, "som": "clique"}, {"t": 3.0, "som": "pop-blip"}])
        self.assertTrue(any("menos de" in e for e in erros))


class Mistura(unittest.TestCase):
    def test_whoosh_comeca_antes_para_bater_no_tempo(self):
        f = sfx.filtro_mistura([{"t": 11.0, "som": "whoosh-curto"}])
        hit = sfx.CATALOGO["whoosh-curto"]["hit"]
        self.assertIn(f"[1:a]adelay={int(round((11.0 - hit) * 1000))}:all=1", f)
        self.assertIn("amix=inputs=2:normalize=0:duration=first[mix]", f)

    def test_vol_da_lista_vence_o_padrao(self):
        self.assertIn("volume=0.1[s0]", sfx.filtro_mistura([{"t": 2.0, "som": "clique", "vol": 0.1}]))

    def test_catalogo_tem_arquivo_para_cada_som(self):
        for som in sfx.CATALOGO:
            self.assertTrue(os.path.exists(sfx.arquivo(som)), som)


if __name__ == "__main__":
    unittest.main()
