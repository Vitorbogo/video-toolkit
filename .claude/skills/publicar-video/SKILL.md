---
name: publicar-video
description: Escreve título, descrição, legenda do TikTok, hashtags e recomendação de capa de um vídeo do video-toolkit (videos/<nome>/meta.json) e gera o publicar.md. Usar quando o plan.json de um vídeo for revisado, quando o vídeo final/capas forem gerados, ou quando o Vitor pedir título, descrição, hashtags ou "tudo para postar".
---

# Metadados de publicação

Objetivo: o Vitor chega ao fim da edição e só copia e cola. Nada de pesquisar regra de plataforma de novo.

## Quando
- **Escreva o `meta.json` logo depois de revisar o `plan.json` com o Vitor** (o rascunho do `cuts.py` ainda não tem as legendas corrigidas; depois da revisão o conteúdo está fresco). Não espere o render.
  A capa ainda não existe nesse momento (o `thumb.json` depende do vídeo final): escreva `"capa": {"variante": "A", "motivo": "PROVISÓRIA: ..."}`.
- **Depois do `thumb.py`**, olhe as capas em `videos/<nome>/capas/`, escolha a variante do `thumb.json` e reescreva `capa` (sem "PROVISÓRIA").
- **Rode `publish.py` depois de `postaudio.py` e `thumb.py`**, com o mp4 final. As capas são lidas de `videos/<nome>/capas/` (ou `--capas`).

```bash
python3 src/vtk/publish.py --name <nome> --video <mp4 final, depois do postaudio.py>
```
Dá `ERRO` (e nada é gerado; um `publicar.md` antigo vira `publicar.md.desatualizado`) se: faltar campo ou o tipo estiver errado, passar limite de plataforma, houver `#hashtag` no título/descrição/legenda, a capa estiver `PROVISÓRIA`, a variante não existir no `thumb.json` ou os arquivos dela não estiverem em `capas/`, o vídeo não existir ou não tiver duração legível. Corrija o `meta.json` e rode de novo. Não edite o `publicar.md` à mão (é regenerado). Os limites vivem em `presets/publish.json`, não aqui.

## Formato do `videos/<nome>/meta.json`
```json
{
  "titulos": ["recomendado", "alternativa 1", "alternativa 2"],
  "descricao": "texto sem hashtags",
  "legenda_tiktok": "texto sem hashtags",
  "hashtags": { "tiktok": ["#Ampla", "#DoTema"], "youtube": ["#Ampla", "#DoTema"] },
  "hashtags_motivo": "1 frase",
  "capa": { "variante": "A", "motivo": "1 frase" },
  "tags_youtube": ["opcional"],
  "comentario_fixado": "opcional",
  "notas": "opcional"
}
```

## Regras de conteúdo
- **Fonte da verdade:** o que o vídeo realmente diz (`plan.json`/legendas) e a nota `AULA -` de origem no vault. Não prometa o que o vídeo não entrega.
- **Público:** o padrão é **geral** (quem usa IA no trabalho, de qualquer área). Vídeo **nichado** (ex.: IA para advogados) só quando o conteúdo só serve àquele público ou o Vitor disser. A aula vir de um curso nichado não torna o vídeo nichado: um exemplo jurídico num vídeo sobre prompt é exemplo, não público. Diga em `hashtags_motivo` qual público você assumiu.
- **Língua e tom:** português do Brasil, colega experiente falando com colega (regra 4 do `CLAUDE.md` do vault). Sem condescendência, sem MAIÚSCULAS gritadas, sem promessa de resultado (jurídico, financeiro ou outro).
- **Título:** a promessa concreta nos **primeiros 50 caracteres** (o feed corta ali). Dar 3 opções, a recomendada primeiro. Nada de isca que o vídeo não cumpre. Sem `<` nem `>` (o YouTube recusa).
- **Descrição e legenda:** o gancho cabe em ~100 caracteres (é o que aparece antes do "mais"). Depois: 1 a 2 frases do que a pessoa leva do vídeo e uma chamada para o próximo passo (curso, vídeo seguinte). Sem links inventados: se não houver link real, não ponha.
- **Hashtags:** padrão 3 a 5 por plataforma, uma ampla (ex.: `#InteligenciaArtificial`) + as demais específicas do tema. Hashtag de público (`#IAParaAdvogados`) só em vídeo nichado. Quais hashtags usar para o público geral ainda é decisão do Vitor: proponha, marque como proposta em `hashtags_motivo` e não trate escolhas anteriores como padrão. CamelCase (`#InteligenciaArtificial`). As primeiras do YouTube podem aparecer acima do título (não confirmado em Shorts): as mais importantes vão primeiro. Sem hashtag "de alcance" genérica por padrão. Fugir da faixa de 3 a 5 só com justificativa em `hashtags_motivo` (o `publish.py` avisa).
- **Capa:** escolha entre as variantes de `thumb.json` (o `nome` dela vai em `capa.variante`) e justifique em uma frase (rosto aberto, texto legível no celular, quadro que representa o vídeo).
- **Fatos de plataforma** (limites, regras de capa) não entram aqui: se precisar de um número novo, atualize `presets/publish.json` depois de conferir na fonte oficial.
- **Sem API paga e sem enviar áudio/vídeo para fora.**
