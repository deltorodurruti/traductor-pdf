"""Regresiones de seguridad e integridad del flujo, sin datos de libros ni llamadas externas."""
import concurrent.futures
import json
import os
import pickle
import tempfile
import unittest
from unittest import mock

import entregar_libro
import estado
import lexicon
import main
import server
from herramientas import auditar_imagenes


def _touch_marker(path):
    with open(path, "w", encoding="utf-8") as f:
        f.write("executed")


class _LegacyPayload:
    def __init__(self, path):
        self.path = path

    def __reduce__(self):
        return _touch_marker, (self.path,)


class RemoteConsentTests(unittest.TestCase):
    def test_all_remote_backends_require_the_cli_confirmation(self):
        self.assertEqual(main._remote_backends("web"), ["web"])
        self.assertEqual(main._remote_backends("edge"), ["edge"])
        self.assertEqual(main._remote_backends("ollama", "web"), ["web"])
        self.assertEqual(main._remote_backends("ollama"), [])

    def test_cli_engine_choices_follow_supported_cloud_providers(self):
        self.assertEqual(set(main.CloudBackend.PROVIDERS) - set(main.ENGINE_CHOICES), set())


class LocalServerTests(unittest.TestCase):
    def test_only_same_origin_loopback_requests_are_allowed(self):
        self.assertTrue(server._origin_allowed("localhost:8765", "http://localhost:8765"))
        self.assertTrue(server._origin_allowed("127.0.0.1:8765", "http://127.0.0.1:8765"))
        self.assertFalse(server._origin_allowed("localhost:8765", "https://attacker.example"))
        self.assertFalse(server._origin_allowed("attacker.example", "http://localhost:8765"))
        self.assertFalse(server._origin_allowed("localhost:8765", ""))

    def test_web_interface_only_exposes_local_engines(self):
        self.assertEqual(server.ALLOWED_ENGINES, {"ollama", "opus", "argos"})

    def test_active_job_limit_rejects_excess_jobs(self):
        with server.jobs_lock:
            old_jobs, old_active, old_limit = server.jobs, server.active_jobs, server.MAX_ACTIVE_JOBS
            server.jobs, server.active_jobs, server.MAX_ACTIVE_JOBS = {}, 0, 2
        try:
            self.assertTrue(server._new_job())
            self.assertTrue(server._new_job())
            self.assertEqual(server._new_job(), "")
        finally:
            with server.jobs_lock:
                server.jobs, server.active_jobs, server.MAX_ACTIVE_JOBS = old_jobs, old_active, old_limit


class WorkflowTests(unittest.TestCase):
    def test_bilingual_file_advances_to_verification(self):
        with mock.patch.object(estado, "archivos", return_value=(None, "/tmp/original.pdf", None)), \
             mock.patch.object(estado, "bilingue", return_value="/tmp/book_bilingue.html"):
            self.assertEqual(estado.etapa("book"), "2 verificar y completar")

    def test_atomic_copy_replaces_destination_with_complete_file(self):
        with tempfile.TemporaryDirectory() as d:
            source, destination = os.path.join(d, "source.pdf"), os.path.join(d, "delivered.pdf")
            with open(source, "wb") as f:
                f.write(b"complete new PDF")
            with open(destination, "wb") as f:
                f.write(b"old PDF")
            entregar_libro._copiar_atomico(source, destination)
            with open(destination, "rb") as f:
                self.assertEqual(f.read(), b"complete new PDF")
            self.assertEqual(sorted(os.listdir(d)), ["delivered.pdf", "source.pdf"])

    def test_learned_lexicon_keeps_concurrent_additions(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "learned.json")
            entries = [[{"original": f"term-{i}", "es_cl": str(i)}] for i in range(16)]
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda batch: lexicon.remember(path, batch), entries))
            with open(path, encoding="utf-8") as f:
                saved = json.load(f)["lexico"]
            self.assertEqual({entry["original"] for entry in saved},
                             {f"term-{i}" for i in range(16)})

    def test_figure_cache_ignores_legacy_pickle_files(self):
        with tempfile.TemporaryDirectory() as d:
            source = os.path.join(d, "source.pdf")
            with open(source, "wb") as f:
                f.write(b"fixture")
            legacy = os.path.join(d, "source.pdf.figuras.pkl")
            marker = os.path.join(d, "pickle-executed")
            with open(legacy, "wb") as f:
                pickle.dump(_LegacyPayload(marker), f)
            from PIL import Image
            sample = [{"pag": 1, "h": 0, "im": Image.new("RGB", (2, 2)), "ingles": False}]
            with mock.patch.object(auditar_imagenes, "de_fuente", return_value=sample) as extract:
                result = auditar_imagenes.de_fuente_cacheada(source, d)
            extract.assert_called_once_with(source)
            self.assertEqual(result[0]["pag"], 1)
            self.assertFalse(os.path.exists(marker))
            self.assertTrue(os.path.exists(legacy))
            self.assertTrue(os.path.exists(os.path.join(d, "source.pdf.figuras.json")))


if __name__ == "__main__":
    unittest.main()
