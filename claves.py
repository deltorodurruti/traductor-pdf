#!/usr/bin/env python3
"""Qué claves gratis hay, en qué orden probarlas y con qué variable las lee cada motor.

Única fuente de esa lista. La armaba cada script por su cuenta, con su propio criterio: al aparecer
una clave nueva había que acordarse de tocarlos todos, y al agotarse Groq se quedaban parados sin
probar los demás motores. La usan `rotar_libro.sh` (con --env) y `completar_libro.py`.


El orden INTERCALA proveedores (una de Groq, una de Gemini, una de OpenRouter, vuelta a empezar):
puestas en bloques, un libro gastaba doce intentos en Groq agotado antes de probar nada más.

Uso:  claves.py            una por línea: «motor<TAB>ruta»
      claves.py --env      añade las variables de entorno con que ese motor lee su clave
      claves.py --sin-cupo la expresión de «se acabó el cupo», para los scripts de shell
      claves.py --espera   lee texto por la entrada y dice los segundos que pide esperar (0 si nada)
"""
from __future__ import annotations

import glob
import os
import re
import sys
from itertools import zip_longest

HOME = os.path.expanduser("~")
MOTORES = ("groq", "gemini", "openrouter", "cloudflare", "sambanova", "mistral", "cohere", "requesty")


SIN_CUPO = (
    r"tokens per day|TPD|RESOURCE_EXHAUSTED|rate.?limit|quota|(?:HTTP|Error|code\W*)\s*429"
    r"|429 Client Error|insufficient|high demand|payment method|daily free allocation"
    r"|used up your daily|credit balance"
)
_SIN_CUPO = re.compile(SIN_CUPO, re.I)
_RELOJ = re.compile(r"(?:try again|retry) in (?:([\d.]+)h)?(?:([\d.]+)m)?(?:([\d.]+)s)?"
                    r"|espero (\d+) min (\d+) s", re.I)


def sin_cupo(texto: str) -> bool:
    """True si la respuesta del servidor dice, de cualquiera de sus formas, que no queda cupo."""
    return bool(_SIN_CUPO.search(texto or ""))


def espera_pedida(texto: str) -> int:
    """Segundos que pide esperar la ÚLTIMA respuesta del texto, o 0 si no lo dice."""
    vistos = _RELOJ.findall(texto or "")
    if not vistos:
        return 0
    h, m, s, m2, s2 = (float(x) if x else 0.0 for x in vistos[-1])
    return int(h * 3600 + (m + m2) * 60 + s + s2)


def cuenta_cloudflare(clave: str) -> str | None:
    """El id de cuenta que acompaña a una clave de Workers AI, o None si no está.

    Se derivaba en cinco sitios distintos con cinco variantes del mismo cálculo.
    """
    sufijo = re.sub(r"^\.cloudflare_key", "", os.path.basename(clave))
    try:
        with open(os.path.join(HOME, f".cloudflare_account{sufijo}")) as fh:
            return fh.read().strip() or None
    except OSError:
        return None


def _n(ruta: str) -> int:
    """El número del final del nombre, para ordenar key2 antes que key10."""
    return int(re.sub(r"\D", "", os.path.basename(ruta)) or 1)


def disponibles() -> list[tuple[str, str, dict]]:
    """[(motor, ruta de la clave, variables de entorno)] intercalando proveedores."""
    por_motor: dict[str, list[tuple[str, str, dict]]] = {}
    for motor in MOTORES:
        for k in sorted(glob.glob(os.path.join(HOME, f".{motor}_key*")), key=_n):
            env = {f"{motor.upper()}_KEY_FILE": k}
            if motor == "cloudflare":
                cuenta = cuenta_cloudflare(k)
                if not cuenta:
                    continue
                env["CLOUDFLARE_ACCOUNT_ID"] = cuenta
            por_motor.setdefault(motor, []).append((motor, k, env))
    FAMILIAS = (("groq", "cloudflare", "sambanova"), ("gemini",), ("openrouter",),
                ("mistral",), ("requesty",))
    salida: list = []
    for familia in FAMILIAS:
        for ronda in zip_longest(*(por_motor.get(m, []) for m in familia)):
            salida += [k for k in ronda if k]
    listados = {m for fam in FAMILIAS for m in fam}
    for m in MOTORES:
        if m not in listados:
            salida += por_motor.get(m, [])
    return salida


def demo() -> None:
    """Autocomprobación: hay claves, no se repiten y el orden agrupa por motor."""
    lista = disponibles()
    assert lista, "no encuentro ninguna clave en ~/.<motor>_key*"
    rutas = [k for _, k, _ in lista]
    assert len(rutas) == len(set(rutas)), "hay claves repetidas"
    motores = [m for m, _, _ in lista]
    gpt_oss = {"groq", "cloudflare", "sambanova"}
    pos_fam = [i for i, m in enumerate(motores) if m in gpt_oss]
    pos_otros = [i for i, m in enumerate(motores) if m not in gpt_oss]
    if pos_fam and pos_otros:
        assert max(pos_fam) < min(pos_otros), f"gpt-oss debe ir antes que otras familias: {motores}"
        fam_motores = [m for m in motores if m in gpt_oss]
        if len({m for m in fam_motores}) > 1:
            assert fam_motores[0] != fam_motores[1], f"la familia no intercala: {fam_motores[:4]}"
    for motor, k, env in lista:
        assert env.get(f"{motor.upper()}_KEY_FILE") == k
    for si in ("Rate limit reached. Please try again in 5m36s", "RESOURCE_EXHAUSTED", "HTTP 429",
               "429 Client Error: Too Many Requests", '"code": 429', "used up your daily free allocation"):
        assert sin_cupo(si), si
    for no in ("[pág 429/830 ████] pág 429 [texto] 3 bloques", "4290 car.", "quedan 429 bloques", "pág 1/289"):
        assert not sin_cupo(no), no
    assert espera_pedida("Please try again in 5m36.2s") == 336
    assert espera_pedida("retry in 30s") == 30
    assert espera_pedida("x: quota — espero 1 min 20 s") == 80
    assert espera_pedida("nada") == 0
    print(f"demo OK · {len(lista)} claves de {len(set(motores))} motores · empieza por {motores[:3]}")


if __name__ == "__main__":
    if "demo" in sys.argv:
        demo()
    elif "--sin-cupo" in sys.argv:
        print(SIN_CUPO)
    elif "--espera" in sys.argv:
        print(espera_pedida(sys.stdin.read()))
    else:
        con_env = "--env" in sys.argv
        for motor, k, env in disponibles():
            extra = " " + " ".join(f"{a}={b}" for a, b in env.items()) if con_env else ""
            print(f"{motor}\t{k}{extra}")
