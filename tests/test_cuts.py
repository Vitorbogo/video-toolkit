"""cuts.decide: palavras do Parakeet -> plan.json do render.py, com a skill de terceiros decidindo os cortes.

    python3 -m unittest discover tests
"""
import json, os, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from vtk import cuts


def words(spec):
    """[(palavra, inicio, fim), ...] -> formato do transcript.json"""
    return [{"w": w, "start": s, "end": e} for w, s, e in spec]


def text_of(plan):
    return " ".join(cuts.legendas(plan))


def invariantes(tc, plan, fps=30.0):
    """O que o render.py espera de qualquer plan.json: trechos crescentes, sem sobreposição, no quadro, de pelo
    menos 0,4 s, e legendas/borrões dentro do trecho."""
    tc.assertTrue(plan, "plano vazio")
    for k, c in enumerate(plan):
        d = c["e"] - c["s"]
        tc.assertGreaterEqual(c["s"], 0, c)
        tc.assertGreaterEqual(d, 0.4 - 1e-6, c)
        if k: tc.assertGreater(c["s"], plan[k - 1]["e"], (plan[k - 1], c))
        for t in (c["s"], c["e"]):
            tc.assertAlmostEqual(t * fps, round(t * fps), delta=1e-3, msg=f"{t} fora do quadro")
            tc.assertEqual(t, round(t, 6))
        for x0, x1, t in c["ev"]:
            tc.assertTrue(0 <= x0 < x1 <= d + 1e-6, (x0, x1, t, d))
        tc.assertLessEqual(c.get("z", 1), 1.2)
        for b in c.get("blur", []):
            tc.assertTrue(0 <= b[0] < b[1] <= d + 1e-6 and len(b) == 6, (b, d))


def decide(tc, ws, edit=None, **kw):
    plan, removed, maybe = cuts.decide(ws, edit or {}, **kw)
    invariantes(tc, plan, kw.get("fps", 30.0))
    return plan, removed, maybe


def frase(texto, t0=0.0, dur=0.3, gap=0.1):
    """Palavras de dur segundos com gap entre elas, a partir de t0."""
    out, t = [], t0
    for w in texto.split():
        out.append((w, round(t, 3), round(t + dur, 3))); t += dur + gap
    return out


class Decide(unittest.TestCase):
    def test_artigo_fica_e_hesitacao_sai_do_video_e_da_legenda(self):
        ws = words([("Estou", 0.0, 0.3), ("com", 0.4, 0.6), ("um", 0.7, 0.8), ("contrato.", 0.9, 1.4),
                    ("ééé", 1.6, 2.4), ("Quero", 2.6, 2.9), ("um", 3.0, 3.1), ("resumo.", 3.2, 3.8)])
        plan, removed, _ = decide(self, ws, total=4.5)
        self.assertEqual(text_of(plan), "Estou com um contrato. Quero um resumo.")
        # nenhum pedaco do "ééé" (1,6 a 2,4 s) pode ficar: a skill deixa a "respiracao" dentro dele
        for c in plan:
            self.assertFalse(c["s"] < 2.4 and c["e"] > 1.6, c)
        self.assertTrue(any("enchimento" in r[2] and "ééé" in r[3] for r in removed), removed)

    def test_legenda_corrigida_e_relativa_ao_trecho_depois_de_pausa_longa(self):
        ws = words([("Use", 0.0, 0.3), ("a", 0.4, 0.5), ("Ya.", 0.6, 1.0),
                    ("Ela", 5.0, 5.3), ("resume.", 5.4, 6.0)])
        plan, _, _ = decide(self, ws, {"replace": {"Ya": "IA"}}, total=6.5)
        self.assertEqual(len(plan), 2)  # a pausa de 4 s vira um corte
        segundo = plan[1]
        self.assertEqual([t for _, _, t in plan[0]["ev"]], ["Use a IA."])
        x0, x1, t = segundo["ev"][0]
        self.assertEqual(t, "Ela resume.")
        self.assertAlmostEqual(segundo["s"] + x0, 5.0, delta=0.01)
        self.assertAlmostEqual(segundo["s"] + x1, 6.0, delta=0.01)

    def test_frase_longa_quebra_no_limite_de_caracteres(self):
        texto = "Quero um resumo executivo com objeto obrigações principais cláusulas de rescisão e riscos."
        plan, _, _ = decide(self, words(frase(texto)), total=6.0, max_chars=30)
        evs = [t for c in plan for _, _, t in c["ev"]]
        self.assertEqual(" ".join(evs), texto)
        self.assertTrue(all(len(t) <= 30 for t in evs), evs)

    def test_quebra_equilibrada_sem_palavra_orfa(self):
        # 69 caracteres com limite 60: antes saia "... tenho que arrumar" + "o texto." (0,7 s na tela)
        texto = "O chat acha que eu sou homem e toda vez eu tenho que arrumar o texto."
        plan, _, _ = decide(self, words(frase(texto, dur=0.2, gap=0.05)), total=5.0)
        evs = plan[0]["ev"]
        self.assertEqual([t for _, _, t in evs], ["O chat acha que eu sou homem", "e toda vez eu tenho que arrumar o texto."])

    def test_frase_que_atravessa_um_corte_fica_inteira_dos_dois_lados(self):
        # o "ééé" no meio da frase vira emenda: "Hoje" sozinho no 1o trecho seria uma legenda orfa
        ws = words(frase("Bom dia.", 0.0) + [("Hoje", 1.2, 1.5), ("ééé", 1.8, 2.6)] + frase("o contrato tem três cláusulas.", 2.9))
        plan, _, _ = decide(self, ws, total=5.5)
        self.assertEqual(len(plan), 2)
        self.assertEqual(plan[0]["ev"][-1][2], "Hoje o contrato tem três cláusulas.")
        self.assertEqual(plan[1]["ev"][0][:1] + plan[1]["ev"][0][2:], [0.0, "Hoje o contrato tem três cláusulas."])
        self.assertAlmostEqual(plan[0]["ev"][-1][1], plan[0]["e"] - plan[0]["s"], places=5)
        self.assertEqual(text_of(plan), "Bom dia. Hoje o contrato tem três cláusulas.")

    def test_legenda_curta_junta_com_a_vizinha_e_fica_1_s(self):
        ws = words([("Sim.", 0.0, 0.3), ("Isso", 0.5, 0.8), ("mesmo.", 0.9, 1.3), ("Ok.", 1.5, 1.8)])
        plan, _, _ = decide(self, ws, total=2.5)
        evs = plan[0]["ev"]
        self.assertEqual([t for _, _, t in evs], ["Sim. Isso mesmo. Ok."])
        self.assertGreaterEqual(evs[0][1] - evs[0][0], 1.0)

    def test_muleta_do_edit_json_soma_com_a_lista_pt(self):
        ws = words([("Isso", 0.0, 0.3), ("muda,", 0.4, 0.8), ("né,", 1.0, 1.3), ("sabe,", 1.5, 1.8), ("tudo.", 2.0, 2.4)])
        plan, _, _ = decide(self, ws, {"extra_fillers": ["sabe"]}, total=3.0)
        self.assertEqual(text_of(plan), "Isso muda, tudo.")

    def test_palavra_colada_no_enchimento_nao_e_cortada(self):
        # "Quero" comeca 20 ms depois do "ééé": menos de um quadro
        ws = words([("Contrato.", 0.0, 0.5), ("ééé", 0.6, 1.21), ("Quero", 1.23, 1.5), ("resumo.", 1.6, 2.0)])
        plan, removed, _ = decide(self, ws, total=2.5)
        self.assertEqual(text_of(plan), "Contrato. Quero resumo.")
        quero = next(c for c in plan if "Quero" in " ".join(t for _, _, t in c["ev"]))
        self.assertLessEqual(quero["s"], 1.23 - cuts.PRE_ROLL + 1e-6)  # pre-roll da skill antes da palavra

    def test_enchimento_colado_dos_dois_lados_volta_para_a_legenda(self):
        # cortar o "hum" daria emenda de menos de 0,12 s: nao corta, e a legenda mostra o que se ouve
        ws = words([("Isso", 0.0, 0.4), ("é", 0.45, 0.6), ("hum", 0.62, 0.74), ("bom.", 0.76, 1.2)])
        plan, _, _ = decide(self, ws, total=1.6)
        self.assertEqual(len(plan), 1)
        self.assertEqual(text_of(plan), "Isso é hum bom.")

    def test_maiuscula_depois_de_abertura_removida(self):
        ws = words(frase("Isso é bom.", 0.0) + frase("Então, quando você fala isso.", 1.5))
        plan, removed, _ = decide(self, ws, total=4.5)
        self.assertEqual(text_of(plan), "Isso é bom. Quando você fala isso.")

    def test_maiuscula_no_comeco_depois_de_corte_a_mao(self):
        ws = words(frase("Bom dia. vamos lá.", 0.0))
        plan, _, _ = decide(self, ws, {"cut": [[0.0, 0.75]]}, total=2.5)
        self.assertEqual(text_of(plan), "Vamos lá.")

    def test_keep_mantem_o_que_a_skill_tiraria(self):
        ws = words(frase("Isso muda, né, tudo."))
        plan, _, _ = decide(self, ws, {"keep": [[0.8, 1.1]]}, total=2.5)
        self.assertEqual(text_of(plan), "Isso muda, né, tudo.")

    def test_corte_a_mao(self):
        ws = words(frase("Primeiro isso.", 0.0) + frase("Frase abandonada que.", 1.5) + frase("Depois aquilo.", 3.5))
        plan, removed, _ = decide(self, ws, {"cut": [[1.5, 2.6, "abandonada"]]}, total=5.0)
        self.assertEqual(text_of(plan), "Primeiro isso. Depois aquilo.")
        self.assertTrue(any("corte à mão" in r[2] and r[3] == "Frase abandonada que." for r in removed), removed)

    def test_corte_a_mao_sem_palavra_avisa(self):
        avisos = []
        ws = words(frase("Primeiro isso.", 0.0) + frase("Depois aquilo.", 3.5))
        decide(self, ws, {"cut": [[1.5, 2.6]]}, total=5.0, avisos=avisos)
        self.assertTrue(any("cut 1.5-2.6" in a and "trim" in a for a in avisos), avisos)

    def test_gagueira(self):
        ws = words([("Isso", 0.0, 0.3), ("é", 0.5, 0.65), ("é", 0.85, 1.0), ("importante.", 1.1, 1.7)])
        plan, removed, _ = decide(self, ws, total=2.2)
        self.assertEqual(text_of(plan), "Isso é importante.")
        self.assertTrue(any("gagueira" in r[2] for r in removed), removed)

    def test_retomada_e_possivel_retomada(self):
        # frase inacabada e recomecada logo depois: a skill corta sozinha
        ws = words(frase("O contrato tem", 0.0) + frase("O contrato tem três cláusulas.", 2.0))
        plan, removed, _ = decide(self, ws, total=4.5)
        self.assertEqual(text_of(plan), "O contrato tem três cláusulas.")
        self.assertTrue(any("retomada" in r[2] for r in removed), removed)
        # frase completa e repetida: so sugere; some do relatorio quando o corte a mao tira a primeira
        ws = words(frase("O contrato tem duas.", 0.0) + frase("O contrato tem três cláusulas.", 2.0))
        _, _, maybe = decide(self, ws, total=4.5)
        self.assertEqual(len(maybe), 1)
        plan, removed, maybe = decide(self, ws, {"cut": [[0.0, 1.5]]}, total=4.5)
        self.assertEqual(maybe, [])
        self.assertNotIn("Possíveis retomadas", cuts.report(plan, removed, maybe, 4.5))

    def test_replace_com_mais_de_uma_palavra(self):
        ws = words(frase("Abra o chat GPT agora e peça um resumo do contrato inteiro."))
        plan, _, _ = decide(self, ws, {"replace": {"chat GPT": "ChatGPT"}}, total=6.0, max_chars=12)
        evs = [t for c in plan for _, _, t in c["ev"]]
        self.assertTrue(any("ChatGPT" in t for t in evs), evs)  # a quebra nao separa "chat" de "GPT"
        ws = words(frase("Apelido, ocupação, mais."))
        plan, _, _ = decide(self, ws, {"replace": {"ocupação": "ocupação,"}}, total=2.0)
        self.assertEqual(text_of(plan), "Apelido, ocupação, mais.")

    def test_trim_tira_trecho_sem_palavra_e_avisa_se_pega_palavra(self):
        # pausa de 0,45 s dentro da frase: a skill mantem; o trim tira
        ws = words([("Um", 0.0, 0.4), ("dois", 0.5, 0.9), ("três", 1.35, 1.8), ("quatro.", 1.9, 2.4)])
        plan, removed, _ = decide(self, ws, total=3.0)
        self.assertEqual(len(plan), 1)
        avisos = []
        plan, removed, _ = decide(self, ws, {"trim": [[0.95, 1.25, "respiração"]]}, total=3.0, avisos=avisos)
        self.assertEqual(len(plan), 2)
        self.assertAlmostEqual(plan[0]["e"], 0.95, delta=1 / 30)
        self.assertAlmostEqual(plan[1]["s"], 1.25, delta=1 / 30)
        self.assertTrue(any("trim" in r[2] for r in removed), removed)
        self.assertEqual(text_of(plan), "Um dois três quatro.")
        self.assertEqual(avisos, [])
        decide(self, ws, {"trim": [[0.95, 1.5]]}, total=3.0, avisos=avisos)
        self.assertTrue(any("três" in a for a in avisos), avisos)

    def test_zoom_do_edit_json(self):
        ws = words(frase("Primeira frase.", 0.0) + frase("Segunda frase.", 4.0) + frase("Terceira frase.", 8.0))
        plan, _, _ = decide(self, ws, {"zoom": [[4.3, 1.15], [8.2, 1.5]]}, total=10.0)
        self.assertEqual([c.get("z", 1) for c in plan], [1, 1.15, 1.2])
        plan, _, _ = decide(self, ws, {"zoom": [[4.3, 1]]}, total=10.0, zoom=1.1)
        self.assertEqual([c.get("z", 1) for c in plan], [1, 1, 1])

    def test_blur_vira_borrao_relativo_em_cada_trecho(self):
        ws = words(frase("Primeira frase.", 0.0) + frase("Segunda frase.", 4.0) + frase("Terceira frase.", 8.0))
        plan, _, _ = decide(self, ws, {"blur": [[0.5, 4.3, 10, 20, 300, 400, "barra lateral"]]}, total=10.0)
        a, b, c = plan
        self.assertEqual(a["blur"], [[round(0.5 - a["s"], 3), round(a["e"] - a["s"], 6), 10, 20, 300, 400]])
        self.assertEqual(b["blur"], [[0.0, round(4.3 - b["s"], 3), 10, 20, 300, 400]])
        self.assertNotIn("blur", c)

    def test_relatorio_soma_os_intervalos_reais(self):
        ws = words(frase("Bom dia.", 1.0) + [("ééé", 2.0, 2.6)] + frase("Hoje tem contrato.", 2.9)
                   + frase("Agora outra coisa.", 7.0))
        plan, removed, maybe = decide(self, ws, total=10.0)
        gaps = [(0.0, plan[0]["s"])] + [(p["e"], q["s"]) for p, q in zip(plan, plan[1:])] + [(plan[-1]["e"], 10.0)]
        self.assertEqual([(a, b) for a, b, _, _ in removed], [(a, b) for a, b in gaps if b - a >= 0.01])
        self.assertAlmostEqual(sum(b - a for a, b, _, _ in removed) + sum(c["e"] - c["s"] for c in plan), 10.0, places=6)
        md = cuts.report(plan, removed, maybe, 10.0)
        self.assertEqual(md.count("\n| "), len(removed) + 1)

    def test_energia_do_audio_estende_as_bordas(self):
        # o som de "frase." vai ate 1,35 s, alem do fim do Parakeet (1,2 s); "Outra" comeca a soar 0,12 s antes
        ws = words([("Uma", 0.3, 0.7), ("frase.", 0.8, 1.2), ("Outra", 4.0, 4.4), ("frase.", 4.5, 5.0)])
        voz = [(0.3, 1.35), (3.88, 5.0)]
        db = [-20.0 if any(a <= k * 0.01 < b for a, b in voz) else -70.0 for k in range(600)]
        sem, _, _ = decide(self, ws, total=6.0)
        com, _, _ = decide(self, ws, total=6.0, db=db, floor=-70.0)
        self.assertGreater(com[0]["e"], 1.35 + 0.03)
        self.assertGreater(com[0]["e"], sem[0]["e"])
        self.assertLess(com[1]["s"], sem[1]["s"])
        self.assertLessEqual(com[1]["s"], 3.88 - 0.03)
        # piso de ruido alto (tudo abaixo de piso + 6 dB conta como silencio): a borda volta para perto do Parakeet
        alto, _, _ = decide(self, ws, total=6.0, db=db, floor=-15.0)
        self.assertLess(alto[0]["e"], com[0]["e"])


class Cli(unittest.TestCase):
    def test_force_guarda_bak_e_usa_edit_e_transcript_da_pasta(self):
        with tempfile.TemporaryDirectory() as d:
            v = os.path.join(d, "videos", "x"); os.makedirs(v)
            ws = words(frase("Primeiro isso.", 0.0) + frase("Frase abandonada.", 1.5) + frase("Depois aquilo.", 3.5))
            for f, data in (("transcript.json", {"words": ws}), ("edit.json", {"cut": [[1.5, 2.6]]}), ("plan.json", ["revisado"])):
                with open(os.path.join(v, f), "w", encoding="utf-8") as fh: json.dump(data, fh)
            stubs = dict(check_tools=lambda: None, probe=lambda p: (100, 100, 5.0, 60.0),
                         audio_energy=lambda p: ([], -60.0), visual_events=lambda p: ([], []))
            argv = ["cuts.py", "--video", "v.mov", "--name", "x"]
            with open(os.devnull, "w") as nul, mock.patch.object(cuts, "ROOT", d), \
                    mock.patch.multiple(cuts.ev, **stubs), mock.patch("sys.stdout", new=nul):
                with mock.patch.object(sys, "argv", argv), self.assertRaises(SystemExit):
                    cuts.main()  # sem --force nao sobrescreve
                with mock.patch.object(sys, "argv", argv + ["--force"]):
                    cuts.main()
            def ler(f):
                with open(os.path.join(v, f), encoding="utf-8") as fh: return fh.read()
            self.assertEqual(json.loads(ler("plan.json.bak")), ["revisado"])
            plan = json.loads(ler("plan.json"))
            invariantes(self, plan)
            self.assertEqual(text_of(plan), "Primeiro isso. Depois aquilo.")
            self.assertIn("corte à mão", ler("edit-plan.md"))


if __name__ == "__main__":
    unittest.main()
