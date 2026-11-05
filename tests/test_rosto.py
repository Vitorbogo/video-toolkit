"""rosto.py (nota de rosto neutro) e o "auto" do thumb.py/publish.py.

    python3 -m unittest discover tests
"""
import contextlib, io, json, math, os, shutil, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from vtk import rosto, thumb, publish

PESOS = rosto.PADRAO["pesos"]


def quiet():
    return contextlib.redirect_stdout(io.StringIO())


class Nota(unittest.TestCase):
    def test_neutro_tem_nota_menor_que_piscada_e_boca_aberta(self):
        neutro = rosto.partes({"eyeBlinkLeft": 0.1, "eyeBlinkRight": 0.1})
        piscada = rosto.partes({"eyeBlinkLeft": 0.9, "eyeBlinkRight": 0.8})
        falando = rosto.partes({"jawOpen": 0.5})
        self.assertLess(rosto.nota(neutro, PESOS), rosto.nota(piscada, PESOS))
        self.assertLess(rosto.nota(neutro, PESOS), rosto.nota(falando, PESOS))

    def test_pose_e_nitidez(self):
        self.assertAlmostEqual(rosto.partes({}, yaw=15, pitch=0)["pose"], 0.5)
        self.assertEqual(rosto.partes({}, yaw=90)["pose"], 1.0)
        self.assertEqual(rosto.partes({}, nitidez=2.0)["nitidez"], 0.0)  # mais nitido que a mediana: sem penalidade
        self.assertAlmostEqual(rosto.partes({}, nitidez=0.25)["nitidez"], 0.75)

    def test_repouso_desconta_o_normal_da_pessoa(self):
        dets = [rosto.partes({"browInnerUp": 0.4 + i / 100}) for i in range(20)] + [None]
        base = rosto.repouso(dets)
        self.assertAlmostEqual(base["testa"], 0.41, places=2)
        p = rosto.desconta(rosto.partes({"browInnerUp": 0.45}, yaw=15), base)
        self.assertAlmostEqual(p["testa"], 0.04, places=2)
        self.assertAlmostEqual(p["pose"], 0.5)  # pose nao e expressao: nao desconta
        self.assertEqual(rosto.desconta(rosto.partes({}), base)["testa"], 0.0)  # nunca negativo

    def test_suaviza_usa_o_pior_vizinho_e_sem_rosto_contamina(self):
        self.assertEqual(rosto.suaviza([1, 0, 1, 0.1, 0.1, 0.1]), [1, 1, 1, 1, 0.1, 0.1])
        self.assertEqual(rosto.suaviza([0.1, None, 0.1, 0.1]), [None, None, None, 0.1])

    def test_escolhe_respeita_distancia_e_margens(self):
        ts = [i * 0.25 for i in range(40)]  # 10 s
        notas = [1.0] * 40
        notas[0] = 0.0; notas[8] = 0.1; notas[9] = 0.05; notas[30] = 0.2; notas[39] = 0.0
        idx = rosto.escolhe(ts, notas, 3, 1.5, inicio=0.5, fim=9.5)
        self.assertEqual(idx[:2], [9, 30])  # 0 e 39 caem na margem; 8 fica perto demais de 9
        self.assertTrue(all(abs(ts[a] - ts[b]) >= 1.5 for a in idx for b in idx if a != b))

    def test_pose_da_matriz(self):
        a = math.radians(20)
        yaw = [[math.cos(a), 0, math.sin(a), 0], [0, 1, 0, 0], [-math.sin(a), 0, math.cos(a), 0], [0, 0, 0, 1]]
        y, p = rosto.pose(yaw)
        self.assertAlmostEqual(y, 20, places=3); self.assertAlmostEqual(p, 0, places=3)
        escala = [[2 * v for v in linha[:3]] + [0] for linha in yaw[:3]] + [[0, 0, 0, 1]]
        self.assertAlmostEqual(rosto.pose(escala)[0], 20, places=3)  # escala do rosto nao muda o angulo


R = {"video": "final.mp4", "candidatos": [{"t": 12.5, "nota": 0.3, "rosto_x": 0.42},
                                          {"t": 30.0, "nota": 0.4, "rosto_x": 0.55}],
     "todos": [[10.0, 0.5, 0.40], [20.0, 0.6, 0.61], [30.0, 0.4, 0.55]]}


class ThumbAuto(unittest.TestCase):
    def test_auto_pela_posicao_da_variante_e_auto_n(self):
        o = thumb.auto({"tempo_s": "auto", "rosto_x": "auto"}, R, 1)
        self.assertEqual((o["tempo_s"], o["rosto_x"]), (30.0, 0.55))
        o = thumb.auto({"tempo_s": "auto:1", "rosto_x": None}, R, 1)
        self.assertEqual((o["tempo_s"], o["rosto_x"]), (12.5, None))

    def test_rosto_x_auto_com_tempo_fixo_usa_quadro_mais_perto(self):
        self.assertEqual(thumb.auto({"tempo_s": 19, "rosto_x": "auto"}, R, 0)["rosto_x"], 0.61)

    def test_candidato_que_nao_existe_e_erro(self):
        with self.assertRaises(SystemExit) as e:
            thumb.auto({"tempo_s": "auto:3", "rosto_x": None}, R, 0)
        self.assertIn("rosto.json tem 2", str(e.exception))

    def test_validacao_aceita_auto_e_recusa_lixo(self):
        thumb.validate({"titulo": "x", "tempo_s": "auto", "rosto_x": "auto"})
        thumb.validate({"titulo": "x", "variantes": [{"nome": "A", "tempo_s": "auto:2"}]})
        for ruim in ({"tempo_s": "automatico"}, {"tempo_s": "auto:0"}, {"tempo_s": 3, "rosto_x": "meio"}):
            with self.assertRaises(SystemExit):
                thumb.validate({"titulo": "x", **ruim})
        self.assertTrue(thumb.usa_auto({"titulo": "x", "tempo_s": 3, "youtube": {"rosto_x": "auto"}}))
        self.assertFalse(thumb.usa_auto({"titulo": "x", "tempo_s": 3}))

    def test_sem_rosto_json_explica_o_que_rodar(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit) as e:
                thumb.ler_rosto(os.path.join(d, "rosto.json"), "final.mp4")
            self.assertIn("rosto.py", str(e.exception))


class PublishUsaTempoReal(unittest.TestCase):
    def test_tempo_do_capas_json_vence_o_auto_do_thumb(self):
        with open(os.path.join(ROOT, "presets", "publish.json"), encoding="utf-8") as f: P = json.load(f)
        M = {"titulos": ["Titulo"], "descricao": "d", "legenda_tiktok": "l", "hashtags_motivo": "m",
             "hashtags": {"tiktok": ["#a"], "youtube": ["#a"]}, "capa": {"variante": "A", "motivo": "neutro"}}
        T = {"variantes": [{"nome": "A", "vertical": {"tempo_s": "auto"}}]}
        md = publish.render("x", M, P, 40.0, T, [], {"A": {"vertical": {"tempo_s": 12.5, "rosto_x": None}}})
        self.assertIn("quadro em ~12.5 s", md)
        self.assertNotIn("auto", publish.render("x", M, P, 40.0, T, []))  # sem capas.json: nao escreve "~auto s"


MODELO = os.environ.get("VTK_FACE_MODEL", rosto.MODELO)


@unittest.skipUnless(shutil.which("ffmpeg") and os.path.isfile(MODELO), "precisa de ffmpeg e models/face_landmarker.task")
class Integracao(unittest.TestCase):
    def test_video_sem_rosto_da_erro_claro(self):
        try:
            import mediapipe  # noqa: F401
        except ImportError:
            self.skipTest("mediapipe nao instalado")
        import subprocess
        from vtk import preset
        with tempfile.TemporaryDirectory() as d:
            v = os.path.join(d, "v.mp4")
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=10:d=3",
                            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", v], check=True)
            with self.assertRaises(SystemExit) as e:
                rosto.analisa(v, preset.load("presets/thumbnail.json"), MODELO)
            self.assertIn("nenhum rosto", str(e.exception))


if __name__ == "__main__":
    unittest.main()
