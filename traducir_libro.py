#!/usr/bin/env python3
"""traducir_libro.py — un libro del taller, de principio a fin, con un solo comando.

Envoltura del flujo que ya existe (rotar_libro.sh · completar_libro.py · libro_nuevo.py).
Traduce con los motores disponibles por rotación de claves. Reanudable: le
pregunta a estado.py en qué etapa va el libro y se salta lo que ya está hecho.

    traducir_libro.py LIBRO [--maquetar] [--revisar] [--todo] [-n]

LIBRO   carpeta del taller (las que lista `estado.py --libros`).

    (sin flags)   traducir + completar  → deja el HTML en español listo
    --maquetar    además, maqueta en FORMATO LIBRO (portada, índice, justificado) y entrega
    --revisar     además, revisa el PDF entregado (inglés suelto y errores de OCR).
    --todo        = --maquetar --revisar
    -n, --simular imprime los comandos sin ejecutar nada

La traducción se realiza con los motores configurados y la revisión
es local. Variables: PYTHON/PY (intérprete con fitz/bs4), TRAB (taller), ENTREGA (carpeta de
entrega), TRADUCTOR_CHROME (navegador para maquetar).
"""
import argparse
import filecmp
import glob
import os
import re
import shutil
import subprocess
import sys

AQUI = os.path.dirname(os.path.realpath(__file__))
PY = os.environ.get("PYTHON") or os.environ.get("PY") or shutil.which("python3") or sys.executable
TRAB = os.environ.get("TRAB", os.path.expanduser("~/traductor/taller"))
ENTREGA = os.environ.get("ENTREGA", os.path.expanduser("~/traductor/libros_esp"))
BRAVE = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"

SALIDA_PROPIA = re.compile(r"_ES|_nuevo|_v[0-9]|antes|limpio|trabajo")


def _entrega_de(lineas, libro, entrega_dir):
    """Ruta del PDF de entrega del libro según las líneas de entregas.tsv, o None.
    Formato: «carpeta<TAB>nombre.pdf<TAB>nombre bonito». Pura, para poder probarla."""
    for ln in lineas:
        if ln.startswith("#") or "\t" not in ln:
            continue
        campos = ln.rstrip("\n").split("\t")
        if campos and campos[0] == libro and len(campos) > 1 and campos[1].strip():
            return os.path.join(entrega_dir, campos[1].strip())
    return None


def entrega_de(libro):
    try:
        with open(os.path.join(TRAB, "entregas.tsv"), encoding="utf-8") as fh:
            return _entrega_de(fh.readlines(), libro, ENTREGA)
    except OSError:
        return None


def etapa(libro):
    """Etapa según estado.py: 1 traducir · 2 completar · 3 maquetar · 0 listo/sin salida."""
    try:
        r = subprocess.run([PY, os.path.join(AQUI, "estado.py"), "--etapa", libro],
                           capture_output=True, text=True, cwd=AQUI)
        ultima = r.stdout.strip().splitlines()[-1]
        if r.returncode or "✗" in ultima:
            raise ValueError(ultima)
        return int(ultima.split()[0])
    except (ValueError, IndexError, OSError) as e:
        sys.exit(f"✗ no pude leer la etapa de {libro} con estado.py: {e}")


def correr(cmd, simular, env=None):
    print("   $ " + " ".join(cmd))
    if simular:
        return 0
    return subprocess.run(cmd, cwd=AQUI, env=env).returncode


def _parser():
    ap = argparse.ArgumentParser(
        prog="traducir_libro.py",
        description="Traduce un libro del taller de principio a fin.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("libro", help="carpeta del taller (ver estado.py --libros)")
    ap.add_argument("--maquetar", action="store_true", help="maqueta en formato libro y entrega")
    ap.add_argument("--revisar", action="store_true", help="revisa el PDF entregado (local)")
    ap.add_argument("--todo", action="store_true", help="= --maquetar --revisar")
    ap.add_argument("-n", "--simular", action="store_true", help="muestra los comandos sin ejecutar")
    return ap


def _expandir(a):
    if a.todo:
        a.maquetar = a.revisar = True
    return a


def _asegura_carpeta(libro, simular=False):
    """Acepta una carpeta del taller O la ruta a un PDF. Si es un PDF, lo da de alta: crea TRAB/<slug>/,
    copia el PDF dentro y registra su entrega con `entregas.alta`. El PDF traducido siempre va a ENTREGA
    (libros_esp), venga el original de donde venga. Devuelve el nombre de carpeta a usar."""
    ruta = os.path.abspath(os.path.expanduser(libro))
    if not (libro.lower().endswith(".pdf") and os.path.isfile(ruta)):
        return libro
    import unicodedata
    import entregas
    base = re.sub(r"[\[(].*?[\])]", "", os.path.splitext(os.path.basename(ruta))[0])
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_") or "libro"
    destino = os.path.join(TRAB, slug)
    dest_pdf = os.path.join(destino, slug + ".pdf")
    if os.path.exists(dest_pdf) and not filecmp.cmp(ruta, dest_pdf, shallow=False):
        sys.exit(f"✗ ya existe {dest_pdf} y es OTRO PDF: renombra el archivo o borra esa carpeta")
    if simular:
        print(f"$ alta: {os.path.basename(ruta)} → taller/{slug}/  (simulado: no copio ni registro)")
        return slug
    os.makedirs(destino, exist_ok=True)
    if not os.path.exists(dest_pdf):
        shutil.copy2(ruta, dest_pdf)
        print(f"alta: {os.path.basename(ruta)} → taller/{slug}/  (entrega en libros_esp)")
    bonito = " ".join(w.capitalize() for w in slug.split("_"))
    entregas.alta(slug, f"{bonito.replace(' ', '_')}_ES.pdf", bonito, TRAB)
    return slug


def main(argv=None):
    a = _expandir(_parser().parse_args(argv))

    a.libro = _asegura_carpeta(a.libro, a.simular)
    d = os.path.join(TRAB, a.libro)
    if not os.path.isdir(d) and a.simular:
        print("(simulado: la carpeta aún no existe; empezaría por 1. traducir)")
        return
    if not os.path.isdir(d):
        sys.exit(f"✗ no existe la carpeta del libro: {d}\n  (libros disponibles: estado.py --libros)")

    glos_todos = sorted(glob.glob(os.path.join(d, "glosario*.txt")))
    glos = [glos_todos[0]] if glos_todos else []
    e0 = etapa(a.libro)

    if e0 == 1:
        orig = next((p for p in sorted(glob.glob(os.path.join(d, "*.pdf")))
                     if not SALIDA_PROPIA.search(os.path.basename(p))), None)
        if not orig:
            sys.exit(f"✗ no encuentro el PDF original en {d}")
        print(f"== 1. traducir (rotación de claves) · {os.path.basename(orig)}")
        if correr([os.path.join(AQUI, "rotar_libro.sh"), d, orig] + glos, a.simular) != 0:
            sys.exit("✗ la traducción no terminó (cupo agotado o error; mira el registro). Relánzalo: retoma donde quedó")

    if e0 in (1, 2):
        html = next(iter(sorted(glob.glob(os.path.join(d, "*_es.html")))), None)
        if not html:
            bil = next(iter(sorted(glob.glob(os.path.join(d, "*_bilingue.html")))), None)
            if bil:
                html = bil[:-len("_bilingue.html")] + "_es.html"
                print("== verificar y sacar el solo-español")
                if correr([PY, os.path.join(AQUI, "_verify_book.py"), bil, html, "en"], a.simular) != 0:
                    sys.exit("✗ la verificación del HTML bilingüe falló")
        if html or a.simular:
            print("== 2. completar lo que quedó en inglés ")
            correr([PY, os.path.join(AQUI, "completar_libro.py"), html or "<es.html>"] + glos
                   + ["--yes-cloud"], a.simular)

    if a.maquetar and not a.simular and etapa(a.libro) in (1, 2):
        sys.exit("✗ quedan bloques en inglés: no maqueto. Relánzalo cuando haya cupo (retoma donde quedó)")
    if a.maquetar:
        print("== 3. maquetar en formato libro y entregar")
        env = dict(os.environ)
        env.setdefault("TRADUCTOR_CHROME", BRAVE)
        if correr([PY, os.path.join(AQUI, "herramientas", "libro_nuevo.py"), a.libro, "--entregar"],
                  a.simular, env=env) != 0:
            sys.exit("✗ el maquetado de libro falló")

    if a.revisar:
        pdf = entrega_de(a.libro)
        if not pdf:
            sys.exit(f"✗ {a.libro} no está en entregas.tsv; no sé qué PDF revisar")
        if not a.simular and not os.path.exists(pdf):
            sys.exit(f"✗ no existe el PDF entregado: {pdf}\n  (¿faltó --maquetar?)")
        print(f"== 4. revisar (local) · {os.path.basename(pdf)}")
        correr([PY, os.path.join(AQUI, "herramientas", "escanear_pdf.py"), pdf], a.simular)

    print("✅ listo" + (" (simulado)" if a.simular else ""))
    if not a.maquetar:
        print("   (traducción lista; usa --maquetar para el PDF en formato libro)")


def _autotest():
    lineas = ["# comentario\n",
              "libro_a\tLibro_A_ES.pdf\tLibro A\n",
              "libro_b\t\n",
              "libro_c\tLibro_C_ES.pdf\n"]
    assert _entrega_de(lineas, "libro_a", "/x") == "/x/Libro_A_ES.pdf"
    assert _entrega_de(lineas, "libro_b", "/x") is None
    assert _entrega_de(lineas, "libro_c", "/x") == "/x/Libro_C_ES.pdf"
    assert _entrega_de(lineas, "noexiste", "/x") is None
    assert _expandir(_parser().parse_args(["x", "--todo"])).maquetar is True
    assert _expandir(_parser().parse_args(["x", "--todo"])).revisar is True
    a = _expandir(_parser().parse_args(["x"]))
    assert a.maquetar is False and a.revisar is False
    assert not SALIDA_PROPIA.search("Libro_B.pdf")
    assert SALIDA_PROPIA.search("Libro_B_ES.pdf")
    assert SALIDA_PROPIA.search("libro_v4.pdf") and SALIDA_PROPIA.search("algo_limpio.pdf")
    import tempfile
    from unittest import mock
    global TRAB
    falla = mock.Mock(returncode=0, stdout="0 ✗ no puedo medir el avance: OSError")
    with mock.patch("subprocess.run", return_value=falla):
        try:
            etapa("x")
            raise AssertionError("etapa() tomó un error como etapa 0")
        except SystemExit:
            pass
    with tempfile.TemporaryDirectory() as t:
        TRAB, viejo = t, TRAB
        try:
            pdf = os.path.join(t, "Mi Libro.pdf")
            open(pdf, "wb").write(b"%PDF uno")
            assert _asegura_carpeta(pdf, simular=True) == "mi_libro"
            assert not os.path.exists(os.path.join(t, "mi_libro")), "simular creó la carpeta"
            os.makedirs(os.path.join(t, "mi_libro"))
            open(os.path.join(t, "mi_libro", "mi_libro.pdf"), "wb").write(b"%PDF dos")
            try:
                _asegura_carpeta(pdf)
                raise AssertionError("reutilizó un PDF distinto con el mismo nombre")
            except SystemExit:
                pass
        finally:
            TRAB = viejo
    print("autotest OK")


if __name__ == "__main__":
    if "--autotest" in sys.argv:
        _autotest()
    else:
        main()
