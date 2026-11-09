"""Motores de traducción intercambiables + revisión multi-pasada.

Predeterminado: Ollama (LLM local) — mejor fidelidad y contexto.
Alternativas: Argos Translate y OPUS-MT (traductores NMT dedicados, offline).

Preservación de palabras intraducibles según el motor:
  * LLM (Ollama): se envía el texto con marcadores MWTKN<n> y se instruye al
    modelo a copiarlos intactos. Da mejor contexto.
  * NMT (Argos / OPUS): se PARTE el texto por los marcadores y solo se traducen
    los segmentos intermedios; los términos nunca llegan al traductor, por lo que
    la preservación es GARANTIZADA (no depende del modelo).

Revisión (solo LLM): tras la traducción inicial, un "revisor" (el mismo modelo)
critica y corrige el borrador hasta `passes` veces, verificando fidelidad,
integridad de los tokens y calidad. Se corta antes si converge.
"""
from __future__ import annotations

import difflib
import re

import requests
import time

TOKEN_RE = re.compile(r"MWTKN\d+")

MAX_LLM_CHARS = 1600


def _split_for_llm(text: str, max_chars: int = MAX_LLM_CHARS) -> list:
    if len(text) <= max_chars:
        return [text]
    units = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_chars:
            units.append(para); continue
        for sent in re.split(r"(?<=[.!?])\s+", para):
            if len(sent) <= max_chars:
                units.append(sent); continue
            cur = ""
            for tok in sent.split():
                if cur and len(cur) + len(tok) + 1 > max_chars:
                    units.append(cur); cur = ""
                cur += (" " if cur else "") + tok
            if cur:
                units.append(cur)
    sep = "\n\n" if re.search(r"\n\s*\n", text) else " "
    pieces, buf = [], ""
    for u in units:
        if buf and len(buf) + len(u) + len(sep) > max_chars:
            pieces.append(buf); buf = ""
        buf += (sep if buf else "") + u
    if buf:
        pieces.append(buf)
    return pieces or [text]


def _tone_line(tone: str) -> str:
    if tone == "literal":
        return ("Prioriza la fidelidad literal: respeta la estructura y los términos "
                "técnicos, sin parafrasear.")
    return "Busca una traducción natural y fluida, fiel al sentido."


def build_translate_prompt(src: str, tgt: str, register: str, tone: str) -> str:
    return (
        f"Eres un traductor experto de {src} a {tgt}.\n"
        f"{register}\n{_tone_line(tone)}\n"
        "REGLAS ESTRICTAS E INVIOLABLES:\n"
        "1) Cualquier token con el formato MWTKN seguido de dígitos (por ejemplo "
        "MWTKN0, MWTKN12) es una PALABRA INTRADUCIBLE. Cópialo EXACTAMENTE igual, "
        "en la misma posición, sin traducirlo, alterarlo ni cambiar su capitalización.\n"
        "2) No agregues comentarios, aclaraciones ni notas, ni formato Markdown (sin "
        "asteriscos ni almohadillas). Devuelve ÚNICAMENTE la traducción.\n"
        "3) Conserva la puntuación y el sentido original.\n"
        "4) Conserva nombres propios, términos técnicos y palabras en otros idiomas o alfabetos "
        "(hebreo, griego, latín, egipcio) en su forma original. Mantén los números romanos "
        "(I, IV, XVII) sin cambios.\n"
        f"5) Traduce TODAS las demás palabras al {tgt}. NO dejes palabras sueltas en "
        f"{src} (salvo los MWTKN y lo indicado en la regla 4).\n"
    )


def build_review_prompt(src: str, tgt: str, register: str, tone: str) -> str:
    return (
        f"Eres un revisor de traducciones de {src} a {tgt}, extremadamente riguroso.\n"
        f"{register}\n{_tone_line(tone)}\n"
        "Recibirás el TEXTO ORIGINAL y un BORRADOR de traducción. Devuelve una versión "
        "corregida y mejorada del BORRADOR que cumpla TODO lo siguiente:\n"
        "- Fidelidad total al ORIGINAL: no omitas ni agregues información.\n"
        "- Terminología correcta y consistente.\n"
        "- Los tokens con formato MWTKN<dígitos> deben quedar EXACTOS y en su lugar.\n"
        "- Conserva nombres propios, términos técnicos y palabras en otros idiomas o alfabetos "
        "(hebreo, griego, latín, egipcio), además de los números romanos.\n"
        "- Que suene natural en el idioma destino.\n"
        "REGLAS: devuelve SOLO la traducción corregida, sin comentarios ni formato Markdown. "
        "Si el borrador ya es óptimo y no cambiarías nada, responde únicamente: OK\n"
    )


def mensaje_revision(origen: str, borrador: str) -> str:
    """Mensaje de persona de la revisión."""
    return f"TEXTO ORIGINAL:\n{origen}\n\nBORRADOR:\n{borrador}\n\nTRADUCCIÓN CORREGIDA:"


class TranslationBackend:
    """Interfaz común. `strategy` decide cómo se preservan los términos."""

    strategy = "context"
    supports_review = False

    def translate(self, text: str) -> str:
        raise NotImplementedError

    def refine(self, source_text: str, draft: str) -> str:
        """Revisa/corrige un borrador. Por defecto no cambia nada (NMT)."""
        return draft

    def fix_residue(self, text: str) -> str:
        """Corrige palabras sueltas en inglés que quedaron en la traducción.
        Base/NMT: sin cambio (lo usa solo el LLM, con contexto)."""
        return text

    def available(self) -> tuple[bool, str]:
        return True, ""


class DummyBackend(TranslationBackend):
    """Para pruebas del pipeline sin modelo ni red. No traduce de verdad."""

    strategy = "segment"

    def translate(self, text: str) -> str:
        return "«ES» " + text if text.strip() else text


class OllamaBackend(TranslationBackend):
    strategy = "context"
    supports_review = True

    def __init__(self, model: str, host: str, temperature: float,
                 src_name: str, tgt_name: str, register: str, tone: str,
                 timeout: int = 600):
        self.model = model
        self.host = host.rstrip("/")
        self.temperature = temperature
        self.timeout = timeout
        self.translate_system = build_translate_prompt(src_name, tgt_name, register, tone)
        self.review_system = build_review_prompt(src_name, tgt_name, register, tone)

    def available(self) -> tuple[bool, str]:
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=5)
            r.raise_for_status()
            names = [m.get("name", "") for m in r.json().get("models", [])]
            base = self.model.split(":")[0]
            if not any(n == self.model or n.split(":")[0] == base for n in names):
                return (True,
                        f"⚠ El modelo '{self.model}' no aparece instalado en Ollama. "
                        f"Instálalo con:  ollama pull {self.model}")
            return True, ""
        except Exception as e:
            return False, (f"✗ No pude conectar con Ollama en {self.host}. "
                           f"¿Está corriendo 'ollama serve'?  Detalle: {e}")

    def _chat(self, system: str, user: str) -> str:
        cap = min(2000, max(256, len(user.split()) * 3 + 120))
        payload = {
            "model": self.model,
            "stream": False,
            "keep_alive": "30m",
            "options": {"temperature": self.temperature, "num_predict": cap},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        r = requests.post(f"{self.host}/api/chat", json=payload, timeout=self.timeout)
        r.raise_for_status()
        return (r.json().get("message", {}) or {}).get("content", "").strip()

    def translate(self, text: str) -> str:
        if not text.strip():
            return text
        return self._chat(self.translate_system, text)

    def refine(self, source_text: str, draft: str) -> str:
        if not source_text.strip():
            return draft
        user = mensaje_revision(source_text, draft)
        return self._chat(self.review_system, user)

    _RESIDUE_SYS = (
        "Devuelve el mismo texto en español, traduciendo al español ÚNICAMENTE las "
        "palabras que quedaron en inglés (a veces con la primera letra cortada por una "
        "capitular, p. ej. 'onversation'='conversación'). No cambies nada más; conserva "
        "nombres propios, términos extranjeros, cifras y puntuación. Responde solo el texto.")

    def fix_residue(self, text: str) -> str:
        if not text.strip():
            return text
        return self._chat(self._RESIDUE_SYS, text)


_DUR = re.compile(r"(\d+(?:\.\d+)?)\s*(h|m(?!s)|s|ms)")
_QUOTA = re.compile(r"Limit:?\s*(\d+),?\s*(?:Used:?\s*(\d+),?\s*)?Requested:?\s*(\d+)")
_OTPM = re.compile(r"output tokens per minute \(OTPM\): Limit:?\s*(\d+)")


def parse_duration(s: str) -> float | None:
    """'1m2.6s' → 62.6 · '8h37m21s' → 31041 · '697ms' → 0.697 · '63' → 63."""
    s = (s or "").strip()
    if not s:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", s):
        return float(s)
    parts = _DUR.findall(s)
    if not parts:
        return None
    mult = {"h": 3600, "m": 60, "s": 1, "ms": 0.001}
    return sum(float(n) * mult[u] for n, u in parts)


ESPERAS_RED = (30, 60, 120, 240, 300, 300, 300, 300)


def con_red(pedir, *a, **kw):
    """Llama a `pedir` y, si la red falla (DNS, conexión cortada, timeout), espera y repite.
    Un corte de Wi‑Fi de minutos no debe tumbar un libro de horas."""
    for espera in ESPERAS_RED:
        try:
            return pedir(*a, **kw)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            print(f"    ⏳ red caída ({type(e).__name__}) — espero {espera} s y repito", flush=True)
            time.sleep(espera)
    return pedir(*a, **kw)


def rate_limit_wait(status: int, headers, body: str) -> tuple[float | None, str]:
    """Cuánto esperar tras un 429/503 y por qué (para el registro).
    Devuelve (None, motivo) si no tiene sentido reintentar: el bloque pide más
    tokens de los que el modelo admite por minuto (nunca pasaría)."""
    body = body or ""
    m = re.search(r'"message"\s*:\s*"((?:[^"\\]|\\.)*)"', body)
    msg = (m.group(1) if m else body).replace("\\n", " ").strip()
    msg = re.sub(r"in organization `[^`]*` service tier `[^`]*` ", "", msg)
    why = re.sub(r"\s+", " ", msg)[:220] or f"HTTP {status}"
    q = _QUOTA.search(msg)
    if q and int(q.group(3)) > int(q.group(1)):
        return None, f"el bloque pide {q.group(3)} tokens y el límite es {q.group(1)}: usa --chunk-chars menor. {why}"
    wait = parse_duration(headers.get("retry-after", ""))
    if wait is None:
        m = re.search(r"(?:try again|retry) in ([0-9hms.]+)", msg, re.I)
        wait = parse_duration(m.group(1)) if m else None
    if wait is None:
        m = re.search(r'"retryDelay"\s*:\s*"([^"]+)"', body)
        wait = parse_duration(m.group(1)) if m else None
    return (max(1.0, wait) if wait is not None else 30.0), why


class CloudBackend(TranslationBackend):
    """LLM en la NUBE vía API compatible con OpenAI (Groq, Cerebras, OpenRouter,
    Gemini). Rápido y con modelos grandes (70b). El texto SALE del equipo → úsalo
    SOLO para material público (libros), NUNCA para contenido propio/privado.
    Mismo pipeline de contexto que Ollama (troceo + revisión + corrección)."""
    strategy = "context"
    supports_review = True

    PROVIDERS = {
        "groq":       ("https://api.groq.com/openai/v1",     "~/.groq_key",       "openai/gpt-oss-120b"),
        "cerebras":   ("https://api.cerebras.ai/v1",         "~/.cerebras_key",   "gpt-oss-120b"),
        "sambanova":  ("https://api.sambanova.ai/v1",        "~/.sambanova_key",  "gpt-oss-120b"),
        "openrouter": ("https://openrouter.ai/api/v1",       "~/.openrouter_key",
                       "nvidia/nemotron-3-ultra-550b-a55b:free"),
        "requesty":   ("https://router.requesty.ai/v1",      "~/.requesty_key",
                       "nvidia/nemotron-3-ultra-550b-a55b"),
        "gemini":     ("https://generativelanguage.googleapis.com/v1beta/openai",
                       "~/.gemini_key", "gemini-flash-lite-latest"),
        "mistral":    ("https://api.mistral.ai/v1",             "~/.mistral_key",    "mistral-medium-latest"),
        "cohere":     ("https://api.cohere.com/v1",             "~/.cohere_key",     "command-r"),
        "cloudflare": ("https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1",
                       "~/.cloudflare_key", "@cf/openai/gpt-oss-120b"),
    }

    @staticmethod
    def _cloudflare_account() -> str:
        import os
        acc = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
        if not acc:
            try:
                with open(os.path.expanduser("~/.cloudflare_account"), encoding="utf-8") as f:
                    acc = f.read().strip()
            except OSError:
                acc = ""
        return acc

    def __init__(self, provider: str, model: str, temperature: float,
                 src_name: str, tgt_name: str, register: str, tone: str, timeout: int = 120):
        import os
        base, keyfile, defmodel = self.PROVIDERS[provider]
        self.provider = provider
        self.base = base.format(account=self._cloudflare_account()) if "{account}" in base else base
        self.model = model or defmodel
        self.temperature = temperature
        self.timeout = timeout
        self._keyfile = os.path.expanduser(os.environ.get(f"{provider.upper()}_KEY_FILE") or keyfile)
        self._key = None
        self._session = requests.Session()
        self.usage = {"calls": 0, "prompt": 0, "completion": 0}
        self.translate_system = build_translate_prompt(src_name, tgt_name, register, tone)
        self.review_system = build_review_prompt(src_name, tgt_name, register, tone)

    def _load_key(self) -> str:
        if self._key is None:
            with open(self._keyfile, encoding="utf-8") as f:
                self._key = f.read().strip()
        return self._key

    def available(self) -> tuple[bool, str]:
        import os
        if not os.path.exists(self._keyfile):
            return False, f"✗ Falta la clave {self._keyfile} para el motor '{self.provider}'."
        if self.provider == "cloudflare" and not self._cloudflare_account():
            return False, "✗ Falta el id de cuenta de Cloudflare (CLOUDFLARE_ACCOUNT_ID o ~/.cloudflare_account)."
        return True, ""

    MAX_NAP = 3600
    MAX_WAITS = 240
    MAX_ESPERA_TOTAL = 900
    _max_out = 0
    reasoning_effort = ""

    def _chat(self, system: str, user: str) -> str:
        import time
        payload = {"model": self.model, "temperature": self.temperature,
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": user}]}
        if self._max_out:
            payload["max_tokens"] = self._max_out
        elif self.provider == "cloudflare":
            payload["max_tokens"] = 4096
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        for _ in range(self.MAX_WAITS):
            r = con_red(self._session.post, f"{self.base}/chat/completions", json=payload,
                                   headers={"Authorization": f"Bearer {self._load_key()}"},
                                   timeout=self.timeout)
            if r.status_code not in (429, 503):
                break
            o = _OTPM.search(r.text or "")
            if o and "max_tokens" not in payload and "too large" in r.text:
                self._max_out = payload["max_tokens"] = int(o.group(1)) * 9 // 10
                print(f"    ⏳ {self.provider}: tope de salida {o.group(1)}/min → max_tokens "
                      f"{self._max_out}", flush=True)
                continue
            wait, why = rate_limit_wait(r.status_code, r.headers, r.text)
            if wait is None:
                raise RuntimeError(f"{self.provider}: {why}")
            self._gastado = getattr(self, "_gastado", 0.0) + wait
            if self._gastado > self.MAX_ESPERA_TOTAL:
                raise RuntimeError(f"{self.provider}: llevo {int(self._gastado // 60)} min esperando cupo "
                                   f"en esta clave; me rindo para que se pruebe otra. {why}")
            print(f"    ⏳ {self.provider}: {why} — espero {int(wait // 60)} min {int(wait % 60)} s",
                  flush=True)
            time.sleep(min(wait, self.MAX_NAP))
        r.raise_for_status()
        j = r.json()
        if (j.get("choices") or [{}])[0].get("finish_reason") == "length":
            raise RuntimeError("el proveedor truncó la salida (finish_reason=length)")
        u = j.get("usage") or {}
        self.usage["calls"] += 1
        self.usage["prompt"] += int(u.get("prompt_tokens") or 0)
        self.usage["completion"] += int(u.get("completion_tokens") or 0)
        return (j["choices"][0]["message"].get("content") or "").strip()

    def translate(self, text: str) -> str:
        return self._chat(self.translate_system, text) if text.strip() else text

    def refine(self, source_text: str, draft: str) -> str:
        if not source_text.strip():
            return draft
        user = mensaje_revision(source_text, draft)
        return self._chat(self.review_system, user)

    def fix_residue(self, text: str) -> str:
        return self._chat(OllamaBackend._RESIDUE_SYS, text) if text.strip() else text


class ArgosBackend(TranslationBackend):
    strategy = "segment"

    def __init__(self, source: str, target: str):
        self.source = source
        self.target = target
        self._t = None

    def available(self) -> tuple[bool, str]:
        import importlib.util
        if importlib.util.find_spec("argostranslate") is None:
            return False, ("✗ Falta 'argostranslate'. Instala:  pip install argostranslate\n"
                           "  y descarga el par en->es (ver README).")
        return True, ""

    def translate(self, text: str) -> str:
        if not text.strip():
            return text
        if self._t is None:
            import argostranslate.translate as t
            self._t = t
        return self._t.translate(text, self.source, self.target)


class GoogleWebBackend(TranslationBackend):
    """Traductor web gratuito (Google, sin API key). Rápido; el texto sale del PC."""
    strategy = "segment"

    def __init__(self, source: str, target: str):
        self.source = source or "auto"
        self.target = target
        self._g = None

    def available(self) -> tuple[bool, str]:
        import importlib.util
        if importlib.util.find_spec("deep_translator") is None:
            return False, "✗ Falta 'deep_translator'. Instala:  pip install deep-translator"
        return True, ""

    def translate(self, text: str) -> str:
        if not text.strip():
            return text
        if self._g is None:
            from deep_translator import GoogleTranslator
            self._g = GoogleTranslator(source=self.source, target=self.target)
        if len(text) <= 4800:
            return self._g.translate(text)
        parts, buf = [], ""
        for seg in re.split(r"(?<=[.!?])\s+", text):
            if len(buf) + len(seg) > 4800:
                parts.append(self._g.translate(buf)); buf = ""
            buf += seg + " "
        if buf.strip():
            parts.append(self._g.translate(buf))
        return " ".join(parts)


class EdgeBackend(TranslationBackend):
    """Traductor de Microsoft (el que usa el navegador Edge), sin clave y sin
    cuota publicada. Rápido (~0,5 s por bloque) y de buena calidad. Endpoint no
    documentado oficialmente: el mismo que usan Immersive Translate, read-frog y
    translate-shell. El texto sale del equipo. Preservación de términos
    garantizada (estrategia por segmentos)."""
    strategy = "context"
    URL = "https://edge.microsoft.com/translate/translatetext"
    UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

    def __init__(self, source: str, target: str, timeout: int = 60):
        import html as _html
        self.source, self.target, self.timeout = source or "", target, timeout
        self._session = requests.Session()
        self._esc, self._unesc = _html.escape, _html.unescape

    def translate(self, text: str) -> str:
        if not text.strip():
            return text
        out = self._call(text)
        toks = TOKEN_RE.findall(text)
        if toks and any(not re.search(r"MWTKN[\s\-_]*" + t[5:] + r"(?!\d)", out, re.I) for t in toks):
            return _segment_translate(text, self)
        return out

    def _call(self, text: str) -> str:
        import time
        payload = [self._esc(text, quote=False)]
        for _ in range(CloudBackend.MAX_WAITS):
            r = con_red(self._session.post, self.URL, json=payload, headers={"User-Agent": self.UA},
                                   params={"from": self.source, "to": self.target,
                                           "isEnterpriseClient": "false"},
                                   timeout=self.timeout)
            if r.status_code not in (429, 503):
                break
            wait, why = rate_limit_wait(r.status_code, r.headers, r.text)
            print(f"    ⏳ edge: {why} — espero {int(wait or 30)} s", flush=True)
            time.sleep(min(wait or 30, CloudBackend.MAX_NAP))
        r.raise_for_status()
        return self._unesc(r.json()[0]["translations"][0]["text"])


class OpusMTBackend(TranslationBackend):
    strategy = "segment"

    def __init__(self, model_name: str = "Helsinki-NLP/opus-mt-en-es"):
        self.model_name = model_name
        self._pipe = None

    def available(self) -> tuple[bool, str]:
        import importlib.util
        if importlib.util.find_spec("transformers") is None:
            return False, ("✗ Falta 'transformers' (y torch). Instala:\n"
                           "  pip install 'transformers[torch]' sentencepiece")
        return True, ""

    def translate(self, text: str) -> str:
        if not text.strip():
            return text
        if self._pipe is None:
            from transformers import pipeline
            self._pipe = pipeline("translation", model=self.model_name)
        chunks = re.split(r"(?<=[.!?])\s+", text)
        out = [self._pipe(c, max_length=512)[0]["translation_text"]
               for c in chunks if c.strip()]
        return " ".join(out)


def _segment_translate(masked_text: str, backend: TranslationBackend) -> str:
    """NMT: traduce solo los trozos entre marcadores; los tokens quedan intactos."""
    parts = TOKEN_RE.split(masked_text)
    tokens = TOKEN_RE.findall(masked_text)
    translated = []
    for seg in parts:
        if seg.strip():
            lead = seg[: len(seg) - len(seg.lstrip())]
            trail = seg[len(seg.rstrip()):]
            out = backend.translate(seg.strip())
            if not out:
                raise RuntimeError("NMT devolvió una salida vacía")
            translated.append(lead + out + trail)
        else:
            translated.append(seg)
    rebuilt = []
    for i, seg in enumerate(translated):
        rebuilt.append(seg)
        if i < len(tokens):
            rebuilt.append(tokens[i])
    return "".join(rebuilt)


def _perdidos(pieza: str, salida: str) -> list:
    """Marcadores MWTKN de la pieza que no aparecen en la salida (tolera «MWTKN 3», «mwtkn-3»)."""
    return [t for t in TOKEN_RE.findall(pieza)
            if not re.search(r"MWTKN[\s\-_]*" + t[5:] + r"(?!\d)", salida, re.I)]


def _is_ok(s: str) -> bool:
    t = s.strip()
    return t.strip(".").upper() == "OK" or (t.upper().startswith("OK, ") and len(t) < 40) or t == "**OK**"


_REFUSAL = re.compile(r"lo siento|no puedo|i cannot|i'?m sorry|as an ai", re.I)


def _is_refusal(text: str) -> bool:
    return bool(_REFUSAL.search((text or "")[:200]))


def _draft(piece: str, backend: TranslationBackend) -> str:
    return backend.translate(piece) if backend.strategy == "context" else _segment_translate(piece, backend)


def translate_and_review(masked_text: str, mapping: dict, backend: TranslationBackend,
                         passes: int = 5, early_stop: bool = True,
                         draft_backend: TranslationBackend | None = None):
    """Traduce y revisa. Devuelve (traducción_restaurada, tokens_perdidos, pasadas_hechas).

    Modo combinado (`draft_backend`): el borrador lo hace un motor gratuito e
    instantáneo (p. ej. Edge) y el LLM solo REVISA contra el original. Una
    llamada por pieza en vez de traducir + revisar, y el revisor responde "OK"
    cuando no hay nada que corregir: 2-3 veces menos tokens de cuota."""
    if not masked_text.strip():
        return masked_text, [], 0

    if backend.strategy == "context" or draft_backend is not None:
        outs, done = [], 0
        for pc in _split_for_llm(masked_text, getattr(backend, "max_chars", MAX_LLM_CHARS)):
            d = _draft(pc, draft_backend) if draft_backend is not None else backend.translate(pc)
            if draft_backend is not None and backend.supports_review and _perdidos(pc, d):
                directo = backend.translate(pc)
                if len(_perdidos(pc, directo)) < len(_perdidos(pc, d)):
                    d = directo
            if backend.supports_review and (draft_backend is None or re.search(r"[a-zà-ÿ]{2,}", pc)):
                for _ in range(max(0, passes)):
                    improved = backend.refine(pc, d)
                    done += 1
                    if _is_ok(improved):
                        break
                    if (not improved.strip() or len(improved) / max(1, len(d)) < 0.6
                            or _is_refusal(improved)
                            or len(_perdidos(pc, improved)) > len(_perdidos(pc, d))):
                        continue
                    conv = difflib.SequenceMatcher(None, improved.strip(), d.strip()).ratio()
                    d = improved
                    if early_stop and conv > 0.98:
                        break
            outs.append(d)
        draft = "\n\n".join(outs)
    else:
        draft = _segment_translate(masked_text, backend)
        done = 0

    restored, lost = _restore(draft, mapping)
    return restored, lost, done


def _restore(text: str, mapping: dict) -> tuple[str, list]:
    """Restaura tokens -> término.

    Tolera que el modelo cambie mayúsc./minúsc. o inserte un separador entre
    'MWTKN' y el número (p.ej. 'MWTKN 0', 'mwtkn-0'), para que nunca quede un
    marcador interno visible en la traducción. Procesa los números más largos
    primero y usa lookahead para no confundir MWTKN1 con MWTKN10.
    """
    lost = []
    for tok in sorted(mapping, key=len, reverse=True):
        term = mapping[tok]
        if tok in text:
            text = text.replace(tok, term)
            continue
        num = tok[len("MWTKN"):]
        pat = re.compile(r"MWTKN[\s\-_]*" + re.escape(num) + r"(?!\d)", re.IGNORECASE)
        if pat.search(text):
            text = pat.sub(lambda _m: term, text)
        else:
            lost.append((tok, term))
    return text, lost


_LANG_NAMES = {"en": "inglés", "es": "español", "la": "latín", "fr": "francés",
               "de": "alemán", "it": "italiano", "pt": "portugués"}


def lang_name(code: str) -> str:
    return _LANG_NAMES.get(code, code)


def make_backend(cfg, name: str = "") -> TranslationBackend:
    b = name or cfg.backend
    if b == "ollama":
        return OllamaBackend(
            model=cfg.ollama_model, host=cfg.ollama_url, temperature=cfg.temperature,
            src_name=lang_name(cfg.source_lang), tgt_name=lang_name(cfg.target_lang),
            register=cfg.register_text, tone=cfg.tone)
    if b in ("web", "google"):
        return GoogleWebBackend(source=cfg.source_lang, target=cfg.target_lang)
    if b == "edge":
        return EdgeBackend(source=cfg.source_lang, target=cfg.target_lang)
    if b in CloudBackend.PROVIDERS:
        cb = CloudBackend(
            provider=b, model=getattr(cfg, "cloud_model", "") or "",
            temperature=cfg.temperature,
            src_name=lang_name(cfg.source_lang), tgt_name=lang_name(cfg.target_lang),
            register=cfg.register_text, tone=cfg.tone)
        cb.reasoning_effort = getattr(cfg, "reasoning_effort", "")
        return cb
    if b == "argos":
        return ArgosBackend(source=cfg.source_lang, target=cfg.target_lang)
    if b == "opus":
        return OpusMTBackend(model_name=cfg.opus_model)
    if b == "dummy":
        return DummyBackend()
    raise ValueError(f"Motor desconocido: {b!r} "
                     f"(usa ollama|groq|cerebras|openrouter|gemini|mistral|cloudflare|web|edge|argos|opus|dummy)")
