#!/usr/bin/env python3
"""Cuántos párrafos tiene de verdad cada página del original, leyéndolo del propio PDF.

El HTML traducido guarda la página entera en un bloque y marca los saltos con <br/>, sin distinguir
el salto que abre párrafo del que solo parte una línea. Hasta ahora eso se adivinaba por la forma del
texto. Aquí se mira el original: la **sangría** de la primera línea y el **hueco** respecto al
interlineado normal dicen dónde empieza un párrafo sin tener que suponer nada.

Uso:  estructura.py libro.pdf [página]      cuenta los párrafos y enseña el reparto
"""
from __future__ import annotations

import statistics
import re
import sys


def _lineas(pagina) -> list[tuple[float, float, str]]:
    """(x de inicio, y, texto) de cada línea con texto, en orden de lectura."""
    out = []
    for b in pagina.get_text("dict")["blocks"]:
        if b["type"] != 0:
            continue
        for l in b["lines"]:
            txt = "".join(s["text"] for s in l["spans"]).strip()
            if txt:
                out.append((l["bbox"][0], l["bbox"][1], txt))
    out.sort(key=lambda t: (round(t[1], 1), t[0]))
    return out


def inicios(pagina, holgura_x: float = 5.0, factor_y: float = 1.45) -> list[int]:
    """Índices de las líneas que abren párrafo en esta página del original.

    Dos señales, las mismas que usa cualquier libro impreso:
      · la primera línea del párrafo va **sangrada** respecto al margen común;
      · o hay un **hueco** mayor que el interlineado normal justo encima.
    Se miden contra la mediana de la propia página, así que da igual el cuerpo de letra o el margen.
    """
    lineas = _lineas(pagina)
    if len(lineas) < 3:
        return [0] if lineas else []
    margen = statistics.median(x for x, _, _ in lineas)
    saltos = [b[1] - a[1] for a, b in zip(lineas, lineas[1:]) if 0 < b[1] - a[1] < 200]
    interlineado = statistics.median(saltos) if saltos else 0
    marcas = [0]
    for i in range(1, len(lineas)):
        x, y, _ = lineas[i]
        hueco = y - lineas[i - 1][1]
        if x > margen + holgura_x or (interlineado and hueco > interlineado * factor_y):
            marcas.append(i)
    return marcas


def parrafos_por_pagina(pdf_path: str) -> dict[int, int]:
    """{nº de página (desde 1): cuántos párrafos tiene} para todo el original."""
    import fitz
    doc = fitz.open(pdf_path)
    return {i + 1: len(inicios(p)) for i, p in enumerate(doc)}


def titulos_desde_pdf(pdf_path: str) -> list[dict]:
    """Recupera líneas de título usando el tamaño, negrita y posición del original.

    Devuelve registros pequeños y serializables: ``nivel``, ``texto``, ``pagina`` y ``y``.
    El cuerpo se calibra con la mediana global, de modo que una página escaneada o una portada no
    cambie los umbrales de las páginas de texto.
    """
    import fitz

    doc = fitz.open(pdf_path)
    try:
        lineas = []
        por_pagina = []
        for pno, pagina in enumerate(doc, 1):
            filas = []
            for bloque in pagina.get_text("dict").get("blocks", []):
                if bloque.get("type") != 0:
                    continue
                for linea in bloque.get("lines", []):
                    spans = [s for s in linea.get("spans", []) if s.get("text", "").strip()]
                    if not spans:
                        continue
                    texto = "".join(s["text"] for s in spans).strip()
                    fila = {
                        "texto": texto,
                        "pagina": pno,
                        "x": float(linea["bbox"][0]),
                        "y": float(linea["bbox"][1]),
                        "y1": float(linea["bbox"][3]),
                        "tam": max(float(s.get("size", 0)) for s in spans),
                        "negrita": any((s.get("flags", 0) & 16) or "Bold" in s.get("font", "")
                                       for s in spans),
                    }
                    filas.append(fila)
                    lineas.append(fila)
            filas.sort(key=lambda x: (round(x["y"], 1), x["x"]))
            por_pagina.append(filas)
        if not lineas:
            return []
        cuerpo = statistics.median(x["tam"] for x in lineas)
        encontrados = []
        numerado = re.compile(r"^\d+[.)]\s+\S")
        for filas in por_pagina:
            if not filas:
                continue
            saltos = [b["y"] - a["y"] for a, b in zip(filas, filas[1:]) if b["y"] > a["y"]]
            paso = statistics.median(saltos) if saltos else 0
            for i, fila in enumerate(filas):
                anterior = filas[i - 1] if i else None
                hueco = fila["y"] - anterior["y1"] if anterior else fila["y"]
                corto = len(fila["texto"]) <= 100
                grande = fila["tam"] >= cuerpo * 1.6 and corto
                sub = (fila["negrita"] and corto and i > 0
                       and not fila["texto"].endswith((".", ",", ";")))
                entrada = bool(numerado.match(fila["texto"])) and corto
                separado = bool(paso and hueco >= paso * 1.25)
                if grande:
                    nivel = 1
                elif entrada and (separado or fila["negrita"]):
                    nivel = 3
                elif sub and (separado or ":" in fila["texto"] or entrada or fila["tam"] >= cuerpo * 1.05):
                    nivel = 2
                else:
                    continue
                encontrados.append({"nivel": nivel, "texto": fila["texto"], "pagina": fila["pagina"],
                                    "y": fila["y"], "tam": fila["tam"], "negrita": fila["negrita"]})
        agrupados = []
        for item in encontrados:
            if (agrupados and item["nivel"] == agrupados[-1]["nivel"] == 1
                    and item["pagina"] == agrupados[-1]["pagina"]
                    and item["y"] - agrupados[-1]["y"] < 2.5 * max(cuerpo, 1)):
                agrupados[-1]["texto"] += " " + item["texto"]
            else:
                agrupados.append(item)
        return agrupados
    finally:
        doc.close()


def demo() -> None:
    """Autocomprobación: una página inventada con dos párrafos sangrados debe dar dos."""
    import fitz
    doc = fitz.open()
    pag = doc.new_page(width=400, height=300)
    pag.insert_text((60, 50), "Primera linea del primer parrafo", fontsize=10)
    pag.insert_text((40, 64), "segunda linea del mismo parrafo", fontsize=10)
    pag.insert_text((40, 78), "tercera linea del mismo parrafo", fontsize=10)
    pag.insert_text((60, 92), "Primera linea del segundo parrafo", fontsize=10)
    pag.insert_text((40, 106), "segunda linea del segundo", fontsize=10)
    marcas = inicios(pag)
    assert marcas == [0, 3], marcas
    print("demo OK · dos párrafos detectados por la sangría:", marcas)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        demo()
    elif len(sys.argv) > 1:
        import fitz
        d = fitz.open(sys.argv[1])
        if len(sys.argv) > 2:
            n = int(sys.argv[2])
            ls = _lineas(d[n - 1])
            marcas = set(inicios(d[n - 1]))
            print(f"página {n}: {len(marcas)} párrafos de {len(ls)} líneas\n")
            for i, (x, y, t) in enumerate(ls):
                print(f"  {'¶' if i in marcas else ' '} {t[:68]}")
        else:
            cuenta = parrafos_por_pagina(sys.argv[1])
            print(f"{len(cuenta)} páginas · {sum(cuenta.values())} párrafos en total")
            print("  primeras:", dict(list(cuenta.items())[:12]))
    else:
        print(__doc__)
