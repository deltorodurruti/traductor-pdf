"""Test de hojas.py: una hoja por página, el texto no se pierde, el exceso se encoge."""
import os, re, tempfile, unittest
from unittest import mock

import hojas


def _dir_prueba():
    """_prueba/ está en .gitignore: en un checkout limpio no existe y TemporaryDirectory falla."""
    os.makedirs("_prueba", exist_ok=True)
    return os.path.abspath("_prueba")

try:
    import fitz
except ImportError:
    fitz = None


def _html(extra_p3=0):
    pag = lambda n, cuerpo: f'<section class="page"><div class="page-num">Página {n}</div>{cuerpo}</section>'
    solo = lambda t: f'<div class="solo">{t}</div>'
    largo = " ".join(["casa"] * 330)
    return ('<!doctype html><html><body><header><h1>x</h1></header>'
            + pag(1, solo("TÍTULO DEL CAPÍTULO") + solo("Texto breve."))
            + pag(2, solo(largo) * 1)
            + pag(3, solo(largo) * (extra_p3 + 2))
            + '</body></html>')


class Hojas(unittest.TestCase):
    def test_es_solo(self):
        with tempfile.TemporaryDirectory() as d:
            a = os.path.join(d, "a.html"); open(a, "w", encoding="utf-8").write(_html())
            b = os.path.join(d, "b.html"); open(b, "w", encoding="utf-8").write(_html().replace("solo", "row").replace('class="row"', 'class="col src"'))
            self.assertTrue(hojas.es_solo(a)); self.assertFalse(hojas.es_solo(b))

    def test_titulo_y_estructura(self):
        h = hojas.construir_html(_html())
        self.assertEqual(h.count("class='hoja'"), 3)
        self.assertIn("<p class='tit'>TÍTULO DEL CAPÍTULO</p>", h)

    @unittest.skipUnless(fitz, "requiere PyMuPDF")
    def test_solo_imagen_sustituye_el_texto_por_la_pagina_del_original(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "o.pdf")
            doc = fitz.open()
            for _ in range(3):
                doc.new_page().insert_text((72, 100), "portada original")
            doc.save(src)
            h = hojas.construir_html(_html(), original=src, solo_imagen=frozenset({1}))
            normal = hojas.construir_html(_html(), original=src)
        hoja1 = h.split("<section class='hoja'")[1]
        self.assertIn("data:image/jpeg;base64,", hoja1)
        self.assertNotIn("Texto breve.", hoja1)
        self.assertIn("Texto breve.", normal)

    def test_pdf_una_hoja_por_pagina_sin_perder_texto(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "l_es.html"); open(src, "w", encoding="utf-8").write(_html())
            pdf = hojas.maquetar(src, log=lambda *a: None)
            doc = fitz.open(pdf)
            self.assertEqual(len(doc), 3)
            txt = [re.sub(r"\s+", " ", p.get_text()) for p in doc]
            for i, t in enumerate(txt, 1):
                self.assertRegex(t, rf"P\s*Á\s*G\s*I\s*N\s*A\s*{' ?'.join(str(i))}")
            self.assertEqual(txt[2].count("casa"), 330 * 2)

    def test_desborde_pasa_a_segunda_hoja_sin_recortar(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "l_es.html"); open(src, "w", encoding="utf-8").write(_html(extra_p3=10))
            doc = fitz.open(hojas.maquetar(src, log=lambda *a: None))
            self.assertGreater(len(doc), 3)
            self.assertEqual(sum(p.get_text().count("casa") for p in doc), 330 * 13)

    def test_desborde_reportado_no_aborta_la_impresion(self):
        class FakeDoc:
            metadata = {}

            def __len__(self):
                return 3

            def close(self):
                pass

        fake_fitz = mock.Mock(open=mock.Mock(return_value=FakeDoc()))

        def run(args, **kwargs):
            if "--dump-dom" in args:
                return mock.Mock(stdout="<div id='informe' data-desborde='3' data-encogidas='0'></div>")
            destino = next(x.split("=", 1)[1] for x in args if x.startswith("--print-to-pdf="))
            with open(destino, "wb") as f:
                f.write(b"PDF")
            return mock.Mock(stdout="")

        with tempfile.TemporaryDirectory(dir=_dir_prueba()) as d:
            src = os.path.join(d, "l_es.html")
            open(src, "w", encoding="utf-8").write(_html())
            with mock.patch.object(hojas, "_chrome", return_value="fake"), \
                 mock.patch.object(hojas.subprocess, "run", side_effect=run), \
                 mock.patch.object(hojas, "_sellar"), \
                 mock.patch.dict("sys.modules", {"fitz": fake_fitz}):
                pdf = hojas.maquetar(src, log=lambda *a: None)
            self.assertTrue(os.path.exists(pdf))


if __name__ == "__main__":
    unittest.main()


class SinCabecera(unittest.TestCase):
    def test_sin_rotulo_de_pagina_y_con_mismo_texto(self):
        con = hojas.construir_html(_html())
        sin = hojas.construir_html(_html(), cabecera=False)
        self.assertIn("<div class='num'>Página 2</div>", con)
        self.assertNotIn("class='num'", sin)
        self.assertEqual(sin.count("class='hoja'"), 3)
        quita_alto = lambda h: re.sub(r"min-height:\d+px", "min-height:0px", h)
        self.assertEqual(quita_alto(re.sub(r"<div class='num'>[^<]*</div>", "", con)), quita_alto(sin))

    def test_sin_cabecera_pdf_sin_hojas_en_blanco(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "l_es.html"); open(src, "w", encoding="utf-8").write(_html())
            pdf = hojas.maquetar(src, log=lambda *a: None, cabecera=False)
            doc = fitz.open(pdf)
            self.assertEqual(len(doc), 3)
            txt = [re.sub(r"\s+", " ", p.get_text()) for p in doc]
            self.assertTrue(all(t.strip() for t in txt))
            self.assertEqual(txt[2].count("casa"), 330 * 2)


class FolioNumerico(unittest.TestCase):
    """El número de página desnudo del original («12», «19») se quita, pero sin comerse versos,
    listas ni contenido que empiece con mayúscula."""

    def test_detecta_folio_y_descarta_prosa(self):
        folio = [str(n) if n % 3 else f"{n} el texto sigue" for n in range(12, 40)]
        self.assertTrue(hojas._folio_numerico(folio))
        self.assertFalse(hojas._folio_numerico(["En el principio", "Capítulo uno", "El texto"] * 4))
        self.assertFalse(hojas._folio_numerico(["72 autores", "en la antología", "y capítulos"] * 3))

    def test_limpiar_quita_folio_desnudo_solo_con_flag(self):
        items = [("t", "12 eso sigue la frase")]
        self.assertEqual(hojas._texto(hojas._limpiar(items, None, folio_num=True)[0][1]),
                         "eso sigue la frase")
        self.assertEqual(hojas._texto(hojas._limpiar(items, None, folio_num=False)[0][1]),
                         "12 eso sigue la frase")

    def test_no_toca_contenido_ni_listas(self):
        self.assertIsNone(hojas.FOLIO_INICIO_NUM.match("72 autores de la antología"))
        self.assertIsNone(hojas.FOLIO_INICIO_NUM.match("1. primer punto"))
