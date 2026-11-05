---
name: efeitos-sonoros
description: Decide onde entram efeitos sonoros (whoosh, pops, clique) num vídeo do video-toolkit e escreve videos/<nome>/sfx.json. Usar depois de revisar o plan.json com o autor, antes do postaudio.py, ou quando pedirem efeitos sonoros, whoosh, pop ou clique.
---

# Efeitos sonoros

A biblioteca fica em `sfx/` (no git) e é gerada por síntese: `python3 src/vtk/sfx.py gerar`. Para mudar um
som, mude a receita em `src/vtk/sfx.py` e gere de novo. Não baixe arquivos de sites: o repo é público,
e só pode entrar som gerado ou CC0.

## Sons (aprovados pelo autor em 05/11/2026)

| Som | Quando usar |
|-----|-------------|
| `whoosh-curto` | passagem: mudança de assunto ou de slide |
| `pop-madeira` | frase de impacto, virada ("e não é verdade") |
| `pop-bolha` | ideia ou texto que aparece |
| `pop-blip` | item de lista, número |
| `clique` | ação na tela: clicar, enviar o prompt |

Recusados pelo autor: o whoosh longo e o pop que caía de tom ("não gostei"). Ele prefere efeitos curtos e sutis.

## Como decidir

1. `python3 src/vtk/sfx.py marcas --plan videos/<nome>/plan.json` lista o início de cada trecho e de cada
   legenda já no tempo do vídeo final.
2. Escolha poucos momentos. Pense em um efeito a cada 8 a 15 s, nunca menos de 5 s entre dois (o `checar`
   barra). Não ponha whoosh em todo corte: só onde o assunto muda. Nunca um efeito em cima do gancho dos
   primeiros 2 s se ele cobrir a fala.
3. Escreva `videos/<nome>/sfx.json`: `[{"t": 11.05, "som": "whoosh-curto"}, ...]`. `t` é o momento em que o som
   bate (no whoosh, o corte). `vol` é opcional; o padrão do catálogo já fica por baixo da voz.
4. `python3 src/vtk/sfx.py checar --sfx videos/<nome>/sfx.json --plan videos/<nome>/plan.json`.
5. Mostre a lista ao autor junto com a revisão dos cortes, com a frase de cada momento. Ele aprova ou tira.
6. Na etapa de áudio: `postaudio.py ... --sfx videos/<nome>/sfx.json`. Os efeitos entram depois do compressor e
   antes do loudnorm, então o resultado continua em -14 LUFS.
