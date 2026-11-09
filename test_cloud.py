"""Motor de nube: espera ante cuotas (429/503), motivo legible, bloque imposible,
y firma de caché por modelo. Sin red: la sesión HTTP es falsa."""
import unittest
from unittest import mock

import transcache
import translate
from config import Config


class _Resp:
    def __init__(self, status, headers=None, text="", content="hola"):
        self.status_code, self.headers, self.text = status, headers or {}, text
        self._content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


GROQ_TPD = ('{"error":{"message":"Rate limit reached for model `m` on tokens per day (TPD): '
            'Limit 200000, Used 199500, Requested 645. Please try again in 1m2.639999999s.",'
            '"type":"tokens"}}')
GROQ_IMPOSIBLE = GROQ_TPD.replace("Requested 645", "Requested 9000").replace("Limit 200000", "Limit 8000")
GROQ_OTPM = ('{"error":{"message":"Request too large for model `qwen/qwen3.8-27b` in organization `o` '
             'service tier `on_demand` on output tokens per minute (OTPM): Limit 1000, Requested 1297. '
             'The request\'s expected output tokens exceed the enforced limit; reduce max_tokens","type":"tokens"}}')
GEMINI_RPD = ('[{"error":{"code":429,"message":"You exceeded your current quota.\\n* Quota exceeded '
              'for metric: generate_content_free_tier_requests, limit: 20\\nPlease retry in 8h37m21.0s.",'
              '"details":[{"@type":"RetryInfo","retryDelay":"31041s"}]}}]')


def _backend(responses):
    b = translate.CloudBackend("groq", "", 0.2, "inglés", "español", "reg", "fluida")
    b._key = "k"
    b._session = mock.Mock()
    b._session.post = mock.Mock(side_effect=responses)
    return b


class Duraciones(unittest.TestCase):
    def test_formatos(self):
        p = translate.parse_duration
        self.assertAlmostEqual(p("1m2.6s"), 62.6)
        self.assertEqual(p("8h37m21s"), 31041)
        self.assertAlmostEqual(p("697ms"), 0.697)
        self.assertEqual(p("63"), 63)
        self.assertEqual(p("31041s"), 31041)
        self.assertIsNone(p(""))
        self.assertIsNone(p("pronto"))


class Esperas(unittest.TestCase):
    def test_retry_after_manda(self):
        wait, why = translate.rate_limit_wait(429, {"retry-after": "63"}, GROQ_TPD)
        self.assertEqual(wait, 63)
        self.assertIn("tokens per day", why)

    def test_mensaje_groq_sin_cabecera(self):
        wait, _ = translate.rate_limit_wait(429, {}, GROQ_TPD)
        self.assertAlmostEqual(wait, 62.64, places=1)

    def test_mensaje_gemini(self):
        wait, why = translate.rate_limit_wait(429, {}, GEMINI_RPD)
        self.assertEqual(wait, 31041)
        self.assertIn("limit: 20", why)

    def test_sin_pistas_30s(self):
        wait, why = translate.rate_limit_wait(503, {}, "")
        self.assertEqual((wait, why), (30.0, "HTTP 503"))

    def test_bloque_imposible(self):
        wait, why = translate.rate_limit_wait(429, {"retry-after": "5"}, GROQ_IMPOSIBLE)
        self.assertIsNone(wait)
        self.assertIn("--chunk-chars", why)


class Chat(unittest.TestCase):
    @mock.patch("time.sleep")
    def test_otpm_pone_max_tokens_y_sigue(self, sleep):
        resps, payloads = iter([_Resp(429, {}, GROQ_OTPM), _Resp(200), _Resp(200)]), []
        b = _backend(lambda *a, **k: (payloads.append(dict(k["json"])), next(resps))[1])
        with mock.patch("builtins.print"):
            self.assertEqual(b.translate("hello"), "hola")
            b.translate("otra")
        self.assertFalse(sleep.called)
        self.assertNotIn("max_tokens", payloads[0])
        self.assertEqual(payloads[1]["max_tokens"], 900)
        self.assertEqual(payloads[2]["max_tokens"], 900)

    def test_clave_alternativa_por_entorno(self):
        with mock.patch.dict("os.environ", {"GROQ_KEY_FILE": "/tmp/otra_clave"}):
            b = translate.CloudBackend("groq", "", 0.2, "inglés", "español", "reg", "fluida")
        self.assertEqual(b._keyfile, "/tmp/otra_clave")
        b2 = translate.CloudBackend("groq", "", 0.2, "inglés", "español", "reg", "fluida")
        self.assertTrue(b2._keyfile.endswith(".groq_key"))

    def test_cloudflare_arma_la_url_con_la_cuenta(self):
        with mock.patch.dict("os.environ", {"CLOUDFLARE_ACCOUNT_ID": "abc123"}):
            b = translate.CloudBackend("cloudflare", "", 0.2, "inglés", "español", "reg", "fluida")
        self.assertEqual(b.base, "https://api.cloudflare.com/client/v4/accounts/abc123/ai/v1")
        self.assertEqual(b.model, "@cf/openai/gpt-oss-120b")
        self.assertTrue(b._keyfile.endswith(".cloudflare_key"))

    def test_cloudflare_fija_max_tokens_para_no_truncar(self):
        payloads = []
        with mock.patch.dict("os.environ", {"CLOUDFLARE_ACCOUNT_ID": "abc123"}):
            b = translate.CloudBackend("cloudflare", "", 0.2, "inglés", "español", "reg", "fluida")
        b._session.post = lambda *a, **k: (payloads.append(dict(k["json"])), _Resp(200))[1]
        b._key = "k"
        b.translate("x")
        self.assertEqual(payloads[0]["max_tokens"], 4096)

    def test_cloudflare_sin_cuenta_no_esta_disponible(self):
        with mock.patch.dict("os.environ", {"CLOUDFLARE_ACCOUNT_ID": ""}), \
             mock.patch.object(translate.CloudBackend, "_cloudflare_account", staticmethod(lambda: "")), \
             mock.patch("os.path.exists", return_value=True):
            b = translate.CloudBackend("cloudflare", "", 0.2, "inglés", "español", "reg", "fluida")
            ok, msg = b.available()
        self.assertFalse(ok)
        self.assertIn("id de cuenta", msg)

    def test_razonamiento_va_en_el_pedido(self):
        payloads = []
        b = _backend(lambda *a, **k: (payloads.append(dict(k["json"])), _Resp(200))[1])
        b.translate("x")
        b.reasoning_effort = "low"
        b.translate("y")
        self.assertNotIn("reasoning_effort", payloads[0])
        self.assertEqual(payloads[1]["reasoning_effort"], "low")

    def test_otpm_sin_used_es_imposible(self):
        wait, _ = translate.rate_limit_wait(429, {}, GROQ_OTPM)
        self.assertIsNone(wait)

    @mock.patch("time.sleep")
    def test_espera_y_sigue(self, sleep):
        b = _backend([_Resp(429, {"retry-after": "63"}, GROQ_TPD), _Resp(503), _Resp(200)])
        with mock.patch("builtins.print"):
            self.assertEqual(b.translate("hello"), "hola")
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [63.0, 30.0])
        self.assertEqual(b._session.post.call_count, 3)

    @mock.patch("time.sleep")
    def test_espera_desmedida_se_rinde(self, sleep):
        b = _backend([_Resp(429, {}, GEMINI_RPD), _Resp(200)])
        with mock.patch("builtins.print"), self.assertRaisesRegex(RuntimeError, "me rindo"):
            b.translate("hello")
        self.assertEqual(sleep.call_count, 0)
        self.assertEqual(b._session.post.call_count, 1)

    @mock.patch("time.sleep")
    def test_presupuesto_de_espera_es_por_clave(self, sleep):
        pide = _Resp(429, {"retry-after": "100"}, GROQ_TPD)
        b = _backend([pide] * 5 + [_Resp(200)] + [pide] * 5 + [_Resp(200)])
        with mock.patch("builtins.print"):
            self.assertEqual(b.translate("hello"), "hola")
            with self.assertRaisesRegex(RuntimeError, "me rindo"):
                b.translate("hello again")
        self.assertEqual(sleep.call_count, 5 + 4)

    @mock.patch("time.sleep")
    def test_imposible_no_reintenta(self, sleep):
        b = _backend([_Resp(429, {"retry-after": "5"}, GROQ_IMPOSIBLE)])
        with self.assertRaises(RuntimeError):
            b.translate("hello")
        sleep.assert_not_called()

    def test_error_normal_propaga(self):
        b = _backend([_Resp(500)])
        with self.assertRaises(RuntimeError):
            b.translate("hello")

    def test_vacio_no_llama(self):
        b = _backend([])
        self.assertEqual(b.translate("   "), "   ")
        b._session.post.assert_not_called()


class Edge(unittest.TestCase):
    def _edge(self, responses):
        b = translate.EdgeBackend("en", "es")
        b._session = mock.Mock(); b._session.post = mock.Mock(side_effect=responses)
        return b

    def test_escapa_html_y_restaura(self):
        class R(_Resp):
            def json(self): return [{"translations": [{"text": "a &lt; b", "to": "es"}]}]
        b = self._edge([R(200)])
        self.assertEqual(b.translate("a < b"), "a < b")
        self.assertEqual(b._session.post.call_args.kwargs["json"], ["a &lt; b"])
        self.assertEqual(b._session.post.call_args.kwargs["params"]["to"], "es")

    @mock.patch("time.sleep")
    def test_espera_429(self, sleep):
        class R(_Resp):
            def json(self): return [{"translations": [{"text": "hola", "to": "es"}]}]
        b = self._edge([_Resp(429, {"retry-after": "7"}), R(200)])
        with mock.patch("builtins.print"):
            self.assertEqual(b.translate("hello"), "hola")
        self.assertEqual(sleep.call_args.args[0], 7.0)

    def test_segmentos_preservan_terminos(self):
        class R(_Resp):
            def json(self): return [{"translations": [{"text": "X", "to": "es"}]}]
        b = self._edge([R(200)] * 5)
        out, lost, _ = translate.translate_and_review("say MWTKN0 now", {"MWTKN0": "PLUMBATAX"}, b)
        self.assertEqual((out, lost), ("X PLUMBATAX X", []))


class Firma(unittest.TestCase):
    def test_modelo_explicito_distingue(self):
        a, b = Config(backend="groq"), Config(backend="groq", cloud_model="qwen/qwen3.8-27b")
        self.assertNotEqual(transcache.signature(a, []), transcache.signature(b, []))
        self.assertIn("|groq|", transcache.signature(a, []))

    def test_cloudflare_comparte_cache_con_groq_si_es_el_mismo_modelo(self):
        g = Config(backend="groq", cloud_model="openai/gpt-oss-120b")
        c = Config(backend="cloudflare", cloud_model="@cf/openai/gpt-oss-120b")
        self.assertEqual(transcache.signature(g, []), transcache.signature(c, []))
        otro = Config(backend="cloudflare", cloud_model="@cf/meta/llama-3.3-70b-instruct-fp8-fast")
        self.assertNotEqual(transcache.signature(g, []), transcache.signature(otro, []))


if __name__ == "__main__":
    unittest.main()
