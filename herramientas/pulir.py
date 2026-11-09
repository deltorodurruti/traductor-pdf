#!/usr/bin/env python3
"""Pule el HTML solo-español de un libro: términos congelados en inglés y basura de OCR árabe.

Dos defectos que deja el traductor y que ningún motor arregla bien:
  * un glosario de «no traducir» demasiado amplio congela en inglés nombres que tienen forma
    española (Mercury, Plato, Natural Philosophy). --reemplazos aplica un archivo de reglas
    «inglés => español» (una por línea, # comenta; distingue mayúsculas; las más largas primero)
    sobre el texto de los bloques, nunca sobre etiquetas ni imágenes.
  * si el PDF trae el árabe, el hebreo o el griego con una fuente rota, el texto se copia como
    mojibake (ȿƮ«ا …, éãù, ôïõ). Se eliminan las fichas con letras árabes, con símbolos de ese
    mojibake o formadas solo por letras latinas acentuadas de 2 o más caracteres (ninguna palabra
    española las tiene: siempre llevan alguna letra sin acento).

  * el hebreo con fuente rota llega como cp1255 leído en Latin-1, en orden visual (íåìù = שלום): con
    --hebreo se decodifica, se invierte al orden lógico y se marca con <span dir="rtl" lang="he">.
    Solo se acepta una ficha si el resultado es hebreo bien formado (las letras finales ך ם ן ף ץ solo
    al final de la palabra); el resto sigue yendo a la regla del mojibake.

  * en un libro de transliteración árabe, el árabe roto también deja corridas de letras latinas
    extendidas y símbolos (Ĵ Ŀy ü Ī b ā ŝy¨©). Con --latin-ext se borran las fichas con una letra fuera de
    lo permitido (español, transliteración, IPA), junto con las fichas sueltas pegadas a ellas, y se
    limpian los paréntesis vacíos que quedan y la «y» huérfana.

  * un índice cuyas entradas numeradas quedaron pegadas en un párrafo («1. Parte I… 2. El primer capítulo…»):
    con --indice 2,3 esas páginas se parten en una entrada por línea (cada número debe ser el siguiente
    del anterior, así una cifra dentro del texto no corta la entrada).

Sin --aplicar solo informa. Con --aplicar guarda un respaldo «.pulir» la primera vez.
Uso: python herramientas/pulir.py libro_es.html [--reemplazos reglas.txt] [--sin-mojibake] [--hebreo] [--latin-ext] [--indice 2,3] [--aplicar]
"""
from __future__ import annotations

import argparse
import html as _html
import os
import re
import shutil
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from render import escribir_atomico
import unicodedata

from bs4 import BeautifulSoup, NavigableString

ARABE = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
MOJIBAKE = re.compile(r"[ȿƮƑŏŗŅĉńŋƁƇƎĳŭĸŻĐ]")
SIGNOS = re.compile(r"[|{}¢£¤¥¦]")
SOLO_ACENTUADAS = re.compile(r"[À-ÿ]{2,}")
SUELTAS = {"ð", "ë", "þ"}
SALTAR = {"script", "style", "img"}
HEB_LETRAS = "אבגדהוזחטיכלמנסעפצקרשת"
HEB_FINALES = "ךםןףץ"
HEB_VALIDO = re.compile(rf"[{HEB_LETRAS}]*[{HEB_FINALES}]?")
HEB_CP1255 = re.compile(r"[à-ú]+")


def reglas(ruta: str) -> list[tuple[str, str]]:
    """[(inglés, español)] ordenadas de la más larga a la más corta."""
    out = []
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if linea and not linea.startswith("#") and "=>" in linea:
                a, b = (x.strip() for x in linea.split("=>", 1))
                out.append((a, b))
    return sorted(out, key=lambda r: -len(r[0]))


def es_basura(ficha: str) -> bool:
    nucleo = re.sub(r"^\W+|\W+$", "", ficha)
    if ARABE.search(ficha) or MOJIBAKE.search(ficha) or ficha in ("¡", "«", "»"):
        return True
    if SIGNOS.search(ficha) and not re.search(r"[A-Za-zÀ-ÿ]{3,}|\d", ficha):
        return True
    return bool(SOLO_ACENTUADAS.fullmatch(nucleo)) or nucleo in SUELTAS


def sin_mojibake(texto: str) -> tuple[str, int]:
    """Quita las fichas con letras árabes o mojibake; devuelve (texto, fichas quitadas)."""
    n = 0
    if not texto.strip():
        return texto, 0
    partes = re.split(r"(\s+)", texto)
    for i, p in enumerate(partes):
        if p and not p.isspace() and es_basura(p):
            partes[i] = ""
            n += 1
    sal = re.sub(r"[ \t]{2,}", " ", "".join(partes)).strip()
    return texto[:len(texto) - len(texto.lstrip())] + sal + texto[len(texto.rstrip()):], n


PERMITIDAS = set("áéíóúüñÁÉÍÓÚÜÑāīūĀĪŪʿʾḥḤṭṬṣṢḍḌẓẒḫḪġĠṯṮḏḎ")
EXTRAS_BASURA = set("¼³¢¶µ¨÷|{}")


def sospechosa(c: str) -> bool:
    """Letra o marca fuera de lo permitido (el IPA, U+0250-02FF, sí lo está)."""
    if ord(c) < 0x80 or c in PERMITIDAS or 0x250 <= ord(c) <= 0x2FF:
        return False
    return unicodedata.category(c)[0] in "LM"


def _fuerte(tok: str) -> bool:
    return any(sospechosa(c) or c in EXTRAS_BASURA for c in tok)


def _debil(tok: str) -> bool:
    """Ficha suelta que acompaña al mojibake: una letra, o solo símbolos (©, ª, ¨...); no cifras ni «a o e u»."""
    nucleo = re.sub(r"[\W_]", "", tok)
    if re.search(r"[()\[\]]", tok):
        return False
    if not nucleo:
        return not re.search(r"\d", tok)
    return len(nucleo) == 1 and nucleo.isalpha() and nucleo.lower() not in "aoeu"


RESIDUO = re.compile(r"[yz©ªº¨]+|[ÁÉÍÓÚáéíóú]?[yz]|[īāū][yz]")
RESIDUO_SUELTO = re.compile(r"[ÁÉÍÓÚáéíóúāīū]")


def sin_residuos(texto: str) -> tuple[str, int]:
    """Quita las corridas de residuos (y y, © y ©, z z y y y). Una «y» sola es la conjunción y se queda."""
    partes = re.split(r"(\s+)", texto)
    idx = [i for i, p in enumerate(partes) if p and not p.isspace()]
    es_res = {i for i in idx if RESIDUO.fullmatch(partes[i])}
    borrar: set[int] = set()
    k = 0
    while k < len(idx):
        if idx[k] not in es_res:
            k += 1
            continue
        j = k
        while j + 1 < len(idx) and idx[j + 1] in es_res:
            j += 1
        a, b = k, j
        if a > 0 and RESIDUO_SUELTO.fullmatch(partes[idx[a - 1]]):
            a -= 1
        if b + 1 < len(idx) and RESIDUO_SUELTO.fullmatch(partes[idx[b + 1]]):
            b += 1
        corrida = idx[a:b + 1]
        if len(corrida) >= 2 or any(re.search(r"[©ªº¨]", partes[i]) for i in corrida):
            borrar.update(corrida)
        k = j + 1
    for i in borrar:
        partes[i] = ""
    sal = re.sub(r"[ \t]{2,}", " ", "".join(partes))
    return texto[:len(texto) - len(texto.lstrip())] + sal.strip() + texto[len(texto.rstrip()):], len(borrar)


def sin_corridas_latinas(texto: str) -> tuple[str, int]:
    """Quita las fichas con letras sospechosas y las fichas débiles contiguas; devuelve (texto, fichas quitadas)."""
    texto, extra = sin_residuos(texto)
    partes = re.split(r"(\s+)", texto)
    idx = [i for i, p in enumerate(partes) if p and not p.isspace()]
    borrar = {i for i in idx if _fuerte(partes[i])}
    if not borrar:
        return texto, extra
    for sentido in (1, -1):
        orden = idx if sentido == 1 else idx[::-1]
        activo = False
        for i in orden:
            if i in borrar:
                activo = True
            elif activo and _debil(partes[i]):
                borrar.add(i)
            else:
                activo = False
    for i in borrar:
        partes[i] = ""
    sal = "".join(partes)
    sal = re.sub(r"\(\s*\)", "", sal)
    sal = re.sub(r"\s+([,.;:)])", r"\1", sal)
    sal = re.sub(r"[ \t]{2,}", " ", sal)
    sal = re.sub(r"(?:\s+y)+\s*$", "", sal)
    return texto[:len(texto) - len(texto.lstrip())] + sal.strip() + texto[len(texto.rstrip()):], len(borrar) + extra


def _hebreo_ficha(ficha: str) -> str:
    """El hebreo (orden lógico) que esconde una ficha en mojibake cp1255, o '' si no lo es."""
    if not HEB_CP1255.fullmatch(ficha):
        return ""
    try:
        logico = ficha.encode("cp1252").decode("cp1255")[::-1]
    except UnicodeError:
        return ""
    return logico if HEB_VALIDO.fullmatch(logico) else ""


def segmentos_hebreo(texto: str) -> list[tuple[str, str]]:
    """[('t', texto) | ('h', hebreo)]. Una corrida de fichas hebreas seguidas se invierte entera (visual → lógico);
    una ficha suelta de una letra solo cuenta si va pegada a una corrida de 2 o más letras."""
    partes = re.split(r"(\s+)", texto)
    nucleos = []
    for p in partes:
        m = re.fullmatch(r"(\W*)(.*?)(\W*)", p, re.S)
        nucleos.append((m.group(1), m.group(2), m.group(3)))
    heb = [bool(p.strip()) and _hebreo_ficha(n[1]) != "" for p, n in zip(partes, nucleos)]
    for i, (p, n) in enumerate(zip(partes, nucleos)):
        if p.strip() and len(n[1]) == 1 and _hebreo_ficha(n[1]):
            vecinos = [j for j in (i - 2, i + 2) if 0 <= j < len(partes) and heb[j] and len(nucleos[j][1]) >= 2]
            heb[i] = bool(vecinos)
    out, i = [], 0
    while i < len(partes):
        if not heb[i]:
            out.append(("t", partes[i]))
            i += 1
            continue
        j = i
        while j + 2 < len(partes) and heb[j + 2] and not partes[j + 1].strip("\n") == "":
            j += 2
        corrida = [k for k in range(i, j + 1, 2)]
        ant, _, _ = nucleos[corrida[0]]
        _, _, post = nucleos[corrida[-1]]
        palabras = [_hebreo_ficha(nucleos[k][1]) for k in reversed(corrida)]
        if ant:
            out.append(("t", ant))
        out.append(("h", " ".join(palabras)))
        if post:
            out.append(("t", post))
        i = j + 1
    return out


def partir_indice(texto: str, siguiente: int) -> tuple[list[str], int]:
    """Parte un texto con entradas numeradas pegadas en [líneas], y devuelve el número que debe seguir."""
    texto = re.sub(r"\s+", " ", texto).strip()
    cortes = [0]
    for m in re.finditer(r"(?:(?<=\s)|^)(\d{1,3})\. ", texto):
        if int(m.group(1)) == siguiente:
            cortes.append(m.start())
            siguiente += 1
    cortes = sorted(set(cortes)) + [len(texto)]
    return [texto[a:b].strip() for a, b in zip(cortes, cortes[1:]) if texto[a:b].strip()], siguiente


ROMANO_PEGADO = re.compile(r"(?<![\w])([ivxl]{1,6})(?=[A-ZÁÉÍÓÚÑ])")


def indice_en_lineas(soup, paginas: set) -> int:
    """Parte en una entrada por línea los bloques de texto de esas páginas (los que no traen numeración 1. 2. 3.
    solo se arreglan los numerales romanos pegados); devuelve cuántas entradas quedaron."""
    siguiente, total = 1, 0
    for sec in soup.select("section.page"):
        pn = sec.select_one(".page-num")
        m = re.search(r"\d+", pn.get_text()) if pn else None
        if not m or int(m.group(0)) not in paginas:
            continue
        for div in sec.select("div.solo"):
            antes = siguiente
            lineas, siguiente = partir_indice(div.get_text(" "), siguiente)
            if siguiente == antes:
                for nodo in div.find_all(string=True):
                    arreglado = ROMANO_PEGADO.sub(r"\1 ", str(nodo))
                    if arreglado != str(nodo):
                        nodo.replace_with(arreglado)
                continue
            div.clear()
            for k, l in enumerate(lineas):
                if k:
                    div.append(soup.new_tag("br"))
                div.append(l)
            total += len(lineas)
    return total


def reemplazar(texto: str, rs: list, cuenta: dict) -> str:
    for a, b in rs:
        texto, k = re.subn(r"(?<![\w])" + re.escape(a) + r"(?![\w])", b, texto)
        if k:
            cuenta[a] = cuenta.get(a, 0) + k
    return texto


PIE_INTERFAZ = re.compile(r"^\s*(\d+\s*%?|\d+\s*mins?\s+restante.*|.*velocidad de lectura.*|.*restante\(s\).*)\s*$", re.I)


def _palabras(linea: str) -> frozenset:
    return frozenset(w for w in re.findall(r"[a-záéíóúñü]{3,}", re.sub(r"<[^>]+>", " ", linea).lower()))


def sin_interfaz(html: str) -> tuple[str, int]:
    """Quita el encabezado corrido y los pies de interfaz (Kindle: «12 min restantes 26 %») que el OCR mete en cada página.
    Encabezado corrido = primera línea cuyas palabras coinciden en más de la mitad con una primera línea que se repite en
    al menos el 20 % de las páginas (y 5 como mínimo); así valen las variantes con que el traductor la fue vertiendo."""
    secs = list(re.finditer(r'(<div class="solo">)(.*?)(</div>)', html, re.S))
    lineas_por_sec = [re.split(r"<br\s*/?>", m.group(2)) for m in secs]
    firmas: dict = {}
    for lineas in lineas_por_sec:
        if lineas and _palabras(lineas[0]):
            firmas[_palabras(lineas[0])] = firmas.get(_palabras(lineas[0]), 0) + 1
    corridas = [f for f, n in firmas.items() if len(f) >= 3 and n >= 5 and n >= 0.2 * len(secs)]

    def es_corrida(linea: str) -> bool:
        w = _palabras(linea)
        return len(w) >= 2 and any(len(w & f) / min(len(w), len(f)) >= 0.6 for f in corridas)
    out, ultimo, quitadas = [], 0, 0
    for m, lineas in zip(secs, lineas_por_sec):
        if lineas and es_corrida(lineas[0]):
            lineas, quitadas = lineas[1:], quitadas + 1
        while lineas and PIE_INTERFAZ.match(re.sub(r"<[^>]+>", "", lineas[-1])):
            lineas, quitadas = lineas[:-1], quitadas + 1
        out.append(html[ultimo:m.start(2)] + "<br/>".join(lineas))
        ultimo = m.end(2)
    out.append(html[ultimo:])
    return "".join(out), quitadas


def pulir(html: str, rs: list, arabe: bool, hebreo: bool = False, latin_ext: bool = False,
          indice: frozenset = frozenset(), interfaz: bool = False) -> tuple[str, dict, int]:
    cuenta: dict = {}
    if interfaz:
        html, n = sin_interfaz(html)
        if n:
            cuenta["líneas de interfaz quitadas"] = n
    soup = BeautifulSoup(html, "html.parser")
    quitadas = 0
    for nodo in list(soup.find_all(string=True)):
        if not isinstance(nodo, NavigableString) or nodo.parent.name in SALTAR:
            continue
        t = str(nodo)
        nuevo = reemplazar(t, rs, cuenta) if rs else t
        segs = segmentos_hebreo(nuevo) if hebreo else [("t", nuevo)]
        unidos: list[tuple[str, str]] = []
        for tipo, txt in segs:
            if tipo == "t" and unidos and unidos[-1][0] == "t":
                unidos[-1] = ("t", unidos[-1][1] + txt)
            else:
                unidos.append((tipo, txt))
        segs = unidos
        if arabe:
            for k, (tipo, txt) in enumerate(segs):
                if tipo == "t":
                    limpio, n = sin_mojibake(txt)
                    if latin_ext:
                        limpio, m = sin_corridas_latinas(limpio)
                        n += m
                    segs[k] = ("t", limpio)
                    quitadas += n
        if hebreo and any(tipo == "h" for tipo, _ in segs):
            cuenta["hebreo recuperado"] = cuenta.get("hebreo recuperado", 0) + sum(tipo == "h" for tipo, _ in segs)
            frag = "".join(f"<span dir='rtl' lang='he'>{txt}</span>" if tipo == "h" else _html.escape(txt, quote=False)
                           for tipo, txt in segs)
            nodo.replace_with(BeautifulSoup(frag, "html.parser"))
        elif "".join(txt for _, txt in segs) != t:
            nodo.replace_with("".join(txt for _, txt in segs))
    if indice:
        cuenta["entradas de índice"] = indice_en_lineas(soup, set(indice))
    return str(soup), cuenta, quitadas


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("html")
    ap.add_argument("--reemplazos", default="")
    ap.add_argument("--sin-mojibake", action="store_true")
    ap.add_argument("--hebreo", action="store_true", help="recupera el hebreo en mojibake cp1255 en vez de borrarlo")
    ap.add_argument("--latin-ext", action="store_true", help="borra corridas de letras latinas extendidas (árabe roto)")
    ap.add_argument("--indice", default="", help="páginas de índice con entradas numeradas pegadas (p. ej. 2,3)")
    ap.add_argument("--interfaz", action="store_true", help="quita el encabezado corrido y los pies de interfaz (Kindle) de cada página")
    ap.add_argument("--aplicar", action="store_true")
    a = ap.parse_args()
    with open(a.html, encoding="utf-8") as f:
        html = f.read()
    nuevo, cuenta, quitadas = pulir(html, reglas(a.reemplazos) if a.reemplazos else [], a.sin_mojibake, a.hebreo, a.latin_ext,
                                 frozenset(int(x) for x in a.indice.split(",") if x), a.interfaz)
    for k, v in sorted(cuenta.items(), key=lambda kv: -kv[1]):
        print(f"   {k}: {v}")
    print(f"{os.path.basename(a.html)}: {sum(cuenta.values())} reemplazos, {quitadas} fichas árabes quitadas")
    if a.aplicar and nuevo != html:
        respaldo = a.html + ".pulir"
        if not os.path.exists(respaldo):
            shutil.copy2(a.html, respaldo)
        escribir_atomico(a.html, nuevo)
        print(f"✔ reescrito {a.html} (respaldo: {respaldo})")


if __name__ == "__main__":
    main()
