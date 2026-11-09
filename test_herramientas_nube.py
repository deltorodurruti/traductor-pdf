import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "herramientas"))

import remoto
import herramientas.maquetar_versos as maquetar_versos
import herramientas.completar_bloques as completar_bloques
import herramientas.paginas_con_tablas as paginas_con_tablas
import herramientas.rehacer_paginas_vacias as rehacer_paginas_vacias
import herramientas.traducir_in_situ as traducir_in_situ
import herramientas.completar_bloques as completar_bloques


class HerramientasNubeTests(unittest.TestCase):
    def test_traducir_in_situ_no_pisa_json_si_falla_el_reemplazo(self):
        with tempfile.TemporaryDirectory() as td:
            ruta = Path(td) / "trad.json"
            ruta.write_text('{"viejo": "valor"}', encoding="utf-8")
            salida = Path(td) / "salida.pdf"
            salida.write_bytes(b"pdf anterior")
            doc = mock.Mock()
            with mock.patch.object(traducir_in_situ.fitz, "open", return_value=doc), \
                    mock.patch.object(traducir_in_situ, "extraer", return_value=[]), \
                    mock.patch.object(traducir_in_situ.os, "replace", side_effect=OSError("corte")), \
                    mock.patch.object(sys, "argv", ["traducir_in_situ.py", "entrada.pdf", str(ruta),
                                                     str(salida), "--extraer"]):
                with self.assertRaises(OSError):
                    traducir_in_situ.main()
            self.assertEqual(ruta.read_text(encoding="utf-8"), '{"viejo": "valor"}')
            self.assertEqual(salida.read_bytes(), b"pdf anterior")

    def test_traducir_in_situ_no_pisa_pdf_si_falla_el_reemplazo(self):
        with tempfile.TemporaryDirectory() as td:
            ruta = Path(td) / "trad.json"
            ruta.write_text("{}", encoding="utf-8")
            salida = Path(td) / "salida.pdf"
            salida.write_bytes(b"pdf anterior")
            doc = mock.Mock()
            with mock.patch.object(traducir_in_situ.fitz, "open", return_value=doc), \
                    mock.patch.object(traducir_in_situ, "extraer", return_value=[]), \
                    mock.patch.object(traducir_in_situ, "aplicar", return_value={"hechas": 0, "pendientes": [],
                                                                                   "reducidas": [], "empujadas": 0}), \
                    mock.patch.object(traducir_in_situ.os, "replace", side_effect=OSError("corte")), \
                    mock.patch.object(sys, "argv", ["traducir_in_situ.py", "entrada.pdf", str(ruta), str(salida)]):
                with self.assertRaises(OSError):
                    traducir_in_situ.main()
            self.assertEqual(salida.read_bytes(), b"pdf anterior")

    def test_motores_remotos_y_locales_usan_la_clasificacion_real(self):
        import main
        for motor in ("ollama", "argos", "dummy"):
            self.assertNotIn(motor, main.REMOTE_BACKENDS)
        for motor in ("groq", "cloudflare", "mistral", "edge", "web", "google"):
            self.assertIn(motor, main.REMOTE_BACKENDS)

    def test_traducir_in_situ_publica_yes_cloud_en_help(self):
        r = subprocess.run(
            [sys.executable, str(ROOT / "herramientas" / "traducir_in_situ.py"), "--help"],
            capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--yes-cloud", r.stdout)

    def _cfg_traducir_in_situ(self):
        return mock.Mock(glossary_path="", review_early_stop=False)

    def test_traducir_in_situ_remoto_sin_consentimiento_no_crea_backend(self):
        cfg = self._cfg_traducir_in_situ()
        with mock.patch("config.Config", return_value=cfg), \
                mock.patch("main.load_glossary", return_value=[]), \
                mock.patch("main.make_masker", return_value=mock.Mock()), \
                mock.patch("remoto.es_remoto", return_value=True), \
                mock.patch("remoto.exigir_consentimiento_nube",
                            side_effect=remoto.SinConsentimiento("no")), \
                mock.patch("translate.make_backend", side_effect=AssertionError("backend prematuro")) as make:
            with self.assertRaises(remoto.SinConsentimiento):
                traducir_in_situ.traducir_faltantes({}, ["texto"], "groq", "modelo", "", aceptado=False)
        make.assert_not_called()

    def test_traducir_in_situ_local_sigue_sin_consentimiento(self):
        cfg = self._cfg_traducir_in_situ()
        backend = mock.Mock()
        backend.available.return_value = (True, "")
        masker = mock.Mock()
        masker.mask.return_value = ("texto", {})
        trad = {}
        with mock.patch("config.Config", return_value=cfg), \
                mock.patch("main.load_glossary", return_value=[]), \
                mock.patch("main.make_masker", return_value=masker), \
                mock.patch("remoto.es_remoto", return_value=False), \
                mock.patch("remoto.exigir_consentimiento_nube",
                            side_effect=AssertionError("consentimiento local")) as gate, \
                mock.patch("translate.make_backend", return_value=backend), \
                mock.patch("translate.translate_and_review", return_value=("traducción", [], 1)):
            self.assertEqual(
                traducir_in_situ.traducir_faltantes(trad, ["texto"], "ollama", "modelo", "", aceptado=False), 1
            )
        self.assertEqual(trad["texto"], "traducción")
        gate.assert_not_called()

    def test_traducir_in_situ_remoto_con_yes_cloud_sigue(self):
        cfg = self._cfg_traducir_in_situ()
        backend = mock.Mock()
        backend.available.return_value = (True, "")
        masker = mock.Mock()
        masker.mask.return_value = ("texto", {})
        with mock.patch("config.Config", return_value=cfg), \
                mock.patch("main.load_glossary", return_value=[]), \
                mock.patch("main.make_masker", return_value=masker), \
                mock.patch("remoto.es_remoto", return_value=True), \
                mock.patch("remoto.exigir_consentimiento_nube") as gate, \
                mock.patch("translate.make_backend", return_value=backend), \
                mock.patch("translate.translate_and_review", return_value=("traducción", [], 1)):
            self.assertEqual(
                traducir_in_situ.traducir_faltantes({}, ["texto"], "groq", "modelo", "", aceptado=True), 1
            )
        gate.assert_called_once_with("traducir_in_situ", aceptado=True)

    def test_entrada_directa_reenvia_yes_cloud(self):
        with tempfile.TemporaryDirectory() as td:
            ruta = Path(td) / "trad.json"
            ruta.write_text("{}", encoding="utf-8")
            with mock.patch.object(traducir_in_situ.fitz, "open", return_value=mock.Mock()), \
                    mock.patch.object(traducir_in_situ, "extraer", return_value=[]), \
                    mock.patch.object(traducir_in_situ, "traducir_faltantes") as traducir, \
                    mock.patch.object(sys, "argv", ["traducir_in_situ.py", "entrada.pdf", str(ruta),
                                                     "--traducir", "--yes-cloud"]):
                traducir_in_situ.main()
        self.assertTrue(traducir.call_args.kwargs["aceptado"])

    def test_rehacer_ayuda_funciona_como_script(self):
        r = subprocess.run(
            [sys.executable, str(ROOT / "herramientas" / "rehacer_paginas_vacias.py"), "--help"],
            capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--yes-cloud", r.stdout)

    @staticmethod
    def _html(td):
        ruta = Path(td) / "libro_es.html"
        ruta.write_text(
            "<section class='page'><div class='page-num'>Página 1</div>"
            "<div class='solo'>the and of this text remains in the source</div></section>",
            encoding="utf-8",
        )
        return ruta

    def test_completar_remoto_exige_consentimiento_antes_del_backend(self):
        with tempfile.TemporaryDirectory() as td:
            ruta = self._html(td)
            with mock.patch("remoto.exigir_consentimiento_nube",
                            side_effect=remoto.SinConsentimiento("no")), \
                    mock.patch("translate.make_backend", side_effect=AssertionError("backend prematuro")), \
                    mock.patch.object(sys, "argv", ["completar_bloques.py", str(ruta), "--motor", "groq", "--aplicar"]):
                with self.assertRaises(SystemExit) as cm:
                    completar_bloques.main()
                self.assertEqual(cm.exception.code, 78)

    def test_motores_locales_no_exigen_consentimiento_en_completar_y_versos(self):
        backend = mock.Mock()
        backend.available.return_value = (True, "")
        masker = mock.Mock()
        for motor in ("ollama", "argos", "dummy"):
            with self.subTest(motor=motor), tempfile.TemporaryDirectory() as td:
                ruta = self._html(td)
                with mock.patch("remoto.exigir_consentimiento_nube",
                                side_effect=AssertionError("consentimiento local")) as gate, \
                        mock.patch("translate.make_backend", return_value=backend), \
                        mock.patch("main.load_glossary", return_value=[]), \
                        mock.patch("main.make_masker", return_value=masker), \
                        mock.patch("main.bad_translation", return_value=False), \
                        mock.patch.object(completar_bloques, "traducir", return_value="traducción"), \
                        mock.patch.object(sys, "argv", ["completar_bloques.py", str(ruta), "--motor", motor, "--aplicar"]):
                    completar_bloques.main()
                gate.assert_not_called()

    def test_motor_local_no_exige_consentimiento_en_versos(self):
        backend = mock.Mock()
        backend.available.return_value = (True, "")
        for motor in ("ollama", "argos", "dummy"):
            with self.subTest(motor=motor), \
                    mock.patch("remoto.exigir_consentimiento_nube",
                               side_effect=AssertionError("consentimiento local")) as gate, \
                    mock.patch("translate.make_backend", return_value=backend), \
                    mock.patch("main.load_glossary", return_value=[]), \
                    mock.patch("intraducibles.Masker", return_value=mock.Mock()), \
                    mock.patch("transcache.TranslationCache"):
                maquetar_versos.Traductor(motor, "modelo", "")
            gate.assert_not_called()
    def test_versos_exige_consentimiento_antes_del_backend(self):
        with mock.patch("remoto.exigir_consentimiento_nube", side_effect=remoto.SinConsentimiento("no")), \
                mock.patch("translate.make_backend", side_effect=AssertionError("backend prematuro")):
            with self.assertRaises(remoto.SinConsentimiento):
                maquetar_versos.Traductor("groq", "modelo", "")

    def test_tablas_exige_consentimiento_antes_del_backend(self):
        with mock.patch("remoto.exigir_consentimiento_nube", side_effect=remoto.SinConsentimiento("no")), \
                mock.patch("translate.make_backend", side_effect=AssertionError("backend prematuro")):
            with self.assertRaises(remoto.SinConsentimiento):
                paginas_con_tablas._traductor("", "modelo")

    def test_tablas_motor_local_no_exige_consentimiento(self):
        cfg = mock.Mock(backend="ollama", glossary_path="", cloud_model="modelo", reasoning_effort="medium",
                        review_passes=1, book_type="especializado", review_early_stop=False)
        backend = mock.Mock()
        backend.available.return_value = (True, "")
        with mock.patch.object(paginas_con_tablas._config, "Config", return_value=cfg), \
                mock.patch("remoto.es_remoto", return_value=False), \
                mock.patch("remoto.exigir_consentimiento_nube", side_effect=AssertionError("consentimiento local")) as gate, \
                mock.patch("translate.make_backend", return_value=backend), \
                mock.patch("main.load_glossary", return_value=[]), \
                mock.patch("main.make_masker", return_value=mock.Mock()):
            paginas_con_tablas._traductor("", "modelo")
        gate.assert_not_called()

    def test_paginas_vacias_exige_consentimiento_antes_de_traducir(self):
        class Page:
            def __init__(self, text):
                self.text = text
                self.rect = mock.Mock(width=600, height=800)

            def get_text(self, kind=None):
                if kind == "blocks":
                    return [(0, 0, 100, 100, self.text, 0, 0)]
                return self.text

            def insert_htmlbox(self, *args, **kwargs):
                return (0, None)

        class Doc:
            def __init__(self, pages):
                self.pages = pages

            def __iter__(self):
                return iter(self.pages)

            def __len__(self):
                return len(self.pages)

            def __getitem__(self, i):
                return self.pages[i]

            def save(self, *args, **kwargs):
                raise AssertionError("no debe guardar")

        tr = Doc([Page("P Á G I N A 1")])
        orig = Doc([Page("texto original " * 30)])
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(rehacer_paginas_vacias.fitz, "open", side_effect=[tr, orig]), \
                    mock.patch("remoto.exigir_consentimiento_nube", side_effect=remoto.SinConsentimiento("no")), \
                    mock.patch("traducir_in_situ.traducir_faltantes", side_effect=AssertionError("backend prematuro")), \
                    mock.patch.object(sys, "argv", ["rehacer_paginas_vacias.py", "tr.pdf", "o.pdf", str(Path(td) / "s.pdf")]):
                with self.assertRaises(remoto.SinConsentimiento):
                    rehacer_paginas_vacias.main()

    def test_paginas_vacias_motor_local_no_exige_consentimiento(self):
        class Page:
            rect = mock.Mock(width=600, height=800)

            def __init__(self, text):
                self.text = text

            def get_text(self, kind=None):
                if kind == "blocks":
                    return [(0, 0, 100, 100, self.text, 0, 0)]
                return self.text

            def insert_htmlbox(self, *args, **kwargs):
                return (0, None)

        class Doc:
            def __init__(self, pages):
                self.pages = pages

            def __iter__(self):
                return iter(self.pages)

            def __len__(self):
                return len(self.pages)

            def __getitem__(self, i):
                return self.pages[i]

        tr = Doc([Page("P Á G I N A 1")])
        orig = Doc([Page("texto original " * 30)])
        with tempfile.TemporaryDirectory() as td:
            salida = Path(td) / "s.pdf"
            with mock.patch.object(rehacer_paginas_vacias.fitz, "open", side_effect=[tr, orig]), \
                    mock.patch("remoto.es_remoto", return_value=False), \
                    mock.patch("remoto.exigir_consentimiento_nube", side_effect=AssertionError("consentimiento local")) as gate, \
                    mock.patch("traducir_in_situ.traducir_faltantes"), \
                    mock.patch.object(rehacer_paginas_vacias, "guardar_pdf_atomico"), \
                    mock.patch.object(sys, "argv", ["rehacer_paginas_vacias.py", "tr.pdf", "o.pdf", str(salida)]):
                rehacer_paginas_vacias.main()
            gate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
