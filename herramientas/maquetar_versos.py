#!/usr/bin/env python3
"""Traduce y maqueta un libro con capa de texto limpia conservando versos y voces línea a línea.

El traductor normal funde las líneas de una página en párrafos; en un libro de versos eso
destruye el orden de las voces (una por renglón, entre versos que sí se traducen). Esta herramienta
lee la geometría del PDF (fuente, cursiva, sangría, ancho de línea) y reconstruye:
  - párrafos: las líneas llenas se unen; una línea corta es un corte duro y se conserva;
  - líneas de solo voces (mayúsculas): se copian tal cual, sin pasar por el modelo;
  - encabezados, capitulares, listas numeradas, notas al pie, figuras y epígrafes;
  - la capa de texto que cae dentro de una figura (basura) se descarta.
Cada unidad se traduce con el motor del traductor (glosario y voces enmascarados) y la caché;
el PDF final es de flujo continuo en el tamaño de página del libro. El índice lleva páginas reales.

Uso: python herramientas/maquetar_versos.py libro.pdf salida.pdf --glosario g.txt
         [--titulo "EL LIBRO" --subtitulo "..." --autor "..."] [--sin-traducir-desde Bibliography]
         [--desde 1 --hasta 40] [--saltar 1,2] [--hilos 6] [--motor groq --modelo openai/gpt-oss-120b]
"""
from __future__ import annotations

import argparse
import base64
import html as _html
import os
import re
import statistics
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz

FLAGS = fitz.TEXT_INHIBIT_SPACES
TOL = 14.0
MARCA = re.compile(r"^(?:[IVXL]+|\d{1,2})\.$")
FOLIO = re.compile(r"^[^\w]*\d+[^\w]*$")
NOTA = re.compile(r"^(\d{1,3})\s+(.*)$", re.S)
def _lineas(pag):
    """Líneas de la página: dict(x0,x1,y0,y1,size,it,bold,t). Une las que comparten renglón."""
    d = pag.get_text("dict", flags=FLAGS)
    imgs = [fitz.Rect(b["bbox"]) for b in d["blocks"] if b["type"] == 1]
    area = pag.rect.width * pag.rect.height
    figuras = [r for r in imgs if r.width * r.height < 0.8 * area and r.width * r.height > 1500]
    crudas = []
    for b in d["blocks"]:
        if b["type"] != 0:
            continue
        for l in b["lines"]:
            sp = [s for s in l["spans"] if s["text"].strip()]
            if not sp:
                continue
            dom = max(sp, key=lambda s: len(s["text"]))
            crudas.append({"x0": l["bbox"][0], "x1": l["bbox"][2], "y0": l["bbox"][1], "y1": l["bbox"][3],
                           "size": dom["size"], "it": bool(dom["flags"] & 2),
                           "bold": "Bold" in dom["font"] and not dom["flags"] & 2,
                           "t": "".join(s["text"] for s in l["spans"]).strip()})
    crudas = [c for c in crudas if not any(r.contains(fitz.Point((c["x0"] + c["x1"]) / 2, (c["y0"] + c["y1"]) / 2))
                                           for r in figuras)]
    crudas.sort(key=lambda c: (round(c["y0"] / 3), c["x0"]))
    filas = []
    for c in crudas:
        if filas and abs(filas[-1][0]["y0"] - c["y0"]) < 3:
            filas[-1].append(c)
        else:
            filas.append([c])
    out = []
    for f in filas:
        f.sort(key=lambda c: c["x0"])
        if len(f) == 1:
            out.append(f[0])
            continue
        if len(f[0]["t"]) == 1 and f[0]["t"].isalpha() and f[0]["size"] >= 16:
            g = dict(f[1])
            g["t"] = f[0]["t"] + " ".join(c["t"] for c in f[1:])
            g["dropcap"] = True
            g["x1"] = max(c["x1"] for c in f)
            out.append(g)
            continue
        g = dict(f[0])
        g["t"] = " ".join(c["t"] for c in f)
        g["x1"] = max(c["x1"] for c in f)
        g["fila"] = [c["t"] for c in f]
        out.append(g)
    return out, figuras


VOCAB: set = set()


def _unir(a: str, b: str) -> str:
    if a.endswith("­"):
        return a[:-1] + b
    if a.endswith("-") and b[:1].islower() and not a.endswith(" -"):
        izq = re.search(r"[A-Za-z]+-$", a)
        der = re.match(r"[a-z]+", b)
        if izq and der and (izq.group(0)[:-1] + der.group(0)).lower() not in VOCAB:
            return a + b
        return a[:-1] + b
    return a + " " + b


def _titulo_legible(t: str) -> bool:
    """Un encabezado real son palabras con vocales y letras seguidas; las marcas del OCR de un sello no lo son."""
    toks = [w for w in re.findall(r"[A-Za-z]+", t)]
    if not toks:
        return False
    bien = sum(1 for w in toks if len(w) >= 2 and re.search(r"[aeiouAEIOU]", w) and not re.search(r"[bcdfgjkpqvwxz]{4}", w.lower()))
    return bien / len(toks) >= 0.6 and sum(len(w) for w in toks) / max(1, len(t.replace(" ", ""))) >= 0.5


def _es_voces(t: str) -> bool:
    letras = [c for c in t if c.isalpha()]
    return len(letras) >= 3 and sum(c.isupper() for c in letras) / len(letras) >= 0.88


def arreglar_voz(t: str) -> str:
    """Arreglos de la capa de texto en palabras en mayúsculas: 0→O y l→I entre letras mayúsculas."""
    t = re.sub(r"(?<=[A-Z])0(?=[A-Z0]|\b)", "O", t)
    t = re.sub(r"(?<=[A-Z])0(?=[A-Z])", "O", t)
    return re.sub(r"(?<=[A-Z])l(?=[A-Z])", "I", t)


def leer(pdf: str, desde: int, hasta: int, saltar: set):
    """[(n_pag, [elemento])] con elemento = ('h', nivel, texto) | ('p', [segmentos], it, marca) |
    ('img', data_uri) | ('nota', n, texto) | ('marca_pag',)."""
    doc = fitz.open(pdf)
    todas = []
    VOCAB.update(w.lower() for w in re.findall(r"[A-Za-z]+(?:-[A-Za-z]+)*", " ".join(p.get_text("text", flags=FLAGS) for p in doc)))
    for pag in doc:
        ls, _ = _lineas(pag)
        todas += [l for l in ls if l["size"] > 9 and l["size"] < 10 and len(l["t"]) > 40]
    pct = lambda xs, q: sorted(xs)[min(len(xs) - 1, int(q * len(xs)))] if xs else 0
    xr_doc = {it: pct([l["x1"] for l in todas if l["it"] == it], 0.9) for it in (True, False)}
    paginas = []
    for pag in doc:
        n = pag.number + 1
        if n < desde or n > hasta or n in saltar:
            continue
        H = pag.rect.height
        ls, figuras = _lineas(pag)
        cuerpo, notas = [], []
        izq = min([l["x0"] for l in ls if 9 < l["size"] < 10 and len(l["t"]) > 40] or [pag.rect.width * 0.2])
        marcas = {}
        for l in ls:
            if l["y1"] < 0.07 * H and l["size"] < 9:
                continue
            if l["y0"] > 0.88 * H and FOLIO.match(l["t"]):
                continue
            if l["size"] <= 8.3 and l["y0"] > 0.5 * H:
                notas.append(l)
                continue
            if MARCA.match(l["t"]) and l["x1"] < izq + 4:
                marcas[round(l["y0"] / 4)] = l["t"]
                continue
            cuerpo.append(l)
        els = []
        pitch = statistics.median([b["y0"] - a["y0"] for a, b in zip(cuerpo, cuerpo[1:])
                                   if 8 < b["y0"] - a["y0"] < 20] or [14.0])
        xr = {}
        for it in (True, False):
            v = [l["x1"] for l in cuerpo if l["it"] == it and 9 < l["size"] < 10 and len(l["t"]) > 55]
            xr[it] = max(v) if len(v) >= 4 else xr_doc[it]
        elementos = [("l", l) for l in cuerpo] + [("f", r) for r in figuras]
        elementos.sort(key=lambda e: e[1]["y0"] if e[0] == "l" else e[1].y0)
        actual = None
        previo = None
        for tipo, e in elementos:
            if tipo == "f":
                actual = None
                pix = pag.get_pixmap(clip=e, dpi=130)
                els.append(("img", "data:image/png;base64," + base64.b64encode(pix.tobytes("png")).decode()))
                previo = None
                continue
            l = e
            if l["size"] >= 10.3 and (l["bold"] or l["size"] >= 12):
                if not _titulo_legible(l["t"]):
                    continue
                niv = 1 if l["size"] >= 15 else 2 if l["size"] >= 12 else 3
                if len(l["t"]) == 1 and l["t"].isalpha() and l["size"] >= 16:
                    actual = ("cap", l["t"])
                    previo = None
                    continue
                if els and els[-1][0] == "h" and els[-1][1] == niv and previo and l["y0"] - previo["y1"] < 6:
                    els[-1] = ("h", niv, els[-1][2] + " " + l["t"])
                else:
                    els.append(("h", niv, l["t"]))
                actual, previo = None, l
                continue
            nueva = (previo is None or actual is None or l["it"] != previo["it"]
                     or l["y0"] - previo["y0"] > 1.25 * pitch or round(l["y0"] / 4) in marcas
                     or (previo["size"] >= 10.3))
            txt = l["t"]
            if isinstance(actual, tuple) and actual[0] == "cap":
                txt = actual[1] + txt
                actual = None
                nueva = True
                cap = True
            elif l.get("dropcap"):
                nueva, cap = True, True
            else:
                cap = False
            if nueva:
                actual = {"lineas": [], "it": l["it"], "marca": marcas.get(round(l["y0"] / 4), ""), "cap": cap}
                els.append(("p", actual))
            llena = l["x1"] >= xr[l["it"]] - TOL
            actual["lineas"].append((txt, llena, l.get("fila")))
            previo = l
        for l in notas:
            m = NOTA.match(l["t"])
            if m and (not l["x0"] > izq + 25):
                els.append(("nota", int(m.group(1)), m.group(2).strip()))
            elif els and els[-1][0] == "nota":
                els[-1] = ("nota", els[-1][1], _unir(els[-1][2], l["t"]))
        paginas.append((n, els))
    return paginas


def segmentos(lineas: list) -> list:
    """Une las líneas llenas; un corte tras una línea corta es duro. Devuelve [(texto, es_voces)]."""
    segs, cur = [], ""
    for i, (t, llena, fila) in enumerate(lineas):
        cur = _unir(cur, t) if cur else t
        if not llena or i == len(lineas) - 1:
            segs.append(cur)
            cur = ""
    return [(arreglar_voz(s) if _es_voces(s) else s, _es_voces(s)) for s in segs]


def aplanar(paginas: list) -> list:
    """Flujo continuo: [(n_pag, tipo, datos…)]. Un párrafo cuya última línea es llena y que cae al
    final de página continúa en la siguiente (si esa no abre con marca ni encabezado)."""
    flujo = []
    for n, els in paginas:
        notas = [e for e in els if e[0] == "nota"]
        for e in els:
            if e[0] == "nota":
                continue
            if e[0] == "p":
                p = e[1]
                segs = segmentos(p["lineas"])
                llena_final = p["lineas"][-1][1]
                flujo.append(["p", n, segs, p["it"], p["marca"], p["cap"], llena_final])
            elif e[0] == "h":
                flujo.append(["h", n, e[1], e[2]])
            else:
                flujo.append(["img", n, e[1]])
        for e in notas:
            flujo.append(["nota", n, e[1], e[2]])
    fusion = []
    for e in flujo:
        if (e[0] == "p" and fusion and fusion[-1][0] == "p" and fusion[-1][6] and fusion[-1][1] != e[1]
                and not e[4] and not e[5] and fusion[-1][3] == e[3]
                and not (fusion[-1][2] and fusion[-1][2][-1][1]) and e[2] and not e[2][0][1]):
            a, b = fusion[-1][2], e[2]
            a[-1] = (_unir(a[-1][0], b[0][0]), False)
            a.extend(b[1:])
            fusion[-1][6] = e[6]
            continue
        fusion.append(e)
    return fusion


def _minusculas_iniciales(t: str, voces: set) -> str:
    """«WITHIN THE WALLS of…» de una capitular: la corrida inicial de mayúsculas pasa a minúsculas."""
    toks = t.split(" ")
    i = 0
    while i < len(toks) and toks[i].strip(".,;:").isupper() and toks[i].strip(".,;:") not in voces:
        i += 1
    if i < 2:
        return t
    return " ".join([toks[0].capitalize()] + [x.lower() for x in toks[1:i]] + toks[i:])



class Traductor:
    def __init__(self, motor, modelo, glosario_ruta, razonamiento="medium", yes_cloud=False):
        import config
        import main as tr_main
        import transcache
        import remoto
        from intraducibles import Masker
        from translate import make_backend
        cfg = config.Config()
        cfg.backend, cfg.cloud_model, cfg.reasoning_effort = motor, modelo, razonamiento
        cfg.review_passes = 1
        cfg.book_type = "especializado"
        glos = tr_main.load_glossary(cfg.glossary_path)
        if glosario_ruta:
            glos += [t for t in tr_main.load_glossary(glosario_ruta) if t not in glos]
        self.cfg, self.tr_main = cfg, tr_main
        self.masker = Masker(glos, auto_detect=True, allcaps_min_len=3)
        if remoto.es_remoto(motor):
            remoto.exigir_consentimiento_nube("maquetar_versos", aceptado=yes_cloud)
        self.backend = make_backend(cfg)
        ok, msg = self.backend.available()
        if not ok:
            sys.exit(f"✗ motor no disponible: {msg}")
        self.cache = transcache.TranslationCache(cfg.trans_cache_path, cfg.cache_translations)
        self.sig = transcache.signature(cfg, glos) + "|versos-v1"
        self.lock = threading.Lock()
        self.fallos = []

    def traducir(self, texto: str) -> str:
        """Traduce con caché; las voces y los marcadores de nota ‹n› viajan como fichas intocables."""
        from translate import translate_and_review
        hit = self.cache.get(self.sig, texto)
        if hit is not None and not self.tr_main.bad_translation(texto, hit, self.cfg):
            return hit
        with self.lock:
            masked, mapping = self.masker.mask(texto)
        mapping = dict(mapping)

        def ficha(m):
            k = f"MWTKN9{int(m.group(1)):03d}"
            mapping[k] = f"‹{m.group(1)}›"
            return f" {k}"
        masked = re.sub(r"‹(\d+)›", ficha, masked)
        ultimo = None
        for _ in range(max(1, self.cfg.retries)):
            try:
                trad, perdidos, _p = translate_and_review(masked, mapping, self.backend, self.cfg.review_passes,
                                                          self.cfg.review_early_stop)
                if not perdidos and not self.tr_main.bad_translation(texto, trad, self.cfg):
                    trad = re.sub(r"\s+(‹)", r"\1", trad)
                    self.cache.set(self.sig, texto, trad)
                    return trad
                ultimo = f"perdidos={perdidos}" if perdidos else "salida inválida"
            except Exception as e:
                ultimo = repr(e)
        self.fallos.append((texto[:80], ultimo))
        return texto


def _marcar_notas(texto: str, numeros: set) -> str:
    """Los números de nota pegados a una palabra o a la puntuación pasan a ‹n›."""
    def g(m):
        nums = re.findall(r"\d+", m.group(2))
        if nums and all(int(k) in numeros for k in nums):
            return m.group(1) + "".join(f"‹{k}›" for k in nums) + (" " if m.group(2).endswith(" ") else "")
        return m.group(0)
    return re.sub(r"([A-Za-z.,;:!?”’)\"_])((?:\d{1,3}(?:\s|$|(?=[.,;:])))+)", g, texto)


def traducir_flujo(flujo: list, tr: Traductor, hilos: int, sin_traducir_desde: str | None, log=print) -> list:
    notas_pag = {}
    for e in flujo:
        if e[0] == "nota":
            notas_pag.setdefault(e[1], set()).add(e[2])
    tareas, literal = [], False
    for e in flujo:
        if e[0] == "h":
            if sin_traducir_desde and e[3].strip().lower().startswith(sin_traducir_desde.lower()):
                literal = True
            tareas.append((e, None, e[3]))
        elif e[0] == "p":
            nums = notas_pag.get(e[1], set())
            nuevas = []
            for i, (s, voz) in enumerate(e[2]):
                if voz or literal:
                    nuevas.append((s, None))
                    continue
                if i == 0 and e[5]:
                    s = _minusculas_iniciales(s, set())
                nuevas.append((s, _marcar_notas(s, nums) if nums else s))
            e[2] = nuevas
            tareas += [(e, k, t) for k, (s, t) in enumerate(nuevas) if t is not None]
        elif e[0] == "nota" and not literal:
            tareas.append((e, None, e[3]))
    log(f"  {len(tareas)} unidades a traducir")
    hechas = [0]

    def trabajo(t):
        trad = tr.traducir(t[2])
        hechas[0] += 1
        if hechas[0] % 25 == 0:
            log(f"  traducidas {hechas[0]}/{len(tareas)}")
        return t, trad

    with ThreadPoolExecutor(max_workers=hilos) as ex:
        for (e, k, _texto), trad in ex.map(trabajo, tareas):
            if k is None:
                e[3] = trad
            else:
                e[2][k] = (e[2][k][0], trad)
    for e in flujo:
        if e[0] == "p":
            e[2] = [t if t is not None else s for s, t in e[2]]
    return flujo



CSS = """
@page{ size:%(W)sin %(H)sin; margin:.72in .7in .8in .7in; }
*{ box-sizing:border-box; }
html{ background:#fff; }
body{ margin:0; font-family:'Palatino Linotype',Palatino,Georgia,serif; font-size:10.4pt; line-height:1.42; color:#111; }
h1{ font-size:19pt; text-align:center; font-weight:normal; letter-spacing:.04em; margin:2.2em 0 1em;
    break-before:page; page-break-before:always; }
h1.primero{ break-before:auto; page-break-before:auto; margin-top:0; }
h2{ font-size:13pt; text-align:center; margin:1.4em 0 .7em; font-weight:bold; break-after:avoid; }
h3{ font-size:10.8pt; text-align:center; margin:1.1em 0 .5em; font-weight:bold; letter-spacing:.03em; break-after:avoid; }
p{ margin:0 0 .6em; text-align:justify; hyphens:auto; -webkit-hyphens:auto; orphans:2; widows:2; }
p.cap::first-letter{ font-size:2.6em; float:left; line-height:.85; padding:.08em .08em 0 0; }
.it p{ text-align:left; hyphens:manual; }
.it{ font-style:italic; margin:0 1.4em; }
.verso{ margin:0 0 .7em 1.4em; break-inside:avoid; font-style:italic; }
.verso div{ margin:0; }
.item{ display:flex; gap:.9em; margin:0 0 .6em; }
.item .n{ flex:0 0 2.6em; text-align:right; }
.item .c{ flex:1; }
.nota{ font-size:8.3pt; line-height:1.3; margin:.1em 0 .6em 0; padding-top:.3em; border-top:.5pt solid #bbb; width:60%%; }
sup{ font-size:.68em; line-height:0; vertical-align:super; }
img.fig{ display:block; margin:.7em auto; max-width:100%%; max-height:46vh; }
.portada{ text-align:center; padding-top:30vh; break-after:page; page-break-after:always; }
.portada .t{ font-size:28pt; letter-spacing:.05em; margin-bottom:.4em; }
.portada .s{ font-style:italic; font-size:13pt; margin-bottom:2.2em; }
.portada .a{ font-size:13pt; }
.indice{ break-after:page; page-break-after:always; }
.indice .fila{ display:flex; align-items:baseline; margin:.45em 0; }
.indice .fila .p{ flex:1; border-bottom:1px dotted #888; margin:0 .4em; }
"""


def _esc(t: str) -> str:
    return re.sub(r"‹(\d+)›", r"<sup>\1</sup>", _html.escape(t, quote=False))


def construir(flujo: list, w_in: float, h_in: float, titulo: str, subtitulo: str, autor: str, toc: list) -> str:
    partes = []
    if titulo:
        partes.append(f"<section class='portada'><div class='t'>{_esc(titulo)}</div>"
                      f"<div class='s'>{_esc(subtitulo)}</div><div class='a'>{_esc(autor)}</div></section>")
    if toc:
        filas = "".join(f"<div class='fila'><span>{_esc(t)}</span><span class='p'></span><span>{n}</span></div>"
                        for t, n in toc)
        partes.append(f"<section class='indice'><h1 class='primero'>Índice</h1>{filas}</section>")
    primero = not partes
    for e in flujo:
        if e[0] == "h":
            cls = " class='primero'" if primero and e[2] == 1 else ""
            partes.append(f"<h{e[2]}{cls}>{_esc(e[3])}</h{e[2]}>")
            primero = False
        elif e[0] == "img":
            partes.append(f"<img class='fig' src='{_html.escape(e[2], quote=True)}' alt='figura'>")
        elif e[0] == "p":
            segs = e[2]
            if len(segs) == 1:
                txt = f"<p class='{'cap' if e[5] else ''}'>{_esc(segs[0])}</p>"
                txt = f"<div class='it'>{txt}</div>" if e[3] else txt
            else:
                txt = "<div class='verso'>" + "".join(f"<div>{_esc(s)}</div>" for s in segs) + "</div>"
            if e[4]:
                txt = f"<div class='item'><span class='n'>{_esc(e[4])}</span><div class='c'>{txt}</div></div>"
            partes.append(txt)
        elif e[0] == "nota":
            partes.append(f"<div class='nota'><b>{e[2]}.</b> {_esc(e[3])}</div>")
    return ("<!doctype html><html lang='es'><head><meta charset='utf-8'><title>libro</title>"
            f"<style>{CSS % {'W': w_in, 'H': h_in}}</style></head><body>" + "".join(partes) + "</body></html>")


def a_pdf(html_doc: str, salida: str) -> None:
    from render import imprimir_pdf
    tmp = os.path.splitext(salida)[0] + "_tmp.html"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(html_doc)
    try:
        imprimir_pdf(tmp, salida, timeout=900)
    finally:
        try:
            os.remove(tmp)
        except FileNotFoundError:
            pass


def numerar_indice(salida: str, titulos: list, desde: int) -> list:
    """[(titulo, pagina)] buscando cada título a partir de la página `desde` (1 = primera)."""
    doc = fitz.open(salida)
    res = []
    for t in titulos:
        pag = next((i for i in range(desde - 1, len(doc)) if doc[i].search_for(t)), None)
        res.append((t, (pag + 1) if pag is not None else 0))
        if pag is not None:
            desde = pag + 1
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pdf")
    ap.add_argument("salida")
    ap.add_argument("--glosario", default="")
    ap.add_argument("--titulo", default="")
    ap.add_argument("--subtitulo", default="")
    ap.add_argument("--autor", default="")
    ap.add_argument("--sin-traducir-desde", default="")
    ap.add_argument("--desde", type=int, default=1)
    ap.add_argument("--hasta", type=int, default=10 ** 6)
    ap.add_argument("--saltar", default="", help="páginas del original que se omiten (portada, índice original…)")
    ap.add_argument("--con-indice", action="store_true", help="índice nuevo con las páginas reales del PDF")
    ap.add_argument("--hilos", type=int, default=6)
    ap.add_argument("--motor", default="groq")
    ap.add_argument("--modelo", default="openai/gpt-oss-120b")
    ap.add_argument("--yes-cloud", action="store_true")
    ap.add_argument("--permitir-parciales", action="store_true")
    a = ap.parse_args()
    saltar = {int(x) for x in a.saltar.split(",") if x}
    flujo = aplanar(leer(a.pdf, a.desde, a.hasta, saltar))
    print(f"{len(flujo)} elementos")
    tr = Traductor(a.motor, a.modelo, a.glosario, yes_cloud=a.yes_cloud)
    traducir_flujo(flujo, tr, a.hilos, a.sin_traducir_desde or None)
    if tr.fallos:
        print(f"⚠ {len(tr.fallos)} unidades sin traducir bien (se dejan en origen):")
        for t, m in tr.fallos[:20]:
            print("   ", t, "→", m)
        if not a.permitir_parciales:
            raise SystemExit("✗ no se genera el PDF: hay unidades sin traducir; usa --permitir-parciales para continuar")
    d0 = fitz.open(a.pdf)
    w, h = d0[0].rect.width / 72, d0[0].rect.height / 72
    toc = []
    if a.con_indice:
        titulos = [e[3] for e in flujo if e[0] == "h" and e[2] == 1]
        toc = [(t, 0) for t in titulos]
    a_pdf(construir(flujo, w, h, a.titulo, a.subtitulo, a.autor, toc), a.salida)
    if toc:
        toc = numerar_indice(a.salida, [t for t, _ in toc], 3 if a.titulo else 2)
        a_pdf(construir(flujo, w, h, a.titulo, a.subtitulo, a.autor, toc), a.salida)
    print(f"✔ {a.salida}: {len(fitz.open(a.salida))} páginas")


if __name__ == "__main__":
    main()
