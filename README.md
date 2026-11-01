# video-toolkit

Ferramentas do Vitor para editar vídeos curtos verticais (TikTok) a partir de uma gravação de tela com a câmera.
Tudo roda local, só com ffmpeg e Python. Receita e decisões estão no vault do Obsidian
(`Vídeos/_Receita de Edição de Vídeo.md`).

## Estrutura

| Pasta | O que tem |
|-------|-----------|
| `vendor/dev-video-editing/` | Skill de terceiros (MIT), **sem modificações**. Decide cortes com tempo por palavra, enchimentos, repetições, punch-ins. Ver `VENDOR.md`. |
| `src/vtk/` | Nossos scripts: `seg.py`, `transcribe_words.py` (tempo por palavra, gratis), `transcribe_sherpa.py` (por trecho, antigo), `render.py`, `postaudio.py`, `thumb.py`, `publish.py` (metadados de publicação). |
| `models/` | Modelo de transcricao (487 MB), **fora do git**. Ver abaixo.  |
| `presets/` | Parâmetros por formato (layout, corte, legenda, áudio, imagem) e limites das plataformas (`publish.json`). |
| `.claude/` | `skills/publicar-video` (como escrever os metadados) e `hooks/guard.py` (bloqueia mídia no git, apagar `.mov`, API paga). |
| `videos/<nome>/` | Transcrição, lista de cortes e legendas de cada vídeo. **Sem mídia.** |

## Fluxo

```bash
# 1. áudio e trechos de fala
ffmpeg -i GRAVACAO.mov -vn -ac 1 -ar 16000 audio.wav
ffmpeg -i audio.wav -af silencedetect=noise=-35dB:d=0.4 -f null - 2>&1 | grep -E "silence_(start|end)" \
  | sed -E 's/.*silence_(start|end): ([0-9.]+).*/\1 \2/' > sil.txt
python3 src/vtk/seg.py --sil sil.txt --dur DURACAO --out segs.json
# 2. transcrever com tempo por palavra (gratis, local, ~11 s para 6 min), ler tudo, escrever plan.json (cortes + legendas corrigidas) em videos/<nome>/
python3 src/vtk/transcribe_words.py --audio audio.wav --segs segs.json \
  --model-dir models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8 --out work/   # transcript.json + transcript.txt
# 3. prévia e final (retoma de onde parou)
python3 src/vtk/render.py --preset presets/tiktok-vertical.json --video GRAVACAO.mov \
  --plan videos/<nome>/plan.json --out render_prev --scale 0.5 --crf 30
ffmpeg -f concat -safe 0 -i lista.txt -c copy final.mp4
# 4. áudio: filtros fixos + loudnorm em 2 passadas (-14 LUFS)
python3 src/vtk/postaudio.py --preset presets/tiktok-vertical.json --in final.mp4 --out final_audio.mp4
# 5. capas: cada formato pode usar um quadro; "variantes" no thumb.json gera vários pares
python3 src/vtk/thumb.py --video final.mp4 --spec videos/<nome>/thumb.json --out capas/
python3 src/vtk/thumb.py --video final.mp4 --spec videos/<nome>/thumb.json --out capas/ --sheet 5,20,40,62,95  # folha de candidatos
# 6. publicação: valida limites das plataformas e gera videos/<nome>/publicar.md (título, descrição, legenda, hashtags, capa)
#    o meta.json é escrito pelo Claude (skill publicar-video) logo depois do plan.json
python3 src/vtk/publish.py --name <nome> --video final_audio.mp4 --capas capas/
```

Imagem da câmera: `--camera-filter off|natural` no `render.py` (padrão do preset).

## Estado (v0.1)

- [x] Layout 9:16 (rosto, slide, legenda) a partir de preset
- [x] Áudio determinístico em 2 passadas: **-14 LUFS, pico ~-1,4 dBTP** (testado no 1º vídeo)
- [x] Tratamento leve de imagem da câmera (opcional)
- [x] Capas 9:16 e 16:9 determinísticas (`thumb.py`), com quadro próprio por formato
- [x] Cópia da skill da DEV Community, sem alterações
- [ ] Ligar a skill de terceiros ao `render.py` (cortes com tempo por palavra e bordas ajustadas pelo áudio)
- [ ] Lista de enchimentos em português (né, tipo, então, ééé)
- [ ] Pausas curtas em vez de apagadas; punch-in leve só no rosto
- [ ] Imagem de verificação das emendas
- [x] Transcrição com tempo por palavra, grátis e local (`transcribe_words.py`, Parakeet TDT v3; resolução 80 ms; erra termos como "IA" → "Ya", revisar o texto)
- [x] Modelo guardado em `models/` (ignorado pelo git)

## Modelo de transcrição

`models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8/` (487 MB, não vai para o git). Para baixar de novo: release `asr-models` de
`github.com/k2-fsa/sherpa-onnx`, arquivo `sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2`, e extrair em `models/`.
Requer `pip install sherpa-onnx numpy`. Não usa chave de API nem envia áudio para fora.

## Licenças

Ver `THIRD_PARTY_LICENSES.md`.
