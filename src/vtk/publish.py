#!/usr/bin/env python3
"""Valida os metadados de publicacao de um video e gera videos/<nome>/publicar.md (pronto para copiar e colar).

A parte criativa (titulos, descricao, hashtags, recomendacao de capa) e escrita pelo Claude em
videos/<nome>/meta.json, seguindo .claude/skills/publicar-video/SKILL.md.
Este script e a parte DETERMINISTICA: confere limites das plataformas (presets/publish.json), formato
das hashtags, capas existentes e duracao, e monta o arquivo final. Mesmo meta.json = mesmo publicar.md.
Sai com codigo 1 se houver ERRO (nada e gerado); AVISOS entram no topo do publicar.md.

  python3 src/vtk/publish.py --name prompt-basico --video final.mp4 --capas capas/
"""
import argparse, datetime, json, os, re, subprocess, sys

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ap = argparse.ArgumentParser()
ap.add_argument("--name", required=True, help="pasta em videos/<nome>/")
ap.add_argument("--video", help="mp4 final (para conferir a duracao)")
ap.add_argument("--capas", help="pasta das capas geradas pelo thumb.py (confere se existem)")
ap.add_argument("--preset", default="presets/publish.json")
ap.add_argument("--out", help="padrao: videos/<nome>/publicar.md")
a = ap.parse_args()

vdir = os.path.join(root, "videos", a.name)
P = json.load(open(a.preset if os.path.isabs(a.preset) else os.path.join(root, a.preset)))
L, H = P["limites"], P["hashtags"]
mp = os.path.join(vdir, "meta.json")

CAMPOS = {
    "titulos": "lista de 1 a 3 titulos (o primeiro e o recomendado)",
    "descricao": "descricao do YouTube, sem hashtags (gancho nos primeiros 100 caracteres)",
    "legenda_tiktok": "legenda do TikTok, sem hashtags",
    "hashtags": '{"tiktok": [...], "youtube": [...]}, cada uma com "#"',
    "hashtags_motivo": "1 frase: por que essas hashtags (ou por que nenhuma)",
    "capa": '{"variante": "A|B|C", "motivo": "..."}',
}
if not os.path.exists(mp):
    print(f"ERRO: falta {os.path.relpath(mp, root)}. Campos obrigatorios:")
    for k, v in CAMPOS.items(): print(f"  - {k}: {v}")
    print("Opcionais: tags_youtube, comentario_fixado, notas. Regras: .claude/skills/publicar-video/SKILL.md")
    sys.exit(1)
M = json.load(open(mp))

erros, avisos = [], []
for k in CAMPOS:
    if k not in M or M[k] in ("", [], {}, None): erros.append(f"campo obrigatorio ausente ou vazio: {k}")
if erros:
    print("\n".join("ERRO: " + e for e in erros)); sys.exit(1)

yt, tt = L["youtube"], L["tiktok"]
for i, t in enumerate(M["titulos"]):
    if len(t) > yt["titulo_max"]: erros.append(f"titulo {i+1} tem {len(t)} caracteres (max {yt['titulo_max']})")
    elif len(t) > yt["titulo_visivel_feed"]:
        avisos.append(f"titulo {i+1} tem {len(t)} caracteres; no feed so aparecem ~{yt['titulo_visivel_feed']}. Ponha o principal no comeco.")
if len(M["descricao"]) > yt["descricao_max"]: erros.append(f"descricao tem {len(M['descricao'])} caracteres (max {yt['descricao_max']})")

rx = re.compile(r"^#[\wÀ-ÿ]+$")
tags = {}
for plat in ("tiktok", "youtube"):
    hs = M["hashtags"].get(plat, [])
    tags[plat] = hs
    bad = [h for h in hs if not rx.match(h)]
    if bad: erros.append(f"hashtags invalidas em {plat} (precisa '#' e sem espaco/pontuacao): {bad}")
    if len({h.lower() for h in hs}) != len(hs): erros.append(f"hashtags repetidas em {plat}")
    if hs and not (H["recomendado_min"] <= len(hs) <= H["recomendado_max"]):
        avisos.append(f"{plat}: {len(hs)} hashtags (recomendado {H['recomendado_min']} a {H['recomendado_max']}). Se for de proposito, explique em hashtags_motivo.")
if len(tags["youtube"]) > yt["hashtags_max"]: erros.append("hashtags do YouTube acima do limite: todas seriam ignoradas")

leg_tt = M["legenda_tiktok"] + ("\n\n" + " ".join(tags["tiktok"]) if tags["tiktok"] else "")
if len(leg_tt) > tt["legenda_max"]: erros.append(f"legenda do TikTok tem {len(leg_tt)} caracteres (max {tt['legenda_max']})")
desc_yt = M["descricao"] + ("\n\n" + " ".join(tags["youtube"]) if tags["youtube"] else "")
if len(desc_yt) > yt["descricao_max"]: erros.append(f"descricao + hashtags tem {len(desc_yt)} caracteres (max {yt['descricao_max']})")
tgs = M.get("tags_youtube", [])
if len(",".join(tgs)) > yt["tags_total_max"]: erros.append(f"tags do YouTube somam {len(','.join(tgs))} caracteres (max {yt['tags_total_max']})")

dur = None
if a.video:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", a.video], capture_output=True, text=True)
    try: dur = float(r.stdout.strip())
    except ValueError: avisos.append(f"nao consegui ler a duracao de {a.video}")
if dur and dur > yt["short_duracao_max_s"]:
    avisos.append(f"video com {int(dur)} s: acima de {yt['short_duracao_max_s']} s, o YouTube nao trata como Short (vira video vertical normal).")

var, tj = M["capa"].get("variante"), None
tp = os.path.join(vdir, "thumb.json")
if os.path.exists(tp): tj = json.load(open(tp))
vinfo = None
if tj and var:
    vinfo = next((v for v in tj.get("variantes", []) if v.get("nome") == var), None)
    if vinfo is None: avisos.append(f"variante de capa '{var}' nao existe em thumb.json")
arqs = {"9x16": f"capa_{var}_9x16_1080x1920.png", "16x9": f"capa_{var}_16x9_1280x720.png"}
if a.capas:
    for f in arqs.values():
        if not os.path.exists(os.path.join(a.capas, f)): avisos.append(f"capa nao encontrada: {os.path.join(a.capas, f)} (rode thumb.py)")

if erros:
    print("\n".join("ERRO: " + e for e in erros)); sys.exit(1)

mmss = lambda s: f"{int(s)//60}:{int(s)%60:02d}"
o = []
o.append(f"# Publicar — {a.name}\n")
o.append(f"_Gerado por `publish.py` em {datetime.date.today().isoformat()}" + (f" · duração {mmss(dur)}" if dur else "") + "_\n")
if avisos:
    o.append("> [!warning] Avisos\n" + "\n".join(f"> - {x}" for x in avisos) + "\n")
o.append("## Capa\n")
o.append(f"**Recomendada: variante {var}.** {M['capa']['motivo']}\n")
o.append(f"- Arquivos: `{arqs['9x16']}` (vertical) e `{arqs['16x9']}` (YouTube)")
if vinfo and vinfo.get("vertical"):
    o.append(f"- TikTok: no editor de capa, escolha o quadro em ~{vinfo['vertical']['tempo_s']} s (é o quadro usado na variante {var}).")
o.append("- YouTube: envie a capa 16:9 como miniatura personalizada. _Para Shorts, confirme se o Studio aceita miniatura personalizada no seu caso (não verificado)._\n")
o.append("## TikTok\n")
o.append("Legenda (cole inteira):\n\n```text\n" + leg_tt + "\n```\n")
o.append("## YouTube\n")
o.append("**Título recomendado:**\n\n```text\n" + M["titulos"][0] + "\n```\n")
if len(M["titulos"]) > 1:
    o.append("Alternativas:\n" + "\n".join(f"- {t}" for t in M["titulos"][1:]) + "\n")
o.append("Descrição (cole inteira; as 3 primeiras hashtags aparecem acima do título):\n\n```text\n" + desc_yt + "\n```\n")
if tgs: o.append("Tags (campo oculto do Studio):\n\n```text\n" + ", ".join(tgs) + "\n```\n")
if M.get("comentario_fixado"): o.append("Comentário fixado:\n\n```text\n" + M["comentario_fixado"] + "\n```\n")
o.append("## Hashtags: por quê\n\n" + M["hashtags_motivo"] + "\n")
if M.get("notas"): o.append("## Notas\n\n" + M["notas"] + "\n")
o.append("## Antes de postar\n\n" + "\n".join(f"- [ ] {c}" for c in P["checklist"]) + "\n")
out = a.out or os.path.join(vdir, "publicar.md")
open(out, "w", encoding="utf-8").write("\n".join(o))
print(f"ok: {os.path.relpath(out, root)}  ({len(avisos)} aviso(s))")
for x in avisos: print("  aviso:", x)
