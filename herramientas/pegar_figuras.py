#!/usr/bin/env python3
"""Pega en un PDF traducido las figuras del original que no están (sin traducir: se pegan tal cual).

Usa la auditoría (auditar_imagenes.py) para saber qué figuras faltan. Las dudosas se vuelven a comparar con un
criterio más flojo, para no pegar dos veces una figura que sí está. Cada página del original con figuras
perdidas pasa a una página nueva, con un pie en español («Figura de la pág. N del original»), colocada justo
después de la página traducida que más se le parece. Si el PDF traducido y el original tienen las mismas páginas,
la correspondencia es directa; si no, se busca por los nombres propios y las cifras que comparten (valen en
cualquier idioma) dentro de una ventana alrededor de la posición proporcional.

Uso: python herramientas/pegar_figuras.py fuente.pdf traducido.pdf salida.pdf [carpeta_cache] [--umbral 14]
"""
from __future__ import annotations

import argparse
import io
import math
import os
import re
import sys
import tempfile
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fitz

import auditar_imagenes as A

VENTANA = 0.10
PIE = "Figura de la pág. {n} del original"
MARGEN = 36


def guardar_pdf_atomico(doc, salida: str) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".figuras-", suffix=".pdf", dir=os.path.dirname(os.path.abspath(salida)))
    os.close(fd)
    try:
        doc.save(tmp, garbage=4, deflate=True)
        os.replace(tmp, salida)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def fichas(texto: str) -> set[str]:
    """Nombres propios y cifras: sobreviven a la traducción."""
    return {w.lower() for w in re.findall(r"\b[A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ'’-]{3,}\b|\b\d{2,4}\b", texto)}


def pagina_destino(sp: int, n_src: int, tokens_src: set, tokens_tr: list[set], idf: dict) -> int:
    """Índice (0-based) de la página traducida tras la que va la figura de la página `sp` (1-based) del original."""
    n_tr = len(tokens_tr)
    if n_src == n_tr:
        return sp - 1
    esperado = (sp - 0.5) / n_src * n_tr
    ventana = max(8, int(VENTANA * n_tr))
    a, b = max(0, int(esperado) - ventana), min(n_tr, int(esperado) + ventana + 1)
    mejor, puntos = None, 0.0
    for i in range(a, b):
        p = sum(idf.get(t, 0) for t in tokens_src & tokens_tr[i])
        if p > puntos:
            mejor, puntos = i, p
    return mejor if mejor is not None else min(n_tr - 1, int(esperado))


def celdas(figs: list[dict], w: float, h: float) -> list[fitz.Rect]:
    """Un recuadro por figura: en columna si son pocas; si son muchas, la cuadrícula que las deje más grandes."""
    area_w, area_h, y0 = w - 2 * MARGEN, h - 2 * MARGEN - 16, MARGEN + 16
    mejor, total = None, -1.0
    for cols in range(1, len(figs) + 1):
        filas = math.ceil(len(figs) / cols)
        cw, ch = area_w / cols, area_h / filas
        t = sum(min(cw / f["im"].width, ch / f["im"].height, 1.6) ** 2 * f["im"].width * f["im"].height for f in figs)
        if t > total:
            mejor, total = cols, t
    cols = mejor
    filas = math.ceil(len(figs) / cols)
    cw, ch = area_w / cols, area_h / filas
    out = []
    for k, f in enumerate(figs):
        esc = min((cw - 6) / f["im"].width, (ch - 6) / f["im"].height, 1.6)
        ancho, alto = f["im"].width * esc, f["im"].height * esc
        cx, cy = MARGEN + (k % cols) * cw + cw / 2, y0 + (k // cols) * ch + ch / 2
        out.append(fitz.Rect(cx - ancho / 2, cy - alto / 2, cx + ancho / 2, cy + alto / 2))
    return out


def segunda_vista(perdidas: list[dict], trad: list[dict]) -> list[dict]:
    """Criterio más flojo para las dudosas: si alguna imagen de la traducción se les parece, no se pegan."""
    reales = [t for t in trad if not t["vacia"]]
    flojas = []
    inl, razon = A.INLIERS, A.RAZON
    A.INLIERS, A.RAZON = 10, 0.25
    try:
        for p in perdidas:
            if not any(A.misma_figura(p, t) for t in reales):
                flojas.append(p)
    finally:
        A.INLIERS, A.RAZON = inl, razon
    return flojas


def pegar(fuente: str, traducido: str, salida: str, cache: str = "", umbral: int = A.UMBRAL) -> dict:
    f = A.de_fuente_cacheada(fuente, cache)
    texto = [x for x in f if x["ingles"]]
    f = [x for x in f if not x["ingles"]]
    t = A.de_traduccion(traducido)
    perdidas, _, _ = A.comparar(f, t, umbral)
    perdidas = segunda_vista(perdidas, t)
    doc, src = fitz.open(traducido), fitz.open(fuente)
    por_pagina: dict[int, list[dict]] = {}
    for p in perdidas:
        por_pagina.setdefault(p["pag"], []).append(p)
    if not por_pagina:
        guardar_pdf_atomico(doc, salida)
        return {"pegadas": 0, "paginas": [], "texto_ingles": len(texto)}
    tok_src = {sp: fichas(src[sp - 1].get_text()) for sp in por_pagina}
    tok_tr = [fichas(p.get_text()) for p in doc]
    df = Counter(w for s in tok_tr for w in s)
    idf = {w: math.log(1 + len(tok_tr) / c) for w, c in df.items()}
    destinos = {sp: pagina_destino(sp, len(src), tok_src[sp], tok_tr, idf) for sp in por_pagina}
    for sp in sorted(por_pagina, key=lambda s: (destinos[s], s), reverse=True):
        vecina = doc[destinos[sp]]
        w, h = vecina.rect.width, vecina.rect.height
        pag = doc.new_page(destinos[sp] + 1, width=w, height=h)
        figs = sorted(por_pagina[sp], key=lambda x: x["im"].size[1], reverse=True) if len(por_pagina[sp]) <= 3 \
            else por_pagina[sp]
        pag.insert_text((MARGEN, MARGEN), PIE.format(n=sp), fontname="heit", fontsize=9, color=(.3, .3, .3))
        for x, rect in zip(figs, celdas(figs, w, h)):
            im = x["im"].convert("RGB")
            buf = io.BytesIO()
            im.save(buf, "PNG")
            pag.insert_image(rect, stream=buf.getvalue())
    guardar_pdf_atomico(doc, salida)
    return {"pegadas": len(perdidas), "paginas": sorted(por_pagina), "texto_ingles": len(texto)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("fuente")
    ap.add_argument("traducido")
    ap.add_argument("salida")
    ap.add_argument("cache", nargs="?", default="")
    ap.add_argument("--umbral", type=int, default=A.UMBRAL)
    a = ap.parse_args()
    r = pegar(a.fuente, a.traducido, a.salida, a.cache, a.umbral)
    print(f"{r['pegadas']} figuras pegadas desde las págs. {r['paginas']} del original → {a.salida}")


if __name__ == "__main__":
    main()
