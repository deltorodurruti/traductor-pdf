#!/usr/bin/env python3
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import fitz

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "herramientas"))

import entregar_libro
from herramientas import libro_nuevo


def pdf_text(path, words):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox((40, 40, 550, 780), " ".join(words), fontsize=8)
    doc.save(str(path))
    doc.close()


class LibroNuevoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.base = root / "trab"
        self.book = self.base / "libro"
        self.entrega = root / "entrega"
        self.respaldo = root / "respaldo"
        self.book.mkdir(parents=True)
        self.entrega.mkdir()
        self.respaldo.mkdir()
        (self.book / "libro_es.html").write_text(
            "<section class='page'><div class='solo'>" + " ".join(f"palabra{i}" for i in range(100))
            + "</div></section>", encoding="utf-8"
        )
        (self.book / "libro_ES.pdf").write_bytes(b"salida propia")
        (self.book / "original.pdf").write_bytes(b"original")
        (self.base / "entregas.tsv").write_text("libro\tLibro.pdf\tNombre bonito\n", encoding="utf-8")
        self.old = (libro_nuevo.BASE, libro_nuevo.ENTREGA, libro_nuevo.RESPALDO,
                    entregar_libro.BASE, entregar_libro.ENTREGA,
                    entregar_libro.RESPALDO, entregar_libro.ENTREGADOS)
        libro_nuevo.BASE = str(self.base)
        libro_nuevo.ENTREGA = str(self.entrega)
        libro_nuevo.RESPALDO = str(self.respaldo)
        entregar_libro.BASE = str(self.base)
        entregar_libro.ENTREGA = str(self.entrega)
        entregar_libro.RESPALDO = str(self.respaldo)
        entregar_libro.ENTREGADOS = {"libro": "Libro.pdf"}

    def tearDown(self):
        (libro_nuevo.BASE, libro_nuevo.ENTREGA, libro_nuevo.RESPALDO,
         entregar_libro.BASE, entregar_libro.ENTREGA,
         entregar_libro.RESPALDO, entregar_libro.ENTREGADOS) = self.old
        self.tmp.cleanup()

    def test_fuentes_elige_html_y_original(self):
        html, original = entregar_libro.fuentes(str(self.book))
        self.assertEqual(Path(html).name, "libro_es.html")
        self.assertEqual(Path(original).name, "original.pdf")

    def test_metadatos_argumento_gana_tsv_entregas_y_carpeta(self):
        (self.base / "libros_meta.tsv").write_text("libro\tTSV\tAutor TSV\n", encoding="utf-8")
        self.assertEqual(libro_nuevo.metadatos("libro", "Argumento", "Autor"), ("Argumento", "Autor"))
        self.assertEqual(libro_nuevo.metadatos("libro"), ("TSV", "Autor TSV"))
        (self.base / "libros_meta.tsv").unlink()
        self.assertEqual(libro_nuevo.metadatos("libro"), ("Nombre bonito", ""))
        (self.base / "entregas.tsv").write_text("libro\tLibro.pdf\n", encoding="utf-8")
        self.assertEqual(libro_nuevo.metadatos("libro"), ("libro", ""))

    def _run(self, *args):
        argv = ["libro_nuevo.py", str(self.book), *args]
        with mock.patch.object(sys, "argv", argv):
            return libro_nuevo.main()

    def _maquetar_ok(self, html, pdf, **kwargs):
        pdf_text(pdf, [f"palabra{i}" for i in range(100)])
        return pdf

    def test_sin_navegador_sale_2_y_no_escribe(self):
        with mock.patch.object(libro_nuevo.render, "find_chrome", return_value=None), \
                mock.patch.object(libro_nuevo.hojas, "maquetar") as maquetar:
            self.assertEqual(self._run(), 2)
        self.assertFalse((self.book / "_libro_nuevo.pdf").exists())
        maquetar.assert_not_called()

    def test_cerrojo_ocupado_sale_3(self):
        cerrojo = entregar_libro._adquirir_cerrojo(str(self.book))
        try:
            with mock.patch.object(libro_nuevo.render, "find_chrome", return_value="chrome"):
                self.assertEqual(self._run(), 3)
        finally:
            cerrojo.close()

    def test_revision_falla_si_falta_texto(self):
        pdf = self.book / "candidato.pdf"
        pdf_text(pdf, ["palabra"] * 96)
        resultado = libro_nuevo.revisar(str(pdf), str(self.book / "libro_es.html"))
        self.assertTrue(resultado.fail)

    def test_revision_avisa_si_sobra_texto(self):
        pdf = self.book / "candidato.pdf"
        pdf_text(pdf, ["palabra"] * 116)
        resultado = libro_nuevo.revisar(str(pdf), str(self.book / "libro_es.html"))
        self.assertFalse(resultado.fail)
        self.assertTrue(resultado.warn)

    def test_revision_no_avisa_por_marcador_de_figura_y_usa_umbral_115(self):
        self.book.joinpath("libro_es.html").write_text(
            "<section class='page'><div class='solo'>"
            + " ".join(f"palabra{i}" for i in range(100))
            + "<br/>[figura: mapa]</div></section>", encoding="utf-8"
        )
        pdf = self.book / "candidato.pdf"
        pdf_text(pdf, ["palabra"] * 113)
        salida = io.StringIO()
        with mock.patch("sys.stdout", salida):
            resultado = libro_nuevo.revisar(str(pdf), str(self.book / "libro_es.html"))
        self.assertFalse(resultado.warn)
        self.assertIn("(1.130)\tOK", salida.getvalue())

    def test_revision_cuenta_entradas_reales_del_indice(self):
        self.book.joinpath("libro_es.html").write_text(
            "<section class='indice'><h2>Índice</h2>"
            "<div class='entrada-indice'><span>Uno</span><span class='puntos'>...</span><span class='pagina'>12</span></div>"
            "<div class='entrada-indice'><span>Dos</span><span class='puntos'>...</span><span class='pagina'>13</span></div>"
            "</section>", encoding="utf-8"
        )
        pdf = self.book / "candidato.pdf"
        pdf_text(pdf, ["palabra"] * 100)
        salida = io.StringIO()
        with mock.patch("sys.stdout", salida):
            libro_nuevo.revisar(str(pdf), str(self.book / "libro_es.html"))
        self.assertIn("índice\t2 entradas", salida.getvalue())

    def test_entrega_respalda_y_copia(self):
        (self.entrega / "Libro.pdf").write_bytes(b"anterior")
        with mock.patch.object(libro_nuevo.render, "find_chrome", return_value="chrome"), \
                mock.patch.object(libro_nuevo.hojas, "maquetar", side_effect=self._maquetar_ok):
            self.assertEqual(self._run("--entregar"), 0)
        self.assertEqual((self.entrega / "Libro.pdf").read_bytes()[:4], b"%PDF")
        self.assertEqual((self.respaldo / "Libro.pdf.antes_libro").read_bytes(), b"anterior")

    def test_justificado_por_defecto_y_bandera_lo_desactiva(self):
        with mock.patch.object(libro_nuevo.render, "find_chrome", return_value="chrome"), \
                mock.patch.object(libro_nuevo.hojas, "maquetar", side_effect=self._maquetar_ok) as maquetar:
            self.assertEqual(self._run(), 0)
            self.assertTrue(maquetar.call_args.kwargs["libro_justificado"])

        with mock.patch.object(libro_nuevo.render, "find_chrome", return_value="chrome"), \
                mock.patch.object(libro_nuevo.hojas, "maquetar", side_effect=self._maquetar_ok) as maquetar:
            self.assertEqual(self._run("--bandera"), 0)
            self.assertFalse(maquetar.call_args.kwargs["libro_justificado"])

    def test_temporal_fallido_no_tapa_error_y_libera_cerrojo(self):
        with mock.patch.object(libro_nuevo.render, "find_chrome", return_value="chrome"), \
                mock.patch.object(libro_nuevo, "_temporal", side_effect=OSError("sin temporal")):
            self.assertEqual(self._run(), 1)
        cerrojo = entregar_libro._adquirir_cerrojo(str(self.book))
        try:
            self.assertTrue(cerrojo)
        finally:
            cerrojo.close()

    def test_no_entrega_si_revision_falla(self):
        def corta(html, pdf, **kwargs):
            pdf_text(pdf, ["palabra"] * 90)
            return pdf
        with mock.patch.object(libro_nuevo.render, "find_chrome", return_value="chrome"), \
                mock.patch.object(libro_nuevo.hojas, "maquetar", side_effect=corta):
            self.assertEqual(self._run("--entregar"), 1)
        self.assertFalse((self.entrega / "Libro.pdf").exists())

    def test_carpeta_fuera_de_entregas_sale_4(self):
        entregar_libro.ENTREGADOS = {}
        with mock.patch.object(libro_nuevo.render, "find_chrome", return_value="chrome"), \
                mock.patch.object(libro_nuevo.hojas, "maquetar") as maquetar:
            self.assertEqual(self._run("--entregar"), 4)
        maquetar.assert_not_called()

    def test_entrega_rechaza_libro_fuera_de_base_aunque_repita_basename(self):
        externo = Path(self.tmp.name) / "externo" / self.book.name
        externo.mkdir(parents=True)
        (externo / "libro_es.html").write_text("<section class='page'>texto</section>", encoding="utf-8")
        salida = self.entrega / "Libro.pdf"
        with mock.patch.object(libro_nuevo.render, "find_chrome", return_value="chrome"), \
                mock.patch.object(libro_nuevo.hojas, "maquetar") as maquetar:
            self.assertEqual(libro_nuevo.ejecutar(str(externo), entregar=True), 4)
        self.assertFalse(salida.exists())
        maquetar.assert_not_called()

    def test_sin_entregar_no_escribe_en_entrega(self):
        with mock.patch.object(libro_nuevo.render, "find_chrome", return_value="chrome"), \
                mock.patch.object(libro_nuevo.hojas, "maquetar", side_effect=self._maquetar_ok):
            self.assertEqual(self._run(), 0)
        self.assertEqual(list(self.entrega.iterdir()), [])

    def test_informe_indica_cantidad_y_origen_manual_de_titulos(self):
        (self.book / "libro_es.html").write_text(
            '<section class="page"><div class="page-num">Página 5</div>'
            '<div class="solo">CAPÍTULO 1<br/>Texto.</div></section>',
            encoding="utf-8",
        )
        (self.book / "titulos.tsv").write_text("1\tCAPÍTULO 1\n", encoding="utf-8")
        salida = io.StringIO()
        with mock.patch.object(libro_nuevo.render, "find_chrome", return_value="chrome"), \
                mock.patch.object(libro_nuevo.hojas, "maquetar", side_effect=self._maquetar_ok) as maquetar, \
                mock.patch("sys.stdout", salida):
            self.assertEqual(self._run(), 0)
        self.assertEqual(maquetar.call_args.kwargs["titulos_manual"], [
            {"nivel": 1, "texto": "CAPÍTULO 1", "suma": "", "linea": 1}
        ])
        self.assertIn("títulos: 1 (manual)", salida.getvalue())


if __name__ == "__main__":
    unittest.main()
