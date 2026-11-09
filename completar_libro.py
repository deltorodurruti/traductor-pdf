#!/usr/bin/env python3
"""Completa los bloques que quedaron en inglés de un HTML solo-español, rotando las claves gratis.

Corre `completar_bloques.py --aplicar` con una clave; si se agota el cupo, sigue con la siguiente.
Cada pasada reescribe el HTML, así que al reanudar se parte de lo ya hecho y no se repite trabajo.
Un bloque que tras traducirse sigue pareciendo inglés (una bibliografía, una lista de siglas) queda
marcado por completar_bloques.py y no se vuelve a pedir: antes se pedía en cada pasada, con cada
clave, una hora tras otra, para siempre.

Es la etapa 2 de flujo.sh; se puede correr suelto.

Uso: completar_libro.py libro_es.html [glosario.txt] [--yes-cloud]
Variables: PLAZO_POR_CLAVE  segundos que se le dan a cada clave antes de pasar a la siguiente (1800)
           ESPERA_MAX       si la cuenta pide esperar más que esto, se cambia de clave (150)
           ESPERAR          0 = al agotarse todas, no esperar una hora a que renueve el cupo
"""
import os
import subprocess
import sys
import time

HTML = GLOS = RAIZ = PY = LOG = VIVO = ""
YES_CLOUD = False
PLAZO = ESPERA_MAX = 0
CODIGO_SIN_CONSENTIMIENTO = 78


def apunta(msg):
    linea = f"{time.strftime('%H:%M:%S')} {msg}"
    print(linea, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(linea + "\n")


def quedan():
    """Bloques que siguen en inglés. Antes se parseaba el HTML entero con BeautifulSoup una vez por
    clave: minutos cada vez, 1,8 h de puro contar en un libro. avance.py lo lee por trozos y guarda
    el resultado mientras el archivo no cambie."""
    return avance.faltan(HTML)


def pasada(motor, env):
    """Una pasada con una clave. Devuelve por qué se cortó, o '' si terminó por sí sola.

    La salida va a un archivo según se produce: así se ve el avance en marcha y se puede cortar en
    cuanto la cuenta diga que no queda cupo, en vez de esperar turnos de cinco minutos que no llegan.
    """
    with open(VIVO, "w", encoding="utf-8") as sal:
        argv = [PY, "herramientas/completar_bloques.py", HTML, "--motor", motor]
        if GLOS:
            argv += ["--glosario", GLOS]
        if YES_CLOUD:
            argv.append("--yes-cloud")
        argv.append("--aplicar")
        proc = subprocess.Popen(argv,
                                cwd=RAIZ, env={**os.environ, **env}, stdout=sal,
                                stderr=subprocess.STDOUT, text=True)
        fin = time.time() + PLAZO
        while proc.poll() is None:
            time.sleep(15)
            cola = open(VIVO, encoding="utf-8", errors="ignore").read()[-1500:]
            pide = claves.espera_pedida(cola)
            if "daily free allocation" in cola:
                corte = "sin cupo del día"
            elif pide > ESPERA_MAX:
                corte = f"la cuenta pide esperar {pide // 60} min"
            elif time.time() > fin:
                corte = f"{PLAZO // 60} min sin terminar"
            else:
                continue
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
            return corte
    if not proc.returncode:
        return ""
    if proc.returncode == CODIGO_SIN_CONSENTIMIENTO:
        return CODIGO_SIN_CONSENTIMIENTO
    cola = open(VIVO, encoding="utf-8", errors="ignore").read()[-700:]
    return "cupo agotado" if claves.sin_cupo(cola) else f"fallo ({proc.returncode}): {cola.strip()[-220:]}"


def main():
    global HTML, GLOS, RAIZ, PY, LOG, VIVO, PLAZO, ESPERA_MAX, YES_CLOUD, avance, claves
    args = [x for x in sys.argv[1:] if x != "--yes-cloud"]
    YES_CLOUD = len(args) != len(sys.argv[1:])
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    HTML = os.path.abspath(args[0])
    GLOS = os.path.abspath(args[1]) if len(args) > 1 and os.path.exists(args[1]) else ""
    RAIZ = os.path.dirname(os.path.abspath(__file__))
    PY = sys.executable
    LOG = HTML + ".completar.log"
    VIVO = HTML + ".en_curso.log"
    PLAZO = int(os.environ.get("PLAZO_POR_CLAVE", 1800))
    ESPERA_MAX = int(os.environ.get("ESPERA_MAX", 150))
    sys.path[:0] = [RAIZ, os.path.join(RAIZ, "herramientas")]
    import avance
    import claves
    n0 = quedan()
    if n0 < 0:
        apunta(f"✗ no existe {HTML}")
        return 2
    if not n0:
        apunta("nada que hacer")
        return 0
    lista = claves.disponibles()
    if not lista:
        apunta("✗ no encuentro ninguna clave en ~/.<motor>_key*")
        return 2
    apunta(f"=== {os.path.basename(HTML)}: {n0} bloques por completar · {len(lista)} claves ===")
    for ciclo in range(1, 7):
        for i, (motor, k, env) in enumerate(lista, 1):
            n = quedan()
            if not n:
                apunta(f"✅ COMPLETO: 0 bloques en inglés (eran {n0})")
                return 0
            apunta(f"[{i}/{len(lista)}] {motor} {os.path.basename(k)} · quedan {n}")
            corte = pasada(motor, env)
            if corte == CODIGO_SIN_CONSENTIMIENTO:
                apunta("✗ falta --yes-cloud / TRADUCTOR_NUBE_OK=1; no se reintentan claves")
                return CODIGO_SIN_CONSENTIMIENTO
            apunta(f"    {corte}, paso a la siguiente (lo hecho queda guardado)" if corte else "    pasada hecha")
        n = quedan()
        if not n:
            apunta(f"✅ COMPLETO (eran {n0})")
            return 0
        if os.environ.get("ESPERAR", "1") != "1":
            break
        apunta(f"⏸ quedan {n} bloques y ninguna cuenta tiene cupo (ciclo {ciclo}); espero una hora y sigo")
        time.sleep(3600)
    apunta(f"⏸ quedan {quedan()} bloques y ninguna clave con cupo ahora (eran {n0}); el flujo vuelve a probar")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
