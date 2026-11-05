"""thumb: precedencia das opcoes, destaque, quebra/encolhimento de texto, validacao do spec e uma rodada real.

    python3 -m unittest discover tests
"""
import contextlib, copy, hashlib, io, os, shutil, subprocess, sys, tempfile, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from vtk import preset, thumb

P = preset.load("presets/thumbnail.json")
F_T = os.path.join(thumb.ROOT, P["fontes"]["titulo"])
SPEC = {"tempo_s": 14, "kicker": "CHATGPT", "titulo": "O chat acha que você é homem?", "destaque": "homem?",
        "rodape": "", "rosto_x": 0.5,
        "variantes": [{"nome": "A", "vertical": {"tempo_s": 14}, "youtube": {"tempo_s": 3}},
                      {"nome": "B", "vertical": {"tempo_s": 3}}]}


def quiet():
    return contextlib.redirect_stdout(io.StringIO())


class Precedencia(unittest.TestCase):
    S = {"tempo_s": 1, "rosto_x": 0.1, "titulo": "topo", "kicker": "K",
         "youtube": {"tempo_s": 2, "titulo": "formato"},
         "variantes": [{"nome": "A", "rosto_x": 0.3, "titulo": "variante", "youtube": {"tempo_s": 4}}]}

    def test_formato_do_topo_vale_sem_variantes(self):
        S = {k: v for k, v in self.S.items() if k != "variantes"}
        o = thumb.resolve(S, {}, "youtube")
        self.assertEqual((o["tempo_s"], o["titulo"], o["rosto_x"]), (2, "formato", 0.1))
        self.assertEqual(thumb.resolve(S, {}, "vertical")["titulo"], "topo")

    def test_ordem_completa(self):
        v = self.S["variantes"][0]
        o = thumb.resolve(self.S, v, "youtube")
        self.assertEqual((o["tempo_s"], o["titulo"], o["rosto_x"], o["kicker"]), (4, "variante", 0.3, "K"))
        o = thumb.resolve(self.S, v, "vertical")
        self.assertEqual((o["tempo_s"], o["titulo"]), (1, "variante"))

    def test_cli_vence_tudo(self):
        o = thumb.resolve(self.S, self.S["variantes"][0], "youtube", time=9, rosto_x=0.9)
        self.assertEqual((o["tempo_s"], o["rosto_x"]), (9, 0.9))

    def test_textos_faltando_viram_vazio(self):
        o = thumb.resolve({"tempo_s": 1, "titulo": "t"}, {}, "vertical")
        self.assertEqual((o["kicker"], o["rodape"], o["destaque"], o["rosto_x"]), ("", "", "", None))


class Destaque(unittest.TestCase):
    def hl(self, titulo, d):
        with quiet() as out: r = thumb.highlight(titulo.split(), d)
        return r, out.getvalue()

    def test_pontuacao_no_destaque_e_no_titulo(self):
        self.assertEqual(self.hl("O chat acha que você é homem?", "homem?")[0], {6})
        self.assertEqual(self.hl("O chat acha que você é homem?", "Homem")[0], {6})

    def test_varias_palavras_em_sequencia(self):
        self.assertEqual(self.hl("Isso não deixa a IA mais esperta", "mais  ESPERTA!")[0], {5, 6})
        self.assertEqual(self.hl("a IA, a ia e a IA", "a IA")[0], {0, 1, 2, 3, 5, 6})

    def test_nao_achou_avisa(self):
        r, out = self.hl("A IA inventa a conta", "esperta")
        self.assertEqual(r, set()); self.assertIn("aviso", out)
        r, out = self.hl("mais algo esperta", "mais esperta")  # palavras soltas nao contam
        self.assertEqual(r, set())

    def test_vazio_nao_avisa(self):
        self.assertEqual(self.hl("A IA", ""), (set(), ""))


class Texto(unittest.TestCase):
    T = P["youtube_16x9"]["titulo"]

    def test_palavra_longa_encolhe_ate_caber(self):
        f, words, lines, lh = thumb.fit("Pare de dizer que a IA é especialista", F_T, self.T, 440)
        self.assertLess(f.size, self.T["tam"])
        self.assertLessEqual(max(f.getlength(" ".join(words[i] for i in l)) for l in lines), 440)

    def test_limite_de_linhas(self):
        cfg = dict(self.T, linhas_max=2)  # no tamanho do preset (84) daria 4 linhas
        f, words, lines, lh = thumb.fit("A IA inventa a conta toda vez", F_T, cfg, 440)
        self.assertLessEqual(len(lines), 2); self.assertLess(f.size, 84)
        self.assertEqual(sum(len(l) for l in lines), len(words))

    def test_altura_maxima(self):
        f, _, lines, lh = thumb.fit("A IA inventa a conta toda vez", F_T, self.T, 440, max_h=240)
        self.assertLessEqual(len(lines) * lh, 240); self.assertLess(f.size, 84)

    def test_nao_cabe_da_erro(self):
        with self.assertRaises(SystemExit) as c:
            thumb.fit("Inconstitucionalissimamente", F_T, self.T, 440)
        self.assertIn("encurte", str(c.exception.code))

    def test_texto_curto_fica_no_tamanho_do_preset(self):
        self.assertEqual(thumb.fit("A IA inventa a conta", F_T, P["vertical_9x16"]["titulo"], 900)[0].size, 112)


class Validacao(unittest.TestCase):
    def erro(self, S):
        with self.assertRaises(SystemExit) as c: thumb.validate(S)
        return str(c.exception.code)

    def test_spec_bom(self):
        thumb.validate(dict(SPEC, _nota="comentario"))
        thumb.validate({"tempo_s": 0, "titulo": "t"})

    def test_erros(self):
        casos = [({"titulo": "t"}, "falta tempo_s"),
                 ({"tempo_s": 1}, "falta titulo"),
                 ({"tempo_s": 1, "titulo": "  "}, "falta titulo"),
                 ({"tempo_s": 1, "titulo": "t", "titlo": "x"}, "chave desconhecida 'titlo'"),
                 ({"tempo_s": -1, "titulo": "t"}, "tempo_s deve ser"),
                 ({"tempo_s": "3", "titulo": "t"}, "tempo_s deve ser"),
                 ({"tempo_s": True, "titulo": "t"}, "tempo_s deve ser"),
                 ({"tempo_s": 1, "titulo": "t", "rosto_x": 1.5}, "rosto_x deve ser"),
                 ({"tempo_s": 1, "titulo": 3}, "titulo deve ser texto"),
                 ({"tempo_s": 1, "titulo": "t", "youtube": {"tempo": 2}}, "youtube: chave desconhecida"),
                 ({"tempo_s": 1, "titulo": "t", "vertical": []}, "vertical precisa ser um objeto"),
                 ({"tempo_s": 1, "titulo": "t", "variantes": []}, "pelo menos uma variante"),
                 ({"tempo_s": 1, "titulo": "t", "variantes": [{"tempo_s": 2}]}, "nome e obrigatorio"),
                 ({"tempo_s": 1, "titulo": "t", "variantes": [{"nome": "a b"}]}, "nome e obrigatorio"),
                 ({"tempo_s": 1, "titulo": "t", "variantes": [{"nome": "A", "youtube": {"rosto_x": -0.1}}]},
                  "variantes[0].youtube.rosto_x"),
                 ({"titulo": "t", "variantes": [{"nome": "A", "vertical": {"tempo_s": 1}}]}, "falta tempo_s (variante A, youtube)")]
        for S, msg in casos:
            with self.subTest(S=S): self.assertIn(msg, self.erro(S))

    def test_nomes_repetidos(self):
        S = copy.deepcopy(SPEC); S["variantes"][1]["nome"] = "A"
        self.assertIn("nome repetido", self.erro(S))

    def test_junta_todos_os_erros(self):
        m = self.erro({"tempo_s": -1, "titulo": "t", "rosto_x": 2, "x": 1})
        for k in ("tempo_s", "rosto_x", "'x'"): self.assertIn(k, m)

    def test_sheet(self):
        self.assertEqual(thumb.parse_sheet("3, 20,48.5,"), [3.0, 20.0, 48.5])
        for s in ("3,x", "", "-1,2"):
            with self.subTest(s=s), self.assertRaises(SystemExit): thumb.parse_sheet(s)


FF = shutil.which("ffmpeg")


@unittest.skipUnless(FF, "ffmpeg nao instalado")
class Integracao(unittest.TestCase):
    def test_capas_deterministicas_e_limpeza(self):
        with tempfile.TemporaryDirectory() as d:
            video = os.path.join(d, "v.mp4")
            subprocess.run([FF, "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=10:d=16",
                            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", video], check=True)
            out1, out2 = os.path.join(d, "c1"), os.path.join(d, "c2")
            os.makedirs(out1)
            for velho in ("capa_C_9x16_1080x1920.png", "capa_9x16_1080x1920.png", "outra.png"):
                open(os.path.join(out1, velho), "w").close()
            with quiet():
                r1 = thumb.run(video, SPEC, P, out1); r2 = thumb.run(video, SPEC, P, out2)
            nomes = ["capa_%s_%s.png" % (v, f) for v in "AB" for f in ("9x16_1080x1920", "16x9_1280x720")]
            self.assertEqual(sorted(r1), sorted(nomes))
            self.assertEqual(sorted(os.listdir(out1)), sorted(nomes + ["outra.png", "capas.json"]))  # so capa_*.png velhas somem
            from PIL import Image
            def h(p):
                with open(p, "rb") as f: return hashlib.md5(f.read()).hexdigest()
            for n in nomes:
                with Image.open(r1[n]) as im: self.assertEqual(im.size, (1080, 1920) if "9x16" in n else (1280, 720))
                self.assertEqual(h(r1[n]), h(r2[n]), n)
            # --only: gera so um formato e nao apaga o outro
            with quiet(): r3 = thumb.run(video, SPEC, P, out1, only="youtube")
            self.assertEqual(sorted(r3), sorted(n for n in nomes if "16x9" in n))
            self.assertEqual(sorted(os.listdir(out1)), sorted(nomes + ["outra.png", "capas.json"]))

    def test_tempo_depois_do_fim(self):
        with tempfile.TemporaryDirectory() as d:
            video = os.path.join(d, "v.mp4")
            subprocess.run([FF, "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=10:d=2",
                            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", video], check=True)
            with self.assertRaises(SystemExit) as c, quiet():
                thumb.run(video, {"tempo_s": 50, "titulo": "t"}, P, os.path.join(d, "c"))
            self.assertIn("t=50s", str(c.exception.code))
            self.assertFalse(os.path.exists(os.path.join(d, "c")))  # nada gravado


if __name__ == "__main__":
    unittest.main()
