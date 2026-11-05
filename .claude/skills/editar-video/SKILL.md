---
name: editar-video
description: Roteiro do agente para editar um vídeo do video-toolkit, da gravação (.mov) ao publicar.md. Usar quando o Vitor trouxer uma gravação nova, ou pedir para cortar, legendar, renderizar, prévia, tratar o áudio, fazer capa ou retomar a edição de um vídeo.
---

# Editar um vídeo (gravação → publicar.md)

O Vitor não roda nada: você roda tudo e para nos **pontos de revisão** (marcados 👀) para ele decidir. Comandos e flags exatos: bloco "Fluxo" do `README.md` (leia antes de começar). Esta skill diz a ordem, quando um passo está pronto e as armadilhas que o código não conta.

`<nome>` é um apelido curto do vídeo (ex.: `instrucoes`). Toda saída vai para `videos/<nome>/` (fora do git). O original fica na pasta do vídeo no vault: `Vídeos/<Título do Vídeo>/<gravação>.mov`.

## Passos

1. **Ambiente.** Confira `ffmpeg -version`, `ffprobe -version` e `python3 -c "import PIL, numpy, sherpa_onnx, mediapipe"`, e os modelos `models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8/` e `models/face_landmarker.task` (como baixar: README, "Modelo de transcrição"). O que faltar, instale (`pip install ...`; no Mac, `brew install ffmpeg`) e diga ao Vitor o que instalou. **Pronto quando** os quatro comandos rodam sem erro.

2. **Preset do vídeo.** Extraia quadros da gravação (ex.: 5 s, 30 s, meio, fim) e olhe cada um. Meça a janela da câmera e o painel do slide/tela (`largura, altura, x, y` em pixels da gravação) e a resolução. Escreva `videos/<nome>/preset.json` só com o que muda:
   `{"base": "presets/tiktok-vertical.json", "source": {"w": .., "h": .., "camera_crop": [..], "slide_crop": [..]}}`.
   Preset antigo copiado inteiro (com `fontsdir` `/usr/share/...`) não roda mais: converta para esse formato. **Pronto quando** uma prévia de 1 trecho (passo 5) mostra rosto e tela inteiros, sem borda preta nem corte.

3. **Transcrever** (`transcribe_words.py --video ... --name <nome>`) e ler o `transcript.txt` inteiro. Anote termos errados (o Parakeet troca "IA" por "Ya", nomes de ferramentas). **Pronto quando** você leu tudo e tem a lista de correções e de palavras que não entendeu.

4. **Cortes.** Ponha as decisões no `videos/<nome>/edit.json`, a fonte única de decisões à mão: `replace` (correções da legenda, vale com várias palavras), `cut`, `keep`, `trim`, `zoom`, `blur` (chaves e formato: docstring do `src/vtk/cuts.py`). Rode `cuts.py --video ... --name <nome>`.
   - **Dado sensível na tela** (títulos de conversas, e-mails, nomes de clientes, abas): olhe os quadros da área da tela ao longo do vídeo e cubra com `blur` (tempos e pixels da gravação original).
   - Zoom fica desligado; só se o Vitor achar as emendas bruscas.
   - 👀 **Revisão 1:** mostre ao Vitor o `edit-plan.md` (o que saiu e por quê, avisos, possíveis retomadas) e o texto das legendas. Palavra não entendida: pergunte, nunca invente. Ajuste o `edit.json` e rode de novo com `--force` até ele aprovar.
   - Logo depois da aprovação, escreva o `meta.json` (skill `publicar-video`).
   **Pronto quando** o Vitor aprovou cortes e legendas.

5. **Prévia** (`render.py ... --out videos/<nome>/render_prev --scale 0.5 --crf 30`). Ela sai em `render_prev/final.mov`. Olhe alguns quadros (borrão no lugar, legenda inteira dentro da tela, rosto enquadrado). 👀 **Revisão 2:** passe ao Vitor o caminho da prévia para ele assistir com fones. **Pronto quando** ele aprovou; mudanças voltam ao `edit.json` (passo 4).

6. **Final.** `render.py` sem `--scale`, em `videos/<nome>/render`. Depois `postaudio.py --in videos/<nome>/render/final.mov --out videos/<nome>/final.mp4`. **Pronto quando** o `postaudio.py` termina com `ok` (-14 LUFS, pico ≤ -1,5 dBTP, `normalization_type=linear`).

7. **Capa.** `rosto.py --video videos/<nome>/final.mp4 --name <nome>` e olhe o `rosto_candidatos.jpg`. Escreva o `thumb.json` (textos do vídeo, `"tempo_s": "auto"` e `"rosto_x": "auto"` nas variantes) e rode o `thumb.py`. 👀 **Revisão 3:** mostre as capas de `videos/<nome>/capas/` ao Vitor. Ele escolhe a variante: atualize `capa` no `meta.json` (sem "PROVISÓRIA"). **Pronto quando** a capa está escolhida.

8. **Publicar.** Rode `publish.py --name <nome> --video videos/<nome>/final.mp4` até sair sem `ERRO`. Copie para a pasta do vídeo no vault: `final.mp4` como `<Título curto> - FINAL.mp4`, as capas em `capas/`, e o `publicar.md` como `PUBLICAR - <Título>.md`. **Pronto quando** os três estão no vault e você entregou ao Vitor o `publicar.md`.

## Armadilhas

- **Erro de script é para ler e corrigir a causa**, não para contornar. Recorte fora do quadro, resolução diferente da do preset, fonte ausente, áudio fora do alvo: todos param o script de propósito.
- **Refazer é rodar o mesmo comando.** O `render.py` retoma de onde parou e refaz só os clipes cujo trecho, preset ou opção mudaram. Se o shell matar processos longos, rode em etapas com `--budget`.
- **O `.mov` original fica até o vídeo estar publicado** (o hook bloqueia apagá-lo ou mandá-lo para o lixo). Arquivos de teste seus: use `.mp4` ou `.mkv`.
- **O `plan.json` é gerado.** Mexer nele à mão se perde no próximo `--force` (o anterior fica em `plan.json.bak`). Toda decisão vai no `edit.json`.
- **A capa usa o vídeo final em 1080×1920**, e o `rosto.py` também: rode os dois sobre o `final.mp4`, não sobre a prévia.
- **Mudou script do toolkit?** Rode `python3 -m unittest discover tests` antes de seguir.
