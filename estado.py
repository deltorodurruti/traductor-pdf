#!/usr/bin/env python3
"""En qué va cada libro: los que corren ahora, los que faltan, y cuántos están listos.

Es la ÚNICA definición de «en qué etapa está un libro»: flujo.sh se lo pregunta a este script
(`--etapa`, `--libros`) en vez de calcularlo por su cuenta. Antes había dos cálculos y daban dos
verdades distintas: uno adivinaba el PDF entregado por las palabras del nombre y nunca casaba
«gallina_negra» con «Black_Pullet_ES.pdf». La lista de libros y su PDF de entrega es
`<taller>/entregas.tsv` (ver entregas.py); ahí también va el nombre para el tablero y qué carpetas no
son libros.

Mide el avance contando el archivo, no el registro: el registro solo dice lo que la herramienta
decide escribir, y se queda mudo horas. Los entregados y al día no se listan, solo se cuentan.

Uso:  ./estado.py              una foto
      ./estado.py -s [seg]     se refresca solo (cada 20 s; Ctrl-C para salir)
      ./estado.py -t           lista también los que ya están listos
      ./estado.py --libros     las carpetas que son libros del flujo, una por línea
      ./estado.py --etapa X    «N motivo»: 1 traducir · 2 completar · 3 maquetar · 0 listo o sin salida
Variables: TRAB (taller de trabajo) y ENTREGA (carpeta donde se entregan los PDF).
"""
import os
import re
import subprocess
import sys
import time

AQUI = os.path.dirname(os.path.realpath(__file__))
TRAB = os.environ.get("TRAB", os.path.expanduser("~/traductor/taller"))
ENTREGA = os.environ.get("ENTREGA", os.path.expanduser("~/traductor/libros_esp"))
sys.path[:0] = [AQUI, os.path.join(AQUI, "herramientas")]
import avance

import entregas
import hojas

ENTREGAS = entregas.leer(TRAB)

V, A, R, AZ, GR, N, B = "\033[32m", "\033[33m", "\033[31m", "\033[36m", "\033[90m", "\033[0m", "\033[1m"
SALIDA_PROPIA = re.compile(r"_ES|_nuevo|_v\d|antes|limpio|trabajo")

SIGUE = {
    "1": "completar lo que quede en inglés → maquetar en corrido → entregar",
    "2": "maquetar en corrido → entregar (solo si no pierde dibujo ni texto)",
    "3": "entregar, si la guarda lo deja pasar",
}


def bonito(carpeta):
    nombre = ENTREGAS.get(carpeta, (None, None))[1]
    return nombre or carpeta.replace("_", " ").title()


def barra(hechas, total, ancho=22):
    if not total:
        return " " * ancho
    n = max(0, min(ancho, hechas * ancho // total))
    return f"{V}{'█' * n}{GR}{'·' * (ancho - n)}{N}"


def edad(ruta):
    if not ruta or not os.path.exists(ruta):
        return "—"
    s = int(time.time() - os.path.getmtime(ruta))
    if s < 90:
        return f"hace {s}s"
    if s < 5400:
        return f"hace {s // 60} min"
    return f"hace {s // 3600} h"



def archivos(carpeta):
    """(HTML de trabajo, PDF original, ruta del PDF entregado o None) de una carpeta."""
    d = os.path.join(TRAB, carpeta)
    htmls = sorted(f for f in os.listdir(d) if f.endswith("_es.html"))
    origs = sorted(f for f in os.listdir(d) if f.endswith(".pdf") and not SALIDA_PROPIA.search(f))
    nombre = ENTREGAS.get(carpeta, (None, None))[0]
    return (os.path.join(d, htmls[0]) if htmls else None,
            os.path.join(d, origs[0]) if origs else None,
            os.path.join(ENTREGA, nombre) if nombre else None)


def bilingue(carpeta):
    d = os.path.join(TRAB, carpeta)
    candidatos = sorted(f for f in os.listdir(d) if f.endswith("_bilingue.html"))
    return os.path.join(d, candidatos[0]) if candidatos else None


def libros():
    """Las carpetas de trabajo que son libros: tienen original o HTML y entregas.tsv no las marca con «-»."""
    out = []
    for c in sorted(os.listdir(TRAB)):
        if not os.path.isdir(os.path.join(TRAB, c)) or (c in ENTREGAS and ENTREGAS[c][0] is None):
            continue
        html, orig, _ = archivos(c)
        if html or orig:
            out.append(c)
    return out


def etapa(carpeta):
    """«N motivo»: 1 traducir · 2 completar (n bloques) · 3 maquetar (por qué) · 0 listo o sin salida.

    Cada etapa se salta sola si ya está hecha, así que flujo.sh puede cortarse y relanzarse las
    veces que haga falta sin repetir nada.
    """
    html, orig, entregado = archivos(carpeta)
    hecho = bool(entregado) and os.path.exists(entregado)
    if not html:
        if bilingue(carpeta):
            return "2 verificar y completar"
        if hecho and orig and os.path.getmtime(entregado) > os.path.getmtime(orig):
            return "0 entregado (sin archivo de trabajo: para rehacerlo hay que retraducir)"
        return "1 traducir" if orig else "0 sin material"
    try:
        quedan = avance.faltan(html)
    except Exception as e:
        return f"0 ✗ no puedo medir el avance: {type(e).__name__}: {str(e)[:80]}"
    if quedan > 0:
        return f"2 completar ({quedan} bloques)"
    if not entregado:
        return "0 sin sitio de entrega (dale de alta: ./flujo.sh --alta CARPETA NOMBRE_ES.pdf)"
    if not hecho:
        return "3 maquetar (no entregado)"
    if os.path.getmtime(html) > os.path.getmtime(entregado):
        return "3 maquetar (el texto cambió)"
    suyo = hojas.formato_de(entregado) or "viejo"
    if suyo != hojas.FORMATO:
        return f"3 maquetar (formato {suyo}, ahora es {hojas.FORMATO})"
    return "0 listo"


def parado(carpeta, e=None):
    """True si flujo.sh dejó este libro parado por la guarda Y nada cambió desde entonces: la huella
    anotada (etapa y fecha del HTML, la misma que calcula flujo.sh) sigue siendo la de ahora."""
    try:
        anotado = open(os.path.join(TRAB, carpeta, ".parado"), encoding="utf-8").read().strip()
    except OSError:
        return False
    html = archivos(carpeta)[0]
    return anotado == f"{e or etapa(carpeta)} @ {int(os.path.getmtime(html)) if html else ''}"



def procesos():
    """Las líneas de comando vivas, para saber qué carpeta está siendo trabajada ahora."""
    r = subprocess.run(["ps", "-Ao", "command"], capture_output=True, text=True)
    return [l for l in r.stdout.splitlines()
            if re.search(r"libro\.sh|main\.py|completar_|rotar_|entregar_libro", l)]


def _cola(ruta, n):
    try:
        return open(ruta, encoding="utf-8", errors="ignore").read()[-n:]
    except OSError:
        return ""


def _logs(d):
    return sorted((os.path.join(d, f) for f in os.listdir(d) if f.endswith(".log")),
                  key=os.path.getmtime, reverse=True)


def motor_en_uso(d):
    """(hora, motor, clave) de lo que está traduciendo ahora, leído del registro del rotador."""
    vistos = re.findall(r"(\d\d:\d\d:\d\d) → (\w+) (\.[\w_]+)", _cola(os.path.join(d, "rotacion.log"), 8000))
    return vistos[-1] if vistos else None


def paso_en_curso(d):
    """En qué paso del traductor va: «3. Completar lo que quedó en inglés»."""
    for log in _logs(d)[:4]:
        pasos = re.findall(r"^== (\d+\. [^\n(]+)", _cola(log, 60000), re.M)
        if pasos:
            return pasos[-1].strip()
    return None


def por_registro(d):
    """Mientras no hay HTML que medir, el registro de libro.sh dice por qué página va.

    Se mira el MÁXIMO de todos los registros, no la última línea del más reciente: al cambiar de
    clave, el traductor reinicia su registro desde la página 1, pero lo traducido sigue en la caché
    y no se repite. Tomando la última línea, el avance parecía volver a cero cada rato.
    """
    mejor, total_mejor, espera = 0, 0, ""
    for log in _logs(d)[:6]:
        cola = _cola(log, 200000)
        for a, b in re.findall(r"pág (\d+)/(\d+)", cola):
            if int(a) > mejor:
                mejor, total_mejor = int(a), int(b)
        if log == _logs(d)[0]:
            esperas = re.findall(r"try again in ([\dhms.]+)", cola[-3000:])
            espera = esperas[-1] if esperas else ""
    if not mejor:
        return None
    aviso = f"  {R}esperando cupo ({espera}){N}" if espera else ""
    eta = _eta(d, mejor, total_mejor)
    eta = f"  {GR}ETA {eta}{N}" if eta else ""
    return f"{barra(mejor, total_mejor)} {mejor * 100 // max(total_mejor, 1):3d}%  pág. {mejor} de {total_mejor}{eta}{aviso}"


def motivo_guarda(carpeta):
    """Por qué la guarda no dejó entregar: la última línea «✗ empeora…» de este libro en flujo.log."""
    pdf = ENTREGAS.get(carpeta, (None, None))[0] or ""
    for linea in reversed(_cola(os.path.join(TRAB, "flujo.log"), 400000).splitlines()):
        if "✗ empeora" in linea and pdf and pdf in linea:
            return linea.split("(", 1)[1].rstrip(") ") if "(" in linea else linea.strip()
    return ""


def racha_sin_avance(d):
    """(cuántas claves seguidas acabaron sin avanzar, desde qué hora) según el registro del rotador.
    «Avanzando, déjalo» con seis claves muertas seguidas era mentir."""
    lineas = _cola(os.path.join(d, "rotacion.log"), 20000).strip().splitlines()
    cortes = [l for l in lineas if re.search(r"estancado|colgado|sin cupo", l)]
    racha, pag_sig = [], None
    for l in reversed(cortes):
        m = re.search(r"pág (\d+)", l)
        pag = int(m.group(1)) if m else None
        if pag_sig is not None and pag is not None and pag != pag_sig:
            break
        racha.append(l)
        pag_sig = pag if pag is not None else pag_sig
    return len(racha), (racha[-1][:8] if racha else "")


def consejo(carpeta, n, corriendo, d):
    """Qué haría yo con este libro. Una frase, concreta."""
    if parado(carpeta):
        por = motivo_guarda(carpeta)
        return (f"{R}la guarda no lo deja entregar" + (f": {por}" if por else "") +
                f". Mira el PDF nuevo en {carpeta}/_limpio.pdf; si está bien, ./flujo.sh --reintentar {carpeta}{N}")
    if corriendo:
        logs = _logs(d)
        quieto = int(time.time() - os.path.getmtime(logs[0])) if logs else 0
        if quieto > 900:
            return f"{R}{quieto // 60} min sin escribir: míralo, puede estar colgado{N}"
        racha, desde = racha_sin_avance(d)
        if racha >= 3:
            return (f"{A}{racha} claves seguidas sin avanzar desde las {desde}: cupo agotado en todos los motores "
                    f"por ahora; el flujo sigue probando y retoma solo cuando se libere{N}")
        ultima = _cola(os.path.join(d, "rotacion.log"), 2000).strip().splitlines()[-1:]
        ultima = ultima[0] if ultima else ""
        if "colgado" in ultima or "estancado" in ultima:
            return f"{A}un proveedor se colgó y el rotador lo cortó; sigue con otra clave, no toques{N}"
        if "ninguna" in ultima or "espero" in ultima:
            return f"{GR}sin cupo ahora mismo; reintenta solo{N}"
        return f"{V}avanzando, déjalo{N}"
    if n == "3":
        return f"{AZ}no gasta cupo: ./flujo.sh {carpeta}{N}"
    return f"{AZ}le toca turno en el flujo; o adelántalo con ./flujo.sh {carpeta}{N}"


def mira(carpeta, vivos):
    """Clasifica un libro: ('marcha'|'falta'|'listo', línea, cuándo, etapa)."""
    d = os.path.join(TRAB, carpeta)
    html, orig, entregado = archivos(carpeta)
    corriendo = any(re.search(rf"[/ ]{re.escape(carpeta)}[/ ]", l) for l in vivos)
    e = etapa(carpeta)
    n, motivo = e[0], e[2:]
    if n == "0":
        if motivo.startswith(("listo", "entregado")):
            return "listo", f"{V}entregado{N} · {os.path.basename(entregado)[:46]}", edad(entregado), n
        return "falta", f"{R if '✗' in motivo else GR}{motivo}{N}", "—", n
    estado = "marcha" if corriendo else "falta"
    if n == "1":
        if corriendo:
            return estado, por_registro(d) or f"{AZ}traduciendo (aún no hay archivo que medir){N}", "—", n
        return estado, f"{GR}original listo, sin empezar o a medias{N}", edad(orig), n
    if n == "2":
        total, hechas, _ = avance.una(html)
        linea = f"{barra(hechas, total)} {hechas * 100 // max(total, 1):3d}%  faltan {total - hechas} de {total} bloques"
        return estado, linea, edad(html), n
    if parado(carpeta, e):
        return "falta", f"{A}sin inglés; la guarda no deja entregar ⏸{N}", edad(os.path.join(d, ".parado")), n
    por_que = motivo.partition("(")[2].rstrip(")")
    return estado, f"{A}sin inglés; falta maquetar y entregar ({por_que}){N}", edad(html), n



CAPS = {"groq": "200k tok/día", "cloudflare": "10k neuronas/día", "gemini": "~250 llam/día",
        "openrouter": "~50 llam/día", "sambanova": "gratis", "mistral": "gratis", "requesty": "gratis"}


def _miles(n):
    return f"{int(n):,}".replace(",", ".")


def _paginas_pdf(ruta):
    if not ruta or not os.path.exists(ruta):
        return 0
    import fitz
    try:
        doc = fitz.open(ruta)
        try:
            return len(doc)
        finally:
            doc.close()
    except Exception:
        return 0


def info_libro(carpeta):
    """Ficha compacta: páginas, palabras (traducidas si hay HTML), figuras, original, entrega, formato."""
    html, orig, entregado = archivos(carpeta)
    base = entregado if entregado and os.path.exists(entregado) else orig
    d = {"paginas": _paginas_pdf(base), "palabras": 0, "figuras": 0,
         "original": os.path.basename(orig) if orig else "—",
         "entrega": os.path.basename(entregado) if entregado else "—", "formato": "—"}
    if html and os.path.exists(html):
        try:
            crudo = open(html, encoding="utf-8", errors="ignore").read()
            d["figuras"] = len(re.findall(r"<img\b", crudo, re.I))
            d["palabras"] = len(re.sub(r"<[^>]+>", " ", hojas._quitar_marcadores_figura(crudo)).split())
        except Exception:
            pass
    if entregado and os.path.exists(entregado):
        try:
            d["formato"] = hojas.formato_de(entregado) or "—"
        except Exception:
            pass
    return d


def _inicio_run(d):
    """Hora «HH:MM:SS» del arranque del run en curso: la última línea «=== … ===» del rotador."""
    marcas = re.findall(r"(\d\d:\d\d:\d\d) === ", _cola(os.path.join(d, "rotacion.log"), 20000))
    return marcas[-1] if marcas else None


def _eta(d, hechas, total):
    """Estimación «~N min» al ritmo medio desde el arranque del run. Vacío si no se puede estimar."""
    ini = _inicio_run(d)
    if not ini or hechas <= 0 or hechas >= total:
        return ""
    ahora = time.localtime()
    h, m, s = (int(x) for x in ini.split(":"))
    transcurrido = (ahora.tm_hour * 3600 + ahora.tm_min * 60 + ahora.tm_sec) - (h * 3600 + m * 60 + s)
    if transcurrido <= 60:
        return ""
    quedan = (total - hechas) * transcurrido / hechas
    if quedan < 90:
        return f"~{int(quedan)}s"
    if quedan < 5400:
        return f"~{int(quedan // 60)} min"
    return f"~{quedan / 3600:.1f} h"


def _logs_de_hoy(sufijo=""):
    """Rutas de rotacion.log (o *.log si sufijo vacío) tocados en las últimas 20 h, por libro."""
    corte = time.time() - 20 * 3600
    for c in sorted(os.listdir(TRAB)):
        d = os.path.join(TRAB, c)
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            if (f == "rotacion.log" if sufijo == "rot" else f.endswith(".log")):
                p = os.path.join(d, f)
                try:
                    if os.path.getmtime(p) >= corte:
                        yield p
                except OSError:
                    continue


def estado_apis():
    """Por motor: claves con cupo / agotadas hoy / cuál en uso, leído de los rotacion.log de hoy."""
    try:
        import claves
        lista = claves.disponibles()
    except Exception as e:
        return [f"  {R}no puedo leer las claves: {type(e).__name__}{N}"]
    por_motor = {}
    for motor, k, _ in lista:
        por_motor.setdefault(motor, []).append(os.path.basename(k))
    sin_cupo, en_uso, visto = set(), None, 0.0
    for rot in _logs_de_hoy("rot"):
        cola = _cola(rot, 40000)
        for _mot, key in re.findall(r"sin cupo en (\w+) (\.[\w_]+)", cola):
            sin_cupo.add(key)
        usos = re.findall(r"→ (\w+) (\.[\w_]+)", cola)
        t = os.path.getmtime(rot)
        if usos and t > time.time() - 900 and t > visto:
            en_uso, visto = usos[-1], t
    filas = []
    for motor in claves.MOTORES:
        ks = por_motor.get(motor, [])
        if not ks:
            continue
        agotadas = sum(1 for k in ks if k in sin_cupo)
        disp = len(ks) - agotadas
        marca = f"  {AZ}← en uso {en_uso[1]}{N}" if en_uso and en_uso[0] == motor else ""
        filas.append(f"  {B}{motor:11s}{N} {(V if disp else R)}{disp}/{len(ks)} con cupo{N}"
                     f"  {GR}({agotadas} agotadas hoy · tope {CAPS.get(motor, '—')}){N}{marca}")
    return filas


def tokens_hoy():
    """Suma aproximada de «tokens de nube: X» (último de cada log) en los libros tocados hoy."""
    total = 0
    for p in _logs_de_hoy(""):
        nums = re.findall(r"tokens de nube:\s*([\d.]+)", _cola(p, 60000))
        if nums:
            try:
                total += int(nums[-1].replace(".", ""))
            except ValueError:
                pass
    return total


def pantalla(todos=False):
    vivos = procesos()
    grupos = {"marcha": [], "falta": [], "listo": []}
    for c in libros():
        d = os.path.join(TRAB, c)
        try:
            estado, linea, cuando, n = mira(c, vivos)
        except Exception as e:
            estado, linea, cuando, n = "falta", f"{R}✗ {type(e).__name__}: {str(e)[:60]}{N}", "—", "0"
        extra = []
        if estado == "marcha":
            uso, paso = motor_en_uso(d), paso_en_curso(d)
            partes = ([f"{AZ}{uso[1]} {uso[2]}{N} desde las {uso[0]}"] if uso else []) \
                + ([f"paso {B}{paso}{N}"] if paso else [])
            if partes:
                extra.append("ahora:  " + " · ".join(partes))
        if estado != "listo":
            try:
                fi = info_libro(c)
                extra.insert(0, f"{GR}info:   {fi['paginas']} pág · {_miles(fi['palabras'])} palabras · "
                                f"{fi['figuras']} figuras · formato {fi['formato']}{N}")
            except Exception:
                pass
            if n in SIGUE:
                extra.append(f"{GR}sigue:  {SIGUE[n]}{N}")
            extra.append(f"qué hago: {consejo(c, n, estado == 'marcha', d)}")
        grupos[estado].append((bonito(c), linea, cuando, extra))

    print(f"\n{B}{AZ} LIBROS {N}  {GR}{time.strftime('%H:%M:%S')}{N}")
    print(f"{GR}{'─' * 64}{N}")
    for clave, titulo, color in (("marcha", "EN MARCHA", V), ("falta", "FALTAN", A)):
        print(f"\n{B}{color}{titulo}{N} {GR}({len(grupos[clave])}){N}")
        if not grupos[clave]:
            print(f"  {GR}ninguno{N}")
        for nom, linea, cuando, extra in grupos[clave]:
            print(f"  {B}{nom[:38]:38s}{N} {linea}  {GR}{cuando}{N}")
            for l in extra:
                print(f"       {l}")
    listos = grupos["listo"]
    print(f"\n{B}{V}LISTOS{N} {GR}({len(listos)}){N}", end="")
    if todos:
        print()
        for nom, linea, cuando, _ in listos:
            print(f"  {B}{nom[:38]:38s}{N} {linea}  {GR}{cuando}{N}")
    else:
        print(f"  {GR}· entregados y al día; con -t se listan{N}")

    print(f"\n{GR}{'─' * 64}{N}")
    carga = subprocess.run(["uptime"], capture_output=True, text=True).stdout
    carga = re.sub(r".*averages?:\s*", "", carga).split()[0] if "average" in carga else "?"
    libre = subprocess.run(["vm_stat"], capture_output=True, text=True).stdout
    paginas = sum(int(n) for n in re.findall(r"Pages (?:free|inactive|speculative):\s+(\d+)", libre))
    print(f"{B}Máquina{N}  carga {carga}  ·  memoria libre: {paginas * 4096 // 1048576} MB")
    print(f"\n{B}{AZ}APIs (claves gratis){N}  {GR}cupo restante por motor; se renueva cada 24 h{N}")
    for fila in (estado_apis() or [f"  {GR}sin claves configuradas{N}"]):
        print(fila)
    tok = tokens_hoy()
    if tok:
        print(f"  {GR}tokens de nube hoy ~{_miles(tok)} (suma de los libros activos){N}")
    print()


def _demo():
    """Autocomprobación de la lógica nueva, sin depender del taller."""
    assert _miles(51624) == "51.624", _miles(51624)
    assert _miles(0) == "0"
    assert _eta("/no/existe", 5, 10) == ""
    assert _eta("/no/existe", 10, 10) == ""
    assert isinstance(estado_apis(), list)
    assert isinstance(tokens_hoy(), int)
    print("estado demo OK")


def main():
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(__doc__)
        return
    if "demo" in sys.argv:
        _demo()
        return
    if "--libros" in sys.argv:
        print("\n".join(libros()))
        return
    if "--etapa" in sys.argv:
        print(etapa(sys.argv[sys.argv.index("--etapa") + 1]))
        return
    todos = "-t" in sys.argv
    if "-s" in sys.argv:
        i = sys.argv.index("-s")
        cada = int(sys.argv[i + 1]) if len(sys.argv) > i + 1 and sys.argv[i + 1].isdigit() else 20
        while True:
            os.system("clear")
            pantalla(todos)
            time.sleep(cada)
    else:
        pantalla(todos)


if __name__ == "__main__":
    main()
