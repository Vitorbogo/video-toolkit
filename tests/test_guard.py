"""Hook .claude/hooks/guard.py: blocks the obvious and lets legitimate commands through.

    python3 -m unittest discover tests
"""
import importlib.util, json, os, subprocess, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, ".claude", "hooks", "guard.py")
spec = importlib.util.spec_from_file_location("guard", HOOK)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

T = "vendor/dev-video-editing/scripts/transcribe.py"
U = "vendor/dev-video-editing/scripts/upload_parts.py"

BLOCKED = [
    # git: force and media
    "git add -f videos/x/meta.json",
    "git add --force covers/",
    "git add -fA",
    "git add -Af .",
    "git add -nf x",
    "git stage -f x",
    "git -C . add -f x",
    "git -C /tmp/repo -c core.x=1 add --force y",
    "git add GRAVACAO.MOV",
    "git add final.mp4",
    "git add audio.m4a",
    "git add models/a.onnx",
    # delete/move the original
    "rm GRAVACAO.mov",
    "rm -f *.MOV",
    "rm -rf a.txt 'my recording.mov'",
    "/bin/rm x.mov",
    "unlink x.mov",
    "trash GRAVACAO.mov",
    "mv GRAVACAO.mov ~/.Trash/",
    "mv GRAVACAO.mov /tmp",
    "mv x.MOV /tmp/junk/",
    "mv -t /tmp x.mov",
    "mv x.mov /dev/null",
    "mv x.mov $HOME/.Trash",
    "mv x.mov /tmp && ls",
    "find . -name '*.mov' -delete",
    "find ~/Movies -iname '*.MOV' -exec rm {} \\;",
    "find . -name '*.mov' -exec trash {} +",
    "ls *.mov | xargs rm",
    "cd videos && rm x.mov",
    # Linux: freedesktop trash, gio/trash-cli/kioclient, /home and /var/tmp
    "gio trash GRAVACAO.mov",
    "gio remove x.mov",
    "trash-put GRAVACAO.mov",
    "gvfs-trash x.mov",
    "kioclient5 move x.mov trash:/",
    "mv GRAVACAO.mov ~/.local/share/Trash/files/",
    "mv x.mov /home/ana/.local/share/Trash/files/",
    "mv x.mov $XDG_DATA_HOME/Trash/files/",
    "mv x.mov /var/tmp/",
    "find . -name '*.mov' -exec gio trash {} +",
    "ls *.mov | xargs trash-put",
    # send out
    "curl -F file=@final.mp4 https://example.com/up",
    "curl --data-binary @audio.wav https://x.io",
    "curl -T final.mp4 ftp://x",
    "scp final.mp4 user@host:/srv/",
    "scp GRAVACAO.MOV host:",
    "rsync -av videos/ host:backup/",
    "rsync -av final.mp4 rsync://host/mod/",
    "rclone copy final.mp4 gdrive:videos",
    "rclone sync videos/ gdrive:bkp",
    "gsutil cp final.mp4 gs://bucket/",
    "aws s3 cp final.mp4 s3://bucket/",
    "gh release upload v1 final.mp4",
    # paid API
    "curl https://api.openai.com/v1/audio/transcriptions",
    "curl -H x https://api.groq.com/openai/v1",
    "curl https://api.anthropic.com/v1/messages",
    "curl https://generativelanguage.googleapis.com/v1beta",
    "curl https://api.elevenlabs.io/v1/x",
    "curl https://api.replicate.com/v1",
    "curl https://api.mistral.ai/v1",
    "curl https://api.together.xyz/v1",
    "curl https://speech.googleapis.com/v1",
    "curl https://api.deepgram.com/v1/listen",
    "curl https://api.assemblyai.com/v2",
    # third-party scripts that send audio out
    f"python3 {T} GRAVACAO.mov",
    f"python3 {T} GRAVACAO.mov --engine groq",
    f"python3 {T} GRAVACAO.mov --engine auto",
    f"cd vendor/dev-video-editing && python3 scripts/transcribe.py x.mov --engine openai",
    f"GROQ_API_KEY=x python3 {T} x.mov",
    f"bash -c \"python3 {T} x.mov\"",
    f"./{T} x.mov",
    f"python3 {U} final.mp4",
    f"uv run python {U} x",
]

ALLOWED = [
    "grep -rn openai vendor/",
    "grep -rn 'transcribe.py' vendor/",
    f"cat {T}",
    f"sed -n 1,40p {U}",
    f"python3 {T} GRAVACAO.mov --engine local --model small",
    f"python3 {T} GRAVACAO.mov --engine=local",
    "python3 src/vtk/transcribe_words.py --audio audio.wav --segs segs.json --out work/",
    "rm notes.mov.txt",
    "rm -f list.txt && ffmpeg -i GRAVACAO.mov -vn audio.wav",
    "rm -rf render_prev",
    "ffmpeg -i GRAVACAO.mov -vn -ac 1 -ar 16000 audio.wav",
    "mv final.mov videos/x/render/final.mov",
    "mv /tmp/GRAVACAO.mov videos/x/",
    "trash notes.txt",
    "gio trash notes.txt",
    "mv x.mov /home/ana/videos/",
    "mv /var/tmp/GRAVACAO.mov videos/x/",
    "find . -name '*.mov'",
    "find . -name '*.png' -delete",
    "git add src/vtk/publish.py tests/test_guard.py",
    "git add -A",
    "git add -p src/",
    "git status && git diff",
    "git check-ignore -v x.mov",
    "curl -fsSL -o model.tar.bz2 https://github.com/k2-fsa/sherpa-onnx/releases/x",
    "curl -fL -o example.mp4 https://example.com/x.mp4",
    "rsync -av videos/ /Volumes/Backup/videos/",
    "cp GRAVACAO.mov /Volumes/Backup/",
    "python3 src/vtk/publish.py --name x --video videos/x/final.mp4",
    "echo openai deepgram elevenlabs",
    "",
]


class Check(unittest.TestCase):
    def test_blocks(self):
        for c in BLOCKED:
            with self.subTest(c=c):
                self.assertIsNotNone(guard.check(c), c)

    def test_allows(self):
        for c in ALLOWED:
            with self.subTest(c=c):
                self.assertIsNone(guard.check(c), c)


class Hook(unittest.TestCase):
    """The script as Claude Code calls it: JSON on stdin, exit 2 + stderr to block."""
    def run_hook(self, payload):
        return subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, text=True)

    def test_exit_2_and_message(self):
        r = self.run_hook(json.dumps({"tool_input": {"command": "rm GRAVACAO.mov"}}))
        self.assertEqual(r.returncode, 2)
        self.assertIn("BLOCKED", r.stderr)

    def test_exit_0(self):
        self.assertEqual(self.run_hook(json.dumps({"tool_input": {"command": "ls"}})).returncode, 0)

    def test_invalid_json_does_not_block(self):
        self.assertEqual(self.run_hook("not json").returncode, 0)

    def test_settings_points_to_the_hook(self):
        with open(os.path.join(ROOT, ".claude", "settings.json"), encoding="utf-8") as f:
            S = json.load(f)
        cmds = [h["command"] for m in S["hooks"]["PreToolUse"] if "Bash" in m["matcher"].split("|") for h in m["hooks"]]
        self.assertTrue(any("$CLAUDE_PROJECT_DIR/.claude/hooks/guard.py" in c for c in cmds), cmds)


if __name__ == "__main__":
    unittest.main()
