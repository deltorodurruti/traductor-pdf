#!/usr/bin/env python3
"""Revisa la calidad de uno o varios PDF traducidos, sin juez LLM (chequeos deterministas).

Cuenta, por PDF: bloques que siguen en inglés, bloques de basura de OCR (casi sin letras o de
letras sueltas) y encabezados que se repiten en muchas páginas. Es lo que conviene correr
después de maquetar y antes de dar un libro por terminado.

Uso: python herramientas/escanear_pdf.py libro1.pdf [libro2.pdf ...]
"""
from __future__ import annotations

import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fitz

from completar_bloques import es_ingles


def es_basura(texto: str) -> bool:
    """Poca proporción de letras, o casi todo son tokens de una letra."""
    tok = texto.split()
    letras = sum(c.isalpha() for c in texto) / max(1, len(texto))
    return letras < 0.55 or (len(tok) >= 6 and sum(len(t) == 1 for t in tok) / len(tok) > 0.45)


def escanear(ruta: str) -> dict:
    doc = fitz.open(ruta)
    ingles, basura, primeras, bloques = [], [], Counter(), 0
    for n, pag in enumerate(doc, 1):
        lineas = [l.strip() for l in pag.get_text().splitlines() if l.strip()]
        if lineas:
            primeras[re.sub(r"\d+", "#", lineas[0])[:40]] += 1
        for b in pag.get_text("blocks"):
            s = re.sub(r"\s+", " ", b[4]).strip()
            if len(s) < 30:
                continue
            bloques += 1
            if es_ingles(s):
                ingles.append((n, s[:90]))
            if es_basura(s):
                basura.append((n, s[:90]))
    cab = [(k, v) for k, v in primeras.most_common(3) if v >= max(5, 0.1 * len(doc))]
    return {"paginas": len(doc), "bloques": bloques, "ingles": ingles, "basura": basura, "encabezados": cab}


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for ruta in sys.argv[1:]:
        r = escanear(ruta)
        print(f"## {os.path.basename(ruta)} | págs {r['paginas']} | bloques {r['bloques']} | "
              f"en inglés {len(r['ingles'])} | basura {len(r['basura'])} | encabezado repetido: {r['encabezados']}")
        for n, s in r["ingles"][:3]:
            print(f"   EN  p{n}: {s}")
        for n, s in r["basura"][:3]:
            print(f"   BAS p{n}: {s}")


if __name__ == "__main__":
    main()
