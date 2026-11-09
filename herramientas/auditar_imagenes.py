#!/usr/bin/env python3
"""Audita que un PDF traducido conserve las figuras del original.

Saca las figuras de la fuente (imágenes incrustadas si la página es nativa, bandas de tinta si es un
escaneo; es la misma detección que usa el traductor) y las imágenes incrustadas del PDF traducido, las
compara por huella perceptual (dHash, no depende del tamaño ni del recorte fino) y lista:
  * figuras del original que no están en la traducción (pérdidas probables),
  * imágenes de la traducción vacías (todo negro o todo blanco),
  * imágenes de la traducción que no vienen del original (rótulos, pies de lámina).
Cada pérdida se guarda como PNG en la carpeta de salida, junto a una hoja de contacto, para verla a ojo.

Uso: python herramientas/auditar_imagenes.py fuente.pdf traducido.pdf [salida/] [--umbral 14]
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz
import numpy as np
from PIL import Image

import figuras

MIN_LADO = 40
UMBRAL = 14


def dhash(im: Image.Image) -> int:
    g = np.asarray(im.convert("L").resize((9, 8), Image.LANCZOS), dtype=np.int16)
    bits = (g[:, 1:] > g[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def vacia(im: Image.Image) -> str:
    """'negra' o 'blanca' si la imagen casi no tiene variación; '' si trae contenido."""
    g = np.asarray(im.convert("L"))
    if g.std() > 6:
        return ""
    return "negra" if g.mean() < 60 else "blanca" if g.mean() > 200 else "gris"


desde_uri = figuras.uri_a_imagen
es_texto_ingles = figuras.es_texto_ingles


def de_fuente(ruta: str) -> list[dict]:
    out = []
    for i, pag in enumerate(fitz.open(ruta), 1):
        try:
            figs = figuras.figuras_pagina(pag)
        except Exception as e:
            print(f"✗ no se pudieron extraer figuras de la página {i}: {e}", file=sys.stderr, flush=True)
            raise RuntimeError(f"auditoría incompleta en la página {i}") from e
        for _, uri in figs:
            im = desde_uri(uri)
            if min(im.size) >= MIN_LADO and not vacia(im):
                out.append({"pag": i, "h": dhash(im), "im": im, "ingles": es_texto_ingles(im)})
    return out


def de_fuente_cacheada(ruta: str, carpeta: str) -> list[dict]:
    """De la fuente se detectan las figuras una sola vez (es lo lento): se guarda junto al informe."""
    import base64
    import io
    import json
    import tempfile
    st = os.stat(ruta)
    cache = os.path.join(carpeta, os.path.basename(ruta) + ".figuras.json") if carpeta else ""
    clave = [st.st_size, int(st.st_mtime), 3]
    if cache and os.path.exists(cache):
        try:
            with open(cache, encoding="utf-8") as f:
                guardado = json.load(f)
            if guardado.get("clave") == clave:
                from PIL import Image
                datos = []
                for item in guardado["figuras"]:
                    im = Image.open(io.BytesIO(base64.b64decode(item.pop("png"))))
                    item["im"] = im.copy()
                    datos.append(item)
                return datos
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            pass
    datos = de_fuente(ruta)
    if cache:
        os.makedirs(carpeta, exist_ok=True)
        serializados = []
        for item in datos:
            buf = io.BytesIO()
            item["im"].save(buf, format="PNG")
            serializados.append({**{k: v for k, v in item.items() if k != "im"},
                                 "png": base64.b64encode(buf.getvalue()).decode("ascii")})
        tmp = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=carpeta,
                                             prefix=".figuras-", suffix=".tmp", delete=False) as f:
                tmp = f.name
                json.dump({"clave": clave, "figuras": serializados}, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, cache)
        finally:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)
    return datos


def de_traduccion(ruta: str) -> list[dict]:
    """Imágenes del PDF tal como se ven en la página (con su máscara alfa), una por (página, imagen)."""
    doc = fitz.open(ruta)
    vistas: dict[tuple, dict] = {}
    out = []
    for i, pag in enumerate(doc, 1):
        for x in pag.get_images(full=True):
            xref = x[0]
            for r in pag.get_image_rects(xref)[:1]:
                if min(r.width, r.height) < MIN_LADO * 0.72:
                    continue
                clave = (xref, round(r.width), round(r.height))
                if clave not in vistas:
                    pix = pag.get_pixmap(dpi=100, clip=r & pag.rect, colorspace=fitz.csRGB, alpha=False)
                    im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    vistas[clave] = {"im": im, "h": dhash(im), "vacia": vacia(im)}
                out.append({"pag": i, "xref": xref, **vistas[clave]})
    return out


INLIERS = 20
RAZON = 0.45


def _orb(it: dict):
    """(puntos, descriptores) ORB de la imagen, calculados una vez."""
    if "orb" not in it:
        import cv2
        g = np.asarray(it["im"].convert("L"))
        e = 520 / max(g.shape)
        if e < 1:
            g = cv2.resize(g, None, fx=e, fy=e, interpolation=cv2.INTER_AREA)
        it["orb"] = cv2.ORB_create(600).detectAndCompute(g, None)
    return it["orb"]


def misma_figura(a: dict, b: dict) -> bool:
    """ORB + homografía: tolera recortes distintos (con o sin pie), color y escala."""
    import cv2
    ka, da = _orb(a)
    kb, db = _orb(b)
    if da is None or db is None or len(ka) < INLIERS or len(kb) < INLIERS:
        return False
    bruto = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(da, db, k=2)
    buenos = [m[0] for m in bruto if len(m) == 2 and m[0].distance < 0.8 * m[1].distance]
    if len(buenos) < INLIERS:
        return False
    src = np.float32([ka[m.queryIdx].pt for m in buenos]).reshape(-1, 1, 2)
    dst = np.float32([kb[m.trainIdx].pt for m in buenos]).reshape(-1, 1, 2)
    _, mascara = cv2.findHomography(src, dst, cv2.RANSAC, 6.0)
    return mascara is not None and int(mascara.sum()) >= INLIERS and mascara.sum() >= RAZON * len(buenos)


def _sin_pareja(items: list[dict], otros: list[dict], umbral: int) -> list[dict]:
    """Los de `items` que no están en `otros`: primero por huella; los dudosos, por puntos característicos."""
    oh = [o["h"] for o in otros]
    out = []
    for it in items:
        if oh and min(bin(it["h"] ^ h).count("1") for h in oh) <= umbral:
            continue
        if any(misma_figura(it, o) for o in otros):
            continue
        out.append(it)
    return out


def comparar(fuente: list[dict], trad: list[dict], umbral: int) -> tuple[list, list, list]:
    reales = [t for t in trad if not t["vacia"]]
    return _sin_pareja(fuente, reales, umbral), [t for t in trad if t["vacia"]], _sin_pareja(reales, fuente, umbral)


def contacto(items: list[dict], ruta: str, cols: int = 6, lado: int = 260) -> None:
    if not items:
        return
    filas = (len(items) + cols - 1) // cols
    hoja = Image.new("RGB", (cols * lado, filas * (lado + 18)), "white")
    from PIL import ImageDraw
    d = ImageDraw.Draw(hoja)
    for k, it in enumerate(items):
        im = it["im"].convert("RGB")
        im.thumbnail((lado - 8, lado - 8))
        x, y = (k % cols) * lado, (k // cols) * (lado + 18)
        hoja.paste(im, (x + 4, y + 18))
        d.text((x + 4, y + 2), f"p.{it['pag']}", fill="red")
    hoja.save(ruta)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("fuente")
    ap.add_argument("traducido")
    ap.add_argument("salida", nargs="?", default="")
    ap.add_argument("--umbral", type=int, default=UMBRAL)
    a = ap.parse_args()
    f, t = de_fuente_cacheada(a.fuente, a.salida), de_traduccion(a.traducido)
    texto = [x for x in f if x["ingles"]]
    f = [x for x in f if not x["ingles"]]
    perdidas, vacias, huerfanas = comparar(f, t, a.umbral)
    nombre = os.path.basename(a.traducido)
    print(f"{nombre}: {len(f)} figuras en el original (sin contar {len(texto)} bloques de texto inglés), {len(t)} imágenes en la traducción")
    print(f"  perdidas probables: {len(perdidas)}  págs. del original: {sorted({p['pag'] for p in perdidas})[:80]}")
    print(f"  vacías en la traducción: {len(vacias)}  págs.: {sorted({p['pag'] for p in vacias})[:60]}")
    print(f"  sin correspondencia en el original: {len(huerfanas)}  págs.: {sorted({p['pag'] for p in huerfanas})[:60]}")
    if a.salida:
        os.makedirs(a.salida, exist_ok=True)
        base = os.path.splitext(nombre)[0]
        contacto(perdidas, os.path.join(a.salida, f"{base}.perdidas.png"))
        contacto(huerfanas, os.path.join(a.salida, f"{base}.huerfanas.png"))
        contacto(vacias, os.path.join(a.salida, f"{base}.vacias.png"))


if __name__ == "__main__":
    main()
