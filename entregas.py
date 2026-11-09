#!/usr/bin/env python3
"""Qué PDF se entrega por cada carpeta del taller: la lista de libros del flujo, en un archivo de texto.

Vive en el taller, no en el código: `<TRAB>/entregas.tsv`, una línea por libro, tres columnas separadas
por tabulador (o por dos o más espacios): carpeta · PDF de entrega · nombre para el tablero (opcional).
Un «-» como PDF dice que esa carpeta no es un libro (restos, arreglos puntuales) y el flujo la ignora.
Antes era un diccionario dentro de un script: para dar de alta un libro había que editar Python.

Uso:  entregas.py                              lista lo que hay
      entregas.py --alta CARPETA PDF [NOMBRE]   da de alta un libro (o corrige su línea si ya existe)
      entregas.py demo
"""
import os
import re
import sys

TRAB = os.environ.get("TRAB", os.path.expanduser("~/traductor/taller"))
ARCHIVO = "entregas.tsv"
CABECERA = ["# carpeta\tPDF de entrega (en la carpeta de entrega)\tnombre para el tablero (opcional)",
            "# Una línea por libro, columnas separadas por TABULADOR. «-» como PDF = esa carpeta no es un libro."]
SEP = re.compile(r"\t| {2,}")


def leer(trab=TRAB):
    """{carpeta: (PDF, o None si la carpeta está marcada con «-»; nombre bonito o None)}."""
    out = {}
    ruta = os.path.join(trab, ARCHIVO)
    if not os.path.exists(ruta):
        return out
    with open(ruta, encoding="utf-8") as fh:
        for linea in fh:
            linea = linea.strip()
            if not linea or linea.startswith("#"):
                continue
            partes = [p.strip() for p in SEP.split(linea)]
            if len(partes) < 2:
                continue
            pdf, nombre = partes[1], (partes[2] if len(partes) > 2 and partes[2] else None)
            out[partes[0]] = (None if pdf == "-" else pdf, nombre)
    return out


def alta(carpeta, pdf, nombre=None, trab=TRAB):
    """Añade la línea de un libro, o reemplaza la que ya tenía. Escribe por archivo nuevo: nadie lee a medias."""
    ruta = os.path.join(trab, ARCHIVO)
    lineas = open(ruta, encoding="utf-8").read().splitlines() if os.path.exists(ruta) else list(CABECERA)
    lineas = [l for l in lineas if l.startswith("#") or not l.strip() or SEP.split(l.strip())[0] != carpeta]
    lineas.append("\t".join([carpeta, pdf] + ([nombre] if nombre else [])))
    with open(ruta + ".nuevo", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lineas) + "\n")
    os.replace(ruta + ".nuevo", ruta)


def demo():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        alta("uno", "Uno_ES.pdf", "El Uno", trab=d)
        alta("dos", "Dos_ES.pdf", trab=d)
        alta("resto", "-", trab=d)
        alta("uno", "Uno_v2_ES.pdf", "El Uno, segunda", trab=d)
        with open(os.path.join(d, ARCHIVO), "a", encoding="utf-8") as fh:
            fh.write("tres   Tres_ES.pdf   Con espacios\n")
        e = leer(d)
        assert e["uno"] == ("Uno_v2_ES.pdf", "El Uno, segunda"), e
        assert e["dos"] == ("Dos_ES.pdf", None)
        assert e["resto"] == (None, None)
        assert e["tres"] == ("Tres_ES.pdf", "Con espacios")
        assert open(os.path.join(d, ARCHIVO), encoding="utf-8").read().count("uno\t") == 1
    print("demo OK · entregas.tsv se lee, se da de alta y se corrige")


if __name__ == "__main__":
    if "demo" in sys.argv:
        demo()
    elif "--alta" in sys.argv:
        a = sys.argv[sys.argv.index("--alta") + 1:]
        if len(a) < 2:
            sys.exit("uso: entregas.py --alta CARPETA PDF [NOMBRE]")
        alta(a[0], a[1], " ".join(a[2:]) or None)
        print(f"✔ {a[0]} → {a[1]}" + (f" ({' '.join(a[2:])})" if len(a) > 2 else ""))
    elif any(x in ("-h", "--help") for x in sys.argv[1:]):
        print(__doc__)
    else:
        for carpeta, (pdf, nombre) in sorted(leer().items()):
            print(f"{carpeta:26} {pdf or '-':50} {nombre or ''}")
