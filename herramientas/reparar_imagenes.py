#!/usr/bin/env python3
"""Repone en un PDF traducido las imágenes dañadas (negras, invertidas o sin canal alfa) con las del original.

Cuando una figura incrustada tiene transparencia (máscara alfa) y se extrae sin ella, sale negra o invertida.
Aquí cada imagen del PDF traducido se empareja con una imagen incrustada del original por su forma (mismo
alto/ancho, a cualquier escala: el traductor las reduce) y se reemplaza por el render de la página original
sobre fondo blanco, que sí respeta la máscara. No toca el resto del PDF: la imagen conserva su sitio y su tamaño.

Una imagen se empareja con la primera del original (en orden de página) que no se haya usado y tenga la misma
proporción (tolerancia 3 %). Las imágenes que no encuentran pareja se dejan como están y se listan.

Uso: python herramientas/reparar_imagenes.py traducido.pdf original.pdf salida.pdf [--dpi 150]
"""
from __future__ import annotations

import argparse
import re
import sys
import os
import tempfile

import fitz

TOL = 0.03
MIN_LADO = 40


def guardar_pdf_atomico(doc, salida: str) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".reparar-", suffix=".pdf", dir=os.path.dirname(os.path.abspath(salida)))
    os.close(fd)
    try:
        doc.save(tmp, garbage=4, deflate=True, clean=True)
        os.replace(tmp, salida)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def imagenes_original(doc) -> list[dict]:
    """Imágenes incrustadas del original, en orden de página: página, xref, tamaño nativo y recuadro."""
    out = []
    for i, pag in enumerate(doc):
        for x in pag.get_images(full=True):
            xref, w, h = x[0], x[2], x[3]
            rects = pag.get_image_rects(xref)
            if min(w, h) >= MIN_LADO and rects:
                out.append({"pag": i, "xref": xref, "w": w, "h": h, "rect": rects[0]})
    return out


def emparejar(tr: list[tuple], fuente: list[dict]) -> dict[int, dict]:
    """{xref de la traducción: imagen del original}. `tr` = [(xref, w, h)] sin repetir xref."""
    usadas: set[int] = set()
    pares: dict[int, dict] = {}
    for xref, w, h in tr:
        if min(w, h) < MIN_LADO:
            continue
        mejor, dif = None, TOL
        for k, f in enumerate(fuente):
            if k in usadas:
                continue
            d = abs((f["w"] / f["h"]) / (w / h) - 1)
            if d < dif or (mejor is None and d <= TOL):
                mejor, dif = k, d
                if d < 1e-3:
                    break
        if mejor is not None:
            usadas.add(mejor)
            pares[xref] = fuente[mejor]
    return pares


def podar_recursos(doc) -> int:
    """replace_image deja la imagen vieja referenciada en los recursos de la página: se quita la que el contenido no usa."""
    quitadas = 0
    for pag in doc:
        contenido = b"".join(doc.xref_stream(c) or b"" for c in pag.get_contents())
        usados = set(re.findall(rb"/([^\s/]+)\s+Do", contenido))
        for x in pag.get_images(full=True):
            if x[7].encode() not in usados:
                doc.xref_set_key(pag.xref, "Resources/XObject/" + x[7], "null")
                quitadas += 1
    return quitadas


def reparar(traducido: str, original: str, salida: str, dpi: int = 150) -> tuple[int, list]:
    tr_doc, or_doc = fitz.open(traducido), fitz.open(original)
    fuente = imagenes_original(or_doc)
    vistas: dict[int, tuple] = {}
    for pag in tr_doc:
        for x in pag.get_images(full=True):
            vistas.setdefault(x[0], (x[0], x[2], x[3]))
    pares = emparejar(list(vistas.values()), fuente)
    hechas = 0
    for xref, f in pares.items():
        pag_or = or_doc[f["pag"]]
        pix = pag_or.get_pixmap(dpi=dpi, clip=f["rect"] & pag_or.rect, alpha=False)
        for pag in tr_doc:
            if any(x[0] == xref for x in pag.get_images(full=True)):
                pag.replace_image(xref, pixmap=pix)
                hechas += 1
                break
    sin_pareja = [(x, vistas[x][1], vistas[x][2]) for x in vistas if x not in pares and min(vistas[x][1:]) >= MIN_LADO]
    podar_recursos(tr_doc)
    guardar_pdf_atomico(tr_doc, salida)
    return hechas, sin_pareja


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("traducido")
    ap.add_argument("original")
    ap.add_argument("salida")
    ap.add_argument("--dpi", type=int, default=150)
    a = ap.parse_args()
    n, sin = reparar(a.traducido, a.original, a.salida, a.dpi)
    print(f"{n} imágenes repuestas desde el original → {a.salida}")
    if sin:
        print(f"{len(sin)} sin pareja (se dejan como están): {sin}")


if __name__ == "__main__":
    sys.exit(main())
