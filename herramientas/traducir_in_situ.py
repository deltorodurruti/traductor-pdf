#!/usr/bin/env python3
"""Traduce un PDF con capa de texto sin rehacer su diseño: tablas, imágenes y escrituras especiales quedan donde están.

Sirve para guías cortas, formularios y tablas, donde reflujar el texto (main.py + hojas.py) destruiría el
diseño. El texto se extrae por párrafos (o por celda, en una tabla), se traduce y se vuelve a escribir en
el mismo sitio, con la misma fuente base 14, tamaño y color. Lo que no es texto traducible (símbolos,
escritura celeste, imágenes, líneas) no se toca.

Tres pasos, todos sobre un JSON {original: español} que se puede corregir a mano entre uno y otro:
  1. --extraer   crea o completa el JSON con cada texto del PDF (las traducciones ya dadas se conservan)
  2. --traducir  llena con el motor del traductor lo que siga vacío (usa --glosario para lo que no se traduce)
  3. (por defecto) escribe el PDF; sin traducción para un texto, lo deja en el idioma original y avisa
     En el JSON, «-» borra un texto sin escribir nada (cuando su traducción pasó a la línea anterior) y
     «\n» dentro de una traducción fuerza un salto de línea.

Uso: python herramientas/traducir_in_situ.py guia.pdf traducciones.json [salida.pdf]
         [--extraer] [--traducir [--motor groq] [--modelo openai/gpt-oss-120b] [--glosario g.txt]]
         [--saltar "Fuente1,Fuente2"] [--conservar "regex"]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz
import render

BASE14 = {"Times-Roman": "tiro", "Times-Bold": "tibo", "Times-Italic": "tiit", "Times-BoldItalic": "tibi",
          "Helvetica": "helv", "Helvetica-Bold": "hebo", "Helvetica-Oblique": "heit",
          "Helvetica-BoldOblique": "hebi", "Courier": "cour"}
SALTAR = {"Symbol", "ZapfDingbats", "Trebuchet-MS"}
GUIA = re.compile(r"^(.*?)\s*\.{4,}\s*(\S+)$")
SUPER = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
LATIN1_SUP = str.maketrans("⁰¹²³", "°¹²³")


@dataclass
class Linea:
    bbox: fitz.Rect
    texto: str
    fuente: str
    tam: float
    color: int
    y: float
    x: float
    viñeta: bool = False
    spans: list = field(default_factory=list)
    cola: str = ""
    punto: dict | None = None


@dataclass
class Unidad:
    lineas: list
    texto: str = ""

    @property
    def rect(self) -> fitz.Rect:
        r = fitz.Rect(self.lineas[0].bbox)
        for ln in self.lineas[1:]:
            r |= ln.bbox
        return r


def _fuente(nombre: str, flags: int) -> str:
    if nombre in BASE14:
        return BASE14[nombre]
    negrita, cursiva = bool(flags & 16), bool(flags & 2)
    sans = any(k in nombre for k in ("Helv", "Arial", "Sans", "Trebuchet", "Morpheus"))
    base = ("hebi" if cursiva else "hebo") if sans and negrita else ("heit" if cursiva else "helv") if sans else \
           ("tibi" if cursiva else "tibo") if negrita else ("tiit" if cursiva else "tiro")
    return base


def lineas(pag, saltar=SALTAR) -> list[Linea]:
    """Líneas con texto traducible de la página. Descarta duplicados exactos (texto superpuesto), une los
    trozos de una misma línea base y deja fuera las viñetas y las fuentes de `saltar`."""
    crudas = []
    for b in pag.get_text("dict")["blocks"]:
        if b["type"]:
            continue
        for ln in b["lines"]:
            utiles = [s for s in ln["spans"] if s["text"].strip() and s["font"] not in saltar]
            if not utiles:
                continue
            bullet = any(s["font"] in ("Symbol", "ZapfDingbats") and s["text"].strip() for s in ln["spans"])
            dom = max(utiles, key=lambda s: len(s["text"].strip()) * s["size"])
            texto = ""
            for s in utiles:
                t = s["text"]
                if (s["size"] < 0.75 * dom["size"] or s["flags"] & 1) and t.strip().isdigit():
                    t = t.strip().translate(SUPER)
                texto += t
            texto = re.sub(r"\s+", " ", texto).strip()
            if not texto:
                continue
            x0 = min(s["bbox"][0] for s in utiles)
            punto = next((s for s in ln["spans"] if s["font"] in ("Symbol", "ZapfDingbats") and s["text"].strip()), None)
            crudas.append(Linea(fitz.Rect(ln["bbox"]), texto, _fuente(dom["font"], dom["flags"]), dom["size"],
                                dom["color"], dom["origin"][1], x0, bullet, utiles, punto=punto))
    crudas = [l for l in crudas if not any(o is not l and l.texto in o.texto and len(l.texto) < len(o.texto)
                                           and (o.bbox + (-4, -1.5, 4, 1.5)).contains(l.bbox) for o in crudas)]
    out: list[Linea] = []
    for ln in sorted(crudas, key=lambda l: (round(l.y), l.x)):
        if any(o.texto == ln.texto and abs(o.y - ln.y) < 2 and abs(o.x - ln.x) < 2 for o in out):
            continue
        prev = out[-1] if out else None
        if (prev and abs(prev.y - ln.y) < 2 and 0 <= ln.x - prev.bbox.x1 < 0.4 * ln.tam
                and prev.fuente == ln.fuente and not ln.viñeta):
            prev.texto += ln.texto
            prev.bbox |= ln.bbox
            continue
        out.append(ln)
    for ln in out:
        m = GUIA.match(ln.texto)
        if m:
            ln.texto, ln.cola = m.group(1).strip(), m.group(2)
    return out


def unidades(lns: list[Linea]) -> list[Unidad]:
    """Agrupa las líneas en párrafos: una línea continúa el párrafo si el renglón anterior llegó hasta el
    margen derecho, tienen el mismo estilo, el mismo margen izquierdo y no hay hueco de más."""
    if not lns:
        return []
    derecha = max(l.bbox.x1 for l in lns if l.tam > 8)
    us: list[Unidad] = []
    for ln in sorted(lns, key=lambda l: (l.y, l.x)):
        u = us[-1] if us else None
        if u:
            p = u.lineas[-1]
            sigue = (not ln.viñeta and not ln.cola and not p.cola and p.fuente == ln.fuente and abs(p.tam - ln.tam) < 0.3 and p.color == ln.color
                     and 0 < ln.y - p.y <= 1.75 * ln.tam and abs(ln.x - p.x) < 4
                     and p.bbox.x1 >= derecha - 3.2 * p.tam)
            if sigue:
                u.lineas.append(ln)
                continue
        us.append(Unidad([ln]))
    for u in us:
        t = ""
        for ln in u.lineas:
            t = t + ln.texto if (not t or t.endswith("-")) else t + " " + ln.texto
        u.texto = t.strip()
    return us


def _tiene_letras(t: str) -> bool:
    return bool(re.search(r"[^\W\d_]{2,}", t))


def extraer(doc, saltar=SALTAR, conservar: str = "") -> list[tuple[int, Unidad]]:
    """[(página, unidad)] con texto traducible; `conservar` es una regex de los textos que se dejan como están."""
    cons = re.compile(conservar) if conservar else None
    return [(i, u) for i, pag in enumerate(doc) for u in unidades(lineas(pag, saltar))
            if _tiene_letras(u.texto) and not (cons and cons.search(u.texto))]


def _envolver(texto: str, fuente: str, tam: float, ancho: float) -> list[str]:
    out, actual = [], ""
    for palabra in texto.split(" "):
        prueba = (actual + " " + palabra).strip()
        if actual and fitz.get_text_length(prueba, fuente, tam) > ancho:
            out.append(actual)
            actual = palabra
        else:
            actual = prueba
    return out + [actual]


def _color(c: int) -> tuple:
    return ((c >> 16) & 255) / 255, ((c >> 8) & 255) / 255, (c & 255) / 255


def verticales(pag) -> list[tuple[float, float, float]]:
    """[(x, y0, y1)] de los bordes verticales de la página (líneas o rectángulos finos): las paredes de las celdas."""
    out = []
    for d in pag.get_drawings():
        for it in d["items"]:
            if it[0] == "re" and it[1].width < 1.5 and it[1].height > 6:
                out.append(((it[1].x0 + it[1].x1) / 2, it[1].y0, it[1].y1))
            elif it[0] == "l" and abs(it[1].x - it[2].x) < 0.5 and abs(it[1].y - it[2].y) > 6:
                out.append((it[1].x, min(it[1].y, it[2].y), max(it[1].y, it[2].y)))
    return out


def celda(u: Unidad, vert: list) -> tuple | None:
    """(borde izquierdo, borde derecho) de la celda que contiene una línea suelta, si está en una tabla."""
    ln0, r = u.lineas[0], u.rect
    cerca = [x for x, y0, y1 in vert if y0 <= r.y0 + 2 and y1 >= r.y1 - 2]
    izq = max([x for x in cerca if x <= ln0.x + 1], default=None)
    der = min([x for x in cerca if x >= r.x1 - 1], default=None)
    return (izq, der) if izq is not None and der is not None and der - izq < 260 else None


def escribir(pag, u: Unidad, es: str, limite_x: float, limite_y: float, dy: float = 0.0,
             cel: tuple | None = None, tope: float = 1.0, dibujar: bool = True) -> tuple[float, float]:
    """Escribe `es` en el lugar de `u`, `dy` más abajo. Devuelve (escala de letra, borde inferior usado).
    Una sola línea se achica hasta que quepa (a la celda, si está en una tabla; si no, hasta el margen),
    un párrafo se envuelve y se achica solo si no cabe a lo alto. Un texto centrado en su celda o en la
    página sigue centrado. `tope` limita la escala (misma letra para el mismo texto en todas las páginas);
    con dibujar=False solo calcula."""
    ln0 = u.lineas[0]
    es = es.translate(LATIN1_SUP)
    if es == "-":
        return 1.0, ln0.y + dy
    r = u.rect
    una = len(u.lineas) == 1
    paso = 1.17 * ln0.tam if una else (u.lineas[-1].y - ln0.y) / (len(u.lineas) - 1)
    col = lambda t, tam: _color(ln0.color) and fitz.get_text_length(t, ln0.fuente, tam)
    if "\n" in es:
        ls = es.split("\n")
        tam = ln0.tam
        while tam > 0.78 * ln0.tam and max(col(t, tam) for t in ls) > limite_x - ln0.x:
            tam -= 0.25
        for k, t in enumerate(ls):
            pag.insert_text((ln0.x, ln0.y + dy + k * paso), t, fontname=ln0.fuente, fontsize=tam,
                            color=_color(ln0.color))
        return tam / ln0.tam, ln0.y + dy + (len(ls) - 1) * paso + 0.25 * tam
    x0, x1, centrado = ln0.x, limite_x, False
    if una and cel:
        centrado = abs((ln0.x + r.x1) / 2 - (cel[0] + cel[1]) / 2) < 4
        x0, x1 = (cel[0] + 2.0, cel[1] - 2.0) if centrado else (ln0.x, cel[1] - 2.0)
    elif una:
        centrado = abs((ln0.x + r.x1) / 2 - pag.rect.width / 2) < 8
        if centrado:
            x0, x1 = ln0.x - 0.0, pag.rect.width - ln0.x
    ancho_max = x1 - x0
    escalas = [e for e in [1 - 0.025 * k for k in range(0, 11)] if e <= tope + 1e-9] or [tope]
    elegida = None
    if una:
        for e in [e for e in escalas if e >= (0.78 if cel else 0.92)]:
            if col(es, ln0.tam * e) <= ancho_max:
                elegida = (e, [es])
                break
    if elegida is None:
        for e in escalas:
            ls = _envolver(es, ln0.fuente, ln0.tam * e, ancho_max)
            elegida = (e, ls)
            if ln0.y + dy + paso * e * (len(ls) - 1) + 0.25 * ln0.tam * e <= limite_y:
                break
    escala, ls = elegida
    tam, pitch = ln0.tam * escala, paso * escala
    if dibujar and ln0.punto:
        tp = ln0.punto["size"]
        pag.draw_circle((ln0.punto["origin"][0] + 0.22 * tp, ln0.y + dy - 0.30 * tp), 0.17 * tp,
                        color=None, fill=_color(ln0.punto["color"]))
    for k, t in enumerate(ls if dibujar else []):
        x = ((x0 + x1) / 2 - col(t, tam) / 2) if centrado else x0
        pag.insert_text((x, ln0.y + dy + k * pitch), t, fontname=ln0.fuente, fontsize=tam, color=_color(ln0.color))
    return escala, ln0.y + dy + (len(ls) - 1) * pitch + 0.25 * tam


def aplicar(doc, pares: list, trad: dict, derecha_pag: float = 525.0, fondo_pag: float = 722.0) -> dict:
    """Reescribe el documento. `pares` viene de extraer(). Devuelve {'hechas', 'pendientes', 'reducidas'}.
    Un párrafo que traducido ocupa más que el original empuja hacia abajo al que le sigue (nunca hacia arriba)."""
    por_pag: dict = {}
    for i, u in pares:
        por_pag.setdefault(i, []).append(u)
    res = {"hechas": 0, "pendientes": [], "reducidas": [], "empujadas": 0}
    topes: dict = {}
    for i, us in por_pag.items():
        vert = verticales(doc[i])
        for u in us:
            es = trad.get(u.texto, "").strip()
            cel = celda(u, vert) if len(u.lineas) == 1 and es and es != "-" else None
            if cel:
                e, _ = escribir(doc[i], u, es, cel[1], fondo_pag, 0.0, cel, dibujar=False)
                k = (u.texto, round(u.lineas[0].tam, 1))
                topes[k] = min(topes.get(k, 1.0), e)
    for i, us in por_pag.items():
        pag = doc[i]
        listas = [(u, trad.get(u.texto, "").strip()) for u in us]
        for u, es in listas:
            if not es:
                res["pendientes"].append((i + 1, u.texto[:60]))
        hechas = sorted(((u, es) for u, es in listas if es), key=lambda t: (t[0].lineas[0].y, t[0].lineas[0].x))
        for u, _ in hechas:
            for ln in u.lineas:
                for s in ln.spans + ([ln.punto] if ln.punto else []):
                    pag.add_redact_annot(fitz.Rect(s["bbox"]) + (-0.3, -0.3, 0.3, 0.3), fill=False)
        pag.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)
        vert = verticales(pag)
        imagenes = [fitz.Rect(im["bbox"]) for im in pag.get_image_info() if fitz.Rect(im["bbox"]).height > 60]
        escritas: list = []
        for u, es in hechas:
            if es == "-":
                res["hechas"] += 1
                continue
            r, ln0 = u.rect, u.lineas[0]
            cel = celda(u, vert) if len(u.lineas) == 1 else None
            lim_x = min([o.rect.x0 - 4 for o in us if o is not u and o.rect.x0 > r.x1 - 1
                         and o.rect.y0 < r.y1 and o.rect.y1 > r.y0] + [max(derecha_pag, r.x1)])
            lim_y = min([im.y0 - 4 for im in imagenes if im.y0 >= r.y1 - 1 and im.x0 < r.x1 and im.x1 > r.x0]
                        + [fondo_pag])
            arriba = ln0.y - 0.8 * ln0.tam
            dy = max([0.0] + [b - arriba + 0.8 * ln0.tam for x0, x1, b in escritas if x0 < r.x1 and x1 > r.x0
                              and b > arriba and b < ln0.y + ln0.tam])
            if dy:
                res["empujadas"] += 1
            e, fondo = escribir(pag, u, es, lim_x, max(lim_y, ln0.y + dy), dy, cel, topes.get((u.texto, round(ln0.tam, 1)), 1.0) if cel else 1.0)
            escritas.append((r.x0, r.x1, fondo))
            res["hechas"] += 1
            if e < 0.999:
                res["reducidas"].append((i + 1, round(e, 2), u.texto[:40]))
    return res


def traducir_faltantes(trad: dict, textos: list, motor: str, modelo: str, glosario: str,
                       aceptado: bool = False) -> int:
    import config
    import main as tr_main
    import remoto
    from translate import make_backend, translate_and_review
    cfg = config.Config()
    cfg.backend, cfg.cloud_model, cfg.reasoning_effort = motor, modelo, "medium"
    cfg.review_passes, cfg.book_type = 1, "especializado"
    glos = tr_main.load_glossary(cfg.glossary_path)
    if glosario:
        glos += [t for t in tr_main.load_glossary(glosario) if t not in glos]
    masker = tr_main.make_masker(cfg, glos)
    if remoto.es_remoto(motor):
        remoto.exigir_consentimiento_nube("traducir_in_situ", aceptado=aceptado)
    backend = make_backend(cfg)
    ok, msg = backend.available()
    if not ok:
        sys.exit(f"✗ motor no disponible: {msg}")
    n = 0
    for t in textos:
        if trad.get(t, "").strip():
            continue
        masked, mapping = masker.mask(t)
        es, _perdidos, _pasadas = translate_and_review(masked, mapping, backend, cfg.review_passes,
                                                       cfg.review_early_stop)
        trad[t] = es.strip()
        n += 1
        print(f"   traducido ({n}): {t[:50]!r}", flush=True)
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pdf")
    ap.add_argument("json")
    ap.add_argument("salida", nargs="?")
    ap.add_argument("--extraer", action="store_true")
    ap.add_argument("--traducir", action="store_true")
    ap.add_argument("--motor", default="groq")
    ap.add_argument("--modelo", default="openai/gpt-oss-120b")
    ap.add_argument("--glosario", default="")
    ap.add_argument("--saltar", default="")
    ap.add_argument("--conservar", default="", help="regex de los textos que se dejan sin traducir")
    ap.add_argument("--yes-cloud", action="store_true")
    a = ap.parse_args()
    saltar = SALTAR | {x for x in a.saltar.split(",") if x}
    doc = fitz.open(a.pdf)
    pares = extraer(doc, saltar, a.conservar)
    if os.path.exists(a.json):
        with open(a.json, encoding="utf-8") as f:
            trad = json.load(f)
    else:
        trad = {}
    textos = list(dict.fromkeys(u.texto for _, u in pares))
    if a.extraer or a.traducir:
        for t in textos:
            trad.setdefault(t, "")
    if a.traducir:
        traducir_faltantes(trad, textos, a.motor, a.modelo, a.glosario, aceptado=a.yes_cloud)
    if a.extraer or a.traducir:
        render.escribir_atomico(a.json, json.dumps(trad, ensure_ascii=False, indent=1))
        print(f"{len(textos)} textos distintos, {sum(1 for t in textos if trad.get(t, '').strip())} con traducción → {a.json}")
        if not a.salida:
            return
    if not a.salida:
        sys.exit("falta el PDF de salida (o usa --extraer / --traducir)")
    res = aplicar(doc, pares, trad)
    directorio = os.path.dirname(os.path.abspath(a.salida))
    fd, temporal = tempfile.mkstemp(prefix="." + os.path.basename(a.salida) + ".", suffix=".tmp", dir=directorio)
    os.close(fd)
    try:
        doc.save(temporal, garbage=3, deflate=True)
        os.replace(temporal, a.salida)
    except BaseException:
        try:
            os.remove(temporal)
        except OSError:
            pass
        raise
    print(f"{res['hechas']} textos escritos; {len(res['pendientes'])} sin traducción; "
          f"{len(res['reducidas'])} con letra reducida; {res['empujadas']} empujadas → {a.salida}")
    for p in res["pendientes"][:10]:
        print("   pendiente:", p)
    for r in res["reducidas"][:10]:
        print("   reducida:", r)


if __name__ == "__main__":
    main()
