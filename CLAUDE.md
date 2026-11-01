# video-toolkit

Ferramentas locais (ffmpeg + Python) para vídeos curtos verticais. Fluxo e comandos: `README.md`. Receita e decisões: `Vídeos/_Receita de Edição de Vídeo.md` no vault do Obsidian.

## Regras fixas
- Tudo local e grátis. Sem API paga, sem enviar áudio/vídeo para fora, a menos que o Vitor peça. (O hook `.claude/hooks/guard.py` bloqueia o óbvio.)
- Mídia, modelos e `videos/` (transcrições, cortes, metadados) nunca entram no git: o repo é público. Guardar a gravação original (`.mov`) até o vídeo estar publicado.
- Cortes e legendas são revisados com o Vitor. Palavra não entendida: perguntar, nunca inventar.

## Todo vídeo termina com publicação
1. Ao escrever `videos/<nome>/plan.json`, escrever também `videos/<nome>/meta.json` (skill `publicar-video`).
2. Depois de `postaudio.py` e `thumb.py`, rodar `python3 src/vtk/publish.py --name <nome> --video <final> --capas <pasta>`.
3. Entregar ao Vitor o `videos/<nome>/publicar.md` (título, descrição, legenda, hashtags, capa, checklist). Limites de plataforma ficam em `presets/publish.json`, não na conversa.
