"""Figuras de un libro escaneado: se recortan del PDF original y se colocan en su sitio.

El OCR solo devuelve texto: los diagramas, símbolos y láminas se pierden. Aquí se
buscan en la página original como bandas de tinta continuas y altas (el texto, en
cambio, deja huecos entre renglones), se recortan y se colocan entre los párrafos
de la traducción según su posición vertical relativa en la página.

Sirve para escaneos limpios. En fotografías de página (sombras, curvatura) la
banda se rompe: ahí conviene pasar las cajas a mano (ver cajas_manuales).

Si la página tiene capa de texto propia (PDF nativo, sin una imagen de fondo que cubra la
página) no se buscan bandas: los párrafos densos se confundirían con figuras y se pegaría el
inglés como imagen. Las figuras son entonces las imágenes incrustadas (ver _incrustadas).
"""
from __future__ import annotations

import base64
import io
import re

MIN_IMG = 0.01
FONDO = 0.5
TEXTO_NATIVO = 200
HUECO = 0.012
ALTO_MIN = 0.12
SIMBOLOS = re.compile(r"[~△+=|<>_]")
CORTAS_OK = {"de", "la", "el", "en", "un", "a", "y", "o", "e", "se", "su", "no", "lo", "al", "es",
             "me", "mi", "tu", "te", "si", "ya", "le"}
INICIOS = {"Como", "El", "La", "Los", "Las", "Un", "Una", "Este", "Esta", "Estos", "Estas", "Cuando",
           "Si", "Hay", "Aquí", "Ahora", "Esto", "Eso", "También", "Pero", "Y", "En", "Para", "Por"}


def _tinta(pag, dpi: int):
    import fitz
    import numpy as np
    pix = pag.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
    g = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    return g, g < 150


def _png_uri(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()


def _es_nativa(pag) -> bool:
    """True si la página trae su propio texto y ninguna imagen de fondo que la cubra."""
    if len(pag.get_text().strip()) < TEXTO_NATIVO:
        return False
    area = pag.rect.width * pag.rect.height
    return all(fitz_area(im["bbox"], pag.rect) <= FONDO * area for im in pag.get_image_info())


def fitz_area(bbox, rect) -> float:
    import fitz
    r = fitz.Rect(bbox) & rect
    return 0.0 if r.is_empty else r.width * r.height


def _incrustadas(pag, dpi: int = 130) -> list[tuple[float, str]]:
    """Imágenes incrustadas de una página nativa, recortadas de su render: [(posición 0-1, PNG)]."""
    import fitz
    area = pag.rect.width * pag.rect.height
    bloques = [b for b in pag.get_text("blocks") if b[6] == 0 and b[4].strip()]
    out = []
    for im in pag.get_image_info():
        r = fitz.Rect(im["bbox"]) & pag.rect
        if r.is_empty or r.width * r.height < MIN_IMG * area:
            continue
        arriba = sum(1 for b in bloques if b[3] <= r.y0 + 2)
        abajo = sum(1 for b in bloques if b[1] >= r.y1 - 2)
        pos = arriba / (arriba + abajo) if arriba + abajo else 1.0
        out.append((pos, _png_uri(pag.get_pixmap(dpi=dpi, clip=r).tobytes("png"))))
    return out


_EN = set("the and of to is that with which for this are was were from by as be it his her their they have has "
          "not but or an these those its into than there when who what shall will may can upon".split())
_ES = set("el la los las de del que y en un una es por con para se su sus al lo como más pero o este esta estos "
          "estas ese esa son fue ser está han había sin sobre entre también".split())


def es_texto_ingles(im) -> bool:
    """True si la imagen es un bloque de texto en inglés (≥8 palabras, ≥5 inglesas y más del doble que
    españolas, leído con Tesseract). Sin Tesseract devuelve False: no se quita nada."""
    import os
    import shutil
    import subprocess
    import tempfile
    if not shutil.which("tesseract"):
        return False
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        im.convert("L").save(f, "PNG")
    try:
        txt = subprocess.run(["tesseract", f.name, "-", "-l", "eng", "--psm", "6"],
                             capture_output=True, text=True, timeout=120).stdout
    except Exception:
        return False
    finally:
        os.remove(f.name)
    w = re.findall(r"[A-Za-z]+", txt.lower())
    en, es = sum(x in _EN for x in w), sum(x in _ES for x in w)
    return len(w) >= 8 and en >= 5 and en > es * 1.5


def uri_a_imagen(uri: str):
    from PIL import Image
    return Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1])))


def sin_texto_ingles(figs: list[tuple[float, str]]) -> list[tuple[float, str]]:
    """Quita de las figuras de una página los recortes que son solo texto en inglés (el libro va en español)."""
    return [(p, u) for p, u in figs if not es_texto_ingles(uri_a_imagen(u))]


def figuras_pagina(pag, dpi: int = 100) -> list[tuple[float, str]]:
    """[(posición 0-1 respecto al texto, imagen PNG como data URI)] de una página del original."""
    if _es_nativa(pag):
        return _incrustadas(pag)
    import numpy as np
    from PIL import Image
    g, tinta = _tinta(pag, dpi)
    alto = g.shape[0]
    filas = tinta.sum(axis=1) > 2
    top, bot, gmax = int(0.085 * alto), int(0.935 * alto), int(HUECO * alto)
    bandas, ini, ult, gap = [], None, 0, 0
    for y in range(top, bot):
        if filas[y]:
            if ini is None:
                ini = y
            ult, gap = y, 0
        elif ini is not None:
            gap += 1
            if gap > gmax:
                bandas.append((ini, ult))
                ini, gap = None, 0
    if ini is not None:
        bandas.append((ini, ult))
    figs = [b for b in bandas if b[1] - b[0] >= ALTO_MIN * alto]
    texto = [b for b in bandas if b[1] - b[0] < ALTO_MIN * alto]
    out = []
    for y0, y1 in figs:
        cols = np.where(tinta[y0:y1 + 1].any(axis=0))[0]
        x0, x1 = max(0, cols[0] - 6), min(g.shape[1], cols[-1] + 7)
        im = Image.fromarray(g[max(0, y0 - 4):y1 + 5, x0:x1])
        if im.width > 1000:
            im = im.resize((1000, int(im.height * 1000 / im.width)))
        b = io.BytesIO()
        im.save(b, "PNG", optimize=True)
        arriba = sum(1 for t in texto if t[1] < y0)
        abajo = sum(1 for t in texto if t[0] > y1)
        pos = arriba / (arriba + abajo) if arriba + abajo else 1.0
        out.append((pos, "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()))
    return out


def cajas_manuales(pag, cajas: list[tuple[float, float, float, float]], dpi: int = 170) -> list[tuple[float, str]]:
    """Recortes a mano: cajas (x0, y0, x1, y1) en fracciones 0-1 de la página; sirve para fotografías."""
    from PIL import Image
    g, _ = _tinta(pag, dpi)
    alto, ancho = g.shape
    out = []
    for x0, y0, x1, y1 in cajas:
        im = Image.fromarray(g[int(y0 * alto):int(y1 * alto), int(x0 * ancho):int(x1 * ancho)])
        b = io.BytesIO()
        im.save(b, "PNG", optimize=True)
        out.append((y0, "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()))
    return out


def colocar(bloques: list[str], figs: list[tuple[float, str]]) -> list[tuple[str, str]]:
    """Mezcla párrafos y figuras: [('p', texto) | ('f', data_uri)]. La figura va en el límite
    de párrafo más cercano a su posición relativa en la página."""
    elems = [("p", b) for b in bloques]
    total = sum(len(b) for b in bloques) or 1
    for pos, uri in sorted(figs, key=lambda f: f[0]):
        acum, cortes = 0, []
        for i, e in enumerate(elems):
            if e[0] == "p":
                cortes.append((acum / total, i))
                acum += len(e[1])
        cortes.append((acum / total, len(elems)))
        k = min(cortes, key=lambda c: abs(c[0] - pos))[1]
        elems.insert(k, ("f", uri))
    return elems


def quitar_cola(b: str) -> str:
    """Quita el resto de OCR de los rótulos de una figura que quedó al final de un párrafo:
    lo que sigue a la última frase si trae símbolos raros (hasta 45 palabras) o casi todo son
    fragmentos de una o dos letras (hasta 18)."""
    fin = list(re.finditer(r"[.!?»”\"]", b))
    if not fin:
        return b
    i = fin[-1].end()
    cola = b[i:].strip()
    toks = cola.split()
    if not toks or len(toks) > 45:
        return b
    cortos = sum(len(t) <= 2 and t.lower() not in CORTAS_OK for t in toks)
    if SIMBOLOS.search(cola) or (len(toks) <= 18 and cortos / len(toks) >= 0.4):
        return b[:i].rstrip()
    return b


def quitar_cabeza(b: str) -> str:
    """Igual que quitar_cola, pero para los rótulos que quedaron al inicio del párrafo: se corta
    hasta el primer inicio de frase habitual, solo si lo anterior trae símbolos y no tiene ninguna
    palabra en minúscula de tres letras o más (eso sería texto del libro, no rótulo)."""
    toks = b.split()
    for i, t in enumerate(toks[:45]):
        previo = toks[:i]
        if (i >= 2 and t in INICIOS and SIMBOLOS.search(" ".join(previo))
                and not any(re.match(r"[a-záéíóúñ]", x) and len(x) >= 3 for x in previo)):
            return " ".join(toks[i:])
    return b
