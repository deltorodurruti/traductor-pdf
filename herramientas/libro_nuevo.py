#!/usr/bin/env python3
"""Remaqueta una carpeta en formato libro y la revisa antes de entregarla."""
import argparse
import os
import re
import sys
import tempfile
from dataclasses import dataclass

from bs4 import BeautifulSoup

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import entregas
import entregar_libro
import hojas
import render

BASE = os.environ.get("TRAB", os.path.expanduser("~/traductor/taller"))
ENTREGA = os.environ.get("ENTREGA", os.path.expanduser("~/traductor/libros_esp"))
RESPALDO = os.environ.get("RESPALDO", os.path.expanduser(
    "~/traductor/taller/_antes_revision"))


@dataclass
class Revision:
    fail: bool
    warn: bool


def metadatos(carpeta, titulo=None, autor=None):
    meta = {}
    ruta = os.path.join(BASE, "libros_meta.tsv")
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as fh:
            for linea in fh:
                if not linea.strip() or linea.lstrip().startswith("#"):
                    continue
                partes = linea.rstrip("\n").split("\t")
                if len(partes) >= 2:
                    meta[partes[0]] = (partes[1], partes[2] if len(partes) > 2 else "")
    entrega = entregas.leer(BASE).get(carpeta)
    bonito = entrega[1] if entrega else None
    por_tsv = meta.get(carpeta, (None, ""))
    return (titulo if titulo is not None else por_tsv[0] or bonito or carpeta,
            autor if autor is not None else por_tsv[1] or "")


def _palabras_html(html):
    return len(entregar_libro.sin_marcas(hojas._quitar_marcadores_figura(html)).split())


def _entradas_indice(pdf, html):
    """(nº de entradas del índice, nº de ellas con página «0»). Un «0» es un título que el
    maquetado no logró paginar: maquetado roto que hay que marcar."""
    entradas = BeautifulSoup(html, "html.parser").select("div.entrada-indice")
    if entradas:
        ceros = sum(1 for e in entradas if (e.select_one(".pagina") or e).get_text(strip=True) == "0")
        return len(entradas), ceros
    import fitz
    doc = fitz.open(pdf)
    try:
        total = ceros = 0
        en_indice = False
        for pagina in doc:
            lineas = pagina.get_text("text").splitlines()
            encab = any(re.search(r"\bÍndice\b", l, re.I) for l in lineas)
            marcas = [m for l in lineas if len(l.strip()) > 4
                      for m in [re.search(r"(?:\.{2,}|\s)(\d+)\s*$", l)] if m]
            if encab:
                en_indice = True
            elif en_indice and len(marcas) < 2:
                break
            if en_indice:
                total += len(marcas)
                ceros += sum(1 for m in marcas if m.group(1) == "0")
        return total, ceros
    finally:
        doc.close()


def _imagenes_distintas(pdf):
    import fitz
    doc = fitz.open(pdf)
    try:
        return len({imagen[0] for pagina in doc for imagen in pagina.get_images(full=True)})
    finally:
        doc.close()


def revisar(pdf, html_p):
    import fitz
    with open(html_p, encoding="utf-8") as fh:
        html = fh.read()
    doc = fitz.open(pdf)
    paginas = len(doc)
    doc.close()
    origen = _palabras_html(html)
    palabras = entregar_libro.palabras(pdf)
    razon = palabras / max(origen, 1)
    imagenes_html = len(re.findall(r"<img\b", html, re.I))
    imagenes_pdf = _imagenes_distintas(pdf)
    area = entregar_libro.medir(pdf)[0]
    ingles = entregar_libro.palabras_inglesas(pdf)
    indices, indices_cero = _entradas_indice(pdf, html)
    fail = razon < 0.97 or indices_cero > 0
    warn = razon > 1.15 or ingles > 400
    print("REVISIÓN")
    print(f"páginas\t{paginas}")
    print(f"palabras\t{palabras}/{origen} ({razon:.3f})\t{'FAIL: falta texto' if razon < 0.97 else 'WARN' if razon > 1.15 else 'OK'}")
    print(f"figuras\tHTML {imagenes_html}; PDF {imagenes_pdf}; área {area} pt²\tINFO")
    print(f"inglés\t{ingles}\t{'WARN' if ingles > 400 else 'INFO'}")
    print(f"índice\t{indices} entradas{f', {indices_cero} sin página' if indices_cero else ''}"
          f"\t{'FAIL: índice con «0»' if indices_cero else 'INFO'}")
    return Revision(fail, warn)


def _paginas(pdf):
    import fitz
    try:
        doc = fitz.open(pdf)
    except Exception:
        return "ilegible"
    try:
        return len(doc)
    finally:
        doc.close()


def _temporal(d):
    fd, ruta = tempfile.mkstemp(prefix=".libro-nuevo-", suffix=".pdf", dir=d)
    os.close(fd)
    os.unlink(ruta)
    return ruta


def _carpeta_y_ruta(argumento):
    if os.path.isabs(argumento):
        return os.path.basename(os.path.normpath(argumento)), argumento
    return argumento, os.path.join(BASE, argumento)


def _titulos_informe(html_p, original, manual):
    try:
        with open(html_p, encoding="utf-8") as archivo:
            soup = BeautifulSoup(archivo.read(), "html.parser")
        return len(hojas._titulos_traducidos(soup, original, manual))
    except Exception:
        return len(manual or [])


def ejecutar(argumento, entregar=False, titulo=None, autor=None, bandera=False):
    carpeta, d = _carpeta_y_ruta(argumento)
    if not os.path.isdir(d):
        print(f"✗ no existe la carpeta del libro: {d}")
        return 1
    if entregar:
        try:
            dentro_de_base = os.path.commonpath((os.path.realpath(d), os.path.realpath(BASE))) == os.path.realpath(BASE)
        except ValueError:
            dentro_de_base = False
        if not dentro_de_base:
            print(f"✗ no se puede entregar un libro fuera de BASE: {d}")
            return 4
    if entregar and carpeta not in entregar_libro.ENTREGADOS:
        print(f"✗ {carpeta} no está en entregas.tsv; no se puede entregar")
        return 4
    chrome = render.find_chrome()
    if not chrome:
        print("✗ no hay navegador: defina TRADUCTOR_CHROME con la ruta de un navegador Chromium")
        return 2
    html_p, original = entregar_libro.fuentes(d)
    if not html_p:
        print(f"✗ {carpeta} no tiene HTML de trabajo")
        return 1
    cerrojo = entregar_libro._adquirir_cerrojo(d)
    if not cerrojo:
        print(f"✗ {carpeta} ya está siendo maquetada; salida 3")
        return 3
    tmp = None
    salida = os.path.join(d, "_libro_nuevo.pdf")
    try:
        tmp = _temporal(d)
        titulo, autor = metadatos(carpeta, titulo, autor)
        titulos_manual = hojas._leer_titulos_tsv(os.path.join(d, "titulos.tsv"))
        cantidad = _titulos_informe(html_p, original, titulos_manual)
        origen_titulos = "manual" if titulos_manual is not None else "automático"
        print(f"títulos: {cantidad} ({origen_titulos})")
        hojas.maquetar(html_p, tmp, original=original, libro=True, titulo=titulo, autor=autor,
                       libro_justificado=not bandera, titulos_manual=titulos_manual)
        os.replace(tmp, salida)
        resultado = revisar(salida, html_p)
        if carpeta in entregar_libro.ENTREGADOS:
            entregado_actual = os.path.join(ENTREGA, entregar_libro.ENTREGADOS[carpeta])
            if os.path.exists(entregado_actual):
                print(f"páginas entregado actual\t{_paginas(entregado_actual)}")
        if resultado.fail or not entregar:
            return 1 if resultado.fail else 0
        entregado = os.path.join(ENTREGA, entregar_libro.ENTREGADOS[carpeta])
        if os.path.exists(entregado):
            entregar_libro._copiar_atomico(entregado,
                                           os.path.join(RESPALDO,
                                                        os.path.basename(entregado) + ".antes_libro"))
        entregar_libro._copiar_atomico(salida, entregado)
        print(f"✓ entregado {entregado}")
        return 0
    except Exception as exc:
        print(f"✗ no se pudo maquetar o revisar: {exc}")
        return 1
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)
        cerrojo.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("carpeta")
    parser.add_argument("--entregar", action="store_true")
    parser.add_argument("--titulo")
    parser.add_argument("--autor")
    parser.add_argument("--bandera", action="store_true")
    args = parser.parse_args()
    return ejecutar(args.carpeta, args.entregar, args.titulo, args.autor, args.bandera)


if __name__ == "__main__":
    raise SystemExit(main())
