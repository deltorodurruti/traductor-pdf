"""Maqueta la traducción solo-español HOJA A HOJA: una hoja por página del original.

Entrada: HTML con <section class="page"> (el solo-español de _verify_book.py, el
render --solo, o el bilingüe: de este se toma solo la columna traducida).
Salida: PDF donde la hoja N lleva "Página N" arriba y el texto de esa página del
original; el tamaño de letra se reduce por hoja (hasta MIN_PT) para que quepa.
Si aun así no cabe, se encoge la imagen; y si tampoco, la hoja se deja correr a una
segunda hoja (NUNCA se recorta texto) y se avisa.

Limpieza automática (se desactiva con --sin-limpiar):
  - encabezado corrido: el título del libro que el OCR repite al inicio de cada página;
  - folio: el número de página que queda pegado al final del último párrafo;
  - la sección de fuentes y términos del traductor, que no es parte del libro
    (se conserva con --con-fuentes).
Con --original libro.pdf se recortan del original las figuras (diagramas, símbolos,
láminas) y se colocan entre los párrafos (ver figuras.py).

Uso: python hojas.py libro_es.html [salida.pdf] [ancho_in alto_in] [--original libro.pdf]
                     [--solo-imagen 1,2] [--con-fuentes] [--sin-limpiar] [--sin-cabecera] [--corrido]
--sin-cabecera: no imprime el rótulo «Página N» de cada hoja (el número sale del orden de las páginas del HTML).
--corrido: el texto fluye y llena la hoja, como en un libro, en vez de una hoja por página del
  original. Se cosen los párrafos que el original parte entre páginas. Se pierde la correspondencia
  exacta hoja↔página del original, que es la que sirve para citar.
--solo-imagen: esas páginas (portada, láminas) salen como imagen del original, sin texto OCR (requiere --original).
"""
from __future__ import annotations

import difflib
import html as _html
import os
import re
import statistics
import subprocess
import sys
import unicodedata

from bs4 import BeautifulSoup

MARGEN_IN = 0.85
BASE_PT, MIN_PT = 12.0, 9.5
FORMATO = "4"
OCR_LARGO = 300
SIMILITUD_ENCABEZADO = 0.72

CSS = """
:root{ --fg:#111; --muted:#777; --rule:#bbb; --accent:#7a5424; }
*{ box-sizing:border-box; }
@page{ size:%(W)sin %(H)sin; margin:%(M)sin; }
html{ background:#fff; }
body{ margin:0; width:%(WU)spx; background:#fff; color:var(--fg); font-family:Georgia,'Times New Roman',serif;
      font-size:%(BASE)spt; line-height:1.52; }
.hoja{ min-height:%(ALTO_HOJA)spx; break-after:%(CORTE)s; page-break-after:%(CORTE_VIEJO)s; }
.hoja:last-of-type{ break-after:auto; page-break-after:auto; }
#informe{ display:none; }
.num{ text-align:center; color:var(--muted); font-size:.72em; letter-spacing:.18em;
      text-transform:uppercase; border-bottom:1px solid var(--rule); padding-bottom:4px;
      margin-bottom:12px; }
/* párrafos separados por aire, sin sangría.
   orphans/widows: no dejar una línea suelta colgando al pie ni al principio de la hoja. */
.cuerpo p{ margin:0 0 .75em; text-align:justify; hyphens:auto; -webkit-hyphens:auto;
           orphans:2; widows:2; }
/* un título no se queda solo al final de la hoja: arrastra consigo lo que viene detrás */
.cuerpo p.tit{ break-after:avoid; page-break-after:avoid; break-inside:avoid; }
/* la regla horizontal del original, fina y discreta */
.cuerpo hr{ border:0; border-top:1px solid var(--rule); width:58%%; margin:1.1em auto; }
/* la llamada de nota, volada y pequeña, sin alterar el interlineado */
.cuerpo sup{ font-size:.68em; line-height:0; vertical-align:super; color:var(--muted);
             padding-left:.06em; }
/* el escaneo de una página entera (portadas, láminas) va en su propia hoja: encajarlo
   entre el texto hace que Chrome, en corrido, no lo coloque y lo pierda */
.cuerpo img.escaneo{ break-before:page; page-break-before:always;
                     break-after:page; page-break-after:always; }
/* tablas y figuras no se parten por la mitad. En las imágenes NO se pone break-inside:avoid:
   con él, una lámina que no cabe en lo que queda de hoja Chrome la descarta en vez de bajarla. */
.cuerpo table, .cuerpo figure{ break-inside:avoid; page-break-inside:avoid; }
.cuerpo p.tit{ text-align:center; font-weight:bold; letter-spacing:.04em; margin:.9em 0 .7em; }
.cuerpo img{ max-width:100%%; max-height:%(IMG_MAX)spx; height:auto; display:block;
             margin:.6em auto; }
.cuerpo img.escaneo{ max-height:%(IMG)spx; }
.cuerpo img.fig{ max-height:%(IMG)spx; }
.cuerpo p.warn{ color:#a8452a; font-style:italic; text-align:left; }
.cuerpo table{ border-collapse:collapse; margin:.8em auto; }
.cuerpo caption{ font-weight:bold; letter-spacing:.04em; margin-bottom:.5em; }
.cuerpo th,.cuerpo td{ padding:.2em .5em; text-align:left; border:1px solid var(--rule); }
.cuerpo th{ font-size:.85em; color:var(--muted); font-style:italic; font-weight:normal; }
a.term{ color:var(--accent); text-decoration:none; border-bottom:1px dotted var(--accent); }
.refs{ font-size:.85em; }
.refs h2{ font-size:1.2em; margin:0 0 .6em; }
.ref{ margin:.5em 0; }
.ref .t{ font-weight:bold; color:var(--accent); }
.desborde .num::after{ content:" · continúa"; }
"""

JS = """
window.addEventListener('load', function(){
  var LIM = %(ALTO)s, base = %(BASE)s, min = %(MIN)s, out = [], CORRIDO = %(CORRIDO)s;
  // En corrido el texto fluye entre hojas: encoger la letra por sección deja párrafos de
  // tamaños distintos en la misma página, que es justo lo que se ve mal.
  if (CORRIDO){
    var d0 = document.createElement('div'); d0.id = 'informe';
    d0.setAttribute('data-desborde', ''); d0.setAttribute('data-encogidas', '0');
    document.body.appendChild(d0); return;
  }
  document.querySelectorAll('.hoja[data-n]').forEach(function(h){
    var c = h.querySelector('.cuerpo'), fs = base;
    var imgs = c.querySelectorAll('img');
    function sobra(){ return h.scrollHeight > LIM; }
    while (sobra() && fs > min){ fs -= .25; c.style.fontSize = fs + 'pt'; }
    var mh = %(IMG)s;
    while (sobra() && imgs.length && mh > 80){ mh *= .85;
      imgs.forEach(function(i){ i.style.maxHeight = mh + 'px'; }); }
    if (sobra()){ h.classList.add('desborde'); out.push(h.dataset.n); }
    h.dataset.fs = fs;
  });
  var d = document.createElement('div'); d.id = 'informe';
  d.setAttribute('data-desborde', out.join(','));
  var enc = 0; document.querySelectorAll('.hoja[data-n]').forEach(function(h){
    if (parseFloat(h.dataset.fs) < base) enc++; });
  d.setAttribute('data-encogidas', enc);
  document.body.appendChild(d);
});
"""

_TIT = re.compile(r"[^\W\d_]", re.U)
FOLIO = re.compile(r"(?:(?<=\s)|^)\s*(?:[-–—‐‑]\s*)?(?:\d+|[ivxlc]+)(?:\s*[-–—‐‑])?\s*$", re.I)
FOLIO_INICIO = re.compile(r"^\s*[•·]\s*(?:\d{1,4}|[ivxlc]+)\s*[•·]\s*", re.I)
FOLIO_INICIO_NUM = re.compile(r"^\s*\d{1,4}(?=\s+[a-záéíóúñ]|\s*$)")
NO_FOLIO = re.compile(r"[=+×·*/:^]\s*(?:\d+|[ivxlcdm]+)[.)]?\s*$", re.I)


def _es_titulo(txt: str) -> bool:
    t = txt.strip()
    if not t or len(t) > 80 or t.endswith((".", ",", ";")):
        return False
    letras = _TIT.findall(t)
    return bool(letras) and sum(c.isupper() for c in letras) / len(letras) > 0.6


def es_solo(html_path: str) -> bool:
    """True si el HTML es de traducción sola (secciones de página, sin columna original)."""
    with open(html_path, encoding="utf-8") as f:
        s = f.read()
    return 'class="page"' in s.replace("'", '"') and 'col src' not in s


def _norm(t: str) -> str:
    return re.sub(r"\W+", " ", t.lower()).strip()


def detectar_encabezado(primeros: list[str], k_max: int = 9, minimo: float = 0.3,
                        n_total: int | None = None) -> list[str] | None:
    """Encabezado corrido: las palabras con que empieza, de forma difusa (el OCR y la traducción lo
    escriben distinto), al menos el 30 % de las páginas, O con un folio que avanza con ellas (ver
    `_folio_avanza`). `primeros` es el texto inicial de cada página. Devuelve las palabras del
    encabezado de referencia, o None si no hay."""
    n = len(primeros)
    if n < 6:
        return None
    n_total = n_total or n
    toks = [t.split()[:k_max + 2] for t in primeros]
    paso = max(1, n // 25)
    candidatos = []
    for k in range(k_max, 1, -1):
        for ref in toks[::paso]:
            if len(ref) < k:
                continue
            r = [_norm(x) for x in ref[:k]]
            casan = [i for i, t in enumerate(toks)
                     if len(t) >= k and _palabras_parecidas(r, [_norm(x) for x in t[:k]])]
            sup = len(casan)
            if sup >= 4 and (sup >= minimo * n_total or _folio_avanza(toks, casan, r)):
                candidatos.append((sup, k, ref[:k]))
    if not candidatos:
        return None
    tope = max(s for s, _, _ in candidatos)
    return max((c for c in candidatos if c[0] >= 0.9 * tope), key=lambda c: (c[1], c[0]))[2]


def _folio_avanza(toks: list[list[str]], casan: list[int], r: list[str]) -> bool:
    """¿El número del encabezado crece más o menos una unidad por página? Entonces es un folio, y el
    encabezado es corrido aunque esté en pocas páginas. Un «Capítulo N» cada diez páginas avanza a
    0,1 por página y las notas al pie partidas («1 03 Un tratado…») a seis: ninguno pasa."""
    pos = next((j for j, x in enumerate(r) if x.isdigit()), None)
    if pos is None or len(casan) < 4 or not any(x.isalpha() for x in r):
        return False
    nums = [(i, int(_norm(toks[i][pos]))) for i in casan if _norm(toks[i][pos]).isdigit()]
    if len(nums) < 4:
        return False
    (i0, n0), (i1, n1) = nums[0], nums[-1]
    pendiente = (n1 - n0) / max(1, i1 - i0)
    crece = sum(1 for (_, a), (_, b) in zip(nums, nums[1:]) if b > a)
    return 0.4 <= pendiente <= 2.5 and crece >= 0.8 * (len(nums) - 1)


def _folio_numerico(primeros: list[str]) -> bool:
    """¿Cada página empieza con un folio desnudo (12, 13, 14…) que avanza una unidad por página?

    El detector de encabezados solo mira headers de dos o más palabras, así que un número suelto se
    le escapa y queda al inicio del cuerpo. Aquí se decide a nivel de LIBRO: se exige que el número
    esté al inicio de muchas páginas y que crezca página a página, la firma de un folio y no de un
    verso o un número de nota (que ni está en todas las páginas ni avanza de a uno)."""
    nums = []
    for i, p in enumerate(primeros):
        m = re.match(r"\s*(\d{1,4})(?=\s|$)", p or "")
        if m:
            nums.append((i, int(m.group(1))))
    if len(nums) < max(6, 0.5 * len(primeros)):
        return False
    (i0, n0), (i1, n1) = nums[0], nums[-1]
    pendiente = (n1 - n0) / max(1, i1 - i0)
    seguidos = sum(1 for (_, a), (_, b) in zip(nums, nums[1:]) if b == a + 1)
    return 0.7 <= pendiente <= 1.3 and seguidos >= 0.85 * (len(nums) - 1)


def _palabras_parecidas(a: list[str], b: list[str]) -> bool:
    """Cada palabra de `a` se parece a la de `b` en su posición (el OCR cambia letras, no palabras).

    Los números son comodín: el encabezado corrido lleva el folio, que cambia en cada página, y
    compararlo letra a letra hacía que «LIBRO UNO 69» y «LIBRO UNO 70» no se reconocieran como el
    mismo encabezado. Por eso se colaban dentro del texto.
    """
    return all(x.isdigit() and y.isdigit() or x == y or difflib.SequenceMatcher(None, x, y).ratio() >= 0.5
               for x, y in zip(a, b))


def detectar_encabezados(primeros: list[str], maximo: int = 4) -> list[list[str]]:
    """Todos los encabezados corridos del libro, no solo el más repetido.

    Un libro partido en secciones cambia de encabezado a mitad («LIBRO UNO 69», «LIBRO DOS 12»), y
    buscando uno solo ninguno llegaba al umbral: se quedaban todos dentro del texto. Aquí se detecta
    el más frecuente, se apartan las páginas que ya cubre, y se vuelve a buscar sobre el resto.
    """
    refs, resto = [], [p for p in primeros if p]
    n_total = len(resto)
    for _ in range(maximo):
        if len(resto) < 6:
            break
        ref = detectar_encabezado(resto, minimo=0.25, n_total=n_total)
        if not ref:
            break
        refs.append(ref)
        r = [_norm(x) for x in ref]
        k = len(r)
        resto = [p for p in resto
                 if not (len(p.split()) >= k
                         and _palabras_parecidas(r, [_norm(x) for x in p.split()[:k]]))]
    return refs


def quitar_encabezado(texto: str, ref: list[str]) -> str:
    """Quita del inicio de `texto` el encabezado, aunque tenga una palabra más o menos que `ref`."""
    toks = texto.split()
    k, r = len(ref), _norm(" ".join(ref))
    mejor_j, mejor_r = 0, SIMILITUD_ENCABEZADO
    for j in range(max(1, k - 2), min(len(toks), k + 2) + 1):
        s = difflib.SequenceMatcher(None, r, _norm(" ".join(toks[:j]))).ratio()
        if s > mejor_r:
            mejor_j, mejor_r = j, s
    return " ".join(toks[mejor_j:]) if mejor_j else texto


def quitar_folio(texto: str) -> str:
    """Quita el número de página (-5-, 36-, -ii-) pegado al final de un párrafo.
    No toca un número que sea un valor (gematría «= 3», razón «3:1»): ahí no hay folio."""
    if NO_FOLIO.search(texto):
        return texto.rstrip()
    return FOLIO.sub("", texto).rstrip()


def _items(sec) -> tuple[list[tuple[str, str]], str | None]:
    """([(tipo, contenido)], src del escaneo): t=texto, img=figura, w=aviso."""
    items, scan = [], None
    for el in sec.find_all(["div", "figure", "p", "table"], recursive=False):
        cls = el.get("class") or []
        if "page-num" in cls:
            continue
        if "scan" in cls:
            im = el.find("img")
            scan = im.get("src") if im else None
        elif "row" in cls:
            t = el.select_one(".col.tgt")
            if t:
                for l in t.select(".lbl"):
                    l.decompose()
                items.append(("t", _quitar_marcadores_figura(t.decode_contents())))
        elif "solo" in cls:
            if not any(getattr(child, "name", None) == "figure" for child in el.contents):
                items.append(("t", _quitar_marcadores_figura(el.decode_contents())))
            else:
                texto = []
                for child in el.contents:
                    if getattr(child, "name", None) == "figure":
                        raw = "".join(str(x) for x in texto)
                        if _texto(raw):
                            items.append(("t", _quitar_marcadores_figura(raw)))
                        texto = []
                        im = child.find("img")
                        if im and im.get("src"):
                            items.append(("img", im["src"]))
                    elif getattr(child, "name", None) == "p":
                        raw = child.decode_contents()
                        if _texto(raw):
                            items.append(("t", _quitar_marcadores_figura(raw)))
                    else:
                        texto.append(child)
                raw = "".join(str(x) for x in texto)
                if _texto(raw):
                    items.append(("t", _quitar_marcadores_figura(raw)))
        elif el.name == "table":
            items.append(("tbl", str(el)))
        elif el.name == "figure":
            im = el.find("img")
            if im and im.get("src"):
                items.append(("img", im["src"]))
        elif "warn" in cls:
            items.append(("w", el.decode_contents()))
    return items, scan


def _texto(v: str) -> str:
    return BeautifulSoup(v, "html.parser").get_text(" ", strip=True)


def _limpiar(items: list[tuple[str, str]], refs: list[list[str]] | list[str] | None,
             folio_num: bool = False) -> list[tuple[str, str]]:
    """Encabezado corrido al inicio del primer texto y folio al final del último."""
    idx = [i for i, (k, _) in enumerate(items) if k == "t"]
    if not idx:
        return items
    items = list(items)
    if refs:
        lista = refs if refs and isinstance(refs[0], list) else [refs]
        i = idx[0]
        t = _texto(items[i][1])
        for ref in lista:
            t = quitar_encabezado(t, ref)
        if "<br" in items[i][1].lower():
            raw = items[i][1]
            first, *rest = re.split(r"(<br\s*/?>)", raw, flags=re.I)
            for ref in lista:
                first = re.sub(r"^\s*(?:" + "\\s+".join(map(re.escape, ref)) + r")\s*", "", first, count=1, flags=re.I)
            items[i] = ("t", first + "".join(rest))
        else:
            items[i] = ("t", _html.escape(t, quote=False))
    i = idx[0]
    t = _texto(items[i][1])
    if FOLIO_INICIO.match(t):
        if "<br" in items[i][1].lower():
            items[i] = ("t", FOLIO_INICIO.sub("", items[i][1], count=1))
        else:
            items[i] = ("t", _html.escape(FOLIO_INICIO.sub("", t), quote=False))
    if folio_num:
        i = idx[0]
        t = _texto(items[i][1])
        if FOLIO_INICIO_NUM.match(t):
            if "<br" in items[i][1].lower():
                items[i] = ("t", FOLIO_INICIO_NUM.sub("", items[i][1], count=1))
            else:
                items[i] = ("t", _html.escape(FOLIO_INICIO_NUM.sub("", t, count=1).lstrip(), quote=False))
    i = idx[-1]
    t_ultimo = _texto(items[i][1])
    if FOLIO.search(t_ultimo) and not NO_FOLIO.search(t_ultimo):
        items[i] = ("t", FOLIO.sub("", items[i][1]) if "<br" in items[i][1].lower()
                    else _html.escape(quitar_folio(t_ultimo), quote=False))
    return [it for it in items if not (it[0] == "t" and not _texto(it[1]))]


BR = re.compile(r"<br\s*/?>", re.I)
FIN_FRASE = re.compile(r"[.!?:;»\"”’')\]…]\s*$")
CONTINUACION = re.compile(r"^[a-záéíóúüñ]")
FICHA_FIN = re.compile(
    r"(\bque\s+(?:gobierna|comanda)\s+\d+\s+capítulos\.?)"
    r"(?:\s|<br\s*/?>)+(?=[A-ZÁÉÍÓÚÜÑ¿¡])", re.I
)
FICHA = re.compile(r"\b(?:gobierna|comanda)\s+\d+\s+capítulos\.?\s*$", re.I)
FICHA_MARCA = "\x00FICHA\x00"
ENTRADA = re.compile(r"^[A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ'\-]{2,}\b")
REGLA = re.compile(r"[_–—-]{6,}")
NOTA_PEGADA = re.compile(
    r"(?<=[a-záéíóúüñA-ZÁÉÍÓÚÜÑ]{2})(\d{1,3})|(?<=\b[yoaeu])(\d{1,3})"
    r"(?![\d:/°ºª-])"
    r"(?![.,]\d)"
    r"(?![a-záéíóúüñA-ZÁÉÍÓÚÜÑ])")


def _partir_hasta(trozos: list[str], objetivo: int) -> list[str]:
    """Junta los trozos hasta dejar exactamente `objetivo` párrafos, cortando por los mejores sitios.

    Un corte vale más cuanto más claro es: después de un punto final, antes de una entrada en
    mayúsculas, y con texto suficiente detrás. Los demás saltos se cosen, que es lo que son: líneas
    partidas por el ancho de la página del original.
    """
    if objetivo <= 1:
        return ["<br/>".join(trozos)]
    if len(trozos) <= objetivo:
        return trozos
    puntuados = []
    for i in range(1, len(trozos)):
        antes, despues = _texto(trozos[i - 1]), _texto(trozos[i])
        pts = 0
        if FIN_FRASE.search(antes):
            pts += 3
        if ENTRADA.match(despues):
            pts += 2
        if _es_titulo(despues) or _es_titulo(antes):
            pts += 2
        if len(antes) > 120:
            pts += 1
        puntuados.append((pts, i))
    cortes = sorted(i for _, i in sorted(puntuados, reverse=True)[:objetivo - 1])
    salida, ini = [], 0
    for c in cortes + [len(trozos)]:
        salida.append("<br/>".join(trozos[ini:c]))
        ini = c
    return [s for s in salida if s.strip()]


def _tipografia(v: str) -> str:
    """Arregla lo que el escaneo dejó mal plantado: las reglas y las llamadas de nota.

    Las reglas horizontales del original salen como una tirada de guiones bajos dentro del texto, y
    las llamadas de nota aparecen pegadas a la palabra («Inteligencia8») en vez de voladas.
    """
    v = REGLA.sub("<hr>", v)
    v = re.sub(r"(?:<br/>)?\s*[_–—-]{1,5}\s*(?=<br/>|<hr>|$)", "", v)
    v = re.sub(r"(<hr>\s*(?:<br/>\s*)?){2,}", "<hr>", v)
    v = _limpiar_texto_tipografico(v)
    return NOTA_PEGADA.sub(lambda m: f"<sup>{m.group(1) or m.group(2)}</sup>", v)


DUPLICADO_FUNCIONAL = re.compile(
    r"\b(a|de|la|el|los|las|un|una|y|o|en|que|se|lo|al|del|con|por|para)\s+\1\b"
)


def _limpiar_texto_tipografico(v: str) -> str:
    """Corrige espacios y duplicados solo en texto, sin tocar atributos HTML."""
    v = re.sub(r"(?<=[\w)])\s+(?=(?:<[^>]+>\s*)?(?:[,;:)]|\.(?![.\d])))", "", v)
    v = re.sub(r"(\()\s+(?=(?:<[^>]+>\s*)?\S)", r"\1", v)
    partes = re.split(r"(<[^>]*>)", v)
    for i, parte in enumerate(partes):
        if parte.startswith("<"):
            continue
        parte = re.sub(r"(?<=[\w)])\s+([,;:)]|\.(?![.\d]))", r"\1", parte)
        parte = re.sub(r"(?m)(?<!^)(?<!\n)\s+([,;])", r"\1", parte)
        parte = re.sub(r"(\()\s+", r"\1", parte)
        partes[i] = DUPLICADO_FUNCIONAL.sub(r"\1", parte)
    return "".join(partes)


NOTA_FINAL = re.compile(r"(?<=[^\s\d])\d{1,3}$")
LINEA_LLENA = 80
METADATO = re.compile(r"\b(?:capítulos|gobierna|pronunciado|duque|rey|presidente)\b", re.I)
PARRAFO_MAYUSCULA = re.compile(r"^(?:Este|Esta|Estos|Estas|El|La|Los|Las|Se|No|Un|Una)\b")


def _parrafos(v: str, objetivo: int | None = None) -> list[str]:
    """Un bloque de página puede traer varios párrafos separados por <br/>. Devuelve uno por párrafo.

    El HTML de trabajo guarda la página entera en un solo bloque y marca los saltos con <br/>, así que
    maquetarlo tal cual daba un párrafo gigante sin separación: el texto salía "de corrido".

    Se decide EN CADA SALTO, no por bloque. Decidir por bloque fallaba por los dos lados: por la
    mediana de longitudes, un encabezado de capítulo (título + «Capítulo N» + capitular) pegado a un
    párrafo largo pasaba por verso y el párrafo salía en escalera; por la proporción de letras, un
    poema seguido de una instrucción, una tabla seguida de una llamada o un título seguido de su
    párrafo pasaban por prosa y se fundían. Medido sobre 1706 bloques de nueve libros: casi la mitad
    de las fusiones por bloque pegaban una línea corta, y de esas, veinte de cada veintidós eran
    títulos, encabezados, versos o filas de tabla.

    La regla: un salto se funde si la línea de antes está LLENA (≥ LINEA_LLENA letras: el salto es
    un retorno del escaneo) o si la siguiente empieza en minúscula y la frase sigue abierta. Una línea
    corta conserva su salto cuando introduce un título, verso, lista o celda.
    """
    ficha_cortada = bool(FICHA_FIN.search(v))
    v = FICHA_FIN.sub(lambda m: m.group(1) + FICHA_MARCA, v)
    trozos = [x.strip() for x in BR.split(v) if _texto(x).strip()]
    if len(trozos) < 2 and FICHA_MARCA not in v:
        return [v]
    if objetivo is not None:
        return _partir_hasta(trozos, objetivo)
    parrafos, lineas = [], [trozos[0]]
    for n, x in enumerate(trozos[1:], 1):
        prev = lineas[-1]
        tp = NOTA_FINAL.sub("", _texto(prev)).rstrip()
        siguiente = _texto(x).lstrip()
        llena = len(tp) >= LINEA_LLENA
        separa_metadato = (len(tp) < 120 and METADATO.search(tp)
                           and PARRAFO_MAYUSCULA.match(_texto(x)))
        if ficha_cortada and n == 1:
            parrafos.append(lineas)
            lineas = [x]
        elif separa_metadato:
            parrafos.append(lineas)
            lineas = [x]
        elif (CONTINUACION.match(siguiente) and not FIN_FRASE.search(tp)
              and not separa_metadato):
            sep = "" if prev.rstrip().endswith("-") else " "
            lineas[-1] = prev.rstrip().rstrip("-") + sep + x
        elif llena and not FIN_FRASE.search(tp) and not ENTRADA.match(_texto(x)):
            sep = "" if prev.rstrip().endswith("-") else " "
            lineas[-1] = prev.rstrip().rstrip("-") + sep + x
        elif llena or len(_texto(x)) >= LINEA_LLENA:
            parrafos.append(lineas)
            lineas = [x]
        else:
            lineas.append(x)
    parrafos.append(lineas)
    salida = []
    for p in ("<br/>".join(x) for x in parrafos):
        salida.extend(x.strip() for x in p.split(FICHA_MARCA) if _texto(x).strip())
    return salida


def demo() -> None:
    """Autocomprobación de _parrafos() y del detector de encabezados, con bloques reales de libros
    entregados (y los casos que un revisor encontró rotos en una versión anterior)."""
    largo = ("ESTE ejercicio presenta una estrategia para organizar las tareas del día, prepara un cuaderno "
             "con una lista de prioridades y revisa cada actividad al terminar. Anota los resultados y "
             "guarda las observaciones para consultarlas después.")
    canto = ("PRIMER DATO, SEGUNDO DATO,<br/>LA MEDICIÓN INICIAL, TERCER DATO,<br/>"
             "CUARTO DATO, QUINTO DATO, EN TODAS LAS SERIES.<br/>SEXTO DATO, SÉPTIMO DATO.")
    tabla = ("o en las horas 3.ª y 4.ª de la noche.<br/>Entre las horas 11.ª y 12.ª.<br/>"
             "SECTOR A (Grupo 1)<br/>Lunes<br/>Entre las horas 9.ª y 10.ª de la noche.<br/>"
             "KORVAX. PLUMBATAX o ZORKAMEL.<br/>Martes")
    P = _parrafos
    assert P(f"LIBRO UNO 77<br/>El manual de campo<br/>Capítulo 17<br/>{largo}") == \
        ["LIBRO UNO 77<br/>El manual de campo<br/>Capítulo 17", largo]
    assert P(f"Capítulo 3<br/>{largo}") == ["Capítulo 3", largo]
    assert P(f"Una chispa solar de luz y fuego<br/>Alex Example<br/>{largo}") == \
        ["Una chispa solar de luz y fuego<br/>Alex Example", largo]
    assert P(canto) == [canto] and P(tabla) == [tabla]
    assert P(f"{canto}<br/>{largo}") == [canto, largo]
    assert P(f"I LIL 16 LEA<br/>2 ARN 17 TAN<br/>3 ZOM 18 ZEN<br/>{largo}") == \
        ["I LIL 16 LEA<br/>2 ARN 17 TAN<br/>3 ZOM 18 ZEN", largo]
    l1 = "Esta es una línea llena del escaneo que no termina la frase y sigue en la de aba-"
    l2 = "jo con la misma frase, que tampoco termina aquí y continúa todavía una línea más"
    l3 = "hasta que por fin se cierra con un punto al final de este tercer renglón largo."
    assert P(f"{l1}<br/>{l2}<br/>{l3}") == [f"{l1[:-1]}{l2} {l3}"]
    f1 = "El informe resume los datos reunidos durante la revisión y presenta lo siguiente:47"
    f2 = "TABLA DE RESULTADOS Y MEDICIONES"
    assert P(f"{f1}<br/>{f2}") == [f1, f2]
    assert P(f"{l3}<br/>{l1}") == [l3, l1]

    palabras = "la casa el río una tarde el viento las nubes el camino la lluvia el mar".split()
    pags = [" ".join(palabras[(i * 3 + j) % len(palabras)] for j in range(9)) + " y sigue la prosa."
            for i in range(120)]
    for i in range(0, 120, 6):
        pags[i] = f"LIBRO UNO {40 + i} El texto de la página sigue aquí."
    for i in range(3, 120, 12):
        pags[i] = f"Capítulo {i // 12 + 1} El título del capítulo."
    for i in range(5, 120, 10):
        pags[i] = "EJERCICIO PRÁCTICO Siéntate y respira."
    refs = [[_norm(x) for x in r] for r in detectar_encabezados(pags)]
    assert ["libro", "uno"] in [r[:2] for r in refs], refs
    assert not any(r[0] in ("capítulo", "ejercicio") for r in refs), refs
    pags2 = ["EL LIBRO DE ORO " + pags[i] for i in range(40)] + pags[40:]
    assert [[_norm(x) for x in r[:4]] for r in detectar_encabezados(pags2)] == [["el", "libro", "de", "oro"]]
    print("demo OK · _parrafos distingue encabezado-de-capítulo de verso/tabla · el folio delata al encabezado corrido")


def _componer(items: list[tuple[str, str]], figs: list | None = None,
              objetivo: int | None = None) -> tuple[list[str], int]:
    """(párrafos HTML de la traducción, nº de letras de texto). Con `figs` (de figuras.py) las
    figuras del original se colocan entre los párrafos y se ignoran las imágenes del HTML."""
    if figs is not None:
        import figuras
        textos = [v for k, v in items if k == "t"]
        limpios = [figuras.quitar_cabeza(figuras.quitar_cola(_texto(t))) for t in textos] if figs else textos
        letras = sum(len(_texto(t)) for t in limpios)
        out = []
        for tipo, v in figuras.colocar([t for t in limpios if _texto(t)], figs):
            if tipo == "f":
                out.append(f"<img class='fig' src='{_html.escape(v, quote=True)}' alt='ilustración'>")
            else:
                txt = _texto(v)
                if _es_titulo(txt):
                    out.append(f"<p class='tit'>{_html.escape(txt, quote=False)}</p>")
                else:
                    out += [_parrafo_html(_escapar_figura(x))
                            for x in _parrafos(v) if _texto(x)]
        out += [f"<img class='fig' src='{_html.escape(v, quote=True)}' alt='ilustración'>"
                for k, v in items if k == "img"]
        return (out + [v for k, v in items if k == "tbl"]
                + [f"<p class='warn'>{v}</p>" for k, v in items if k == "w"]), letras
    out, letras = [], 0
    for kind, v in items:
        if kind == "t":
            txt = _texto(v)
            letras += len(txt)
            if txt:
                if _es_titulo(txt):
                    out.append(f"<p class='tit'>{v}</p>")
                else:
                    out += [_parrafo_html(x) for x in _parrafos(v, objetivo)]
        elif kind == "img":
            out.append(f"<img class='fig' src='{_html.escape(v, quote=True)}' alt='ilustración'>")
        elif kind == "tbl":
            out.append(v)
        else:
            out.append(f"<p class='warn'>{v}</p>")
    return out, letras


def _parrafo_html(v: str) -> str:
    clase = " class='ficha'" if FICHA.search(_texto(v)) else ""
    return f"<p{clase}>{_tipografia(v)}</p>"


def _escapar_figura(v: str) -> str:
    """Escapa texto proveniente de figuras sin perder los saltos de línea del original."""
    seguro = _html.escape(v, quote=False)
    return re.sub(r"&lt;br\s*/?&gt;", "<br/>", seguro, flags=re.I)



def _coser(hojas_cuerpos: list[list[str]]) -> list[list[str]]:
    """Une el último párrafo de cada página con el primero de la siguiente cuando la frase va cortada.

    El original parte frases al cambiar de página («…el Camino del Dragón no ofrece la posibilidad de
    volver atrás. Aquellos que» / «pretenden…»). Encadenando las páginas sin más, ese corte quedaría
    como dos párrafos distintos. Aquí se cosen: el texto vuelve a ser uno.
    """
    salida = [list(h) for h in hojas_cuerpos]
    for i in range(len(salida) - 1):
        if not salida[i] or not salida[i + 1]:
            continue
        ult, sig = salida[i][-1], salida[i + 1][0]
        if not (ult.startswith("<p>") and sig.startswith("<p>")):
            continue
        txt_ult, txt_sig = _texto(ult), _texto(sig)
        if not txt_ult or not txt_sig:
            continue
        if not FIN_FRASE.search(txt_ult) and CONTINUACION.match(txt_sig):
            union = ult[:-4].rstrip()
            resto = sig[3:]
            sep = "" if union.endswith("-") else " "
            unido = union.rstrip("-") + sep + resto if union.endswith("-") else union + sep + resto
            salida[i][-1] = _tipografia(unido)
            salida[i + 1] = salida[i + 1][1:]
    return salida


def _pagina_como_imagen(pag, dpi: int = 110) -> str:
    """La página del original tal cual (JPEG como data URI): para portadas y láminas sin texto que traducir."""
    import base64
    return "data:image/jpeg;base64," + base64.b64encode(pag.get_pixmap(dpi=dpi).tobytes("jpeg")).decode()


LIBRO_CSS = """
@page{size:%(W)sin %(H)sin;margin:20mm 20mm 25mm 30mm;}
@page :left{margin-left:20mm;margin-right:30mm;}
@page :right{margin-left:30mm;margin-right:20mm;}
/* Las páginas preliminares conservan el folio en el índice. */
@page portada{size:%(W)sin %(H)sin;margin:0;@bottom-center{content:none;}}
@page portadilla{size:%(W)sin %(H)sin;margin:20mm 20mm 25mm 30mm;@bottom-center{content:none;}}
*{box-sizing:border-box}
html,body{margin:0;background:#fff;color:#17130f}
/* Interlineado medido en libros reales: 1.15-1.35. */
body{font-family:Georgia,'Times New Roman',serif;font-size:10.8pt;line-height:1.3}
@page{@bottom-center{content:counter(page);font-family:Georgia,serif;font-size:9pt;color:#555;}}
.portada{page:portada;break-after:page;page-break-after:always;width:100%%;height:100vh;display:flex;align-items:center;justify-content:center}
.portada img{display:block;width:100%%;height:100%%;object-fit:contain}
.portadilla{page:portadilla;break-after:page;page-break-after:always;min-height:220mm;text-align:center;padding-top:45mm}
.portadilla h1{font-family:'Times New Roman',serif;font-size:30pt;line-height:1.1;margin:0 0 16pt;letter-spacing:.04em}
.portadilla .autor{font-size:15pt;margin:0 0 12pt}
.portadilla .subtitulo{font-size:12pt;font-style:italic}
.indice{break-after:page;page-break-after:always}
.indice h2{font-family:'Times New Roman',serif;font-size:19pt;text-align:center;margin:0 0 18pt}
.entrada-indice{display:flex;gap:.45em;align-items:baseline;margin:.22em 0;line-height:1.25;break-inside:avoid;page-break-inside:avoid}
.entrada-indice a{color:inherit;text-decoration:none}
.entrada-indice.nivel-2{padding-left:1.5em}
.entrada-indice.nivel-3{padding-left:3em}
.entrada-indice::before{content:'';order:2;flex:1;border-bottom:1px dotted #888;transform:translateY(-.22em)}
.entrada-indice .puntos{order:2;letter-spacing:.12em;color:#888;}
.entrada-indice .pagina{order:3;min-width:2ch;text-align:right}
.cuerpo{max-width:none}
.cuerpo a{color:inherit;text-decoration:none;border:0}
.cuerpo p{margin:0 0 .62em;text-align:%(ALIGN)s;hyphens:%(HYPHENS)s;-webkit-hyphens:%(HYPHENS)s;hyphenate-limit-chars:8 4 4;-webkit-hyphenate-limit-chars:8 4 4;orphans:2;widows:2}
.entrada-cabecera{break-inside:avoid;page-break-inside:avoid;break-after:avoid;page-break-after:avoid}
.cuerpo p.titulo{font-family:'Times New Roman',serif;text-align:left;font-weight:bold;line-height:1.15;margin:1.4em 0 .75em;break-after:avoid;page-break-after:avoid;break-inside:avoid}
.cuerpo p.titulo-1{font-size:19pt;text-align:center;margin-top:0;break-before:page;page-break-before:always}
.cuerpo p.titulo-2{font-size:13pt;margin-top:1.1em}
.cuerpo p.titulo-3{font-size:12.2pt;font-weight:bold;margin-top:.9em}
.cuerpo p.ficha{margin-left:0;font-style:italic;font-variant:small-caps;text-align:left}
.cuerpo img{max-width:100%%;height:auto;display:block;margin:.7em auto;break-inside:avoid;page-break-inside:avoid}
.cuerpo img.fig{display:block;max-width:100%%;max-height:80vh;margin:.7em auto;break-inside:avoid;page-break-inside:avoid}
.cuerpo img.escaneo{display:block;max-width:100%%;max-height:92vh;margin:.4em auto;break-inside:avoid;page-break-inside:avoid}
.cuerpo hr{border:0;border-top:1px solid #aaa;margin:1em auto;width:58%%}
.cuerpo table{border-collapse:collapse;margin:.8em auto;break-inside:avoid}
.cuerpo th,.cuerpo td{padding:.2em .5em;border:1px solid #aaa}
.libro-seccion{break-inside:auto}
.refs{font-size:9.5pt;break-before:page;page-break-before:always}
.refs h2{font-family:'Times New Roman',serif;font-size:16pt}
.refs .ref{font-style:italic}
"""


def _norm_titulo(v: str) -> str:
    return re.sub(r"\W+", " ", BeautifulSoup(v, "html.parser").get_text(" ", strip=True).lower()).strip()


def _trozos_seccion(sec) -> list[str]:
    out = []
    for el in sec.select(".solo, .col.tgt"):
        for raw in BR.split(_quitar_marcadores_figura(el.decode_contents())):
            t = _texto(raw)
            if t:
                out.append(t)
    return out


FIGURA_MARCADOR = re.compile(r"^\[fig[uú]ra:\s*[^\]]+\]$", re.I)


def _quitar_marcadores_figura(raw: str) -> str:
    partes = BR.split(raw)
    limpias = [parte for parte in partes if not FIGURA_MARCADOR.fullmatch(_texto(parte))]
    return raw if len(limpias) == len(partes) else "<br/>".join(limpias)


def _norm_titulo_manual(v: str) -> str:
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", v)
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"[^\w]+", " ", sin_tildes.casefold(), flags=re.UNICODE).strip()


def _leer_titulos_tsv(ruta: str) -> list[dict] | None:
    if not os.path.exists(ruta):
        return None
    salida = []
    with open(ruta, encoding="utf-8") as archivo:
        for numero, linea in enumerate(archivo, 1):
            if not linea.strip() or linea.lstrip().startswith("#"):
                continue
            columnas = linea.rstrip("\r\n").split("\t")
            if len(columnas) >= 2 and columnas[0].strip().casefold() == "nivel" \
                    and columnas[1].strip().casefold() == "texto":
                continue
            try:
                nivel = int(columnas[0])
                texto = columnas[1].strip()
            except (IndexError, ValueError):
                print(f"aviso: titulos.tsv línea {numero}: formato inválido", file=sys.stderr)
                continue
            if nivel not in (1, 2, 3) or not texto:
                print(f"aviso: titulos.tsv línea {numero}: nivel o texto inválido", file=sys.stderr)
                continue
            salida.append({"nivel": nivel, "texto": texto,
                           "suma": columnas[2].strip() if len(columnas) > 2 else "",
                           "linea": numero})
    return salida


def _titulos_manuales(soup, manual: list[dict], internos: bool = False) -> list[dict]:
    bloques = []
    for sec in soup.select("section.page"):
        pn = sec.select_one(".page-num")
        m = re.search(r"\d+", pn.get_text()) if pn else None
        pagina = int(m.group()) if m else len(bloques) + 1
        for texto in _trozos_seccion(sec):
            bloques.append((pagina, texto))
    salida = []
    desde = 0
    for fila in manual:
        buscado = _norm_titulo_manual(fila["texto"])
        suma = _norm_titulo_manual(fila.get("suma", ""))
        encontrado = None
        for i in range(desde, len(bloques)):
            if _norm_titulo_manual(bloques[i][1]).startswith(buscado):
                if suma and i + 1 >= len(bloques):
                    continue
                encontrado = i
                break
        if encontrado is None:
            print(f"aviso: titulos.tsv línea {fila.get('linea', '?')}: no se encontró «{fila['texto']}»",
                  file=sys.stderr)
            continue
        pagina, base = bloques[encontrado]
        partes = [base]
        if suma:
            partes.append(fila["suma"].strip())
        texto = fila["texto"] + (f": {fila['suma']}" if suma else "")
        salida.append({"nivel": fila["nivel"], "texto": texto,
                       "pagina_original": pagina, "y": 0,
                       "_partes": partes})
        desde = encontrado + len(partes)
    for i, titulo in enumerate(salida, 1):
        titulo["id"] = f"titulo-{i}"
        if not internos:
            titulo.pop("_partes", None)
    return salida


def _titulos_traducidos(soup, original: str | None,
                        titulos_manual: list[dict] | None = None) -> list[dict]:
    """Empareja títulos recuperados del PDF con sus bloques españoles de la misma página."""
    if titulos_manual is not None:
        return _titulos_manuales(soup, titulos_manual)
    if not original:
        salida = []
        for sec in soup.select("section.page"):
            pn = sec.select_one(".page-num")
            m = re.search(r"\d+", pn.get_text()) if pn else None
            trozos = _trozos_seccion(sec)
            for texto in trozos:
                if re.match(r"^(?:cap[ií]tulo|chapter)\b", texto, re.I) or re.match(r"^\d+[.)]\s+\S", texto):
                    nivel = 1 if not re.match(r"^\d+[.)]\s+\S", texto) else 3
                    salida.append({"nivel": nivel, "texto": texto,
                                   "pagina_original": int(m.group()) if m else len(salida) + 1,
                                   "y": 0, "id": f"titulo-{len(salida) + 1}"})
        return salida
    import estructura
    fuente = estructura.titulos_desde_pdf(original)
    por_pagina = {}
    for t in fuente:
        if t["pagina"] <= 4:
            continue
        por_pagina.setdefault(t["pagina"], []).append(t)
    traducidos = []
    for sec in soup.select("section.page"):
        pn = sec.select_one(".page-num")
        m = re.search(r"\d+", pn.get_text()) if pn else None
        if not m or int(m.group()) not in por_pagina:
            continue
        trozos = _trozos_seccion(sec)
        if not trozos:
            continue
        usados = set()
        fuentes = por_pagina[int(m.group())]
        for fuente_t in fuentes:
            candidato = None
            indice = None
            if fuente_t["nivel"] == 1:
                for i, x in enumerate(trozos):
                    if i not in usados and len(x) <= 120 and not re.search(r"[.!?]$", x):
                        candidato, indice = x, i
                        break
                if candidato is None:
                    for i, x in enumerate(trozos):
                        if i in usados:
                            continue
                        corte = re.search(r"\s(?=[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]{1,}\s)", x)
                        if corte and 8 <= len(x[:corte.start()].strip()) <= 80:
                            candidato, indice = x[:corte.start()].strip(), i
                            break
            elif fuente_t["nivel"] == 3:
                candidato = next((x for i, x in enumerate(trozos) if i not in usados
                                  and re.match(r"^\d+[.)]\s+\S", x)), None)
            else:
                if ":" in fuente_t["texto"]:
                    candidato = next((x for i, x in enumerate(trozos) if i not in usados and ":" in x
                                      and len(x.split(":", 1)[0]) <= 80), None)
                else:
                    candidato = next((x for i, x in enumerate(trozos) if i not in usados and len(x) <= 80
                                      and not re.search(r"[.!?]$", x)), None)
            if candidato is None:
                continue
            if indice is None:
                indice = trozos.index(candidato)
            usados.add(indice)
            if fuente_t["nivel"] == 3:
                m_titulo = re.match(r"^(\d+\.\s+[^:]*?(?:#\d+)?)(?:\s+|$)", candidato)
                if m_titulo:
                    candidato = m_titulo.group(1).strip()
            elif fuente_t["nivel"] == 2 and ":" in candidato:
                candidato = candidato.split(":", 1)[0].strip() + ":"
            traducidos.append({"nivel": fuente_t["nivel"], "texto": candidato,
                               "pagina_original": fuente_t["pagina"], "y": fuente_t["y"]})
    unicos, vistos = [], set()
    for t in traducidos:
        clave = (t["pagina_original"], _norm_titulo(t["texto"]), t["nivel"])
        if clave not in vistos:
            vistos.add(clave)
            t["id"] = f"titulo-{len(unicos) + 1}"
            unicos.append(t)
    return unicos


def _rellenar_indice(html: str, paginas: dict[str, int]) -> str:
    def quitar_entrada(m):
        if m.group(1) in paginas:
            return m.group(0)
        enlace = BeautifulSoup(m.group(0), "html.parser").select_one("a")
        nombre = enlace.get_text(" ", strip=True) if enlace else m.group(1)
        print(f"aviso: índice: no pude paginar «{nombre}»", file=sys.stderr)
        return m.group(0)

    html = re.sub(
        r"<div class='entrada-indice [^']*'>.*?data-target='([^']+)'[^>]*>.*?</div>",
        quitar_entrada, html, flags=re.S,
    )

    def reemplazo(m):
        if m.group(1) not in paginas:
            return m.group(0)
        return f"<span class='pagina' data-target='{m.group(1)}'>{paginas[m.group(1)]}</span>"
    return re.sub(r"<span class='pagina' data-target='([^']+)'>\d+</span>", reemplazo, html)


def _estabilizar_indice(html: str, medir, max_pasadas: int = 3) -> str:
    """Actualiza números del índice hasta que una pasada no cambie la paginación."""
    actual = html
    for _ in range(max(2, max_pasadas)):
        siguiente = _rellenar_indice(actual, medir(actual))
        if siguiente == actual and _ != 0:
            return actual
        actual = siguiente
    return actual


def _lineas_pdf(pagina) -> list[dict]:
    try:
        bloques = pagina.get_text("dict").get("blocks", [])
    except (AttributeError, TypeError):
        return [{"texto": x.strip(), "tam": 0, "negrita": False}
                for x in pagina.get_text().splitlines() if x.strip()]
    lineas = []
    for bloque in bloques:
        if bloque.get("type") != 0:
            continue
        for linea in bloque.get("lines", []):
            spans = [s for s in linea.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            lineas.append({
                "texto": "".join(s["text"] for s in spans).strip(),
                "tam": max(float(s.get("size", 0)) for s in spans),
                "negrita": any((s.get("flags", 0) & 16) or "Bold" in s.get("font", "")
                               for s in spans),
            })
    return lineas


def _pagina_de_titulos(pdf_path: str, titulos: list[dict]) -> dict[str, int]:
    import fitz
    import warnings
    doc = fitz.open(pdf_path)
    try:
        encontrados = {}
        paginas = [_lineas_pdf(doc[i]) for i in range(4, len(doc))]
        tamanos = [linea["tam"] for pagina in paginas for linea in pagina if linea["tam"]]
        cuerpo = statistics.median(tamanos) if tamanos else 0
        minimo = 4
        for t in titulos:
            buscado = _norm_titulo(t["texto"])
            pagina_encontrada = None
            for pno in range(minimo, len(doc)):
                lineas = _lineas_pdf(doc[pno])
                candidatas = [
                    linea for linea in lineas
                    if not cuerpo or linea["negrita"] or linea["tam"] >= cuerpo * 1.08
                ]
                for i, linea in enumerate(candidatas):
                    for fin in (i + 1, i + 2):
                        texto = " ".join(x["texto"] for x in candidatas[i:fin])
                        if _norm_titulo(texto) == buscado:
                            pagina_encontrada = pno
                            break
                    if pagina_encontrada is not None:
                        break
                if pagina_encontrada is not None:
                    break
            if pagina_encontrada is None and not cuerpo:
                for pno in range(minimo, len(doc)):
                    if buscado and buscado in _norm_titulo(doc[pno].get_text()):
                        pagina_encontrada = pno
                        break
            if pagina_encontrada is None:
                warnings.warn(f"índice: no se encontró el título «{t['texto']}» en el cuerpo")
                continue
            encontrados[t["id"]] = pagina_encontrada + 1
            minimo = pagina_encontrada
        return encontrados
    finally:
        doc.close()


NUM_ENTRADA = re.compile(r"^\d+\.\s+[^.!?:;]{1,80}$")


def _clase_titulo(bloque: str, nivel: int) -> str:
    def reemplazo(m):
        clases = (m.group(1) or "").split()
        for clase in ("titulo", f"titulo-{nivel}"):
            if clase not in clases:
                clases.append(clase)
        return "<p class='" + " ".join(clases) + "'"

    return re.sub(r"^<p(?: class='([^']*)')?", reemplazo, bloque, count=1)


def _normalizar_cuerpo_libro(cuerpo: list[str], promover_entradas: bool = False) -> list[str]:
    """Elimina entradas numeradas repetidas y nivela una secuencia de entradas."""
    salida, vistos = [], set()
    for bloque in cuerpo:
        if not bloque.startswith("<p"):
            salida.append(bloque)
            continue
        texto = _texto(bloque)
        es_entrada = bool(NUM_ENTRADA.match(texto))
        es_titulo = " class='" in bloque and "titulo" in bloque.split("'", 2)[1]
        if (es_entrada or es_titulo) and texto in vistos:
            continue
        if es_entrada or es_titulo:
            vistos.add(texto)
        salida.append(bloque)
    entradas = [i for i, bloque in enumerate(salida)
                if bloque.startswith("<p") and NUM_ENTRADA.match(_texto(bloque))]
    if promover_entradas or len(entradas) >= 2:
        for i in entradas:
            salida[i] = _clase_titulo(salida[i], 3)
    return salida


def _agrupar_cabeceras(cuerpo: list[str]) -> list[str]:
    """Agrupa cada título con su número y ficha inmediatos para evitar huérfanos."""
    salida = []
    i = 0
    while i < len(cuerpo):
        bloque = cuerpo[i]
        if not BeautifulSoup(bloque, "html.parser").select_one("p.titulo"):
            salida.append(bloque)
            i += 1
            continue
        grupo = [bloque]
        i += 1
        while i < len(cuerpo):
            siguiente = cuerpo[i]
            texto = _texto(siguiente)
            parrafo = BeautifulSoup(siguiente, "html.parser").select_one("p")
            es_ficha = parrafo is not None and "ficha" in (parrafo.get("class") or [])
            if (len(grupo) == 1 and re.fullmatch(r"#\d+", texto)) or es_ficha:
                grupo.append(siguiente)
                i += 1
                continue
            break
        titulo = BeautifulSoup(grupo[0], "html.parser").select_one("p.titulo")
        niveles = titulo.get("class", []) if titulo else []
        if len(grupo) == 1 and any(f"titulo-{nivel}" in niveles for nivel in (2, 3)) and i < len(cuerpo):
            siguiente = cuerpo[i]
            if not BeautifulSoup(siguiente, "html.parser").select_one("p.titulo"):
                grupo.append(siguiente)
                i += 1
        salida.append("<div class='entrada-cabecera'>" + "".join(grupo) + "</div>")
    return salida


def _titulos_de_cuerpos(libro_cuerpos: list[tuple[int, list[str]]], fuente: list[dict]) -> list[dict]:
    """Ancla también los títulos promovidos y devuelve índice y cuerpo en el mismo orden."""
    por_id = {t["id"]: t for t in fuente if t.get("id")}
    usados = set()
    siguiente = max((int(t["id"].split("-")[-1]) for t in fuente
                     if t.get("id", "").startswith("titulo-")
                     and t["id"].split("-")[-1].isdigit()), default=0) + 1
    salida = []
    for pagina, cuerpo in libro_cuerpos:
        for i, bloque in enumerate(cuerpo):
            fragmento = BeautifulSoup(bloque, "html.parser")
            encontrados = fragmento.select("p.titulo")
            if not encontrados:
                continue
            for p in encontrados:
                ident = p.get("id")
                if not ident or ident in usados:
                    while f"titulo-{siguiente}" in usados or f"titulo-{siguiente}" in por_id:
                        siguiente += 1
                    ident = f"titulo-{siguiente}"
                    siguiente += 1
                    p["id"] = ident
                usados.add(ident)
                titulo = por_id.get(ident)
                if titulo is None:
                    nivel = next((int(x.split("-")[-1]) for x in (p.get("class") or [])
                                  if x.startswith("titulo-") and x.split("-")[-1].isdigit()), 3)
                    titulo = {"nivel": nivel, "texto": p.get_text(" ", strip=True),
                              "pagina_original": pagina, "y": 0, "id": ident}
                salida.append(titulo)
            cuerpo[i] = "".join(str(x) for x in fragmento.contents)
    return salida


def _colocar_titulo(bloque: str, partes_titulo: list[str], texto: str,
                    nivel: int, tid: str) -> tuple[list[str], bool, bool] | None:
    """Coloca un título (y consume su «suma») dentro de un bloque del cuerpo.

    Casa el título al INICIO DE UNA LÍNEA (el bloque, o una línea tras <br>) o arrastrado
    al final de una oración, nunca como subcadena a mitad de frase —eso partía «…como
    Hesíodo y Porfirio» en «Hesíodo»—. El cuerpo se compone con <br> (créditos, encabezado
    y primer párrafo quedan en un mismo bloque), así que hay que mirar línea por línea o el
    encabezado queda enterrado y se duplica. Devuelve (reemplazo, suma_consumida, hay_cola)
    o None si el título no casa en este bloque.
    """
    if not bloque.startswith("<p"):
        return None
    objetivo = _norm_titulo(partes_titulo[0])
    if not objetivo:
        return None
    lineas = [_texto(x) for x in BR.split(bloque)]
    for j, linea in enumerate(lineas):
        norm = _norm_titulo(linea)
        if not norm:
            continue
        ini = fin = None
        if norm == objetivo:
            ini, fin = 0, len(linea)
        elif norm.startswith(objetivo + " "):
            mm = re.match(re.escape(partes_titulo[0]), linea, re.I)
            if mm:
                ini, fin = 0, mm.end()
        elif objetivo.startswith(norm + " ") and re.fullmatch(
                r"[\divxlcdm]+", objetivo[len(norm) + 1:].strip(), re.I):
            ini, fin = 0, len(linea)
        if ini is None:
            mm = re.search(r"(?<=[.!?:»”)])\s+(" + re.escape(partes_titulo[0]) + r")\s*$", linea, re.I)
            if mm:
                ini, fin = mm.start(1), mm.end(1)
        if ini is None:
            continue
        previos = [l for l in lineas[:j] if l]
        if linea[:ini].strip():
            previos.append(linea[:ini].strip())
        cola = ([linea[fin:].strip()] if linea[fin:].strip() else []) + [l for l in lineas[j + 1:] if l]
        suma_consumida = False
        if len(partes_titulo) > 1 and cola and _norm_titulo(cola[0]) == _norm_titulo(partes_titulo[1]):
            cola.pop(0)
            suma_consumida = True
        reemplazo = []
        if previos:
            reemplazo.append(f"<p>{_tipografia(_html.escape(' '.join(previos)))}</p>")
        reemplazo.append(f"<p class='titulo titulo-{nivel}' id='{tid}'>{_html.escape(texto)}</p>")
        if cola:
            reemplazo.append(f"<p>{_tipografia(_html.escape(' '.join(cola)))}</p>")
        return reemplazo, suma_consumida, bool(cola)
    return None


def _construir_libro_html(html_in: str, w_in: float, h_in: float, original: str | None,
                          titulo: str | None, autor: str | None,
                          libro_justificado: bool = False,
                          libro_sangria: bool = False,
                          titulos_manual: list[dict] | None = None) -> tuple[str, list[dict]]:
    soup = BeautifulSoup(html_in, "html.parser")
    titulos = (_titulos_manuales(soup, titulos_manual, internos=True)
               if titulos_manual is not None else _titulos_traducidos(soup, original))
    por_pagina = {}
    for t in titulos:
        por_pagina.setdefault(t["pagina_original"], []).append(t)
    partes = []
    if original:
        import fitz
        doc = fitz.open(original)
        try:
            portada = _pagina_como_imagen(doc[0], dpi=150) if len(doc) and doc[0].get_images() else ""
        finally:
            doc.close()
    else:
        portada = ""
    if portada:
        partes.append(f"<section class='portada'><img src='{portada}' alt='portada'></section>")
    trozos3 = _trozos_seccion(soup.select("section.page")[2]) if len(soup.select("section.page")) >= 3 else []
    titulo = titulo or (trozos3[0] if trozos3 else "Libro")
    autor = autor or next((x for x in trozos3[1:] if re.search(r"\b(?:De|Por)\b", x)), "")
    editorial = re.compile(r"publicado por|edición|kindle|copyright|©|isbn|avalonia|all rights", re.I)
    subtitulos = []
    for trozo in trozos3[1:]:
        if trozo == autor or editorial.search(trozo):
            continue
        if re.search(r"(?:https?://|www\.)", trozo, re.I):
            antes_url = re.split(r"(?:https?://|www\.)", trozo, maxsplit=1, flags=re.I)[0].strip()
            if antes_url and not editorial.search(antes_url):
                subtitulos.append(antes_url)
            break
        subtitulos.append(trozo)
    subtitulo = " · ".join(subtitulos)[:160].rstrip(" ·")
    partes.append(f"<section class='portadilla'><h1>{_html.escape(titulo)}</h1>"
                  f"<p class='autor'>{_html.escape(autor)}</p><p class='subtitulo'>{_html.escape(subtitulo)}</p></section>")
    libro_cuerpos = []
    en_resultados = False
    for sec in soup.select("section.page"):
        pn = sec.select_one(".page-num")
        m = re.search(r"\d+", pn.get_text()) if pn else None
        if not m:
            continue
        n = int(m.group())
        items, scan = _items(sec)
        cuerpo, letras = _componer(_limpiar(items, None), None, None)
        if original and n in (1, 3, 4) and letras < 400:
            continue
        if scan:
            img_escaneo = (f"<img class='escaneo' src='{_html.escape(scan, quote=True)}' "
                           f"alt='página {n}'>")
            if letras == 0:
                cuerpo = [img_escaneo]
            elif letras < OCR_LARGO:
                cuerpo.insert(0, img_escaneo)
        for t in por_pagina.get(n, []):
            partes_titulo = t.get("_partes", [t["texto"]])
            encontrado = False
            for i, bloque in enumerate(cuerpo):
                res = _colocar_titulo(bloque, partes_titulo, t["texto"], t["nivel"], t["id"])
                if res is None:
                    continue
                reemplazo, suma_consumida, hay_cola = res
                cuerpo[i:i + 1] = reemplazo
                if len(partes_titulo) > 1 and not suma_consumida:
                    idx = i + len(reemplazo)
                    if (not hay_cola and idx < len(cuerpo)
                            and _norm_titulo(_texto(cuerpo[idx])) == _norm_titulo(partes_titulo[1])):
                        del cuerpo[idx]
                    else:
                        print(f"aviso: suma «{partes_titulo[1]}» no casa el bloque siguiente; no se retira",
                              file=sys.stderr)
                encontrado = True
                break
            if not encontrado:
                cuerpo.insert(0, f"<p class='titulo titulo-{t['nivel']}' id='{t['id']}'>{_html.escape(t['texto'])}</p>")
        if any(_norm_titulo(t["texto"]) == "los resultados" for t in por_pagina.get(n, [])):
            en_resultados = True
        normalizado = _normalizar_cuerpo_libro(cuerpo, en_resultados)
        libro_cuerpos.append((n, normalizado))
    titulos = _titulos_de_cuerpos(libro_cuerpos, titulos)
    for t in titulos:
        t.pop("_partes", None)
    toc = [t for t in titulos if t["nivel"] in (1, 2, 3)]
    entradas = []
    for t in toc:
        texto_indice = re.sub(r":\s*$", "", t["texto"])
        entradas.append(f"<div class='entrada-indice nivel-{t['nivel']}'><a href='#{t['id']}'>{_html.escape(texto_indice)}</a><span class='puntos'>...</span>"
                        f"<span class='pagina' data-target='{t['id']}'>0</span></div>")
    partes.append("<section class='indice' data-indice-pasada='1'><h2>Índice</h2>" + "".join(entradas) + "</section>")
    cosidos = _coser([cuerpo for _, cuerpo in libro_cuerpos])
    for (n, _), cuerpo in zip(libro_cuerpos, cosidos):
        partes.append(f"<section class='libro-seccion'><div class='cuerpo'>{''.join(_agrupar_cabeceras(cuerpo))}</div></section>")
    refs = soup.select_one("section.refs")
    if refs:
        partes.append(f"<section class='refs'>{refs.decode_contents()}</section>")
    css = LIBRO_CSS % {"W": w_in, "H": h_in,
                       "ALIGN": "justify" if libro_justificado else "left",
                       "HYPHENS": "auto"}
    if libro_sangria:
        css += (".cuerpo p{text-indent:1.2em;margin-bottom:0}"
                ".cuerpo p.titulo{text-indent:0}.cuerpo p.ficha{text-indent:0}"
                ".entrada-cabecera + p{text-indent:0}.cuerpo > p:first-child{text-indent:0}")
    return ("<!doctype html><html lang='es'><head><meta charset='utf-8'><title>libro</title>"
            f"<style>{css}</style></head><body>{''.join(partes)}"
            "<div id='informe' data-desborde='' data-encogidas='0'></div></body></html>", titulos)


def construir_html(html_in: str, w_in: float = 8.5, h_in: float = 11.0, original: str | None = None,
                   con_fuentes: bool = False, limpiar: bool = True, solo_imagen: frozenset = frozenset(),
                   cabecera: bool = True, corrido: bool = False,
                   escaneos: list | None = None, libro: bool = False,
                   titulo: str | None = None, autor: str | None = None,
                   libro_justificado: bool = False,
                   libro_sangria: bool = False,
                   titulos_manual: list[dict] | None = None) -> str:
    if libro:
        return _construir_libro_html(html_in, w_in, h_in, original, titulo, autor,
                                     libro_justificado, libro_sangria, titulos_manual)[0]
    soup = BeautifulSoup(html_in, "html.parser")
    alto = int((h_in - 2 * MARGEN_IN) * 96) - 2
    prm = {"W": w_in, "H": h_in, "M": MARGEN_IN, "BASE": BASE_PT, "MIN": MIN_PT,
           "ALTO": alto, "IMG": int(alto * 0.42), "WU": int((w_in - 2 * MARGEN_IN) * 96),
           "ALTO_HOJA": 0 if (corrido or not cabecera) else alto,
           "IMG_MAX": alto - 20 if corrido else 100000,
           "CORRIDO": "true" if corrido else "false",
           "CORTE": "auto" if corrido else "page",
           "CORTE_VIEJO": "auto" if corrido else "always"}
    secciones, sin_figuras = [], set()
    for sec in soup.select("section.page"):
        pn = sec.select_one(".page-num")
        m = re.search(r"\d+", pn.get_text()) if pn else None
        n = m.group(0) if m else str(len(secciones) + 1)
        if "sin-figuras" in (sec.get("class") or []):
            sin_figuras.add(n)
        secciones.append((n, *_items(sec)))
    ref = None
    folio_num = False
    if limpiar:
        primeros = [_texto(next((v for k, v in items if k == "t"), "")) for _, items, _ in secciones]
        ref = detectar_encabezados([p for p in primeros if p])
        folio_num = _folio_numerico(primeros)
    doc_orig = None
    if original:
        import fitz
        doc_orig = fitz.open(original)
    hojas, cuerpos = [], []
    for n, items, scan in secciones:
        if int(n) in solo_imagen and doc_orig is not None and 1 <= int(n) <= len(doc_orig):
            cuerpos.append((n, [f"<img class='escaneo' style='max-height:{alto - 60}px;margin:0 auto' "
                                f"src='{_pagina_como_imagen(doc_orig[int(n) - 1])}' alt='página {n}'>"]))
            continue
        if limpiar:
            items = _limpiar(items, ref, folio_num)
        figs = None
        if doc_orig is not None and 1 <= int(n) <= len(doc_orig) and n not in sin_figuras:
            import figuras
            figs = figuras.sin_texto_ingles(figuras.figuras_pagina(doc_orig[int(n) - 1]))
        objetivo = None
        if doc_orig is not None and 1 <= int(n) <= len(doc_orig):
            try:
                import estructura
                objetivo = len(estructura.inicios(doc_orig[int(n) - 1])) or None
            except Exception:
                objetivo = None
        cuerpo, letras = _componer(items, figs, objetivo)
        if scan and letras == 0:
            cuerpo = [c for c in cuerpo if "class='warn'" not in c]
        if scan:
            if letras == 0:
                if escaneos is not None:
                    escaneos.append((len(cuerpos), scan))
                    continue
                cuerpo.insert(0, f"<img class='escaneo' style='max-height:{alto - 40}px' "
                                 f"src='{_html.escape(scan, quote=True)}' alt='página {n}'>")
            elif letras < OCR_LARGO and not figs:
                cuerpo.insert(0, f"<img class='escaneo' src='{_html.escape(scan, quote=True)}' "
                                 f"alt='página {n}'>")
        cuerpos.append((n, cuerpo))
    if corrido:
        cosidos = _coser([c for _, c in cuerpos])
        cuerpos = [(n, c) for (n, _), c in zip(cuerpos, cosidos)]
    for n, cuerpo in cuerpos:
        rotulo = f"<div class='num'>Página {n}</div>" if cabecera else ""
        hojas.append(f"<section class='hoja' data-n='{n}'>{rotulo}"
                     f"<div class='cuerpo'>{''.join(cuerpo)}</div></section>")
    refs = soup.select_one("section.refs")
    if refs and con_fuentes:
        hojas.append(f"<section class='hoja refs'>{refs.decode_contents()}</section>")
    return ("<!doctype html><html lang='es'><head><meta charset='utf-8'>"
            f"<title>libro</title><style>{CSS % prm}</style></head><body>"
            + "".join(hojas) + f"<script>{JS % prm}</script></body></html>")


def _chrome() -> str | None:
    from render import find_chrome
    return find_chrome()


def formato_de(pdf_path: str) -> str:
    """Con qué versión de maquetado se hizo ese PDF, o "" si es anterior al sellado."""
    import fitz
    try:
        return (fitz.open(pdf_path).metadata or {}).get("keywords", "").split("formato=")[-1].split()[0]
    except Exception:
        return ""


def _sellar(pdf_path: str, corrido: bool) -> None:
    """Deja escrito en el PDF con qué formato se maquetó, para no tener que adivinarlo por fechas."""
    import fitz
    try:
        d = fitz.open(pdf_path)
        meta = d.metadata or {}
        meta["keywords"] = f"formato={FORMATO} modo={'corrido' if corrido else 'hoja-a-hoja'}"
        d.set_metadata(meta)
        d.saveIncr() if d.can_save_incrementally() else d.save(pdf_path + ".tmp")
        if not d.can_save_incrementally():
            os.replace(pdf_path + ".tmp", pdf_path)
        d.close()
    except Exception:
        pass


def _pegar_escaneos(pdf_path: str, escaneos: list, w_in: float, h_in: float, log=print) -> None:
    """Mete las páginas que son solo escaneo (portadas, láminas) en el PDF, a página completa.

    No pasan por el maquetador: son una imagen y no hay nada que componer. Se pegan después, en el
    orden en que venían, para que no dependan de si Chrome consigue encajarlas entre el texto.
    """
    import base64

    import fitz
    d = fitz.open(pdf_path)
    rect = fitz.Rect(0, 0, w_in * 72, h_in * 72)
    puestas = 0
    for orden, (pos, src) in enumerate(escaneos):
        if "," not in src:
            continue
        try:
            datos = base64.b64decode(src.split(",", 1)[1])
        except Exception:
            continue
        destino = min(pos + orden, len(d))
        pag = d.new_page(pno=destino, width=rect.width, height=rect.height)
        caja = rect + (18, 18, -18, -18)
        try:
            px = fitz.Pixmap(datos)
            escala = min(caja.width / px.width, caja.height / px.height)
            w, h = px.width * escala, px.height * escala
            caja = fitz.Rect((rect.width - w) / 2, (rect.height - h) / 2,
                             (rect.width + w) / 2, (rect.height + h) / 2)
        except Exception:
            pass
        pag.insert_image(caja, stream=datos, keep_proportion=True)
        puestas += 1
    if puestas:
        d.saveIncr() if d.can_save_incrementally() else d.save(pdf_path + ".tmp")
        if not d.can_save_incrementally():
            os.replace(pdf_path + ".tmp", pdf_path)
        log(f"  {puestas} página(s) de escaneo pegadas tal cual")
    d.close()


def _ruta_pdf_temporal(pdf_path: str) -> str:
    return pdf_path + ".tmp"


def _validar_paginas(actual: int, esperadas: int, pdf_path: str) -> None:
    if actual < esperadas:
        raise RuntimeError(f"faltan hojas: {actual} de {esperadas} ({pdf_path})")


def _regex_informe(dom: str):
    return re.search(r"id=['\"]informe['\"]\s+data-desborde=['\"]([^'\"]*)['\"]\s+data-encogidas=['\"](\d+)['\"]", dom)


def _imprimir_html(chrome: str, html_path: str, pdf_path: str, require_report: bool = True):
    url = "file://" + os.path.abspath(html_path)
    base = [chrome, "--headless", "--disable-gpu"]
    dom = subprocess.run(base + ["--dump-dom", url], capture_output=True, timeout=600, text=True).stdout
    informe = _regex_informe(dom)
    if require_report and not informe:
        raise RuntimeError("Chrome no devolvió el informe de maquetación")
    tmp_pdf = _ruta_pdf_temporal(pdf_path)
    try:
        subprocess.run(base + ["--no-pdf-header-footer", f"--print-to-pdf={tmp_pdf}", url],
                       check=True, capture_output=True, timeout=600)
        if not os.path.exists(tmp_pdf) or os.path.getsize(tmp_pdf) == 0:
            raise RuntimeError("Chrome no produjo un PDF completo")
        os.replace(tmp_pdf, pdf_path)
    finally:
        if os.path.exists(tmp_pdf):
            os.remove(tmp_pdf)
    return dom, informe


def _titulos_desde_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    return [{"id": p.get("id"), "texto": p.get_text(" ", strip=True)}
            for p in soup.select("p.titulo[id]")]


def _maquetar_libro_desde_html(html: str, pdf_path: str, chrome: str, log=print) -> str:
    import fitz
    titulos = _titulos_desde_html(html)
    temp_html = os.path.splitext(pdf_path)[0] + "_libro.html"
    pass_pdf = pdf_path + ".indice"

    def medir(actual):
        with open(temp_html, "w", encoding="utf-8") as f:
            f.write(actual)
        _imprimir_html(chrome, temp_html, pass_pdf, require_report=False)
        return _pagina_de_titulos(pass_pdf, titulos)

    try:
        html = _estabilizar_indice(html, medir)
        with open(temp_html, "w", encoding="utf-8") as f:
            f.write(html)
        _imprimir_html(chrome, temp_html, pdf_path, require_report=False)
    finally:
        for path in (temp_html, pass_pdf):
            if os.path.exists(path):
                os.remove(path)
    _sellar(pdf_path, True)
    doc = fitz.open(pdf_path)
    n = len(doc)
    doc.close()
    log(f"  libro: {n} páginas; índice estabilizado en hasta 3 pasadas")
    return pdf_path


def maquetar(html_path: str, pdf_path: str | None = None, w_in: float = 8.5,
             h_in: float = 11.0, log=print, original: str | None = None,
             con_fuentes: bool = False, limpiar: bool = True, solo_imagen: frozenset = frozenset(),
             cabecera: bool = True, corrido: bool = False, libro: bool = False,
             titulo: str | None = None, autor: str | None = None,
             libro_justificado: bool = False,
             libro_sangria: bool = False,
             titulos_manual: list[dict] | None = None) -> str:
    """Devuelve la ruta del PDF maquetado hoja a hoja ('' si no hay Chrome)."""
    pdf_path = pdf_path or os.path.splitext(html_path)[0] + ".pdf"
    chrome = _chrome()
    if not chrome:
        raise RuntimeError("sin Chrome: no se puede maquetar hoja a hoja")
    if libro:
        if titulos_manual is None:
            titulos_manual = _leer_titulos_tsv(os.path.join(os.path.dirname(html_path), "titulos.tsv"))
        with open(html_path, encoding="utf-8") as f:
            doc, _ = _construir_libro_html(f.read(), w_in, h_in, original, titulo, autor,
                                           libro_justificado, libro_sangria, titulos_manual)
        return _maquetar_libro_desde_html(doc, pdf_path, chrome, log)
    escaneos: list = []
    with open(html_path, encoding="utf-8") as f:
        doc = construir_html(f.read(), w_in, h_in, original, con_fuentes, limpiar, solo_imagen,
                             cabecera, corrido, escaneos)
    tmp = os.path.splitext(pdf_path)[0] + "_hojas.html"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(doc)
    try:
        dom, m = _imprimir_html(chrome, tmp, pdf_path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    desb = [x for x in (m.group(1).split(",") if m else []) if x]
    log(f"  hoja a hoja: {m.group(2) if m else '?'} hojas con letra reducida; "
        f"{len(desb)} desbordan a 2ª hoja" + (f" (págs {', '.join(desb)})" if desb else ""))
    if escaneos:
        _pegar_escaneos(pdf_path, escaneos, w_in, h_in, log)
    _sellar(pdf_path, corrido)
    import fitz
    d = fitz.open(pdf_path)
    n_pdf = len(d)
    n_src = len(re.findall(r"data-n='", doc))
    d.close()
    if corrido:
        log(f"  PDF: {n_pdf} hojas de texto corrido, de {n_src} páginas del original")
    else:
        log(f"  PDF: {n_pdf} hojas para {n_src} páginas del original"
            + ("" if n_pdf >= n_src else "  ⚠ faltan hojas"))
        try:
            _validar_paginas(n_pdf, n_src, pdf_path)
        except RuntimeError:
            incompleto = pdf_path + ".incompleto"
            os.replace(pdf_path, incompleto)
            raise
    return pdf_path


if __name__ == "__main__":
    if "demo" in sys.argv:
        demo()
        sys.exit(0)
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    flags = [x for x in sys.argv[1:] if x.startswith("--")]
    orig = None
    if "--original" in flags:
        i = sys.argv.index("--original")
        orig = sys.argv[i + 1]
        a = [x for x in a if x != orig]
    solo = frozenset()
    if "--solo-imagen" in flags:
        i = sys.argv.index("--solo-imagen")
        solo = frozenset(int(x) for x in sys.argv[i + 1].split(","))
        a = [x for x in a if x != sys.argv[i + 1]]
    if not a:
        sys.exit(__doc__)
    w, h = (float(a[2]), float(a[3])) if len(a) >= 4 else (8.5, 11.0)
    print(maquetar(a[0], a[1] if len(a) > 1 else None, w, h, original=orig,
                   con_fuentes="--con-fuentes" in flags, limpiar="--sin-limpiar" not in flags,
                   solo_imagen=solo, cabecera="--sin-cabecera" not in flags,
                   corrido="--corrido" in flags))
