#!/usr/bin/env python3
"""Rehace, en el HTML solo-español de un libro con PDF nativo, las páginas que tienen tablas.

El traductor aplana las tablas: cada celda sale como una línea suelta y se pierde la rejilla. Aquí cada
página se reconstruye desde su estructura (find_tables de PyMuPDF): las tablas pasan a ser <table> reales con
cada celda traducida; el texto fuera de las tablas va en párrafos; las imágenes incrustadas se conservan;
todo en orden de lectura (por altura). Se descartan la cabecera y el pie que el navegador imprimió en cada
página y la barra de navegación del sitio. El hebreo en mojibake (cp1255 leído como Latin-1) se recupera
antes de traducir (pulir.segmentos_hebreo) y queda marcado <span dir="rtl" lang="he">.

La traducción de las filas se guarda en `<html>.tablas.json` (se puede repetir sin volver a pagar).
Las páginas rehechas llevan la clase `sin-figuras`: hojas.py no vuelve a pegarles figuras del original.

Uso: python herramientas/paginas_con_tablas.py origen.pdf libro_es.html [páginas|auto] [--glosario g.txt]
                                              [--modelo openai/gpt-oss-120b] [--hilos 6] [--aplicar]
  «auto» elige las páginas que tienen alguna tabla real. Sin --aplicar solo traduce y muestra el resultado.
"""
from __future__ import annotations

import argparse
import html as _html
import json
import os
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fitz
from bs4 import BeautifulSoup

import figuras
import config as _config
from main import bad_translation
import pulir
from render import escribir_atomico

SEP = " ¦ "
CON_LETRAS = re.compile(r"[A-Za-zÀ-ÿ]{3,}")
HEBREO = re.compile(r"[֐-׿]+(?:\s+[֐-׿]+)*")
NAVEGACION = ("Twilit Grotto", "Contents Prev")


def _limpio(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


def _dentro(b, bbox) -> bool:
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    return bbox[0] - 2 <= cx <= bbox[2] + 2 and bbox[1] - 2 <= cy <= bbox[3] + 2


def _recuperar_hebreo(t: str) -> str:
    """Las fichas en mojibake cp1255 pasan a hebreo real (orden lógico); el resto del texto no se toca."""
    return "".join(txt for _, txt in pulir.segmentos_hebreo(t))


def _celdas(fila: list[str]) -> list[str]:
    """Celdas de una fila con el hebreo recuperado. Una letra suelta en mojibake (cada letra del nombre en su
    celda) solo cuenta como hebreo si otra celda de la fila ya lo es."""
    celdas = [_recuperar_hebreo(c) for c in fila]
    if any(HEBREO.search(c) for c in celdas):
        celdas = [c.encode("cp1252").decode("cp1255") if re.fullmatch(r"[à-ú]", c) else c for c in celdas]
    return celdas


def paginas_con_tablas(doc) -> list[int]:
    out = []
    for i, pag in enumerate(doc, 1):
        for t in pag.find_tables().tables:
            filas = t.extract()
            texto = " ".join(c or "" for f in filas for c in f)
            if not any(n in texto for n in NAVEGACION) and len(filas) >= 2 and len(filas[0]) >= 2:
                out.append(i)
                break
    return out


def contenido(pag) -> list[tuple]:
    """[(y0, 'tabla', filas) | (y0, 'texto', str) | (y0, 'img', uri)] en orden de lectura."""
    tablas = []
    for t in pag.find_tables().tables:
        filas = [[_limpio(c) for c in f] for f in t.extract()]
        if any(n in " ".join(sum(filas, [])) for n in NAVEGACION):
            tablas.append((t.bbox, None))
        else:
            tablas.append((t.bbox, filas))
    items = [(bbox[1], "tabla", filas) for bbox, filas in tablas if filas]
    for b in pag.get_text("blocks"):
        if b[6] != 0 or any(_dentro(b, bbox) for bbox, _ in tablas):
            continue
        t = _limpio(b[4])
        if not t or t.startswith(("file:///", "Sample Author:")) or any(n in t for n in NAVEGACION):
            continue
        items.append((b[1], "texto", t))
    area = pag.rect.width * pag.rect.height
    for im in pag.get_image_info():
        r = fitz.Rect(im["bbox"]) & pag.rect
        if not r.is_empty and r.width * r.height >= figuras.MIN_IMG * area:
            items.append((r.y0, "img", figuras._png_uri(pag.get_pixmap(dpi=130, clip=r).tobytes("png"))))
    return sorted(items, key=lambda x: x[0])


def unidades(items: list[tuple]) -> list[str]:
    """Textos que hay que traducir: cada párrafo y cada fila de tabla (celdas unidas con ¦)."""
    out = []
    for _, tipo, v in items:
        if tipo == "texto":
            out.append(_recuperar_hebreo(v))
        elif tipo == "tabla":
            for fila in v:
                u = SEP.join(_celdas(fila))
                if CON_LETRAS.search(re.sub(r"[֐-׿]+", "", u)):
                    out.append(u)
    return out


def _traductor(glosario: str, modelo: str, yes_cloud: bool = False):
    import config
    import main as tr_main
    import remoto
    from translate import make_backend, translate_and_review
    cfg = config.Config()
    cfg.backend, cfg.cloud_model, cfg.reasoning_effort = "groq", modelo, "medium"
    cfg.review_passes, cfg.book_type = 1, "especializado"
    glos = tr_main.load_glossary(cfg.glossary_path)
    if glosario:
        glos += [t for t in tr_main.load_glossary(glosario) if t not in glos]
    masker = tr_main.make_masker(cfg, glos)
    if remoto.es_remoto(cfg.backend):
        remoto.exigir_consentimiento_nube("paginas_con_tablas", aceptado=yes_cloud)
    backend = make_backend(cfg)
    ok, msg = backend.available()
    if not ok:
        sys.exit(f"✗ motor no disponible: {msg}")

    def traducir(t: str) -> str:
        masked, mapping = masker.mask(t)
        es, _, _ = translate_and_review(masked, mapping, backend, cfg.review_passes, cfg.review_early_stop)
        return es.strip()
    return traducir


def traducir_unidades(textos: list[str], cache: dict, traducir, hilos: int) -> None:
    """Traduce los textos que faltan en `cache`; una fila de tabla debe volver con el mismo número de celdas."""
    pendientes = [t for t in dict.fromkeys(textos) if t not in cache]

    def una(t: str) -> tuple[str, str]:
        es = traducir(t)
        if SEP.strip() in t and es.count("¦") != t.count("¦"):
            celdas = [c.strip() for c in t.split("¦")]
            es = SEP.join(traducir(c) if CON_LETRAS.search(re.sub(r"[֐-׿]+", "", c)) else c for c in celdas)
        return t, es if es and not bad_translation(t, es, _config.Config()) else None
    with ThreadPoolExecutor(hilos) as ex:
        for k, (t, es) in enumerate(ex.map(una, pendientes), 1):
            if es is not None:
                cache[t] = es
            print(f"   traducido ({k}/{len(pendientes)}): {t[:60]!r}", flush=True)


def _hebreo_html(t: str) -> str:
    """Escapa el texto y envuelve cada tramo de hebreo en <span dir=rtl lang=he>."""
    out, i = [], 0
    for m in HEBREO.finditer(t):
        out.append(_html.escape(t[i:m.start()], quote=False))
        out.append(f"<span dir='rtl' lang='he'>{m.group(0)}</span>")
        i = m.end()
    out.append(_html.escape(t[i:], quote=False))
    return "".join(out)


def seccion(n: int, items: list[tuple], cache: dict) -> str:
    partes = [f"<div class='page-num'>Página {n}</div>"]
    for _, tipo, v in items:
        if tipo == "texto":
            u = _recuperar_hebreo(v)
            if not cache.get(u, "").strip():
                raise RuntimeError(f"falta traducción de la unidad de la página {n}")
            partes.append(f"<div class='solo'>{_hebreo_html(cache[u])}</div>")
        elif tipo == "img":
            partes.append(f"<figure><img src='{v}' alt='ilustración'></figure>")
        else:
            filas = []
            for fila in v:
                u = SEP.join(_celdas(fila))
                requiere_traduccion = bool(CON_LETRAS.search(re.sub(r"[֐-׿]+", "", u)))
                if requiere_traduccion and not cache.get(u, "").strip():
                    raise RuntimeError(f"falta traducción de una fila de la página {n}")
                celdas = cache[u].split("¦") if u in cache else _celdas(fila)
                if requiere_traduccion and len(celdas) != len(fila):
                    raise RuntimeError(f"traducción incompleta de una fila de la página {n}")
                filas.append("<tr>" + "".join(f"<td>{_hebreo_html(c.strip())}</td>" for c in celdas) + "</tr>")
            partes.append(f"<table class='tabla'><tbody>{''.join(filas)}</tbody></table>")
    return f"<section class='page sin-figuras'>{''.join(partes)}</section>"


def aplicar(html_ruta: str, nuevas: dict[int, str]) -> int:
    with open(html_ruta, encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    hechas = 0
    for sec in soup.select("section.page"):
        pn = sec.select_one(".page-num")
        m = re.search(r"\d+", pn.get_text()) if pn else None
        if m and int(m.group(0)) in nuevas:
            sec.replace_with(BeautifulSoup(nuevas[int(m.group(0))], "html.parser"))
            hechas += 1
    respaldo = html_ruta + ".antes_tablas"
    if not os.path.exists(respaldo):
        shutil.copy2(html_ruta, respaldo)
    escribir_atomico(html_ruta, str(soup))
    return hechas


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pdf")
    ap.add_argument("html")
    ap.add_argument("paginas", nargs="?", default="auto")
    ap.add_argument("--glosario", default="")
    ap.add_argument("--modelo", default="openai/gpt-oss-120b")
    ap.add_argument("--hilos", type=int, default=6)
    ap.add_argument("--aplicar", action="store_true")
    ap.add_argument("--yes-cloud", action="store_true")
    a = ap.parse_args()
    doc = fitz.open(a.pdf)
    if a.paginas == "auto":
        paginas = paginas_con_tablas(doc)
    else:
        paginas = []
        for p in a.paginas.split(","):
            x, _, y = p.partition("-")
            paginas += range(int(x), int(y or x) + 1)
    print(f"páginas con tabla: {paginas}")
    cache_ruta = a.html + ".tablas.json"
    cache = json.load(open(cache_ruta, encoding="utf-8")) if os.path.exists(cache_ruta) else {}
    contenidos = {n: contenido(doc[n - 1]) for n in paginas}
    textos = [u for its in contenidos.values() for u in unidades(its)]
    pendientes = [t for t in dict.fromkeys(textos) if t not in cache]
    print(f"{len(textos)} textos, {len(pendientes)} por traducir")
    if pendientes:
        traducir_unidades(textos, cache, _traductor(a.glosario, a.modelo, a.yes_cloud), a.hilos)
        escribir_atomico(cache_ruta, json.dumps(cache, ensure_ascii=False, indent=1))
    faltantes = [t for t in textos if not cache.get(t, "").strip()]
    if faltantes:
        raise SystemExit(f"✗ no se aplican tablas: {len(faltantes)} unidades sin traducción válida")
    nuevas = {n: seccion(n, its, cache) for n, its in contenidos.items()}
    if a.aplicar:
        print(f"✔ {aplicar(a.html, nuevas)} páginas rehechas en {a.html} (respaldo: {a.html}.antes_tablas)")


if __name__ == "__main__":
    main()
