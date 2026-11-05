# Licenças de terceiros

Este repositório inclui código de terceiros (licença MIT) e fontes (SIL OFL 1.1). O aviso de direitos autorais
e o texto da licença original são mantidos junto de cada cópia.

## video-editing-skill — Frank Heijdenrijk

- Origem: https://github.com/social-media-skills/video-editing-skill
- Licença: MIT (texto completo em `vendor/dev-video-editing/LICENSE`)
- Onde está: `vendor/dev-video-editing/` (cópia **sem modificações**; a versão está em
  `vendor/dev-video-editing/.upstream-commit`)
- Mudanças nossas ficam em `src/` e `presets/`, nunca dentro de `vendor/`.

## ffmpeg-skill — kajisho5 (referência, nada copiado)

- Origem: https://github.com/kajisho5/ffmpeg-skill
- Licença: MIT
- Não há código dele neste repositório. Se algum dia for copiado, incluir aqui o aviso de
  direitos autorais e o texto da licença original.

## Poppins — fonte usada nas capas

- Arquivos: `vendor/dev-video-editing/fonts/Poppins-*.ttf`
- Licença: SIL Open Font License 1.1 (`vendor/dev-video-editing/fonts/OFL-Poppins.txt`)

## Liberation Sans Bold — fonte da legenda

- Arquivo: `assets/fonts/LiberationSans-Bold.ttf` (versão 2.1.5, release oficial de
  https://github.com/liberationfonts/liberation-fonts)
- Licença: SIL Open Font License 1.1 (`assets/fonts/licencas/LiberationSans-OFL.txt`). © 2012 Red Hat, Inc.;
  Digitized data © 2010 Google Corporation
- A licença fica numa subpasta porque o libass tenta abrir como fonte todo arquivo da pasta `fontsdir`.
