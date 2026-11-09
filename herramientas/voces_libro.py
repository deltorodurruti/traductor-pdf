#!/usr/bin/env python3
"""Lista las términos que no se traducen que el identificador reconoce en un libro, para revisarlas antes o después de traducir.

Por cada voz: veces, páginas, y su estado: «léxico» (ya conocida), «nueva» (se congelará tal cual y se aprenderá),
o «corregida ← original» (variante de OCR de una voz conocida; se usa la forma del léxico). Con --aprender, las nuevas
se guardan en lexicons/aprendidas.json para que el próximo libro las reconozca; con --glosario, las vuelca a un archivo
de texto que puedes pasar al traductor con --glosario-extra.

Uso: python herramientas/voces_libro.py libro.pdf [--aprender] [--glosario voces.txt] [--min 1]
"""
from __future__ import annotations

import argparse
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz

import lexicon
from intraducibles import Masker

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEXICOS = [os.path.join(RAIZ, "glossary.txt"), os.path.join(RAIZ, "lexicons", "terminos.json"),
           os.path.join(RAIZ, "lexicons", "voces_verificadas.json"), os.path.join(RAIZ, "lexicons", "aprendidas.json")]


def voces_de(pdf: str) -> tuple[dict, dict, dict]:
    """({voz: veces}, {voz: páginas}, {token original: forma corregida})."""
    m = Masker(glossary=[], auto_detect=False, detect_unknown=True, lexicon_paths=LEXICOS)
    veces: collections.Counter = collections.Counter()
    paginas: dict = collections.defaultdict(set)
    for i, pag in enumerate(fitz.open(pdf), 1):
        _, mapping = m.mask(pag.get_text())
        for term in mapping.values():
            if any("Ͱ" <= c <= "Ͽ" or "֐" <= c <= "׿" for c in term):
                continue
            veces[term] += 1
            paginas[term].add(i)
    return dict(veces), {k: sorted(v) for k, v in paginas.items()}, dict(m.correcciones)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pdf")
    ap.add_argument("--aprender", action="store_true", help="guardar las voces nuevas en lexicons/aprendidas.json")
    ap.add_argument("--glosario", default="", help="volcar todas las voces a este archivo (una por línea)")
    ap.add_argument("--min", type=int, default=1, help="veces mínimas para listar una voz")
    a = ap.parse_args()
    veces, paginas, correcciones = voces_de(a.pdf)
    m = Masker(glossary=[], auto_detect=False, detect_unknown=True, lexicon_paths=LEXICOS)
    corregidas = {v: k for k, v in correcciones.items()}
    print(f"{'voz':28} {'veces':>5}  estado           páginas")
    nuevas = []
    for voz, n in sorted(veces.items(), key=lambda kv: (-kv[1], kv[0])):
        if n < a.min:
            continue
        if voz in corregidas:
            estado = f"corregida ← {corregidas[voz]}"
        elif m._voz_conocida(voz) is not None:
            estado = "léxico"
        else:
            estado, nuevas = "nueva", nuevas + [voz]
        pags = ", ".join(map(str, paginas[voz][:8])) + ("…" if len(paginas[voz]) > 8 else "")
        print(f"{voz:28} {n:5}  {estado:16} {pags}")
    print(f"\n{len(veces)} voces distintas; {len(nuevas)} nuevas; {len(correcciones)} corregidas por OCR")
    if a.glosario:
        with open(a.glosario, "w", encoding="utf-8") as f:
            f.write("\n".join(sorted(veces)) + "\n")
        print(f"→ {a.glosario}")
    if a.aprender and nuevas:
        n = lexicon.remember(os.path.join(RAIZ, "lexicons", "aprendidas.json"),
                             [{"original": v, "translit": "", "es_cl": "", "auto": True, "fuente": os.path.basename(a.pdf),
                               "notas": "voz detectada por el identificador; verifica y fija es_cl"} for v in nuevas])
        print(f"→ {n} voces nuevas aprendidas")


if __name__ == "__main__":
    main()
