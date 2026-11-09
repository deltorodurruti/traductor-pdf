import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "herramientas"))

import entregar_libro
import completar_libro
import herramientas.auditar_imagenes as auditar_imagenes
import herramientas.completar_bloques as completar_bloques
import herramientas.paginas_con_tablas as paginas_con_tablas
import herramientas.pegar_figuras as pegar_figuras
import herramientas.rehacer_paginas_vacias as rehacer_paginas_vacias
import _verify_book


class CompletarBloquesTests(unittest.TestCase):
    def test_dos_respuestas_invalidas_conservan_el_bloque(self):
        with tempfile.TemporaryDirectory() as td:
            html = Path(td) / "libro_es.html"
            original = "the and of this text remains in the source"
            html.write_text(
                f"<section class='page'><div class='page-num'>Página 1</div>"
                f"<div class='solo'>{original}</div></section>", encoding="utf-8"
            )
            backend = mock.Mock()
            backend.available.return_value = (True, "")
            masker = mock.Mock()
            with mock.patch.object(completar_bloques, "traducir", side_effect=[
                "I cannot translate this", "I cannot translate this"
            ]), mock.patch("translate.make_backend", return_value=backend), \
                    mock.patch("main.load_glossary", return_value=[]), \
                    mock.patch("main.make_masker", return_value=masker), \
                    mock.patch("main.bad_translation", return_value=True), \
                    mock.patch.object(sys, "argv", ["completar_bloques.py", str(html), "--aplicar", "--yes-cloud"]):
                completar_bloques.main()
            self.assertIn(original, html.read_text(encoding="utf-8"))


class EntregaTests(unittest.TestCase):
    def _run_una(self, returncode, make_pdf):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "libro"
            entrega = Path(td) / "entrega"
            d.mkdir()
            entrega.mkdir()
            (d / "libro_es.html").write_text(
                "<section class='page'><div class='solo'>texto español</div></section>",
                encoding="utf-8",
            )
            entregar_libro.ENTREGADOS = {"libro": "libro.pdf"}
            entregar_libro.ENTREGA = str(entrega)
            entregar_libro.FORZAR = True

            def run(cmd, **kwargs):
                if make_pdf:
                    import fitz
                    doc = fitz.open()
                    page = doc.new_page()
                    page.insert_text((40, 40), "texto español")
                    doc.save(cmd[3])
                    doc.close()
                return subprocess.CompletedProcess(cmd, returncode, "", "falló")

            with mock.patch.object(entregar_libro.subprocess, "run", side_effect=run):
                return entregar_libro._una("libro", str(d)), entrega / "libro.pdf"

    def test_no_entrega_si_maquetado_devuelve_error_aunque_haya_pdf(self):
        ok, destino = self._run_una(1, True)
        self.assertFalse(ok)
        self.assertFalse(destino.exists())

    def test_no_entrega_pdf_vacio_en_primera_entrega(self):
        ok, destino = self._run_una(0, False)
        self.assertFalse(ok)
        self.assertFalse(destino.exists())

    def test_cerrojo_exclusivo_reemplaza_pid_muerto(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / ".maquetando").write_text("99999999", encoding="ascii")
            cerrojo = entregar_libro._adquirir_cerrojo(str(d))
            self.assertTrue(cerrojo)
            try:
                self.assertEqual((d / ".maquetando").read_text(encoding="ascii"), str(os.getpid()))
            finally:
                cerrojo.close()

    def test_cerrojo_flock_conserva_descriptor_y_no_borra_archivo(self):
        with tempfile.TemporaryDirectory() as td:
            primero = entregar_libro._adquirir_cerrojo(td)
            self.assertTrue(primero)
            try:
                self.assertFalse(entregar_libro._adquirir_cerrojo(td))
            finally:
                primero.close()
            segundo = entregar_libro._adquirir_cerrojo(td)
            self.assertTrue(segundo)
            segundo.close()
            self.assertTrue((Path(td) / ".maquetando").exists())

    def test_una_libera_flock_tras_excepcion_y_retorno_temprano(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "libro"
            d.mkdir()
            old_base = entregar_libro.BASE
            entregar_libro.BASE = td
            try:
                with mock.patch.object(entregar_libro, "_una", side_effect=RuntimeError("fallo")):
                    with self.assertRaises(RuntimeError):
                        entregar_libro.una("libro")
                cerrojo = entregar_libro._adquirir_cerrojo(str(d))
                self.assertTrue(cerrojo)
                cerrojo.close()

                with mock.patch.object(entregar_libro, "_una", return_value=False):
                    self.assertFalse(entregar_libro.una("libro"))
                cerrojo = entregar_libro._adquirir_cerrojo(str(d))
                self.assertTrue(cerrojo)
                cerrojo.close()
            finally:
                entregar_libro.BASE = old_base

    def test_una_borra_temporal_si_medir_falla(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "libro"
            d.mkdir()
            (d / "libro_es.html").write_text("<html>texto</html>", encoding="utf-8")
            entrega = Path(td) / "entrega"
            entrega.mkdir()
            old = (entregar_libro.ENTREGADOS, entregar_libro.ENTREGA, entregar_libro.FORZAR)
            entregar_libro.ENTREGADOS = {"libro": "libro.pdf"}
            entregar_libro.ENTREGA = str(entrega)
            entregar_libro.FORZAR = True
            temporal = d / ".limpio-falla.pdf"
            temporal.write_bytes(b"pdf")
            try:
                with mock.patch.object(entregar_libro, "arreglar", return_value=("nuevo", 1)), \
                        mock.patch.object(entregar_libro, "titulo_corrido", return_value=("nuevo", 0)), \
                        mock.patch.object(entregar_libro, "_pdf_temporal", return_value=str(temporal)), \
                        mock.patch.object(entregar_libro.subprocess, "run",
                                          return_value=types.SimpleNamespace(returncode=0, stdout="", stderr="")), \
                        mock.patch.object(entregar_libro, "_pdf_valido", return_value=True), \
                        mock.patch.object(entregar_libro, "referencia_de", return_value="referencia.pdf"), \
                        mock.patch.object(entregar_libro, "medir", side_effect=RuntimeError("medir")):
                    with self.assertRaises(RuntimeError):
                        entregar_libro._una("libro", str(d))
                self.assertFalse(temporal.exists())
            finally:
                entregar_libro.ENTREGADOS, entregar_libro.ENTREGA, entregar_libro.FORZAR = old

    def test_pdf_temporal_es_unico(self):
        with tempfile.TemporaryDirectory() as td:
            a = entregar_libro._pdf_temporal(td)
            b = entregar_libro._pdf_temporal(td)
            self.assertNotEqual(a, b)
            for p in (a, b):
                self.assertFalse(os.path.exists(p))

    def test_pdf_solo_imagen_es_valido(self):
        import fitz
        with tempfile.TemporaryDirectory() as td:
            origen = Path(td) / "imagen.pdf"
            png = Path(td) / "imagen.png"
            doc = fitz.open()
            pagina = doc.new_page()
            pix = fitz.Pixmap(fitz.csRGB, (0, 0, 20, 20))
            pix.clear_with(0x336699)
            pagina.insert_image(pagina.rect, pixmap=pix)
            doc.save(str(origen))
            doc.close()
            self.assertTrue(entregar_libro._pdf_valido(str(origen)))

    def test_rechazo_conserva_pdf_limpio_y_exito_lo_elimina(self):
        def run(cmd, **kwargs):
            import fitz
            doc = fitz.open()
            doc.new_page().insert_text((40, 40), "texto español")
            doc.save(cmd[3])
            doc.close()
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "libro"
            entrega = Path(td) / "entrega"
            d.mkdir()
            entrega.mkdir()
            (d / "libro_es.html").write_text("<section class='page'><div class='solo'>texto</div></section>", encoding="utf-8")
            (d / "libro_ES.pdf").write_bytes(b"referencia")
            limpio = d / "_limpio.pdf"
            limpio.write_bytes(b"residuo viejo")
            old = (entregar_libro.ENTREGADOS, entregar_libro.ENTREGA, entregar_libro.FORZAR)
            try:
                entregar_libro.ENTREGADOS = {"libro": "libro.pdf"}
                entregar_libro.ENTREGA = str(entrega)
                entregar_libro.FORZAR = True
                with mock.patch.object(entregar_libro.subprocess, "run", side_effect=run), \
                        mock.patch.object(entregar_libro, "medir", side_effect=[(100, 0), (50, 0)]), \
                        mock.patch.object(entregar_libro, "palabras", side_effect=[100, 100]):
                    self.assertFalse(entregar_libro._una("libro", str(d)))
                self.assertTrue(limpio.exists())
                self.assertFalse((entrega / "libro.pdf").exists())

                with mock.patch.object(entregar_libro.subprocess, "run", side_effect=run), \
                        mock.patch.object(entregar_libro, "medir", side_effect=[(100, 0), (100, 0)]), \
                        mock.patch.object(entregar_libro, "palabras", side_effect=[100, 100]):
                    self.assertTrue(entregar_libro._una("libro", str(d)))
                self.assertFalse(limpio.exists())
                self.assertTrue((entrega / "libro.pdf").exists())
            finally:
                entregar_libro.ENTREGADOS, entregar_libro.ENTREGA, entregar_libro.FORZAR = old

    def test_cerrojo_perdido_no_muestra_pid_none(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(entregar_libro, "_ocupado", return_value=None), \
                mock.patch.object(entregar_libro, "_adquirir_cerrojo", return_value=False), \
                mock.patch.object(entregar_libro, "_una", side_effect=AssertionError("no debe entrar")), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as salida:
            self.assertFalse(entregar_libro.una("libro"))
            self.assertNotIn("pid None", salida.getvalue())

    def test_fallo_de_replace_conserva_html_y_pdf_anterior(self):
        with tempfile.TemporaryDirectory() as td:
            html = Path(td) / "libro.html"
            html.write_text("viejo", encoding="utf-8")
            with mock.patch("render.os.replace", side_effect=OSError("disco lleno")):
                with self.assertRaises(OSError):
                    paginas_con_tablas.aplicar(str(html), {1: "nuevo"})
            self.assertEqual(html.read_text(encoding="utf-8"), "viejo")

            pdf = Path(td) / "libro.pdf"
            pdf.write_bytes(b"viejo-pdf")
            origen = Path(td) / "origen.pdf"
            origen.write_bytes(b"nuevo-pdf")
            with mock.patch.object(entregar_libro.os, "replace", side_effect=OSError("disco lleno")):
                with self.assertRaises(OSError):
                    entregar_libro._copiar_atomico(str(origen), str(pdf))
            self.assertEqual(pdf.read_bytes(), b"viejo-pdf")


class CompletarLibroTests(unittest.TestCase):
    def test_falta_consentimiento_no_rota_claves_ni_duerme(self):
        proceso = mock.Mock()
        proceso.poll.return_value = 78
        proceso.returncode = 78
        avance = types.SimpleNamespace(faltan=mock.Mock(return_value=1))
        claves = types.SimpleNamespace(
            disponibles=lambda: [("groq", "clave-1", {}), ("gemini", "clave-2", {})],
            espera_pedida=mock.Mock(return_value=0),
            sin_cupo=mock.Mock(side_effect=AssertionError("no debe mirar cupo")),
        )
        with tempfile.TemporaryDirectory() as td:
            html = Path(td) / "libro_es.html"
            html.write_text("<html></html>", encoding="utf-8")
            with mock.patch.dict(sys.modules, {"avance": avance, "claves": claves}), \
                    mock.patch.object(completar_libro.subprocess, "Popen", return_value=proceso) as popen, \
                    mock.patch.object(completar_libro.time, "sleep") as dormir, \
                    mock.patch.object(sys, "argv", ["completar_libro.py", str(html)]), \
                    mock.patch.dict(os.environ, {"ESPERAR": "1"}, clear=False):
                self.assertEqual(completar_libro.main(), 78)
        popen.assert_called_once()
        dormir.assert_not_called()


class FlujoTests(unittest.TestCase):
    def test_versos_cloud_del_flujo_llevan_yes_cloud(self):
        texto = (ROOT / "herramientas" / "libro.sh").read_text(encoding="utf-8")
        for linea in texto.splitlines():
            if linea.lstrip().startswith("#"):
                continue
            if any(nombre in linea for nombre in ("completar_bloques.py", "paginas_con_tablas.py")):
                self.assertIn("--yes-cloud", linea, linea)

    def test_main_devuelve_error_si_un_libro_falla(self):
        old_base, old_pedidos = entregar_libro.BASE, entregar_libro.PEDIDOS
        try:
            with tempfile.TemporaryDirectory() as td, mock.patch.object(entregar_libro, "BASE", td), \
                    mock.patch.object(entregar_libro, "PEDIDOS", ["libro"]), \
                    mock.patch.object(entregar_libro, "una", return_value=False):
                Path(td, "libro").mkdir()
                self.assertEqual(entregar_libro.main(), 1)
        finally:
            entregar_libro.BASE, entregar_libro.PEDIDOS = old_base, old_pedidos


class VerifyTests(unittest.TestCase):
    def test_entrada_sin_filas_es_fatal_y_no_escribe(self):
        with tempfile.TemporaryDirectory() as td:
            bil = Path(td) / "v.html"
            solo = Path(td) / "s.html"
            bil.write_text("<html><body><p>sin filas</p></body></html>", encoding="utf-8")
            r = subprocess.run([sys.executable, str(ROOT / "_verify_book.py"), str(bil), str(solo)],
                               capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertFalse(solo.exists())

    def test_residuos_son_advertencia_y_no_frenan_el_flujo(self):
        rows = "".join(
            "<div class='row'><div class='col src'>Hello</div>"
            "<div class='col tgt'>information breve</div></div>" for _ in range(6)
        )
        with tempfile.TemporaryDirectory() as td:
            bil, solo = Path(td) / "v.html", Path(td) / "s.html"
            bil.write_text(f"<html><body>{rows}</body></html>", encoding="utf-8")
            cmd = f"{sys.executable} {ROOT / '_verify_book.py'} {bil} {solo} en | tail -5"
            r = subprocess.run(["bash", "-o", "pipefail", "-c", cmd], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("ADVERTENCIA", r.stdout)


class TablasTests(unittest.TestCase):
    def test_no_secciona_tabla_si_falta_una_traduccion(self):
        items = [(0, "tabla", [["English cell", "Other cell"]])]
        with self.assertRaises(RuntimeError):
            paginas_con_tablas.seccion(1, items, {})

    def test_aplicar_html_usa_escritura_atomica(self):
        with tempfile.TemporaryDirectory() as td:
            ruta = Path(td) / "libro.html"
            ruta.write_text("<section class='page'><div class='page-num'>Página 1</div>viejo</section>", encoding="utf-8")
            with mock.patch.object(paginas_con_tablas, "escribir_atomico", wraps=paginas_con_tablas.escribir_atomico) as guardar:
                paginas_con_tablas.aplicar(str(ruta), {1: "<section class='page'><div class='page-num'>Página 1</div>nuevo</section>"})
            self.assertTrue(guardar.called)


class AuditoriaTests(unittest.TestCase):
    def test_error_de_extraccion_no_se_convierte_en_auditoria_vacia(self):
        with mock.patch.object(auditar_imagenes.fitz, "open", return_value=[mock.Mock()]), \
                mock.patch.object(auditar_imagenes.figuras, "figuras_pagina", side_effect=ValueError("PDF roto")):
            with self.assertRaises(RuntimeError):
                auditar_imagenes.de_fuente("dummy.pdf")


class RehacerTests(unittest.TestCase):
    def test_no_guarda_si_una_pagina_desborda(self):
        class Page:
            rect = mock.Mock(width=600, height=800)

            def __init__(self, texto):
                self.texto = texto

            def get_text(self, kind=None):
                if kind == "blocks":
                    return [(0, 0, 100, 100, self.texto, 0, 0)]
                return self.texto

            def insert_htmlbox(self, *args, **kwargs):
                return (-1, None)

        class Doc:
            def __init__(self, pages):
                self.pages = pages

            def __iter__(self):
                return iter(self.pages)

            def __len__(self):
                return len(self.pages)

            def __getitem__(self, i):
                return self.pages[i]

        with tempfile.TemporaryDirectory() as td:
            salida = Path(td) / "salida.pdf"
            cache = Path(str(salida) + ".json")
            fuente = ("texto original " * 30).strip()
            cache.write_text(json.dumps({fuente: "traducción"}), encoding="utf-8")
            tr, orig = Doc([Page("P Á G I N A 1")]), Doc([Page(fuente)])
            with mock.patch.object(rehacer_paginas_vacias.fitz, "open", side_effect=[tr, orig]), \
                    mock.patch.object(rehacer_paginas_vacias, "guardar_pdf_atomico") as guardar, \
                    mock.patch.object(sys, "argv", ["rehacer_paginas_vacias.py", "tr.pdf", "or.pdf", str(salida), "--yes-cloud"]):
                self.assertEqual(rehacer_paginas_vacias.main(), 1)
            guardar.assert_not_called()


if __name__ == "__main__":
    unittest.main()
