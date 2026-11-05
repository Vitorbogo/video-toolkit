#!/usr/bin/env python3
"""PreToolUse: bloqueia (exit 2) comandos que quebram as regras fixas do projeto.
Le o JSON do hook no stdin; olha tool_input.command. Mensagem vai para o stderr e chega ao Claude.
E uma rede para o obvio, nao um sandbox: prefere deixar passar a bloquear comando legitimo (ler, grep, ffmpeg).
Testes: tests/test_guard.py (chamam check(comando) direto).
"""
import json, re, sys

S = r"[^|;&\n]*"                                    # resto do mesmo comando (para em | ; & e quebra de linha)
FIM = r"(?=$|[\s;|&)'\"`])"                          # fim do argumento: "x.mov" sim, "x.mov.txt" nao
CMD = r"(?<![\w.-])"                                 # inicio de palavra de comando (aceita /bin/rm)
MIDIA = r"\.(?:mov|mp4|m4v|mkv|wav|mp3|m4a|aac|webm|mts|aiff?|onnx)" + FIM
MOV = r"\.mov" + FIM
CARGA = r"(?:" + MIDIA + r"|(?:^|[\s\"'=/])videos(?:/|" + FIM + r"))"   # midia ou a pasta videos/
LIXO = (r"(?:(?:~|\$HOME|\$\{HOME\}|/Users/[^/\s]+)/\.Trash|(?:/private)?/tmp(?:/|" + FIM + r")"
        r"|/dev/null|\$\{?TMPDIR\}?|/var/folders/)")
GIT_ADD = CMD + r"git(?:\s+(?:-C\s+\S+|-c\s+\S+|--[\w-]+(?:=\S+)?|-[a-zA-Z]+))*\s+(?:add|stage)\b"
HOSTS = ["api.openai.com", "api.groq.com", "api.anthropic.com", "generativelanguage.googleapis.com",
         "api.elevenlabs.io", "api.replicate.com", "api.mistral.ai", "api.together.xyz",
         "speech.googleapis.com", "api.deepgram.com", "api.assemblyai.com"]

M_GIT = "Midia e modelos nunca entram no git (o repo e publico)."
M_MOV = "Nao apague nem descarte gravacao original (.mov). So depois do video publicado, e a pedido do Vitor."
M_UP = "Nao envie audio/video (nem videos/) para fora do computador sem o Vitor pedir."
M_API = "Transcricao e edicao sao locais e gratis neste projeto. Nada de API paga sem o Vitor pedir."
M_HF = ("HyperFrames: so o render local e gratis (init, lint, snapshot, render, docs, preview). Login, creditos, nuvem e "
        "templates/skills Pro da HeyGen sao pagos ou mandam coisas para fora: so com o Vitor pedindo.")

REGRAS = [
    (GIT_ADD + S + r"\s(?:(?-i:-[a-zA-Z]*f[a-zA-Z]*)|--force)" + FIM, "git add --force passa por cima do .gitignore. " + M_GIT),
    (GIT_ADD + S + MIDIA, "Nao adicione midia/modelos ao git (video, audio, .onnx). " + M_GIT),
    (CMD + r"(?:rm|unlink|shred|srm|trash)\s" + S + MOV, M_MOV),
    (CMD + r"mv\s(?=" + S + MOV + r")(?:" + S + r"(?<=\s)[\"']?" + LIXO + r"[^\s;|&]*\s*(?:$|[;|&\n)`])"  # destino e o ultimo
     r"|" + S + r"-t\s*[\"']?" + LIXO + ")", M_MOV),
    (CMD + r"find\s(?=" + S + r"mov\b)(?=" + S + r"(?:(?<=\s)-delete\b|(?<=\s)-exec(?:dir)?\s+\S*(?<![\w.-])(?:rm|trash|shred|unlink|mv)\b))", M_MOV),
    (MOV + r"[^\n]*\|\s*xargs\b" + S + r"\s\S*(?<![\w.-])(?:rm|trash|shred|unlink)\b", M_MOV),
    (CMD + r"(?:curl|wget|https?|xh)\s" + S + r"(?:(?-i:(?<=\s)-[FTd]\b)|--form|--data|--upload-file|--post-file)" + S + CARGA, M_UP),
    (CMD + r"(?:curl|wget|https?|xh)\s" + S + r"@\S*" + MIDIA, M_UP),
    (CMD + r"(?:scp|rsync|sftp)\s(?=" + S + CARGA + r")(?=" + S + r"(?:(?<=\s)[\"']?[\w.@-]+:|rsync://))", M_UP),
    (CMD + r"(?:rclone|gsutil|gcloud\s+storage|aws\s+s3(?:api)?|s3cmd|azcopy|b2)\s" + S + CARGA, M_UP),
    (CMD + r"gh\s+(?:release\s+(?:upload|create)|gist\s+create)\s" + S + CARGA, M_UP),
    ("|".join(re.escape(h) for h in HOSTS), M_API),
    # HyperFrames: so o render local e gratis; estes comandos usam conta, creditos ou nuvem da HeyGen
    (CMD + r"hyperframes(?:@\S+)?\s+(?:auth|login|billing|cloud|lambda|cloudrun|publish|templates|reverse|catch-up)\b", M_HF),
    (CMD + r"hyperframes(?:@\S+)?\s+(?:transcribe|tts|remove-background)\s" + S + r"--engine[=\s]+[\"']?heygen\b", M_HF),
    (CMD + r"hyperframes(?:@\S+)?\s+skills\s+update\s+(?:reverse-any-video|style-sampling)\b", M_HF),
]

# rodar um script (nao ler): inicio do comando, com prefixos comuns, opcionalmente via python
RODA = (r"^[\s(]*(?:(?:\w+=\S*|time|nohup|exec|env|sudo|uv\s+run|pipx\s+run|(?:ba|z)?sh\s+-c\s+[\"']?)\s*)*"
        r"(?:\S*python[\d.]*\s+(?:-\S+\s+)*)?[\"']?\S*(?<![\w-])")
SCRIPTS = [
    (RODA + r"transcribe\.py\b", r"--engine[=\s]+[\"']?local\b",
     "transcribe.py da skill de terceiros so com --engine local (o padrao 'auto' pode mandar o audio para Groq/OpenAI). "
     "Prefira src/vtk/transcribe_words.py."),
    (RODA + r"upload_parts\.py\b", None, "upload_parts.py envia o video para fora. " + M_UP),
]


# sfx/*.wav (efeitos curtos gerados por sintese, src/vtk/sfx.py) e a unica midia que pode entrar no git:
# some do comando antes da regra de midia no git (a regra do --force continua valendo para ele)
SFX = re.compile(r"(?<![\w/.-])(?:\./)?sfx/[\w.*-]+\.wav" + FIM, re.I)


def check(cmd):
    """Motivo do bloqueio (texto) ou None se o comando pode rodar."""
    cmd = cmd or ""
    for i, (rx, msg) in enumerate(REGRAS):
        alvo = SFX.sub("sfx/", cmd) if i == 1 else cmd  # REGRAS[1]: midia no git
        if re.search(rx, alvo, re.I):
            return msg
    for seg in re.split(r"&&|\|\||[;|&\n`]|\$\(", cmd):
        for rx, libera, msg in SCRIPTS:
            if re.search(rx, seg, re.I) and not (libera and re.search(libera, seg, re.I)):
                return msg
    return None


def main():
    try:
        cmd = (json.load(sys.stdin).get("tool_input") or {}).get("command", "") or ""
    except Exception:
        return 0
    msg = check(cmd)
    if msg:
        print(f"BLOQUEADO pelo guard do video-toolkit: {msg}\nComando: {cmd[:200]}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
