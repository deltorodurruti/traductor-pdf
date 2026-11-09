import os
import subprocess
import tempfile
import unittest

RAIZ = os.path.dirname(os.path.abspath(__file__))
ANTIGUA = 'n=$(grep -o "[0-9]* bloques quedaron SIN traducir" "$TRAB/traducir_$intento.log" | grep -o "^[0-9]*"); [ -z "$n" ] && break'


def linea_actual() -> str:
    with open(os.path.join(RAIZ, "herramientas", "libro.sh"), encoding="utf-8") as f:
        for l in f:
            if l.strip().startswith('n=$(grep -o "[0-9]* bloques quedaron SIN traducir"'):
                return l.strip()
    raise AssertionError("no encuentro la línea del reintento en libro.sh")


def correr(linea: str, log: str):
    """Ejecuta la línea del reintento tal como la ejecuta libro.sh (set -euo pipefail, dentro de su bucle)."""
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "traducir_1.log"), "w", encoding="utf-8") as f:
            f.write(log)
        guion = f'set -euo pipefail\nTRAB="{d}"\nfor intento in 1; do\n{linea}\necho siguio\ndone\necho fin\n'
        r = subprocess.run(["bash", "-c", guion], capture_output=True, text=True)
        return r.returncode, r.stdout


class ReintentosDeLibro(unittest.TestCase):
    def test_sin_bloques_pendientes_el_libro_sigue_con_los_pasos_siguientes(self):
        codigo, salida = correr(linea_actual(), "traducción completa, sin pendientes\n")
        self.assertEqual(codigo, 0)
        self.assertIn("fin", salida)

    def test_con_bloques_pendientes_se_reintenta(self):
        codigo, salida = correr(linea_actual(), "  ⚠ 3 bloques quedaron SIN traducir (vuelve a ejecutar)\n")
        self.assertEqual(codigo, 0)
        self.assertIn("siguio", salida)

    def test_la_version_anterior_detenia_el_libro(self):
        codigo, _ = correr(ANTIGUA, "traducción completa, sin pendientes\n")
        self.assertNotEqual(codigo, 0, "esta es la causa: sin pendientes, la versión anterior salía con error")


if __name__ == "__main__":
    unittest.main()
