"""Regresiones F1 de consentimiento de nube, sin red ni dependencias opcionales."""
from __future__ import annotations

import io
import os
from pathlib import Path
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


class ConsentimientoTests(unittest.TestCase):
    def test_verificar_no_hace_round_trip_sin_consentimiento(self):
        import verificar

        with mock.patch.dict(os.environ, {"TRADUCTOR_NUBE_OK": ""}, clear=False), \
             mock.patch.object(sys.stdin, "isatty", return_value=False), \
             mock.patch.object(verificar, "pairs_from_html",
                               return_value=[("palabra " * 20, "palabra " * 20)]), \
             mock.patch.object(verificar, "round_trip") as round_trip, \
             mock.patch("urllib.request.urlopen", side_effect=AssertionError("HTTP inesperado")), \
             mock.patch("sys.stdout", new_callable=io.StringIO):
            verificar.main(["libro.html", "--no-llama"])
        round_trip.assert_not_called()

    def test_server_rechaza_yes_cloud_no_booleano(self):
        _stub_optional_imports()
        import server

        with self.assertRaisesRegex(ValueError, "yes_cloud debe ser true o false"):
            server._validate_options({"engine": "ollama", "yes_cloud": 1})


if __name__ == "__main__":
    unittest.main()
