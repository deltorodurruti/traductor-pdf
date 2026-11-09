"""Léxico aprendido (memoria de términos entre libros) y guía de pronunciación."""
import json
import os
import tempfile
import unittest

import lexicon
import pronounce
import voces


class Aprendidas(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.p = os.path.join(self.d.name, "sub", "aprendidas.json")

    def tearDown(self):
        self.d.cleanup()

    def test_crea_agrega_y_no_duplica(self):
        e = [{"original": "ZORKAMEL", "translit": "", "es_cl": "zor-KA-mel", "auto": True},
             {"original": "RIVOTAN", "translit": "", "es_cl": "ri-VO-tan", "auto": True}]
        self.assertEqual(lexicon.remember(self.p, e), 2)
        self.assertEqual(lexicon.remember(self.p, e + [{"original": "zorkamel", "es_cl": "x"}]), 0)
        self.assertEqual(lexicon.remember(self.p, [{"original": "KORVAX", "es_cl": "KOR-vax"}]), 1)
        data = json.load(open(self.p, encoding="utf-8"))
        self.assertEqual([x["original"] for x in data["lexico"]], ["ZORKAMEL", "RIVOTAN", "KORVAX"])
        self.assertEqual(data["lexico"][0]["es_cl"], "zor-KA-mel")
        self.assertIn("uso", data["_meta"])

    def test_vacio_no_crea_archivo(self):
        self.assertEqual(lexicon.remember(self.p, []), 0)
        self.assertFalse(os.path.exists(self.p))

    def test_curado_gana_al_aprendido(self):
        cur = os.path.join(self.d.name, "curado.json")
        json.dump({"lexico": [{"original": "ΝΙΚΗ", "translit": "KORVAX", "es_cl": "NI-ke"}]},
                  open(cur, "w", encoding="utf-8"), ensure_ascii=False)
        lexicon.remember(self.p, [{"original": "KORVAX", "es_cl": "malo", "auto": True},
                                  {"original": "PLUMBATAX", "es_cl": "plum-BA-tax", "auto": True}])
        lx = lexicon.load_many([cur, self.p])
        self.assertEqual(lx.get("korvax")["es_cl"], "NI-ke")
        self.assertEqual(pronounce.pronounce("PLUMBATAX", curated=lx.get("PLUMBATAX"))["kind"], "aprendida")
        self.assertEqual(pronounce.pronounce("ΝΙΚΗ", curated=lx.get("ΝΙΚΗ"))["kind"], "curada")

    def test_archivo_roto_no_rompe(self):
        os.makedirs(os.path.dirname(self.p)); open(self.p, "w").write("{no json")
        self.assertEqual(len(lexicon.load_many([self.p])), 0)
        self.assertEqual(lexicon.remember(self.p, [{"original": "A", "es_cl": "a"}]), 1)


class Guia(unittest.TestCase):
    def test_silabeo(self):
        casos = {"PLUMBATAX": "plum-BA-tax", "ZORKAMEL": "zor-KA-mel",
                 "RIVOTAN": "ri-VO-tan", "KORVAX": "KOR-vax", "xyz": "XIZ", "": ""}
        for w, g in casos.items():
            self.assertEqual(pronounce.respell(w), g, w)

    def test_latino_guia_primero(self):
        pr = pronounce.pronounce("ZORKAMEL")
        self.assertEqual((pr["kind"], pr["say"], pr["guia"]), ("aprox", "zor-KA-mel", "zor-KA-mel"))
        if pronounce.have_espeak():
            self.assertTrue(pr["ipa"] and "ð" not in pr["ipa"])

    def test_ipa_descarta_deletreo(self):
        if not pronounce.have_espeak():
            self.skipTest("sin espeak")
        self.assertIsInstance(pronounce.ipa("PLUMBATAX"), (str, type(None)))


class Voces(unittest.TestCase):
    def test_extrae_voces_y_descarta_titulos(self):
        t = "PLUMBATAX dijo VIII veces: PLUMBA-TAX y ZORKAMEL. La CASA de la casa. THE END"
        c = voces.del_texto(t)
        self.assertEqual(c["PLUMBATAX"], 2)
        self.assertEqual(c["ZORKAMEL"], 1)
        for no in ("VIII", "CASA", "THE", "END"):
            self.assertNotIn(no, c)

    def test_verificada_no_se_descarta_por_estar_en_minusculas(self):
        t = "Se dice zorkamel en voz baja y luego ZORKAMEL"
        self.assertNotIn("ZORKAMEL", voces.del_texto(t))
        self.assertIn("ZORKAMEL", voces.del_texto(t, {"ZORKAMEL"}))

    def test_no_toma_titulos_con_tilde(self):
        self.assertEqual(len(voces.del_texto("INTRODUCCIÓN y BIBLIOGRAFÍA")), 0)

    def test_perdidas_nuevas_y_sugerencia(self):
        origen = "ZORKAMEL PLUMBATAX QUIRVANTOS ZORKAMEL"
        trad = "ZORKAMEL PLUMBATEX AIIHXTXQ"
        r = voces.revisar(trad, origen)
        self.assertEqual(r["perdidas"], {"ZORKAMEL": (2, 1), "PLUMBATAX": (1, 0), "QUIRVANTOS": (1, 0)})
        self.assertEqual(r["nuevas"]["PLUMBATEX"], "PLUMBATAX")
        self.assertIsNone(r["nuevas"]["AIIHXTXQ"])

    def test_sugerencia_ambigua_no_se_propone(self):
        self.assertIsNone(voces.sugerir("ZORKAMEL", ["ZORKAMAL", "ZORKAMIL"]))
        self.assertEqual(voces.sugerir("ZORKAMEL", ["ZORKAMAL", "PLUMBATAX"]), "ZORKAMAL")

    def test_sin_origen_usa_la_lista_verificada(self):
        r = voces.revisar("PLUMBATEX y ZORKAMEL", None, {"PLUMBATAX", "ZORKAMEL"})
        self.assertEqual(r["nuevas"], {"PLUMBATEX": "PLUMBATAX"})
        self.assertEqual((r["voces"], r["verificadas"]), (2, 1))

    def test_corregir_cambia_solo_voces_enteras(self):
        t, n = voces.corregir("PLUMBATEX; PLUMBATEXTRA; PLUMBA-TEX", {"PLUMBATEX": "PLUMBATAX"})
        self.assertEqual((t, n), ("PLUMBATAX; PLUMBATEXTRA; PLUMBATAX", 2))

    def test_cargar_acepta_ambos_formatos_y_archivo_roto(self):
        with tempfile.TemporaryDirectory() as d:
            a, b, c = (os.path.join(d, x) for x in ("a.json", "b.json", "c.json"))
            json.dump({"voces": [{"voz": "Zorkamel", "fuente": "x"}]}, open(a, "w"))
            json.dump({"lexico": [{"original": "ΝΙΚΗ", "translit": "Plumbatax"}]}, open(b, "w"), ensure_ascii=False)
            open(c, "w").write("{no json")
            self.assertEqual(voces.cargar(a, b, c, os.path.join(d, "nada.json")), {"ZORKAMEL", "PLUMBATAX"})

    @unittest.skipUnless(os.path.exists(voces.VERIFICADAS), "lista local, fuera del repo")
    def test_lista_local_se_puede_cargar(self):
        self.assertGreater(len(voces.cargar(voces.VERIFICADAS, voces.CURADO)), 100)


if __name__ == "__main__":
    unittest.main()
