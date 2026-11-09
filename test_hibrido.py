"""Modo combinado: borrador de un motor gratuito + revisión del LLM contra el
original. Sin red: motores falsos."""
import unittest

import transcache
import translate
from config import Config


class _Borrador(translate.TranslationBackend):
    strategy = "context"

    def translate(self, text):
        return "BORRADOR(" + text + ")"


class _Revisor(translate.TranslationBackend):
    strategy = "context"
    supports_review = True

    def __init__(self, respuestas):
        self.respuestas, self.traducidos, self.revisados = list(respuestas), [], []

    def translate(self, text):
        self.traducidos.append(text)
        return "LLM(" + text + ")"

    def refine(self, src, draft):
        self.revisados.append((src, draft))
        return self.respuestas.pop(0)


class Hibrido(unittest.TestCase):
    def test_ok_conserva_el_borrador_y_no_traduce(self):
        rev = _Revisor(["OK"])
        out, lost, passes = translate.translate_and_review(
            "hello MWTKN0", {"MWTKN0": "PLUMBATAX"}, rev, passes=3, draft_backend=_Borrador())
        self.assertEqual(out, "BORRADOR(hello PLUMBATAX)")
        self.assertEqual((lost, passes), ([], 1))
        self.assertEqual(rev.traducidos, [])
        self.assertEqual(rev.revisados, [("hello MWTKN0", "BORRADOR(hello MWTKN0)")])

    def test_correccion_reemplaza_el_borrador(self):
        rev = _Revisor(["corregido MWTKN0", "OK."])
        out, _, passes = translate.translate_and_review(
            "hello MWTKN0", {"MWTKN0": "PLUMBATAX"}, rev, passes=3, draft_backend=_Borrador())
        self.assertEqual((out, passes), ("corregido PLUMBATAX", 2))

    def test_sin_borrador_sigue_igual(self):
        rev = _Revisor(["OK"])
        out, _, passes = translate.translate_and_review("hello", {}, rev, passes=3)
        self.assertEqual((out, passes), ("LLM(hello)", 1))
        self.assertEqual(rev.traducidos, ["hello"])

    def test_borrador_por_segmentos(self):
        seg = translate.DummyBackend()
        rev = _Revisor(["OK"])
        out, lost, _ = translate.translate_and_review(
            "say MWTKN0 now", {"MWTKN0": "KORVAX"}, rev, passes=1, draft_backend=seg)
        self.assertEqual((out, lost), ("«ES» say KORVAX «ES» now", []))

    def test_es_ok(self):
        for s in ("OK", "ok", " OK. ", "Ok"):
            self.assertTrue(translate._is_ok(s))
        for s in ("", "Está OK"):
            self.assertFalse(translate._is_ok(s))
        self.assertTrue(translate._is_ok("OK, breve"))


class Firmas(unittest.TestCase):
    def test_firma_propia_y_firma_plana(self):
        a = Config(backend="groq"); b = Config(backend="groq", draft_backend="edge")
        self.assertEqual(transcache.signature(a, []), transcache.plain_signature(b, []))
        self.assertNotEqual(transcache.signature(a, []), transcache.signature(b, []))
        self.assertTrue(transcache.signature(b, []).endswith("+edge"))
        self.assertEqual(b.draft_backend, "edge")

    def test_fallbacks_cubren_todas_las_pasadas(self):
        b = Config(backend="groq", draft_backend="edge", review_passes=1)
        fb = transcache.fallback_signatures(b, [])
        self.assertEqual(fb[0], transcache.plain_signature(b, []))
        self.assertIn(transcache.signature(Config(backend="groq", review_passes=3), []), fb)
        self.assertEqual((b.review_passes, b.draft_backend), (1, "edge"))
        self.assertEqual(transcache.fallback_signatures(Config(backend="groq"), []), [])


class RotulosSinRevisar(unittest.TestCase):
    def test_rotulo_en_mayusculas_no_pasa_por_el_revisor(self):
        rev = _Revisor(["no debería llamarse"])
        out, _, passes = translate.translate_and_review(
            "CHAPTER IV MWTKN0", {"MWTKN0": "PLUMBATAX"}, rev, passes=3, draft_backend=_Borrador())
        self.assertEqual((out, passes), ("BORRADOR(CHAPTER IV PLUMBATAX)", 0))



class BorradorQueSeComeMarcadores(translate.TranslationBackend):
    strategy = "context"

    def translate(self, texto):
        return "BORR(" + texto.replace("MWTKN0", "").replace("MWTKN1", "") + ")"


class MarcadoresPerdidos(unittest.TestCase):
    def test_si_el_borrador_pierde_marcadores_el_llm_traduce_directo(self):
        rev = _Revisor(["OK"])
        out, lost, _ = translate.translate_and_review(
            "by MWTKN0 and MWTKN1 amen", {"MWTKN0": "ZORKAMEL", "MWTKN1": "PLUMBATAX"}, rev, passes=1,
            draft_backend=BorradorQueSeComeMarcadores())
        self.assertEqual(lost, [])
        self.assertIn("ZORKAMEL", out)
        self.assertIn("PLUMBATAX", out)
        self.assertEqual(rev.traducidos, ["by MWTKN0 and MWTKN1 amen"], "se pidió la traducción directa de la pieza")

    def test_si_el_borrador_conserva_los_marcadores_no_se_traduce_directo(self):
        rev = _Revisor(["OK"])
        translate.translate_and_review("by MWTKN0 amen", {"MWTKN0": "ZORKAMEL"}, rev, passes=1, draft_backend=_Borrador())
        self.assertEqual(rev.traducidos, [])


if __name__ == "__main__":
    unittest.main()
