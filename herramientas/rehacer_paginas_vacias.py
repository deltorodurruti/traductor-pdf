#!/usr/bin/env python3
"""Rehace las páginas de un PDF traducido que quedaron sin texto (solo el encabezado «PÁGINA n»).

Para libros cuyo PDF traducido tiene la misma numeración que el original y cuyo original trae texto nativo:
detecta las páginas vacías (encabezado y nada más) cuya página original sí tiene texto, traduce ese texto con el motor
del traductor (por bloques; los versos conservan sus saltos de línea) y lo escribe bajo el encabezado.

Solo para obras que se puedan traducir (dominio público o propias). El texto traducido se guarda en
`<salida>.json` para no volver a pagar si se repite.

Uso: python herramientas/rehacer_paginas_vacias.py traducido.pdf original.pdf salida.pdf
                                                   [--glosario g.txt] [--modelo openai/gpt-oss-120b] [--solo 6,12]
"""
from __future__ import annotations

import argparse
import html as _html
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fitz
from render import escribir_atomico

ENCABEZADO = re.compile(r"P\s*Á\s*G\s*I\s*N\s*A\s+((?:\d\s*)+)", re.I)
CORRIDO = re.compile(r"^\s*(THE\s+PREFACE|[IVXL\d]+)\s*[\d.]*\s*$", re.I)
MIN_ORIGINAL = 150
MARGEN_X, ARRIBA, ABAJO = 34, 88, 34


def numero_de_pagina(pag) -> int | None:
    m = ENCABEZADO.search(pag.get_text())
    return int(re.sub(r"\s+", "", m.group(1))) if m else None


def paginas_vacias(traducido, original) -> list[tuple[int, int]]:
    """[(índice de página traducida, página original)]: solo encabezado en la traducción y texto en el original."""
    out = []
    for i, pag in enumerate(traducido):
        n = numero_de_pagina(pag)
        if n is None or not 1 <= n <= len(original):
            continue
        resto = ENCABEZADO.sub("", pag.get_text()).strip()
        if len(resto) < 20 and len(original[n - 1].get_text().strip()) >= MIN_ORIGINAL:
            out.append((i, n))
    return out


def bloques(pag) -> list[tuple[str, bool]]:
    """[(texto, es_verso)] de la página original en orden de lectura, sin el encabezado corrido."""
    out = []
    for b in pag.get_text("blocks"):
        if b[6] != 0:
            continue
        lineas = [l.strip() for l in b[4].splitlines() if l.strip()]
        if not lineas or (len(lineas) == 1 and CORRIDO.match(lineas[0])):
            continue
        medio = sum(len(l) for l in lineas) / len(lineas)
        verso = len(lineas) >= 3 and medio < 45
        out.append(("\n".join(lineas) if verso else re.sub(r"\s+", " ", " ".join(lineas)), verso))
    return out


def a_html(partes: list[tuple[str, bool]], trad: dict) -> str:
    out = []
    for texto, verso in partes:
        es = trad.get(texto, texto)
        cuerpo = "<br>".join(_html.escape(l) for l in es.splitlines()) if verso else _html.escape(es)
        out.append(f"<p class='{'v' if verso else ''}'>{cuerpo}</p>")
    return "".join(out)


CSS = ("body{font-family:serif;font-size:9pt;line-height:1.34;color:#16161a;}"
       "p{margin:0 0 .55em;text-align:justify;} p.v{text-align:left;margin-left:1.2em;}")


def escribir(pag, html: str) -> bool:
    r = fitz.Rect(MARGEN_X, ARRIBA, pag.rect.width - MARGEN_X, pag.rect.height - ABAJO)
    espacio, _ = pag.insert_htmlbox(r, html, css=CSS)
    return espacio >= 0


def guardar_pdf_atomico(doc, salida: str) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".rehacer-", suffix=".pdf", dir=os.path.dirname(os.path.abspath(salida)))
    os.close(fd)
    try:
        doc.save(tmp, garbage=4, deflate=True)
        os.replace(tmp, salida)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("traducido")
    ap.add_argument("original")
    ap.add_argument("salida")
    ap.add_argument("--glosario", default="")
    ap.add_argument("--modelo", default="openai/gpt-oss-120b")
    ap.add_argument("--solo", default="", help="páginas originales a rehacer, separadas por comas")
    ap.add_argument("--yes-cloud", action="store_true")
    a = ap.parse_args()
    tr, orig = fitz.open(a.traducido), fitz.open(a.original)
    vacias = paginas_vacias(tr, orig)
    if a.solo:
        quiero = {int(x) for x in a.solo.split(",")}
        vacias = [(i, n) for i, n in vacias if n in quiero]
    print(f"páginas vacías con texto en el original: {[n for _, n in vacias]}")
    cache_ruta = a.salida + ".json"
    trad = json.load(open(cache_ruta, encoding="utf-8")) if os.path.exists(cache_ruta) else {}
    por_pagina = {n: bloques(orig[n - 1]) for _, n in vacias}
    textos = [t for ps in por_pagina.values() for t, _ in ps]
    if any(t not in trad for t in textos):
        from traducir_in_situ import traducir_faltantes
        import remoto
        motor = "groq"
        if remoto.es_remoto(motor):
            remoto.exigir_consentimiento_nube("rehacer_paginas_vacias", aceptado=a.yes_cloud)
        traducir_faltantes(trad, textos, motor, a.modelo, a.glosario, aceptado=a.yes_cloud)
        escribir_atomico(cache_ruta, json.dumps(trad, ensure_ascii=False, indent=1))
    desbordan = []
    for i, n in vacias:
        if not escribir(tr[i], a_html(por_pagina[n], trad)):
            desbordan.append(n)
    if desbordan:
        print(f"✗ no se guarda el PDF: páginas que no caben {desbordan}", flush=True)
        return 1
    guardar_pdf_atomico(tr, a.salida)
    print(f"✔ {len(vacias)} páginas rehechas → {a.salida}" + (f"; no caben del todo: {desbordan}" if desbordan else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
