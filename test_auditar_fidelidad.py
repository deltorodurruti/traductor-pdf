import os
import sys
import tempfile
import unittest

import fitz

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "herramientas"))
import auditar_fidelidad as A

RELLENO = " The scribe copied every line of the record with great care and nothing was left out of it."
ORIG = [
    "the researcher met the editor in 1582 at Riverside. The table had 49 squares. the editor saw the term Zorkamel." + RELLENO * 2,
    "Chapter two begins here. In 1533 and during 1537 the team recorded river flow and sediment levels. The northern basin contains several layers of stone." + RELLENO * 2,
    "In 1604 the manuscript was lost. The publisher printed it in 1659 with the word Quirvantos on the cover." + RELLENO * 2,
    "The samples were stored in glass containers in 1508 near Riverside." + RELLENO * 2,
    "Later researchers repeated the measurements in 1531 and 1537." + RELLENO * 2,
]
RELLENO_ES = " El escriba copió cada línea del registro con gran cuidado y nada quedó fuera."
TRAD = [
    "the researcher conoció a the editor en 1582 en Riverside. La tabla tenía 49 casillas. the editor vio al término Zorkamel." + RELLENO_ES * 2,
    "Aquí empieza el capítulo dos. La cuenca norte contiene varias capas de piedra." + RELLENO_ES * 2,
    "En 1604 se perdió el manuscrito. La editorial lo imprimió en 1659 con la palabra Quirvantós en la portada." + RELLENO_ES * 2,
    "Las muestras se guardaron en recipientes de vidrio en 1508 cerca de Riverside." + RELLENO_ES * 2,
    "Investigaciones posteriores repitieron las mediciones en 1531 y 1537." + RELLENO_ES * 2,
]


def _pdf(ruta, paginas):
    doc = fitz.open()
    for t in paginas:
        doc.new_page().insert_textbox(fitz.Rect(40, 40, 560, 780), t, fontsize=10)
    doc.save(ruta)


class Fidelidad(unittest.TestCase):
    def test_detecta_oracion_omitida_y_voz_alterada(self):
        with tempfile.TemporaryDirectory() as d:
            o, t, g = os.path.join(d, "o.pdf"), os.path.join(d, "t.pdf"), os.path.join(d, "g.txt")
            _pdf(o, ORIG)
            _pdf(t, TRAD)
            open(g, "w").write("Zorkamel\nQuirvantos\n")
            inf = A.auditar(o, t, os.path.join(d, "inf.json"), [g])
            self.assertEqual(inf["sin_correspondencia"], [])
            self.assertEqual([x["pag"] for x in inf["omisiones"]], [2])
            self.assertEqual(inf["omisiones"][0]["faltan"], ["1533", "1537"])
            self.assertEqual(len(inf["omisiones"][0]["oraciones"]), 1)
            self.assertEqual(inf["omisiones"][0]["ausentes_del_libro"], ["1533"])
            self.assertEqual(inf["voces"], [{"pag": 3, "voces": ["Quirvantos"]}])
            self.assertEqual(inf["hojas_vacias"], [])
            self.assertTrue(os.path.exists(os.path.join(d, "inf.json")))
            self.assertIn("1 págs. con fichas ausentes (1 oraciones; 1 con cifras ausentes de todo el libro)", A.resumen(inf))

    def test_alineacion_tolera_paginas_insertadas(self):
        trad = ["Portada de la edición española." + RELLENO_ES] + TRAD[:1] + ["Nota del traductor." + RELLENO_ES] + TRAD[1:]
        ali = A.alinear(ORIG, trad)
        self.assertEqual([q for q, _ in ali], [1, 2, 4, 5, 6])

    def test_palabra_partida_por_guion_al_final_de_linea_sigue_contando(self):
        self.assertEqual(A.desguionar("incluso inter\u2010\nnacional)"), "incluso internacional)")
        self.assertEqual(A.desguionar("re-\nlevancia"), "relevancia")
        self.assertEqual(A.desguionar("uno\ndos"), "uno\ndos")

    def test_misma_paginacion_es_directa(self):
        self.assertEqual([q for q, _ in A.alinear(ORIG, TRAD)], [0, 1, 2, 3, 4])


if __name__ == "__main__":
    unittest.main()
