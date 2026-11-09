#!/usr/bin/env python3
"""Coteja un libro traducido con su original sin ningún modelo de lenguaje (cero tokens).

Alinea cada página del original con la página traducida que más nombres propios y cifras comparte
(sobreviven a la traducción) y revisa, página por página:
  * cifras y nombres del original que no aparecen en la traducción (posible omisión o nombre cambiado);
  * oraciones con dos o más de esas fichas de las que no aparece ninguna (posible oración omitida);
  * páginas del original sin ninguna página traducida parecida (posible página perdida);
  * voces del glosario (términos que no se traducen, nombres propios) que el original trae y la traducción no conserva;
  * y en la traducción: bloques que siguen en inglés, basura de OCR, encabezados repetidos y hojas vacías.
Las figuras no se cotejan aquí (auditar_imagenes.py). Un original escaneado sin capa de texto se lee con
Tesseract (local) y el texto queda en caché junto al informe.

Uso: python herramientas/auditar_fidelidad.py original.pdf traducido.pdf informe.json [--glosario g.txt]
"""
from __future__ import annotations

import argparse
import difflib
import json
import math
import os
import re
import sys
import unicodedata
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz

from escanear_pdf import escanear

VENTANA = 0.08
MIN_PAG = 200
MIN_FALTAN = 3
CIFRA = re.compile(r"(?<![\d.,])\d{2,4}(?![\d.,])")
NOMBRE = re.compile(r"\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{3,}\b")
PALABRA = re.compile(r"[a-z]{4,}")
ENCABEZADO = re.compile(r"P\s*Á\s*G\s*I\s*N\s*A\s+((?:\d\s*)+)", re.I)
FIN_ORACION = ".!?:;\"“”'([«"
PARECIDO = 0.72
_DICC: set[str] | None = None


def plano(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def diccionario() -> set[str]:
    """Palabras comunes del inglés: las que el diccionario del sistema escribe en minúscula (los nombres van con mayúscula)."""
    global _DICC
    if _DICC is None:
        try:
            with open("/usr/share/dict/words", encoding="utf-8", errors="ignore") as f:
                _DICC = {w.strip() for w in f if w.strip().islower()}
        except OSError:
            _DICC = set()
    return _DICC


GUION_FIN_LINEA = re.compile(r"[\u2010\u2011\u00ad-]\n")


def desguionar(t: str) -> str:
    """Une la palabra que el maquetado parte con guion al final de línea («inter-⏎nacional» → «internacional»)."""
    return GUION_FIN_LINEA.sub("", t)


def ocr_tesseract(png: bytes, lang: str = "eng") -> str:
    """Tesseract por línea de comandos (sin pytesseract: su import arrastra pandas/pyarrow, que falla con numpy 2)."""
    import shutil
    import subprocess
    import tempfile
    exe = shutil.which("tesseract") or "/usr/local/bin/tesseract"
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(png)
    try:
        r = subprocess.run([exe, f.name, "-", "-l", lang], capture_output=True, text=True, timeout=120)
        return r.stdout
    finally:
        os.unlink(f.name)


def textos(pdf: str, cache: str) -> list[str]:
    """Texto de cada página; un escaneo sin capa de texto pasa por Tesseract y se guarda en `cache`."""
    doc = fitz.open(pdf)
    out = [desguionar(p.get_text()) for p in doc]
    if len(doc) and sum(map(len, out)) / len(doc) >= 50:
        return out
    if os.path.exists(cache):
        return json.load(open(cache, encoding="utf-8"))
    out = [desguionar(ocr_tesseract(p.get_pixmap(dpi=200).tobytes("png"))) for p in doc]
    json.dump(out, open(cache, "w", encoding="utf-8"), ensure_ascii=False)
    return out


def nombres_propios(paginas: list[str]) -> set[str]:
    """Palabras con mayúscula que no son del diccionario y aparecen alguna vez en medio de una oración:
    nombres propios, no inicios de frase ni sustantivos que el inglés antiguo escribe con mayúscula."""
    c: Counter = Counter()
    dicc = diccionario()
    for t in paginas:
        for m in NOMBRE.finditer(t):
            prev = t[:m.start()].rstrip()[-1:]
            if prev and prev not in FIN_ORACION and m.group(0).lower() not in dicc:
                c[m.group(0)] += 1
    return set(c)


def fichas(t: str, nombres: set[str]) -> set[str]:
    return set(CIFRA.findall(t)) | {w for w in NOMBRE.findall(t) if w in nombres}


def encabezados(trad: list[str]) -> list[int | None]:
    """Número «PÁGINA n» impreso al inicio de cada página traducida (None si no lo hay)."""
    out = []
    for t in trad:
        m = ENCABEZADO.search(t[:200])
        out.append(int(re.sub(r"\s+", "", m.group(1))) if m else None)
    return out


def alinear(orig: list[str], trad: list[str]) -> list[tuple[int, float]]:
    """Para cada página del original: (índice de la página traducida que le corresponde, puntaje).
    Misma cantidad de páginas → una a una. Si la traducción trae encabezados «PÁGINA n» que concuerdan con el
    contenido, mandan los encabezados. Si no, gana la página que más nombres y cifras comparte."""
    n_o, n_t = len(orig), len(trad)
    if n_o == n_t:
        return [(p, 1.0) for p in range(n_o)]
    contenido = _alinear_contenido(orig, trad)
    por_num: dict[int, int] = {}
    for i, n in enumerate(encabezados(trad)):
        if n and 1 <= n <= n_o:
            por_num.setdefault(n, i)
    if len(por_num) >= 0.6 * n_t:
        pares = [(por_num[p + 1], q) for p, (q, s) in enumerate(contenido) if s > 0 and p + 1 in por_num]
        if pares and sum(abs(a - b) <= 1 for a, b in pares) >= 0.6 * len(pares):
            return [(por_num[p + 1], 1.0) if p + 1 in por_num else contenido[p] for p in range(n_o)]
    return contenido


def _esperados(fos: list[set], tok_tr: list[set], idf: dict, n_o: int, n_t: int) -> list[int]:
    """Posición esperada de cada página del original en la traducción: interpolación entre anclas (páginas que
    comparten al menos dos fichas con una sola página traducida, de forma inequívoca, y van en orden creciente).
    Sin anclas, la posición proporcional. Así da igual que las hojas extra estén al final o repartidas."""
    anclas = []
    for p, fo in enumerate(fos):
        if len(fo) < 3:
            continue
        mejores = sorted(((sum(idf.get(w, 0) for w in fo & s), len(fo & s), i) for i, s in enumerate(tok_tr)), reverse=True)
        if mejores and mejores[0][1] >= 2 and (len(mejores) < 2 or mejores[0][0] >= 2 * mejores[1][0]):
            anclas.append((p, mejores[0][2]))
    largo, antes = [1] * len(anclas), [-1] * len(anclas)
    for a in range(len(anclas)):
        for b in range(a):
            if anclas[b][1] < anclas[a][1] and largo[b] + 1 > largo[a]:
                largo[a], antes[a] = largo[b] + 1, b
    cadena = []
    if anclas:
        k = max(range(len(anclas)), key=largo.__getitem__)
        while k != -1:
            cadena.append(anclas[k])
            k = antes[k]
        cadena.reverse()
    xs = [-1] + [p for p, _ in cadena] + [n_o]
    ys = [-1] + [i for _, i in cadena] + [n_t]
    out, k = [], 0
    for p in range(n_o):
        while xs[k + 1] < p:
            k += 1
        e = ys[k] + (ys[k + 1] - ys[k]) * (p - xs[k]) / max(1, xs[k + 1] - xs[k])
        out.append(min(n_t - 1, max(0, int(round(e)))))
    return out


def _alinear_contenido(orig: list[str], trad: list[str]) -> list[tuple[int, float]]:
    """Mejor camino creciente (las páginas van en orden) que maximiza los nombres y cifras compartidos;
    cada página del original solo mira una banda alrededor de su posición proporcional."""
    tok_tr = [set(CIFRA.findall(t)) | {plano(w) for w in NOMBRE.findall(t)} for t in trad]
    df = Counter(w for s in tok_tr for w in s)
    idf = {w: math.log(1 + len(tok_tr) / c) for w, c in df.items()}
    n_o, n_t = len(orig), len(trad)
    ventana = max(6, int(VENTANA * n_t))
    fos = [set(CIFRA.findall(t)) | {plano(w) for w in NOMBRE.findall(t)} for t in orig]
    esperados = _esperados(fos, tok_tr, idf, n_o, n_t)
    inicio, crudo, puntos = [], [], []
    for p, fo in enumerate(fos):
        esperado = esperados[p]
        a, b = max(0, esperado - ventana), min(n_t, esperado + ventana + 1)
        fila_c, fila_p = [], []
        for i in range(a, b):
            d = abs(i - esperado) / (ventana + 1)
            s = sum(idf.get(w, 0) for w in fo & tok_tr[i])
            fila_c.append(s)
            fila_p.append(s * (1 - 0.5 * d) + 1e-6 * (1 - d))
        inicio.append(a)
        crudo.append(fila_c)
        puntos.append(fila_p)
    acum, atras = [puntos[0][:]], [[None] * len(puntos[0])]
    for p in range(1, n_o):
        pa, prev, a = inicio[p - 1], acum[-1], inicio[p]
        cur, back, mejor, mejor_i, k = [], [], float("-inf"), None, 0
        for j, s in enumerate(puntos[p]):
            while k < len(prev) and pa + k <= a + j:
                if prev[k] > mejor:
                    mejor, mejor_i = prev[k], pa + k
                k += 1
            cur.append(s + (mejor if mejor_i is not None else 0.0))
            back.append(mejor_i)
        acum.append(cur)
        atras.append(back)
    out: list = [None] * n_o
    j = max(range(len(acum[-1])), key=acum[-1].__getitem__)
    i = inicio[-1] + j
    for p in range(n_o - 1, -1, -1):
        out[p] = (i, crudo[p][i - inicio[p]])
        i = atras[p][i - inicio[p]] if atras[p][i - inicio[p]] is not None else i
    return out


def _voces_json(ruta: str) -> list[str]:
    """Voces de un léxico JSON: lista «voces» de {voz, fuente} o diccionario «lexico»."""
    d = json.load(open(ruta, encoding="utf-8"))
    if isinstance(d, dict):
        d = d.get("voces", d.get("lexico", [k for k in d if not k.startswith("_")]))
    if isinstance(d, dict):
        d = list(d)
    return [x.get("voz", "") if isinstance(x, dict) else str(x) for x in d]


def cargar_glosario(rutas: list[str]) -> tuple[dict[str, str], list[str]]:
    """({voz en minúscula: voz}, voces de varias palabras), de los archivos que existan (.txt o .json)."""
    uni, multi = {}, []
    for r in rutas:
        if not r or not os.path.exists(r):
            continue
        if r.endswith(".json"):
            voces = _voces_json(r)
        else:
            voces = [linea.split("#")[0].strip() for linea in open(r, encoding="utf-8")]
        for v in voces:
            if len(v) < 4:
                continue
            (multi.append(v) if " " in v else uni.setdefault(v.lower(), v))
    return uni, multi


def cotejar(orig: list[str], trad: list[str], glos_uni: dict[str, str], glos_multi: list[str]) -> dict:
    conservados = {plano(w) for t in trad for w in NOMBRE.findall(t)}
    nombres = {n for n in nombres_propios(orig) if plano(n) in conservados}
    ali = alinear(orig, trad)
    todo = plano(" ".join(trad))
    inf: dict = {"omisiones": [], "sin_correspondencia": [], "voces": [], "paginas_cotejadas": 0}
    for p, t in enumerate(orig):
        if len(t.strip()) < MIN_PAG:
            continue
        inf["paginas_cotejadas"] += 1
        q, puntos = ali[p]
        ventana_txt = " ".join(trad[max(0, q - 1): q + 2])
        w_plano = plano(ventana_txt)
        w_tokens = set(PALABRA.findall(w_plano))
        fo = fichas(t, nombres)
        cifras = {c for c in fo if c.isdigit()}
        if puntos == 0 and len(fo) >= 3:
            inf["sin_correspondencia"].append(p + 1)
            continue
        faltan = {c for c in cifras if not re.search(r"(?<!\d)" + c + r"(?!\d)", w_plano)}
        faltan |= {n for n in fo - cifras
                   if plano(n) not in w_tokens and not difflib.get_close_matches(plano(n), w_tokens, n=1, cutoff=PARECIDO)}
        oraciones = []
        for o in re.split(r"(?<=[.!?])\s+", t):
            f = fichas(o, nombres)
            if len(f) >= 2 and f <= faltan:
                oraciones.append(re.sub(r"\s+", " ", o)[:140])
        if len(faltan) >= MIN_FALTAN or oraciones:
            del_libro = sorted(c for c in faltan & cifras
                               if len(c) >= 3 and not re.search(r"(?<!\d)" + c + r"(?!\d)", todo))
            inf["omisiones"].append({"pag": p + 1, "trad": q + 1, "faltan": sorted(faltan), "oraciones": oraciones,
                                     "ausentes_del_libro": del_libro})
        palabras = {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z'-]{3,}", t)}
        presentes = [glos_uni[w] for w in palabras if w in glos_uni] + [g for g in glos_multi if g in t]
        perdidas = sorted(g for g in presentes if g.lower() not in ventana_txt.lower())
        if perdidas:
            inf["voces"].append({"pag": p + 1, "voces": perdidas})
    return inf


def hojas_vacias(pdf: str) -> list[int]:
    doc = fitz.open(pdf)
    return [i + 1 for i, p in enumerate(doc) if len(p.get_text().strip()) < 20 and not p.get_images()]


def auditar(original: str, traducido: str, informe: str, glosarios: list[str]) -> dict:
    orig = textos(original, informe + ".ocr.json")
    trad = textos(traducido, informe + ".ocr_trad.json")
    inf = cotejar(orig, trad, *cargar_glosario(glosarios))
    esc = escanear(traducido)
    basura = [b for b in esc["basura"]
              if sum(c.isdigit() for c in b[1]) < 0.3 * len(b[1]) and not ENCABEZADO.search(b[1])]
    inf.update({"original": original, "traducido": traducido, "paginas_original": len(orig),
                "paginas_traduccion": len(trad), "hojas_vacias": hojas_vacias(traducido),
                "ingles": esc["ingles"], "basura": basura, "encabezados": esc["encabezados"]})
    json.dump(inf, open(informe, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return inf


def resumen(inf: dict) -> str:
    oraciones = sum(len(o["oraciones"]) for o in inf["omisiones"])
    graves = sum(1 for o in inf["omisiones"] if o.get("ausentes_del_libro"))
    return (f"{os.path.basename(inf['traducido'])}: {inf['paginas_original']} págs. orig / {inf['paginas_traduccion']} trad · "
            f"{inf['paginas_cotejadas']} cotejadas · {len(inf['sin_correspondencia'])} sin correspondencia · "
            f"{len(inf['omisiones'])} págs. con fichas ausentes ({oraciones} oraciones; {graves} con cifras ausentes de todo el libro) · "
            f"{len(inf['voces'])} págs. con voces no conservadas · inglés {len(inf['ingles'])} · "
            f"basura {len(inf['basura'])} · hojas vacías {len(inf['hojas_vacias'])}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("original")
    ap.add_argument("traducido")
    ap.add_argument("informe")
    ap.add_argument("--glosario", action="append", default=[], help="glosario del libro (se puede repetir)")
    a = ap.parse_args()
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    base = [os.path.join(raiz, "glossary.txt"), os.path.join(raiz, "lexicons", "voces_verificadas.json"),
            os.path.join(raiz, "lexicons", "terminos.json")]
    print(resumen(auditar(a.original, a.traducido, a.informe, base + a.glosario)))


if __name__ == "__main__":
    main()
