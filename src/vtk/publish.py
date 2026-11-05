#!/usr/bin/env python3
"""Valida os metadados de publicacao de um video e gera videos/<nome>/publicar.md (pronto para copiar e colar).

A parte criativa (titulos, descricao, hashtags, recomendacao de capa) e escrita pelo Claude em
videos/<nome>/meta.json, seguindo .claude/skills/publicar-video/SKILL.md.
Este script e a parte DETERMINISTICA: confere tipos e limites das plataformas (presets/publish.json), formato
das hashtags, a capa escolhida (thumb.json + arquivos em capas/) e a duracao, e monta o arquivo final.
Mesmas entradas (meta.json, thumb.json, preset, duracao do video) = mesmo publicar.md, byte a byte (nao tem data).
Sai com codigo 1 se houver ERRO: nada e gerado e um publicar.md antigo vira publicar.md.desatualizado.
AVISOS entram no topo do publicar.md.

  python3 src/vtk/publish.py --name <nome> --video <mp4 final>   # capas: videos/<nome>/capas (ou --capas)
"""
import argparse, json, os, re, shutil, subprocess, sys, unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CAMPOS = {
    "titulos": "lista de 1 a 3 titulos (o primeiro e o recomendado)",
    "descricao": "descricao do YouTube, sem hashtags (gancho nos primeiros 100 caracteres)",
    "legenda_tiktok": "legenda do TikTok, sem hashtags",
    "hashtags": '{"tiktok": [...], "youtube": [...]}, cada uma com "#"',
    "hashtags_motivo": "1 frase: por que essas hashtags (ou por que nenhuma)",
    "capa": '{"variante": "A|B|C" (de thumb.json), "motivo": "..."}',
}
OPCIONAIS = ("tags_youtube", "comentario_fixado", "notas")
PLATAFORMAS = ("tiktok", "youtube")

RX_HASHTAG = re.compile(r"^#\w+$")
RX_HASH_NO_TEXTO = re.compile(r"(?<![\w&/])#\w+")
RX_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍]")


def nfc(x):
    """Normaliza (NFC) todas as strings: "ã" conta 1 caractere, venha de onde vier."""
    if isinstance(x, str): return unicodedata.normalize("NFC", x)
    if isinstance(x, list): return [nfc(v) for v in x]
    if isinstance(x, dict): return {k: nfc(v) for k, v in x.items()}
    return x


def texto(v):
    return isinstance(v, str) and v.strip() != ""


def lista_textos(v):
    return isinstance(v, list) and all(texto(x) for x in v)


def arquivos_capa(var):
    return {"9x16": f"capa_{var}_9x16_1080x1920.png", "16x9": f"capa_{var}_16x9_1280x720.png"}


def legenda_tt(M):
    hs = M["hashtags"]["tiktok"]
    return M["legenda_tiktok"] + ("\n\n" + " ".join(hs) if hs else "")


def descricao_yt(M):
    hs = M["hashtags"]["youtube"]
    return M["descricao"] + ("\n\n" + " ".join(hs) if hs else "")


def tags_total(tags):
    """Como o YouTube conta o campo de tags: virgulas entre elas + 2 aspas em cada tag com espaco."""
    return len(",".join(tags)) + 2 * sum(1 for t in tags if " " in t)


def duracao(video):
    """Duracao em segundos (1 casa) via ffprobe. Levanta ValueError com mensagem legivel."""
    if not os.path.isfile(video):
        raise ValueError(f"video nao encontrado: {video}")
    if not shutil.which("ffprobe"):
        raise ValueError("ffprobe nao encontrado no PATH (vem com o ffmpeg); sem ele nao da para conferir a duracao")
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video],
                       capture_output=True, text=True)
    try:
        return round(float(r.stdout.strip()), 1)
    except ValueError:
        raise ValueError(f"nao consegui ler a duracao de {video} (ffprobe: {r.stderr.strip()[:200] or 'sem saida'})")


def validate(M, P, dur=None, thumb=None, capas=None):
    """Confere o meta.json (ja em NFC) contra o preset. Devolve (erros, avisos).
    dur: segundos ou None (nao confere); thumb: thumb.json ou None (falta); capas: nomes dos arquivos em capas/ ou None."""
    erros, avisos = [], []
    if not isinstance(M, dict):
        return ["meta.json precisa ser um objeto JSON {...}"], []
    tem = lambda k: k in M and M[k] not in ("", [], {}, None)
    for k in CAMPOS:
        if not tem(k): erros.append(f"campo obrigatorio ausente ou vazio: {k} ({CAMPOS[k]})")
    for k in ("descricao", "legenda_tiktok", "hashtags_motivo"):
        if tem(k) and not texto(M[k]): erros.append(f"{k} precisa ser texto")
    t = M.get("titulos")
    if tem("titulos") and not (isinstance(t, list) and 1 <= len(t) <= 3 and lista_textos(t)):
        erros.append("titulos precisa ser lista de 1 a 3 textos nao vazios")
    h = M.get("hashtags")
    if tem("hashtags"):
        if not isinstance(h, dict): erros.append('hashtags precisa ser {"tiktok": [...], "youtube": [...]}')
        else:
            for p in sorted(set(h) - set(PLATAFORMAS)): erros.append(f"hashtags: plataforma desconhecida '{p}' (use {', '.join(PLATAFORMAS)})")
            for p in PLATAFORMAS:
                if p not in h: erros.append(f"hashtags.{p} ausente (lista vazia [] se nao houver)")
                elif not (isinstance(h[p], list) and all(isinstance(x, str) for x in h[p])): erros.append(f"hashtags.{p} precisa ser lista de textos")
    c = M.get("capa")
    if tem("capa"):
        if not isinstance(c, dict): erros.append('capa precisa ser {"variante": "...", "motivo": "..."}')
        else:
            for k in ("variante", "motivo"):
                if not texto(c.get(k)): erros.append(f"capa.{k} ausente ou vazio")
    if "tags_youtube" in M and not lista_textos(M["tags_youtube"]):
        erros.append("tags_youtube precisa ser lista de textos nao vazios")
    for k in ("comentario_fixado", "notas"):
        if k in M and not isinstance(M[k], str): erros.append(f"{k} precisa ser texto")
    for k in sorted(set(M) - set(CAMPOS) - set(OPCIONAIS)): avisos.append(f"campo desconhecido no meta.json (ignorado): {k}")
    if erros:
        return erros, avisos

    L, H = P["limites"], P["hashtags"]
    yt, tt = L["youtube"], L["tiktok"]
    for i, t in enumerate(M["titulos"], 1):
        if len(t) > yt["titulo_max"]: erros.append(f"titulo {i} tem {len(t)} caracteres (max {yt['titulo_max']})")
        elif len(t) > yt["titulo_visivel_feed"]:
            avisos.append(f"titulo {i} tem {len(t)} caracteres; no feed so aparecem ~{yt['titulo_visivel_feed']}. Ponha o principal no comeco.")

    textos = [(f"titulo {i}", t) for i, t in enumerate(M["titulos"], 1)] + [("descricao", M["descricao"]), ("legenda_tiktok", M["legenda_tiktok"])]
    for nome, s in textos:
        achou = RX_HASH_NO_TEXTO.findall(s)
        if achou: erros.append(f"{nome} tem hashtag no texto {achou}: hashtags vao so nas listas de hashtags")
        if nome != "legenda_tiktok" and re.search("[<>]", s): erros.append(f"{nome} tem '<' ou '>' (o YouTube nao aceita)")
    com_emoji = [n for n, s in textos if RX_EMOJI.search(s)]
    if com_emoji: avisos.append(f"emoji em {', '.join(com_emoji)}: a plataforma pode contar diferente (confira o limite ao colar)")

    for p in PLATAFORMAS:
        hs = M["hashtags"][p]
        bad = [x for x in hs if not RX_HASHTAG.match(x)]
        if bad: erros.append(f"hashtags invalidas em {p} (precisa '#' e sem espaco/pontuacao): {bad}")
        vistos, rep = set(), []
        for x in hs:
            if x.casefold() in vistos: rep.append(x)
            vistos.add(x.casefold())
        if rep: erros.append(f"hashtags repetidas em {p} (maiuscula/minuscula nao diferencia): {rep}")
        if hs and not (H["recomendado_min"] <= len(hs) <= H["recomendado_max"]):
            avisos.append(f"{p}: {len(hs)} hashtags (recomendado {H['recomendado_min']} a {H['recomendado_max']}). Se for de proposito, explique em hashtags_motivo.")
    if len(M["hashtags"]["youtube"]) > yt["hashtags_max"]:
        erros.append(f"{len(M['hashtags']['youtube'])} hashtags no YouTube (max {yt['hashtags_max']}): acima disso todas sao ignoradas")

    n = len(legenda_tt(M))
    if n > tt["legenda_max"]: erros.append(f"legenda do TikTok + hashtags tem {n} caracteres (max {tt['legenda_max']})")
    d = descricao_yt(M)
    if len(d) > yt["descricao_max"]: erros.append(f"descricao + hashtags tem {len(d)} caracteres (max {yt['descricao_max']})")
    elif len(d.encode("utf-8")) > yt["descricao_max"]:
        avisos.append(f"descricao + hashtags tem {len(d.encode('utf-8'))} bytes em UTF-8 (> {yt['descricao_max']}); se o limite for em bytes, o YouTube corta")
    tg = M.get("tags_youtube", [])
    if tags_total(tg) > yt["tags_total_max"]:
        erros.append(f"tags do YouTube somam {tags_total(tg)} caracteres, contando virgulas e aspas das tags com espaco (max {yt['tags_total_max']})")

    if dur is not None:
        if dur <= 0: erros.append(f"duracao do video e {dur:.1f} s: arquivo vazio ou corrompido")
        elif dur > yt["short_duracao_max_s"]:
            avisos.append(f"video com {dur:.1f} s: acima de {yt['short_duracao_max_s']} s, o YouTube nao trata como Short (vira video vertical normal).")

    var, motivo = M["capa"]["variante"], M["capa"]["motivo"]
    if motivo.strip().upper().startswith("PROVIS"):
        erros.append("capa ainda provisoria: olhe as capas do thumb.py e atualize capa.variante e capa.motivo")
    if thumb is None:
        erros.append("falta thumb.json do video: a capa e escolhida entre as variantes dele")
    else:
        nomes = [v.get("nome") for v in thumb.get("variantes") or [] if isinstance(v, dict)]
        if var not in nomes:
            opc = nomes or 'nenhuma; ponha "variantes" no thumb.json'
            erros.append(f"variante de capa '{var}' nao existe em thumb.json (variantes: {opc})")
    if capas is None:
        erros.append("pasta de capas nao encontrada (rode thumb.py)")
    else:
        for f in arquivos_capa(var).values():
            if f not in capas: erros.append(f"capa nao encontrada: {f} (rode thumb.py)")
    return erros, avisos


def render(nome, M, P, dur, thumb, avisos, usados=None):
    """Monta o publicar.md. So depende das entradas (sem data, sem caminho absoluto).
    usados: capas/capas.json do thumb.py (tempos reais, inclusive os "auto" do rosto neutro)."""
    yt, tt = P["limites"]["youtube"], P["limites"]["tiktok"]
    var = M["capa"]["variante"]
    arqs = arquivos_capa(var)
    vinfo = next((v for v in (thumb or {}).get("variantes") or [] if isinstance(v, dict) and v.get("nome") == var), None)
    corte = lambda s, n: " ".join(s[:n].split()) + ("…" if len(s) > n else "")  # numa linha so
    mmss = lambda s: f"{int(round(s)) // 60}:{int(round(s)) % 60:02d}"
    o = [f"# Publicar — {nome}\n"]
    o.append("_Gerado por `publish.py`" + (f" · duração {mmss(dur)}" if dur else "") + "_\n")
    if avisos:
        o.append("> [!warning] Avisos\n" + "\n".join(f"> - {x}" for x in avisos) + "\n")
    o.append("## Capa\n")
    o.append(f"**Recomendada: variante {var}.** {M['capa']['motivo']}\n")
    o.append(f"- Arquivos: `{arqs['9x16']}` (vertical) e `{arqs['16x9']}` (YouTube)")
    t = ((usados or {}).get(var) or {}).get("vertical", {}).get("tempo_s")
    if t is None and vinfo and isinstance(vinfo.get("vertical"), dict):
        t = vinfo["vertical"].get("tempo_s")
    if isinstance(t, (int, float)) and not isinstance(t, bool):
        o.append(f"- TikTok: no editor de capa, escolha o quadro em ~{t:g} s (é o quadro usado na variante {var}).")
    o.append("- YouTube: envie a capa 16:9 como miniatura personalizada. _Para Shorts, confirme se o Studio aceita miniatura personalizada no seu caso (não verificado)._\n")
    o.append("## TikTok\n")
    o.append("Legenda (cole inteira):\n\n```text\n" + legenda_tt(M) + "\n```\n")
    o.append(f"Antes do \"mais\" (~{tt['legenda_visivel']} caracteres): {corte(M['legenda_tiktok'], tt['legenda_visivel'])}\n")
    o.append("## YouTube\n")
    o.append("**Título recomendado:**\n\n```text\n" + M["titulos"][0] + "\n```\n")
    if len(M["titulos"]) > 1:
        o.append("Alternativas:\n" + "\n".join(f"- {t}" for t in M["titulos"][1:]) + "\n")
    o.append(f"Descrição (cole inteira; as {yt['hashtags_acima_do_titulo']} primeiras hashtags podem aparecer acima do título, "
             "não verificado para Shorts):\n\n```text\n" + descricao_yt(M) + "\n```\n")
    o.append(f"Antes do \"mais\" (~{yt['descricao_visivel']} caracteres): {corte(M['descricao'], yt['descricao_visivel'])}\n")
    if M.get("tags_youtube"): o.append("Tags (campo oculto do Studio):\n\n```text\n" + ", ".join(M["tags_youtube"]) + "\n```\n")
    if M.get("comentario_fixado"): o.append("Comentário fixado:\n\n```text\n" + M["comentario_fixado"] + "\n```\n")
    o.append("## Hashtags: por quê\n\n" + M["hashtags_motivo"] + "\n")
    if M.get("notas"): o.append("## Notas\n\n" + M["notas"] + "\n")
    o.append("## Antes de postar\n\n" + "\n".join(f"- [ ] {c}" for c in P["checklist"]) + "\n")
    return "\n".join(o)


def ler_json(path, rotulo, erros):
    try:
        with open(path, encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError) as e:
        erros.append(f"{rotulo} ilegivel ({path}): {e}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Valida videos/<nome>/meta.json e gera publicar.md")
    ap.add_argument("--name", required=True, help="pasta em videos/<nome>/ (ou caminho absoluto da pasta)")
    ap.add_argument("--video", required=True, help="mp4 final (confere a duracao)")
    ap.add_argument("--capas", help="pasta das capas do thumb.py (padrao: videos/<nome>/capas)")
    ap.add_argument("--preset", default="presets/publish.json")
    ap.add_argument("--out", help="padrao: videos/<nome>/publicar.md")
    a = ap.parse_args(argv)

    vdir = a.name if os.path.isabs(a.name) else os.path.join(ROOT, "videos", a.name)
    nome = os.path.basename(os.path.normpath(vdir))
    out = os.path.abspath(a.out) if a.out else os.path.join(vdir, "publicar.md")
    capas = a.capas or os.path.join(vdir, "capas")
    mp, tp = os.path.join(vdir, "meta.json"), os.path.join(vdir, "thumb.json")
    erros, avisos = [], []

    P = ler_json(a.preset if os.path.isabs(a.preset) else os.path.join(ROOT, a.preset), "preset", erros)
    M = None
    if not os.path.exists(mp):
        erros.append(f"falta {mp}. Campos obrigatorios:\n" + "\n".join(f"  - {k}: {v}" for k, v in CAMPOS.items())
                     + f"\nOpcionais: {', '.join(OPCIONAIS)}. Regras: .claude/skills/publicar-video/SKILL.md")
    else:
        M = ler_json(mp, "meta.json", erros)
    thumb = ler_json(tp, "thumb.json", erros) if os.path.exists(tp) else None
    dur = None
    try: dur = duracao(a.video)
    except ValueError as e: erros.append(str(e))
    if M is not None and P is not None:
        M = nfc(M)
        e2, avisos = validate(M, P, dur, thumb, set(os.listdir(capas)) if os.path.isdir(capas) else None)
        erros += e2

    velho = out + ".desatualizado"
    if erros:
        print("\n".join("ERRO: " + e for e in erros))
        if os.path.exists(out):
            os.replace(out, velho)
            print(f"publicar.md antigo renomeado para {os.path.basename(velho)} (nao use: nao bate com o meta.json atual)")
        return 1
    tmp = out + ".tmp"
    usados = None
    try:
        with open(os.path.join(capas, "capas.json"), encoding="utf-8") as f: usados = json.load(f)
    except (OSError, ValueError): pass
    with open(tmp, "w", encoding="utf-8", newline="\n") as f: f.write(render(nome, M, P, dur, thumb, avisos, usados))
    os.replace(tmp, out)
    if os.path.exists(velho): os.remove(velho)
    print(f"ok: {out}  ({len(avisos)} aviso(s))")
    for x in avisos: print("  aviso:", x)
    return 0


if __name__ == "__main__":
    sys.exit(main())
