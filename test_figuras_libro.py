"""Regresión del maquetado con figuras:
  B1 — con --original, una figura que YA venía en el HTML no se descarta.
  B2 — una página --solo-imagen va en SU posición, no saltada al inicio del PDF.
"""
import os
import tempfile

import hojas

try:
    import fitz
except ImportError:
    fitz = None
import pytest


def test_b1_conserva_figura_del_html_con_figs():
    items = [("t", "<p>Un párrafo de texto cualquiera para la página.</p>"),
             ("img", "data:image/png;base64,AAAAFIGURA")]
    out, _ = hojas._componer(items, figs=[])
    assert any("AAAAFIGURA" in o for o in out), "B1: se perdió la figura que venía en el HTML"


@pytest.mark.skipif(fitz is None, reason="requiere PyMuPDF")
def test_b2_solo_imagen_en_su_posicion():
    doc = fitz.open()
    for _ in range(3):
        doc.new_page()
    pdf = tempfile.mktemp(suffix=".pdf")
    doc.save(pdf)
    doc.close()
    try:
        html = "<html><body>" + "".join(
            f'<section class="page"><div class="page-num">Página {n}</div>'
            f'<p>texto{n}aqui</p></section>' for n in (1, 2, 3)) + "</body></html>"
        out = hojas.construir_html(html, original=pdf, solo_imagen=frozenset([3]), cabecera=True)
        assert out.find("texto2aqui") < out.find("alt='página 3'"), "B2: --solo-imagen saltó al inicio"
    finally:
        os.unlink(pdf)


if __name__ == "__main__":
    test_b1_conserva_figura_del_html_con_figs()
    print("B1 OK")
