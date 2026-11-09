#!/usr/bin/env python3
"""Pasada de limpieza determinista sobre los libros que tienen HTML fuente. Cero API, cero modelos.

Arregla solo lo inequívoco:
  1. cortes de palabra que el OCR dejó con guion y espacio ("reac- tivados" → "reactivados"),
     y solo si las dos mitades son minúsculas y la palabra unida aparece en otro sitio del libro;
  2. marcas de nota con un corchete de más ("[ii]]" → "[ii]");
  3. el título del libro en inglés repetido al pie de cada página (encabezado corrido del original).

Después remaqueta y **solo entrega si el resultado no pierde figuras ni gana inglés** respecto a la
referencia: el PDF ya entregado o, en una primera entrega, el hoja a hoja que dejó libro.sh en la
carpeta. Si empeora, deja el anterior y lo dice. Respalda el HTML (.antes_limpieza) y el PDF en
`~/traductor/taller/_antes_revision`.

Si en la carpeta hay un `entregar.sh`, es él quien produce el PDF (recibe la ruta de salida), por
ejemplo para una obra compuesta de varias partes. Entonces la referencia es solo el hoja a hoja de
la carpeta, si lo hay: el PDF entregado puede corresponder a otra edición.

Es la etapa 3 de flujo.sh; se puede correr suelto. La lista de libros y su PDF de entrega es
`<taller>/entregas.tsv` (ver entregas.py). Variables: TRAB (taller de trabajo), ENTREGA (carpeta
donde se entregan los PDF), RESPALDO (donde se guarda el PDF anterior antes de reemplazarlo).

Uso:  entregar_libro.py                    todos los libros con HTML
      entregar_libro.py --forzar muestra   remaqueta y entrega aunque no haya nada que limpiar
      entregar_libro.py --corrido muestra  ídem, en texto corrido (es lo que usa flujo.sh)
      entregar_libro.py muestra            solo esos (por nombre de carpeta)
      entregar_libro.py --simulacro        dice qué cambiaría, sin tocar nada
      entregar_libro.py demo               autocomprobación de la guarda, sin maquetar nada
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
try:
    import fcntl
except ImportError:
    fcntl = None

RAIZ = os.path.dirname(os.path.abspath(__file__))
BASE = os.environ.get("TRAB", os.path.expanduser("~/traductor/taller"))
ENTREGA = os.environ.get("ENTREGA", os.path.expanduser("~/traductor/libros_esp"))
RESPALDO = os.environ.get("RESPALDO", os.path.expanduser(
    "~/traductor/taller/_antes_revision"))
sys.path.insert(0, RAIZ)
import entregas
from render import escribir_atomico

PY = sys.executable
SIMULACRO = "--simulacro" in sys.argv
FORZAR = "--forzar" in sys.argv
CORRIDO = "--corrido" in sys.argv
PEDIDOS = [a for a in sys.argv[1:] if not a.startswith("--") and a != "demo"]

ENTREGADOS = {c: pdf for c, (pdf, _) in entregas.leer(BASE).items() if pdf}

CORTE = re.compile(r"\b([a-záéíóúüñ]{2,})-\s*(?:<br/>)?\s+([a-záéíóúüñ]{2,})\b")
NOTA_DOBLE = re.compile(r"(\[(?:[ivxlcdm]{1,8})\])\s*\]")
EN_FUNC = re.compile(r"\b(the|and|with|from|your|which|while|that|this|into)\b", re.I)


def sin_marcas(h):
    """Texto del HTML sin etiquetas ni imágenes incrustadas, para contar y buscar."""
    h = re.sub(r'src="data:[^"]*"', "", h)
    h = re.sub(r"<div class=(?:\"ref\"|'ref').*?</div>", "", h, flags=re.S)
    return re.sub(r"<[^>]+>", " ", h)


def arreglar(html, log):
    texto = sin_marcas(html)
    palabras = set(re.findall(r"\b[a-záéíóúüñ]{4,}\b", texto.lower()))
    n_cortes = 0

    def une(m):
        nonlocal n_cortes
        junta = m.group(1) + m.group(2)
        if junta.lower() in palabras:
            n_cortes += 1
            return junta
        return m.group(0)

    html = CORTE.sub(une, html)
    html, n_notas = NOTA_DOBLE.subn(r"\1", html)
    if n_cortes:
        log.append(f"      {n_cortes} cortes de palabra unidos")
    if n_notas:
        log.append(f"      {n_notas} marcas de nota con ] de más")
    return html, n_cortes + n_notas


def titulo_corrido(html, log):
    """Quita el título del libro en inglés repetido al pie de muchas páginas."""
    import collections
    pies = re.findall(r"<br/>([^<>]{25,90})</div></section>", html)
    if not pies:
        return html, 0
    cand, veces = collections.Counter(p.strip() for p in pies).most_common(1)[0]
    if veces < 12 or not EN_FUNC.search(cand) or len(re.findall(r"[A-Za-z]", cand)) < 20:
        return html, 0
    pat = re.compile(r"(?:^|<br\s*/>)\s*(?:[0-9ivxl ]{1,9})?\s*" + re.escape(cand) + r"(?=\s*</div>)", re.M)
    html, n = pat.subn("", html)
    if n:
        log.append(f"      {n} veces el título corrido en inglés: «{cand[:46]}…»")
    return html, n


ROTULO = re.compile(r"^\s*(?:P\s*Á\s*G\s*I\s*N\s*A|Página)\s*[\d ]+\s*$", re.I | re.M)


def palabras(pdf):
    """Cuántas palabras tiene el PDF: la red de seguridad contra perder texto al remaquetar.
    Si no se puede leer, revienta: devolver 0 hacía que un PDF ilegible pasara por bueno.
    Sin contar el rótulo «P Á G I N A  N» del hoja a hoja: son seis letras sueltas por página
    (2000 «palabras» en un libro de 336) que el corrido no lleva, y daban un 3,6 % de texto perdido
    donde no se había perdido nada."""
    import fitz
    texto = "".join(p.get_text() for p in fitz.open(pdf))
    return len(ROTULO.sub("", texto).split())


EN = set("the and of to in is that for with as by on this which from are was be or it an at not have "
         "their they also his its were been shall thou thee unto".split())
ES = set("el la los las de que y en un una para con por se del al es son como sus su más pero o muy "
         "este esta fue lo le".split())


def palabras_inglesas(pdf):
    """Cuántas PALABRAS caen en un tramo donde el inglés manda: una ventana de 40 palabras con cuatro o
    más inglesas y más inglesas que españolas.

    Palabras, no bloques: al remaquetar el texto se reparte en bloques distintos y una misma
    bibliografía pasaba de 6 bloques a 13 sin cambiar una palabra. Y ventana DESLIZANTE, no fija:
    con ventanas fijas la cuenta dependía de dónde cayeran los cortes, y un PDF con veinte palabras
    más al principio (otras divisiones por guion al cambiar la maquetación) corría todas las ventanas
    y daba 280→440 sobre la misma bibliografía, y la guarda rechazaba un libro intacto.
    """
    import fitz
    pal = re.findall(r"[a-záéíóúüñ']+", "".join(p.get_text() for p in fitz.open(pdf)).lower())
    n, v = len(pal), 40
    en, es = [0] * (n + 1), [0] * (n + 1)
    for i, w in enumerate(pal):
        en[i + 1], es[i + 1] = en[i] + (w in EN), es[i] + (w in ES)
    marca = bytearray(n)
    for i in range(max(1, n - v + 1)):
        j = min(n, i + v)
        e, s = en[j] - en[i], es[j] - es[i]
        if e >= 4 and e > s:
            marca[i:j] = b"\x01" * (j - i)
    return sum(marca)


def medir(pdf):
    """(tinta de las figuras, bloques en inglés) del PDF, con las herramientas locales.

    La "tinta" es el ÁREA que ocupan las imágenes, no cuántas son. Contarlas engañaba: al remaquetar,
    una página que antes traía tres figuras sueltas puede pegarse como una sola imagen de página
    completa. El recuento bajaba de tres a uno y parecía una pérdida, cuando el área subía. El área
    no depende de cómo se agrupen: si baja, falta dibujo de verdad.
    """
    import fitz
    d = fitz.open(pdf)
    area = 0.0
    for p in d:
        for im in p.get_images(full=True):
            for rect in p.get_image_rects(im[0]) or []:
                area += rect.width * rect.height
    return round(area), palabras_inglesas(pdf)


def referencia_de(d, entregado, hook):
    """Contra qué se compara el PDF nuevo: el entregado; o el hoja a hoja más reciente que dejó
    libro.sh en la carpeta si es la primera entrega, si la arma un entregar.sh, o si ese hoja a hoja
    es MÁS NUEVO que el entregado (una retraducción: el entregado es otra edición, con otras páginas
    pegadas como imagen, y compararse con ella rechazaba un libro bien hecho); o nada."""
    propios = sorted((os.path.join(d, f) for f in os.listdir(d) if f.endswith("_ES.pdf")),
                     key=os.path.getmtime)
    hoja = propios[-1] if propios else None
    if os.path.exists(entregado) and not hook and not (hoja and os.path.getmtime(hoja) > os.path.getmtime(entregado)):
        return entregado
    return hoja


def empeora(fig_a, en_a, pal_a, fig_b, en_b, pal_b):
    """La guarda: pierde dibujo, gana inglés o pierde más del 3 % del texto. En corrido se pierden
    los encabezados corridos (eso se busca), pero nada más."""
    perdido = (pal_a - pal_b) / max(pal_a, 1)
    return fig_b < fig_a * 0.98 or en_b > max(en_a * 1.15, en_a + 40) or perdido > 0.03


def _ocupado(d):
    """Otra pasada está maquetando esta carpeta ahora mismo (cerrojo .maquetando con su pid vivo)."""
    try:
        with open(os.path.join(d, ".maquetando"), encoding="ascii") as fh:
            pid = int(fh.read().strip())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def _adquirir_cerrojo(d):
    ruta = os.path.join(d, ".maquetando")
    fh = None
    try:
        fh = open(ruta, "a+", encoding="ascii")
        if fcntl:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        if fh is not None:
            fh.close()
        return False
    fh.seek(0)
    fh.truncate()
    fh.write(str(os.getpid()))
    fh.flush()
    return fh


def _pdf_temporal(d):
    fd, ruta = tempfile.mkstemp(prefix=".limpio-", suffix=".pdf", dir=d)
    os.close(fd)
    os.unlink(ruta)
    return ruta


def _pdf_valido(ruta):
    import fitz
    try:
        doc = fitz.open(ruta)
        valido = len(doc) > 0 and any(p.get_text().strip() or p.get_images(full=True) for p in doc)
        doc.close()
        return valido
    except Exception:
        return False


def una(carpeta):
    d = os.path.join(BASE, carpeta)
    cerrojo = _adquirir_cerrojo(d)
    if not cerrojo:
        pid = _ocupado(d)
        detalle = f" (pid {pid})" if pid else ""
        print(f"\n── {carpeta}\n      ✗ ya lo está maquetando otro proceso{detalle}; lo dejo", flush=True)
        return False
    try:
        return _una(carpeta, d)
    finally:
        cerrojo.close()


def _una(carpeta, d):
    try:
        return _una_impl(carpeta, d)
    finally:
        for nombre in os.listdir(d) if os.path.isdir(d) else ():
            if nombre.startswith(".limpio-") and nombre.endswith(".pdf"):
                _discard(os.path.join(d, nombre))


def _una_impl(carpeta, d):
    _discard(os.path.join(d, "_limpio.pdf"))
    if carpeta not in ENTREGADOS:
        print(f"\n── {carpeta}\n      ✗ no está en entregas.tsv: dale de alta con ./flujo.sh --alta {carpeta} NOMBRE_ES.pdf", flush=True)
        return False
    html_p, orig_p = fuentes(d)
    if not html_p:
        print(f"\n── {carpeta}\n      ✗ no tiene HTML de trabajo: habría que retraducirlo", flush=True)
        return False
    entregado = os.path.join(ENTREGA, ENTREGADOS[carpeta])
    hook = os.path.join(d, "entregar.sh")
    hook = hook if os.path.exists(hook) else None
    log = [f"\n── {carpeta}"]
    with open(html_p, encoding="utf-8") as fh:
        orig_html = fh.read()
    nuevo, n1 = arreglar(orig_html, log)
    nuevo, n2 = titulo_corrido(nuevo, log)
    if not (n1 + n2) and not (FORZAR or CORRIDO):
        log.append("      nada que arreglar")
        print("\n".join(log), flush=True)
        return True
    if not (n1 + n2):
        log.append("      nada que limpiar; remaqueto y entrego igual (--forzar)")
    if SIMULACRO:
        print("\n".join(log) + "      (simulacro: no se tocó nada)", flush=True)
        return True

    candidato = ""
    if n1 + n2:
        candidato = html_p + ".candidato"
        escribir_atomico(candidato, nuevo)

    previo = ""
    if hook and candidato:
        previo = html_p + ".previo"
        shutil.copy2(html_p, previo)
        os.replace(candidato, html_p)

    pdf_nuevo = _pdf_temporal(d)
    if hook:
        orden = [hook, pdf_nuevo]
    else:
        orden = [PY, "hojas.py", candidato or html_p, pdf_nuevo, "--sin-cabecera"]
        if orig_p:
            orden[4:4] = ["--original", orig_p]
        if CORRIDO:
            orden.append("--corrido")
    r = subprocess.run(orden, cwd=RAIZ, capture_output=True, text=True)
    if getattr(r, "returncode", 0) != 0 or not os.path.exists(pdf_nuevo) or not _pdf_valido(pdf_nuevo):
        if previo:
            os.replace(previo, html_p)
        _discard(candidato)
        log.append(f"      ✗ no se pudo maquetar: {(r.stderr or r.stdout or '')[-150:]}")
        print("\n".join(log), flush=True)
        if os.path.exists(pdf_nuevo):
            os.replace(pdf_nuevo, os.path.join(d, "_limpio.pdf"))
        return False
    ref = referencia_de(d, entregado, hook)
    if ref:
        fig_a, en_a = medir(ref)
        fig_b, en_b = medir(pdf_nuevo)
        pal_a, pal_b = palabras(ref), palabras(pdf_nuevo)
        detalle = (f"dibujo {fig_a:,}→{fig_b:,} pt², inglés {en_a}→{en_b} palabras, "
                   f"texto {pal_a}→{pal_b} palabras")
        if empeora(fig_a, en_a, pal_a, fig_b, en_b, pal_b):
            if previo:
                os.replace(previo, html_p)
            _discard(candidato)
            log.append(f"      ✗ empeora respecto a {os.path.basename(ref)} ({detalle}): NO se entrega")
            print("\n".join(log), flush=True)
            os.replace(pdf_nuevo, os.path.join(d, "_limpio.pdf"))
            return False
    else:
        detalle = "primera entrega, sin nada con que compararla"
    if candidato:
        respaldo_html = html_p + ".antes_limpieza"
        if not os.path.exists(respaldo_html):
            shutil.copy2(previo or html_p, respaldo_html)
        if not hook:
            os.replace(candidato, html_p)
    _discard(previo)
    try:
        if os.path.exists(entregado):
            os.makedirs(RESPALDO, exist_ok=True)
            _copiar_atomico(entregado, os.path.join(RESPALDO, ENTREGADOS[carpeta] + ".antes_limpieza"))
        _copiar_atomico(pdf_nuevo, entregado)
    except OSError as e:
        log.append(f"      ✗ no se pudo entregar: {e}")
        print("\n".join(log), flush=True)
        if os.path.exists(pdf_nuevo):
            os.replace(pdf_nuevo, os.path.join(d, "_limpio.pdf"))
        return False
    log.append(f"      ✅ entregado ({detalle})")
    print("\n".join(log), flush=True)
    _discard(pdf_nuevo)
    return True


def fuentes(d):
    """Devuelve el HTML de trabajo y el PDF original, si existe."""
    htmls = sorted(f for f in os.listdir(d) if f.endswith("_es.html"))
    origs = sorted(f for f in os.listdir(d)
                   if f.endswith(".pdf") and not re.search(r"_ES|_nuevo|_v\d|antes|limpio|trabajo", f))
    return (os.path.join(d, htmls[0]) if htmls else None,
            os.path.join(d, origs[0]) if origs else None)


def _copiar_atomico(origen, destino):
    """Copia al mismo directorio y reemplaza al final, para no dejar un PDF truncado."""
    directorio = os.path.dirname(os.path.abspath(destino))
    os.makedirs(directorio, exist_ok=True)
    temporal = None
    try:
        with tempfile.NamedTemporaryFile(dir=directorio, prefix=".entrega-", suffix=".tmp", delete=False) as f:
            temporal = f.name
        shutil.copy2(origen, temporal)
        os.replace(temporal, destino)
    finally:
        if temporal and os.path.exists(temporal):
            os.unlink(temporal)


def _discard(path):
    if not path:
        return
    try:
        os.remove(path)
    except OSError:
        pass


def demo():
    """Autocomprobación de la guarda y de la elección de referencia, sin maquetar nada."""
    import tempfile
    assert not empeora(100, 10, 1000, 100, 10, 980)
    assert empeora(100, 10, 1000, 97, 10, 1000)
    assert empeora(100, 10, 1000, 100, 60, 1000)
    assert empeora(100, 10, 1000, 100, 10, 960)
    assert not empeora(100, 0, 1000, 100, 30, 1000)
    with tempfile.TemporaryDirectory() as d:
        os.mkdir(os.path.join(d, "entrega"))
        ent = os.path.join(d, "entrega", "Libro_ES.pdf")
        assert referencia_de(d, ent, None) is None
        open(os.path.join(d, "Libro_ES.pdf"), "w").close()
        assert referencia_de(d, ent, None).endswith(f"{d}/Libro_ES.pdf")
        open(ent, "w").close()
        assert referencia_de(d, ent, None) == ent
        os.utime(os.path.join(d, "Libro_ES.pdf"), None)
        assert referencia_de(d, ent, None).endswith(f"{d}/Libro_ES.pdf")
        assert referencia_de(d, ent, "hook").endswith(f"{d}/Libro_ES.pdf")
    print("demo OK")


def main():
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(__doc__)
        return
    if "demo" in sys.argv:
        demo()
        return
    carpetas = PEDIDOS or sorted(ENTREGADOS)
    print(f"Limpieza determinista de {len(carpetas)} libros{' (simulacro)' if SIMULACRO else ''}", flush=True)
    fallos = 0
    for c in carpetas:
        if os.path.isdir(os.path.join(BASE, c)):
            try:
                if not una(c):
                    fallos += 1
            except Exception as e:
                fallos += 1
                print(f"\n── {c}\n      ✗ {type(e).__name__}: {str(e)[:140]}", flush=True)
    print("\nfin", flush=True)
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
