#!/usr/bin/env python3
"""Cuánto lleva traducido un libro, mirando el archivo en vez del registro.

El registro solo cuenta lo que la herramienta decide escribir; si está una hora en el mismo tramo,
no dice nada. Esto abre el HTML y cuenta los bloques que ya están en español, así que el porcentaje
es el de verdad aunque nadie escriba nada.

Lee en trozos (los HTML pasan del gigabyte por las imágenes incrustadas) y guarda el resultado en un
`.avance` junto al archivo, para que mirar el estado cada pocos segundos no vuelva a recorrerlo todo.

Uso:  avance.py libro_es.html [otro_es.html ...]
      avance.py --faltan libro_es.html        solo el número de bloques que siguen en inglés
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from completar_bloques import es_ingles

ABRE = re.compile(rb'<div class="(?:solo|col tgt)"')
B64 = re.compile(rb'src="data:[^"]*"')
TAG = re.compile(rb"<[^>]+>")
TROZO = 8 << 20


def hecho(p: bytes) -> bool:
    """Un bloque está hecho si ya no parece inglés, o si completar_bloques.py lo marcó como
    intraducible: se tradujo y sigue pareciendo inglés (una bibliografía, una lista de siglas).
    Sin la marca, ese bloque se pedía en cada pasada, con cada clave, para siempre."""
    if b"data-intraducible" in p[:300]:
        return True
    return not es_ingles(TAG.sub(b" ", p).decode("utf-8", "ignore"))


def cuenta(ruta):
    """(bloques, en español) recorriendo el archivo por trozos, sin cargarlo entero."""
    total = listos = 0
    resto = b""
    with open(ruta, "rb") as fh:
        while True:
            dato = fh.read(TROZO)
            if not dato:
                break
            dato = B64.sub(b"", resto + dato)
            cortes = [m.start() for m in ABRE.finditer(dato)]
            if not cortes:
                resto = dato[-4096:]
                continue
            resto, dato = dato[cortes[-1]:], dato[:cortes[-1]]
            partes = ABRE.split(dato)[1:]
            for p in partes:
                total += 1
                listos += hecho(p)
    if resto:
        for p in ABRE.split(B64.sub(b"", resto))[1:]:
            total += 1
            listos += hecho(p)
    return total, listos


def una(ruta):
    cache = ruta + ".avance"
    sello = str(os.path.getmtime(ruta))
    if os.path.exists(cache):
        try:
            viejo, total, listos = open(cache).read().split()
            if viejo == sello:
                return int(total), int(listos), True
        except ValueError:
            pass
    total, listos = cuenta(ruta)
    with open(cache, "w") as fh:
        fh.write(f"{sello} {total} {listos}")
    return total, listos, False


def faltan(ruta: str) -> int:
    """Cuántos bloques quedan en inglés. Para quien solo necesita ese número.

    Antes cada llamador parseaba la línea de texto a su manera: estado.sh por tabuladores y flujo.sh
    restando columnas con awk. Si cambiaba el formato, uno de los dos fallaba en silencio.
    """
    if not os.path.exists(ruta):
        return -1
    total, hechas, _ = una(ruta)
    return total - hechas


def main():
    rutas = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--faltan" in sys.argv:
        for r in rutas:
            print(faltan(r))
        return
    for r in rutas:
        if not os.path.exists(r):
            print(f"{os.path.basename(r)}\t—\tno está")
            continue
        total, listos, de_cache = una(r)
        pct = listos * 100 // max(total, 1)
        print(f"{os.path.basename(r)}\t{listos}\t{total}\t{pct}\t{'cache' if de_cache else 'recien'}")


if __name__ == "__main__":
    main()
