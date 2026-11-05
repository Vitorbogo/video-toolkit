# video-toolkit

Ferramentas locais (ffmpeg + Python) para vídeos curtos verticais. O autor não roda nada à mão: o agente roda o fluxo inteiro e para nos pontos de revisão com ele.

- **Editar um vídeo** (gravação nova, cortes, legenda, prévia, áudio, capa, retomar uma edição): skill `editar-video`. Ela tem a ordem, os pontos de revisão e as armadilhas.
- **Metadados de publicação** (título, descrição, hashtags, capa): skill `publicar-video`.
- **Efeitos sonoros** (whoosh, pops, clique): skill `efeitos-sonoros`. **Ilustrações animadas** no lugar do slide (HyperFrames): skill `ilustracoes`, quando o vídeo não tem conteúdo visual suficiente ou for pedido.
- Comandos e estado das ferramentas: `README.md`. Contexto do autor (onde ficam as gravações e notas, público do canal, decisões de conteúdo): `CLAUDE.local.md`, fora do git. Se não existir, pergunte.

## Regras fixas
- Tudo local e grátis. Sem API paga, sem enviar áudio/vídeo para fora, sem pedido explícito. (O hook `.claude/hooks/guard.py` bloqueia o óbvio.)
- Mídia, modelos e `videos/` (transcrições, cortes, metadados, clipes, capas) nunca entram no git: o repo é público. Toda saída de um vídeo vai para `videos/<nome>/`, nunca para a raiz. Guardar a gravação original (`.mov`) até o vídeo estar publicado.
- Decisões de corte à mão (replace, cut, keep, trim, zoom, blur) vão no `videos/<nome>/edit.json`, não no `plan.json`: o `cuts.py --force` refaz o plano.
- Cortes e legendas são revisados com o autor. Palavra não entendida: perguntar, nunca inventar.
- Todo vídeo termina com o `videos/<nome>/publicar.md` entregue ao autor. Limites de plataforma ficam em `presets/publish.json`, não na conversa.
