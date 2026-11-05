# video-toolkit

Ferramentas do Vitor para editar vídeos curtos verticais (TikTok) a partir de uma gravação de tela com a câmera.
Tudo roda local, só com ffmpeg e Python. Receita e decisões estão no vault do Obsidian
(`Vídeos/_Receita de Edição de Vídeo.md`).

## Estrutura

| Pasta | O que tem |
|-------|-----------|
| `src/vtk/` | Nossos scripts: `engine.py` (motor de cortes: tempo por palavra, enchimentos, repetições, punch-ins; começou como cópia da skill dev-video-editing, MIT, ver `THIRD_PARTY_LICENSES.md`), `transcribe_words.py` (tempo por palavra, grátis), `cuts.py` (cortes pelo `engine.py` → `plan.json`), `render.py` (legenda desenhada por `captions.py`), `postaudio.py` (efeitos sonoros com `--sfx`), `sfx.py` (biblioteca e lista de efeitos sonoros), `rosto.py` (quadros com rosto neutro para a capa), `thumb.py`, `publish.py` (metadados de publicação), `preset.py` (carrega preset com herança). |
| `models/` | Modelos de transcrição (487 MB) e de rosto (3,7 MB), **fora do git**. Ver abaixo. |
| `presets/` | Parâmetros por formato (layout, corte, legenda, áudio, imagem), capas (`thumbnail.json`), enchimentos em português (`fillers-pt.json`) e limites das plataformas (`publish.json`). |
| `assets/fonts/` | Poppins (legenda e capas, SIL OFL 1.1, `OFL-Poppins.txt`). |
| `sfx/` | Efeitos sonoros curtos (whoosh, pops, clique), **gerados** por `src/vtk/sfx.py gerar`. Únicos `.wav` no git. |
| `tests/` | Testes (`python3 -m unittest discover tests`; os que precisam de ffmpeg ou do modelo são pulados sem eles). |
| `.claude/` | `skills/editar-video` (roteiro do agente: gravação → `publicar.md`, com os pontos de revisão), `skills/publicar-video` (como escrever os metadados), `skills/efeitos-sonoros` (onde pôr cada efeito), `skills/ilustracoes` (animações no lugar do slide, com HyperFrames) e `hooks/guard.py` (bloqueia mídia no git, apagar/mover `.mov`, enviar mídia para fora, API paga, `transcribe.py` da skill sem `--engine local`, `upload_parts.py`). |
| `videos/<nome>/` | **Tudo de cada vídeo**: transcrição, `edit.json`, `plan.json`, `preset.json`, clipes (`render/`), vídeo final, capas (`capas/`), `meta.json`, `publicar.md`. **Fora do git** (o repo é público e o conteúdo não pode vazar antes de o vídeo sair). |

Requisitos: `ffmpeg` (com `ffprobe`), Python 3 com `Pillow`, `numpy`, `sherpa-onnx` e `mediapipe` (só para o `rosto.py`).

## Fluxo

```bash
# 0. preset do vídeo: só o que muda (recortes medidos num quadro da gravação); o resto vem do base
#    videos/<nome>/preset.json = {"base": "presets/tiktok-vertical.json",
#                                 "source": {"w": 2940, "h": 1612, "camera_crop": [...], "slide_crop": [...]}}
#    o render.py para com erro se a gravação tiver outra resolução ou se um recorte sair do quadro
# 1. transcrever com tempo por palavra (grátis, local): áudio, silêncios e janelas são feitos dentro do script
python3 src/vtk/transcribe_words.py --video GRAVACAO.mov --name <nome>   # videos/<nome>/transcript.json + .txt
#    (--audio x.wav no lugar de --video; --out DIR no lugar de --name; --model-dir se o modelo não estiver em models/)
# 2. cortes decididos pelo engine.py (enchimentos PT, pausas encurtadas, bordas pelo áudio) -> rascunho do
#    plan.json + edit-plan.md. Revisar cortes e legendas com o Vitor.
python3 src/vtk/cuts.py --video GRAVACAO.mov --name <nome> [--zoom] [--force]
#    lê por padrão videos/<nome>/transcript.json, edit.json e preset.json (se existirem)
#    ajustes no videos/<nome>/edit.json, com tempos da gravação original (sobrevivem ao --force):
#      cut [[a, b, "nota"]]          tira as palavras do intervalo (avisa se não pegar nenhuma)
#      keep [[a, b]]                 protege o intervalo
#      trim [[a, b, "nota"]]         tira o intervalo bruto, mesmo sem palavra (pausa longa, ruído)
#      replace {"chat GPT": "ChatGPT"} corrige a legenda (vale com mais de uma palavra)
#      zoom [[t, 1.1]]               zoom só na câmera no trecho que contém t (máx. 1.2; 1 tira)
#      blur [[t0, t1, x, y, w, h, "nota"]] borra a caixa (pixels da gravação) entre t0 e t1
#      style, pauses, extra_fillers  chaves do engine.py
#    zoom é opcional e fica desligado: só se as emendas ficarem bruscas (--zoom sugere, o edit.json decide)
#    --force refaz o plan.json (o anterior fica em plan.json.bak); legenda editada direto no plan.json se perde
#    o plan.json guarda em "wt" o início de cada palavra: a legenda destaca a palavra falada (texto mudado no
#    replace com outro número de palavras cai numa estimativa pelo tamanho)
# 2b. efeitos sonoros (skill efeitos-sonoros): videos/<nome>/sfx.json, revisado junto com os cortes
python3 src/vtk/sfx.py marcas --plan videos/<nome>/plan.json     # tempos no vídeo final, para escolher os momentos
python3 src/vtk/sfx.py checar --sfx videos/<nome>/sfx.json --plan videos/<nome>/plan.json
# 2c. ilustrações (skill ilustracoes), só quando o vídeo não tem conteúdo visual suficiente ou o Vitor pedir
# 3. prévia e final: retoma de onde parou e refaz só os clipes cujo trecho, preset ou opções mudaram
#    saída: render/c00.mov... (áudio PCM, sem atraso nas emendas), render/lista.txt e, com todos prontos, render/final.mov
python3 src/vtk/render.py --preset videos/<nome>/preset.json --video GRAVACAO.mov \
  --plan videos/<nome>/plan.json --out videos/<nome>/render_prev --scale 0.5 --crf 30
python3 src/vtk/render.py --preset videos/<nome>/preset.json --video GRAVACAO.mov \
  --plan videos/<nome>/plan.json --out videos/<nome>/render
# 4. áudio: filtros fixos + pré-limitador automático + loudnorm LINEAR em 2 passadas (-14 LUFS, pico <= -1,5 dBTP
#    medido no resultado; fora do alvo sai com erro). Redução de ruído desligada no preset (voz robótica)
python3 src/vtk/postaudio.py --preset videos/<nome>/preset.json --in videos/<nome>/render/final.mov --out videos/<nome>/final.mp4 \
  [--sfx videos/<nome>/sfx.json]
# 5. capas. Primeiro os quadros com rosto neutro (olhos abertos, boca fechada, cabeça reta, imagem nítida), em ~3 s:
python3 src/vtk/rosto.py --video videos/<nome>/final.mp4 --name <nome>   # rosto.json + rosto_candidatos.jpg (conferir)
#    no thumb.json: "tempo_s": "auto" (variante A = 1º candidato, B = 2º...) ou "auto:3"; "rosto_x": "auto" centraliza
#    o 16:9 no rosto. Pesos da nota em presets/thumbnail.json ("neutro"). Número fixo em tempo_s continua valendo.
#    capas -> videos/<nome>/capas/ (padrão). Cada formato e variante pode ter quadro e textos próprios:
#    "youtube": {"titulo": .., "destaque": ..} no thumb.json; --only vertical|youtube gera um formato só
python3 src/vtk/thumb.py --video videos/<nome>/final.mp4 --spec videos/<nome>/thumb.json
python3 src/vtk/thumb.py --video videos/<nome>/final.mp4 --spec videos/<nome>/thumb.json --sheet 5,20,40,62,95  # folha de candidatos
# 6. publicação: valida limites das plataformas e gera videos/<nome>/publicar.md (título, descrição, legenda, hashtags, capa)
#    o meta.json é escrito pelo Claude (skill publicar-video) logo depois da revisão do plan.json, com a capa
#    PROVISÓRIA; depois do thumb.py, escolher a capa e atualizar. Com ERRO nada é gerado (o antigo vira .desatualizado)
python3 src/vtk/publish.py --name <nome> --video videos/<nome>/final.mp4   # capas lidas de videos/<nome>/capas
```

Imagem da câmera: `--camera-filter off|natural` no `render.py` (padrão do preset).

## Estado (v0.2)

- [x] Layout 9:16 (rosto, slide, legenda) a partir de preset; preset por vídeo herda do base (`"base"`)
- [x] Áudio determinístico em 2 passadas, -14 LUFS (1º vídeo, cadeia antiga: -14,05 LUFS, -1,36 dBTP)
- [ ] Cadeia de áudio nova como padrão: sem redução de ruído (o `afftdn` deixava a voz robótica), compressor 2:1, pré-limitador automático (loudnorm sempre linear) e folga de pico para o AAC. Medido em voz sintética com plosivas: -14,1 LUFS, -2,2 dBTP, linear. Falta medir num vídeo real
- [x] Tratamento leve de imagem da câmera (opcional)
- [x] Capas 9:16 e 16:9 determinísticas (`thumb.py`), com quadro e textos próprios por formato; texto encolhe para caber
- [x] Capa com expressão neutra: `rosto.py` dá nota a cada quadro (MediaPipe, local) contra o rosto em repouso do próprio vídeo; `thumb.json` usa `"auto"`
- [x] Motor de cortes como código nosso (`engine.py`, derivado da skill dev-video-editing)
- [x] `engine.py` ligado ao `render.py` pelo `cuts.py` (usado no "especialista" e no "instruções")
  - Decisão nossa por cima do motor original: ela deixa uma "respiração" no lugar do enchimento removido, e uma ponta do som continuava audível. O `cuts.py` tira também essa ponta, mas não corta se a emenda ficar com menos de 0,12 s ou sobrar trecho com fala de menos de 0,4 s (a palavra volta para a legenda). O `edit-plan.md` é refeito a partir dos trechos finais
- [x] Lista de enchimentos em português (`presets/fillers-pt.json`, aplicada pelo `cuts.py`)
- [x] Pausas curtas em vez de apagadas (o engine encurta para uma respiração)
- [x] Emendas sem atraso de áudio: clipes com áudio PCM e duração exata em quadros, juntados pelo próprio `render.py`
- [x] Borrar uma região por um intervalo (`blur` no `edit.json`), para esconder dados na tela
- [ ] Zoom leve só na câmera, **opcional** (`cuts.py --zoom` sugere, `zoom` no `edit.json` decide; `render.py` aplica). Falta rodar num vídeo real
- [ ] Imagem de verificação das emendas (dá para usar a `cut_sheet` do `engine.py` sobre o nosso final)
- [x] Legenda desenhada com Pillow (o ffmpeg do Homebrew não tem libass): frase inteira, palavra falada em laranja (estilo escolhido em 05/11/2026)
- [ ] Efeitos sonoros gerados (`sfx/`), lista por vídeo (`sfx.json`), mistura no `postaudio.py --sfx`. Testado em trechos; falta um vídeo completo
- [ ] Ilustrações com HyperFrames (skill `ilustracoes`). Testado no "teste ilustração" (05/11/2026); falta ligar ao `render.py`
- [x] Transcrição com tempo por palavra, grátis e local (`transcribe_words.py`, Parakeet TDT v3; erra termos como "IA" → "Ya", revisar o texto). Janelas longas divididas no ponto mais quieto, sem palavra duplicada; fim da palavra alinhado ao silêncio
- [x] Modelo guardado em `models/` (ignorado pelo git)

## Modelo de transcrição

`models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8/` (487 MB, não vai para o git). Para baixar de novo: release `asr-models` de
`github.com/k2-fsa/sherpa-onnx`, arquivo `sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2`, e extrair em `models/`.
Requer `pip install sherpa-onnx numpy`. Não usa chave de API nem envia áudio para fora.

Rosto (para o `rosto.py`): `models/face_landmarker.task` (3,7 MB, Apache 2.0, não vai para o git), de
`https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task`.
Requer `pip install mediapipe`. Roda local; o vídeo não sai da máquina.

## Licenças

Ver `THIRD_PARTY_LICENSES.md`.
