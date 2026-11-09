import json
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from intraducibles import Masker, cargar_lexicos, es_derivado, es_ingles


def _lexico(d, *voces):
    ruta = os.path.join(d, "lex.json")
    json.dump({"voces": [{"voz": v} for v in voces]}, open(ruta, "w", encoding="utf-8"))
    return ruta


def _terms(masker, texto):
    """Términos enmascarados en orden de aparición (con repeticiones)."""
    masked, mapping = masker.mask(texto)
    return [mapping[t] for t in re.findall(r"MWTKN\d+", masked)]


class Identificador(unittest.TestCase):
    def test_ingles_y_derivados_no_se_congelan(self):
        self.assertTrue(es_ingles("planets") and es_ingles("listed") and es_ingles("terms") and es_ingles("copies"))
        self.assertTrue(es_derivado("historical") and es_derivado("revisionist") and es_derivado("naturalization"))
        m = Masker(glossary=[], auto_detect=False, detect_unknown=True)
        self.assertEqual(_terms(m, "The unusual terminology appeared in a rare manuscript in Paris."), [])
        self.assertEqual(_terms(m, "THE STUDY OF LANGUAGE"), [], "un título en versalitas no se congela")

    def test_tirada_de_voces_y_mayusculas(self):
        m = Masker(glossary=[], auto_detect=False, detect_unknown=True)
        self.assertEqual(_terms(m, "Then he said: by ZORKAMEL, amen."), ["ZORKAMEL"])
        with tempfile.TemporaryDirectory() as d:
            m2 = Masker(glossary=[], auto_detect=False, detect_unknown=True, lexicon_paths=[_lexico(d, "PLUMBATAX")])
            self.assertEqual(_terms(m2, "Then he said: by ZORKAMEL, PLUMBATAX, amen."), ["ZORKAMEL", "PLUMBATAX"])
        self.assertEqual(_terms(m, "ZORKAMEL ZORKAMEL QUIRVANTOS ZORKAMEL"), ["ZORKAMEL", "ZORKAMEL", "QUIRVANTOS", "ZORKAMEL"])
        self.assertEqual(_terms(m, "whisper korvax plumbatax plumbatax softly"), ["korvax", "plumbatax", "plumbatax"])
        self.assertEqual(_terms(m, "whisper korvax softly"), [], "una sola voz en minúsculas y sin señal se deja al modelo")

    def test_nombre_en_medio_de_frase_si_y_al_inicio_suelto_no(self):
        m = Masker(glossary=[], auto_detect=False, detect_unknown=True)
        self.assertEqual(_terms(m, "The term KORVAX appeared to the reader."), ["KORVAX"])
        self.assertEqual(_terms(m, "Readers gathered at dawn."), [])
        self.assertEqual(_terms(m, "the project team spoke"), [], "palabra del diccionario con mayúscula: no es voz")

    def test_diacriticos_de_transliteracion(self):
        m = Masker(glossary=[], auto_detect=False, detect_unknown=True)
        self.assertEqual(_terms(m, "write the letter ṭāʾ and the name Muḥyī here"), ["ṭāʾ", "Muḥyī"])

    def test_el_lexico_reconoce_y_respeta_las_mayusculas_del_original(self):
        with tempfile.TemporaryDirectory() as d:
            lex = _lexico(d, "PLUMBATAX", "KORVAX")
            m = Masker(glossary=[], auto_detect=False, detect_unknown=True, lexicon_paths=[lex])
            self.assertEqual(_terms(m, "mark it with the PLUMBATAX now"), ["PLUMBATAX"])
            self.assertEqual(_terms(m, "mark it with the plumbatax now"), ["plumbatax"])
            self.assertEqual(_terms(m, "and so be it, amen."), [], "«amen» suelto es inglés corriente: no se congela")
            self.assertEqual(_terms(m, "AMEN AMEN RIVOTAN"), ["AMEN", "AMEN", "RIVOTAN"])

    def test_el_glosario_ya_no_cambia_las_mayusculas(self):
        m = Masker(glossary=["ZORKAMEL"], auto_detect=False, detect_unknown=False)
        self.assertEqual(_terms(m, "cry ZORKAMEL aloud"), ["ZORKAMEL"])

    def test_variante_de_ocr_de_una_voz_conocida_se_corrige(self):
        with tempfile.TemporaryDirectory() as d:
            lex = _lexico(d, "RIVOTAN", "KORVAX", "RIVOTAN")
            m = Masker(glossary=[], auto_detect=False, detect_unknown=True, lexicon_paths=[lex])
            self.assertEqual(_terms(m, "then Riv0tan and Korvax came"), ["RIVOTAN", "Korvax"])
            self.assertEqual(_terms(m, "then RIVOTAN came"), ["RIVOTAN"])
            self.assertEqual(m.correcciones, {"Riv0tan": "RIVOTAN"})
            self.assertEqual(_terms(m, "the reader RIVOTANl spoke"), ["RIVOTANl"], "una grafía antigua del original se respeta tal cual")
            self.assertEqual(_terms(m, "as KORVAX's list and ZORKAMEL's book show"), ["KORVAX", "ZORKAMEL"], "el posesivo inglés no entra en la voz")

    def test_una_voz_del_lexico_que_es_ingles_corriente_solo_se_congela_en_mayusculas(self):
        with tempfile.TemporaryDirectory() as d:
            lex = _lexico(d, "Group", "Scope")
            m = Masker(glossary=[], auto_detect=False, detect_unknown=True, lexicon_paths=[lex])
            self.assertEqual(_terms(m, "the Group of the scope came upon him"), [])
            self.assertEqual(_terms(m, "I call you, GROUP, by the SCOPE"), ["GROUP", "SCOPE"])

    def test_las_voces_nuevas_se_cuentan_para_aprenderlas(self):
        m = Masker(glossary=[], auto_detect=False, detect_unknown=True)
        m.mask("by ZORKAMEL and by ZORKAMEL again, said KORVAX")
        self.assertEqual(dict(m.nuevas), {"ZORKAMEL": 2, "KORVAX": 1})

    def test_cargar_lexicos_mezcla_txt_y_json(self):
        with tempfile.TemporaryDirectory() as d:
            txt = os.path.join(d, "g.txt")
            open(txt, "w", encoding="utf-8").write("# comentario\nRIVOTAN\nKORVAX\nZORKAMEL RIVOTAN\n")
            js = os.path.join(d, "c.json")
            json.dump({"lexico": [{"original": "λόγος", "translit": "LOGOS"}, {"original": "PLUMBATAX", "translit": "suf. rey"}]},
                      open(js, "w", encoding="utf-8"))
            formas, frases = cargar_lexicos([txt, js, os.path.join(d, "no_existe.json")])
            self.assertEqual(frases, ["ZORKAMEL RIVOTAN"])
            self.assertEqual(formas["logos"], "LOGOS")
            self.assertEqual(formas["plumbatax"], "PLUMBATAX")
            self.assertIn("ZORKAMEL RIVOTAN", frases)


if __name__ == "__main__":
    unittest.main()
