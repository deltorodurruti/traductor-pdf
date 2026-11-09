"""Regresiones para los hallazgos de la auditoría, sin red ni datos de libros."""
from __future__ import annotations

import base64
import importlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parent
ENTRYPOINTS = (
    "main.py", "hojas.py", "_verify_book.py", "entregar_libro.py",
    "completar_libro.py", "verificar.py", "server.py",
)
class RequirementsTests(unittest.TestCase):
    def test_supported_entrypoints_import_and_require_beautifulsoup(self):
        for path in ENTRYPOINTS:
            importlib.import_module(Path(path).stem)
        self.assertIn("beautifulsoup4", (ROOT / "requirements.txt").read_text(encoding="utf-8").lower())


class MainCountersTests(unittest.TestCase):
    def test_process_pdf_counts_a_failed_block_once_after_retries(self):
        import main
        from config import Config

        page = types.SimpleNamespace(
            mode="text", number=1,
            items=[types.SimpleNamespace(type="text", text="texto de prueba")],
        )
        masker = types.SimpleNamespace(mask=lambda text: (text, {}), terms={}, romanizations={})
        cfg = Config(cache_translations=False, pronounce=False,
                     make_pdf=False, retries=2, output_html=os.path.join(tempfile.gettempdir(), "out.html"))
        with mock.patch.object(main.extract, "extract_document", return_value=[page]), \
             mock.patch.object(main, "make_masker", return_value=masker), \
             mock.patch.object(main, "translate_and_review", side_effect=RuntimeError("fallo")), \
             mock.patch.object(main.render, "render_html"):
            result = main.process_pdf("entrada.pdf", cfg, object(), [], True, "2026-01-01", log=lambda _: None)
        self.assertEqual(result["errors"], 1)


class AtomicWriteTests(unittest.TestCase):
    def test_failed_replace_keeps_destination_and_removes_tmp(self):
        import render

        with tempfile.TemporaryDirectory() as d:
            destination = os.path.join(d, "salida.html")
            Path(destination).write_text("completo anterior", encoding="utf-8")
            with mock.patch.object(render.os, "replace", side_effect=OSError("disco lleno")):
                with self.assertRaises(OSError):
                    render.escribir_atomico(destination, "nuevo completo")
            self.assertEqual(Path(destination).read_text(encoding="utf-8"), "completo anterior")
            self.assertEqual(list(Path(d).glob("*.tmp")), [])

    def test_failed_layout_keeps_working_html(self):
        import entregar_libro

        with tempfile.TemporaryDirectory() as d:
            html = os.path.join(d, "libro_es.html")
            Path(html).write_text("original completo", encoding="utf-8")
            failed = types.SimpleNamespace(returncode=1, stdout="", stderr="maquetación fallida")
            with mock.patch.object(entregar_libro, "ENTREGADOS", {"libro": "Libro_ES.pdf"}), \
                 mock.patch.object(entregar_libro, "arreglar", return_value=("nuevo candidato", 1)), \
                 mock.patch.object(entregar_libro, "titulo_corrido", return_value=("nuevo candidato", 0)), \
                 mock.patch.object(entregar_libro.subprocess, "run", return_value=failed):
                entregar_libro._una("libro", d)
            self.assertEqual(Path(html).read_text(encoding="utf-8"), "original completo")
            self.assertFalse(os.path.exists(html + ".candidato"))


class DeliveryHookTests(unittest.TestCase):
    def _patches(self, module, d):
        return (
            mock.patch.object(module, "ENTREGADOS", {"libro": "Libro_ES.pdf"}),
            mock.patch.object(module, "ENTREGA", d),
            mock.patch.object(module, "arreglar", return_value=("nuevo candidato", 1)),
            mock.patch.object(module, "titulo_corrido", return_value=("nuevo candidato", 0)),
        )

    def test_failed_hook_restores_working_html_and_discards_candidates(self):
        import entregar_libro

        with tempfile.TemporaryDirectory() as d:
            html = os.path.join(d, "libro_es.html")
            hook = os.path.join(d, "entregar.sh")
            Path(html).write_text("original completo", encoding="utf-8")
            Path(hook).touch()
            failed = types.SimpleNamespace(returncode=1, stdout="", stderr="maquetación fallida")
            patches = self._patches(entregar_libro, d)
            with patches[0], patches[1], patches[2], patches[3], \
                 mock.patch.object(entregar_libro.subprocess, "run", return_value=failed):
                entregar_libro._una("libro", d)
            self.assertEqual(Path(html).read_text(encoding="utf-8"), "original completo")
            self.assertFalse(os.path.exists(html + ".previo"))
            self.assertFalse(os.path.exists(html + ".candidato"))

    def test_successful_hook_keeps_new_working_html(self):
        import entregar_libro

        with tempfile.TemporaryDirectory() as d:
            html = os.path.join(d, "libro_es.html")
            hook = os.path.join(d, "entregar.sh")
            Path(html).write_text("original completo", encoding="utf-8")
            Path(hook).touch()

            seen_by_hook = []

            def succeeds(command, **_kwargs):
                seen_by_hook.append(Path(html).read_text(encoding="utf-8"))
                import fitz
                doc = fitz.open()
                doc.new_page().insert_text((40, 40), "texto")
                doc.save(command[1])
                doc.close()
                return types.SimpleNamespace(returncode=0, stdout="", stderr="")

            patches = self._patches(entregar_libro, d)
            with patches[0], patches[1], patches[2], patches[3], \
                 mock.patch.object(entregar_libro.subprocess, "run", side_effect=succeeds):
                entregar_libro._una("libro", d)
            self.assertEqual(seen_by_hook, ["nuevo candidato"])
            self.assertEqual(Path(html).read_text(encoding="utf-8"), "nuevo candidato")
            self.assertFalse(os.path.exists(html + ".previo"))


class RuntimePathTests(unittest.TestCase):
    def test_supported_entrypoints_have_no_personal_or_anaconda_paths(self):
        paths = [
            "main.py", "hojas.py", "_verify_book.py", "entregar_libro.py", "completar_libro.py",
            "verificar.py", "server.py", "flujo.sh", "herramientas/libro.sh", "revisar_todos.sh",
        ]
        for path in paths:
            text = (ROOT / path).read_text(encoding="utf-8")
            self.assertNotIn("/opt/anaconda3", text)


class ServerOptionsTests(unittest.TestCase):
    def _post(self, options):
        import server
        body = json.dumps({"pdf_base64": base64.b64encode(b"pdf").decode(), "options": options}).encode()
        fake = types.SimpleNamespace(
            path="/api/translate",
            headers={"Host": "localhost:8765", "Origin": "http://localhost:8765", "Content-Length": str(len(body))},
            rfile=io.BytesIO(body),
        )
        sent = []
        fake._send = lambda code, payload, *args: sent.append((code, payload))
        server.Handler.do_POST(fake)
        return sent[0]

    def test_invalid_options_return_400_with_field_name(self):
        for options, message in (
            ({"engine": "cloud"}, "el servidor web solo permite motores locales"),
            ({"book_type": "desconocido"}, "tipo de texto inválido"),
            ({"max_pages": -1}, "max_pages"),
            ({"review_passes": 6}, "review_passes"),
        ):
            code, payload = self._post(options)
            self.assertEqual(code, 400)
            self.assertIn(message, json.loads(payload)["error"])

    def test_valid_options_build_a_config(self):
        import server
        with mock.patch.object(server, "_validate_options", side_effect=AssertionError("no se valida aquí")):
            cfg = server._cfg_from_options(
                {"engine": "ollama", "book_type": "general", "max_pages": 0,
                 "pronounce": True},
                "entrada.pdf", "salida.html",
            )
        self.assertEqual((cfg.backend, cfg.book_type, cfg.max_pages, cfg.review_passes),
                         ("ollama", "general", None, server.Config().review_passes))
        self.assertIsNone(server._validate_options({"engine": "ollama"}))


if __name__ == "__main__":
    unittest.main()
