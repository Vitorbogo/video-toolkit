"""Hook guard.py: sfx/*.wav é a única mídia que pode entrar no git.

    python3 -m unittest discover tests
"""
import importlib.util, os, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("guard", os.path.join(ROOT, ".claude", "hooks", "guard.py"))
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

ADD = "git " + "add "


class SfxNoGit(unittest.TestCase):
    def test_libera_efeitos_de_sfx(self):
        for c in [ADD + "sfx/whoosh-curto.wav", ADD + "sfx/*.wav", ADD + "./sfx/pop-blip.wav src/vtk/sfx.py", ADD + "sfx/"]:
            self.assertIsNone(guard.check(c), c)

    def test_continua_bloqueando_o_resto(self):
        for c in [ADD + "work/x.wav sfx/a.wav", ADD + "foo/sfx/a.wav", ADD + "-" + "f sfx/a.wav", ADD + "final.mp4",
                  ADD + "sfx/a.wav.mov"]:
            self.assertIsNotNone(guard.check(c), c)


if __name__ == "__main__":
    unittest.main()
