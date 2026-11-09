"""Resolución de credenciales y consentimiento para servicios remotos."""
from __future__ import annotations

import os
import sys
from pathlib import Path


_PROVIDERS = [
    ("~/.groq_key", "https://api.groq.com/openai/v1/chat/completions",
     "openai/gpt-oss-120b", "openai"),
    ("~/.openrouter_key", "https://openrouter.ai/api/v1/chat/completions",
     "meta-llama/llama-3.3-70b-instruct:free", "openai"),
    ("~/.cerebras_key", "https://api.cerebras.ai/v1/chat/completions",
     "llama-3.3-70b", "openai"),
    ("~/.openai_key", "https://api.openai.com/v1/chat/completions",
     "gpt-4o-mini", "openai"),
    ("~/.gemini_key", None, "gemini-2.5-flash", "gemini"),
]

_consentimiento_aceptado = False


class SinConsentimiento(RuntimeError):
    pass


def es_remoto(motor: str) -> bool:
    """Indica si el motor envía texto fuera del equipo."""
    import main
    return motor in main.REMOTE_BACKENDS


def proveedores_con_clave():
    """Devuelve los proveedores configurados, en su orden de preferencia."""
    for keyfile, url, model, kind in _PROVIDERS:
        path = Path(keyfile).expanduser()
        if not path.exists():
            continue
        key = path.read_text(encoding="utf-8").strip()
        if key:
            yield key, url, model, kind, path


def clave_gemini() -> str:
    """Lee la clave de Gemini desde el entorno o su archivo privado habitual."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    path = Path("~/.gemini_key").expanduser()
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def exigir_consentimiento_nube(contexto: str, aceptado: bool = False) -> None:
    """Exige una decisión explícita antes de enviar texto a un servicio remoto."""
    global _consentimiento_aceptado
    if aceptado or os.environ.get("TRADUCTOR_NUBE_OK") == "1" or _consentimiento_aceptado:
        return
    if not sys.stdin or not sys.stdin.isatty():
        raise SinConsentimiento(
            f"{contexto}: se requiere consentimiento para enviar texto a la nube; "
            "pasa --yes-cloud o define TRADUCTOR_NUBE_OK=1."
        )
    try:
        respuesta = input(
            f"{contexto}: el texto SALDRÁ de tu equipo hacia ese servicio. Úsalo SOLO para material "
            "PÚBLICO (libros). NUNCA para contenido propio/privado. (Para traducir local y 100% privado: "
            "--engine ollama)\n[s/N] "
        )
    except EOFError:
        respuesta = ""
    if respuesta.strip().lower() == "s":
        _consentimiento_aceptado = True
        return
    raise SinConsentimiento("Cancelado — nada salió del equipo.")
