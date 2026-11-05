---
name: ilustracoes
description: Cria ilustrações animadas (HTML + GSAP, renderizadas com HyperFrames) que entram no lugar do slide num vídeo do video-toolkit. Usar quando o vídeo não tiver conteúdo visual suficiente (só câmera, slide parado demais, conceito difícil de ver), quando o Vitor pedir ilustração, animação, desenho ou "algo na tela", ou ao retomar um vídeo que tem videos/<nome>/ilustracao/.
---

# Ilustrações animadas

A ilustração é um vídeo do tamanho do painel do slide (882×850, `layout.slide` do preset) que o `render.py --painel`
põe no lugar do slide recortado. Ela segue a fala: cada coisa aparece na palavra que a nomeia.

## Quando usar

- O vídeo não tem conteúdo visual suficiente: só câmera, ou um slide parado por muito tempo.
- O Vitor pediu.
- Não use só para enfeitar um vídeo que já tem gravação de tela com conteúdo. Na dúvida, proponha e deixe ele decidir.

## Ferramenta

HyperFrames (Apache 2.0, da HeyGen), via `npx hyperframes@0.9.16`, fixado nessa versão. Ele roda local (Node 22+,
ffmpeg, um Chrome headless que ele mesmo baixa) e não envia o vídeo para fora. Na primeira vez numa máquina, rode
`npx hyperframes@0.9.16 telemetry disable`. Docs offline: `npx hyperframes@0.9.16 docs <tópico>`
(data-attributes, gsap, compositions, rendering).

**Grátis e sem limite é só o local:** `init`, `lint`, `snapshot`, `render`, `preview`, `docs`. Conta, créditos e nuvem
da HeyGen são pagos ou mandam coisas para fora, e o `guard.py` bloqueia: `auth`, `billing`, `cloud`, `lambda`,
`cloudrun`, `publish`, `templates`, `reverse`, `--engine heygen`, e as skills Pro `reverse-any-video` e
`style-sampling`. O app HyperFrames Studio (plano Free com 5 exportações na nuvem por mês, Pro pago) também não faz
parte do fluxo. Mantenha a versão fixada: a Apache 2.0 da 0.9.16 não pode ser retirada.

## Passos

1. **Proposta** (junto com a revisão dos cortes, passo 4 da `editar-video`). Rode
   `python3 src/vtk/sfx.py marcas --plan videos/<nome>/plan.json` para ter os tempos no vídeo final. Escreva para o
   Vitor uma lista: frase falada (com o tempo), o que aparece, como entra. Texto, números e valores na tela são
   conteúdo: ele aprova como aprova a legenda. Nada de dado inventado apresentado como real.
   👀 Ele aprova, corta ou muda. **Pronto quando** a lista está aprovada.
2. **Projeto.** Em `videos/<nome>/ilustracao/` (fora do git):
   `npx hyperframes@0.9.16 init ilustracao --example blank --non-interactive --skip-skills --resolution square`.
   Depois troque o `index.html` partindo de `presets/ilustracao/exemplo-planilha.html`, e copie as fontes Poppins
   de `assets/fonts/` para `ilustracao/assets/`.
3. **Escrever a animação.** Regras do HyperFrames: `#root` com `data-composition-id`, `data-start`,
   `data-duration` (= duração do vídeo final) e `data-width="882" data-height="850"`. Cada elemento com tempo tem
   `class="clip"`, `data-start` e `data-duration`. Uma timeline GSAP pausada em `window.__timelines["main"]`.
   Nada de `Math.random()`, `Date.now()` nem fetch. Tempos absolutos, tirados do `marcas` (a palavra, não a frase).
4. **Conferir.** `npx hyperframes@0.9.16 lint`, depois `npx hyperframes@0.9.16 snapshot --at <tempos>` e **olhe o
   `contact-sheet.jpg`** antes de seguir. Lint passando não diz como ficou.
5. **Renderizar.** `npx hyperframes@0.9.16 render -o ../ilustracao.mp4` (~10 s para 20 s de vídeo).
6. **Montar.** `render.py ... --painel videos/<nome>/ilustracao.mp4` (prévia e final). Vídeo só de câmera: o preset
   do vídeo mede o `camera_crop` em volta do rosto. O `slide_crop` não é usado com `--painel`, mas precisa caber no
   quadro. 👀 A prévia vai para o Vitor como sempre.

## Estilo (aprovado em 05/11/2026, vídeo "teste ilustração")

- Fundo `#141B2D` (o mesmo do vídeo), cartões `#1E2740` com borda `#2C3757` e cantos de 22 px.
- Poppins Bold e ExtraBold. Destaque em laranja `#F5A623` (o mesmo da legenda e do selo dos slides). Verde
  `#3DDC84` para "deu certo", vermelho `#FF5A4F` para erro ou raiva.
- Personagens e reações: Fluent Emoji 3D da Microsoft (MIT), baixados de
  `https://raw.githubusercontent.com/microsoft/fluentui-emoji/main/assets/<Nome>/3D/<nome>_3d.png` (com tom de pele:
  `<Nome>/Default/3D/<nome>_3d_default.png`). Não desenhe rosto em SVG à mão: o Vitor achou feio.
- Entradas curtas (0,3–0,5 s, `back.out`), um elemento por vez, sem nada se mexendo enquanto ele explica outra coisa.
  Tremida só para raiva ou erro.

## Armadilhas

- **Aparecer antes da hora.** O elemento entra na palavra que o nomeia, não no começo da frase. No teste, a
  planilha entrou em "trabalho" e o Vitor notou: o certo era em "planilha".
- **Efeito sonoro junto.** Se a ilustração tem um momento forte (algo aparece, alguém grita), combine com a skill
  `efeitos-sonoros` no mesmo tempo. Mínimo de 3,5 s entre efeitos.
- **A ilustração segue o vídeo final.** Se os cortes mudarem depois (`cuts.py --force`), os tempos mudam: rode o
  `marcas` de novo e ajuste a timeline antes de renderizar.
- O GSAP vem de CDN na hora do render (o HTML do exemplo usa jsDelivr). Sem internet, baixe o `gsap.min.js` para
  `ilustracao/assets/` e aponte para ele.
