"""Voces verificadas: control de las términos que no se traducen de una traducción.

El enmascarado (intraducibles.py) protege las voces del motor de traducción, pero un OCR sucio las
corrompe antes de llegar ahí (ZORKAMEL -> ZORKAMEI). Este módulo compara las voces de una
traducción con dos referencias:

  * el texto del libro, cuando tiene capa de texto limpia: toda voz de la traducción debe existir
    en el origen y ninguna del origen debe perderse;
  * la lista verificada (lexicons/voces_verificadas.json, cada voz con su fuente, más el corpus
    curado de pronunciación): sirve cuando el origen es un escaneo, para proponer la corrección
    de una voz que se parece a una verificada.

Una «voz» es una palabra en MAYÚSCULAS de 4 o más letras que no es un título corriente: se
descartan las del glosario común (STOPWORDS), los numerales romanos y las que aparecen también
en minúsculas dentro del mismo texto (PROSPERIDAD / prosperidad), salvo que estén verificadas.
Un nombre capitalizado (ZORKAMEL) no cuenta como minúscula: su forma en mayúsculas sigue siendo voz.
Las claves ignoran guiones, apóstrofos y mayúsculas, porque un renglón puede cortar la voz.

Uso: python voces.py traduccion.pdf [--origen libro_limpio.pdf] [--verificadas a.json b.json]
"""
from __future__ import annotations

import difflib
import json
import os
import re
import sys
from collections import Counter

from intraducibles import STOPWORDS, _is_roman
from lexicon import _norm

VERIFICADAS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lexicons", "voces_verificadas.json")
CURADO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lexicons", "terminos.json")

_VOZ = re.compile(r"(?<!\w)[A-Z][A-Z'’\-]{3,}(?!\w)")
_PALABRA = re.compile(r"(?<!\w)[A-Za-zÁÉÍÓÚÑáéíóúñ]{4,}(?!\w)")


def clave(voz: str) -> str:
    """Forma comparable de una voz: mayúsculas, sin guiones ni apóstrofos."""
    return re.sub(r"['’\-]", "", voz).upper()


def del_texto(texto: str, verificadas=()) -> Counter:
    """{clave: veces} de las voces del texto."""
    comunes = {w for w in _PALABRA.findall(texto) if w.islower()}
    ok = set(verificadas)
    c: Counter = Counter()
    for m in _VOZ.findall(texto):
        k = clave(m)
        if len(k) < 4 or _is_roman(k) or k in STOPWORDS:
            continue
        if k.lower() in comunes and k not in ok:
            continue
        c[k] += 1
    return c


def cargar(*rutas: str) -> set:
    """Claves de las listas verificadas: acepta {"voces": [{"voz"}]} y el corpus {"lexico": [{"original","translit"}]}."""
    out: set = set()
    for ruta in rutas:
        if not ruta or not os.path.exists(ruta):
            continue
        try:
            with open(ruta, encoding="utf-8") as f:
                datos = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        for e in datos.get("voces", []) + datos.get("lexico", []):
            for campo in (e.get("voz"), e.get("original"), e.get("translit")):
                n = _norm(campo)
                if re.fullmatch(r"[a-z'’\-]{4,}", n):
                    out.add(clave(n))
    return out


def sugerir(k: str, candidatas, minimo: float = 0.82):
    """La candidata más parecida a `k` si es única (la segunda queda al menos 0.04 más lejos)."""
    pares = sorted(((difflib.SequenceMatcher(None, k, c).ratio(), c) for c in candidatas if c != k), reverse=True)[:2]
    if not pares or pares[0][0] < minimo:
        return None
    if len(pares) == 2 and pares[0][0] - pares[1][0] < 0.04:
        return None
    return pares[0][1]


def revisar(traduccion: str, origen: str | None = None, verificadas=()) -> dict:
    """Informe de voces. Con `origen`, la referencia es su texto; sin él, solo la lista verificada.
    perdidas: voces del origen que faltan o aparecen menos veces · nuevas: {voz: sugerencia|None}
    que no están en la referencia · sin_verificar: voces del origen que ninguna lista respalda."""
    ver = set(verificadas)
    trad = del_texto(traduccion, ver)
    if origen is None:
        ref = Counter({k: 1 for k in ver})
        perdidas, sin_verificar = {}, []
    else:
        ref = del_texto(origen, ver)
        perdidas = {k: (n, trad.get(k, 0)) for k, n in ref.items() if trad.get(k, 0) < n}
        sin_verificar = sorted(k for k in ref if k not in ver)
    candidatas = set(ref) | ver
    nuevas = {k: sugerir(k, candidatas) for k in trad if k not in ref}
    return {"perdidas": perdidas, "nuevas": nuevas, "sin_verificar": sin_verificar,
            "voces": len(trad), "verificadas": sum(1 for k in trad if k in ver)}


def corregir(texto: str, cambios: dict) -> tuple[str, int]:
    """Reemplaza cada voz cuya clave está en `cambios` por el valor; devuelve (texto, reemplazos)."""
    n = 0

    def cambia(m):
        nonlocal n
        nuevo = cambios.get(clave(m.group(0)))
        if nuevo:
            n += 1
            return nuevo
        return m.group(0)
    return _VOZ.sub(cambia, texto), n


def _leer(ruta: str) -> str:
    if ruta.lower().endswith(".pdf"):
        import fitz
        return "\n".join(p.get_text() for p in fitz.open(ruta))
    with open(ruta, encoding="utf-8") as f:
        return f.read()


def main(argv: list) -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("traduccion")
    ap.add_argument("--origen")
    ap.add_argument("--verificadas", nargs="*", default=[VERIFICADAS, CURADO])
    a = ap.parse_args(argv)
    ver = cargar(*a.verificadas)
    r = revisar(_leer(a.traduccion), _leer(a.origen) if a.origen else None, ver)
    print(f"voces en la traducción: {r['voces']} (verificadas en lista: {r['verificadas']})")
    print(f"perdidas o con menos apariciones: {len(r['perdidas'])}")
    for k, (n, m) in sorted(r["perdidas"].items()):
        print(f"   {k}: origen {n}, traducción {m}")
    print(f"ausentes de la referencia: {len(r['nuevas'])}")
    for k, s in sorted(r["nuevas"].items()):
        print(f"   {k}" + (f"  ->  {s}" if s else ""))
    if a.origen:
        print(f"del libro sin respaldo en ninguna lista verificada: {len(r['sin_verificar'])}")


if __name__ == "__main__":
    main(sys.argv[1:])
