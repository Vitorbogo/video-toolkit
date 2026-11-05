#!/usr/bin/env python3
"""PreToolUse: bloqueia (exit 2) comandos que quebram as regras fixas do projeto.
Le o JSON do hook no stdin; olha tool_input.command. Mensagem vai para o stderr e chega ao Claude.
"""
import json, re, sys

try:
    cmd = (json.load(sys.stdin).get("tool_input") or {}).get("command", "") or ""
except Exception:
    sys.exit(0)

MIDIA = r"\.(mov|mp4|m4v|mkv|wav|mp3|onnx)\b"
REGRAS = [
    (r"\bgit\s+add\b[^|;&]*(\s-f\b|--force)",
     "git add --force passa por cima do .gitignore. Midia e modelos nunca entram no git."),
    (r"\bgit\s+add\b[^|;&]*" + MIDIA,
     "Nao adicione midia/modelos ao git (video, audio, .onnx). Fica fora do repositorio."),
    (r"\b(rm|unlink|shred)\b[^|;&]*\.mov\b",
     "Nao apague gravacao original (.mov). So depois do video final estar publicado, e a pedido."),
    (r"\bmv\b[^|;&]*\.mov\b[^|;&]*\s/dev/null",
     "Nao descarte gravacao original (.mov)."),
    (r"\b(curl|wget|http|scp|rclone)\b[^|;&]*(-F\b|--form|--data-binary|-T\b|--upload-file|@)[^|;&]*" + MIDIA,
     "Nao envie audio/video para fora do computador sem o autor pedir."),
    (r"api\.openai\.com|assemblyai|deepgram|elevenlabs|api\.groq\.com|speech\.googleapis",
     "Transcricao e edicao sao locais e gratis neste projeto. Nada de API paga sem o autor pedir."),
]
# sfx/*.wav (efeitos curtos gerados por sintese) e a unica midia que pode entrar no git:
# tira esses caminhos antes de checar a regra de "git add" com midia (o --force continua bloqueado)
SFX = re.compile(r"(?<![\w/.-])(\./)?sfx/[\w.*-]+")
for rx, msg in REGRAS:
    alvo = SFX.sub("sfx/", cmd) if rx.endswith(MIDIA) and "git" in rx else cmd
    if re.search(rx, alvo, re.I):
        print(f"BLOQUEADO pelo guard do video-toolkit: {msg}\nComando: {cmd[:200]}", file=sys.stderr)
        sys.exit(2)
sys.exit(0)
