"""Hook guard.py: do HyperFrames só o que é local e grátis passa.

    python3 -m unittest discover tests
"""
import importlib.util, os, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("guard", os.path.join(ROOT, ".claude", "hooks", "guard.py"))
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

HF = "npx hyperframes@0.9.16 "


class HyperFrames(unittest.TestCase):
    def test_local_e_gratis_passa(self):
        for c in ["init ilustracao --example blank --non-interactive --skip-skills --resolution square", "lint",
                  "snapshot --at 4,8.3", "render -o ../ilustracao.mp4", "docs gsap", "telemetry disable",
                  "preview --background", "transcribe audio.wav", "tts 'oi'", "--help"]:
            self.assertIsNone(guard.check(HF + c), c)
        self.assertIsNone(guard.check("cd videos/x/ilustracao && npx hyperframes render -o a.mp4"))

    def test_pago_ou_nuvem_bloqueia(self):
        for c in ["auth login", "auth status", "billing", "billing add-credits", "cloud render", "lambda deploy",
                  "cloudrun deploy", "publish", "templates pull finance", "reverse x.mp4", "catch-up",
                  "transcribe a.wav --engine heygen", "tts oi --engine=heygen", "skills update style-sampling",
                  "skills update reverse-any-video"]:
            self.assertIsNotNone(guard.check(HF + c), c)
        self.assertIsNotNone(guard.check("npx hyperframes auth login"))
        self.assertIsNotNone(guard.check("cd x && npx -y hyperframes@latest cloud render"))


if __name__ == "__main__":
    unittest.main()
