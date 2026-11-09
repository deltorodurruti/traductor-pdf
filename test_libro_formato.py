import os
import base64
import re
import stat
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stderr
from io import StringIO
from unittest import mock

from bs4 import BeautifulSoup

import estructura
import hojas
import render


def _dir_prueba():
    """_prueba/ está en .gitignore: en un checkout limpio no existe y TemporaryDirectory falla."""
    os.makedirs("_prueba", exist_ok=True)
    return os.path.abspath("_prueba")

try:
    import fitz
except ImportError:
    fitz = None


class LibroFormato(unittest.TestCase):
    @unittest.skipUnless(fitz, "requiere PyMuPDF")
    def test_recupera_tres_niveles_desde_tipografia_y_posicion(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "tipografia.pdf")
            doc = fitz.open()
            page = doc.new_page(width=420, height=600)
            page.insert_text((60, 70), "CAPÍTULO", fontsize=24, fontname="hebo")
            page.insert_text((60, 115), "Sección práctica", fontsize=16, fontname="hebo")
            page.insert_text((60, 150), "Texto del cuerpo que ocupa una línea normal.", fontsize=11)
            page.insert_text((60, 220), "3. Entrada del catálogo", fontsize=11, fontname="hebo")
            page.insert_text((60, 255), "Otro párrafo de cuerpo suficientemente largo.", fontsize=11)
            doc.save(path)
            doc.close()

            titles = estructura.titulos_desde_pdf(path)

        self.assertEqual([t["nivel"] for t in titles], [1, 2, 3])
        self.assertEqual([t["pagina"] for t in titles], [1, 1, 1])
        self.assertEqual(titles[2]["texto"], "3. Entrada del catálogo")

    def test_indice_tiene_anclas_y_dos_pasadas_hasta_estabilizar(self):
        html = hojas.construir_html(
            '<section class="page"><div class="page-num">Página 1</div>'
            '<div class="solo">Capítulo Uno<br/>Texto.</div></section>',
            libro=True,
            titulo="Prueba",
            autor="Autora",
        )
        self.assertIn("class='indice'", html)
        self.assertIn("data-indice-pasada", html)
        self.assertIn("href='#titulo-", html)

        llamadas = []

        def medir(actual):
            llamadas.append(actual)
            return {"titulo-1": 4} if len(llamadas) == 1 else {"titulo-1": 4}

        estable = hojas._estabilizar_indice("<span class='pagina' data-target='titulo-1'>0</span>", medir)
        self.assertEqual(len(llamadas), 2)
        self.assertIn(">4<", estable)

    def test_figuras_conservan_parrafos_agrupados(self):
        fake = mock.Mock()
        fake.quitar_cabeza.side_effect = lambda x: x
        fake.quitar_cola.side_effect = lambda x: x
        fake.colocar.return_value = [("t", "línea larga que continúa<br/>segunda línea")]
        with mock.patch.dict("sys.modules", {"figuras": fake}):
            out, _ = hojas._componer(
                [("t", "línea larga que continúa<br/>segunda línea")], figs=["figura"]
            )
        self.assertEqual(sum(x.startswith("<p>") for x in out), 1)
        self.assertIn("segunda línea", out[0])

    def test_linea_de_metadatos_no_se_pega_al_parrafo_siguiente(self):
        self.assertEqual(
            hojas._parrafos("Registro que describe 22 capítulos<br/>Este término es idéntico al anterior."),
            ["Registro que describe 22 capítulos", "Este término es idéntico al anterior."],
        )

    def test_faltan_hojas_se_propaga_y_no_traga_el_error(self):
        self.assertTrue(hasattr(hojas, "_validar_paginas"))
        with self.assertRaises(RuntimeError):
            hojas._validar_paginas(1, 2, "libro.pdf")

    def test_impresion_es_atomica(self):
        with tempfile.TemporaryDirectory() as d:
            html = os.path.join(d, "libro.html")
            pdf = os.path.join(d, "libro.pdf")
            with open(html, "w", encoding="utf-8") as f:
                f.write("<html></html>")
            llamadas = []

            def run(args, **kwargs):
                llamadas.append(args)
                if "--dump-dom" in args:
                    return mock.Mock(stdout="<div id='informe' data-desborde='' data-encogidas='0'></div>")
                destino = next(x.split("=", 1)[1] for x in args if x.startswith("--print-to-pdf="))
                with open(destino, "wb") as f:
                    f.write(b"PDF")
                return mock.Mock(stdout="")

            with mock.patch("hojas.subprocess.run", side_effect=run):
                hojas._imprimir_html("chrome", html, pdf)
            self.assertTrue(os.path.exists(pdf))
            self.assertFalse(os.path.exists(pdf + ".tmp"))
            self.assertIn("--print-to-pdf=" + pdf + ".tmp", llamadas[1])

    def test_continuacion_minúscula_se_une_aunque_las_lineas_sean_cortas(self):
        self.assertEqual(
            hojas._parrafos("Por lo menos, esta doctrina<br/>parecían hacer que los milagros..."),
            ["Por lo menos, esta doctrina parecían hacer que los milagros..."],
        )

    def test_ficha_de_etermu_se_separa_del_primer_parrafo(self):
        self.assertEqual(
            hojas._parrafos(
                "HGYONY (Lógico) pronunciado Ha - gui - Oh - ni Presidente que gobierna 33 capítulos "
                "Al igual que el término #31, este término enseña lógica."
            ),
            [
                "HGYONY (Lógico) pronunciado Ha - gui - Oh - ni Presidente que gobierna 33 capítulos",
                "Al igual que el término #31, este término enseña lógica.",
            ],
        )

    def test_entradas_numeradas_quitan_duplicado_y_comparten_nivel(self):
        cuerpo = [
            "<p>6. Purson</p>", "<p>Los administradores financieros han hecho un trabajo encomiable.</p>",
            "<p>6. Purson</p>", "<p>7. Haagenti</p>", "<p>8. Furcas</p>",
        ]
        out = hojas._normalizar_cuerpo_libro(cuerpo)
        self.assertEqual(sum(hojas._texto(x) == "6. Purson" for x in out), 1)
        self.assertTrue(all("titulo-3" in x for x in out if re.match(r"<p>\d+\.\s", x)))

    def test_indice_incluye_niveles_y_conserva_orden_sin_aliases(self):
        entrada = (
            '<section class="page"><div class="page-num">Página 2</div><div class="solo">'
            "Preliminar.</div></section>"
            '<section class="page"><div class="page-num">Página 5</div><div class="solo">'
            "Capítulo Uno<br/>Sección Uno<br/>1. Agares<br/>Los resultados</div></section>"
        )
        titulos = [
            {"nivel": 1, "texto": "Capítulo Uno", "pagina_original": 5, "id": "titulo-1"},
            {"nivel": 2, "texto": "Sección Uno", "pagina_original": 5, "id": "titulo-2"},
            {"nivel": 3, "texto": "1. Agares", "pagina_original": 5, "id": "titulo-3"},
            {"nivel": 3, "texto": "Los resultados", "pagina_original": 5, "id": "titulo-4"},
        ]
        with mock.patch.object(hojas, "_titulos_traducidos", return_value=titulos):
            html = hojas.construir_html(entrada, libro=True)
        indice = html.split("<section class='indice'", 1)[1].split("</section>", 1)[0]
        posiciones = [indice.index(texto) for texto in ("Capítulo Uno", "Sección Uno", "1. Agares", "Los resultados")]
        self.assertEqual(posiciones, sorted(posiciones))
        self.assertEqual(indice.count("href='#titulo-"), 4)
        self.assertNotIn("Revisión de los elementos prácticos", indice)
        self.assertIn(".entrada-indice a{color:inherit;text-decoration:none}", html)
        self.assertIn(".entrada-indice.nivel-3{padding-left:3em}", html)
        self.assertIn("page-break-inside:avoid", html)

    def test_css_libro_neutraliza_enlaces_del_cuerpo_y_baja_interlineado(self):
        css = hojas.LIBRO_CSS % {"W": 8.5, "H": 11, "ALIGN": "left", "HYPHENS": "auto"}
        self.assertIn(".cuerpo a{color:inherit;text-decoration:none;border:0}", css)
        self.assertIn("body{font-family:Georgia,'Times New Roman',serif;font-size:10.8pt;line-height:1.3}", css)

    def test_css_libro_dimensiona_figuras_y_laminas(self):
        css = hojas.LIBRO_CSS % {"W": 8.5, "H": 11, "ALIGN": "left", "HYPHENS": "auto"}
        self.assertIn(
            ".cuerpo img.fig{display:block;max-width:100%;max-height:80vh;margin:.7em auto;"
            "break-inside:avoid;page-break-inside:avoid}",
            css,
        )
        self.assertIn(
            ".cuerpo img.escaneo{display:block;max-width:100%;max-height:92vh;margin:.4em auto;"
            "break-inside:avoid;page-break-inside:avoid}",
            css,
        )

    def test_libro_conserva_scan_de_seccion_sin_texto(self):
        src = (
            '<section class="page"><div class="page-num">Página 5</div>'
            '<div class="scan"><img src="data:image/png;base64,AAA" alt="lámina"></div></section>'
        )
        html, _ = hojas._construir_libro_html(src, 8.5, 11, None, "Libro", "Autora")
        soup = BeautifulSoup(html, "html.parser")
        laminas = soup.select(".cuerpo img.escaneo")
        self.assertEqual(len(laminas), 1)
        self.assertEqual(laminas[0]["src"], "data:image/png;base64,AAA")

    def test_libro_conserva_figura_anidada_en_solo(self):
        src = (
            '<section class="page"><div class="page-num">Página 5</div><div class="solo">'
            '<p>Texto antes.</p><figure><img src="data:image/jpeg;base64,BBB"></figure>'
            '</div></section>'
        )
        html, _ = hojas._construir_libro_html(src, 8.5, 11, None, "Libro", "Autora")
        soup = BeautifulSoup(html, "html.parser")
        figuras = soup.select(".cuerpo img.fig")
        self.assertEqual(len(figuras), 1)
        self.assertEqual(figuras[0]["src"], "data:image/jpeg;base64,BBB")

    def test_indice_conserva_entrada_sin_pagina_y_avisa(self):
        html = (
            "<section class='indice'>"
            "<div class='entrada-indice nivel-1'><a href='#titulo-1'>Perdido</a>"
            "<span class='pagina' data-target='titulo-1'>0</span></div>"
            "<div class='entrada-indice nivel-1'><a href='#titulo-2'>Encontrado</a>"
            "<span class='pagina' data-target='titulo-2'>0</span></div>"
            "</section>"
        )
        aviso = StringIO()
        with redirect_stderr(aviso):
            resultado = hojas._rellenar_indice(html, {"titulo-2": 7})
        self.assertIn("data-target='titulo-1'", resultado)
        self.assertIn(">7<", resultado)
        self.assertIn("aviso: índice: no pude paginar «Perdido»", aviso.getvalue())

    def test_suma_manual_no_retiro_bloque_real_si_no_coincide(self):
        html = (
            '<section class="page"><div class="page-num">Página 5</div><div class="solo">'
            "CAPÍTULO 1<br/>Párrafo real que no es el subtítulo.<br/>Continuación del cuerpo."
            "</div></section>"
        )
        manual = [{"nivel": 1, "texto": "CAPÍTULO 1", "suma": "Subtítulo declarado"}]
        aviso = StringIO()
        with redirect_stderr(aviso):
            resultado, _ = hojas._construir_libro_html(
                html, 8.5, 11, None, "Libro", "Autora", titulos_manual=manual
            )
        cuerpo = BeautifulSoup(resultado, "html.parser").select_one(".cuerpo")
        self.assertIn("Párrafo real que no es el subtítulo.", cuerpo.get_text(" ", strip=True))
        self.assertIn("aviso: suma «Subtítulo declarado» no casa el bloque siguiente; no se retira", aviso.getvalue())

    @unittest.skipUnless(fitz, "requiere PyMuPDF")
    def test_portada_solo_se_incluye_si_la_primera_pagina_tiene_imagen(self):
        html = '<section class="page"><div class="page-num">Página 1</div><div class="solo">Texto.</div></section>'
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        with tempfile.TemporaryDirectory() as d:
            con = os.path.join(d, "con.pdf")
            sin = os.path.join(d, "sin.pdf")
            for ruta, con_imagen in ((con, True), (sin, False)):
                doc = fitz.open()
                pagina = doc.new_page()
                if con_imagen:
                    pagina.insert_image(fitz.Rect(10, 10, 40, 40), stream=png)
                doc.save(ruta)
                doc.close()
            con_html, _ = hojas._construir_libro_html(html, 8.5, 11, con, "Libro", "Autora")
            sin_html, _ = hojas._construir_libro_html(html, 8.5, 11, sin, "Libro", "Autora")
        self.assertIn("<section class='portada'>", con_html)
        self.assertNotIn("<section class='portada'>", sin_html)

    def test_agrupar_titulos_2_y_3_con_un_bloque_sin_unir_titulos(self):
        resultado = hojas._agrupar_cabeceras([
            "<p class='titulo titulo-2'>Sección</p>",
            "<p class='titulo titulo-3'>Subsección</p>",
            "<p>Primer párrafo.</p>",
        ])
        soup = BeautifulSoup("".join(resultado), "html.parser")
        grupos = soup.select(".entrada-cabecera")
        self.assertEqual(len(grupos), 2)
        self.assertEqual(len(grupos[0].select("p")), 1)
        self.assertEqual([p.get_text(strip=True) for p in grupos[1].select("p")], ["Subsección", "Primer párrafo."])

    def test_paginas_de_titulos_usa_ocurrencia_del_cuerpo_y_orden_monotono(self):
        class Page:
            def __init__(self, text):
                self.text = text

            def get_text(self):
                return self.text

        class Doc:
            def __init__(self):
                self.pages = [Page("portada"), Page("portadilla"), Page("Índice Uno 4 Dos 5"),
                              Page("Índice Uno 4 Dos 5"), Page("Capítulo Uno"), Page("Sección Dos")]

            def __len__(self):
                return len(self.pages)

            def __getitem__(self, i):
                return self.pages[i]

            def close(self):
                pass

        fake_fitz = types.ModuleType("fitz")
        fake_fitz.open = lambda path: Doc()
        titulos = [{"id": "a", "texto": "Uno"}, {"id": "b", "texto": "Dos"}]
        with mock.patch.dict(sys.modules, {"fitz": fake_fitz}):
            self.assertEqual(hojas._pagina_de_titulos("x.pdf", titulos), {"a": 5, "b": 6})

    def test_portadilla_no_folio_y_titulo_nivel_1_abre_pagina(self):
        css = hojas.LIBRO_CSS % {"W": 8.5, "H": 11, "ALIGN": "left", "HYPHENS": "auto"}
        self.assertIn(".portadilla{page:portadilla", css)
        self.assertIn("@page portadilla", css)
        self.assertIn(".cuerpo p.titulo-1{", css)
        self.assertIn("break-before:page", css)
        self.assertNotIn("titulo-1:first-child", css)

    def test_modo_libro_bandera_derecha_por_defecto_y_justificado_opt_in(self):
        html = '<section class="page"><div class="page-num">Página 5</div><div class="solo">Capítulo Uno<br/>Texto.</div></section>'
        por_defecto = hojas.construir_html(html, libro=True)
        justificado = hojas.construir_html(html, libro=True, libro_justificado=True)
        self.assertIn("text-align:left;hyphens:auto", por_defecto)
        self.assertIn("hyphenate-limit-chars:8 4 4", por_defecto)
        self.assertIn("text-align:justify;hyphens:auto", justificado)

    def test_modo_libro_sangria_es_opt_in_y_no_sangra_tras_titulo(self):
        html = '<section class="page"><div class="page-num">Página 5</div><div class="solo">Capítulo Uno<br/>Texto.</div></section>'
        por_defecto = hojas.construir_html(html, libro=True)
        sangria = hojas.construir_html(html, libro=True, libro_sangria=True)
        self.assertNotIn("text-indent:1.2em", por_defecto)
        self.assertIn("text-indent:1.2em", sangria)
        self.assertIn("margin:0", sangria)
        self.assertIn(".entrada-cabecera + p{text-indent:0}", sangria)

    def test_find_chrome_prioriza_variable_de_entorno_ejecutable(self):
        with tempfile.TemporaryDirectory(dir=_dir_prueba()) as d:
            chrome = os.path.join(d, "brave")
            open(chrome, "w").close()
            os.chmod(chrome, os.stat(chrome).st_mode | stat.S_IXUSR)
            with mock.patch.dict(os.environ, {"TRADUCTOR_CHROME": chrome}), \
                 mock.patch.object(render, "CHROME_CANDIDATES", ()):
                self.assertEqual(render.find_chrome(), chrome)

    def test_titulos_tsv_reemplaza_deteccion_y_une_suma_en_orden(self):
        html = (
            '<section class="page"><div class="page-num">Página 5</div><div class="solo">'
            'CAPÍTULO 3<br/>un ejemplo descriptivo<br/>Texto largo.</div></section>'
            '<section class="page"><div class="page-num">Página 6</div><div class="solo">'
            'CAPÍTULO 3<br/>Otra aparición.</div></section>'
        )
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "titulos.tsv")
            with open(ruta, "w", encoding="utf-8") as f:
                f.write("# comentario\n1\tCAPÍTULO 3\tun ejemplo descriptivo\n1\tCAPÍTULO 3\n")
            html = html.replace("un ejemplo descriptivo", "Claro un ejemplo descriptivo")
            manual = hojas._leer_titulos_tsv(ruta)
        _, titulos = hojas._construir_libro_html(
            html, 8.5, 11, None, "Libro", "Autora", titulos_manual=manual
        )
        self.assertEqual(
            [(t["nivel"], t["texto"], t["pagina_original"]) for t in titulos],
            [(1, "CAPÍTULO 3: un ejemplo descriptivo", 5), (1, "CAPÍTULO 3", 6)],
        )
        self.assertEqual([t["id"] for t in titulos], ["titulo-1", "titulo-2"])

    def test_titulos_tsv_avisar_linea_no_encontrada_y_continua(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "titulos.tsv")
            with open(ruta, "w", encoding="utf-8") as f:
                f.write("1\tNo existe\n1\tPrólogo\n")
            manual = hojas._leer_titulos_tsv(ruta)
        self.assertEqual(len(manual), 2)
        html = '<section class="page"><div class="page-num">Página 5</div><div class="solo">Prólogo<br/>Texto.</div></section>'
        salida = StringIO()
        with redirect_stderr(salida):
            _, titulos = hojas._construir_libro_html(
                html, 8.5, 11, None, "Libro", "Autora", titulos_manual=manual
            )
        self.assertEqual([t["texto"] for t in titulos], ["Prólogo"])
        self.assertIn("línea 1", salida.getvalue())

    def test_modo_libro_elimina_bloques_marcador_de_figura(self):
        con_marcador = (
            '<section class="page"><div class="page-num">Página 5</div><div class="solo">'
            'Antes del bloque.<br/>[figura: 00003.jpg]<br/>Después del bloque.</div></section>'
        )
        sin_marcador = con_marcador.replace("[figura: 00003.jpg]<br/>", "")
        con_html, _ = hojas._construir_libro_html(con_marcador, 8.5, 11, None, "Libro", "Autora")
        sin_html, _ = hojas._construir_libro_html(sin_marcador, 8.5, 11, None, "Libro", "Autora")
        self.assertNotIn("[figura:", con_html.lower())
        self.assertEqual(con_html, sin_html)


class ImprimirPdf(unittest.TestCase):
    def test_chrome_que_falla_no_pisa_el_pdf_anterior(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "libro.pdf")
            open(pdf, "wb").write(b"%PDF bueno")

            def falla(args, **kw):
                destino = next(a.split("=", 1)[1] for a in args if a.startswith("--print-to-pdf="))
                open(destino, "wb").write(b"%PDF a med")
                raise subprocess.CalledProcessError(1, args)

            with mock.patch("subprocess.run", side_effect=falla):
                with self.assertRaises(subprocess.CalledProcessError):
                    render.imprimir_pdf(os.path.join(d, "x.html"), pdf, chrome="fake")
            self.assertEqual(open(pdf, "rb").read(), b"%PDF bueno")
            self.assertEqual(os.listdir(d), ["libro.pdf"])


if __name__ == "__main__":
    unittest.main()
