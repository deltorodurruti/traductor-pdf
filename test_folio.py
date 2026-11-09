"""Regresión: quitar_folio quita el número de página, pero NO un valor final.

Un número al final de un párrafo precedido de un operador (razón «3:1», suma «2 + 1»,
igualdad «= 3») es un valor, no un folio: perderlo destruye datos (p. ej. una gematría).
"""
import hojas


def test_quita_folio_real():
    assert hojas.quitar_folio("Fin del capítulo. 42") == "Fin del capítulo."
    assert hojas.quitar_folio("Introducción -5-") == "Introducción"
    assert hojas.quitar_folio("Prefacio  iv") == "Prefacio"


def test_preserva_valor_final():
    for t in ("La suma es 2 + 1 = 3", "Proporción 3:1", "El resultado: 2 + 2"):
        assert hojas.quitar_folio(t) == t


if __name__ == "__main__":
    test_quita_folio_real()
    test_preserva_valor_final()
    print("test_folio OK")
