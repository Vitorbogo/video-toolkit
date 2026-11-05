"""Contrato com a skill de terceiros (vendor/dev-video-editing, sem modificações): se ela for atualizada, estes
testes dizem o que mudou nas funções que usamos (src/vtk/_vendor.py, USED).

    python3 -m unittest discover tests
"""
import ast, inspect, os, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from vtk import _vendor, cuts
from vtk._vendor import ev

# como cuts.py e render.py chamam cada função da skill (nomes dos parâmetros, na ordem)
CHAMADAS = {
    "mark": ["words", "spec"],
    "plan_spans": ["words", "reason", "spec", "total", "fps", "db", "floor", "blacks", "scenes"],
    "zoom_plan": ["spans", "spec", "scenes", "blacks"],
    "apply_replace": ["text", "rep"],
    "stamp": ["t"],
    "probe": ["path"],
    "audio_energy": ["src"],
    "visual_events": ["src"],
    "check_tools": [],
}


def usados(path):
    """Atributos da skill acessados num arquivo nosso (pelo nome com que 'ev' de vtk._vendor foi importado)."""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    nomes = {a.asname or a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "vtk._vendor"
             for a in n.names if a.name == "ev"}
    return {n.attr for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in nomes}


class Contrato(unittest.TestCase):
    def test_used_existe_na_skill(self):
        for nome in _vendor.USED:
            self.assertTrue(hasattr(ev, nome), nome)
        self.assertIsInstance(ev.WARNINGS, list)
        self.assertIsInstance(ev.EYE_LINE, float)

    def test_assinaturas_das_funcoes_chamadas(self):
        for nome, params in CHAMADAS.items():
            self.assertIn(nome, _vendor.USED)
            self.assertEqual(list(inspect.signature(getattr(ev, nome)).parameters), params, nome)
        self.assertEqual(inspect.signature(ev.zoom_plan).parameters["blacks"].default, ())

    def test_nossos_arquivos_so_usam_o_que_esta_em_used(self):
        for f in ("src/vtk/cuts.py", "src/vtk/render.py"):
            path = os.path.join(ROOT, f)
            with open(path, encoding="utf-8") as fh:
                self.assertNotIn("edit_video.py", fh.read(), f"{f}: carregar a skill por vtk._vendor")
            self.assertLessEqual(usados(path), set(_vendor.USED), f)
        self.assertLessEqual(set(CHAMADAS), usados(os.path.join(ROOT, "src/vtk/cuts.py")))

    def test_constantes_copiadas_da_skill(self):
        self.assertEqual(cuts.PRE_ROLL, ev.PRE_ROLL)
        self.assertEqual(ev.PRESETS["youtube"]["min_cut"], cuts.MIN_PIECE)


# transcrição fixa: enchimento, gagueira, muleta com vírgula, corte e trim à mão, replace de duas palavras, pausa
# longa, zoom e borrão. Se a skill mudar a decisão, este resultado muda: conferir antes de atualizar.
W = [("Bom", 0.5, 0.8), ("dia.", 0.9, 1.3), ("ééé", 1.6, 2.2), ("Hoje", 2.5, 2.8), ("o", 2.9, 3.0), ("o", 3.1, 3.2),
     ("contrato", 3.3, 3.8), ("chat", 3.9, 4.2), ("GPT,", 4.3, 4.7), ("né,", 4.9, 5.2), ("tem", 5.4, 5.6), ("três", 5.7, 6.0),
     ("cláusulas.", 6.1, 6.9), ("Frase", 7.5, 7.8), ("abandonada.", 7.9, 8.6), ("Agora", 12.0, 12.3), ("a", 12.4, 12.5),
     ("parte", 12.6, 12.9), ("final", 13.0, 13.4), ("do", 13.5, 13.6), ("vídeo.", 13.7, 14.3)]
EDIT = {"cut": [[7.5, 8.6, "abandonada"]], "replace": {"chat GPT": "ChatGPT"}, "trim": [[13.41, 13.49]],
        "zoom": [[12.5, 1.1]], "blur": [[3.0, 13.0, 10, 20, 300, 400]]}
FRASE = "Hoje o contrato ChatGPT, tem três cláusulas."
FIM = "Agora a parte final do vídeo."
PLANO = [
    {"s": 0.266667, "e": 1.6, "ev": [[0.233, 1.233, "Bom dia."]]},
    {"s": 2.233333, "e": 2.866667, "ev": [[0.267, 0.633334, FRASE]]},
    {"s": 3.0, "e": 4.9, "ev": [[0.0, 1.9, FRASE]], "blur": [[0.0, 1.9, 10, 20, 300, 400]]},
    {"s": 5.2, "e": 7.466667, "ev": [[0.0, 1.7, FRASE]], "blur": [[0.0, 2.266667, 10, 20, 300, 400]]},
    {"s": 11.533333, "e": 13.4, "ev": [[0.467, 1.866667, FIM]], "z": 1.1, "blur": [[0.0, 1.467, 10, 20, 300, 400]]},
    {"s": 13.5, "e": 14.733333, "ev": [[0.0, 0.8, FIM]]},
]
REMOVIDOS = [(0.0, 0.266667, "silêncio", ""), (1.6, 2.233333, "enchimento", "ééé"), (2.866667, 3.0, "gagueira", "o"),
             (4.9, 5.2, "enchimento", "né,"), (7.466667, 11.533333, "corte à mão, silêncio", "Frase abandonada."),
             (13.4, 13.5, "trim, silêncio", ""), (14.733333, 15.0, "silêncio", "")]


class Golden(unittest.TestCase):
    def test_decide_numa_transcricao_fixa(self):
        ws = [{"w": w, "start": s, "end": e} for w, s, e in W]
        avisos = []
        plan, removed, maybe = cuts.decide(ws, EDIT, total=15.0, avisos=avisos)
        self.assertEqual(plan, PLANO)
        self.assertEqual(removed, REMOVIDOS)
        self.assertEqual((maybe, avisos), ([], []))


if __name__ == "__main__":
    unittest.main()
