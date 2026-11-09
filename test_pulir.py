"""pulir.py: términos congelados en inglés y basura de OCR árabe en el HTML solo-español."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "herramientas"))
import pulir


class Pulir(unittest.TestCase):
    def test_reemplaza_palabra_completa_y_solo_texto(self):
        rs = [("Danube", "Danubio"), ("Natural Philosophy", "Filosofía Natural")]
        html = "<p class='Danube'>El valle del Danube y Danubes; <b>Natural Philosophy</b></p><img alt='Danube'>"
        out, cuenta, _ = pulir.pulir(html, rs, False)
        self.assertIn("valle del Danubio y Danubes", out)
        self.assertIn("<b>Filosofía Natural</b>", out)
        self.assertIn("class=\"Danube\"", out)
        self.assertEqual(cuenta, {"Danube": 1, "Natural Philosophy": 1})

    def test_regla_mas_larga_gana(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("# comentario\nlos Trade Winds => los vientos alisios\nTrade Winds => vientos alisios\n")
        rs = pulir.reglas(f.name)
        os.remove(f.name)
        out, _, _ = pulir.pulir("<p>los Trade Winds y sus Trade Winds</p>", rs, False)
        self.assertIn("los vientos alisios y sus vientos alisios", out)

    def test_quita_mojibake_y_conserva_transliteracion(self):
        t, n = pulir.sin_mojibake("Ṣalāḥ al-Dīn al-Ayyūbī ¡ }ŏëاȿńëا £¤ȿا y el Ḥalab")
        self.assertEqual(t, "Ṣalāḥ al-Dīn al-Ayyūbī y el Ḥalab")
        self.assertEqual(n, 3)

    def test_no_toca_signos_del_espanol(self):
        t = "«Mira», dijo. ¡Oh Óptica! OPERACIÓN {así} Zoë 1ª edición © 2026 £5"
        self.assertEqual(pulir.sin_mojibake(t), (t, 0))

    def test_quita_hebreo_en_latin1_pero_no_espanol(self):
        t, n = pulir.sin_mojibake("Tel Aviv Yafo úòãå äåìà Beer Sheva, está aquí; ñ ó «éãù»")
        self.assertEqual(t, "Tel Aviv Yafo Beer Sheva, está aquí; ñ ó")
        self.assertEqual(n, 3)


class Hebreo(unittest.TestCase):
    def test_ficha_en_cp1255_se_recupera_en_orden_logico(self):
        out, cuenta, _ = pulir.pulir("<p>El nombre íåìù aquí</p>", [], True, True)
        self.assertIn("<span dir=\"rtl\" lang=\"he\">שלום</span>", out.replace("'", '"'))
        self.assertEqual(cuenta["hebreo recuperado"], 1)

    def test_corrida_de_fichas_se_invierte_entera(self):
        out, _, _ = pulir.pulir("<p>(íìåò íåìù)</p>", [], True, True)
        self.assertIn("שלום עולם", out)
        self.assertIn("(", out)

    def test_letra_final_en_medio_no_es_hebreo(self):
        self.assertEqual(pulir._hebreo_ficha("éïá"), "")

    def test_espanol_y_letras_sueltas_quedan_igual(self):
        t = "<p>también está é y ñ</p>"
        out, cuenta, _ = pulir.pulir(t, [], True, True)
        self.assertEqual(out, t)
        self.assertNotIn("hebreo recuperado", cuenta)

    def test_sin_la_opcion_el_hebreo_se_borra_como_antes(self):
        out, _, n = pulir.pulir("<p>nombre äåäé aquí</p>", [], True, False)
        self.assertNotIn("äåäé", out)
        self.assertEqual(n, 1)


class CorridasLatinas(unittest.TestCase):
    def limpio(self, t):
        return pulir.sin_corridas_latinas(t)[0]

    def test_corrida_de_basura_se_borra_con_sus_fichas_sueltas(self):
        self.assertEqual(self.limpio("Oh persona, Señor de las esferas ¼ č Ǎ Ǎ ā Ǎ Ǎ č Ǎ"), "Oh persona, Señor de las esferas")
        self.assertEqual(self.limpio("z Ŵ Ĝ © Ƌ Ą ū ú © äy Ĵ Ĵ La ciencia"), "La ciencia")

    def test_y_huerfana_al_final_se_quita_y_la_conjuncion_se_respeta(self):
        self.assertEqual(self.limpio("el nombre Ŀ y"), "el nombre")
        self.assertEqual(self.limpio("luz y fuego"), "luz y fuego")

    def test_parentesis_vacios_y_espacios_antes_de_comas(self):
        self.assertEqual(self.limpio("Safʿ ( ĭ ĥ ), Malʿ ( ħ ), Mayʿ ( )"), "Safʿ, Malʿ, Mayʿ")

    def test_transliteracion_ipa_diagramas_y_cifras_no_se_tocan(self):
        t = "Ḥāṣib Zaʿkamil Būnī · IPA: /ˈɪbn/ ◆ ◇ ⟵ pattern 3×3 ñandú Persona"
        self.assertEqual(self.limpio(t), t)
        self.assertEqual(self.limpio("Capítulo 3 Ŵ"), "Capítulo 3")

    def test_residuos_de_letras_arabes_y_la_conjuncion_se_respeta(self):
        self.assertEqual(self.limpio("al final z z y y y"), "al final")
        self.assertEqual(self.limpio("y © z Áy © © © © í Di: Oh persona"), "Di: Oh persona")
        self.assertEqual(self.limpio("la luz y la sombra y y © z"), "la luz y la sombra")
        self.assertEqual(self.limpio("persona y el mundo"), "persona y el mundo")

    def test_se_activa_con_la_opcion(self):
        out, _, n = pulir.pulir("<p>texto Ĵ z Ŵ aquí</p>", [], True, False, True)
        self.assertIn("texto aquí", out)
        self.assertEqual(n, 3)
        sin, _, _ = pulir.pulir("<p>texto Ĵ z Ŵ aquí</p>", [], True, False, False)
        self.assertIn("Ĵ", sin)


class Indice(unittest.TestCase):
    def test_entradas_numeradas_pegadas_se_parten_en_orden(self):
        lineas, sig = pulir.partir_indice("Índice 1. Parte I: La ciencia 2. El primer capítulo: Sobre 28 ríos 3. Tercero", 1)
        self.assertEqual(lineas, ["Índice", "1. Parte I: La ciencia", "2. El primer capítulo: Sobre 28 ríos", "3. Tercero"])
        self.assertEqual(sig, 4)

    def test_la_numeracion_continua_en_el_bloque_siguiente(self):
        lineas, sig = pulir.partir_indice("Letras 10. El Tercero 11. El Cuarto", 10)
        self.assertEqual(lineas, ["Letras", "10. El Tercero", "11. El Cuarto"])
        self.assertEqual(sig, 12)

    def test_sin_numeracion_solo_se_separan_los_romanos_pegados(self):
        html = "<section class='page'><div class='page-num'>Página 6</div><div class='solo'>PARTE I<br/>iiEl primer capítulo<br/>xiii El Octavo</div></section>"
        out, cuenta, _ = pulir.pulir(html, [], False, indice=frozenset({6}))
        self.assertIn("PARTE I<br/>ii El primer capítulo<br/>xiii El Octavo", out)
        self.assertEqual(cuenta["entradas de índice"], 0)

    def test_pagina_de_indice_en_html(self):
        html = ("<section class='page'><div class='page-num'>Página 2</div><div class='solo'>Índice 1. A<br/>b 2. B</div>"
                "</section><section class='page'><div class='page-num'>Página 3</div><div class='solo'>texto 3. no</div></section>")
        out, cuenta, _ = pulir.pulir(html, [], False, indice=frozenset({2}))
        self.assertIn("Índice<br/>1. A b<br/>2. B", out)
        self.assertEqual(cuenta["entradas de índice"], 3)
        self.assertIn("texto 3. no", out)


if __name__ == "__main__":
    unittest.main()


class Interfaz(unittest.TestCase):
    def test_quita_encabezado_corrido_y_pies_de_kindle(self):
        fija = "DISEÑO DE DIAGRAMAS VECTORIALES: LA GUÍA"
        cab = [fija] * 5 + ["DISEÑAR DIAGRAMAS VECTORIALES", "DISEÑO DE DIAGRAMAS", fija]
        pies = ["26%", "3 min restante(s) en el libro 27%", "Aprendiendo velocidad de lectura 28%", "29", "", "", "", ""]
        html = "".join(f'<section class="page"><div class="page-num">Página {k+1}</div><div class="solo">{cab[k]}<br/>Texto {k} de verdad.<br/>Más texto.'
                       + (f"<br/>{pies[k]}" if pies[k] else "") + "</div></section>" for k in range(8))
        nuevo, n = pulir.sin_interfaz(html)
        self.assertEqual(n, 8 + 4)
        self.assertNotIn("DIAGRAMAS", nuevo)
        self.assertNotIn("restante", nuevo)
        self.assertEqual(nuevo.count("de verdad.<br/>Más texto.</div>"), 8)

    def test_un_titulo_que_no_se_repite_no_se_toca(self):
        html = "".join(f'<section class="page"><div class="page-num">Página {k+1}</div><div class="solo">Capítulo {k}<br/>Texto.</div></section>' for k in range(6))
        html += '<section class="page"><div class="page-num">Página 7</div><div class="solo">La torre de los astrónomos<br/>Texto.</div></section>' * 1
        nuevo, n = pulir.sin_interfaz(html)
        self.assertEqual((n, nuevo), (0, html))
