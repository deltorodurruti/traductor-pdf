"""figuras.py: una página con texto nativo solo da como figuras sus imágenes incrustadas."""
import io
import shutil
import unittest

import fitz
from PIL import Image

import figuras


def _png(color, w=120, h=120) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (w, h), color).save(b, "PNG")
    return b.getvalue()


def _pagina(imagen: bool, fondo: bool = False):
    doc = fitz.open()
    pag = doc.new_page(width=612, height=792)
    if fondo:
        pag.insert_image(pag.rect, stream=_png("white", 600, 780))
    for i in range(40):
        pag.insert_text((72, 90 + 12 * i), "El libro dice que el texto corrido es denso y largo " * 1, fontsize=9)
    if imagen:
        pag.insert_image(fitz.Rect(200, 600, 320, 720), stream=_png("black"))
    return pag


class Figuras(unittest.TestCase):
    def test_pagina_nativa_sin_imagenes_no_tiene_figuras(self):
        self.assertEqual(figuras.figuras_pagina(_pagina(False)), [])

    def test_pagina_nativa_da_la_imagen_incrustada(self):
        figs = figuras.figuras_pagina(_pagina(True))
        self.assertEqual(len(figs), 1)
        self.assertEqual(figs[0][0], 1.0)
        self.assertTrue(figs[0][1].startswith("data:image/png;base64,"))

    def test_imagen_de_fondo_no_cuenta_como_nativa(self):
        self.assertFalse(figuras._es_nativa(_pagina(False, fondo=True)))


def _render(texto: str) -> Image.Image:
    doc = fitz.open()
    pag = doc.new_page(width=400, height=200)
    pag.insert_textbox(fitz.Rect(20, 20, 380, 180), texto, fontsize=12)
    pix = pag.get_pixmap(dpi=150)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


@unittest.skipUnless(shutil.which("tesseract"), "sin Tesseract")
class TextoIngles(unittest.TestCase):
    def test_bloque_en_ingles_se_reconoce(self):
        im = _render("It is the work of the sages that the term shall obey the will of the master, "
                     "and it was written that they have not seen the light of the sun.")
        self.assertTrue(figuras.es_texto_ingles(im))

    def test_bloque_en_espanol_o_dibujo_no(self):
        self.assertFalse(figuras.es_texto_ingles(_render("El término obedecerá la voluntad del maestro, "
                                                         "como está escrito en el libro de los sabios.")))
        self.assertFalse(figuras.es_texto_ingles(Image.new("L", (200, 200), 255)))

    def test_sin_texto_ingles_conserva_las_figuras(self):
        uri = figuras._png_uri(_png("black"))
        self.assertEqual(figuras.sin_texto_ingles([(0.5, uri)]), [(0.5, uri)])


if __name__ == "__main__":
    unittest.main()
