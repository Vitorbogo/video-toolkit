# video-toolkit

Ferramentas do Vitor para editar vídeos curtos verticais (TikTok) a partir de uma gravação de tela com a câmera.
Tudo roda local, só com ffmpeg e Python. Receita e decisões estão no vault do Obsidian
(`Vídeos/_Receita de Edição de Vídeo.md`).

## Estrutura

| Pasta | O que tem |
|-------|-----------|
| `vendor/dev-video-editing/` | Skill de terceiros (MIT), **sem modificações**. Decide cortes com tempo por palavra, enchimentos, repetições, punch-ins. Ver `VENDOR.md`. |
| `src/vtk/` | Nossos scripts: `seg.py`, `transcribe_sherpa.py`, `render.py`, `postaudio.py`. |
| `presets/` | Parâmetros por formato (layout, corte, legenda, áudio, imagem). `tiktok-vertical.json`. |
| `videos/<nome>/` | Transcrição, lista de cortes e legendas de cada vídeo. **Sem mídia.** |

## Fluxo

```bash
# 1. áudio e trechos de fala
ffmpeg -i GRAVACAO.mov -vn -ac 1 -ar 16000 audio.wav
ffmpeg -i audio.wav -af silencedetect=noise=-35dB:d=0.4 -f null - 2>&1 | grep -E "silence_(start|end)" \
  | sed -E 's/.*silence_(start|end): ([0-9.]+).*/\1 \2/' > sil.txt
python3 src/vtk/seg.py --sil sil.txt --dur DURACAO --out segs.json
# 2. transcrever, ler tudo, escrever plan.json (cortes + legendas corrigidas) em videos/<nome>/
python3 src/vtk/transcribe_sherpa.py --audio audio.wav --segs segs.json --model-dir MODELO/ --out tr.json
# 3. prévia e final (retoma de onde parou)
python3 src/vtk/render.py --preset presets/tiktok-vertical.json --video GRAVACAO.mov \
  --plan videos/<nome>/plan.json --out render_prev --scale 0.5 --crf 30
ffmpeg -f concat -safe 0 -i lista.txt -c copy final.mp4
# 4. áudio: filtros fixos + loudnorm em 2 passadas (-14 LUFS)
python3 src/vtk/postaudio.py --preset presets/tiktok-vertical.json --in final.mp4 --out final_audio.mp4
```

Imagem da câmera: `--camera-filter off|natural` no `render.py` (padrão do preset).

## Estado (v0.1)

- [x] Layout 9:16 (rosto, slide, legenda) a partir de preset
- [x] Áudio determinístico em 2 passadas: **-14 LUFS, pico ~-1,4 dBTP** (testado no 1º vídeo)
- [x] Tratamento leve de imagem da câmera (opcional)
- [x] Cópia da skill da DEV Community, sem alterações
- [ ] Ligar a skill de terceiros ao `render.py` (cortes com tempo por palavra e bordas ajustadas pelo áudio)
- [ ] Lista de enchimentos em português (né, tipo, então, ééé)
- [ ] Pausas curtas em vez de apagadas; punch-in leve só no rosto
- [ ] Imagem de verificação das emendas
- [ ] Modelo de transcrição guardado fora do repositório

## Licenças

Ver `THIRD_PARTY_LICENSES.md`.
