#!/usr/bin/env python3
"""Convierte un libro traducido en markdown a PDF (A4, Georgia 9,5 pt) con Chrome.

Para las traducciones que se escriben o se corrigen a mano en markdown (no pasan por el HTML del
traductor). Las imágenes se resuelven respecto a la carpeta del markdown: `![](_figuras/x.png)`.
El interlineado por defecto (1,45) reproduce el aspecto de los libros ya maquetados; con 1,3
salen menos páginas.

Uso: python herramientas/md_a_pdf.py libro.md salida.pdf [interlineado]
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CSS = """
@page { size: A4; margin: 14mm 15mm; }
body { font-family: Georgia,'Times New Roman',serif; font-size: 9.5pt; line-height: %s; color:#16161a; margin:0; }
h1 { font-size:16pt; line-height:1.2; margin:1.1em 0 .5em; border-bottom:1.5px solid #888; padding-bottom:3px; }
h2 { font-size:12pt; margin:1em 0 .4em; } h3 { font-size:10.3pt; margin:.9em 0 .3em; } h4 { font-size:9.8pt; margin:.8em 0 .3em; }
p { margin:0 0 .55em; text-align:justify; hyphens:auto; }
blockquote { margin:.5em 0 .6em 0; padding:.1em .9em; border-left:2px solid #999; color:#333; }
hr { border:0; border-top:1px solid #bbb; margin:1em 0; }
ul, ol { margin:.3em 0 .6em 1.3em; padding:0; } li { margin:0 0 .25em; }
table { border-collapse:collapse; margin:.5em 0; } td, th { border:1px solid #999; padding:2px 6px; font-size:9pt; }
img { display:block; margin:.5em auto .15em; max-width:70%%; max-height:95mm; }
img[alt^='Portada'], img[alt^='Durero'] { max-width:100%%; max-height:210mm; }
p > em:only-child { display:block; text-align:center; font-size:8.5pt; color:#444; margin-bottom:.7em; }
"""


def convertir(md_ruta: str, pdf_ruta: str, interlineado: str = "1.45") -> int:
    import markdown
    from render import imprimir_pdf
    md_ruta, pdf_ruta = os.path.abspath(md_ruta), os.path.abspath(pdf_ruta)
    cuerpo = markdown.markdown(open(md_ruta, encoding="utf-8").read(), extensions=["extra", "sane_lists"])
    tmp = os.path.join(os.path.dirname(md_ruta), "." + os.path.basename(pdf_ruta) + ".tmp.html")
    open(tmp, "w", encoding="utf-8").write(
        f'<!doctype html><html lang="es"><head><meta charset="utf-8"><style>{CSS % interlineado}</style></head>'
        f"<body>{cuerpo}</body></html>")
    try:
        imprimir_pdf(tmp, pdf_ruta, timeout=300)
    finally:
        os.remove(tmp)
    import fitz
    return len(fitz.open(pdf_ruta))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    print(convertir(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "1.45"), "páginas")
