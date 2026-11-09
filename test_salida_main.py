"""Regresiones F1 del núcleo, sin red ni PDF real."""
from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parent


def _stub_optional_imports() -> None:
    requests = types.ModuleType("requests")

    class HTTPError(Exception):
        response = None

    requests.HTTPError = HTTPError
    requests.exceptions = types.SimpleNamespace(ConnectionError=OSError, Timeout=TimeoutError)
    requests.Session = lambda: types.SimpleNamespace()
    requests.get = mock.Mock()
    requests.post = mock.Mock()
    sys.modules.setdefault("requests", requests)
    sys.modules.setdefault("fitz", types.ModuleType("fitz"))


def _main_module():
    _stub_optional_imports()
    sys.path.insert(0, str(ROOT))
    import main
    return main


class SalidaTests(unittest.TestCase):
    def test_pdf_inexistente_sale_con_codigo_no_cero(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "requests.py").write_text(
                "class HTTPError(Exception):\n"
                "    response = None\n"
                "class _E: ConnectionError = OSError; Timeout = TimeoutError\n"
                "exceptions = _E()\n"
                "class Session: pass\n"
                "def get(*a, **k): raise RuntimeError('no debe usarse')\n"
                "def post(*a, **k): raise RuntimeError('no debe usarse')\n",
                encoding="utf-8",
            )
            Path(d, "fitz.py").write_text("", encoding="utf-8")
            env = os.environ.copy()
            env["PYTHONPATH"] = d + os.pathsep + str(ROOT)
            run = subprocess.run(
                [sys.executable, str(ROOT / "main.py"), "no-existe.pdf", "--yes",
                 "--engine", "dummy", "", "--no-pdf"],
                cwd=ROOT, env=env, capture_output=True, text=True,
            )
        self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_idioma_sin_detector_rechaza_original_largo(self):
        main = _main_module()
        from config import Config

        original = "Das ist ein langer deutscher Satz mit genügend Wörtern para superar el límite."
        self.assertTrue(main.bad_translation(original, original, Config(source_lang="de")))

    def test_pdf_fallido_no_toca_destino_existente(self):
        main = _main_module()
        with tempfile.TemporaryDirectory() as d:
            html = Path(d, "libro.html")
            destino = Path(d, "libro.pdf")
            html.write_text("<p>texto</p>", encoding="utf-8")
            destino.write_bytes(b"PDF anterior")

            def falla(command, **kwargs):
                generado = Path(next(x.split("=", 1)[1] for x in command if x.startswith("--print-to-pdf=")))
                generado.write_bytes(b"PDF parcial")
                raise RuntimeError("generador falló")

            with mock.patch.object(main.render, "find_chrome", return_value="chrome"), \
                 mock.patch("subprocess.run", side_effect=falla):
                self.assertEqual(main.html_to_pdf(str(html), log=lambda _: None), "")
            self.assertEqual(destino.read_bytes(), b"PDF anterior")

    def test_cache_vieja_se_descarta_si_falta_termino_actual(self):
        main = _main_module()
        import transcache
        from config import Config

        with tempfile.TemporaryDirectory() as d:
            source = "then Asmodeus came"
            cache_path = str(Path(d, "tr.db"))
            cfg = Config(cache_translations=True, trans_cache_path=cache_path,
                         pronounce=False, make_pdf=False,
                         retries=1, output_html=str(Path(d, "out.html")))
            sig = transcache.signature(cfg, [])
            old = transcache.TranslationCache(cache_path, True)
            old.set(sig, source, "then Asn1odeus came")
            old.close()
            page = types.SimpleNamespace(
                number=1, mode="text",
                items=[types.SimpleNamespace(type="text", text=source)],
            )
            masker = types.SimpleNamespace(
                terms={}, romanizations={},
                mask=lambda text: ("then MWTKN0 came", {"MWTKN0": "Asmodeus"}),
            )
            backend = object()
            with mock.patch.object(main.extract, "extract_document", return_value=[page]), \
                 mock.patch.object(main, "make_masker", return_value=masker), \
                 mock.patch.object(main.render, "render_html"), \
                 mock.patch.object(main, "translate_and_review",
                                   return_value=("then MWTKN0 came", [], 1)) as translate:
                main.process_pdf(source, cfg, backend, [], True, "2026-11-04", log=lambda _: None)
            translate.assert_called_once()

    def test_guard_de_test_hibrido_queda_al_final(self):
        tree = ast.parse((ROOT / "test_hibrido.py").read_text(encoding="utf-8"))
        guard = next(n for n in tree.body if isinstance(n, ast.If)
                     and isinstance(n.test, ast.Compare)
                     and "__name__" in ast.unparse(n.test))
        last_class = max(n.lineno for n in tree.body if isinstance(n, ast.ClassDef))
        self.assertGreater(guard.lineno, last_class)


if __name__ == "__main__":
    unittest.main()
