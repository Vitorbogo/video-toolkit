"""transcribe_words: silencios, janelas, emenda de janelas, fim das palavras e saida, sem o modelo.

    python3 -m unittest discover tests
O teste de integracao roda o Parakeet de verdade so se houver modelo (models/... ou VTK_MODEL_DIR), sherpa-onnx,
ffmpeg e o `say` do macOS; senao e pulado.
"""
import json, os, re, shutil, subprocess, sys, tempfile, unittest, wave
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from vtk import transcribe_words as T

SR = T.SR
SCRIPT = os.path.join(ROOT, "src", "vtk", "transcribe_words.py")


def sig(*parts):
    """('s', 1.0) = silencio, ('v', 2.0) = 'voz' (seno a -10 dBFS), ('n', 1.0) = ruido fraco (-45 dBFS)."""
    rng = np.random.default_rng(0); out = []
    for kind, d in parts:
        n = int(d * SR); t = np.arange(n) / SR
        out.append({"s": np.zeros(n), "v": 0.45 * np.sin(2 * np.pi * 220 * t),
                    "n": 0.0056 * rng.standard_normal(n)}[kind])
    return np.concatenate(out).astype(np.float32)


def runs_of(x):
    return T.speech_runs(T.frame_db(x), len(x) / SR)


def W(*spec):
    return [{"w": w, "start": s, "end": e} for w, s, e in spec]


class Silences(unittest.TestCase):
    def assertRuns(self, got, want):
        self.assertEqual(len(got), len(want), got)
        for g, w in zip(got, want):
            self.assertAlmostEqual(g[0], w[0], delta=0.03); self.assertAlmostEqual(g[1], w[1], delta=0.03)

    def test_starts_and_ends_in_silence(self):
        self.assertRuns(runs_of(sig(("s", 1), ("v", 2), ("s", 1), ("v", 1), ("s", 0.5))), [[1, 3], [4, 5]])

    def test_starts_and_ends_in_speech(self):
        self.assertRuns(runs_of(sig(("v", 2), ("s", 1), ("v", 1.5))), [[0, 2], [3, 4.5]])

    def test_no_silence(self):
        self.assertRuns(runs_of(sig(("v", 3))), [[0, 3]])

    def test_short_pause_and_weak_noise(self):
        # pausa de 0,3 s nao separa; ruido a -45 dB conta como silencio
        self.assertRuns(runs_of(sig(("v", 1), ("s", 0.3), ("v", 1), ("n", 1), ("v", 1))), [[0, 2.3], [3.3, 4.3]])

    def test_all_silence(self):
        self.assertEqual(runs_of(sig(("s", 2))), [])

    def test_plain_floats(self):
        r = runs_of(sig(("s", 1), ("v", 1), ("s", 1)))
        self.assertTrue(all(type(t) is float for p in r for t in p))


class Windows(unittest.TestCase):
    def test_long_run_split_at_quiet_point(self):
        x = sig(("v", 19.0), ("s", 0.1), ("v", 21.0)); db = T.frame_db(x)
        w = T.windows(runs_of(x), db)
        self.assertEqual(len(w), 2)
        self.assertAlmostEqual(w[0][1], 19.05, delta=0.03); self.assertEqual(w[0][1], w[1][0])
        self.assertAlmostEqual(w[1][1], 40.1, delta=0.03)

    def test_split_never_at_fixed_time(self):
        # sem ponto quieto: ainda cai entre 15 e 25 s; com um vale a 17,3 s, cai nele (e nao em 25 s)
        x = sig(("v", 17.3), ("n", 0.08), ("v", 30)); w = T.windows(runs_of(x), T.frame_db(x))
        self.assertAlmostEqual(w[0][1], 17.34, delta=0.03)
        self.assertTrue(all(e - s <= 25.0 for s, e in w))
        self.assertTrue(all(15.0 <= e - s for s, e in w[:-1]))

    def test_neighbours_merge_up_to_max(self):
        runs = [[0, 5], [6, 12], [13, 24], [26, 30]]
        self.assertEqual(T.windows(runs, np.zeros(0)), [[0, 24], [26, 30]])

    def test_quiet_point(self):
        db = np.full(1000, -10.0); db[600:604] = -80     # quadros de 20 ms: 12,00-12,08 s
        self.assertAlmostEqual(T.quiet_point(db, 10, 15), 12.04, delta=0.001)


class Join(unittest.TestCase):
    def test_duplicate_at_join(self):
        # erro real: "bem."@24.72 e "Bem"@25.12 na emenda de 25 s
        prev = W(("muito", 24.2, 24.6), ("bem.", 24.72, 24.88)); new = W(("Bem", 25.12, 25.28), ("feito", 25.3, 25.7))
        self.assertEqual([w["w"] for w in T.join(prev, new, 24.8, 25.2)], ["muito", "bem.", "feito"])

    def test_keeps_the_version_away_from_the_edge(self):
        # "cor" veio cortado no fim da janela anterior; "cortar" inteiro na seguinte
        prev = W(("vou", 24.4, 24.7), ("cor", 24.9, 25.2)); new = W(("cortar", 24.85, 25.3), ("isso", 25.3, 25.6))
        self.assertEqual([w["w"] for w in T.join(prev, new, 24.8, 25.2)], ["vou", "cortar", "isso"])

    def test_two_short_words_duplicated(self):
        prev = W(("parte", 24.3, 24.7), ("de", 24.82, 24.9), ("um", 24.95, 25.1))
        new = W(("de", 24.85, 24.95), ("um", 25.0, 25.12), ("jeito", 25.15, 25.5))
        self.assertEqual([w["w"] for w in T.join(prev, new, 24.8, 25.2)], ["parte", "de", "um", "jeito"])

    def test_real_repetition_outside_zone_stays(self):
        prev = W(("muito", 23.0, 23.3)); new = W(("muito", 25.5, 25.8))
        self.assertEqual(len(T.join(prev, new, 24.8, 25.2)), 2)

    def test_windows_apart_in_silence(self):
        prev = W(("fim.", 10.0, 10.4)); new = W(("fim", 10.9, 11.2))
        self.assertEqual(len(T.join(prev, new, 10.8, 10.8)), 2)

    def test_similar(self):
        self.assertTrue(T.similar("bem.", "Bem")); self.assertTrue(T.similar("locais.", "Lokais"))
        self.assertTrue(T.similar("é", "e")); self.assertFalse(T.similar("o", "ou")); self.assertFalse(T.similar("cor", "mar"))


class WordTimes(unittest.TestCase):
    TOK = [" Es", "sa", " é", " uma", " co", "isa", ".", " E"]
    TS = [6.88, 7.2, 7.44, 7.68, 7.92, 8.24, 8.56, 8.96]
    DUR = [0.32, 0.24, 0.24, 0.24, 0.32, 0.32, 0.16, 0.24]

    def test_end_from_duration_and_punctuation_does_not_move_it(self):
        ws = T.words_of(self.TOK, self.TS, self.DUR)
        self.assertEqual([w["w"] for w in ws], ["Essa", "é", "uma", "coisa.", "E"])
        self.assertEqual(ws[3], {"w": "coisa.", "start": 7.92, "end": 8.56})    # 8.24 + 0.32, nao 8.56 + 0.16
        self.assertEqual(ws[0]["end"], 7.44)

    def test_fallback_without_durations(self):
        for d in (None, []):
            ws = T.words_of(self.TOK, self.TS, d)
            self.assertEqual(ws[3]["end"], 8.4)                                  # ultimo token 8.24 + 0.16

    def test_offset_zero_duration_and_leading_punct(self):
        ws = T.words_of([".", " Oi", ",", " tu", "do"], [0.0, 0.1, 0.3, 0.4, 0.5], [0.08, 0.16, 0.08, 0.08, 0.0], offset=20)
        self.assertEqual(ws, [{"w": "Oi,", "start": 20.1, "end": 20.26}, {"w": "tudo", "start": 20.4, "end": 20.58}])

    def test_finish_snaps_to_silence(self):
        runs = [[0.0, 1.4], [2.8, 5.46], [7.16, 8.3]]
        ws = T.finish(W(("Bom", 0.0, 0.3), ("pessoal.", 0.9, 1.6),                 # passa do silencio: volta
                        ("de", 4.8, 5.0), ("vídeo.", 5.1, 5.2),                    # termina cedo: vai ate o silencio
                        ("coisa.", 7.9, 8.56), ("Oi", 11.0, 11.2)), 12.0, runs)
        self.assertEqual([w["end"] for w in ws], [0.3, 1.4, 5.0, 5.46, 8.3, 11.2])

    def test_finish_caps(self):
        ws = T.finish(W(("a", 1.0, 1.5), ("b", 1.3, 1.4), ("c", 2.0, 2.9)), 2.5, [[0.9, 2.45]])
        self.assertEqual([w["end"] for w in ws], [1.3, 1.4, 2.45])
        far = T.finish(W(("a", 1.0, 1.2)), 5.0, [[0.9, 3.0]])                     # mais de 0,5 s: nao estica
        self.assertEqual(far[0]["end"], 1.2)


class Output(unittest.TestCase):
    def test_transcript_shape(self):
        ws = T.finish(W(("Olá,", 0.1, 0.4), ("ação.", 0.5, 0.9), ("Fim", 2.5, 2.8)), 3.0)
        with tempfile.TemporaryDirectory() as d:
            T.write(d, "x.wav", 3.0, ws)
            with open(os.path.join(d, "transcript.json"), encoding="utf-8") as f: j = json.load(f)
            with open(os.path.join(d, "transcript.txt"), encoding="utf-8") as f: txt = f.read()
        self.assertEqual(j["words"], ws)
        self.assertTrue(all(list(w) == ["w", "start", "end"] for w in j["words"]))
        self.assertEqual(j["sentences"], [{"start": 0.1, "end": 0.9, "text": "Olá, ação."},
                                          {"start": 2.5, "end": 2.8, "text": "Fim"}])
        self.assertEqual(j["duration"], 3.0)
        self.assertEqual(txt, "[00:00.1-00:00.9] Olá, ação.\n[00:02.5-00:02.8] Fim\n")

    def test_read_wav_without_ffmpeg(self):
        x = (sig(("v", 0.5)) * 32767).astype(np.int16)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.wav")
            with wave.open(p, "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(x.tobytes())
            y = T.decode(p)
        self.assertEqual(len(y), len(x)); self.assertAlmostEqual(float(np.abs(y).max()), 0.45, delta=0.01)

    def test_missing_model_hint(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit) as e: T.check_model(d)
        self.assertIn("encoder.int8.onnx", str(e.exception)); self.assertIn("README", str(e.exception))

    def test_cli_checks_model_before_loading(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.wav")
            with open(p, "wb") as f: f.write(b"x")
            r = subprocess.run([sys.executable, SCRIPT, "--audio", p, "--out", d, "--model-dir", d],
                               capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0); self.assertIn("sherpa-onnx-nemo-parakeet", r.stderr)

    def test_cli_needs_input_and_output(self):
        r = subprocess.run([sys.executable, SCRIPT, "--audio", "a.wav"], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0); self.assertIn("--name", r.stderr)


def _model_dir():
    for d in (os.environ.get("VTK_MODEL_DIR"), T.MODEL):
        if d and all(os.path.isfile(os.path.join(d, f)) for f in T.MODEL_FILES): return d


def _have_sherpa():
    try:
        import sherpa_onnx  # noqa: F401
        return True
    except ImportError:
        return False


@unittest.skipUnless(_model_dir() and _have_sherpa() and shutil.which("say") and shutil.which("ffmpeg"),
                     "precisa do modelo (models/ ou VTK_MODEL_DIR), sherpa-onnx, ffmpeg e say")
class RealModel(unittest.TestCase):
    PAUSES = ("Bom dia, pessoal. [[slnc 1200]] Hoje vamos falar de edição de vídeo. [[slnc 1500]] Essa é uma coisa. "
              "[[slnc 1000]] E essa é outra coisa importante. [[slnc 1300]] Então é isso, até a próxima.")
    LONG = ("hoje eu quero mostrar para vocês como eu edito os meus vídeos curtos usando apenas ferramentas locais e "
            "gratuitas no meu computador sem precisar mandar nada para a internet e sem pagar nenhuma assinatura o "
            "processo começa com a gravação da tela junto com a câmera depois eu transcrevo o áudio com um modelo que "
            "roda aqui mesmo e que marca o tempo de cada palavra com isso eu consigo cortar os enchimentos as "
            "repetições e as pausas longas de um jeito bem preciso e no final eu gero as legendas a capa e o texto")

    def run_on(self, text):
        d = self.enterContext(tempfile.TemporaryDirectory())
        aiff = os.path.join(d, "fala.aiff")
        subprocess.run(["say", "-v", "Luciana", "-r", "175", "-o", aiff, text], check=True)
        r = subprocess.run([sys.executable, SCRIPT, "--audio", aiff, "--out", d, "--model-dir", _model_dir()],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(d, "transcript.json"), encoding="utf-8") as f: j = json.load(f)
        sd = subprocess.run(["ffmpeg", "-nostdin", "-i", aiff, "-af", "silencedetect=noise=-35dB:d=0.4", "-f", "null", "-"],
                            capture_output=True, text=True).stderr
        starts = [float(v) for v in re.findall(r"silence_start: (-?[\d.]+(?:e[-+]?\d+)?)", sd)]
        return j, starts

    def assertNoAdjacentRepeats(self, ws):
        self.assertFalse([(a, b) for a, b in zip(ws, ws[1:]) if T.norm(a["w"]) == T.norm(b["w"])])

    def test_sentence_ends_at_silence(self):
        j, starts = self.run_on(self.PAUSES)
        ends = [w["end"] for w in j["words"] if w["w"][-1] in ".?!"]
        self.assertEqual(len(ends), 5, [w["w"] for w in j["words"]])
        for e, s in zip(ends, starts): self.assertAlmostEqual(e, s, delta=0.1)
        self.assertNoAdjacentRepeats(j["words"])

    def test_long_take_without_pauses(self):
        j, starts = self.run_on(self.LONG)
        self.assertGreater(j["duration"], 26)
        self.assertFalse([s for s in starts if s < j["duration"] - 1])               # sem pausa: precisa dividir
        self.assertGreaterEqual(len(j["words"]), 95)
        self.assertNoAdjacentRepeats(j["words"])
        self.assertTrue(all(a["start"] <= b["start"] for a, b in zip(j["words"], j["words"][1:])))


if __name__ == "__main__":
    unittest.main()
