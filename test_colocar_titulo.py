"""Regresión de la colocación de títulos en el cuerpo del libro (hojas._colocar_titulo).

Fija el arreglo de la regresión que metió «emparejar títulos solo al inicio del bloque»:
un encabezado que viene enterrado tras créditos (separados por <br>) o arrastrado al final
de una oración dejaba de extraerse y quedaba DUPLICADO (una copia limpia arriba + la enterrada).
A la vez, un título NO debe casar a mitad de una frase («…como Hesíodo y Porfirio»).

Autocontenido: no depende de _prueba/ ni de libros del taller, así que corre en cualquier
checkout. Son los casos que test_libro_real.py comprueba con libros reales, en miniatura.
"""
import hojas


def _texto_junto(reemplazo):
    return " ".join(hojas._texto(x) for x in reemplazo)


def test_encabezado_enterrado_tras_creditos_con_br_se_extrae_una_vez():
    bloque = ("<p>Sorita d’Este &amp; David Rankine<br/>Mayo de 2009, Gales"
              "<br/>CAPÍTULO 1<br/>De los Tres Caminos</p>")
    res = hojas._colocar_titulo(bloque, ["CAPÍTULO 1", "De los Tres Caminos"],
                                "CAPÍTULO 1: De los Tres Caminos", 1, "t1")
    assert res is not None, "no extrajo el encabezado enterrado"
    reemplazo, suma_consumida, _ = res
    junto = _texto_junto(reemplazo)
    assert suma_consumida, "no consumió la suma «De los Tres Caminos»"
    assert junto.count("De los Tres Caminos") == 1, junto
    assert "class='titulo titulo-1' id='t1'" in "".join(reemplazo)
    assert "Sorita" in junto and "Mayo de 2009" in junto


def test_encabezado_arrastrado_al_final_de_una_oracion_se_extrae():
    bloque = "<p>Los administradores han hecho un buen trabajo. 6. Purson</p>"
    res = hojas._colocar_titulo(bloque, ["6. Purson"], "6. Purson", 3, "t2")
    assert res is not None, "no extrajo el encabezado arrastrado"
    reemplazo, _, _ = res
    junto = _texto_junto(reemplazo)
    assert junto.count("6. Purson") == 1, junto
    assert "class='titulo titulo-3' id='t2'" in "".join(reemplazo)
    assert "Los administradores han hecho un buen trabajo." in junto


def test_no_casa_a_mitad_de_una_frase():
    bloque = "<p>Autores como Hesíodo y Porfirio escribieron sobre esto.</p>"
    assert hojas._colocar_titulo(bloque, ["Hesíodo"], "Hesíodo", 2, "t3") is None


def test_bloque_que_es_exactamente_el_titulo():
    res = hojas._colocar_titulo("<p>CAPÍTULO 2</p>", ["CAPÍTULO 2"], "CAPÍTULO 2", 1, "t4")
    assert res is not None
    reemplazo, _, hay_cola = res
    assert not hay_cola
    assert reemplazo == ["<p class='titulo titulo-1' id='t4'>CAPÍTULO 2</p>"]


def test_titulo_prefijo_conserva_el_cuerpo_que_sigue():
    bloque = "<p>CAPÍTULO 10 El texto del capítulo sigue aquí.</p>"
    res = hojas._colocar_titulo(bloque, ["CAPÍTULO 10"], "CAPÍTULO 10", 1, "t5")
    assert res is not None
    reemplazo, _, hay_cola = res
    assert hay_cola
    junto = _texto_junto(reemplazo)
    assert "CAPÍTULO 10" in junto and "El texto del capítulo sigue aquí." in junto


def test_folio_borrado_del_encabezado_se_repone_del_tsv():
    res = hojas._colocar_titulo("<p>CAPÍTULO</p>", ["CAPÍTULO 10"], "CAPÍTULO 10", 1, "t6")
    assert res is not None
    reemplazo, _, _ = res
    assert reemplazo == ["<p class='titulo titulo-1' id='t6'>CAPÍTULO 10</p>"]


if __name__ == "__main__":
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_"):
            fn()
            print("OK", nombre)
