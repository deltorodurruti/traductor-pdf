import os
import re
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
FUENTES = (ROOT / "herramientas" / "libro.sh", ROOT / "flujo.sh",
           ROOT / "rotar_libro.sh", ROOT / "completar_libro.py")


class ContratosFlujoTests(unittest.TestCase):
    def test_toda_llamada_remota_del_flujo_lleva_yes_cloud(self):
        fuentes = (ROOT / "herramientas" / "libro.sh", ROOT / "flujo.sh", ROOT / "rotar_libro.sh")
        objetivos = ("completar_bloques.py", "paginas_con_tablas.py",
                     "rehacer_paginas_vacias.py", "traducir_in_situ.py", "maquetar_versos.py",
                     "completar_libro.py")
        encontrados = set()
        for fuente in fuentes:
            texto = fuente.read_text(encoding="utf-8").replace("\\\n", " ")
            for linea in texto.splitlines():
                if linea.lstrip().startswith("#"):
                    continue
                for objetivo in objetivos:
                    if objetivo in linea:
                        encontrados.add(objetivo)
                        self.assertIn("--yes-cloud", linea,
                                      f"{fuente.name}: llamada sin --yes-cloud: {linea.strip()}")
        self.assertTrue({"completar_bloques.py", "paginas_con_tablas.py",
                         "completar_libro.py"} <= encontrados)

    def _scripts_con_bandera(self):
        encontrados = set()
        for fuente in FUENTES:
            for linea in fuente.read_text(encoding="utf-8").splitlines():
                if linea.lstrip().startswith("#") or "--yes-cloud" not in linea:
                    continue
                for nombre in re.findall(r"[A-Za-z0-9_./-]+\.py", linea):
                    nombre = nombre.rsplit("/", 1)[-1]
                    ruta = next(ROOT.rglob(nombre), None)
                    if ruta:
                        encontrados.add(ruta)
        return sorted(encontrados)

    def test_cada_script_con_yes_cloud_publica_la_bandera_en_help(self):
        scripts = self._scripts_con_bandera()
        self.assertTrue(scripts)
        for script in scripts:
            with self.subTest(script=script.name):
                r = subprocess.run([sys.executable, str(script), "--help"],
                                   capture_output=True, text=True)
                ayuda = r.stdout + r.stderr
                if "--yes-cloud" not in ayuda and script.name == "":
                    r = subprocess.run([sys.executable, str(script), "enviar", "--help"],
                                       capture_output=True, text=True)
                    ayuda = r.stdout + r.stderr
                self.assertEqual(r.returncode, 0, ayuda)
                self.assertIn("--yes-cloud", ayuda, str(script))

    def test_completar_libro_reenvia_yes_cloud_al_subproceso(self):
        import completar_libro

        proceso = mock.Mock()
        proceso.poll.return_value = 0
        proceso.returncode = 0
        with tempfile.TemporaryDirectory() as td:
            html = Path(td) / "libro_es.html"
            html.write_text("<html></html>", encoding="utf-8")
            avance = types.SimpleNamespace(faltan=mock.Mock(side_effect=[1, 1, 0]))
            claves = types.SimpleNamespace(
                disponibles=lambda: [("groq", "clave", {})],
                espera_pedida=lambda _: 0,
                sin_cupo=lambda _: False,
            )
            with mock.patch.dict(sys.modules, {"avance": avance, "claves": claves}), \
                    mock.patch.object(completar_libro.subprocess, "Popen", return_value=proceso) as popen, \
                    mock.patch.object(completar_libro.time, "sleep"), \
                    mock.patch.dict(os.environ, {"ESPERAR": "0"}, clear=False), \
                    mock.patch.object(sys, "argv", ["completar_libro.py", str(html), "--yes-cloud"]):
                self.assertEqual(completar_libro.main(), 0)
            argv = popen.call_args.args[0]
            self.assertIn("--yes-cloud", argv)


if __name__ == "__main__":
    unittest.main()
