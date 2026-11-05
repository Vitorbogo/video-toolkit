"""render.py: grade de quadros, retomada por hash, legenda, recortes, desfoque e um render de verdade (se houver ffmpeg).

    python3 -m unittest discover tests
"""
import contextlib, io, json, os, shutil, subprocess, sys, tempfile, unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "src"))
from vtk import preset, render

P = preset.load(os.path.join(RAIZ, "presets/tiktok-vertical.json"))
def dump(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


SEG = {"s": 1.0, "e": 2.5, "ev": [[0.1, 1.2, "Oi, tudo bem?"]]}


class Quadros(unittest.TestCase):
    def test_quadros_pela_grade(self):
        self.assertEqual(render.frames({"s": 0, "e": 1.0}, 30), 30)
        self.assertEqual(render.frames({"s": 0.864, "e": 8.114}, 30), round(7.25 * 30))
        self.assertEqual(render.frames({"s": 5.66, "e": 8.511}, 30), 86)  # plano antigo, fora da grade

    def test_fim_antes_do_inicio_e_erro_claro(self):
        with self.assertRaises(SystemExit) as e:
            render.frames({"s": 2, "e": 2}, 30, 3)
        self.assertIn("trecho 3", str(e.exception))
        with self.assertRaises(SystemExit):
            render.frames({"s": 2, "e": 2.01}, 30)

    def test_plano_zoom_limitado_e_blur_validado(self):
        with contextlib.redirect_stdout(io.StringIO()):
            info = render.check_plan([dict(SEG), dict(SEG, z=1.5), dict(SEG, z=1.1)], 30)
        self.assertEqual(info, [(45, 1.0), (45, 1.2), (45, 1.1)])
        with self.assertRaises(SystemExit):
            render.check_plan([dict(SEG, blur=[[0.5, 0.2, 0, 0, 10, 10]])], 30)
        with self.assertRaises(SystemExit):
            render.check_plan([dict(SEG, blur=[[0, 1, 0, 0, 10]])], 30)

    def test_comando_tem_quadros_e_audio_exatos(self):
        cmd = render.clip_cmd(SEG, 45, 1.0, P, (2518, 1726), "", 0.5, "30", "/v.mov", ("/o/c00-leg.txt", 100), "/o/c00.mov.part")
        self.assertLess(cmd.index("-ss"), cmd.index("-i"))
        self.assertEqual(cmd[cmd.index("-frames:v") + 1], "45")
        self.assertEqual(cmd[cmd.index("-c:a") + 1], "pcm_s16le")
        fg = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("atrim=end_sample=72000,apad=whole_len=72000", fg)  # 45/30 s a 48 kHz
        self.assertIn("afade=t=out:st=1.4700:d=0.03", fg)
        self.assertIn("scale=540:", fg)  # --scale 0.5


class Recortes(unittest.TestCase):
    S = {"w": 320, "h": 240, "camera_crop": [160, 120, 160, 0], "slide_crop": [160, 240, 0, 0]}

    def test_tudo_dentro(self):
        self.assertEqual(render.check_source(self.S, (320, 240), [SEG]), [])

    def test_resolucao_diferente(self):
        errs = render.check_source(self.S, (640, 480), [SEG])
        self.assertEqual(len(errs), 1)
        self.assertIn("640x480", errs[0])

    def test_preset_antigo_sem_wh_so_confere_recortes(self):
        S = {k: v for k, v in self.S.items() if k not in ("w", "h")}
        self.assertEqual(render.check_source(S, (640, 480), [SEG]), [])
        self.assertEqual(len(render.check_source(S, (300, 240), [SEG])), 1)  # camera sai pela direita

    def test_caixa_de_blur_fora(self):
        errs = render.check_source(self.S, (320, 240), [dict(SEG, blur=[[0, 1, 300, 10, 40, 10]])])
        self.assertEqual(len(errs), 1)
        self.assertIn("blur", errs[0])

    def test_preset_base_tem_resolucao(self):
        self.assertEqual((P["source"]["w"], P["source"]["h"]), (2518, 1726))
        self.assertEqual(render.check_source(P["source"], (2518, 1726), [SEG]), [])


class Desfoque(unittest.TestCase):
    def test_sem_caixas(self):
        self.assertEqual(render.blur_graph([], (320, 240)), ("", "v0"))

    def test_caixas_em_cadeia(self):
        g, out = render.blur_graph([[0.3, 0.7, 20, 40, 120, 80], [1, 2, 11, 21, 30, 30]], (320, 240))
        self.assertEqual(out, "bl2")
        self.assertIn("[v0]split=2[bm0][bc0];[bc0]crop=120:80:20:40,gblur=sigma=26", g)
        self.assertIn("[bm0][bk0]overlay=20:40:enable='between(t,0.3,0.7)'[bl1];", g)
        self.assertIn("crop=32:32:10:20", g)  # impar -> par, sempre para fora
        self.assertIn("[bl1]split=2", g)
        self.assertTrue(g.endswith(";"))

    def test_desfoque_vem_antes_dos_recortes(self):
        c = dict(SEG, blur=[[0, 1, 20, 40, 120, 80]])
        fg = render.clip_cmd(c, 45, 1.0, P, (2518, 1726), "", 1, "20", "/v", ("/l.txt", 100), "/o")
        fg = fg[fg.index("-filter_complex") + 1]
        self.assertLess(fg.index("gblur"), fg.index("[bl1]split=2[a][b]"))


class Retomada(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.video = os.path.join(self.d.name, "g.mov")
        dump("x", self.video)

    def tearDown(self):
        self.d.cleanup()

    def h(self, c=SEG, z=1.0, P=P, cam="", scale=1.0, crf="20"):
        return render.clip_hash(c, z, P, cam, scale, crf, self.video)

    def test_hash_muda_com_o_que_afeta_o_clipe(self):
        base = self.h()
        self.assertEqual(base, self.h())
        self.assertNotEqual(base, render.clip_hash(SEG, 1.0, P, "", 1.0, "20", self.video, (self.video, 2.0)))
        mudancas = [self.h(c=dict(SEG, ev=[[0.1, 1.2, "outro"]])), self.h(c=dict(SEG, wt=[[0.1, 0.5, 0.9]])), self.h(c=dict(SEG, e=2.6)), self.h(z=1.1),
                    self.h(c=dict(SEG, blur=[[0, 1, 0, 0, 10, 10]])), self.h(cam=",eq"), self.h(scale=0.5),
                    self.h(crf="30"), self.h(P=preset.merge(P, {"subtitles": {"size": 70}})),
                    self.h(P=preset.merge(P, {"source": {"camera_crop": [1, 2, 3, 4]}})),
                    self.h(P=preset.merge(P, {"cut": {"audio_fade_out_s": 0.05}}))]
        self.assertEqual(len(set(mudancas + [base])), len(mudancas) + 1)
        self.assertEqual(base, self.h(P=preset.merge(P, {"source": {"_nota": "outra"}, "audio": {"limiter": 0.5}})))
        os.utime(self.video, (1, 1))
        self.assertNotEqual(base, self.h())

    def test_limpa_sobras_e_clipes_antigos(self):
        d = self.d.name
        for f in ["c00.mov", "c00.json", "c00.mov.part", "c01.mp4", "c01.z", "c03.mov", "c03.json", "c12.ass",
                  "final.mov", "lista.txt"]:
            open(os.path.join(d, f), "w").close()
        render.clean(d, 3)
        self.assertEqual(sorted(os.listdir(d)), ["c00.json", "c00.mov", "final.mov", "g.mov", "lista.txt"])

    def test_pronto_so_com_o_mesmo_hash(self):
        d = self.d.name
        self.assertFalse(render.ready(d, 0, "abc"))
        open(os.path.join(d, "c00.mov"), "w").close()
        self.assertFalse(render.ready(d, 0, "abc"))  # sem sidecar = não terminou
        dump({"hash": "abc"}, os.path.join(d, "c00.json"))
        self.assertTrue(render.ready(d, 0, "abc"))
        self.assertFalse(render.ready(d, 0, "outro"))


class Fonte(unittest.TestCase):
    def test_fonte_do_repositorio(self):
        render.captions.check_font(P["subtitles"])
        self.assertTrue(os.path.exists(render.captions.fonte(P["subtitles"])))

    def test_sem_fonte_aborta(self):
        with self.assertRaises(SystemExit) as e:
            render.captions.check_font(dict(P["subtitles"], font_file="assets/fonts/nao-existe.ttf"))
        self.assertIn("font_file", str(e.exception))


def quadros_e_amostras(path):
    """(quadros de vídeo, amostras de áudio a 48 kHz, passos de pts), decodificando com o ffmpeg (sem ffprobe)."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-map", "0:v", "-f", "framecrc", "-"],
                       capture_output=True, text=True, check=True)
    pts = [int(l.split(",")[2]) for l in r.stdout.splitlines() if l and not l.startswith("#")]
    a = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-map", "0:a", "-f", "s16le", "-ac", "1", "-ar", "48000", "-"],
                       capture_output=True, check=True).stdout
    return len(pts), len(a) // 2, {b - a for a, b in zip(pts, pts[1:])}


@unittest.skipIf(shutil.which("ffmpeg") is None, "sem ffmpeg")
class RenderDeVerdade(unittest.TestCase):
    PLANO = [{"s": 0.5, "e": 0.913, "ev": [[0, 0.4, "Um {dois}"]]},
             {"s": 1.2, "e": 1.61, "ev": [[0, 0.4, "três"]], "blur": [[0, 0.2, 10, 10, 60, 40]]},
             {"s": 2.05, "e": 2.62, "z": 1.1, "ev": [[0, 0.5, "quatro"]]}]

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)
        self.video = os.path.join(self.d, "g.mov")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=30:d=3",
                        "-f", "lavfi", "-i", "sine=f=440:sample_rate=48000:d=3", "-c:v", "libx264", "-preset", "ultrafast",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", self.video], check=True)
        self.preset = os.path.join(self.d, "preset.json")
        dump({"base": os.path.join(RAIZ, "presets/tiktok-vertical.json"), "canvas": {"w": 180, "h": 320},
                   "source": {"w": 320, "h": 240, "camera_crop": [160, 120, 160, 0], "slide_crop": [160, 240, 0, 0]},
                   "layout": {"camera": {"y": 10, "h": 90}, "slide": {"x": 10, "y": 110, "w": 160, "h": 150}}},
             self.preset)
        self.plan = os.path.join(self.d, "plan.json")
        dump(self.PLANO, self.plan)
        self.out = os.path.join(self.d, "out")
        probe = render.probe
        render.probe = lambda v: (320, 240)  # sem ffprobe nos testes
        self.addCleanup(setattr, render, "probe", probe)

    def run_render(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            render.main(["--preset", self.preset, "--video", self.video, "--plan", self.plan, "--out", self.out])
        return buf.getvalue()

    def test_final_na_grade_e_retomada(self):
        log = self.run_render()
        n = [render.frames(c, 30) for c in self.PLANO]
        self.assertEqual(n, [12, 12, 17])
        q, a, passos = quadros_e_amostras(os.path.join(self.out, "final.mov"))
        self.assertEqual(q, sum(n))
        self.assertEqual(a, sum(n) * 48000 // 30)  # áudio = vídeo, sem sobra nas emendas
        self.assertEqual(len(passos), 1)  # taxa de quadros constante
        self.assertEqual(read(os.path.join(self.out, "lista.txt")), "file 'c00.mov'\nfile 'c01.mov'\nfile 'c02.mov'\n")
        self.assertIn("3 / 3 clipes prontos", log)
        # de novo: nada é refeito; mudar só um trecho refaz só ele; trechos que saíram são apagados
        self.assertNotIn("ok ", self.run_render())
        dump([self.PLANO[0], dict(self.PLANO[1], ev=[[0, 0.4, "outro"]])], self.plan)
        log = self.run_render()
        self.assertEqual([l.split()[1] for l in log.splitlines() if l.startswith("ok ")], ["1"])
        self.assertIn("2 / 2 clipes prontos", log)
        self.assertFalse(any(f.startswith("c02") for f in os.listdir(self.out)))
        self.assertEqual(quadros_e_amostras(os.path.join(self.out, "final.mov"))[:2], (24, 24 * 1600))

    def test_painel_no_lugar_do_slide(self):
        painel = os.path.join(self.d, "painel.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=160x150:r=30:d=2",
                        "-pix_fmt", "yuv420p", painel], check=True)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            render.main(["--preset", self.preset, "--video", self.video, "--plan", self.plan, "--out", self.out,
                         "--painel", painel])
        self.assertIn("3 / 3 clipes prontos", buf.getvalue())
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", "0.5", "-i", os.path.join(self.out, "final.mov"), "-frames:v", "1",
                            "-vf", "crop=4:4:88:183", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True)
        px = r.stdout[:3]
        self.assertGreater(px[0], 200); self.assertLess(px[1], 60)  # vermelho do painel no meio da área do slide

    def test_legenda_desenhada_no_quadro(self):
        self.run_render()
        self.assertTrue(any(f.startswith("c00-leg-") and f.endswith(".png") for f in os.listdir(self.out)))
