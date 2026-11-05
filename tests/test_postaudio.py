"""postaudio: leitura do loudnorm, cadeia do preset, conta do loudnorm linear e uma rodada real com ffmpeg.

    python3 -m unittest discover tests
"""
import contextlib, io, os, re, shutil, subprocess, sys, tempfile, unittest, unittest.mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from vtk import postaudio as pa, preset

STDERR = """[Parsed_loudnorm_3 @ 0x1] \n{
\t"input_i" : "-26.49",
\t"input_tp" : "-5.41",
\t"input_lra" : "1.60",
\t"input_thresh" : "-36.50",
\t"output_i" : "-14.97",
\t"output_tp" : "-1.50",
\t"output_lra" : "1.40",
\t"output_thresh" : "-24.97",
\t"normalization_type" : "dynamic",
\t"target_offset" : "0.97"
}
[out#0/null @ 0x2] video:0KiB audio:22080KiB
"""
SILENCIO = STDERR.replace('"-26.49"', '"-inf"').replace('"-5.41"', '"-inf"').replace('"0.97"', '"inf"')
A = preset.load("presets/tiktok-vertical.json")["audio"]


class Parse(unittest.TestCase):
    def test_le_json_e_converte_numeros(self):
        j = pa.parse_loudnorm(STDERR)
        self.assertEqual(j["input_i"], -26.49); self.assertEqual(j["input_tp"], -5.41)
        self.assertEqual(j["normalization_type"], "dynamic")

    def test_inf(self):
        j = pa.parse_loudnorm(SILENCIO)
        self.assertEqual(j["input_i"], float("-inf")); self.assertEqual(j["target_offset"], float("inf"))

    def test_sem_json(self):
        self.assertIsNone(pa.parse_loudnorm("Stream map '0:a:0' matches no streams."))


class Measure(unittest.TestCase):
    def fake(self, stderr):
        class R: pass
        r = R(); r.stderr = stderr; r.returncode = 1
        return lambda args: (r, pa.parse_loudnorm(stderr))

    def test_silencio_da_erro_claro(self):
        with unittest.mock.patch.object(pa, "ffmpeg_ln", self.fake(SILENCIO)):
            with self.assertRaises(SystemExit) as c: pa.measure("x.mov", "anull", "I=-14")
        self.assertIn("silencio", str(c.exception.code))

    def test_sem_audio_da_erro_claro(self):
        with unittest.mock.patch.object(pa, "ffmpeg_ln", self.fake("Stream map '0:a:0' matches no streams.")):
            with self.assertRaises(SystemExit) as c: pa.measure("x.mov", "anull", "I=-14")
        self.assertIn("nao tem faixa de audio", str(c.exception.code))


class Chain(unittest.TestCase):
    def test_preset_padrao(self):
        c = pa.chain(A)
        self.assertTrue(c.startswith("aresample=192000,highpass=f=80,"))
        self.assertNotIn("afftdn", c); self.assertNotIn("alimiter", c)

    def test_pre_limitador_sem_auto_level_e_sem_atraso(self):
        c = pa.chain(A, -12.0)
        lim = re.search(r"alimiter=([^,]+)$", c).group(1)
        self.assertIn("level=0", lim); self.assertIn("latency=1", lim)
        self.assertAlmostEqual(float(re.search(r"limit=([\d.]+)", lim).group(1)), 10 ** (-12 / 20), places=5)

    def test_denoise_opcional(self):
        B = dict(A); B.pop("denoise")
        self.assertNotIn("afftdn", pa.chain(B))
        B["denoise"] = {"enabled": True, "nr_db": 3, "noise_floor_db": -60}
        self.assertIn("afftdn=nr=3:nf=-60", pa.chain(B))

    def test_preset_invalido(self):
        for k in ("loudnorm", "compressor"):
            B = dict(A); B.pop(k)
            with self.assertRaises(SystemExit): pa.check_preset(B)
        with self.assertRaises(SystemExit): pa.check_preset(dict(A, pre_limiter=2))
        with self.assertRaises(SystemExit): pa.check_preset(dict(A, tp_margin_db=-1))
        with contextlib.redirect_stdout(io.StringIO()):
            pa.check_preset(dict(A, pre_limiter=1.0, limiter=0.84))  # preset antigo continua valendo


class Linear(unittest.TestCase):
    def test_excesso(self):
        # -26.49 LUFS, pico -5.41: ganho 12.49 -> pico 7.08, 9.58 dB acima de -2.5
        self.assertAlmostEqual(pa.excess({"input_i": -26.49, "input_tp": -5.41}, -14, -2.5), 9.58, places=2)
        self.assertLessEqual(pa.excess({"input_i": -27.42, "input_tp": -16.8}, -14, -2.5), 0)

    def test_proximo_pre_limite_torna_linear_possivel(self):
        m = {"input_i": -26.49, "input_tp": -5.41}
        pre = pa.next_pre_db(m, -14, -2.5, None)
        self.assertAlmostEqual(pre, -5.41 - 9.58 - pa.STEP_DB, places=2)
        # se o volume nao mudasse, o novo pico + ganho ficaria abaixo do plano pela folga
        self.assertAlmostEqual(pa.excess({"input_i": -26.49, "input_tp": pre}, -14, -2.5), -pa.STEP_DB, places=6)

    def test_proximo_pre_limite_parte_do_limite_atual(self):
        m = {"input_i": -27.3, "input_tp": -15.0}
        self.assertAlmostEqual(pa.next_pre_db(m, -14, -2.5, -16.0), -16.0 - pa.excess(m, -14, -2.5) - pa.STEP_DB)


FF = shutil.which("ffmpeg")


@unittest.skipUnless(FF, "ffmpeg nao instalado")
class Integracao(unittest.TestCase):
    def test_final_mov_vira_mp4_no_alvo(self):
        with tempfile.TemporaryDirectory() as d:
            inp, out = os.path.join(d, "final.mov"), os.path.join(d, "final.mp4")
            # "voz" modulada a -26 dB + plosivas curtas perto de 0 dBFS (forcam o pre-limitador), 44.1 kHz mono
            voz = ("0.08*sin(2*PI*180*t)*(0.6+0.4*sin(2*PI*4*t))"
                   "+0.9*exp(-mod(t,1.3)*120)*sin(2*PI*110*t)*lt(mod(t,1.3),0.05)")
            subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=30:d=6",
                            "-f", "lavfi", "-i", "aevalsrc=%s:s=44100:d=6" % voz.replace(",", "\\,"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                            "-c:a", "pcm_s16le", inp], check=True)
            with contextlib.redirect_stdout(io.StringIO()):
                r = pa.run(inp, out, A)
            self.assertLessEqual(abs(r["I"] + 14), 0.5); self.assertLessEqual(r["TP"], A["loudnorm"]["TP"])
            self.assertEqual(r["normalization_type"], "linear"); self.assertIsNotNone(r["pre_limit_db"])
            info = subprocess.run([FF, "-hide_banner", "-i", out], capture_output=True, text=True).stderr
            self.assertRegex(info, r"Audio: aac.*48000 Hz")
            md5 = lambda p: subprocess.run([FF, "-v", "error", "-i", p, "-map", "0:v", "-c", "copy", "-f", "md5", "-"],
                                           capture_output=True, text=True, check=True).stdout
            self.assertEqual(md5(inp), md5(out))
            self.assertEqual(sorted(os.listdir(d)), ["final.mov", "final.mp4"])  # sem .tmp sobrando


if __name__ == "__main__":
    unittest.main()
