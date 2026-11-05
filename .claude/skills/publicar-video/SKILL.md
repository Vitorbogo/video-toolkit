---
name: publicar-video
description: Escreve título, descrição, legenda do TikTok, hashtags e recomendação de capa de um vídeo do video-toolkit (videos/<nome>/meta.json) e gera o publicar.md. Usar quando o plan.json de um vídeo for revisado, quando o vídeo final/capas forem gerados, ou quando pedirem título, descrição, hashtags ou "tudo para postar".
---

# Metadados de publicação

Objetivo: o autor chega ao fim da edição e só copia e cola. Nada de pesquisar regra de plataforma de novo.

## Quando
- **Escreva o `meta.json` logo depois de revisar o `plan.json` com o autor** (o rascunho do `cuts.py` ainda não tem as legendas corrigidas; depois da revisão o conteúdo está fresco). Não espere o render.
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
- **Fonte da verdade:** o que o vídeo realmente diz (`plan.json`/legendas) e o material de origem, se o autor indicar um (`CLAUDE.local.md`). Não prometa o que o vídeo não entrega.
- **Público:** siga o conteúdo do vídeo. O padrão é o público mais amplo que o tema atende; o público padrão do canal, se houver, está no `CLAUDE.local.md`. Vídeo **nichado** (um público ou área específica) só quando o conteúdo só serve àquele público ou o autor disser. A origem do material ser nichada não torna o vídeo nichado: um exemplo de uma área num vídeo sobre um tema geral é exemplo, não público. Diga em `hashtags_motivo` qual público você assumiu.
- **Língua e tom:** a língua do vídeo, colega experiente falando com colega. Sem condescendência, sem MAIÚSCULAS gritadas, sem promessa de resultado (financeiro, profissional ou outro).
- **Título:** a promessa concreta nos **primeiros 50 caracteres** (o feed corta ali). Dar 3 opções, a recomendada primeiro. Nada de isca que o vídeo não cumpre. Sem `<` nem `>` (o YouTube recusa).
- **Descrição e legenda:** o gancho cabe em ~100 caracteres (é o que aparece antes do "mais"). Depois: 1 a 2 frases do que a pessoa leva do vídeo e uma chamada para o próximo passo (vídeo seguinte, material relacionado). Sem links inventados: se não houver link real, não ponha.
- **Hashtags:** padrão 3 a 5 por plataforma, uma ampla do tema + as demais específicas do conteúdo do vídeo. Hashtag de público (ex.: `#<Tema>Para<Profissão>`) só em vídeo nichado. Quais hashtags usar para o público geral ainda é decisão do autor: proponha, marque como proposta em `hashtags_motivo` e não trate escolhas anteriores como padrão. CamelCase (`#EdicaoDeVideo`). As primeiras do YouTube podem aparecer acima do título (não confirmado em Shorts): as mais importantes vão primeiro. Sem hashtag "de alcance" genérica por padrão. Fugir da faixa de 3 a 5 só com justificativa em `hashtags_motivo` (o `publish.py` avisa).
- **Capa:** escolha entre as variantes de `thumb.json` (o `nome` dela vai em `capa.variante`) e justifique em uma frase (rosto aberto, texto legível no celular, quadro que representa o vídeo).
- **Fatos de plataforma** (limites, regras de capa) não entram aqui: se precisar de um número novo, atualize `presets/publish.json` depois de conferir na fonte oficial.
- **Sem API paga e sem enviar áudio/vídeo para fora.**
