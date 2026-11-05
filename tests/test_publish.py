"""publish.py: valida meta.json (tipos, limites, hashtags, capa, duracao) e gera publicar.md deterministico.

    python3 -m unittest discover tests
"""
import contextlib, copy, io, json, os, re, sys, tempfile, unicodedata, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from vtk import publish

with open(os.path.join(ROOT, "presets", "publish.json"), encoding="utf-8") as f:
    P = json.load(f)
YT, TT = P["limites"]["youtube"], P["limites"]["tiktok"]

META = {
    "titulos": ["Os 4 elementos de um bom prompt", "Alternativa curta"],
    "descricao": "Gancho curto.\n\nO que voce leva do video.",
    "legenda_tiktok": "Gancho curto da legenda.",
    "hashtags": {"tiktok": ["#InteligenciaArtificial", "#Prompt", "#Produtividade"],
                 "youtube": ["#InteligenciaArtificial", "#Prompt", "#Produtividade"]},
    "hashtags_motivo": "PROPOSTA: publico geral.",
    "capa": {"variante": "A", "motivo": "Rosto aberto e texto legivel."},
}
THUMB = {"variantes": [{"nome": "A", "vertical": {"tempo_s": 14}}, {"nome": "B"}]}
CAPAS = {f for v in "AB" for f in publish.arquivos_capa(v).values()}


def meta(**over):
    M = copy.deepcopy(META)
    M.update(over)
    return M


def check(M, dur=45.0, thumb=THUMB, capas=CAPAS):
    return publish.validate(publish.nfc(M), P, dur, thumb, capas)


class Campos(unittest.TestCase):
    def assertErro(self, M, trecho, **kw):
        erros, _ = check(M, **kw)
        self.assertTrue(any(trecho in e for e in erros), f"esperava '{trecho}' em {erros}")

    def test_meta_valido(self):
        self.assertEqual(check(META), ([], []))

    def test_cada_obrigatorio_ausente_ou_vazio(self):
        for k in publish.CAMPOS:
            for vazio in (None, "", [], {}):
                M = meta(); M[k] = vazio
                with self.subTest(k=k, v=vazio): self.assertErro(M, f"ausente ou vazio: {k}")
            M = meta(); del M[k]
            with self.subTest(k=k, v="del"): self.assertErro(M, f"ausente ou vazio: {k}")

    def test_tipos_errados(self):
        casos = [
            (dict(titulos="um titulo so"), "titulos precisa"),
            (dict(titulos=["a", "b", "c", "d"]), "titulos precisa"),
            (dict(titulos=["a", ""]), "titulos precisa"),
            (dict(titulos=["a", 3]), "titulos precisa"),
            (dict(descricao=5), "descricao precisa ser texto"),
            (dict(descricao=0), "descricao precisa ser texto"),
            (dict(legenda_tiktok=["x"]), "legenda_tiktok precisa ser texto"),
            (dict(hashtags_motivo={"a": 1}), "hashtags_motivo precisa ser texto"),
            (dict(hashtags=["#a"]), "hashtags precisa ser"),
            (dict(hashtags={"tiktok": ["#a", "#b", "#c"]}), "hashtags.youtube ausente"),
            (dict(hashtags={"tiktok": [], "youtube": [], "instagram": []}), "plataforma desconhecida 'instagram'"),
            (dict(hashtags={"tiktok": "#a #b", "youtube": []}), "hashtags.tiktok precisa ser lista"),
            (dict(hashtags={"tiktok": [], "youtube": [1]}), "hashtags.youtube precisa ser lista"),
            (dict(capa="A"), "capa precisa ser"),
            (dict(capa={"variante": "A"}), "capa.motivo"),
            (dict(capa={"motivo": "x", "variante": 1}), "capa.variante"),
            (dict(tags_youtube="ia, prompt"), "tags_youtube precisa"),
            (dict(comentario_fixado=3), "comentario_fixado precisa ser texto"),
            (dict(notas=["x"]), "notas precisa ser texto"),
        ]
        for over, trecho in casos:
            with self.subTest(over=over): self.assertErro(meta(**over), trecho)

    def test_meta_nao_objeto(self):
        self.assertErro(["x"], "objeto JSON")

    def test_hashtags_vazias_sao_validas(self):
        erros, _ = check(meta(hashtags={"tiktok": [], "youtube": []}))
        self.assertEqual(erros, [])

    def test_campo_desconhecido_avisa(self):
        erros, avisos = check(meta(comentario_fixo="x"))
        self.assertEqual(erros, [])
        self.assertTrue(any("comentario_fixo" in a for a in avisos))


class Textos(unittest.TestCase):
    def test_titulo_acima_do_max_e_erro(self):
        erros, _ = check(meta(titulos=["x" * (YT["titulo_max"] + 1)]))
        self.assertTrue(any("titulo 1" in e for e in erros))

    def test_titulo_so_acima_do_visivel_e_aviso(self):
        erros, avisos = check(meta(titulos=["x" * YT["titulo_max"]]))
        self.assertEqual(erros, [])
        self.assertTrue(any("titulo 1" in a and "feed" in a for a in avisos))
        erros, avisos = check(meta(titulos=["x" * YT["titulo_visivel_feed"]]))
        self.assertEqual((erros, avisos), ([], []))

    def test_nfc_antes_de_contar(self):
        nfd = unicodedata.normalize("NFD", "é" * YT["titulo_max"])
        self.assertGreater(len(nfd), YT["titulo_max"])
        erros, _ = check(meta(titulos=[nfd]))
        self.assertEqual(erros, [])

    def test_emoji_avisa(self):
        erros, avisos = check(meta(legenda_tiktok="Olha isso 🔥"))
        self.assertEqual(erros, [])
        self.assertTrue(any("emoji" in a and "legenda_tiktok" in a for a in avisos))

    def test_hashtag_dentro_do_texto(self):
        for k, v in (("descricao", "Veja #IA aqui"), ("legenda_tiktok", "#Prompt no comeco"), ("titulos", ["Prompt #1 do ano"])):
            with self.subTest(k=k):
                erros, _ = check(meta(**{k: v}))
                self.assertTrue(any("hashtag no texto" in e for e in erros), erros)

    def test_cerquilha_que_nao_e_hashtag(self):
        erros, _ = check(meta(descricao="Exemplo em C# e no site x.com/#secao; aspas &#39; ok"))
        self.assertEqual(erros, [])

    def test_menor_maior_no_youtube(self):
        for k, v in (("titulos", ["Prompt <bom>"]), ("descricao", "a > b")):
            with self.subTest(k=k):
                erros, _ = check(meta(**{k: v}))
                self.assertTrue(any("'<' ou '>'" in e for e in erros), erros)
        erros, _ = check(meta(legenda_tiktok="a > b"))
        self.assertEqual(erros, [])


class Hashtags(unittest.TestCase):
    def test_invalidas(self):
        for h in ("IA", "#com espaco", "#a-b", "#", "#ponto."):
            with self.subTest(h=h):
                erros, _ = check(meta(hashtags={"tiktok": ["#Ok", h, "#Mais"], "youtube": []}))
                self.assertTrue(any("invalidas em tiktok" in e for e in erros), erros)

    def test_acento_e_valido(self):
        erros, _ = check(meta(hashtags={"tiktok": ["#Inteligência", "#Prompt", "#Ação"], "youtube": []}))
        self.assertEqual(erros, [])

    def test_repetidas_sem_diferenciar_caixa(self):
        erros, _ = check(meta(hashtags={"tiktok": [], "youtube": ["#IA", "#Prompt", "#ia"]}))
        self.assertTrue(any("repetidas em youtube" in e and "#ia" in e for e in erros), erros)

    def test_fora_da_faixa_recomendada_avisa(self):
        erros, avisos = check(meta(hashtags={"tiktok": ["#A1"], "youtube": []}))
        self.assertEqual(erros, [])
        self.assertTrue(any(a.startswith("tiktok: 1 hashtags") for a in avisos))

    def test_youtube_60_ok_61_erro(self):
        n = YT["hashtags_max"]
        erros, _ = check(meta(descricao="d", hashtags={"tiktok": [], "youtube": [f"#T{i}" for i in range(n)]}))
        self.assertEqual(erros, [])
        erros, _ = check(meta(descricao="d", hashtags={"tiktok": [], "youtube": [f"#T{i}" for i in range(n + 1)]}))
        self.assertTrue(any("hashtags no YouTube" in e for e in erros), erros)

    def test_legenda_mais_hashtags_no_limite(self):
        hs = ["#Aa", "#Bb", "#Cc"]
        resto = TT["legenda_max"] - len("\n\n" + " ".join(hs))
        erros, _ = check(meta(legenda_tiktok="x" * resto, hashtags={"tiktok": hs, "youtube": []}))
        self.assertEqual(erros, [])
        erros, _ = check(meta(legenda_tiktok="x" * (resto + 1), hashtags={"tiktok": hs, "youtube": []}))
        self.assertTrue(any("legenda do TikTok + hashtags" in e for e in erros), erros)

    def test_descricao_mais_hashtags_no_limite(self):
        hs = ["#Aa", "#Bb", "#Cc"]
        resto = YT["descricao_max"] - len("\n\n" + " ".join(hs))
        erros, _ = check(meta(descricao="x" * resto, hashtags={"tiktok": [], "youtube": hs}))
        self.assertEqual(erros, [])
        erros, _ = check(meta(descricao="x" * (resto + 1), hashtags={"tiktok": [], "youtube": hs}))
        self.assertTrue(any("descricao + hashtags" in e for e in erros), erros)

    def test_descricao_em_bytes_avisa(self):
        erros, avisos = check(meta(descricao="ç" * 3000, hashtags={"tiktok": [], "youtube": []}))
        self.assertEqual(erros, [])
        self.assertTrue(any("bytes" in a for a in avisos))

    def test_tags_youtube_aspas_em_tag_com_espaco(self):
        self.assertEqual(publish.tags_total(["ia", "bom prompt"]), len("ia,bom prompt") + 2)
        cheio = ["x" * 99] * 5  # 5*99 + 4 virgulas = 499
        self.assertEqual(check(meta(tags_youtube=cheio))[0], [])
        com_espaco = cheio[:-1] + ["x" * 49 + " " + "x" * 49]  # 499 + 2 aspas = 501
        erros, _ = check(meta(tags_youtube=com_espaco))
        self.assertTrue(any("tags do YouTube somam 501" in e for e in erros), erros)


class CapaEDuracao(unittest.TestCase):
    def test_variante_inexistente(self):
        erros, _ = check(meta(capa={"variante": "Z", "motivo": "x"}))
        self.assertTrue(any("variante de capa 'Z'" in e for e in erros), erros)

    def test_sem_thumb_json(self):
        erros, _ = check(META, thumb=None)
        self.assertTrue(any("thumb.json" in e for e in erros), erros)

    def test_capa_provisoria(self):
        erros, _ = check(meta(capa={"variante": "A", "motivo": "PROVISÓRIA: escolher depois do thumb.py"}))
        self.assertTrue(any("provisoria" in e for e in erros), erros)

    def test_sem_pasta_de_capas(self):
        erros, _ = check(META, capas=None)
        self.assertTrue(any("pasta de capas" in e for e in erros), erros)

    def test_arquivo_da_capa_faltando(self):
        erros, _ = check(META, capas={publish.arquivos_capa("A")["9x16"]})
        self.assertTrue(any("capa_A_16x9" in e for e in erros), erros)

    def test_duracao_zero_e_erro(self):
        erros, _ = check(META, dur=0.0)
        self.assertTrue(any("0.0 s" in e for e in erros), erros)

    def test_duracao_acima_do_short_avisa_com_uma_casa(self):
        erros, avisos = check(META, dur=230.0)
        self.assertEqual(erros, [])
        self.assertTrue(any("230.0 s" in a for a in avisos), avisos)


def fake_ffprobe(bindir, saida):
    p = os.path.join(bindir, "ffprobe")
    with open(p, "w") as f:
        f.write(f"#!/bin/sh\necho '{saida}'\n")
    os.chmod(p, 0o755)


class Duracao(unittest.TestCase):
    def test_video_inexistente(self):
        with self.assertRaisesRegex(ValueError, "video nao encontrado"):
            publish.duracao("/nao/existe.mp4")

    def test_sem_ffprobe(self):
        with tempfile.TemporaryDirectory() as d:
            v = os.path.join(d, "f.mp4"); open(v, "w").close()
            with mock.patch.dict(os.environ, {"PATH": d}):
                with self.assertRaisesRegex(ValueError, "ffprobe nao encontrado"):
                    publish.duracao(v)

    def test_arredonda_e_saida_ilegivel(self):
        with tempfile.TemporaryDirectory() as d:
            v = os.path.join(d, "f.mp4"); open(v, "w").close()
            fake_ffprobe(d, "45.47")
            with mock.patch.dict(os.environ, {"PATH": d}):
                self.assertEqual(publish.duracao(v), 45.5)
            fake_ffprobe(d, "N/A")
            with mock.patch.dict(os.environ, {"PATH": d}):
                with self.assertRaisesRegex(ValueError, "nao consegui ler a duracao"):
                    publish.duracao(v)


class Main(unittest.TestCase):
    """Ponta a ponta: pasta do video em diretorio temporario (--name absoluto) e ffprobe falso no PATH."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.bin = os.path.join(d, "bin"); os.mkdir(self.bin)
        fake_ffprobe(self.bin, "62.34")
        self.vdir = os.path.join(d, "meu-video")
        os.makedirs(os.path.join(self.vdir, "capas"))
        for f in CAPAS: open(os.path.join(self.vdir, "capas", f), "w").close()
        self.video = os.path.join(self.vdir, "final.mp4"); open(self.video, "w").close()
        self.write("meta.json", META); self.write("thumb.json", THUMB)
        self.out = os.path.join(self.vdir, "publicar.md")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, data):
        with open(os.path.join(self.vdir, name), "w", encoding="utf-8") as f:
            f.write(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False))

    def run_main(self, *extra, video=None):
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"PATH": self.bin}), contextlib.redirect_stdout(buf):
            rc = publish.main(["--name", self.vdir, "--video", video or self.video, *extra])
        return rc, buf.getvalue()

    def read(self):
        with open(self.out, "rb") as f: return f.read()

    def test_gera_deterministico_sem_data(self):
        rc, _ = self.run_main()
        self.assertEqual(rc, 0)
        a = self.read()
        rc, _ = self.run_main()
        self.assertEqual(a, self.read())
        txt = a.decode("utf-8")
        self.assertNotRegex(txt, r"\d{4}-\d{2}-\d{2}")
        self.assertIn("# Publicar — meu-video", txt)
        self.assertIn("duração 1:02", txt)
        self.assertIn("capa_A_9x16_1080x1920.png", txt)
        self.assertIn("~14 s", txt)
        self.assertIn(f"as {YT['hashtags_acima_do_titulo']} primeiras hashtags", txt)

    def test_video_inexistente_sem_traceback(self):
        rc, out = self.run_main(video=os.path.join(self.vdir, "nao.mp4"))
        self.assertEqual(rc, 1)
        self.assertIn("ERRO: video nao encontrado", out)

    def test_meta_json_quebrado(self):
        self.write("meta.json", "{ nao e json")
        rc, out = self.run_main()
        self.assertEqual(rc, 1)
        self.assertIn("ERRO: meta.json ilegivel", out)

    def test_meta_json_ausente_lista_campos(self):
        os.remove(os.path.join(self.vdir, "meta.json"))
        rc, out = self.run_main()
        self.assertEqual(rc, 1)
        self.assertIn("hashtags_motivo", out)

    def test_capas_em_outra_pasta(self):
        rc, out = self.run_main("--capas", os.path.join(self.vdir, "nao-existe"))
        self.assertEqual(rc, 1)
        self.assertIn("pasta de capas", out)

    def test_erro_nao_deixa_publicar_md_velho(self):
        self.assertEqual(self.run_main()[0], 0)
        velho = self.read()
        self.write("meta.json", meta(capa={"variante": "Z", "motivo": "x"}))
        rc, out = self.run_main()
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(self.out))
        self.assertIn("desatualizado", out)
        with open(self.out + ".desatualizado", "rb") as f: self.assertEqual(f.read(), velho)
        self.write("meta.json", META)
        self.assertEqual(self.run_main()[0], 0)
        self.assertFalse(os.path.exists(self.out + ".desatualizado"))

    def test_erro_sem_publicar_md_nao_cria_nada(self):
        self.write("meta.json", meta(titulos="x"))
        rc, _ = self.run_main()
        self.assertEqual(rc, 1)
        self.assertEqual(sorted(f for f in os.listdir(self.vdir) if f.startswith("publicar")), [])


if __name__ == "__main__":
    unittest.main()
